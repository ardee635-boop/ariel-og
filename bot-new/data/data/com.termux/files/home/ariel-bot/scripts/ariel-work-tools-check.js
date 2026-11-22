#!/usr/bin/env node
// Work Mode tool checks (offline, temp folder): node scripts/ariel-work-tools-check.js
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createSandbox } from '../bot/wmode/tools/sandbox.js';
import { createToolRegistry } from '../bot/wmode/tools/index.js';
import { registerFsTools } from '../bot/wmode/tools/fs_tools.js';
import { registerCmdTools, tokenize } from '../bot/wmode/tools/cmd_tools.js';
import { resolveSettings } from '../bot/wmode/settings.js';

const fails = [];
const check = (ok, what) => { console.log(`${ok ? '✓' : '✗'} ${what}`); if (!ok) fails.push(what); };

const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'wm-tools-'));
const root = path.join(tmp, 'ws'); const outside = path.join(tmp, 'outside');
fs.mkdirSync(outside); fs.writeFileSync(path.join(outside, 'secret.txt'), 'top secret');
const settings = resolveSettings({}, {});
const sandbox = createSandbox({ root });
const settingsCmd = { ...settings, commandTimeoutMs: 1500 };
const reg = registerCmdTools(registerFsTools(createToolRegistry({ settings: settingsCmd }), { sandbox, settings: settingsCmd }), { sandbox, settings: settingsCmd });
const call = (n, a, c) => reg.call(n, a, c);

// sandbox
check(!(await call('read_file', { path: '../outside/secret.txt' })).ok, 'dotdot escape blocked');
check((await call('read_file', { path: '/etc/passwd' })).code === 'outside_workspace', 'absolute path blocked');
fs.symlinkSync(outside, path.join(root, 'link'));
check(!(await call('read_file', { path: 'link/secret.txt' })).ok, 'symlink escape blocked');
check(!(await call('create_file', { path: 'link/new.txt', content: 'x' })).ok && !fs.existsSync(path.join(outside, 'new.txt')), 'write through symlink blocked');
check((await call('create_file', { path: '.env', content: 'K=1' })).code === 'protected', '.env protected');
check((await call('create_file', { path: '.git/config', content: 'x' })).code === 'protected', 'write into .git blocked');

// create / read / edit
const c = await call('create_file', { path: 'src/a.js', content: 'const a = 1;\nconst b = 2;\n' });
check(c.ok && fs.readFileSync(path.join(root, 'src/a.js'), 'utf8').includes('const b'), 'create_file writes + verifies');
check((await call('create_file', { path: 'src/a.js', content: 'again' })).code === 'exists', 'create_file refuses to overwrite');
const r = await call('read_file', { path: 'src/a.js', start: 2, end: 2 });
check(r.ok && r.output.includes('2\tconst b = 2;') && !r.output.includes('const a'), 'read_file line range');
check((await call('edit_file', { path: 'src/a.js', old: 'const b = 2;', new: 'const b = 3;' })).ok && fs.readFileSync(path.join(root, 'src/a.js'), 'utf8').includes('b = 3'), 'edit_file replaces');
check((await call('edit_file', { path: 'src/a.js', old: 'nope', new: 'x' })).code === 'no_match', 'edit_file no match reported');
await call('create_file', { path: 'dup.txt', content: 'x\nx\n' });
check((await call('edit_file', { path: 'dup.txt', old: 'x', new: 'y' })).code === 'ambiguous', 'edit_file ambiguous reported');
check((await call('edit_file', { path: 'src/a.js', old: 'a = 1', new: '$&$&' })).ok && fs.readFileSync(path.join(root, 'src/a.js'), 'utf8').includes('$&$&'), 'edit_file treats $ literally');
check(!fs.readdirSync(path.join(root, 'src')).some((f) => f.endsWith('.tmp')), 'no temp files left');

// list / search
check((await call('list_dir', { path: '.' })).output.includes('src/'), 'list_dir');
fs.mkdirSync(path.join(root, 'node_modules/x'), { recursive: true }); fs.writeFileSync(path.join(root, 'node_modules/x/i.js'), 'const b = 9');
const s = await call('search_code', { query: 'const b' });
check(s.ok && s.output.includes('src/a.js:2') && !s.output.includes('node_modules'), 'search_code skips node_modules');
check((await call('search_code', { query: 'const\\s+b', regex: true })).output.includes('src/a.js'), 'search_code regex');
check(!(await call('search_code', { query: '(', regex: true })).ok, 'bad regex reported');

// approval
const d = await call('delete_file', { path: 'dup.txt' });
check(d.needsApproval === true && fs.existsSync(path.join(root, 'dup.txt')), 'delete_file blocked without approval');
check((await call('delete_file', { path: 'dup.txt' }, { approved: true })).ok && !fs.existsSync(path.join(root, 'dup.txt')), 'delete_file runs when approved');
check((await call('nope', {})).code === 'unknown_tool' && (await call('read_file', {})).code === 'bad_args', 'unknown tool / missing args');
check((await call('create_file', { path: 'big.txt', content: 'x'.repeat(settings.maxWriteBytes + 1) })).code === 'too_large', 'write size limit');

// ── 5B: commands ────────────────────────────────────────────────
const w = (f, t) => { fs.mkdirSync(path.dirname(path.join(root, f)), { recursive: true }); fs.writeFileSync(path.join(root, f), t); };
for (const bad of ['ls; rm -rf /', 'node a.js | cat', 'node a.js > x', 'node `id`', 'node $(id)', 'node a.js && id']) {
    check((await call('run_command', { command: bad })).code === 'blocked', `shell syntax blocked: ${bad}`);
}
check(tokenize('node "a b.js" \'c\'').join('|') === 'node|a b.js|c', 'tokenizer quotes');
for (const bad of ['rm a.js', 'curl http://x', 'npx cowsay', 'node -e 1', 'node -p 1', 'python3 -c 1', 'npm install left-pad', 'git push', 'git diff --output=x', 'git -c core.pager=sh log', 'node ../outside/secret.txt', 'node /etc/passwd']) {
    const r = await call('run_command', { command: bad }, { approved: true });
    check(!r.ok && ['blocked', 'outside_workspace'].includes(r.code), `refused even when approved: ${bad}`);
}
check((await call('run_command', { command: 'node --version' })).output.includes('exit 0'), 'node --version runs without approval');
w('ok.js', "console.log('hello', Object.keys(process.env).sort().join(','));");
w('bad.js', 'const = ;');
w('loop.js', 'while (true) {}');
w('sub/where.js', "console.log(process.cwd());");
const ap = await call('run_command', { command: 'node ok.js' });
check(ap.needsApproval === true, 'running code needs approval');
process.env.SECRET_API_KEY = 'leak-me'; process.env.SUPABASE_DB_URL = 'postgres://x';
const run = await call('run_command', { command: 'node ok.js' }, { approved: true });
check(run.ok && run.output.includes('hello') && run.meta.exitCode === 0, 'approved command runs');
check(!run.output.includes('SECRET_API_KEY') && !run.output.includes('SUPABASE_DB_URL'), 'secrets not passed to the command');
const syn = await call('run_command', { command: 'node --check bad.js' });
check(syn.ok && syn.meta.exitCode !== 0 && /SyntaxError/.test(syn.output), 'node --check reports syntax errors, no approval');
const lp = await call('run_command', { command: 'node loop.js' }, { approved: true });
check(lp.meta.timedOut === true && lp.output.includes('TIMED OUT') && lp.meta.ms < 5000, 'infinite loop killed at timeout');
check((await call('run_command', { command: 'node where.js', cwd: 'sub' }, { approved: true })).output.includes(path.join(sandbox.root, 'sub')), 'cwd option');
check(!(await call('run_command', { command: 'node ok.js', cwd: '../outside' }, { approved: true })).ok, 'cwd cannot leave workspace');
check((await call('run_command', { command: 'node missing.js' }, { approved: true })).meta.exitCode !== 0, 'missing file: nonzero exit reported');
check((await call('run_command', { command: 'node .env' }, { approved: true })).code === 'protected', 'secret file cannot be run');
// git (read-only, no approval)
const { execFileSync } = await import('node:child_process');
const git = (...a) => execFileSync('git', ['-c', 'user.name=t', '-c', 'user.email=t@t', ...a], { cwd: root, stdio: 'ignore' });
git('init', '-q'); git('add', 'ok.js'); git('commit', '-qm', 'init'); w('ok.js', "console.log('changed');");
const gs = await call('run_command', { command: 'git status --short' });
check(gs.ok && gs.output.includes('ok.js'), 'git status works without approval');
check((await call('run_command', { command: 'git diff' })).output.includes('changed'), 'git diff works');
// tests
check((await call('run_tests', {}, { approved: true })).code === 'no_tests', 'run_tests: no tests yet -> no_tests');
w('math.test.js', "import test from 'node:test'; import assert from 'node:assert'; test('adds', () => assert.equal(1 + 1, 2));");
check((await call('run_tests', {})).needsApproval === true, 'run_tests needs approval by default');
const t1 = await call('run_tests', {}, { approved: true });
check(t1.ok && t1.meta.passed === true && t1.output.includes('tests PASSED'), 'run_tests PASSED with real exit code');
w('math.test.js', "import test from 'node:test'; import assert from 'node:assert'; test('adds', () => assert.equal(1 + 1, 3));");
const t2 = await call('run_tests', {}, { approved: true });
check(t2.ok && t2.meta.passed === false && t2.output.includes('tests FAILED'), 'failing tests reported as FAILED');
fs.rmSync(path.join(root, 'math.test.js')); fs.rmSync(path.join(root, 'ok.js'));
check((await call('run_tests', {}, { approved: true })).code === 'no_tests', 'run_tests: no tests found is an error');
const auto = createToolRegistry({ settings: { ...settingsCmd, autoApproveTests: true } });
registerCmdTools(auto, { sandbox, settings: { ...settingsCmd, autoApproveTests: true } });
w('a.test.js', "import test from 'node:test'; test('x', () => {});");
check((await auto.call('run_tests', {})).ok, 'autoApproveTests setting skips approval');

fs.rmSync(tmp, { recursive: true, force: true });
console.log(fails.length ? `\n${fails.length} FAILED` : '\nall tool checks passed');
process.exit(fails.length ? 1 : 0);
