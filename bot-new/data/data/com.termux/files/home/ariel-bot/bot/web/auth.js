// web/auth.js  (split out of index.js)
import argon2 from 'argon2';
import jwt from 'jsonwebtoken';
import { app } from './app.js';
import { buildSenderJid, issueSessionCookie } from '../lib/session.js';
import { _getDB } from '../lib/db.js';
import { err } from '../lib/log.js';
import { JWT_SECRET } from '../lib/env.js';

// ── Site auth API ───────────────────────────────────────────
app.post('/api/auth/signup', async (req, res) => {
    try {
        const { username, countryCode, phoneNumber, password } = req.body || {};

        if (!username || !username.trim() || username.length > 50) {
            return res.status(400).json({ error: 'Username is required (max 50 characters).' });
        }
        if (!countryCode || !phoneNumber) {
            return res.status(400).json({ error: 'Phone number is required.' });
        }
        if (!password || password.length < 5) {
            return res.status(400).json({ error: 'Password must be at least 5 characters.' });
        }

        const sender = buildSenderJid(countryCode, phoneNumber);
        const phone  = sender.split('@')[0];
        const trimmedName = username.trim();

        const db = await _getDB();

        // One account per phone number, ever — reject if already signed up on the site.
        const existingUser = await db.query('SELECT 1 FROM users WHERE phone = $1 LIMIT 1', [phone]);
        if (existingUser.rows.length > 0) {
            return res.status(409).json({ error: 'An account already exists for this phone number. Try logging in instead.' });
        }

        // Symbiotic upsert into players: rename existing WA trainer, or leave untouched
        // (a real Player row gets created later when they register in-game).
        const existingPlayer = await db.query('SELECT data FROM players WHERE sender = $1', [sender]);
        if (existingPlayer.rows.length > 0) {
            const data = existingPlayer.rows[0].data;
            data.name = trimmedName;
            await db.query('UPDATE players SET data = $1 WHERE sender = $2', [data, sender]);
        }

        const passwordHash = await argon2.hash(password, { type: argon2.argon2id });
        await db.query(
            `INSERT INTO users (phone, username, password_hash) VALUES ($1, $2, $3)`,
            [phone, trimmedName, passwordHash]
        );

        issueSessionCookie(res, { phone, username: trimmedName });
        res.status(201).json({ username: trimmedName, phone });
    } catch (e) {
        err('🔐', `signup error: ${e.message}`);
        res.status(500).json({ error: 'Something went wrong. Try again.' });
    }
});

app.post('/api/auth/login', async (req, res) => {
    try {
        const { countryCode, phoneNumber, password } = req.body || {};
        if (!countryCode || !phoneNumber || !password) {
            return res.status(400).json({ error: 'Phone number and password are required.' });
        }

        const sender = buildSenderJid(countryCode, phoneNumber);
        const phone  = sender.split('@')[0];

        const db = await _getDB();
        const result = await db.query('SELECT username, password_hash FROM users WHERE phone = $1', [phone]);
        if (result.rows.length === 0) {
            return res.status(401).json({ error: 'No account found for this phone number.' });
        }

        const { username, password_hash } = result.rows[0];
        const valid = await argon2.verify(password_hash, password);
        if (!valid) {
            return res.status(401).json({ error: 'Incorrect password.' });
        }

        issueSessionCookie(res, { phone, username });
        res.status(200).json({ username, phone });
    } catch (e) {
        err('🔐', `login error: ${e.message}`);
        res.status(500).json({ error: 'Something went wrong. Try again.' });
    }
});

app.get('/api/auth/me', async (req, res) => {
    const token = req.cookies?.niflheim_session;
    if (!token) return res.status(401).json({ error: 'Not logged in.' });
    try {
        const payload = jwt.verify(token, JWT_SECRET);
        const db = await _getDB();
        const result = await db.query('SELECT username FROM users WHERE phone = $1', [payload.phone]);
        if (result.rows.length === 0) {
            // Account was reset/deleted server-side — the JWT is still
            // cryptographically valid but the account it points to is gone.
            res.clearCookie('niflheim_session', { httpOnly: true, secure: true, sameSite: 'none' });
            return res.status(401).json({ error: 'Session expired.' });
        }
        res.json({ username: result.rows[0].username, phone: payload.phone });
    } catch {
        res.status(401).json({ error: 'Session expired.' });
    }
});

app.post('/api/auth/logout', (req, res) => {
    res.clearCookie('niflheim_session', { httpOnly: true, secure: true, sameSite: 'none' });
    res.status(200).json({ ok: true });
});

// ── Site player-data API ────────────────────────────────────
// Shared helper: verify session cookie, return { phone, sender } or null.
export async function _siteAuth(req) {
    const token = req.cookies?.niflheim_session;
    if (!token) return null;
    try {
        const payload = jwt.verify(token, JWT_SECRET);
        const db = await _getDB();
        const result = await db.query('SELECT username FROM users WHERE phone = $1', [payload.phone]);
        if (result.rows.length === 0) return null; // account reset/deleted server-side
        return { phone: payload.phone, username: result.rows[0].username, sender: `${payload.phone}@s.whatsapp.net` };
    } catch {
        return null;
    }
}

