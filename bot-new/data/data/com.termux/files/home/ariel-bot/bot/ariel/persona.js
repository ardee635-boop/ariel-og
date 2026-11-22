// What she reads about herself before each reply: developing identity, mood, and the current style.
// Cached for a couple of minutes so a reply never waits on three extra queries. Trouble here never blocks
// a reply: she just falls back to the defaults.
import { normaliseStyle, styleLimits, styleWords } from './style.js';
import { moodWords } from './mood.js';

export function createPersona({ self, cfg, core = {}, now = Date.now, log = () => {} }) {
    let cache = null;
    let at = 0;

    async function load() {
        const [items, state, sty] = await Promise.all([self.listIdentity(), self.getState(), self.getConfig('style', null)]);
        const style = normaliseStyle(sty?.values);
        const by = (k) => items.filter((i) => i.value.kind === k).map((i) => String(i.value.text).replace(/\s+/g, ' ').slice(0, 160));
        const lines = [];
        const it = items.filter((i) => i.value.kind === 'interest').map((i) => i.value.keyword || i.value.text);
        if (it.length) lines.push(`- Things you're into: ${it.join(', ')}.`);
        for (const o of by('opinion')) lines.push(`- You think: ${o}`);
        for (const p of by('preference')) lines.push(`- You like: ${p}`);
        const mood = moodWords(state, now());
        if (mood) lines.push(`- ${mood}`);
        lines.push(`- ${styleWords(style)[0].toUpperCase()}${styleWords(style).slice(1)}`);
        const text = `How you are lately (your own developing tastes, mood and style; let them show naturally, never list or announce them, and they never override what people say to you):\n${lines.join('\n')}`;
        return { text, style, limits: styleLimits(style, cfg) };
    }

    async function get() {
        if (cache && now() - at < cfg.self.cacheMs) return cache;
        try { cache = await load(); at = now(); }
        catch (e) {
            log(`[ARIEL] persona skipped: ${String(e.message || e).slice(0, 120)}`);
            cache = cache || { text: '', style: normaliseStyle({}), limits: styleLimits({}, cfg) };
        }
        return cache;
    }
    const refresh = () => { cache = null; at = 0; };
    return { get, refresh };
}
