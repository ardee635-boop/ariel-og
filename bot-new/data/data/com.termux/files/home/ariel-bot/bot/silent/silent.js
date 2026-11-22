// silent/silent.js  (split out of index.js)
import { _getDB } from '../lib/db.js';
import { botState } from '../lib/state.js';
import { err, log } from '../lib/log.js';
import { KING_NUMBER, MINE_WATCH_NUMBER } from '../lib/env.js';
import { sendAny, sendText, sleep } from '../lib/send.js';
import { callPython } from '../bridge.js';

 // [groupJid, ...]

export async function loadSilentGroups() {
    try {
        const db = await _getDB();
        const res = await db.query('SELECT value FROM bot_auth WHERE key = $1', ['silent_groups']);
        if (res.rows.length) {
            botState.silentGroups = JSON.parse(res.rows[0].value);
            log('🤫', `Loaded ${botState.silentGroups.length} silent-linked groups.`);
        } else {
            botState.silentGroups = [];
        }
    } catch(e) {
        err('🤫', `Failed to load silent groups: ${e.message}`);
        botState.silentGroups = [];
    }
}

export async function saveSilentGroups() {
    try {
        const db = await _getDB();
        await db.query(
            `INSERT INTO bot_auth (key, value) VALUES ($1, $2)
             ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value`,
            ['silent_groups', JSON.stringify(botState.silentGroups)]
        );
    } catch(e) {
        err('🤫', `Failed to save silent groups: ${e.message}`);
    }
}

export function isSilentGroup(groupJid) {
    return botState.silentGroups.includes(groupJid);
}

 // [groupJid, ...]

export async function loadSilentChatGroups() {
    try {
        const db = await _getDB();
        const res = await db.query('SELECT value FROM bot_auth WHERE key = $1', ['silent_chat_groups']);
        if (res.rows.length) {
            botState.silentChatGroups = JSON.parse(res.rows[0].value);
            log('🤫', `Loaded ${botState.silentChatGroups.length} silent-chat groups.`);
        } else {
            botState.silentChatGroups = [];
        }
    } catch(e) {
        err('🤫', `Failed to load silent-chat groups: ${e.message}`);
        botState.silentChatGroups = [];
    }
}

export async function saveSilentChatGroups() {
    try {
        const db = await _getDB();
        await db.query(
            `INSERT INTO bot_auth (key, value) VALUES ($1, $2)
             ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value`,
            ['silent_chat_groups', JSON.stringify(botState.silentChatGroups)]
        );
    } catch(e) {
        err('🤫', `Failed to save silent-chat groups: ${e.message}`);
    }
}

export function isSilentChatGroup(groupJid) {
    return isSilentGroup(groupJid) && botState.silentChatGroups.includes(groupJid);
}

// Ambient reaction tuning for silent-chat groups — see the isSilentGroup
// block in handleMessage. Kept as named constants (not magic numbers)
// so the behavior is easy to find and adjust later.
export const SILENT_CHAT_IDLE_REACTION_CHANCE = 0.05;

 // ~1 in 20 messages gets a filler reaction
export const SILENT_CHAT_FILLERS = ['mmm', 'hmmm', 'hm', 'mm'];

 // [{ id, groupJid, groupLabel, text, intervalMs, label, paused, autoPaused, autoResumeAt, startedAt }]
export const mineTimers = {};

 // { [id]: NodeJS.Timer }
export const mineAutoResumeTimers = {};

 // { [groupJid:label]: NodeJS.Timeout }
export const silentGroupLastSeen = {};

 // { [groupJid]: timestamp ms } — last msg from the configured watch number
export const MINE_TIMEOUT_MS = 8 * 60 * 1000;

 // 8 minutes
export const MINE_AUTO_RESUME_MS = 20 * 60 * 1000;

 // { groupJid, groupLabel, targetNumber } or null
const silentStealBusy = {};

 // { [groupJid]: boolean } — prevent overlapping steal calls

export async function loadMines() {
    try {
        const db = await _getDB();
        const res = await db.query('SELECT value FROM bot_auth WHERE key = $1', ['active_mines']);
        if (res.rows.length) {
            const raw = JSON.parse(res.rows[0].value);
            // Migrate old mine objects that lack label/paused fields
            botState.activeMines = raw.map(m => ({
                ...m,
                label:  m.label  ?? 1,
                paused: m.paused ?? false,
                autoPaused: m.autoPaused ?? false,
                autoResumeAt: m.autoResumeAt ?? null,
            }));
            log('⛏️', `Loaded ${botState.activeMines.length} active mine(s).`);
        } else {
            botState.activeMines = [];
        }
    } catch(e) {
        err('⛏️', `Failed to load mines: ${e.message}`);
        botState.activeMines = [];
    }
}

export async function saveMines() {
    try {
        const db = await _getDB();
        await db.query(
            `INSERT INTO bot_auth (key, value) VALUES ($1, $2)
             ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value`,
            ['active_mines', JSON.stringify(botState.activeMines)]
        );
    } catch(e) {
        err('⛏️', `Failed to save mines: ${e.message}`);
    }
}

export function _normalizeWatchNumber(value) {
    const digits = String(value ?? '').replace(/\D/g, '');
    return digits || null;
}

export function _watchNumberMatches(senderJid, number = botState.mineWatchNumber) {
    return Boolean(number) && (
        senderJid === `${number}@s.whatsapp.net` ||
        senderJid?.startsWith(`${number}@`)
    );
}

export async function loadMineWatchNumber() {
    try {
        const db = await _getDB();
        const res = await db.query('SELECT value FROM bot_auth WHERE key = $1', ['mine_watch_number']);
        if (!res.rows.length) {
            botState.mineWatchNumber = MINE_WATCH_NUMBER;
        } else {
            const saved = String(res.rows[0].value || '').trim().toLowerCase();
            botState.mineWatchNumber = saved === 'none' ? null : _normalizeWatchNumber(saved);
        }
        log('⛏️', botState.mineWatchNumber
            ? `Mine watch number: ${botState.mineWatchNumber}`
            : 'Mine watch number disabled.');
    } catch (e) {
        err('⛏️', `Failed to load mine watch number: ${e.message}`);
        botState.mineWatchNumber = MINE_WATCH_NUMBER;
    }
}

export async function saveMineWatchNumber() {
    try {
        const db = await _getDB();
        await db.query(
            `INSERT INTO bot_auth (key, value) VALUES ($1, $2)
             ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value`,
            ['mine_watch_number', botState.mineWatchNumber || 'none']
        );
    } catch (e) {
        err('⛏️', `Failed to save mine watch number: ${e.message}`);
    }
}

export async function loadSilentStealNumber() {
    try {
        const db = await _getDB();
        const res = await db.query('SELECT value FROM bot_auth WHERE key = $1', ['silent_steal_config']);
        if (res.rows.length) {
            const saved = JSON.parse(res.rows[0].value);
            botState.silentStealConfig = saved?.groupJid && saved?.targetNumber
                ? {
                    groupJid: saved.groupJid,
                    groupLabel: saved.groupLabel || 'selected group',
                    targetNumber: _normalizeWatchNumber(saved.targetNumber),
                }
                : null;
        } else {
            // Number-only settings from the previous format are intentionally
            // left inactive until the new group-number format is configured.
            const legacy = await db.query('SELECT value FROM bot_auth WHERE key = $1', ['silent_steal_number']);
            const saved = String(legacy.rows[0]?.value || '').trim().toLowerCase();
            botState.silentStealConfig = null;
            if (saved && saved !== 'none') {
                log('🤫', 'Ignoring legacy number-only silent-steal setting; configure .ssteal <group no.> <number>.');
            }
        }
        log('🤫', botState.silentStealConfig?.groupJid
            ? `Silent-steal target: ${botState.silentStealConfig.targetNumber} in ${botState.silentStealConfig.groupLabel}`
            : 'Silent-steal watcher disabled.');
    } catch (e) {
        err('🤫', `Failed to load silent-steal target: ${e.message}`);
        botState.silentStealConfig = null;
    }
}

export async function saveSilentStealNumber() {
    try {
        const db = await _getDB();
        await db.query(
            `INSERT INTO bot_auth (key, value) VALUES ($1, $2)
             ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value`,
            ['silent_steal_config', JSON.stringify(botState.silentStealConfig || { disabled: true })]
        );
    } catch (e) {
        err('🤫', `Failed to save silent-steal target: ${e.message}`);
    }
}

// Sends with a 3s typing indicator first, so a silent-linked group
// always sees Ariel "typing..." before the message lands — this is
// what keeps another bot/observer from flagging her as a bot.
export async function _sendAsArielSilently(sock, groupJid, text) {
    try {
        await sock.sendPresenceUpdate('composing', groupJid);
    } catch {}
    await sleep(3000);
    try {
        await sock.sendPresenceUpdate('paused', groupJid);
    } catch {}
    await sendText(sock, groupJid, text);
}

export async function _sendAnyAsArielSilently(sock, groupJid, message) {
    try {
        await sock.sendPresenceUpdate('composing', groupJid);
    } catch {}
    await sleep(3000);
    try {
        await sock.sendPresenceUpdate('paused', groupJid);
    } catch {}
    await sendAny(sock, groupJid, message);
}

export function _isSilentStealFundingCommand(message) {
    return /\.(?:sell|wd)\b/i.test(String(message || ''));
}

export async function _runSilentSteal(sock, groupJid, targetJid) {
    if (silentStealBusy[groupJid]) return;
    silentStealBusy[groupJid] = true;
    try {
        // Use the owner's game account as the account receiving a successful
        // steal. The target is supplied exactly like a quoted participant.
        const result = await callPython(
            `${KING_NUMBER}@s.whatsapp.net`,
            `.steal @${targetJid.split('@')[0]}`,
            targetJid,
            groupJid,
            null,
            'Ice King'
        );

        if (result?.response) {
            // Do not interpret or replace the engine response: this preserves
            // success, failure, and cooldown messages from the real .steal flow.
            await _sendAnyAsArielSilently(sock, groupJid, result.response);
        }

        if (result?.outbox?.length) {
            const seen = new Set();
            for (const item of result.outbox) {
                if (!item?.message || seen.has(item.message)) continue;
                seen.add(item.message);
                await _sendAnyAsArielSilently(sock, groupJid, item.message);
            }
        }
    } catch (e) {
        err('🤫', `Silent-steal failed: ${e.message}`);
    } finally {
        delete silentStealBusy[groupJid];
    }
}

