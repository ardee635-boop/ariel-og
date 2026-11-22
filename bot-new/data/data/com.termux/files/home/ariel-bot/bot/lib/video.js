// bot/lib/video.js - ffmpeg-backed conversions: GIF -> mp4 (WhatsApp only plays real mp4 as a gif),
// sticker/image -> mp4 (`.tovid`), video -> animated webp sticker (`.sticker` on a video).
// Needs `ffmpeg` on PATH (Termux: pkg install ffmpeg).
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawn } from 'node:child_process';

const FFMPEG_TIMEOUT_MS = 45_000;
const MAX_STICKER_BYTES = 500 * 1024;      // WhatsApp drops animated stickers much above this

export const kindOf = (b) => {
    if (!b || b.length < 12) return 'unknown';
    const head = b.subarray(0, 12);
    if (head.subarray(0, 4).toString('latin1') === 'GIF8') return 'gif';
    if (head.subarray(4, 8).toString('latin1') === 'ftyp') return 'mp4';
    if (head.subarray(0, 4).toString('latin1') === 'RIFF' && head.subarray(8, 12).toString('latin1') === 'WEBP') return 'webp';
    if (head[0] === 0x89 && head.subarray(1, 4).toString('latin1') === 'PNG') return 'png';
    if (head[0] === 0xff && head[1] === 0xd8) return 'jpeg';
    return 'unknown';
};

function ffmpeg(args) {
    return new Promise((resolve, reject) => {
        const p = spawn('ffmpeg', ['-y', '-loglevel', 'error', ...args]);
        let stderr = '';
        const t = setTimeout(() => { p.kill('SIGKILL'); reject(new Error('ffmpeg timed out')); }, FFMPEG_TIMEOUT_MS);
        p.stderr.on('data', (d) => { stderr += d; });
        p.on('error', (e) => { clearTimeout(t); reject(e.code === 'ENOENT' ? new Error('ffmpeg is not installed (pkg install ffmpeg)') : e); });
        p.on('close', (code) => { clearTimeout(t); code === 0 ? resolve() : reject(new Error(`ffmpeg exit ${code}: ${stderr.slice(0, 200)}`)); });
    });
}

/** Write `buf` to a temp file, run `fn(inPath, outPath)`, return the output bytes, always clean up. */
async function withTmp(buf, inExt, outExt, fn) {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'vid_'));
    const inP = path.join(dir, `in.${inExt}`), outP = path.join(dir, `out.${outExt}`);
    try {
        fs.writeFileSync(inP, buf);
        await fn(inP, outP);
        const out = fs.readFileSync(outP);
        if (!out.length) throw new Error('ffmpeg produced an empty file');
        return out;
    } finally { fs.rmSync(dir, { recursive: true, force: true }); }
}

const H264 = ['-c:v', 'libx264', '-preset', 'veryfast', '-crf', '26', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', '-an'];
const EVEN = 'scale=trunc(iw/2)*2:trunc(ih/2)*2';       // h264 needs even dimensions

export const gifToMp4 = (buf) => withTmp(buf, 'gif', 'mp4', (i, o) => ffmpeg(['-i', i, '-vf', EVEN, ...H264, o]));

/** A still picture as a short looping-friendly mp4. */
export const stillToMp4 = (buf, ext = 'png', seconds = 3) =>
    withTmp(buf, ext, 'mp4', (i, o) => ffmpeg(['-loop', '1', '-i', i, '-t', String(seconds), '-r', '25', '-vf', EVEN, ...H264, o]));

/** Animated (or static) webp sticker -> mp4. ffmpeg cannot decode animated webp everywhere, so go webp -> gif (sharp) -> mp4. */
export async function stickerToMp4(buf) {
    const sharp = (await import('sharp')).default;
    const meta = await sharp(buf, { animated: true }).metadata();
    if ((meta.pages || 1) > 1) {
        const gif = await sharp(buf, { animated: true }).gif().toBuffer();
        return { mp4: await gifToMp4(gif), animated: true };
    }
    const png = await sharp(buf).png().toBuffer();
    return { mp4: await stillToMp4(png, 'png'), animated: false };
}

/** Any video (incl. WhatsApp "gif" mp4s) -> animated webp sticker, centre-cropped to a 512x512 square, under WhatsApp's size limit. */
export async function videoToStickerWebp(buf) {
    const tries = [
        { fps: 15, q: 45, secs: 8 },
        { fps: 12, q: 30, secs: 8 },
        { fps: 10, q: 20, secs: 6 },
        { fps: 8,  q: 12, secs: 5 },
    ];
    let last = null;
    for (const t of tries) {
        // scale so the SHORT side is 512, then crop the centre 512x512 (fills the sticker, no padding)
        const vf = `fps=${t.fps},scale=512:512:force_original_aspect_ratio=increase,crop=512:512,format=yuva420p`;
        last = await withTmp(buf, 'mp4', 'webp', (i, o) =>
            ffmpeg(['-i', i, '-t', String(t.secs), '-vf', vf, '-an', '-loop', '0', '-c:v', 'libwebp', '-q:v', String(t.q), '-compression_level', '6', o]));
        if (!last.includes('ANIM')) throw new Error('ffmpeg produced a still image, not an animation');
        if (last.length <= MAX_STICKER_BYTES) return last;
    }
    return last;                                    // smallest attempt; WhatsApp may still accept it
}

// Tiny in-memory cache so a popular reaction gif is converted once, not on every .hug
const cache = new Map();
const CACHE_MAX = 40;
export async function cachedGifToMp4(key, buf) {
    if (cache.has(key)) { const v = cache.get(key); cache.delete(key); cache.set(key, v); return v; }
    const mp4 = await gifToMp4(buf);
    cache.set(key, mp4);
    if (cache.size > CACHE_MAX) cache.delete(cache.keys().next().value);
    return mp4;
}
