import { AIError, kindFromStatus } from './errors.js';

// POST JSON, return parsed JSON, or throw a classified AIError.
// `signal` comes from the caller's timeout (see index.js).
export async function postJson(url, { headers = {}, body, signal, fetchImpl = globalThis.fetch, provider, model }) {
    return requestJson(url, { method: 'POST', headers, body, signal, fetchImpl, provider, model });
}

export async function getJson(url, { headers = {}, signal, fetchImpl = globalThis.fetch, provider } = {}) {
    return requestJson(url, { method: 'GET', headers, signal, fetchImpl, provider, model: null });
}

async function requestJson(url, { method, headers, body, signal, fetchImpl, provider, model }) {
    let res;
    try {
        res = await fetchImpl(url, {
            method,
            headers: { 'Content-Type': 'application/json', ...headers },
            body: body === undefined ? undefined : JSON.stringify(body),
            signal,
        });
    } catch (e) {
        if (e?.name === 'AbortError' || e?.name === 'TimeoutError') {
            throw new AIError('timeout', `${provider}: request timed out`, { provider, model });
        }
        throw new AIError('network', `${provider}: ${e?.cause?.code || e?.message || 'network error'}`, { provider, model });
    }
    const raw = await res.text().catch(() => '');
    if (!res.ok) {
        let msg = raw.slice(0, 300);
        try { const j = JSON.parse(raw); msg = j?.error?.message || j?.message || msg; } catch { /* not json */ }
        throw new AIError(kindFromStatus(res.status), `${provider} ${res.status}: ${msg}`.slice(0, 400),
            { status: res.status, provider, model });
    }
    try {
        return raw ? JSON.parse(raw) : {};
    } catch {
        throw new AIError('bad', `${provider}: response was not JSON`, { status: res.status, provider, model });
    }
}

// Models sometimes leak reasoning as <think>…</think>; never show it.
export function cleanText(s) {
    return String(s ?? '').replace(/<think>[\s\S]*?<\/think>/gi, '').trim();
}

export function normalize(vec) {
    let n = 0;
    for (const x of vec) n += x * x;
    n = Math.sqrt(n) || 1;
    return vec.map((x) => x / n);
}
