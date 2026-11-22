// lib/ratelimit.js  (split out of index.js)

// ── Simple in-memory rate limiter ──
// Scoped to this one Render process (no Redis needed for a limit this small).
// Keyed by JID so it's per-player, not per-IP — matches how everything else
// here already identifies a user via _siteAuth().sender.
export const _rateLimitHits = new Map();

 // sender -> array of timestamps (ms)
export function _isRateLimited(key, maxHits, windowMs) {
    const now = Date.now();
    const hits = (_rateLimitHits.get(key) || []).filter(t => now - t < windowMs);
    if (hits.length >= maxHits) {
        _rateLimitHits.set(key, hits);
        return true;
    }
    hits.push(now);
    _rateLimitHits.set(key, hits);
    return false;
}

