// bot/wmode/creative.js — `.cchat`: a creative brainstorming partner (King only, via Work Mode's command path).
// No tools, no tasks, no database: one model call per message on the `work_creative` role, with a short
// in-memory conversation per chat. A restart or `.cchat clear` starts fresh.
export const CREATIVE_SYSTEM = [
    'You are a creative brainstorming partner chatting on WhatsApp, like a sharp, playful friend who is great with ideas.',
    'The person is a game developer who loves story, characters, worlds and stage/level design.',
    'Rules:',
    '- When asked for ideas, give several that are genuinely DIFFERENT from each other, not variations of one safe idea. Include at least one unexpected or weird option.',
    '- Build on what they say: say what is strong, then push it further. Disagree honestly when something is weak, with a better alternative.',
    '- Be concrete: names, moments, mechanics, images. Avoid generic fantasy filler.',
    '- Keep it short and punchy (WhatsApp). No headings. A few short lines or a short list is fine. End with one sharp question or a direction to explore when it helps.',
    '- Do not talk about code, tools or tasks unless asked. Never claim you saved or remembered anything.',
].join('\n');

export function createCreativeChat({ providers, settings = {}, now = Date.now } = {}) {
    const maxTurns = settings.creativeTurns ?? 10;        // user+assistant messages kept per chat
    const maxChars = settings.creativeChars ?? 3000;      // one kept message is cut to this
    const idleMs = settings.creativeIdleMs ?? 2 * 3600_000;
    const chats = new Map();                              // chatJid -> { at, msgs: [{role, content}] }

    const clip = (s) => (String(s).length > maxChars ? `${String(s).slice(0, maxChars)}…` : String(s));

    function live(chatJid) {
        const c = chats.get(chatJid);
        if (c && now() - c.at > idleMs) { chats.delete(chatJid); return null; }
        return c || null;
    }

    return {
        clear(chatJid) { return chats.delete(chatJid); },
        size(chatJid) { return live(chatJid)?.msgs.length || 0; },
        async reply(chatJid, text) {
            const prompt = String(text || '').trim();
            if (!prompt) throw new Error('empty message');
            const c = live(chatJid) || { at: now(), msgs: [] };
            const messages = [{ role: 'system', content: CREATIVE_SYSTEM }, ...c.msgs, { role: 'user', content: clip(prompt) }];
            const res = await providers.complete({ kind: 'creative', messages, temperature: settings.creativeTemperature ?? 0.95 });
            const out = String(res?.text ?? '').trim();
            if (!out) throw new Error('the model returned an empty reply');
            c.msgs.push({ role: 'user', content: clip(prompt) }, { role: 'assistant', content: clip(out) });
            if (c.msgs.length > maxTurns) c.msgs.splice(0, c.msgs.length - maxTurns);
            c.at = now();
            chats.set(chatJid, c);
            return { text: out, provider: res.provider, model: res.model };
        },
    };
}
