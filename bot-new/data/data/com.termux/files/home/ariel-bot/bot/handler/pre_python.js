// bot/handler/pre_python.js - Group-linked/ignored gates, DB handle, activity tracking, participants, antilink, registration lookup.
// Moved verbatim out of handleMessage (handler.js, original lines 2507-2574).
// run(ctx) returns CONTINUE to fall through to the next step, or ends handling of the message (return / return value).
import { enforceAntilink, trackActivity } from '../commands.js';
import { botState } from '../lib/state.js';
import { PHONE_NUMBER } from '../lib/env.js';
import { groupMetaCache } from '../lib/cache.js';
import { _getDB } from '../lib/db.js';
import { CONTINUE } from './_common.js';

export async function run(ctx) {
    let { sock, msg, chatJid, rawJid, senderJid } = ctx;

    if (!botState.allowedGroups.includes(chatJid)) return;

    if (botState.ignoredGroups.includes(chatJid)) return;

    if (rawJid !== senderJid) console.log(`[LID] ${rawJid} → ${senderJid}`);
    if (senderJid.endsWith('@lid')) console.warn(`[LID] UNRESOLVED: ${senderJid}`);
    const sender      = senderJid;
    const cleanNumber = senderJid.split('@')[0];
    if (cleanNumber === PHONE_NUMBER) return;

    // -- DB handle for activity tracking + antilink --
    // (the mute / ignore check now runs earlier, right after the pool gates)
    const db = await _getDB();

    // ── Activity tracking (for .active/.inactive) ────────────
    // Every non-muted group message counts, command or not.
    trackActivity(db, chatJid, senderJid).catch(() => {}); // fire-and-forget

    // ── Bot commands (independent of game state) ──────────────
    let groupParticipants = [];
    try {
        if (!groupMetaCache[chatJid] || Date.now() - groupMetaCache[chatJid].ts > 300_000) {
            groupMetaCache[chatJid] = { meta: await sock.groupMetadata(chatJid), ts: Date.now() };
            // Fire-and-forget presence subscribe for every member of this
            // group, piggybacked on the same 5-min metadata refresh cycle
            // rather than .online triggering it on demand. The cache fills
            // in passively via the presence.update listener below —
            // .online just reads whatever's there when asked, instantly.
            for (const p of groupMetaCache[chatJid].meta.participants) {
                sock.presenceSubscribe(p.id).catch(() => {});
            }
        }
        groupParticipants = groupMetaCache[chatJid].meta.participants;
    } catch {}

    // ── Antilink — runs on every group message, before commands ──
    // Exempts admins/Baron+; deletes (and optionally warns/kicks) others.
    if (chatJid.endsWith('@g.us')) {
        try {
            const handledByAntilink = await enforceAntilink({
                sock, db, msg, chatJid, senderJid, groupParticipants,
            });
            if (handledByAntilink) return;
        } catch (e) { console.warn(`[ANTILINK] check failed: ${e.message}`); }
    }

    // Check registration status for commands that need it
    let isRegistered = false;
    try {
        const regCheck = await db.query(
            'SELECT 1 FROM players WHERE sender = $1 LIMIT 1', [senderJid]
        );
        isRegistered = (regCheck.rows?.length ?? regCheck.length ?? 0) > 0;
    } catch { }

    // Track jid/lid on the player row for identity matching (e.g. the
    // "special few" legacy-egg check). senderJid is always the resolved
    // phone JID; rawJid is whatever WhatsApp actually sent this message
    // as — a real @s.whatsapp.net jid most of the time, or an @lid when
    // WhatsApp routes it that way. Fire-and-forget: never block the
    // player's message on this.
    if (isRegistered) {
        const isLidRaw = rawJid.endsWith('@lid');
        db.query(
            `UPDATE players SET jid = $1, lid = COALESCE($2, lid) WHERE sender = $3`,
            [senderJid, isLidRaw ? rawJid : null, senderJid]
        ).catch(() => {}); // best-effort — never blocks the message pipeline
    }
    ctx.sender = sender;
    ctx.cleanNumber = cleanNumber;
    ctx.db = db;
    ctx.groupParticipants = groupParticipants;
    ctx.isRegistered = isRegistered;
    return CONTINUE;
}
