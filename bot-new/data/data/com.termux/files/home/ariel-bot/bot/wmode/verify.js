// bot/wmode/verify.js — stage 7: pure helpers that decide whether work counts as verified.
// No I/O, no clock. "Attempting a task" and "completing it" are different things: everything here is
// computed from saved tool turns, never from what a model says about its own work.
const clip = (v, n) => { const s = String(v ?? ''); return s.length > n ? `${s.slice(0, n - 1)}…` : s; };

// Files whose changes deserve a run or a review. Notes, text and markdown never trigger either.
export const CODE_FILE_RE = /\.(js|mjs|cjs|ts|tsx|jsx|py|sh|json|sql|html|css|yml|yaml)$/i;
const WRITE_TOOLS = ['create_file', 'edit_file'];

const used = (turns) => (turns || []).filter((t) => t.tool && !t.denied);
const isCheckRun = (t) => t.ok && (t.tool === 'run_tests' || (t.tool === 'run_command' && t.meta?.exitCode !== undefined));
const passed = (t) => (t.tool === 'run_tests' ? t.meta?.passed === true : t.meta?.exitCode === 0 && !t.meta?.timedOut);

// Code files written (successfully) and what happened after the last write.
export function codeState(turns) {
    const u = used(turns);
    const writes = u.map((t, i) => ({ t, i })).filter(({ t }) => WRITE_TOOLS.includes(t.tool) && t.ok && CODE_FILE_RE.test(String(t.meta?.path || '')));
    const lastWrite = writes.length ? writes.at(-1).i : -1;
    const after = u.slice(lastWrite + 1).filter(isCheckRun);
    return {
        files: [...new Set(writes.map(({ t }) => t.meta.path))],
        changed: writes.length > 0,
        checked: after.length > 0,                       // some check ran after the last code change
        passing: after.length > 0 && passed(after.at(-1)),
        lastRun: after.at(-1) || null,
    };
}

// Should Ariel push back once before accepting a final answer? Only when a check could actually be run.
export function needsCheckBeforeFinal(turns, { canRun = false, nudges = 0, maxNudges = 1 } = {}) {
    if (!canRun || nudges >= maxNudges) return false;
    const s = codeState(turns);
    return s.changed && !s.checked;
}
export const NUDGE_NOTE = 'You changed code but nothing has been run since. Run the tests (run_tests) or a syntax check (run_command, e.g. node --check <file>), '
    + 'then give your final answer. If you truly cannot run a check, say so plainly in the final answer.';

// Success words in a final answer that no passing run backs up.
const CLAIM_RE = /\b(all (the )?tests? (are )?pass(ed|ing)?|tests? (now )?pass(ed|es|ing)?|works? (correctly|as expected|perfectly)|(is|are) working|successfully (ran|run|tested|executed)|verified|no errors?)\b/i;
export function unbackedClaims(turns, finalText) {
    const s = codeState(turns);
    if (!s.changed || s.passing || !CLAIM_RE.test(String(finalText || ''))) return [];
    return [s.checked ? 'the answer says it works, but the last check after your changes FAILED' : 'the answer says it works, but no test or command was run after the code changed'];
}

// ── independent review ─────────────────────────────────────
// The reviewer sees what was written and what the checks said — not the author's reasoning.
export function reviewTarget(turns) {
    const u = used(turns);
    const edits = u.filter((t) => WRITE_TOOLS.includes(t.tool) && t.ok && CODE_FILE_RE.test(String(t.meta?.path || '')));
    return edits.length > 0;
}

export function buildReviewMessages(task, turns, finalText, { reviewChars = 6000 } = {}) {
    const u = used(turns);
    const per = Math.max(400, Math.floor(reviewChars / Math.max(1, u.filter((t) => WRITE_TOOLS.includes(t.tool)).length || 1)));
    const writes = u.filter((t) => WRITE_TOOLS.includes(t.tool) && t.ok).map((t) => (t.tool === 'create_file'
        ? `CREATED ${t.meta?.path}:\n${clip(t.args?.content, per)}`
        : `EDITED ${t.meta?.path}\n--- old ---\n${clip(t.args?.old, per / 2)}\n--- new ---\n${clip(t.args?.new ?? t.args?.replacement, per / 2)}`)).join('\n\n');
    const runs = u.filter(isCheckRun).map((t) => `${t.tool} ${clip(JSON.stringify(t.args || {}), 120)} → ${passed(t) ? 'PASSED' : 'FAILED'}: ${clip(t.result, 400)}`).join('\n') || '(no check was run)';
    return [
        { role: 'system', content: 'You are an independent code reviewer. You did not write this code. Judge ONLY what is shown. '
            + 'Look for bugs, missed requirements, unsafe behaviour, and claims in the final answer that the evidence does not support. '
            + 'Reply with exactly one JSON object: {"verdict":"ok"|"concerns","issues":["short, specific issue", ...]}. '
            + 'Use "ok" with an empty list if you find nothing real. At most 5 issues. No prose, no code fences.' },
        { role: 'user', content: `Request:\n${clip(task.description, 800)}\n\nCode written:\n${writes}\n\nChecks run:\n${runs}\n\nAuthor's final answer:\n${clip(finalText, 800)}` },
    ];
}

export function parseReview(text) {
    const s = String(text || '').trim().replace(/^```(?:json)?\s*/i, '').replace(/```\s*$/i, '').trim();
    const a = s.indexOf('{'); const b = s.lastIndexOf('}');
    if (a === -1 || b <= a) return null;
    let j; try { j = JSON.parse(s.slice(a, b + 1)); } catch { return null; }
    const verdict = String(j?.verdict || '').toLowerCase();
    if (verdict !== 'ok' && verdict !== 'concerns') return null;
    const issues = (Array.isArray(j.issues) ? j.issues : []).map((x) => clip(String(x).replace(/\s+/g, ' ').trim(), 220)).filter(Boolean).slice(0, 5);
    if (verdict === 'concerns' && !issues.length) return null;           // "concerns" with nothing named is not usable
    return { verdict: issues.length ? 'concerns' : 'ok', issues };
}

// Lines added to the "checked by Ariel" footer. `review` = { verdict, issues, by, sameFamily } | { skipped } | null.
export function verifyLines({ claims = [], review = null, nudged = false } = {}) {
    const out = [];
    for (const c of claims) out.push(`⚠️ unbacked claim: ${c}`);
    if (review?.skipped) out.push(`🔎 independent review skipped (${review.skipped})`);
    else if (review) {
        const who = review.by ? ` by ${review.by}${review.sameFamily ? ' — same model as the author, so not fully independent' : ''}` : '';
        if (review.verdict === 'ok') out.push(`🔎 independent review${who}: no problems found (a review is not a test)`);
        else out.push(`🔎 independent review${who} raised ${review.issues.length} concern(s):\n${review.issues.map((i) => `  • ${i}`).join('\n')}`);
    }
    if (nudged) out.push('↩️ Ariel asked for a check before accepting the answer');
    return out;
}
