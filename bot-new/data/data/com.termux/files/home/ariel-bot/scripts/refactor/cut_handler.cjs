// node --expose-internals tools/cut_handler.cjs   (run from the repo root)
// Slices bot/handler.js's handleMessage into bot/handler/*.js (verbatim statements, AST-verified).
const acorn = require('internal/deps/acorn/acorn/dist/acorn');
const fs = require('fs');
const path = require('path');
const SRC = 'bot/handler.js', BACKUP = '/tmp/handler_orig.js';
if (!fs.existsSync(BACKUP)) fs.copyFileSync(SRC, BACKUP);
const src = fs.readFileSync(BACKUP, 'utf8');
const lines = src.split('\n');
const parse = (s) => acorn.parse(s, { sourceType: 'module', ecmaVersion: 'latest', locations: true });
const ast = parse(src);

const GROUPS = [   // [name, first statement line, last statement line, doc]
 ['entry',          31,   295, 'Early gates, the DM path, text/caption extraction, sender/LID resolution, mentions, quoted text, `lower`, king flag.'],
 ['king_toggles',   300,  426, 'King-only toggles (`.silent on/off`, `.chatdm`, `.forcechatoff`), silent work/card/watch shortcuts and the silent-pool gate.'],
 ['group_lists',    430,  476, '`.groups` and `.linkedgroups`.'],
 ['silent_cmds',    478,  958, 'Silent-cluster commands: silentlink/unlink/chat, label, ssteal, silent menus, mines, sleep windows.'],
 ['silent_watch',   966, 1053, 'Messages inside silent groups (watch-number handling, steals, idle chat reactions).'],
 ['gates',         1065, 1196, 'Link gate, ignored-group gate, per-command rank override, pool toggle commands, normal-pool gate, mute/ignore enforcement.'],
 ['group_admin',   1204, 1314, '`.linkgc` / `.unlinkgc` / `.ignoregc` / `.unignoregc` / `.ignore` / `.unignore`.'],
 ['dev_cmds',      1316, 1531, '`.arielstatus`, `.clearauth`, `.preview`, `.d`, profile pictures, `.ping`/`.test`/`.uptime`/`.stats`/`.owner`, menu of menus.'],
 ['broadcast',     1541, 1656, '`.hidetag`, `.broadcast`, `.resetgroups`, `.help <cmd>`.'],
 ['fun_cmds',      1658, 1878, 'Local image commands, memes, neko actions, joke/truth/dare/wyr.'],
 ['media_cmds',    1881, 2177, 'Stickers: `.sticker`, `.toimg`, `.vv`, `.take`, Ariel sticker packs.'],
 ['web_cmds',      2179, 2373, '`.translate`, `.ship`, `.wallpaper`, `.pint`, `.play`.'],
 ['games',         2375, 2505, '`.spinbottle`, `.kidnap`, `.ttt`, `.note`, `.copilot`.'],
 ['pre_python',    2507, 2574, 'Group-linked/ignored gates, DB handle, activity tracking, participants, antilink, registration lookup.'],
 ['late_cmds',     2589, 2776, '`.btest`, `.listtest`, `.gen`.'],
 ['python_dispatch',2778, 2870, 'Command library (`handleBotCommand`), then the Python game engine call and sending its reply/outbox.'],
];
let fn = null;
for (const n of ast.body) { const d = n.type === 'ExportNamedDeclaration' ? n.declaration : n; if (d && d.type === 'FunctionDeclaration' && d.id.name === 'handleMessage') fn = d; }
const stmts = fn.body.body;
// ---------- helpers ----------
function collect(p, out) {
    if (!p) return;
    if (p.type === 'Identifier') out.add(p.name);
    else if (p.type === 'ObjectPattern') p.properties.forEach(x => collect(x.value || x.argument, out));
    else if (p.type === 'ArrayPattern') p.elements.forEach(x => collect(x, out));
    else if (p.type === 'AssignmentPattern') collect(p.left, out);
    else if (p.type === 'RestElement') collect(p.argument, out);
}
function topDeclared(st, out) {
    if (st.type === 'VariableDeclaration') st.declarations.forEach(d => collect(d.id, out));
    else if (st.type === 'FunctionDeclaration') out.add(st.id.name);
}
function visit(node, fnCb, parent, key) {
    if (!node || typeof node.type !== 'string') return;
    fnCb(node, parent, key);
    for (const k of Object.keys(node)) { const v = node[k]; if (Array.isArray(v)) v.forEach(c => visit(c, fnCb, node, k)); else if (v && typeof v.type === 'string') visit(v, fnCb, node, k); }
}
function referenced(nodes) {          // every identifier used as a value (over-approximation: also matches shadowing declarations)
    const out = new Set();
    for (const n of nodes) visit(n, (x, p, k) => {
        if (x.type !== 'Identifier') return;
        if (p && p.type === 'MemberExpression' && k === 'property' && !p.computed) return;
        if (p && p.type === 'Property' && k === 'key' && !p.computed && !p.shorthand) return;
        if (p && (p.type === 'MethodDefinition' || p.type === 'PropertyDefinition') && k === 'key' && !p.computed) return;
        if (p && (p.type === 'LabeledStatement' || p.type === 'BreakStatement' || p.type === 'ContinueStatement') && k === 'label') return;
        out.add(x.name);
    });
    return out;
}
function assigned(nodes) {
    const out = new Set();
    for (const n of nodes) visit(n, (x) => {
        if (x.type === 'AssignmentExpression') collect(x.left.type === 'MemberExpression' ? null : x.left, out);
        if (x.type === 'UpdateExpression' && x.argument.type === 'Identifier') out.add(x.argument.name);
        if ((x.type === 'ForInStatement' || x.type === 'ForOfStatement') && x.left.type !== 'VariableDeclaration') collect(x.left, out);
    });
    return out;
}
const norm = (n) => JSON.stringify(n, (k, v) => (k === 'start' || k === 'end' || k === 'loc' || k === 'range') ? undefined : v);
// ---------- module-level imports ----------
const imports = [];     // {local, imported, source, kind}
for (const n of ast.body) if (n.type === 'ImportDeclaration')
    for (const s of n.specifiers) imports.push({ local: s.local.name, imported: s.type === 'ImportSpecifier' ? s.imported.name : s.type === 'ImportDefaultSpecifier' ? 'default' : '*', source: n.source.value });
const importLocals = new Set(imports.map(i => i.local));
// ---------- groups ----------
const SHARED = new Set(['sock', 'msg']);
for (const st of stmts) topDeclared(st, SHARED);
const startIdx = (line) => stmts.findIndex(s => s.loc.start.line === line);
const endIdx = (line) => stmts.findIndex(s => s.loc.end.line === line);
const groups = GROUPS.map(([name, a, b, doc]) => {
    const i = startIdx(a), j = endIdx(b);
    if (i < 0 || j < 0 || j < i) throw new Error(`group ${name}: ${a}-${b} does not align to statement boundaries`);
    return { name, doc, i, j, stmts: stmts.slice(i, j + 1) };
});
// groups must tile the whole body, in order
let expect = 0;
for (const g of groups) { if (g.i !== expect) throw new Error(`gap/overlap before group ${g.name}: statement ${g.i} vs expected ${expect}`); expect = g.j + 1; }
if (expect !== stmts.length) throw new Error(`statements after the last group: ${stmts.length - expect}`);
const declaredBefore = new Set(['sock', 'msg']);
groups.forEach((g, gi) => {
    const prevEnd = gi === 0 ? fn.body.loc.start.line : stmts[g.i - 1].loc.end.line;
    g.text = lines.slice(prevEnd, g.stmts[g.stmts.length - 1].loc.end.line).join('\n');   // lines after prevEnd .. last stmt end (keeps leading comments)
    if (gi === 0) g.text = lines.slice(fn.body.loc.start.line, g.stmts[g.stmts.length - 1].loc.end.line).join('\n');
    g.top = new Set(); g.stmts.forEach(s => topDeclared(s, g.top));
    g.refs = referenced(g.stmts); g.assigned = assigned(g.stmts);
    g.unpack = [...SHARED].filter(n => g.refs.has(n) && declaredBefore.has(n) && !g.top.has(n));
    g.top.forEach(n => declaredBefore.add(n));
});
groups.forEach((g, gi) => {
    const later = new Set(); groups.slice(gi + 1).forEach(h => h.refs.forEach(n => later.add(n)));
    g.writeback = [...new Set([...g.top, ...g.unpack.filter(n => g.assigned.has(n))])].filter(n => later.has(n) && SHARED.has(n));
});
// ---------- closures that could capture a variable another block later reassigns ----------
const closureWarn = [];
groups.forEach((g, gi) => g.stmts.forEach(s => { if (s.type === 'VariableDeclaration') s.declarations.forEach(d => {
    let hasFn = false; visit(d.init, x => { if (/Function/.test(x.type)) hasFn = true; });
    if (hasFn && d.id.type === 'Identifier') {
        const used = referenced([d.init]);
        const risky = [...used].filter(n => SHARED.has(n) && groups.slice(gi + 1).some(h => h.assigned.has(n)));
        closureWarn.push(`${g.name}: closure ${d.id.name} captures ${[...used].filter(n => SHARED.has(n)).join(',') || '-'}${risky.length ? '  <-- reassigned later: ' + risky.join(',') : ''}`);
    }
}); }));
// ---------- emit ----------
const GLOBALS = new Set('undefined NaN Infinity globalThis process console Buffer Math JSON Promise Date Number String Array Object Set Map WeakMap WeakSet URL URLSearchParams fetch setTimeout clearTimeout setInterval clearInterval setImmediate parseInt parseFloat isNaN isFinite Error TypeError RangeError RegExp Symbol encodeURIComponent decodeURIComponent encodeURI decodeURI Boolean AbortController Intl structuredClone performance Uint8Array ArrayBuffer BigInt escape unescape TextEncoder TextDecoder Response Headers FormData Blob AbortSignal queueMicrotask arguments require module exports __dirname __filename Atomics Reflect Proxy Function eval global'.split(' '));
fs.mkdirSync('bot/handler', { recursive: true });
fs.writeFileSync('bot/handler/_common.js', `// bot/handler/_common.js - shared by the handleMessage steps.\n// A step returns CONTINUE to fall through to the next step; anything else (including undefined) ends handling of the message.\nexport const CONTINUE = Symbol('continue');\n`);
const problems = [];
for (const g of groups) {
    const need = new Set([...g.refs]);
    const byFile = new Map();
    for (const im of imports) if (need.has(im.local) && !g.top.has(im.local)) {
        const src = im.source.startsWith('./') ? '.' + im.source : im.source;   // handler.js sits one level above bot/handler/
        if (!byFile.has(src)) byFile.set(src, { def: null, ns: null, named: [] });
        const e = byFile.get(src);
        if (im.imported === 'default') e.def = im.local; else if (im.imported === '*') e.ns = im.local; else e.named.push(im.imported === im.local ? im.local : `${im.imported} as ${im.local}`);
    }
    const importLines = [...byFile.entries()].map(([s, e]) => `import ${[e.def, e.ns ? `* as ${e.ns}` : null, e.named.length ? `{ ${e.named.join(', ')} }` : null].filter(Boolean).join(', ')} from '${s}';`);
    const unpackLine = g.unpack.length ? `    let { ${g.unpack.join(', ')} } = ctx;\n` : '';
    const wb = g.writeback.map(n => `    ctx.${n} = ${n};`).join('\n');
    const code = `// bot/handler/${g.name}.js - ${g.doc}\n// Moved verbatim out of handleMessage (handler.js, original lines ${g.stmts[0].loc.start.line}-${g.stmts[g.stmts.length - 1].loc.end.line}).\n// run(ctx) returns CONTINUE to fall through to the next step, or ends handling of the message (return / return value).\n`
        + importLines.join('\n') + (importLines.length ? '\n' : '') + `import { CONTINUE } from './_common.js';\n\nexport async function run(ctx) {\n${unpackLine}${g.text}\n${wb ? wb + '\n' : ''}    return CONTINUE;\n}\n`;
    fs.writeFileSync(`bot/handler/${g.name}.js`, code);
    // --- verification 1: the moved statements are AST-identical to the originals
    const gen = parse(code);
    const run = gen.body.find(n => n.type === 'ExportNamedDeclaration' && n.declaration && n.declaration.id && n.declaration.id.name === 'run').declaration;
    const body = run.body.body;
    const core = body.slice(g.unpack.length ? 1 : 0, body.length - 1 - g.writeback.length);
    const a = g.stmts.map(norm), b = core.map(norm);
    if (a.length !== b.length || a.some((x, i) => x !== b[i])) problems.push(`AST mismatch in ${g.name}`);
    // --- verification 2: every identifier resolves (declared somewhere in the file, imported, a global, or the unpacked ctx names)
    const declared = new Set([...GLOBALS]);
    visit(gen, (x) => {
        if (x.type === 'ImportSpecifier' || x.type === 'ImportDefaultSpecifier' || x.type === 'ImportNamespaceSpecifier') declared.add(x.local.name);
        if (x.type === 'VariableDeclarator') collect(x.id, declared);
        if (/Function/.test(x.type)) { x.params.forEach(p => collect(p, declared)); if (x.id) declared.add(x.id.name); }
        if (x.type === 'CatchClause' && x.param) collect(x.param, declared);
        if (x.type === 'ClassDeclaration' && x.id) declared.add(x.id.name);
    });
    const unresolved = [...referenced([run.body])].filter(n => !declared.has(n));
    if (unresolved.length) problems.push(`${g.name}: unresolved identifiers: ${unresolved.join(', ')}`);
    console.log(`${g.name.padEnd(16)} ${String(g.stmts[0].loc.start.line).padStart(4)}-${String(g.stmts[g.stmts.length - 1].loc.end.line).padEnd(4)} unpack=${g.unpack.length} writeback=[${g.writeback.join(',')}] imports=${byFile.size}`);
}
// ---------- new handler.js ----------
const stepImports = groups.map(g => `import * as ${g.name} from './handler/${g.name}.js';`).join('\n');
const entry = `// handler.js - entry point for every WhatsApp message.\n// handleMessage used to be one ${fn.loc.end.line - fn.loc.start.line + 1}-line function; it is now a list of steps, one file each in ./handler/,\n// run in the original order. A step returns CONTINUE to hand over to the next one; anything else ends handling of the message.\n// Locals one step needs from an earlier one (chatJid, senderJid, lower, db, ...) travel in \`ctx\`.\nimport { CONTINUE } from './handler/_common.js';\n${stepImports}\n\nconst STEPS = [\n${groups.map(g => `    ${g.name}.run,`).join('\n')}\n];\n\nexport async function handleMessage(sock, msg) {\n    const ctx = { sock, msg };\n    for (const step of STEPS) {\n        const r = await step(ctx);\n        if (r !== CONTINUE) return r;\n    }\n}\n`;
fs.writeFileSync(SRC, entry);
console.log('\nclosure check (closures created in one step that read variables another step reassigns later):');
closureWarn.forEach(w => console.log('  ' + w));
if (problems.length) { console.log('\nPROBLEMS:'); problems.forEach(p => console.log('  ' + p)); process.exitCode = 1; } else console.log('\nall steps AST-identical and all identifiers resolve');
