// Connects the testable pieces (hook / ingest / admin) to the live bot.
// This is the only Ariel file that imports from the rest of bot/. Everything
// is built lazily, on the first message, so a missing database setting can
// never stop the bot from booting.
import { lidMap, groupMetaCache, _getGroupPrefix } from '../lib/cache.js';
import { botState } from '../lib/state.js';
import { _getDB } from '../lib/db.js';
import { PHONE_NUMBER, KING_NUMBER } from '../lib/env.js';
import { normJid, phoneOf, isLid, isPhoneJid } from './ids.js';
import { createHook } from './hook.js';
import { createIngest } from './ingest.js';
import { createAdmin } from './admin.js';
import { createPgStore } from './store/pg.js';
import { withChatCache } from './store/cached.js';
import { createConversation } from './conversation.js';
import { withDefaults } from './config.js';
import { createSender } from './send.js';
import { createMemory } from './memory.js';
import { createMaintStore } from './store/maint.js';
import { createSummariser } from './summarise.js';
import { createHousekeeping } from './housekeeping.js';
import { createJobs } from './jobs.js';
import { createSocial } from './social.js';
import { createParticipation } from './participation.js';
import { createStickerPicker } from './stickers.js';
import { createRelations, loadBase } from './relations.js';
import { createInitiative } from './initiative.js';
import { createSelfStore } from './store/self.js';
import { createMood } from './mood.js';
import { createFeedback } from './feedback.js';
import { createPersona } from './persona.js';
import { createReflection } from './reflect.js';
import { createSelfCommands } from './selfcmds.js';
import { readFileSync } from 'node:fs';

const BOT_JID = PHONE_NUMBER ? `${PHONE_NUMBER}@s.whatsapp.net` : null;
const META_TTL_MS = 300_000;                 // same 5 min as the rest of the bot
const say = (...a) => console.log(...a);

let built = null;                            // { hook, ingest, admin } | { off: true }
const extraBotIds = new Set();               // the bot's own jid / @lid, learned from the socket
let lastSock = null;
const rawMsgs = new Map();                   // waId -> raw WhatsApp message, for quoting and reacting (last 400)
const presenceSock = new WeakSet();
const subscribed = new Set();
let convRef = null;
let memRef = null;
let memTimer = null;
let jobsRef = null;
let maintRef = null;
let houseRef = null;
let sumRef = null;
let socialRef = null;
let storeRef = null;
let initRef = null;
let selfRef = null;
let feedbackRef = null;
let personaRef = null;
let reflectRef = null;
let moodRef = null;
let selfCmds = null;

function learnBot(sock) {
    lastSock = sock;
    listenTyping(sock);
    for (const j of [sock?.user?.id, sock?.user?.lid]) {
        const n = normJid(j);
        if (n) extraBotIds.add(n);
    }
}

// "typing…" from people in a chat makes her wait a little longer before answering.
function listenTyping(sock) {
    if (!sock?.ev || presenceSock.has(sock)) return;
    presenceSock.add(sock);
    sock.ev.on('presence.update', ({ id, presences }) => {
        try {
            for (const [who, p] of Object.entries(presences || {})) {
                if ((p?.lastKnownPresence === 'composing' || p?.lastKnownPresence === 'recording') && !isBot(who)) {
                    convRef?.onTyping(id);
                    break;
                }
            }
        } catch { /* typing is a nicety */ }
    });
}

function remember(msg) {
    const id = msg?.key?.id;
    if (!id) return;
    rawMsgs.set(id, msg);
    if (rawMsgs.size > 400) rawMsgs.delete(rawMsgs.keys().next().value);
}

// `jid` may be a jid, a @lid or a bare identity value (digits).
function isBot(jid) {
    if (!jid) return false;
    if (jid === PHONE_NUMBER) return true;
    const n = normJid(jid);
    if (!n) return false;
    if (n === BOT_JID || extraBotIds.has(n)) return true;
    if (phoneOf(n) === PHONE_NUMBER) return true;
    const mapped = normJid(lidMap[n]);
    return !!mapped && (mapped === BOT_JID || phoneOf(mapped) === PHONE_NUMBER);
}

function isEnabled(chatJid, isDM) {
    if (isDM) return botState.chatDmOn === true;
    return botState.groupPools?.[chatJid]?.chat === true
        || (botState.silentPoolOn === true && (botState.silentChatGroups || []).includes(chatJid));
}

// Work Mode asks this before it may be switched on (normal chat must already be enabled).
export function isChatEnabled(chatJid, isDM) { return isEnabled(chatJid, isDM); }

// Other ids we know for one jid: lid <-> phone, from the bot's own map and from
// Baileys' signal store when this version has one.
async function altIds(sock, raw) {
    const n = normJid(raw);
    if (!n) return [];
    const out = [];
    if (lidMap[n]) out.push(lidMap[n]);
    if (isPhoneJid(n)) {
        for (const [lid, pn] of Object.entries(lidMap)) if (normJid(pn) === n) out.push(lid);
    }
    const map = sock?.signalRepository?.lidMapping;
    try {
        if (isLid(n) && typeof map?.getPNForLID === 'function') out.push(await map.getPNForLID(n));
        if (isPhoneJid(n) && typeof map?.getLIDForPN === 'function') out.push(await map.getLIDForPN(n));
    } catch { /* optional feature of newer Baileys */ }
    return out.filter(Boolean);
}

// Group member list, cached like the rest of the bot (groupMetaCache, 5 min).
async function groupParticipants(sock, jid) {
    let c = groupMetaCache[jid];
    if (!c || Date.now() - c.ts > META_TTL_MS) {
        c = { meta: await sock.groupMetadata(jid), ts: Date.now() };
        groupMetaCache[jid] = c;
    }
    const parts = c.meta?.participants || [];
    for (const p of parts) {               // teach the shared lid map while we're here
        const pn = p.phoneNumber || (isPhoneJid(normJid(p.id)) ? p.id : null);
        const lid = p.lid || (isLid(normJid(p.id)) ? p.id : null);
        if (pn && lid && !lidMap[lid]) lidMap[lid] = pn;
    }
    return parts;
}

async function getPrefix(chatJid) {
    return _getGroupPrefix(await _getDB(), chatJid);
}

function build() {
    if (built) return built;
    if (String(process.env.ARIEL_INGEST || '').toLowerCase() === 'off') {
        say('[ARIEL] ingest disabled (ARIEL_INGEST=off)');
        return (built = { off: true });
    }
    if (!process.env.ARIEL_DB_URL && !process.env.SUPABASE_DB_URL) {
        say('[ARIEL] ingest disabled: SUPABASE_DB_URL is not set');
        return (built = { off: true });
    }
    return (built = (async () => {
        const db = await import('./db.js');
        const pgStore = createPgStore({ query: db.query, tx: db.tx });
        // Chat history cache (ARIEL_CACHE=off turns it off; ARIEL_CACHE_TTL_S changes how long rows are kept, default 30).
        const cacheOn = String(process.env.ARIEL_CACHE || '').toLowerCase() !== 'off';
        const ttlS = Number(process.env.ARIEL_CACHE_TTL_S);
        const store = cacheOn ? withChatCache(pgStore, Number.isFinite(ttlS) && ttlS > 0 ? { ttlMs: ttlS * 1000 } : {}) : pgStore;
        const ingest = createIngest({ store, isBot, log: say });

        // Conversation (stage 3). If the reply side can't start, ingest keeps working.
        let conv = null;
        if (String(process.env.ARIEL_REPLY || '').toLowerCase() === 'off') {
            say('[ARIEL] replies disabled (ARIEL_REPLY=off)');
        } else {
            try {
                const core = JSON.parse(readFileSync(new URL('./core.json', import.meta.url), 'utf8'));
                const mod = await import('./providers/default.js');
                const ai = mod.ai || mod.default;
                if (!ai || typeof ai.chat !== 'function') throw new Error('providers/default.js must export `ai` with ai.chat()');
                // Her `.take` sticker library (Supabase). ARIEL_STICKERS=off turns sticker use off.
                let sendSticker = null, stickers = null;
                if (String(process.env.ARIEL_STICKERS || '').toLowerCase() !== 'off') {
                    try {
                        const stk = await import('../chat/stickers.js');
                        let man = { at: 0, tags: {} };
                        const listTags = async () => {
                            if (Date.now() - man.at > 5 * 60_000) man = { at: Date.now(), tags: await stk._loadArielManifest() };
                            return man.tags;
                        };
                        sendSticker = (jid, tag, quoted) => stk._sendArielSticker(lastSock, jid, tag, quoted);
                        stickers = createStickerPicker({ ai, listTags, log: say });
                    } catch (e) { say(`[ARIEL] stickers are off: ${e.message}`); }
                }
                const send = createSender({
                    getSock: () => lastSock, getRaw: (id) => rawMsgs.get(id) || null,
                    store, cfg: withDefaults(), sendSticker, log: say,
                });
                const memory = createMemory({
                    store, ai, log: say,
                    ownerValues: () => (KING_NUMBER ? [String(KING_NUMBER), `${KING_NUMBER}@s.whatsapp.net`] : []),
                });
                memTimer = setInterval(() => memory.backfill().catch(() => {}), 10 * 60_000);
                memTimer.unref?.();
                memRef = memory;
                const social = createSocial({ store, log: say });
                socialRef = social; storeRef = store;
                const participation = createParticipation({ ai, log: say, botTokens: () => [PHONE_NUMBER, ...[...extraBotIds].map((j) => j.split('@')[0])].filter(Boolean) });
                // Stage 8: identity evolution, mood, feedback. ARIEL_SELF=off keeps her exactly as before it.
                const selfOn = String(process.env.ARIEL_SELF || '').toLowerCase() !== 'off';
                let persona = null, feedback = null, mood = null, reflection = null;
                const selfCfg = withDefaults();
                if (selfOn) {
                    const selfStore = createSelfStore({ query: db.query, tx: db.tx });
                    mood = createMood({ self: selfStore, log: say });
                    feedback = createFeedback({ self: selfStore, cfg: selfCfg, log: say });
                    persona = createPersona({ self: selfStore, cfg: selfCfg, core, log: say });
                    reflection = createReflection({ self: selfStore, ai, cfg: selfCfg, core, log: say });
                    selfRef = selfStore; feedbackRef = feedback; personaRef = persona; reflectRef = reflection; moodRef = mood;
                    selfCmds = createSelfCommands({ self: selfStore, feedback, persona, reflection, mood });
                } else say('[ARIEL] self-evolution disabled (ARIEL_SELF=off)');
                // Fixed family facts + ranks (config/relations.json). ARIEL_RELATIONS=off turns this off.
                let relations = null;
                if (String(process.env.ARIEL_RELATIONS || '').toLowerCase() !== 'off') {
                    try {
                        const base = loadBase(JSON.parse(readFileSync(new URL('../../config/relations.json', import.meta.url), 'utf8')));
                        const rankOf = async (phone, groupJid) => {
                            const { getRank } = await import('../commands.js');
                            return getRank(await _getDB(), `${phone}@s.whatsapp.net`, [], true, groupJid);
                        };
                        relations = createRelations({ base, store, rankOf, log: say });
                        say(`[ARIEL] relations: ${base.length} fixed relation(s) loaded`);
                    } catch (e) { say(`[ARIEL] relations are off: ${e.message}`); }
                }
                conv = createConversation({
                    store, ai, core, send, memory, social, participation, persona, feedback, stickers, relations, log: say,
                    botTokens: () => [PHONE_NUMBER, ...[...extraBotIds].map((j) => j.split('@')[0])].filter(Boolean),
                });
                convRef = conv;
                // Background work (stage 5): summaries, memory upkeep, raw-message cleanup.
                const cfg = withDefaults();
                const maint = createMaintStore({ query: db.query, tx: db.tx });
                const summariser = createSummariser({ maint, store, ai, cfg, social: socialRef, mood, log: say });
                const house = createHousekeeping({ maint, ai, cfg, log: say });
                initRef = createInitiative({ store, flags: maint, ai, conv, send, isEnabled, log: say });
                jobsRef = createJobs({
                    maint, cfg, log: say,
                    handlers: {
                        initiative_tick: () => initRef.tick(), segment_close: summariser.segmentClose, summarise: summariser.summarise, consolidate: house.consolidate, cleanup: house.cleanup,
                        ...(selfOn ? {
                            style_review: async () => { await feedback.review(); persona.refresh(); },
                            reflect: async () => { await reflection.run(); persona.refresh(); },
                        } : {}),
                    },
                });
                maintRef = maint; houseRef = house; sumRef = summariser;
                if (String(process.env.ARIEL_JOBS || '').toLowerCase() === 'off') say('[ARIEL] background jobs disabled (ARIEL_JOBS=off)');
                else jobsRef.start();
                say('[ARIEL] conversation engine ready');
            } catch (e) {
                say(`[ARIEL] replies are off: ${e.message}`);
            }
        }
        const onStored = conv ? (x) => {
            remember(x.msg);
            if (x.ev.chat.kind === 'dm' && !subscribed.has(x.ev.chat.jid)) {
                subscribed.add(x.ev.chat.jid);
                Promise.resolve(lastSock?.presenceSubscribe?.(x.ev.chat.jid)).catch(() => {});
            }
            conv.onStored(x);
        } : null;

        const hook = createHook({
            onStored,
            ingest, isEnabled, isBot, getPrefix, altIds, groupParticipants,
            chatName: (jid) => groupMetaCache[jid]?.meta?.subject || null,
            log: say,
        });
        const admin = createAdmin({
            query: db.query, hookStatus: hook.status, counters: ingest.counters,
            enabledInfo: () => ({
                dmOn: botState.chatDmOn === true,
                groupsOn: Object.values(botState.groupPools || {}).filter((p) => p?.chat === true).length,
            }),
            commands: {
                initiative: async (arg, ctx) => {
                    if (!storeRef || !maintRef) return '🌱 initiative is off (replies are off)';
                    const a = String(arg || '').trim().toLowerCase();
                    const ok = ['off', 'shadow', 'live'];
                    if (a.startsWith('dm ')) {
                        const m = a.slice(3).trim();
                        if (!ok.includes(m)) return '🌱 _Usage: .ariel initiative dm off | shadow | live_';
                        await maintRef.setFlag('initiative.dm', m);
                        return m === 'live' ? '🌱 DMs: she may now start conversations for real (within her caps, never at night).' : `🌱 DMs: initiative is ${m}${m === 'shadow' ? ' (logged only, nothing is sent)' : ''}.`;
                    }
                    if (ok.includes(a)) {
                        if (!ctx?.isGroup) return '🌱 Use this inside a group (it sets that group), or `.ariel initiative dm off|shadow|live` for DMs.';
                        const set = await storeRef.setChatSetting(ctx.jid, 'initiative', a);
                        if (!set) return '🌱 This group is not stored yet (turn on .chat first, then send a few messages).';
                        return a === 'live' ? '🌱 Live here: she may start conversations in this group (max 2 a day, never 23:00-07:00).' : a === 'shadow' ? '🌱 Shadow here: she only logs what she would have said. See .ariel initiatives.' : '🌱 Off here.';
                    }
                    const c = initRef?.counters;
                    const dm = await maintRef.getFlag('initiative.dm', 'shadow');
                    return `🌱 *Initiative* DMs: ${dm}. Ticks ${c?.ticks || 0}, picked ${c?.picked || 0}, shadow ${c?.shadow || 0}, sent ${c?.sent || 0}, skipped ${c?.skipped || 0}.\n_.ariel initiative off | shadow | live (in a group) · .ariel initiative dm off | shadow | live · .ariel initiatives_`;
                },
                initiatives: async () => {
                    if (!storeRef) return '🌱 initiative is off';
                    const rows = await storeRef.recentInitiatives(8);
                    if (!rows.length) return '🌱 Nothing yet. She only speaks first after a real reason, and most ticks end with nothing.';
                    return ['🌱 *Recent initiatives*', ...rows.map((r) => {
                        const where = r.chat_kind === 'dm' ? 'DM' : 'group';
                        const text = String(r.outcome?.text || '').slice(0, 110);
                        const res = r.outcome?.resolved ? (r.outcome.answered ? ' ✓answered' : ' ✗ignored') : '';
                        return `#${r.id} ${r.status}${res} · ${where} · ${r.kind}${text ? `: "${text}"` : ''}`;
                    })].join('\n');
                },
                join: async (arg, ctx) => {
                    if (!storeRef) return '💬 replies are off';
                    if (!ctx?.isGroup) return '💬 Use .ariel join inside a group. It sets how often she joins in unprompted there.';
                    const a = String(arg || '').trim();
                    if (a) {
                        const n = a === 'off' ? 0 : a === 'on' ? 25 : Number(a);
                        if (!Number.isFinite(n) || n < 0 || n > 500) return '💬 _Usage: .ariel join off | on | <messages, e.g. 25>_';
                        const ok = await storeRef.setChatSetting(ctx.jid, 'involvement', n);
                        if (!ok) return '💬 This group is not stored yet (turn on .chat first, then send a few messages).';
                        return n === 0 ? '💬 She will only answer when spoken to here.' : `💬 She may join in about once every ${n} messages here (when she has something to add).`;
                    }
                    return '💬 _Usage: .ariel join off | on | <n>_  (she joins in about once per n messages when she has something to add; default 25, off = only when spoken to)';
                },
                reset: async (_arg, ctx) => {
                    if (!storeRef) return '🧹 replies are off';
                    if (!ctx?.jid) return '🧹 Use .ariel reset inside the chat you want to reset.';
                    const ok = await storeRef.setChatSetting(ctx.jid, 'context_from', new Date().toISOString());
                    if (!ok) return '🧹 This chat is not stored yet (turn on .chat first, then send a few messages).';
                    return '🧹 Fresh start here: from now she ignores everything said in this chat before this moment (messages and summaries). Memories stay: ask her to forget those by name.';
                },
                ...(selfCmds || {}),
                jobs: async () => {
                    if (!maintRef) return '🗂 background jobs are off';
                    const j = await maintRef.jobSummary();
                    const c = j.counts;
                    const out = [`🗂 *Jobs* queued ${c.queued || 0} · running ${c.running || 0} · done ${c.done || 0} · dead ${c.dead || 0}`];
                    for (const d of j.dead) out.push(`☠ #${d.id} ${d.kind} (${d.attempts}x): ${String(d.last_error || '').slice(0, 120)}`);
                    if (jobsRef?.status.lastError) out.push(`last error: ${jobsRef.status.lastError}`);
                    return out.join('\n');
                },
                cleanup: async (arg) => {
                    if (!maintRef) return '🗂 background jobs are off';
                    const a = String(arg || '').trim();
                    if (a === 'live') { await maintRef.setFlag('cleanup.live', true); return '🗑 Cleanup is now LIVE. Tonight it will delete verified raw messages past retention.'; }
                    if (a === 'dry') { await maintRef.setFlag('cleanup.live', false); return '🗑 Cleanup is back to dry-run (counts only).'; }
                    const live = (await maintRef.getFlag('cleanup.live', false)) === true;
                    const days = await maintRef.getFlag('cleanup.retention_days', 14);
                    const n = await maintRef.cleanupCount({ retentionDays: Math.max(3, Number(days) || 14), keepLatest: 200 });
                    return `🗑 Cleanup is ${live ? 'LIVE' : 'in dry-run'}. ${n} verified message(s) are past ${days} days and would go (the newest 200 per chat always stay).\n_.ariel cleanup live | dry_`;
                },
            },
            extraLines: async () => {
                if (!conv) return ['💬 replies: off'];
                const c = conv.counters;
                const out = [`💬 replies: ${c.replies} sent (${c.bubbles} bubbles), ${c.reacts} reacts, ${c.silent} silent, ${c.errors} errors`];
                if (store.cache) { const k = store.cache.counters; const t = k.hits + k.misses; out.push(`⚡ chat cache: ${k.hits}/${t} reads from memory${t ? ` (${Math.round((100 * k.hits) / t)}%)` : ''}, ${k.invalidated} refreshed on new messages`); }
                if (memRef) { const m = memRef.counters; out.push(`🧩 memory: ${m.saved} saved, ${m.updated} updated, ${m.forgotten} forgotten, ${m.retrieved} recalled${m.embedFailed ? `, ${m.embedFailed} embed fails` : ''}`); }
                if (initRef) { const i = initRef.counters; if (i.shadow || i.sent || i.picked) out.push(`🌱 initiative: ${i.shadow} shadow, ${i.sent} sent, ${i.skipped} skipped`); }
                if (socialRef) { const z = socialRef.counters; out.push(`🤝 social: ${z.interactions} interactions, ${z.signals} relationship signals, ${z.labelled} labelled`); }
                { const c2 = conv.counters; if (c2.joinChecks || c2.joinReplies || c2.joinReacts) out.push(`🙋 joined in: ${c2.joinReplies} replies, ${c2.joinReacts} reacts (${c2.joinChecks} checks, ${c2.joinSkipped} skipped)`); }
                if (feedbackRef) { const f = feedbackRef.counters; const r = reflectRef.counters; out.push(`🪞 self: ${f.stored} feedback remarks, ${f.changes} style change(s), reflection ${r.applied} applied / ${r.proposed} proposed (.ariel self)`); }
                if (sumRef) { const x = sumRef.counters; out.push(`📚 summaries: ${x.summaries} saved, ${x.memories} memories from them, ${x.skipped} trivial skipped`); }
                if (jobsRef) { const y = jobsRef.counters; out.push(`🗂 jobs since boot: ${y.done} done, ${y.retried} retried, ${y.dead} dead (.ariel jobs)`); }
                if (houseRef?.counters.lastRun) { const z = houseRef.counters.lastRun; out.push(`🗑 last cleanup: ${z.eligible} eligible, ${z.live ? 'live' : 'dry run'}`); }
                if (c.regenerated || c.limited || c.stale) out.push(`   repeats redone ${c.regenerated}, rate-limited ${c.limited}, stale skipped ${c.stale}`);
                if (conv.status.lastError) out.push(`   last error: ${conv.status.lastError}`);
                return out;
            },
        });
        return { hook, ingest, admin, store };
    })());
}

// Fire and forget: never awaited by the caller, never throws.
export function arielIngest(sock, msg) {
    try {
        learnBot(sock);
        const b = build();
        if (b.off) return;
        Promise.resolve(b).then(async (x) => {
            const r = await x.hook.run(sock, msg);
            // say why a message was not stored (chat-off and own messages are normal, so those stay quiet)
            if (r?.status === 'skipped' && !['self-or-empty', 'chat-off', 'command'].includes(r.reason)) console.log(`[ARIEL] message not stored: ${r.reason}${r.reason === 'no-body' || r.reason === 'ignored-type' ? ` (message parts: ${Object.keys(msg.message || {}).join(', ')})` : ''}`);
            if (r?.status === 'skipped' && r.reason === 'chat-off' && msg.key?.remoteJid?.endsWith('@g.us')) console.log('[ARIEL] message not stored: chat switch is off for this group');
            return r;
        }).catch((e) => {
            console.error('[ARIEL] ingest crashed:', e?.message || e);
        });
    } catch (e) {
        console.error('[ARIEL] ingest setup failed:', e?.message || e);
    }
}

// `.ariel ...` (King only, checked by the caller). Returns reply text or null.
export async function arielAdmin(text, ctx = {}) {
    const lower = String(text || '').trim().toLowerCase();
    if (lower !== '.ariel' && !lower.startsWith('.ariel ')) return null;
    const b = await build();
    if (b.off) return '🧠 Ariel ingest is off (set SUPABASE_DB_URL, and remove ARIEL_INGEST=off).';
    try { return await b.admin.handle(text, ctx); }
    catch (e) { return `🧠 ⚠️ ${String(e.message || e).slice(0, 200)}`; }
}

// Called by setPool() when `.chat on/off` changes a group, so chats.settings follows.
export function syncChatEnabled(jid, on) {
    if (!jid?.endsWith('@g.us')) return;
    Promise.resolve(build()).then((b) => b.off ? null : b.store.setChatEnabled(jid, 'group', on))
        .catch((e) => console.error('[ARIEL] could not sync chat setting:', e?.message || e));
}
