// lib/cache.js  (split out of index.js)

export const groupMetaCache = {};

export const groupPrefixCache = {};

export const presenceCache = {};

 // jid -> { status, ts, chatJid } — filled by presence.update listener

// Per-group custom prefix, looked up once per 5 min per group (mirrors
// groupMetaCache's TTL pattern below). Returns null if the group uses the
// default '-'.
export async function _getGroupPrefix(db, chatJid) {
    if (groupPrefixCache[chatJid] && Date.now() - groupPrefixCache[chatJid].ts < 300_000) {
        return groupPrefixCache[chatJid].prefix;
    }
    let prefix = null;
    try {
        const res = await db.query('SELECT prefix FROM group_settings WHERE group_jid = $1', [chatJid]);
        prefix = res.rows[0]?.prefix || null;
    } catch { /* default to '-' on any DB hiccup */ }
    groupPrefixCache[chatJid] = { prefix, ts: Date.now() };
    return prefix;
}

export const lidMap = {};

 // lid → phone JID
export const stats = {
    msgsReceived: 0, msgsHandled: 0, msgsSent: 0,
    errors: 0, pythonCalls: 0, pythonErrors: 0,
    lastMsg: null, lastSender: null,
};

