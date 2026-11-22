// Ongoing state: mood and energy. Updated after conversations (from the vibe the summariser reports and
// how busy the conversation was). Both drift back to neutral by themselves, computed from timestamps when
// they are read, so no job is needed. She sees plain words, never numbers.
const MOOD_HALF_LIFE_H = 18;
const ENERGY_HALF_LIFE_H = 8;
const ENERGY_BASE = 0.65;
const VIBES = { positive: 0.30, playful: 0.30, neutral: 0, tense: -0.25, sad: -0.20, hostile: -0.35 };
const clamp = (x, lo, hi) => Math.min(hi, Math.max(lo, x));
const decay = (hours, half) => 0.5 ** (Math.max(0, hours) / half);

// The state as it is `nowMs`, after drifting.
export function drifted(state, nowMs) {
    const at = Number(state?.at) || nowMs;
    const h = (nowMs - at) / 3600_000;
    const mood = clamp(Number(state?.mood) || 0, -1, 1) * decay(h, MOOD_HALF_LIFE_H);
    const e0 = Number.isFinite(Number(state?.energy)) && state?.energy !== undefined ? Number(state.energy) : ENERGY_BASE;
    const energy = ENERGY_BASE + (clamp(e0, 0, 1) - ENERGY_BASE) * decay(h, ENERGY_HALF_LIFE_H);
    return { mood, energy, at: nowMs };
}

// A finished conversation nudges her mood a little and tires her a little.
export function applyVibe(state, { vibe, messages = 0 }, nowMs) {
    const d = drifted(state, nowMs);
    const delta = VIBES[String(vibe || '').toLowerCase()] ?? 0;
    const mood = clamp(d.mood + delta * 0.6, -0.8, 0.8);
    const lift = delta > 0 ? 0.03 : 0;
    const energy = clamp(d.energy - Math.min(0.1, Math.max(0, messages) / 600) + lift, 0.05, 1);
    return { mood: Math.round(mood * 1000) / 1000, energy: Math.round(energy * 1000) / 1000, at: nowMs };
}

// '' when nothing is worth saying (a normal day).
export function moodWords(state, nowMs) {
    const { mood, energy } = drifted(state, nowMs);
    const out = [];
    if (mood > 0.55) out.push('in a really good mood');
    else if (mood > 0.2) out.push('in a good mood');
    else if (mood < -0.55) out.push('feeling pretty low');
    else if (mood < -0.2) out.push('a little off today');
    if (energy < 0.3) out.push('low on energy, so you keep it brief');
    else if (energy > 0.85) out.push('full of energy');
    return out.length ? `You are ${out.join(' and ')}. Let it colour how you text a little; never announce it, and never take it out on anyone.` : '';
}

export function createMood({ self, now = Date.now, log = () => {} }) {
    const counters = { updates: 0 };
    async function recordSegment({ vibe, messages }) {
        const st = await self.getState();
        const next = applyVibe(st, { vibe, messages }, now());
        await self.mergeState({ mood: next.mood, energy: next.energy, at: next.at, last_vibe: String(vibe || 'neutral').slice(0, 20) });
        counters.updates++;
    }
    async function words() {
        return moodWords(await self.getState(), now());
    }
    return { recordSegment, words, counters };
}
