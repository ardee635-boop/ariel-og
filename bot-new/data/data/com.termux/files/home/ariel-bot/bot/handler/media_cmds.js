// bot/handler/media_cmds.js - Stickers: `.sticker`, `.toimg`, `.vv`, `.tb`, `.take`, Ariel sticker packs.
// Moved verbatim out of handleMessage (handler.js, original lines 1881-2177).
// run(ctx) returns CONTINUE to fall through to the next step, or ends handling of the message (return / return value).
import { downloadContentFromMessage } from '@whiskeysockets/baileys';
import { getRank, getRankLevel } from '../commands.js';
import { sendText } from '../lib/send.js';
import { stats } from '../lib/cache.js';
import { _getDB } from '../lib/db.js';
import { err, log } from '../lib/log.js';
import { ARIEL_FALLBACK_TAG, ARIEL_STICKERS_PREFIX, ARIEL_STICKER_PACK_NAME, _listStickerObjectPaths, _listStickerVariants, _loadArielManifest, _saveArielManifest, _stickerDelete, _stickerUpload } from '../chat/stickers.js';
import { _findLikelyTypo } from '../lib/typo.js';
import { CONTINUE } from './_common.js';


// ── .sp <name> — find a sticker pack by name (sticker.ly) and send it ──
const SP_MAX = 30;          // WhatsApp pack limit
const SP_COOLDOWN_MS = 20_000;
const _spLast = new Map();  // senderJid -> last use
const _spBusy = new Set();  // chatJid currently sending a pack

async function _spSearch(query) {
    const r = await fetch('https://api.sticker.ly/v4/stickerPack/smartSearch', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'User-Agent': 'androidapp.stickerly/2.16.0 (Pixel 6; U; Android 12; en-US; us;)',
        },
        body: JSON.stringify({
            keyword: query,
            enabledKeywordSearch: true,
            filter: { extendSearchResult: false, sortBy: 'RECOMMENDED', languages: ['ALL'], minStickerCount: 5, searchBy: 'ALL', stickerType: 'ALL' },
        }),
        signal: AbortSignal.timeout(15_000),
    });
    if (!r.ok) throw new Error(`search HTTP ${r.status}`);
    const j = await r.json();
    return (j?.result?.stickerPacks || []).filter(p => p?.resourceUrlPrefix && p?.resourceFiles?.length);
}

async function _spDownload(url) {
    const res = await fetch(url, { signal: AbortSignal.timeout(15_000) });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return Buffer.from(await res.arrayBuffer());
}

async function _handleStickerPack(ctx) {
    const { sock, msg, chatJid, senderJid, lower } = ctx;
    let q = lower.replace(/^\.sp\s*/, '').trim();
    if (!q) { await sendText(sock, chatJid, '_Usage: *.sp [name]* — e.g. .sp joker_\n_Add -2, -3… for the next match._', msg); return; }

    let pick = 1;
    const m = q.match(/\s-(\d)$/);
    if (m) { pick = Math.max(1, Number(m[1])); q = q.slice(0, m.index).trim(); }

    const now = Date.now();
    if (now - (_spLast.get(senderJid) || 0) < SP_COOLDOWN_MS) {
        await sendText(sock, chatJid, '_Easy — wait a few seconds before the next pack._', msg);
        return;
    }
    if (_spBusy.has(chatJid)) { await sendText(sock, chatJid, '_Still working on a pack here._', msg); return; }
    _spLast.set(senderJid, now);
    _spBusy.add(chatJid);
    try {
        const packs = await _spSearch(q);
        const pack = packs[pick - 1];
        if (!pack) { await sendText(sock, chatJid, `_No sticker pack found for "${q}"._`, msg); return; }

        const urls = pack.resourceFiles.slice(0, SP_MAX).map(f => pack.resourceUrlPrefix + f);
        // Check the first sticker is reachable before building a card around it.
        try { await _spDownload(urls[0]); } catch (e) {
            err('🎴', `sp first sticker unreachable: ${e.message}`);
            await sendText(sock, chatJid, '_Found the pack but its stickers wouldn\'t download._', msg);
            return;
        }

        const name = pack.name || q;
        const publisher = pack.authorName || 'Ariel';
        const link = pack.packId ? `https://sticker.ly/s/${pack.packId}` : null;
        const more = packs.length > pick ? `\n_Not it? try *.sp ${q} -${pick + 1}*_` : '';

        // Native WhatsApp pack card ("View pack"). Needs a Baileys build that
        // supports `stickerPack`; if it throws or is unsupported we fall back
        // to the pack link and log why, so it's visible in Render logs.
        try {
            await sock.sendMessage(chatJid, {
                stickerPack: {
                    name,
                    publisher,
                    description: `${name} — via Ariel`,
                    cover: { url: urls[0] },
                    stickers: urls.map(u => ({ data: { url: u } })),
                },
            }, { quoted: msg });
            stats.msgsSent++;
            log('🎴', `.sp "${q}" → native pack "${name}" (${urls.length} stickers)`);
            if (more) await sendText(sock, chatJid, more.trim(), msg);
        } catch (e) {
            err('🎴', `native sticker pack failed (${e.message}) — falling back to link`);
            await sendText(sock, chatJid,
                `🎴 *${name}* — ${publisher}\n_${urls.length} stickers_` + (link ? `\n${link}` : '') + more, msg);
        }
    } catch (e) {
        err('🎴', `.sp failed: ${e.message}`);
        await sendText(sock, chatJid, '_Sticker search failed. Try again in a bit._', msg);
    } finally {
        _spBusy.delete(chatJid);
    }
}

export async function run(ctx) {
    let { sock, msg, chatJid, text, senderJid, lower, _cmdOverride } = ctx;

    if (lower === '.sp' || lower.startsWith('.sp ')) { await _handleStickerPack(ctx); return; }

    // ── Sticker (FIXED) ───────────────────────────────────────
    if (lower === '.sticker' || lower === '.s') {
        const ctx    = msg.message?.extendedTextMessage?.contextInfo;
        const quoted = ctx?.quotedMessage;
        const imgMsg = quoted?.imageMessage || quoted?.videoMessage || quoted?.gifMessage;
        if (!imgMsg) {
            await sendText(sock, chatJid, '_Reply to an image or video to make a sticker._', msg);
            return;
        }
        try {
            const msgType = quoted?.imageMessage ? 'image' : 'video';
            const stream  = await downloadContentFromMessage(imgMsg, msgType);
            const chunks  = [];
            for await (const chunk of stream) chunks.push(chunk);
            const buffer  = Buffer.concat(chunks);
            // Try sharp for proper conversion, fallback to raw buffer
            let stickerBuf = buffer;
            try {
                const sharp = (await import('sharp')).default;
                stickerBuf = await sharp(buffer)
                    .resize(512, 512, { fit: 'contain', background: { r:0,g:0,b:0,alpha:0 } })
                    .webp()
                    .toBuffer();
            } catch(sharpErr) {
                // sharp not available - send raw buffer
            }
            await sock.sendMessage(chatJid, { sticker: stickerBuf }, { quoted: msg });
            stats.msgsSent++;
        } catch(e) {
            err('🖼️', `Sticker failed: ${e.message}`);
            await sendText(sock, chatJid, '_Sticker conversion failed. Try again._', msg);
        }
        return;
    }

    // ── To Image ─────────────────────────────────────────────
    if (lower === '.toimg') {
        const ctx    = msg.message?.extendedTextMessage?.contextInfo;
        const quoted = ctx?.quotedMessage;
        if (!quoted?.stickerMessage) {
            await sendText(sock, chatJid, '_Reply to a sticker to convert it to an image._', msg);
            return;
        }
        try {
            const stream  = await downloadContentFromMessage(quoted.stickerMessage, 'sticker');
            const chunks  = [];
            for await (const chunk of stream) chunks.push(chunk);
            const buffer  = Buffer.concat(chunks);
            await sock.sendMessage(chatJid, { image: buffer, caption: '🖼️ _Converted from sticker_' }, { quoted: msg });
        } catch(e) {
            err('🖼️', `ToImg failed: ${e.message}`);
            await sendText(sock, chatJid, '_Conversion failed. Try again._', msg);
        }
        return;
    }

    // ── .tb — transcribe a replied-to voice note (Groq Whisper) ──
    if (lower === '.tb') {
        const quoted = msg.message?.extendedTextMessage?.contextInfo?.quotedMessage;
        const inner  = quoted?.viewOnceMessage?.message
            || quoted?.viewOnceMessageV2?.message
            || quoted?.viewOnceMessageV2Extension?.message
            || quoted;
        const audio  = inner?.audioMessage;
        if (!audio) {
            await sendText(sock, chatJid, '_Reply to a voice note with .tb to transcribe it._', msg);
            return;
        }
        const key = (process.env.GROQ_API_KEY || '').trim();
        if (!key) {
            await sendText(sock, chatJid, '_Transcription is not configured (missing GROQ_API_KEY)._', msg);
            return;
        }
        try {
            const stream = await downloadContentFromMessage(audio, 'audio');
            const chunks = [];
            for await (const chunk of stream) chunks.push(chunk);
            const buffer = Buffer.concat(chunks);
            // Groq's free tier caps uploads at 25 MB.
            if (buffer.length > 24 * 1024 * 1024) {
                await sendText(sock, chatJid, '_That voice note is too large to transcribe._', msg);
                return;
            }
            const form = new FormData();
            form.append('file', new Blob([buffer], { type: 'audio/ogg' }), 'voice.ogg');
            form.append('model', 'whisper-large-v3-turbo');
            form.append('response_format', 'json');
            const res = await fetch('https://api.groq.com/openai/v1/audio/transcriptions', {
                method: 'POST',
                headers: { Authorization: `Bearer ${key}` },
                body: form,
                signal: AbortSignal.timeout(60000),
            });
            const data = await res.json();
            const out = (data.text || '').trim();
            if (!res.ok || !out) {
                err('🎙️', `.tb transcription failed: HTTP ${res.status} ${JSON.stringify(data).slice(0, 200)}`);
                await sendText(sock, chatJid, out === '' && res.ok ? '_No speech detected in that voice note._' : '_Could not transcribe that voice note._', msg);
                return;
            }
            await sendText(sock, chatJid, `🎙️ *Transcript:*\n${out}`, msg);
        } catch (e) {
            err('🎙️', `.tb failed: ${e.message}`);
            await sendText(sock, chatJid, '_Could not transcribe that voice note._', msg);
        }
        return;
    }

    // ── VV (unwrap a view-once message) — Royalty only ────────
    // Reply to a view-once photo/video/voice note with ".vv" to
    // re-send it into the same chat as a normal, permanent message.
    // Gated to Queen+ (same floor as ROYALTY_POOL in commands.js) —
    // this can expose someone's view-once media without their
    // knowledge, so it isn't a general-purpose command.
    if (lower === '.vv') {
        const db = await _getDB();
        const rank = await getRank(db, senderJid, [], true);
        if (!_cmdOverride && getRankLevel(rank) < getRankLevel('queen')) {
            await sendText(sock, chatJid, `👑 _Only Royalty can use this._`, msg);
            return;
        }

        const ctx     = msg.message?.extendedTextMessage?.contextInfo;
        const quoted  = ctx?.quotedMessage;
        // View-once wraps the real media one level down, under one of
        // these three keys depending on WhatsApp client version.
        const voWrap  = quoted?.viewOnceMessage?.message
            || quoted?.viewOnceMessageV2?.message
            || quoted?.viewOnceMessageV2Extension?.message;
        const inner   = voWrap || quoted; // some clients send it unwrapped already
        const mediaMsg = inner?.imageMessage || inner?.videoMessage || inner?.audioMessage;

        if (!mediaMsg) {
            await sendText(sock, chatJid, '_Reply to a view-once photo, video, or voice note with .vv._', msg);
            return;
        }

        try {
            const msgType = inner.imageMessage ? 'image' : inner.videoMessage ? 'video' : 'audio';
            const stream  = await downloadContentFromMessage(mediaMsg, msgType);
            const chunks  = [];
            for await (const chunk of stream) chunks.push(chunk);
            const buffer  = Buffer.concat(chunks);
            const caption = mediaMsg.caption || '';

            if (msgType === 'image') {
                await sock.sendMessage(chatJid, { image: buffer, caption }, { quoted: msg });
            } else if (msgType === 'video') {
                await sock.sendMessage(chatJid, { video: buffer, caption }, { quoted: msg });
            } else {
                await sock.sendMessage(chatJid, { audio: buffer, mimetype: mediaMsg.mimetype || 'audio/ogg; codecs=opus', ptt: true }, { quoted: msg });
            }
            stats.msgsSent++;
        } catch (e) {
            err('👁️', `VV failed: ${e.message}`);
            await sendText(sock, chatJid, '_Could not open that view-once message._', msg);
        }
        return;
    }

    // ── Take (save a sticker into Ariel's vocabulary) ─────────
    // Reply to any sticker with ".take <tag>" to save it as one of
    // Ariel's expression stickers. <tag> is the internal name
    // (letters/numbers/underscore only) — a tag can hold several
    // different images (stickers/ariel/<tag>/1.webp, 2.webp, ...); if
    // it already has any, this adds another variant rather than
    // overwriting. No description anymore — the picker (ariel.py)
    // matches purely on tag name now, so pick a name that reads
    // clearly on its own (e.g. "happy", "blush").
    //
    // If <tag> looks like a likely typo of an existing tag (e.g.
    // "bluzh" vs "blush"), this warns instead of silently creating a
    // near-duplicate — say ".take <tag> confirm" (confirm right after
    // the tag) to save it as a genuinely new tag anyway.
    if (lower.startsWith('.take')) {
        const ctx    = msg.message?.extendedTextMessage?.contextInfo;
        const quoted = ctx?.quotedMessage;
        if (!quoted?.stickerMessage) {
            await sendText(sock, chatJid, '_Reply to a sticker with .take <tag> to save it for Ariel._', msg);
            return;
        }
        const argText = text.slice(5).trim(); // strip ".take"
        const spaceIdx = argText.indexOf(' ');
        const rawTag = (spaceIdx === -1 ? argText : argText.slice(0, spaceIdx)).trim();
        const rest = (spaceIdx === -1 ? '' : argText.slice(spaceIdx + 1).trim());
        const tag = rawTag.toLowerCase().replace(/[^a-z0-9_]/g, '');
        if (!tag) {
            await sendText(sock, chatJid, '_Usage: reply to a sticker with .take <tag>. Example: .take happy_', msg);
            return;
        }

        // "confirm" right after the tag overrides the typo check.
        const forceNewTag = /^confirm\b/i.test(rest);

        const manifest = await _loadArielManifest();
        const existingTags = Object.keys(manifest);
        const isExactExisting = existingTags.includes(tag);

        if (!isExactExisting && !forceNewTag) {
            const typo = _findLikelyTypo(tag, existingTags);
            if (typo) {
                await sendText(
                    sock, chatJid,
                    `_"${tag}" looks close to an existing tag, "${typo}" — did you mean that one? If "${tag}" is meant to be a genuinely new tag, reply again with ".take ${tag} confirm".`,
                    msg
                );
                return;
            }
        }

        try {
            const stream  = await downloadContentFromMessage(quoted.stickerMessage, 'sticker');
            const chunks  = [];
            for await (const chunk of stream) chunks.push(chunk);
            const rawBuffer = Buffer.concat(chunks);

            // Stamp the WhatsApp sticker-pack name/author metadata so
            // if someone saves this sticker from a chat, it shows up
            // grouped under an "Ariel" pack on their end. This is a
            // one-way label on outgoing files only — the bot can't
            // read anything back from "the pack" later, so the actual
            // variant storage below is independent of this metadata.
            let stickerBuf = rawBuffer;
            try {
                const { Sticker } = await import('wa-sticker-formatter');
                const formatted = new Sticker(rawBuffer, {
                    pack: ARIEL_STICKER_PACK_NAME,
                    author: 'Ariel',
                });
                stickerBuf = await formatted.toBuffer();
            } catch (metaErr) {
                // wa-sticker-formatter not installed yet, or failed —
                // fall back to the raw sticker buffer rather than
                // losing the save entirely over a metadata nice-to-have.
                err('🎨', `Sticker pack metadata skipped: ${metaErr.message}`);
            }

            const existingVariants = await _listStickerVariants(tag);
            const nextIndex = existingVariants.length
                ? Math.max(...existingVariants.map(f => parseInt(f))) + 1
                : 1;
            const objectPath = `${ARIEL_STICKERS_PREFIX}/${tag}/${nextIndex}.webp`;
            await _stickerUpload(objectPath, stickerBuf, 'image/webp');
            log('🎨', `[sticker] .take wrote variant ${nextIndex} for tag "${tag}" -> ${objectPath}`);

            if (!(tag in manifest)) manifest[tag] = '';
            await _saveArielManifest(manifest);

            const variantCount = nextIndex;
            const countNote = variantCount > 1 ? ` (variant ${variantCount})` : '';
            await sendText(sock, chatJid, `_Saved sticker as "${tag}"${countNote}_`, msg);
        } catch (e) {
            err('🎨', `.take failed: ${e.message}`);
            await sendText(sock, chatJid, '_Could not save that sticker. Try again._', msg);
        }
        return;
    }

    // .arielstickers — lists every saved tag. The reserved "ariel"
    // fallback tag is always shown first, at position 1, even if it
    // has zero images saved yet (see ARIEL_FALLBACK_TAG) — every other
    // tag follows, alphabetically, starting at 2. No descriptions are
    // shown or stored anymore; the picker now matches on tag name
    // alone, so this is just tag + how many images it holds.
    if (lower === '.arielstickers') {
        const manifest = await _loadArielManifest();
        const otherTags = Object.keys(manifest).filter(t => t !== ARIEL_FALLBACK_TAG).sort();
        const allTags = [ARIEL_FALLBACK_TAG, ...otherTags];
        const lines = ["_Ariel's stickers_"];
        for (let i = 0; i < allTags.length; i++) {
            const tag = allTags[i];
            const count = (await _listStickerVariants(tag)).length;
            lines.push(`${i + 1}. ${tag}: ${count} sticker${count === 1 ? '' : 's'}`);
        }
        await sendText(sock, chatJid, lines.join('\n'), msg);
        return;
    }

    // .resetstickers — wipes every saved tag EXCEPT the reserved
    // "ariel" fallback tag: its manifest entry and images survive a
    // reset on purpose, since it needs to always be there for the
    // picker's fallback to work. Destructive and total for everything
    // else, so it still requires a typed confirm the same way .take's
    // typo-guard does.
    if (lower === '.resetstickers' || lower === '.resetstickers confirm') {
        const manifest = await _loadArielManifest();
        const tagsToWipe = Object.keys(manifest).filter(t => t !== ARIEL_FALLBACK_TAG);
        const tagCount = tagsToWipe.length;
        if (!tagCount) {
            await sendText(sock, chatJid, '_No stickers saved — nothing to reset._', msg);
            return;
        }
        if (lower !== '.resetstickers confirm') {
            await sendText(sock, chatJid, `_This deletes all ${tagCount} saved sticker tag(s) and their files (the "${ARIEL_FALLBACK_TAG}" fallback tag is kept). Reply ".resetstickers confirm" to proceed._`, msg);
            return;
        }
        try {
            const allPaths = [];
            for (const tag of tagsToWipe) {
                allPaths.push(...await _listStickerObjectPaths(tag));
            }
            const keptManifest = {};
            if (ARIEL_FALLBACK_TAG in manifest) keptManifest[ARIEL_FALLBACK_TAG] = manifest[ARIEL_FALLBACK_TAG];
            if (allPaths.length) await _stickerDelete(allPaths);
            await _saveArielManifest(keptManifest);
            log('🎨', `[sticker] .resetstickers wiped ${tagCount} tag(s), kept "${ARIEL_FALLBACK_TAG}"`);
            await sendText(sock, chatJid, `_Cleared ${tagCount} sticker tag(s). "${ARIEL_FALLBACK_TAG}" was kept._`, msg);
        } catch (e) {
            err('🎨', `.resetstickers failed: ${e.message}`);
            await sendText(sock, chatJid, '_Could not reset stickers. Check logs._', msg);
        }
        return;
    }

    // .delpack <tag> — deletes one tag (all its variant files + its
    // manifest entry), addressed directly by tag name rather than a
    // number from .arielstickers. Numbers there shift whenever a tag
    // is added or removed, so a name is the only stable reference.
    // Tag matching runs through the same normalization as .take
    // (lowercase, strip anything but a-z0-9_) so ".delpack Blush" and
    // ".delpack blush" both hit the same saved tag.
    if (lower.startsWith('.delpack')) {
        const rawArg = text.slice(8).trim();
        const tag = rawArg.toLowerCase().replace(/[^a-z0-9_]/g, '');
        if (!tag) {
            await sendText(sock, chatJid, '_Usage: .delpack <tag> — e.g. .delpack blush. See .arielstickers for saved tags._', msg);
            return;
        }
        const manifest = await _loadArielManifest();
        if (tag === ARIEL_FALLBACK_TAG) {
            await sendText(sock, chatJid, `_"${ARIEL_FALLBACK_TAG}" is the reserved fallback tag — it can't be deleted. You can still clear its images by removing them individually if needed._`, msg);
            return;
        }
        if (!(tag in manifest)) {
            await sendText(sock, chatJid, `_No saved tag called "${tag}". Check .arielstickers for current tags._`, msg);
            return;
        }
        try {
            const objectPaths = await _listStickerObjectPaths(tag);
            if (objectPaths.length) await _stickerDelete(objectPaths);
            delete manifest[tag];
            await _saveArielManifest(manifest);
            log('🎨', `[sticker] .delpack removed tag "${tag}"`);
            await sendText(sock, chatJid, `_Deleted "${tag}" and its sticker(s)._`, msg);
        } catch (e) {
            err('🎨', `.delpack failed: ${e.message}`);
            await sendText(sock, chatJid, '_Could not delete that tag. Check logs._', msg);
        }
        return;
    }
    return CONTINUE;
}
