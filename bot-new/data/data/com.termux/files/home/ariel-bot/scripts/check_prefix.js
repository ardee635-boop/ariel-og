import pg from 'pg';
const pool = new pg.Pool({ connectionString: process.env.SUPABASE_DB_URL, ssl: { rejectUnauthorized: false } });
const res = await pool.query(
  "SELECT group_jid, prefix FROM group_settings WHERE group_jid = $1",
  ['120363423288562636@g.us']
);
console.log(res.rows);
await pool.end();
