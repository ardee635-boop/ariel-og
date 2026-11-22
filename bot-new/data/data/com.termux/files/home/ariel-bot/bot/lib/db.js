// lib/db.js  (split out of index.js)
import pg from 'pg';
import { setupCommandsTables } from '../commands.js';
import { botState } from './state.js';
import { err, log } from './log.js';

const { Client } = pg;

export async function _getDB() {
    if (botState._pgPool) return botState._pgPool;
    botState._pgPool = new pg.Pool({
        connectionString: process.env.SUPABASE_DB_URL,
        ssl: { rejectUnauthorized: false },
    });
    // Don't let a single bad connection crash the whole process.
    botState._pgPool.on('error', (e) => {
        err('🔐', `pg pool idle client error: ${e.message}`);
    });

    // Guard one-time setup (table creation) so concurrent early callers
    // don't race to run it multiple times; later callers just reuse the pool.
    if (!botState._pgReady) {
        botState._pgReady = (async () => {
            await botState._pgPool.query(`
                CREATE TABLE IF NOT EXISTS bot_auth (
                    key   TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
            `);
            await botState._pgPool.query(`
                CREATE TABLE IF NOT EXISTS users (
                    phone         TEXT PRIMARY KEY,
                    username      TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
                )
            `);
            await setupCommandsTables(botState._pgPool);
            log('🔐', 'Supabase auth DB connected.');
        })();
    }
    await botState._pgReady;
    return botState._pgPool;
}

