// bot/ariel/db.js — Ariel's own Postgres access (schema `ariel`, Supabase).
// Separate pool from the game's (lib/db.js) so chat load never starves commands.
import pg from 'pg';
export { toVector, renderSql } from './sqlutil.js';

let pool = null;

// Return bigint (int8) columns as JS numbers for this pool only.
// Fine for ids and counts at this scale; the rest of the bot is untouched.
const types = {
    getTypeParser(oid, format) {
        if (oid === 20) return (v) => Number(v);
        return pg.types.getTypeParser(oid, format);
    },
};

export function getPool() {
    if (pool) return pool;
    const url = process.env.ARIEL_DB_URL || process.env.SUPABASE_DB_URL;
    if (!url) throw new Error('SUPABASE_DB_URL is not set');
    pool = new pg.Pool({
        connectionString: url,
        ssl: { rejectUnauthorized: false },   // same as lib/db.js
        max: Number(process.env.ARIEL_DB_POOL_MAX || 5),
        types,
    });
    pool.on('error', (e) => console.error('[ariel-db] idle client error:', e.message));
    return pool;
}

export const query = (text, params) => getPool().query(text, params);

// Run fn(client) inside a transaction; rolls back on throw.
export async function tx(fn) {
    const client = await getPool().connect();
    try {
        await client.query('begin');
        const out = await fn(client);
        await client.query('commit');
        return out;
    } catch (e) {
        try { await client.query('rollback'); } catch { /* connection already gone */ }
        throw e;
    } finally {
        client.release();
    }
}

export async function getConfig(key, fallback = null) {
    const r = await query('select value from ariel.config where key = $1', [key]);
    return r.rows.length ? r.rows[0].value : fallback;
}

export async function setConfig(key, value) {
    await query(
        `insert into ariel.config (key, value) values ($1, $2::jsonb)
         on conflict (key) do update set value = excluded.value, updated_at = now()`,
        [key, JSON.stringify(value)],
    );
}

export async function logUsage(u) {
    await query(
        `insert into ariel.llm_usage (provider, model, role, tokens_in, tokens_out, latency_ms, ok, error, cost_usd)
         values ($1, $2, $3, $4, $5, $6, $7, $8, $9)`,
        [u.provider, u.model, u.role, u.tokensIn ?? null, u.tokensOut ?? null, u.latencyMs ?? null,
         !!u.ok, u.error ? String(u.error).slice(0, 500) : null, u.costUsd ?? null],
    );
}

// Tokens used today (Lagos day) by a role — feeds the daily budget.
export async function todayTokens(role) {
    const r = await query(
        `select coalesce(sum(coalesce(tokens_in, 0) + coalesce(tokens_out, 0)), 0)::bigint as n
           from ariel.llm_usage
          where role = $1 and ok
            and ts >= (date_trunc('day', now() at time zone 'Africa/Lagos') at time zone 'Africa/Lagos')`,
        [role],
    );
    return Number(r.rows[0].n);
}

export async function endPool() {
    if (pool) { await pool.end(); pool = null; }
}
