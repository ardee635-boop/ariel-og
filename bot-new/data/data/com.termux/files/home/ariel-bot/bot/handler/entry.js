// bot/handler/entry.js - Early gates, the DM path, text/caption extraction, sender/LID resolution, mentions, quoted text, `lower`, king flag.
// Moved verbatim out of handleMessage (handler.js, original lines 31-295).
// run(ctx) returns CONTINUE to fall through to the next step, or ends handling of the message (return / return value).
import { jidNormalizedUser } from '@whiskeysockets/baileys';
import { isMuted, enforceAntilink } from '../commands.js';
import { handleWorkMessage } from '../work.js';
import { botState } from '../lib/state.js';
import { BOT_START_TIME, KING_NUMBER, PHONE_NUMBER } from '../lib/env.js';
import { callPython } from '../bridge.js';
import { _findCaption, sendAny } from '../lib/send.js';
import { _getGroupPrefix, groupMetaCache, lidMap, stats } from '../lib/cache.js';
import { _replyMaybeSilent } from '../silent/mines.js';
import { _getDB } from '../lib/db.js';
import { ts } from '../lib/log.js';
import { CONTINUE } from './_common.js';
import { arielIngest, arielAdmin } from '../ariel/wire.js';
import { workModeIntercept } from '../wmode/index.js';

export async function run(ctx) {
    let { sock, msg } = ctx;
    if (!msg.message) return;
    console.log(`[HANDLE] chatJid=${msg.key.remoteJid} fromMe=${msg.key.fromMe} text=${msg.message?.conversation || msg.message?.extendedTextMessage?.text || ''}`);
    if (msg.key.fromMe) return;

    const chatJid = msg.key.remoteJid;
    const isDM = chatJid?.endsWith('@s.whatsapp.net') || chatJid?.endsWith('@lid');
    if (!chatJid?.endsWith('@g.us') && !isDM) return; // ignore anything that's neither a group nor a 1:1 DM (broadcast lists, status, etc.)

    // ── Work Mode (King only: .wchat on/off) — runs BEFORE Ariel's own ingest ──
    // Consumes the King's messages only in chats where Work Mode is on, plus the .w* commands.
    // Everything else returns false and continues exactly as before.
    if (await workModeIntercept(sock, msg)) return;

    // ── Ariel ingest (stage 2) — store the message silently ─────────
    // Fire and forget: never awaited, never throws, so a database problem
    // can't slow down or break commands. It only stores messages from chats
    // where Ariel's chat switch is on, and skips commands. It sends nothing.
    arielIngest(sock, msg);

    // ── DM path — Ariel (stage 3) answers from arielIngest above ────
    // DMs never touch the rest of this function (group metadata, LID
    // resolution, rank checks, every other pool/command). The old Python
    // chat call is gone: Ariel's Node engine stores the message and replies
    // on its own when .chatdm is on.
    if (isDM) {
        let dmText = (
            msg.message?.conversation ||
            msg.message?.extendedTextMessage?.text || ''
        ).trim();
        if (!dmText) return;
        const dmQuotedText = (
            msg.message?.extendedTextMessage?.contextInfo?.quotedMessage?.conversation ||
            msg.message?.extendedTextMessage?.contextInfo?.quotedMessage?.extendedTextMessage?.text ||
            null
        );
        const isReplyToBot = (
            msg.message?.extendedTextMessage?.contextInfo?.participant === PHONE_NUMBER + '@s.whatsapp.net'
        );
        const isAmongUsCommand = /^\.(?:m|map|stop|goback|where|status|kill|task|tasks|players|progress|vent|vitals|witness|cds|cooldown|repair|follow|unfollow|cscene|crimescene|cs|report|meeting|vote|say|gc|dm|sabotage|scan|ready|endgame|amenu|leave)\b/i.test(dmText)
            // O₂/Reactor repair: a plain `scan` (no dot) is the paired-scan reply.
            || /^scan$/i.test(dmText);
        const isAmongUsTaskReply = /\[Task Ref:\s*I\d+\]/i.test(dmQuotedText || '');
        if (isAmongUsCommand || isAmongUsTaskReply) {
            // Players are registered in the game under their PHONE jid (resolved in
            // the group). A DM can arrive as an @lid chat; hand Python the phone jid
            // or it will not recognise the player and every reply is dropped. The
            // reply itself still goes back to the chat it came from (chatJid).
            let amongUsSender = chatJid;
            if (chatJid.endsWith('@lid')) {
                const alt = msg.key?.remoteJidAlt;
                if (typeof alt === 'string' && alt.endsWith('@s.whatsapp.net')) {
                    lidMap[chatJid] = alt;           // remember it for later messages
                    amongUsSender = alt;
                } else if (lidMap[chatJid]) {
                    amongUsSender = lidMap[chatJid];
                }
            }
            const result = await callPython(
                amongUsSender,
                dmText,
                null,
                null,
                // A task reply, or a `scan` replying to a bot message (O2/Reactor):
                // Python treats a non-empty quoted text as "reply to the bot".
                isAmongUsTaskReply ? dmQuotedText
                    : (isReplyToBot && /^\.?scan$/i.test(dmText)) ? (dmQuotedText || '[bot message]')
                    : null,
                msg.pushName || null,
                msg.key,
            );
            if (result?.response) await sendAny(sock, chatJid, result.response, msg);
            return;
        }
        // Niflheim is group-only in Session 1. Only Niflheim-exclusive command
        // names get this notice; shared names (.reg, .explore, ...) are left alone in DMs.
        if (/^\.(?:nmenu|duel|boss|dungeon|website|site)\b/i.test(dmText)) {
            await sendAny(sock, chatJid, 'Niflheim is played in groups where the world is switched on.', msg);
            return;
        }
        return;     // every other DM is Ariel's (arielIngest above) -- not handled here
    }

    const msgTime = Number(msg.messageTimestamp);
    if (msgTime && msgTime < BOT_START_TIME - 10) return;

    let text = (
        msg.message?.conversation ||
        msg.message?.extendedTextMessage?.text || ''
    ).trim();
    if (!text) {
        // Image/video captions (e.g. card-bot spawns) feed the work/card
        // watcher before the empty-text drop below.
        const _cap = _findCaption(msg.message);
        if (_cap && chatJid.endsWith('@g.us')) {
            try {
                const _raw = msg.key.participant || chatJid;
                let _snd = lidMap[_raw] || _raw;
                if (!_snd.endsWith('@s.whatsapp.net')) {
                    const _meta = await sock.groupMetadata(chatJid);
                    const _f = _meta.participants.find(p => p.lid === _raw || p.id === _raw);
                    _snd = _f?.phoneNumber || _f?.id || _snd;
                    if (_snd.endsWith('@s.whatsapp.net')) lidMap[_raw] = _snd;
                }
                console.log(`[WORK] caption from ${_snd}: ${_cap.slice(0, 40).replace(/\n/g, ' ')}`);
                await handleWorkMessage(chatJid, _snd, _cap, {
                    say: (t) => _replyMaybeSilent(sock, chatJid, t, msg),
                });
            } catch (e) { console.warn(`[WORK] caption hook failed: ${e.message}`); }
        }
        // No plain text — but a group image/video/document caption can still
        // carry a link, so give antilink a look before dropping the message.
        if (chatJid.endsWith('@g.us') && botState.allowedGroups.includes(chatJid)) {
            try {
                const _rawJid = msg.key.participant || msg.key.remoteJid;
                const _db = await _getDB();
                const _sender = lidMap[_rawJid] || _rawJid;
                if (!(await isMuted(_db, chatJid, _sender))) {
                    if (!groupMetaCache[chatJid] || Date.now() - groupMetaCache[chatJid].ts > 300_000) {
                        groupMetaCache[chatJid] = { meta: await sock.groupMetadata(chatJid), ts: Date.now() };
                    }
                    await enforceAntilink({
                        sock, db: _db, msg, chatJid, senderJid: _sender,
                        groupParticipants: groupMetaCache[chatJid].meta.participants,
                    });
                }
            } catch (e) { console.warn(`[ANTILINK] caption check failed: ${e.message}`); }
        }
        return;
    }

    // ── Custom prefix translation ───────────────────────────────
    // If this group has a King-set prefix (.setprefix), translate it to the
    // canonical '.' here, once, before any command logic — both commands.js
    // and the Python router stay hardcoded to '.' and never know the
    // difference. Once a custom prefix is set, the old default '.' stops
    // matching commands for that group (defanged into plain text below)
    // rather than continuing to work alongside the new one.
    try {
        const _db = await _getDB();
        const customPrefix = await _getGroupPrefix(_db, chatJid);
        if (customPrefix && customPrefix !== '.') {
            if (text.startsWith(customPrefix)) {
                text = '.' + text.slice(customPrefix.length);
            } else if (text.startsWith('.')) {
                text = text.slice(1);
            }
        }
    } catch { /* never let a prefix lookup failure block a normal message */ }

    stats.msgsReceived++;
    stats.lastMsg = `[${ts()}] "${text.slice(0, 30)}"`;

    let rawJid = msg.key.participant || msg.key.remoteJid;
    let senderJid = rawJid;

    // Resolve sender to a real phone JID using group metadata as source of truth
    if (chatJid.endsWith('@g.us')) {
        try {
            // 1. Check persistent lidMap cache first
            if (lidMap[rawJid]) {
                senderJid = lidMap[rawJid];
            } else {
                // 2. Pull group metadata and find participant by lid or id
                const meta = await sock.groupMetadata(chatJid);
                console.log(`[LID_DEBUG] rawJid=${rawJid} participants sample:`, JSON.stringify(meta.participants.slice(0,2)));
                const found = meta.participants.find(p =>
                    p.lid === rawJid || p.id === rawJid ||
                    p.lid === jidNormalizedUser(rawJid) || p.id === jidNormalizedUser(rawJid)
                );
                const resolvedId = found?.phoneNumber || found?.id;
                if (resolvedId?.endsWith('@s.whatsapp.net')) {
                    senderJid = resolvedId;
                    lidMap[rawJid] = senderJid; // cache for future messages
                    console.log(`[LID_RESOLVED] ${rawJid} → ${senderJid}`);
                } else {
                    console.log(`[LID_NOMATCH] rawJid=${rawJid} jidNormalized=${jidNormalizedUser(rawJid)} totalParticipants=${meta.participants.length}`);
                    // 3. Fall back to store contacts (store removed, skip)
                    const contacts = {};
                    const contactEntry = Object.values(contacts).find(c => c.lid === rawJid || c.id === rawJid);
                    if (contactEntry?.id?.endsWith('@s.whatsapp.net')) {
                        senderJid = contactEntry.id;
                        lidMap[rawJid] = senderJid;
                    } else {
                        // 4. Retry once with a forced-fresh metadata fetch — a
                        // participant who just joined/registered is exactly
                        // the case where the first fetch above may have run
                        // against metadata that hadn't synced them in yet.
                        try {
                            const metaRetry = await sock.groupMetadata(chatJid);
                            const foundRetry = metaRetry.participants.find(p =>
                                p.lid === rawJid || p.id === rawJid ||
                                p.lid === jidNormalizedUser(rawJid) || p.id === jidNormalizedUser(rawJid)
                            );
                            const resolvedRetry = foundRetry?.phoneNumber || foundRetry?.id;
                            if (resolvedRetry?.endsWith('@s.whatsapp.net')) {
                                senderJid = resolvedRetry;
                                lidMap[rawJid] = senderJid;
                                console.log(`[LID_RESOLVED_RETRY] ${rawJid} → ${senderJid}`);
                            }
                        } catch { }

                        // 5. Last resort: jidNormalizedUser (may return LID-derived garbage)
                        if (senderJid === rawJid) {
                            try {
                                const normalized = jidNormalizedUser(rawJid);
                                if (normalized && /^\d+@s\.whatsapp\.net$/.test(normalized)) {
                                    senderJid = normalized;
                                }
                            } catch { }
                        }
                    }
                }
            }
        } catch { }
    }

    let mentionedJid = null;
    const rawMentions = msg.message?.extendedTextMessage?.contextInfo?.mentionedJid || [];
    if (rawMentions.length > 0) {
        const raw = rawMentions[0];
        if (raw.endsWith('@s.whatsapp.net')) {
            mentionedJid = raw;
        } else if (raw.includes('@')) {
            try {
                const meta  = await sock.groupMetadata(chatJid);
                const found = meta.participants.find(p => p.lid === raw || p.id === raw);
                if (found) {
                    const resolvedId = found.phoneNumber || found.id;
                    mentionedJid = resolvedId.endsWith('@s.whatsapp.net')
                        ? resolvedId
                        : resolvedId.split('@')[0] + '@s.whatsapp.net';
                }
            } catch { }
        }
    }

    // If no tag, try to resolve target from quoted message sender
    if (!mentionedJid) {
        const quotedParticipant = msg.message?.extendedTextMessage?.contextInfo?.participant;
        if (quotedParticipant) {
            if (quotedParticipant.endsWith('@s.whatsapp.net')) {
                mentionedJid = quotedParticipant;
            } else if (quotedParticipant.includes('@')) {
                try {
                    const meta  = await sock.groupMetadata(chatJid);
                    const found = meta.participants.find(p => p.lid === quotedParticipant || p.id === quotedParticipant);
                    if (found) {
                        const resolvedId = found.phoneNumber || found.id;
                        mentionedJid = resolvedId.endsWith('@s.whatsapp.net')
                            ? resolvedId
                            : resolvedId.split('@')[0] + '@s.whatsapp.net';
                    }
                } catch { }
            }
        }
    }

    // Extract quoted message text (for Ariel quote-reply trigger)
    const quotedText = (
        msg.message?.extendedTextMessage?.contextInfo?.quotedMessage?.conversation ||
        msg.message?.extendedTextMessage?.contextInfo?.quotedMessage?.extendedTextMessage?.text ||
        null
    );

    // If the bot itself was tagged, prepend "ariel" so router triggers her
    const BOT_JID = PHONE_NUMBER + '@s.whatsapp.net';
    const isBotTagged = rawMentions.some(jid => jid === BOT_JID || jid.startsWith(PHONE_NUMBER));

    // Detect if the quoted message was sent by the bot.
    // Must resolve LID-format participant IDs the same way senderJid/mentionedJid
    // are resolved above — WhatsApp often reports a group participant, including
    // the bot itself, as an @lid id rather than its real phone-number JID, so a
    // raw string compare against BOT_JID silently failed almost every time and
    // Ariel's quote-reply trigger never actually fired.
    let isBotQuote = false;
    if (quotedText) {
        const quotedParticipant = msg.message?.extendedTextMessage?.contextInfo?.participant;
        if (quotedParticipant === BOT_JID) {
            isBotQuote = true;
        } else if (quotedParticipant) {
            if (lidMap[quotedParticipant] === BOT_JID) {
                isBotQuote = true;
            } else {
                try {
                    const meta  = await sock.groupMetadata(chatJid);
                    const found = meta.participants.find(p => p.lid === quotedParticipant || p.id === quotedParticipant);
                    const resolvedId = found?.phoneNumber || found?.id;
                    if (resolvedId === BOT_JID || resolvedId?.split('@')[0] === PHONE_NUMBER) {
                        isBotQuote = true;
                        lidMap[quotedParticipant] = BOT_JID; // cache for future quotes
                    }
                } catch { }
            }
        }
    }

    let lower = text.toLowerCase().trim().replace(/\s+/g, ' ');
    if (lower.startsWith('. ')) lower = '.' + lower.slice(2).trimStart();

    // ── King-only ops: .groups / .silentlink / .mine / .mines ──────
    // These run BEFORE the link gate below — they must work even in a
    // completely unlinked or silent-linked group, since a silent group
    // is deliberately never added to allowedGroups. Every check here is
    // a hard senderJid === KING_JID comparison (not the rank system),
    // since these are single-operator ops, not royalty-tier commands.
    const KING_JID_FULL = KING_NUMBER + '@s.whatsapp.net';
    const isKingSender  = senderJid === KING_JID_FULL || senderJid?.startsWith(KING_NUMBER + '@');
    const lowerCmdOnlyPre = lower.split(' ')[0];
    ctx.chatJid = chatJid;
    ctx.text = text;
    ctx.rawJid = rawJid;
    ctx.senderJid = senderJid;
    ctx.mentionedJid = mentionedJid;
    ctx.quotedText = quotedText;
    ctx.BOT_JID = BOT_JID;
    ctx.isBotTagged = isBotTagged;
    ctx.isBotQuote = isBotQuote;
    ctx.lower = lower;
    ctx.isKingSender = isKingSender;
    ctx.lowerCmdOnlyPre = lowerCmdOnlyPre;

    // ── .ariel status / .ariel people — King only, read-only checks ──
    // (not .arielstatus / .arielstickers: those are separate old commands)
    if (isKingSender && (lower === '.ariel' || lower.startsWith('.ariel '))) {
        const reply = await arielAdmin(text, { jid: chatJid, isGroup: chatJid.endsWith('@g.us') });
        if (reply) await _replyMaybeSilent(sock, chatJid, reply, msg);
        return;
    }
    return CONTINUE;
}
