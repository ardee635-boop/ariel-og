// bot/wmode/project.js — project memory: notes, decisions and to-dos, kept per chat (sql/005_work_project.sql).
// Two stores with the same API: Postgres (createProjectStore) and in-memory (createMemoryProjectStore, for checks).
// Items are scoped by chat_jid; every read/write names the chat, so one chat can never see another's items.
export const KINDS = ['note', 'decision', 'todo'];
export const TODO_STATUSES = ['open', 'doing', 'done', 'dropped'];
const DEFAULT_STATUS = { note: 'active', decision: 'active', todo: 'open' };

export const SECRET_RE = /\b(sk-[A-Za-z0-9_-]{20,}|AIza[0-9A-Za-z_-]{30,}|gsk_[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{30,}|xox[abp]-[A-Za-z0-9-]{10,}|tvly-[A-Za-z0-9-]{10,}|postgres(?:ql)?:\/\/[^\s:/]+:[^\s@]+@)/;
export const looksLikeSecret = (s) => SECRET_RE.test(String(s || ''));

const clip = (v, n) => { const s = String(v ?? '').replace(/\s+/g, ' ').trim(); return s.length > n ? `${s.slice(0, n - 1)}…` : s; };
const STOP = new Set(['this', 'that', 'with', 'from', 'have', 'what', 'when', 'will', 'your', 'about', 'into', 'then', 'them', 'they', 'there', 'please', 'could', 'would', 'should', 'make', 'some', 'file', 'files']);
const words = (t) => [...new Set(String(t || '').toLowerCase().match(/[a-z0-9_]{4,}/g) || [])].filter((w) => !STOP.has(w));

export function mapItem(r) {
    if (!r) return null;
    return { id: Number(r.id), chatJid: r.chat_jid, userId: r.user_id, kind: r.kind, title: r.title, body: r.body || '', status: r.status,
        taskId: r.task_id == null ? null : Number(r.task_id), createdAt: r.created_at, updatedAt: r.updated_at };
}

// What a task should know about the project, small and relevant: open to-dos, recent decisions, and only the notes
// that share words with the request. Never "everything we ever stored".
export function buildContext({ todos = [], decisions = [], notes = [] }, description, { maxItems = 5, maxChars = 1500 } = {}) {
    const w = words(description);
    const scored = notes.map((n) => ({ n, s: w.filter((x) => `${n.title} ${n.body}`.toLowerCase().includes(x)).length })).filter((x) => x.s > 0)
        .sort((a, b) => b.s - a.s).slice(0, Math.min(3, maxItems)).map((x) => x.n);
    const lines = [];
    for (const t of todos.slice(0, maxItems)) lines.push(`- todo #${t.id} [${t.status}] ${clip(t.title, 100)}`);
    for (const d of decisions.slice(0, Math.min(4, maxItems))) lines.push(`- decision #${d.id}: ${clip(d.title, 80)} — ${clip(d.body, 160)}`);
    for (const n of scored) lines.push(`- note #${n.id} ${clip(n.title, 80)}: ${clip(n.body, 200)}`);
    if (!lines.length) return '';
    let out = lines.join('\n');
    if (out.length > maxChars) out = `${out.slice(0, maxChars - 1)}…`;
    return out;
}

async function contextFor(store, chatJid, description, limits) {
    const [todoA, todoB, decisions, notes] = await Promise.all([
        store.list(chatJid, { kind: 'todo', status: 'open', limit: 20 }), store.list(chatJid, { kind: 'todo', status: 'doing', limit: 20 }),
        store.list(chatJid, { kind: 'decision', status: 'active', limit: 4 }), store.list(chatJid, { kind: 'note', status: 'active', limit: 100 })]);
    return buildContext({ todos: [...todoB, ...todoA], decisions, notes }, description, limits);
}

function checkNew({ kind, title, status }) {
    if (!KINDS.includes(kind)) throw new Error(`bad kind "${kind}"`);
    if (!String(title || '').trim()) throw new Error('title is required');
    const st = status || DEFAULT_STATUS[kind];
    return st;
}
const limitError = (max) => Object.assign(new Error(`this chat already has ${max} project items — mark old to-dos done/dropped or ask the user to clean up`), { code: 'limit' });

// ── in-memory ──
export function createMemoryProjectStore({ maxItems = 500 } = {}) {
    const items = new Map(); let next = 1; const iso = () => new Date().toISOString();
    const store = {
        kind: 'memory',
        async add({ chatJid, userId, kind, title, body = '', status = null, taskId = null }) {
            const st = checkNew({ kind, title, status });
            if ([...items.values()].filter((i) => i.chat_jid === chatJid).length >= maxItems) throw limitError(maxItems);
            const r = { id: next++, chat_jid: chatJid, user_id: userId, kind, title: String(title).trim(), body: String(body), status: st, task_id: taskId, created_at: iso(), updated_at: iso() };
            items.set(r.id, r); return mapItem({ ...r });
        },
        async get(chatJid, id) { const r = items.get(Number(id)); return r && r.chat_jid === chatJid ? mapItem({ ...r }) : null; },
        async update(chatJid, id, { title, body, status } = {}) {
            const r = items.get(Number(id)); if (!r || r.chat_jid !== chatJid) return null;
            if (title != null) r.title = String(title).trim(); if (body != null) r.body = String(body); if (status != null) r.status = status;
            r.updated_at = iso(); return mapItem({ ...r });
        },
        async list(chatJid, { kind = null, status = null, query = null, limit = 20 } = {}) {
            const q = query ? String(query).toLowerCase() : null;
            return [...items.values()].filter((r) => r.chat_jid === chatJid && (!kind || r.kind === kind) && (!status || r.status === status)
                && (!q || `${r.title} ${r.body}`.toLowerCase().includes(q)))
                .sort((a, b) => (b.updated_at.localeCompare(a.updated_at)) || b.id - a.id).slice(0, limit).map((r) => mapItem({ ...r }));
        },
        async counts(chatJid) {
            const c = { note: 0, decision: 0, todo: 0, openTodos: 0 };
            for (const r of items.values()) if (r.chat_jid === chatJid) { c[r.kind] += 1; if (r.kind === 'todo' && ['open', 'doing'].includes(r.status)) c.openTodos += 1; }
            return c;
        },
    };
    store.context = (chatJid, description, limits) => contextFor(store, chatJid, description, limits);
    return store;
}

// ── Postgres ──
export function createProjectStore(db, { maxItems = 500 } = {}) {
    const q = (t, p) => db.query(t, p);
    const like = (s) => `%${String(s).replace(/[\\%_]/g, '\\$&')}%`;
    const store = {
        kind: 'pg',
        async add({ chatJid, userId, kind, title, body = '', status = null, taskId = null }) {
            const st = checkNew({ kind, title, status });
            const n = await q('select count(*)::int as n from ariel.work_project_items where chat_jid = $1', [chatJid]);
            if (n.rows[0].n >= maxItems) throw limitError(maxItems);
            const r = await q(`insert into ariel.work_project_items (chat_jid, user_id, kind, title, body, status, task_id) values ($1,$2,$3,$4,$5,$6,$7) returning *`,
                [chatJid, userId, kind, String(title).trim(), String(body), st, taskId]);
            return mapItem(r.rows[0]);
        },
        async get(chatJid, id) { return mapItem((await q('select * from ariel.work_project_items where chat_jid = $1 and id = $2', [chatJid, Number(id)])).rows[0]); },
        async update(chatJid, id, { title, body, status } = {}) {
            const r = await q(`update ariel.work_project_items set title = coalesce($3, title), body = coalesce($4, body), status = coalesce($5, status), updated_at = now()
                               where chat_jid = $1 and id = $2 returning *`, [chatJid, Number(id), title ?? null, body ?? null, status ?? null]);
            return mapItem(r.rows[0]);
        },
        async list(chatJid, { kind = null, status = null, query = null, limit = 20 } = {}) {
            const r = await q(`select * from ariel.work_project_items where chat_jid = $1 and ($2::text is null or kind = $2) and ($3::text is null or status = $3)
                               and ($4::text is null or title ilike $4 or body ilike $4) order by updated_at desc, id desc limit $5`,
                [chatJid, kind, status, query ? like(query) : null, limit]);
            return r.rows.map(mapItem);
        },
        async counts(chatJid) {
            const r = await q(`select kind, count(*)::int as n, count(*) filter (where status in ('open','doing'))::int as open from ariel.work_project_items where chat_jid = $1 group by kind`, [chatJid]);
            const c = { note: 0, decision: 0, todo: 0, openTodos: 0 };
            for (const x of r.rows) { c[x.kind] = x.n; if (x.kind === 'todo') c.openTodos = x.open; }
            return c;
        },
    };
    store.context = (chatJid, description, limits) => contextFor(store, chatJid, description, limits);
    return store;
}
