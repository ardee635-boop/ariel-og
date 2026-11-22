// bot/wmode/tools/fs_tools.js — read / search / create / edit / delete files inside the workspace.
// Every write is re-read and hashed afterwards, so "file created" is something the tool proved, not assumed.
import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import { ToolError, SKIP_DIRS } from './sandbox.js';

const sha = (buf) => crypto.createHash('sha256').update(buf).digest('hex').slice(0, 12);
const isBinary = (buf) => buf.subarray(0, 4000).includes(0);

async function readText(abs, maxBytes) {
    const st = await fs.stat(abs).catch(() => null);
    if (!st) throw new ToolError('file does not exist', 'not_found');
    if (!st.isFile()) throw new ToolError('not a regular file', 'not_file');
    if (st.size > maxBytes * 20) throw new ToolError(`file is too large (${st.size} bytes)`, 'too_large');
    const buf = await fs.readFile(abs);
    if (isBinary(buf)) throw new ToolError('binary file', 'binary');
    return buf.toString('utf8');
}

async function writeVerified(abs, rel, content, maxWrite, { exclusive = false } = {}) {
    if (Buffer.byteLength(content) > maxWrite) throw new ToolError(`content is larger than the ${maxWrite} byte limit`, 'too_large');
    await fs.mkdir(path.dirname(abs), { recursive: true });
    const tmp = `${abs}.wm-${process.pid}.tmp`;
    await fs.writeFile(tmp, content, 'utf8');
    try {
        if (exclusive) { await fs.link(tmp, abs).catch((e) => { throw e.code === 'EEXIST' ? new ToolError('file already exists (use edit_file)', 'exists') : e; }); await fs.unlink(tmp); }
        else await fs.rename(tmp, abs);
    } catch (e) { await fs.unlink(tmp).catch(() => {}); throw e; }
    const back = await fs.readFile(abs);
    if (sha(back) !== sha(Buffer.from(content, 'utf8'))) throw new ToolError(`verification failed: ${rel} on disk differs from what was written`, 'verify_failed');
    return { bytes: back.length, sha: sha(back) };
}

export function registerFsTools(registry, { sandbox, settings = {} }) {
    const maxRead = settings.maxReadBytes ?? 60_000;
    const maxWrite = settings.maxWriteBytes ?? 200_000;
    const maxList = settings.maxListEntries ?? 200;
    const maxHits = settings.maxSearchResults ?? 40;

    registry.register({
        name: 'read_file', risk: 'read', args: { path: 'string', start: 'number?', end: 'number?' },
        description: 'Read a text file (optional 1-based line range start..end).',
        async run({ path: p, start, end }) {
            const { abs, rel } = sandbox.resolve(p);
            const lines = (await readText(abs, maxRead)).split('\n');
            const a = Math.max(1, start || 1); const b = Math.min(lines.length, end || lines.length);
            let text = lines.slice(a - 1, b).map((l, i) => `${a + i}\t${l}`).join('\n');
            if (text.length > maxRead) text = `${text.slice(0, maxRead)}\n…[clipped; ask for a narrower line range]`;
            return { output: `${rel} (${lines.length} lines, showing ${a}-${b})\n${text}`, meta: { path: rel, lines: lines.length } };
        },
    });

    registry.register({
        name: 'list_dir', risk: 'read', args: { path: 'string?' },
        description: 'List files and folders in a workspace directory ("." for the root).',
        async run({ path: p }) {
            const { abs, rel } = sandbox.resolve(p || '.');
            const st = await fs.stat(abs).catch(() => null);
            if (!st?.isDirectory()) throw new ToolError('not a directory', 'not_found');
            const ents = (await fs.readdir(abs, { withFileTypes: true })).filter((e) => !sandbox.isSecretName(e.name)).sort((x, y) => x.name.localeCompare(y.name));
            const shown = ents.slice(0, maxList).map((e) => (e.isDirectory() ? `${e.name}/` : e.name));
            return { output: `${rel}: ${ents.length} entries\n${shown.join('\n')}${ents.length > maxList ? '\n…' : ''}`, meta: { count: ents.length } };
        },
    });

    registry.register({
        name: 'search_code', risk: 'read', args: { query: 'string', path: 'string?', regex: 'boolean?' },
        description: 'Find lines matching a text (or regex) in files under a directory. Skips node_modules, .git, binaries, secrets.',
        async run({ query, path: p, regex }) {
            const { abs, rel } = sandbox.resolve(p || '.');
            let re;
            try { re = regex ? new RegExp(query, 'i') : null; } catch { throw new ToolError('invalid regex', 'bad_args'); }
            const needle = String(query).toLowerCase();
            const hits = []; let scanned = 0;
            async function walk(dir) {
                for (const e of await fs.readdir(dir, { withFileTypes: true })) {
                    if (hits.length >= maxHits || scanned > 3000) return;
                    if (e.isSymbolicLink() || sandbox.isSecretName(e.name)) continue;
                    const full = path.join(dir, e.name);
                    if (e.isDirectory()) { if (!SKIP_DIRS.has(e.name)) await walk(full); continue; }
                    const st = await fs.stat(full); if (st.size > 1_000_000) continue;
                    const buf = await fs.readFile(full); scanned++;
                    if (isBinary(buf)) continue;
                    buf.toString('utf8').split('\n').forEach((line, i) => {
                        if (hits.length < maxHits && (re ? re.test(line) : line.toLowerCase().includes(needle))) hits.push(`${path.relative(sandbox.root, full).split(path.sep).join('/')}:${i + 1}: ${line.trim().slice(0, 200)}`);
                    });
                }
            }
            const st = await fs.stat(abs).catch(() => null);
            if (!st) throw new ToolError('path does not exist', 'not_found');
            if (st.isDirectory()) await walk(abs);
            else { const t = await readText(abs, maxRead); t.split('\n').forEach((l, i) => { if (hits.length < maxHits && (re ? re.test(l) : l.toLowerCase().includes(needle))) hits.push(`${rel}:${i + 1}: ${l.trim().slice(0, 200)}`); }); }
            return { output: hits.length ? `${hits.length} match(es)${hits.length >= maxHits ? ' (limit reached)' : ''}\n${hits.join('\n')}` : 'no matches', meta: { matches: hits.length, scanned } };
        },
    });

    registry.register({
        name: 'create_file', risk: 'write', args: { path: 'string', content: 'string' },
        description: 'Create a NEW file (fails if it exists). Parent folders are created. The result is verified on disk.',
        async run({ path: p, content }) {
            const { abs, rel } = sandbox.resolve(p, { write: true });
            const v = await writeVerified(abs, rel, content, maxWrite, { exclusive: true });
            return { output: `created ${rel} (${v.bytes} bytes, sha ${v.sha}) — verified on disk`, meta: { path: rel, ...v } };
        },
    });

    registry.register({
        name: 'edit_file', risk: 'write', args: { path: 'string', old: 'string', new: 'string' },
        description: 'Replace one exact piece of text in an existing file. "old" must appear exactly once. Verified on disk.',
        async run({ path: p, old, new: neu }) {
            const { abs, rel } = sandbox.resolve(p, { write: true });
            const text = await readText(abs, maxRead);
            const count = text.split(old).length - 1;
            if (count === 0) throw new ToolError('"old" text not found — read the file again and copy it exactly', 'no_match');
            if (count > 1) throw new ToolError(`"old" text appears ${count} times — include more surrounding lines`, 'ambiguous');
            const v = await writeVerified(abs, rel, text.replace(old, () => neu), maxWrite);
            return { output: `edited ${rel} (${v.bytes} bytes, sha ${v.sha}) — verified on disk`, meta: { path: rel, ...v } };
        },
    });

    registry.register({
        name: 'delete_file', risk: 'danger', args: { path: 'string' },
        description: 'Delete one file. Always needs user approval.',
        async run({ path: p }) {
            const { abs, rel } = sandbox.resolve(p, { write: true });
            const st = await fs.stat(abs).catch(() => null);
            if (!st?.isFile()) throw new ToolError('not a file', 'not_found');
            await fs.unlink(abs);
            if (await fs.stat(abs).catch(() => null)) throw new ToolError('verification failed: file still exists', 'verify_failed');
            return { output: `deleted ${rel} — verified`, meta: { path: rel } };
        },
    });
    return registry;
}
