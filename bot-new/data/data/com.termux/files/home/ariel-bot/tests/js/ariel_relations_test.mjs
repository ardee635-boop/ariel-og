// Fixed family relations + ranks reach the prompt.
// Run:  node --test tests/js/ariel_relations_test.mjs      (no database, no network)
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRelations, loadBase } from '../../bot/ariel/relations.js';
import { buildContext } from '../../bot/ariel/prompt.js';

const file = JSON.parse(readFileSync(new URL('../../config/relations.json', import.meta.url), 'utf8'));
const env = { KING_NUMBER: '2348000000001' };
const base = loadBase(file, env);
const phones = new Map([[1, ['2347073047260@s.whatsapp.net', '2347073047260']], [2, ['2348154056320']], [3, ['2348000000001']], [4, ['2349999999999']]]);
const store = () => ({ calls: 0, personPhones: async function (ids) { this.calls++; return new Map(ids.map((i) => [i, phones.get(i) || []])); } });

test('base: Ivy and Yuki are sisters, the King is the brother', () => {
    assert.deepEqual(base.map((b) => [b.name, b.relation]), [['Ivy', 'your sister'], ['Yuki', 'your sister'], ['the King', 'your brother']]);
});

test('people are matched by phone, strangers get nothing, plain ranks are ignored', async () => {
    const r = createRelations({ base, store: store(), rankOf: async (p) => (p === '2349999999999' ? 'guest' : p === '2348000000001' ? 'king' : 'baron') });
    const m = await r.describe({ personIds: [1, 2, 3, 4] });
    assert.equal(m.get(1).relation, 'your sister'); assert.equal(m.get(1).rank, 'baron');
    assert.equal(m.get(2).relation, 'your sister');
    assert.equal(m.get(3).relation, 'your brother'); assert.equal(m.get(3).rank, 'king');
    assert.equal(m.has(4), false);
});

test('a notable rank alone is still reported; results are cached', async () => {
    const s = store();
    const r = createRelations({ base, store: s, rankOf: async () => 'queen' });
    assert.equal((await r.describe({ personIds: [4] })).get(4).rank, 'queen');
    await r.describe({ personIds: [4] });
    assert.equal(s.calls, 1);
});

test('lookup or rank failures never throw', async () => {
    const bad = createRelations({ base, store: { personPhones: async () => { throw new Error('db down'); } } });
    assert.equal((await bad.describe({ personIds: [1] })).size, 0);
    const noRank = createRelations({ base, store: store(), rankOf: async () => { throw new Error('x'); } });
    assert.equal((await noRank.describe({ personIds: [1] })).get(1).relation, 'your sister');
});

test('the prompt shows family, rank and the "fixed facts" note', () => {
    const rows = [{ id: 1, wa_message_id: 'W1', person_id: 1, name: 'Ivy', body: 'hi', meta: {}, created_at: new Date() }];
    const social = { levels: new Map([[1, 'you barely know them']]), relations: [], family: new Map([[1, { relation: 'your sister', aka: ['Nessa'], rank: 'baron' }]]) };
    const { user } = buildContext({ core: { core: ['x'] }, rows, chat: { kind: 'dm', name: null }, triggerWaIds: ['W1'], now: new Date(), social });
    assert.match(user, /Ivy: your sister \(family, you know them well\); also goes by Nessa; rank baron in the bot/);
    assert.match(user, /fixed facts/);
    assert.doesNotMatch(user, /barely know/);
});
