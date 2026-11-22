// ============================================================
// ARIEL — reactions.js
// Sends GIF reactions as animated WhatsApp videos
// Drop this file next to index.js
// ============================================================
//
// HOW TO USE IN index.js:
//
//   import { sendReaction } from './reactions.js';
//
//   Replace the LOCAL_IMAGES block's send call:
//     BEFORE: await sock.sendMessage(chatJid, { image: { url: imgUrl }, caption, mentions }, { quoted: msg });
//     AFTER:  await sendReaction(sock, chatJid, imgUrl, caption, mentions, msg);
//
//   Replace the NEKO_ACTIONS block's send call:
//     BEFORE: await sock.sendMessage(chatJid, { image: { url: gif }, caption, mentions }, { quoted: msg });
//     AFTER:  await sendReaction(sock, chatJid, gif, caption, mentions, msg);
//
// ============================================================

/**
 * Fetches a GIF URL as a buffer and sends it as an animated
 * WhatsApp video (gifPlayback: true). Falls back to static
 * image if fetch fails.
 *
 * @param {object} sock        - Baileys socket
 * @param {string} chatJid     - Destination JID
 * @param {string} gifUrl      - Direct URL to the GIF
 * @param {string} caption     - Message caption
 * @param {string[]} mentions  - Array of JIDs to mention
 * @param {object} quotedMsg   - Message to quote/reply to
 */
export async function sendReaction(sock, chatJid, gifUrl, caption, mentions, quotedMsg) {
    try {
        const res = await fetch(gifUrl, {
            headers: { 'User-Agent': 'Mozilla/5.0' },
            signal: AbortSignal.timeout(10_000), // 10s timeout
        });

        if (!res.ok) throw new Error(`HTTP ${res.status}`);

        const buffer = Buffer.from(await res.arrayBuffer());

        await sock.sendMessage(
            chatJid,
            {
                video:       buffer,
                gifPlayback: true,
                caption:     caption,
                mentions:    mentions,
                mimetype:    'video/mp4',
            },
            { quoted: quotedMsg }
        );

    } catch (err) {
        console.error(`[REACTIONS] Failed to send GIF (${gifUrl}):`, err.message);

        // Fallback — send as static image so something always shows
        try {
            await sock.sendMessage(
                chatJid,
                {
                    image:    { url: gifUrl },
                    caption:  caption,
                    mentions: mentions,
                },
                { quoted: quotedMsg }
            );
        } catch (fallbackErr) {
            console.error(`[REACTIONS] Fallback also failed:`, fallbackErr.message);
        }
    }
}


// ============================================================
// CAPTION HELPERS
// Keeps caption logic in one place
// ============================================================

/**
 * Builds a reaction caption.
 * e.g. "@Alice hugs @Bob"  or  "@Alice dances"
 *
 * @param {string} senderJid
 * @param {string|null} targetJid
 * @param {string} action       - verb e.g. 'hug', 'slap'
 * @param {string} [suffix]     - optional anime/source name
 * @returns {{ caption: string, mentions: string[] }}
 */
export function buildReactionCaption(senderJid, targetJid, action, suffix = '') {
    const senderNum = senderJid.split('@')[0];
    const targetNum = targetJid?.split('@')[0];
    const targetTag = targetNum ? `@${targetNum}` : '';
    const mentions  = [senderJid];
    if (targetJid) mentions.push(targetJid);

    const verb    = action.endsWith('s') ? action : `${action}s`; // hug → hugs
    const line    = `@${senderNum} *${verb}* ${targetTag}`.trim();
    const caption = suffix ? `${line}\n_${suffix}_` : line;

    return { caption, mentions };
}
