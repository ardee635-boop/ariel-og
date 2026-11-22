#!/usr/bin/env node
// Checks the stage 7 SQL against your real database. ONE transaction, always rolled back.
//   node --env-file=.env scripts/ariel-initiative-check.js
import { createPgStore } from '../bot/ariel/store/pg.js';

const db = await import('../bot/ariel/db.js');
const client = await db.getPool().connect();
const fails = [];
const check = (ok, what) => { console.log(`${ok ? '✓' : '✗'} ${what}`); if (!ok) fails.push(what); };

try {
    await client.query('begin');
    const q = (t, p) => client.query(t, p);
    const store = createPgStore({ query: q, tx: async (fn) => fn(client) });
    const ins = async (sql, p) => (await q(sql, p)).rows[0].id;
    const a = await ins(`insert into ariel.people (display_name) values ('ini-A') returning id`);
    const dm = await ins(`insert into ariel.chats (kind, wa_jid, settings) values ('dm', 'inicheck-dm', '{"send_jid":"1@s.whatsapp.net"}') returning id`);
    const grp = await ins(`insert into ariel.chats (kind, wa_jid) values ('group', 'inicheck-grp') returning id`);
    await q(`insert into ariel.chat_members (chat_id, person_id) values ($1, $2), ($3, $2)`, [dm, a, grp]);

    const chats = await store.initiativeChats();
    check(chats.find((c) => c.id === dm)?.person_id === a, 'DM chats report their person');

    const id1 = await store.logInitiative({ chatId: dm, personId: a, kind: 'followup', reason: 'r', status: 'shadow', key: 'thread:1:0', text: 'hello' });
    check(await store.hasInitiativeKey('thread:1:0') && !(await store.hasInitiativeKey('nope')), 'follow-up keys stop repeats');
    const id2 = await store.logInitiative({ chatId: dm, personId: a, kind: 'checkin', reason: 'r', status: 'sent', key: null, text: 'hi' });
    check((await store.initiativeHistory(dm, 10)).length === 2, 'history lists shadow and sent');

    // a reply 10 minutes after she wrote counts as an answer in a DM
    await q(`update ariel.initiatives set sent_at = now() - interval '2 days' where id = $1`, [id2]);
    await q(`insert into ariel.messages (chat_id, person_id, wa_message_id, body, created_at) values ($1, $2, 'ic1', 'hey', now() - interval '2 days' + interval '10 minutes')`, [dm, a]);
    const un = await store.unresolvedInitiatives(180);
    check(un.some((r) => r.id === id2) && !un.some((r) => r.id === id1), 'only really-sent, unresolved ones are listed');
    const first = await store.firstResponseSince({ chatId: dm, personId: a, since: un.find((r) => r.id === id2).sent_at, dm: true });
    check(!!first, 'a DM reply counts as taking her up on it');
    await store.resolveInitiative(id2, { resolved: true, answered: true, latency_min: 10 });
    check((await store.unresolvedInitiatives(180)).length === 0, 'resolved ones drop out');

    // group: chatter that never addresses her is not "answered" when directOnly
    await q(`insert into ariel.messages (chat_id, person_id, wa_message_id, body, created_at) values ($1, $2, 'ic2', 'lol', now()), ($1, $2, 'ic3', 'true', now())`, [grp, a]);
    const since = new Date(Date.now() - 3600e3);
    check(!!(await store.firstResponseSince({ chatId: grp, personId: null, since, dm: false })), 'group picking up the conversation counts');
    check(!(await store.firstResponseSince({ chatId: grp, personId: null, since, dm: false, directOnly: true })), 'directOnly ignores chatter');
    await q(`insert into ariel.messages (chat_id, person_id, wa_message_id, body, meta) values ($1, $2, 'ic4', 'ok', '{"quoted_ariel": true}')`, [grp, a]);
    check(!!(await store.firstResponseSince({ chatId: grp, personId: null, since, dm: false, directOnly: true })), 'a quote of her counts as direct');

    // receptiveness, boundaries, activity
    await store.setReceptiveness(a, 0.42);
    check(Math.abs((await store.getReceptiveness(a)) - 0.42) < 1e-6, 'receptiveness saved');
    await store.setBoundary(a, 'no_initiative', true);
    check((await store.getBoundaries(a)).no_initiative === true, 'opt-out boundary saved');
    const act = await store.chatActivity(grp);
    check(act.h24 >= 3 && act.last_human, 'chat activity counts');
    check(Array.isArray(await store.openThreadsFor(grp)), 'open threads query runs');
    check((await store.recentInitiatives(5)).length >= 2, 'admin list query runs');
} catch (e) {
    console.error('✗ check crashed:', e.message);
    fails.push('crash');
} finally {
    await client.query('rollback').catch(() => {});
    client.release();
    await db.endPool();
}
console.log(fails.length ? `\n${fails.length} problem(s). Nothing was saved.` : '\n✓ stage 7 SQL checks passed (nothing was saved)');
process.exit(fails.length ? 1 : 0);
