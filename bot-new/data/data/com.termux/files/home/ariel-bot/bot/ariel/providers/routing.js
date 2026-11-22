// Default routing: role -> ordered model chain. STARTING POINT ONLY.
// The real table is chosen after scripts/ariel-bench.js, and lives in the
// `config` table (key "routing"), which overrides these per role.
//
// Model ids below are the ones the Python engine already uses (engine/rpg/llm_models.py),
// with the same env overrides, so nothing new is assumed. Verify with:
//   node scripts/ariel-bench.js models
//
// Entry fields: provider, model, reasoning?, headroom?, structured? (false | true | 'object'),
//               priceIn?, priceOut? (USD per 1M tokens, for cost tracking).
// Role fields:  chain, timeoutMs, maxTokens, temperature,
//               cheap? (chain used once softTokens is passed), softTokens?, hardTokens? (daily, Lagos day).
export function defaultRouting(env = process.env) {
    const gFlash = { provider: 'gemini', model: env.GEMINI_FLASH_MODEL || 'gemini-3.8-flash' };
    const gLite  = { provider: 'gemini', model: env.GEMINI_LITE_MODEL  || 'gemini-3.5-flash-lite' };
    const oss120 = { provider: 'groq', model: 'openai/gpt-oss-120b', reasoning: 'low', headroom: 300 };
    const oss20  = { provider: 'groq', model: 'openai/gpt-oss-20b',  reasoning: 'low', headroom: 300 };
    // Third provider: only added once you name a model (see `ariel-bench.js models --grep`).
    const orRoute = env.ARIEL_OPENROUTER_MODEL ? [{ provider: 'openrouter', model: env.ARIEL_OPENROUTER_MODEL }] : [];

    const dim = Number(env.ARIEL_EMBED_DIM || 768);
    return {
        roles: {
            converse: { chain: [oss120, gFlash, oss20, gLite, ...orRoute], cheap: [oss20, gLite],
                        timeoutMs: 30000, maxTokens: 700, temperature: 0.8 },
            decide:   { chain: [oss20, gLite, ...orRoute],   timeoutMs: 8000,  maxTokens: 200, temperature: 0.3 },
            extract:  { chain: [gFlash, oss120, ...orRoute], cheap: [gLite, oss20],
                        timeoutMs: 40000, maxTokens: 1500, temperature: 0.2 },
            // Embeddings are NEVER failed over to a different model: vectors from two
            // models are not comparable. One entry; it is retried, not replaced.
            embed:    { chain: [{ provider: 'gemini', model: env.ARIEL_EMBED_MODEL || 'gemini-embedding-001', dim }],
                        timeoutMs: 15000 },
        },
    };
}

// Merge a (possibly partial) override from the config table over the defaults, per role.
export function mergeRouting(base, override) {
    if (!override?.roles) return base;
    const roles = { ...base.roles };
    for (const [role, cfg] of Object.entries(override.roles)) roles[role] = { ...(roles[role] || {}), ...cfg };
    return { roles };
}
