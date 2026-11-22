// bot/wmode/tools/index.js — the tool registry. Tools are plain objects; add one with registry.register().
//   { name, description, risk: 'read' | 'write' | 'danger', needsApproval?(args), args: { argName: 'string' | 'string?' | 'number?' | 'boolean?' }, run(args, ctx) }
// risk 'danger' (or needsApproval(args) === true) never runs without ctx.approved === true; call() returns { needsApproval } instead.
import { ToolError } from './sandbox.js';

const clip = (v, n) => { const s = String(v ?? ''); return s.length > n ? `${s.slice(0, n)}\n…[clipped ${s.length - n} chars]` : s; };

function checkArgs(spec = {}, args = {}) {
    const out = {};
    for (const [k, t] of Object.entries(spec)) {
        const optional = t.endsWith('?'); const type = t.replace('?', '');
        let v = args[k];
        if (v === undefined || v === null || v === '') { if (optional) continue; throw new ToolError(`missing argument "${k}"`, 'bad_args'); }
        if (type === 'number') v = Number(v);
        if (type === 'boolean') v = v === true || v === 'true';
        if (type === 'string') v = String(v);
        if (type === 'number' && !Number.isFinite(v)) throw new ToolError(`argument "${k}" must be a number`, 'bad_args');
        out[k] = v;
    }
    return out;
}

export function createToolRegistry({ settings, log = () => {} } = {}) {
    const tools = new Map();
    const maxOut = () => settings?.toolOutputChars ?? 6000;

    function register(tool) {
        if (!tool?.name || typeof tool.run !== 'function') throw new Error('tool needs a name and run()');
        if (!['read', 'write', 'danger'].includes(tool.risk)) throw new Error(`tool ${tool.name}: bad risk`);
        tools.set(tool.name, tool);
        return api;
    }

    // Compact text for the model prompt (the model has no native tool protocol here).
    function describe() {
        return [...tools.values()].map((t) => `- ${t.name}(${Object.entries(t.args || {}).map(([k, v]) => `${k}${v.endsWith('?') ? '?' : ''}`).join(', ')}) [${t.risk}] ${t.description}`).join('\n');
    }

    // Never throws: always { ok, output } | { ok:false, error, code } | { ok:false, needsApproval, ... }.
    async function call(name, rawArgs, ctx = {}) {
        const t = tools.get(name);
        if (!t) return { ok: false, error: `unknown tool "${name}"`, code: 'unknown_tool' };
        try {
            const args = checkArgs(t.args, rawArgs);
            const needs = typeof t.needsApproval === 'function' ? t.needsApproval(args) : t.risk === 'danger';
            if (needs && ctx.approved !== true) return { ok: false, needsApproval: true, tool: name, args, code: 'needs_approval', error: `"${name}" needs your approval` };
            const res = await t.run(args, ctx);
            log(`tool ${name} ok`);
            return { ok: true, tool: name, risk: t.risk, output: clip(typeof res === 'string' ? res : (res?.output ?? JSON.stringify(res)), maxOut()), meta: res?.meta || {} };
        } catch (e) {
            log(`tool ${name} failed: ${e.message}`);
            return { ok: false, tool: name, error: clip(e.message, 600), code: e.code || 'tool_error' };
        }
    }

    const api = { register, describe, call, has: (n) => tools.has(n), get: (n) => tools.get(n), names: () => [...tools.keys()] };
    return api;
}
