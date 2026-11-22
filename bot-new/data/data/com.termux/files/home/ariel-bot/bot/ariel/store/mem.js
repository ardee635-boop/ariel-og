// In-memory store with the same methods and rules as store/pg.js + sql/002_ingest.sql.
// Used by the tests (no database needed). Not used in production.

export function createMemStore() {
    let seq = 0;
    const next = () => ++seq;
    const s = {
        people: new Map(),      // id -> { id, display_name, first_seen, last_seen, style, boundaries }
        identities: new Map(),  // value -> { person_id, kind }
        chats: new Map(),       // key -> { id, kind, key, settings }
        members: new Map(),     // `${chatId}:${personId}` -> { chat_id, person_id, msg_count, last_seen }
        messages: [],           // { id, chat_id, person_id, wa_message_id, reply_to, body, meta, created_at }
        memories: [],           // mirrors ariel.memories
        calls: 0,               // statements issued, for cache tests
    };

    const ops = {
        async identityRows(values) {
            s.calls++;
            return values.filter((v) => s.identities.has(v))
                .map((v) => ({ person_id: s.identities.get(v).person_id, value: v }));
        },
        async createPerson(displayName) {
            s.calls++;
            const id = next();
            const now = new Date();
            s.people.set(id, { id, display_name: displayName || null, first_seen: now, last_seen: now, style: {}, boundaries: {} });
            return id;
        },
        async addIdentities(personId, identities) {
            s.calls++;
            for (const i of identities) if (!s.identities.has(i.value)) s.identities.set(i.value, { person_id: personId, kind: i.kind });
        },
        async mergePeople(keepId, dropId) {
            s.calls++;
            if (keepId === dropId || !s.people.has(dropId)) return;
            if (!s.people.has(keepId)) throw new Error(`merge_people: keep person ${keepId} does not exist`);
            for (const v of s.identities.values()) if (v.person_id === dropId) v.person_id = keepId;

            const keepDm = s.chats.get(`dm:${keepId}`);
            const dropDm = s.chats.get(`dm:${dropId}`);
            if (dropDm) {
                if (!keepDm) {
                    s.chats.delete(dropDm.key);
                    dropDm.key = `dm:${keepId}`;
                    s.chats.set(dropDm.key, dropDm);
                } else {
                    const have = new Set(s.messages.filter((m) => m.chat_id === keepDm.id && m.wa_message_id).map((m) => m.wa_message_id));
                    s.messages = s.messages.filter((m) => !(m.chat_id === dropDm.id && m.wa_message_id && have.has(m.wa_message_id)));
                    for (const m of s.messages) if (m.chat_id === dropDm.id) m.chat_id = keepDm.id;
                    keepDm.settings = { ...dropDm.settings, ...keepDm.settings };
                    // carry the duplicate's message count over before its member row goes away
                    const from = s.members.get(`${dropDm.id}:${dropId}`);
                    const into = s.members.get(`${keepDm.id}:${keepId}`);
                    if (from && into) {
                        into.msg_count += from.msg_count;
                        if (from.last_seen > into.last_seen) into.last_seen = from.last_seen;
                    }
                    for (const [k, mem] of [...s.members]) if (mem.chat_id === dropDm.id) s.members.delete(k);
                    s.chats.delete(dropDm.key);
                }
            }
            for (const [k, d] of [...s.members]) {
                if (d.person_id !== dropId) continue;
                const kk = `${d.chat_id}:${keepId}`;
                const kept = s.members.get(kk);
                if (kept) {
                    kept.msg_count += d.msg_count;
                    if (d.last_seen > kept.last_seen) kept.last_seen = d.last_seen;
                    s.members.delete(k);
                } else {
                    s.members.delete(k);
                    s.members.set(kk, { ...d, person_id: keepId });
                }
            }
            for (const m of s.messages) if (m.person_id === dropId) m.person_id = keepId;
            const k = s.people.get(keepId);
            const d = s.people.get(dropId);
            k.first_seen = k.first_seen < d.first_seen ? k.first_seen : d.first_seen;
            k.last_seen = k.last_seen > d.last_seen ? k.last_seen : d.last_seen;
            k.display_name = k.display_name ?? d.display_name;
            k.style = { ...d.style, ...k.style };
            k.boundaries = { ...d.boundaries, ...k.boundaries };
            s.people.delete(dropId);
        },
        async ensureChat({ key, kind, settings }) {
            s.calls++;
            let c = s.chats.get(key);
            if (!c) { c = { id: next(), kind, key, settings: {} }; s.chats.set(key, c); }
            c.settings = { ...c.settings, ...(settings || {}) };
            return c.id;
        },
        async recordMessage({ chatId, personId, waId, replyTo, body, meta, ts, displayName }) {
            s.calls++;
            if (waId && s.messages.some((m) => m.chat_id === chatId && m.wa_message_id === waId)) {
                touch(personId, ts, displayName);
                return { inserted: false };
            }
            s.messages.push({ id: next(), chat_id: chatId, person_id: personId, wa_message_id: waId, reply_to: replyTo, body, meta: meta || {}, created_at: ts });
            const k = `${chatId}:${personId}`;
            const m = s.members.get(k);
            if (m) { m.msg_count++; if (ts > m.last_seen) m.last_seen = ts; }
            else s.members.set(k, { chat_id: chatId, person_id: personId, msg_count: 1, last_seen: ts });
            touch(personId, ts, displayName);
            return { inserted: true };
        },
        async recentMessages(chatId, limit) {
            s.calls++;
            return s.messages.filter((m) => m.chat_id === chatId)
                .sort((a, b) => (a.created_at - b.created_at) || (a.id - b.id)).slice(-limit)
                .map((m) => ({ ...m, name: m.person_id == null ? null : s.people.get(m.person_id)?.display_name || null }));
        },
        async recordOwn({ chatId, waId, replyTo, body, ts }) {
            s.calls++;
            s.messages.push({ id: next(), chat_id: chatId, person_id: null, wa_message_id: waId, reply_to: replyTo, body, meta: { own: true }, created_at: ts });
        },
        // ── memory (stage 4): same rules as ariel.retrieve_memories, words only (no vectors) ──
        async retrieveMemories({ chatId, presentPersonIds, queryText, k }) {
            s.calls++;
            const chat = [...s.chats.values()].find((c) => c.id === chatId);
            if (!chat) return [];
            const words = new Set(String(queryText || '').toLowerCase().match(/[\p{L}\p{N}']{3,}/gu) || []);
            const present = new Set(presentPersonIds || []);
            const ok = s.memories.filter((m) => !m.superseded_by && (!m.expires_at || m.expires_at > new Date()) && (
                m.scope === 'global'
                || (m.scope === 'group' && m.chat_id === chatId)
                || (m.scope === 'person' && present.has(m.person_id)
                    && s.members.has(`${chatId}:${m.person_id}`)
                    && (chat.kind === 'dm' || m.visibility === 'group_ok'))));
            const hit = (m) => (m.content.toLowerCase().match(/[\p{L}\p{N}']{3,}/gu) || []).some((w) => words.has(w));
            const pick = ok.filter((m) => hit(m) || (m.scope === 'person' && m.importance === 4) || !words.size);
            pick.sort((a, b) => b.importance - a.importance || b.id - a.id);
            const out = pick.slice(0, k || 10);
            for (const m of out) { m.use_count++; m.last_used = new Date(); }
            return out.map(({ id, scope, person_id, visibility, kind, content, importance }) => ({ id, scope, person_id, visibility, kind, content, importance, score: 1 }));
        },
        async personNames(ids) {
            return new Map(ids.map((i) => [i, s.people.get(i)?.display_name || null]));
        },
        async personPhones(ids) {
            const m = new Map();
            for (const [v, x] of s.identities.entries()) if (ids.includes(x.person_id) && (x.kind === 'phone' || x.kind === 'jid')) { if (!m.has(x.person_id)) m.set(x.person_id, []); m.get(x.person_id).push(v); }
            return m;
        },
        async isOwner(personId, values) {
            if (!personId || !values?.length) return false;
            return [...s.identities.entries()].some(([v, x]) => x.person_id === personId && values.includes(v));
        },
        async insertMemory({ scope, personId, chatId, visibility, kind, content, importance, confidence, vec, expiresAt }) {
            const id = next();
            s.memories.push({ id, scope, person_id: personId, chat_id: chatId, visibility, kind, content, importance, confidence, embedding: vec || null, expires_at: expiresAt, superseded_by: null, use_count: 0, last_used: null, created_at: new Date() });
            return id;
        },
        async findSimilar({ scope, personId, chatId, vec }) {
            if (!vec) return null;
            return s.memories.find((m) => !m.superseded_by && m.scope === scope && m.embedding
                && (scope !== 'person' || m.person_id === personId) && (scope !== 'group' || m.chat_id === chatId)
                && JSON.stringify(m.embedding) === JSON.stringify(vec)) || null;
        },
        async touchMemory(id) { const m = s.memories.find((x) => x.id === id); if (m) m.use_count++; },
        async memoryCandidates({ personId, chatId, limit }) {
            return s.memories.filter((m) => !m.superseded_by && ((m.scope === 'person' && m.person_id === personId) || (m.scope === 'group' && m.chat_id === chatId)))
                .sort((a, b) => b.id - a.id).slice(0, limit || 8);
        },
        async deleteMemories({ ids, personId, chatId }) {
            const gone = s.memories.filter((m) => ids.includes(m.id) && ((m.scope === 'person' && m.person_id === personId) || (m.scope === 'group' && m.chat_id === chatId)));
            const goneIds = new Set(gone.map((m) => m.id));
            s.memories = s.memories.filter((m) => !goneIds.has(m.id) && !goneIds.has(m.superseded_by));
            return gone.map((m) => m.id);
        },
        async supersede({ oldIds, newId, personId, chatId, allowGlobal }) {
            for (const m of s.memories) {
                if (oldIds.includes(m.id) && m.id !== newId && ((m.scope === 'person' && m.person_id === personId) || (m.scope === 'group' && m.chat_id === chatId) || (m.scope === 'global' && allowGlobal))) m.superseded_by = newId;
            }
        },
        async memoriesMissingEmbedding(limit) { return s.memories.filter((m) => !m.embedding && !m.superseded_by).slice(0, limit).map((m) => ({ id: m.id, content: m.content })); },
        async setEmbedding(id, vec) { const m = s.memories.find((x) => x.id === id); if (m) m.embedding = vec; },
        async editMessage({ chatId, personId, waId, body }) {
            s.calls++;
            const m = s.messages.find((x) => x.chat_id === chatId && x.wa_message_id === waId && x.person_id === personId);
            if (!m) return { updated: false };
            m.body = body; m.meta = { ...m.meta, edited: true };
            return { updated: true };
        },
        async deleteMessage({ chatId, personId, waId }) {
            s.calls++;
            const before = s.messages.length;
            s.messages = s.messages.filter((x) => !(x.chat_id === chatId && x.wa_message_id === waId && x.person_id === personId));
            return { deleted: s.messages.length < before };
        },
        async setChatEnabled(jid, kind, on) {
            s.calls++;
            let c = s.chats.get(jid);
            if (!c) { c = { id: next(), kind, key: jid, settings: {} }; s.chats.set(jid, c); }
            c.settings = { ...c.settings, chat_on: !!on };
        },
    };

    function touch(personId, ts, displayName) {
        const p = s.people.get(personId);
        if (!p) return;
        if (ts > p.last_seen) p.last_seen = ts;
        if (displayName) p.display_name = displayName;
    }

    // Transactions: snapshot, run, restore on throw.
    ops.tx = async (fn) => {
        const snap = {
            people: structuredClone([...s.people]), identities: structuredClone([...s.identities]),
            chats: structuredClone([...s.chats]), members: structuredClone([...s.members]),
            messages: structuredClone(s.messages), seq,
        };
        try { return await fn(ops); }
        catch (e) {
            s.people = new Map(snap.people); s.identities = new Map(snap.identities);
            s.chats = new Map(snap.chats); s.members = new Map(snap.members);
            s.messages = snap.messages; seq = snap.seq;
            throw e;
        }
    };

    return Object.assign(ops, { state: s });
}
