// web/health.js  (split out of index.js)
import { app } from './app.js';
import { getLocalIP, log, now } from '../lib/log.js';
import { botState } from '../lib/state.js';
import { BOT_START_TIME, PORT } from '../lib/env.js';
import { clearSupabaseAuth } from '../baileys-auth.js';
import { pendingCallbacks } from '../bridge.js';
import { stats } from '../lib/cache.js';

app.get('/', (req, res) => {
    const ip = getLocalIP();
    if (!botState.currentQR && !botState.currentPairingCode) {
        return res.send(`<!DOCTYPE html><html><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Ariel Bot</title>
<style>body{font-family:sans-serif;text-align:center;padding:30px;background:#111;color:#eee}
h2{color:#7fc97f}p{color:#aaa}.status{font-size:2em;margin:20px}</style>
<meta http-equiv="refresh" content="10">
</head><body>
<h2>⚔️ Ariel Bot</h2>
<div class="status">✅ Connected</div>
<p>Auth stored in Supabase — survives deploys.</p>
<p><a href="/status" style="color:#7fc97f">View JSON status →</a></p>
<hr><p style="font-size:0.8em">IP: ${ip} · Port: ${PORT}</p>
</body></html>`);
    }
    if (botState.currentPairingCode) {
        return res.send(`<!DOCTYPE html><html><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Ariel — Pairing Code</title>
<style>body{font-family:sans-serif;text-align:center;padding:30px;background:#111;color:#eee}
h2{color:#7fc97f}
.code{font-size:3em;font-weight:bold;color:#7fc97f;letter-spacing:8px;
background:#1a1a1a;padding:20px 40px;border-radius:12px;border:2px solid #7fc97f;display:inline-block;margin:20px 0}
.steps{text-align:left;max-width:400px;margin:0 auto;color:#aaa;line-height:2}
.highlight{color:#7fc97f;font-weight:bold}</style>
<meta http-equiv="refresh" content="30">
</head><body>
<h2>⚔️ Ariel Bot — Enter This Code</h2>
<div class="code">${botState.currentPairingCode}</div>
<div class="steps">
<p><span class="highlight">Step 1:</span> Open WhatsApp</p>
<p><span class="highlight">Step 2:</span> Tap ⋮ → Linked Devices</p>
<p><span class="highlight">Step 3:</span> Link a Device</p>
<p><span class="highlight">Step 4:</span> Link with phone number instead</p>
<p><span class="highlight">Step 5:</span> Enter the code above</p>
</div>
<p style="color:#666;font-size:0.8em">Expires in ~60s. Auto-refreshes.</p>
</body></html>`);
    }
    res.send(`<!DOCTYPE html><html><head>
<meta charset="utf-8"><title>Ariel — Scan QR</title>
<style>body{font-family:sans-serif;text-align:center;padding:20px;background:#111;color:#eee}
h2{color:#7fc97f}img{max-width:300px;width:90vw;border:4px solid #7fc97f;border-radius:12px;margin:20px auto;display:block}
p{color:#aaa}.note{color:#f90;font-size:0.9em}</style>
<meta http-equiv="refresh" content="20">
</head><body>
<h2>⚔️ Scan QR with WhatsApp</h2>
<img src="https://api.qrserver.com/v1/create-qr-code/?size=300x300&data=${encodeURIComponent(botState.currentQR)}" alt="QR Code">
<p class="note">⚠️ QR expires every ~20s. Auto-refreshes.</p>
<p>WhatsApp → Linked Devices → Link a Device → Scan</p>
</body></html>`);
});

app.get('/health', (req, res) => {
    res.status(200).json({ status: 'ok', uptime: Math.floor(Date.now()/1000 - BOT_START_TIME) });
});

app.get('/reset', (req, res) => {
    res.send(`<!DOCTYPE html><html><head><meta charset="utf-8">
<title>Ariel — Reset</title>
<style>body{font-family:sans-serif;text-align:center;padding:40px;background:#111;color:#eee}
h2{color:#f66}button{background:#f66;color:#fff;border:none;padding:15px 30px;font-size:1.2em;border-radius:8px;cursor:pointer;margin:20px}</style>
</head><body>
<h2>⚠️ Reset WhatsApp Session</h2>
<p>Clears Supabase auth and restarts. You'll need to re-pair.</p>
<form method="POST" action="/reset"><button type="submit">🗑️ Clear & Restart</button></form>
</body></html>`);
});

app.post('/reset', (req, res) => {
    res.send(`<!DOCTYPE html><html><head><meta charset="utf-8">
<title>Resetting...</title>
<style>body{font-family:sans-serif;text-align:center;padding:40px;background:#111;color:#eee}
h2{color:#7fc97f}p{color:#aaa}.big{font-size:3em;color:#f90}</style>
</head><body>
<h2>✅ Auth Cleared!</h2>
<div class="big" id="timer">30</div>
<p>Go to WhatsApp → Linked Devices → <strong>Unlink ALL devices</strong> now.</p>
<p>Bot will hard-restart automatically when the timer hits zero.</p>
<script>
let t = 30;
const el = document.getElementById('timer');
const iv = setInterval(() => { el.textContent = -.t; if(t<=0) clearInterval(iv); }, 1000);
</script>
</body></html>`);
    setTimeout(async () => {
        await clearSupabaseAuth();
        log('🗑️', 'Auth cleared via /reset. Restarting...');
        setTimeout(() => process.exit(0), 30_000);
    }, 1000);
});

app.get('/status', (req, res) => {
    res.json({
        time: now(), connected: !!botState.activeSockRef, pythonReady: botState.pythonReady,
        uptime: Math.floor(Date.now() / 1000 - BOT_START_TIME),
        linkedGroups: botState.allowedGroups.length, groups: botState.allowedGroups,
        pendingCallbacks: Object.keys(pendingCallbacks).length, stats, ip: getLocalIP(),
    });
});

app.listen(PORT, '0.0.0.0', () => {
    const ip = getLocalIP();
    log('🌐', `Web server started`);
    log('🌐', `On THIS phone:  http://localhost:${PORT}`);
    log('🌐', `On OTHER phone: http://${ip}:${PORT}`);
});

