// bot/handler/broadcast.js - `.hidetag`, `.broadcast`, `.resetgroups`, `.help <cmd>`.
// Moved verbatim out of handleMessage (handler.js, original lines 1541-1656).
// run(ctx) returns CONTINUE to fall through to the next step, or ends handling of the message (return / return value).
import { getRank, getRankLevel } from '../commands.js';
import { botState } from '../lib/state.js';
import { saveGroups } from '../groups.js';
import { buildTagPayload, deleteCommandMessage, sendText } from '../lib/send.js';
import { _getDB } from '../lib/db.js';
import { log } from '../lib/log.js';
import { CONTINUE } from './_common.js';

export async function run(ctx) {
    let { sock, msg, chatJid, text, senderJid, lower, _cmdOverride } = ctx;

    // ── .hidetag — silent tag all in current group (Lord+, matches .tagall) ─
    // Two ways to use it:
    //   .hidetag <text>            → sends <text>, tagging everyone silently
    //   (reply to a message) .hidetag → re-sends THAT message (text, image,
    //                                   video, audio, sticker, document)
    //                                   tagging everyone silently
    // In both cases the command message itself is deleted afterwards
    // (requires Ariel to be a group admin), so only the tagged message shows.
    if (lower === '.hidetag' || lower.startsWith('.hidetag ')) {
        const db = await _getDB();
        let hidetagParticipants = [];
        try { hidetagParticipants = (await sock.groupMetadata(chatJid)).participants; } catch {}
        const rank = await getRank(db, senderJid, hidetagParticipants, true);
        if (!_cmdOverride && getRankLevel(rank) < getRankLevel('lord')) {
            await sendText(sock, chatJid, `⚠️ _Only Lords and above can use .hidetag._`, msg);
            return;
        }
        const typed = text.slice('.hidetag'.length).trim();
        const { content, error } = await buildTagPayload(msg, typed);
        if (!content) {
            const why = error === 'empty'
                ? `_Usage: .hidetag <text> — or reply to a message with .hidetag_`
                : error === 'unsupported'
                    ? `_I can't re-send that kind of message. Reply to text, image, video, audio, sticker or document._`
                    : `⚠️ _Hidetag failed: ${error}_`;
            await sendText(sock, chatJid, why, msg);
            return;
        }
        try {
            const mentions = hidetagParticipants.map(p => p.id);
            await sock.sendMessage(chatJid, { ...content, mentions });
            await deleteCommandMessage(sock, chatJid, msg);
        } catch (e) {
            await sendText(sock, chatJid, `_Failed: ${e.message}_`, msg);
        }
        return;
    }

    // ── .broadcast — silent tag all in every linked group (King only) ─
    // Same two modes as .hidetag (typed text, or reply to a message), sent
    // to EVERY linked group. The command message is deleted afterwards.
    if (lower === '.broadcast' || lower.startsWith('.broadcast ')) {
        const db = await _getDB();
        const rank = await getRank(db, senderJid, [], true);
        if (!_cmdOverride && getRankLevel(rank) < getRankLevel('king')) {
            await sendText(sock, chatJid, `👑 _Only the King can broadcast._`, msg);
            return;
        }
        const typed = text.slice('.broadcast'.length).trim();
        const { content, error } = await buildTagPayload(msg, typed);
        if (!content) {
            const why = error === 'empty'
                ? `_Usage: .broadcast <text> — or reply to a message with .broadcast_`
                : error === 'unsupported'
                    ? `_I can't re-send that kind of message. Reply to text, image, video, audio, sticker or document._`
                    : `⚠️ _Broadcast failed: ${error}_`;
            await sendText(sock, chatJid, why, msg);
            return;
        }
        let sent = 0, failed = 0;
        for (const gid of botState.allowedGroups) {
            try {
                const meta = await sock.groupMetadata(gid);
                const mentions = meta.participants.map(p => p.id);
                await sock.sendMessage(gid, { ...content, mentions });
                sent++;
            } catch { failed++; }
            await new Promise(r => setTimeout(r, 1000));
        }
        await deleteCommandMessage(sock, chatJid, msg);
        log('📢', `Broadcast done: ${sent} sent, ${failed} failed`);
        return;
    }

    // ── .resetgroups — farewell all groups + wipe (King only) ─
    if (lower === '.resetgroups') {
        const db = await _getDB();
        const rank = await getRank(db, senderJid, [], true);
        if (!_cmdOverride && getRankLevel(rank) < getRankLevel('king')) {
            await sendText(sock, chatJid, `👑 _Only the King can reset groups._`, msg);
            return;
        }
        const groupsToWipe = [...botState.allowedGroups];
        let sent = 0, failed = 0;
        for (const gid of groupsToWipe) {
            try {
                await sock.sendMessage(gid, { text: `🚪 *Ariel has been unlinked from this group.*\n_Contact the owner to re-link._` });
                sent++;
            } catch {
                failed++;
            }
        }
        botState.allowedGroups = [];
        await saveGroups(botState.allowedGroups);
        await sendText(sock, chatJid,
            `🗑️ *Groups reset*\n✅ Farewell sent to ${sent} · ❌ ${failed} failed\n_All groups unlinked._`, msg);
        return;
    }


    if (lower.startsWith('.help ')) {
        const cmd = lower.slice(6).trim();
        const helpMap = {
            'pvp':       '⚔️ *.pvp*\nCheck your PvP stats.',
            'battle':    '⚔️ *.battle @tag*\nChallenge another player to a duel.',
            'status':    '👤 *.status*\nView your RPG profile and stats.',
            'inv':       '👤 *.inv*\nView your inventory.',
            'map':       '🗺️ *.map*\nView the world map.',
            'minimap':   '🗺️ *.minimap*\nView your local area map.',
            'ping':      '🔧 *.ping*\nCheck bot response time.',
            'uptime':    '🔧 *.uptime*\nSee how long the bot has been running.',
            'd':         '🧹 *.d* (reply to a message)\nDelete that message (admins only).',
            'mypfp':     '🖼️ *.mypfp*\nSend your profile picture.',
            'pfp':       '🖼️ *.pfp @user* (or reply)\nSend someone\'s profile picture.',
            'gcpfp':     '🖼️ *.gcpfp*\nSend this group\'s profile picture.',
            'translate': '🤖 *.translate [text]*\nTranslate text to English.',
            'gpt':       '🤖 *.gpt [question]*\nAsk Ariel anything.',
            'tldr':      '🤖 *.tldr [text]*\nSummarise long text.',
            'sticker':   '🔄 *.sticker*\nReply to an image to make a sticker.',
        };
        const res = helpMap[cmd] || `❓ No help for *-${cmd}*\nType *.menu* to see all commands.`;
        await sendText(sock, chatJid, res, msg);
        return;
    }
    return CONTINUE;
}
