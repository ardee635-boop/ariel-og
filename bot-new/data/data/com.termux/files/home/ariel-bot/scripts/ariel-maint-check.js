#!/usr/bin/env node
// Checks the stage 5 SQL against your real database. ONE transaction, always rolled back: nothing is saved.
//   node --env-file=.env scripts/ariel-maint-check.js
import { createMaintStore } from '../bot/ariel/store/maint.js';
import { createPgStore } from '../bot/ariel/store/pg.js';

const db = await import('../bot/ariel/db.js');
const client = await db.getPool().connect();
const fails = [];
const check = (ok, what) => { console.log(`${ok ? '✓' : '✗'} ${what}`); if (!ok) fails.push(what); };

try {
    await client.query('begin');
    const q = (t, p) => client.query(t, p);
    const txFn = async (fn) => fn(client);            // already inside our outer transaction
    const maint = createMaintStore({ query: q, tx: txFn });
    const pg = createPgStore({ query: q, tx: txFn });
    const dim = (await q(`select a.atttypmod as d from pg_attribute a where a.attrelid = to_regclass('ariel.memories') and a.attname = 'embedding' and not a.attisdropped`)).rows[0].d;
    const vec = (i) => { const v = new Array(dim).fill(0); v[i % dim] = 1; return v; };
    const ins = async (sql, p) => (await q(sql, p)).rows[0].id;

    const a = await ins(`insert into ariel.people (display_name) values ('chk-A') returning id`);
    const chat = await ins(`insert into ariel.chats (kind, wa_jid) values ('dm', 'maintcheck-dm') returning id`);
    await q(`insert into ariel.chat_members (chat_id, person_id) values ($1, $2)`, [chat, a]);

    // messages: 5 old ones (processed 20 days ago) and 3 fresh unprocessed
    const ids = [];
    for (let i = 0; i < 8; i++) ids.push(await ins(`insert into ariel.messages (chat_id, person_id, wa_message_id, body, created_at) values ($1, $2, $3, $4, now() - ($5 || ' minutes')::interval) returning id`, [chat, a, `mc${i}`, `msg ${i}`, String((8 - i) * 60 * 24)]));
    await q(`update ariel.messages set processed_at = now() - interval '20 days' where id = any($1)`, [ids.slice(0, 5)]);

    // 1. a segment saves, verifies and stamps its messages — atomically
    const segIds = ids.slice(5);
    const before = (await q(`select count(*)::int n from ariel.messages where id = any($1) and processed_at is null`, [segIds])).rows[0].n;
    const saved = await maint.saveSegment({
        chatId: chat, fromId: segIds[0], toId: segIds[2], start: new Date(Date.now() - 3600e3), end: new Date(),
        summary: { body: 'chk summary', vec: vec(1), topics: ['t'], openThreads: [{ text: 'open' }] },
        memories: [{ scope: 'person', personId: a, chatId: chat, visibility: 'private', kind: 'fact', content: 'chk-A likes chk', importance: 2, confidence: 1, vec: vec(2), expiresAt: null }],
    });
    const after = (await q(`select count(*)::int n from ariel.messages where id = any($1) and processed_at is null`, [segIds])).rows[0].n;
    const sm = (await q(`select verified_at from ariel.summaries where id = $1`, [saved.summaryId])).rows[0];
    check(before === 3 && after === 0 && sm.verified_at, 'segment saved, verified and messages stamped together');
    check((await pg.latestSummaries(chat, 2)).length === 1, 'verified summary is readable for the context pack');

    // 2. cleanup: only processed + old messages go, never the newest `keepLatest`
    const n = await maint.cleanupCount({ retentionDays: 14, keepLatest: 6 });
    check(n === 2, `cleanup keeps the newest 6 (would delete 2, got ${n})`);
    const gone = await maint.cleanupDelete({ retentionDays: 14, keepLatest: 6, batch: 10 });
    check(gone === 2 && (await q(`select count(*)::int n from ariel.messages where chat_id = $1`, [chat])).rows[0].n === 6, 'cleanup deletes in a batch and leaves 6');
    check((await maint.cleanupCount({ retentionDays: 14, keepLatest: 0 })) === 3, 'fresh-processed messages are protected by the retention window (3 old remain eligible)');

    // 3. merge supersedes; forgetting the merged memory takes the old versions with it
    const m1 = await pg.insertMemory({ scope: 'person', personId: a, chatId: chat, visibility: 'private', kind: 'fact', content: 'chk-A likes jollof', importance: 2, confidence: 1, vec: vec(3), expiresAt: null });
    const m2 = await pg.insertMemory({ scope: 'person', personId: a, chatId: chat, visibility: 'private', kind: 'fact', content: 'chk-A loves jollof rice', importance: 2, confidence: 1, vec: vec(3), expiresAt: null });
    const merged = await maint.applyMerge({ scope: 'person', personId: a, chatId: null, originChatId: chat, visibility: 'private', kind: 'fact', content: 'chk-A loves jollof rice', importance: 2, confidence: 1, vec: vec(3), oldIds: [m1, m2], expiresAt: null, keepDays: 30 });
    const old = (await q(`select superseded_by from ariel.memories where id = any($1)`, [[m1, m2]])).rows;
    check(old.every((r) => r.superseded_by === merged), 'merge hides the old versions (superseded)');
    const del = await pg.deleteMemories({ ids: [merged], personId: a, chatId: chat });
    const left = (await q(`select count(*)::int n from ariel.memories where id = any($1)`, [[m1, m2, merged]])).rows[0].n;
    check(del.length === 1 && left === 0, 'forgetting a merged memory also removes its older versions (no resurrection)');

    // 4. the retention-day flag round-trips
    await maint.setFlag('chk.flag', { v: 1 });
    check((await maint.getFlag('chk.flag', null)).v === 1, 'config flags round-trip');

    // 5. job queue: unique key, claim, retry, dead
    const j1 = await maint.enqueue({ kind: 'chk', payload: {}, key: 'k1' });
    const j2 = await maint.enqueue({ kind: 'chk', payload: {}, key: 'k1' });
    check(j1 && !j2, 'a keyed job is not queued twice');
    const claimed = await maint.claimJob();
    check(claimed && claimed.id === j1 && claimed.attempts === 1, 'job is claimed once');
    await maint.failJob(j1, { error: 'x', dead: true });
    check((await maint.jobSummary()).dead.some((d) => d.id === j1), 'dead jobs are listed');
} catch (e) {
    console.error('✗ check crashed:', e.message);
    fails.push('crash');
} finally {
    await client.query('rollback').catch(() => {});
    client.release();
    await db.endPool();
}
console.log(fails.length ? `\n${fails.length} problem(s). Nothing was saved.` : '\n✓ stage 5 SQL checks passed (nothing was saved)');
process.exit(fails.length ? 1 : 0);
