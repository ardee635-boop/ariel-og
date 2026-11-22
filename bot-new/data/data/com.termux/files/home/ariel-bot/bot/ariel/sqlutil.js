// Pure helpers (no pg import) so they can be tested without a database.
import crypto from 'crypto';

export const DEFAULT_EMBED_DIM = 768;

// pgvector's HNSW index supports up to 2000 dimensions.
export function renderSql(sql, { dim = DEFAULT_EMBED_DIM } = {}) {
    const d = Number(dim);
    if (!Number.isInteger(d) || d < 2 || d > 2000) {
        throw new Error(`embed dim must be an integer between 2 and 2000 (HNSW limit), got ${dim}`);
    }
    return sql.split('{{EMBED_DIM}}').join(String(d));
}

// pg sends vectors as text: '[0.1,0.2,...]' (use with a $n::vector cast).
export function toVector(arr) {
    if (!Array.isArray(arr) || !arr.length) throw new Error('toVector: need a non-empty array');
    return '[' + arr.map((x) => {
        const n = Number(x);
        if (!Number.isFinite(n)) throw new Error('toVector: non-finite value');
        return n;
    }).join(',') + ']';
}

export function checksum(text) {
    return crypto.createHash('sha256').update(text).digest('hex').slice(0, 16);
}
