// The wired-up singleton the bot uses: env keys + DB-backed routing/usage.
// Kept apart from index.js so the layer can be tested without a database.
import { createAI } from './index.js';
import { buildAdapters } from './adapters.js';
import { defaultRouting, mergeRouting } from './routing.js';

let cached = null;
let cachedAt = 0;

async function getRouting() {
    if (cached && Date.now() - cachedAt < 60_000) return cached;
    let override = null;
    try {
        const db = await import('../db.js');
        override = await db.getConfig('routing', null);
    } catch { /* DB down or not migrated yet: defaults still work */ }
    cached = mergeRouting(defaultRouting(), override);
    cachedAt = Date.now();
    return cached;
}

const usage = {
    async record(row) { const db = await import('../db.js'); return db.logUsage(row); },
    async todayTokens(role) { const db = await import('../db.js'); return db.todayTokens(role); },
};

export const ai = createAI({ adapters: buildAdapters(process.env), getRouting, usage });
