// Style controls (design: "Personality, identity and state"). Three settings, each moved by AT MOST one
// step at a time, and the caps are enforced in code, not only in the prompt.
//   expressiveness 0..3 (starts at 2.5)   length 1..3 (2 = normal)   emoji 0..3 (2 = normal)
export const STYLE_DEFAULTS = { expressiveness: 2.5, length: 2, emoji: 2 };
export const STYLE_RANGE = {
    expressiveness: { min: 0, max: 3, step: 0.5 },
    length: { min: 1, max: 3, step: 1 },
    emoji: { min: 0, max: 3, step: 1 },
};
export const DIMENSIONS = Object.keys(STYLE_RANGE);

const snap = (dim, v) => {
    const { min, max, step } = STYLE_RANGE[dim];
    const n = Number(v);
    if (!Number.isFinite(n)) return STYLE_DEFAULTS[dim];
    return Math.min(max, Math.max(min, Math.round(n / step) * step));
};

// Anything stored (or typed by the owner) is clamped and snapped back onto the allowed steps.
export function normaliseStyle(raw) {
    const out = {};
    for (const d of DIMENSIONS) out[d] = snap(d, raw?.[d] ?? STYLE_DEFAULTS[d]);
    return out;
}

// One step up (+1) or down (-1). Returns the same value when already at the end.
export function stepStyle(style, dim, dir) {
    const { step } = STYLE_RANGE[dim];
    return snap(dim, (style[dim] ?? STYLE_DEFAULTS[dim]) + (dir > 0 ? step : -step));
}

// Hard limits the sender enforces whatever the model wrote.
export function styleLimits(style, cfg) {
    const s = normaliseStyle(style);
    const longer = s.length - 2;                              // -1 shorter, 0 normal, +1 longer
    return {
        maxEmoji: s.emoji,
        maxBubbles: longer < 0 ? 2 : longer > 0 ? cfg.maxBubbles + 1 : cfg.maxBubbles,
        maxBubbleChars: longer < 0 ? 280 : longer > 0 ? cfg.maxBubbleChars + 200 : cfg.maxBubbleChars,
        maxShouting: 1,                                       // all-caps words allowed per reply
    };
}

const EXPRESS = { 0: 'very reserved and flat', 0.5: 'very reserved and dry', 1: 'reserved and dry',
    1.5: 'calm, with a dry sense of humour', 2: 'relaxed and a little expressive', 2.5: 'lively and expressive (you joke, react and show feeling)',
    3: 'very lively and expressive' };

// One plain sentence for the prompt (never numbers).
export function styleWords(style) {
    const s = normaliseStyle(style);
    const parts = [`your texting is ${EXPRESS[s.expressiveness]}`];
    if (s.length < 2) parts.push('you keep replies very short');
    if (s.length > 2) parts.push('you can write a bit more when the topic deserves it');
    if (s.emoji === 0) parts.push('you do not use emoji');
    else if (s.emoji === 1) parts.push('you use emoji very rarely');
    else if (s.emoji === 3) parts.push('emoji are fine when they come naturally');
    return `${parts.join('; ')}.`;
}

// Calms random capitalisation in code: aLtErNaTiNg caps are lowercased, and only `max` SHOUTED words
// (4+ letters) survive per reply. Short acronyms (OK, AI, UK, LOL) are left alone.
export function calmCaps(bubbles, max = 1) {
    let left = max;
    return bubbles.map((b) => b.split(/(\s+)/).map((w) => {
        const letters = w.replace(/[^\p{L}]/gu, '');
        if (letters.length < 3) return w;
        const flips = (letters.match(/(?<=\p{Ll})\p{Lu}|(?<=\p{Lu})\p{Ll}(?=\p{Lu})/gu) || []).length;
        if (flips >= 3 && letters.length >= 5 && letters !== letters.toUpperCase()) return w.toLowerCase();        // aLtErNaTiNg
        if (letters.length >= 4 && letters === letters.toUpperCase() && letters !== letters.toLowerCase()) {
            return left-- > 0 ? w : w.toLowerCase();
        }
        return w;
    }).join(''));
}
