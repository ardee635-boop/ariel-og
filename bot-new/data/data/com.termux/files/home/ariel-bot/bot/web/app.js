// web/app.js  (split out of index.js)
import express from 'express';
import cookieParser from 'cookie-parser';

export const app = express();

// ── CORS: allow the Vercel-hosted site to call this API with cookies ──
// TODO: swap this placeholder for your real Vercel domain once it's live,
// e.g. 'https://niflheim-online.vercel.app'
// SITE_ORIGIN may hold several origins separated by commas (e.g. two Vercel domains).
const SITE_ORIGINS = (process.env.SITE_ORIGIN || 'https://YOUR-SITE.vercel.app').split(',').map(x => x.trim()).filter(Boolean);

app.use((req, res, next) => {
    const origin = req.headers.origin;
    if (SITE_ORIGINS.includes(origin) || origin === 'http://localhost:3000') {
        res.setHeader('Access-Control-Allow-Origin', origin);
        res.setHeader('Access-Control-Allow-Credentials', 'true');
        res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
        res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
    }
    if (req.method === 'OPTIONS') return res.sendStatus(204);
    next();
});

app.use(express.json());

app.use(cookieParser());

