// Groq and OpenRouter both speak the OpenAI chat-completions dialect.
import { AIError } from './errors.js';
import { postJson, cleanText, normalize } from './http.js';

export function makeOpenAICompat({ name, apiKey, baseUrl, extraHeaders = {}, supportsEmbed = false, fetchImpl }) {
    const headers = () => ({ Authorization: `Bearer ${apiKey}`, ...extraHeaders });

    return {
        name,
        capabilities: { structured: true, embed: supportsEmbed },

        async chat(entry, req, signal) {
            const body = {
                model: entry.model,
                messages: req.messages,
                max_tokens: req.maxTokens + (entry.headroom || 0),   // reasoning models spend hidden tokens
                temperature: req.temperature,
            };
            if (entry.reasoning) body.reasoning_effort = entry.reasoning;   // e.g. gpt-oss on Groq
            if (req.schema && entry.structured) {
                body.response_format = entry.structured === 'object'
                    ? { type: 'json_object' }
                    : { type: 'json_schema', json_schema: { name: 'ariel_out', schema: req.schema } };
            }
            const j = await postJson(`${baseUrl}/chat/completions`, {
                headers: headers(), body, signal, fetchImpl, provider: name, model: entry.model,
            });
            const choice = j?.choices?.[0];
            return {
                text: cleanText(choice?.message?.content),
                tokensIn: j?.usage?.prompt_tokens ?? 0,
                tokensOut: j?.usage?.completion_tokens ?? 0,
                finish: choice?.finish_reason ?? null,
            };
        },

        async embed(entry, texts, opts, signal) {
            if (!supportsEmbed) throw new AIError('bad', `${name}: no embeddings endpoint`, { provider: name });
            const body = { model: entry.model, input: texts };
            if (entry.dim) body.dimensions = entry.dim;
            const j = await postJson(`${baseUrl}/embeddings`, {
                headers: headers(), body, signal, fetchImpl, provider: name, model: entry.model,
            });
            const rows = (j?.data || []).slice().sort((a, b) => a.index - b.index);
            return {
                vectors: rows.map((r) => normalize(r.embedding)),
                tokensIn: j?.usage?.prompt_tokens ?? j?.usage?.total_tokens ?? 0,
            };
        },
    };
}
