// ============================================================
// work.js — Tensura `.work` auto-player + `.card` auto-claim
// Lives ALONGSIDE .mine / .label (nothing here touches them).
// State persists in bot_auth (keys: work_state, card_state).
// No numbers are hardcoded: watch numbers come from `.work watch`,
// `.card watch`, or the first host/spawn sender.
// ============================================================

import { setIdMode, setIdLog, idInfo, phoneId, isLibStyle } from './lib/msgid.js';

let D = null; // deps injected by initWork()

// Shown in .scard / .swork status so you can tell which build is deployed.
const WORK_BUILD = 'w8-active';
const WORK_KEY = 'work_state';
const CARD_KEY = 'card_state';

const HOUR_MS     = 60 * 60 * 1000;
const WORK_GAP_MS = 5000;           // min gap between any two .work commands
const TOTAL_HOURS = 24;
const MAX_CLAIMED = 500;
const RESTART_COOLDOWN_MS = 60 * 1000;

// First match wins. Reorder to change what matters most.
const PRIORITY = [
    /chest/i,              // bonus coins
    /strange rock/i,       // coal
    /merchant/i,           // food (-1 hunger)
    /runaway|missing/i,    // restore a worker
    /slacking|tangled/i,   // stop a loss
    /quiet/i,              // nothing
];
const MERCHANT_RE = /merchant/i;
const QUIET_RE    = /quiet/i;

// { [groupJid]: { enabled, frozen, watch, hour, nextAt, labelMs, groupLabel,
//                 claimNext, seen:[], lastStartAt } }
let work = {};
// card.groups: { [groupJid]: { label, watch } } — watch is per group
let card = { groups: {}, claimed: [], active: { target: 0 } };

const workTimers   = {};  // groupJid -> setTimeout (hourly tick)
const freezeTimers = {};  // groupJid -> setTimeout (label reply deadline)

const rand = (a, b) => a + Math.random() * (b - a);
const jitter = () => Math.round(rand(5000, 15000));
const digits = v => String(v ?? '').replace(/\D/g, '') || null;
const jidNum = jid => String(jid || '').split('@')[0].split(':')[0];
const isKing = num => Boolean(D?.kingNumber) && num === String(D.kingNumber);

// ── persistence ────────────────────────────────────────────────
async function _save(key, value) {
    try {
        const db = await D.getDB();
        await db.query(
            `INSERT INTO bot_auth (key, value) VALUES ($1, $2)
             ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value`,
            [key, JSON.stringify(value)]
        );
    } catch (e) { D.err('🛠️', `work save(${key}) failed: ${e.message}`); }
}
const saveWork = () => _save(WORK_KEY, work);
const saveCard = () => _save(CARD_KEY, card);

export async function loadWork() {
    try {
        const db = await D.getDB();
        let r = await db.query('SELECT value FROM bot_auth WHERE key = $1', [WORK_KEY]);
        work = r.rows.length ? JSON.parse(r.rows[0].value) : {};
        r = await db.query('SELECT value FROM bot_auth WHERE key = $1', [CARD_KEY]);
        card = r.rows.length ? JSON.parse(r.rows[0].value) : card;
        card.groups  ||= {};
        card.claimed ||= [];
        card.active  ||= { target: 0 };
        setIdMode(card.idMode);   // restore .scard id setting after a restart
        // Migrate older shapes: groups[jid] was a name string, watch was global.
        for (const [jid, v] of Object.entries(card.groups)) {
            if (typeof v === 'string') card.groups[jid] = { label: v, watch: card.watch || null };
        }
        delete card.watch;
        // A King-number watch can only come from an old test build; never keep it.
        for (const cg of Object.values(card.groups)) if (isKing(cg.watch)) cg.watch = null;
        for (const g of Object.values(work)) if (isKing(g.watch)) g.watch = null;
        D.log('🛠️', `[${WORK_BUILD}] Loaded work (${Object.keys(work).length} group(s)) + card state (${Object.keys(card.groups).length} group(s)).`);
    } catch (e) {
        D.err('🛠️', `work load failed: ${e.message}`);
    }
}

// ── send paths ─────────────────────────────────────────────────
async function _typeSend(jid, text, typingMs) {
    const sock = D.getSock();
    if (!sock) return false;
    try { await sock.sendPresenceUpdate('composing', jid); } catch {}
    await D.sleep(typingMs);
    try { await sock.sendPresenceUpdate('paused', jid); } catch {}
    const sent = await D.sendText(sock, jid, text);
    return Boolean(sent);
}

// .work commands: serialized, >= 5s between any two.
let workChain = Promise.resolve();
let lastWorkSendAt = 0;
function workSend(jid, text) {
    const p = workChain.then(async () => {
        const wait = lastWorkSendAt + WORK_GAP_MS - Date.now();
        if (wait > 0) await D.sleep(wait);
        const ok = await _typeSend(jid, text, 3000);
        lastWorkSendAt = Date.now();
        return ok;
    });
    workChain = p.catch(() => {});
    return p;
}

// Claims: own path, never waits for or delays the .work queue.
// Claims always go out with a phone-shaped message ID (independent of .scard id),
// and we log the ID that actually came back so a library override is visible.
async function claimSend(jid, text) {
    const sock = D.getSock();
    if (!sock) return false;
    try { await sock.sendPresenceUpdate('composing', jid); } catch {}
    await D.sleep(Math.round(rand(800, 2200)));   // typing time varies
    try { await sock.sendPresenceUpdate('paused', jid); } catch {}
    const want = phoneId();
    try {
        const sent = await sock.sendMessage(jid, { text }, { messageId: want });
        const got = sent?.key?.id;
        D.log('🆔', `[claim] wanted id=${want} got id=${got} libStyle=${isLibStyle(got)}${got === want ? '' : ' (MISMATCH: library overrode the id)'}`);
        return Boolean(sent);
    } catch (e) {
        D.err('🃏', `claimSend failed: ${e.message}`);
        return false;
    }
}

// ── run loop ───────────────────────────────────────────────────
function clearTimers(jid) {
    if (workTimers[jid])   { clearTimeout(workTimers[jid]);   delete workTimers[jid]; }
    if (freezeTimers[jid]) { clearTimeout(freezeTimers[jid]); delete freezeTimers[jid]; }
}

function scheduleTick(jid, at) {
    const g = work[jid];
    if (!g) return;
    if (workTimers[jid]) clearTimeout(workTimers[jid]);
    g.nextAt = at;
    workTimers[jid] = setTimeout(() => { void tick(jid); }, Math.max(0, at - Date.now()));
}

function armFreeze(jid) {
    const g = work[jid];
    if (!g?.labelMs) return;
    if (freezeTimers[jid]) clearTimeout(freezeTimers[jid]);
    freezeTimers[jid] = setTimeout(async () => {
        delete freezeTimers[jid];
        if (!work[jid]?.enabled) return;
        work[jid].frozen = true;
        if (workTimers[jid]) { clearTimeout(workTimers[jid]); delete workTimers[jid]; }
        await saveWork();
        D.log('🧊', `Work frozen in ${g.groupLabel || jid} — no reply in time.`);
    }, g.labelMs);
}

// The 24h run is over: send `.work start` (>= 5s after any other command)
// and begin a fresh run. A cooldown stops two triggers sending it twice.
async function restart(jid, why) {
    const g = work[jid];
    if (!g || !g.enabled || g.frozen) return;
    if (Date.now() - (g.lastStartAt || 0) < RESTART_COOLDOWN_MS) return;
    g.lastStartAt = Date.now();
    g.hour = 0;
    g.seen = [];
    g.claimNext = false;
    if (workTimers[jid]) { clearTimeout(workTimers[jid]); delete workTimers[jid]; }
    D.log('🛠️', `Work ${g.groupLabel || jid}: sending .work start (${why}).`);
    await workSend(jid, '.work start');
    scheduleTick(jid, Date.now() + HOUR_MS + jitter());
    await saveWork();
}

async function tick(jid) {
    const g = work[jid];
    delete workTimers[jid];
    if (!g || !g.enabled || g.frozen) return;

    if (g.claimNext) {
        // Hour 24 done: claim, then (>= 5s later, enforced by the queue) start anew.
        await workSend(jid, '.work');
        await restart(jid, 'hour 24 finished');
        return;
    }

    await workSend(jid, '.work');
    armFreeze(jid);
    scheduleTick(jid, Date.now() + HOUR_MS + jitter());
    await saveWork();
}

export function startWork() {
    startActiveKeeper();
    for (const [jid, g] of Object.entries(work)) {
        if (!g.enabled || g.frozen) continue;
        // late is fine, early never is
        scheduleTick(jid, Math.max(g.nextAt || 0, Date.now() + 2000));
        D.log('🛠️', `Work re-armed for ${g.groupLabel || jid}.`);
    }
}

// ── event picking ──────────────────────────────────────────────
export function parseOptions(text) {
    const opts = [];
    let prev = '';
    for (const raw of String(text).split('\n')) {
        const line = raw.replace(/[*_`~]/g, '').trim();
        if (!line) continue;
        const m = /^[\[(]?(\d{1,2})(?:\uFE0F?\u20E3|\s*[.)\]:\-])\s*(.+)$/.exec(line);
        if (m) {
            opts.push({ n: parseInt(m[1], 10), text: m[2], ctx: `${prev} ${m[2]}` });
        } else {
            prev = line;
        }
    }
    return opts;
}

export function pickOption(text, opts) {
    let order = PRIORITY;
    const hunger = /hunger\D{0,12}(\d)\s*\/\s*2/i.exec(text);
    if (hunger && hunger[1] === '2') {
        // starving: food first
        order = [MERCHANT_RE, ...PRIORITY.filter(r => r !== MERCHANT_RE)];
    }
    for (const field of ['text', 'ctx']) {          // option text first, then its header line
        for (const re of order) {
            const hit = opts.find(o => re.test(o[field]));
            if (hit) return hit;
        }
    }
    return opts.find(o => QUIET_RE.test(o.ctx)) || opts[0]; // never hang
}

// toUs: true only when the host's message quotes one of OUR messages or tags
// us. Anything else is the host answering another player's .work, so skip it.
async function onWorkMessage(jid, g, text, toUs) {
    if (g.frozen) return;
    if (!toUs) return;
    // any reply from the host clears the label deadline
    if (freezeTimers[jid]) { clearTimeout(freezeTimers[jid]); delete freezeTimers[jid]; }

    // "You don't have any pending choices right now…" = the 24h run is over.
    // Only act on it when it's aimed at us (not another player's .work).
    if (/pending choices/i.test(text)) {
        await restart(jid, 'host: no pending choices');
        return;
    }

    if (/crew is busy|next event in/i.test(text)) return;   // no effect on the timer

    const hm = /hour\s*(\d+)\s*\/\s*(\d+)/i.exec(text);
    const opts = parseOptions(text);
    if (opts.length < 2) return;                             // not an event list

    const key = text.replace(/\s+/g, ' ').trim().toLowerCase();
    g.seen ||= [];
    if (g.seen.includes(key)) return;                        // host repeats itself ~3x
    g.seen.push(key);
    if (g.seen.length > 20) g.seen.shift();

    const choice = pickOption(text, opts);
    const hour = hm ? parseInt(hm[1], 10) : (g.hour || 0) + 1;
    const total = hm ? parseInt(hm[2], 10) : TOTAL_HOURS;
    g.hour = hour;
    if (hour >= total) g.claimNext = true;                   // next tick = claim + restart
    await saveWork();

    D.log('⛏️', `Work ${g.groupLabel || jid}: hour ${hour}, picked ${choice.n} "${choice.text.slice(0, 40)}"`);
    await D.sleep(Math.round(rand(1000, 3000)));
    await workSend(jid, `.work ${choice.n}`);
}

// ── card spawns ────────────────────────────────────────────────
// ── activity keeper (.sactive) ─────────────────────────────────
// The card game only lets an account claim once it has sent N messages in the
// last hour. We count every message the bot account sends in a group (by
// wrapping sock.sendMessage), top up with short, varied filler lines when it
// is short, and make sure it is at the target right before a claim.
const ACTIVE_BUFFER = 2;                 // background top-up aims a little above the target
const sentLog = {};                      // groupJid -> [{ id, at }]
const lastFillers = {};                  // groupJid -> recent filler texts
const nextFillAt = {};                   // groupJid -> earliest next background filler
const filling = {};                      // groupJid -> Promise while a burst is running
let activeTimer = null;

const FILLERS = [
    'lol', 'fr', 'true', 'hm', 'same', 'wait', 'nah', 'ok', 'bet', 'oh', 'damn', 'facts',
    'lmao', 'idk', 'yeah', 'mhm', 'aight', 'fair', 'sheesh', 'noted', 'huh', 'ikr', 'oof',
    'right', 'hmm', 'word', 'lowkey true', 'wild', 'ah ok', 'makes sense', '💀', '😂', '👀',
];

function recordSent(jid, id) {
    const now = Date.now();
    const list = (sentLog[jid] ||= []);
    const key = id || `${now}-${Math.random()}`;
    if (!list.some(e => e.id === key)) list.push({ id: key, at: now });
    while (list.length && now - list[0].at > HOUR_MS) list.shift();
}

export function countSent(jid) {
    const list = sentLog[jid];
    if (!list) return 0;
    const now = Date.now();
    while (list.length && now - list[0].at > HOUR_MS) list.shift();
    return list.length;
}

// Wrap the live socket once so every message the account sends in a group is counted.
export function watchOutgoing(sock) {
    if (!sock || sock.__activityWrapped || typeof sock.sendMessage !== 'function') return;
    const orig = sock.sendMessage.bind(sock);
    sock.sendMessage = async (jid, content, ...rest) => {
        const res = await orig(jid, content, ...rest);
        try {
            const isNoise = content && (content.react || content.delete || content.protocolMessage);
            if (res && !isNoise && String(jid).endsWith('@g.us')) recordSent(jid, res?.key?.id);
        } catch {}
        return res;
    };
    sock.__activityWrapped = true;
}

function pickFiller(jid) {
    const recent = (lastFillers[jid] ||= []);
    const options = FILLERS.filter(f => !recent.includes(f));
    const pick = options[Math.floor(Math.random() * options.length)] || FILLERS[0];
    recent.push(pick);
    while (recent.length > 8) recent.shift();
    return pick;
}

const fillOne = (jid) => workSend(jid, pickFiller(jid));

async function burstFill(jid, need) {
    if (filling[jid]) return filling[jid];
    filling[jid] = (async () => {
        try {
            for (let i = 0; i < need; i++) { if (!(await fillOne(jid))) break; }
        } finally { delete filling[jid]; }
    })();
    return filling[jid];
}

// Right before a claim: bring the account up to the target (no-op when off or already there).
async function ensureActive(jid) {
    const target = card.active?.target || 0;
    if (!target) return { skipped: true, count: countSent(jid), target };
    let count = countSent(jid);
    if (count < target) {
        const need = Math.min(target - count, 25);
        D.log('🃏', `[active] ${count}/${target} in last hour, sending ${need} filler(s) before claiming.`);
        await burstFill(jid, need);
        count = countSent(jid);
    }
    return { ok: count >= target, count, target };
}

async function keepActiveOnce() {
    const target = card.active?.target || 0;
    if (!target) return;
    for (const jid of Object.keys(card.groups)) {
        if (filling[jid]) continue;
        if (countSent(jid) >= target + ACTIVE_BUFFER) continue;
        if (Date.now() < (nextFillAt[jid] || 0)) continue;
        nextFillAt[jid] = Date.now() + Math.round(rand(150000, 420000));   // every 2.5 to 7 min
        void fillOne(jid);
    }
}
export const _keepActiveOnceForTest = keepActiveOnce;

export function startActiveKeeper() {
    if (activeTimer) clearInterval(activeTimer);
    activeTimer = setInterval(() => { void keepActiveOnce(); }, 60 * 1000);
}

export async function handleActiveCommand(sock, chatJid, text, reply) {
    const args = text.trim().split(/\s+/).slice(1);
    const sub = (args[0] || '').toLowerCase();
    const groups = Object.entries(card.groups);

    if (sub === 'fill') {
        const idx = parseInt(args[1], 10);
        let targets = groups;
        if (idx) {
            const t = await resolveGroup(sock, idx);
            if (!t || !card.groups[t.id]) return reply('_That group does not have card auto-claim on. Use .scard on <gc no.> first._');
            targets = [[t.id, card.groups[t.id]]];
        }
        const target = card.active?.target || 0;
        if (!target) return reply('_Set a target first, e.g. .sactive 10_');
        for (const [jid, cg] of targets) void burstFill(jid, Math.max(0, target - countSent(jid)));
        return reply(`💬 Filling to ${target} msgs/hr in ${targets.length} group(s).`);
    }

    if (sub === 'off' || sub === '0') {
        card.active = { target: 0 };
        await saveCard();
        return reply('💬 *Active keeper off.*');
    }

    if (/^\d+$/.test(sub)) {
        const n = parseInt(sub, 10);
        if (n < 1 || n > 60) return reply('_Pick a number from 1 to 60, e.g. .sactive 10_');
        card.active = { target: n };
        await saveCard();
        return reply(`💬 *Active target: ${n} msgs/hr* for every card group (background top-up aims for ${n + ACTIVE_BUFFER}, and she fills up to ${n} right before a claim).`);
    }

    const target = card.active?.target || 0;
    const rows = groups.map(([jid, cg]) => `• ${cg.label || jid}: ${countSent(jid)}/${target || '-'} in the last hour`);
    return reply(`💬 *Active keeper*: ${target ? target + ' msgs/hr' : 'off'}\n${rows.length ? rows.join('\n') : '_No card groups yet. .scard on <gc no.>_'}\n_.sactive <n> · .sactive off · .sactive fill [gc no.]_`);
}

// ── card auto-claim (rewritten) ────────────────────────────────
// Rules, unchanged:
//   * Card auto-claim must be ON for the group (.scard on <gc no.>).
//   * A spawn the King forwards by hand ALWAYS claims (test mode).
//   * Otherwise the first real sender of a spawn becomes the group's watch
//     number, and only that number's spawns are claimed, once per spawn ID.
// New: every spawn ends in exactly one traced outcome (log + .scard status),
// and the King is told in chat when a forwarded spawn is NOT claimed (non-silent groups only).

const cardLast = { at: 0, from: null, id: null, result: 'no spawn seen since the bot started' };

// Reads a spawn out of a card-bot message. Strips WhatsApp formatting first.
export function parseSpawn(rawText) {
    // NFKC turns fancy Unicode (𝟬𝟱𝟱𝟳𝟬, 𝗦𝗽𝗮𝘄𝗻 𝗜𝗗, fullwidth...) into plain ASCII,
    // which is how the card bot writes the spawn ID.
    const text = String(rawText || '')
        .normalize('NFKC')
        .replace(/[​-‏⁠﻿]/g, '')
        .replace(/[*_~`]/g, '');
    if (!/wild\s+card\s+has\s+appeared/i.test(text)) return null;
    const id =
        /\bclaim\s+(\d{3,10}|[A-Za-z0-9]*\d[A-Za-z0-9]*)\b/i.exec(text)?.[1] ||       // "...claim 05570"
        /spawn\s*id\W{0,8}([A-Za-z0-9]{3,10})/i.exec(text)?.[1] ||                      // "Spawn ID: 05570"
        /\bid\W{0,8}(\d{4,10})\b/i.exec(text)?.[1];                                    // "ID: 05570"
    if (!id) return null;
    return {
        id: id.toLowerCase(),
        name:  /name\W{0,4}([^\n]+)/i.exec(text)?.[1]?.trim(),
        tier:  /tier\W{0,4}(\S+)/i.exec(text)?.[1],
        price: /price\W{0,4}\$?([\d,]+)/i.exec(text)?.[1],
    };
}

async function onCardMessage(jid, num, fromKing, text, say) {
    // Explanatory chat notes only for the King's hand-forwarded tests, and never
    // in a silent-linked group (replies there are visible to everyone). In a
    // silent group the outcome goes to the log and to `.scard` (Last spawn).
    const note = async (t) => {
        if (!fromKing || !say || D.isSilentGroup(jid)) return;
        try { await say(t); } catch {}
    };
    const trace = (spawnId, result) => {
        cardLast.at = Date.now(); cardLast.from = num; cardLast.id = spawnId || null; cardLast.result = result;
        D.log('🃏', `[card] ${spawnId ? 'spawn ' + spawnId : 'message'} from ${num}${fromKing ? ' (King)' : ''}: ${result}`);
    };

    const spawn = parseSpawn(text);
    if (!spawn) {
        trace(null, `could not read a spawn ID. Text: ${String(text).slice(0, 160).replace(/\n/g, ' | ')}`);
        await note('_🃏 Not claimed: I could not read a spawn ID from that message._');
        return;
    }

    const cg = card.groups[jid];
    if (!cg) {
        trace(spawn.id, 'NOT claimed, card auto-claim is OFF in this group (.scard on <gc no.>)');
        await note('_🃏 Not claimed: card auto-claim is OFF for this group. Use .scard on <gc no.> (the group number from .groups)._');
        return;
    }

    if (!fromKing) {
        if (!cg.watch) {                       // first real sender becomes the card bot
            cg.watch = num;
            await saveCard();
            D.log('🃏', `[card] watch for ${cg.label || jid} set to ${num}`);
        }
        if (num !== cg.watch) {
            trace(spawn.id, `NOT claimed, sender is not this group's card watch (${cg.watch})`);
            return;
        }
        if (card.claimed.includes(spawn.id)) {
            trace(spawn.id, 'NOT claimed, already handled');
            return;
        }
    }

    if (!card.claimed.includes(spawn.id)) card.claimed.push(spawn.id);
    if (card.claimed.length > MAX_CLAIMED) card.claimed.shift();
    await saveCard();

    // Human-like reaction time: usually 2-6s, sometimes slower. Never a fixed gap.
    await D.sleep(Math.round(Math.random() < 0.15 ? rand(6000, 12000) : rand(2000, 6000)));
    const act = await ensureActive(jid);
    const ok = await claimSend(jid, `.claim ${spawn.id}`);
    if (ok) {
        trace(spawn.id, `CLAIMED (${spawn.name || '?'}, tier ${spawn.tier || '?'}, $${spawn.price || '?'})${act.skipped ? '' : ` · active ${act.count}/${act.target}`}`);
    } else {
        card.claimed = card.claimed.filter(x => x !== spawn.id);   // let a later copy retry
        await saveCard();
        trace(spawn.id, 'NOT claimed, the claim message could not be sent (socket unavailable)');
        await note('_🃏 The claim could not be sent (socket unavailable). Check the logs._');
    }
}

// Resolve a sender (phone JID or @lid) to a bare phone number.
async function phoneOf(groupJid, senderJid) {
    const raw = String(senderJid || '');
    if (raw.endsWith('@s.whatsapp.net')) return jidNum(raw);
    const mapped = D.lidMap?.[raw];
    if (mapped?.endsWith('@s.whatsapp.net')) return jidNum(mapped);
    try {
        const meta = await D.getSock().groupMetadata(groupJid);
        const f = meta.participants.find(p => p.lid === raw || p.id === raw);
        const id = f?.phoneNumber || f?.id;
        if (id?.endsWith('@s.whatsapp.net')) {
            if (D.lidMap) D.lidMap[raw] = id;
            return jidNum(id);
        }
    } catch {}
    return jidNum(raw);
}

// ── message hook (call before the silent-group early return) ───
// `text` may be an image caption. opts.toUs: host msg quotes/tags us.
// Never throws.
export async function handleWorkMessage(jid, senderJid, text, opts = {}) {  // opts: { toUs, say }
    try {
        if (!text) return;
        // strip zero-width characters; \s already covers non-breaking spaces
        // NFKC also folds fancy Unicode lettering (𝗰𝗵𝗲𝘀𝘁, 𝟬𝟱) to plain ASCII so the regexes match.
        text = String(text).normalize('NFKC').replace(/[\u200B-\u200F\u2060\uFEFF]/g, '');
        const num = await phoneOf(jid, senderJid);
        const fromKing = isKing(num);

        if (/wild\s+card\s+has\s+appeared/i.test(text.normalize('NFKC'))) {
            await onCardMessage(jid, num, fromKing, text, opts.say);
        }

        const g = work[jid];
        if (!g?.enabled || fromKing) return;
        if (!g.watch) {
            // first host-looking sender becomes the watch number
            if (/crew|hour\s*\d|miner|fisher|hunger/i.test(text)) {
                g.watch = num;
                await saveWork();
                D.log('🛠️', `Work watch number for ${g.groupLabel || jid}: ${g.watch}`);
            } else return;
        }
        if (num !== g.watch) return;
        await onWorkMessage(jid, g, text, opts.toUs === true);
    } catch (e) {
        D.err('🛠️', `handleWorkMessage: ${e.message}`);
    }
}

// ── commands (.work / .card) — caller checks King ──────────────
async function resolveGroup(sock, idx) {
    const list = await D.getOrderedGroups(sock);   // same numbering as .groups
    return list[idx - 1] || null;
}

export async function handleWorkCommand(sock, chatJid, text, reply) {
    const args = text.trim().split(/\s+/).slice(1);   // after ".work"
    const sub = (args[0] || '').toLowerCase();

    if (sub === 'on' || sub === 'off') {
        const idx = parseInt(args[1], 10);
        const t = idx ? await resolveGroup(sock, idx) : null;
        if (!t) return reply('_Usage: .swork on|off <gc no.> — run .groups for the number._');
        const jid = t.id;
        if (sub === 'on' && !D.isSilentGroup(jid)) {
            return reply(`_${t.subject} isn't silent-linked. Use .silentlink ${parseInt(args[1], 10)} first._`);
        }
        if (sub === 'off') {
            clearTimers(jid);
            if (work[jid]) { work[jid].enabled = false; work[jid].frozen = false; }
            await saveWork();
            return reply(`🛠️ *Work off* in *${t.subject}*.`);
        }
        const prev = work[jid];
        const resuming = prev && prev.frozen && prev.hour > 0;
        work[jid] = {
            enabled: true, frozen: false,
            watch: prev?.watch || null,
            hour: resuming ? prev.hour : 0,
            labelMs: prev?.labelMs || null,
            groupLabel: t.subject,
            claimNext: resuming ? !!prev.claimNext : false,
            seen: [], nextAt: 0,
            lastStartAt: resuming ? 0 : Date.now(),
        };
        clearTimers(jid);
        await saveWork();
        if (resuming) {
            await workSend(jid, '.work');
            armFreeze(jid);
        } else {
            await workSend(jid, '.work start');
        }
        scheduleTick(jid, Date.now() + HOUR_MS + jitter());
        await saveWork();
        return reply(`🛠️ *Work ${resuming ? 'resumed' : 'on'}* in *${t.subject}*.`);
    }

    if (sub === 'label') {
        const idx = parseInt(args[1], 10);
        const t = idx ? await resolveGroup(sock, idx) : null;
        const dur = args[2];
        if (!t || !dur) return reply('_Usage: .swork label <gc no.> <duration|none> — e.g. .swork label 2 10m_');
        if (!D.isSilentGroup(t.id)) {
            return reply(`_${t.subject} isn't silent-linked. Use .silentlink ${idx} first._`);
        }
        work[t.id] ||= { enabled: false, frozen: false, watch: null, hour: 0, groupLabel: t.subject, seen: [], nextAt: 0 };
        if (dur.toLowerCase() === 'none') {
            work[t.id].labelMs = null;
            if (freezeTimers[t.id]) { clearTimeout(freezeTimers[t.id]); delete freezeTimers[t.id]; }
        } else {
            const ms = D.parseDuration(dur);
            if (!ms || ms < 1000) return reply('_Duration like 10m, 90s, 1h._');
            work[t.id].labelMs = ms;
        }
        await saveWork();
        return reply(`🏷️ *Work label* for *${t.subject}*: ${work[t.id].labelMs ? dur : 'off'}.`);
    }

    if (sub === 'watch') {
        // .work watch <number>  (inside the group)  or  .work watch <gc no.> <number>
        let jid = chatJid, num = args[1];
        if (args.length >= 3) {
            const t = await resolveGroup(sock, parseInt(args[1], 10));
            if (!t) return reply('_No group at that position._');
            jid = t.id; num = args[2];
        }
        const n = digits(num);
        if (!n || !work[jid]) return reply('_Usage: .swork watch <number> (in a work-enabled group) or .swork watch <gc no.> <number>_');
        work[jid].watch = n;
        await saveWork();
        return reply(`👀 *Work watch number:* \`${n}\`.`);
    }

    if (sub === 'status' || !sub) {
        const rows = Object.entries(work).map(([jid, g]) =>
            `• ${g.groupLabel || jid}: ${g.enabled ? (g.frozen ? '🧊 frozen' : '▶️ on') : '⏹ off'} · hour ${g.hour || 0}/${TOTAL_HOURS} · watch ${g.watch || 'pending'}` +
            (g.labelMs ? ` · label ${Math.round(g.labelMs / 60000)}m` : '') +
            (g.enabled && !g.frozen && g.nextAt ? ` · next ${new Date(g.nextAt).toISOString().slice(11, 19)}Z` : ''));
        return reply(rows.length ? `🛠️ *Work* (build ${WORK_BUILD})\n${rows.join('\n')}` : '_No work groups yet. .swork on <gc no.>_');
    }

    return reply('_.swork on|off <gc no.> · .swork label <gc no.> <time|none> · .swork watch <number> · .swork status_');
}

export async function handleCardCommand(sock, chatJid, text, reply) {
    const args = text.trim().split(/\s+/).slice(1);
    const sub = (args[0] || '').toLowerCase();

    if (sub === 'on' || sub === 'off') {
        const t = await resolveGroup(sock, parseInt(args[1], 10));
        if (!t) return reply('_Usage: .scard on|off <gc no.>_');
        if (sub === 'on' && !D.isSilentGroup(t.id)) {
            return reply(`_${t.subject} isn't silent-linked. Use .silentlink ${parseInt(args[1], 10)} first._`);
        }
        if (sub === 'on') card.groups[t.id] = { label: t.subject, watch: card.groups[t.id]?.watch || null };
        else delete card.groups[t.id];
        await saveCard();
        return reply(`🃏 *Card auto-claim ${sub}* in *${t.subject}*.`);
    }
    if (sub === 'watch') {
        // .card watch <number> (inside the group)  or  .card watch <gc no.> <number>
        let jid = chatJid, num = args[1];
        if (args.length >= 3) {
            const t = await resolveGroup(sock, parseInt(args[1], 10));
            if (!t) return reply('_No group at that position._');
            jid = t.id; num = args[2];
        }
        const n = digits(num);
        if (!n || !card.groups[jid]) return reply('_Usage: .scard watch <number> (in a card-enabled group) or .scard watch <gc no.> <number>_');
        card.groups[jid].watch = n;
        await saveCard();
        return reply(`👀 *Card watch number* for *${card.groups[jid].label}*: \`${n}\`.`);
    }
    if (sub === 'id') {
        const a = (args[1] || '').toLowerCase();
        if (a === 'phone' || a === 'default') {
            card.idMode = a; setIdMode(a); await saveCard();
            return reply(`🆔 *Message ID mode:* ${a}`);
        }
        if (a === 'log') {
            const on = (args[2] || '').toLowerCase() !== 'off';
            setIdLog(on);
            return reply(`🆔 ID logging ${on ? 'on' : 'off'} (see console for [MSGID] lines).`);
        }
        const i = idInfo();
        return reply(`🆔 *Message ID mode:* ${i.mode} · log ${i.log ? 'on' : 'off'} · id length ${i.sampleLen}\nSamples (your phone): ${i.samples.join(', ') || 'none yet, send a message from your phone'}\n_.scard id phone | default | log on|off_`);
    }
    if (sub === 'clear') {
        const n = card.claimed.length;
        card.claimed = [];
        await saveCard();
        return reply(`🃏 Cleared ${n} remembered spawn ID(s).`);
    }
    const rows = Object.values(card.groups).map(g => `• ${g.label}: watch ${g.watch || 'pending (first spawner)'}`);
    const last = cardLast.at
        ? `${new Date(cardLast.at).toISOString().slice(11, 19)}Z · ${cardLast.id ? 'spawn ' + cardLast.id : 'message'} · ${cardLast.result}`
        : cardLast.result;
    return reply(`🃏 *Card*\n${rows.length ? rows.join('\n') : '_No card groups. .scard on <gc no.>_'}\nClaimed: ${card.claimed.length} · build ${WORK_BUILD}\nLast spawn: ${last}`);
}

// .silentwatch reset — every work + card watch goes back to *pending*:
// the next host / spawn sender in that group is picked automatically.
export async function handleWatchCommand(text, reply) {
    const sub = (text.trim().split(/\s+/)[1] || '').toLowerCase();
    if (sub !== 'reset') return reply('_Usage: .silentwatch reset — sets every work + card watch back to pending._');
    let w = 0, c = 0;
    for (const g of Object.values(work))      { if (g.watch)  { g.watch = null;  w++; } }
    for (const g of Object.values(card.groups)) { if (g.watch) { g.watch = null; c++; } }
    await saveWork();
    await saveCard();
    return reply(`♻️ *Watch numbers reset* — ${w} work + ${c} card group(s) are now pending (auto-pick on next sender).`);
}

export function initWork(deps) { D = deps; }
