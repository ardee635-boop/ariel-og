// bot/handler/web_cmds.js - `.translate`, `.lyrics`, `.ship`, `.wallpaper`, `.pint`, `.play`.
// Moved verbatim out of handleMessage (handler.js, original lines 2179-2373).
// run(ctx) returns CONTINUE to fall through to the next step, or ends handling of the message (return / return value).
import { sendImage, sendText, sleep } from '../lib/send.js';
import { stats } from '../lib/cache.js';
import { err } from '../lib/log.js';
import { downloadYouTubeAudio, filterValidImageUrls, pinterestSearch, searchYouTube } from '../media.js';
import { CONTINUE } from './_common.js';
import { sendVoiceNote, setVoiceChat } from '../lib/tts.js';
import { KING_NUMBER } from '../lib/env.js';


// ── Lyrics lookup: lrclib.net first, lyrics.ovh as fallback (both free, no key) ──
async function getJson(url) {
    const res = await fetch(url, { headers: { 'User-Agent': 'ariel-bot (WhatsApp)' }, signal: AbortSignal.timeout(15000) });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
}

async function findLyrics(query) {
    try {
        const list = await getJson(`https://lrclib.net/api/search?q=${encodeURIComponent(query)}`);
        const t = Array.isArray(list) ? list.find((x) => x.plainLyrics && x.plainLyrics.trim()) : null;
        if (t) return { title: t.trackName, artist: t.artistName, lyrics: t.plainLyrics.trim() };
    } catch (e) {
        err('🎤', `lrclib failed for "${query}": ${e.message}`);
    }
    try {
        // "artist - song" if given, otherwise let lyrics.ovh's suggest resolve it.
        let artist, title;
        const m = query.match(/^(.+?)\s+[-–]\s+(.+)$/);
        if (m) { artist = m[1].trim(); title = m[2].trim(); }
        else {
            const sug = await getJson(`https://api.lyrics.ovh/suggest/${encodeURIComponent(query)}`);
            const first = sug?.data?.[0];
            if (!first) return null;
            artist = first.artist?.name; title = first.title;
        }
        if (!artist || !title) return null;
        const d = await getJson(`https://api.lyrics.ovh/v1/${encodeURIComponent(artist)}/${encodeURIComponent(title)}`);
        const lyrics = (d?.lyrics || '').replace(/\r\n/g, '\n').trim();
        if (lyrics) return { title, artist, lyrics };
    } catch (e) {
        err('🎤', `lyrics.ovh failed for "${query}": ${e.message}`);
    }
    return null;
}

export async function run(ctx) {
    let { sock, msg, chatJid, text, lower } = ctx;

    if (lower.startsWith('.translate ') || lower.startsWith('.tt ')) {
        const textToTranslate = text.slice(text.indexOf(' ') + 1).trim();
        if (!textToTranslate) {
            await sendText(sock, chatJid, '_Usage: .translate [text]_', msg);
            return;
        }
        try {
            const res = await fetch('https://libretranslate.com/translate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ q: textToTranslate, source: 'auto', target: 'en', format: 'text' }),
            });
            const data = await res.json();
            if (data.translatedText) {
                await sendText(sock, chatJid, `🌐 *Translation:*\n${data.translatedText}`, msg);
            } else {
                await sendText(sock, chatJid, '_Translation failed. Try again._', msg);
            }
        } catch(e) {
            await sendText(sock, chatJid, '_Translation service unavailable._', msg);
        }
        return;
    }

    if (lower === '.lyrics' || lower === '.lyric' || lower.startsWith('.lyrics ') || lower.startsWith('.lyric ')) {
        const query = text.includes(' ') ? text.slice(text.indexOf(' ') + 1).trim() : '';
        if (!query) { await sendText(sock, chatJid, '_Usage: .lyrics [song name or artist - song]_', msg); return; }
        try {
            const hit = await findLyrics(query);
            if (!hit) {
                await sendText(sock, chatJid, `_No lyrics found for "${query}"._`, msg);
                return;
            }
            const MAX = 3500; // keep each message readable
            const chunks = [];
            let rest = `🎤 *${hit.title}* — ${hit.artist}\n\n${hit.lyrics}`;
            while (rest.length > MAX) {
                let cut = rest.lastIndexOf('\n\n', MAX);
                if (cut < MAX / 2) cut = rest.lastIndexOf('\n', MAX);
                if (cut < MAX / 2) cut = MAX;
                chunks.push(rest.slice(0, cut).trim());
                rest = rest.slice(cut).trim();
            }
            chunks.push(rest);
            for (let i = 0; i < chunks.length; i++) {
                await sendText(sock, chatJid, chunks[i], i === 0 ? msg : null);
                if (i < chunks.length - 1) await sleep(500);
            }
        } catch (e) {
            err('🎤', `.lyrics failed for "${query}": ${e.message}`);
            await sendText(sock, chatJid, '_Could not fetch lyrics right now._', msg);
        }
        return;
    }

    // .tts <text>  (or reply to a text message with .tts) -> voice note
    if (lower === '.tts' || lower.startsWith('.tts ')) {
        let speak = text.includes(' ') ? text.slice(text.indexOf(' ') + 1).trim() : '';
        if (!speak) {
            const q = msg.message?.extendedTextMessage?.contextInfo?.quotedMessage;
            speak = (q?.conversation || q?.extendedTextMessage?.text || q?.imageMessage?.caption || '').trim();
        }
        if (!speak) { await sendText(sock, chatJid, '_Usage: .tts [text] — or reply to a message with .tts_', msg); return; }
        try {
            await sock.sendPresenceUpdate('recording', chatJid).catch(() => {});
            await sendVoiceNote(sock, chatJid, speak, msg);
            stats.msgsSent++;
        } catch (e) {
            err('🔊', `.tts failed: ${e.message}`);
            await sendText(sock, chatJid, '_Could not make a voice note right now._', msg);
        }
        return;
    }

    // .voice on|off — Ariel answers her chat messages as voice notes in this chat
    if (lower === '.voice' || lower.startsWith('.voice ')) {
        const arg = lower.split(/\s+/)[1];
        if (arg !== 'on' && arg !== 'off') { await sendText(sock, chatJid, '_Usage: .voice on / .voice off_', msg); return; }
        let allowed = !chatJid.endsWith('@g.us') || (ctx.senderJid || '').startsWith(KING_NUMBER);
        if (!allowed) {
            try {
                const meta = await sock.groupMetadata(chatJid);
                const me = meta.participants.find((p) => p.id === ctx.senderJid || p.lid === ctx.senderJid);
                allowed = !!me?.admin;
            } catch {}
        }
        if (!allowed) { await sendText(sock, chatJid, '_Only group admins can change this._', msg); return; }
        setVoiceChat(chatJid, arg === 'on');
        await sendText(sock, chatJid, arg === 'on' ? '🎙️ _Ariel will now reply with voice notes here._' : '💬 _Ariel is back to text replies here._', msg);
        return;
    }

    if (lower.startsWith('.ship')) {
        const parts = text.split(' ').slice(1);
        const p1    = parts[0] || 'Someone';
        const p2    = parts[1] || 'Someone else';
        const pct   = Math.floor(Math.random() * 101);
        const bar   = '❤️'.repeat(Math.floor(pct / 10)) + '🖤'.repeat(10 - Math.floor(pct / 10));
        await sendText(sock, chatJid, `💘 *Ship Results*\n\n${p1} + ${p2}\n${bar}\n*${pct}% compatible!*`, msg);
        return;
    }

    if (lower.startsWith('.wallpaper ')) {
        const query = text.slice(text.indexOf(' ') + 1).trim();
        if (!query) { await sendText(sock, chatJid, '_Usage: .wallpaper [search term]_', msg); return; }
        try {
            const encoded = encodeURIComponent(query);
            const res  = await fetch(
                `https://api.pexels.com/v1/search?query=${encoded}&per_page=6&orientation=portrait`,
                { headers: { Authorization: 'Evtp6BqhsdcBl5dOFKe1oCohDrAcdq3VTqA6wk8hQ9qcFXMCCWgZSbu7' } }
            );
            const data = await res.json();
            const photos = data?.photos;
            if (!photos || photos.length === 0) {
                await sendText(sock, chatJid, `_No images found for "${query}"._`, msg);
                return;
            }
            const picks = photos.slice(0, 6);
            for (let i = 0; i < picks.length; i++) {
                const p = picks[i];
                const imageUrl = p.src?.large || p.src?.medium;
                const credit   = p.photographer || 'Pexels';
                const caption  = i === 0 ? `🔍 *${query}*\n_Photo by ${credit} on Pexels_` : `_Photo by ${credit}_`;
                await sendImage(sock, chatJid, imageUrl, caption, i === 0 ? msg : null);
                if (i < picks.length - 1) await sleep(400);
            }
        } catch(e) {
            await sendText(sock, chatJid, '_Could not fetch image right now._', msg);
        }
        return;
    }

    if (lower.startsWith('.pint ')) {
        const query = text.slice(text.indexOf(' ') + 1).trim();
        if (!query) { await sendText(sock, chatJid, '_Usage: .pint [search term]_', msg); return; }
        try {
            // Pinterest's internal search endpoint has been observed
            // returning HTTP 200 + valid JSON but an EMPTY results array
            // for otherwise-common queries, with `is_unauth_botspam_asn:
            // true` in the same response — a soft, IP-reputation-based
            // degradation rather than a real "no results" or a hard
            // block. A slightly reworded retry sometimes gets through
            // where the original phrasing didn't; this is a mitigation
            // for that specific behavior, not a real fix (there isn't
            // one available without an official Pinterest API — and
            // Pinterest's own v5 API doesn't expose public pin search
            // at all, so it can't replace this endpoint either).
            let rawImages = await pinterestSearch(query, 6);
            if (!rawImages || rawImages.length === 0) {
                rawImages = await pinterestSearch(`${query} `, 6).catch(() => []); // trailing space -> different cache/edge path
            }
            if (!rawImages || rawImages.length === 0) {
                await sendText(sock, chatJid, `_No images found for "${query}"._`, msg);
                return;
            }
            const images = await filterValidImageUrls(rawImages);
            if (images.length === 0) {
                err('📌', `.pint "${query}": all ${rawImages.length} result(s) failed image validation`);
                await sendText(sock, chatJid, `_No images found for "${query}"._`, msg);
                return;
            }
            const opts = msg ? { quoted: msg } : {};
            try {
                // Preferred path: one album message, WhatsApp's native
                // 2-wide grid (with a "+N" tile if there are more than
                // fit) — a single bubble that group chat can't
                // interleave text into.
                await sock.sendMessage(chatJid, {
                    albumMessage: images.map((url) => ({ image: { url } })),
                }, opts);
                stats.msgsSent++;
            } catch (albumErr) {
                // The album send itself can fail outright (e.g.
                // "Invalid media type") if even ONE url in the batch is
                // bad in a way our own validation didn't catch (an
                // expired Pinterest CDN token, a redirect, a format
                // Baileys' own album handling doesn't like) — Baileys
                // sends albumMessage as a single atomic unit, so one bad
                // tile currently loses the whole result. Fall back to
                // sending each image as its own message instead of
                // losing everything; this loses the grid layout for
                // this one reply but still gets the player something.
                err('📌', `.pint "${query}" album send failed, falling back to individual sends: ${albumErr.message}`);
                let sentAny = false;
                for (let i = 0; i < images.length; i++) {
                    try {
                        await sendImage(sock, chatJid, images[i], i === 0 ? `🔍 *${query}*` : '', i === 0 ? msg : null);
                        sentAny = true;
                    } catch (imgErr) {
                        err('📌', `.pint "${query}" fallback image ${i} failed: ${imgErr.message}`);
                    }
                    if (i < images.length - 1) await sleep(300);
                }
                if (!sentAny) {
                    await sendText(sock, chatJid, '_Could not fetch image right now._', msg);
                }
            }
        } catch(e) {
            err('📌', `.pint failed for query "${query}": ${e.message}`);
            await sendText(sock, chatJid, '_Could not fetch image right now._', msg);
        }
        return;
    }

    if (lower.startsWith('.play ')) {
        const query = text.slice(text.indexOf(' ') + 1).trim();
        if (!query) { await sendText(sock, chatJid, '_Usage: .play [song/video name]_', msg); return; }

        if (msg) {
            await sock.sendMessage(chatJid, { react: { text: '▶️', key: msg.key } })
                .catch((e) => err('🎵', `.play reaction failed: ${e.message}`));
        }

        const video = await searchYouTube(query).catch((e) => {
            err('🎵', `.play search failed for "${query}": ${e?.message || e}`);
            return null;
        });
        if (!video) {
            await sendText(sock, chatJid, `_No results found for "${query}"._`, msg);
            return;
        }

        const opts = msg ? { quoted: msg } : {};
        await sock.sendMessage(chatJid, {
            image: video.thumbnail ? { url: video.thumbnail } : undefined,
            caption: `Playing: ${video.title}\nPlease wait...`,
        }, opts).catch(() => sendText(sock, chatJid, `Playing: ${video.title}\nPlease wait...`, msg));

        try {
            const result = await downloadYouTubeAudio(video.url, video.videoId);
            await sock.sendMessage(chatJid, {
                audio: result.buffer,
                mimetype: result.mimetype || 'audio/mpeg',
                ptt: false,
            }, opts);
            stats.msgsSent++;
        } catch (e) {
            err('🎵', `.play failed for "${query}" (${video.url}): ${e.message}`);
            await sendText(sock, chatJid, "_Couldn't play audio._", msg);
        }
        return;
    }
    return CONTINUE;
}
