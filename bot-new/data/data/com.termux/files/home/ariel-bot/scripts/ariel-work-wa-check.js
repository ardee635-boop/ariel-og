#!/usr/bin/env node
// Work Mode stage 8 checks: the WhatsApp interface (offline: fake send, in-memory store, scripted models).
//   node scripts/ariel-work-wa-check.js
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
import { parseWorkCommand, toWhatsApp, chunkMessage, createProgress, helpText, formatTask, formatLog, formatTaskList, WORK_COMMANDS, createWorkInterface } from '../bot/wmode/wa.js';

const fails = [];
const check = (ok, what) => { console.log(`${ok ? '✓' : '✗'} ${what}`); if (!ok) fails.push(what); };
const J = JSON.stringify;
const tool = (name, args) => J({ tool: name, args });
const fin = (text) => J({ final: text });

// ── pure: command parsing ──
{
    const p = parseWorkCommand('.WApprove  #12');
    check(p.isCmd && p.cmd === '.wapprove' && p.id === 12, 'parse: case, spaces, #id');
    check(parseWorkCommand('.wtask 3').cmd === '.wtask' && parseWorkCommand('.wtasks').cmd === '.wtasks', 'parse: .wtask and .wtasks are different commands');
    check(!parseWorkCommand('hello').isCmd && !parseWorkCommand('.chat on').isCmd && parseWorkCommand('.wchat on').arg === 'on', 'parse: plain text and normal commands are not Work commands');
}

// ── pure: WhatsApp formatting ──
{
    check(toWhatsApp('# Title\nSome **bold** and __also__') === '*Title*\nSome *bold* and *also*', 'format: headings and bold become WhatsApp bold');
    check(toWhatsApp('see [docs](https://x.dev/a) and [https://y.dev](https://y.dev)') === 'see docs (https://x.dev/a) and https://y.dev', 'format: markdown links become plain text + url');
    check(toWhatsApp('* one\n+ two\n- three') === '- one\n- two\n- three', 'format: bullets normalised');
    const code = 'run `a **b** c` then\n```js\n# not a heading\nconst x = **y**;\n```\nok **done**';
    const out = toWhatsApp(code);
    check(out.includes('`a **b** c`') && out.includes('# not a heading\nconst x = **y**;') && out.endsWith('ok *done*'), 'format: inline and fenced code are never touched');
    check(toWhatsApp('') === '' && toWhatsApp(null) === '', 'format: empty input');
}

// ── pure: chunking ──
{
    check(chunkMessage('short').length === 1 && chunkMessage('  ').length === 0, 'chunk: short stays whole, blank is nothing');
    const long = Array.from({ length: 40 }, (_, i) => `Paragraph ${i} ${'word '.repeat(30)}`).join('\n\n');
    const parts = chunkMessage(long, 500);
    check(parts.length > 3 && parts.every((p) => p.length <= 500), 'chunk: every part fits the limit');
    check(parts.join(' ').replace(/\s+/g, ' ').trim() === long.replace(/\s+/g, ' ').trim(), 'chunk: nothing lost or duplicated');
    const fenced = `intro\n\`\`\`js\n${'const a = 1;\n'.repeat(120)}\`\`\`\nend`;
    const fp = chunkMessage(fenced, 400);
    check(fp.length > 2 && fp.every((p) => (p.match(/```/g) || []).length % 2 === 0), 'chunk: a split inside a code block closes and reopens it');
}

// ── pure: progress throttling (fake clock + timers) ──
{
    let t = 0; const sent = []; const timers = [];
    const mk = (o = {}) => createProgress({ send: async (x) => sent.push(x), now: () => t, setTimer: (fn, ms) => { const h = { fn, ms, unref() {} }; timers.push(h); return h; }, clearTimer: (h) => { h.dead = true; }, minMs: 8000, maxLines: 3, maxMessages: 3, ...o });
    const p = mk();
    await p.push('🔧 a'); await p.push('🔧 b'); await p.push('🔧 b'); await p.push('🔧 c');
    check(sent.length === 1 && sent[0] === '🔧 a' && timers.length === 1, 'progress: first line at once, the rest wait for the timer (and duplicates are dropped)');
    t = 9000; await timers[0].fn(); await new Promise((r) => setImmediate(r));
    check(sent.length === 2 && sent[1] === '🔧 b\n🔧 c', 'progress: waiting lines go out merged in one message');
    const o = mk({ maxMessages: 10 }); sent.length = 0; t = 20000;
    await o.push('🔧 0'); for (const l of ['1', '2', '3', '4', '5']) await o.push(`🔧 ${l}`);
    await o.flush();
    check(sent.length === 2 && sent[1].split('\n').length === 4 && sent[1].includes('and 2 more'), 'progress: overflow lines are counted, not sent');
    t = 40000; await p.push('🔧 x'); t = 60000; await p.push('🔧 y'); await p.flush();
    check(p.stats.sent === 3 && p.stats.hidden >= 1, 'progress: a task stops sending progress after maxMessages');
    const q = mk({ maxMessages: 10 }); sent.length = 0; t = 100000;
    await q.push('🔧 first'); await q.push('🔧 second'); await q.push('📋 Plan', { now: true });
    check(sent.length === 2 && sent[1] === '🔧 second\n📋 Plan', 'progress: an urgent line flushes everything waiting');
    const dead = createProgress({ send: async () => { throw new Error('offline'); }, now: () => 0 });
    check((await dead.push('x').then(() => 'ok', () => 'threw')) === 'ok', 'progress: a failing send never breaks the task');
}

// ── pure: views ──
{
    const base = { id: 7, status: 'running', description: 'build the thing', plan: [{ n: 1, title: 'one', status: 'done' }, { n: 2, title: 'two', status: 'pending' }], tokensIn: 700, tokensOut: 300, tokenBudget: 60000, provider: 'groq', model: 'openai/gpt-oss-120b', createdAt: '2026-11-02T10:05:00Z', agent: { turns: [{ tool: 'read_file' }, { invalid: true }] } };
    const v = formatTask(base);
    check(v.includes('Task #7') && v.includes('Plan* 1/2') && v.includes('✅ 1. one') && v.includes('⬜ 2. two') && v.includes('1000 / 60000') && v.includes('1 tool call'), 'task view: plan progress, tokens, tool calls');
    check(formatTask({ ...base, status: 'waiting_approval', agent: { turns: [], pending: { tool: 'run_command' } } }).includes('.wapprove 7') && formatTask({ ...base, status: 'paused', pauseReason: 'quota' }).includes('.wresume 7'), 'task view: tells you what to send next');
    const lg = formatLog(7, [{ ts: '2026-11-02T10:06:00Z', kind: 'tool', data: { tool: 'run_tests', ok: true } }, { ts: '2026-11-02T10:07:00Z', kind: 'provider_switch', data: { from: 'groq/a', to: 'gemini/b' } }, { ts: '2026-11-02T10:07:01Z', kind: 'weird_new_kind', data: {} }]);
    check(lg.includes('tool run_tests ✓') && lg.includes('groq/a → gemini/b') && lg.includes('weird_new_kind'), 'log view: readable lines, unknown kinds still shown');
    const help = helpText();
    check([...WORK_COMMANDS].every((c) => help.includes(c)), 'help lists every Work command');
    check(formatTaskList([]).includes('No tasks') && formatTaskList([{ id: 1, status: 'paused', description: 'x', pauseReason: 'quota' }]).includes('quota'), 'task list: empty and paused reason');
}

// ── interface with a real manager ──
function rig({ settings = {}, groq = [], enabled = true, ws, onTyping } = {}) {
    const mk = (script) => ({ calls: [], script, async chat(entry, req) { this.calls.push(req); const s = this.script.length ? this.script.shift() : null; if (s instanceof Error) throw s; return { text: s ?? fin('(no scripted reply)'), tokensIn: 100, tokensOut: 50, finish: 'stop' }; } });
    const adapters = { groq: mk(groq), gemini: mk([]) };
    const s = resolveSettings({ toolMode: 'auto', review: false, ...settings }, {}); s.retryBackoffMs = 0; s.workspaceDir = ws;
    const providers = createProviderManager({ adapters, settings: s, sleep: async () => {}, env: { GEMINI_FLASH_MODEL: 'g-flash', GEMINI_LITE_MODEL: 'g-lite' } });
    const sandbox = createSandbox({ root: ws });
    const tools = registerCmdTools(registerFsTools(createToolRegistry({ settings: s }), { sandbox, settings: s }), { sandbox, settings: s });
    const manager = createWorkManager({ store: createMemoryWorkStore(), providers, settings: s, tools, owner: `o${Math.random()}`, isChatEnabled: () => enabled });
    const out = []; const typing = [];
    const iface = createWorkInterface({ manager, settings: s, send: async (jid, text) => { out.push({ jid, text }); }, typing: async (jid, on) => { typing.push(on); onTyping?.(on); }, log: () => {} });
    let n = 0;
    const say = (text, { chat = CHAT, id = `m${++n}` } = {}) => iface.handle({ text, chatJid: chat, userId: 'u1', isDM: true, msgId: id });
    return { iface, manager, out, typing, say, adapters, texts: () => out.map((o) => o.text) };
}
const CHAT = '234800@s.whatsapp.net';
const tmp = () => fs.mkdtempSync(path.join(os.tmpdir(), 'wm-wa-'));

// 1. off => untouched; on needs normal chat
{
    const r = rig({ ws: tmp() });
    check((await r.say('hello there')) === false && r.out.length === 0, 'Work Mode off: plain messages are not consumed, nothing sent');
    check((await r.say('.chat on')) === false, 'normal "." commands are not consumed');
    const r2 = rig({ ws: tmp(), enabled: false });
    await r2.say('.wchat on');
    check(/normal chat/i.test(r2.texts()[0]) && (await r2.say('hi')) === false, '.wchat on rejected while normal chat is off');
}

// 2. on => request answered, formatted, typing shown
{
    const r = rig({ ws: tmp(), groq: ['## Answer\nA **closure** keeps its scope.'] });
    await r.say('.wchat on');
    const consumed = await r.say('what is a closure?');
    const final = r.texts().at(-1);
    check(consumed === true && final.includes('*Answer*') && final.includes('*closure*') && !final.includes('**') && /_#1 · /.test(final), 'answer: Markdown converted, task footer added');
    check(r.typing[0] === true && r.typing.at(-1) === false, 'typing indicator on while working, off after');
    check((await r.say('what is a closure?', { id: 'm2' })) === true && r.adapters.groq.calls.length === 1, 'redelivered message does not run twice');
}

// 3. views: help, list, detail, log, isolation
{
    const r = rig({ ws: tmp(), groq: ['one', 'two'] });
    await r.say('.wchat on'); await r.say('first question'); await r.say('second question');
    r.out.length = 0;
    await r.say('.whelp'); await r.say('.wtasks'); await r.say('.wtask'); await r.say('.wtask 1'); await r.say('.wlog 1'); await r.say('.wtask 99');
    const t = r.texts();
    check(t[0].includes('.wtask [id]') && t[1].includes('#2') && t[1].includes('#1'), '.whelp and .wtasks answer');
    check(t[2].includes('Task #2') && t[3].includes('Task #1') && t[3].includes('first question'), '.wtask with no id shows the latest; with id shows that one');
    check(/model groq/.test(t[4]) && /started|created/.test(t[4]), '.wlog shows the real event history');
    check(t[5].includes('No task #99'), 'unknown task id is a clean message');
    r.out.length = 0; await r.iface.handle({ text: '.wtask 1', chatJid: 'other@g.us', userId: 'u1', msgId: 'z' });
    check(r.texts()[0].includes('No task #1'), "another chat cannot see this chat's task");
}

// 4. approval through the interface
{
    const ws = tmp(); const marker = path.join(ws, 'ran.txt');
    const r = rig({ ws, groq: [tool('create_file', { path: 'w.js', content: "require('fs').writeFileSync('ran.txt','yes')" }), tool('run_command', { command: 'node w.js' }), fin('Ran w.js.')] });
    await r.say('.wchat on'); await r.say('create w.js in the workspace and run it');
    check(r.texts().some((x) => x.includes('.wapprove 1')) && !fs.existsSync(marker) && r.typing.at(-1) === false, 'approval asked in chat; nothing ran; typing stopped while waiting');
    await r.say('.wtask');
    check(r.texts().at(-1).includes('waiting_approval') && r.texts().at(-1).includes('.wapprove 1'), '.wtask on a waiting task says what to send');
    await r.say('.wapprove');
    check(fs.readFileSync(marker, 'utf8') === 'yes' && r.texts().some((x) => x.includes('Ran w.js')), '.wapprove runs it and delivers the final answer');
    check((await r.say('.wapprove')) === true && /not waiting|Nothing is waiting/.test(r.texts().at(-1)), 'second .wapprove is a clean refusal');
}

// 5. progress is throttled in a real run
{
    const ws = tmp();
    const steps = Array.from({ length: 6 }, (_, i) => tool('list_dir', { path: '.' }));
    const r = rig({ ws, settings: { progressMinMs: 1e9 }, groq: [...steps, fin('Looked six times.')] });
    await r.say('.wchat on'); r.out.length = 0;
    await r.say('list the files in the workspace folder');
    const prog = r.texts().filter((x) => x.includes('🔧'));
    check(prog.length <= 2 && r.texts().at(-1).includes('Looked six times'), `6 tool calls produced ${prog.length} progress message(s), then the answer`);
}

// 6. failure paths
{
    const r = rig({ ws: tmp() });
    await r.say('.wchat on');
    r.manager.runQueued = async () => { throw new Error('boom'); };
    const consumed = await r.say('do something');
    check(consumed === true && r.texts().at(-1).includes('Work Mode hit an error: boom') && r.typing.at(-1) === false, 'a crash is reported in chat and typing is switched off');
}

// 7. pause / resume / cancel / resumable listing
{
    const r = rig({ ws: tmp(), groq: ['ok'] });
    await r.say('.wchat on');
    const { task } = await r.manager.submit({ chatJid: CHAT, userId: 'u1', text: 'parked job', msgId: 'p1' });
    await r.say(`.wpause ${task.id}`);
    await r.say('.wchat off'); await r.say('.wchat on');
    check(r.texts().some((x) => x.includes('Unfinished from before') && x.includes('parked job')), '.wchat on lists unfinished tasks from before');
    await r.say(`.wresume ${task.id}`);
    check(r.texts().some((x) => x.includes('Resuming task #1')) && (await r.manager.getTask(task.id)).status === 'completed', '.wresume continues and completes it');
    const { task: t2 } = await r.manager.submit({ chatJid: CHAT, userId: 'u1', text: 'cancel me', msgId: 'p2' });
    await r.say(`.wcancel ${t2.id}`);
    check(r.texts().at(-1).includes('cancelled'), '.wcancel works');
}

console.log(fails.length ? `\n${fails.length} FAILED` : '\nall WhatsApp interface checks passed');
process.exit(fails.length ? 1 : 0);
