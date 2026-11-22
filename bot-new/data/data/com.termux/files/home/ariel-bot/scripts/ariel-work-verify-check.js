#!/usr/bin/env node
// Work Mode stage 7 checks: verification gate, unbacked claims, independent review (offline, scripted models).
//   node scripts/ariel-work-verify-check.js
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { AIError } from '../bot/ariel/providers/index.js';
import { createMemoryWorkStore } from '../bot/wmode/store_memory.js';
import { createProviderManager } from '../bot/wmode/providers.js';
import { createWorkManager } from '../bot/wmode/manager.js';
import { resolveSettings } from '../bot/wmode/settings.js';
import { codeState, needsCheckBeforeFinal, unbackedClaims, reviewTarget, parseReview, verifyLines, buildReviewMessages } from '../bot/wmode/verify.js';
import { createSandbox } from '../bot/wmode/tools/sandbox.js';
import { createToolRegistry } from '../bot/wmode/tools/index.js';
import { registerFsTools } from '../bot/wmode/tools/fs_tools.js';
import { registerCmdTools } from '../bot/wmode/tools/cmd_tools.js';

const fails = [];
const check = (ok, what) => { console.log(`${ok ? '✓' : '✗'} ${what}`); if (!ok) fails.push(what); };
const J = JSON.stringify;
const tool = (name, args) => J({ tool: name, args });
const fin = (text) => J({ final: text });
const REVIEW_OK = J({ verdict: 'ok', issues: [] });

// Groq answers the author role (work_code); Gemini answers the review role. `groq` scripts the author, `gemini` the reviewer.
function rig({ settings = {}, groq = [], gemini = [], ws } = {}) {
    const mk = (script) => ({ calls: [], script,
        async chat(entry, req) {
            this.calls.push({ model: entry.model, req });
            const step = this.script.length ? this.script.shift() : { text: fin('(no scripted reply)') };
            if (step instanceof Error) throw step;
            return { text: step.text ?? step, tokensIn: 100, tokensOut: 50, finish: 'stop' };
        } });
    const adapters = { groq: mk(groq), gemini: mk(gemini) };
    const s = resolveSettings({ toolMode: 'auto', ...settings }, {}); s.retryBackoffMs = 0; s.workspaceDir = ws;
    const providers = createProviderManager({ adapters, settings: s, sleep: async () => {}, env: { GEMINI_FLASH_MODEL: 'g-flash', GEMINI_LITE_MODEL: 'g-lite' } });
    const sandbox = createSandbox({ root: ws });
    const tools = registerCmdTools(registerFsTools(createToolRegistry({ settings: s }), { sandbox, settings: s }), { sandbox, settings: s });
    const manager = createWorkManager({ store: createMemoryWorkStore(), providers, settings: s, tools, owner: `o${Math.random()}`, isChatEnabled: () => true });
    return { manager, adapters };
}
const CHAT = '234800@s.whatsapp.net'; let mid = 0;
async function ask(r, text) {
    await r.manager.activate(CHAT, 'u1', {});
    const { task } = await r.manager.submit({ chatJid: CHAT, userId: 'u1', text, msgId: `m${++mid}` });
    return { task, outcome: await r.manager.runQueued(task, { notify: () => {} }) };
}
const tmp = () => fs.mkdtempSync(path.join(os.tmpdir(), 'wm-verify-'));
const W = (p, extra = {}) => ({ n: 1, tool: 'create_file', ok: true, args: { path: p, content: 'x' }, meta: { path: p }, ...extra });
const RUN = (ok, n = 2) => ({ n, tool: 'run_command', ok: true, args: { command: 'node --check a.js' }, result: ok ? '' : 'SyntaxError', meta: { exitCode: ok ? 0 : 1 } });

// ── pure helpers ──
check(codeState([W('a.js')]).changed && !codeState([W('a.js')]).checked, 'codeState: code written, not checked');
check(!codeState([W('notes.md')]).changed && !codeState([W('a.txt')]).changed, 'codeState: markdown/text do not count as code');
check(codeState([W('a.js'), RUN(true)]).passing && !codeState([W('a.js'), RUN(false)]).passing, 'codeState: pass vs fail after the write');
check(!codeState([RUN(true, 1), W('a.js', { n: 2 })]).checked, 'codeState: a run BEFORE the last write does not count');
check(needsCheckBeforeFinal([W('a.js')], { canRun: true }) && !needsCheckBeforeFinal([W('a.js')], { canRun: false }) && !needsCheckBeforeFinal([W('a.js')], { canRun: true, nudges: 1 }) && !needsCheckBeforeFinal([W('a.js'), RUN(true)], { canRun: true }), 'needsCheckBeforeFinal: only when a check is possible, unrun, and nudges remain');
check(unbackedClaims([W('a.js')], 'All tests pass.').length === 1 && unbackedClaims([W('a.js'), RUN(true)], 'All tests pass.').length === 0 && unbackedClaims([W('a.js')], 'Created a.js.').length === 0, 'unbackedClaims: only success words with no passing run');
check(/FAILED/.test(unbackedClaims([W('a.js'), RUN(false)], 'It works as expected.')[0] || ''), 'unbackedClaims: says FAILED when the last check failed');
check(parseReview('```json\n{"verdict":"concerns","issues":["off by one"]}\n```')?.issues[0] === 'off by one' && parseReview(REVIEW_OK)?.verdict === 'ok', 'parseReview: fenced concerns and plain ok');
check(parseReview('{"verdict":"concerns","issues":[]}') === null && parseReview('looks fine') === null && parseReview('{"verdict":"maybe"}') === null, 'parseReview: unusable replies are rejected, not guessed');
check(reviewTarget([W('a.js')]) && !reviewTarget([W('notes.md')]) && !reviewTarget([]), 'reviewTarget: code writes only');
{
    const m = buildReviewMessages({ description: 'make a.js' }, [W('a.js', { args: { path: 'a.js', content: 'const answer = 42;' } }), RUN(false)], 'Done');
    check(m[1].content.includes('const answer = 42;') && m[1].content.includes('FAILED') && !m[1].content.includes('SECRET'), 'review prompt shows the code and the real check result');
}
check(verifyLines({ review: { skipped: 'no free quota left' } })[0].includes('skipped') && /same model/.test(verifyLines({ review: { verdict: 'ok', issues: [], by: 'groq/x', sameFamily: true } })[0]), 'verifyLines: skipped and same-model wording');

// ── 1. nudge: final without a run sends the model back once ──
{
    const ws = tmp();
    const r = rig({ ws, groq: [tool('create_file', { path: 'a.js', content: "console.log('a');\n" }), fin('Created a.js.'), tool('run_command', { command: 'node --check a.js' }), fin('Created a.js and checked its syntax.')], gemini: [REVIEW_OK] });
    const { task, outcome } = await ask(r, 'create a.js that logs a');
    check(outcome.status === 'completed' && /last command: PASSED/.test(outcome.text) && /asked for a check/.test(outcome.text), 'unrun code: model sent back, ran a check, footer says PASSED');
    check(r.adapters.groq.calls.at(-1).req.messages.at(-1).content.includes('(Ariel) You changed code'), 'the nudge reached the model in its prompt');
    check((await r.manager.listEvents(task.id)).some((e) => e.kind === 'verify_nudge'), 'nudge logged as an event');
}

// ── 2. nudged only once: a model that insists is not looped forever, and is flagged ──
{
    const ws = tmp();
    const r = rig({ ws, groq: [tool('create_file', { path: 'a.js', content: 'x=1' }), fin('Done, all tests pass.'), fin('Done, all tests pass.')], gemini: [REVIEW_OK] });
    const { outcome } = await ask(r, 'create a.js');
    check(outcome.status === 'completed' && /not run|unverified/.test(outcome.text) && /unbacked claim/.test(outcome.text), 'insisting model: finishes, flagged unverified AND unbacked claim');
}

// ── 3. docs-only change: no nudge, no review ──
{
    const ws = tmp();
    const r = rig({ ws, groq: [tool('create_file', { path: 'notes.md', content: '# hi' }), fin('Wrote notes.md.')] });
    const { outcome } = await ask(r, 'create notes.md with a heading');
    check(outcome.status === 'completed' && !/asked for a check|independent review/.test(outcome.text) && r.adapters.gemini.calls.length === 0, 'markdown only: no nudge, no review call');
}

// ── 4. independent review ──
{
    const ws = tmp();
    const r = rig({ ws, groq: [tool('create_file', { path: 'a.js', content: "console.log('a');\n" }), tool('run_command', { command: 'node --check a.js' }), fin('Created a.js.')], gemini: [REVIEW_OK] });
    const { task, outcome } = await ask(r, 'create a.js that logs a');
    check(/independent review by gemini\/g-flash: no problems found/.test(outcome.text), 'review by a different provider is named in the footer');
    check(r.adapters.gemini.calls.length === 1 && r.adapters.gemini.calls[0].req.messages[1].content.includes("console.log('a')"), 'reviewer saw the written code');
    const ev = (await r.manager.listEvents(task.id)).find((e) => e.kind === 'review');
    check(ev?.data?.verdict === 'ok' && ev.data.by === 'gemini/g-flash', 'review logged as an event with verdict and reviewer');
}
{
    const ws = tmp();
    const r = rig({ ws, groq: [tool('create_file', { path: 'a.js', content: 'x' }), tool('run_command', { command: 'node --check a.js' }), fin('Done.')], gemini: [J({ verdict: 'concerns', issues: ['does not log anything', 'no error handling'] })] });
    const { outcome } = await ask(r, 'create a.js');
    check(outcome.status === 'completed' && /raised 2 concern/.test(outcome.text) && outcome.text.includes('does not log anything'), 'concerns are shown to the user; task still completes');
}

// ── 5. review can never break or pause a task ──
{
    const ws = tmp();
    const down = () => new AIError('ratelimit', 'gemini 429: quota exceeded', { provider: 'gemini' });
    const r = rig({ ws, groq: [tool('create_file', { path: 'a.js', content: 'x=1' }), tool('run_command', { command: 'node --check a.js' }), fin('Done.'), { text: REVIEW_OK }], gemini: [down(), down(), down(), down(), down(), down()] });
    const { outcome } = await ask(r, 'create a.js');
    check(outcome.status === 'completed' && /independent review by groq\/.*same model as the author/.test(outcome.text), 'Gemini out of quota: Groq reviews, and the footer admits it is the same model');
}
{
    const ws = tmp();
    const down = (p) => () => new AIError('ratelimit', `${p} 429: quota exceeded`, { provider: p });
    const r = rig({ ws, groq: [tool('create_file', { path: 'a.js', content: 'x=1' }), tool('run_command', { command: 'node --check a.js' }), fin('Done.'), ...Array.from({ length: 12 }, down('groq'))], gemini: Array.from({ length: 12 }, down('gemini')) });
    const { outcome } = await ask(r, 'create a.js');
    check(outcome.status === 'completed' && /Done\./.test(outcome.text) && /review skipped \((no free quota left|reviewer unavailable)\)/.test(outcome.text), 'every reviewer provider down: task still completes, review reported as skipped');
}
{
    const ws = tmp();
    const r = rig({ ws, groq: [tool('create_file', { path: 'a.js', content: 'x=1' }), tool('run_command', { command: 'node --check a.js' }), fin('Done.')], gemini: ['not json at all'] });
    const { outcome } = await ask(r, 'create a.js');
    check(outcome.status === 'completed' && /review skipped \(reviewer reply was not usable\)/.test(outcome.text), 'garbled review is reported as skipped, not as approval');
}
{
    const ws = tmp();
    const r = rig({ ws, settings: { reviewMinTokens: 1e9 }, groq: [tool('create_file', { path: 'a.js', content: 'x=1' }), tool('run_command', { command: 'node --check a.js' }), fin('Done.')] });
    const { outcome } = await ask(r, 'create a.js');
    check(outcome.status === 'completed' && /review skipped \(token budget nearly used\)/.test(outcome.text) && r.adapters.gemini.calls.length === 0, 'low budget: review skipped, no extra call, no pause');
}

// ── 6. switches ──
{
    const ws = tmp();
    const r = rig({ ws, settings: { review: false }, groq: [tool('create_file', { path: 'a.js', content: 'x=1' }), tool('run_command', { command: 'node --check a.js' }), fin('Done.')] });
    const { outcome } = await ask(r, 'create a.js');
    check(outcome.status === 'completed' && r.adapters.gemini.calls.length === 0 && !/independent review/.test(outcome.text), 'review:false makes no review call');
    const ws2 = tmp();
    const r2 = rig({ ws: ws2, settings: { verify: false }, groq: [tool('create_file', { path: 'a.js', content: 'x=1' }), fin('Done, all tests pass.')] });
    const o2 = (await ask(r2, 'create a.js')).outcome;
    check(o2.status === 'completed' && !/asked for a check|unbacked|independent review/.test(o2.text) && /unverified/.test(o2.text), 'verify:false: stage 7 is off; the older unverified footer remains');
}

// ── 7. survives a provider switch: the review is not repeated after a restart-style resume ──
{
    const ws = tmp();
    const r = rig({ ws, groq: [tool('create_file', { path: 'a.js', content: 'x=1' }), tool('run_command', { command: 'node --check a.js' }), fin('Done.')], gemini: [REVIEW_OK] });
    const { task } = await ask(r, 'create a.js');
    const t = await r.manager.getTask(task.id);
    check(t.agent.reviewed === true && r.adapters.gemini.calls.length === 1, 'review state saved on the task (reviewed once)');
}

console.log(fails.length ? `\n${fails.length} FAILED` : '\nall verify checks passed');
process.exit(fails.length ? 1 : 0);
