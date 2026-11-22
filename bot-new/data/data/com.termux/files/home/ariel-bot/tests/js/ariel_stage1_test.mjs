// Stage 1 tests: provider layer, schema file, SQL helpers, bench helpers.
// Run:  node --test tests/js/ariel_stage1_test.mjs      (no database, no network, no API keys)
import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { createAI, AIError, lagosDay } from '../../bot/ariel/providers/index.js';
import { buildAdapters } from '../../bot/ariel/providers/adapters.js';
import { defaultRouting, mergeRouting } from '../../bot/ariel/providers/routing.js';
import { renderSql, toVector, checksum } from '../../bot/ariel/sqlutil.js';
import * as lib from '../../scripts/ariel-bench-lib.js';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');

// ── helpers ─────────────────────────────────────────────────
function fakeAdapter(name, script) {
    const calls = [];
    return {
        name, calls, capabilities: { structured: true, embed: true },
        async chat(entry, req) {
            calls.push({ entry, req });
            const step = typeof script === 'function' ? script(entry, req, calls.length) : script;
            if (step instanceof Error) throw step;
            return step;
        },
        async embed(entry, texts) {
            calls.push({ entry, texts });
            const step = typeof script === 'function' ? script(entry, texts, calls.length) : script;
            if (step instanceof Error) throw step;
            return step;
        },
    };
}
const ok = (text, tin = 10, tout = 5) => ({ text, tokensIn: tin, tokensOut: tout, finish: 'stop' });
const err = (kind) => new AIError(kind, `${kind} error`);
const msgs = [{ role: 'user', content: 'hi' }];
const routingOf = (roles) => async () => ({ roles });

// ── schema file / sql helpers ───────────────────────────────
test('schema defines the 16 design tables, the privacy function, and no leftover placeholders', () => {
    const sql = fs.readFileSync(path.join(ROOT, 'bot/ariel/sql/001_schema.sql'), 'utf8');
    const tables = ['people', 'person_identities', 'chats', 'chat_members', 'messages', 'summaries', 'memories',
        'person_state', 'relationships', 'identity', 'ariel_state', 'initiatives', 'feedback_signals', 'jobs', 'llm_usage', 'config'];
    for (const t of tables) assert.match(sql, new RegExp(`create table if not exists ariel\\.${t} \\(`), `missing table ${t}`);
    assert.match(sql, /create or replace function ariel\.retrieve_memories/);
    const rendered = renderSql(sql, { dim: 768 });
    assert.ok(!rendered.includes('{{'));
    assert.equal((rendered.match(/vector\(768\)/g) || []).length, 2);   // summaries.embedding + memories.embedding
});

test('renderSql validates the vector size (HNSW limit 2000) and toVector formats for pg', () => {
    assert.throws(() => renderSql('x {{EMBED_DIM}}', { dim: 3072 }), /2000/);
    assert.throws(() => renderSql('x', { dim: 'abc' }));
    assert.equal(renderSql('vector({{EMBED_DIM}})', { dim: 1536 }), 'vector(1536)');
    assert.equal(toVector([0.5, 1, -2]), '[0.5,1,-2]');
    assert.throws(() => toVector([NaN]));
    assert.throws(() => toVector([]));
    assert.equal(checksum('a'), checksum('a'));
    assert.notEqual(checksum('a'), checksum('b'));
});

// ── fallback / breaker / budget ─────────────────────────────
test('falls over to the next model on 429/5xx/timeout/empty and records every attempt', async () => {
    const a = fakeAdapter('groq', err('ratelimit'));
    const b = fakeAdapter('gemini', ok('hello there'));
    const rows = [];
    const ai = createAI({
        adapters: { groq: a, gemini: b },
        getRouting: routingOf({ converse: { chain: [{ provider: 'groq', model: 'g1' }, { provider: 'gemini', model: 'm1', priceIn: 1, priceOut: 2 }] } }),
        usage: { record: (r) => rows.push(r) },
    });
    const r = await ai.chat({ role: 'converse', messages: msgs });
    assert.equal(r.text, 'hello there');
    assert.equal(r.provider, 'gemini');
    assert.equal(rows.length, 2);
    assert.equal(rows[0].ok, false);
    assert.equal(rows[1].ok, true);
    assert.equal(rows[1].costUsd, (10 * 1 + 5 * 2) / 1e6);
});

test('an empty reply counts as a failure and moves on', async () => {
    const ai = createAI({
        adapters: { a: fakeAdapter('a', ok('')), b: fakeAdapter('b', ok('real')) },
        getRouting: routingOf({ decide: { chain: [{ provider: 'a', model: 'x' }, { provider: 'b', model: 'y' }] } }),
    });
    assert.equal((await ai.chat({ role: 'decide', messages: msgs })).text, 'real');
});

test('when every model fails the error is "exhausted" (caller stays silent)', async () => {
    const ai = createAI({
        adapters: { a: fakeAdapter('a', err('server')), b: fakeAdapter('b', err('timeout')) },
        getRouting: routingOf({ converse: { chain: [{ provider: 'a', model: 'x' }, { provider: 'b', model: 'y' }] } }),
    });
    await assert.rejects(() => ai.chat({ role: 'converse', messages: msgs }), (e) => e.kind === 'exhausted' && e.attempts.length === 2);
});

test('unknown role and missing provider key are handled', async () => {
    const ai = createAI({ adapters: {}, getRouting: routingOf({ converse: { chain: [{ provider: 'groq', model: 'x' }] } }) });
    await assert.rejects(() => ai.chat({ role: 'nope', messages: msgs }), /no routing/);
    await assert.rejects(() => ai.chat({ role: 'converse', messages: msgs }), (e) => e.kind === 'exhausted');
});

test('3 failures in a row open a 60 s breaker; it closes again afterwards', async () => {
    let clock = 1_000_000;
    const bad = fakeAdapter('a', err('ratelimit'));
    const good = fakeAdapter('b', ok('fine'));
    const ai = createAI({
        adapters: { a: bad, b: good }, now: () => clock,
        getRouting: routingOf({ converse: { chain: [{ provider: 'a', model: 'x' }, { provider: 'b', model: 'y' }] } }),
    });
    for (let i = 0; i < 3; i++) await ai.chat({ role: 'converse', messages: msgs });
    assert.equal(bad.calls.length, 3);
    await ai.chat({ role: 'converse', messages: msgs });
    assert.equal(bad.calls.length, 3, 'breaker should skip model x');
    clock += 61_000;
    await ai.chat({ role: 'converse', messages: msgs });
    assert.equal(bad.calls.length, 4, 'breaker closed: model x is tried again');
});

test('transport failures open the breaker for the whole provider, not just one model', async () => {
    const a = fakeAdapter('a', err('server'));
    const good = fakeAdapter('b', ok('fine'));
    const ai = createAI({
        adapters: { a, b: good },
        getRouting: routingOf({ converse: { chain: [{ provider: 'a', model: 'm1' }, { provider: 'a', model: 'm2' }, { provider: 'b', model: 'y' }] } }),
    });
    for (let i = 0; i < 2; i++) await ai.chat({ role: 'converse', messages: msgs });   // 2 calls × (m1 + m2) = 4 failures >= 3
    const before = a.calls.length;
    await ai.chat({ role: 'converse', messages: msgs });
    assert.equal(a.calls.length, before, 'provider a is skipped entirely');
});

test('a dead model (404) does not take its provider down', async () => {
    const a = fakeAdapter('a', (entry) => (entry.model === 'dead' ? err('notfound') : ok('alive')));
    const ai = createAI({
        adapters: { a },
        getRouting: routingOf({ converse: { chain: [{ provider: 'a', model: 'dead' }, { provider: 'a', model: 'live' }] } }),
    });
    for (let i = 0; i < 4; i++) assert.equal((await ai.chat({ role: 'converse', messages: msgs })).text, 'alive');
});

test('daily budget: soft limit switches to the cheap chain, hard limit throws', async () => {
    const big = fakeAdapter('big', ok('from big', 60, 60));
    const small = fakeAdapter('small', ok('from small', 1, 1));
    const ai = createAI({
        adapters: { big, small },
        getRouting: routingOf({ converse: {
            chain: [{ provider: 'big', model: 'b' }], cheap: [{ provider: 'small', model: 's' }],
            softTokens: 100, hardTokens: 200,
        } }),
    });
    assert.equal((await ai.chat({ role: 'converse', messages: msgs })).text, 'from big');     // 120 used
    assert.equal((await ai.chat({ role: 'converse', messages: msgs })).text, 'from small');   // soft passed
    const ai2 = createAI({
        adapters: { big }, usage: { todayTokens: async () => 500 },
        getRouting: routingOf({ converse: { chain: [{ provider: 'big', model: 'b' }], hardTokens: 200 } }),
    });
    await assert.rejects(() => ai2.chat({ role: 'converse', messages: msgs }), (e) => e.kind === 'budget');
});

test('lagosDay uses the Lagos calendar day', () => {
    assert.equal(lagosDay(Date.UTC(2026, 9, 31, 23, 30)), '2026-11-01');   // 23:30 UTC = 00:30 Lagos next day
    assert.equal(lagosDay(Date.UTC(2026, 9, 31, 12, 0)), '2026-10-31');
});

test('structured output: parsed when supported, tolerant fallback when not', async () => {
    const a = fakeAdapter('a', (e, req) => ok(req.schema ? '{"x":1}' : 'plain text'));
    const mk = (entry) => createAI({ adapters: { a }, getRouting: routingOf({ extract: { chain: [entry] } }) });
    const schema = { type: 'object' };

    const on = await mk({ provider: 'a', model: 'm', structured: true }).chat({ role: 'extract', messages: msgs, schema });
    assert.deepEqual(on.json, { x: 1 }); assert.equal(on.structured, true);

    const off = await mk({ provider: 'a', model: 'm' }).chat({ role: 'extract', messages: msgs, schema });
    assert.equal(off.structured, false); assert.equal(off.json, undefined); assert.equal(off.text, 'plain text');
    assert.equal(a.calls.at(-1).req.schema, null, 'schema is not sent to a model not marked structured');

    const bad = createAI({ adapters: { a: fakeAdapter('a', ok('not json')) }, getRouting: routingOf({ extract: { chain: [{ provider: 'a', model: 'm', structured: true }] } }) });
    const r = await bad.chat({ role: 'extract', messages: msgs, schema });
    assert.equal(r.structured, false); assert.equal(r.text, 'not json');
});

test('embeddings: never fail over to another model; retry the same one; check dimensions', async () => {
    const mkVec = (n) => ({ vectors: [Array(n).fill(0.1)], tokensIn: 1 });
    let n = 0;
    const flaky = fakeAdapter('g', () => (++n === 1 ? err('server') : mkVec(4)));
    const other = fakeAdapter('o', mkVec(4));
    const ai = createAI({ adapters: { g: flaky, o: other }, getRouting: routingOf({ embed: { chain: [{ provider: 'g', model: 'e', dim: 4 }, { provider: 'o', model: 'e2', dim: 4 }] } }) });
    const r = await ai.embed('hi');
    assert.equal(r.dim, 4); assert.equal(flaky.calls.length, 2); assert.equal(other.calls.length, 0);

    const wrong = createAI({ adapters: { g: fakeAdapter('g', mkVec(3)) }, getRouting: routingOf({ embed: { chain: [{ provider: 'g', model: 'e', dim: 4 }] } }) });
    await assert.rejects(() => wrong.embed('hi'), /dims/);

    const dead = fakeAdapter('g', err('server'));
    const none = createAI({ adapters: { g: dead, o: other }, getRouting: routingOf({ embed: { chain: [{ provider: 'g', model: 'e' }, { provider: 'o', model: 'e2' }] } }) });
    await assert.rejects(() => none.embed(['a', 'b']), (e) => e.kind === 'server');
    assert.equal(other.calls.length, 0);
});

// ── routing / adapters ──────────────────────────────────────
test('default routing: embed has exactly one model; merge overrides per role', () => {
    const r = defaultRouting({});
    assert.equal(r.roles.embed.chain.length, 1);
    assert.equal(r.roles.embed.chain[0].dim, 768);
    for (const role of ['converse', 'decide', 'extract']) assert.ok(r.roles[role].chain.length >= 2);
    assert.equal(defaultRouting({ ARIEL_EMBED_DIM: '1536' }).roles.embed.chain[0].dim, 1536);
    assert.ok(defaultRouting({ ARIEL_OPENROUTER_MODEL: 'x/y' }).roles.converse.chain.some((e) => e.provider === 'openrouter'));
    const merged = mergeRouting(r, { roles: { decide: { timeoutMs: 1234 } } });
    assert.equal(merged.roles.decide.timeoutMs, 1234);
    assert.equal(merged.roles.decide.chain.length, r.roles.decide.chain.length);
    assert.equal(mergeRouting(r, null), r);
});

test('buildAdapters creates only adapters whose key exists', () => {
    assert.deepEqual(Object.keys(buildAdapters({})), []);
    assert.deepEqual(Object.keys(buildAdapters({ GROQ_API_KEY: 'k', GOOGLE_API_KEY: 'g' })).sort(), ['gemini', 'groq']);
    assert.deepEqual(Object.keys(buildAdapters({ OPENROUTER_API_KEY: 'k' })), ['openrouter']);
});

// ── real adapters against a local mock server ───────────────
async function withServer(handler, fn) {
    const seen = [];
    const server = http.createServer((req, res) => {
        let body = '';
        req.on('data', (c) => (body += c));
        req.on('end', () => {
            const rec = { url: req.url, headers: req.headers, body: body ? JSON.parse(body) : null };
            seen.push(rec);
            handler(rec, res);
        });
    });
    await new Promise((r) => server.listen(0, '127.0.0.1', r));
    const base = `http://127.0.0.1:${server.address().port}`;
    try { await fn(base, seen); } finally { server.closeAllConnections?.(); await new Promise((r) => server.close(r)); }
}
const json = (res, status, obj) => { res.writeHead(status, { 'content-type': 'application/json' }); res.end(JSON.stringify(obj)); };

test('groq adapter: request shape, reasoning headroom, structured format, <think> stripped, usage', async () => {
    await withServer((rec, res) => json(res, 200, {
        choices: [{ message: { content: '<think>secret</think>ACTION: reply\nhey' }, finish_reason: 'stop' }],
        usage: { prompt_tokens: 11, completion_tokens: 7 },
    }), async (base, seen) => {
        const ai = createAI({ adapters: buildAdapters({ GROQ_API_KEY: 'sk-test' }, { baseUrls: { groq: base } }), getRouting: routingOf({}) });
        const r = await ai.callOnce({ provider: 'groq', model: 'openai/gpt-oss-120b', reasoning: 'low', headroom: 300, structured: true },
            { messages: [{ role: 'system', content: 'S' }, { role: 'user', content: 'U' }], maxTokens: 100, temperature: 0.5, schema: { type: 'object' } }, 5000);
        assert.equal(r.text, 'ACTION: reply\nhey');
        assert.equal(r.tokensIn, 11); assert.equal(r.tokensOut, 7);
        const q = seen[0];
        assert.equal(q.url, '/chat/completions');
        assert.equal(q.headers.authorization, 'Bearer sk-test');
        assert.equal(q.body.model, 'openai/gpt-oss-120b');
        assert.equal(q.body.max_tokens, 400);
        assert.equal(q.body.reasoning_effort, 'low');
        assert.equal(q.body.response_format.type, 'json_schema');
        assert.deepEqual(q.body.messages[0], { role: 'system', content: 'S' });
    });
});

test('gemini adapter: system -> systemInstruction, alternating turns merged, thoughts dropped, thinking tokens counted', async () => {
    await withServer((rec, res) => json(res, 200, {
        candidates: [{ content: { parts: [{ text: 'private', thought: true }, { text: 'visible ' }, { text: 'reply' }] }, finishReason: 'STOP' }],
        usageMetadata: { promptTokenCount: 20, candidatesTokenCount: 5, thoughtsTokenCount: 30 },
    }), async (base, seen) => {
        const ai = createAI({ adapters: buildAdapters({ GEMINI_API_KEY: 'gk' }, { baseUrls: { gemini: base } }), getRouting: routingOf({}) });
        const r = await ai.callOnce({ provider: 'gemini', model: 'gem-x' },
            { messages: [{ role: 'system', content: 'SYS' }, { role: 'user', content: 'a' }, { role: 'user', content: 'b' }, { role: 'assistant', content: 'c' }], maxTokens: 100, temperature: 0.3, schema: null }, 5000);
        assert.equal(r.text, 'visible reply');
        assert.equal(r.tokensOut, 35); assert.equal(r.tokensIn, 20);
        const q = seen[0];
        assert.equal(q.url, '/models/gem-x:generateContent');
        assert.equal(q.headers['x-goog-api-key'], 'gk');
        assert.deepEqual(q.body.systemInstruction, { parts: [{ text: 'SYS' }] });
        assert.equal(q.body.contents.length, 2);
        assert.equal(q.body.contents[0].parts[0].text, 'a\nb');
        assert.equal(q.body.contents[1].role, 'model');
        assert.equal(q.body.generationConfig.maxOutputTokens, 356);
    });
});

test('gemini embeddings: batch request, dimension requested, vectors normalised', async () => {
    await withServer((rec, res) => json(res, 200, { embeddings: [{ values: [3, 4] }, { values: [0, 2] }] }), async (base, seen) => {
        const ai = createAI({ adapters: buildAdapters({ GEMINI_API_KEY: 'gk' }, { baseUrls: { gemini: base } }),
            getRouting: routingOf({ embed: { chain: [{ provider: 'gemini', model: 'emb', dim: 2 }] } }) });
        const r = await ai.embed(['x', 'y'], { kind: 'query' });
        assert.deepEqual(r.vectors, [[0.6, 0.8], [0, 1]]);
        assert.equal(seen[0].url, '/models/emb:batchEmbedContents');
        assert.equal(seen[0].body.requests[0].outputDimensionality, 2);
        assert.equal(seen[0].body.requests[0].taskType, 'RETRIEVAL_QUERY');
        assert.equal(seen[0].body.requests[0].model, 'models/emb');
    });
});

test('openrouter embeddings come back in input order', async () => {
    await withServer((rec, res) => json(res, 200, { data: [{ index: 1, embedding: [0, 1] }, { index: 0, embedding: [1, 0] }], usage: { prompt_tokens: 4 } }), async (base, seen) => {
        const ai = createAI({ adapters: buildAdapters({ OPENROUTER_API_KEY: 'k' }, { baseUrls: { openrouter: base } }),
            getRouting: routingOf({ embed: { chain: [{ provider: 'openrouter', model: 'e', dim: 2 }] } }) });
        const r = await ai.embed(['a', 'b']);
        assert.deepEqual(r.vectors, [[1, 0], [0, 1]]);
        assert.equal(seen[0].body.dimensions, 2);
    });
});

test('http errors are classified; a slow server times out', async () => {
    for (const [status, kind] of [[429, 'ratelimit'], [503, 'server'], [404, 'notfound'], [401, 'auth'], [400, 'bad']]) {
        await withServer((rec, res) => json(res, status, { error: { message: 'nope' } }), async (base) => {
            const ai = createAI({ adapters: buildAdapters({ GROQ_API_KEY: 'k' }, { baseUrls: { groq: base } }), getRouting: routingOf({}) });
            await assert.rejects(() => ai.callOnce({ provider: 'groq', model: 'm' }, { messages: msgs, maxTokens: 5, temperature: 0 }, 2000), (e) => e.kind === kind && /nope/.test(e.message));
        });
    }
    await withServer(() => { /* never answers */ }, async (base) => {
        const ai = createAI({ adapters: buildAdapters({ GROQ_API_KEY: 'k' }, { baseUrls: { groq: base } }), getRouting: routingOf({}) });
        await assert.rejects(() => ai.callOnce({ provider: 'groq', model: 'm' }, { messages: msgs, maxTokens: 5, temperature: 0 }, 150), (e) => e.kind === 'timeout');
    });
});

// ── bench helpers ───────────────────────────────────────────
const ANDROID = `12/03/2026, 14:05 - Messages and calls are end-to-end encrypted.
12/03/2026, 14:06 - Tolu: wetin dey happen?? call me on +234 801 234 5678
12/03/2026, 14:07 - +234 809 111 2222: i go reach there by 5
and i dey bring food
12/03/2026, 14:08 - Tolu: <Media omitted>
12/03/2026, 14:09 - Tolu: This message was deleted
12/03/2026, 14:10 - Chidi: mail me chidi.o@example.com @2348012345678 abeg`;

const IOS = `[12/03/2026, 14:06:33] Tolu: hello there
[12/03/2026, 2:07:01 PM] \u200eAmaka: you good?
\u200e[12/03/2026, 14:08:10] Tolu: \u200eimage omitted`;

test('whatsapp import: system/deleted lines dropped, multiline joined, phones/emails masked, phone-only senders aliased', () => {
    const m = lib.parseWhatsApp(ANDROID);
    assert.deepEqual(m.map((x) => x.from), ['Tolu', 'Person1', 'Tolu', 'Chidi']);
    assert.equal(m[0].text, 'wetin dey happen?? call me on [phone]');
    assert.equal(m[1].text, 'i go reach there by 5\nand i dey bring food');
    assert.equal(m[2].text, '[media]');
    assert.ok(!/\d{9}/.test(JSON.stringify(m)));
    assert.match(m[3].text, /\[email\] @\[person\] abeg/);
    const i = lib.parseWhatsApp(IOS);
    assert.equal(i.length, 3);
    assert.deepEqual(i.map((x) => x.from), ['Tolu', 'Amaka', 'Tolu']);
    assert.equal(i[2].text, '[media]');
});

test('maskPhones leaves dates and short numbers alone', () => {
    assert.equal(lib.maskPhones('on 12-03-2026 pay 50,000 at 5pm'), 'on 12-03-2026 pay 50,000 at 5pm');
    assert.equal(lib.maskPhones('call 08012345678 now'), 'call [phone] now');
});

test('makeCases windows, group/dm detection, and cap', () => {
    const many = Array.from({ length: 400 }, (_, i) => ({ from: ['A', 'B', 'C'][i % 3], text: `m${i}` }));
    const cases = lib.makeCases(many, { window: 15, every: 40, max: 5, prefix: 'x' });
    assert.equal(cases.length, 5);
    assert.equal(cases[0].id, 'x-001');
    assert.equal(cases[0].chatKind, 'group');
    assert.equal(cases[0].messages.length, 15);
    const dm = lib.makeCases(Array.from({ length: 30 }, (_, i) => ({ from: i % 2 ? 'A' : 'B', text: 'x' })), { window: 10, every: 10, prefix: 'd' });
    assert.ok(dm.every((c) => c.chatKind === 'dm'));
});

test('parseAction is tolerant: missing header still counts as a reply', () => {
    assert.deepEqual(lib.parseAction('ACTION: silent'), { action: 'silent', formatOk: true });
    assert.deepEqual(lib.parseAction('action: Reply\nhi'), { action: 'reply', formatOk: true });
    assert.deepEqual(lib.parseAction('just text'), { action: 'reply', formatOk: false });
    assert.deepEqual(lib.parseAction(''), { action: 'silent', formatOk: false });
    assert.equal(lib.bodyOf('ACTION: reply\nREPLY_TO: 4\nhi\n---\nthere'), 'hi\n---\nthere');
});

test('parseModelSpec handles slashes, :free suffixes and @dim', () => {
    assert.deepEqual(lib.parseModelSpec('groq=openai/gpt-oss-120b'), { provider: 'groq', model: 'openai/gpt-oss-120b' });
    assert.deepEqual(lib.parseModelSpec('openrouter=meta/llama:free@768'), { provider: 'openrouter', model: 'meta/llama:free', dim: 768 });
    assert.throws(() => lib.parseModelSpec('nonsense'));
});

test('pickPairs: blind, balanced, skips silence/identical, deterministic', () => {
    const results = [];
    for (let c = 0; c < 12; c++) for (const model of ['m1', 'm2', 'm3']) {
        results.push({ caseId: `c${c}`, model, ok: true, action: 'reply', text: `ACTION: reply\n${model} says ${c}` });
    }
    results.push({ caseId: 'c0', model: 'm4', ok: true, action: 'silent', text: 'ACTION: silent' });
    const p1 = lib.pickPairs(results, { pairs: 12, seed: 7 });
    const p2 = lib.pickPairs(results, { pairs: 12, seed: 7 });
    assert.deepEqual(p1, p2);
    assert.equal(p1.length, 12);
    const shown = {};
    for (const p of p1) { shown[p.a] = (shown[p.a] || 0) + 1; shown[p.b] = (shown[p.b] || 0) + 1; assert.notEqual(p.a, p.b); assert.ok(!('m4' in { [p.a]: 1, [p.b]: 1 })); }
    const counts = Object.values(shown);
    assert.ok(Math.max(...counts) - Math.min(...counts) <= 2, `unbalanced: ${JSON.stringify(shown)}`);
    assert.ok(p1.some((p) => p.a === 'm1') && p1.some((p) => p.b === 'm1'), 'A/B order is randomised');
});

test('summarize: ok rate, silence accuracy, latency, cost, A/B win rates', () => {
    const results = [
        { caseId: 'c1', model: 'm1', ok: true, action: 'silent', formatOk: true, ms: 100, tokensIn: 10, tokensOut: 5, cost: 0.001 },
        { caseId: 'c2', model: 'm1', ok: true, action: 'reply', formatOk: false, ms: 300, tokensIn: 10, tokensOut: 5, cost: 0.001 },
        { caseId: 'c1', model: 'm2', ok: true, action: 'reply', formatOk: true, ms: 200, tokensIn: 20, tokensOut: 10, cost: null },
        { caseId: 'c2', model: 'm2', ok: false, action: null, formatOk: false, ms: 0, tokensIn: 0, tokensOut: 0, cost: null },
    ];
    const cases = [{ id: 'c1', expect: 'silent' }, { id: 'c2', expect: 'reply' }];
    const scores = [
        { caseId: 'c1', a: 'm1', b: 'm2', personality: 'a', naturalness: 'b' },
        { caseId: 'c2', a: 'm2', b: 'm1', personality: '=', naturalness: 'a' },
    ];
    const [m1, m2] = lib.summarize(results, scores, cases);
    assert.equal(m1.okRate, 1); assert.equal(m1.silenceAcc, 1); assert.equal(m1.formatRate, 0.5);
    assert.equal(m1.p50, 300); assert.equal(m1.tokIn, 10);
    assert.ok(Math.abs(m1.costPer100 - 0.1) < 1e-9);
    assert.equal(m2.okRate, 0.5); assert.equal(m2.silenceAcc, 0); assert.equal(m2.costPer100, null);
    assert.equal(m1.personality, 0.75); assert.equal(m1.naturalness, 0);
    assert.equal(m2.personality, 0.25); assert.equal(m2.naturalness, 1);
});

test('scoreEmbeddings: perfect vectors score top1 = 1 with a positive margin', () => {
    const n = lib.EMBED_PAIRS.length;
    const dim = n + 1;
    const unit = (i) => Array.from({ length: dim }, (_, k) => (k === i ? 1 : 0));
    const mem = Array.from({ length: n }, (_, i) => unit(i));
    const qry = Array.from({ length: n }, (_, i) => unit(i));
    const unr = lib.EMBED_UNRELATED.map(() => unit(n));
    const s = lib.scoreEmbeddings([...mem, ...qry, ...unr]);
    assert.equal(s.top1, 1);
    assert.ok(s.margin > 0.9);
    assert.ok(lib.cosine([1, 0], [0, 1]) === 0);
});
