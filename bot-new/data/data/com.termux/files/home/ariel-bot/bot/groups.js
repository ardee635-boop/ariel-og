// groups.js  (split out of index.js)
import { _getDB } from './lib/db.js';
import { botState } from './lib/state.js';
import { err, log } from './lib/log.js';

export async function loadGroups() {
    try {
        const db = await _getDB();
        const res = await db.query('SELECT value FROM bot_auth WHERE key = $1', ['allowed_groups']);
        if (res.rows.length) {
            botState.allowedGroups = JSON.parse(res.rows[0].value);
            log('📋', `Loaded ${botState.allowedGroups.length} groups from Supabase.`);
        } else {
            botState.allowedGroups = [];
            log('📋', 'No groups found. Send .linkgroup in your group.');
        }
    } catch(e) {
        err('📋', `Failed to load groups: ${e.message}`);
        botState.allowedGroups = [];
    }
}

export async function saveGroups(g) {
    try {
        const db = await _getDB();
        await db.query(
            `INSERT INTO bot_auth (key, value) VALUES ($1, $2)
             ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value`,
            ['allowed_groups', JSON.stringify(g)]
        );
    } catch(e) {
        err('📋', `Failed to save groups: ${e.message}`);
    }
}

// ── Ignored groups (.ignore <no.> / .unignore <no.>) ─────────────
// Separate from allowedGroups — an ignored group stays linked (still
// counts toward .groups, .linkgroup isn't needed again to undo this),
// the bot just stops responding to every command in it until unignored.
// Same bot_auth key/value persistence pattern as allowedGroups.
export async function loadIgnoredGroups() {
    try {
        const db = await _getDB();
        const res = await db.query('SELECT value FROM bot_auth WHERE key = $1', ['ignored_groups']);
        botState.ignoredGroups = res.rows.length ? JSON.parse(res.rows[0].value) : [];
    } catch(e) {
        err('📋', `Failed to load ignored groups: ${e.message}`);
        botState.ignoredGroups = [];
    }
}

export async function saveIgnoredGroups(g) {
    try {
        const db = await _getDB();
        await db.query(
            `INSERT INTO bot_auth (key, value) VALUES ($1, $2)
             ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value`,
            ['ignored_groups', JSON.stringify(g)]
        );
    } catch(e) {
        err('📋', `Failed to save ignored groups: ${e.message}`);
    }
}

// ── Group pool toggles (Layer 1) ─────────────────────────────────
// Per-group on/off switches for the Pokemon, Among Us, Chat, Normal,
// and Silent command pools. ALL five default to OFF for a newly
// linked group — an admin (Baron+) must explicitly turn each on with
// .pokemon on / .amongus on / .chat on / .normal on / .silent on.
//
// NOTE: prior to this change, "Normal" commands (.menu, .ping, admin
// commands, etc.) ran unconditionally once a group was linked, with
// no toggle at all. Defaulting .normal to OFF is a deliberate,
// intentional break for consistency with the other pools — every
// already-linked group will need an explicit ".normal on" run in it
// after this deploys, or its utility/admin commands go silent.
//
// Loaded once into memory at startup (see loadGroupPools() call next
// to loadGroups()) and only re-read from the DB when actually
// changed, so the Layer 1 check on every message is a plain in-memory
// object lookup — no per-message DB query, no added latency.
export const POOL_NAMES = ['pokemon', 'amongus', 'chat', 'normal', 'rpg', 'niflheim'];

// One game world per group (Niflheim design: "last one switched on wins").
// Normal, Chat and Silent are NOT in this list — they stay independent.
export const GAME_WORLDS = ['pokemon', 'amongus', 'rpg', 'niflheim'];

const DEFAULT_POOLS = { pokemon: false, amongus: false, chat: false, normal: false, rpg: false, niflheim: false };

 // { [groupJid]: { pokemon: bool, amongus: bool, chat: bool, normal: bool, rpg: bool } }
// .rpg is King-only to toggle (unlike the Baron+ pools above) — see
// the KING-only check carved out of the shared pool-toggle block
// below, right next to where Baron+ is checked for the others.

// Social/roleplay/fun commands — these actually belong to the Normal
// pool (moved here from a "Chat pool" that used to gate them; the
// Chat pool now means the real Ariel conversation feature — see
// .chat on/off below and pool_chat in router/handle.py). Deliberately
// excludes .sticker/.s/.toimg/.translate/.tt/.pint/.wallpaper/
// .copilot — those are utility/converter commands and live in Normal
// too, but sit code-adjacent to this cluster rather than in this set.
// .sleep is shared with the King-only mine sleep-window feature
// (".sleep <window>", handled earlier in the file and returns before
// reaching this gate) — only bare ".sleep" (the fun gif) is actually
// gated below.
export const NORMAL_FUN_COMMANDS = new Set([
    '.hug', '.kiss', '.slap', '.pat', '.dance', '.smile', '.laugh', '.cry',
    '.blush', '.stare', '.pout', '.roar', '.shrug', '.lick', '.punch', '.bonk',
    '.tickle', '.shoot', '.spin', '.think', '.clap', '.run', '.sleep',
    '.meme', '.shootmeme', '.sadmeme', '.coolmeme', '.triggered', '.joke',
    '.truth', '.dare', '.wyr', '.ship', '.spinbottle', '.kidnap', '.ttt', '.alpha',
    '.note', '.notes', '.delnote', '.editnote', '.pnote', '.pnotes', '.delpnote', '.editpnote',
]);

export async function loadSilentPool() {
    try {
        const db = await _getDB();
        const res = await db.query('SELECT value FROM bot_auth WHERE key = $1', ['silent_pool_on']);
        botState.silentPoolOn = res.rows.length ? res.rows[0].value === 'true' : false;
    } catch(e) {
        err('🧩', `Failed to load silent pool flag: ${e.message}`);
        botState.silentPoolOn = false;
    }
}

export async function saveSilentPool() {
    try {
        const db = await _getDB();
        await db.query(
            `INSERT INTO bot_auth (key, value) VALUES ($1, $2)
             ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value`,
            ['silent_pool_on', String(botState.silentPoolOn)]
        );
    } catch(e) {
        err('🧩', `Failed to save silent pool flag: ${e.message}`);
    }
}

export async function loadChatDm() {
    try {
        const db = await _getDB();
        const res = await db.query('SELECT value FROM bot_auth WHERE key = $1', ['chat_dm_on']);
        botState.chatDmOn = res.rows.length ? res.rows[0].value === 'true' : false;
    } catch(e) {
        err('🧩', `Failed to load chat-dm flag: ${e.message}`);
        botState.chatDmOn = false;
    }
}

export async function saveChatDm() {
    try {
        const db = await _getDB();
        await db.query(
            `INSERT INTO bot_auth (key, value) VALUES ($1, $2)
             ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value`,
            ['chat_dm_on', String(botState.chatDmOn)]
        );
    } catch(e) {
        err('🧩', `Failed to save chat-dm flag: ${e.message}`);
    }
}

export async function loadGroupPools() {
    try {
        const db = await _getDB();
        const res = await db.query('SELECT value FROM bot_auth WHERE key = $1', ['group_pools']);
        if (res.rows.length) {
            botState.groupPools = JSON.parse(res.rows[0].value);
            log('🧩', `Loaded pool settings for ${Object.keys(botState.groupPools).length} groups.`);
        } else {
            botState.groupPools = {};
        }
    } catch(e) {
        err('🧩', `Failed to load group pools: ${e.message}`);
        botState.groupPools = {};
    }
}

export async function saveGroupPools() {
    try {
        const db = await _getDB();
        await db.query(
            `INSERT INTO bot_auth (key, value) VALUES ($1, $2)
             ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value`,
            ['group_pools', JSON.stringify(botState.groupPools)]
        );
    } catch(e) {
        err('🧩', `Failed to save group pools: ${e.message}`);
    }
}

export function isPoolOn(groupJid, poolName) {
    return botState.groupPools[groupJid]?.[poolName] === true;
}

export function setPool(groupJid, poolName, on) {
    if (!botState.groupPools[groupJid]) botState.groupPools[groupJid] = { ...DEFAULT_POOLS };
    botState.groupPools[groupJid][poolName] = on;
    // Ariel keeps a copy of the .chat switch in ariel.chats.settings. Loaded lazily
    // (dynamic import) so groups.js doesn't pull the Ariel files in at startup.
    if (poolName === 'chat') {
        import('./ariel/wire.js').then((m) => m.syncChatEnabled(groupJid, on === true)).catch(() => {});
    }
}

// ── Message handler ───────────────────────────────────────────
// ── Ordered group list (what .groups shows, and what every <gc no.> uses) ──
// Numbers are stable: each group gets the next free slot the first time Ariel
// sees it (oldest-created first when seeding), and keeps it. A new group goes
// to the END of the list instead of landing somewhere in the middle. If Ariel
// leaves and later rejoins a group, it gets its old slot back.
const GROUP_ORDER_KEY = 'group_order';

export async function getOrderedGroups(sock) {
    const run = botState._groupOrderChain.then(async () => {
        const all = await sock.groupFetchAllParticipating();
        if (botState._groupOrder === null) {
            try {
                const db = await _getDB();
                const r = await db.query('SELECT value FROM bot_auth WHERE key = $1', [GROUP_ORDER_KEY]);
                botState._groupOrder = r.rows.length ? JSON.parse(r.rows[0].value) : [];
            } catch { botState._groupOrder = []; }
        }
        const known = new Set(botState._groupOrder);
        const fresh = Object.values(all)
            .filter(g => !known.has(g.id))
            .sort((a, b) => (a.creation || 0) - (b.creation || 0) || a.id.localeCompare(b.id));
        if (fresh.length) {
            botState._groupOrder = botState._groupOrder.concat(fresh.map(g => g.id));
            try {
                const db = await _getDB();
                await db.query(
                    `INSERT INTO bot_auth (key, value) VALUES ($1, $2)
                     ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value`,
                    [GROUP_ORDER_KEY, JSON.stringify(botState._groupOrder)]
                );
            } catch (e) { console.warn(`[GROUPS] couldn't save group order: ${e.message}`); }
        }
        return botState._groupOrder.filter(j => all[j]).map(j => all[j]);
    });
    botState._groupOrderChain = run.catch(() => {});
    return run;
}

