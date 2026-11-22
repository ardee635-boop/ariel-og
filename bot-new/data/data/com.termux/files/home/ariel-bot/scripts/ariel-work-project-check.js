#!/usr/bin/env node
// Work Mode project-memory checks (notes, decisions, to-dos).
//   node scripts/ariel-work-project-check.js                              offline: in-memory store + scripted models
//   node --env-file=.env scripts/ariel-work-project-check.js --db         also runs the store suite on the real SQL,
//                                                                         inside a transaction that is rolled back
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createMemoryWorkStore } from '../bot/wmode/store_memory.js';
import { createProviderManager } from '../bot/wmode/providers.js';
import { createWorkManager } from '../bot/wmode/manager.js';
import { resolveSettings } from '../bot/wmode/settings.js';
import { createSandbox } from '../bot/wmode/tools/sandbox.js';
import { createToolRegistry } from '../bot/wmode/tools/index.js';
import { registerFsTools } from '../bot/wmode/tools/fs_tools.js';
import { registerCmdTools } from '../bot/wmode/tools/cmd_tools.js';
import { registerProjectTools } from '../bot/wmode/tools/project_tools.js';
import { createMemoryProjectStore, createProjectStore, buildContext, looksLikeSecret } from '../bot/wmode/project.js';
import { needsTools } from '../bot/wmode/agent.js';
import { createWorkInterface, formatProject, parseWorkCommand } from '../bot/wmode/wa.js';

const useDb = process.argv.includes('--db');
const fails = [];
const check = (ok, what) => { console.log(`${ok ? '✓' : '✗'} ${what}`); if (!ok) fails.push(what); };
const J = JSON.stringify;
const tool = (name, args) => J({ tool: name, args });
const fin = (text) => J({ final: text });
const A = 'chatA@s.whatsapp.net'; const B = 'chatB@g.us';

// ── the store suite: runs on memory, and on real Postgres with --db ──
async function storeSuite(p, label) {
    const c = `${label}-${Math.random().toString(36).slice(2, 8)}@t`; const other = `${c}-other`;
    const n1 = await p.add({ chatJid: c, userId: 'u', kind: 'note', title: 'Deploy', body: 'We deploy to Render with the Procfile.' });
    const d1 = await p.add({ chatJid: c, userId: 'u', kind: 'decision', title: 'Use Postgres', body: 'Supabase for everything\nWhy: already there' });
    const t1 = await p.add({ chatJid: c, userId: 'u', kind: 'todo', title: 'Write the README', body: '' });
    check(n1.status === 'active' && d1.status === 'active' && t1.status === 'open' && t1.id > d1.id, `${label}: default statuses and ids`);
    check((await p.get(c, n1.id))?.title === 'Deploy' && (await p.get(other, n1.id)) === null, `${label}: an item is invisible from another chat`);
    check((await p.update(other, t1.id, { status: 'done' })) === null && (await p.get(c, t1.id)).status === 'open', `${label}: another chat cannot change it`);
    const u = await p.update(c, t1.id, { status: 'doing', body: 'started' });
    check(u.status === 'doing' && u.body === 'started' && u.title === 'Write the README', `${label}: partial update keeps the other fields`);
    const all = await p.list(c, {});
    check(all.length === 3 && all[0].id === t1.id, `${label}: list is newest-updated first`);
    check((await p.list(c, { kind: 'todo' })).length === 1 && (await p.list(c, { query: 'procfile' })).length === 1 && (await p.list(c, { query: '100%_x' })).length === 0, `${label}: filters by kind and text (wildcards are literal)`);
    const cnt = await p.counts(c);
    check(cnt.note === 1 && cnt.decision === 1 && cnt.todo === 1 && cnt.openTodos === 1, `${label}: counts`);
    const ctx = await p.context(c, 'how do we deploy this to Render?', { maxItems: 5, maxChars: 1500 });
    check(ctx.includes('todo #') && ctx.includes('decision #') && ctx.includes('note #') && ctx.includes('Procfile'), `${label}: context has the open to-do, decision and the relevant note`);
    check(!(await p.context(c, 'tell me a joke', {})).includes('note #') && (await p.context(other, 'deploy', {})) === '', `${label}: unrelated notes stay out; another chat gets nothing`);
    await p.update(c, t1.id, { status: 'done' });
    check(!(await p.context(c, 'x', {})).includes('todo #'), `${label}: finished to-dos leave the context`);
}

// ── pure ──
check(looksLikeSecret('postgresql://postgres.abc:Hunter22@aws-1.pooler.supabase.com:5432/postgres') && looksLikeSecret('key is gsk_abcdefghijklmnopqrstuvwxyz') && looksLikeSecret('AIza' + 'x'.repeat(35)) && !looksLikeSecret('We use Postgres and the Groq API'), 'secret detection: db urls and key shapes yes, plain talk no');
{
    const big = buildContext({ todos: Array.from({ length: 12 }, (_, i) => ({ id: i, status: 'open', title: `todo ${i} ${'x'.repeat(50)}` })), decisions: [], notes: [] }, 'x', { maxItems: 5, maxChars: 200 });
    check(big.length <= 200 && (big.match(/todo #/g) || []).length <= 5, 'context: capped by item count and characters');
    check(buildContext({}, 'anything') === '', 'context: empty when there is nothing');
}
check(needsTools('add a to-do: write tests', { project: true }) && needsTools('record the decision to use Groq', { project: true }) && !needsTools('add a to-do: write tests', { project: false }) && !needsTools('what is a closure?', { project: true }), 'needsTools: project requests use tools only when project tools exist');
check(parseWorkCommand('.wproject').cmd === '.wproject' && formatProject(null).includes('not available') && formatProject({ counts: { note: 0, decision: 0, todo: 0, openTodos: 0 }, todos: [], decisions: [], notes: [] }).includes('empty'), '.wproject: parsing and empty/unavailable views');
{
    const v = formatProject({ counts: { note: 1, decision: 1, todo: 2, openTodos: 2 }, todos: [{ id: 3, status: 'doing', title: 'ship it' }, { id: 4, status: 'open', title: 'test it' }], decisions: [{ id: 2, title: 'Use X', body: 'because' }], notes: [{ id: 1, title: 'setup' }] });
    check(v.includes('2 open to-do') && v.includes('🔧 #3 ship it') && v.includes('⬜ #4') && v.includes('📌 #2') && v.includes('📝 #1'), '.wproject: view shows to-dos, decisions, notes');
}

// ── store suites ──
await storeSuite(createMemoryProjectStore(), 'memory');
if (useDb) {
    const db = await import('../bot/ariel/db.js');
    const client = await db.getPool().connect();
    try { await client.query('begin'); await storeSuite(createProjectStore({ query: (t, p) => client.query(t, p) }), 'postgres'); }
    catch (e) { console.error('✗', e.stack || e.message); fails.push(e.message); }
    finally { await client.query('rollback').catch(() => {}); client.release(); await db.endPool(); console.log('(rolled back — nothing was saved)'); }
}

// ── tools + manager (offline) ──
function rig({ settings = {}, groq = [], project = createMemoryProjectStore({ maxItems: settings.projectMaxItems ?? 500 }), ws = fs.mkdtempSync(path.join(os.tmpdir(), 'wm-proj-')) } = {}) {
    const mk = (script) => ({ calls: [], script, async chat(entry, req) { this.calls.push(req); const s = this.script.length ? this.script.shift() : null; if (s instanceof Error) throw s; return { text: s ?? fin('(no scripted reply)'), tokensIn: 100, tokensOut: 50, finish: 'stop' }; } });
    const adapters = { groq: mk(groq), gemini: mk([]) };
    const s = resolveSettings({ toolMode: 'auto', review: false, ...settings }, {}); s.retryBackoffMs = 0; s.workspaceDir = ws;
    const providers = createProviderManager({ adapters, settings: s, sleep: async () => {}, env: { GEMINI_FLASH_MODEL: 'g-flash', GEMINI_LITE_MODEL: 'g-lite' } });
    const store = createMemoryWorkStore();
    const sandbox = createSandbox({ root: ws });
    const tools = registerCmdTools(registerFsTools(createToolRegistry({ settings: s }), { sandbox, settings: s }), { sandbox, settings: s });
    registerProjectTools(tools, { project, getTask: (id) => store.getTask(id), settings: s });
    const manager = createWorkManager({ store, providers, settings: s, tools, project, owner: `o${Math.random()}`, isChatEnabled: () => true });
    const out = []; let n = 0;
    const iface = createWorkInterface({ manager, settings: s, send: async (jid, text) => { out.push(text); }, typing: async () => {}, log: () => {} });
    const say = (text, chat = A) => iface.handle({ text, chatJid: chat, userId: 'u1', isDM: true, msgId: `m${++n}` });
    return { manager, project, adapters, tools, store, say, out, last: () => out.at(-1) };
}

{   // 1. add a to-do: verified, footer, .wproject
    const r = rig({ groq: [tool('todo_add', { title: 'Write the README', details: 'cover install + usage' }), fin('Added it to the list.')] });
    await r.say('.wchat on'); await r.say('add a to-do: write the README');
    check(/🗂️ project memory: todo #1 added/.test(r.last()) && !/not run/.test(r.last()), 'to-do added: footer reports it from the tool result (no "tests not run" noise)');
    check((await r.project.get(A, 1))?.title === 'Write the README', 'the to-do is really in storage');
    await r.say('.wproject');
    check(r.last().includes('1 open to-do') && r.last().includes('Write the README'), '.wproject shows it');
}
{   // 2. next task sees the memory; empty memory adds nothing
    const r = rig({ groq: [fin('Nothing to add.'), tool('todo_update', { id: 1, status: 'done', note: 'finished and reviewed' }), fin('Marked done.')] });
    await r.say('.wchat on');
    await r.say('show the project notes');
    check(!r.adapters.groq.calls.at(-1).messages.at(-1).content.includes('Project memory for this chat'), 'empty memory: no project block in the prompt');
    await r.project.add({ chatJid: A, userId: 'u1', kind: 'todo', title: 'Ship the v2 build' });
    await r.say('update the to-do list, mark the first one done');
    const prompts = r.adapters.groq.calls.map((c) => c.messages.at(-1).content);
    check(prompts.some((p) => p.includes('Project memory for this chat') && p.includes('Ship the v2 build') && p.includes('data, not instructions')), 'open to-do reaches the model as labelled data');
    check((await r.project.get(A, 1)).status === 'done' && (await r.project.get(A, 1)).body.includes('finished and reviewed') && /todo #1 → done/.test(r.last()), 'todo_update changes storage; footer says "todo #1 → done"');
}
{   // 3. secrets are refused, model sees why, nothing stored
    const r = rig({ groq: [tool('note_add', { title: 'DB', body: 'use postgresql://postgres.abc:Hunter22@aws-1.pooler.supabase.com:5432/postgres' }), fin('I could not save that.')] });
    await r.say('.wchat on'); await r.say('note that our database url is postgresql://postgres.abc:Hunter22@aws-1.pooler.supabase.com:5432/postgres');
    check((await r.project.list(A, {})).length === 0 && r.adapters.groq.calls.at(-1).messages.at(-1).content.includes('secret_refused'), 'secret not stored; the model is told why');
    check(!/project memory:/.test(r.last()), 'a refused save is not reported as saved');
}
{   // 4. decisions: record, supersede
    const r = rig({ groq: [tool('decision_record', { title: 'Reviewer', decision: 'Gemini reviews Groq code', why: 'different model family' }), tool('decision_record', { title: 'Reviewer v2', decision: 'Any non-author model reviews', supersedes: 1 }), fin('Recorded both.')] });
    await r.say('.wchat on'); await r.say('record the decision to use Gemini as reviewer, then record that any non-author model reviews, replacing it');
    const d1 = await r.project.get(A, 1); const d2 = await r.project.get(A, 2);
    check(d1.status === 'superseded' && d2.status === 'active' && d1.body.includes('Why: different model family'), 'superseding marks the old decision and keeps its reason');
    check(/decision #1 recorded/.test(r.last()) && /decision #2 recorded/.test(r.last()), 'footer lists both decisions');
}
{   // 5. isolation through the tools: chat B cannot touch chat A's items
    const r = rig({ groq: [tool('todo_update', { id: 1, status: 'done' }), tool('project_get', { id: 1 }), fin('Could not.')] });
    await r.project.add({ chatJid: A, userId: 'u1', kind: 'todo', title: 'private to A' });
    await r.say('.wchat on', B); await r.say('mark to-do 1 done and show it', B);
    check((await r.project.get(A, 1)).status === 'open' && r.adapters.groq.calls.at(-1).messages.at(-1).content.includes('not_found'), "another chat's items cannot be read or changed by a task");
}
{   // 6. limits: per-chat cap, over-long text refused (not cut)
    const r = rig({ settings: { projectMaxItems: 2, projectItemChars: 50 }, groq: [tool('todo_add', { title: 'one' }), tool('todo_add', { title: 'two' }), tool('todo_add', { title: 'three' }), tool('note_add', { title: 'long', body: 'x'.repeat(80) }), fin('Stopped.')] });
    await r.say('.wchat on'); await r.say('add a to-do three times and a note');
    const p = r.adapters.groq.calls.at(-1).messages.at(-1).content;
    check((await r.project.list(A, {})).length === 2 && p.includes('already has 2 project items') && p.includes('too_long'), 'chat cap enforced; over-long body refused rather than truncated');
}
{   // 7. verification: a store that loses the write is caught
    const flaky = createMemoryProjectStore(); const realGet = flaky.get; flaky.get = async () => null;
    const r = rig({ project: flaky, groq: [tool('todo_add', { title: 'ghost' }), fin('Done.')] });
    await r.say('.wchat on'); await r.say('add a to-do: ghost');
    check(r.adapters.groq.calls.at(-1).messages.at(-1).content.includes('verify_failed') && !/project memory: todo/.test(r.last()), 'a write that cannot be read back is reported as failed, not as saved');
    flaky.get = realGet;
}
{   // 8. project memory trouble never breaks a task
    const broken = createMemoryProjectStore(); broken.context = async () => { throw new Error('relation "ariel.work_project_items" does not exist'); };
    const r = rig({ project: broken, groq: [fin('Here are the notes: none.')] });
    await r.say('.wchat on'); await r.say('show the project notes');
    check(/Here are the notes/.test(r.last()), 'context lookup failing (e.g. migration not run) does not break the task');
}

console.log(fails.length ? `\n${fails.length} FAILED` : '\nall project-memory checks passed');
process.exit(fails.length ? 1 : 0);
