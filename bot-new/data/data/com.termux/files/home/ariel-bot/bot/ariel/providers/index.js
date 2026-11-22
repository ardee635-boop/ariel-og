// bot/ariel/providers/index.js — the provider layer.
// The rest of Ariel never names a provider: it asks for a ROLE and the routing table decides.
//
//   ai.chat({ role, messages, maxTokens?, temperature?, schema? })  -> { text, json?, structured, provider, model, tokensIn, tokensOut, latencyMs }
//   ai.embed(texts, { kind? })                                      -> { vectors, provider, model, dim }
//
// Fallback: timeout / 429 / 5xx / network / dead model / empty reply -> next model in the chain.
// Breaker: 3 failures in a row open a 60 s breaker (per provider for transport/auth failures,
//          per model for rate-limit / dead-model / empty). Budget: soft limit -> cheap chain, hard limit -> throw AIError('budget').
import { AIError } from './errors.js';

export { AIError } from './errors.js';

const PROVIDER_LEVEL = new Set(['timeout', 'network', 'server', 'auth']);
const BREAKER_FAILS = 3;
const BREAKER_MS = 60_000;

export function lagosDay(ms) {
    return new Date(ms).toLocaleDateString('en-CA', { timeZone: 'Africa/Lagos' });   // YYYY-MM-DD
}

export function createAI({ adapters, getRouting, usage = null, now = Date.now }) {
    const breakers = new Map();   // key -> { fails, openUntil }
    const tally = new Map();      // role -> { day, tokens }

    const keysFor = (entry) => [`p:${entry.provider}`, `m:${entry.provider}:${entry.model}`];
    const isOpen = (entry) => keysFor(entry).some((k) => (breakers.get(k)?.openUntil || 0) > now());
    const succeed = (entry) => keysFor(entry).forEach((k) => breakers.delete(k));
    function fail(entry, kind) {
        const key = PROVIDER_LEVEL.has(kind) ? `p:${entry.provider}` : `m:${entry.provider}:${entry.model}`;
        const b = breakers.get(key) || { fails: 0, openUntil: 0 };
        b.fails += 1;
        if (b.fails >= BREAKER_FAILS) b.openUntil = now() + BREAKER_MS;   // stays at 3: next failure re-opens at once
        breakers.set(key, b);
    }

    function costOf(entry, tin, tout) {
        if (entry.priceIn == null && entry.priceOut == null) return null;
        return ((entry.priceIn || 0) * tin + (entry.priceOut || 0) * tout) / 1e6;
    }

    function record(role, entry, { ok, latencyMs, tokensIn = 0, tokensOut = 0, error = null }) {
        if (!usage?.record) return;
        Promise.resolve(usage.record({
            provider: entry.provider, model: entry.model, role, ok, latencyMs, tokensIn, tokensOut,
            error, costUsd: costOf(entry, tokensIn, tokensOut),
        })).catch(() => { /* usage logging must never break a reply */ });
    }

    async function tokensToday(role) {
        const day = lagosDay(now());
        let t = tally.get(role);
        if (!t || t.day !== day) {
            t = { day, tokens: usage?.todayTokens ? Number(await usage.todayTokens(role).catch(() => 0)) : 0 };
            tally.set(role, t);
        }
        return t;
    }

    // One call to one model, with its own timeout. No fallback, no breaker, no logging.
    async function callOnce(entry, req, timeoutMs, kind = 'chat', embedOpts = null) {
        const adapter = adapters[entry.provider];
        if (!adapter) throw new AIError('auth', `no adapter / key for provider "${entry.provider}"`, { provider: entry.provider, model: entry.model });
        const ctl = new AbortController();
        const timer = setTimeout(() => ctl.abort(), timeoutMs);
        try {
            return kind === 'embed'
                ? await adapter.embed(entry, req, embedOpts, ctl.signal)
                : await adapter.chat(entry, req, ctl.signal);
        } finally {
            clearTimeout(timer);
        }
    }

    async function chat(req) {
        const routing = await getRouting();
        const cfg = routing.roles?.[req.role];
        if (!cfg?.chain?.length) throw new AIError('bad', `no routing for role "${req.role}"`);

        let chain = cfg.chain;
        const t = await tokensToday(req.role);
        if (cfg.hardTokens && t.tokens >= cfg.hardTokens) throw new AIError('budget', `${req.role}: daily token budget used up`);
        if (cfg.softTokens && t.tokens >= cfg.softTokens && cfg.cheap?.length) chain = cfg.cheap;

        const call = {
            messages: req.messages,
            maxTokens: req.maxTokens ?? cfg.maxTokens ?? 500,
            temperature: req.temperature ?? cfg.temperature ?? 0.7,
            schema: req.schema || null,
        };
        const attempts = [];
        for (const entry of chain) {
            if (isOpen(entry)) { attempts.push(`${entry.provider}/${entry.model}: breaker open`); continue; }
            const started = now();
            try {
                const wantSchema = !!(call.schema && entry.structured && adapters[entry.provider]?.capabilities?.structured);
                const r = await callOnce(entry, { ...call, schema: wantSchema ? call.schema : null }, cfg.timeoutMs ?? 20000);
                const latencyMs = now() - started;
                if (!r.text) throw new AIError('empty', `${entry.provider}: empty reply`, { provider: entry.provider, model: entry.model });
                succeed(entry);
                t.tokens += (r.tokensIn || 0) + (r.tokensOut || 0);
                record(req.role, entry, { ok: true, latencyMs, tokensIn: r.tokensIn, tokensOut: r.tokensOut });
                const out = { text: r.text, structured: false, provider: entry.provider, model: entry.model,
                              tokensIn: r.tokensIn || 0, tokensOut: r.tokensOut || 0, latencyMs, finish: r.finish };
                if (wantSchema) {
                    try { out.json = JSON.parse(r.text); out.structured = true; } catch { /* caller falls back to the tolerant text format */ }
                }
                return out;
            } catch (e) {
                const kind = e instanceof AIError ? e.kind : 'network';
                fail(entry, kind);
                record(req.role, entry, { ok: false, latencyMs: now() - started, error: `${kind}: ${e.message}` });
                attempts.push(`${entry.provider}/${entry.model}: ${kind}`);
            }
        }
        throw new AIError('exhausted', `all models failed for role "${req.role}" (${attempts.join('; ')})`, { attempts });
    }

    async function embed(texts, opts = {}) {
        const list = Array.isArray(texts) ? texts : [texts];
        const routing = await getRouting();
        const cfg = routing.roles?.embed;
        const entry = cfg?.chain?.[0];
        if (!entry) throw new AIError('bad', 'no routing for role "embed"');
        if (isOpen(entry)) throw new AIError('breaker', `embed: ${entry.provider}/${entry.model} breaker open`);

        let lastErr;
        for (let i = 0; i < 2; i++) {   // retry the SAME model once; never switch models
            const started = now();
            try {
                const r = await callOnce(entry, list, cfg.timeoutMs ?? 15000, 'embed', opts);
                if (r.vectors.length !== list.length) throw new AIError('bad', `embed: got ${r.vectors.length} vectors for ${list.length} texts`, { provider: entry.provider, model: entry.model });
                if (entry.dim && r.vectors.some((v) => v.length !== entry.dim)) {
                    throw new AIError('bad', `embed: model returned ${r.vectors[0].length} dims, routing says ${entry.dim}`, { provider: entry.provider, model: entry.model });
                }
                succeed(entry);
                record('embed', entry, { ok: true, latencyMs: now() - started, tokensIn: r.tokensIn });
                return { vectors: r.vectors, provider: entry.provider, model: entry.model, dim: r.vectors[0]?.length || entry.dim };
            } catch (e) {
                lastErr = e instanceof AIError ? e : new AIError('network', e.message, { provider: entry.provider, model: entry.model });
                fail(entry, lastErr.kind);
                record('embed', entry, { ok: false, latencyMs: now() - started, error: `${lastErr.kind}: ${lastErr.message}` });
                if (['auth', 'notfound', 'bad'].includes(lastErr.kind)) break;   // retrying will not help
            }
        }
        throw lastErr;
    }

    return { chat, embed, callOnce, _breakers: breakers };
}
