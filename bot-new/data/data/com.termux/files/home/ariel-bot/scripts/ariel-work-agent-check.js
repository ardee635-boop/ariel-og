#!/usr/bin/env node
// Work Mode tool-loop checks (offline: in-memory store, scripted fake models, temp workspace).
//   node scripts/ariel-work-agent-check.js
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { AIError } from '../bot/ariel/providers/index.js';
import { createMemoryWorkStore } from '../bot/wmode/store_memory.js';
import { createProviderManager } from '../bot/wmode/providers.js';
import { createWorkManager } from '../bot/wmode/manager.js';
import { resolveSettings } from '../bot/wmode/settings.js';
import { needsTools, parseAction, verifiedFooter } from '../bot/wmode/agent.js';
import { createSandbox } from '../bot/wmode/tools/sandbox.js';
import { createToolRegistry } from '../bot/wmode/tools/index.js';
import { registerFsTools } from '../bot/wmode/tools/fs_tools.js';
import { registerCmdTools } from '../bot/wmode/tools/cmd_tools.js';

const fails = [];
const check = (ok, what) => { console.log(`${ok ? '✓' : '✗'} ${what}`); if (!ok) fails.push(what); };
const J = (o) => JSON.stringify(o);
const tool = (name, args) => J({ tool: name, args });
const fin = (text) => J({ final: text });

function rig({ settings = {}, store = createMemoryWorkStore(), groq = [], replies = [], ws } = {}) {
    const log = { prompts: [] };
    const mk = (name) => ({ calls: [], script: name === 'groq' ? groq : [],
        async chat(entry, req) {
            this.calls.push({ model: entry.model, req });
            const step = this.script.length ? this.script.shift() : null;
            if (step instanceof Error) throw step;
            const text = step?.text ?? replies.shift() ?? fin('(no scripted reply)');
            log.prompts.push(String(req.messages.at(-1).content));
            return { text, tokensIn: 100, tokensOut: 50, finish: 'stop' };
        } });
    const adapters = { groq: mk('groq'), gemini: mk('gemini') };
    const s = resolveSettings({ toolMode: 'auto', ...settings }, {}); s.retryBackoffMs = 0; s.workspaceDir = ws;
    const providers = createProviderManager({ adapters, settings: s, sleep: async () => {}, env: { GEMINI_FLASH_MODEL: 'g-flash', GEMINI_LITE_MODEL: 'g-lite' } });
    const sandbox = createSandbox({ root: ws });
    const tools = registerCmdTools(registerFsTools(createToolRegistry({ settings: s }), { sandbox, settings: s }), { sandbox, settings: s });
    const manager = createWorkManager({ store, providers, settings: s, tools, owner: `o${Math.random()}`, isChatEnabled: () => true });
    return { store, manager, adapters, log, tools, settings: s, replies, ws };
}
let mid = 0;
const CHAT = '234800@s.whatsapp.net';
async function ask(r, text) {
    await r.manager.activate(CHAT, 'u1', {});
    const { task } = await r.manager.submit({ chatJid: CHAT, userId: 'u1', text, msgId: `m${++mid}` });
    const notes = [];
    return { task, notes, outcome: await r.manager.runQueued(task, { notify: (t) => notes.push(t) }) };
}
const tmp = () => fs.mkdtempSync(path.join(os.tmpdir(), 'wm-agent-'));

// ── pure helpers ──
check(needsTools('create hello.js that prints hi') && needsTools('run the tests in the workspace') && !needsTools('what is a closure in JS?'), 'needsTools routes file/work requests only');
check(!needsTools('edit file x', { toolMode: 'never' }) && needsTools('hi', { toolMode: 'always' }), 'toolMode never/always');
check(parseAction('```json\n{"tool":"list_dir","args":{"path":"."}}\n```')?.tool === 'list_dir' && parseAction('{"final":"done"}')?.final === 'done' && parseAction('sure thing!') === null, 'parseAction: fenced, final, prose');
check(/created: a\.js/.test(verifiedFooter([{ n: 1, tool: 'create_file', ok: true, meta: { path: 'a.js' } }])) && /unverified/.test(verifiedFooter([{ n: 1, tool: 'create_file', ok: true, meta: { path: 'a.js' } }])), 'footer: unverified changes flagged');
check(/PASSED/.test(verifiedFooter([{ n: 1, tool: 'edit_file', ok: true, meta: { path: 'a' } }, { n: 2, tool: 'run_tests', ok: true, meta: { passed: true, exitCode: 0 } }])) && /changed after/.test(verifiedFooter([{ n: 1, tool: 'run_tests', ok: true, meta: { passed: true, exitCode: 0 } }, { n: 2, tool: 'edit_file', ok: true, meta: { path: 'a' } }])), 'footer: pass, and stale pass after later edit');

// ── 1. plain question never gets the loop ──
{
    const ws = tmp(); const r = rig({ ws, replies: ['A closure is a function plus its scope.'] });
    const { outcome } = await ask(r, 'what is a closure?');
    check(outcome.status === 'completed' && r.adapters.groq.calls.length + r.adapters.gemini.calls.length === 1 && !outcome.text.includes('checked by Ariel'), 'simple question: one plain call, no loop');
}

// ── 2. create + read + final, verified footer ──
{
    const ws = tmp(); const r = rig({ ws, replies: [
        tool('list_dir', { path: '.' }),
        tool('create_file', { path: 'hello.js', content: "console.log('hi');\n" }),
        tool('run_command', { command: 'node --check hello.js' }),
        fin('Created hello.js.'),
    ] });
    const { task, outcome, notes } = await ask(r, 'create hello.js that logs hi');
    check(outcome.status === 'completed' && fs.readFileSync(path.join(ws, 'hello.js'), 'utf8').includes('hi'), 'loop creates the file on disk');
    check(/created: hello\.js/.test(outcome.text) && /last command: PASSED/.test(outcome.text), 'final answer carries tool-verified footer');
    const t = await r.manager.getTask(task.id);
    check(t.status === 'completed' && t.agent.turns.length === 3 && t.tokensIn >= 400, 'turns + tokens persisted');
    check(notes.some((n) => n.includes('create_file')) && (await r.manager.listEvents(task.id)).filter((e) => e.kind === 'tool').length === 3, 'progress messages + tool events logged');
}

// ── 3. approval: nothing runs until approved ──
{
    const ws = tmp(); const marker = path.join(ws, 'ran.txt');
    const r = rig({ ws, replies: [
        tool('create_file', { path: 'w.js', content: "require('fs').writeFileSync('ran.txt','yes')" }),
        tool('run_command', { command: 'node w.js' }),
        fin('Ran it.'),
    ] });
    const { task, outcome } = await ask(r, 'create w.js and run it');
    const t1 = await r.manager.getTask(task.id);
    check(outcome.status === 'waiting_approval' && t1.status === 'waiting_approval' && !fs.existsSync(marker), 'run_command pauses for approval, nothing executed');
    check(outcome.notice.includes(`.wapprove ${task.id}`) && outcome.notice.includes('node w.js'), 'approval notice names the action and the commands');
    check((await r.manager.recover()).length === 0, 'recovery sweep does not touch a waiting task');
    const a = await r.manager.approve(CHAT, task.id);
    const o2 = await r.manager.runQueued(a.task);
    check(a.ok && o2.status === 'completed' && fs.readFileSync(marker, 'utf8') === 'yes', 'approve -> command runs -> loop continues to the end');
    check((await r.manager.approve(CHAT, task.id)).ok === false, 'cannot approve twice');
}

// ── 4. deny: model is told, can choose another way ──
{
    const ws = tmp(); const r = rig({ ws, replies: [
        tool('create_file', { path: 'x.txt', content: 'x' }),
        tool('delete_file', { path: 'x.txt' }),
        fin('Left the file in place.'),
    ] });
    const { task } = await ask(r, 'create x.txt then delete the file x.txt');
    const d = await r.manager.deny(CHAT, task.id);
    const o = await r.manager.runQueued(d.task);
    check(d.ok && o.status === 'completed' && fs.existsSync(path.join(ws, 'x.txt')), 'denied delete: file still there, task finishes');
    check(r.log.prompts.at(-1).includes('DENIED by the user') && /1 action\(s\) you denied/.test(o.text), 'model saw the denial; footer reports it');
}

// ── 5. restart while waiting for approval ──
{
    const ws = tmp(); const store = createMemoryWorkStore();
    const r1 = rig({ ws, store, replies: [tool('run_tests', {})] });
    fs.writeFileSync(path.join(ws, 'a.test.js'), "import t from 'node:test'; t('x', () => {});");
    const { task } = await ask(r1, 'run the tests in the workspace');
    const r2 = rig({ ws, store, replies: [fin('Tests ran.')] });      // "restarted bot": new manager, same store
    check((await r2.manager.getTask(task.id)).status === 'waiting_approval' && (await r2.manager.recover()).length === 0, 'waiting state survives a restart');
    const a = await r2.manager.approve(CHAT, task.id);
    const o = await r2.manager.runQueued(a.task);
    check(o.status === 'completed' && /tests: PASSED/.test(o.text), 'approve after restart runs real tests, footer says PASSED');
}

// ── 6. provider failover mid-loop keeps the history ──
{
    const ws = tmp();
    const daily = () => new AIError('ratelimit', 'groq 429: tokens per day (TPD): Limit 200000, Used 200000', { provider: 'groq' });
    const r = rig({ ws, groq: [{ text: tool('create_file', { path: 'f.txt', content: 'one' }) }, daily(), daily(), daily()], replies: [fin('Done on the second provider.')] });
    const { outcome } = await ask(r, 'create f.txt containing one');
    check(outcome.status === 'completed' && r.adapters.gemini.calls.length >= 1, 'second provider finished the task');
    check(r.adapters.gemini.calls.at(-1).req.messages.at(-1).content.includes('create_file') && /created: f\.txt/.test(outcome.text) && fs.readFileSync(path.join(ws, 'f.txt'), 'utf8') === 'one', 'new provider got the earlier tool result; nothing redone');
}

// ── 7. step limit pauses; resume grants more ──
{
    const ws = tmp(); const r = rig({ ws, settings: { agentMaxSteps: 3 }, replies: [tool('list_dir', {}), tool('list_dir', {}), tool('list_dir', {}), tool('list_dir', {}), fin('Enough looking.')] });
    const { task, outcome } = await ask(r, 'list the files in the workspace folder');
    check(outcome.status === 'paused' && /step limit/.test(outcome.notice), 'step limit pauses the task');
    const res = await r.manager.resume(CHAT, task.id);
    const o2 = await r.manager.runQueued(res.task);
    check(res.ok && o2.status === 'completed', 'resume gives another batch and the task finishes');
}

// ── 8. bad model output ──
{
    const ws = tmp(); const r = rig({ ws, replies: ['I will just do it.', 'No really.'] });
    const { outcome } = await ask(r, 'create nope.js');
    check(outcome.status === 'completed' && /not answer in the tool format/.test(outcome.text) && !fs.existsSync(path.join(ws, 'nope.js')), 'two non-JSON replies: finished with an honest warning');
    const r2 = rig({ ws: tmp(), replies: ['hmm', tool('nope_tool', {}), tool('list_dir', {}), fin('ok')] });
    const o2 = (await ask(r2, 'list the files in the workspace')).outcome;
    check(o2.status === 'completed' && r2.log.prompts.some((p) => p.includes('unknown tool')), 'invalid reply and unknown tool are fed back; loop recovers');
}

// ── 9. cancel while waiting ──
{
    const ws = tmp(); const r = rig({ ws, replies: [tool('run_command', { command: 'node x.js' })] });
    fs.writeFileSync(path.join(ws, 'x.js'), '1');
    const { task } = await ask(r, 'run x.js in the workspace');
    const c = await r.manager.cancel(CHAT, task.id);
    check(c.ok && (await r.manager.getTask(task.id)).status === 'cancelled', 'waiting task can be cancelled');
}

// ── 10. budget still applies inside the loop ──
{
    const ws = tmp(); const r = rig({ ws, settings: { taskTokenBudget: 400 }, replies: [tool('list_dir', {}), tool('list_dir', {}), tool('list_dir', {}), fin('x')] });
    const { outcome } = await ask(r, 'list the files in the workspace');
    check(outcome.status === 'paused' && /budget/.test(outcome.notice), 'token budget pauses the loop instead of overspending');
}

console.log(fails.length ? `\n${fails.length} FAILED` : '\nall agent checks passed');
process.exit(fails.length ? 1 : 0);
