// bot/lib/notes.js - storage + pure helpers for the notes system (.note / .pnote and friends).
//
// Two kinds of note, one table (bot_notes):
//   personal  scope='personal'  owner_key = the user's number   -> only that user can see / change them
//   public    scope='public'    owner_key = the group JID       -> any member of THAT group, never another group
//
// Every note has a stable internal id (random, never reused). The number people see (#1, #2, ...) is just the
// note's position in creation order, so deleting #1 renumbers the list naturally while edits and deletes
// (including a pending reply-edit) still hit the right record.
import { randomUUID } from 'crypto';

export const SCOPE_PERSONAL = 'personal';
export const SCOPE_PUBLIC = 'public';

/** Abuse limits. */
export const MAX_NOTE_CHARS = 2000;
export const MAX_PERSONAL_NOTES = 50;       // per user
export const MAX_PUBLIC_NOTES = 50;         // per group
export const PENDING_EDIT_MS = 5 * 60_000;  // a reply-edit prompt goes stale after this
export const PREVIEW_CHARS = 50;

export const maxNotesFor = (scope) => (scope === SCOPE_PUBLIC ? MAX_PUBLIC_NOTES : MAX_PERSONAL_NOTES);

/** The user part of a jid: '234801:12@s.whatsapp.net' -> '234801'. */
export const userKey = (jid) => String(jid || '').split('@')[0].split(':')[0];

/** Clean note text: normalise line endings and trim the outside, but keep inner line breaks and spacing as typed. */
export const cleanNoteText = (raw) => String(raw ?? '').replace(/\r\n?/g, '\n').trim();

/**
 * Split a message into the note-saving commands.
 * `.note text` / `.pnote text` - everything after the command, line breaks included, is ONE note.
 * Returns null when the message is not .note / .pnote (so .notes, .pnotes, .noteX never match).
 */
export function parseSave(text) {
    const m = /^\.\s*(note|pnote)(?:\s+([\s\S]*))?$/i.exec(String(text || ''));
    if (!m) return null;
    return { scope: m[1].toLowerCase() === 'pnote' ? SCOPE_PUBLIC : SCOPE_PERSONAL, body: cleanNoteText(m[2]) };
}

/** '1' -> 1, '#2' -> 2, anything else -> null. */
export function parseNumber(arg) {
    const m = /^#?(\d{1,6})$/.exec(String(arg ?? '').trim());
    if (!m) return null;
    const n = Number(m[1]);
    return n >= 1 ? n : null;
}

/** One-line preview for the list view: first non-empty line, clipped, with an ellipsis if there is more. */
export function preview(content) {
    const lines = String(content || '').split('\n').map((l) => l.trim()).filter(Boolean);
    const first = lines[0] || '';
    const clipped = first.length > PREVIEW_CHARS;
    return clipped ? first.slice(0, PREVIEW_CHARS - 1).trimEnd() + '…' : (lines.length > 1 ? first + ' …' : first);
}

// ── storage ───────────────────────────────────────────────────

const ready = new WeakSet();    // pools whose table is known to exist

/** Create the table (once per DB handle). Throws on failure so a command can say so instead of silently losing notes. */
export async function ensureNotesTable(db) {
    if (ready.has(db)) return;
    await db.query(`CREATE TABLE IF NOT EXISTS bot_notes (
        id         TEXT PRIMARY KEY,
        scope      TEXT NOT NULL,
        owner_key  TEXT NOT NULL,
        content    TEXT NOT NULL,
        created_by TEXT,
        created_at BIGINT NOT NULL,
        updated_by TEXT,
        updated_at BIGINT
    )`);
    await db.query('CREATE INDEX IF NOT EXISTS bot_notes_owner_idx ON bot_notes (scope, owner_key, created_at)');
    ready.add(db);
}

/** All notes of one owner, oldest first. Position in this array (+1) is the number people see. */
export async function listNotes(db, scope, ownerKey) {
    const r = await db.query(
        'SELECT id, content, created_by, created_at, updated_at FROM bot_notes WHERE scope = $1 AND owner_key = $2 ORDER BY created_at ASC, id ASC',
        [scope, ownerKey]);
    return r.rows || [];
}

// Creation stamps are strictly increasing, so two notes saved in the same millisecond still keep their order.
let lastStamp = 0;
const nextStamp = (now) => (lastStamp = Math.max(now, lastStamp + 1));

/** Add a note. Returns { ok:true, number, id } or { ok:false, reason:'full'|'empty'|'too_long' }. */
export async function addNote(db, scope, ownerKey, content, by, now = Date.now()) {
    const text = cleanNoteText(content);
    if (!text) return { ok: false, reason: 'empty' };
    if (text.length > MAX_NOTE_CHARS) return { ok: false, reason: 'too_long' };
    const have = (await listNotes(db, scope, ownerKey)).length;
    if (have >= maxNotesFor(scope)) return { ok: false, reason: 'full', max: maxNotesFor(scope) };
    const id = randomUUID();
    await db.query(
        'INSERT INTO bot_notes (id, scope, owner_key, content, created_by, created_at) VALUES ($1,$2,$3,$4,$5,$6)',
        [id, scope, ownerKey, text, by || null, nextStamp(now)]);
    return { ok: true, number: have + 1, id };
}

/** Delete by stable id. The scope + owner in the WHERE keeps one user / group from ever touching another's note. */
export async function deleteNote(db, scope, ownerKey, id) {
    const r = await db.query('DELETE FROM bot_notes WHERE id = $1 AND scope = $2 AND owner_key = $3', [id, scope, ownerKey]);
    return (r.rowCount || 0) > 0;
}

/** Replace a note's text by stable id. Returns { ok:true } or { ok:false, reason:'gone'|'empty'|'too_long' }. */
export async function updateNote(db, scope, ownerKey, id, content, by, now = Date.now()) {
    const text = cleanNoteText(content);
    if (!text) return { ok: false, reason: 'empty' };
    if (text.length > MAX_NOTE_CHARS) return { ok: false, reason: 'too_long' };
    const r = await db.query(
        'UPDATE bot_notes SET content = $1, updated_by = $2, updated_at = $3 WHERE id = $4 AND scope = $5 AND owner_key = $6',
        [text, by || null, now, id, scope, ownerKey]);
    return (r.rowCount || 0) > 0 ? { ok: true } : { ok: false, reason: 'gone' };
}

// ── pending reply-edits ───────────────────────────────────────
// In memory on purpose: a pending edit lives a few minutes, and losing it in a restart just means "run .editnote again".
// Keyed by the bot's own prompt message, so only a reply to THAT message can complete the edit.

export class PendingEdits {
    constructor(ttlMs = PENDING_EDIT_MS) { this.ttl = ttlMs; this.map = new Map(); }
    static key(chatJid, botMsgId) { return `${chatJid}|${botMsgId}`; }
    sweep(now = Date.now()) { for (const [k, v] of this.map) if (v.expires <= now) this.map.delete(k); }
    /** One pending edit per (user, group, note type): starting a new one cancels the old one. */
    start({ chatJid, botMsgId, user, scope, noteId, ownerKey }, now = Date.now()) {
        this.sweep(now);
        for (const [k, v] of this.map) if (v.chatJid === chatJid && v.user === user && v.scope === scope) this.map.delete(k);
        this.map.set(PendingEdits.key(chatJid, botMsgId), { chatJid, botMsgId, user, scope, noteId, ownerKey, expires: now + this.ttl });
    }
    /** The pending edit this reply is answering, or null. Personal edits only for their initiator; public for any member. */
    find(chatJid, quotedId, user, now = Date.now()) {
        if (!quotedId) return null;
        this.sweep(now);
        const p = this.map.get(PendingEdits.key(chatJid, quotedId));
        if (!p) return null;
        if (p.scope === SCOPE_PERSONAL && p.user !== user) return null;
        return p;
    }
    done(p) { this.map.delete(PendingEdits.key(p.chatJid, p.botMsgId)); }
    get size() { return this.map.size; }
}
