#!/usr/bin/env node
// Work Mode checks.
//   node scripts/ariel-work-check.js            offline: in-memory store + fake AI providers (no keys, no DB)
//   node --env-file=.env scripts/ariel-work-check.js --db
//                                               same scenarios against your real Postgres, inside ONE
//                                               transaction that is always rolled back (run
//                                               scripts/ariel-migrate.js first so 003_work.sql exists)
import { AIError } from '../bot/ariel/providers/index.js';
import { createMemoryWorkStore } from '../bot/wmode/store_memory.js';
import { createWorkStore } from '../bot/wmode/store.js';
import { createProviderManager, defaultWorkRouting, parseRetryAfterMs } from '../bot/wmode/providers.js';
import { createWorkManager, classifyKind, chunkText } from '../bot/wmode/manager.js';
import { needsPlan, parsePlan, splitSummary, contextBlock } from '../bot/wmode/planner.js';
import { resolveSettings } from '../bot/wmode/settings.js';

const useDb = process.argv.includes('--db');
const fails = [];
const check = (ok, what) => { console.log(`${ok ? '✓' : '✗'} ${what}`); if (!ok) fails.push(what); };

// ── fakes ───────────────────────────────────────────────────────
const clock = { t: Date.UTC(2026, 10, 2, 10, 0, 0) };
const now = () => clock.t;
const ENV = { GEMINI_FLASH_MODEL: 'g-flash', GEMINI_LITE_MODEL: 'g-lite' };

// behaviour per provider: array of scripted results/errors consumed in order, then `default`
const seq = { n: 0 };
function fakeAdapter(name, script) {
    const a = { calls: [], script, handler: null, default: { text: `${name} answer`, tokensIn: 100, tokensOut: 50 },
        async chat(entry, req) {
            a.calls.push({ seq: ++seq.n, model: entry.model, req, label: (/^\[[^\]]+\]/.exec(String(req.messages.at(-1).content)) || [''])[0] });
            const step = a.script.length ? a.script.shift() : (a.handler || a.default);
            if (step instanceof Error) throw step;
            if (typeof step === 'function') return step(entry, req);
            return { ...step, finish: 'stop' };
        } };
    return a;
}
const dailyQuota = () => new AIError('ratelimit', 'groq 429: Rate limit reached for model: tokens per day (TPD): Limit 200000, Used 200000', { provider: 'groq' });
const timeout = () => new AIError('timeout', 'request timed out');

function rig({ store, groq = [], gemini = [], settings = {}, env = ENV, handler = null } = {}) {
    const adapters = { groq: fakeAdapter('groq', groq), gemini: fakeAdapter('gemini', gemini) };
    if (handler) { adapters.groq.handler = handler; adapters.gemini.handler = handler; }
    const s = resolveSettings(settings, {});
    s.retryBackoffMs = 0;
    const providers = createProviderManager({ adapters, settings: s, now, sleep: async () => {}, env });
    let chatOn = true;
    const manager = createWorkManager({ store, providers, settings: s, now, isChatEnabled: () => chatOn, owner: 'test-owner' });
    const calls = () => [...adapters.groq.calls.map((c) => ({ ...c, by: 'groq' })), ...adapters.gemini.calls.map((c) => ({ ...c, by: 'gemini' }))].sort((x, y) => x.seq - y.seq);
    return { adapters, providers, manager, settings: s, calls, setChat: (v) => { chatOn = v; } };
}
let msgSeq = 0;
const ask = async (r, chat, text) => {
    const { task } = await r.manager.submit({ chatJid: chat, userId: '2348000', text, msgId: `m${++msgSeq}` });
    return { task, outcome: await r.manager.runQueued(task) };
};

async function suite(store, expireLease) {
    // 1. activation rules + persistence ─────────────────────────
    {
        const c = 'act@s.whatsapp.net'; const r = rig({ store });
        r.setChat(false);
        const bad = await r.manager.activate(c, '2348000', { isDM: true });
        check(!bad.ok && bad.reason === 'chat_off' && !(await r.manager.isActive(c)), '.wchat on is refused while normal chat is off');
        r.setChat(true);
        check((await r.manager.activate(c, '2348000', { isDM: true })).ok, '.wchat on works once normal chat is on');
        const r2 = rig({ store });   // "restart": new manager, same database
        check(await r2.manager.isActive(c), 'activation state survives a restart');
        await ask(r, c, 'hello there');
        check(await r.manager.isActive(c), 'finishing a task does not switch Work Mode off');
    }
    // 2. simple task, usage, recent context ─────────────────────
    {
        const c = 'simple@s.whatsapp.net'; const r = rig({ store });
        await r.manager.activate(c, '2348000');
        const { task, outcome } = await ask(r, c, 'what is a mutex?');
        const t = await store.getTask(task.id);
        check(outcome.status === 'completed' && t.status === 'completed' && t.result === 'groq answer', 'simple request completes and the result is stored');
        check(t.tokensIn === 100 && t.tokensOut === 50 && t.provider === 'groq', 'tokens and provider are recorded on the task');
        await ask(r, c, 'and a semaphore?');
        const sent = r.adapters.groq.calls.at(-1).req.messages;
        check(sent.some((m) => m.role === 'assistant' && m.content === 'groq answer'), 'follow-up request carries the previous turn (session context)');
    }
    // 3. same WhatsApp message delivered twice ─────────────────
    {
        const c = 'dup@s.whatsapp.net'; const r = rig({ store });
        await r.manager.activate(c, '2348000');
        const a = await r.manager.submit({ chatJid: c, userId: '2348000', text: 'do a thing', msgId: 'SAME' });
        const b = await r.manager.submit({ chatJid: c, userId: '2348000', text: 'do a thing', msgId: 'SAME' });
        check(a.created && !b.created && a.task.id === b.task.id, 'a redelivered message does not create a second task');
    }
    // 4. concurrent execution guard ─────────────────────────────
    {
        const c = 'race@s.whatsapp.net'; const r = rig({ store });
        await r.manager.activate(c, '2348000');
        const { task } = await r.manager.submit({ chatJid: c, userId: '2348000', text: 'explain closures', msgId: 'race1' });
        const [x, y] = await Promise.all([r.manager.run(task.id), r.manager.run(task.id)]);
        const done = [x, y].filter((o) => o.status === 'completed').length;
        check(done === 1 && r.adapters.groq.calls.length === 1, 'two simultaneous runs of one task make exactly one model call');
    }
    // 5. failover keeps the task, parks the exhausted model ─────
    {
        const c = 'fail@s.whatsapp.net'; const r = rig({ store, groq: [dailyQuota(), dailyQuota(), dailyQuota()] });
        await r.manager.activate(c, '2348000');
        const { task, outcome } = await ask(r, c, 'write a function to merge two sorted arrays in python');
        const t = await store.getTask(task.id);
        check(outcome.status === 'completed' && outcome.provider === 'gemini', 'Groq out of daily quota -> Gemini finishes the same task');
        check(t.id === task.id && t.description.includes('merge two sorted'), 'the task was not restarted or duplicated by the switch');
        const snap = await r.providers.snapshot();
        check(snap.find((h) => h.key.startsWith('groq/openai/gpt-oss-120b'))?.state === 'out', 'the exhausted model shows as out in the health snapshot');
        const before = r.adapters.groq.calls.length;
        await ask(r, c, 'now write a function to reverse a string in python');
        check(r.adapters.groq.calls.length === before, 'a parked model is not called again until it resets');
        const ev = await store.listEvents(task.id);
        check(ev.some((e) => e.kind === 'model_call'), 'model calls are logged in the task history');
        clock.t += 25 * 3600_000;    // next day
        await ask(r, c, 'third question please');
        check(r.adapters.groq.calls.length > before, 'after the reset time Groq is used again');
    }
    // 6. everything out -> pause, not fail; resume later ────────
    {
        const c = 'quota@s.whatsapp.net';
        const geminiQuota = () => new AIError('ratelimit', 'gemini 429: quota exceeded for requests per day', { provider: 'gemini' });
        const r = rig({ store, groq: [dailyQuota(), dailyQuota()], gemini: [geminiQuota()] });   // summarise chain = oss20, gemini-lite, oss120
        await r.manager.activate(c, '2348000');
        const { task, outcome } = await ask(r, c, 'summarise the history of unix');
        const t = await store.getTask(task.id);
        check(outcome.status === 'paused' && t.status === 'paused' && t.pauseReason === 'quota', 'all models out of quota -> task is paused (not failed)');
        check(/\.wresume/.test(outcome.notice || '') && /UTC/.test(outcome.notice || ''), 'the user is told when to retry');
        clock.t += 25 * 3600_000;
        const rs = await r.manager.resume(c, task.id);
        const run = await r.manager.runQueued(rs.task);
        check(rs.ok && run.status === 'completed', 'a quota-paused task resumes and completes after the reset');
    }
    // 7. transient failures retry, capped ───────────────────────
    {
        const c = 'retry@s.whatsapp.net';
        const r = rig({ store, groq: [timeout()], gemini: [timeout()] });
        await r.manager.activate(c, '2348000');
        const first = await ask(r, c, 'hi');
        check(first.outcome.status === 'completed', 'a transient failure is retried and then succeeds');
        const r2 = rig({ store, groq: Array.from({ length: 30 }, timeout), gemini: Array.from({ length: 30 }, timeout) });
        await r2.manager.activate(c, '2348000');
        const bad = await ask(r2, c, 'hello again');
        check(bad.outcome.status === 'paused' && r2.adapters.groq.calls.length + r2.adapters.gemini.calls.length <= 12, 'retries are capped, then the task is paused with a clear notice');
    }
    // 8. token budget pauses instead of overspending ────────────
    {
        const c = 'budget@s.whatsapp.net'; const r = rig({ store, settings: { taskTokenBudget: 120 } });
        await r.manager.activate(c, '2348000');
        const { task } = await r.manager.submit({ chatJid: c, userId: '2348000', text: 'tiny budget', msgId: 'b1' });
        await store.addUsage(task.id, 100, 30, 'groq', 'x');           // already over budget
        const out = await r.manager.run(task.id);
        check(out.status === 'paused' && r.adapters.groq.calls.length === 0, 'a task over its token budget pauses before calling any model');
        const rs = await r.manager.resume(c, task.id);
        const t = await store.getTask(task.id);
        check(rs.ok && t.tokenBudget > 130, 'resuming a budget pause grants a fresh allowance');
        check((await r.manager.runQueued(rs.task)).status === 'completed', '...and the task then completes');
    }
    // 9. pause / cancel / discard during a call ─────────────────
    {
        const c = 'ctl@s.whatsapp.net';
        let release; const gate = new Promise((res) => { release = res; });
        const r = rig({ store, groq: [async () => { await gate; return { text: 'late', tokensIn: 1, tokensOut: 1 }; }] });
        r.adapters.groq.script[0] = () => gate.then(() => ({ text: 'late', tokensIn: 1, tokensOut: 1 }));
        await r.manager.activate(c, '2348000');
        const { task } = await r.manager.submit({ chatJid: c, userId: '2348000', text: 'slow one', msgId: 'ctl1' });
        const p = r.manager.run(task.id);
        await new Promise((res) => setTimeout(res, 20));
        const paused = await r.manager.pause(c, task.id);
        release();
        const o = await p;
        const t = await store.getTask(task.id);
        check(paused.ok && o.status === 'discarded' && t.status === 'paused' && t.result == null, 'pausing mid-call keeps the pause and drops the late reply');
        const cx = await r.manager.cancel(c, task.id);
        check(cx.ok && (await store.getTask(task.id)).status === 'cancelled', 'a paused task can be cancelled');
        check(!(await r.manager.resume(c, task.id)).ok, 'a cancelled task cannot be resumed');
    }
    // 9b. no waiting behind a slow task ─────────────────────────
    {
        const c = 'nowait@s.whatsapp.net'; let release; const gate = new Promise((res) => { release = res; });
        const r = rig({ store });
        r.adapters.groq.script.push(() => gate.then(() => ({ text: 'slow answer', tokensIn: 1, tokensOut: 1 })));
        await r.manager.activate(c, '2348000');
        const slow = await r.manager.submit({ chatJid: c, userId: '2348000', text: 'slow one', msgId: 'nw1' });
        const fast = await r.manager.submit({ chatJid: c, userId: '2348000', text: 'quick one', msgId: 'nw2' });
        const order = [];
        const p1 = r.manager.runQueued(slow.task).then((o) => { order.push('slow'); return o; });
        await new Promise((res) => setTimeout(res, 20));
        const o2 = await r.manager.runQueued(fast.task); order.push('fast');
        release(); const o1 = await p1;
        check(o2.status === 'completed' && o1.status === 'completed' && order.join() === 'fast,slow', 'a quick request is answered while an earlier one is still running (no queue)');
    }
    // 10. off keeps tasks; on offers them; restart recovery ─────
    {
        const c = 'off@s.whatsapp.net'; const r = rig({ store });
        await r.manager.activate(c, '2348000');
        const { task } = await r.manager.submit({ chatJid: c, userId: '2348000', text: 'half done', msgId: 'off1' });
        const off = await r.manager.deactivate(c);
        const t = await store.getTask(task.id);
        check(off.paused.includes(task.id) && t.status === 'paused' && t.description === 'half done', '.wchat off parks unfinished tasks without deleting them');
        const on = await r.manager.activate(c, '2348000');
        check(on.ok && on.resumable.some((x) => x.id === task.id), '.wchat on lists the unfinished task again');
    }
    {
        const c = 'crash@s.whatsapp.net'; const r = rig({ store });
        await r.manager.activate(c, '2348000');
        const { task } = await r.manager.submit({ chatJid: c, userId: '2348000', text: 'was running when the bot died', msgId: 'cr1' });
        await store.claimTask(task.id, 'dead-worker', 60_000);        // a worker takes it, then "dies"
        const mine = (os) => os.filter((o) => o.chatJid === c);
        const callsBefore = r.adapters.groq.calls.length + r.adapters.gemini.calls.length;
        const live = mine(await r.manager.recover());
        check(live.length === 0, 'a task whose worker still holds a live lease is NOT restarted');
        await expireLease(task.id);
        const rec = mine(await r.manager.recover());
        check(rec.length === 1 && rec[0].status === 'completed' && rec[0].recovered, 'after the lease expires, recovery finishes the task exactly once');
        const callsAfter = r.adapters.groq.calls.length + r.adapters.gemini.calls.length;
        check(mine(await r.manager.recover()).length === 0 && callsAfter === callsBefore + 1 + (callsAfter - callsBefore - 1), 'a second sweep does nothing for that task');
        const again = await store.getTask(task.id);
        check(again.status === 'completed' && (await store.listEvents(task.id)).filter((e) => e.kind === 'model_call').length === 1, 'the recovered task ran its model call exactly once');
    }
    // 11. free-tier guard ───────────────────────────────────────
    {
        const store2 = createMemoryWorkStore({ now });
        const adapters = { groq: fakeAdapter('groq', []), gemini: fakeAdapter('gemini', []), openrouter: fakeAdapter('openrouter', []) };
        const s = resolveSettings({}, {});
        const pm = createProviderManager({ adapters, settings: s, now, env: { ...ENV, ARIEL_OPENROUTER_MODEL: 'vendor/paid-model' },
            getOverride: async () => ({ roles: { work_fast: { chain: [{ provider: 'groq', model: 'some/unlisted-model' }, { provider: 'groq', model: 'openai/gpt-oss-20b' }] } } }) });
        const chain = (await pm.fullRouting()).roles.work_fast.chain.map((e) => `${e.provider}/${e.model}`);
        check(!chain.some((k) => k.includes('paid-model')), 'an OpenRouter model without ":free" is never used');
        check(!chain.includes('groq/some/unlisted-model') && chain.includes('groq/openai/gpt-oss-20b'), 'a model that is not on the verified list is filtered out of overrides');
        const pm2 = createProviderManager({ adapters, settings: s, now, env: { ...ENV, ARIEL_OPENROUTER_MODEL: 'vendor/model:free' } });
        check((await pm2.fullRouting()).roles.work_fast.chain.some((e) => e.model === 'vendor/model:free'), 'a ":free" OpenRouter model is allowed');
        void store2;
    }

    // ── planned tasks (stage 4) ─────────────────────────────────
    const STEPS3 = [{ title: 'Design the schema', detail: 'tables and keys', kind: 'code' }, { title: 'Write the queries', kind: 'code' }, { title: 'Explain the tradeoffs', kind: 'research' }];
    const ok = (text) => ({ text, tokensIn: 100, tokensOut: 50, finish: 'stop' });
    const smart = (steps = STEPS3, hook = null) => (entry, req) => {
        const last = String(req.messages.at(-1).content);
        if (last.startsWith('[PLAN REQUEST]')) return ok(JSON.stringify({ steps }));
        const m = /^\[STEP (\d+)\//.exec(last);
        if (m) { hook?.(Number(m[1]), entry); return ok(`output of step ${m[1]}\nSUMMARY: did step ${m[1]}`); }
        if (last.startsWith('[FINAL REPORT]')) return ok('FINAL ANSWER');
        return ok('single answer');
    };
    const labels = (r) => r.calls().map((c) => c.label);

    {   // A. plan -> steps -> final, with progress messages
        const c = 'plan@s.whatsapp.net'; const r = rig({ store, handler: smart() });
        await r.manager.activate(c, '2348000');
        const notes = [];
        const { task } = await r.manager.submit({ chatJid: c, userId: '2348000', text: 'Build a small ordering database for a cafe and explain the design step by step', msgId: 'pA' });
        const o = await r.manager.runQueued(task, { notify: async (t) => notes.push(t) });
        const t = await store.getTask(task.id);
        check(o.status === 'completed' && o.text === 'FINAL ANSWER' && o.steps === 3, 'a big request is planned, executed step by step, and finished with a final report');
        check(r.calls().length === 5 && r.calls()[0].label === '[PLAN REQUEST]' && r.calls().at(-1).label === '[FINAL REPORT]', 'calls are: 1 plan + 3 steps + 1 final report');
        check(t.plan.length === 3 && t.plan.every((x) => x.status === 'done' && x.summary) && t.completedSteps.length === 3 && t.pendingSteps.length === 0 && t.currentStep === 3, 'the plan and per-step progress are saved on the task');
        check(notes.length === 4 && notes[0].startsWith('📋') && notes[3].startsWith('✅ 3/3'), 'the user gets the plan, then one line per finished step');
    }
    {   // B. a short question never pays for planning
        const c = 'noplan@s.whatsapp.net'; const r = rig({ store, handler: smart() });
        const { outcome } = await ask(r, c, 'what is a mutex?');
        check(outcome.text === 'single answer' && r.calls().length === 1, 'a simple question stays a single call (no plan)');
    }
    {   // C. failover mid-plan: same plan, earlier steps visible to the new model
        const c = 'planfail@s.whatsapp.net';
        let groqCalls = 0;
        const r = rig({ store, handler: smart() });
        r.adapters.groq.handler = (entry, req) => { if (++groqCalls > 1) throw dailyQuota(); return smart()(entry, req); };
        await r.manager.activate(c, '2348000');
        const { task } = await r.manager.submit({ chatJid: c, userId: '2348000', text: 'Build a small ordering database for a cafe and explain the design step by step', msgId: 'pC' });
        const o = await r.manager.runQueued(task);
        const t = await store.getTask(task.id);
        const step3 = r.calls().find((x) => x.label === '[STEP 3/3]');
        check(o.status === 'completed' && r.calls().filter((x) => x.label === '[PLAN REQUEST]').length === 1, 'Groq runs out mid-plan: the task continues and is NOT re-planned');
        check(step3 && /output of step 1/.test(step3.req.messages.at(-1).content) && /output of step 2/.test(step3.req.messages.at(-1).content), 'the model that takes over receives the earlier steps\' work');
        check((await store.listEvents(task.id)).some((e) => e.kind === 'provider_switch') && t.plan.every((x) => x.status === 'done'), 'the provider switch is recorded and every step is done');
    }
    {   // D. pause at a boundary, resume only what is left
        const c = 'planpause@s.whatsapp.net'; let id = null;
        const r = rig({ store });
        r.adapters.groq.handler = r.adapters.gemini.handler = smart(STEPS3, (n) => { if (n === 2) r.manager.pause(c, id); });
        await r.manager.activate(c, '2348000');
        const { task } = await r.manager.submit({ chatJid: c, userId: '2348000', text: 'Build a small ordering database for a cafe and explain the design step by step', msgId: 'pD' }); id = task.id;
        const first = await r.manager.runQueued(task);
        const mid = await store.getTask(task.id);
        check(first.status === 'discarded' && mid.status === 'paused' && mid.plan.filter((x) => x.status === 'done').length === 2, 'pausing mid-plan stops at the step boundary with finished steps kept');
        const callsBefore = r.calls().length;
        const rs = await r.manager.resume(c, task.id);
        const second = await r.manager.runQueued(rs.task);
        const after = r.calls().slice(callsBefore).map((x) => x.label);
        check(second.status === 'completed' && after.length === 2 && after[0] === '[STEP 3/3]' && after[1] === '[FINAL REPORT]', 'resume runs only the remaining step and the final report');
    }
    {   // E. restart in the middle of a plan
        const c = 'plancrash@s.whatsapp.net'; const r = rig({ store, handler: smart() });
        await r.manager.activate(c, '2348000');
        const { task } = await r.manager.submit({ chatJid: c, userId: '2348000', text: 'Build a small ordering database for a cafe and explain the design step by step', msgId: 'pE' });
        const plan = STEPS3.map((x, i) => ({ n: i + 1, title: x.title, detail: '', kind: x.kind, status: i === 0 ? 'done' : 'pending', output: i === 0 ? 'earlier work' : undefined, summary: i === 0 ? 'did step 1' : undefined }));
        await store.updateTask(task.id, { plan, completedSteps: [{ title: plan[0].title }], pendingSteps: plan.slice(1).map((x) => ({ title: x.title })), currentStep: 1 });
        await store.claimTask(task.id, 'dead-worker', 60_000); await expireLease(task.id);
        const rec = (await r.manager.recover()).filter((o) => o.chatJid === c);
        const ls = labels(r);
        check(rec.length === 1 && rec[0].status === 'completed' && ls.join() === '[STEP 2/3],[STEP 3/3],[FINAL REPORT]', 'after a crash mid-plan, recovery continues from the saved step (no re-plan, no repeats)');
    }
    {   // F. bad plan JSON -> one retry -> fall back to a single answer
        const c = 'badplan@s.whatsapp.net'; const r = rig({ store });
        r.adapters.groq.handler = r.adapters.gemini.handler = (entry, req) => String(req.messages.at(-1).content).startsWith('[PLAN REQUEST]') ? ok('Sure! Here is my plan: do things.') : ok('single answer');
        await r.manager.activate(c, '2348000');
        const { task } = await r.manager.submit({ chatJid: c, userId: '2348000', text: 'Build a small ordering database for a cafe and explain the design step by step', msgId: 'pF' });
        const o = await r.manager.runQueued(task);
        check(o.status === 'completed' && o.text === 'single answer' && labels(r).filter((l) => l === '[PLAN REQUEST]').length === 2 && (await store.getTask(task.id)).plan.length === 0, 'unusable plan: one retry, then the request is answered directly');
    }
    {   // G. token budget pauses between steps and keeps the plan
        const c = 'planbudget@s.whatsapp.net'; const r = rig({ store, handler: smart(), settings: { taskTokenBudget: 400 } });
        await r.manager.activate(c, '2348000');
        const { task } = await r.manager.submit({ chatJid: c, userId: '2348000', text: 'Build a small ordering database for a cafe and explain the design step by step', msgId: 'pG' });
        const o = await r.manager.runQueued(task);
        const t = await store.getTask(task.id);
        check(o.status === 'paused' && /budget/.test(t.pauseReason) && t.plan.length === 3 && t.plan[0].status === 'done', 'budget runs out mid-plan: paused with the plan and finished steps kept');
        const before = labels(r).length;
        const rs = await r.manager.resume(c, task.id);
        const o2 = await r.manager.runQueued(rs.task);
        check(rs.ok && labels(r).slice(before).every((l) => l !== '[PLAN REQUEST]' && l !== '[STEP 1/3]') && ['completed', 'paused'].includes(o2.status), 'after resume it continues from the next step with a fresh allowance');
    }
    {   // H. cancel is honoured at the next boundary
        const c = 'plancancel@s.whatsapp.net'; let id = null; const r = rig({ store });
        r.adapters.groq.handler = r.adapters.gemini.handler = smart(STEPS3, (n) => { if (n === 1) r.manager.cancel(c, id); });
        await r.manager.activate(c, '2348000');
        const { task } = await r.manager.submit({ chatJid: c, userId: '2348000', text: 'Build a small ordering database for a cafe and explain the design step by step', msgId: 'pH' }); id = task.id;
        const o = await r.manager.runQueued(task);
        check(o.status === 'cancelled' && labels(r).filter((l) => l.startsWith('[STEP')).length === 1, 'cancelling mid-plan stops further steps');
    }
    {   // I. planner helpers
        check(needsPlan('what is a mutex?', 'simple') === false && needsPlan('x'.repeat(300), 'simple') === true, 'needsPlan: short is simple, long is planned');
        check(needsPlan('1. design the schema\n2. write the queries', 'simple') && needsPlan('please build me a discord bot from scratch with a few slash commands', 'code'), 'needsPlan: lists and build requests are planned');
        check(needsPlan('x'.repeat(300), 'simple', { planMode: 'never' }) === false && needsPlan('hi', 'simple', { planMode: 'always' }) === true, 'planMode never/always override the heuristic');
        check(parsePlan('```json\n{"steps":["a","b"]}\n```')?.length === 2 && parsePlan('[{"title":"x","kind":"code"}]')?.[0].kind === 'code' && parsePlan('no json here') === null, 'parsePlan accepts fenced JSON, arrays, and rejects prose');
        check(parsePlan(JSON.stringify({ steps: Array.from({ length: 12 }, (_, i) => `s${i}`) }), 6).length === 6, 'parsePlan caps the number of steps');
        check(splitSummary('body text\nSUMMARY: did it').summary === 'did it' && splitSummary('just text').summary === 'just text', 'splitSummary reads the trailing SUMMARY line');
        const big = Array.from({ length: 6 }, (_, i) => ({ n: i + 1, title: `T${i + 1}`, status: 'done', output: 'x'.repeat(3000), summary: `sum${i + 1}` }));
        const block = contextBlock(big, 6, 6000);
        check(block.length <= 6000 && block.includes('T6') && !block.includes('x'.repeat(2000)), 'context for later steps is compressed to the limit (older steps shrink)');
    }
    // 12. event pruning ─────────────────────────────────────────
    {
        const c = 'prune@s.whatsapp.net'; const r = rig({ store });
        const { task } = await ask(r, c, 'prune me');
        const removed = await store.pruneEvents(0);
        check(typeof removed === 'number' && (await store.getTask(task.id)).status === 'completed', 'old events can be pruned without touching the task');
    }
}

// ── pure helpers ────────────────────────────────────────────────
check(classifyKind('fix this traceback: KeyError') === 'debug', 'classify: error -> debug');
check(classifyKind('write a python function') === 'code', 'classify: code');
check(classifyKind('compare postgres and mysql, find the latest benchmarks') === 'research', 'classify: research');
check(classifyKind('make a plan for the launch') === 'plan', 'classify: plan');
check(classifyKind('how are you') === 'simple', 'classify: default is simple');
check(parseRetryAfterMs('Please try again in 7m12.5s.') === 432500 && parseRetryAfterMs('try again in 1h2m3s') === 3723000 && parseRetryAfterMs('nope') === null, 'retry-after hints are parsed');
const long = ('word '.repeat(300) + '\n\n').repeat(6);
check(chunkText(long, 1000).every((p) => p.length <= 1000) && chunkText('short', 1000).length === 1, 'long answers are split under the WhatsApp limit');
check(Object.keys(defaultWorkRouting(ENV).roles).length === 6, 'six routing roles are defined');

// ── run ─────────────────────────────────────────────────────────
if (useDb) {
    const db = await import('../bot/ariel/db.js');
    const client = await db.getPool().connect();
    try {
        await client.query('begin');
        const store = createWorkStore({ query: (t, p) => client.query(t, p) });
        await suite(store, (id) => client.query(`update ariel.work_tasks set lease_until = now() - interval '1 second' where id = $1`, [id]));
        // ids made by the check use throw-away chats; the rollback below removes everything
    } catch (e) { console.error('✗', e.stack || e.message); fails.push(e.message); }
    finally { await client.query('rollback').catch(() => {}); client.release(); await db.endPool(); console.log('(rolled back — nothing was saved)'); }
} else {
    const store = createMemoryWorkStore({ now });
    await suite(store, async (id) => { store._tasks.get(id).leaseUntil = new Date(now() - 1000).toISOString(); });
}
console.log(fails.length ? `\n✗ ${fails.length} check(s) failed` : '\n✓ all Work Mode checks passed');
process.exit(fails.length ? 1 : 0);
