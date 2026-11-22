// bot/handler/dev_cmds.js - `.arielstatus`, `.clearauth`, `.preview`, `.d`, profile pictures, `.ping`/`.test`/`.uptime`/`.stats`/`.owner`, menu of menus.
// Moved verbatim out of handleMessage (handler.js, original lines 1316-1531).
// run(ctx) returns CONTINUE to fall through to the next step, or ends handling of the message (return / return value).
import { getRank, getRankLevel } from '../commands.js';
import { botState } from '../lib/state.js';
import { BOT_START_TIME, KING_NUMBER, PHONE_NUMBER } from '../lib/env.js';
import { deleteCommandMessage, sendText } from '../lib/send.js';
import { stats } from '../lib/cache.js';
import { _getDB } from '../lib/db.js';
import { getDiagnostics } from '../lib/diagnostics.js';
import { clearSupabaseAuth } from '../baileys-auth.js';
import { startSock } from '../baileys.js';
import { sendThumbnail } from '../media.js';
import { sendCard, sendAdCard } from '../lib/card.js';
import { CONTINUE } from './_common.js';

export async function run(ctx) {
    let { sock, msg, chatJid, senderJid, mentionedJid, BOT_JID, isBotQuote, lower, isKingSender, _cmdOverride } = ctx;

    if (lower === '.arielstatus') {
        await sendText(sock, chatJid, getDiagnostics());
        return;
    }

    if (lower === '.clearauth') {
        const db = await _getDB();
        const rank = await getRank(db, senderJid, [], true);
        if (!_cmdOverride && getRankLevel(rank) < getRankLevel('king')) {
            await sendText(sock, chatJid, `👑 _Only the King can use this._`, msg);
            return;
        }
        await sendText(sock, chatJid, '🗑️ Clearing Supabase auth and re-linking...');
        await clearSupabaseAuth();
        // No process.exit(0) here on purpose. Exiting hands control to Render's
        // restart, and there's a window where the process could be killed/
        // restarted again (redeploy, crash, platform hiccup) before a QR/pairing
        // code is ever shown or scanned — leaving you stuck regenerating codes.
        // Instead we tear down the current socket and call startSock() directly
        // in this same process, so a fresh QR/pairing code appears immediately
        // and reliably, with no restart race.
        try { sock.end(new Error('manual .clearauth reset')); } catch {}
        setTimeout(startSock, 1000);
        return;
    }

    // -- .preview: link-preview test bench --
    //   .preview               list the styles
    //   .preview a|b|c|d|e|f|g  send one style          .preview all   send every style
    //   .preview <letter|all> <image url>   use your own picture (GitHub raw link, ibb, anything direct)
    // Check the result from ANOTHER person's phone: the sender's own phone often shows a card
    // that nobody else can see.
    if (lower === '.preview' || lower.startsWith('.preview ')) {
        const raw   = msg.message?.conversation || msg.message?.extendedTextMessage?.text || '';
        const parts = raw.trim().split(/\s+/).slice(1);
        let pick = (parts[0] || '').toLowerCase();
        const img  = parts.find((x) => /^https?:\/\//i.test(x)) || process.env.PREVIEW_IMG || 'https://i.ibb.co/whDqS2fm/Ghoul-Egg.jpg';
        if (/^https?:\/\//i.test(pick)) pick = 'all';
        const og = `https://ariel-og.vercel.app/api/preview?v=${Date.now()}&title=${encodeURIComponent('Test Preview')}&sub=${encodeURIComponent('Niflheim Online')}&img=${encodeURIComponent(img)}`;
        const T = { title: 'Test Preview', body: 'Niflheim Online - Ariel Bot', image: img, quoted: msg, strict: true };
        const SITE = 'https://niflheim-online.vercel.app';
        const styles = {
            a: ['bare Vercel OG link (old way, WhatsApp crawls it)',     () => sock.sendMessage(chatJid, { text: og })],
            b: ['sendThumbnail (what Ariel really uses)',                () => sendThumbnail(sock, chatJid, img, 'Test Preview', 'Niflheim Online - Ariel Bot', '_style B_', msg)],
            c: ['mini card (linkPreview, small square)',                 () => sendCard(sock, chatJid, { ...T, url: SITE, text: '_style C_' })],
            d: ['big card (linkPreview, big picture)',                   () => sendCard(sock, chatJid, { ...T, url: SITE, text: '_style D_', big: true, shape: 'auto' })],
            e: ['ad-reply card (externalAdReply, what .invite uses)',    () => sendAdCard(sock, chatJid, { ...T, url: SITE, text: '_style E_', big: true })],
            f: ['plain link, no extras (needs link-preview-js)',         () => sock.sendMessage(chatJid, { text: 'https://github.com/WhiskeySockets/Baileys' })],
            g: ['photo with caption (always shows)',                     () => sock.sendMessage(chatJid, { image: { url: img }, caption: '_style G_ - photo + caption' })],
        };
        if (!pick || (pick !== 'all' && !styles[pick])) {
            await sendText(sock, chatJid,
                '*Preview test bench*\n' +
                Object.entries(styles).map(([k, v]) => `*.preview ${k}* - ${v[0]}`).join('\n') +
                '\n\n*.preview all* - send every style\n_Add a picture link at the end to use your own, e.g. .preview d https://raw.githubusercontent.com/..._\n' +
                `_Picture now: ${img}_`, msg);
            return;
        }
        const run = pick === 'all' ? Object.keys(styles) : [pick];
        const nap = (ms) => new Promise((r) => setTimeout(r, ms));
        for (const k of run) {
            try {
                if (run.length > 1) { await sendText(sock, chatJid, `*${k.toUpperCase()}* - ${styles[k][0]}`); await nap(800); }
                await styles[k][1]();
            } catch (e) {
                await sendText(sock, chatJid, `_Style ${k.toUpperCase()} failed: ${e.message}_`, msg);
            }
            if (run.length > 1) await nap(2500);
        }
        return;
    }

    // ── .d — reply to a message to delete it (group admins / King) ──
    if (lower === '.d') {
        if (!chatJid.endsWith('@g.us')) return;
        const _ci = msg.message?.extendedTextMessage?.contextInfo;
        if (!_ci?.stanzaId) {
            await sendText(sock, chatJid, '_Reply to the message you want deleted with .d_', msg);
            return;
        }
        let _parts = [];
        try { _parts = (await sock.groupMetadata(chatJid)).participants; } catch { }
        if (!isKingSender && !_cmdOverride) {
            const _db = await _getDB();
            const _rank = await getRank(_db, senderJid, _parts, true, chatJid);
            if (getRankLevel(_rank) < getRankLevel('baron')) {
                await sendText(sock, chatJid, '_Only group admins (Baron+) can use .d_', msg);
                return;
            }
        }
        // Deleting someone else's message needs Ariel to be a group admin.
        if (!isBotQuote) {
            const _me = _parts.find(p =>
                p.id === BOT_JID || p.phoneNumber === BOT_JID ||
                p.id?.split('@')[0] === PHONE_NUMBER || p.phoneNumber?.split('@')[0] === PHONE_NUMBER);
            if (_me && !_me.admin) {
                await sendText(sock, chatJid, "_I need to be a group admin to delete other people's messages._", msg);
                return;
            }
        }
        const _key = { remoteJid: chatJid, id: _ci.stanzaId, fromMe: isBotQuote, participant: _ci.participant };
        try {
            await sock.sendMessage(chatJid, { delete: _key });
        } catch (e) {
            await sendText(sock, chatJid, `_Couldn't delete that: ${e.message}_`, msg);
            return;
        }
        await deleteCommandMessage(sock, chatJid, msg);   // tidy up the ".d" too (best effort)
        return;
    }

    // ── Profile pictures: .mypfp · .pfp @user / reply · .gcpfp ─────
    if (lower === '.mypfp' || lower === '.gcpfp' || lower === '.pfp' || lower.startsWith('.pfp ')) {
        const isGc = lower === '.gcpfp';
        let target;
        if (isGc) {
            target = chatJid;
        } else if (lower === '.mypfp') {
            target = senderJid;
        } else {
            const _typed = (lower.split(' ')[1] || '').replace(/\D/g, '');
            target = mentionedJid
                || (_typed.length >= 7 && _typed.length <= 15 ? `${_typed}@s.whatsapp.net` : null)
                || senderJid;                         // bare .pfp = your own
        }
        if (isGc && !chatJid.endsWith('@g.us')) {
            await sendText(sock, chatJid, '_.gcpfp only works inside a group._', msg);
            return;
        }
        let url = null, picErr = '';
        try { url = await sock.profilePictureUrl(target, 'image'); }
        catch (e) { picErr = e?.message || String(e); }
        if (!url) {
            try { url = await sock.profilePictureUrl(target, 'preview'); }
            catch (e) { picErr = picErr || e?.message || String(e); }
        }
        console.log(`[PFP] ${target} -> ${url ? 'ok' : 'none'}${picErr ? ` (${picErr})` : ''}`);
        if (!url) {
            const why = /not-authorized|forbidden|401|403/i.test(picErr)
                ? 'hidden by their privacy settings (the bot can only see what its own number can see)'
                : /not-found|404/i.test(picErr) || !picErr
                    ? 'none set'
                    : `WhatsApp said: ${picErr}`;
            await sendText(sock, chatJid,
                isGc ? `_Couldn't get the group picture — ${why}._`
                     : `_Couldn't get that profile picture — ${why}._`, msg);
            return;
        }
        let caption, mentions = [];
        if (isGc) {
            let subject = 'Group';
            try { subject = (await sock.groupMetadata(chatJid)).subject || subject; } catch { }
            caption = `🖼️ *${subject}*`;
        } else {
            caption = `🖼️ @${target.split('@')[0]}`;
            mentions = [target];
        }
        try {
            await sock.sendMessage(chatJid, { image: { url }, caption, mentions }, { quoted: msg });
        } catch {
            try {   // some CDN links reject WhatsApp's own fetch — download it ourselves
                const buf = Buffer.from(await (await fetch(url)).arrayBuffer());
                await sock.sendMessage(chatJid, { image: buf, caption, mentions }, { quoted: msg });
            } catch (e) {
                await sendText(sock, chatJid, `_Couldn't send that picture: ${e.message}_`, msg);
            }
        }
        stats.msgsSent++;
        return;
    }

    if (lower === '.ping') {
        const start = Date.now();
        await sendText(sock, chatJid, `🏓 *Pong!*\n⚡ Response: ${Date.now() - start}ms`, msg);
        return;
    }

    if (lower === '.test') {
        await sendText(sock, chatJid, '✅ *Ariel is online and working!*', msg);
        return;
    }

    if (lower === '.uptime') {
        const up = Math.floor(Date.now() / 1000 - BOT_START_TIME);
        const hh = String(Math.floor(up / 3600)).padStart(2, '0');
        const mm = String(Math.floor((up % 3600) / 60)).padStart(2, '0');
        const ss = String(up % 60).padStart(2, '0');
        await sendText(sock, chatJid, `⏱ *Ariel Uptime*\n${hh}:${mm}:${ss}`, msg);
        return;
    }

    if (lower === '.stats') {
        const up = Math.floor(Date.now() / 1000 - BOT_START_TIME);
        const hh = String(Math.floor(up / 3600)).padStart(2, '0');
        const mm = String(Math.floor((up % 3600) / 60)).padStart(2, '0');
        const ss = String(up % 60).padStart(2, '0');
        await sendText(sock, chatJid,
            `📊 *Ariel Stats*\n\n` +
            `⏱ Uptime: ${hh}:${mm}:${ss}\n` +
            `📥 Received: ${stats.msgsReceived}\n` +
            `⚙️ Handled: ${stats.msgsHandled}\n` +
            `📤 Sent: ${stats.msgsSent}\n` +
            `❌ Errors: ${stats.errors}\n` +
            `🐍 Python calls: ${stats.pythonCalls}\n` +
            `📋 Linked groups: ${botState.allowedGroups.length}`,
        msg);
        return;
    }

    if (lower === '.owner') {
        await sendText(sock, chatJid,
            `👑 *Ariel Owner*\n\n` +
            `• Name: Ice King\n` +
            `• WA: wa.me/${KING_NUMBER}\n` +
            `• Bot crafted with ❤️ using Baileys`,
        msg);
        return;
    }

    // ── .menumenu — index of every menu command ─────────────────────
    // A short directory, not the full content of each menu — just
    // command names to run individually for details. King sees the
    // King-only ones too; everyone else sees only the public menus.
    if (lower === '.menumenu' || lower === '.allmenu' || lower === '.menus') {
        const lines = [
            '📋 *All Menus*', '',
            '• *.menu* — main command menu',
            '• *.pmenu* — Pokémon/Soulbound menu',
            '• *.betmenu* — casino/gambling menu',
            '• *.amenu* — Among Us menu',
        ];
        if (isKingSender) {
            lines.push(
                '• *.royalmenu* — full King command reference',
                '• *.silenttmenu* / *.smenu* — silent-link command reference',
            );
        }
        lines.push('', '_Run any of these directly for the full list._');
        await sendText(sock, chatJid, lines.join('\n'), msg);
        return;
    }
    return CONTINUE;
}
