// bot/wmode/manager.js — the Work Manager: owns tasks, sessions and the on/off state.
// "Ariel owns the task. AI providers are replaceable workers."
//
// Stage 5c adds the tool loop (runAgent): the model calls workspace tools, risky ones wait for .wapprove.
// Stage 1–3 scope: persistent tasks, activation state, provider failover, budgets, pause/resume/cancel,
// restart recovery. Every request currently runs as ONE model call (the "simple question" path of the
// design). The plan/execute loop (stage 4) plugs into execute() later without touching anything else.
import { AIError } from '../ariel/providers/index.js';
import { WorkQuotaError } from './providers.js';
import { TERMINAL } from './store.js';
import { needsTools, parseAction, describeCall, buildAgentMessages, verifiedFooter } from './agent.js';
import { needsCheckBeforeFinal, NUDGE_NOTE, unbackedClaims, reviewTarget, buildReviewMessages, parseReview, verifyLines } from './verify.js';
import { SYSTEM_BASE, needsPlan, parsePlan, buildPlanMessages, buildStepMessages, buildFinalMessages, splitSummary, stepColumns } from './planner.js';

export const STATUSES = ['pending', 'planning', 'running', 'waiting_approval', 'paused', 'completed', 'failed', 'cancelled'];
const PAUSABLE = ['pending', 'planning', 'running', 'waiting_approval'];

// Heuristic only — it picks WHICH model family answers, never whether the request is allowed.
export function classifyKind(text) {
    const t = String(text || '').toLowerCase();
    if (/\b(traceback|stack ?trace|exception|error:|bug|crash(es|ed)?|not working|doesn'?t work|fix (this|the|my))\b/.test(t)) return 'debug';
    if (/\b(code|function|script|class|regex|sql|api|json|python|javascript|typescript|node|bash|refactor|implement|compile|unit test)\b|```/.test(t)) return 'code';
    if (/\b(search|research|look ?up|find out|compare|latest|sources?|news about)\b/.test(t)) return 'research';
    if (/\b(plan|roadmap|design|architecture|strategy|steps to|break (this|it) down)\b/.test(t)) return 'plan';
    if (/\b(summari[sz]e|tl;?dr|shorten|recap)\b/.test(t)) return 'summarise';
    return 'simple';
}

export function chunkText(text, max = 3500) {
    const s = String(text || '').trim();
    if (!s) return [];
    if (s.length <= max) return [s];
    const out = []; let rest = s;
    while (rest.length > max) {
        let cut = rest.lastIndexOf('\n\n', max);
        if (cut < max * 0.4) cut = rest.lastIndexOf('\n', max);
        if (cut < max * 0.4) cut = rest.lastIndexOf(' ', max);
        if (cut < max * 0.4) cut = max;
        out.push(rest.slice(0, cut).trim()); rest = rest.slice(cut).trim();
    }
    if (rest) out.push(rest);
    return out;
}

const clip = (v, n) => { const s = typeof v === 'string' ? v : JSON.stringify(v); return s && s.length > n ? `${s.slice(0, n)}…` : v; };
const hhmm = (ms) => (ms ? new Date(ms).toISOString().slice(11, 16) + ' UTC' : 'later');

export function createWorkManager({ store, providers, settings, owner = `w-${process.pid}-${Math.random().toString(36).slice(2, 8)}`,
                                    now = Date.now, isChatEnabled = () => true, tools = null, project = null, log = () => {} }) {
    const running = new Set();      // task ids this process is executing right now
    const modeCache = new Map();    // chatJid -> boolean (loaded lazily from the DB)

    const event = (taskId, kind, data = {}) =>
        store.addEvent(taskId, kind, clip(data, settings.eventClipChars) === data ? data : { note: clip(data, settings.eventClipChars) })
            .catch((e) => log(`event ${kind} failed: ${e.message}`));

    // ── activation ──────────────────────────────────────────────
    async function isActive(chatJid) {
        if (!modeCache.has(chatJid)) modeCache.set(chatJid, await store.getMode(chatJid));
        return modeCache.get(chatJid) === true;
    }

    async function activate(chatJid, userId, { isDM = false } = {}) {
        if (!isChatEnabled(chatJid, isDM)) {
            return { ok: false, reason: 'chat_off',
                message: `Work Mode needs Ariel's normal chat switched on first. Turn it on (${isDM ? '.chatdm on' : '.chat on'}), then send .wchat on again.` };
        }
        await store.setMode(chatJid, true, userId);
        await store.ensureSession(chatJid, userId);
        modeCache.set(chatJid, true);
        const resumable = await store.listTasks(chatJid, { statuses: ['paused', 'pending', 'running', 'waiting_approval'], limit: 20 });
        return { ok: true, resumable };
    }

    async function deactivate(chatJid) {
        await store.setMode(chatJid, false);
        modeCache.set(chatJid, false);
        // Nothing is deleted. In-flight tasks are parked so .wchat on can pick them up again.
        const paused = await store.pauseActiveInChat(chatJid, 'work mode turned off');
        for (const id of paused) await event(id, 'paused', { reason: 'work mode turned off' });
        return { ok: true, paused };
    }

    // ── tasks ───────────────────────────────────────────────────
    async function submit({ chatJid, userId, text, msgId = null }) {
        const description = String(text || '').trim().slice(0, settings.maxRequestChars);
        const kind = classifyKind(description);
        const { task, created } = await store.createTask({ userId, chatJid, sourceMsgId: msgId, description, kind, tokenBudget: settings.taskTokenBudget });
        if (created) await event(task.id, 'created', { kind, budget: settings.taskTokenBudget });
        return { task, created };
    }

    function buildMessages(task, recent) {
        const system = `${SYSTEM_BASE}\nIf the request is too vague to do well, ask ONE specific question instead of guessing.`;
        const msgs = [{ role: 'system', content: system }];
        for (const t of recent) if (t?.text) msgs.push({ role: t.role === 'assistant' ? 'assistant' : 'user', content: String(t.text) });
        // Task state travels in the prompt, not in any provider's memory — that is what lets a
        // different provider continue the same task after a failover.
        const state = [];
        if (task.completedSteps?.length) state.push(`Completed steps:\n${task.completedSteps.map((s, i) => `${i + 1}. ${s.title || s}${s.summary ? ` — ${s.summary}` : ''}`).join('\n')}`);
        if (task.pendingSteps?.length) state.push(`Outstanding steps:\n${task.pendingSteps.map((s, i) => `${i + 1}. ${s.title || s}`).join('\n')}`);
        msgs.push({ role: 'user', content: state.length ? `${task.description}\n\n[Task state]\n${state.join('\n\n')}` : task.description });
        return msgs;
    }

    async function pauseTask(task, reason, notice) {
        const t = await store.setStatus(task.id, 'paused', { pauseReason: reason }, { from: ['pending', 'planning', 'running'] });
        if (t) await event(task.id, 'paused', { reason });
        return { status: 'paused', task: t || task, notice };
    }

    // Raised inside a task to end it early with a ready-made outcome (budget pause, stop at a boundary).
    class Stop extends Error { constructor(outcome) { super('stop'); this.outcome = outcome; } }

    async function failure(task, e) {
        if (e instanceof WorkQuotaError) {
            return pauseTask(task, 'quota', `⏸️ Task #${task.id} paused: every Work Mode model is out of free quota${e.resetAt ? ` until about ${hhmm(e.resetAt)}` : ''}. Progress is saved — send .wresume ${task.id} later.`);
        }
        if (e instanceof AIError) {
            return pauseTask(task, 'providers unavailable', `⏸️ Task #${task.id} paused: the AI providers kept failing (${String(e.message).slice(0, 160)}). Progress is saved — send .wresume ${task.id} to try again.`);
        }
        const failed = await store.setStatus(task.id, 'failed', { error: String(e.message).slice(0, 500) }, { from: ['pending', 'planning', 'running'] });
        await event(task.id, 'failed', { error: String(e.message) });
        return { status: 'failed', task: failed || task, notice: `❌ Task #${task.id} failed: ${String(e.message).slice(0, 200)}` };
    }

    // One budget-checked, failover-aware model call for a task. `state.task` always holds the latest
    // saved task; `label` only names the call in the history ("plan", "step 2", "final").
    async function modelCall(state, kind, messages, label) {
        const task = state.task;
        const budget = task.tokenBudget ?? settings.taskTokenBudget;
        const used = task.tokensIn + task.tokensOut;
        const floor = Math.min(256, Math.floor(settings.taskTokenBudget / 2));   // a call needs room to answer
        if (budget && budget - used < floor) {
            throw new Stop(await pauseTask(task, 'token budget reached',
                `⏸️ Task #${task.id} paused: it used ${used} of its ${budget} token budget. Progress is saved — send .wresume ${task.id} to continue with a fresh allowance.`));
        }
        const res = await providers.complete({ kind, messages, taskId: task.id, maxTokensCap: budget ? budget - used : undefined });
        const now_ = `${res.provider}/${res.model}`;
        if (state.last && state.last !== now_) await event(task.id, 'provider_switch', { from: state.last, to: now_, at: label });
        state.last = now_;
        state.task = await store.addUsage(task.id, res.tokensIn, res.tokensOut, res.provider, res.model);
        await event(task.id, 'model_call', { label, role: res.role, provider: res.provider, model: res.model, tokensIn: res.tokensIn, tokensOut: res.tokensOut, ms: res.latencyMs });
        return res;
    }

    async function finish(state, text, extra = {}) {
        const task = state.task;
        const done = await store.setStatus(task.id, 'completed', { result: text }, { from: ['running', 'planning'] });
        if (!done) {   // paused or cancelled while the model was thinking: keep that decision, drop the reply
            await event(task.id, 'discarded', { why: 'task changed state during the model call' });
            return { status: 'discarded', task };
        }
        await store.appendTurns(task.chatJid, task.userId,
            [{ role: 'user', text: task.description }, { role: 'assistant', text }], settings.recentTurns, settings.recentChars);
        return { status: 'completed', task: done, text, provider: state.last?.split('/')[0], model: state.last?.split('/').slice(1).join('/'), ...extra };
    }

    // ── simple path: one call ──────────────────────────────────
    async function runSingle(state) {
        const recent = await store.getRecent(state.task.chatJid);
        const res = await modelCall(state, state.task.kind || 'simple', buildMessages(state.task, recent), 'answer');
        return finish(state, res.text);
    }

    // ── planned path ───────────────────────────────────────────
    const tell = async (notify, text) => { try { await notify?.(text); } catch { /* progress messages must never break a task */ } };

    // Returns an outcome to stop with, or null (plan saved, or planning skipped -> single call).
    async function makePlan(state, notify) {
        const id = state.task.id;
        await store.setStatus(id, 'planning', {}, { from: ['running', 'planning'] });
        let steps = null;
        for (let attempt = 0; attempt < 2 && !steps; attempt++) {
            const res = await modelCall(state, 'plan', buildPlanMessages(state.task, settings.maxSteps, attempt > 0), 'plan');
            steps = parsePlan(res.text, settings.maxSteps);
            if (!steps) await event(id, 'plan_invalid', { attempt, reply: res.text });
        }
        const back = await store.setStatus(id, 'running', {}, { from: ['planning', 'running'] });
        if (!back) return { status: 'discarded', task: state.task };      // paused/cancelled while planning
        if (!steps || steps.length < 2) { await event(id, 'plan_skipped', { reason: steps ? 'one step' : 'unparseable' }); return null; }
        state.task = await store.updateTask(id, { plan: steps, ...stepColumns(steps) });
        await event(id, 'planned', { steps: steps.map((s) => s.title) });
        await tell(notify, `📋 Plan for #${id}:\n${steps.map((s) => `${s.n}. ${s.title}`).join('\n')}`);
        return null;
    }

    async function runPlan(state, notify) {
        const id = state.task.id;
        let plan = state.task.plan.map((s) => ({ ...s }));
        for (let i = 0; i < plan.length; i++) {
            if (plan[i].status === 'done') continue;
            const cur = await store.getTask(id);        // stop at a boundary if the user paused/cancelled
            if (!cur || !['running', 'planning'].includes(cur.status)) return { status: cur?.status === 'cancelled' ? 'cancelled' : 'discarded', task: cur || state.task };
            state.task = { ...cur, plan };
            const step = plan[i];
            const kind = step.kind && step.kind !== 'simple' ? step.kind : (state.task.kind !== 'simple' ? state.task.kind : 'plan');
            const res = await modelCall(state, kind, buildStepMessages(state.task, i, settings), `step ${step.n}`);
            const { body, summary } = splitSummary(res.text);
            plan[i] = { ...step, status: 'done', output: body.slice(0, settings.stepOutputChars), summary, by: `${res.provider}` };
            state.task = await store.updateTask(id, { plan, ...stepColumns(plan) });
            await event(id, 'step_done', { n: step.n, title: step.title, provider: res.provider });
            await tell(notify, `✅ ${step.n}/${plan.length} ${step.title}`);
        }
        const cur = await store.getTask(id);
        if (!cur || !['running', 'planning'].includes(cur.status)) return { status: cur?.status === 'cancelled' ? 'cancelled' : 'discarded', task: cur || state.task };
        state.task = { ...cur, plan };
        const finalKind = ['code', 'debug'].includes(state.task.kind) ? state.task.kind : 'plan';
        const res = await modelCall(state, finalKind, buildFinalMessages(state.task, settings), 'final');
        return finish(state, res.text, { steps: plan.length });
    }


    // ── tool-using path (stage 5c) ─────────────────────────────
    // State lives in task.agent = { active, cap, turns[], pending }. The prompt is rebuilt from it on every call.
    const turnOf = (n, tool, args, r) => ({ n, tool, args, ok: r.ok === true, code: r.code, result: String(r.ok ? r.output : r.error).slice(0, settings.agentResultChars ?? 1500),
        meta: r.meta && (r.meta.path || r.meta.exitCode !== undefined || r.meta.url || r.meta.urls || r.meta.item) ? { item: r.meta.item, path: r.meta.path, exitCode: r.meta.exitCode, passed: r.meta.passed, timedOut: r.meta.timedOut, url: r.meta.url, urls: r.meta.urls?.slice(0, 10) } : undefined });

    // Small, relevant slice of the chat's project memory. Never blocks or fails a task.
    async function projectContext(task) {
        if (!project || !tools?.has('note_add')) return '';
        try { return await project.context(task.chatJid, task.description, { maxItems: settings.projectContextItems ?? 5, maxChars: settings.projectContextChars ?? 1500 }); }
        catch { return ''; }
    }

    async function runAgent(state, notify) {
        const id = state.task.id;
        const ag = { active: true, cap: settings.agentMaxSteps ?? 12, turns: [], pending: null, ...(state.task.agent || {}) };
        const save = async () => { state.task = await store.updateTask(id, { agent: ag }); };
        if (!state.task.agent?.active) { await save(); await event(id, 'agent_started', { tools: tools.names() }); }
        let invalid = 0;
        for (;;) {
            const cur = await store.getTask(id);          // stop at a boundary if the user paused/cancelled
            if (!cur || !['running', 'planning'].includes(cur.status)) return { status: cur?.status === 'cancelled' ? 'cancelled' : 'discarded', task: cur || state.task };
            state.task = { ...cur, agent: ag };

            if (ag.pending) {
                const p = ag.pending;
                if (!p.decision) return askApproval(state, p);          // resumed while still undecided
                ag.pending = null;
                const turn = p.decision === 'approve'
                    ? turnOf(p.n, p.tool, p.args, await tools.call(p.tool, p.args, { approved: true, taskId: id }))
                    : { n: p.n, tool: p.tool, args: p.args, denied: true };
                ag.turns.push(turn); await save();
                await event(id, 'tool', { tool: p.tool, approved: p.decision, ok: turn.ok, code: turn.code });
                continue;
            }
            if (ag.turns.length >= ag.cap) {
                await save();
                throw new Stop(await pauseTask(state.task, 'step limit reached', `⏸️ Task #${id} paused after ${ag.turns.length} tool calls (step limit). Progress is saved — send .wresume ${id} to allow more.`));
            }
            const recent = await store.getRecent(state.task.chatJid);
            const res = await modelCall(state, state.task.kind === 'debug' ? 'debug' : state.task.kind === 'research' ? 'research' : 'code', buildAgentMessages(state.task, recent, tools.describe(), settings, await projectContext(state.task)), `agent ${ag.turns.length + 1}`);
            const act = parseAction(res.text);
            const n = ag.turns.length + 1;
            if (!act) {
                invalid += 1; ag.turns.push({ n, invalid: true }); await save();
                await event(id, 'agent_invalid', { reply: res.text });
                if (invalid >= 2) return finish(state, `⚠️ The model did not answer in the tool format, so nothing below was checked by tools.\n\n${String(res.text).trim()}`, { steps: ag.turns.length });
                continue;
            }
            invalid = 0;
            if (act.final !== undefined) {
                // Stage 7: no "done" for changed code that was never run — send the model back once.
                if (settings.verify !== false && needsCheckBeforeFinal(ag.turns, { canRun: tools.has('run_tests') || tools.has('run_command'), nudges: ag.nudges || 0, maxNudges: settings.verifyNudges ?? 1 })) {
                    ag.nudges = (ag.nudges || 0) + 1; ag.turns.push({ n, nudge: true, note: NUDGE_NOTE }); await save();
                    await event(id, 'verify_nudge', { n: ag.nudges });
                    continue;
                }
                const extra = await verifyStage(state, ag, act.final);
                return finish(state, `${act.final}${verifiedFooter(ag.turns, act.final)}${extra}`, { steps: ag.turns.filter((t) => t.tool).length });
            }

            const r = await tools.call(act.tool, act.args, { approved: false, taskId: id });
            if (r.needsApproval) {
                ag.pending = { n, tool: act.tool, args: r.args, decision: null }; await save();
                return askApproval(state, ag.pending);
            }
            ag.turns.push(turnOf(n, act.tool, act.args, r)); await save();
            await event(id, 'tool', { tool: act.tool, args: act.args, ok: r.ok, code: r.code, meta: r.meta });
            await tell(notify, `🔧 ${describeCall(act.tool, act.args)}${r.ok ? '' : ` ✗ ${r.code || 'error'}`}`);
        }
    }

    // Stage 7: unbacked-claim check + one independent review. Never pauses or fails the task: a review that
    // cannot run (no quota, low budget, bad reply) is reported as skipped, and the answer still ships.
    async function verifyStage(state, ag, finalText) {
        if (settings.verify === false) return '';
        const id = state.task.id;
        const claims = unbackedClaims(ag.turns, finalText);
        let review = null;
        if (settings.review !== false && reviewTarget(ag.turns) && !ag.reviewed) {
            ag.reviewed = true;
            const task = state.task; const budget = task.tokenBudget ?? settings.taskTokenBudget;
            if (budget && budget - (task.tokensIn + task.tokensOut) < (settings.reviewMinTokens ?? 1500)) review = { skipped: 'token budget nearly used' };
            else {
                const author = state.last;
                try {
                    const res = await modelCall(state, 'review', buildReviewMessages(task, ag.turns, finalText, settings), 'review');
                    const parsed = parseReview(res.text);
                    const by = `${res.provider}/${res.model}`;
                    review = parsed ? { ...parsed, by, sameFamily: !!author && author === by } : { skipped: 'reviewer reply was not usable' };
                } catch (e) {
                    if (e instanceof Stop) throw e;
                    review = { skipped: e instanceof WorkQuotaError ? 'no free quota left' : 'reviewer unavailable' };
                }
            }
            await event(id, 'review', { verdict: review.verdict || null, issues: review.issues || null, skipped: review.skipped || null, by: review.by || null });
        }
        const lines = verifyLines({ claims, review, nudged: (ag.nudges || 0) > 0 });
        return lines.length ? `\n${lines.join('\n')}` : '';
    }

    async function askApproval(state, p) {
        const task = state.task;
        const t = await store.setStatus(task.id, 'waiting_approval', { pauseReason: 'approval' }, { from: ['running', 'planning'] });
        if (!t) return { status: 'discarded', task };
        await event(task.id, 'approval_requested', { tool: p.tool, args: p.args });
        return { status: 'waiting_approval', task: t, notice: `🙋 Task #${task.id} wants to ${describeCall(p.tool, p.args)}\nReply .wapprove ${task.id} to allow or .wdeny ${task.id} to refuse.` };
    }

    async function decide(chatJid, id, decision) {
        if (!(await isActive(chatJid))) return { ok: false, message: 'Work Mode is off here. Send .wchat on first.' };
        const t = id ? await store.getTask(id) : await latest(chatJid, ['waiting_approval']);
        if (!t || t.chatJid !== chatJid) return { ok: false, message: id ? `No task #${id} here.` : 'Nothing is waiting for approval.' };
        if (t.status !== 'waiting_approval' || !t.agent?.pending) return { ok: false, message: `Task #${t.id} is ${t.status}, not waiting for approval.` };
        await store.updateTask(t.id, { agent: { ...t.agent, pending: { ...t.agent.pending, decision } } });
        const u = await store.setStatus(t.id, 'pending', { pauseReason: null }, { from: ['waiting_approval'] });
        if (!u) return { ok: false, message: `Task #${t.id} changed state; try again.` };
        await event(t.id, decision === 'approve' ? 'approved' : 'denied', { tool: t.agent.pending.tool });
        return { ok: true, task: u, tool: t.agent.pending.tool, args: t.agent.pending.args };
    }

    async function execute(task, notify) {
        const state = { task, last: task.provider ? `${task.provider}/${task.model}` : null };
        try {
            if (tools && (state.task.agent?.active || needsTools(state.task.description, { ...settings, web: tools.has('web_search'), project: tools.has('note_add') }))) return await runAgent(state, notify);
            if (state.task.plan?.length) return await runPlan(state, notify);          // resumed: never re-plan
            if (needsPlan(state.task.description, state.task.kind, settings)) {
                const stop = await makePlan(state, notify);
                if (stop) return stop;
                if (state.task.plan?.length) return await runPlan(state, notify);
            }
            return await runSingle(state);
        } catch (e) {
            if (e instanceof Stop) return e.outcome;
            return failure(state.task, e);
        }
    }

    // Run one task to its next resting state. Safe to call twice: only one caller wins the claim.
    async function run(taskId, { notify = null } = {}) {
        if (running.has(Number(taskId))) return { status: 'skipped', reason: 'already running here' };
        const claimed = await store.claimTask(taskId, owner, settings.leaseMs);
        if (!claimed) return { status: 'skipped', reason: 'not claimable' };
        running.add(claimed.id);
        const hb = setInterval(() => store.heartbeat(claimed.id, owner, settings.leaseMs).catch(() => {}), Math.max(1000, settings.leaseMs / 3));
        hb.unref?.();
        try {
            await event(claimed.id, 'started', { owner });
            return await execute(claimed, notify);
        } catch (e) {
            log(`task ${claimed.id} crashed: ${e.stack || e.message}`);
            const failed = await store.setStatus(claimed.id, 'failed', { error: String(e.message).slice(0, 500) }, { from: ['pending', 'planning', 'running'] }).catch(() => null);
            return { status: 'failed', task: failed || claimed, notice: `❌ Task #${claimed.id} failed: ${String(e.message).slice(0, 200)}` };
        } finally {
            clearInterval(hb);
            running.delete(claimed.id);
            await store.releaseLock(claimed.id, owner).catch(() => {});
        }
    }

    // No queue: every request starts the moment it arrives and is answered as soon as its own answer
    // is ready, even if an earlier request in the same chat is still running. run() already guarantees
    // one task never executes twice, so nothing else needs to wait.
    const runQueued = (task, opts) => run(task.id, opts);

    // ── control ─────────────────────────────────────────────────
    async function latest(chatJid, statuses) { return (await store.listTasks(chatJid, { statuses, limit: 1 }))[0] || null; }

    async function pause(chatJid, id = null) {
        const t = id ? await store.getTask(id) : await latest(chatJid, PAUSABLE);
        if (!t || t.chatJid !== chatJid) return { ok: false, message: id ? `No task #${id} here.` : 'Nothing is running to pause.' };
        const u = await store.setStatus(t.id, 'paused', { pauseReason: 'paused by user' }, { from: PAUSABLE });
        if (!u) return { ok: false, message: `Task #${t.id} is already ${t.status}.` };
        await event(t.id, 'paused', { reason: 'user' });
        return { ok: true, task: u };
    }

    async function resume(chatJid, id = null) {
        if (!(await isActive(chatJid))) return { ok: false, message: 'Work Mode is off here. Send .wchat on first.' };
        const t = id ? await store.getTask(id) : await latest(chatJid, ['paused']);
        if (!t || t.chatJid !== chatJid) return { ok: false, message: id ? `No task #${id} here.` : 'No paused task to resume.' };
        if (t.status !== 'paused') return { ok: false, message: `Task #${t.id} is ${t.status}, not paused.` };
        // A budget pause means the allowance was spent: grant a fresh one rather than looping.
        if (/budget/.test(t.pauseReason || '')) {
            await store.updateTask(t.id, { tokenBudget: (t.tokensIn + t.tokensOut) + settings.taskTokenBudget });
        }
        if (/step limit/.test(t.pauseReason || '') && t.agent?.active) {
            await store.updateTask(t.id, { agent: { ...t.agent, cap: (t.agent.turns?.length || 0) + (settings.agentMaxSteps ?? 12) } });
        }
        const u = await store.setStatus(t.id, 'pending', { pauseReason: null }, { from: ['paused'] });
        if (!u) return { ok: false, message: `Task #${t.id} changed state; try again.` };
        await event(t.id, 'resumed', {});
        return { ok: true, task: u };
    }

    async function cancel(chatJid, id = null) {
        const open = ['pending', 'planning', 'running', 'waiting_approval', 'paused'];
        const t = id ? await store.getTask(id) : await latest(chatJid, open);
        if (!t || t.chatJid !== chatJid) return { ok: false, message: id ? `No task #${id} here.` : 'No open task to cancel.' };
        const u = await store.setStatus(t.id, 'cancelled', {}, { from: open });
        if (!u) return { ok: false, message: `Task #${t.id} is already ${t.status}.` };
        await event(t.id, 'cancelled', {});
        return { ok: true, task: u };
    }

    // ── recovery ────────────────────────────────────────────────
    // Finds tasks whose worker vanished (restart, crash, expired lease) in chats where Work Mode is on
    // and runs them again. claimTask() makes this safe even if two sweeps or two instances overlap.
    async function recover({ notifyFor = null } = {}) {
        const outcomes = [];
        const stuck = await store.findAbandoned(20);
        for (const t of stuck) {
            modeCache.set(t.chatJid, true);
            const o = await runQueued(t, { notify: notifyFor ? notifyFor(t) : null }).catch((e) => ({ status: 'failed', task: t, notice: `❌ Task #${t.id} failed: ${e.message}` }));
            if (o.status !== 'skipped') outcomes.push({ chatJid: t.chatJid, recovered: true, ...o });
        }
        return outcomes;
    }

    async function status(chatJid) {
        const [active, tasks, health] = await Promise.all([isActive(chatJid), store.listTasks(chatJid, { limit: 50 }), providers.snapshot()]);
        const counts = {};
        for (const t of tasks) counts[t.status] = (counts[t.status] || 0) + 1;
        return { active, counts, health, budget: settings.taskTokenBudget, owner, search: tools?.get('web_search')?.status?.() || null };
    }

    async function housekeeping() { return store.pruneEvents(settings.eventKeepDays); }

    return { isActive, activate, deactivate, submit, run, runQueued, pause, resume, cancel,
             approve: (chatJid, id = null) => decide(chatJid, id, 'approve'), deny: (chatJid, id = null) => decide(chatJid, id, 'deny'), recover, status, housekeeping,
             list: (chatJid, limit = 8) => store.listTasks(chatJid, { limit }), getTask: (id) => store.getTask(id), listEvents: (id) => store.listEvents(id),
             projectView: async (chatJid) => (project ? {
                 counts: await project.counts(chatJid),
                 todos: [...await project.list(chatJid, { kind: 'todo', status: 'doing', limit: 8 }), ...await project.list(chatJid, { kind: 'todo', status: 'open', limit: 8 })].slice(0, 8),
                 decisions: await project.list(chatJid, { kind: 'decision', status: 'active', limit: 5 }),
                 notes: await project.list(chatJid, { kind: 'note', status: 'active', limit: 5 }) } : null),
             _running: running, _owner: owner };
}
