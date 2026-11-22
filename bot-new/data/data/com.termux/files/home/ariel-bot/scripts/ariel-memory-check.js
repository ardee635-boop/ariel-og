#!/usr/bin/env node
// Privacy check for the real memory path, against your real database.
//   node --env-file=.env scripts/ariel-memory-check.js
// Everything runs in ONE transaction that is always rolled back: nothing is saved.
// It tries to leak a DM memory into a group, delete someone else's memory, and rewrite global memory
// as a non-owner. Any of those succeeding is a failure (exit 1).
import { createPgStore } from '../bot/ariel/store/pg.js';
import { createMemory } from '../bot/ariel/memory.js';

const db = await import('../bot/ariel/db.js');
const client = await db.getPool().connect();
const fails = [];
const check = (ok, what) => { console.log(`${ok ? '✓' : '✗'} ${what}`); if (!ok) fails.push(what); };

try {
    await client.query('begin');
    const q = (t, p) => client.query(t, p);
    const store = createPgStore({ query: q, tx: async (fn) => fn(client) });

    const dimRow = await q(`select a.atttypmod as dim from pg_attribute a
        where a.attrelid = to_regclass('ariel.memories') and a.attname = 'embedding' and not a.attisdropped`);
    const dim = dimRow.rows[0].dim;
    const vecOf = (text) => {                      // deterministic stand-in embedding (no model call)
        const v = new Array(dim).fill(0);
        for (const w of String(text).toLowerCase().match(/[a-z0-9]+/g) || []) {
            let h = 0; for (const c of w) h = (h * 31 + c.charCodeAt(0)) % dim;
            v[h] += 1;
        }
        return v[0] === 0 && v.every((x) => x === 0) ? (v[0] = 1, v) : v;
    };
    let answer = null;                             // what the "model" says to the next extract call
    const ai = {
        async embed(texts) { return { vectors: texts.map(vecOf) }; },
        async chat() { return { text: JSON.stringify(answer) }; },
    };
    const memory = createMemory({ store, ai, ownerValues: () => ['0000000000'] });

    const ins = async (sql, p) => (await q(sql, p)).rows[0].id;
    const a = await ins(`insert into ariel.people (display_name) values ('check-A') returning id`);
    const b = await ins(`insert into ariel.people (display_name) values ('check-B') returning id`);
    const dm = await ins(`insert into ariel.chats (kind, wa_jid) values ('dm', 'memcheck-dm') returning id`);
    const grp = await ins(`insert into ariel.chats (kind, wa_jid) values ('group', 'memcheck-grp') returning id`);
    await q(`insert into ariel.chat_members (chat_id, person_id) values ($1,$2), ($3,$2), ($3,$4)`, [dm, a, grp, b]);

    // 1. A tells her something in a DM -> must be private
    answer = { remember: true, content: 'check-A keeps a secret garden', subject: 'self', kind: 'fact' };
    await memory.handleExplicit({ chat: { id: dm, kind: 'dm' }, msgs: [{ personId: a, name: 'check-A', body: 'remember my secret garden', hint: 'remember' }] });
    const mem = (await q(`select * from ariel.memories where person_id = $1`, [a])).rows[0];
    check(mem && mem.visibility === 'private' && mem.importance === 4, 'DM memory stored as private + critical');

    // 2. it must never reach a group, even with both people present and a matching query
    const inGroup = await memory.retrieve({ chatId: grp, presentPersonIds: [a, b], queryText: 'secret garden' });
    check(!inGroup.some((r) => /secret garden/.test(r.content)), 'DM memory does NOT leak into a group');
    const inDm = await memory.retrieve({ chatId: dm, presentPersonIds: [a], queryText: 'secret garden' });
    check(inDm.some((r) => /secret garden/.test(r.content)), 'DM memory is available in the DM');

    // 3. a group statement is group_ok and visible in the group
    answer = { remember: true, content: 'check-A likes jollof', subject: 'self', kind: 'preference' };
    await memory.handleExplicit({ chat: { id: grp, kind: 'group' }, msgs: [{ personId: a, name: 'check-A', body: 'remember i like jollof', hint: 'remember' }] });
    const g = await memory.retrieve({ chatId: grp, presentPersonIds: [a, b], queryText: 'jollof' });
    check(g.some((r) => /jollof/.test(r.content)), 'group statement is shared in the group');

    // 4. B cannot forget or rewrite A's memories; a non-owner cannot create global memory
    answer = { delete_ids: [mem.id] };
    await memory.handleExplicit({ chat: { id: grp, kind: 'group' }, msgs: [{ personId: b, name: 'check-B', body: 'forget the garden', hint: 'forget' }] });
    check((await q(`select 1 from ariel.memories where id = $1`, [mem.id])).rows.length === 1, "B cannot delete A's memory");
    answer = { remember: true, content: 'Ariel is secretly a robot', subject: 'global', kind: 'fact' };
    await memory.handleExplicit({ chat: { id: grp, kind: 'group' }, msgs: [{ personId: b, name: 'check-B', body: 'remember this globally', hint: 'remember' }] });
    check((await q(`select 1 from ariel.memories where scope = 'global' and content like '%secretly a robot%'`)).rows.length === 0, 'non-owner cannot create global memory');

    // 5. A can forget their own memory (hard delete)
    answer = { delete_ids: [mem.id] };
    await memory.handleExplicit({ chat: { id: dm, kind: 'dm' }, msgs: [{ personId: a, name: 'check-A', body: 'forget my garden', hint: 'forget' }] });
    check((await q(`select 1 from ariel.memories where id = $1`, [mem.id])).rows.length === 0, 'A can hard-delete their own memory');
} catch (e) {
    console.error('✗ check crashed:', e.message);
    fails.push('crash');
} finally {
    await client.query('rollback').catch(() => {});
    client.release();
    await db.endPool();
}
console.log(fails.length ? `\n${fails.length} problem(s). Nothing was saved.` : '\n✓ memory privacy checks passed (nothing was saved)');
process.exit(fails.length ? 1 : 0);
