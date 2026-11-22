// Feedback: remarks about HOW she behaves ("you sound robotic", "too many emojis") are stored as
// feedback_signals. A style setting moves only after 3 separate signals within 7 days from at least 2
// different people, and then by one step at most. One angry comment changes nothing.
import { DIMENSIONS, STYLE_RANGE, normaliseStyle, stepStyle, styleWords } from './style.js';

// "you ..." phrases that make a remark about HER (so "that movie is cringe" never counts).
const YOU = String.raw`(?:you(?:'re|’re| are| r|'ve been| be| dey| sound(?:s|ed|ing)?| talk(?:s|ing)?| text(?:s|ing)?| type| typing| write| writing| reply| replies| answer(?:s|ing)?| keep)|u (?:r|are|sound|dey|talk|text|type|write|reply)|ur|your|ariel(?: is| sounds?| dey| talks?| replies| type[s]?))`;
const near = (kw) => new RegExp(String.raw`\b${YOU}\b[^.!?\n]{0,30}?(?:${kw})`, 'i');

// Order matters: the first kinds listed win ties ("too short" before "too long").
const RULES = [
    { kind: 'too_short', re: [near(String.raw`too short|so short|one[- ]word|dry replies|too dry and short|say more|write more|longer repl`), /\b(?:longer|more detailed) (?:replies|answers|texts|messages)\b/i] },
    { kind: 'too_long', re: [near(String.raw`too long|so long|too wordy|wordy|yapping|yap too much|writing essays|essay|too many words`), /\b(?:keep it short|reply shorter|shorter (?:replies|answers|texts|messages)|stop (?:yapping|writing essays))\b/i] },
    { kind: 'emoji_less', re: [/\b(?:too many|so many|stop (?:using |the |with the )?(?:so many )?|less|fewer|no more|reduce (?:the )?)\s*emojis?\b/i, /\bstop (?:the )?emojis?\b/i, near(String.raw`too many emojis?|emoji too much|spam(?:ming)? emojis?`)] },
    { kind: 'emoji_more', re: [/\b(?:use|add|send|put) more emojis?\b/i, near(String.raw`never use emojis?|no emojis?|don'?t use (?:any )?emojis?`)] },
    { kind: 'overdone', re: [near(String.raw`doing too much|overdo(?:ing)?|over the top|trying too hard|try[- ]hard|cringe|too extra|so extra|too dramatic`), /\b(?:calm down|tone it down|relax small)\b/i] },
    { kind: 'robotic', re: [near(String.raw`robotic|like (?:a )?(?:robot|bot|machine|chatbot|customer service|call cent(?:er|re)|ai|assistant)|fake|stiff|scripted|canned|generic|too formal|so formal|lifeless|flat|boring|no energy|dry`)] },
    { kind: 'repetitive', re: [near(String.raw`repeat(?:ing)? yourself|saying the same|same thing (?:again|over)|repeat(?:ing)? the same|always say|keep saying`), /\byou('?re| are)? (?:always|keep) (?:saying|doing) (?:the same|that)\b/i] },
];

// → ['robotic', ...] (empty when the message is not feedback)
export function detectFeedback(text) {
    const t = String(text || '').replace(/\s+/g, ' ').trim();
    if (!t || t.length > 240 || t.startsWith('.')) return [];
    const kinds = [];
    for (const r of RULES) {
        if (r.re.some((re) => re.test(t))) kinds.push(r.kind);
    }
    // "too short" and "too long" in one remark contradict each other: keep neither
    if (kinds.includes('too_short') && kinds.includes('too_long')) return kinds.filter((k) => k !== 'too_short' && k !== 'too_long');
    if (kinds.includes('emoji_less') && kinds.includes('emoji_more')) return kinds.filter((k) => !k.startsWith('emoji'));
    return kinds.slice(0, 2);
}

// Which feedback kinds push which setting, and which way.
export const KIND_EFFECT = {
    robotic: { dim: 'expressiveness', dir: +1 }, overdone: { dim: 'expressiveness', dir: -1 },
    too_short: { dim: 'length', dir: +1 }, too_long: { dim: 'length', dir: -1 },
    emoji_more: { dim: 'emoji', dir: +1 }, emoji_less: { dim: 'emoji', dir: -1 },
};

const scrub = (t) => String(t || '').replace(/\s+/g, ' ').replace(/@\d{5,}/g, '@someone').replace(/\b\d{6,}\b/g, '(number)').trim().slice(0, 200);

export function createFeedback({ self, cfg, now = Date.now, log = () => {} }) {
    const F = cfg.self.feedback;
    const counters = { seen: 0, stored: 0, changes: 0 };

    // Called for messages that were said TO her. Never throws into the conversation.
    async function observe({ personId, body }) {
        if (personId == null) return 0;
        const kinds = detectFeedback(body);
        let n = 0;
        for (const kind of kinds) {
            counters.seen++;
            if (await self.addFeedback({ personId, kind, text: scrub(body), weight: 1, dedupeHours: F.dedupeHours })) { n++; counters.stored++; }
        }
        return n;
    }

    async function getStyle() {
        const c = await self.getConfig('style', null);
        return { values: normaliseStyle(c?.values), changed: c?.changed && typeof c.changed === 'object' ? c.changed : {} };
    }
    async function setStyle(values, changed) {
        await self.setConfig('style', { values: normaliseStyle(values), changed });
    }

    // The daily review (job `style_review`). Moves a setting one step when the rule is met.
    async function review() {
        const t = now();
        const since = new Date(t - F.windowDays * 86400_000);
        const signals = await self.feedbackSince(since);
        const cur = await getStyle();
        const values = { ...cur.values }; const changed = { ...cur.changed };
        const moves = [];
        for (const dim of DIMENSIONS) {
            // signals already used for an earlier move of this setting don't count again
            const after = changed[dim] ? new Date(changed[dim]) : since;
            const mine = signals.filter((s) => KIND_EFFECT[s.kind]?.dim === dim && new Date(s.created_at) > after);
            const side = (dir) => mine.filter((s) => KIND_EFFECT[s.kind].dir === dir);
            for (const dir of [+1, -1]) {
                const yes = side(dir); const no = side(-dir);
                const people = new Set(yes.map((s) => s.person_id)).size;
                if (yes.length < F.minSignals || people < F.minPeople || no.length >= 2) continue;
                const next = stepStyle(values, dim, dir);
                if (next === values[dim]) break;                      // already at the end of the range
                const entry = { at: new Date(t).toISOString(), type: 'style', status: 'applied', key: dim, from: values[dim], to: next,
                    text: `${dim}: ${values[dim]} → ${next}`, evidence: yes.map((s) => s.id), reason: `${yes.length} remarks from ${people} people in ${F.windowDays} days` };
                values[dim] = next; changed[dim] = new Date(t).toISOString();
                await self.appendLog(entry);
                moves.push(entry); counters.changes++;
                break;
            }
        }
        if (moves.length) await setStyle(values, changed);
        const purged = await self.purgeFeedback(F.keepDays);
        if (moves.length) log(`[ARIEL] style moved: ${moves.map((m) => m.text).join('; ')}`);
        return { moves, purged, signals: signals.length };
    }

    // Owner override: set one value by hand (snapped onto the allowed steps), or reset them all.
    async function setByHand(dim, value) {
        if (!STYLE_RANGE[dim]) throw new Error(`unknown setting "${dim}" (${DIMENSIONS.join(', ')})`);
        const n = Number(value);
        if (!Number.isFinite(n)) throw new Error('give a number');
        const cur = await getStyle();
        const next = normaliseStyle({ ...cur.values, [dim]: n });
        await setStyle(next, { ...cur.changed, [dim]: new Date(now()).toISOString() });
        await self.appendLog({ at: new Date(now()).toISOString(), type: 'style', status: 'applied', key: dim, from: cur.values[dim], to: next[dim], text: `${dim}: ${cur.values[dim]} → ${next[dim]} (set by hand)`, evidence: [], reason: 'owner' });
        return next;
    }
    async function reset() {
        await setStyle({}, {});
        await self.appendLog({ at: new Date(now()).toISOString(), type: 'style', status: 'applied', key: 'all', text: 'style reset to defaults', evidence: [], reason: 'owner' });
    }

    async function summary() {
        const cur = await getStyle();
        const sig = await self.feedbackSince(new Date(now() - F.windowDays * 86400_000));
        const by = {};
        for (const s of sig) { by[s.kind] ??= { n: 0, people: new Set() }; by[s.kind].n++; by[s.kind].people.add(s.person_id); }
        return { style: cur.values, words: styleWords(cur.values), kinds: Object.fromEntries(Object.entries(by).map(([k, v]) => [k, { n: v.n, people: v.people.size }])) };
    }

    return { observe, review, getStyle, setByHand, reset, summary, counters };
}
