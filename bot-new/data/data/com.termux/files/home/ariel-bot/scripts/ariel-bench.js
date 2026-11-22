#!/usr/bin/env node
// Ariel model benchmark. Picks the embedding model first, then the chat models.
//   node --env-file=.env scripts/ariel-bench.js <command> [options]
//
//   models  [--grep text]                 list real model ids per provider; marks the ones in the default routing
//   embed   --models gemini=gemini-embedding-001@768,openrouter=openai/text-embedding-3-small@768
//   import  <whatsapp-export.txt> [--prefix name] [--window 15] [--every 40] [--max 60]
//   run     [--models groq=openai/gpt-oss-120b,gemini=<id>] [--cases bench/cases] [--core file] [--limit N] [--delay 1200] [--resume <runId>]
//   ab      [<runId>] [--pairs 30]        blind A/B scoring in the terminal (resumable)
//   report  [<runId>]
import fs from 'fs';
import path from 'path';
import readline from 'readline/promises';
import { fileURLToPath } from 'url';
import { buildAdapters } from '../bot/ariel/providers/adapters.js';
import { defaultRouting } from '../bot/ariel/providers/routing.js';
import { createAI } from '../bot/ariel/providers/index.js';
import { getJson } from '../bot/ariel/providers/http.js';
import {
    PLACEHOLDER_CORE, EMBED_PAIRS, EMBED_UNRELATED, parseWhatsApp, makeCases, parseAction, bodyOf,
    buildMessages, parseModelSpec, specKey, pickPairs, summarize, scoreEmbeddings,
} from './ariel-bench-lib.js';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const BENCH = path.join(ROOT, 'bench');
const argv = process.argv.slice(2);
const cmd = argv[0];
const rest = argv.slice(1);
const opt = (n, d) => { const i = rest.indexOf(`--${n}`); return i >= 0 ? rest[i + 1] : d; };
const positional = () => rest.filter((a, i) => !a.startsWith('--') && !(i > 0 && rest[i - 1].startsWith('--')))[0];
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const pct = (x) => (x == null ? '  -  ' : `${Math.round(x * 100)}%`.padStart(5));
const num = (x, d = 0) => (x == null ? '-' : Number(x).toFixed(d));

const adapters = buildAdapters(process.env);
const ai = createAI({ adapters, getRouting: async () => defaultRouting() });   // callOnce only; no DB

function need(...providers) {
    for (const p of providers) if (!adapters[p]) console.error(`(no key for ${p}: set ${p === 'gemini' ? 'GEMINI_API_KEY' : p.toUpperCase() + '_API_KEY'})`);
    return providers.filter((p) => adapters[p]);
}

// ── models ──────────────────────────────────────────────────
async function cmdModels() {
    const grep = (opt('grep', '') || '').toLowerCase();
    const inRouting = new Set();
    for (const r of Object.values(defaultRouting().roles)) for (const e of [...(r.chain || []), ...(r.cheap || [])]) inRouting.add(`${e.provider}=${e.model}`);
    const lists = {};
    if (adapters.groq) {
        const j = await getJson('https://api.groq.com/openai/v1/models', { headers: { Authorization: `Bearer ${process.env.GROQ_API_KEY}` }, provider: 'groq' });
        lists.groq = (j.data || []).map((m) => m.id);
    }
    if (adapters.gemini) {
        const key = process.env.GEMINI_API_KEY || process.env.GOOGLE_API_KEY;
        const j = await getJson('https://generativelanguage.googleapis.com/v1beta/models?pageSize=200', { headers: { 'x-goog-api-key': key }, provider: 'gemini' });
        lists.gemini = (j.models || []).map((m) => `${m.name.replace(/^models\//, '')}   [${(m.supportedGenerationMethods || []).join(',')}]`);
    }
    if (adapters.openrouter) {
        const j = await getJson('https://openrouter.ai/api/v1/models', { provider: 'openrouter' });
        lists.openrouter = (j.data || []).map((m) => m.id);
    }
    need('groq', 'gemini', 'openrouter');
    for (const [p, ids] of Object.entries(lists)) {
        console.log(`\n== ${p} (${ids.length}) ==`);
        for (const id of ids.filter((x) => x.toLowerCase().includes(grep))) console.log('  ' + id);
    }
    console.log('\n== default routing check ==');
    for (const k of [...inRouting].sort()) {
        const [p, ...m] = k.split('='); const model = m.join('=');
        const ids = lists[p]; if (!ids) { console.log(`  ?  ${k}  (no key for ${p})`); continue; }
        console.log(`  ${ids.some((x) => x.split(' ')[0] === model) ? '✓' : '✗'}  ${k}`);
    }
}

// ── embed ───────────────────────────────────────────────────
async function cmdEmbed() {
    const specs = (opt('models', '') || '').split(',').filter(Boolean).map(parseModelSpec);
    if (!specs.length) throw new Error('give --models provider=model@dim,…  (default dim in the schema is 768)');
    const texts = [...EMBED_PAIRS.map((p) => p[0]), ...EMBED_PAIRS.map((p) => p[1]), ...EMBED_UNRELATED];
    console.log('model'.padEnd(46), 'dim'.padStart(5), 'ms'.padStart(7), 'top1'.padStart(6), 'margin'.padStart(8));
    for (const s of specs) {
        const entry = { provider: s.provider, model: s.model, dim: s.dim || 768 };
        const started = Date.now();
        try {
            const r = await ai.callOnce(entry, texts, 30000, 'embed', { kind: 'document' });
            const sc = scoreEmbeddings(r.vectors);
            console.log(specKey(entry).padEnd(46), String(r.vectors[0].length).padStart(5), String(Date.now() - started).padStart(7),
                pct(sc.top1).padStart(6), sc.margin.toFixed(3).padStart(8));
        } catch (e) {
            console.log(specKey(entry).padEnd(46), `FAILED: ${e.message}`);
        }
    }
    console.log('\ntop1 = how often the right memory ranks first for a reworded/Pidgin question (higher is better).');
    console.log('margin = how far related text scores above unrelated text (higher is better).');
    console.log('Pick ONE model: the vector size is fixed by it (migrate with --dim).');
}

// ── import ──────────────────────────────────────────────────
function cmdImport() {
    const file = positional();
    if (!file) throw new Error('usage: import <whatsapp-export.txt>');
    const msgs = parseWhatsApp(fs.readFileSync(file, 'utf8'));
    const prefix = opt('prefix', path.basename(file).replace(/\.[^.]+$/, '').replace(/[^\w-]+/g, '-').slice(0, 24) || 'chat');
    const cases = makeCases(msgs, { window: Number(opt('window', 15)), every: Number(opt('every', 40)), max: Number(opt('max', 60)), prefix });
    const dir = path.join(BENCH, 'cases');
    fs.mkdirSync(dir, { recursive: true });
    for (const c of cases) fs.writeFileSync(path.join(dir, `${c.id}.json`), JSON.stringify(c, null, 2));
    console.log(`${msgs.length} messages -> ${cases.length} cases in ${path.relative(ROOT, dir)}/ (phone numbers and emails masked).`);
    console.log('Now delete the ones you do not want, and edit "tags" / "expect" ("reply" or "silent") on the ones with a clear right answer.');
}

// ── run ─────────────────────────────────────────────────────
function loadCases() {
    const dir = path.resolve(ROOT, opt('cases', 'bench/cases'));
    if (!fs.existsSync(dir)) throw new Error(`no cases folder at ${dir} — run the import command first`);
    return fs.readdirSync(dir).filter((f) => f.endsWith('.json')).sort().map((f) => JSON.parse(fs.readFileSync(path.join(dir, f), 'utf8')));
}

function loadCore() {
    const f = opt('core', null) || path.join(ROOT, 'bot', 'ariel', 'core.json');
    if (fs.existsSync(f)) {
        const raw = fs.readFileSync(f, 'utf8');
        try { const j = JSON.parse(raw); if (j.prompt) return { text: j.prompt, placeholder: false }; } catch { return { text: raw, placeholder: false }; }
    }
    console.warn('⚠ no core identity found (bot/ariel/core.json with a "prompt" field, or --core file). Using a PLACEHOLDER:');
    console.warn('  speed, cost, format and silence results are valid; personality/naturalness scores are NOT meaningful yet.\n');
    return { text: PLACEHOLDER_CORE, placeholder: true };
}

const runDir = (id) => path.join(BENCH, 'out', id);
function latestRun() {
    const base = path.join(BENCH, 'out');
    const ids = fs.existsSync(base) ? fs.readdirSync(base).filter((d) => fs.existsSync(path.join(base, d, 'results.jsonl'))).sort() : [];
    if (!ids.length) throw new Error('no runs yet — use the run command');
    return ids[ids.length - 1];
}
const readJsonl = (f) => (fs.existsSync(f) ? fs.readFileSync(f, 'utf8').split('\n').filter(Boolean).map((l) => JSON.parse(l)) : []);

async function cmdRun() {
    let entries;
    const m = opt('models', null);
    if (m) entries = m.split(',').filter(Boolean).map(parseModelSpec);
    else {
        const seen = new Map();
        const r = defaultRouting().roles.converse;
        for (const e of [...r.chain, ...(r.cheap || [])]) seen.set(specKey(e), e);
        entries = [...seen.values()];
    }
    const defaults = new Map();
    for (const r of Object.values(defaultRouting().roles)) for (const e of [...(r.chain || []), ...(r.cheap || [])]) defaults.set(specKey(e), e);
    entries = entries.map((e) => ({ ...(defaults.get(specKey(e)) || {}), ...e }));   // keep reasoning/headroom for known models
    const usable = entries.filter((e) => adapters[e.provider]);
    for (const e of entries.filter((x) => !adapters[x.provider])) console.warn(`skipping ${specKey(e)}: no key for ${e.provider}`);
    if (!usable.length) throw new Error('no usable models');

    let cases = loadCases();
    const limit = Number(opt('limit', 0)); if (limit) cases = cases.slice(0, limit);
    const core = loadCore();
    const pricing = fs.existsSync(path.join(BENCH, 'pricing.json')) ? JSON.parse(fs.readFileSync(path.join(BENCH, 'pricing.json'), 'utf8')) : {};
    const id = opt('resume', null) || new Date().toISOString().replace(/[-:T]/g, '').slice(0, 14);
    fs.mkdirSync(runDir(id), { recursive: true });
    const file = path.join(runDir(id), 'results.jsonl');
    const done = new Set(readJsonl(file).map((r) => `${r.caseId}|${r.model}`));
    fs.writeFileSync(path.join(runDir(id), 'meta.json'), JSON.stringify({ id, models: usable.map(specKey), cases: cases.map((c) => c.id), corePlaceholder: core.placeholder }, null, 2));

    const delay = Number(opt('delay', 1200));
    const nextAt = {};
    let n = 0; const total = cases.length * usable.length;
    console.log(`run ${id}: ${cases.length} cases × ${usable.length} models`);
    for (const c of cases) {
        for (const e of usable) {
            n++;
            const key = specKey(e);
            if (done.has(`${c.id}|${key}`)) continue;
            const wait = (nextAt[e.provider] || 0) - Date.now(); if (wait > 0) await sleep(wait);
            const req = { messages: buildMessages({ core: core.text, chatKind: c.chatKind, messages: c.messages }),
                          maxTokens: Number(opt('max-tokens', 500)), temperature: Number(opt('temperature', 0.8)), schema: null };
            const rec = { caseId: c.id, model: key, ok: false, text: '', action: null, formatOk: false, ms: 0, tokensIn: 0, tokensOut: 0, cost: null, error: null };
            for (let attempt = 0; attempt < 2; attempt++) {
                const started = Date.now();
                try {
                    const r = await ai.callOnce(e, req, 40000);
                    if (!r.text) throw Object.assign(new Error('empty reply'), { kind: 'empty' });
                    const a = parseAction(r.text);
                    Object.assign(rec, { ok: true, text: r.text, action: a.action, formatOk: a.formatOk, ms: Date.now() - started,
                        tokensIn: r.tokensIn || 0, tokensOut: r.tokensOut || 0, error: null });
                    const p = pricing[key] || (e.priceIn != null ? { in: e.priceIn, out: e.priceOut } : null);
                    if (p) rec.cost = ((p.in || 0) * rec.tokensIn + (p.out || 0) * rec.tokensOut) / 1e6;
                    break;
                } catch (err) {
                    rec.error = `${err.kind || 'error'}: ${err.message}`.slice(0, 200);
                    rec.ms = Date.now() - started;
                    if (err.kind === 'ratelimit' && attempt === 0) { await sleep(6000); continue; }
                    break;
                }
            }
            nextAt[e.provider] = Date.now() + delay;
            fs.appendFileSync(file, JSON.stringify(rec) + '\n');
            process.stdout.write(`\r${n}/${total} ${key.slice(0, 40).padEnd(40)} ${rec.ok ? `${rec.ms}ms` : 'FAILED'}      `);
        }
    }
    console.log(`\ndone → ${path.relative(ROOT, file)}\nnext: ariel-bench.js ab ${id}   then   ariel-bench.js report ${id}`);
}

// ── ab ──────────────────────────────────────────────────────
async function cmdAb() {
    const id = positional() || latestRun();
    const results = readJsonl(path.join(runDir(id), 'results.jsonl'));
    const cases = new Map(loadCasesFor(id).map((c) => [c.id, c]));
    const scoreFile = path.join(runDir(id), 'scores.jsonl');
    const scored = new Set(readJsonl(scoreFile).map((s) => `${s.caseId}|${[s.a, s.b].sort().join('|')}`));
    const pairs = pickPairs(results, { pairs: Number(opt('pairs', 30)), seed: 1 })
        .filter((p) => !scored.has(`${p.caseId}|${[p.a, p.b].sort().join('|')}`));
    if (!pairs.length) { console.log('Nothing left to score.'); return; }
    const meta = JSON.parse(fs.readFileSync(path.join(runDir(id), 'meta.json'), 'utf8'));
    if (meta.corePlaceholder) console.warn('⚠ this run used the PLACEHOLDER identity: personality scores will not mean much.\n');
    // Line iterator (not rl.question): also works when answers are piped in, and end-of-input quits.
    const rl = readline.createInterface({ input: process.stdin });
    const lines = rl[Symbol.asyncIterator]();
    const ask = async (q) => {
        for (;;) {
            process.stdout.write(q);
            const { value, done } = await lines.next();
            if (done) return 'q';
            const a = value.trim().toLowerCase();
            if (['a', 'b', '=', 's', 'q'].includes(a)) return a;
        }
    };
    console.log('For each pair: a = A better, b = B better, = tie, s = skip, q = quit (progress is saved).\n');
    let k = 0;
    for (const p of pairs) {
        k++;
        const c = cases.get(p.caseId);
        console.log(`\n──── ${k}/${pairs.length} · ${p.caseId} ────`);
        for (const m of (c?.messages || []).slice(-6)) console.log(`  ${m.from}: ${m.text.replace(/\n/g, ' ').slice(0, 160)}`);
        console.log(`\n[A]\n${p.aText}\n\n[B]\n${p.bText}\n`);
        const personality = await ask('Personality (more her / more alive)? a/b/=/s/q: ');
        if (personality === 'q') break;
        const naturalness = personality === 's' ? 's' : await ask('Naturalness (sounds like a real person texting)? a/b/=/s/q: ');
        if (naturalness === 'q') break;
        fs.appendFileSync(scoreFile, JSON.stringify({ caseId: p.caseId, a: p.a, b: p.b, personality, naturalness }) + '\n');
    }
    rl.close();
    console.log(`\nsaved. Run: ariel-bench.js report ${id}`);
}

function loadCasesFor(id) {
    const meta = JSON.parse(fs.readFileSync(path.join(runDir(id), 'meta.json'), 'utf8'));
    const dir = path.resolve(ROOT, opt('cases', 'bench/cases'));
    return meta.cases.map((cid) => path.join(dir, `${cid}.json`)).filter((f) => fs.existsSync(f)).map((f) => JSON.parse(fs.readFileSync(f, 'utf8')));
}

// ── report ──────────────────────────────────────────────────
function cmdReport() {
    const id = positional() || latestRun();
    const results = readJsonl(path.join(runDir(id), 'results.jsonl'));
    const scores = readJsonl(path.join(runDir(id), 'scores.jsonl'));
    const rows = summarize(results, scores, loadCasesFor(id));
    console.log(`run ${id}\n`);
    console.log('model'.padEnd(44), 'n'.padStart(3), 'ok'.padStart(5), 'fmt'.padStart(5), 'p50ms'.padStart(6), 'p95ms'.padStart(6),
        'tokIn'.padStart(6), 'tokOut'.padStart(6), '$/100'.padStart(7), 'silent'.padStart(7), 'person'.padStart(7), 'natural'.padStart(8));
    for (const r of rows) {
        console.log(r.model.slice(0, 43).padEnd(44), String(r.n).padStart(3), pct(r.okRate), pct(r.formatRate), num(r.p50).padStart(6), num(r.p95).padStart(6),
            num(r.tokIn).padStart(6), num(r.tokOut).padStart(6), (r.costPer100 == null ? 'n/a' : r.costPer100.toFixed(3)).padStart(7),
            pct(r.silenceAcc).padStart(7), pct(r.personality).padStart(7), pct(r.naturalness).padStart(8));
    }
    console.log('\nok = calls that worked · fmt = followed the ACTION format · silent = right reply/silent decision on cases with "expect" set');
    console.log('person/natural = blind A/B win rate (tie = half a win). Few games means noise: treat <15 games per model as a hint, not a verdict.');
    const fails = results.filter((r) => !r.ok);
    if (fails.length) {
        console.log(`\n${fails.length} failed calls, e.g.:`);
        for (const f of fails.slice(0, 5)) console.log(`  ${f.model}: ${f.error}`);
    }
}

const commands = { models: cmdModels, embed: cmdEmbed, import: cmdImport, run: cmdRun, ab: cmdAb, report: cmdReport };
if (!commands[cmd]) {
    console.log(fs.readFileSync(fileURLToPath(import.meta.url), 'utf8').split('\n').slice(1, 10).map((l) => l.replace(/^\/\/ ?/, '')).join('\n'));
    process.exit(cmd ? 1 : 0);
}
try {
    await commands[cmd]();
} catch (e) {
    console.error('✗', e.message);
    process.exitCode = 1;
}
