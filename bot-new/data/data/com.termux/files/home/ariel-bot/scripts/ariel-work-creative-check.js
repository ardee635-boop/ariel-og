// Offline checks for `.cchat` (creative brainstorming). No database, no network, no real models.
import { createCreativeChat, CREATIVE_SYSTEM } from '../bot/wmode/creative.js';
import { createWorkInterface, WORK_COMMANDS, helpText } from '../bot/wmode/wa.js';
import { defaultWorkRouting, TASK_ROLE } from '../bot/wmode/providers.js';
import { resolveSettings } from '../bot/wmode/settings.js';

let pass = 0, fail = 0;
const check = (ok, name) => { if (ok) { pass++; console.log(`✓ ${name}`); } else { fail++; console.log(`✗ ${name}`); } };

// fake provider manager that records what it was asked
const calls = [];
let mode = 'ok';
const providers = {
    async complete(req) {
        calls.push(req);
        if (mode === 'quota') { const e = new Error('out'); e.name = 'WorkQuotaError'; e.resetAt = Date.UTC(2026, 10, 3, 0, 0); throw e; }
        if (mode === 'empty') return { text: '  ', provider: 'gemini', model: 'g' };
        return { text: `idea #${calls.length}`, provider: 'gemini', model: 'models/gemini-x' };
    },
};

// routing
check(TASK_ROLE.creative === 'work_creative', 'creative kind maps to work_creative');
const r = defaultWorkRouting({}).roles.work_creative;
check(r && r.chain.length >= 2 && r.temperature >= 0.8, 'work_creative role: fallback chain, high temperature');
check(r.chain[0].provider === 'gemini', 'creative starts on Gemini');
check(resolveSettings().creativeTurns === 10, 'settings default present');

// history
let t = 1000;
const c = createCreativeChat({ providers, settings: { creativeTurns: 4, creativeIdleMs: 5000 }, now: () => t });
const a1 = await c.reply('chatA', 'boss that uses the cold');
check(a1.text === 'idea #1' && a1.provider === 'gemini', 'reply returns text and model');
check(calls[0].kind === 'creative' && calls[0].temperature === 0.95, 'asks for the creative role with high temperature');
check(calls[0].messages[0].role === 'system' && calls[0].messages[0].content === CREATIVE_SYSTEM, 'system prompt first');
await c.reply('chatA', 'make it weirder');
const m2 = calls[1].messages;
check(m2.length === 4 && m2[1].content === 'boss that uses the cold' && m2[2].content === 'idea #1' && m2[3].content === 'make it weirder', 'second call carries the earlier turn');
await c.reply('chatA', 'third'); await c.reply('chatA', 'fourth');
check(c.size('chatA') === 4, 'history capped at creativeTurns');
await c.reply('chatB', 'other chat');
check(calls[calls.length - 1].messages.length === 2, 'chats do not share history');
t += 6000;
check(c.size('chatA') === 0, 'idle chat starts fresh');
await c.reply('chatA', 'after idle');
check(calls[calls.length - 1].messages.length === 2, 'no stale context after idle');
c.reply('chatA', '   ').then(() => check(false, 'empty message rejected'), () => check(true, 'empty message rejected'));
mode = 'empty';
let threw = false; try { await c.reply('chatA', 'x'); } catch { threw = true; }
check(threw && c.size('chatA') === 2, 'empty model reply throws and is not remembered');
mode = 'ok';

// WhatsApp interface
const sent = [];
const typingLog = [];
const mk = (creative) => createWorkInterface({ manager: {}, creative, settings: { typing: true }, send: async (j, tx) => { sent.push(tx); }, typing: async (j, on) => { typingLog.push(on); } });
const iface = mk(createCreativeChat({ providers }));
check(WORK_COMMANDS.has('.cchat') && helpText().includes('.cchat'), '.cchat is a Work command and is in .whelp');
sent.length = 0; calls.length = 0;
check((await iface.handle({ text: '.cchat A Boss With Capital Letters', chatJid: 'g1', userId: '1' })) === true, '.cchat is consumed');
check(calls.at(-1).messages.at(-1).content === 'A Boss With Capital Letters', 'original case and spacing preserved');
check(/idea #1/.test(sent[0]) && /gemini\/gemini-x/.test(sent[0]), 'answer carries the model footer');
check(typingLog[0] === true && typingLog.at(-1) === false, 'typing on then off');
sent.length = 0;
await iface.handle({ text: '.cchat', chatJid: 'g1', userId: '1' });
check(/brainstorm/.test(sent[0]) && calls.length === 1, 'bare .cchat shows usage, no model call');
sent.length = 0;
await iface.handle({ text: '.cchat clear', chatJid: 'g1', userId: '1' });
await iface.handle({ text: '.cchat again', chatJid: 'g1', userId: '1' });
check(calls.at(-1).messages.length === 2, '.cchat clear wipes the conversation');
mode = 'quota'; sent.length = 0; typingLog.length = 0;
await iface.handle({ text: '.cchat hello', chatJid: 'g1', userId: '1' });
check(/out of quota/.test(sent[0]) && typingLog.at(-1) === false, 'quota error is friendly and typing is switched off');
mode = 'ok';
const none = mk(null); sent.length = 0;
await none.handle({ text: '.cchat hi', chatJid: 'g1', userId: '1' });
check(/unavailable/.test(sent[0]), 'no creative engine: says so, does not crash');
sent.length = 0;
await iface.handle({ text: '.cchat **bold** idea', chatJid: 'g1', userId: '1' });
check(sent.length === 1, 'one message per reply');

console.log(fail ? `\n${fail} FAILED, ${pass} passed` : `\nall creative checks passed (${pass})`);
process.exit(fail ? 1 : 0);
