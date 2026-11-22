// ============================================================
// ARIEL  bot/index.js  (boot only)
// The WhatsApp bot, split by feature:
//   lib/      env, log, db, botState, send helpers, rate limiter, caches
//   groups.js group lists + pools      silent/   silent pool, mines, sleep
//   bridge.js Python bridge            media.js  YouTube/Pinterest/images
//   handler.js handleMessage           baileys.js socket + reconnects
//   web/      Express API              commands.js admin/moderation
// ============================================================

import './lib/config.js';   // must be first: fills process.env from config/identities.json
import './web/auth.js';
import './web/pokemon.js';
import './web/niflheim.js';
import './web/health.js';
import { log, now } from './lib/log.js';
import { PORT, PYTHON_SCRIPT } from './lib/env.js';
import { startPython } from './bridge.js';
import { startSock } from './baileys.js';

// ── Boot ──────────────────────────────────────────────────────
log('🚀', `Ariel booting — ${now()}`);

log('🚀', `Auth: Supabase`);

log('🚀', `Python: ${PYTHON_SCRIPT}`);

startPython();

startSock();

// ── Render keepalive ──────────────────────────────────────────
if (process.env.RENDER || process.env.FLY_APP_NAME) {
    const RENDER_URL = process.env.RENDER_EXTERNAL_URL
        || (process.env.FLY_APP_NAME ? `https://${process.env.FLY_APP_NAME}.fly.dev` : `http://localhost:${PORT}`);
    setInterval(async () => {
        try {
            const http = await import('http');
            const url  = new URL('/health', RENDER_URL);
            http.default.get(url.toString(), (res) => { res.resume(); }).on('error', () => {});
        } catch(e) {}
    }, 14 * 60 * 1000);
    log('💓', `Render keepalive active`);
}

