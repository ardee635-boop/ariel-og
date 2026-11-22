// bot/wmode/planner.js — pure helpers for planned (multi-step) tasks. No I/O, no clock.
//
// A planned task is: plan call -> N step calls -> one final-report call. Everything a model needs to
// continue is rebuilt from the saved task on every call (plan, finished steps, the current step), so a
// different provider can pick the task up mid-way and nothing is repeated.
import { TASK_ROLE } from './providers.js';

export const SYSTEM_BASE = [
    'You are Ariel in Work Mode: a precise, practical assistant for coding, debugging, research, planning and project work.',
    'Be direct and structured. No small talk, no persona.',
    'You cannot run code, open files, browse the web or execute commands in this mode yet. Never say you ran, tested, installed or verified anything.',
    'When you give code, say plainly that it has not been run. For research from memory, separate what you are sure of from what you are guessing, and say you have no live sources.',
].join('\n');

const BUILD_WORDS = /\b(build|create|implement|migrate|refactor|set ?up|design|end[- ]to[- ]end|step by step|from scratch|architecture|roadmap|audit|compare .+ (and|vs)|research .+ and)\b/i;

// Cheap decision, no model call. planMode: 'auto' | 'always' | 'never' (a setting).
export function needsPlan(text, kind, settings = {}) {
    const mode = settings.planMode || 'auto';
    if (mode === 'never') return false;
    if (mode === 'always') return true;
    const t = String(text || '').trim();
    if (t.length >= (settings.planMinChars ?? 280)) return true;
    const listLines = t.split('\n').filter((l) => /^\s*(\d+[.)]|[-*•])\s+\S/.test(l)).length;
    if (listLines >= 2) return true;
    if (t.length >= 60 && BUILD_WORDS.test(t)) return true;
    if ((kind === 'plan' || kind === 'research') && t.length >= 120) return true;
    return false;
}

const KINDS = new Set(Object.keys(TASK_ROLE));
const clipStr = (s, n) => { const v = String(s ?? '').replace(/\s+/g, ' ').trim(); return v.length > n ? `${v.slice(0, n - 1)}…` : v; };

function extractJson(text) {
    const s = String(text || '').trim().replace(/^```(?:json)?\s*/i, '').replace(/```\s*$/i, '').trim();
    // Try whichever bracket opens first, so a bare array of objects is not mistaken for its first object.
    const pairs = [['{', '}'], ['[', ']']].map(([o, c]) => ({ o, c, at: s.indexOf(o) })).filter((x) => x.at !== -1).sort((a, b) => a.at - b.at);
    for (const { c, at } of pairs) {
        const end = s.lastIndexOf(c);
        if (end > at) { try { return JSON.parse(s.slice(at, end + 1)); } catch { /* try the other shape */ } }
    }
    return null;
}

// Accepts {"steps":[...]} or a bare array; each item a string or {title, detail, kind}.
// Returns [{n, title, detail, kind, status:'pending'}] or null when nothing usable came back.
export function parsePlan(text, maxSteps = 6) {
    const j = extractJson(text);
    const raw = Array.isArray(j) ? j : Array.isArray(j?.steps) ? j.steps : null;
    if (!raw) return null;
    const steps = [];
    for (const it of raw) {
        const title = clipStr(typeof it === 'string' ? it : (it?.title || it?.step || it?.name), 120);
        if (!title) continue;
        const kind = KINDS.has(it?.kind) ? it.kind : 'simple';
        steps.push({ n: steps.length + 1, title, detail: clipStr(typeof it === 'object' ? (it.detail || it.description || '') : '', 400), kind, status: 'pending' });
        if (steps.length >= maxSteps) break;
    }
    return steps.length ? steps : null;
}

export function buildPlanMessages(task, maxSteps, strict = false) {
    const sys = `${SYSTEM_BASE}\nYou are the PLANNER. Break the user's request into the fewest steps that do the job well (at most ${maxSteps}). `
        + 'Each step must be something you can complete by writing text (analysis, code, a draft, a comparison) — not something that needs running tools. '
        + 'Reply with JSON only, no prose, no code fences: {"steps":[{"title":"short imperative","detail":"what exactly to produce","kind":"code|debug|research|plan|summarise|simple"}]}'
        + (strict ? '\nYour previous reply was not valid JSON. Output ONLY the JSON object.' : '');
    return [{ role: 'system', content: sys }, { role: 'user', content: `[PLAN REQUEST]\n${task.description}` }];
}

// Parse a trailing "SUMMARY: ..." line off a step answer.
export function splitSummary(text) {
    const s = String(text || '').trim();
    const m = /\n?\s*SUMMARY:\s*([^\n]+)\s*$/i.exec(s);
    if (!m) return { body: s, summary: clipStr(s, 220) };
    return { body: s.slice(0, m.index).trim() || s, summary: clipStr(m[1], 220) };
}

// What earlier steps contribute to the next prompt, within `limit` characters:
// newest steps keep their full output, older ones shrink to a summary, the oldest to a title.
export function contextBlock(plan, upTo, limit = 6000, outputClip = 1200) {
    const done = plan.slice(0, upTo).filter((s) => s.status === 'done');
    const lines = []; let used = 0;
    for (let i = done.length - 1; i >= 0; i--) {
        const s = done[i];
        const out = String(s.output || s.summary || '');
        const full = `Step ${s.n} — ${s.title}\n${out.length > outputClip ? `${out.slice(0, outputClip)}…` : out}`;
        const mid = `Step ${s.n} — ${s.title}: ${s.summary || ''}`;
        const small = `Step ${s.n} — ${s.title}`;
        const pick = [full, mid, small].find((v) => used + v.length <= limit) || null;
        if (!pick) break;
        used += pick.length; lines.unshift(pick);
    }
    return lines.join('\n\n');
}

const planOutline = (plan, current) => plan.map((s) => `${s.status === 'done' ? '✔' : s.n - 1 === current ? '▶' : '·'} ${s.n}. ${s.title}`).join('\n');

export function buildStepMessages(task, index, settings = {}) {
    const plan = task.plan; const step = plan[index];
    const prior = contextBlock(plan, index, settings.contextChars ?? 6000);
    const user = [
        `[STEP ${step.n}/${plan.length}]`,
        `Overall request:\n${task.description}`,
        `Plan:\n${planOutline(plan, index)}`,
        prior ? `Work so far:\n${prior}` : null,
        `Now do step ${step.n}: ${step.title}${step.detail ? `\nDetails: ${step.detail}` : ''}`,
        'Write only the result of this step. Finish with one line: SUMMARY: <one sentence of what this step produced>.',
    ].filter(Boolean).join('\n\n');
    return [{ role: 'system', content: SYSTEM_BASE }, { role: 'user', content: user }];
}

export function buildFinalMessages(task, settings = {}) {
    const plan = task.plan;
    const work = contextBlock(plan, plan.length, (settings.contextChars ?? 6000) * 1.5, 2500);
    const user = [
        '[FINAL REPORT]',
        `Original request:\n${task.description}`,
        `Work completed:\n${work}`,
        'Write the final answer for the user: complete and directly usable, merging the steps into one coherent reply (no step-by-step recap unless it helps). '
        + 'State clearly anything that was not run, tested or verified, and any assumptions you made.',
    ].join('\n\n');
    return [{ role: 'system', content: SYSTEM_BASE }, { role: 'user', content: user }];
}

// Mirror the plan into the two columns the design calls for.
export function stepColumns(plan) {
    return {
        completedSteps: plan.filter((s) => s.status === 'done').map((s) => ({ title: s.title, summary: s.summary || '' })),
        pendingSteps: plan.filter((s) => s.status !== 'done').map((s) => ({ title: s.title })),
        currentStep: plan.findIndex((s) => s.status !== 'done') === -1 ? plan.length : plan.findIndex((s) => s.status !== 'done'),
    };
}
