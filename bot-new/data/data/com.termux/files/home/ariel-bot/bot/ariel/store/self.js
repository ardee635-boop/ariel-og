// Postgres side of stage 8: her developing identity, ongoing state, feedback signals and the change log.
// No new tables: it uses ariel.identity, ariel.ariel_state, ariel.feedback_signals and ariel.config.
// A tiny in-memory twin (createMemSelfStore) is used by the tests.

const LOG_KEY = '_log';          // identity row that holds the change log (never shown to the model)
const LOG_MAX = 150;

export function createSelfStore({ query: q, tx }) {
    return {
        // ── config (ariel.config) ────────────────────────────
        async getConfig(key, fallback = null) {
            const r = await q(`select value from ariel.config where key = $1::text`, [key]);
            return r.rows.length ? r.rows[0].value : fallback;
        },
        async setConfig(key, value) {
            await q(`insert into ariel.config (key, value) values ($1::text, $2::jsonb)
                     on conflict (key) do update set value = excluded.value, updated_at = now()`, [key, JSON.stringify(value)]);
        },

        // ── ongoing state (the single ariel_state row) ──────
        async getState() {
            const r = await q(`select state from ariel.ariel_state where id = 1`);
            return r.rows[0]?.state || {};
        },
        async mergeState(patch) {
            await q(`insert into ariel.ariel_state (id, state) values (1, $1::jsonb)
                     on conflict (id) do update set state = ariel.ariel_state.state || excluded.state, updated_at = now()`, [JSON.stringify(patch)]);
        },

        // ── developing identity (ariel.identity) ────────────
        async listIdentity() {
            const r = await q(`select key, value, evidence_count, version, updated_at from ariel.identity
                                where key not like '\\_%' escape '\\' order by key`);
            return r.rows;
        },
        async upsertIdentity({ key, value, evidenceCount }) {
            await q(`insert into ariel.identity (key, value, evidence_count) values ($1::text, $2::jsonb, $3::int)
                     on conflict (key) do update set value = excluded.value, evidence_count = excluded.evidence_count,
                            version = ariel.identity.version + 1, updated_at = now()`, [key, JSON.stringify(value), evidenceCount]);
        },
        async deleteIdentity(key) {
            const r = await q(`delete from ariel.identity where key = $1::text and key not like '\\_%' escape '\\' returning key`, [key]);
            return r.rows.length > 0;
        },
        async getLog() {
            const r = await q(`select value from ariel.identity where key = $1::text`, [LOG_KEY]);
            return Array.isArray(r.rows[0]?.value?.entries) ? r.rows[0].value.entries : [];
        },
        async appendLog(entry) {
            await tx(async (c) => {
                const cur = await c.query(`select value from ariel.identity where key = $1::text for update`, [LOG_KEY]);
                const entries = [...(Array.isArray(cur.rows[0]?.value?.entries) ? cur.rows[0].value.entries : []), entry].slice(-LOG_MAX);
                await c.query(`insert into ariel.identity (key, value) values ($1::text, $2::jsonb)
                               on conflict (key) do update set value = excluded.value, version = ariel.identity.version + 1, updated_at = now()`,
                    [LOG_KEY, JSON.stringify({ entries })]);
            });
        },

        // ── feedback ────────────────────────────────────────
        // Same person + same kind inside `dedupeHours` counts once (one angry person is one signal).
        async addFeedback({ personId, kind, text, weight = 1, dedupeHours = 12 }) {
            const r = await q(
                `insert into ariel.feedback_signals (person_id, kind, text, weight)
                 select $1::bigint, $2::text, $3::text, $4::real
                  where not exists (select 1 from ariel.feedback_signals f
                                     where f.person_id = $1::bigint and f.kind = $2::text
                                       and f.created_at > now() - ($5::int * interval '1 hour'))
                 returning id`, [personId, kind, text, weight, dedupeHours]);
            return r.rows.length > 0;
        },
        async feedbackSince(since) {
            const r = await q(`select id, person_id, kind, text, created_at from ariel.feedback_signals
                                where created_at > $1::timestamptz order by created_at`, [since.toISOString()]);
            return r.rows;
        },
        async purgeFeedback(days) {
            const r = await q(`delete from ariel.feedback_signals where created_at < now() - ($1::int * interval '1 day') returning id`, [days]);
            return r.rows.length;
        },

        // ── what reflection reads ───────────────────────────
        async recentSummaries({ days, limit }) {
            const r = await q(
                `select s.id, s.chat_id, s.body, s.topics, c.kind, upper(s.period) as ended
                   from ariel.summaries s join ariel.chats c on c.id = s.chat_id
                  where s.verified_at is not null and upper(s.period) > now() - ($1::int * interval '1 day')
                  order by upper(s.period) desc limit $2::int`, [days, limit]);
            return r.rows;
        },
        async personNames() {
            const r = await q(`select display_name from ariel.people where display_name is not null limit 5000`);
            return r.rows.map((x) => x.display_name);
        },
    };
}

export function createMemSelfStore() {
    const s = { config: new Map(), state: {}, identity: new Map(), log: [], feedback: [], summaries: [], names: [], seq: 0, clock: () => Date.now() };
    return {
        state: s,
        async getConfig(k, fb = null) { return s.config.has(k) ? structuredClone(s.config.get(k)) : fb; },
        async setConfig(k, v) { s.config.set(k, structuredClone(v)); },
        async getState() { return structuredClone(s.state); },
        async mergeState(p) { s.state = { ...s.state, ...structuredClone(p) }; },
        async listIdentity() {
            return [...s.identity].sort((a, b) => a[0].localeCompare(b[0])).map(([key, x]) => ({ key, value: structuredClone(x.value), evidence_count: x.evidence_count, version: x.version, updated_at: new Date(s.clock()) }));
        },
        async upsertIdentity({ key, value, evidenceCount }) {
            const cur = s.identity.get(key);
            s.identity.set(key, { value: structuredClone(value), evidence_count: evidenceCount, version: cur ? cur.version + 1 : 1 });
        },
        async deleteIdentity(key) { return s.identity.delete(key); },
        async getLog() { return structuredClone(s.log); },
        async appendLog(e) { s.log = [...s.log, structuredClone(e)].slice(-LOG_MAX); },
        async addFeedback({ personId, kind, text, weight = 1, dedupeHours = 12 }) {
            const t = s.clock();
            if (s.feedback.some((f) => f.person_id === personId && f.kind === kind && t - f.created_at.getTime() < dedupeHours * 3600_000)) return false;
            s.feedback.push({ id: ++s.seq, person_id: personId, kind, text, weight, created_at: new Date(t) });
            return true;
        },
        async feedbackSince(since) { return s.feedback.filter((f) => f.created_at > since).map((f) => ({ ...f })); },
        async purgeFeedback(days) { const n = s.feedback.length; s.feedback = s.feedback.filter((f) => s.clock() - f.created_at.getTime() < days * 86400_000); return n - s.feedback.length; },
        async recentSummaries({ days, limit }) {
            return s.summaries.filter((x) => s.clock() - new Date(x.ended).getTime() < days * 86400_000).sort((a, b) => new Date(b.ended) - new Date(a.ended)).slice(0, limit);
        },
        async personNames() { return [...s.names]; },
    };
}
