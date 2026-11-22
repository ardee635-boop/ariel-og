#!/usr/bin/env node
// Checks the stage 6 SQL against your real database. ONE transaction, always rolled back.
//   node --env-file=.env scripts/ariel-social-check.js
import { createPgStore } from '../bot/ariel/store/pg.js';
import { createSocial } from '../bot/ariel/social.js';

const db = await import('../bot/ariel/db.js');
const client = await db.getPool().connect();
const fails = [];
const check = (ok, what) => { console.log(`${ok ? '✓' : '✗'} ${what}`); if (!ok) fails.push(what); };

try {
    await client.query('begin');
    const q = (t, p) => client.query(t, p);
    const store = createPgStore({ query: q, tx: async (fn) => fn(client) });
    const social = createSocial({ store });
    const ins = async (sql, p) => (await q(sql, p)).rows[0].id;
    const a = await ins(`insert into ariel.people (display_name) values ('soc-A') returning id`);
    const b = await ins(`insert into ariel.people (display_name) values ('soc-B') returning id`);
    const chat = await ins(`insert into ariel.chats (kind, wa_jid, settings) values ('group', 'soccheck-grp', '{"chat_on": true}') returning id`);

    // familiarity: two interactions on the same day = one day, two interactions
    await social.recordInteraction(a, 1);
    await social.recordInteraction(a, 1);
    const st = (await store.getPersonStates([a])).get(a);
    check(st && st.rapport.days.length === 1 && st.rapport.n === 2 && st.familiarity <= 0.25, 'interactions saved; one day is not familiarity');

    // relationships: the pair is stored with person_a < person_b whatever order we pass; label shows after 3 signals
    const hi = Math.max(a, b); const lo = Math.min(a, b);
    await social.addSignals(chat, [{ a: hi, b: lo, kind: 'teasing', note: 'banter' }]);
    check((await social.describe({ chatId: chat, personIds: [a, b] })).relations.length === 0, 'one signal does not make a label');
    await social.addSignals(chat, [{ a: lo, b: hi, kind: 'teasing' }, { a: hi, b: lo, kind: 'teasing' }]);
    const rel = (await social.describe({ chatId: chat, personIds: [a, b] })).relations;
    check(rel.length === 1 && rel[0].kind === 'teasing' && rel[0].a === lo && rel[0].b === hi, 'three consistent signals make a label (stored person_a < person_b)');
    await social.addSignals(chat, [{ a: lo, b: hi, kind: 'rival' }]);
    check((await social.describe({ chatId: chat, personIds: [a, b] })).relations[0]?.kind === 'teasing', 'one contradicting signal does not flip it');

    // per-chat setting merges without wiping others
    check(await store.setChatSetting('soccheck-grp', 'involvement', 12), 'per-chat setting saved');
    const sset = await store.chatSettings(chat);
    check(sset.involvement === 12 && sset.chat_on === true, 'setting merged, chat_on untouched');
    check((await store.getArielState()) !== undefined, 'her state row is readable');
} catch (e) {
    console.error('✗ check crashed:', e.message);
    fails.push('crash');
} finally {
    await client.query('rollback').catch(() => {});
    client.release();
    await db.endPool();
}
console.log(fails.length ? `\n${fails.length} problem(s). Nothing was saved.` : '\n✓ stage 6 SQL checks passed (nothing was saved)');
process.exit(fails.length ? 1 : 0);
