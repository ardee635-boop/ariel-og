// Fixed relations (config/relations.json: Ivy, Yuki and the King are family) plus each person's rank in the bot.
// The file is the base and always stays. Anything she learns later (memories, e.g. "Ivy is also called Nessa")
// is read next to it in the prompt and never replaces it. Any failure -> she simply has no relation line.
const digits = (v) => {
    const s = String(v || '').split('@')[0].split(':')[0];
    return /^\d{7,15}$/.test(s) ? s : null;
};
const PLAIN = new Set(['', 'guest', 'player', 'member', 'user']);

export function loadBase(raw, env = process.env) {
    const out = [];
    for (const p of raw?.people || []) {
        const phone = digits(p.phone || (p.phoneEnv ? env[p.phoneEnv] : ''));
        if (phone && p.relation) out.push({ phone, name: p.name || null, relation: String(p.relation).slice(0, 80), aka: Array.isArray(p.aka) ? p.aka.slice(0, 4) : [] });
    }
    return out;
}

export function createRelations({ base = [], store, rankOf = null, ttlMs = 300_000, now = Date.now, log = () => {} }) {
    const cache = new Map();        // `${personId}|${chatJid}` -> { at, info }
    const byPhone = new Map(base.map((b) => [b.phone, b]));

    // personIds -> Map(personId -> { relation, aka, rank }) for people who have a fixed relation or a notable rank
    async function describe({ personIds, chatJid = null }) {
        const ids = [...new Set((personIds || []).filter((x) => x != null))];
        const out = new Map();
        const need = [];
        for (const id of ids) {
            const c = cache.get(`${id}|${chatJid}`);
            if (c && now() - c.at < ttlMs) { if (c.info) out.set(id, c.info); } else need.push(id);
        }
        if (!need.length) return out;
        let phones = new Map();
        try { phones = (await store.personPhones(need)) || new Map(); } catch (e) { log(`[ARIEL] relations: phone lookup skipped: ${String(e.message || e).slice(0, 100)}`); return out; }
        for (const id of need) {
            const mine = (phones.get(id) || []).map(digits).filter(Boolean);
            const fixed = mine.map((p) => byPhone.get(p)).find(Boolean) || null;
            let rank = null;
            if (rankOf && mine.length) { try { const r = String(await rankOf(mine[0], chatJid) || '').toLowerCase(); rank = PLAIN.has(r) ? null : r; } catch { /* no rank line */ } }
            const info = fixed || rank ? { relation: fixed?.relation || null, aka: fixed?.aka || [], rank } : null;
            cache.set(`${id}|${chatJid}`, { at: now(), info });
            if (cache.size > 500) cache.delete(cache.keys().next().value);
            if (info) out.set(id, info);
        }
        return out;
    }
    return { describe };
}
