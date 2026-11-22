// The conversation engine: stored message -> gate -> wait for quiet -> one model call -> parse -> send.
// Stage 3 scope: replies to messages addressed to her (every DM message; in groups a tag, a quote of
// her, or her name). No memory yet. She may answer, react with an emoji, or stay silent.
import { buildContext } from './prompt.js';
import { parseReply, capEmoji, firstEmoji, repeatsRecent, stripFakeTags, inLoop } from './parse.js';
import { createBatcher } from './batcher.js';
import { withDefaults } from './config.js';
import { memoryHint } from './memory.js';
import { cheapScore } from './participation.js';
import { calmCaps } from './style.js';

const normalize = (r) => {
    if (typeof r === 'string') return r;
    const c = r?.text ?? r?.content ?? r?.message?.content ?? r?.choices?.[0]?.message?.content ?? '';
    return Array.isArray(c) ? c.map((p) => (typeof p === 'string' ? p : p?.text || '')).join('') : String(c || '');
};

// `.ariel reset` sets context_from on a chat: everything before it (messages and summaries) is ignored.
const dropOwnTail = (rows, n) => {
    let left = n; const out = [];
    for (let i = rows.length - 1; i >= 0; i--) { if (rows[i].person_id == null && left > 0) { left--; continue; } out.push(rows[i]); }
    return out.reverse();
};

export function createConversation({ store, ai, core, send, memory = null, social = null, participation = null, persona = null, feedback = null, stickers = null, relations = null, botTokens = () => [], config = {}, log = () => {}, now = Date.now, batcher = createBatcher(), rand = Math.random }) {
    const cfg = withDefaults(config);
    const nameRe = new RegExp(`\\b(${(core.aliases || [core.call_me || 'ariel']).map((a) => a.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|')})\\b`, 'i');
    const chats = new Map();         // chatId -> state
    const byJid = new Map();         // jid -> chatId (typing events arrive by jid)
    const rate = new Map();          // personId -> [timestamps]
    const counters = { stickers: 0, stickerOnly: 0, considered: 0, replies: 0, bubbles: 0, reacts: 0, silent: 0, errors: 0, stale: 0, limited: 0, followUps: 0, regenerated: 0, restarted: 0, joinChecks: 0, joinReplies: 0, joinReacts: 0, joinSkipped: 0 };
    const status = { lastError: null, lastReplyAt: null };
    let reqN = 0;

    function state(chatId, chat) {
        let st = chats.get(chatId);
        if (!st) {
            st = { chatId, kind: chat.kind, jid: chat.jid, name: chat.name || null, triggers: [], trigSeq: 0, running: false, memNotes: new Map(), observe: false, msgsSince: 0, settings: {}, settingsAt: 0, spoke: null, followRun: 0 };
            chats.set(chatId, st);
        }
        st.jid = chat.jid;
        if (chat.name) st.name = chat.name;
        byJid.set(chat.jid, chatId);
        return st;
    }

    function addressed(ev) {
        if (ev.chat.kind === 'dm') return true;
        const m = ev.op.meta || {};
        return !!(m.mentioned_ariel || m.quoted_ariel || nameRe.test(ev.op.body || ''));
    }

    function limited(personId) {
        const t = now();
        const arr = (rate.get(personId) || []).filter((x) => t - x < 60_000);
        arr.push(t);
        rate.set(personId, arr);
        return arr.length > cfg.ratePerMin;
    }

    // Back-and-forth: for a short while after she answers someone in a group, that person's next plain message
    // counts as talking to her (a real person would answer "how hot is it?" right after "Lagos is scorching").
    // It stops if they talk to or quote someone else, after a few in a row, or once the chat goes quiet.
    // ARIEL_FOLLOWUP=off turns it off.
    function followsUp(st, personId, ev) {
        if (String(process.env.ARIEL_FOLLOWUP || '').toLowerCase() === 'off') return false;
        if (st.kind !== 'group' || !st.spoke || personId == null) return false;
        if (now() - st.spoke.at > cfg.followUpMs || st.followRun >= cfg.maxFollowUps) return false;
        if (!st.spoke.persons.has(personId)) return false;
        const m = ev.op.meta || {};
        if ((ev.op.mentionJids || []).length && !m.mentioned_ariel) return false;        // tagged someone else
        if (ev.op.replyTo && !m.quoted_ariel) return false;                              // answering another message
        return true;
    }
    const rememberSpoke = (st, personIds) => { st.spoke = { at: now(), persons: new Set(personIds.filter((x) => x != null)) }; };

    // per-chat setting `involvement` = about one unprompted contribution per N messages (0 = never)
    const involvement = (st) => (Number.isFinite(Number(st.settings?.involvement)) ? Number(st.settings.involvement) : cfg.involvement);
    const joinOn = (st) => involvement(st) > 0 && String(process.env.ARIEL_JOIN || '').toLowerCase() !== 'off';
    function refreshSettings(st) {
        if (now() - st.settingsAt < 60_000 || !store.chatSettings) return;
        st.settingsAt = now();
        store.chatSettings(st.chatId).then((x) => { st.settings = x || {}; }).catch(() => {});
    }

    const waitFor = (st) => (st.kind === 'dm' ? cfg.batch.dmMs : cfg.batch.groupMs);
    const schedule = (st) => batcher.touch(st.chatId, waitFor(st), cfg.batch.capMs, () => turn(st));

    // Called by the hook for every newly stored message in an enabled chat.
    function onStored({ ev, out }) {
        const st = state(out.chatId, ev.chat);
        if (feedback) feedback.observe({ personId: out.personId, body: ev.op.body }).catch((e) => log(`[ARIEL] feedback skipped: ${String(e.message || e).slice(0, 100)}`));
        const ts = ev.op.ts instanceof Date ? ev.op.ts.getTime() : now();
        if (now() - ts > cfg.staleMs) { counters.stale++; return; }       // backlog after a restart
        const direct = addressed(ev);
        const follow = !direct && followsUp(st, out.personId, ev);
        if (!direct && !follow) {
            if (st.kind === 'group') {
                st.msgsSince++;
                refreshSettings(st);
                // far too early to consider joining in: she has not been quiet long enough
                if (participation && joinOn(st) && st.msgsSince >= Math.max(3, Math.floor(involvement(st) * 0.5))) st.observe = true;
            }
            if (st.observe || batcher.has(st.chatId)) schedule(st);        // chat is still moving: keep waiting
            return;
        }
        st.msgsSince++;
        if (follow) { st.followRun++; counters.followUps++; } else st.followRun = 0;
        if (limited(out.personId)) { counters.limited++; return; }
        st.triggers.push({ waId: ev.op.waId, personId: out.personId });
        st.trigSeq++;
        schedule(st);
    }

    // "typing…" from anyone in the chat pushes the wait back (still bounded by the cap).
    function onTyping(jid) {
        const id = byJid.get(jid);
        const st = id != null ? chats.get(id) : null;
        if (st && batcher.has(st.chatId)) schedule(st);
    }

    async function callModel(ctx, extra = '', lim = {}) {
        const r = await ai.chat({
            role: 'converse',
            messages: [{ role: 'system', content: ctx.system }, { role: 'user', content: ctx.user + extra }],
            maxTokens: cfg.maxOutputTokens,
            temperature: cfg.temperature,
        });
        return parseReply(normalize(r), { maxBubbles: lim.maxBubbles ?? cfg.maxBubbles, maxChars: lim.maxBubbleChars ?? cfg.maxBubbleChars });
    }

    // Memory for this turn: act on explicit remember / forget / update requests first (once per message),
    // then pull what she should know, only through the scope function. Memory trouble never blocks a reply.
    async function memoryFor(st, rows, live, rid, unprompted = false) {
        if (!memory) return { notes: [], memories: [] };
        const notes = [];
        try {
            const todo = [];
            if (unprompted) throw Object.assign(new Error('skip'), { skip: true });   // nobody asked her to remember anything
            for (const t of live) {
                if (st.memNotes.has(t.waId)) { notes.push(...st.memNotes.get(t.waId)); continue; }
                const row = rows.find((r) => r.wa_message_id === t.waId);
                const hint = row ? memoryHint(row.body) : null;
                if (hint) todo.push({ personId: t.personId, name: row.name, body: row.body, hint, waId: t.waId });
                else st.memNotes.set(t.waId, []);
            }
            if (todo.length) {
                for (const m of todo) {
                    const r = await memory.handleExplicit({ chat: { id: st.chatId, kind: st.kind }, msgs: [m] });
                    st.memNotes.set(m.waId, r.notes);
                    notes.push(...r.notes);
                }
                if (st.memNotes.size > 200) st.memNotes.delete(st.memNotes.keys().next().value);
                log(`[ARIEL] ${rid} memory: ${notes.length} change(s)`);
            }
        } catch (e) { if (!e.skip) log(`[ARIEL] ${rid} memory write skipped: ${String(e.message || e).slice(0, 160)}`); }
        let memories = [];
        try {
            const recent = rows.slice(-30);
            const ids = [...new Set([...recent.map((r) => r.person_id), ...live.map((t) => t.personId)].filter((x) => x != null))];
            const q = [...live.slice(-3).map((t) => rows.find((r) => r.wa_message_id === t.waId)?.body), rows[rows.length - 1]?.body]
                .filter(Boolean).join(' ').slice(0, 400);
            memories = await memory.retrieve({ chatId: st.chatId, presentPersonIds: ids, queryText: q });
        } catch (e) { log(`[ARIEL] ${rid} memory read skipped: ${String(e.message || e).slice(0, 160)}`); }
        return { notes, memories };
    }

    async function floorOf(chatId) {
        try { const t = Date.parse((await store.chatSettings?.(chatId))?.context_from); return Number.isFinite(t) ? t : 0; } catch { return 0; }
    }
    const afterFloor = (rows, floor, key = 'created_at') => (floor ? rows.filter((r) => new Date(r[key]).getTime() >= floor) : rows);

    async function draft(st, triggers, rid, { unprompted = false } = {}) {
        const floor = await floorOf(st.chatId);
        const rows = afterFloor(await store.recentMessages(st.chatId, cfg.recentLimit), floor);
        const present = new Set(rows.map((r) => r.wa_message_id));
        const live = triggers.filter((t) => present.has(t.waId));          // deleted before she answered -> gone
        if (!live.length) return null;
        const { notes, memories } = await memoryFor(st, rows, live, rid, unprompted);
        let summaries = [];
        try { summaries = store.latestSummaries ? afterFloor(await store.latestSummaries(st.chatId, 2), floor, 'ended') : []; }
        catch (e) { log(`[ARIEL] ${rid} summaries skipped: ${String(e.message || e).slice(0, 120)}`); }
        let socialInfo = null;
        if (social) {
            try {
                const ids = [...new Set([...rows.slice(-30).map((r) => r.person_id), ...live.map((t) => t.personId)].filter((x) => x != null))];
                socialInfo = await social.describe({ chatId: st.chatId, personIds: ids });
                if (relations) socialInfo.family = await relations.describe({ personIds: ids, chatJid: st.kind === 'group' ? st.jid : null });
            } catch (e) { log(`[ARIEL] ${rid} social skipped: ${String(e.message || e).slice(0, 120)}`); }
        }
        let pers = null;
        if (persona) { try { pers = await persona.get(); } catch { /* she keeps the defaults */ } }
        const lim = pers?.limits || {};
        const shape = (x) => { x.bubbles = calmCaps(capEmoji(stripFakeTags(x.bubbles, ctx.people), lim.maxEmoji ?? cfg.maxEmoji), lim.maxShouting ?? 1); return x; };   // caps are enforced in code
        const mk = (rs) => buildContext({
            core, rows: rs, chat: { kind: st.kind, name: st.name }, triggerWaIds: live.map((t) => t.waId),
            now: new Date(now()), budgetTokens: cfg.tokenBudget, tz: cfg.tz, botTokens: botTokens(),
            memories, notes, summaries, social: socialInfo, unprompted, self: pers?.text || '',
        });
        const ctx = mk(rows);
        let d = await callModel(ctx, '', lim);
        if (d.action === 'reply') {
            shape(d);
            if (repeatsRecent(d.bubbles, ctx.ariel.slice(-cfg.repeatWindow))) {
                counters.regenerated++;
                const sample = ctx.ariel.slice(-3).map((b) => `"${b.slice(0, 60)}"`).join(', ');
                log(`[ARIEL] ${rid} draft repeated her recent wording, regenerating once`);
                const again = await callModel(ctx, `\n\nNote: your draft reused wording from your recent messages (${sample}). Say it differently, or stay silent if there is nothing new.`, lim);
                if (again.action === 'reply') shape(again);
                d = again;
                // still repeating after the redo: say nothing rather than send the same line again
                if (d.action === 'reply' && repeatsRecent(d.bubbles, ctx.ariel.slice(-cfg.repeatWindow))) { counters.repeatDropped = (counters.repeatDropped || 0) + 1; d = { ...d, action: 'silent', bubbles: [] }; }
            }
            // Stuck in the same move for three replies in a row: she stops seeing her own recent lines and changes direction.
            if (d.action === 'reply' && inLoop(d.bubbles, ctx.ariel)) {
                counters.loopBroken = (counters.loopBroken || 0) + 1;
                log(`[ARIEL] ${rid} loop detected, redrafting without her own recent lines`);
                const again = await callModel(mk(dropOwnTail(rows, 4)), '\n\nNote: your last few replies in this chat have all been the same kind of message. Do not continue that. React to what they just said, say something different, or stay silent.', lim);
                if (again.action === 'reply') shape(again);
                d = again;
                if (d.action === 'reply' && inLoop(d.bubbles, ctx.ariel)) { counters.repeatDropped = (counters.repeatDropped || 0) + 1; d = { ...d, action: 'silent', bubbles: [] }; }
            }
        }
        // resolve #n to a WhatsApp message id
        let quote = d.replyRef != null ? ctx.refs.get(d.replyRef) || null : null;
        const own = new Set(ctx.lines.filter((l) => l.own).map((l) => l.waId));
        if (quote && own.has(quote)) quote = null;
        const latest = ctx.lines[ctx.lines.length - 1]?.waId || null;
        const lastTrig = live[live.length - 1].waId;
        if (!quote && st.kind === 'group' && lastTrig !== latest) quote = lastTrig;  // others spoke since: say who it is for
        // Her reply quotes the message she is answering (quoteChance, default always). Only the first bubble quotes
        // (see send.js) and a sticker added after the text never does. Reacts and silence never get here.
        if (!quote && d.action === 'reply' && rand() < (cfg.quoteChance[st.kind] ?? 0)) quote = lastTrig;
        return { ...d, quote, lastTrig };
    }

    async function deliver(st, d, rid) {
        if (d.action === 'silent' || !d.bubbles.length) { counters.silent++; log(`[ARIEL] ${rid} silent`); return; }
        if (d.action === 'react') {
            const emoji = firstEmoji(d.bubbles[0]);
            if (!emoji) { counters.silent++; return; }
            const ok = await send.react({ chatId: st.chatId, jid: st.jid, emoji, targetWaId: d.quote || d.lastTrig });
            if (ok) { counters.reacts++; st.msgsSince = 0; log(`[ARIEL] ${rid} reacted ${emoji}`); } else counters.silent++;
            return;
        }
        // Stickers (rolled in code so the rates are exact): some short replies become just a sticker, some get one added.
        let mode = 'none', tag = null;
        if (stickers && send.sticker) {
            const sc = cfg.sticker; const roll = rand(); const said = d.bubbles.join(' ');
            if (roll < sc.only) { if (said.length <= sc.onlyMaxChars) mode = 'only'; }
            else if (roll < sc.only + sc.alongside) mode = 'alongside';
            if (mode !== 'none') {
                try { tag = await stickers.pick({ text: said, mode }); } catch (e) { log(`[ARIEL] ${rid} sticker pick skipped: ${String(e.message || e).slice(0, 100)}`); }
                if (!tag) mode = 'none';
            }
        }
        if (mode === 'only' && await send.sticker({ chatId: st.chatId, jid: st.jid, tag, quoteWaId: d.quote })) {
            counters.stickers++; counters.stickerOnly++; counters.replies++; status.lastReplyAt = now(); st.msgsSince = 0;
            log(`[ARIEL] ${rid} sent sticker ${tag}`);
            return true;
        }
        const n = await send.say({ chatId: st.chatId, jid: st.jid, bubbles: d.bubbles, quoteWaId: d.quote });
        if (mode !== 'none' && tag && await send.sticker({ chatId: st.chatId, jid: st.jid, tag, afterText: true })) counters.stickers++;
        counters.replies++; counters.bubbles += n; status.lastReplyAt = now(); st.msgsSince = 0;
        log(`[ARIEL] ${rid} sent ${n} bubble(s)`);
        return true;
    }

    // Nobody spoke to her. Cheap rules, then the small `decide` model, then (maybe) the normal main call.
    async function participate(st, rid) {
        const rows = await store.recentMessages(st.chatId, 30);
        const last = rows[rows.length - 1];
        if (!last || last.person_id == null) return;
        const per = involvement(st);
        const sinceHer = (() => { let n = 0; for (let i = rows.length - 1; i >= 0 && rows[i].person_id != null; i--) n++; return n; })();
        const ownAt = [...rows].reverse().find((r) => r.person_id == null)?.created_at;
        if (ownAt && now() - new Date(ownAt).getTime() < 3 * 60_000) { counters.joinSkipped++; return; }          // she just spoke
        if (sinceHer < Math.round(per * (0.6 + Math.random() * 0.7))) { counters.joinSkipped++; return; }       // about 1 in N messages
        let interests = [];
        try { interests = (await store.getArielState?.())?.interests || []; } catch { /* none yet */ }
        const cheap = cheapScore(rows, { interests });
        if (cheap.score < 2 && !(cheap.score >= 1 && sinceHer >= per * 2)) { counters.joinSkipped++; return; }
        counters.joinChecks++;
        const d = await participation.decide({ rows, reasons: cheap.reasons, fallbackRow: cheap.target || last });
        log(`[ARIEL] ${rid} join check (score ${cheap.score}): ${d.action}`);
        if (d.action === 'silent' || !d.row) return;
        if (d.action === 'react') {
            const ok = await send.react({ chatId: st.chatId, jid: st.jid, emoji: d.emoji, targetWaId: d.row.wa_message_id });
            if (ok) { counters.joinReacts++; st.msgsSince = 0; }
            return;
        }
        const out = await draft(st, [{ waId: d.row.wa_message_id, personId: d.row.person_id }], rid, { unprompted: true });
        if (out && out.action === 'reply' && out.bubbles.length) {
            counters.joinReplies++;
            if (await deliver(st, out, rid)) rememberSpoke(st, [d.row.person_id]);
        } else counters.silent++;
    }

    async function turn(st) {
        if (st.running) return;                       // the running turn re-schedules itself when it ends
        st.running = true;
        const rid = `r${++reqN}`;
        try {
            let restarted = false;
            for (;;) {
                const triggers = st.triggers.splice(0);
                if (!triggers.length) {
                    if (st.observe && participation) { st.observe = false; await participate(st, rid); }
                    break;
                }
                st.observe = false;
                counters.considered++;
                const seq = st.trigSeq;
                const d = await draft(st, triggers, rid);
                if (st.trigSeq !== seq && !restarted) {   // another message for her landed while she was thinking
                    restarted = true; counters.restarted++;
                    st.triggers.unshift(...triggers);
                    continue;
                }
                const spoke = d ? await deliver(st, d, rid) : false;
                if (spoke) rememberSpoke(st, triggers.map((t) => t.personId));
                if (social) {                                    // she answered them: that counts as an interaction
                    const per = new Map();
                    for (const t of triggers) if (t.personId != null) per.set(t.personId, (per.get(t.personId) || 0) + 1);
                    for (const [pid, n] of per) social.recordInteraction(pid, n).catch((e) => log(`[ARIEL] ${rid} social save failed: ${String(e.message || e).slice(0, 100)}`));
                }
                break;
            }
        } catch (e) {
            counters.errors++;
            status.lastError = String(e?.message || e).slice(0, 300);
            log(`[ARIEL] ${rid} failed, staying silent: ${status.lastError}`);        // never a canned error line
        } finally {
            st.running = false;
            if (st.triggers.length) schedule(st);
        }
    }

    // ── proactive messages (stage 7): she writes the opening line, initiative.js decides whether to send ──
    // Returns { busy: true } if a conversation is in progress, else { action, bubbles }.
    async function compose({ chatId, kind, jid, name, personId, reason }) {
        const st = state(chatId, { kind, jid, name });
        if (st.running || batcher.has(chatId)) return { busy: true };
        const rid = `i${++reqN}`;
        const floor = await floorOf(chatId);
        const rows = afterFloor(await store.recentMessages(chatId, cfg.recentLimit), floor);
        const ids = [...new Set([personId, ...rows.slice(-30).map((r) => r.person_id)].filter((x) => x != null))];
        let memories = []; let summaries = []; let socialInfo = null;
        try { if (memory) memories = await memory.retrieve({ chatId, presentPersonIds: ids, queryText: String(reason).slice(0, 300) }); } catch (e) { log(`[ARIEL] ${rid} memory read skipped: ${String(e.message || e).slice(0, 120)}`); }
        try { summaries = store.latestSummaries ? afterFloor(await store.latestSummaries(chatId, 2), floor, 'ended') : []; } catch { /* none */ }
        try {
            if (social) {
                socialInfo = await social.describe({ chatId, personIds: ids });
                if (relations) socialInfo.family = await relations.describe({ personIds: ids, chatJid: kind === 'group' ? jid : null });
            }
        } catch { /* none */ }
        let pers = null;
        if (persona) { try { pers = await persona.get(); } catch { /* defaults */ } }
        const lim = pers?.limits || {};
        const shape = (x) => { x.bubbles = calmCaps(capEmoji(stripFakeTags(x.bubbles, ctx.people), lim.maxEmoji ?? cfg.maxEmoji), lim.maxShouting ?? 1); return x; };
        const ctx = buildContext({
            core, rows, chat: { kind, name }, triggerWaIds: [], now: new Date(now()), budgetTokens: cfg.tokenBudget, tz: cfg.tz,
            botTokens: botTokens(), memories, notes: [], summaries, social: socialInfo, initiative: reason, self: pers?.text || '',
        });
        let d = await callModel(ctx, '', lim);
        if (d.action === 'reply') {
            shape(d);
            if (repeatsRecent(d.bubbles, ctx.ariel.slice(-cfg.repeatWindow))) {
                counters.regenerated++;
                d = await callModel(ctx, '\n\nNote: that reused wording from your recent messages. Say it differently, or stay silent.', lim);
                if (d.action === 'reply') shape(d);
            }
        }
        log(`[ARIEL] ${rid} initiative drafted: ${d.action}`);
        return d;
    }
    const isBusy = (chatId) => { const st = chats.get(chatId); return !!st && (st.running || batcher.has(chatId)); };
    const afterInitiative = (chatId) => { const st = chats.get(chatId); if (st) st.msgsSince = 0; };

    return { onStored, onTyping, compose, isBusy, afterInitiative, counters, status };
}
