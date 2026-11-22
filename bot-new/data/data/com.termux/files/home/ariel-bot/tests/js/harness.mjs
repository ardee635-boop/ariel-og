// Shared pieces for the JS golden tests. No network, no node_modules, no real DB, no real phone numbers.
// Everything the bot logic touches is replaced by a deterministic fake that RECORDS what happened:
//   sock calls, Python-bridge calls (with the pool flags), media helper calls, and every mutating SQL statement.
import crypto from 'node:crypto';
import { DatabaseSync } from 'node:sqlite';

// ---- fake identities (set BEFORE the bot's modules are imported; env wins over config/identities.json) ----
export const NUM = { BOT: '15550000001', KING: '15550000002', ADMIN: '15550000003', YUKI: '15550000004',
                     PAIRING: '15550000001', WATCH: '15550000009' };
process.env.BOT_NUMBER = NUM.BOT; process.env.KING_NUMBER = NUM.KING; process.env.PAIRING_NUMBER = NUM.PAIRING;
process.env.ADMIN_NUMBER = NUM.ADMIN; process.env.YUKI_NUMBER = NUM.YUKI; process.env.MINE_WATCH_NUMBER = NUM.WATCH;
process.env.JWT_SECRET = 'test-secret';
delete process.env.SUPABASE_DB_URL; delete process.env.SUPABASE_URL; delete process.env.SUPABASE_SERVICE_ROLE_KEY;

export const jid = (n) => `${n}@s.whatsapp.net`;
export const J = { BOT: jid(NUM.BOT), KING: jid(NUM.KING), ADMIN: jid(NUM.ADMIN), YUKI: jid(NUM.YUKI),
                   U1: jid('15551110001'), U2: jid('15551110002'), U3: jid('15551110003'), QUEEN: jid('15551110004'),
                   LID1: '99900000001@lid', GROUP: '120363000000000001@g.us', GROUP2: '120363000000000002@g.us',
                   GROUP3: '120363000000000003@g.us' };

// ---- the log everything is recorded into (stubs read globalThis.__golden.log) ----
export const golden = globalThis.__golden = { log: [], manifest: null, fault: null };

// ---- deterministic clock / random / timers / console ----
export const BASE_TIME = Date.UTC(2026, 9, 8, 12, 0, 0);       // Thu 2026-10-08 12:00 UTC
let _now = BASE_TIME;
export const setClock = (ms) => { _now = ms; };
export const nowMs = () => _now;
export const advanceClock = (ms) => { _now += ms; };
const RealDate = Date;
class FakeDate extends RealDate {
    constructor(...a) { if (a.length) super(...a); else super(_now); }
    static now() { return _now; }
}
globalThis.Date = FakeDate;

let _seed = 1;
export const seedRandom = (s) => { _seed = (s >>> 0) || 1; };
let _forced = null;
export const forceRandom = (v) => { _forced = v; };
Math.random = () => { if (_forced !== null) return _forced; _seed = (Math.imul(_seed, 1664525) + 1013904223) >>> 0; return _seed / 4294967296; };

export const realSetTimeout = globalThis.setTimeout;
export const realSetImmediate = globalThis.setImmediate;
const timerHandle = () => ({ unref() { return this; }, ref() { return this; }, refresh() { return this; }, close() {}, hasRef: () => false });
globalThis.setTimeout = (fn, ms, ...a) => { Promise.resolve().then(() => fn(...a)); return timerHandle(); };
globalThis.setInterval = () => timerHandle();
globalThis.clearTimeout = () => {}; globalThis.clearInterval = () => {};
globalThis.setImmediate = (fn, ...a) => { Promise.resolve().then(() => fn(...a)); return timerHandle(); };

// ---- fake fetch: every HTTP call the bot makes is logged and answered deterministically ----
globalThis.fetch = async (url, opts = {}) => {
    const u = String(url?.url ?? url);
    golden.log.push(['fetch', opts.method || 'GET', u.slice(0, 120), opts.body ? String(opts.body).slice(0, 60) : null]);
    if (golden.fault === 'fetch') throw new TypeError('fetch failed');
    const bodyS = opts.body ? String(opts.body) : '';
    if (bodyS.includes('failgen')) return new Response('{"error":"x"}', { status: 500 });
    const json_ = (o, status = 200) => new Response(JSON.stringify(o), { status, headers: { 'content-type': 'application/json' } });
    if (u.includes('/storage/v1/')) {                                   // the sticker bucket: manifest + objects kept in memory per scenario
        if (u.includes('manifest')) {
            if ((opts.method || 'GET') === 'GET') return golden.manifest ? json_(golden.manifest) : json_({}, 404);
            try { golden.manifest = JSON.parse(String(opts.body)); } catch {}
            return json_({});
        }
        return u.includes('/list/') ? json_([]) : json_({});
    }
    if (/none|notfound|fail/.test(u)) return new Response('{}', { status: 404, headers: { 'content-type': 'application/json' } });
    if (bodyS.includes('noimage')) return new Response(JSON.stringify({ candidates: [{ content: { parts: [{ text: 'only text' }] } }] }), { status: 200, headers: { 'content-type': 'application/json' } });
    const json = { url: 'https://img.example/a.jpg', title: 'T', results: [{ url: 'https://img.example/a.gif', anime_name: 'Anime', artist_name: 'Art', source_url: 'https://src.example' }],
                   setup: 'S', punchline: 'P', joke: 'J', text: 'FETCH-TEXT', data: [{ images: { original: { url: 'https://img.example/g.gif' } } }], images: ['https://img.example/1.jpg'],
                   candidates: [{ content: { parts: [{ text: 'GEMINI' }, { inlineData: { mimeType: 'image/png', data: 'QUJD' } }] } }], choices: [{ message: { content: 'GPT' } }], translations: [{ text: 'TR' }], responseData: { translatedText: 'TR' } };
    return new Response(JSON.stringify(json), { status: 200, headers: { 'content-type': 'application/json' } });
};

export const realConsole = { ...console };
for (const k of ['log', 'warn', 'error', 'info', 'debug']) console[k] = () => {};

// ---- fake Postgres pool backed by in-memory SQLite ----
const BOOL_COLS = new Set(['muted', 'ignored']);
const toSqlite = (sql) => sql.replace(/\$(\d+)/g, '?$1').replace(/\bNOW\(\)/gi, 'CURRENT_TIMESTAMP')
                             .replace(/::\w+(\[\])?/g, '').replace(/\bTIMESTAMPTZ\b/gi, 'TIMESTAMP');
const bindable = (v) => v === undefined ? null : typeof v === 'boolean' ? (v ? 1 : 0)
                       : v instanceof Date ? v.toISOString() : (v && typeof v === 'object' && !Buffer.isBuffer(v)) ? JSON.stringify(v) : v;

export function makePool() {
    const db = new DatabaseSync(':memory:');
    const run = (text, params = []) => {
        const sql = toSqlite(text).trim();
        const verb = sql.split(/\s+/)[0].toUpperCase();
        const ps = params.map(bindable);
        if (/^ALTER TABLE\s+\w+\s+DROP CONSTRAINT/i.test(sql)) return { rows: [], rowCount: 0, command: 'ALTER' };   // PG-only; nothing to drop on a fresh table
        if (/^ALTER TABLE\s+\w+\s+ADD COLUMN IF NOT EXISTS\s/i.test(sql)) {      // not valid SQLite: strip it, ignore duplicates
            try { db.exec(sql.replace(/IF NOT EXISTS\s+/i, '')); } catch (e) { if (!/duplicate column/i.test(e.message)) throw e; }
            return { rows: [], rowCount: 0, command: 'ALTER' };
        }
        if (!/^SELECT|^WITH/i.test(sql)) golden.log.push(['sql', sql.replace(/\s+/g, ' ').slice(0, 220), ps]);
        if (!ps.length && sql.replace(/;\s*$/, '').includes(';')) { db.exec(sql); return { rows: [], rowCount: 0, command: verb }; }
        const st = db.prepare(sql.replace(/;\s*$/, ''));
        if (verb === 'SELECT' || verb === 'WITH' || /\bRETURNING\b/i.test(sql)) {
            const rows = st.all(...ps).map(r => { const o = { ...r }; for (const k of Object.keys(o)) if (BOOL_COLS.has(k)) o[k] = !!o[k]; return o; });
            return { rows, rowCount: rows.length, command: verb };
        }
        const info = st.run(...ps);
        return { rows: [], rowCount: Number(info.changes), command: verb };
    };
    const pool = { query: async (t, p) => run(t, p), on() {}, end: async () => {}, raw: db,
                   connect: async () => ({ query: async (t, p) => run(t, p), release() {} }) };
    return pool;
}

// ---- fake socket: records every call; unknown methods are recorded too (never crash on them) ----
const jsonSafe = (_k, v) => Buffer.isBuffer(v) || v?.type === 'Buffer' ? `<Buffer ${v.length ?? v.data?.length}>`
                           : typeof v === 'function' ? '<fn>' : typeof v === 'bigint' ? String(v) : v;
export const norm = (x) => JSON.parse(JSON.stringify(x ?? null, jsonSafe));

export function makeSock(groups = {}, fetchAll = groups) {
    let n = 0;
    const rec = (name, args) => golden.log.push([name, ...args.map(norm)]);
    const base = {
        user: { id: `${NUM.BOT}:7@s.whatsapp.net`, lid: '99900000099:7@lid', name: 'Ariel' },
        async sendMessage(to, content, opts) { if (JSON.stringify(content, jsonSafe)?.includes('THROWSEND')) { rec('send-throws', [to]); throw new Error('send failed'); } rec('send', [to, content, opts?.quoted ? { quoted: opts.quoted.key?.id } : null]); return { key: { id: `M${++n}`, remoteJid: to, fromMe: true }, message: content }; },
        async groupMetadata(g) { rec('groupMetadata', [g]); if (groups[g]) return groups[g]; throw new Error('item-not-found'); },
        async relayMessage(to, content, opts) { rec('relay', [to, content, opts]); return `R${++n}`; },
        async profilePictureUrl(j, kind) { rec('pfp', [j, kind]); if (j.includes('555111') || j.endsWith('0001@g.us')) return `https://pfp.example/${j}`; throw new Error('item-not-found'); },
        async groupFetchAllParticipating() { rec('groupFetchAllParticipating', []); return fetchAll; },
        async groupInviteCode(g) { rec('groupInviteCode', [g]); if (g.includes('0004')) throw new Error('item-not-found'); if (g.includes('0005')) throw new Error('not-authorized'); return 'INVITECODE'; },
        async presenceSubscribe(j) { rec('presenceSubscribe', [j]); },
        end(e) { rec('end', [String(e || '')]); },
    };
    return new Proxy(base, { get(t, k) {
        if (k in t) return t[k];
        if (typeof k === 'symbol' || k === 'then') return undefined;
        return async (...a) => { rec(`sock.${String(k)}`, a); return undefined; };   // e.g. groupParticipantsUpdate, updateBlockStatus
    } });
}

// ---- group metadata fixtures ----
export function groupMeta(id, extra = []) {
    return { id, subject: `Group ${id.slice(-3)}`, owner: J.KING, creation: 1700000000, desc: 'A test group',
             participants: [{ id: J.KING, admin: 'superadmin' }, { id: J.ADMIN, admin: 'admin' }, { id: J.BOT, admin: 'admin' },
                            { id: J.QUEEN, admin: null }, { id: J.U1, admin: null }, { id: J.U2, admin: null }, { id: J.U3, admin: null },
                            ...extra] };
}

// ---- message builders (Baileys-shaped) ----
let _mid = 0;
export function mkMsg({ text, from = J.U1, chat = J.GROUP, quoted = null, mentions = [], pushName = 'Tester', kind = 'text', id, participantAlt } = {}) {
    const isDM = !chat.endsWith('@g.us');
    const key = { remoteJid: chat, fromMe: false, id: id || `ID${String(++_mid).padStart(4, '0')}` };
    if (!isDM) key.participant = from;
    if (participantAlt) key.participantAlt = participantAlt;
    const ctx = {};
    if (mentions.length) ctx.mentionedJid = mentions;
    if (quoted) {
        ctx.stanzaId = quoted.id || 'QID1'; ctx.participant = quoted.from || J.U2;
        const QK = { sticker: { stickerMessage: { mimetype: 'image/webp' } }, image: { imageMessage: { caption: quoted.text || '', mimetype: 'image/jpeg' } },
                     video: { videoMessage: { mimetype: 'video/mp4' } }, audio: { audioMessage: { mimetype: 'audio/ogg' } },
                     viewonce: { viewOnceMessageV2: { message: { imageMessage: { mimetype: 'image/jpeg' } } } } };
        ctx.quotedMessage = QK[quoted.kind] ?? (quoted.media ? QK.image : { conversation: quoted.text || '' });
    }
    let message;
    if (kind === 'image') message = { imageMessage: { caption: text || '', mimetype: 'image/jpeg', ...(Object.keys(ctx).length ? { contextInfo: ctx } : {}) } };
    else if (kind === 'sticker') message = { stickerMessage: { mimetype: 'image/webp' } };
    else if (Object.keys(ctx).length) message = { extendedTextMessage: { text, contextInfo: ctx } };
    else message = { conversation: text };
    return { key, message, pushName, messageTimestamp: Math.floor(_now / 1000) };
}

// ---- stable hashing for the golden file ----
export const sha = (s) => crypto.createHash('sha1').update(s).digest('hex').slice(0, 12);
export const hashSeed = (s) => parseInt(sha(s).slice(0, 8), 16);
