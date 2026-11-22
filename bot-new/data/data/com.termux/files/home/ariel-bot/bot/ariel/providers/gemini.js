// Google Gemini (generativelanguage v1beta). Request shape follows what the
// Python engine already uses successfully (engine/rpg/llm_models.py).
import { postJson, cleanText, normalize } from './http.js';

const TASK = { document: 'RETRIEVAL_DOCUMENT', query: 'RETRIEVAL_QUERY' };

export function makeGemini({ apiKey, baseUrl = 'https://generativelanguage.googleapis.com/v1beta', fetchImpl }) {
    const headers = () => ({ 'x-goog-api-key': apiKey });

    return {
        name: 'gemini',
        capabilities: { structured: true, embed: true },

        async chat(entry, req, signal) {
            const system = [];
            const contents = [];
            for (const m of req.messages) {
                if (m.role === 'system') { system.push(m.content); continue; }
                const role = m.role === 'assistant' ? 'model' : 'user';
                const last = contents[contents.length - 1];
                if (last && last.role === role) last.parts[0].text += '\n' + m.content;   // Gemini wants alternating turns
                else contents.push({ role, parts: [{ text: m.content }] });
            }
            const generationConfig = {
                // Gemini counts hidden "thinking" tokens inside this cap: leave headroom.
                maxOutputTokens: req.maxTokens + (entry.headroom ?? 256),
                temperature: req.temperature,
            };
            if (req.schema && entry.structured) {
                generationConfig.responseMimeType = 'application/json';
                if (entry.structured !== 'object') generationConfig.responseJsonSchema = req.schema;
            }
            const body = { contents: contents.length ? contents : [{ role: 'user', parts: [{ text: '.' }] }], generationConfig };
            if (system.length) body.systemInstruction = { parts: [{ text: system.join('\n\n') }] };

            const j = await postJson(`${baseUrl}/models/${entry.model}:generateContent`, {
                headers: headers(), body, signal, fetchImpl, provider: 'gemini', model: entry.model,
            });
            const cand = j?.candidates?.[0];
            const parts = cand?.content?.parts || [];
            const um = j?.usageMetadata || {};
            return {
                text: cleanText(parts.filter((p) => !p.thought).map((p) => p.text || '').join('')),
                tokensIn: um.promptTokenCount ?? 0,
                tokensOut: (um.candidatesTokenCount ?? 0) + (um.thoughtsTokenCount ?? 0),
                finish: cand?.finishReason ?? null,
            };
        },

        async embed(entry, texts, opts, signal) {
            const taskType = TASK[opts?.kind] || undefined;
            const requests = texts.map((t) => ({
                model: `models/${entry.model}`,
                content: { parts: [{ text: t }] },
                ...(taskType ? { taskType } : {}),
                ...(entry.dim ? { outputDimensionality: entry.dim } : {}),
            }));
            const j = await postJson(`${baseUrl}/models/${entry.model}:batchEmbedContents`, {
                headers: headers(), body: { requests }, signal, fetchImpl, provider: 'gemini', model: entry.model,
            });
            // Reduced-dimension Gemini vectors are not unit length: normalise so cosine behaves.
            return { vectors: (j?.embeddings || []).map((e) => normalize(e.values)), tokensIn: 0 };
        },
    };
}
