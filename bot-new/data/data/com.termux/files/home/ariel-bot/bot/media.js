// media.js  (split out of index.js)
import crypto from 'crypto';
import yts from 'yt-search';
import { err } from './lib/log.js';
import { stats } from './lib/cache.js';
import { sendText } from './lib/send.js';
import { sendCard } from './lib/card.js';

// Pinterest's internal search endpoint (unofficial — Pinterest can change
// this without notice; the one header below is what a live header-ablation
// test found load-bearing as of 2026-09-08). No login/cookies needed today.
export async function pinterestSearch(query, limit = 6) {
    const options = {
        isPrefetch: false,
        query,
        scope: 'pins',
        no_fetch_context_on_resource: false,
    };
    const url = `https://www.pinterest.com/resource/BaseSearchResource/get/` +
        `?source_url=${encodeURIComponent(`/search/pins/?q=${encodeURIComponent(query)}`)}` +
        `&data=${encodeURIComponent(JSON.stringify({ options, context: {} }))}`;

    const res = await fetch(url, {
        headers: {
            'x-pinterest-pws-handler': 'www/search/[scope].js',
            'x-requested-with': 'XMLHttpRequest',
            'accept': 'application/json, text/javascript, */*, q=0.01',
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36',
            'referer': `https://www.pinterest.com/search/pins/?q=${encodeURIComponent(query)}`,
        },
    });
    if (!res.ok) {
        const body = await res.text().catch(() => '');
        throw new Error(`Pinterest search HTTP ${res.status}: ${body.slice(0, 200)}`);
    }
    const rawText = await res.text();
    let data;
    try {
        data = JSON.parse(rawText);
    } catch (parseErr) {
        throw new Error(`Pinterest search returned non-JSON (likely blocked/challenged): ${rawText.slice(0, 200)}`);
    }

    const results = data?.resource_response?.data?.results
        || data?.resource_response?.data
        || [];

    const images = [];
    for (const pin of Array.isArray(results) ? results : []) {
        const img = pin?.images?.orig?.url
            || pin?.images?.['736x']?.url
            || pin?.images?.['474x']?.url;
        if (img) images.push(img);
        if (images.length >= limit) break;
    }
    return images;
}

// .play — searches YouTube with yt-search, then asks the savetube.me
// converter for an mp3 and downloads it ourselves. We verify the bytes are
// real audio before sending, so a dead/expired CDN link (the 404s) fails
// cleanly instead of sending a broken ~50 kB "audio".
export async function searchYouTube(query) {
    const { videos } = await yts(query);
    if (!videos || !videos.length) return null;
    return videos[0]; // { title, url, videoId, timestamp, thumbnail, ... }
}

// savetube moved its API to savetube.vip; .me kept as a fallback.
const _ST_BASES = ['https://media.savetube.vip/api', 'https://media.savetube.me/api'];
const _ST_HEADERS = {
    accept: '*/*',
    'content-type': 'application/json',
    origin: 'https://yt.savetube.me',
    referer: 'https://yt.savetube.me/',
    'user-agent': 'Postify/1.0.0',
};
const _ST_SECRET_HEX = 'C5D58EF67A7584E4A29F6C35BBC4EB12';

// savetube returns its info payload as base64: first 16 bytes = IV, rest =
// AES-128-CBC ciphertext.
function _stDecrypt(b64) {
    const raw = Buffer.from(b64, 'base64');
    const decipher = crypto.createDecipheriv('aes-128-cbc', Buffer.from(_ST_SECRET_HEX, 'hex'), raw.subarray(0, 16));
    const out = Buffer.concat([decipher.update(raw.subarray(16)), decipher.final()]);
    return JSON.parse(out.toString('utf8'));
}

async function _stPost(url, body) {
    const res = await fetch(url, { method: 'POST', headers: _ST_HEADERS, body: JSON.stringify(body) });
    if (!res.ok) throw new Error(`savetube HTTP ${res.status} (${new URL(url).pathname})`);
    return res.json();
}

// Sniff the real container from magic bytes. Returns a WhatsApp mimetype or null.
function _sniffAudio(buf) {
    if (buf.length < 12) return null;
    if (buf.toString('ascii', 0, 3) === 'ID3') return 'audio/mpeg';
    if (buf[0] === 0xff && (buf[1] & 0xe0) === 0xe0) return 'audio/mpeg';
    if (buf.toString('ascii', 4, 8) === 'ftyp') return 'audio/mp4';
    if (buf.toString('ascii', 0, 4) === 'OggS') return 'audio/ogg; codecs=opus';
    return null;
}

// savetube download against one API base. Returns { buffer, mimetype, title }. Throws on failure.
async function _downloadViaSavetube(base, videoUrl, videoId) {
    const cdnRes = await fetch(`${base}/random-cdn`, { headers: _ST_HEADERS });
    if (!cdnRes.ok) throw new Error(`savetube random-cdn HTTP ${cdnRes.status}`);
    const { cdn } = await cdnRes.json();
    if (!cdn) throw new Error('savetube returned no cdn');

    const info = await _stPost(`https://${cdn}/v2/info`, { url: videoUrl });
    if (!info?.data) throw new Error('savetube info returned no data');
    const meta = _stDecrypt(info.data);

    const dl = await _stPost(`https://${cdn}/download`, {
        id: meta.id || videoId,
        downloadType: 'audio',
        quality: '128',
        key: meta.key,
    });
    const audioUrl = dl?.data?.downloadUrl;
    if (!audioUrl) throw new Error('savetube returned no downloadUrl');

    const res = await fetch(audioUrl, { redirect: 'follow', headers: { 'user-agent': _ST_HEADERS['user-agent'] } });
    if (!res.ok) throw new Error(`audio URL HTTP ${res.status}`);
    const buffer = Buffer.from(await res.arrayBuffer());
    const mimetype = _sniffAudio(buffer);
    if (!mimetype) throw new Error(`audio URL did not return audio (${res.headers.get('content-type')}, ${buffer.length} bytes)`);
    if (buffer.length < 100 * 1024) throw new Error(`audio too small (${buffer.length} bytes)`);
    return { buffer, mimetype, title: meta.title };
}

// Tries each provider in order; the thrown error lists every provider's
// failure so the log shows exactly what broke (not just "Couldn't play audio").
export async function downloadYouTubeAudio(videoUrl, videoId) {
    const providers = _ST_BASES.map((base) => [base, (u, id) => _downloadViaSavetube(base, u, id)]);
    const errors = [];
    for (const [name, fn] of providers) {
        try {
            return await fn(videoUrl, videoId);
        } catch (e) {
            const msg = `${name}: ${(e?.stderr || e?.message || e).toString().trim().slice(0, 300)}`;
            err('🎵', `.play provider failed — ${msg}`);
            errors.push(msg);
        }
    }
    throw new Error(errors.join(' | '));
}

// one URL isn't actually image bytes (Pinterest sometimes returns a page
// URL, a redirect to an interstitial, or a non-image content-type), the
// whole send fails with an opaque "Invalid media type" that doesn't say
// which URL was the problem.
//
// A plain HEAD check isn't reliable enough here — some CDNs answer HEAD
// with different headers than the actual GET (or don't support HEAD at
// all), so a URL can pass a HEAD check and still fail when Baileys
// actually fetches it. This does a small ranged GET instead (only pulls
// the first few KB) and checks both the reported content-type and the
// actual magic bytes, so a mislabeled or broken URL gets caught before
// it ever reaches sock.sendMessage.
const _IMAGE_MAGIC_BYTES = [
    { sig: [0xff, 0xd8, 0xff], type: 'jpeg' },
    { sig: [0x89, 0x50, 0x4e, 0x47], type: 'png' },
    { sig: [0x47, 0x49, 0x46], type: 'gif' },
    { sig: [0x52, 0x49, 0x46, 0x46], type: 'webp' }, // RIFF container; WEBP checked separately below
];

function _looksLikeImageBytes(buf) {
    for (const { sig } of _IMAGE_MAGIC_BYTES) {
        if (buf.length >= sig.length && sig.every((b, i) => buf[i] === b)) {
            // RIFF containers can be more than webp; confirm the WEBP tag.
            if (sig.length === 4 && sig[0] === 0x52) {
                return buf.length >= 12 && buf.toString('ascii', 8, 12) === 'WEBP';
            }
            return true;
        }
    }
    return false;
}

async function _isLikelyImageUrl(url) {
    try {
        const res = await fetch(url, { headers: { Range: 'bytes=0-4095' } });
        if (!res.ok && res.status !== 206) return false;
        const ct = res.headers.get('content-type') || '';
        if (!ct.startsWith('image/')) return false;
        const buf = Buffer.from(await res.arrayBuffer());
        return _looksLikeImageBytes(buf);
    } catch {
        return false;
    }
}

export async function filterValidImageUrls(urls) {
    const checks = await Promise.all(urls.map(async (url) => ({
        url,
        ok: await _isLikelyImageUrl(url),
    })));
    return checks.filter((c) => c.ok).map((c) => c.url);
}

export async function sendThumbnail(sock, jid, imageUrl, title, subtitle, body = '', quotedMsg = null) {
    // ariel-og.onrender.com (old standalone OG service) is no longer
    // reachable — replaced by a Vercel serverless function living in
    // the main site repo. Same title/sub/img param shape, so nothing
    // else about this function needed to change.
    const ogUrl = `https://ariel-og.vercel.app/api/preview?v=${Date.now()}&title=${encodeURIComponent(title || 'Ariel')}&sub=${encodeURIComponent(subtitle || '')}&img=${encodeURIComponent(imageUrl || '')}`;
    const text  = body ? `${ogUrl}\n\n${body}` : ogUrl;
    console.log('[SEND_THUMB] jid:', jid, '| title:', title, '| ogUrl:', ogUrl.slice(0, 120));
    try {
        // A bare URL only gets a preview if Baileys crawls it itself, which needs the
        // optional link-preview-js package (not installed here) — so that silently stopped
        // working. Hand WhatsApp the title/description/picture directly via the card helper.
        const sent = await sendCard(sock, jid, {
            url: ogUrl,
            title: title || 'Ariel',
            body: subtitle || '',
            text,
            image: imageUrl || undefined,
            big: true,
            shape: 'auto',
            quoted: quotedMsg || undefined,
            strict: true,
        });
        stats.msgsSent++;
        return sent;
    } catch (e) {
        stats.errors++;
        err('🖼️', `sendThumbnail failed: ${e.message}`);
        return sendText(sock, jid, text, quotedMsg);
    }
}

