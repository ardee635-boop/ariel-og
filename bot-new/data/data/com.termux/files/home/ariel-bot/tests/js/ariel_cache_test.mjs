// Chat history cache tests. Run:  node --test tests/js/ariel_cache_test.mjs   (no database, no network)
import test from 'node:test';
import assert from 'node:assert/strict';
import { createMemStore } from '../../bot/ariel/store/mem.js';
import { withChatCache } from '../../bot/ariel/store/cached.js';

async function setup(opts = {}) {
    const mem = createMemStore();
    let t = 1_000_000;
    const clock = { now: () => t, tick: (ms) => { t += ms; } };
    const store = withChatCache(mem, { now: clock.now, ...opts });
    const personId = await mem.createPerson('Ada');
    const chatId = await mem.ensureChat({ key: 'c1', kind: 'dm', settings: {} });
    let n = 0;
    const say = (body) => store.recordMessage({ chatId, personId, waId: `w${++n}`, replyTo: null, body, meta: {}, ts: new Date(clock.now() + n), displayName: 'Ada' });
    return { mem, store, chatId, personId, say, clock };
}

test('second read comes from memory (no extra database call)', async () => {
    const { mem, store, chatId, say } = await setup();
    await say('hi'); await say('there');
    const a = await store.recentMessages(chatId, 80);
    const calls = mem.state.calls;
    const b = await store.recentMessages(chatId, 80);
    assert.equal(mem.state.calls, calls);
    assert.deepEqual(b.map((r) => r.body), ['hi', 'there']);
    assert.deepEqual(a, b);
    assert.equal(store.cache.counters.hits, 1);
});

test('smaller limit is served from the bigger cached read; bigger limit refetches', async () => {
    const { mem, store, chatId, say } = await setup();
    for (let i = 0; i < 5; i++) await say(`m${i}`);
    await store.recentMessages(chatId, 3);
    const calls = mem.state.calls;
    assert.deepEqual((await store.recentMessages(chatId, 2)).map((r) => r.body), ['m3', 'm4']);
    assert.equal(mem.state.calls, calls);
    assert.equal((await store.recentMessages(chatId, 5)).length, 5);   // needs more than was fetched
    assert.ok(mem.state.calls > calls);
    const c2 = mem.state.calls;
    assert.equal((await store.recentMessages(chatId, 50)).length, 5);  // asked for 50, got 5: the chat is just short
    const c3 = mem.state.calls;
    assert.ok(c3 > c2);
    assert.equal((await store.recentMessages(chatId, 100)).length, 5); // short chat: nothing more to find, no refetch
    assert.equal(mem.state.calls, c3);
});

test('new, own, edited and deleted messages show up straight away', async () => {
    const { store, chatId, personId, say } = await setup();
    await say('one');
    await store.recentMessages(chatId, 80);
    await say('two');
    assert.deepEqual((await store.recentMessages(chatId, 80)).map((r) => r.body), ['one', 'two']);
    await store.recordOwn({ chatId, waId: 'own1', replyTo: null, body: 'hello from her', ts: new Date(2_000_000) });
    assert.equal((await store.recentMessages(chatId, 80)).at(-1).body, 'hello from her');
    await store.editMessage({ chatId, personId, waId: 'w1', body: 'ONE' });
    assert.equal((await store.recentMessages(chatId, 80))[0].body, 'ONE');
    await store.deleteMessage({ chatId, personId, waId: 'w2' });
    assert.ok(!(await store.recentMessages(chatId, 80)).some((r) => r.body === 'two'));
});

test('a duplicate message (not inserted) does not throw the cache away', async () => {
    const { mem, store, chatId, personId, say } = await setup();
    await say('one');
    await store.recentMessages(chatId, 80);
    const r = await store.recordMessage({ chatId, personId, waId: 'w1', replyTo: null, body: 'one', meta: {}, ts: new Date(), displayName: 'Ada' });
    assert.equal(r.inserted, false);
    const calls = mem.state.calls;
    await store.recentMessages(chatId, 80);
    assert.equal(mem.state.calls, calls);
});

test('entries expire after the TTL', async () => {
    const { mem, store, chatId, say, clock } = await setup({ ttlMs: 10_000 });
    await say('x');
    await store.recentMessages(chatId, 80);
    clock.tick(9_000);
    let calls = mem.state.calls; await store.recentMessages(chatId, 80); assert.equal(mem.state.calls, calls);
    clock.tick(2_000);
    calls = mem.state.calls; await store.recentMessages(chatId, 80); assert.ok(mem.state.calls > calls);
});

test('a read that overlaps a write is not cached', async () => {
    const { mem, chatId, personId } = await setup();
    let release; const gate = new Promise((r) => { release = r; });
    const slow = Object.create(mem);
    slow.recentMessages = async (...a) => { const rows = await mem.recentMessages(...a); await gate; return rows; };
    const store = withChatCache(slow);
    const pending = store.recentMessages(chatId, 80);                      // reads the empty chat, then waits
    await store.recordMessage({ chatId, personId, waId: 'late', replyTo: null, body: 'late', meta: {}, ts: new Date(), displayName: 'Ada' });
    release(); await pending;
    assert.deepEqual((await store.recentMessages(chatId, 80)).map((r) => r.body), ['late']);   // not the stale empty result
});

test('callers get copies: changing them does not change the cache', async () => {
    const { store, chatId, say } = await setup();
    await say('keep me');
    const a = await store.recentMessages(chatId, 80);
    a[0].body = 'changed'; a.push({ body: 'junk' });
    const b = await store.recentMessages(chatId, 80);
    assert.deepEqual(b.map((r) => r.body), ['keep me']);
});

test('chats are separate, memory is bounded, errors are not cached', async () => {
    const { mem, store, personId } = await setup({ maxChats: 2 });
    const ids = [];
    for (let i = 0; i < 4; i++) {
        const id = await mem.ensureChat({ key: `k${i}`, kind: 'dm', settings: {} });
        ids.push(id);
        await store.recordMessage({ chatId: id, personId, waId: `x${i}`, replyTo: null, body: `chat${i}`, meta: {}, ts: new Date(), displayName: 'Ada' });
        assert.equal((await store.recentMessages(id, 80))[0].body, `chat${i}`);
    }
    assert.ok(store.cache.size() <= 2);
    const flaky = { ...mem, recentMessages: async () => { throw new Error('db down'); } };
    const s2 = withChatCache(Object.assign(Object.create(mem), { recentMessages: flaky.recentMessages }));
    await assert.rejects(() => s2.recentMessages(ids[0], 80), /db down/);
    assert.equal(s2.cache.size(), 0);
});

test('summaries are cached longer, and other store methods pass straight through', async () => {
    const { mem, store, chatId, clock } = await setup({ summariesTtlMs: 60_000 });
    let n = 0;
    mem.latestSummaries = async () => { n++; return [{ body: `s${n}`, open_threads: [], ended: null }]; };
    const w = withChatCache(mem, { now: clock.now, summariesTtlMs: 60_000 });
    assert.equal((await w.latestSummaries(chatId, 2))[0].body, 's1');
    assert.equal((await w.latestSummaries(chatId, 2))[0].body, 's1');
    clock.tick(61_000);
    assert.equal((await w.latestSummaries(chatId, 2))[0].body, 's2');
    assert.equal(typeof store.createPerson, 'function');
});
