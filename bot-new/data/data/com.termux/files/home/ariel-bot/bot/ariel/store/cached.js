// Read-through cache for the chat history Ariel reads before every reply.
//
//   const store = withChatCache(createPgStore(...), { ttlMs, summariesTtlMs, maxChats })
//
// Only two reads are cached: recentMessages(chatId, limit) and latestSummaries(chatId, n).
// Everything else passes straight through, so the wrapped store behaves like the original.
//
// Safety rules (a stale history would make her answer things that were deleted, or repeat herself):
//  - Any write that changes a chat's messages (recordMessage that inserted, recordOwn, editMessage,
//    deleteMessage) drops that chat's cached messages at once.
//  - A read that started before a write finished is never stored (per-chat version check).
//  - Entries also expire on their own (ttlMs), which covers writes made by other stores (the nightly
//    cleanup, other processes). Summaries have a longer TTL: they only change when the summariser runs.
//  - Callers get copies, so nothing they do to the rows can poison the cache.
//  - Failed reads are never cached. Memory is bounded (maxChats, oldest evicted first).
export function withChatCache(store, { ttlMs = 30_000, summariesTtlMs = 300_000, maxChats = 200, now = Date.now } = {}) {
    const msgs = new Map();      // chatId -> { rows, at, limit, version }
    const sums = new Map();      // `${chatId}:${n}` -> { rows, at }
    const versions = new Map();  // chatId -> number, bumped by every message write
    const counters = { hits: 0, misses: 0, invalidated: 0 };

    const ver = (chatId) => versions.get(chatId) || 0;
    const copy = (rows) => rows.map((r) => ({ ...r }));
    const fresh = (e, ttl) => e && now() - e.at < ttl;

    function bump(chatId) {
        versions.set(chatId, ver(chatId) + 1);
        if (msgs.delete(chatId)) counters.invalidated++;
    }
    function remember(map, key, entry, max) {
        map.delete(key);
        map.set(key, entry);
        while (map.size > max) map.delete(map.keys().next().value);   // oldest first
    }

    async function fetchMessages(chatId, limit) {
        const v = ver(chatId);
        const rows = await store.recentMessages(chatId, limit);
        // keep it only if no message write landed while we were reading
        if (ver(chatId) === v) remember(msgs, chatId, { rows, at: now(), limit, version: v }, maxChats);
        return rows;
    }

    async function recentMessages(chatId, limit) {
        const e = msgs.get(chatId);
        // A cached fetch answers any request for the same or fewer rows (rows are oldest-first, so keep the tail),
        // or any request at all when the chat has fewer rows than the fetch asked for (nothing more to find).
        if (fresh(e, ttlMs) && e.version === ver(chatId) && (limit <= e.limit || e.rows.length < e.limit)) {
            counters.hits++;
            return copy(limit < e.rows.length ? e.rows.slice(-limit) : e.rows);
        }
        counters.misses++;
        return copy(await fetchMessages(chatId, limit));
    }

    async function latestSummaries(chatId, n) {
        const key = `${chatId}:${n || 2}`;
        const e = sums.get(key);
        if (fresh(e, summariesTtlMs)) { counters.hits++; return copy(e.rows); }
        counters.misses++;
        const rows = await store.latestSummaries(chatId, n);
        remember(sums, key, { rows, at: now() }, maxChats * 2);
        return copy(rows);
    }

    const wrapped = Object.create(store);   // every other method falls through to the real store
    Object.assign(wrapped, {
        recentMessages,
        async recordMessage(args) {
            const r = await store.recordMessage(args);
            if (r?.inserted !== false) bump(args.chatId);
            return r;
        },
        async recordOwn(args) { const r = await store.recordOwn(args); bump(args.chatId); return r; },
        async editMessage(args) { const r = await store.editMessage(args); bump(args.chatId); return r; },
        async deleteMessage(args) { const r = await store.deleteMessage(args); bump(args.chatId); return r; },
    });
    if (store.latestSummaries) wrapped.latestSummaries = latestSummaries;

    wrapped.cache = {
        counters,
        size: () => msgs.size + sums.size,
        clear: () => { msgs.clear(); sums.clear(); },
    };
    return wrapped;
}
