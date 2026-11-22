// bot/wmode/providers.js — Work Mode's AI Provider Manager.
//
// It does NOT talk to Groq / Gemini itself. It wraps Ariel's existing provider layer
// (ariel/providers: adapters, per-call fallback, circuit breakers, usage logging) and adds
// what a long task needs on top:
//   • task-kind -> role routing (fast / code / debug / research / plan / review)
//   • quota awareness: a model that hits a DAILY limit is parked until it resets, instead of
//     being retried every minute; the next model in the chain takes over
//   • a free-tier guard: only models in the built-in list (or explicitly allowed in settings)
//     are ever called, and OpenRouter is used only for ids ending in ":free"
//   • retries for transient failures, with a hard cap
//   • a health snapshot for `.wchat status`
//
// Provider switching never loses task state: nothing here keeps a conversation. The manager
// rebuilds the prompt from the task record on every call, so whichever model answers next
// receives the same plan, completed steps and outstanding work.
import { createAI, AIError } from '../ariel/providers/index.js';

export const TASK_ROLE = {
    simple: 'work_fast', summarise: 'work_fast', code: 'work_code', debug: 'work_debug',
    research: 'work_research', plan: 'work_plan', review: 'work_review', creative: 'work_creative',
};

export class WorkQuotaError extends Error {
    constructor(role, resetAt) {
        super(`every model for "${role}" is out of quota`);
        this.name = 'WorkQuotaError'; this.role = role; this.resetAt = resetAt || null;
    }
}

const keyOf = (e) => `${e.provider}/${e.model}`;

// Free-tier models Ariel already uses elsewhere (same ids and env overrides as ariel/providers/routing.js).
export function builtinEntries(env = process.env) {
    return {
        gFlash: { provider: 'gemini', model: env.GEMINI_FLASH_MODEL || 'gemini-3.8-flash' },
        gLite:  { provider: 'gemini', model: env.GEMINI_LITE_MODEL || 'gemini-3.5-flash-lite' },
        oss120: { provider: 'groq', model: 'openai/gpt-oss-120b', reasoning: 'low', headroom: 300 },
        oss20:  { provider: 'groq', model: 'openai/gpt-oss-20b', reasoning: 'low', headroom: 300 },
    };
}

export function defaultWorkRouting(env = process.env) {
    const { gFlash, gLite, oss120, oss20 } = builtinEntries(env);
    // OpenRouter joins only if you name a ":free" model — see allowedEntry().
    const or = env.ARIEL_OPENROUTER_MODEL ? [{ provider: 'openrouter', model: env.ARIEL_OPENROUTER_MODEL }] : [];
    return {
        roles: {
            work_fast:     { chain: [oss20, gLite, oss120, ...or], timeoutMs: 30_000, maxTokens: 1200, temperature: 0.4 },
            // Groq first for writing code; the REVIEW role starts on Gemini, so a reviewer is a
            // different model family from the author whenever both are available.
            work_code:     { chain: [oss120, gFlash, oss20, ...or], timeoutMs: 60_000, maxTokens: 3000, temperature: 0.2 },
            work_debug:    { chain: [gFlash, oss120, ...or],        timeoutMs: 60_000, maxTokens: 3000, temperature: 0.2 },
            work_research: { chain: [gFlash, oss120, ...or],        timeoutMs: 60_000, maxTokens: 2500, temperature: 0.3 },
            work_plan:     { chain: [gFlash, oss120, ...or],        timeoutMs: 45_000, maxTokens: 2000, temperature: 0.3 },
            work_review:   { chain: [gFlash, oss120, ...or],        timeoutMs: 45_000, maxTokens: 1500, temperature: 0.1 },
            // `.cchat` brainstorming: Gemini first (more fluent), high temperature for varied ideas.
            work_creative: { chain: [gFlash, oss120, ...or],        timeoutMs: 45_000, maxTokens: 1500, temperature: 0.95 },
        },
    };
}

// The free-tier rule. Built-in entries pass; anything else must be named in settings.verifiedModels;
// OpenRouter additionally needs a ":free" suffix so a paid route can never be selected by accident.
export function allowedEntry(entry, { builtin, verified = [] }) {
    const k = keyOf(entry);
    if (entry.provider === 'openrouter' && !String(entry.model).endsWith(':free')) return false;
    return builtin.has(k) || verified.includes(k) || entry.provider === 'openrouter';
}

// ── quota / health ──────────────────────────────────────────────
const DAILY_RE = /per day|daily|\bTPD\b|\bRPD\b|quota|resource.?exhausted/i;

export function parseRetryAfterMs(msg) {
    const m = /try again in\s+(?:(\d+)h)?\s*(?:(\d+)m(?!s))?\s*(?:(\d+(?:\.\d+)?)s)?/i.exec(String(msg || ''));
    if (!m || (!m[1] && !m[2] && !m[3])) return null;
    return ((+m[1] || 0) * 3600 + (+m[2] || 0) * 60 + (+m[3] || 0)) * 1000;
}

export function nextUtcMidnight(ms) { return (Math.floor(ms / 86_400_000) + 1) * 86_400_000; }

export function createHealth({ now = Date.now, persist = null } = {}) {
    const out = new Map();   // "provider/model" or "provider/*" -> { until, reason }
    const live = (v) => v && v.until > now();

    const api = {
        load(saved) {
            for (const [k, v] of Object.entries(saved || {})) if (v && Number(v.until) > now()) out.set(k, { until: Number(v.until), reason: v.reason || '' });
        },
        park(key, until, reason) {
            out.set(key, { until, reason });
            if (persist) Promise.resolve(persist(api.dump())).catch(() => {});
        },
        dump() { const o = {}; for (const [k, v] of out) if (live(v)) o[k] = v; return o; },
        isOut(entry) { return live(out.get(keyOf(entry))) || live(out.get(`${entry.provider}/*`)); },
        resetAt(entry) { return Math.max(out.get(keyOf(entry))?.until || 0, out.get(`${entry.provider}/*`)?.until || 0) || null; },
        // Called with every error an adapter throws. Decides whether the model/provider should be parked.
        observe(entry, err) {
            if (!(err instanceof AIError)) return;
            const msg = String(err.message || '');
            if (err.kind === 'ratelimit') {
                const hint = parseRetryAfterMs(msg);
                const daily = DAILY_RE.test(msg);
                if (daily) api.park(keyOf(entry), hint && hint < 86_400_000 ? now() + hint : nextUtcMidnight(now()), 'daily quota');
                else if (hint && hint > 120_000) api.park(keyOf(entry), now() + Math.min(hint, 86_400_000), 'rate limited');
                // short per-minute limits are left to the circuit breaker (60 s)
            } else if (err.kind === 'notfound') {
                api.park(keyOf(entry), now() + 12 * 3600_000, 'model not found');
            } else if (err.kind === 'auth') {
                api.park(`${entry.provider}/*`, now() + 30 * 60_000, 'auth failed');
            }
        },
    };
    return api;
}

// Wrap each adapter so every failure is shown to the health tracker before it propagates.
export function wrapAdapters(adapters, health) {
    const out = {};
    for (const [name, a] of Object.entries(adapters || {})) {
        out[name] = {
            ...a,
            async chat(entry, req, signal) {
                try { return await a.chat(entry, req, signal); }
                catch (e) { health.observe(entry, e); throw e; }
            },
        };
    }
    return out;
}

const TRANSIENT = new Set(['timeout', 'network', 'server', 'empty']);
const sleepDefault = (ms) => new Promise((r) => setTimeout(r, ms));

export function createProviderManager({ adapters, settings, getOverride = async () => null, usage = null, now = Date.now,
                                         sleep = sleepDefault, env = process.env, persistHealth = null, onEvent = () => {} }) {
    const health = createHealth({ now, persist: persistHealth });
    const builtin = new Set(Object.values(builtinEntries(env)).map(keyOf));
    const guard = { builtin, verified: settings.verifiedModels || [] };

    async function fullRouting() {
        const base = defaultWorkRouting(env);
        let ov = null;
        try { ov = await getOverride(); } catch { /* DB hiccup: built-in routing still works */ }
        const roles = { ...base.roles };
        for (const [role, cfg] of Object.entries(ov?.roles || {})) roles[role] = { ...(roles[role] || {}), ...cfg };
        for (const cfg of Object.values(roles)) {
            cfg.chain = (cfg.chain || []).filter((e) => allowedEntry(e, guard));
            if (cfg.cheap) cfg.cheap = cfg.cheap.filter((e) => allowedEntry(e, guard));
        }
        return { roles };
    }
    // What createAI sees: the same table minus anything parked until it resets.
    async function getRouting() {
        const r = await fullRouting();
        const roles = {};
        for (const [role, cfg] of Object.entries(r.roles)) roles[role] = { ...cfg, chain: cfg.chain.filter((e) => !health.isOut(e)) };
        return { roles };
    }

    const ai = createAI({ adapters: wrapAdapters(adapters, health), getRouting, usage, now });

    function soonestReset(chain) {
        const times = chain.map((e) => health.resetAt(e)).filter(Boolean);
        return times.length ? Math.min(...times) : null;
    }

    // One logical model call for a task. Returns the AI result; throws WorkQuotaError / AIError.
    async function complete({ kind = 'simple', messages, maxTokens, maxTokensCap, temperature, taskId = null }) {
        const role = TASK_ROLE[kind] || 'work_fast';
        let attempt = 0;
        for (;;) {
            const live = (await getRouting()).roles[role];
            if (!live?.chain?.length) {
                const all = (await fullRouting()).roles[role];
                throw new WorkQuotaError(role, soonestReset(all?.chain || []));
            }
            try {
                const cap = maxTokensCap ? Math.max(64, Math.min(maxTokensCap, live.maxTokens ?? 1000)) : undefined;
                const res = await ai.chat({ role, messages, maxTokens: maxTokens ?? cap, temperature });
                onEvent({ type: 'call', taskId, role, provider: res.provider, model: res.model });
                return { ...res, role };
            } catch (e) {
                if (!(e instanceof AIError)) throw e;
                const kinds = (e.attempts || []).map((a) => String(a).split(': ').pop());
                const transient = e.kind === 'exhausted' && kinds.some((k) => TRANSIENT.has(k));
                if (e.kind === 'exhausted') {
                    const left = (await getRouting()).roles[role];
                    if (!left?.chain?.length) {
                        const all = (await fullRouting()).roles[role];
                        throw new WorkQuotaError(role, soonestReset(all?.chain || []));
                    }
                }
                if (transient && attempt < (settings.maxRetries ?? 2)) {
                    attempt += 1;
                    onEvent({ type: 'retry', taskId, role, attempt, why: e.message });
                    await sleep((settings.retryBackoffMs ?? 1500) * attempt);
                    continue;
                }
                throw e;
            }
        }
    }

    async function snapshot() {
        const r = await fullRouting();
        const seen = new Map();
        for (const [role, cfg] of Object.entries(r.roles)) {
            for (const e of cfg.chain) {
                const k = keyOf(e);
                if (!seen.has(k)) seen.set(k, { key: k, provider: e.provider, roles: [] });
                seen.get(k).roles.push(role.replace('work_', ''));
            }
        }
        return [...seen.values()].map((s) => {
            const entry = { provider: s.provider, model: s.key.slice(s.provider.length + 1) };
            const breaker = ai._breakers.get(`m:${s.key.replace('/', ':')}`)?.openUntil > now() || ai._breakers.get(`p:${s.provider}`)?.openUntil > now();
            const until = health.resetAt(entry);
            const hasAdapter = !!adapters?.[s.provider];
            return { ...s, state: !hasAdapter ? 'no-key' : (until && until > now()) ? 'out' : breaker ? 'cooling' : 'ok', until: until && until > now() ? until : null };
        });
    }

    return { complete, snapshot, health, ai, getRouting, fullRouting };
}
