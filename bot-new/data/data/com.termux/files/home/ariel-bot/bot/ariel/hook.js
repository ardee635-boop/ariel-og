// The part that sits between the WhatsApp socket and ingest.js.
// All outside things (socket, caches, bot state) are passed in, so this file
// imports nothing from the rest of the bot and can be tested on its own.
import { extractMessage } from './extract.js';
import { normJid, isGroupJid, isLid, isPhoneJid } from './ids.js';

const BACKOFF_SHORT_MS = 60_000;
const BACKOFF_SCHEMA_MS = 5 * 60_000;

/**
 * deps = {
 *   ingest,                       // from createIngest
 *   isEnabled(chatJid, isDM),     // is Ariel's chat switched on here?
 *   isBot(jid),                   // is this jid Ariel herself?
 *   getPrefix(chatJid),           // async: custom command prefix for a group, or null
 *   altIds(sock, rawJid),         // async: other ids known for this jid (lid <-> phone)
 *   groupParticipants(sock, jid), // async: [{ id, lid, phoneNumber }] (cached by caller)
 *   chatName(chatJid),            // sync: group name if already known, else null
 *   log, now
 * }
 */
export function createHook(deps) {
    const { ingest, isEnabled, isBot, getPrefix, altIds, groupParticipants, chatName = () => null, log = () => {}, now = Date.now, onStored = null } = deps;
    const status = { seen: 0, errors: 0, lastError: null, lastStoredAt: null, pausedUntil: 0 };
    let consecutive = 0;

    async function senderIds(sock, msg, chatJid, isGroup) {
        const key = msg.key || {};
        const ids = [];
        const add = (j) => { const n = normJid(j); if (n && !ids.includes(n)) ids.push(n); };

        if (!isGroup) {
            add(key.remoteJid);
            add(key.remoteJidAlt); add(key.senderPn); add(key.participantPn);
            for (const a of await safe(() => altIds(sock, key.remoteJid))) add(a);
            return ids;
        }

        const raw = key.participant;
        add(raw);
        add(key.participantAlt); add(key.participantPn); add(key.senderPn);
        for (const a of await safe(() => altIds(sock, raw))) add(a);

        // Still only a @lid? The group's member list says which phone it belongs to.
        const n = normJid(raw);
        if (n && isLid(n) && !ids.some(isPhoneJid)) {
            const parts = await safe(() => groupParticipants(sock, chatJid));
            const me = parts.find((p) => normJid(p.lid) === n || normJid(p.id) === n);
            if (me) { add(me.id); add(me.lid); add(me.phoneNumber); }
        }
        return ids;
    }

    async function safe(fn) {
        try { return (await fn()) || []; } catch { return []; }
    }

    async function run(sock, msg) {
        if (!msg?.message || msg.key?.fromMe) return { status: 'skipped', reason: 'self-or-empty' };
        const chatJid = msg.key?.remoteJid;
        const isGroup = isGroupJid(chatJid);
        const isDM = !isGroup && (isPhoneJid(chatJid) || isLid(chatJid));
        if (!isGroup && !isDM) return { status: 'skipped', reason: 'not-a-chat' };
        if (!isEnabled(chatJid, isDM)) return { status: 'skipped', reason: 'chat-off' };
        if (status.pausedUntil > now()) return { status: 'skipped', reason: 'paused' };

        const ex = extractMessage(msg, { isBot });
        if (ex.skip) return { status: 'skipped', reason: ex.reason };

        // Commands never reach Ariel (the group's own prefix counts if it has one).
        if (ex.kind === 'message') {
            const custom = isGroup ? await safe1(() => getPrefix(chatJid)) : null;
            const prefix = custom || '.';
            if (ex.commandText.startsWith(prefix)) return { status: 'skipped', reason: 'command' };
        }

        status.seen++;
        try {
            const ids = await senderIds(sock, msg, chatJid, isGroup);
            const ev = {
                chat: { jid: chatJid, kind: isGroup ? 'group' : 'dm', name: isGroup ? chatName(chatJid) : null },
                sender: { ids, pushName: msg.pushName || '' },
                op: ex,
            };
            const out = await ingest.handle(ev);
            consecutive = 0;
            if (out.status === 'stored') {
                status.lastStoredAt = now();
                if (onStored) {          // stage 3: a new message may deserve an answer. Never blocks, never throws.
                    try { Promise.resolve(onStored({ ev, out, msg })).catch((e) => log(`[ARIEL] reply hook failed: ${e?.message || e}`)); }
                    catch (e) { log(`[ARIEL] reply hook failed: ${e?.message || e}`); }
                }
            }
            return out;
        } catch (e) {
            status.errors++;
            status.lastError = String(e.message || e).slice(0, 300);
            consecutive++;
            const schemaMissing = /relation .* does not exist|schema "ariel" does not exist|function ariel\..* does not exist/i.test(status.lastError);
            if (schemaMissing || consecutive >= 3) {
                const wait = schemaMissing ? BACKOFF_SCHEMA_MS : BACKOFF_SHORT_MS;
                status.pausedUntil = now() + wait;
                log(schemaMissing
                    ? '[ARIEL] ingest paused 5 min: the ariel schema is missing. Run: node --env-file=.env scripts/ariel-migrate.js'
                    : `[ARIEL] ingest paused 60 s after ${consecutive} failures: ${status.lastError}`);
                consecutive = 0;
            } else {
                log(`[ARIEL] ingest failed (message not stored): ${status.lastError}`);
            }
            return { status: 'error', error: status.lastError };
        }
    }

    async function safe1(fn) {
        try { return await fn(); } catch { return null; }
    }

    return { run, status };
}
