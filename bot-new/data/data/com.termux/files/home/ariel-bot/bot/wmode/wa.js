// bot/wmode/wa.js — stage 8: the WhatsApp interface of Work Mode, with no Baileys or database imports.
// index.js hands in `send(chatJid, text, quoted)` and `typing(chatJid, on)`; everything else (command routing,
// progress throttling, WhatsApp formatting, task views) lives here so it can be tested offline.
const ICON = { pending: '🕓', planning: '🧭', running: '⚙️', waiting_approval: '🙋', paused: '⏸️', completed: '✅', failed: '❌', cancelled: '🚫' };
export const WORK_COMMANDS = new Set(['.wchat', '.whelp', '.wtasks', '.wtask', '.wlog', '.wproject', '.wpause', '.wresume', '.wcancel', '.wapprove', '.wdeny', '.cchat']);

const short = (s, n = 48) => { const t = String(s || '').replace(/\s+/g, ' ').trim(); return t.length > n ? `${t.slice(0, n - 1)}…` : t; };
const untilStr = (ms) => (ms ? `${new Date(ms).toISOString().slice(11, 16)} UTC` : '');
const hhmm = (iso) => (iso ? String(iso).slice(11, 16) : '');

export function parseWorkCommand(text) {
    const lower = String(text || '').trim().toLowerCase().replace(/\s+/g, ' ');
    const cmd = lower.split(' ')[0];
    if (!WORK_COMMANDS.has(cmd)) return { isCmd: false };
    const arg = lower.slice(cmd.length).trim();
    const m = /^#?(\d+)$/.exec(arg);
    return { isCmd: true, cmd, arg, id: m ? Number(m[1]) : null };
}

// ── model text -> WhatsApp formatting ──────────────────────
// WhatsApp: *bold*  _italic_  ~strike~  ```code```. Models write Markdown, which shows up as stray ** and ###.
// Code (fenced and inline) is never touched.
export function toWhatsApp(md) {
    const parts = String(md ?? '').split(/(```[\s\S]*?```|`[^`\n]+`)/g);
    return parts.map((p, i) => {
        if (i % 2 === 1) return p;
        return p
            .replace(/^#{1,6}[ \t]+(.+?)[ \t]*#*$/gm, (_, h) => `*${h.replace(/\*+/g, '').trim()}*`)
            .replace(/\*\*(.+?)\*\*/g, '*$1*')
            .replace(/__(.+?)__/g, '*$1*')
            .replace(/~~(.+?)~~/g, '~$1~')
            .replace(/!?\[([^\]\n]+)\]\((https?:\/\/[^)\s]+)\)/g, (_, t, u) => (t.trim() === u ? u : `${t} (${u})`))
            .replace(/^[ \t]*[*+][ \t]+/gm, '- ')
            .replace(/^[ \t]*([-*_])([ \t]*\1){2,}[ \t]*$/gm, '───');
    }).join('');
}

// Splits on paragraph/line/space boundaries. A split inside a ``` block closes it and reopens it in the next part.
export function chunkMessage(text, max = 3500) {
    const s = String(text ?? '').trim();
    if (!s) return [];
    if (s.length <= max) return [s];
    const out = []; let rest = s; let reopen = false;
    while (rest.length > max) {
        const room = max - 8;
        let cut = rest.lastIndexOf('\n\n', room);
        if (cut < room * 0.4) cut = rest.lastIndexOf('\n', room);
        if (cut < room * 0.4) cut = rest.lastIndexOf(' ', room);
        if (cut < room * 0.4) cut = room;
        let piece = rest.slice(0, cut).trim(); rest = rest.slice(cut).trim();
        if (reopen) piece = `\`\`\`\n${piece}`;
        reopen = (piece.match(/```/g) || []).length % 2 === 1;
        if (reopen) piece += '\n```';
        out.push(piece);
    }
    if (rest) out.push(reopen ? `\`\`\`\n${rest}` : rest);
    return out;
}

// ── progress without spam ──────────────────────────────────
// Tool calls can come several per second. WhatsApp punishes floods, so lines are merged into one message per
// `minMs`, a batch shows at most `maxLines` lines, and a task sends at most `maxMessages` progress messages.
// Lines pushed with {now:true} (plans, approvals) go out immediately together with whatever is waiting.
export function createProgress({ send, now = Date.now, setTimer = setTimeout, clearTimer = clearTimeout, minMs = 8000, maxLines = 6, maxMessages = 10 }) {
    let queue = []; let last = -Infinity; let sent = 0; let timer = null; let hidden = 0;
    const emit = async () => {
        if (timer) { clearTimer(timer); timer = null; }
        if (!queue.length) return;
        const lines = queue; queue = [];
        if (sent >= maxMessages) { hidden += lines.length; return; }
        const shown = lines.slice(0, maxLines);
        const more = lines.length - shown.length;
        sent += 1; last = now();
        try { await send(`${shown.join('\n')}${more > 0 ? `\n…and ${more} more step(s)` : ''}`); } catch { /* progress must never break a task */ }
    };
    return {
        async push(line, { now: urgent = false } = {}) {
            const t = String(line || '').trim();
            if (!t || queue.at(-1) === t) return;
            queue.push(t);
            if (urgent || now() - last >= minMs) return emit();
            if (!timer) { timer = setTimer(() => { timer = null; emit(); }, Math.max(0, minMs - (now() - last))); timer.unref?.(); }
        },
        flush: emit,
        stop() { if (timer) { clearTimer(timer); timer = null; } queue = []; },
        get stats() { return { sent, hidden }; },
    };
}

// ── views ──────────────────────────────────────────────────
export function helpText() {
    return ['🧰 *Work Mode*',
        '*.whelp* — this list',
        '*.wchat on* / *off* — switch it for this chat (tasks are kept)',
        '*.wchat status* — state, models, search',
        '*.wtasks* — recent tasks',
        '*.wtask [id]* — one task: plan, progress, tokens',
        '*.wlog [id]* — what it actually did (tool calls, model switches)',
        '*.wproject* — saved to-dos, decisions and notes for this chat',
        '*.wpause* / *.wresume* / *.wcancel* [id]',
        '*.wapprove* / *.wdeny* [id] — answer a request to run code or delete a file',
        '*.cchat* <message> — creative brainstorming partner (stories, characters, stages); *.cchat clear* starts fresh',
        '',
        'With Work Mode on, just send what you need. Messages starting with "." still run normal commands.'].join('\n');
}

export function formatStatus(s) {
    const counts = Object.entries(s.counts).map(([k, v]) => `${ICON[k] || ''}${v}`).join(' ') || 'no tasks yet';
    const prov = s.health.map((h) => {
        const mark = h.state === 'ok' ? '🟢' : h.state === 'cooling' ? '🟡' : h.state === 'out' ? `🔴 until ${untilStr(h.until)}` : '⚪ no key';
        return `${mark} ${h.key.split('/').slice(-1)[0]} (${h.provider})`;
    }).join('\n');
    const web = s.search ? `\n\n*Search*\n${s.search.map((b) => `${b.state === 'ok' ? '🟢' : b.state === 'paused' ? '🟡' : '⚪'} ${b.name}${b.state === 'no key' ? ' (no key)' : b.state === 'paused' ? ' (paused)' : ''}`).join(' · ')}` : '';
    return `🧰 *Work Mode:* ${s.active ? 'ON' : 'off'}\n📋 Tasks: ${counts}\n🪙 Budget per task: ${s.budget} tokens\n\n*Models*\n${prov}${web}`;
}

export function formatTaskList(list) {
    if (!list.length) return '🧰 No tasks yet.';
    return `🧰 *Recent tasks*\n${list.map((t) => `${ICON[t.status]} #${t.id} ${short(t.description)}${t.status === 'paused' && t.pauseReason ? ` _(${t.pauseReason})_` : ''}`).join('\n')}\n\n_.wtask <id> for details_`;
}

export function formatTask(t) {
    const used = (t.tokensIn || 0) + (t.tokensOut || 0);
    const lines = [`${ICON[t.status]} *Task #${t.id}* — ${t.status}${t.pauseReason && t.status === 'paused' ? ` (${t.pauseReason})` : ''}`, short(t.description, 160)];
    if (t.plan?.length) {
        const done = t.plan.filter((s) => s.status === 'done').length;
        lines.push('', `*Plan* ${done}/${t.plan.length}`, ...t.plan.map((s) => `${s.status === 'done' ? '✅' : '⬜'} ${s.n}. ${short(s.title, 60)}`));
    }
    const calls = (t.agent?.turns || []).filter((x) => x.tool).length;
    if (calls) lines.push('', `🔧 ${calls} tool call(s)${t.agent?.pending ? ` · waiting on: ${t.agent.pending.tool}` : ''}`);
    lines.push('', `🪙 ${used}${t.tokenBudget ? ` / ${t.tokenBudget}` : ''} tokens${t.provider ? ` · last model ${t.provider}/${String(t.model).split('/').pop()}` : ''}`);
    lines.push(`🕓 started ${hhmm(t.startedAt || t.createdAt)} UTC${t.completedAt ? ` · finished ${hhmm(t.completedAt)} UTC` : ''}`);
    if (t.error) lines.push(`❌ ${short(t.error, 200)}`);
    if (t.status === 'completed' && t.result) lines.push('', `*Result*\n${short(t.result, 300)}`);
    if (t.status === 'waiting_approval') lines.push('', `Reply .wapprove ${t.id} or .wdeny ${t.id}`);
    if (t.status === 'paused') lines.push('', `Send .wresume ${t.id} to continue.`);
    return lines.join('\n');
}

export function formatProject(v) {
    if (!v) return '🧰 Project memory is not available.';
    const c = v.counts;
    if (!c.note && !c.decision && !c.todo) return '🧰 *Project memory* is empty. Ask Work Mode to "add a to-do…", "note that…" or "record the decision…".';
    const out = [`🗂️ *Project memory* — ${c.openTodos} open to-do(s) · ${c.decision} decision(s) · ${c.note} note(s)`];
    if (v.todos.length) out.push('', '*To-dos*', ...v.todos.map((t) => `${t.status === 'doing' ? '🔧' : '⬜'} #${t.id} ${short(t.title, 70)}`));
    if (v.decisions.length) out.push('', '*Decisions*', ...v.decisions.map((d) => `📌 #${d.id} ${short(d.title, 60)} — ${short(d.body, 80)}`));
    if (v.notes.length) out.push('', '*Notes*', ...v.notes.map((n) => `📝 #${n.id} ${short(n.title, 70)}`));
    return out.join('\n');
}

const EVENT_TEXT = {
    created: () => 'created', started: () => 'started', planned: (d) => `planned ${d.steps?.length ?? '?'} steps`, plan_skipped: () => 'planning skipped',
    step_done: (d) => `step ${d.n} done: ${short(d.title, 40)}`, model_call: (d) => `model ${d.provider}/${String(d.model).split('/').pop()} (${d.label}, ${(d.tokensIn || 0) + (d.tokensOut || 0)} tok)`,
    provider_switch: (d) => `switched ${d.from} → ${d.to}`, tool: (d) => `tool ${d.tool}${d.approved ? ` (${d.approved})` : ''} ${d.ok === false ? '✗' : '✓'}`,
    approval_requested: (d) => `asked approval: ${d.tool}`, approved: (d) => `approved ${d.tool}`, denied: (d) => `denied ${d.tool}`,
    verify_nudge: () => 'sent back to run a check', review: (d) => (d.skipped ? `review skipped (${d.skipped})` : `review by ${d.by}: ${d.verdict}`),
    paused: (d) => `paused: ${d.reason}`, failed: (d) => `failed: ${short(d.error, 60)}`,
};
export function formatLog(id, events, max = 12) {
    const rows = (events || []).filter((e) => e.kind !== 'agent_invalid').slice(-max);
    if (!rows.length) return `🧰 No log for task #${id}.`;
    return `🧰 *Task #${id} log* (last ${rows.length})\n${rows.map((e) => `${hhmm(e.ts)} ${(EVENT_TEXT[e.kind] || (() => e.kind))(e.data || {})}`).join('\n')}`;
}

// ── the interface ──────────────────────────────────────────
// handle() returns true when Work Mode consumed the message. It never throws.
export function createWorkInterface({ manager, creative = null, settings = {}, send, typing = async () => {}, log = () => {}, setTimer = setTimeout, clearTimer = clearTimeout, setTick = setInterval, clearTick = clearInterval, now = Date.now }) {
    const say = async (chatJid, text, quoted = null) => { for (const part of chunkMessage(text, settings.maxMessageChars || 3500)) await send(chatJid, part, quoted); };

    async function deliver(chatJid, outcome, quoted = null) {
        if (!outcome || outcome.status === 'skipped' || outcome.status === 'discarded') return;
        const prefix = outcome.recovered ? `🔁 _Resumed after a restart — task #${outcome.task?.id}_\n\n` : '';
        if (outcome.status === 'completed') {
            const foot = `\n\n_#${outcome.task.id} · ${outcome.provider}/${String(outcome.model).split('/').pop()}${outcome.steps ? ` · ${outcome.steps} steps` : ''}_`;
            await say(chatJid, `${prefix}${toWhatsApp(outcome.text)}${foot}`, quoted);
        } else if (outcome.notice) await say(chatJid, `${prefix}${outcome.notice}`, quoted);
    }

    // Runs one task with a typing indicator and throttled progress, then delivers its result.
    async function work(chatJid, task, { quoted = null, recovered = false } = {}) {
        const progress = createProgress({ send: (t) => say(chatJid, t, quoted), now, setTimer, clearTimer,
            minMs: settings.progressMinMs ?? 8000, maxLines: settings.progressMaxLines ?? 6, maxMessages: settings.progressMaxMessages ?? 10 });
        const on = settings.typing !== false;
        let tick = null;
        if (on) { await typing(chatJid, true).catch(() => {}); tick = setTick(() => typing(chatJid, true).catch(() => {}), settings.typingRefreshMs ?? 10_000); tick.unref?.(); }
        try {
            const outcome = await manager.runQueued(task, { notify: (line) => progress.push(line, { now: /^(📋|🙋)/.test(line) }) });
            await progress.flush();
            await deliver(chatJid, recovered ? { ...outcome, recovered: true } : outcome, quoted);
            return outcome;
        } finally {
            progress.stop();
            if (tick) clearTick(tick);
            if (on) await typing(chatJid, false).catch(() => {});
        }
    }

    async function handle({ text, chatJid, userId, isDM = false, msgId = null, quoted = null }) {
        try {
            const c = parseWorkCommand(text);
            if (!c.isCmd) {
                if (!String(text || '').trim() || String(text).trim().startsWith('.')) return false;   // normal commands keep working
                if (!(await manager.isActive(chatJid))) return false;                                  // Work Mode off: Ariel as before
                const { task, created } = await manager.submit({ chatJid, userId, text, msgId });
                if (created) await work(chatJid, task, { quoted });                                    // a redelivered message is already a task
                return true;
            }
            const { cmd, arg, id } = c;

            if (cmd === '.whelp') { await say(chatJid, helpText(), quoted); return true; }

            if (cmd === '.wchat') {
                if (arg === 'on') {
                    const r = await manager.activate(chatJid, userId, { isDM });
                    if (!r.ok) { await say(chatJid, `🧰 ${r.message}`, quoted); return true; }
                    const open = r.resumable.length
                        ? `\n\n📌 Unfinished from before:\n${r.resumable.map((t) => `${ICON[t.status]} #${t.id} ${short(t.description)}`).join('\n')}\nSend .wresume to continue the latest paused one.` : '';
                    await say(chatJid, `🧰 *Work Mode ON.* Send requests normally; commands starting with "." still work as usual. .whelp lists the Work commands. Turn off with .wchat off. Tasks are kept.${open}`, quoted);
                    for (const t of r.resumable.filter((x) => x.status === 'pending' || x.status === 'running')) work(chatJid, t, { recovered: true }).catch((e) => log(`resume failed: ${e?.message}`));
                } else if (arg === 'off') {
                    const r = await manager.deactivate(chatJid);
                    await say(chatJid, `🧰 *Work Mode OFF.* Ariel is back to normal.${r.paused.length ? ` Parked ${r.paused.length} unfinished task(s): ${r.paused.map((x) => `#${x}`).join(', ')} — they resume after .wchat on.` : ''}`, quoted);
                } else if (arg === 'status' || arg === '') await say(chatJid, formatStatus(await manager.status(chatJid)), quoted);
                else await say(chatJid, 'Use: .wchat on · .wchat off · .wchat status · .whelp', quoted);
                return true;
            }

            if (cmd === '.cchat') {
                const raw = String(text || '').trim().replace(/^\S+\s*/, '');     // keep the original case and spacing
                if (!raw || /^(help|\?)$/i.test(raw)) { await say(chatJid, '🎨 *.cchat* <message> — brainstorm ideas with me. *.cchat clear* — start a fresh conversation. I remember the last few messages in this chat.', quoted); return true; }
                if (/^(clear|reset)$/i.test(raw)) { creative?.clear(chatJid); await say(chatJid, '🎨 Fresh start.', quoted); return true; }
                if (!creative) { await say(chatJid, '🎨 Creative chat is unavailable right now.', quoted); return true; }
                const on = settings.typing !== false;
                if (on) await typing(chatJid, true).catch(() => {});
                try {
                    const r = await creative.reply(chatJid, raw);
                    await say(chatJid, `${toWhatsApp(r.text)}\n\n_${r.provider}/${String(r.model).split('/').pop()}_`, quoted);
                } catch (e) {
                    const quota = e?.name === 'WorkQuotaError';
                    await say(chatJid, quota ? `🎨 Every model for creative chat is out of quota${e.resetAt ? ` until ${untilStr(e.resetAt)}` : ''}. Try again later.` : `🎨 ⚠️ ${String(e?.message || e).slice(0, 160)}`, quoted);
                } finally {
                    if (on) await typing(chatJid, false).catch(() => {});
                }
                return true;
            }

            if (cmd === '.wtasks') { await say(chatJid, formatTaskList(await manager.list(chatJid, 8)), quoted); return true; }

            if (cmd === '.wtask' || cmd === '.wlog') {
                const t = id ? await manager.getTask(id) : (await manager.list(chatJid, 1))[0];
                if (!t || t.chatJid !== chatJid) { await say(chatJid, id ? `🧰 No task #${id} here.` : '🧰 No tasks yet.', quoted); return true; }   // another chat's task is invisible
                await say(chatJid, cmd === '.wtask' ? formatTask(t) : formatLog(t.id, await manager.listEvents(t.id), settings.logLines ?? 12), quoted);
                return true;
            }

            if (cmd === '.wproject') { await say(chatJid, formatProject(await manager.projectView(chatJid)), quoted); return true; }

            if (cmd === '.wpause' || cmd === '.wcancel') {
                const r = await (cmd === '.wpause' ? manager.pause(chatJid, id) : manager.cancel(chatJid, id));
                await say(chatJid, r.ok ? `${ICON[r.task.status]} Task #${r.task.id} ${r.task.status}.` : `🧰 ${r.message}`, quoted);
                return true;
            }
            if (cmd === '.wapprove' || cmd === '.wdeny') {
                const r = await (cmd === '.wapprove' ? manager.approve(chatJid, id) : manager.deny(chatJid, id));
                if (!r.ok) { await say(chatJid, `🧰 ${r.message}`, quoted); return true; }
                await say(chatJid, cmd === '.wapprove' ? `✅ Approved for task #${r.task.id}. Running…` : `🚫 Denied for task #${r.task.id}. It will try another way.`, quoted);
                await work(chatJid, r.task, { quoted });
                return true;
            }
            if (cmd === '.wresume') {
                const r = await manager.resume(chatJid, id);
                if (!r.ok) { await say(chatJid, `🧰 ${r.message}`, quoted); return true; }
                await say(chatJid, `▶️ Resuming task #${r.task.id}…`, quoted);
                await work(chatJid, r.task, { quoted });
                return true;
            }
            return false;
        } catch (e) {
            log(`interface error: ${e?.stack || e?.message}`);
            try { await send(chatJid, `🧰 ⚠️ Work Mode hit an error: ${String(e?.message || e).slice(0, 160)}`, quoted); } catch { /* nothing more to do */ }
            return true;
        }
    }

    return { handle, deliver: (chatJid, outcome) => deliver(chatJid, outcome), work };
}
