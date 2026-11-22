import { makeOpenAICompat } from './openai_compat.js';
import { makeGemini } from './gemini.js';

// Build every adapter whose key is present. Pure: reads only the env object it is given.
// Env: GROQ_API_KEY, GEMINI_API_KEY (or GOOGLE_API_KEY), OPENROUTER_API_KEY.
// Optional *_BASE_URL overrides (GROQ_BASE_URL, GEMINI_BASE_URL, OPENROUTER_BASE_URL) for proxies and tests.
export function buildAdapters(env = process.env, { fetchImpl, baseUrls = {} } = {}) {
    const out = {};
    if (env.GROQ_API_KEY) {
        out.groq = makeOpenAICompat({
            name: 'groq', apiKey: env.GROQ_API_KEY, fetchImpl,
            baseUrl: baseUrls.groq || env.GROQ_BASE_URL || 'https://api.groq.com/openai/v1',
        });
    }
    const gKey = env.GEMINI_API_KEY || env.GOOGLE_API_KEY;
    if (gKey) {
        out.gemini = makeGemini({ apiKey: gKey, fetchImpl, ...((baseUrls.gemini || env.GEMINI_BASE_URL) ? { baseUrl: baseUrls.gemini || env.GEMINI_BASE_URL } : {}) });
    }
    if (env.OPENROUTER_API_KEY) {
        out.openrouter = makeOpenAICompat({
            name: 'openrouter', apiKey: env.OPENROUTER_API_KEY, fetchImpl, supportsEmbed: true,
            baseUrl: baseUrls.openrouter || env.OPENROUTER_BASE_URL || 'https://openrouter.ai/api/v1',
            extraHeaders: { 'X-Title': 'Ariel' },
        });
    }
    return out;
}
