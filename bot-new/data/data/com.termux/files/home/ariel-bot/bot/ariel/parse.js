// Reads the model's answer. Tolerant on purpose: a messy answer must never block a reply.
//   ACTION: reply | react | silent
//   REPLY_TO: #12
//   bubble one
//   ---
//   bubble two
const ACTION_RE = /^\s*[*_`>#-]*\s*action\s*[*_`]*\s*[:=\-]\s*[*_`]*\s*([a-z]+)/i;
const REPLY_RE = /^\s*[*_`>#-]*\s*reply[_ ]?to\s*[*_`]*\s*[:=\-]\s*(.*)$/i;
const SILENT_WORDS = new Set(['silent', 'skip', 'ignore', 'none', 'nothing', 'pass', 'no reply', 'noreply']);
const EMOJI_RE = /\p{Extended_Pictographic}(?:\u200d\p{Extended_Pictographic}|\ufe0f|[\u{1F3FB}-\u{1F3FF}])*/gu;

export function parseReply(raw, { maxBubbles = 4, maxChars = 700 } = {}) {
    let text = String(raw ?? '').replace(/\r\n?/g, '\n').trim();
    text = text.replace(/^```[a-z]*\n?/i, '').replace(/\n?```$/, '').trim();
    if (!text) return { action: 'silent', replyRef: null, bubbles: [] };

    const lines = text.split('\n');
    let action = null, replyRef = null, i = 0;
    for (; i < lines.length; i++) {
        const l = lines[i];
        if (!l.trim()) continue;
        let m = l.match(ACTION_RE);
        if (m && action === null) {
            const a = m[1].toLowerCase();
            action = a.startsWith('react') ? 'react' : SILENT_WORDS.has(a) ? 'silent' : 'reply';
            const rest = l.slice(l.indexOf(m[1]) + m[1].length).trim();
            if (rest && action === 'reply' && !/^[|/]/.test(rest)) lines[i] = rest; else continue;
            if (lines[i] === l) continue;
            break;
        }
        m = l.match(REPLY_RE);
        if (m && replyRef === null) {
            const n = m[1].match(/#?\s*(\d{1,4})/);
            replyRef = n ? Number(n[1]) : null;
            continue;
        }
        break;
    }
    const body = lines.slice(i).join('\n').trim();
    const only = body.toLowerCase().replace(/[^a-z ]/g, '').trim();
    if (action === 'silent' || (!action && (!body || SILENT_WORDS.has(only)))) {
        return { action: 'silent', replyRef, bubbles: [] };
    }

    // A bubble break is `---`. Models often write it inline ("hi 😄---and more"), so split on it anywhere.
    let bubbles = body.split(/\s*-{3,}\s*/).map(cleanBubble).filter(Boolean);
    if (bubbles.length > maxBubbles) bubbles = [...bubbles.slice(0, maxBubbles - 1), bubbles.slice(maxBubbles - 1).join(' ')];
    bubbles = bubbles.map((b) => (b.length > maxChars ? b.slice(0, maxChars).replace(/\s+\S*$/, '') : b));
    if (!bubbles.length) return { action: 'silent', replyRef, bubbles: [] };
    return { action: action || 'reply', replyRef, bubbles };
}

function cleanBubble(b) {
    let t = String(b).trim();
    t = t.replace(/^(?:#\d+\s+)?(?:satoru\s+)?ariel\s*(?:\([^)]*\))?\s*:\s*/i, '');   // she copied the transcript style
    if (/^"[^"]*"$/s.test(t) || /^“[^”]*”$/s.test(t)) t = t.slice(1, -1);
    return t.trim();
}

// Caps emoji across the whole reply, in code (not only in the prompt).
export function capEmoji(bubbles, max) {
    let left = max;
    return bubbles.map((b) => b.replace(EMOJI_RE, (e) => (left-- > 0 ? e : '')).replace(/[ \t]{2,}/g, ' ').trim()).filter(Boolean);
}

export function firstEmoji(text) {
    const m = String(text || '').match(EMOJI_RE);
    return m ? m[0] : null;
}

// ── repetition guard ────────────────────────────────────
const words = (s) => String(s).toLowerCase().replace(/[^\p{L}\p{N}\s']/gu, ' ').split(/\s+/).filter(Boolean);
function shingles(w, n = 3) {
    const out = new Set();
    for (let i = 0; i + n <= w.length; i++) out.add(w.slice(i, i + n).join(' '));
    return out;
}

// True when a draft reuses an opener, a whole bubble, or most of a recent message of hers.
export function repeatsRecent(bubbles, recent) {
    const past = recent.map((r) => Object.assign(words(r), { raw: String(r) })).filter((w) => w.length);
    for (const b of bubbles) {
        const w = words(b);
        const bRaw = String(b);
        if (!w.length) continue;
        const key = w.join(' ');
        const sh = shingles(w);
        for (const p of past) {
            if (p.join(' ') === key && w.length >= 2) return true;
            if (w.length >= 3 && p.length >= 3 && p.slice(0, 3).join(' ') === w.slice(0, 3).join(' ')) return true;
            // two short replies with the same opening word that both end in a question: same move again
            if (w[0] === p[0] && w.length <= 10 && p.length <= 10 && /\?[^\p{L}\p{N}?]*$/u.test(bRaw) && /\?[^\p{L}\p{N}?]*$/u.test(p.raw)) return true;
            if (w.length >= 2 && p.length >= 2 && w.length <= 8 && p.length <= 8 && p.slice(0, 2).join(' ') === w.slice(0, 2).join(' ')) return true;
            if (w.length >= 5 && p.length >= 5) {
                const ps = shingles(p);
                let hit = 0;
                for (const s of sh) if (ps.has(s)) hit++;
                if (hit / (sh.size + ps.size - hit) >= 0.6) return true;
            }
        }
    }
    return false;
}

// She cannot really tag anyone (messages go out as plain text), so a typed "@name" would only look like a
// broken tag. Keep a name that is really in the chat as a plain name; drop "@someone" and invented names.
export function stripFakeTags(bubbles, people = []) {
    const known = [...new Set(people.map((p) => String(p || '').trim()).filter(Boolean))].sort((a, b) => b.length - a.length);
    const low = (x) => x.toLowerCase();
    return bubbles.map((b) => b.replace(/@(\S+)/g, (all, tok, off, str) => {
        if (off > 0 && /[\p{L}\p{N}._+-]/u.test(str[off - 1])) return all;      // an email address, leave it
        const rest = str.slice(off + 1);
        const hit = known.find((k) => low(rest).startsWith(low(k)));
        if (hit) return rest.slice(0, hit.length);
        return '';
    }).replace(/[ \t]{2,}/g, ' ').trim()).filter(Boolean);
}

// True when her draft and her last two replies all look alike (shared words, short, same move again).
// Language-free: it compares word overlap only, so it catches a stuck game or bit, not a particular phrase.
export function inLoop(bubbles, recent, { minWords = 2, overlap = 0.3 } = {}) {
    const draft = words(bubbles.join(' '));
    const past = recent.slice(-2).map((r) => words(r));
    if (past.length < 2 || draft.length < minWords || past.some((w) => w.length < minWords)) return false;
    const jac = (a, b) => {
        const A = new Set(a); const B = new Set(b);
        let hit = 0;
        for (const x of A) if (B.has(x)) hit++;
        return hit / (A.size + B.size - hit);
    };
    const all = [draft, ...past];
    for (let i = 0; i < all.length; i++) for (let j = i + 1; j < all.length; j++) if (jac(all[i], all[j]) < overlap) return false;
    return true;
}
