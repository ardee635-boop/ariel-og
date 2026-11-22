// baileys-auth.js  (split out of index.js)
import { BufferJSON } from '@whiskeysockets/baileys';
import { _getDB } from './lib/db.js';
import { err, log } from './lib/log.js';

async function _readAuth(key) {
    try {
        const db = await _getDB();
        const res = await db.query('SELECT value FROM bot_auth WHERE key = $1', [key]);
        if (!res.rows.length) return null;
        return JSON.parse(res.rows[0].value, BufferJSON.reviver); // ← reviver goes here
    } catch { return null; }
}

async function _writeAuth(key, value) {
    try {
        const db = await _getDB();
        await db.query(
            `INSERT INTO bot_auth (key, value) VALUES ($1, $2)
             ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value`,
            [key, JSON.stringify(value, BufferJSON.replacer)]
        );
    } catch (e) { console.error('[Auth] Write failed:', e.message); }
}

async function _deleteAuth(key) {
    try {
        const db = await _getDB();
        await db.query('DELETE FROM bot_auth WHERE key = $1', [key]);
    } catch {}
}

export async function clearSupabaseAuth() {
    try {
        const db = await _getDB();
        await db.query("DELETE FROM bot_auth WHERE key = 'creds' OR key LIKE 'key-%'");
        log('🗑️', 'Supabase auth cleared.');
    } catch (e) { err('🗑️', `Clear failed: ${e.message}`); }
}

export async function useSupabaseAuthState() {
    const { initAuthCreds, proto } = await import('@whiskeysockets/baileys');

    // Read creds directly (not via _readAuth) so a DB failure and a genuinely
    // empty row are two different outcomes here — that distinction is what
    // was missing before. _readAuth() collapses both into null, which made
    // an unreadable session indistinguishable from a first-ever pairing and
    // led straight to a fabricated new identity replacing the real one.
    const db = await _getDB();
    const row = await db.query('SELECT value FROM bot_auth WHERE key = $1', ['creds']);
    const creds = row.rows.length
        ? JSON.parse(row.rows[0].value, BufferJSON.reviver)
        : initAuthCreds(); // no row at all — this really is a first-ever pairing
    const keys = {};
    const state = {
        creds,
        keys: {
            get: async (type, ids) => {
                const data = {};
                for (const id of ids) {
                    let value = keys[`${type}-${id}`];
                    if (!value) value = await _readAuth(`key-${type}-${id}`);
                    if (value) {
    if (type === 'app-state-sync-key') {
        value = proto.Message.AppStateSyncKeyData.fromObject(value);
        if (value.keyData && !Buffer.isBuffer(value.keyData))
            value.keyData = Buffer.from(Object.values(value.keyData));
        if (value.timestamp && typeof value.timestamp === 'object')
            value.timestamp = value.timestamp;
    }
    data[id] = value;
}
                }
                return data;
            },
            set: async (data) => {
                const tasks = [];
                for (const category of Object.keys(data)) {
                    for (const id of Object.keys(data[category])) {
                        const value  = data[category][id];
                        const dbKey  = `key-${category}-${id}`;
                        if (value) {
                            keys[`${category}-${id}`] = value;
                            tasks.push(_writeAuth(dbKey, value));
                        } else {
                            delete keys[`${category}-${id}`];
                            tasks.push(_deleteAuth(dbKey));
                        }
                    }
                }
                await Promise.all(tasks);
            },
        },
    };
    const saveCreds = async () => { await _writeAuth('creds', state.creds); };
    return { state, saveCreds };
}

