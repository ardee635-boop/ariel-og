// node --expose-internals tools/js_plan.cjs bot/handler.js
const acorn = require('internal/deps/acorn/acorn/dist/acorn');
const walk = require('internal/deps/acorn/acorn-walk/dist/walk');
const fs = require('fs');
const file = process.argv[2];
const src = fs.readFileSync(file, 'utf8');
const ast = acorn.parse(src, { sourceType: 'module', ecmaVersion: 'latest', locations: true });
const lines = src.split('\n');
let fn = null;
for (const n of ast.body) {
    const d = n.type === 'ExportNamedDeclaration' ? n.declaration : n;
    if (d && d.type === 'FunctionDeclaration' && d.id.name === 'handleMessage') fn = d;
}
function declared(node) {
    const out = [];
    if (node.type === 'VariableDeclaration') for (const d of node.declarations) collect(d.id, out);
    if (node.type === 'FunctionDeclaration') out.push(node.id.name);
    return out;
}
function collect(p, out) {
    if (p.type === 'Identifier') out.push(p.name);
    else if (p.type === 'ObjectPattern') p.properties.forEach(x => collect(x.value || x.argument, out));
    else if (p.type === 'ArrayPattern') p.elements.forEach(x => x && collect(x, out));
    else if (p.type === 'AssignmentPattern') collect(p.left, out);
    else if (p.type === 'RestElement') collect(p.argument, out);
}
function countReturns(node) {
    let n = 0;
    (function rec(x) {
        if (!x || typeof x.type !== 'string') return;
        if (x.type === 'ReturnStatement') n++;
        if (x !== node && /Function/.test(x.type)) return;   // returns of nested functions are theirs
        for (const k of Object.keys(x)) { const v = x[k]; if (Array.isArray(v)) v.forEach(rec); else if (v && typeof v.type === 'string') rec(v); }
    })(node);
    return n;
}
console.log('handleMessage lines', fn.loc.start.line, '-', fn.loc.end.line, '| params:', fn.params.map(p => p.name).join(','), '| async:', fn.async);
const rows = [];
for (const st of fn.body.body) {
    const first = lines[st.loc.start.line - 1].trim().slice(0, 74);
    rows.push({ a: st.loc.start.line, b: st.loc.end.line, type: st.type, decl: declared(st), ret: countReturns(st), first });
}
if (process.argv.includes('--json')) { fs.writeFileSync('/tmp/hm_stmts.json', JSON.stringify(rows)); }
for (const r of rows) console.log(`${String(r.a).padStart(5)}-${String(r.b).padEnd(5)} ${r.type.slice(0, 14).padEnd(14)} ret=${String(r.ret).padStart(2)} ${r.decl.length ? 'decl[' + r.decl.join(',') + '] ' : ''}${r.first}`);
