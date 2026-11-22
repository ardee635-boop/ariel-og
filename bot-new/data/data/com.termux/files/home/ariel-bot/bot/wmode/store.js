// bot/wmode/store.js — Postgres storage for Work Mode (tables in sql/003_work.sql).
// `db` is { query(text, params) } — pass ariel/db.js, or a transaction client in the check script.
// Every method returns plain camelCase objects; the manager never sees SQL rows.
export const TERMINAL = ['completed', 'failed', 'cancelled'];
const TERMINAL_SQL = `('completed','failed','cancelled')`;

const JSON_FIELDS = { plan: 'plan', completedSteps: 'completed_steps', pendingSteps: 'pending_steps', agent: 'agent' };
const PLAIN_FIELDS = { kind: 'kind', currentStep: 'current_step', provider: 'provider', model: 'model',
    result: 'result', error: 'error', pauseReason: 'pause_reason', tokenBudget: 'token_budget' };

export function mapTask(r) {
    if (!r) return null;
    return {
        id: Number(r.id), userId: r.user_id, chatJid: r.chat_jid, sourceMsgId: r.source_msg_id,
        description: r.description, kind: r.kind, status: r.status,
        plan: r.plan || [], currentStep: r.current_step, completedSteps: r.completed_steps || [], pendingSteps: r.pending_steps || [],
        agent: r.agent || {}, provider: r.provider, model: r.model, tokensIn: Number(r.tokens_in || 0), tokensOut: Number(r.tokens_out || 0),
        tokenBudget: r.token_budget, result: r.result, error: r.error, pauseReason: r.pause_reason,
        lockedBy: r.locked_by, leaseUntil: r.lease_until, createdAt: r.created_at, startedAt: r.started_at,
        completedAt: r.completed_at, updatedAt: r.updated_at,
    };
}

export function capTurns(turns, maxTurns, maxChars) {
    let out = turns.slice(-maxTurns);
    const size = () => out.reduce((n, t) => n + String(t.text || '').length, 0);
    while (out.length > 1 && size() > maxChars) out = out.slice(1);
    return out.map((t) => ({ ...t, text: String(t.text || '').slice(0, maxChars) }));
}

export function createWorkStore(db) {
    const q = (t, p) => db.query(t, p);

    return {
        kind: 'pg',

        // ── mode ────────────────────────────────────────────
        async getMode(chatJid) {
            const r = await q('select active from ariel.work_mode where chat_jid = $1', [chatJid]);
            return r.rows.length ? r.rows[0].active === true : false;
        },
        async listActiveChats() {
            const r = await q('select chat_jid from ariel.work_mode where active');
            return r.rows.map((x) => x.chat_jid);
        },
        async setMode(chatJid, active, userId = null) {
            await q(
                `insert into ariel.work_mode (chat_jid, active, activated_by, activated_at, updated_at)
                 values ($1, $2, $3, case when $2 then now() end, now())
                 on conflict (chat_jid) do update
                   set active = excluded.active,
                       activated_by = coalesce(excluded.activated_by, ariel.work_mode.activated_by),
                       activated_at = case when excluded.active then now() else ariel.work_mode.activated_at end,
                       updated_at = now()`,
                [chatJid, active === true, userId]);
        },

        // ── session (temporary context + notes) ─────────────
        async ensureSession(chatJid, userId) {
            await q(`insert into ariel.work_sessions (chat_jid, user_id) values ($1, $2) on conflict (chat_jid) do nothing`, [chatJid, userId]);
        },
        async getRecent(chatJid) {
            const r = await q('select recent from ariel.work_sessions where chat_jid = $1', [chatJid]);
            return r.rows[0]?.recent || [];
        },
        async appendTurns(chatJid, userId, turns, maxTurns, maxChars) {
            await this.ensureSession(chatJid, userId);
            const cur = capTurns([...(await this.getRecent(chatJid)), ...turns], maxTurns, maxChars);
            await q('update ariel.work_sessions set recent = $2::jsonb, updated_at = now() where chat_jid = $1', [chatJid, JSON.stringify(cur)]);
        },

        // ── tasks ───────────────────────────────────────────
        async createTask({ userId, chatJid, sourceMsgId = null, description, kind = 'simple', tokenBudget = null }) {
            const ins = await q(
                `insert into ariel.work_tasks (user_id, chat_jid, source_msg_id, description, kind, token_budget)
                 values ($1, $2, $3, $4, $5, $6)
                 on conflict (chat_jid, source_msg_id) where source_msg_id is not null do nothing
                 returning *`,
                [userId, chatJid, sourceMsgId, description, kind, tokenBudget]);
            if (ins.rows.length) return { task: mapTask(ins.rows[0]), created: true };
            const ex = await q('select * from ariel.work_tasks where chat_jid = $1 and source_msg_id = $2', [chatJid, sourceMsgId]);
            return { task: mapTask(ex.rows[0]), created: false };
        },
        async getTask(id) {
            const r = await q('select * from ariel.work_tasks where id = $1', [id]);
            return mapTask(r.rows[0]);
        },
        async listTasks(chatJid, { statuses = null, limit = 10 } = {}) {
            const r = statuses
                ? await q('select * from ariel.work_tasks where chat_jid = $1 and status = any($2::text[]) order by id desc limit $3', [chatJid, statuses, limit])
                : await q('select * from ariel.work_tasks where chat_jid = $1 order by id desc limit $2', [chatJid, limit]);
            return r.rows.map(mapTask);
        },
        // Only the worker that wins this UPDATE may run the task. A second worker, or a redelivered
        // message after a restart, gets null — that is the duplicate-execution guard.
        async claimTask(id, owner, leaseMs) {
            const r = await q(
                `update ariel.work_tasks
                    set locked_by = $2, lease_until = now() + make_interval(secs => $3::double precision / 1000),
                        status = case when status = 'pending' then 'running' else status end,
                        started_at = coalesce(started_at, now()), pause_reason = null, updated_at = now()
                  where id = $1 and status in ('pending','running','planning')
                    and (locked_by is null or lease_until is null or lease_until < now())
                  returning *`,
                [id, owner, leaseMs]);
            return mapTask(r.rows[0]);
        },
        async heartbeat(id, owner, leaseMs) {
            const r = await q(
                `update ariel.work_tasks set lease_until = now() + make_interval(secs => $3::double precision / 1000)
                  where id = $1 and locked_by = $2 returning id`, [id, owner, leaseMs]);
            return r.rows.length > 0;
        },
        async releaseLock(id, owner) {
            await q('update ariel.work_tasks set locked_by = null, lease_until = null where id = $1 and locked_by = $2', [id, owner]);
        },
        // Returns the updated task, or null when the transition was refused (task already finished,
        // or its current status is not in `from`). Callers treat null as "someone else got there first".
        async setStatus(id, status, extra = {}, { from = null } = {}) {
            const sets = ['status = $2', 'updated_at = now()'];
            const params = [id, status];
            const add = (col, val, cast = '') => { params.push(val); sets.push(`${col} = $${params.length}${cast}`); };
            if (extra.result !== undefined) add('result', extra.result);
            if (extra.error !== undefined) add('error', extra.error);
            if (extra.pauseReason !== undefined) add('pause_reason', extra.pauseReason);
            if (TERMINAL.includes(status)) sets.push('completed_at = now()');
            if (status === 'running') sets.push('started_at = coalesce(started_at, now())');
            if (status !== 'running' && status !== 'planning') sets.push('locked_by = null', 'lease_until = null');
            let where = `id = $1 and status not in ${TERMINAL_SQL}`;
            if (from) { params.push(from); where += ` and status = any($${params.length}::text[])`; }
            const r = await q(`update ariel.work_tasks set ${sets.join(', ')} where ${where} returning *`, params);
            return mapTask(r.rows[0]);
        },
        async updateTask(id, patch) {
            const sets = ['updated_at = now()']; const params = [id];
            for (const [k, col] of Object.entries(PLAIN_FIELDS)) if (patch[k] !== undefined) { params.push(patch[k]); sets.push(`${col} = $${params.length}`); }
            for (const [k, col] of Object.entries(JSON_FIELDS)) if (patch[k] !== undefined) { params.push(JSON.stringify(patch[k])); sets.push(`${col} = $${params.length}::jsonb`); }
            const r = await q(`update ariel.work_tasks set ${sets.join(', ')} where id = $1 returning *`, params);
            return mapTask(r.rows[0]);
        },
        async addUsage(id, tokensIn, tokensOut, provider, model) {
            const r = await q(
                `update ariel.work_tasks set tokens_in = tokens_in + $2, tokens_out = tokens_out + $3,
                        provider = $4, model = $5, updated_at = now()
                  where id = $1 returning *`, [id, tokensIn || 0, tokensOut || 0, provider, model]);
            return mapTask(r.rows[0]);
        },
        // Tasks that look abandoned: runnable status, nobody holds a live lease.
        async findAbandoned(limit = 20) {
            const r = await q(
                `select t.* from ariel.work_tasks t
                   join ariel.work_mode m on m.chat_jid = t.chat_jid and m.active
                  where t.status in ('pending','running','planning')
                    and (t.locked_by is null or t.lease_until is null or t.lease_until < now())
                  order by t.id limit $1`, [limit]);
            return r.rows.map(mapTask);
        },
        // Work Mode turned off in a chat: park whatever was in flight there.
        async pauseActiveInChat(chatJid, reason) {
            const r = await q(
                `update ariel.work_tasks set status = 'paused', pause_reason = $2, locked_by = null, lease_until = null, updated_at = now()
                  where chat_jid = $1 and status in ('pending','running','planning') returning id`, [chatJid, reason]);
            return r.rows.map((x) => Number(x.id));
        },

        // ── events ──────────────────────────────────────────
        async addEvent(taskId, kind, data = {}) {
            await q('insert into ariel.work_events (task_id, kind, data) values ($1, $2, $3::jsonb)', [taskId, kind, JSON.stringify(data)]);
        },
        async listEvents(taskId, limit = 50) {
            const r = await q('select ts, kind, data from ariel.work_events where task_id = $1 order by id desc limit $2', [taskId, limit]);
            return r.rows.reverse().map((x) => ({ ts: x.ts, kind: x.kind, data: x.data }));
        },
        async pruneEvents(days) {
            const r = await q(`delete from ariel.work_events where ts < now() - make_interval(days => $1::int)`, [days]);
            return r.rowCount || 0;
        },

        // ── small key/value (provider health survives restarts) ──
        async getConfig(key, fallback = null) {
            const r = await q('select value from ariel.config where key = $1', [key]);
            return r.rows.length ? r.rows[0].value : fallback;
        },
        async setConfig(key, value) {
            await q(`insert into ariel.config (key, value) values ($1, $2::jsonb)
                     on conflict (key) do update set value = excluded.value, updated_at = now()`, [key, JSON.stringify(value)]);
        },
    };
}
