// lib/diagnostics.js  (split out of index.js)
import { BOT_START_TIME, PORT } from './env.js';
import { getLocalIP, now } from './log.js';
import { botState } from './state.js';
import { stats } from './cache.js';
import { pendingCallbacks } from '../bridge.js';

export function getDiagnostics() {
    const up  = Math.floor(Date.now() / 1000 - BOT_START_TIME);
    const hh  = String(Math.floor(up / 3600)).padStart(2, '0');
    const mm  = String(Math.floor((up % 3600) / 60)).padStart(2, '0');
    const ss  = String(up % 60).padStart(2, '0');
    const ip  = getLocalIP();
    return (
        `🤖 *Ariel Diagnostics* — ${now()}\n\n` +
        `⏱ Uptime: ${hh}:${mm}:${ss}\n` +
        `🌐 WA Connected: ${botState.activeSockRef ? '✅' : '❌'}\n` +
        `🐍 Python Ready: ${botState.pythonReady ? '✅' : '❌'}\n` +
        `📋 Linked Groups: ${botState.allowedGroups.length}\n` +
        `📥 Received: ${stats.msgsReceived}  ⚙️ Handled: ${stats.msgsHandled}\n` +
        `📤 Sent: ${stats.msgsSent}  ❌ Errors: ${stats.errors}\n` +
        `🕐 Last msg: ${stats.lastMsg || 'none'}\n` +
        `👤 Last sender: ${stats.lastSender || 'none'}\n` +
        `🐍 Pending callbacks: ${Object.keys(pendingCallbacks).length}\n` +
        `🌍 Status: http://${ip}:${PORT}\n\n` +
        `🔐 Auth: Supabase (persistent)`
    );
}

