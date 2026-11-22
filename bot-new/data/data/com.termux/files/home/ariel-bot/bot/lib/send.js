// lib/send.js  (split out of index.js)
import { generateWAMessageFromContent, downloadContentFromMessage } from '@whiskeysockets/baileys';
import fs from 'fs';
import path from 'path';
import { ROOT } from './env.js';
import { proto } from '@whiskeysockets/baileys';
import { err } from './log.js';
import { stats } from './cache.js';
import { sendThumbnail } from '../media.js';

// ── Helpers ───────────────────────────────────────────────────
export function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

// ── .rpg status reactions ────────────────────────────────────
// Lightweight emoji react used only for .rpg / .rpg sim turns, since
// the real reply can take a while (Groq calls inside the Python
// pipeline) and a bare "seen ✓✓" gives no signal the bot is actually
// working. Sequence per turn:
//   🎲  sent immediately on receipt — "working on it"
//   ⚔️  sent once the narration reply has actually gone out
//   ✔️  sent instead of ⚔️ when the turn was processed and SAVED
//       (session.save already ran Python-side) but no reply text
//       ever made it back/out — e.g. Node's 20s callPython timeout,
//       or Python died mid-request. The player's state moved even
//       though they saw nothing, so this is "done, but silently".
//   ✖️  sent when the turn was NOT processed at all — callPython
//       threw, or Python explicitly reported an error with nothing
//       usable to show.
// Best-effort only: a failed react must never block the real reply.
export async function sendRpgReaction(sock, chatJid, msg, emoji) {
    if (!msg?.key) return;
    try {
        await sock.sendMessage(chatJid, { react: { text: emoji, key: msg.key } });
    } catch (e) {
        err('🎲', `.rpg reaction (${emoji}) failed: ${e.message}`);
    }
}

export async function sendText(sock, jid, text, quotedMsg = null, extraOpts = {}) {
    if (!text || !jid) return null;
    try {
        const mentionedJids = [];
        const re = /@(\d{7,15})/g;
        let m;
        while ((m = re.exec(text)) !== null) mentionedJids.push(m[1] + '@s.whatsapp.net');
        const content = mentionedJids.length > 0 ? { text, mentions: mentionedJids } : { text };
        const opts    = { ...(quotedMsg ? { quoted: quotedMsg } : {}), ...extraOpts };
        console.log('[SEND_TEXT] jid:', jid, '| text:', text.slice(0, 80));
        const sent    = await sock.sendMessage(jid, content, opts);
        stats.msgsSent++;
        return sent;
    } catch (e) {
        stats.errors++;
        err('📤', `sendText failed: ${e.message}`);
        return null;
    }
}

// Among Us stage pictures are composited by the engine into this folder; only files
// inside it may be sent from disk (the reference comes from our own engine, but stay strict).
const STAGE_CACHE = path.resolve(process.env.AMONGUS_STAGE_CACHE || path.join(ROOT, 'assets', 'amongus', '.cache'));
export function isStageFile(ref) {
    if (typeof ref !== 'string' || /^https?:/i.test(ref)) return false;
    try {
        const p = path.resolve(ref);
        return p.startsWith(STAGE_CACHE + path.sep) && /\.(jpe?g|png)$/i.test(p) && fs.existsSync(p);
    } catch { return false; }
}

export async function sendImage(sock, jid, imageUrl, caption = '', quotedMsg = null) {
    if (!imageUrl || !jid) return null;
    try {
        const opts = quotedMsg ? { quoted: quotedMsg } : {};
        console.log('[SEND_IMAGE] jid:', jid, '| url:', imageUrl.slice(0, 80));
        const image = isStageFile(imageUrl) ? fs.readFileSync(path.resolve(imageUrl)) : { url: imageUrl };
        const sent = await sock.sendMessage(jid, { image, caption }, opts);
        stats.msgsSent++;
        return sent;
    } catch (e) {
        stats.errors++;
        err('🖼️', `sendImage failed: ${e.message}`);
        return sendText(sock, jid, caption || '', quotedMsg);
    }
}

async function editMessage(sock, jid, msgKey, newText) {
    if (!msgKey || !jid || !newText) return null;
    try {
        return await sock.sendMessage(jid, { text: newText, edit: msgKey });
    } catch (e) {
        return sendText(sock, jid, newText);
    }
}

// ── Native WhatsApp list message (tap-to-select bottom sheet) ──
// Extracted from the old .listtest debug command (see the git
// history / earlier comments there) into a real, reusable sender —
// same underlying trick: mainline @whiskeysockets/baileys doesn't
// build the binary nodes WhatsApp needs to render this, so we inject
// them manually via additionalNodes on relayMessage. This is the
// FIRST live caller of this path — Summoner trial's Phase 1 species
// picker (see townia_trials.render_species_list_payload() /
// router/rpg.py's __LIST__ marker).
//
// payload shape: { title, description, button_text, rows: [{id, title}] }
// WhatsApp caps listMessage at 10 rows total across ALL sections
// combined (a WhatsApp-wide limit, not ours) — callers must keep
// rows.length <= 10; this function does not paginate/shelve.
async function sendListMessage(sock, jid, payload, quotedMsg = null) {
    try {
        const rows = (payload.rows || []).map(r => ({
            rowId: r.id,
            title: r.title,
            description: r.description || '',
        }));
        const listMsg = {
            listMessage: {
                title: payload.title || '',
                description: payload.description || '',
                buttonText: payload.button_text || 'Select',
                listType: 1, // SINGLE_SELECT
                sections: [{ title: payload.title || '', rows }],
            },
        };
        const preppedMsg = generateWAMessageFromContent(
            jid,
            proto.Message.fromObject(listMsg),
            { userJid: sock.user.id, quoted: quotedMsg || undefined }
        );
        await sock.relayMessage(jid, preppedMsg.message, {
            messageId: preppedMsg.key.id,
            // listMessage needs a <list> node, NOT the
            // <interactive><native_flow> node buttonsMessage uses —
            // mixing these up causes a silent client-side drop.
            additionalNodes: [{
                tag: 'biz',
                attrs: {},
                content: [{
                    tag: 'list',
                    attrs: { type: 'product_list', v: '2' },
                }],
            }],
        });
        stats.msgsSent++;
    } catch (e) {
        stats.errors++;
        err('📋', `sendListMessage failed: ${e.message}`);
        // Graceful plain-text fallback — a numbered list a player can
        // reply to by name, so the flow still works if the client/
        // Baileys version doesn't render the native picker.
        const lines = (payload.rows || []).map((r, i) => `${i + 1}. ${r.title}`);
        const fallback = [
            payload.title || '',
            payload.description || '',
            '',
            ...lines,
        ].filter(Boolean).join('\n');
        await sendText(sock, jid, fallback, quotedMsg);
    }
}

export async function sendAny(sock, jid, message, quotedMsg = null) {
    if (typeof message !== 'string') {
        err('sendAny', `non-string message type=${typeof message} val=${JSON.stringify(message)}`);
        if (Array.isArray(message)) message = message[0];
        if (typeof message !== 'string') return;
    }
    // __LIST__<json>__/LIST__ — native list message, checked before
    // __HUD__/__IMG__ splitting since it carries its own JSON payload
    // rather than plain trailing text.
    const listIdx = message.indexOf('__LIST__');
    if (listIdx >= 0) {
        const endIdx = message.indexOf('__/LIST__', listIdx);
        if (endIdx >= 0) {
            const before = message.slice(0, listIdx).trim();
            const after  = message.slice(endIdx + 9).trim();
            const jsonStr = message.slice(listIdx + 8, endIdx);
            if (before) await sendText(sock, jid, before, quotedMsg);
            try {
                const payload = JSON.parse(jsonStr);
                await sendListMessage(sock, jid, payload, before ? null : quotedMsg);
            } catch (e) {
                err('📋', `__LIST__ payload parse failed: ${e.message}`);
            }
            if (after) await sendAny(sock, jid, after, null);
            return;
        }
    }
    const hudIdx   = message.indexOf('__HUD__');
    const mainPart = hudIdx >= 0 ? message.slice(0, hudIdx).trim() : message;
    const hudPart  = hudIdx >= 0 ? message.slice(hudIdx + 7) : null;

    if (mainPart) {
        // Handle __IMG__ tag anywhere in the message (not just at start)
        const imgIdx = mainPart.indexOf('__IMG__');
        if (mainPart.startsWith('__THUMB__')) {
            const raw   = mainPart.slice(9);
            const [imgRaw, rest1 = ''] = raw.split('__TITLE__');
            const [title, rest2 = ''] = rest1.split('__SUB__');
            const [sub,   rest3 = ''] = rest2.split('__TYPE__');
            const [mtype, body  = ''] = rest3.split('__CAP__');
            const subtitle = [sub.trim(), mtype.trim()].filter(Boolean).join(' · ');
            await sendThumbnail(sock, jid, imgRaw.trim(), title.trim(), subtitle, body.trim(), quotedMsg);
        } else if (imgIdx >= 0) {
            // __IMG__ can appear mid-message — send any text before it first
            const textBefore = mainPart.slice(0, imgIdx).trim();
            if (textBefore) await sendText(sock, jid, textBefore, quotedMsg);
            const afterTag = mainPart.slice(imgIdx + 7);
            const [imgUrl, cap = ''] = afterTag.split('__CAP__');
            const url = imgUrl.trim();
            if (url.startsWith('/') || url.startsWith('./')) {
                try {
                    const buf  = fs.readFileSync(url);
                    const opts = quotedMsg ? { quoted: quotedMsg } : {};
                    await sock.sendMessage(jid, { image: buf, caption: cap.trim() }, opts);
                    stats.msgsSent++;
                } catch (e) {
                    err('🖼️', `Local file send failed: ${e.message}`);
                    await sendText(sock, jid, cap.trim(), quotedMsg);
                }
            } else {
                await sendImage(sock, jid, url, cap.trim(), textBefore ? null : quotedMsg);
            }
        } else {
            await sendText(sock, jid, mainPart, quotedMsg);
        }
    }

    if (hudPart) {
        await sleep(250);
        await sendText(sock, jid, hudPart);
    }
}

// ── Hidetag / broadcast payload builder ───────────────────────
// Builds the outgoing message for .hidetag / .broadcast from EITHER:
//   • the text typed after the command  (".hidetag hello"), or
//   • the message being replied to      (reply to anything + ".hidetag").
// Typed text wins if both are present for text-type replies (it is used
// as the caption for media, so admins can add their own words).
// Returns { content, error } — content is a Baileys message body WITHOUT
// mentions (callers attach each target group's own mention list).
export async function buildTagPayload(msg, typedText) {
    const ci     = msg.message?.extendedTextMessage?.contextInfo;
    const quoted = ci?.quotedMessage;

    // No reply: plain text mode, same as before.
    if (!quoted) {
        if (!typedText) return { content: null, error: 'empty' };
        return { content: { text: typedText } };
    }

    // Unwrap ephemeral / view-once wrappers so replies inside disappearing
    // chats or view-once media are still recognised.
    const q = quoted.ephemeralMessage?.message
           || quoted.viewOnceMessage?.message
           || quoted.viewOnceMessageV2?.message
           || quoted;

    const quotedTextOnly = q.conversation || q.extendedTextMessage?.text;
    if (quotedTextOnly) {
        // Reply to a text message: re-send its text (typed text, if any, is
        // added on top so "reply + .hidetag note" still works).
        return { content: { text: typedText ? `${typedText}\n\n${quotedTextOnly}` : quotedTextOnly } };
    }

    const dl = async (node, type) => {
        const stream = await downloadContentFromMessage(node, type);
        const chunks = [];
        for await (const c of stream) chunks.push(c);
        return Buffer.concat(chunks);
    };

    try {
        if (q.imageMessage) {
            const cap = typedText || q.imageMessage.caption || undefined;
            return { content: { image: await dl(q.imageMessage, 'image'), caption: cap } };
        }
        if (q.videoMessage) {
            const cap = typedText || q.videoMessage.caption || undefined;
            return { content: {
                video: await dl(q.videoMessage, 'video'), caption: cap,
                gifPlayback: !!q.videoMessage.gifPlayback,
            } };
        }
        if (q.audioMessage) {
            return { content: {
                audio: await dl(q.audioMessage, 'audio'),
                mimetype: q.audioMessage.mimetype || 'audio/mpeg',
                ptt: !!q.audioMessage.ptt,
            } };
        }
        if (q.stickerMessage) {
            return { content: { sticker: await dl(q.stickerMessage, 'sticker') } };
        }
        if (q.documentMessage) {
            const d = q.documentMessage;
            return { content: {
                document: await dl(d, 'document'),
                mimetype: d.mimetype || 'application/octet-stream',
                fileName: d.fileName || 'file',
                caption: typedText || d.caption || undefined,
            } };
        }
    } catch (e) {
        return { content: null, error: `media download failed: ${e.message}` };
    }

    // Reply to something we can't re-send (poll, contact, location...): fall
    // back to typed text if there is any, otherwise explain.
    if (typedText) return { content: { text: typedText } };
    return { content: null, error: 'unsupported' };
}

// Deletes the command message that triggered .hidetag / .broadcast so the
// tag looks like it came out of nowhere. Best-effort: needs Ariel to be a
// group admin (WhatsApp only lets admins delete other people's messages);
// silently skipped otherwise so the command itself never fails because of it.
export async function deleteCommandMessage(sock, chatJid, msg) {
    if (!chatJid?.endsWith('@g.us')) return;
    try { await sock.sendMessage(chatJid, { delete: msg.key }); } catch { /* not admin — leave it */ }
}

// Finds an image/video/document caption, looking through the wrapper
// message types (disappearing, view-once, document-with-caption).
export function _findCaption(m, depth = 0) {
    if (!m || typeof m !== 'object' || depth > 5) return '';
    for (const k of ['imageMessage', 'videoMessage', 'documentMessage']) {
        const c = m[k]?.caption;
        if (typeof c === 'string' && c) return c;
    }
    for (const k of ['ephemeralMessage', 'viewOnceMessage', 'viewOnceMessageV2',
                     'viewOnceMessageV2Extension', 'documentWithCaptionMessage', 'editedMessage']) {
        const c = _findCaption(m[k]?.message, depth + 1);
        if (c) return c;
    }
    return '';
}

