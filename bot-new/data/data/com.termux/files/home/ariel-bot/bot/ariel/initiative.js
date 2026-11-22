// Initiative engine: every 15 minutes she looks for a reason to speak. Most ticks end with nothing,
// and that is the normal result. Order of play for each chat:
//   cheap gates (no model) -> candidates -> small `decide` pick -> she writes the opening -> shadow-log or send.
// Modes per chat: off | shadow (log what she WOULD send; the default) | live (really send).
//   groups: chats.settings.initiative      DMs: config flag initiative.dm

export const LIMITS = {
    dm: { daily: 1, weekly: 3, gapH: 12, waitsH: [72, 336], quietMin: 30 },      // waits after 1 / 2 unanswered
    group: { daily: 2, weekly: 8, gapH: 4, waitsH: [24, 72], quietMin: 10 },
};
export const WINDOWS = [10, 14, 18];          // Lagos hours when the timer asks "anything worth saying?"
const MIN_RECEPTIVE = 0.3;
const HOUR = 3600_000;

const parts = (ms, tz) => {
    const p = new Intl.DateTimeFormat('en-CA', { timeZone: tz, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', hourCycle: 'h23' })
        .formatToParts(new Date(ms)).reduce((a, x) => ((a[x.type] = x.value), a), {});
    return { day: `${p.year}-${p.month}-${p.day}`, hour: Number(p.hour) };
};
export const quietHours = (ms, tz = 'Africa/Lagos') => { const h = parts(ms, tz).hour; return h >= 23 || h < 7; };
const daysBetween = (a, b) => Math.round((Date.parse(`${b}T00:00:00Z`) - Date.parse(`${a}T00:00:00Z`)) / 86400_000);
const ms = (d) => new Date(d).getTime();

// history: this chat's sent/shadow initiatives, newest first
export function capReason(kind, hist, nowMs) {
    const L = LIMITS[kind];
    const at = (h) => ms(h.sent_at || h.created_at);
    if (hist.length && nowMs - at(hist[0]) < L.gapH * HOUR) return 'minimum gap since the last one';
    if (hist.filter((h) => nowMs - at(h) < 24 * HOUR).length >= L.daily) return 'daily cap used';
    if (hist.filter((h) => nowMs - at(h) < 7 * 24 * HOUR).length >= L.weekly) return 'weekly cap used';
    return null;
}

// Unanswered streak from messages she really sent (shadow ones were never seen by anyone).
export function streakInfo(hist) {
    const sent = hist.filter((h) => h.status === 'sent');
    let streak = 0;
    for (const h of sent) {
        if (!h.outcome?.resolved) return { streak, pending: true, lastSentAt: sent[0] ? ms(sent[0].sent_at) : null };
        if (h.outcome.answered === false) streak++; else break;
    }
    return { streak, pending: false, lastSentAt: sent[0] ? ms(sent[0].sent_at) : null };
}

// → null if allowed; 'blocked-until-addressed' means check whether they spoke to her since.
export function waitReason(kind, info, nowMs) {
    if (info.pending) return 'waiting to see if the last one was answered';
    if (info.streak <= 0) return null;
    if (info.streak >= 3) return 'blocked-until-addressed';
    const wait = LIMITS[kind].waitsH[info.streak - 1] * HOUR;
    return nowMs - info.lastSentAt < wait ? `paused after ${info.streak} unanswered` : null;
}

export function parsePick(text, n) {
    const m = String(text || '').match(/pick\s*[:=]\s*(none|\d{1,2})/i);
    if (!m || m[1].toLowerCase() === 'none') return null;
    const i = Number(m[1]);
    return i >= 1 && i <= n ? i - 1 : null;
}

export function createInitiative({ store, flags, ai, conv, send, isEnabled, log = () => {}, now = Date.now, tz = 'Africa/Lagos' }) {
    const counters = { ticks: 0, chats: 0, candidates: 0, picked: 0, shadow: 0, sent: 0, skipped: 0, resolved: 0, lastTick: null };
    const windowDone = new Set();

    const modeFor = async (c) => {
        const v = c.kind === 'dm' ? await flags.getFlag('initiative.dm', 'shadow') : (c.settings?.initiative ?? 'shadow');
        return ['off', 'shadow', 'live'].includes(v) ? v : 'shadow';
    };

    // ── outcomes: did they take her up on it? feeds receptiveness ──
    async function resolve() {
        for (const r of await store.unresolvedInitiatives(180)) {
            const dm = r.chat_kind === 'dm';
            const first = await store.firstResponseSince({ chatId: r.chat_id, personId: r.person_id, since: r.sent_at, dm });
            const answered = !!first;
            const latency = first ? Math.round((ms(first) - ms(r.sent_at)) / 60000) : null;
            await store.resolveInitiative(r.id, { resolved: true, answered, latency_min: latency });
            const score = !answered ? 0 : latency <= 30 ? 1 : 0.7;
            if (dm && r.person_id != null) {
                const old = (await store.getReceptiveness(r.person_id)) ?? 0.6;
                await store.setReceptiveness(r.person_id, Math.round((old * 0.7 + score * 0.3) * 1000) / 1000);
            } else if (!dm) {
                const set = await store.chatSettings(r.chat_id);
                const old = Number.isFinite(Number(set.receptiveness)) ? Number(set.receptiveness) : 0.6;
                await store.setChatSettingById(r.chat_id, 'receptiveness', Math.round((old * 0.7 + score * 0.3) * 1000) / 1000);
            }
            counters.resolved++;
        }
    }

    // ── candidates, best first: dated follow-ups / promises, open threads, check-ins, quiet group, timer window ──
    async function gather(c, { nowMs, act, state, kind }) {
        const out = [];
        const today = parts(nowMs, tz);
        for (const s of await store.openThreadsFor(c.id)) {
            const threads = Array.isArray(s.open_threads) ? s.open_threads : [];
            for (let i = 0; i < threads.length; i++) {
                const t = threads[i]; const text = String(t?.text || '').trim();
                if (!text) continue;
                const key = `thread:${s.id}:${i}`;
                if (await store.hasInitiativeKey(key)) continue;
                const ageH = (nowMs - ms(s.ended)) / HOUR;
                if (t.due) {
                    const late = daysBetween(t.due, today.day);
                    if (late < 0 || late > 3) continue;                               // not yet due, or too stale
                    out.push({ kind: 'followup', priority: 1, key, reason: `A follow-up that came due ${late === 0 ? 'today' : `${late} day(s) ago`}: ${text}` });
                } else if (t.ariel && ageH >= 3 && ageH <= 24 * 5) {
                    out.push({ kind: 'promise', priority: 1, key, reason: `You said you would: ${text}` });
                } else if (ageH >= 3 && ageH <= 24 * 3) {
                    out.push({ kind: 'thread', priority: 2, key, reason: `An earlier conversation was left unfinished: ${text}` });
                }
            }
        }
        const lastHumanH = act.last_human ? (nowMs - ms(act.last_human)) / HOUR : Infinity;
        if (kind === 'dm' && lastHumanH >= 72 && lastHumanH <= 14 * 24) {
            out.push({ kind: 'checkin', priority: 3, key: null, reason: 'It has been a few days since you two talked. A light, natural check-in could fit, only if you have a real reason to say something.' });
        }
        if (kind === 'group' && lastHumanH >= 6 && lastHumanH <= 72 && act.h7 >= 8) {
            out.push({ kind: 'revive', priority: 4, key: null, reason: 'The group was lively and has gone quiet. Something light that fits this group might restart it, only if you have something to say.' });
        }
        const wkey = `${c.id}:${today.day}:${today.hour}`;
        if (WINDOWS.includes(today.hour) && !windowDone.has(wkey)) {
            windowDone.add(wkey);
            if (windowDone.size > 500) windowDone.delete(windowDone.values().next().value);
            out.push({ kind: 'thought', priority: 5, key: null, reason: 'Timer window. Reach out only if you genuinely have something worth saying: a callback to something you remember about them, a small observation, a thought. Otherwise say nothing.' });
        }
        return out.sort((a, b) => a.priority - b.priority);
    }

    async function pick(cands) {
        if (cands.length === 1 && cands[0].priority === 1) return 0;       // a due follow-up or a promise: no need to ask
        const r = await ai.chat({
            role: 'decide', maxTokens: 20, temperature: 0.3,
            messages: [
                { role: 'system', content: 'You decide whether Ariel should message someone first. Most of the time the answer is none. Choose a reason only if a real person would plausibly send that message now. Reply with one line: PICK: <number> or PICK: none' },
                { role: 'user', content: cands.map((x, i) => `${i + 1}. [${x.kind}] ${x.reason}`).join('\n') },
            ],
        });
        return parsePick(r?.text ?? r, cands.length);
    }

    async function evaluate(c) {
        const kind = c.kind === 'dm' ? 'dm' : 'group';
        const jid = kind === 'dm' ? c.settings?.send_jid : c.wa_jid;
        if (!jid || !isEnabled(jid, kind === 'dm')) return false;
        const mode = await modeFor(c);
        if (mode === 'off') return false;
        const nowMs = now();
        if (conv.isBusy(c.id)) return false;

        const act = await store.chatActivity(c.id);
        if (act.last_human && nowMs - ms(act.last_human) < LIMITS[kind].quietMin * 60_000) return false;   // they are mid-conversation
        const personId = kind === 'dm' ? c.person_id : null;
        let receptive;
        if (kind === 'dm') {
            if (personId == null) return false;
            if ((await store.getBoundaries(personId)).no_initiative) return false;                           // they asked her to stop
            const st = (await store.getPersonStates([personId])).get(personId);
            if (!st || nowMs - ms(st.last_interaction) > 14 * 24 * HOUR || Number(st.familiarity) < 0.1) return false;
            receptive = (await store.getReceptiveness(personId)) ?? 0.6;
        } else {
            if (act.h24 < 1 && !(act.last_human && nowMs - ms(act.last_human) > 6 * HOUR && nowMs - ms(act.last_human) < 72 * HOUR)) return false;
            receptive = Number.isFinite(Number(c.settings?.receptiveness)) ? Number(c.settings.receptiveness) : 0.6;
        }
        if (receptive < MIN_RECEPTIVE) return false;

        const hist = await store.initiativeHistory(c.id, 30);
        if (capReason(kind, hist, nowMs)) return false;
        const info = streakInfo(hist);
        const wait = waitReason(kind, info, nowMs);
        if (wait === 'blocked-until-addressed') {
            const back = await store.firstResponseSince({ chatId: c.id, personId, since: new Date(info.lastSentAt), dm: kind === 'dm', directOnly: true });
            if (!back) return false;                                       // stays quiet until they talk to her first
        } else if (wait) return false;

        const cands = await gather(c, { nowMs, act, state: info, kind });
        counters.candidates += cands.length;
        if (!cands.length) return false;
        const i = await pick(cands);
        if (i == null) return false;
        const chosen = cands[i];
        counters.picked++;

        const d = await conv.compose({ chatId: c.id, kind, jid, name: null, personId, reason: chosen.reason });
        if (d.busy) return false;
        const log1 = (status, text) => store.logInitiative({ chatId: c.id, personId, kind: chosen.kind, reason: chosen.reason, status, key: chosen.key, text });
        if (d.action !== 'reply' || !d.bubbles.length) {
            if (chosen.key) await log1('skipped', null);                   // she thought better of it: do not ask again
            counters.skipped++;
            return false;
        }
        const text = d.bubbles.join(' / ');
        if (mode === 'shadow') {
            await log1('shadow', text);
            counters.shadow++;
            log(`[ARIEL] initiative (shadow) ${chosen.kind} in chat ${c.id}: ${text.slice(0, 100)}`);
            return true;
        }
        let n = 0; let err = null;
        try { n = await send.say({ chatId: c.id, jid, bubbles: d.bubbles }); } catch (e) { err = e; }
        if (err && !n) {
            if (chosen.key) await log1('skipped', null);
            counters.skipped++;
            log(`[ARIEL] initiative send failed: ${String(err.message || err).slice(0, 120)}`);
            return false;
        }
        await log1('sent', text);
        conv.afterInitiative(c.id);
        counters.sent++;
        log(`[ARIEL] initiative SENT ${chosen.kind} in chat ${c.id}`);
        return true;
    }

    // ── the job ──
    async function tick() {
        if (String(process.env.ARIEL_INITIATIVE || '').toLowerCase() === 'off') return;
        counters.ticks++; counters.lastTick = now();
        await resolve();
        if (quietHours(now(), tz)) return;                                  // 23:00 to 07:00 Lagos: nothing starts
        let made = 0;
        for (const c of await store.initiativeChats()) {
            if (made >= 2) break;                                           // never more than two per tick, whatever the chats
            counters.chats++;
            try { if (await evaluate(c)) made++; }
            catch (e) { log(`[ARIEL] initiative skipped chat ${c.id}: ${String(e.message || e).slice(0, 140)}`); }
        }
    }

    return { tick, resolve, evaluate, counters };
}
