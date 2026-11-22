#!/usr/bin/env node
// scripts/host_images.mjs - move every i.ibb.co picture into your GitHub repo and point the code at it.
//
//   node scripts/host_images.mjs              dry run: lists what it would download + rewrite
//   node scripts/host_images.mjs --write      download into assets/cdn/ and rewrite the links
//   node scripts/host_images.mjs --write --push   ...then git add / commit / push
//   add  --repo owner/name --branch main  if this folder is not a git clone (otherwise read from `git remote`)
//
// Needs the repo to be PUBLIC (raw.githubusercontent.com does not serve private repos).
import fs from 'fs';
import path from 'path';
import { execSync } from 'child_process';
import { fileURLToPath } from 'url';

const ROOT  = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const args  = process.argv.slice(2);
const has   = (f) => args.includes(f);
const val   = (f) => { const i = args.indexOf(f); return i >= 0 ? args[i + 1] : null; };
const WRITE = has('--write') || has('--push');
const OUT   = path.join(ROOT, 'assets', 'cdn');

const sh = (c) => { try { return execSync(c, { cwd: ROOT, stdio: ['ignore', 'pipe', 'ignore'] }).toString().trim(); } catch { return ''; } };

let repo = val('--repo'), branch = val('--branch');
if (!repo) {
    const m = sh('git remote get-url origin').match(/github\.com[:/]+([^/]+\/[^/.\s]+)(?:\.git)?\s*$/i);
    if (m) repo = m[1];
}
if (!branch) branch = sh('git rev-parse --abbrev-ref HEAD') || 'main';
if (!repo) { console.error('Could not tell your GitHub repo. Run with  --repo yourname/ariel-bot  [--branch main]'); process.exit(1); }
const RAW = `https://raw.githubusercontent.com/${repo}/${branch}/assets/cdn/`;
console.log(`Repo ${repo} @ ${branch}\nNew links look like: ${RAW}<file>\n`);

const SKIP_DIR = new Set(['node_modules', '.git', 'broken', 'cdn', '__pycache__', '.cache']);
const EXT      = new Set(['.js', '.mjs', '.py', '.json']);
const files = [];
(function walk(d) {
    for (const e of fs.readdirSync(d, { withFileTypes: true })) {
        if (e.isDirectory()) { if (!SKIP_DIR.has(e.name)) walk(path.join(d, e.name)); }
        else if (EXT.has(path.extname(e.name)) && e.name !== 'package-lock.json') files.push(path.join(d, e.name));
    }
})(ROOT);

const URL_RE = /https:\/\/i\.ibb\.co\/[A-Za-z0-9_./%~+-]+/g;
const found = new Map();                         // url -> [files]
for (const f of files) {
    const txt = fs.readFileSync(f, 'utf8');
    for (const u of new Set(txt.match(URL_RE) || [])) { if (!found.has(u)) found.set(u, []); found.get(u).push(f); }
}
const nameOf = (u) => {                          // i.ibb.co/<id>/<name.ext>  ->  <id>-<name.ext>
    const seg = new URL(u).pathname.split('/').filter(Boolean).map(decodeURIComponent);
    return seg.join('-').replace(/[^A-Za-z0-9._-]+/g, '_').toLowerCase();
};
console.log(`${found.size} different ibb pictures in ${new Set([...found.values()].flat()).size} files.`);
if (!WRITE) {
    for (const [u, fs_] of found) console.log(`  ${u}\n    -> ${RAW}${nameOf(u)}   (${fs_.length} file${fs_.length > 1 ? 's' : ''})`);
    console.log('\nDry run only. Add --write to do it.');
    process.exit(0);
}

fs.mkdirSync(OUT, { recursive: true });
const ok = new Map(), bad = [];
async function grab(u) {
    const dest = path.join(OUT, nameOf(u));
    if (fs.existsSync(dest) && fs.statSync(dest).size > 0) return true;
    for (let i = 0; i < 3; i++) {
        try {
            const r = await fetch(u, { headers: { 'user-agent': 'Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 Chrome/120 Mobile Safari/537.36', referer: 'https://ibb.co/' }, signal: AbortSignal.timeout(25000) });
            if (!r.ok) throw new Error(`HTTP ${r.status}`);
            const buf = Buffer.from(await r.arrayBuffer());
            if (buf.length < 200 || /^\s*</.test(buf.subarray(0, 20).toString())) throw new Error('not an image');
            fs.writeFileSync(dest, buf);
            return true;
        } catch (e) { if (i === 2) { bad.push(`${u}  (${e.message})`); return false; } await new Promise((r) => setTimeout(r, 1200)); }
    }
}
const queue = [...found.keys()];
await Promise.all(Array.from({ length: 4 }, async () => { while (queue.length) { const u = queue.shift(); if (await grab(u)) ok.set(u, RAW + nameOf(u)); process.stdout.write('.'); } }));
console.log(`\nDownloaded ${ok.size}/${found.size}.`);
if (bad.length) console.log('FAILED (links left as they were):\n  ' + bad.join('\n  '));

let changed = [];
for (const f of new Set([...found.values()].flat())) {
    let txt = fs.readFileSync(f, 'utf8'), n = txt;
    for (const [u, r] of ok) n = n.split(u).join(r);
    if (n !== txt) { fs.writeFileSync(f, n); changed.push(path.relative(ROOT, f)); }
}
console.log(`Rewrote links in ${changed.length} files.`);
const first = [...ok.values()][0];
if (first) console.log(`\nTest one in WhatsApp:  .preview d ${first}`);

if (has('--push')) {
    const run = (c) => { console.log('$ ' + c); execSync(c, { cwd: ROOT, stdio: 'inherit' }); };
    run('git add assets/cdn');
    for (const c of changed) run(`git add "${c}"`);
    run('git commit -m "Host pictures in the repo (assets/cdn) instead of ibb"');
    run('git push');
} else {
    console.log('\nNext:\n  git add assets/cdn ' + (changed.length ? '-u' : '') + '\n  git commit -m "Host pictures in repo"\n  git push\nThen wait ~1 min and try the .preview line above.');
}
