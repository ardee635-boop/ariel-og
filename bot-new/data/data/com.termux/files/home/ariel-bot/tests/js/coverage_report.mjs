// Line coverage from V8's raw coverage (NODE_V8_COVERAGE), no dependencies.
//   NODE_V8_COVERAGE=/tmp/cov node --no-warnings --import ./tests/js/register.mjs tests/js/golden_handler_test.mjs
//   node tests/js/coverage_report.mjs /tmp/cov handler.js commands.js [--lines]
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
const [dir, ...rest] = process.argv.slice(2);
const wantLines = rest.includes('--lines');
const suffixes = rest.filter(a => !a.startsWith('--'));
const perFile = {};                       // path -> Int32Array of max counts per char (merged across dumps)
for (const f of fs.readdirSync(dir)) {
    if (!f.endsWith('.json')) continue;
    const { result } = JSON.parse(fs.readFileSync(path.join(dir, f), 'utf8'));
    for (const script of result) {
        if (!script.url.startsWith('file://') || !suffixes.some(s => script.url.endsWith('/bot/' + s))) continue;
        const p = fileURLToPath(script.url);
        const src = fs.readFileSync(p, 'utf8');
        const counts = new Int32Array(src.length).fill(-1);
        const ranges = script.functions.flatMap(fn => fn.ranges).sort((a, b) => a.startOffset - b.startOffset || b.endOffset - a.endOffset);
        for (const r of ranges) counts.fill(r.count, r.startOffset, Math.min(r.endOffset, src.length));   // inner ranges come later and override
        const prev = perFile[p]?.counts;
        if (prev) for (let i = 0; i < counts.length; i++) counts[i] = Math.max(prev[i], counts[i]);
        perFile[p] = { counts, src };
    }
}
for (const [p, { counts, src }] of Object.entries(perFile)) {
    const lines = src.split('\n'); let off = 0, total = 0, hit = 0; const miss = [];
    lines.forEach((ln, i) => {
        let any = false, cov = false;
        for (let j = 0; j < ln.length; j++) { if (/\s/.test(ln[j])) continue; any = true; if (counts[off + j] > 0) { cov = true; break; } }
        const t = ln.trim();
        if (any && !t.startsWith('//') && !t.startsWith('*') && !t.startsWith('/*') && !/^[}\])\s;,]*$/.test(t)) { total++; if (cov) hit++; else miss.push(i + 1); }
        off += ln.length + 1;
    });
    console.log(`${path.relative(process.cwd(), p)}: ${(100 * hit / total).toFixed(1)}% of ${total} code lines`);
    if (wantLines) { const runs = []; let a = miss[0], b = a; for (const m of miss.slice(1)) { if (m !== b + 1) { runs.push([a, b]); a = m; } b = m; } if (a) runs.push([a, b]); console.log('  never ran:', runs.map(([x, y]) => x === y ? x : `${x}-${y}`).join(', ')); }
}
