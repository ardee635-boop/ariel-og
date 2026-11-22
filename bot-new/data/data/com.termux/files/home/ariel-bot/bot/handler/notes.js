// bot/handler/notes.js - personal + public notes (spec: bot_notes_system.md). Normal pool.
//
//   Personal (private to the user, any linked group):  .note <text>  .notes  .notes <n>  .delnote <n>  .editnote <n>
//   Public    (shared by one group, never another):    .pnote <text> .pnotes .pnotes <n> .delpnote <n> .editpnote <n>
//
// Each .note / .pnote message is ONE note, line breaks kept. Notes live in Supabase (bot_notes), so they survive restarts.
// .editnote / .editpnote: the bot replies with the current text; the NEXT reply to THAT bot message becomes the new text.
// Runs after pre_python (needs ctx.db) and before everything that would treat the message as a command or chat.
import { CONTINUE } from './_common.js';
import { isPoolOn } from '../groups.js';
import {
    SCOPE_PERSONAL, SCOPE_PUBLIC, MAX_NOTE_CHARS, PENDING_EDIT_MS,
    userKey, parseSave, parseNumber, preview, maxNotesFor,
    ensureNotesTable, listNotes, addNote, deleteNote, updateNote, PendingEdits,
} from '../lib/notes.js';

export const pendingEdits = new PendingEdits();     // exported for tests

const CMDS = new Set(['.note', '.pnote', '.notes', '.pnotes', '.delnote', '.delpnote', '.editnote', '.editpnote']);

// Words per note kind, so one code path serves both.
const KIND = {
    [SCOPE_PERSONAL]: { label: 'Your notes', one: 'note', add: '.note', list: '.notes', del: '.delnote', edit: '.editnote', icon: '📝', scope: SCOPE_PERSONAL },
    [SCOPE_PUBLIC]:   { label: 'Group notes', one: 'public note', add: '.pnote', list: '.pnotes', del: '.delpnote', edit: '.editpnote', icon: '📌', scope: SCOPE_PUBLIC },
};

/** Whose notes: a user for personal, this group for public. */
const ownerOf = (scope, chatJid, me) => (scope === SCOPE_PUBLIC ? chatJid : me);

export async function run(ctx) {
    const { sock, msg, chatJid, senderJid, lower, text } = ctx;
    if (!chatJid?.endsWith('@g.us')) return CONTINUE;

    const cmd = lower.split(' ')[0];
    const quotedId = msg.message?.extendedTextMessage?.contextInfo?.stanzaId || null;
    const isCmd = CMDS.has(cmd);
    // A plain reply can only matter if it answers one of our pending edit prompts.
    if (!isCmd && !(quotedId && pendingEdits.size)) return CONTINUE;
    if (!isPoolOn(chatJid, 'normal')) return CONTINUE;

    const db = ctx.db;
    const me = userKey(senderJid);
    // Sent without mentions on purpose: note text containing "@1234567" must not ping anyone.
    const say = (body) => sock.sendMessage(chatJid, { text: body }, { quoted: msg });

    // ── completing a reply-edit (checked first: a reply may even start with a "." and still be the new note text)
    if (!isCmd || quotedId) {
        const p = pendingEdits.find(chatJid, quotedId, me);
        if (p) {
            const k = KIND[p.scope];
            const res = await updateNote(db, p.scope, p.ownerKey, p.noteId, text, me);
            if (!res.ok && res.reason === 'gone') {
                pendingEdits.done(p);
                await say(`_That ${k.one} no longer exists, so nothing was changed._`);
            } else if (!res.ok) {
                // keep the pending edit alive so they can reply again with something valid
                await say(res.reason === 'too_long'
                    ? `⚠️ _Too long: a ${k.one} can be at most ${MAX_NOTE_CHARS} characters. Reply again with a shorter text._`
                    : '⚠️ _The new text is empty. Reply again with the replacement text._');
            } else {
                pendingEdits.done(p);
                const n = (await listNotes(db, p.scope, p.ownerKey)).findIndex((x) => x.id === p.noteId) + 1;
                await say(`✅ _${cap(k.one)} #${n} updated._`);
            }
            return;
        }
        if (!isCmd) return CONTINUE;
    }

    try { await ensureNotesTable(db); }
    catch (e) { console.warn(`[NOTES] table setup failed: ${e.message}`); await say('⚠️ _Notes are unavailable right now. Try again in a bit._'); return; }

    try {
        // ── save
        const save = (cmd === '.note' || cmd === '.pnote') ? parseSave(text) : null;
        if (save) {
            const k = KIND[save.scope];
            if (!save.body) { await say(`_Usage: ${k.add} <text> (line breaks are kept; the whole message is one note)_`); return; }
            const r = await addNote(db, save.scope, ownerOf(save.scope, chatJid, me), save.body, me);
            if (r.ok) await say(`✅ _${cap(k.one)} #${r.number} saved._`);
            else if (r.reason === 'too_long') await say(`⚠️ _Too long: a ${k.one} can be at most ${MAX_NOTE_CHARS} characters._`);
            else if (r.reason === 'full') await say(`⚠️ _${save.scope === SCOPE_PUBLIC ? 'This group has' : 'You have'} the maximum of ${r.max} ${k.one}s. Delete one with ${k.del} <number> first._`);
            else await say(`_Usage: ${k.add} <text>_`);
            return;
        }

        const scope = (cmd === '.pnotes' || cmd === '.delpnote' || cmd === '.editpnote') ? SCOPE_PUBLIC : SCOPE_PERSONAL;
        const k = KIND[scope];
        const owner = ownerOf(scope, chatJid, me);
        const arg = lower.split(' ')[1];
        const notes = await listNotes(db, scope, owner);

        // ── list / view
        if (cmd === '.notes' || cmd === '.pnotes') {
            if (arg === undefined) {
                if (!notes.length) { await say(`${k.icon} _No ${k.one}s yet. Save one with ${k.add} <text>_`); return; }
                const rows = notes.map((n, i) => `${i + 1}. ${preview(n.content)}`).join('\n');
                await say(`${k.icon} *${k.label}* (${notes.length}/${maxNotesFor(scope)})\n\n${rows}\n\n_${k.list} <number> to read one_`);
                return;
            }
            const n = parseNumber(arg);
            if (n === null) { await say(`_Usage: ${k.list} or ${k.list} <number>_`); return; }
            if (n > notes.length) { await say(noSuch(k, n, notes.length)); return; }
            await say(`${k.icon} *${cap(k.one)} #${n}*\n\n${notes[n - 1].content}`);
            return;
        }

        // ── delete / edit need a valid number
        const n = parseNumber(arg);
        if (n === null) { await say(`_Usage: ${cmd} <number>_`); return; }
        if (n > notes.length) { await say(noSuch(k, n, notes.length)); return; }
        const target = notes[n - 1];

        if (cmd === '.delnote' || cmd === '.delpnote') {
            const gone = await deleteNote(db, scope, owner, target.id);
            await say(gone ? `🗑️ _${cap(k.one)} #${n} deleted. The list is renumbered._` : `_That ${k.one} no longer exists._`);
            return;
        }

        // .editnote / .editpnote: show the current text, then wait for a reply to THIS message
        const sent = await say(`✏️ *Editing ${k.one} #${n}*\n\n${target.content}\n\n_Reply to this message with the new text (line breaks are kept). Expires in ${PENDING_EDIT_MS / 60000} minutes._`);
        const botMsgId = sent?.key?.id;
        if (!botMsgId) return;
        pendingEdits.start({ chatJid, botMsgId, user: me, scope, noteId: target.id, ownerKey: owner });
        return;
    } catch (e) {
        console.warn(`[NOTES] ${cmd} failed: ${e.message}`);
        await say('⚠️ _Something went wrong with that note command. Nothing was changed; try again._').catch(() => {});
        return;
    }
}

const cap = (s) => s.charAt(0).toUpperCase() + s.slice(1);
const noSuch = (k, n, have) => `_There is no ${k.one} #${n}. ${have
    ? `Use a number from 1 to ${have}.`
    : `${k.scope === SCOPE_PUBLIC ? 'This group has' : 'You have'} none yet; save one with ${k.add} <text>.`}_`;
