#!/usr/bin/env node
// Checks the stage 8 SQL against your real database. ONE transaction, always rolled back: nothing is saved.
//   node --env-file=.env scripts/ariel-self-check.js
import { createSelfStore } from '../bot/ariel/store/self.js';
import { createFeedback } from '../bot/ariel/feedback.js';
import { createReflection } from '../bot/ariel/reflect.js';
import { createPersona } from '../bot/ariel/persona.js';
import { withDefaults } from '../bot/ariel/config.js';

const db = await import('../bot/ariel/db.js');
const client = await db.getPool().connect();
const fails = [];
const check = (ok, what) => { console.log(`${ok ? '✓' : '✗'} ${what}`); if (!ok) fails.push(what); };

try {
    await client.query('begin');
    const q = (t, p) => client.query(t, p);
    const self = createSelfStore({ query: q, tx: async (fn) => fn(client) });     // already inside our outer transaction
    const cfg = withDefaults();
    const ins = async (sql, p) => (await q(sql, p)).rows[0].id;

    // config + state
    await self.setConfig('selfcheck.flag', { a: 1 });
    check((await self.getConfig('selfcheck.flag')).a === 1 && (await self.getConfig('selfcheck.none', 'fb')) === 'fb', 'config reads and writes');
    await self.mergeState({ interests: ['lofi'] });
    await self.mergeState({ mood: 0.4 });
    const st = await self.getState();
    check(st.mood === 0.4 && st.interests?.[0] === 'lofi', 'state merges without wiping other keys');

    // identity + log
    await self.upsertIdentity({ key: 'interest:selfcheck', value: { kind: 'interest', text: 'checks', keyword: 'check', evidence: [1, 2, 3] }, evidenceCount: 3 });
    await self.upsertIdentity({ key: 'interest:selfcheck', value: { kind: 'interest', text: 'checks twice', keyword: 'check', evidence: [1, 2, 3, 4] }, evidenceCount: 4 });
    await self.appendLog({ at: new Date().toISOString(), type: 'identity', status: 'applied', text: 'x' });
    await self.appendLog({ at: new Date().toISOString(), type: 'style', status: 'applied', text: 'y' });
    const items = await self.listIdentity();
    const mine = items.find((i) => i.key === 'interest:selfcheck');
    check(mine && mine.version === 2 && mine.evidence_count === 4, 'identity upsert bumps the version');
    check(!items.some((i) => i.key.startsWith('_')), 'the change log never shows up as a trait');
    check((await self.getLog()).length === 2, 'change log appends');
    check(await self.deleteIdentity('interest:selfcheck') && !(await self.deleteIdentity('_log')), 'identity delete works and refuses the log row');

    // feedback
    const pid = async (n) => ins(`insert into ariel.people (display_name) values ($1) returning id`, [n]);
    const A = await pid('self-A'); const B = await pid('self-B'); const C = await pid('self-C');
    check(await self.addFeedback({ personId: A, kind: 'robotic', text: 'you sound robotic' }), 'feedback saved');
    check(!(await self.addFeedback({ personId: A, kind: 'robotic', text: 'again' })), 'same person, same kind, same day counts once');
    await self.addFeedback({ personId: B, kind: 'robotic', text: 'robotic' });
    await self.addFeedback({ personId: C, kind: 'robotic', text: 'robotic' });
    check((await self.feedbackSince(new Date(Date.now() - 7 * 86400_000))).filter((f) => [A, B, C].includes(f.person_id)).length === 3, 'feedback read back');

    // the daily review, end to end
    const fb = createFeedback({ self, cfg });
    const before = (await fb.getStyle()).values.expressiveness;
    const r = await fb.review();
    const after = (await fb.getStyle()).values.expressiveness;
    check(r.moves.length === 1 && after === Math.min(3, before + 0.5), `3 remarks from 3 people moved expressiveness ${before} -> ${after}`);
    check((await fb.review()).moves.length === 0, 'the same remarks are not used twice');

    // what reflection reads
    {
        const chat = await ins(`insert into ariel.chats (kind, wa_jid) values ('dm', 'selfcheck-dm') returning id`);
        await q(`insert into ariel.summaries (chat_id, period, body, topics, verified_at)
                 values ($1, tstzrange(now() - interval '2 hours', now() - interval '1 hour'), 'They talked about lofi.', '{music}', now())`, [chat]);
        const s = await self.recentSummaries({ days: 28, limit: 10 });
        check(s.some((x) => x.body === 'They talked about lofi.' && x.kind === 'dm'), 'recent summaries (with the chat kind) are readable');
    }
    check((await self.personNames()).includes('self-A'), 'people names are readable (used to keep names out of her tastes)');

    // reflection: a fake model, real database
    const sums = await self.recentSummaries({ days: 28, limit: 60 });
    if (sums.length >= 3 && new Set(sums.slice(0, 3).map((x) => x.chat_id)).size >= 2) {
        const ids = sums.slice(0, 3).map((x) => `S${x.id}`);
        const ai = { chat: async () => ({ text: JSON.stringify({ changes: [{ op: 'add', kind: 'interest', text: 'She keeps coming back to checking things.', keyword: 'selfcheck topic', episodes: ids }] }) }) };
        const refl = createReflection({ self, ai, cfg });
        await self.setConfig('reflect.live', true);
        const out = await refl.run();
        check(out.applied.length === 1 && (await self.getState()).interests?.includes('selfcheck topic'), 'reflection applied one change and her interests follow');
    } else console.log(`· skipped the reflection check (it needs 3 recent summaries from at least 2 chats; you have ${sums.length})`);

    // what the prompt will read
    const persona = createPersona({ self, cfg });
    const p = await persona.get();
    check(/How you are lately/.test(p.text) && p.limits.maxEmoji >= 0, 'her prompt block builds from the database');
} catch (e) {
    console.error('✗ check crashed:', e.message);
    fails.push('crash');
} finally {
    await client.query('rollback').catch(() => {});
    client.release();
    await db.endPool();
}
console.log(fails.length ? `\n${fails.length} problem(s). Nothing was saved.` : '\n✓ stage 8 SQL checks passed (nothing was saved)');
process.exit(fails.length ? 1 : 0);
