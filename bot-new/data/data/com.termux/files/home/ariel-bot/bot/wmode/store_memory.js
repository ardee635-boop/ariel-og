// bot/wmode/store_memory.js — in-memory twin of store.js. Same methods, same rules.
// Used by the offline check script (and handy for a dry run without a database).
// The Postgres version is exercised by `scripts/ariel-work-check.js --db`.
import { TERMINAL, capTurns } from './store.js';

export function createMemoryWorkStore({ now = Date.now } = {}) {
    const modes = new Map(); const sessions = new Map(); const tasks = new Map();
    const events = []; const config = new Map();
    let nextId = 1;
    const clone = (t) => (t ? JSON.parse(JSON.stringify(t)) : null);
    const iso = () => new Date(now()).toISOString();
    const leaseLive = (t) => t.lockedBy && t.leaseUntil && new Date(t.leaseUntil).getTime() >= now();

    return {
        kind: 'memory',
        _tasks: tasks, _events: events,

        async getMode(c) { return modes.get(c)?.active === true; },
        async listActiveChats() { return [...modes].filter(([, v]) => v.active).map(([k]) => k); },
        async setMode(c, active) { modes.set(c, { active: active === true }); },

        async ensureSession(c, userId) { if (!sessions.has(c)) sessions.set(c, { userId, recent: [] }); },
        async getRecent(c) { return clone(sessions.get(c)?.recent || []); },
        async appendTurns(c, userId, turns, maxTurns, maxChars) {
            await this.ensureSession(c, userId);
            const s = sessions.get(c);
            s.recent = capTurns([...s.recent, ...turns], maxTurns, maxChars);
        },

        async createTask({ userId, chatJid, sourceMsgId = null, description, kind = 'simple', tokenBudget = null }) {
            if (sourceMsgId) {
                for (const t of tasks.values()) if (t.chatJid === chatJid && t.sourceMsgId === sourceMsgId) return { task: clone(t), created: false };
            }
            const t = { id: nextId++, userId, chatJid, sourceMsgId, description, kind, status: 'pending', plan: [], currentStep: 0,
                completedSteps: [], pendingSteps: [], agent: {}, provider: null, model: null, tokensIn: 0, tokensOut: 0, tokenBudget,
                result: null, error: null, pauseReason: null, lockedBy: null, leaseUntil: null,
                createdAt: iso(), startedAt: null, completedAt: null, updatedAt: iso() };
            tasks.set(t.id, t);
            return { task: clone(t), created: true };
        },
        async getTask(id) { return clone(tasks.get(Number(id))); },
        async listTasks(c, { statuses = null, limit = 10 } = {}) {
            return [...tasks.values()].filter((t) => t.chatJid === c && (!statuses || statuses.includes(t.status)))
                .sort((a, b) => b.id - a.id).slice(0, limit).map(clone);
        },
        async claimTask(id, owner, leaseMs) {
            const t = tasks.get(Number(id));
            if (!t || !['pending', 'running', 'planning'].includes(t.status) || leaseLive(t)) return null;
            t.lockedBy = owner; t.leaseUntil = new Date(now() + leaseMs).toISOString();
            if (t.status === 'pending') t.status = 'running';
            t.startedAt = t.startedAt || iso(); t.pauseReason = null; t.updatedAt = iso();
            return clone(t);
        },
        async heartbeat(id, owner, leaseMs) {
            const t = tasks.get(Number(id));
            if (!t || t.lockedBy !== owner) return false;
            t.leaseUntil = new Date(now() + leaseMs).toISOString(); return true;
        },
        async releaseLock(id, owner) {
            const t = tasks.get(Number(id));
            if (t && t.lockedBy === owner) { t.lockedBy = null; t.leaseUntil = null; }
        },
        async setStatus(id, status, extra = {}, { from = null } = {}) {
            const t = tasks.get(Number(id));
            if (!t || TERMINAL.includes(t.status) || (from && !from.includes(t.status))) return null;
            t.status = status; t.updatedAt = iso();
            for (const k of ['result', 'error', 'pauseReason']) if (extra[k] !== undefined) t[k] = extra[k];
            if (TERMINAL.includes(status)) t.completedAt = iso();
            if (status === 'running') t.startedAt = t.startedAt || iso();
            if (status !== 'running' && status !== 'planning') { t.lockedBy = null; t.leaseUntil = null; }
            return clone(t);
        },
        async updateTask(id, patch) {
            const t = tasks.get(Number(id)); if (!t) return null;
            for (const k of ['kind', 'plan', 'currentStep', 'completedSteps', 'pendingSteps', 'agent', 'provider', 'model', 'result', 'error', 'pauseReason', 'tokenBudget']) {
                if (patch[k] !== undefined) t[k] = patch[k];
            }
            t.updatedAt = iso(); return clone(t);
        },
        async addUsage(id, tin, tout, provider, model) {
            const t = tasks.get(Number(id)); if (!t) return null;
            t.tokensIn += tin || 0; t.tokensOut += tout || 0; t.provider = provider; t.model = model; t.updatedAt = iso();
            return clone(t);
        },
        async findAbandoned(limit = 20) {
            return [...tasks.values()].filter((t) => ['pending', 'running', 'planning'].includes(t.status)
                && modes.get(t.chatJid)?.active && !leaseLive(t)).sort((a, b) => a.id - b.id).slice(0, limit).map(clone);
        },
        async pauseActiveInChat(c, reason) {
            const ids = [];
            for (const t of tasks.values()) {
                if (t.chatJid === c && ['pending', 'running', 'planning'].includes(t.status)) {
                    t.status = 'paused'; t.pauseReason = reason; t.lockedBy = null; t.leaseUntil = null; t.updatedAt = iso(); ids.push(t.id);
                }
            }
            return ids;
        },

        async addEvent(taskId, kind, data = {}) { events.push({ taskId: Number(taskId), ts: iso(), kind, data: clone(data) }); },
        async listEvents(taskId, limit = 50) { return events.filter((e) => e.taskId === Number(taskId)).slice(-limit).map(clone); },
        async pruneEvents(days) {
            const cut = now() - days * 86400_000; const keep = events.filter((e) => new Date(e.ts).getTime() >= cut);
            const n = events.length - keep.length; events.length = 0; events.push(...keep); return n;
        },

        async getConfig(k, fb = null) { return config.has(k) ? clone(config.get(k)) : fb; },
        async setConfig(k, v) { config.set(k, clone(v)); },
    };
}
