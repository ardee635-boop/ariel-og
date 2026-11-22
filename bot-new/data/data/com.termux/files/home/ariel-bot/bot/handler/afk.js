// bot/handler/afk.js - `.afk [reason]`, `.afknote @user <note>`, and what makes them useful:
//   * anyone tags / replies to / quotes / hidetags / tagalls an afk person -> the bot says
//         @user is afk
//         Reason: xxx
//     (everything except `.afknote` itself, which is meant to tag them quietly)
//   * the afk person talks again, in ANY linked group -> "welcome back" line from a preset pool + the notes left for them
// `.afk` itself answers only in the group it was typed in, with a preset goodbye (no LLM, no Python call).
// Survives restarts: every afk (and its notes) is stored in the bot_afk table and reloaded on the first message after boot.
import { CONTINUE } from './_common.js';
import { isPoolOn } from '../groups.js';
import {
    numOf, tag, cleanReason, announce, afkLine, backNotice, pickFallback, notesText, parseNote,
    aliasesFor, targetsOf, TAG_EVERYONE_CMDS, MAX_NOTES,
} from '../lib/afk.js';

const MAX_LISTED = 8;           // afk people named in one reply (a .tagall can hit many)
const afk = new Map();          // key (phone number) -> { jid, reason, since, aliases[], notes[] }
const index = new Map();        // any alias number -> key
let tableReady = false;
export { afk as afkMap };

const reindex = () => { index.clear(); for (const [k, a] of afk) for (const n of [k, ...a.aliases]) index.set(n, k); };
const put = (key, a) => { afk.set(key, a); reindex(); };
const drop = (key) => { afk.delete(key); reindex(); };

async function ensureTable(db) {
    if (tableReady) return;
    tableReady = true;          // try once per boot; without a DB afk still works until the next restart
    try {
        await db.query('CREATE TABLE IF NOT EXISTS bot_afk (num TEXT PRIMARY KEY, jid TEXT, reason TEXT, since BIGINT, aliases TEXT)');
        await db.query('ALTER TABLE bot_afk ADD COLUMN IF NOT EXISTS aliases TEXT');
        await db.query('ALTER TABLE bot_afk ADD COLUMN IF NOT EXISTS notes TEXT');
        const rows = (await db.query('SELECT num, jid, reason, since, aliases, notes FROM bot_afk')).rows || [];
        for (const r of rows) {
            let al = [], notes = [];
            try { al = JSON.parse(r.aliases || '[]'); } catch {}
            try { notes = JSON.parse(r.notes || '[]'); } catch {}
            if (!afk.has(r.num)) afk.set(r.num, { jid: r.jid, reason: r.reason || '', since: Number(r.since), aliases: al, notes });
        }
        reindex();
    } catch { /* keep going in memory */ }
}
const save = (db, key, a) => Promise.resolve(db.query(
    `INSERT INTO bot_afk (num, jid, reason, since, aliases, notes) VALUES ($1,$2,$3,$4,$5,$6)
     ON CONFLICT (num) DO UPDATE SET jid=$2, reason=$3, since=$4, aliases=$5, notes=$6`,
    [key, a.jid, a.reason, a.since, JSON.stringify(a.aliases), JSON.stringify(a.notes || [])])).catch(() => {});
const remove = (db, key) => Promise.resolve(db.query('DELETE FROM bot_afk WHERE num = $1', [key])).catch(() => {});

/** Which afk keys does a list of jids / numbers point at? */
function afkKeysFor(jids, groupParticipants, exclude = []) {
    const keys = new Set();
    for (const j of jids) {
        for (const n of aliasesFor([j], groupParticipants)) {
            const k = index.get(n);
            if (k && afk.has(k) && !exclude.includes(k)) keys.add(k);
        }
    }
    return keys;
}

export async function run(ctx) {
    const { sock, msg, db, chatJid, senderJid, rawJid, lower, text, groupParticipants } = ctx;
    if (!chatJid.endsWith('@g.us')) return CONTINUE;
    const cmd = lower.split(' ')[0];
    const isAfkCmd = cmd === '.afk';
    const isNoteCmd = cmd === '.afknote';
    await ensureTable(db);
    if (!isAfkCmd && !isNoteCmd && !afk.size) return CONTINUE;     // nobody afk: normal chatter costs nothing
    if (!isPoolOn(chatJid, 'normal')) return CONTINUE;

    const mine = aliasesFor([senderJid, rawJid, msg.key?.participant].filter(Boolean), groupParticipants);
    const me = numOf(senderJid);
    const reply = (body, mentions = []) => sock.sendMessage(chatJid, { text: body, mentions }, { quoted: msg });

    // ── .afk [reason]: announce + preset goodbye, in THIS group only
    if (isAfkCmd) {
        const reason = cleanReason(text.trim().slice(4));
        const old = afk.get(me) || afk.get(mine.map(n => index.get(n)).find(Boolean));
        const entry = { jid: senderJid, reason, since: Date.now(), aliases: mine, notes: old?.notes || [] };
        for (const n of mine) { const k = index.get(n); if (k && k !== me) drop(k); }   // same person under an older key
        put(me, entry);
        save(db, me, entry);
        await reply(`${announce(senderJid, reason)}\n${pickFallback()}`, [senderJid]);
        return;
    }

    // ── the afk person is talking again (in any linked group): welcome back + their notes
    const myKey = mine.map(n => index.get(n)).find(Boolean);
    if (myKey) {
        const was = afk.get(myKey);
        drop(myKey);
        remove(db, myKey);
        await reply(backNotice(senderJid, was), [senderJid]);
        if (was.notes?.length) {
            const mentions = [senderJid, ...new Set(was.notes.map(n => n.from))];
            const only = was.notes.length === 1 && was.notes[0].chat === chatJid && was.notes[0].id ? was.notes[0] : null;
            const quoted = only ? { key: { remoteJid: chatJid, id: only.id, participant: only.participant, fromMe: false }, message: { conversation: only.orig || '.afknote' } } : msg;
            await sock.sendMessage(chatJid, { text: notesText(senderJid, was.notes), mentions }, { quoted });
        }
    }

    // ── .afknote @user <note>: leave a message for an afk person. Never triggers the afk reply itself.
    if (isNoteCmd) {
        const aimed = targetsOf(msg.message, text);
        const hit = [...afkKeysFor(aimed, groupParticipants, mine)][0];
        const note = parseNote(text);
        if (!aimed.length || !note) { await reply('_Usage: .afknote @user <message> — or reply to them with .afknote <message>_'); return; }
        if (!hit) { await reply(`${tag(aimed[0])} is not afk right now.`, [aimed[0]]); return; }
        const a = afk.get(hit);
        if ((a.notes || []).length >= MAX_NOTES) { await reply(`${tag(a.jid)} already has ${MAX_NOTES} notes waiting.`, [a.jid]); return; }
        a.notes = [...(a.notes || []), { from: senderJid, chat: chatJid, text: note, at: Date.now(), id: msg.key?.id || null, participant: msg.key?.participant || senderJid, orig: text.slice(0, 400) }];
        save(db, hit, a);
        await reply(`📝 Noted. ${tag(a.jid)} will get it when they are back.`, [a.jid]);
        return;
    }

    // ── anyone aimed at an afk person: @tag, reply/quote, typed @number, in any kind of message,
    //    plus .tagall / .hidetag which aim at the whole group.
    const hits = afkKeysFor(targetsOf(msg.message, text), groupParticipants, mine);
    if (TAG_EVERYONE_CMDS.has(cmd)) {
        for (const p of groupParticipants || []) for (const k of afkKeysFor([p.id, p.lid, p.phoneNumber].filter(Boolean), groupParticipants, mine)) hits.add(k);
    }
    if (hits.size) {
        const list = [...hits].map(k => afk.get(k));
        const shown = list.slice(0, MAX_LISTED);
        const more = list.length - shown.length;
        await reply(shown.map(a => afkLine(a.jid, a)).join('\n\n') + (more > 0 ? `\n\n…and ${more} more afk.` : ''), shown.map(a => a.jid));
    }
    return CONTINUE;
}
