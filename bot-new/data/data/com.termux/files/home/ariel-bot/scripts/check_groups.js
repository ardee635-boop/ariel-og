import pg from 'pg';
const pool = new pg.Pool({ connectionString: process.env.SUPABASE_DB_URL, ssl: { rejectUnauthorized: false } });
const res = await pool.query("SELECT value FROM bot_auth WHERE key = $1", ['allowed_groups']);
console.log(res.rows);
await pool.end();
