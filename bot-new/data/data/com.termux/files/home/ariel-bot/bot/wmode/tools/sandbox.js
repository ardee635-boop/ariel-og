// bot/wmode/tools/sandbox.js — every filesystem path a tool touches goes through here.
// Rules: stay inside the workspace root (symlinks resolved), never touch secrets, never write into .git.
import fs from 'node:fs';
import path from 'node:path';

export class ToolError extends Error {
    constructor(message, code = 'tool_error') { super(message); this.name = 'ToolError'; this.code = code; }
}

const SECRET_NAME = /^(\.env(\..*)?|.*\.pem|.*\.key|id_rsa.*|id_ed25519.*|\.npmrc|\.netrc|credentials(\.json)?)$/i;
const SECRET_DIR = new Set(['.ssh', '.aws', '.gnupg']);
export const SKIP_DIRS = new Set(['node_modules', '.git', 'dist', 'build', '.cache']);

export function createSandbox({ root }) {
    if (!root) throw new Error('sandbox needs a root');
    fs.mkdirSync(root, { recursive: true });
    const base = fs.realpathSync(root);
    const inside = (p) => p === base || p.startsWith(base + path.sep);

    // Nearest existing ancestor, resolved through symlinks, so a link inside the workspace cannot lead out of it.
    function realish(abs) {
        let cur = abs; const tail = [];
        for (;;) {
            try { return path.join(fs.realpathSync(cur), ...tail.reverse()); }
            catch (e) {
                if (e.code !== 'ENOENT' && e.code !== 'ENOTDIR') throw new ToolError(`cannot resolve path: ${e.code}`, 'bad_path');
                const up = path.dirname(cur);
                if (up === cur) throw new ToolError('cannot resolve path', 'bad_path');
                tail.push(path.basename(cur)); cur = up;
            }
        }
    }

    function resolve(rel, { write = false } = {}) {
        const s = String(rel ?? '').trim();
        if (!s || s.includes('\0')) throw new ToolError('path is empty or invalid', 'bad_path');
        if (path.isAbsolute(s)) throw new ToolError('use a path relative to the workspace', 'outside_workspace');
        const abs = path.resolve(base, s);
        if (!inside(abs)) throw new ToolError('path is outside the workspace', 'outside_workspace');
        const real = realish(abs);
        if (!inside(real)) throw new ToolError('path leaves the workspace through a symlink', 'outside_workspace');
        const parts = path.relative(base, real).split(path.sep).filter(Boolean);
        if (parts.some((p) => SECRET_DIR.has(p)) || SECRET_NAME.test(parts.at(-1) || '')) throw new ToolError('that file is protected (secrets)', 'protected');
        if (write && parts.includes('.git')) throw new ToolError('writing into .git is not allowed', 'protected');
        return { abs: real, rel: parts.join('/') || '.' };
    }

    return { root: base, resolve, inside, isSecretName: (n) => SECRET_NAME.test(n) };
}
