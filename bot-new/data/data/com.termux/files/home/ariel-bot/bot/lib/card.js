// bot/lib/card.js - the small "link card" under a message (title + body line + thumbnail + the link's domain),
// the same one other bots use for .bal / .profile.
//   * the link row is always the domain of `url`, and tapping the card opens it
//   * keep the thumbnail small: square jpeg ~300px (we crop + shrink it here)
//
// Built as a normal text message with WhatsApp's native `linkPreview` (not `externalAdReply`).
// externalAdReply is documented by this project's own Baileys fork as "may not be displayed on
// some WhatsApp versions" — testing confirmed it only ever rendered on the sending device, never
// for other people, however the thumbnail/link/image fields were set. `linkPreview` is the normal,
// universally-supported mechanism (the one used when you just paste a URL into a chat), and lets us
// hand WhatsApp the title/description/thumbnail directly instead of relying on it to crawl the URL.
import { err } from './log.js';

export const MENU_IMG = 'https://i.ibb.co/Kj0WDD9J/Ariel-16-Satoru-Ariel.jpg';   // the picture the menu uses
export const DEFAULT_URL = 'https://niflheim-online.vercel.app';
const THUMB_PX = 300;
const BIG_W = 640, BIG_H = 336;          // big card: wide ~1.9:1 picture, WhatsApp shows it full-width

const thumbCache = new Map();           // "<w>x<h>:url" -> jpeg Buffer (or null if it could not be made)

/** Download `url` and make a jpeg thumbnail (square THUMB_PX by default, or w x h). Returns null on any problem (the card then goes out without a picture). */
export async function squareThumb(url, w = THUMB_PX, h = THUMB_PX) {
    const isBuf = Buffer.isBuffer(url);                 // a picture we already have in memory (e.g. a group photo)
    const key = `${w}x${h}:${isBuf ? '' : url}`;
    if (!isBuf && thumbCache.has(key)) return thumbCache.get(key);
    let out = null;
    try {
        let input = url;
        if (!isBuf) {
            const res = await fetch(url, { signal: AbortSignal.timeout(10_000) });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            input = Buffer.from(await res.arrayBuffer());
        }
        const sharp = (await import('sharp')).default;
        out = await sharp(input)
            .resize(w, h, { fit: 'cover' })
            .jpeg({ quality: 70 })
            .toBuffer();
    } catch (e) { err('🖼️', `card thumbnail failed (${isBuf ? 'buffer' : url}): ${e.message}`); }
    if (out && !isBuf) thumbCache.set(key, out);
    return out;
}

const imageCache = new Map();           // url -> original picture bytes (kept until the bot restarts)
const IMAGE_CACHE_MAX = 24;

/** Picture bytes from a url (or the Buffer itself). Downloaded once, then served from memory. null on any problem. */
async function loadImage(src) {
    if (Buffer.isBuffer(src)) return src;
    if (imageCache.has(src)) return imageCache.get(src);
    try {
        const res = await fetch(src, { signal: AbortSignal.timeout(10_000) });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const buf = Buffer.from(await res.arrayBuffer());
        if (imageCache.size >= IMAGE_CACHE_MAX) imageCache.delete(imageCache.keys().next().value);   // drop the oldest
        imageCache.set(src, buf);
        return buf;
    } catch (e) { err('🖼️', `card picture download failed (${src}): ${e.message}`); return null; }
}

/** width / height of a picture, kept between 1 (square) and 1.91 (the widest WhatsApp card). */
async function aspectOf(buf) {
    try {
        const sharp = (await import('sharp')).default;
        const m = await sharp(buf).metadata();
        return Math.min(1.91, Math.max(1, m.width / m.height));
    } catch { return 1.91; }
}

/**
 * Upload `buf` to WhatsApp as a link-preview thumbnail. WhatsApp only draws the BIG card when the message
 * carries this uploaded picture (a plain jpegThumbnail, however wide, always gives the mini card).
 * Returns the fields linkPreview.highQualityThumbnail needs, or null if the upload is not possible.
 */
async function uploadBigThumb(sock, buf) {
    try {
        const { prepareWAMessageMedia } = await import('@whiskeysockets/baileys');
        const m = await prepareWAMessageMedia({ image: buf }, { upload: sock.waUploadToServer, mediaTypeOverride: 'thumbnail-link' });
        const i = m.imageMessage;
        if (!i?.directPath) throw new Error('upload gave no directPath');
        return {
            directPath: i.directPath, mediaKey: i.mediaKey, mediaKeyTimestamp: i.mediaKeyTimestamp,
            width: i.width, height: i.height, fileSha256: i.fileSha256, fileEncSha256: i.fileEncSha256,
        };
    } catch (e) { err('🖼️', `big card thumbnail upload failed (${e.message}) - sending mini card`); return null; }
}

/**
 * Send `text` with a link card under it.
 * @param {object} o { title, body, url, text, image, mentions, quoted }
 *   image: picture url (default: the menu picture); anything WhatsApp can fetch works, we crop it square.
 *   shape: 'square' | 'auto' (keep the picture's own proportions) — only with big.
 *   strict: true -> throw if the card can't be sent instead of falling back to plain text.
 *   big:   true -> wide picture uploaded to WhatsApp as the link thumbnail, so it draws the BIG card instead of the mini one.
 */
export async function sendCard(sock, jid, o = {}) {
    const url = o.url || DEFAULT_URL;
    const sq = o.shape === 'square';
    let src = o.image || MENU_IMG;
    let tw = THUMB_PX, th = THUMB_PX, hw = 800, hh = 800;          // mini card: small square
    if (o.big) {
        if (o.shape === 'auto') {
            // keep the picture's own proportions (square .. 1.91:1) so nothing important is cropped
            const buf = await loadImage(src);
            if (buf) { src = buf; const r = await aspectOf(buf); tw = 640; th = Math.round(640 / r); hw = 800; hh = Math.round(800 / r); }
            else { tw = BIG_W; th = BIG_H; hw = 800; hh = 420; }
        } else if (sq) { tw = 640; th = 640; hw = 800; hh = 800; }
        else { tw = BIG_W; th = BIG_H; hw = 800; hh = 420; }
    }
    const thumb = await squareThumb(src, tw, th);
    // The URL has to actually be present in `text` — linkPreview attaches to a
    // matching substring, it doesn't invent one. Append it if the caller's text
    // doesn't already contain it.
    const hq = o.big ? await uploadBigThumb(sock, await squareThumb(src, hw, hh)) : null;
    const baseText = o.bare ? url : (o.text || ' ');
    const text = baseText.includes(url) ? baseText : `${baseText}\n${url}`.trim();
    const content = {
        text,
        ...(o.mentions?.length ? { mentions: o.mentions } : {}),
        linkPreview: {
            'matched-text': url,
            title: String(o.title || 'Ariel').slice(0, 60),
            description: String(o.body || '').slice(0, 80),
            previewType: 0,
            ...(thumb ? { jpegThumbnail: thumb } : {}),
            ...(hq ? { highQualityThumbnail: hq } : {}),
        },
    };
    const opts = o.quoted ? { quoted: o.quoted } : {};
    try {
        return await sock.sendMessage(jid, content, opts);
    } catch (e) {
        if (o.strict) throw e;     // caller has its own fallback (e.g. send the picture as a plain photo)
        err('🖼️', `card send failed (${e.message}) - plain text instead`);
        return sock.sendMessage(jid, { text: o.text || `${o.title || ''}\n${url}`.trim(), ...(o.mentions?.length ? { mentions: o.mentions } : {}) }, opts);
    }
}

/**
 * Ad-reply style card (contextInfo.externalAdReply) - the style `.invite preview` uses.
 * @param {object} o { title, body, url, text, image, big, quoted }   big: true -> large thumbnail
 */
export async function sendAdCard(sock, jid, o = {}) {
    const url = o.url || DEFAULT_URL;
    const thumb = await squareThumb(o.image || MENU_IMG, o.big ? 640 : 300, o.big ? 640 : 300);
    const baseText = o.text || ' ';
    const text = baseText.includes(url) ? baseText : `${baseText}\n${url}`.trim();
    const content = {
        text,
        contextInfo: {
            externalAdReply: {
                title: String(o.title || 'Ariel').slice(0, 60),
                body: String(o.body || '').slice(0, 80),
                mediaType: 1,
                renderLargerThumbnail: !!o.big,
                showAdAttribution: false,
                sourceUrl: url,
                ...(thumb ? { thumbnail: thumb } : {}),
            },
        },
    };
    return sock.sendMessage(jid, content, o.quoted ? { quoted: o.quoted } : {});
}
