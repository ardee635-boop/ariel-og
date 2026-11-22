// bot/handler/python_dispatch.js - Command library (`handleBotCommand`), then the Python game engine call and sending its reply/outbox.
// Moved verbatim out of handleMessage (handler.js, original lines 2778-2870).
// run(ctx) returns CONTINUE to fall through to the next step, or ends handling of the message (return / return value).
import { handleBotCommand, REPLY_HANDLED } from '../commands.js';
import { callPython } from '../bridge.js';
import { sendAny, sendRpgReaction, sendText, sleep } from '../lib/send.js';
import { groupPrefixCache, presenceCache, stats } from '../lib/cache.js';
import { err, log, ts } from '../lib/log.js';
import { _sendArielSticker } from '../chat/stickers.js';
import { CONTINUE } from './_common.js';
import { isVoiceChat, sendVoiceNote } from '../lib/tts.js';

export async function run(ctx) {
    let { sock, msg, chatJid, text, senderJid, mentionedJid, quotedText, isBotTagged, isBotQuote, sender, cleanNumber, db, groupParticipants, isRegistered } = ctx;

    // .say <question> — ask Ariel and get her answer as a voice note.
    let isSay = false;
    if (/^\.say\s+\S/i.test(text)) {
        isSay = true;
        text = 'ariel ' + text.replace(/^\.say\s+/i, '');
    }

    const botReply = await handleBotCommand({
        sock, db, msg, chatJid, senderJid, text,
        mentionedJid, groupParticipants, isRegistered, groupPrefixCache,
        presenceCache,
    });
    if (botReply === REPLY_HANDLED) return;   // command already sent its own message
    if (botReply) {
        await sendAny(sock, chatJid, botReply, msg);
        return;
    }

    stats.msgsHandled++;
    stats.lastSender = cleanNumber;
    log('💬', `[${ts()}] ${cleanNumber} in ${chatJid.slice(0, 15)}… → "${text.slice(0, 45)}"`);

    // .rpg / .rpg sim turns go through this same generic callPython
    // path as everything else, so detect them here to drive the
    // status-reaction sequence (see sendRpgReaction above).
    const isRpgTurn = /^\.rpg(\s|$)/i.test(text.trim());
    if (isRpgTurn) await sendRpgReaction(sock, chatJid, msg, '🎲');

    let response, outbox, sticker, deleteMessageKey, pyError;
    try {
        // If bot was tagged or player quoted the bot, prepend "ariel"
        const lower_ = text.toLowerCase();
        const effectiveText = (isBotTagged || isBotQuote) && !lower_.includes('ariel')
            ? `ariel ${text}`.trim()
            : text;
        const pushName = msg.pushName || null;
        const pythonQuotedText = isBotQuote ? quotedText : null;
        ({
            response,
            outbox,
            sticker,
            delete_message_key: deleteMessageKey,
            error: pyError,
        } = await callPython(
            sender,
            effectiveText,
            mentionedJid,
            chatJid,
            pythonQuotedText,
            pushName,
            msg.key,
        ));
    } catch (e) {
        stats.errors++;
        err('🐍', `callPython error: ${e.message}`);
        if (isRpgTurn) await sendRpgReaction(sock, chatJid, msg, '✖️');
        return;
    }

    if (deleteMessageKey && chatJid.endsWith('@g.us')) {
        try {
            await sock.sendMessage(chatJid, { delete: deleteMessageKey });
        } catch (e) {
            err('🧹', `Could not delete a private Among Us message in ${chatJid.slice(0, 15)}…: ${e.message}`);
        }
    }

    if (response) {
        log('📤', `[${ts()}] → ${response.length} chars to ${chatJid.slice(0, 15)}…`);
        const isHud = response.includes('__HUD__');
        const quote = isHud ? null : msg;
        // Ariel chat replies (never commands / HUD) go out as a voice note when
        // .say was used or .voice is on for this chat. Falls back to text on any failure.
        let sentVoice = false;
        const wantVoice = !isHud && !isRpgTurn
            && (isSay || (isVoiceChat(chatJid) && !text.trim().startsWith('.')));
        if (wantVoice) {
            try {
                await sock.sendPresenceUpdate('recording', chatJid).catch(() => {});
                await sendVoiceNote(sock, chatJid, response, msg);
                stats.msgsSent++;
                sentVoice = true;
            } catch (e) {
                err('🔊', `voice reply failed, sending text: ${e.message}`);
            }
        }
        if (!sentVoice) await sendAny(sock, chatJid, response, quote);
        if (isRpgTurn) await sendRpgReaction(sock, chatJid, msg, '⚔️');
    } else if (isRpgTurn) {
        // No reply text made it back. callPython's timeout/dead-process
        // paths resolve with an `error` string but the Python side may
        // already have run session.apply_engine_result()+session.save()
        // before Node gave up waiting — i.e. the turn was saved even
        // though nothing was shown. ✔️ signals "went through, silently";
        // ✖️ is reserved for turns that genuinely never processed.
        const wasProcessed = !!pyError; // callPython only sets `error` after dispatching to Python, not on pre-flight "not ready" bail-outs
        await sendRpgReaction(sock, chatJid, msg, wasProcessed ? '✔️' : '✖️');
        if (pyError) {
            await sendText(
                sock, chatJid,
                '_Your action went through, but the reply timed out — try *.rpg state* to see what happened._',
                msg
            );
        }
    }

    // Ariel's chosen expression sticker — sent after the text reply so
    // it reads as a reaction to what she just said, not before it. She
    // now sends one on every turn (see ariel.py's _pick_sticker), as
    // long as she has at least one saved.
    await _sendArielSticker(sock, chatJid, sticker, msg);

    if (outbox?.length > 0) {
        const seen = new Set();
        for (const item of outbox) {
            if (seen.has(item.message)) continue;
            seen.add(item.message);
            const targetJid = item.group_jid || chatJid;
            if (item.tag_all) {
                try {
                    const meta    = await sock.groupMetadata(targetJid);
                    const members = meta.participants.map(p => p.id);
                    const tags    = item.hide_tags ? '' : members.map(id => '@' + id.split('@')[0]).join(' ');
                    const fullMsg = tags ? item.message + '\n' + tags : item.message;
                    await sock.sendMessage(targetJid, {
                        text: fullMsg,
                        mentions: item.hide_tags ? [] : members,
                    });
                } catch(e) {
                    await sendAny(sock, targetJid, item.message, null);
                }
            } else {
                await sendAny(sock, targetJid, item.message, msg);
            }
            await sleep(300);
        }
    }
    return CONTINUE;
}
