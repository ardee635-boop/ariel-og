#!/usr/bin/env node
// Apply Ariel's schema to Supabase.
//   node --env-file=.env scripts/ariel-migrate.js [--dim 768] [--dry-run] [--check]
//
//   (none)     apply every bot/ariel/sql/NNN_*.sql whose content changed (files are idempotent)
//   --dim N    vector size (default 768 or ARIEL_EMBED_DIM). Fixed once the embedding model is chosen.
//   --dry-run  print what would run; no database connection
//   --check    run sql/check.sql (privacy rules) in a transaction that is always rolled back
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import { renderSql, checksum, DEFAULT_EMBED_DIM } from '../bot/ariel/sqlutil.js';

const SQL_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', 'bot', 'ariel', 'sql');
const args = process.argv.slice(2);
const flag = (n) => args.includes(`--${n}`);
const opt = (n, d) => { const i = args.indexOf(`--${n}`); return i >= 0 ? args[i + 1] : d; };

const dim = Number(opt('dim', process.env.ARIEL_EMBED_DIM || DEFAULT_EMBED_DIM));
const files = fs.readdirSync(SQL_DIR).filter((f) => /^\d+_.*\.sql$/.test(f)).sort();

if (flag('dry-run')) {
    for (const f of files) {
        const sql = renderSql(fs.readFileSync(path.join(SQL_DIR, f), 'utf8'), { dim });
        console.log(`${f}: ${sql.length} chars, vector(${dim}), checksum ${checksum(sql)}`);
    }
    process.exit(0);
}

const db = await import('../bot/ariel/db.js');

try {
    if (flag('check')) {
        const sql = fs.readFileSync(path.join(SQL_DIR, 'check.sql'), 'utf8');
        const client = await db.getPool().connect();
        try {
            await client.query('begin');
            client.on('notice', (n) => console.log('[db]', n.message));
            await client.query(sql);
            console.log('✓ privacy checks passed (nothing was saved)');
        } finally {
            await client.query('rollback').catch(() => {});
            client.release();
        }
    } else {
        await db.tx(async (c) => {
            await c.query('create schema if not exists ariel');
            await c.query(`create table if not exists ariel._migrations (
                name text primary key, checksum text not null, embed_dim integer, applied_at timestamptz not null default now())`);

            // Vector size is fixed once tables exist: changing it means re-embedding.
            const cur = await c.query(`
                select a.atttypmod as dim from pg_attribute a
                 where a.attrelid = to_regclass('ariel.memories') and a.attname = 'embedding' and not a.attisdropped`);
            if (cur.rows.length && cur.rows[0].dim > 0 && cur.rows[0].dim !== dim) {
                throw new Error(`ariel.memories.embedding is vector(${cur.rows[0].dim}) but you asked for ${dim}. `
                    + 'Changing the size means re-embedding everything; do that deliberately, not through this script.');
            }

            for (const f of files) {
                const sql = renderSql(fs.readFileSync(path.join(SQL_DIR, f), 'utf8'), { dim });
                const sum = checksum(sql);
                const done = await c.query('select checksum from ariel._migrations where name = $1', [f]);
                if (done.rows[0]?.checksum === sum) { console.log(`= ${f} unchanged`); continue; }
                console.log(`→ applying ${f} (vector(${dim}))`);
                await c.query(sql);
                await c.query(
                    `insert into ariel._migrations (name, checksum, embed_dim) values ($1, $2, $3)
                     on conflict (name) do update set checksum = excluded.checksum, embed_dim = excluded.embed_dim, applied_at = now()`,
                    [f, sum, dim]);
            }
        });
        console.log('✓ migration done. Next: node --env-file=.env scripts/ariel-migrate.js --check');
    }
} catch (e) {
    console.error('✗', e.message);
    process.exitCode = 1;
} finally {
    await db.endPool();
}
