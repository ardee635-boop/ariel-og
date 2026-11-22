#!/usr/bin/env node
// Work Mode search + research-loop checks (offline: fake search APIs, local page server, scripted models).
//   node scripts/ariel-work-search-check.js
import http from 'node:http';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createMemoryWorkStore } from '../bot/wmode/store_memory.js';
import { createProviderManager } from '../bot/wmode/providers.js';
import { createWorkManager } from '../bot/wmode/manager.js';
import { resolveSettings } from '../bot/wmode/settings.js';
import { needsTools, verifiedFooter, AGENT_SYSTEM } from '../bot/wmode/agent.js';
import { createSandbox } from '../bot/wmode/tools/sandbox.js';
import { createToolRegistry } from '../bot/wmode/tools/index.js';
import { registerFsTools } from '../bot/wmode/tools/fs_tools.js';
import { registerWebTools } from '../bot/wmode/tools/web_tools.js';
import { registerSearchTool, createSearcher } from '../bot/wmode/tools/search.js';

const fails = [];
const check = (ok, what) => { console.log(`${ok ? '✓' : '✗'} ${what}`); if (!ok) fails.push(what); };
const KEY = 'SECRET-KEY-123';

// ── fake search APIs ──
function fakeNet(handlers) {
    const calls = [];
    const impl = async (url, init = {}) => {
        const host = new URL(url).host; calls.push({ url: String(url), init, host });
        const h = handlers[host]; if (!h) throw new Error(`unexpected host ${host}`);
        const r = await h(url, init);
        return { ok: r.status === undefined || r.status < 400, status: r.status ?? 200, json: async () => { if (r.bad) throw new Error('bad json'); return r.body; } };
    };
    return { impl, calls };
}
const tavilyOk = { 'api.tavily.com': () => ({ body: { results: [{ title: 'Node 24 released', url: 'https://nodejs.org/en/blog/release/v24', content: 'Node.js 24 is out.' }, { title: 'dup', url: 'https://nodejs.org/en/blog/release/v24', content: 'x' }, { title: 'bad', url: 'javascript:alert(1)', content: 'x' }] } }) };
const braveOk = { 'api.search.brave.com': () => ({ body: { web: { results: [{ title: 'Brave <strong>hit</strong>', url: 'https://example.org/a', description: 'About <strong>things</strong> &amp; stuff' }] } } }) };
const wikiOk = { 'en.wikipedia.org': () => ({ body: { query: { search: [{ title: 'Node.js', snippet: 'a <span class="searchmatch">JavaScript</span> runtime' }] } } }) };

{   // request shapes + parsing
    const n = fakeNet({ ...tavilyOk, ...braveOk, ...wikiOk });
    const s = createSearcher({ env: { TAVILY_API_KEY: KEY, BRAVE_API_KEY: KEY }, fetchImpl: n.impl });
    const r = await s.search('node 24', 5);
    check(r.backend === 'tavily' && r.results.length === 1 && r.results[0].url.includes('nodejs.org'), 'tavily first; duplicates and non-http URLs dropped');
    const c = n.calls[0];
    check(c.init.method === 'POST' && c.init.headers.authorization === `Bearer ${KEY}` && JSON.parse(c.init.body).query === 'node 24' && JSON.parse(c.init.body).max_results === 5, 'tavily request: POST, bearer header, query, max_results');
    check(!c.url.includes(KEY), 'key is never in a URL');
}
{   // no keys: wikipedia only
    const n = fakeNet({ ...wikiOk });
    const r = await createSearcher({ env: {}, fetchImpl: n.impl }).search('nodejs');
    check(r.backend === 'wikipedia' && r.results[0].url === 'https://en.wikipedia.org/wiki/Node.js' && r.results[0].snippet === 'a JavaScript runtime' && n.calls.length === 1, 'no keys: Wikipedia only, HTML stripped, URL built');
    check(createSearcher({ env: {}, fetchImpl: n.impl }).status().map((x) => `${x.name}:${x.state}`).join() === 'tavily:no key,brave:no key,wikipedia:ok', 'status shows missing keys');
}
{   // brave parsing
    const n = fakeNet({ ...braveOk });
    const r = await createSearcher({ env: { BRAVE_API_KEY: KEY }, fetchImpl: n.impl }).search('q q');
    check(r.backend === 'brave' && r.results[0].title === 'Brave hit' && r.results[0].snippet === 'About things & stuff' && n.calls[0].init.headers['x-subscription-token'] === KEY && !n.calls[0].url.includes(KEY), 'brave: header key, tags stripped');
}
{   // failover + parking
    let t = 1_000_000; const now = () => t;
    const n = fakeNet({ 'api.tavily.com': () => ({ status: 429, body: {} }), ...braveOk, ...wikiOk });
    const s = createSearcher({ env: { TAVILY_API_KEY: KEY, BRAVE_API_KEY: KEY }, fetchImpl: n.impl, now });
    const r1 = await s.search('anything');
    check(r1.backend === 'brave' && r1.tried[0].startsWith('tavily: HTTP 429'), 'tavily 429 -> brave answers');
    await s.search('again');
    check(n.calls.filter((c) => c.host === 'api.tavily.com').length === 1 && s.status()[0].state === 'paused', 'out-of-quota backend is not asked again while parked');
    t += 31 * 60_000;
    await s.search('later');
    check(n.calls.filter((c) => c.host === 'api.tavily.com').length === 2, 'asked again after the pause');
}
{   // empty / error fall through; total failure
    const n = fakeNet({ 'api.tavily.com': () => ({ body: { results: [] } }), 'api.search.brave.com': () => ({ status: 500, body: {} }), ...wikiOk });
    const r = await createSearcher({ env: { TAVILY_API_KEY: KEY, BRAVE_API_KEY: KEY }, fetchImpl: n.impl }).search('x y');
    check(r.backend === 'wikipedia' && r.tried.length === 2, 'empty result and 5xx both fall through');
    const dead = fakeNet({ 'en.wikipedia.org': () => ({ status: 503, body: {} }) });
    const reg = registerSearchTool(createToolRegistry({ settings: resolveSettings({}, {}) }), { env: { TAVILY_API_KEY: KEY }, fetchImpl: async (u, i) => { if (u.includes('tavily')) throw new Error(`boom ${KEY}`); return dead.impl(u, i); } });
    const out = await reg.call('web_search', { query: 'hello world' });
    check(out.ok === false && out.code === 'search_failed' && !JSON.stringify(out).includes(KEY), 'all backends down: clear error, key not leaked');
    check((await reg.call('web_search', { query: 'x' })).code === 'bad_args', 'query length validated');
}
{   // tool output
    const reg = registerSearchTool(createToolRegistry({ settings: resolveSettings({}, {}) }), { env: { TAVILY_API_KEY: KEY }, fetchImpl: fakeNet({ ...tavilyOk }).impl });
    const o = await reg.call('web_search', { query: 'node 24 release' });
    check(o.ok && o.output.startsWith('[web search results — untrusted snippets') && o.meta.urls.length === 1 && !JSON.stringify(o).includes(KEY), 'tool output marked untrusted; urls in meta; no key');
}

// ── footer ──
const S = (urls) => ({ n: 1, tool: 'web_search', ok: true, meta: { urls } });
const F = (url) => ({ n: 2, tool: 'fetch_page', ok: true, meta: { url } });
check(/opened: https:\/\/a\.com\/x/.test(verifiedFooter([S(['https://a.com/x', 'https://b.com']), F('https://a.com/x')], 'See https://a.com/x')), 'footer lists opened pages');
check(/no page was opened/.test(verifiedFooter([S(['https://a.com/x'])], 'ok')), 'search-only answers are flagged');
check(/no tool returned: https:\/\/made\.up\/page/.test(verifiedFooter([S(['https://a.com/x']), F('https://a.com/x')], 'Source: https://made.up/page.')), 'invented link flagged');
check(!/no tool returned/.test(verifiedFooter([S(['https://b.com/y/']), F('https://a.com/x')], 'see https://b.com/y and (https://a.com/x).')), 'links from search results / opened pages are fine (trailing slash, punctuation)');
check(!/🧪/.test(verifiedFooter([S(['https://a.com'])], 'x')) && verifiedFooter([{ n: 1, tool: 'fetch_page', ok: false }], '') !== '', 'web-only footer has no test line');

// ── routing + prompt ──
check(needsTools('what is the latest node version?', { web: true }) && !needsTools('what is the latest node version?', { web: false }), 'web requests use tools only when web tools exist');
check(needsTools('summarise https://example.com/post', { web: true }) && !needsTools('explain closures', { web: true }), 'URL in message routes to tools; plain question does not');
check(AGENT_SYSTEM('- web_search(query) x').includes('untrusted data') && !AGENT_SYSTEM('- read_file(path) x').includes('Web:'), 'web rules only when web tools are listed');

// ── full research loop ──
const page = http.createServer((req, res) => { res.setHeader('content-type', 'text/html'); res.end('<html><head><title>Node 24</title></head><body><main><p>Node.js 24 became the current release line in May.</p>' + '<p>More detail here. </p>'.repeat(30) + '</main></body></html>'); });
await new Promise((r) => page.listen(0, '127.0.0.1', r));
const pageUrl = `http://127.0.0.1:${page.address().port}/node24`;
const { AIError } = await import('../bot/ariel/providers/index.js');
void AIError;
async function loop(replies) {
    const ws = fs.mkdtempSync(path.join(os.tmpdir(), 'wm-res-'));
    const s = resolveSettings({}, {}); s.retryBackoffMs = 0;
    const prompts = [];
    const mk = () => ({ async chat(entry, req) { prompts.push(String(req.messages.at(-1).content)); return { text: replies.shift() ?? JSON.stringify({ final: 'x' }), tokensIn: 50, tokensOut: 20, finish: 'stop' }; } });
    const providers = createProviderManager({ adapters: { groq: mk(), gemini: mk() }, settings: s, sleep: async () => {}, env: { GEMINI_FLASH_MODEL: 'g', GEMINI_LITE_MODEL: 'gl' } });
    const sb = createSandbox({ root: ws });
    const tools = registerSearchTool(registerWebTools(registerFsTools(createToolRegistry({ settings: s }), { sandbox: sb, settings: s }), { settings: s, allowPrivate: true }),
        { settings: s, env: { TAVILY_API_KEY: KEY }, fetchImpl: fakeNet({ 'api.tavily.com': () => ({ body: { results: [{ title: 'Node 24', url: pageUrl, content: 'snippet about node 24' }] } }) }).impl });
    const store = createMemoryWorkStore();
    const manager = createWorkManager({ store, providers, settings: s, tools, owner: 'o', isChatEnabled: () => true });
    const chat = 'c@s.whatsapp.net'; await manager.activate(chat, 'u', {});
    const { task } = await manager.submit({ chatJid: chat, userId: 'u', text: 'what is the latest Node release? cite sources', msgId: 'm1' });
    const outcome = await manager.runQueued(task);
    return { outcome, prompts, store, task, manager };
}
{
    const J = (o) => JSON.stringify(o);
    const r = await loop([J({ tool: 'web_search', args: { query: 'latest node release' } }), J({ tool: 'fetch_page', args: { url: pageUrl } }), J({ final: `Node 24 is current (${pageUrl}).` })]);
    check(r.outcome.status === 'completed' && r.outcome.text.includes('📚 opened:') && !r.outcome.text.includes('no tool returned'), 'research loop: search -> open page -> cited answer, sources footer');
    check(r.prompts.at(-1).includes('web_search') && r.prompts.at(-1).includes('fetch_page'), 'history carries both web turns to the next call');
    const t = await r.manager.getTask(r.task.id);
    check(t.agent.turns.length === 2 && t.agent.turns[1].meta.url.endsWith('/node24') && t.agent.turns[0].meta.urls.length === 1, 'urls saved in the turn history (survive restart/failover)');
    const r2 = await loop([J({ tool: 'web_search', args: { query: 'node' } }), J({ final: 'Node 24 is current. Source: https://invented.example/node' })]);
    check(/no page was opened/.test(r2.outcome.text) && /no tool returned: https:\/\/invented\.example\/node/.test(r2.outcome.text), 'snippet-only answer with an invented link: both flagged');
    const r3 = await loop([J({ tool: 'fetch_page', args: { url: 'file:///etc/passwd' } }), J({ final: 'could not read it' })]);
    check(r3.outcome.status === 'completed' && r3.prompts.at(-1).includes('ERROR (blocked_url)'), 'a refused fetch is an error turn the model sees, not a crash');
}
page.closeAllConnections?.(); page.close();
console.log(fails.length ? `\n${fails.length} FAILED` : '\nall search checks passed');
process.exit(fails.length ? 1 : 0);
