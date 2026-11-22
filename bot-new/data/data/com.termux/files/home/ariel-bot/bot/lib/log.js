// lib/log.js  (split out of index.js)
import os from 'os';

// ══════════════════════════════════════════════════════════════

// ── Nigerian time (WAT = UTC+1) ───────────────────────────────
export function ts() {
    return new Date().toLocaleTimeString('en-NG', {
        hour12: true, timeZone: 'Africa/Lagos',
        hour: '2-digit', minute: '2-digit', second: '2-digit',
    });
}

export function now() {
    return new Date().toLocaleString('en-NG', { timeZone: 'Africa/Lagos', hour12: true });
}

export function log(emoji, ...args)  { console.log(`[${ts()}] ${emoji}`, ...args); }

export function warn(emoji, ...args) { console.warn(`[${ts()}] ${emoji}`, ...args); }

export function err(emoji, ...args)  { console.error(`[${ts()}] ${emoji}`, ...args); }

export function getLocalIP() {
    const ifaces = os.networkInterfaces();
    for (const name of Object.keys(ifaces)) {
        for (const iface of ifaces[name]) {
            if (iface.family === 'IPv4' && !iface.internal) return iface.address;
        }
    }
    return '127.0.0.1';
}

export const silentLogger = {
    level: 'silent',
    trace(){}, debug(){}, info(){}, warn(){}, error(){},
    child(){ return this; }
};

