// baileys.js  (split out of index.js)
import makeWASocket, { fetchLatestBaileysVersion, makeCacheableSignalKeyStore, Browsers, DisconnectReason } from '@whiskeysockets/baileys';
import { BufferJSON } from '@whiskeysockets/baileys';
import { onMemberJoin, onMemberLeave } from './commands.js';
import sharp from 'sharp';
import { initWork, loadWork, startWork, watchOutgoing } from './work.js';
import { botState } from './lib/state.js';
import { err, log, now, silentLogger, warn } from './lib/log.js';
import { getOrderedGroups, loadChatDm, loadGroupPools, loadGroups, loadIgnoredGroups, loadSilentPool } from './groups.js';
import { isSilentGroup, loadMineWatchNumber, loadMines, loadSilentChatGroups, loadSilentGroups, loadSilentStealNumber } from './silent/silent.js';
import { _getDB } from './lib/db.js';
import { sendText, sleep } from './lib/send.js';
import { _parseDuration, startAllMines } from './silent/mines.js';
import { KING_NUMBER, PAIRING_NUMBER } from './lib/env.js';
import { lidMap, presenceCache, stats } from './lib/cache.js';
import { loadSleepWindows } from './silent/sleep.js';
import { clearSupabaseAuth, useSupabaseAuthState } from './baileys-auth.js';
import { handleMessage } from './handler.js';
import { nextId, noteOurs, observe } from './lib/msgid.js';

export async function startSock() {
    if (botState._sockStarting) {
        warn('🔌', 'startSock() already in progress — skipping duplicate call.');
        return;
    }
    botState._sockStarting = true;
    try {
        await _startSockInner();
    } finally {
        botState._sockStarting = false;
    }
}

async function _startSockInner() {
    // Tear down any previous socket before creating a new one so we never
    // have two live sockets (and two sets of listeners/timers) at once.
    if (botState._currentSock) {
        try {
            botState._currentSock.ev.removeAllListeners();
            botState._currentSock.end(new Error('superseded by new startSock() call'));
        } catch { /* best effort — old socket may already be dead */ }
        botState._currentSock = null;
    }

    await loadGroups();
    await loadIgnoredGroups();
    await loadGroupPools();
    await loadSilentPool();
    await loadSilentChatGroups();
    await loadChatDm();
    await loadSilentGroups();
    await loadMines();
    initWork({
        getDB: _getDB,
        getSock: () => botState.activeSockRef,
        sendText,
        sleep,
        parseDuration: _parseDuration,
        kingNumber: KING_NUMBER,
        lidMap,
        isSilentGroup,
        getOrderedGroups,
        log,
        err,
    });
    await loadWork();
    await loadMineWatchNumber();
    await loadSilentStealNumber();
    await loadSleepWindows();
    console.log('BufferJSON:', typeof BufferJSON, Object.keys(BufferJSON));
    // ... rest of the code
    let state, saveCreds;
    try {
        ({ state, saveCreds } = await useSupabaseAuthState());
        log('🔐', 'Auth loaded from Supabase.');
    } catch (e) {
        err('🔐', `Supabase auth failed: ${e.message}`);
        err('🔐', 'Check SUPABASE_DB_URL env var.');
        return setTimeout(startSock, 5000);
    }

    let version;
    try {
        ({ version } = await fetchLatestBaileysVersion());
        log('🔌', `Baileys v${version.join('.')}`);
    } catch (e) {
        warn('🔌', `Could not fetch Baileys version. Using fallback.`);
        version = [2, 3000, 1023527190];
    }

    const sock = makeWASocket({
        version,
        auth: {
        creds: state.creds,
        keys: makeCacheableSignalKeyStore(state.keys, silentLogger),
    },
        logger:              silentLogger,
        printQRInTerminal:   false,
        mobile:              false,
        browser:             Browsers.ubuntu('Chrome'),
        markOnlineOnConnect: false,
        generateHighQualityLinkPreview: true,   // needs link-preview-js; plain URLs get a real card
        syncFullHistory:     false,
        getMessage: async (key) => { return { conversation: '' }; },
        connectTimeoutMs:    60_000,
        keepAliveIntervalMs: 30_000,
    });
    botState._currentSock = sock;
    // .scard id phone — give Ariel's sends phone-shaped message IDs.
    // nextId() returns undefined in 'default' mode, so nothing changes then.
    {
        const _origSend = sock.sendMessage.bind(sock);
        sock.sendMessage = async (jid, content, options = {}) => {
            const id = options?.messageId ? undefined : nextId();
            const sent = await _origSend(jid, content, id ? { ...options, messageId: id } : options);
            noteOurs(sent?.key?.id);
            return sent;
        };
    }
    // Build LID → phone JID map from contacts
    sock.ev.on('contacts.upsert', (contacts) => {
        for (const c of contacts) {
            if (c.lid && c.id) lidMap[c.lid] = c.id;
        }
    });
    sock.ev.on('contacts.update', (updates) => {
        for (const c of updates) {
            if (c.lid && c.id) lidMap[c.lid] = c.id;
        }
    });

    botState.activeSockRef = sock;
    watchOutgoing(sock);   // count every message this account sends in a group (.sactive)
    let pairingRequested = false;
    let wasConnected = false;

        sock.ev.on('connection.update', async ({ connection, lastDisconnect, qr }) => {
        if (qr && !state.creds.registered && !pairingRequested) {
            pairingRequested = true;
            botState.currentQR = qr;
            log('📱', `Attempting pairing code for ${PAIRING_NUMBER}...`);
            try {
                await sleep(2000);
                const code = await sock.requestPairingCode(PAIRING_NUMBER);
                const formatted = code?.match(/.{1,4}/g)?.join('-') || code;
                log('🔑', `PAIRING CODE: ${formatted}`);
                botState.currentPairingCode = formatted;
            } catch(e) {
                err('🔑', `Pairing code failed: ${e.message}`);
            }
        }

        if (connection === 'open') {
            wasConnected       = true;
            botState.currentQR          = null;
            botState.currentPairingCode = null;
            botState.activeSockRef      = sock;
            log('✅', `ARIEL ONLINE — ${now()}`);
            log('✅', `Linked groups: ${botState.allowedGroups.length}`);
            await startAllMines();
            startWork();
            import('./wmode/index.js').then((m) => m.workModeOnConnected(sock)).catch((e) => err('🧰', `Work Mode startup failed: ${e.message}`));
        }

        if (connection === 'close') {
            botState.activeSockRef = null;
            if (botState._currentSock === sock) botState._currentSock = null;
            const code   = lastDisconnect?.error?.output?.statusCode;
            const reason = lastDisconnect?.error?.message || 'unknown';
            const logout = code === DisconnectReason.loggedOut;
            warn('🔌', `Disconnected — code ${code}...`);
if (code === 440) {
    err('🔌', 'Conflict — newer instance detected. Shutting down.');
    process.exit(0);
}
if (logout) {
                err('🔐', 'Session logged out / invalid (401). Clearing Supabase auth and re-pairing.');
                try {
                    await clearSupabaseAuth();
                    log('🔐', 'Supabase auth cleared.');
                } catch (e) {
                    err('🔐', `Failed to clear Supabase auth: ${e.message}`);
                }
                // Auth is gone either way, so there's no "dead session" left to
                // spam WhatsApp with. Restart so a fresh QR/pairing code is
                // actually shown, instead of leaving the bot connected to nothing.
                setTimeout(startSock, 3000);
                return;
            } else {
                setTimeout(startSock, code === 515 || code === 428 ? 3000 : 5000);
            }
        }
    });

    sock.ev.on('creds.update', saveCreds);

    // Log ALL events to see what's being received
    const origEmit = sock.ev.emit.bind(sock.ev);
    sock.ev.emit = (event, ...args) => {

        return origEmit(event, ...args);
    };

    // ── Presence tracking (for .online) ──────────────────────
    // Baileys only reports presence for JIDs we've subscribed to,
    // so this cache fills in as subscribeToPresence() is called
    // (see _cmdOnline in commands.js) and updates land here.
    sock.ev.on('presence.update', ({ id, presences }) => {
        for (const [jid, p] of Object.entries(presences || {})) {
            presenceCache[jid] = { status: p.lastKnownPresence, ts: Date.now(), chatJid: id };
        }
    });

    // ── Group participant events (welcome / leave) ───────────
    sock.ev.on('group-participants.update', async ({ id, participants, action }) => {
        // Only fire welcome/leave if bot is actually connected and linked to this group
        if (!botState.activeSockRef) return;
        if (!botState.allowedGroups.includes(id)) return;
        const db = await _getDB();
        const ctx = { sock, db, chatJid: id, groupParticipants: [] };
        // Normalize — participants can be strings or objects
        const jids = participants.map(p => typeof p === 'string' ? p : p.id || p.jid || String(p));
        if (action === 'add') {
            for (const jid of jids) await onMemberJoin(ctx, jid);
        }
        if (action === 'remove' || action === 'leave') {
            for (const jid of jids) await onMemberLeave(ctx, jid);
        }
    });

    sock.ev.on('messages.upsert', async ({ messages, type }) => {
        console.log(`[MSG] upsert type=${type} count=${messages.length}`);
        for (const _m of messages) observe(_m, type);   // learn your phone's ID length
        if (type !== 'notify') return;
        for (const msg of messages) {
            console.log(`[MSG] from=${msg.key.remoteJid} fromMe=${msg.key.fromMe}`);
            // Temporary diagnostic: dump the raw structure of any incoming
            // group-invite message (ours or another bot's, e.g. while
            // debugging .invite's small-thumbnail issue against another
            // bot's working version in a shared group) so we can compare
            // real field values/sizes instead of guessing from screenshots.
            const invite = msg.message?.groupInviteMessage;
            if (invite) {
                console.log(`[INVITE:raw] from=${msg.key.remoteJid} participant=${msg.key.participant || 'n/a'}`);
                console.log(`[INVITE:raw] groupJid=${invite.groupJid} groupName=${invite.groupName} caption=${invite.caption}`);
                console.log(`[INVITE:raw] jpegThumbnail present=${!!invite.jpegThumbnail} bytes=${invite.jpegThumbnail?.length || 0}`);
                if (invite.jpegThumbnail) {
                    try {
                        const meta = await sharp(Buffer.from(invite.jpegThumbnail)).metadata();
                        console.log(`[INVITE:raw] jpegThumbnail dims=${meta.width}x${meta.height} format=${meta.format}`);
                    } catch (e) {
                        console.log(`[INVITE:raw] jpegThumbnail sharp parse failed: ${e.message}`);
                    }
                }
            }
            try {
                await handleMessage(sock, msg);
            } catch (e) {
                stats.errors++;
                err('💬', `handleMessage crash: ${e.message}`);
                err('💬', e.stack?.split('\n')[1] || '');
            }
        }
    });
}

