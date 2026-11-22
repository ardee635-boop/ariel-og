// bot/wmode/tools/cmd_tools.js — run_command and run_tests.
// No shell, ever: a command is split into argv, checked against a per-binary policy, and spawned directly.
// "safe" commands (version checks, syntax checks, read-only git) run freely; anything that executes workspace
// code needs approval. NOTE: approval + a scrubbed environment + timeout is the boundary here. It is not a
// container — approved code runs with the bot's OS permissions, so approve only what you have looked at.
import fs from 'node:fs';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { ToolError } from './sandbox.js';

const META = /[;|&<>`$()\n\r\\]/;
const NAME = /^[\w:.-]+$/;
const GIT_FLAGS = new Set(['--stat', '--oneline', '--name-only', '--name-status', '--short', '-s', '--cached', '--no-color', '--staged']);
const PY_TEST_FLAGS = new Set(['-q', '-v', '-x', '-vv']);

export function tokenize(cmd) {
    const s = String(cmd || '').trim();
    if (!s) throw new ToolError('empty command', 'bad_args');
    if (META.test(s)) throw new ToolError('shell syntax (; | & < > ` $ ( ) \\) is not allowed — one plain command only', 'blocked');
    const out = []; let cur = ''; let q = null; let has = false;
    for (const ch of s) {
        if (q) { if (ch === q) q = null; else cur += ch; }
        else if (ch === '"' || ch === "'") { q = ch; has = true; }
        else if (/\s/.test(ch)) { if (cur || has) out.push(cur); cur = ''; has = false; }
        else cur += ch;
    }
    if (q) throw new ToolError('unclosed quote', 'bad_args');
    if (cur || has) out.push(cur);
    return out;
}

// Returns { argv, safe } or throws ToolError. File arguments are resolved through the sandbox.
export function classify(tokens, sandbox) {
    let [bin, ...a] = tokens;
    if (bin === 'python') bin = 'python3';
    const file = (f, exts) => {
        const r = sandbox.resolve(f);
        if (exts && !exts.some((x) => r.rel.endsWith(x))) throw new ToolError(`expected a ${exts.join('/')} file`, 'blocked');
        return r.rel;
    };
    const no = (why) => { throw new ToolError(`not allowed: ${why}. Allowed: node, npm, python3, git (read-only).`, 'blocked'); };

    if (bin === 'node') {
        if (a.length === 1 && a[0] === '--version') return { argv: [bin, ...a], safe: true };
        if (a[0] === '--check' && a.length === 2) return { argv: [bin, '--check', file(a[1], ['.js', '.mjs', '.cjs'])], safe: true };
        if (a[0] === '--test') return { argv: [bin, '--test', ...a.slice(1).map((f) => file(f))], safe: false };
        if (a[0] && !a[0].startsWith('-')) return { argv: [bin, file(a[0], ['.js', '.mjs', '.cjs']), ...a.slice(1)], safe: false };
        no('node flags other than --version, --check, --test (no -e / -p)');
    }
    if (bin === 'npm') {
        if (a.length === 1 && a[0] === '--version') return { argv: [bin, ...a], safe: true };
        if (a.length === 1 && a[0] === 'test') return { argv: [bin, 'test'], safe: false };
        if (a[0] === 'run' && a.length === 2 && NAME.test(a[1])) return { argv: [bin, 'run', a[1]], safe: false };
        no('npm is limited to: test, run <script>, --version (no install)');
    }
    if (bin === 'python3') {
        if (a.length === 1 && a[0] === '--version') return { argv: [bin, ...a], safe: true };
        if (a[0] === '-m' && a[1] === 'py_compile' && a.length === 3) return { argv: [bin, '-m', 'py_compile', file(a[2], ['.py'])], safe: true };
        if (a[0] === '-m' && (a[1] === 'pytest' || a[1] === 'unittest')) {
            const rest = a.slice(2).map((x) => (x.startsWith('-') ? (PY_TEST_FLAGS.has(x) || a[1] === 'unittest' && x === 'discover' ? x : no(`flag ${x}`)) : (x === 'discover' ? x : file(x))));
            return { argv: [bin, '-m', a[1], ...rest], safe: false };
        }
        if (a[0] && !a[0].startsWith('-')) return { argv: [bin, file(a[0], ['.py']), ...a.slice(1)], safe: false };
        no('python3 flags other than --version, -m pytest|unittest|py_compile (no -c)');
    }
    if (bin === 'git') {
        const sub = a[0];
        if (!['status', 'diff', 'log', 'show'].includes(sub)) no('git is limited to status, diff, log, show');
        const rest = a.slice(1).map((x) => {
            if (x.startsWith('-')) return GIT_FLAGS.has(x) || /^-\d{1,3}$/.test(x) ? x : no(`git flag ${x}`);
            if (/^[\w./^~@-]+$/.test(x) && !x.includes('..') ) return x.includes('/') || fs.existsSync(path.join(sandbox.root, x)) ? file(x) : x;
            return no(`git argument ${x}`);
        });
        return { argv: [bin, '--no-pager', sub, ...rest], safe: true };
    }
    return no(`"${bin}"`);
}

// Nothing from the bot's environment reaches the command: no API keys, no DB url.
export function cleanEnv(root) {
    return { PATH: process.env.PATH || '/usr/bin:/bin', HOME: root, LANG: 'C.UTF-8', CI: '1', NODE_ENV: 'test', NO_COLOR: '1',
        GIT_PAGER: 'cat', GIT_TERMINAL_PROMPT: '0', GIT_CONFIG_NOSYSTEM: '1', GIT_CONFIG_GLOBAL: '/dev/null', npm_config_update_notifier: 'false' };
}

export function runProcess(argv, { cwd, env, timeoutMs, collectMax = 200_000 }) {
    return new Promise((resolve) => {
        const t0 = Date.now(); let out = ''; let timedOut = false; let done = false;
        const child = spawn(argv[0], argv.slice(1), { cwd, env, shell: false, detached: true, stdio: ['ignore', 'pipe', 'pipe'] });
        const add = (b) => { if (out.length < collectMax) out += b.toString('utf8'); };
        child.stdout.on('data', add); child.stderr.on('data', add);
        const kill = () => { try { process.kill(-child.pid, 'SIGKILL'); } catch { try { child.kill('SIGKILL'); } catch { /* gone */ } } };
        const timer = setTimeout(() => { timedOut = true; kill(); }, timeoutMs);
        const end = (code, signal, err) => { if (done) return; done = true; clearTimeout(timer); kill(); resolve({ code, signal, out: err ? `${out}\n${err}` : out, timedOut, ms: Date.now() - t0 }); };
        child.on('error', (e) => end(null, null, `could not start: ${e.code || e.message}`));
        child.on('close', (code, signal) => end(code, signal));
    });
}

const tail = (s, n) => (s.length > n ? `…[first ${s.length - n} chars cut]\n${s.slice(-n)}` : s);

export function registerCmdTools(registry, { sandbox, settings = {} }) {
    const timeoutMs = settings.commandTimeoutMs ?? 30_000;
    const outChars = settings.commandOutputChars ?? 4000;

    async function exec(argv, cwdRel) {
        const cwd = cwdRel ? sandbox.resolve(cwdRel).abs : sandbox.root;
        if (!fs.statSync(cwd, { throwIfNoEntry: false })?.isDirectory()) throw new ToolError('cwd is not a directory', 'not_found');
        const r = await runProcess(argv, { cwd, env: cleanEnv(sandbox.root), timeoutMs });
        const status = r.timedOut ? `TIMED OUT after ${Math.round(timeoutMs / 1000)}s (killed)` : r.signal ? `killed by ${r.signal}` : `exit ${r.code}`;
        return { r, status, text: `$ ${argv.join(' ')}\n${status} · ${r.ms}ms\n${tail(r.out.trim(), outChars) || '(no output)'}` };
    }

    registry.register({
        name: 'run_command', risk: 'danger', args: { command: 'string', cwd: 'string?' },
        description: 'Run one plain command in the workspace (no shell). Allowed: node (--version, --check f, --test, f.js), npm (test, run <script>), python3 (f.py, -m pytest|unittest|py_compile), git (status, diff, log, show). Running code asks for approval.',
        needsApproval(args) { try { return !classify(tokenize(args.command), sandbox).safe; } catch { return false; } },   // invalid commands fail in run(), nothing to approve
        async run({ command, cwd }) {
            const { argv } = classify(tokenize(command), sandbox);
            const { r, text } = await exec(argv, cwd);
            return { output: text, meta: { exitCode: r.code, timedOut: r.timedOut, ms: r.ms } };
        },
    });

    registry.register({
        name: 'run_tests', risk: 'danger', args: { cwd: 'string?' },
        description: 'Detect and run the project tests in the workspace (npm test, node --test, or python unittest/pytest). Reports PASSED/FAILED with the real exit code.',
        needsApproval: () => settings.autoApproveTests !== true,
        async run({ cwd }) {
            const dir = cwd ? sandbox.resolve(cwd).abs : sandbox.root;
            let argv = null;
            try {
                const pkg = JSON.parse(fs.readFileSync(path.join(dir, 'package.json'), 'utf8'));
                if (pkg.scripts?.test && !/no test specified/.test(pkg.scripts.test)) argv = ['npm', 'test'];
            } catch { /* no package.json */ }
            const names = fs.readdirSync(dir, { recursive: true }).map(String).filter((f) => !/(^|[\\/])(node_modules|\.git)([\\/]|$)/.test(f));
            if (!argv && names.some((f) => /\.(test|spec)\.[cm]?js$/.test(f))) argv = ['node', '--test'];
            if (!argv && names.some((f) => /(^|\/)test_.*\.py$|_test\.py$/.test(f))) argv = names.some((f) => /(^|\/)(pytest\.ini|conftest\.py)$/.test(f)) ? ['python3', '-m', 'pytest', '-q'] : ['python3', '-m', 'unittest', 'discover'];
            if (!argv) throw new ToolError('no tests found (looked for an npm test script, *.test.js, test_*.py)', 'no_tests');
            const { r, text } = await exec(argv, cwd);
            const passed = r.code === 0 && !r.timedOut;
            return { output: `tests ${passed ? 'PASSED' : 'FAILED'} via ${argv.join(' ')}\n${text}`, meta: { exitCode: r.code, passed, timedOut: r.timedOut, command: argv.join(' ') } };
        },
    });
    return registry;
}
