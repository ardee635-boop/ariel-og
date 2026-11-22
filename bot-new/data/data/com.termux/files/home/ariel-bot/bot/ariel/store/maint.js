// Postgres side of the background work: job queue, conversation segments, summaries,
// consolidation and cleanup. Methods are plain SQL; the decisions live in jobs.js,
// summarise.js and housekeeping.js (which are tested against fake stores).
import { toVector } from '../sqlutil.js';
import { createPgStore, vschema } from './pg.js';

export function createMaintStore({ query: q, tx }) {
    return {
        // ── job queue ────────────────────────────────────────────
        // `key` makes a job unique while it is queued or running (so ticks never pile up).
        async enqueue({ kind, payload = {}, runAt = null, key = null }) {
            const body = key ? { ...payload, key } : payload;
            const r = await q(
                `insert into ariel.jobs (kind, payload, run_at)
                 select $1::text, $2::jsonb, coalesce($3::timestamptz, now())
                  where $4::text is null or not exists (
                        select 1 from ariel.jobs j
                         where j.kind = $1::text and j.status in ('queued', 'running') and j.payload->>'key' = $4::text)
                 returning id`,
                [kind, JSON.stringify(body), runAt, key]);
            return r.rows[0]?.id || null;
        },
        async hasKey(kind, key) {
            const r = await q(`select 1 from ariel.jobs where kind = $1::text and payload->>'key' = $2::text limit 1`, [kind, key]);
            return r.rows.length > 0;
        },
        // FOR UPDATE SKIP LOCKED: two instances can never take the same job.
        async claimJob() {
            const r = await q(
                `update ariel.jobs set status = 'running', locked_at = now(), attempts = attempts + 1
                  where id = (select id from ariel.jobs where status = 'queued' and run_at <= now()
                               order by run_at, id for update skip locked limit 1)
                  returning id, kind, payload, attempts`);
            return r.rows[0] || null;
        },
        async finishJob(id) {
            await q(`update ariel.jobs set status = 'done', finished_at = now(), locked_at = null, last_error = null where id = $1::bigint`, [id]);
        },
        async failJob(id, { error, dead, retryAt }) {
            await q(
                `update ariel.jobs set status = $2::text, last_error = $3::text, run_at = coalesce($4::timestamptz, run_at),
                        locked_at = null, finished_at = case when $2::text = 'dead' then now() else null end
                  where id = $1::bigint`,
                [id, dead ? 'dead' : 'queued', String(error).slice(0, 500), retryAt]);
        },
        // A worker that died mid-job leaves it "running"; jobs are safe to run twice, so put it back.
        async recoverStuck() {
            const r = await q(`update ariel.jobs set status = 'queued', locked_at = null
                                where status = 'running' and locked_at < now() - interval '15 minutes' returning id`);
            return r.rows.length;
        },
        async jobSummary() {
            const c = await q(`select status, count(*)::int as n from ariel.jobs group by status`);
            const d = await q(`select id, kind, attempts, last_error from ariel.jobs where status = 'dead' order by finished_at desc nulls last limit 5`);
            return { counts: Object.fromEntries(c.rows.map((x) => [x.status, x.n])), dead: d.rows };
        },
        async purgeOldJobs() {
            const r = await q(`delete from ariel.jobs where status = 'done' and finished_at < now() - interval '7 days' returning id`);
            return r.rows.length;
        },

        // ── flags (ariel.config) ─────────────────────────────────
        async getFlag(key, fallback) {
            const r = await q(`select value from ariel.config where key = $1::text`, [key]);
            return r.rows.length ? r.rows[0].value : fallback;
        },
        async setFlag(key, value) {
            await q(`insert into ariel.config (key, value) values ($1::text, $2::jsonb)
                     on conflict (key) do update set value = excluded.value, updated_at = now()`, [key, JSON.stringify(value)]);
        },

        // ── segments ─────────────────────────────────────────────
        // Chats whose unprocessed messages form a closed segment: idle long enough, or already long.
        async findOpenSegments({ idleMinutes, maxMessages }) {
            const r = await q(
                `select chat_id, n, first_id, last_id,
                        (last_at < now() - ($1::int * interval '1 minute')) as idle
                   from (select chat_id, count(*)::int as n, min(id) as first_id, max(id) as last_id, max(created_at) as last_at
                           from ariel.messages where processed_at is null group by chat_id) u
                  where last_at < now() - ($1::int * interval '1 minute') or n >= $2::int`,
                [idleMinutes, maxMessages]);
            return r.rows;
        },
        async segmentEnd(chatId, limit) {
            const r = await q(
                `select max(id) as last_id from (select id from ariel.messages
                  where chat_id = $1::bigint and processed_at is null order by id limit $2::int) x`, [chatId, limit]);
            return r.rows[0]?.last_id || null;
        },
        async chatInfo(chatId) {
            const r = await q(`select id, kind, wa_jid from ariel.chats where id = $1::bigint`, [chatId]);
            return r.rows[0] || null;
        },
        async segmentMessages({ chatId, fromId, toId }) {
            const r = await q(
                `select m.id, m.person_id, p.display_name as name, m.body, m.created_at
                   from ariel.messages m left join ariel.people p on p.id = m.person_id
                  where m.chat_id = $1::bigint and m.id between $2::bigint and $3::bigint and m.processed_at is null
                  order by m.id`,
                [chatId, fromId, toId]);
            return r.rows;
        },
        // Nothing worth keeping in this segment: stamp it processed without a summary.
        async markProcessed({ chatId, fromId, toId }) {
            await q(`update ariel.messages set processed_at = now()
                      where chat_id = $1::bigint and id between $2::bigint and $3::bigint and processed_at is null`,
                [chatId, fromId, toId]);
        },

        /**
         * The verification step, in ONE transaction: summary row, every memory, every embedding present,
         * then verified_at and the messages' processed_at. Any failure rolls everything back and nothing is
         * ever stamped, so the raw messages stay and the job retries.
         */
        async saveSegment({ chatId, fromId, toId, start, end, summary, memories }) {
            return tx(async (client) => {
                const qq = (t, p) => client.query(t, p);
                const t = await vschema(qq);
                const pg = createPgStore({ query: qq, tx: null });
                const sr = await qq(
                    `insert into ariel.summaries (chat_id, period, body, topics, open_threads, embedding)
                     values ($1::bigint, tstzrange($2::timestamptz, $3::timestamptz, '[]'), $4::text, $5::text[], $6::jsonb, $7::${t}.vector)
                     returning id`,
                    [chatId, start, end, summary.body, summary.topics, JSON.stringify(summary.openThreads), toVector(summary.vec)]);
                const summaryId = sr.rows[0].id;
                const memoryIds = [];
                for (const m of memories) memoryIds.push(await pg.insertMemory(m));

                const v = await qq(
                    `select (select count(*) from ariel.summaries where id = $1::bigint and embedding is not null)::int as s,
                            (select count(*) from ariel.memories where id = any($2::bigint[]) and embedding is not null)::int as m`,
                    [summaryId, memoryIds]);
                if (v.rows[0].s !== 1 || v.rows[0].m !== memoryIds.length) {
                    throw new Error(`verification failed (summary ${v.rows[0].s}/1, memories ${v.rows[0].m}/${memoryIds.length})`);
                }
                await qq(`update ariel.summaries set verified_at = now() where id = $1::bigint`, [summaryId]);
                await qq(`update ariel.messages set processed_at = now()
                           where chat_id = $1::bigint and id between $2::bigint and $3::bigint and processed_at is null`,
                    [chatId, fromId, toId]);
                return { summaryId, memoryIds };
            });
        },

        // ── consolidation ────────────────────────────────────────
        async memoryOwners() {
            const r = await q(
                `select scope, person_id, case when scope = 'group' then chat_id end as chat_id, count(*)::int as n
                   from ariel.memories where superseded_by is null
                  group by scope, person_id, case when scope = 'group' then chat_id end
                 having count(*) >= 2`);
            return r.rows;
        },
        async memoriesOf({ scope, personId, chatId }) {
            const r = await q(
                `select id, chat_id, kind, content, importance, visibility, confidence, last_used, created_at, embedding::text as emb
                   from ariel.memories
                  where superseded_by is null and scope = $1::text
                    and ($1::text <> 'person' or person_id = $2::bigint)
                    and ($1::text <> 'group'  or chat_id = $3::bigint)
                  order by id limit 800`,
                [scope, personId, chatId]);
            return r.rows.map((x) => ({ ...x, emb: x.emb ? JSON.parse(x.emb) : null }));
        },
        // New merged memory + old rows marked superseded (kept `keepDays` for rollback), atomically.
        async applyMerge({ scope, personId, chatId, originChatId, visibility, kind, content, importance, confidence, vec, oldIds, expiresAt, keepDays }) {
            return tx(async (client) => {
                const qq = (t, p) => client.query(t, p);
                const pg = createPgStore({ query: qq, tx: null });
                const id = await pg.insertMemory({
                    scope, personId, chatId: scope === 'group' ? chatId : scope === 'person' ? originChatId : null,
                    visibility, kind, content, importance, confidence, vec, expiresAt,
                });
                await qq(
                    `update ariel.memories set superseded_by = $2::bigint, expires_at = now() + ($3::int * interval '1 day'), updated_at = now()
                      where id = any($1::bigint[]) and id <> $2::bigint and superseded_by is null`,
                    [oldIds, id, keepDays]);
                return id;
            });
        },
        // Over the size limit after merging: drop only low-value rows (importance 1-2), worst first.
        async enforceLimit({ scope, personId, chatId, limit }) {
            const r = await q(
                `with ranked as (
                   select id, importance,
                          row_number() over (order by importance desc, coalesce(last_used, created_at) desc, id desc) as rn
                     from ariel.memories
                    where superseded_by is null and scope = $1::text
                      and ($1::text <> 'person' or person_id = $2::bigint)
                      and ($1::text <> 'group'  or chat_id = $3::bigint))
                 delete from ariel.memories m using ranked r
                  where m.id = r.id and r.rn > $4::int and r.importance <= 2
                    and not exists (select 1 from ariel.memories x where x.superseded_by = m.id)
                  returning m.id`,
                [scope, personId, chatId, limit]);
            return r.rows.length;
        },
        // Age-outs. The guards stop a delete from un-superseding an older version through the FK.
        async expireMemories() {
            const guard = `and not exists (select 1 from ariel.memories x where x.superseded_by = m.id and (x.expires_at is null or x.expires_at >= now()))`;
            const expired = await q(`delete from ariel.memories m where m.expires_at is not null and m.expires_at < now() ${guard} returning m.id`);
            const stale = await q(
                `delete from ariel.memories m
                  where m.superseded_by is null and m.importance = 2 and coalesce(m.last_used, m.created_at) < now() - interval '90 days'
                    and not exists (select 1 from ariel.memories x where x.superseded_by = m.id)
                  returning m.id`);
            const demoted = await q(
                `update ariel.memories set importance = 2, updated_at = now()
                  where superseded_by is null and importance = 3 and coalesce(last_used, created_at) < now() - interval '12 months' returning id`);
            return { expired: expired.rows.length, stale: stale.rows.length, demoted: demoted.rows.length };
        },

        // ── raw message cleanup ──────────────────────────────────
        // Only messages already verified (processed_at set), past retention, and never the newest `keepLatest` per chat.
        async cleanupCount({ retentionDays, keepLatest }) {
            const r = await q(
                `select count(*)::int as n from ariel.messages m
                  where m.processed_at is not null and m.processed_at < now() - ($1::int * interval '1 day')
                    and m.id not in (select id from (select id, row_number() over (partition by chat_id order by created_at desc, id desc) as rn
                                                       from ariel.messages) x where x.rn <= $2::int)`,
                [retentionDays, keepLatest]);
            return r.rows[0].n;
        },
        async cleanupDelete({ retentionDays, keepLatest, batch }) {
            const r = await q(
                `delete from ariel.messages where id in (
                   select m.id from ariel.messages m
                    where m.processed_at is not null and m.processed_at < now() - ($1::int * interval '1 day')
                      and m.id not in (select id from (select id, row_number() over (partition by chat_id order by created_at desc, id desc) as rn
                                                         from ariel.messages) x where x.rn <= $2::int)
                    order by m.id limit $3::int)
                 returning id`,
                [retentionDays, keepLatest, batch]);
            return r.rows.length;
        },
    };
}
