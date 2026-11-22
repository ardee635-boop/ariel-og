// lib/session.js  (split out of index.js)
import jwt from 'jsonwebtoken';
import { JWT_SECRET } from './env.js';

// ══════════════════════════════════════════════════════════════
// SITE AUTH — phone-based signup/login, one account per number
// ══════════════════════════════════════════════════════════════

// Strips a leading 0, then joins country code + number → WA JID.
// e.g. countryCode "234", phoneNumber "08012345678" → "2348012345678@s.whatsapp.net"
export function buildSenderJid(countryCode, phoneNumber) {
    const cc  = String(countryCode || '').replace(/\D/g, '');
    let num   = String(phoneNumber || '').replace(/\D/g, '');
    if (num.startsWith('0')) num = num.slice(1);
    return `${cc}${num}@s.whatsapp.net`;
}

export function issueSessionCookie(res, payload) {
    const token = jwt.sign(payload, JWT_SECRET, { expiresIn: '30d' });
    res.cookie('niflheim_session', token, {
        httpOnly: true,
        secure: true,
        sameSite: 'none', // cross-origin: site is on Vercel, API is on Render
        maxAge: 30 * 24 * 60 * 60 * 1000,
    });
}

