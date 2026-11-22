// silent/mines.js  (split out of index.js)
import { MINE_AUTO_RESUME_MS, MINE_TIMEOUT_MS, _sendAsArielSilently, isSilentGroup, mineAutoResumeTimers, mineTimers, saveMines, silentGroupLastSeen } from './silent.js';
import { botState } from '../lib/state.js';
import { _isSleeping } from './sleep.js';
import { log } from '../lib/log.js';
import { KING_NUMBER } from '../lib/env.js';
import { sendText } from '../lib/send.js';

export function _armMineTimer(mine) {
    if (mineTimers[mine.id]) clearInterval(mineTimers[mine.id]);
    // Initialise lastSeen for this group so the 8-min clock starts fresh on arm
    if (!silentGroupLastSeen[mine.groupJid]) {
        silentGroupLastSeen[mine.groupJid] = Date.now();
    }
    mineTimers[mine.id] = setInterval(async () => {
        if (!botState.activeSockRef) return;
        if (_isSleeping()) return; // fully skip — no typing, no message

        // Skip if this mine was paused (manually or by auto-timeout)
        const liveRef = botState.activeMines.find(m => m.id === mine.id);
        if (liveRef?.paused) return;

        // 8-minute timeout: if the configured watch number hasn't sent anything
        // in this group for 8 minutes, auto-pause all mines with the same label.
        // `.label none` disables this check while mines keep running normally.
        const lastSeen = silentGroupLastSeen[mine.groupJid] || 0;
        if (botState.mineWatchNumber && Date.now() - lastSeen > MINE_TIMEOUT_MS) {
            const mineLabel = liveRef?.label ?? mine.label ?? 1;
            const toPause = botState.activeMines.filter(
                m => m.groupJid === mine.groupJid && (m.label ?? 1) === mineLabel && !m.paused
            );
            if (toPause.length > 0) {
                for (const m of toPause) {
                    m.paused = true;
                    m.autoPaused = true;
                    m.autoResumeAt = null;
                }
                await saveMines();
                log('⛏️', `Auto-paused ${toPause.length} mine(s) (label ${mineLabel}) in ${mine.groupLabel} — no response in 8 min.`);
                // Notify King via DM
                const KING_JID_FULL2 = KING_NUMBER + '@s.whatsapp.net';
                try {
                    await sendText(botState.activeSockRef, KING_JID_FULL2,
                        `⛏️ *Mine auto-paused* — no response in *${mine.groupLabel}* for 8 min. Mine label: *${mineLabel}*\n_It will resume 20 min after the watch number sends again._`
                    );
                } catch {}
            }
            return;
        }

        await _sendAsArielSilently(botState.activeSockRef, mine.groupJid, mine.text);
    }, mine.intervalMs);
}

function _mineAutoResumeKey(groupJid, label) {
    return `${groupJid}:${label ?? 1}`;
}

export function _clearMineAutoResumeTimer(groupJid, label) {
    const key = _mineAutoResumeKey(groupJid, label);
    if (mineAutoResumeTimers[key]) {
        clearTimeout(mineAutoResumeTimers[key]);
        delete mineAutoResumeTimers[key];
    }
}

export function _scheduleMineAutoResume(groupJid, label, resumeAt = Date.now() + MINE_AUTO_RESUME_MS) {
    const key = _mineAutoResumeKey(groupJid, label);
    _clearMineAutoResumeTimer(groupJid, label);
    const delay = Math.max(0, resumeAt - Date.now());
    mineAutoResumeTimers[key] = setTimeout(async () => {
        delete mineAutoResumeTimers[key];
        const targets = botState.activeMines.filter(m =>
            m.groupJid === groupJid &&
            (m.label ?? 1) === label &&
            m.paused &&
            m.autoPaused &&
            m.autoResumeAt &&
            m.autoResumeAt <= Date.now()
        );
        if (!targets.length) return;

        for (const m of targets) {
            m.paused = false;
            m.autoPaused = false;
            m.autoResumeAt = null;
        }
        silentGroupLastSeen[groupJid] = Date.now();
        await saveMines();
        log('⛏️', `Auto-resumed ${targets.length} mine(s) (label ${label}) after 20 min in ${targets[0].groupLabel}.`);

        if (botState.activeSockRef) {
            const KING_JID_FULL2 = KING_NUMBER + '@s.whatsapp.net';
            try {
                await sendText(botState.activeSockRef, KING_JID_FULL2,
                    `▶️ *Mines auto-resumed* — ${targets.length} mine${targets.length > 1 ? 's' : ''} in *${targets[0].groupLabel}* after the watch number returned (label: *${label}*).`
                );
            } catch {}
        }
    }, delay);
}

export function _extractRushCommand(message) {
    const source = String(message || '');
    const match = /\.rush\b\s+([^\r\n]+)/i.exec(source);
    if (!match) return null;

    let label = match[1]
        // Rush labels use underscores instead of spaces, e.g.
        // `*.rush forest_patrol*`. Keep `_` intact; only remove the
        // surrounding markdown markers.
        .replace(/[*~`]+/g, ' ')
        .split(/\s*(?:—|–|\||-{2,})\s*/)[0]
        .replace(/\s+\d+(?:\.\d+)?\s*(?:ms|s|sec|secs|seconds|m|min|mins|minutes)\b.*$/i, '')
        .replace(/[.!?,;:]+$/g, '')
        .replace(/\s+/g, ' ')
        .trim();

    if (!label) return null;
    return `.rush ${label}`;
}

// Used for replies to King's own .groups/.silentlink/.mine/.mines/.unmine
// commands: if King typed the command inside a group that's silent-linked,
// route the reply through the disguised typing-indicator path so the
// confirmation itself never breaks cover. Anywhere else (a normal linked
// group, or an unlinked group not yet silent), just reply normally.
export async function _replyMaybeSilent(sock, chatJid, text, msg = null) {
    if (isSilentGroup(chatJid)) {
        await _sendAsArielSilently(sock, chatJid, text);
    } else {
        await sendText(sock, chatJid, text, msg);
    }
}

export function _disarmMineTimer(id) {
    if (mineTimers[id]) {
        clearInterval(mineTimers[id]);
        delete mineTimers[id];
    }
}

export async function startAllMines() {
    for (const mine of botState.activeMines) {
        _armMineTimer(mine);
        if (mine.paused && mine.autoPaused && mine.autoResumeAt) {
            _scheduleMineAutoResume(mine.groupJid, mine.label ?? 1, mine.autoResumeAt);
        }
    }
    if (botState.activeMines.length) log('⛏️', `Re-armed ${botState.activeMines.length} mine(s) after boot.`);
}

// Parses a duration string like "10s", "5m", "1h" into milliseconds.
// Returns null if unparseable.
export function _parseDuration(str) {
    const m = /^(\d+(?:\.\d+)?)\s*(ms|s|m|h)$/i.exec(str.trim());
    if (!m) return null;
    const n = parseFloat(m[1]);
    const unit = m[2].toLowerCase();
    const mult = { ms: 1, s: 1000, m: 60_000, h: 3_600_000 }[unit];
    return Math.round(n * mult);
}

