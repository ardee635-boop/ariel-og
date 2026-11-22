// silent/sleep.js  (split out of index.js)
import { _getDB } from '../lib/db.js';
import { botState } from '../lib/state.js';
import { err, log } from '../lib/log.js';

 // [{ id, label, startMin, endMin }, ...]

export async function loadSleepWindows() {
    try {
        const db = await _getDB();
        const res = await db.query('SELECT value FROM bot_auth WHERE key = $1', ['sleep_windows']);
        if (res.rows.length) {
            botState.sleepWindows = JSON.parse(res.rows[0].value);
            log('😴', `Loaded ${botState.sleepWindows.length} sleep window(s).`);
        } else {
            botState.sleepWindows = [];
        }
    } catch(e) {
        err('😴', `Failed to load sleep windows: ${e.message}`);
        botState.sleepWindows = [];
    }
}

export async function saveSleepWindows() {
    try {
        const db = await _getDB();
        await db.query(
            `INSERT INTO bot_auth (key, value) VALUES ($1, $2)
             ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value`,
            ['sleep_windows', JSON.stringify(botState.sleepWindows)]
        );
    } catch(e) {
        err('😴', `Failed to save sleep windows: ${e.message}`);
    }
}

// Parses "11:00am-12:00pm" / "11:00am - 9:30pm" / "23:00-06:00" into
// { startMin, endMin } (minutes since midnight, 0-1439). Returns null
// if unparseable.
export function _parseSleepWindow(str) {
    const clean = str.trim().replace(/\s+/g, '');
    const parts = clean.split('-');
    if (parts.length !== 2) return null;
    const toMinutes = (t) => {
        const m = /^(\d{1,2}):?(\d{2})?(am|pm)?$/i.exec(t.trim());
        if (!m) return null;
        let hour = parseInt(m[1], 10);
        const min = m[2] ? parseInt(m[2], 10) : 0;
        const ampm = m[3]?.toLowerCase();
        if (ampm === 'pm' && hour !== 12) hour += 12;
        if (ampm === 'am' && hour === 12) hour = 0;
        if (hour > 23 || min > 59) return null;
        return hour * 60 + min;
    };
    const startMin = toMinutes(parts[0]);
    const endMin   = toMinutes(parts[1]);
    if (startMin === null || endMin === null) return null;
    return { startMin, endMin };
}

export function _fmtMinutes(mins) {
    const h24 = Math.floor(mins / 60);
    const m   = mins % 60;
    const ampm = h24 < 12 ? 'am' : 'pm';
    let h12 = h24 % 12;
    if (h12 === 0) h12 = 12;
    return `${h12}:${String(m).padStart(2, '0')}${ampm}`;
}

// True if "now" (Africa/Lagos) falls inside ANY active sleep window.
// Handles windows that wrap past midnight (e.g. 11pm-6am).
export function _isSleeping() {
    if (!botState.sleepWindows.length) return false;
    const nowStr = new Date().toLocaleString('en-US', {
        timeZone: 'Africa/Lagos', hour12: false, hour: '2-digit', minute: '2-digit'
    });
    const [h, min] = nowStr.split(':').map(Number);
    const nowMin = h * 60 + min;
    return botState.sleepWindows.some(({ startMin, endMin }) => {
        if (startMin <= endMin) return nowMin >= startMin && nowMin < endMin;
        return nowMin >= startMin || nowMin < endMin; // wraps past midnight
    });
}

