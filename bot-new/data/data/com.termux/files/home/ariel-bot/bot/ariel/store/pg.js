// Postgres store for ingest. Every method is ONE plain SQL statement; the logic
// that decides what to call lives in ingest.js (tested against store/mem.js).
// `query(text, params)` and `tx(fn(client))` come from bot/ariel/db.js.

import { toVector } from '../sqlutil.js';

// pgvector may live in `public` or `extensions` (Supabase). Ask once, then write the type and
// operator with their schema so these queries never depend on the session's search_path.
let vschemaCache = null;
async function vschema(q) {
    if (vschemaCache) return vschemaCache;
    const r = await q(`select n.nspname from pg_extension e join pg_namespace n on n.oid = e.extnamespace where e.extname = 'vector'`);
    const n = r.rows[0]?.nspname;
    if (!n || !/^[a-z_][a-z0-9_]*$/.test(n)) throw new Error('pgvector is not installed in this database');
    return (vschemaCache = n);
}
export { vschema };
const orQuery = (text) => [...new Set(String(text || '').toLowerCase().match(/[\p{L}\p{N}']{3,}/gu) || [])].slice(0, 12).join(' or ');

function build(q) {
    return {
        // [{ person_id, value }] for identity values that already exist.
        async identityRows(values) {
            if (!values.length) return [];
            const r = await q(
                `select person_id, value from ariel.person_identities where value = any($1::text[])`,
                [values]);
            return r.rows;
        },

        async createPerson(displayName) {
            const r = await q(
                `insert into ariel.people (display_name) values ($1::text) returning id`,
                [displayName || null]);
            return r.rows[0].id;
        },

        // identities: [{ kind, value }]. Already-known values are left alone.
        async addIdentities(personId, identities) {
            if (!identities.length) return;
            await q(
                `insert into ariel.person_identities (person_id, kind, value)
                 select $1::bigint, t.k, t.v from unnest($2::text[], $3::text[]) as t(k, v)
                 on conflict (value) do nothing`,
                [personId, identities.map((i) => i.kind), identities.map((i) => i.value)]);
        },

        async mergePeople(keepId, dropId) {
            await q(`select ariel.merge_people($1::bigint, $2::bigint)`, [keepId, dropId]);
        },

        // Create the chat if needed and merge `settings` into it. Returns its id.
        async ensureChat({ key, kind, settings }) {
            const r = await q(
                `insert into ariel.chats (kind, wa_jid, settings)
                 values ($1::text, $2::text, $3::jsonb)
                 on conflict (wa_jid) do update set settings = ariel.chats.settings || excluded.settings
                 returning id`,
                [kind, key, JSON.stringify(settings || {})]);
            return r.rows[0].id;
        },

        // Store a message, count it for the member, touch the person. One statement.
        // Returns { inserted } (false when this WhatsApp message id was already stored).
        async recordMessage({ chatId, personId, waId, replyTo, body, meta, ts, displayName }) {
            const r = await q(
                `with ins as (
                   insert into ariel.messages (chat_id, person_id, wa_message_id, reply_to, body, meta, created_at)
                   values ($1::bigint, $2::bigint, $3::text, $4::text, $5::text, $6::jsonb, $7::timestamptz)
                   on conflict (chat_id, wa_message_id) where wa_message_id is not null do nothing
                   returning id
                 ), mem as (
                   insert into ariel.chat_members (chat_id, person_id, msg_count, last_seen)
                   select $1::bigint, $2::bigint, 1, $7::timestamptz from ins
                   on conflict (chat_id, person_id) do update
                     set msg_count = ariel.chat_members.msg_count + 1,
                         last_seen = greatest(ariel.chat_members.last_seen, excluded.last_seen)
                   returning 1
                 ), ppl as (
                   update ariel.people
                      set last_seen = greatest(last_seen, $7::timestamptz),
                          display_name = coalesce(nullif($8::text, ''), display_name)
                    where id = $2::bigint
                   returning 1
                 )
                 select (select count(*) from ins)::int as inserted`,
                [chatId, personId, waId, replyTo, body, JSON.stringify(meta || {}), ts.toISOString(), displayName || null]);
            return { inserted: r.rows[0].inserted > 0 };
        },

        // Only the author can change or remove their own message.
        async editMessage({ chatId, personId, waId, body }) {
            const r = await q(
                `update ariel.messages set body = $4::text, meta = meta || '{"edited": true}'::jsonb
                  where chat_id = $1::bigint and wa_message_id = $2::text and person_id = $3::bigint
                  returning id`,
                [chatId, waId, personId, body]);
            return { updated: r.rows.length > 0 };
        },

        async deleteMessage({ chatId, personId, waId }) {
            const r = await q(
                `delete from ariel.messages
                  where chat_id = $1::bigint and wa_message_id = $2::text and person_id = $3::bigint
                  returning id`,
                [chatId, waId, personId]);
            return { deleted: r.rows.length > 0 };
        },


        // Newest `limit` messages of a chat, oldest first, with the author's name (person_id null = Ariel).
        async recentMessages(chatId, limit) {
            const r = await q(
                `select m.id, m.wa_message_id, m.person_id, p.display_name as name, m.body, m.meta, m.created_at
                   from ariel.messages m left join ariel.people p on p.id = m.person_id
                  where m.chat_id = $1::bigint
                  order by m.created_at desc, m.id desc
                  limit $2::int`,
                [chatId, limit]);
            return r.rows.reverse();
        },

        // Ariel's own sent message (person_id stays NULL).
        async recordOwn({ chatId, waId, replyTo, body, ts }) {
            await q(
                `insert into ariel.messages (chat_id, person_id, wa_message_id, reply_to, body, meta, created_at)
                 values ($1::bigint, null, $2::text, $3::text, $4::text, '{"own": true}'::jsonb, $5::timestamptz)
                 on conflict (chat_id, wa_message_id) where wa_message_id is not null do nothing`,
                [chatId, waId, replyTo, body, ts.toISOString()]);
        },



        // Newest verified summaries of a chat, oldest first (for the context pack).
        async latestSummaries(chatId, n) {
            const r = await q(
                `select body, open_threads, upper(period) as ended from ariel.summaries
                  where chat_id = $1::bigint and verified_at is not null
                  order by upper(period) desc limit $2::int`,
                [chatId, n || 2]);
            return r.rows.reverse();
        },


        // ── social (stage 6) ─────────────────────────────────────
        async getPersonStates(ids) {
            const out = new Map();
            if (!ids.length) return out;
            const r = await q(`select person_id, familiarity, rapport, last_interaction from ariel.person_state where person_id = any($1::bigint[])`, [ids]);
            for (const x of r.rows) out.set(x.person_id, x);
            return out;
        },
        async savePersonState({ personId, familiarity, rapport, lastInteraction }) {
            await q(
                `insert into ariel.person_state (person_id, familiarity, rapport, last_interaction)
                 values ($1::bigint, $2::real, $3::jsonb, $4::timestamptz)
                 on conflict (person_id) do update
                   set familiarity = excluded.familiarity, rapport = excluded.rapport, last_interaction = excluded.last_interaction`,
                [personId, familiarity, JSON.stringify(rapport), lastInteraction]);
        },
        async getRelationships(chatId, personIds) {
            if (personIds.length < 2) return [];
            const r = await q(
                `select person_a, person_b, kind, strength, notes from ariel.relationships
                  where chat_id = $1::bigint and person_a = any($2::bigint[]) and person_b = any($2::bigint[])`,
                [chatId, personIds]);
            return r.rows;
        },
        async upsertRelationship({ chatId, a, b, kind, strength, notes }) {
            const [lo, hi] = a < b ? [a, b] : [b, a];          // the table requires person_a < person_b
            await q(
                `insert into ariel.relationships (person_a, person_b, chat_id, kind, strength, notes)
                 values ($1::bigint, $2::bigint, $3::bigint, $4::text, $5::real, $6::text)
                 on conflict (chat_id, person_a, person_b) do update
                   set kind = excluded.kind, strength = excluded.strength, notes = excluded.notes, updated_at = now()`,
                [lo, hi, chatId, kind, strength, notes]);
        },
        async chatSettings(chatId) {
            const r = await q(`select settings from ariel.chats where id = $1::bigint`, [chatId]);
            return r.rows[0]?.settings || {};
        },
        async setChatSetting(jid, key, value) {
            const r = await q(
                `update ariel.chats set settings = settings || jsonb_build_object($2::text, $3::jsonb) where wa_jid = $1::text returning id`,
                [jid, key, JSON.stringify(value)]);
            return r.rows.length > 0;
        },
        async getArielState() {
            const r = await q(`select state from ariel.ariel_state where id = 1`);
            return r.rows[0]?.state || {};
        },


        // ── initiative (stage 7) ─────────────────────────────────
        async initiativeChats() {
            const r = await q(
                `select c.id, c.kind, c.wa_jid, c.settings,
                        case when c.kind = 'dm' then (select cm.person_id from ariel.chat_members cm where cm.chat_id = c.id order by cm.msg_count desc limit 1) end as person_id
                   from ariel.chats c`);
            return r.rows;
        },
        async chatActivity(chatId) {
            const r = await q(
                `select max(created_at) filter (where person_id is not null) as last_human,
                        max(created_at) filter (where person_id is null) as last_own,
                        (count(*) filter (where person_id is not null and created_at > now() - interval '24 hours'))::int as h24,
                        (count(*) filter (where person_id is not null and created_at > now() - interval '7 days'))::int as h7
                   from ariel.messages where chat_id = $1::bigint`, [chatId]);
            return r.rows[0];
        },
        // Recent proactive messages (sent or shadow), newest first.
        async initiativeHistory(chatId, limit) {
            const r = await q(
                `select id, kind, status, sent_at, created_at, outcome from ariel.initiatives
                  where chat_id = $1::bigint and status in ('sent', 'shadow') order by created_at desc limit $2::int`,
                [chatId, limit || 30]);
            return r.rows;
        },
        async hasInitiativeKey(key) {
            const r = await q(`select 1 from ariel.initiatives where outcome->>'key' = $1::text limit 1`, [key]);
            return r.rows.length > 0;
        },
        async logInitiative({ chatId, personId, kind, reason, status, key, text }) {
            const r = await q(
                `insert into ariel.initiatives (chat_id, person_id, kind, reason, status, sent_at, outcome)
                 values ($1::bigint, $2::bigint, $3::text, $4::text, $5::text, case when $5::text = 'sent' then now() end, $6::jsonb)
                 returning id`,
                [chatId, personId, kind, reason, status, JSON.stringify({ key: key || null, text: text || null })]);
            return r.rows[0].id;
        },
        async unresolvedInitiatives(olderThanMinutes) {
            const r = await q(
                `select i.id, i.chat_id, i.person_id, i.sent_at, c.kind as chat_kind
                   from ariel.initiatives i join ariel.chats c on c.id = i.chat_id
                  where i.status = 'sent' and (i.outcome->>'resolved') is null
                    and i.sent_at < now() - ((case when c.kind = 'dm' then $1::int * 4 else $1::int end) * interval '1 minute')`,
                [olderThanMinutes]);
            return r.rows;
        },
        async resolveInitiative(id, outcome) {
            await q(`update ariel.initiatives set outcome = coalesce(outcome, '{}'::jsonb) || $2::jsonb where id = $1::bigint`, [id, JSON.stringify(outcome)]);
        },
        // First time someone took her up on it after `since`. DM: any message from that person.
        // Group: a message to her (tag, quote, her name), or the chat picking up (2+ messages within 30 min).
        async firstResponseSince({ chatId, personId, since, dm, directOnly = false }) {
            const r = await q(
                `with m as (
                   select created_at, meta, body from ariel.messages
                    where chat_id = $1::bigint and person_id is not null and created_at > $3::timestamptz
                      and ($2::bigint is null or person_id = $2::bigint))
                 select
                   (select min(created_at) from m where $4::boolean or meta->>'mentioned_ariel' = 'true' or meta->>'quoted_ariel' = 'true' or body ~* 'ariel') as direct,
                   (select count(*) from m where created_at < $3::timestamptz + interval '30 minutes')::int as quick,
                   (select min(created_at) from m) as any_first`,
                [chatId, dm ? personId : null, since, !!dm]);
            const x = r.rows[0];
            if (x.direct) return x.direct;
            return !dm && !directOnly && x.quick >= 2 ? x.any_first : null;
        },
        async setReceptiveness(personId, value) {
            await q(
                `insert into ariel.person_state (person_id, receptiveness) values ($1::bigint, $2::real)
                 on conflict (person_id) do update set receptiveness = excluded.receptiveness`, [personId, value]);
        },
        async getReceptiveness(personId) {
            const r = await q(`select receptiveness from ariel.person_state where person_id = $1::bigint`, [personId]);
            return r.rows.length ? Number(r.rows[0].receptiveness) : null;
        },
        async setChatSettingById(chatId, key, value) {
            await q(`update ariel.chats set settings = settings || jsonb_build_object($2::text, $3::jsonb) where id = $1::bigint`, [chatId, key, JSON.stringify(value)]);
        },
        async getBoundaries(personId) {
            const r = await q(`select boundaries from ariel.people where id = $1::bigint`, [personId]);
            return r.rows[0]?.boundaries || {};
        },
        async setBoundary(personId, key, value) {
            await q(`update ariel.people set boundaries = boundaries || jsonb_build_object($2::text, $3::jsonb) where id = $1::bigint`, [personId, key, JSON.stringify(value)]);
        },
        async openThreadsFor(chatId) {
            const r = await q(
                `select id, open_threads, upper(period) as ended from ariel.summaries
                  where chat_id = $1::bigint and verified_at is not null and upper(period) > now() - interval '14 days'
                  order by upper(period) desc limit 4`, [chatId]);
            return r.rows;
        },
        async recentInitiatives(limit) {
            const r = await q(
                `select i.id, i.kind, i.status, i.reason, i.created_at, i.outcome, c.kind as chat_kind, c.wa_jid
                   from ariel.initiatives i join ariel.chats c on c.id = i.chat_id order by i.id desc limit $1::int`, [limit || 8]);
            return r.rows;
        },

        // ── memory (stage 4) ─────────────────────────────────────
        // The ONLY read path for memories shown to a chat: the privacy function.
        async retrieveMemories({ chatId, presentPersonIds, queryText, vec, k }) {
            const t = await vschema(q);
            const r = await q(
                `select id, scope, person_id, visibility, kind, content, importance, score
                   from ariel.retrieve_memories($1::bigint, $2::bigint[], $3::text, $4::${t}.vector, $5::int)`,
                [chatId, presentPersonIds || [], queryText || '', vec ? toVector(vec) : null, k || 10]);
            return r.rows;
        },

        async personNames(ids) {
            const out = new Map();
            if (!ids.length) return out;
            const r = await q(`select id, display_name from ariel.people where id = any($1::bigint[])`, [ids]);
            for (const x of r.rows) out.set(x.id, x.display_name);
            return out;
        },

        // personIds -> Map(personId -> [phone numbers]) (from the phone / jid identities)
        async personPhones(ids) {
            const m = new Map();
            if (!ids?.length) return m;
            const r = await q(`select person_id, value from ariel.person_identities where person_id = any($1::bigint[]) and kind in ('phone','jid')`, [ids]);
            for (const x of r.rows) { const k = Number(x.person_id); if (!m.has(k)) m.set(k, []); m.get(k).push(x.value); }
            return m;
        },
        async isOwner(personId, values) {
            if (!personId || !values?.length) return false;       // fail closed
            const r = await q(
                `select 1 from ariel.person_identities where person_id = $1::bigint and value = any($2::text[]) limit 1`,
                [personId, values]);
            return r.rows.length > 0;
        },

        async insertMemory({ scope, personId, chatId, visibility, kind, content, importance, confidence, vec, expiresAt }) {
            const t = await vschema(q);
            const r = await q(
                `insert into ariel.memories (scope, person_id, chat_id, visibility, kind, content, importance, confidence, embedding, expires_at)
                 values ($1::text, $2::bigint, $3::bigint, $4::text, $5::text, $6::text, $7::smallint, $8::real, $9::${t}.vector, $10::timestamptz)
                 returning id`,
                [scope, personId, chatId, visibility, kind, content, importance, confidence, vec ? toVector(vec) : null, expiresAt]);
            return r.rows[0].id;
        },

        // Nearly the same memory already stored in this scope? (cosine similarity >= minSim)
        async findSimilar({ scope, personId, chatId, vec, minSim }) {
            const t = await vschema(q);
            const r = await q(
                `select id, content from ariel.memories m
                  where m.superseded_by is null and m.embedding is not null
                    and ((m.scope = 'person' and $1::text = 'person' and m.person_id = $2::bigint)
                      or (m.scope = 'group'  and $1::text = 'group'  and m.chat_id = $3::bigint)
                      or (m.scope = 'global' and $1::text = 'global'))
                    and 1 - (m.embedding operator(${t}.<=>) $4::${t}.vector) >= $5::float8
                  order by m.embedding operator(${t}.<=>) $4::${t}.vector
                  limit 1`,
                [scope, personId, chatId, toVector(vec), minSim]);
            return r.rows[0] || null;
        },

        async touchMemory(id) {
            await q(`update ariel.memories set last_used = now(), use_count = use_count + 1 where id = $1::bigint`, [id]);
        },

        // What THIS speaker may forget or correct: their own person memories and this chat's group memories.
        // Ranked by word / meaning match, then recency. Never global, never someone else's.
        async memoryCandidates({ personId, chatId, queryText, vec, limit }) {
            const t = await vschema(q);
            const r = await q(
                `select m.id, m.scope, m.person_id, m.chat_id, m.visibility, m.kind, m.content, m.importance
                   from ariel.memories m
                  where m.superseded_by is null
                    and ((m.scope = 'person' and m.person_id = $1::bigint)
                      or (m.scope = 'group'  and m.chat_id = $2::bigint))
                  order by
                    ( case when $3::text <> '' and m.fts @@ websearch_to_tsquery('simple', $3::text) then 1 else 0 end
                    + case when $4::${t}.vector is not null and m.embedding is not null
                           then greatest(0, 1 - (m.embedding operator(${t}.<=>) $4::${t}.vector)) else 0 end ) desc,
                    m.created_at desc
                  limit $5::int`,
                [personId, chatId, orQuery(queryText), vec ? toVector(vec) : null, limit || 8]);
            return r.rows;
        },

        // Hard delete, limited in SQL to what the speaker is allowed to remove. Older versions that this
        // memory replaced go with it (they would otherwise come back to life when the FK clears).
        // Returns the ids of the memories the speaker asked about that were really deleted.
        async deleteMemories({ ids, personId, chatId }) {
            const r = await q(
                `with target as (
                   select m.id from ariel.memories m
                    where m.id = any($1::bigint[])
                      and ((m.scope = 'person' and m.person_id = $2::bigint) or (m.scope = 'group' and m.chat_id = $3::bigint))
                 ), chain as (
                   select id from target
                   union
                   select m.id from ariel.memories m join target t on m.superseded_by = t.id
                 ), gone as (
                   delete from ariel.memories where id in (select id from chain) returning id
                 )
                 select id from gone where id = any($1::bigint[])`,
                [ids, personId, chatId]);
            return r.rows.map((x) => x.id);
        },

        // Old rows stay for `keepDays` (rollback), hidden from retrieval because superseded_by is set.
        async supersede({ oldIds, newId, personId, chatId, keepDays, allowGlobal }) {
            await q(
                `update ariel.memories
                    set superseded_by = $2::bigint, expires_at = now() + ($3::int * interval '1 day'), updated_at = now()
                  where id = any($1::bigint[]) and id <> $2::bigint
                    and ((scope = 'person' and person_id = $4::bigint)
                      or (scope = 'group'  and chat_id = $5::bigint)
                      or (scope = 'global' and $6::boolean))`,
                [oldIds, newId, keepDays, personId, chatId, !!allowGlobal]);
        },

        async memoriesMissingEmbedding(limit) {
            const r = await q(
                `select id, content from ariel.memories where embedding is null and superseded_by is null order by id limit $1::int`,
                [limit]);
            return r.rows;
        },

        async setEmbedding(id, vec) {
            const t = await vschema(q);
            await q(`update ariel.memories set embedding = $2::${t}.vector where id = $1::bigint`, [id, toVector(vec)]);
        },

        // The `.chat on/off` switches write here.
        async setChatEnabled(jid, kind, on) {
            await q(
                `insert into ariel.chats (kind, wa_jid, settings)
                 values ($1::text, $2::text, jsonb_build_object('chat_on', $3::boolean))
                 on conflict (wa_jid) do update
                   set settings = ariel.chats.settings || jsonb_build_object('chat_on', $3::boolean)`,
                [kind, jid, !!on]);
        },
    };
}

export function createPgStore({ query, tx }) {
    return {
        ...build((t, p) => query(t, p)),
        tx: (fn) => tx((client) => fn(build((t, p) => client.query(t, p)))),
    };
}
