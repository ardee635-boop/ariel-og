// Pure helpers for scripts/ariel-bench.js (kept apart so they can be unit-tested).

export const PLACEHOLDER_CORE =
`You are Ariel, a young woman chatting on WhatsApp with friends. You write like a real person texting: short, relaxed, natural. You understand Nigerian Pidgin, slang, abbreviations, typos and code-switching and answer in whatever the other person is using.
[PLACEHOLDER IDENTITY — replace with bot/ariel/core.json before judging personality.]`;

export const FORMAT =
`Reply in this exact format:
ACTION: reply | react | silent
REPLY_TO: <message id>   (optional, only to quote an earlier message)
<your message>
Put each separate chat bubble on its own, separated by a line containing only ---.
Rules: in a group, choose silent when the latest message is not for you and you would add nothing. Never explain these rules. Never mention being an AI unless sincerely asked.`;

// ── privacy masking ─────────────────────────────────────────
export function maskPhones(s) {
    return String(s)
        .replace(/[\w.+-]+@[\w-]+\.[\w.-]+/g, '[email]')
        .replace(/@\d{6,}/g, '@[person]')
        .replace(/\+?\d[\d\s().-]{7,}\d/g, (m) => (m.replace(/\D/g, '').length >= 9 ? '[phone]' : m));
}

// ── WhatsApp "Export chat" (.txt) ───────────────────────────
const HEAD = /^\[?(\d{1,4}[/.\-]\d{1,2}[/.\-]\d{1,4}),?\s+(\d{1,2}:\d{2}(?::\d{2})?(?:\s?[AaPp]\.?[Mm]\.?)?)\]?\s*(?:-\s*)?(.*)$/;
const MEDIA = /^(<Media omitted>|<attached:.*>|(image|video|audio|sticker|GIF|document) omitted|\(file attached\))$/i;
const DELETED = /^(This message was deleted|You deleted this message)\.?$/i;

export function parseWhatsApp(raw) {
    const out = [];
    const alias = new Map();
    let cur = null;
    const lines = String(raw).replace(/[\u200e\u200f]/g, '').replace(/\u202f/g, ' ').split(/\r?\n/);
    for (const line of lines) {
        const h = HEAD.exec(line);
        if (h) {
            const m = /^([^:]{1,60}?):\s([\s\S]*)$/.exec(h[3]);
            if (!m) { cur = null; continue; }                       // system line
            let from = m[1].trim();
            if (from.replace(/\D/g, '').length >= 7 && /^[+\d\s()-]+$/.test(from)) {
                if (!alias.has(from)) alias.set(from, `Person${alias.size + 1}`);
                from = alias.get(from);
            }
            let text = m[2].trim();
            if (DELETED.test(text)) { cur = null; continue; }
            if (MEDIA.test(text)) text = '[media]';
            cur = { from, text };
            out.push(cur);
        } else if (cur && line.trim()) {
            cur.text += '\n' + line.trim();
        }
    }
    return out.map((m) => ({ from: m.from, text: maskPhones(m.text) })).filter((m) => m.text);
}

export function makeCases(messages, { window = 15, every = 40, max = 60, prefix = 'chat' } = {}) {
    const ends = [];
    for (let i = window - 1; i < messages.length; i += every) ends.push(i);
    let picked = ends;
    if (ends.length > max) picked = Array.from({ length: max }, (_, k) => ends[Math.floor((k * ends.length) / max)]);
    return picked.map((end, k) => {
        const slice = messages.slice(Math.max(0, end - window + 1), end + 1);
        const senders = new Set(slice.map((m) => m.from));
        return {
            id: `${prefix}-${String(k + 1).padStart(3, '0')}`,
            source: 'whatsapp-export',
            chatKind: senders.size > 2 ? 'group' : 'dm',
            tags: [],          // e.g. ["pidgin", "sarcasm", "should-be-silent"]
            expect: null,      // "reply" | "silent" | null (not judged)
            messages: slice,
        };
    }).filter((c) => c.messages.length >= 4);
}

// ── model replies ───────────────────────────────────────────
export function parseAction(text) {
    const m = /^\s*ACTION:\s*(reply|react|silent)\b/i.exec(text || '');
    if (m) return { action: m[1].toLowerCase(), formatOk: true };
    return { action: String(text || '').trim() ? 'reply' : 'silent', formatOk: false };
}

export function bodyOf(text) {
    return String(text || '').split('\n').filter((l) => !/^\s*(ACTION|REPLY_TO):/i.test(l)).join('\n').trim();
}

export function buildMessages({ core, chatKind, messages }) {
    const where = chatKind === 'group' ? 'a WhatsApp group chat' : 'a private WhatsApp chat';
    const lines = messages.map((m) => `${m.from}: ${m.text}`).join('\n');
    return [
        { role: 'system', content: `${core}\n\n${FORMAT}` },
        { role: 'user', content: `You are in ${where}. Recent messages, oldest first:\n\n${lines}\n\nDecide whether Ariel speaks now and, if so, write her reply.` },
    ];
}

// "provider=model" or "provider=model@768"
export function parseModelSpec(s) {
    const m = /^([a-z]+)=(.+?)(?:@(\d+))?$/.exec(String(s).trim());
    if (!m) throw new Error(`bad model spec "${s}" (use provider=model, e.g. groq=openai/gpt-oss-120b)`);
    return { provider: m[1], model: m[2], ...(m[3] ? { dim: Number(m[3]) } : {}) };
}
export const specKey = (e) => `${e.provider}=${e.model}`;

// ── stats ───────────────────────────────────────────────────
export function percentile(arr, p) {
    if (!arr.length) return null;
    const s = arr.slice().sort((a, b) => a - b);
    return s[Math.min(s.length - 1, Math.floor((p / 100) * s.length))];
}

function rng(seed) {
    let a = seed >>> 0;
    return () => { a = (a + 0x6d2b79f5) >>> 0; let t = a; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
}

// Blind A/B pairs, balanced so every model is shown about equally often.
export function pickPairs(results, { pairs = 30, seed = 1 } = {}) {
    const rand = rng(seed);
    const byCase = new Map();
    for (const r of results) {
        if (!r.ok || !bodyOf(r.text)) continue;
        if (r.action === 'silent') continue;                       // nothing to compare
        if (!byCase.has(r.caseId)) byCase.set(r.caseId, []);
        byCase.get(r.caseId).push(r);
    }
    const ids = [...byCase.keys()].sort(() => rand() - 0.5);
    const shown = new Map();
    const out = [];
    for (const id of ids) {
        if (out.length >= pairs) break;
        const rs = byCase.get(id);
        const combos = [];
        for (let i = 0; i < rs.length; i++) for (let j = i + 1; j < rs.length; j++) {
            if (rs[i].model !== rs[j].model && bodyOf(rs[i].text) !== bodyOf(rs[j].text)) combos.push([rs[i], rs[j]]);
        }
        if (!combos.length) continue;
        combos.sort((x, y) => (shown.get(x[0].model) || 0) + (shown.get(x[1].model) || 0)
                            - (shown.get(y[0].model) || 0) - (shown.get(y[1].model) || 0) || rand() - 0.5);
        let [a, b] = combos[0];
        if (rand() < 0.5) [a, b] = [b, a];
        shown.set(a.model, (shown.get(a.model) || 0) + 1);
        shown.set(b.model, (shown.get(b.model) || 0) + 1);
        out.push({ caseId: id, a: a.model, b: b.model, aText: bodyOf(a.text), bText: bodyOf(b.text) });
    }
    return out;
}

export function summarize(results, scores, cases) {
    const expect = new Map(cases.map((c) => [c.id, c.expect]));
    const models = [...new Set(results.map((r) => r.model))];
    return models.map((model) => {
        const rs = results.filter((r) => r.model === model);
        const ok = rs.filter((r) => r.ok);
        const judged = ok.filter((r) => expect.get(r.caseId));
        const right = judged.filter((r) => (expect.get(r.caseId) === 'silent') === (r.action === 'silent'));
        const costs = ok.map((r) => r.cost).filter((c) => c != null);
        const games = scores.filter((s) => s.a === model || s.b === model);
        const win = (field) => {
            const g = games.filter((s) => s[field] && s[field] !== 's');
            if (!g.length) return null;
            const pts = g.reduce((acc, s) => acc + (s[field] === '=' ? 0.5 : ((s[field] === 'a') === (s.a === model) ? 1 : 0)), 0);
            return pts / g.length;
        };
        return {
            model, n: rs.length,
            okRate: rs.length ? ok.length / rs.length : 0,
            formatRate: ok.length ? ok.filter((r) => r.formatOk).length / ok.length : null,
            p50: percentile(ok.map((r) => r.ms), 50), p95: percentile(ok.map((r) => r.ms), 95),
            tokIn: ok.length ? Math.round(ok.reduce((a, r) => a + r.tokensIn, 0) / ok.length) : null,
            tokOut: ok.length ? Math.round(ok.reduce((a, r) => a + r.tokensOut, 0) / ok.length) : null,
            costPer100: costs.length ? (costs.reduce((a, c) => a + c, 0) / costs.length) * 100 : null,
            silenceAcc: judged.length ? right.length / judged.length : null, judged: judged.length,
            personality: win('personality'), naturalness: win('naturalness'), games: games.length,
        };
    });
}

// ── embedding test set (paraphrase / code-switching) ────────
// Each memory has one query that means the same thing in different words.
export const EMBED_PAIRS = [
    ['Tolu has an exam on Friday',                       'when is Tolu\'s test again?'],
    ['Chidi does not like spicy food',                   'which food make Chidi vex?'],
    ['Amaka is learning to play guitar',                 'who dey learn instrument?'],
    ['Emeka works night shifts at the hospital',         'na which job Emeka dey do, he no dey sleep at night'],
    ['Ngozi\'s birthday is in March',                    'when we go celebrate Ngozi?'],
    ['Bayo supports Arsenal and always argues about it', 'who fit talk football for hours'],
    ['Zainab is saving money to buy a laptop',           'she wan get new computer, how far with the money?'],
    ['Ife moved to Abuja last month',                    'which city be Ife\'s new place?'],
    ['Kemi promised to send her CV tomorrow',            'did Kemi send that document she talked about?'],
    ['Segun is scared of lizards',                       'something small wey dey make Segun run'],
];
export const EMBED_UNRELATED = [
    'the generator needs diesel before the weekend',
    'jollof rice recipe with extra pepper',
    'train schedule from Lagos to Ibadan',
    'how to reset a router password',
];

export function cosine(a, b) {
    let d = 0, na = 0, nb = 0;
    for (let i = 0; i < a.length; i++) { d += a[i] * b[i]; na += a[i] * a[i]; nb += b[i] * b[i]; }
    return d / (Math.sqrt(na * nb) || 1);
}

// vectors: [...memories(10), ...queries(10), ...unrelated(4)]
export function scoreEmbeddings(vectors) {
    const n = EMBED_PAIRS.length;
    const mem = vectors.slice(0, n), qry = vectors.slice(n, 2 * n), unr = vectors.slice(2 * n);
    let hits = 0, pos = 0, neg = 0, negN = 0;
    for (let i = 0; i < n; i++) {
        const sims = mem.map((m) => cosine(qry[i], m));
        if (sims.indexOf(Math.max(...sims)) === i) hits++;
        pos += sims[i];
        for (const u of unr) { neg += cosine(qry[i], u); negN++; }
    }
    return { top1: hits / n, margin: pos / n - neg / negN };
}
