// ============================================================
// ARIEL — commands.js
// Group management · Ranks · Welcome/Leave · Warnings
// ============================================================
//
// TABLES (auto-created on first run):
//   bot_ranks      — global royalty/lords; barons are per-group (group_jid)
//   group_settings — per-group welcome/leave/rules
//   warnings       — per-group user warning counts
//
// HIERARCHY (highest → lowest):
//   Royalty  → King (1), Queen (many), Prince/Princess/Duke/Duchess
//   Lords    → appointed by King/Queen
//   Admin    → WhatsApp group admins
//   Baron    → earned in-game (same level as Admin)
//   Player   → registered, game access only
//   Guest    → in group, hasn't typed .start
//
// RANK LEVELS (numeric for comparison):
//   King=100  Queen=90  Prince/Princess/Duke/Duchess=80
//   Lord=70   Admin/Baron=50  Player=10  Guest=0
// ============================================================

import { sendCard } from './lib/card.js';
import './lib/config.js';
import sharp from 'sharp';
import { generateWAMessageFromContent } from '@whiskeysockets/baileys';
import { toFraktur, toScript, sendHidetag } from './fancy.js';

// Returned by a command that already sent its own message (e.g. a hidetag),
// so index.js knows it was handled and doesn't send anything else.
export const REPLY_HANDLED = '__HANDLED__';

// Announce in the group with a hidden tag-everyone. Returns true if sent.
async function _announce(ctx, text) {
    if (!ctx.chatJid?.endsWith('@g.us')) return false;
    try {
        await sendHidetag(ctx.sock, ctx.chatJid, text, ctx.groupParticipants);
        return true;
    } catch {
        return false;
    }
}

// ── Rank level map ────────────────────────────────────────────
const RANK_LEVEL = {
    'king':     100,
    'queen':    90,
    'prince':   80,
    'princess': 80,
    'duke':     80,
    'duchess':  80,
    'lord':     70,
    'jester':   60,   // below lord (70) so jesters can't use lord-level powers
    'baron':    50,
    'player':   10,
    'guest':    0,
};

// Titles that are Royalty tier
const ROYALTY_TITLES = new Set(['king', 'queen', 'prince', 'princess', 'duke', 'duchess']);

// Valid .crown titles (king cannot be crowned, only set at deploy)
const CROWNBLE_TITLES = ['baron', 'lord', 'jester', 'queen', 'prince', 'princess', 'duke', 'duchess'];

// Ranks that ship with the bot — .delrank refuses to touch these.
const BUILTIN_RANKS = new Set(Object.keys(RANK_LEVEL));

// Custom ranks (made with .new rank, stored in custom_ranks) are merged
// into RANK_LEVEL / CROWNBLE_TITLES at startup and on creation, so every
// existing level check, .ascmd and .crown picks them up automatically.
export async function loadCustomRanks(db) {
    try {
        const res = await db.query('SELECT name, level FROM custom_ranks');
        for (const r of res.rows) {
            const name = r.name.toLowerCase();
            if (BUILTIN_RANKS.has(name)) continue;
            RANK_LEVEL[name] = r.level;
            if (!CROWNBLE_TITLES.includes(name)) CROWNBLE_TITLES.push(name);
        }
    } catch { /* table not there yet */ }
}

// ── Royalty command pool ────────────────────────────────────────
// Commands that exercise a royal power (crowning/deposing other
// players, or spawning Pokémon into the world). Every command in
// this pool is checked through checkRoyaltyGate() below, so the
// rank floor lives in ONE place instead of being hardcoded per
// command. Currently: King + Queen only (RANK_LEVEL['queen']=90).
// Raise/lower ROYALTY_MIN_LEVEL to change the floor for the whole
// pool at once, or move a command in/out of ROYALTY_POOL to change
// its membership.
const ROYALTY_POOL = new Set([
    '.crown', '.dethrone', '.spawn', '.spawnp',
]);
const ROYALTY_MIN_LEVEL = RANK_LEVEL['queen']; // King=100 and Queen=90 both pass

/**
 * Shared permission check for any command in ROYALTY_POOL.
 * A DB override from .ascmd takes precedence over the hardcoded
 * King/Queen floor — see checkCommandRank() below, which is what
 * actually enforces overrides. This stays as the pool's built-in
 * default for commands nobody has explicitly reassigned.
 * Returns null if the sender is allowed to proceed, or an error
 * string to send back (and stop dispatch) if they're not.
 */
function checkRoyaltyGate(cmd, senderLevel) {
    if (!ROYALTY_POOL.has(cmd)) return null; // not a royalty command — no gate
    if (senderLevel < ROYALTY_MIN_LEVEL) {
        return `👑 _Only the King or Queen can use ${cmd}._`;
    }
    return null;
}

// ── Global command-rank overrides ───────────────────────────────
// In-process cache of command_ranks so every message dispatch
// doesn't hit the DB. Refreshed on write (.ascmd) and on a TTL.
let _cmdRankCache = null;      // Map<cmd, rank>
let _cmdRankCacheTs = 0;
const CMD_RANK_CACHE_TTL = 60_000;

async function _loadCommandRanks(db) {
    if (_cmdRankCache && Date.now() - _cmdRankCacheTs < CMD_RANK_CACHE_TTL) return _cmdRankCache;
    try {
        const res = await db.query('SELECT cmd, min_rank FROM command_ranks');
        _cmdRankCache = new Map(res.rows.map(r => [r.cmd, r.min_rank.toLowerCase()]));
    } catch {
        _cmdRankCache = _cmdRankCache || new Map();
    }
    _cmdRankCacheTs = Date.now();
    return _cmdRankCache;
}

/**
 * Global gate checked for EVERY command before dispatch. If an
 * admin has assigned this command a rank via .ascmd, the sender
 * must be at least that rank (or higher) to use it — this OVERRIDES
 * any other permission logic for that command, royalty pool included.
 * Returns { denied, overrides } — denied is null if allowed, or a
 * denial string to send back. overrides is the loaded Map so the
 * caller can check hasOverride without a second DB round-trip.
 */
async function checkCommandRankOverride(db, cmd, senderLevel) {
    const overrides = await _loadCommandRanks(db);
    if (!overrides.has(cmd)) return { denied: null, overrides }; // no override — defer to normal checks
    const requiredLevel = getRankLevel(overrides.get(cmd));
    if (senderLevel < requiredLevel) {
        return { denied: `🔒 _${cmd} requires ${rankBadge(overrides.get(cmd))} or higher._`, overrides };
    }
    return { denied: null, overrides };
}

// Used by index.js so .ascmd also covers commands handled there
// (.linkgroup etc.). Returns the assigned minimum rank, or null.
export async function getCommandOverrideRank(db, cmd) {
    const overrides = await _loadCommandRanks(db);
    return overrides.get(cmd) || null;
}

// The one true King
const KING_NUMBER = process.env.KING_NUMBER;
const KING_JID    = `${KING_NUMBER}@s.whatsapp.net`;

// ── Default messages ──────────────────────────────────────────
const DEFAULT_WELCOME = `👋 Welcome to {group}, {name}! Type *.start* to begin your journey in Niflheim.`;
const DEFAULT_LEAVE   = `🚪 *{name}* has left {group}. Safe travels.`;
const DEFAULT_RULES   = `📜 *Group Rules*\n\n1. Be respectful\n2. No spam\n3. Have fun\n\n_Type *.start* to join the game._`;

const MAX_WARNINGS = 5;

// Default message threshold for .active — overridable per group via .setactive
const DEFAULT_ACTIVE_THRESHOLD = 5;

// How recent a cached presence.update has to be to count as "online"
// for .online (Baileys only pushes updates for JIDs we've subscribed to).
const ONLINE_WINDOW_MS = 2 * 60 * 1000;


// ============================================================
// DATABASE SETUP
// ============================================================

export async function setupCommandsTables(db) {
    await db.query(`
        CREATE TABLE IF NOT EXISTS bot_ranks (
            jid         TEXT NOT NULL,
            phone       TEXT,
            lid         TEXT,
            rank        TEXT NOT NULL,
            group_jid   TEXT,
            granted_by  TEXT,
            granted_at  TIMESTAMPTZ DEFAULT NOW()
        )
    `);
    // Add columns if table already exists (safe migration)
    await db.query('ALTER TABLE bot_ranks ADD COLUMN IF NOT EXISTS phone TEXT');
    await db.query('ALTER TABLE bot_ranks ADD COLUMN IF NOT EXISTS lid TEXT');
    // group_jid: NULL means a global rank (king/queen/lord/etc — one
    // row per person, unaffected by group). A non-NULL group_jid
    // means the rank only applies inside that group — used
    // exclusively for baron, since WA admin itself is inherently
    // per-group (the same person can be admin in one group chat and
    // not another), so the bot's baron rank now mirrors that instead
    // of one global row incorrectly applying everywhere.
    await db.query('ALTER TABLE bot_ranks ADD COLUMN IF NOT EXISTS group_jid TEXT');
    // jid was PRIMARY KEY before this migration (one row per person,
    // period). Dropping that and replacing it with a partial unique
    // index per NULL-ness of group_jid: one global row per jid
    // (group_jid IS NULL), plus one row per (jid, group_jid) pair for
    // baron. A plain UNIQUE(jid, group_jid) does NOT work here —
    // Postgres treats every NULL as distinct for uniqueness purposes,
    // so it would silently allow duplicate global rows instead of
    // enforcing "only one global rank per person."
    await db.query('ALTER TABLE bot_ranks DROP CONSTRAINT IF EXISTS bot_ranks_pkey');
    await db.query(`
        CREATE UNIQUE INDEX IF NOT EXISTS bot_ranks_global_uidx
        ON bot_ranks (jid) WHERE group_jid IS NULL
    `);
    await db.query(`
        CREATE UNIQUE INDEX IF NOT EXISTS bot_ranks_group_uidx
        ON bot_ranks (jid, group_jid) WHERE group_jid IS NOT NULL
    `);

    await db.query(`
        CREATE TABLE IF NOT EXISTS group_settings (
            group_jid   TEXT PRIMARY KEY,
            welcome_msg TEXT,
            leave_msg   TEXT,
            rules       TEXT,
            updated_at  TIMESTAMPTZ DEFAULT NOW()
        )
    `);
    // NULL prefix means "use the default '.'"
    await db.query('ALTER TABLE group_settings ADD COLUMN IF NOT EXISTS prefix TEXT');
    // Antilink: NULL/'off' = disabled, 'delete' = delete link messages,
    // 'warn' = delete + add a warning, 'kick' = delete + remove the sender.
    await db.query('ALTER TABLE group_settings ADD COLUMN IF NOT EXISTS antilink TEXT');

    await db.query(`
        CREATE TABLE IF NOT EXISTS warnings (
            group_jid   TEXT,
            user_jid    TEXT,
            count       INTEGER DEFAULT 0,
            warned_by   TEXT,
            updated_at  TIMESTAMPTZ DEFAULT NOW(),
            PRIMARY KEY (group_jid, user_jid)
        )
    `);

    await db.query(`
        CREATE TABLE IF NOT EXISTS activity_counts (
            group_jid   TEXT,
            user_jid    TEXT,
            msg_count   INTEGER DEFAULT 0,
            updated_at  TIMESTAMPTZ DEFAULT NOW(),
            PRIMARY KEY (group_jid, user_jid)
        )
    `);

    // Per-day message counts, used for the rolling 7-day window that
    // .active/.inactive actually report on. activity_counts above stays
    // as the all-time total (still useful, e.g. for future stats), but
    // is no longer what .active reads from.
    await db.query(`
        CREATE TABLE IF NOT EXISTS activity_daily (
            group_jid   TEXT,
            user_jid    TEXT,
            day         DATE,
            msg_count   INTEGER DEFAULT 0,
            PRIMARY KEY (group_jid, user_jid, day)
        )
    `);
    await db.query('CREATE INDEX IF NOT EXISTS idx_activity_daily_group_day ON activity_daily (group_jid, day)');

    // NULL threshold means "use DEFAULT_ACTIVE_THRESHOLD"
    await db.query('ALTER TABLE group_settings ADD COLUMN IF NOT EXISTS active_threshold INTEGER');

    // ── Command rank overrides (global — set via .ascmd/.assigncmd) ──
    // A row here means: this command's floor is now this rank's level,
    // system-wide, overriding whatever the command's built-in default is.
    await db.query(`
        CREATE TABLE IF NOT EXISTS command_ranks (
            cmd         TEXT PRIMARY KEY,
            min_rank    TEXT NOT NULL,
            assigned_by TEXT,
            assigned_at TIMESTAMPTZ DEFAULT NOW()
        )
    `);

    // Custom ranks created with .new rank (hardcoded ranks are NOT stored here)
    await db.query(`
        CREATE TABLE IF NOT EXISTS custom_ranks (
            name       TEXT PRIMARY KEY,
            level      INTEGER NOT NULL,
            created_by TEXT,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
    `);
    await loadCustomRanks(db);

    // Seed the King if not present. group_jid stays NULL — king is
    // global, not per-group. ON CONFLICT targets the partial unique
    // index (bot_ranks_global_uidx) rather than the old jid-only
    // primary key, which no longer exists after the per-group baron
    // migration above.
    await db.query(`
        INSERT INTO bot_ranks (jid, phone, rank, granted_by)
        VALUES ($1, $1, 'king', 'system')
        ON CONFLICT (jid) WHERE group_jid IS NULL DO NOTHING
    `, [KING_JID]);

    // ── Moderation flags (.mute/.unmute, .ignore/.unignore) ──────
    // muted   -> messages are deleted (enforced in index.js via delete key)
    // ignored -> messages are silently dropped, not deleted
    // Independent flags, own table — not reusing warnings.count anymore.
    await db.query(`
        CREATE TABLE IF NOT EXISTS moderation (
            group_jid   TEXT,
            user_jid    TEXT,
            muted       BOOLEAN DEFAULT FALSE,
            ignored     BOOLEAN DEFAULT FALSE,
            updated_by  TEXT,
            updated_at  TIMESTAMPTZ DEFAULT NOW(),
            PRIMARY KEY (group_jid, user_jid)
        )
    `);
}


// ============================================================
// RANK HELPERS
// ============================================================

// ============================================================
// GROUP ADMIN HELPERS (LID-safe)
// Baileys 7 can key group participants by @lid with the phone JID in
// p.phoneNumber (or the reverse, depending on addressing mode). A JID we
// hold might be either form, so compare against id, lid AND phoneNumber,
// normalised to the bare number/lid user part.
// ============================================================
function _jidUser(j) {
    if (!j || typeof j !== 'string') return '';
    return j.split('@')[0].split(':')[0];
}

function _participantMatches(p, jid) {
    if (!p || !jid) return false;
    const target = _jidUser(jid);
    if (!target) return false;
    return [p.id, p.lid, p.phoneNumber, p.jid].some(v => v && _jidUser(v) === target);
}

export function isGroupAdmin(jid, groupParticipants = []) {
    const p = (groupParticipants || []).find(x => _participantMatches(x, jid));
    return p?.admin === 'admin' || p?.admin === 'superadmin';
}

// Is the BOT itself a group admin? (Needed for .close/.open/antilink deletes.)
export function isBotGroupAdmin(sock, groupParticipants = []) {
    const ids = [sock?.user?.id, sock?.user?.lid, sock?.user?.jid].filter(Boolean);
    return ids.some(id => isGroupAdmin(id, groupParticipants));
}

// Get rank for a JID. Checks DB first (group-scoped row for this
// group, if any, AND the global row), returning whichever resolves
// higher — then WA admin list as a last resort.
export async function getRank(db, jid, groupParticipants = [], isRegistered = false, group_jid = null) {
    // Always return king for the king
    if (jid === KING_JID || jid.startsWith(KING_NUMBER + '@')) return 'king';

    try {
        // A person can hold a global rank (king/queen/lord/etc, one
        // row, group_jid IS NULL) AND a separate group-scoped baron
        // row at the same time — e.g. crowned Prince globally but
        // also happens to be a plain group-scoped Baron somewhere
        // that predates the crown. Take whichever is actually higher
        // rather than assuming group always wins — a global Prince
        // must never resolve down to group-scoped Baron just because
        // this check happens inside that group. Callers with no group
        // context (group_jid left null) just get the global row, same
        // as before this parameter existed.
        const globalRes = await db.query(
            `SELECT rank FROM bot_ranks
             WHERE (jid = $1 OR phone = $1 OR lid = $1) AND group_jid IS NULL`,
            [jid]
        );
        const globalRank = globalRes.rows.length ? globalRes.rows[0].rank.toLowerCase() : null;

        let groupRank = null;
        if (group_jid) {
            const groupRes = await db.query(
                `SELECT rank FROM bot_ranks
                 WHERE (jid = $1 OR phone = $1 OR lid = $1) AND group_jid = $2`,
                [jid, group_jid]
            );
            groupRank = groupRes.rows.length ? groupRes.rows[0].rank.toLowerCase() : null;
        }

        if (globalRank && groupRank) {
            return getRankLevel(globalRank) >= getRankLevel(groupRank) ? globalRank : groupRank;
        }
        if (globalRank || groupRank) return globalRank || groupRank;
    } catch {}

    // Check if WA group admin (covers pre-existing admins, not just bot-promoted ones).
    // Uses isGroupAdmin() so LID-addressed groups work: index.js resolves the
    // sender to a phone JID, but Baileys 7 participants can be keyed by @lid
    // (p.id = lid, p.phoneNumber = phone jid) — matching on p.id alone never
    // found the sender there, so real WA admins were being ranked as players.
    if (isGroupAdmin(jid, groupParticipants)) {
        return 'baron'; // WA admins are baron-tier
    }

    // Registered players outrank guests
    if (isRegistered) return 'player';

    return 'guest';
}

export function getRankLevel(rank) {
    return RANK_LEVEL[rank?.toLowerCase()] ?? 0;
}

// Can actor perform an action on target?
// Returns { allowed: bool, reason: string }
export function canActOn(actorRank, targetRank) {
    const actorLevel  = getRankLevel(actorRank);
    const targetLevel = getRankLevel(targetRank);

    if (targetRank === 'king') {
        return { allowed: false, reason: `👑 _The King is untouchable._` };
    }
    if (targetRank === 'queen' && actorRank !== 'king') {
        return { allowed: false, reason: `👑 _Only the King may act upon a Queen._` };
    }
    if (actorLevel <= targetLevel) {
        return {
            allowed: false,
            reason: targetLevel >= RANK_LEVEL['prince']
                ? `🛡️ _You dare raise a hand against Royalty of Niflheim?_`
                : `⚔️ _You cannot act on someone of equal or higher rank._`
        };
    }
    return { allowed: true, reason: null };
}

// Format rank for display
export function rankBadge(rank) {
    const badges = {
        king:     '👑 King',
        queen:    '👑 Queen',
        prince:   '🤴 Prince',
        princess: '👸 Princess',
        duke:     '🎖️ Duke',
        duchess:  '🎖️ Duchess',
        lord:     '⚔️ Lord',
        jester:   '🃏 Jester',
        baron:    '🏅 Baron',
        player:   '🧭 Player',
        guest:    '👤 Guest',
    };
    const key = rank?.toLowerCase();
    if (badges[key]) return badges[key];
    if (key && key in RANK_LEVEL) return `🔰 ${key.charAt(0).toUpperCase()}${key.slice(1)}`;   // custom rank
    return '👤 Guest';
}

// ============================================================
// UNIVERSAL TAG CONVERTER
// Any jid — a real @s.whatsapp.net phone jid OR an opaque @lid —
// in: a real WhatsApp phone number tag, "@<number>". @lid values
// aren't phone numbers themselves, so they're resolved through
// groupParticipants (p.lid → p.id/p.phoneNumber) same as the
// sender-resolution logic in index.js. Falls back to the raw
// jid's left side if it can't be resolved, so output is never
// blank — worst case it prints an unreadable lid instead of a tag.
// ============================================================

// Resolves a jid (possibly an @lid) to the real phone jid, using
// groupParticipants the same way toTag() does for display. Returns
// null if it can't be resolved (unlike toTag, which always falls
// back to something printable) — callers that need to match this
// jid against data keyed by phone jid (e.g. activity tracking) need
// to know resolution actually failed, not just get a fallback string.
function _resolveToPhoneJid(jid, groupParticipants = []) {
    if (!jid) return null;
    if (jid.endsWith('@s.whatsapp.net')) return jid;
    if (jid.endsWith('@lid')) {
        const found = groupParticipants.find(p => p.lid === jid || p.id === jid);
        if (found?.phoneNumber) {
            return found.phoneNumber.endsWith('@s.whatsapp.net')
                ? found.phoneNumber
                : `${found.phoneNumber.split('@')[0]}@s.whatsapp.net`;
        }
        if (found?.id?.endsWith('@s.whatsapp.net')) return found.id;
        return null; // genuinely unresolvable from what we have on hand
    }
    return jid;
}

export function toTag(jid, groupParticipants = []) {
    if (!jid) return '';

    if (jid.endsWith('@s.whatsapp.net')) {
        return `@${jid.split('@')[0]}`;
    }

    if (jid.endsWith('@lid')) {
        const resolved = _resolveToPhoneJid(jid, groupParticipants);
        if (resolved) return `@${resolved.split('@')[0]}`;
        // Unresolved lid — no phone number available from what we have on hand
        return `@${jid.split('@')[0]}`;
    }

    // Anything else (already a bare number, unexpected format, etc.)
    return `@${jid.split('@')[0]}`;
}


// ============================================================
// COMMAND HANDLER
// Entry point — call this from index.js handleMessage()
// Returns response string or null (not a bot command)
// ============================================================

export async function handleBotCommand(ctx) {
    const { sock, db, msg, chatJid, senderJid, text, mentionedJid, groupParticipants, isRegistered } = ctx;

    const lower = text.trim().toLowerCase();
    const parts = text.trim().split(/\s+/);
    const cmd   = parts[0].toLowerCase();
    const args  = parts.slice(1);

    // Resolve ranks. group_jid only when chatJid is actually a group —
    // this dispatcher also handles DM commands, where a per-group
    // baron row would never apply (there is no group).
    const groupJidForRank = chatJid?.endsWith('@g.us') ? chatJid : null;
    const senderRank = await getRank(db, senderJid, groupParticipants, isRegistered, groupJidForRank);
    let senderLevel = getRankLevel(senderRank);

    // ── Global command-rank override gate — checked first, since an
    // .ascmd assignment overrides ANY other permission logic below,
    // including the hardcoded royalty pool floor.
    const { denied: overrideDenied, overrides } = await checkCommandRankOverride(db, cmd, senderLevel);
    if (overrideDenied) return overrideDenied;

    // ── Royalty pool gate — one check covers every command in
    // ROYALTY_POOL, so the King/Queen floor is enforced consistently
    // instead of each command hardcoding its own copy of the check.
    // Skipped if this command already has an .ascmd override (handled
    // above), since the override fully replaces this default. Reuses
    // the `overrides` map from the call above instead of loading it
    // a second time.
    const hasOverride = overrides.has(cmd);
    const royaltyDenied = hasOverride ? null : checkRoyaltyGate(cmd, senderLevel);
    if (royaltyDenied) return royaltyDenied;

    // An .ascmd assignment REPLACES the command's own built-in rank floor
    // (every _cmdX below has a "senderLevel < baron/lord/king" check). The
    // sender already passed the override gate above, so hand the command
    // top-level clearance for those floors. Who they can act ON is still
    // decided by canActOn(senderRank, targetRank), which uses their real rank.
    if (hasOverride) senderLevel = RANK_LEVEL['king'];

    // ── .crown [title] @user ─────────────────────────────────
    if (cmd === '.crown') {
        return _cmdCrown(ctx, senderRank, senderLevel, args, mentionedJid);
    }

    // ── .dethrone @user ──────────────────────────────────────
    if (cmd === '.dethrone') {
        return _cmdDethrone(ctx, senderRank, senderLevel, mentionedJid);
    }

    // ── .promote @user ───────────────────────────────────────
    if (cmd === '.promote') {
        return _cmdPromote(ctx, senderRank, senderLevel, mentionedJid);
    }

    // ── .demote @user ────────────────────────────────────────
    if (cmd === '.demote') {
        return _cmdDemote(ctx, senderRank, senderLevel, mentionedJid);
    }

    // ── .warn @user ──────────────────────────────────────────
    if (cmd === '.warn') {
        return _cmdWarn(ctx, senderRank, senderLevel, mentionedJid);
    }

    // ── .warnings @user ──────────────────────────────────────
    if (cmd === '.warnings') {
        return _cmdWarnings(ctx, senderLevel, mentionedJid);
    }

    // ── .clearwarns @user (aliases: .resetwarn, .resetwarns) ─────────
    if (cmd === '.clearwarns' || cmd === '.resetwarn' || cmd === '.resetwarns') {
        return _cmdClearWarns(ctx, senderRank, senderLevel, mentionedJid);
    }

    // ── .kick @user ──────────────────────────────────────────
    if (cmd === '.kick') {
        return _cmdKick(ctx, senderRank, senderLevel, mentionedJid);
    }

    // ── .mute @user ──────────────────────────────────────────
    if (cmd === '.mute') {
        return _cmdMute(ctx, senderRank, senderLevel, mentionedJid, args);
    }

    // ── .unmute @user ────────────────────────────────────────
    if (cmd === '.unmute') {
        return _cmdUnmute(ctx, senderRank, senderLevel, mentionedJid);
    }

    // ── .ignore @user ────────────────────────────────────────
    if (cmd === '.ignore') {
        return _cmdIgnore(ctx, senderRank, senderLevel, mentionedJid);
    }

    // ── .unignore @user ──────────────────────────────────────
    if (cmd === '.unignore') {
        return _cmdUnignore(ctx, senderRank, senderLevel, mentionedJid);
    }

    // ── .close / .open — lock/unlock the group (admins-only messaging) ──
    if (cmd === '.close') {
        return _cmdGroupLock(ctx, senderLevel, true);
    }
    if (cmd === '.open') {
        return _cmdGroupLock(ctx, senderLevel, false);
    }

    // ── .antilink [on|off|warn|kick|status] ───────────────────
    if (cmd === '.antilink') {
        return _cmdAntilink(ctx, senderLevel, args);
    }

    // ── .tagall [message] ────────────────────────────────────
    if (cmd === '.tagall') {
        return _cmdTagAll(ctx, senderLevel, args);
    }

    // ── .setwelcome [message] / .setwelcome (reset) ──────────
    if (cmd === '.setwelcome') {
        return _cmdSetWelcome(ctx, senderLevel, args);
    }

    // ── .setleave [message] / .setleave (reset) ──────────────
    if (cmd === '.setleave') {
        return _cmdSetLeave(ctx, senderLevel, args);
    }

    // ── .setrules [message] (Lord+ only) ─────────────────────
    if (cmd === '.setrules') {
        return _cmdSetRules(ctx, senderRank, senderLevel, args);
    }

    // ── .setprefix <symbol> / .setprefix . (reset) / .setprefix (show current)
    if (cmd === '.setprefix') {
        return _cmdSetPrefix(ctx, senderLevel, args);
    }

    // ── .rules ───────────────────────────────────────────────
    if (cmd === '.rules') {
        return _cmdRules(ctx);
    }

    // ── .pin [message] ───────────────────────────────────────
    if (cmd === '.pin') {
        return _cmdPin(ctx, senderLevel, args);
    }

    // ── .invite ──────────────────────────────────────────────
    if (cmd === '.invite') {
        return _cmdInvite(ctx, args);
    }

    // ── .menu ────────────────────────────────────────────────
    if (cmd === '.menu') {
        return _cmdMenu();
    }

    // ── .pmenu ───────────────────────────────────────────────
    if (cmd === '.pmenu') {
        return _cmdPmenu(ctx);
    }

    // ── .ranks ───────────────────────────────────────────────
    if (cmd === '.ranks') {
        return _cmdRanks(ctx);
    }

    // ── .whois @user ─────────────────────────────────────────
    if (cmd === '.whois') {
        return _cmdWhois(ctx, mentionedJid);
    }

    // ── .active [message] ─────────────────────────────────────
    if (cmd === '.active') {
        return _cmdActive(ctx, args);
    }

    // ── .inactive ────────────────────────────────────────────
    if (cmd === '.inactive') {
        return _cmdInactive(ctx);
    }

    // ── .setactive <x> — King only ──────────────────────────
    if (cmd === '.setactive') {
        return _cmdSetActive(ctx, senderRank, args);
    }

    // ── .online ──────────────────────────────────────────────
    if (cmd === '.online') {
        return _cmdOnline(ctx);
    }

    // ── .admin ───────────────────────────────────────────────
    if (cmd === '.admin') {
        return _cmdAdmin(ctx);
    }

    // ── .ascmd / .assigncmd <cmd> <rank> — King/Queen only ──
    if (cmd === '.ascmd' || cmd === '.assigncmd') {
        return _cmdAssignCmd(ctx, senderRank, senderLevel, args);
    }

    // ── .new rank <name> <power> / .delrank <name> — King/Queen only ──
    if (cmd === '.new' && (args[0] || '').toLowerCase() === 'rank') {
        return _cmdNewRank(ctx, senderRank, senderLevel, args);
    }
    if (cmd === '.delrank') {
        return _cmdDelRank(ctx, senderRank, senderLevel, args);
    }

    // ── .spawn [name] [zone] ──────────────────────────────────
    if (cmd === '.spawn') {
        return _cmdSpawn(ctx, senderRank, senderLevel, args);
    }

    // ── .spawnp [name] ───────────────────────────────────────
    if (cmd === '.spawnp') {
        return _cmdSpawnP(ctx, senderRank, senderLevel, args);
    }

    return null; // not a bot command — fall through to game layer
}


// ============================================================
// WELCOME / LEAVE EVENTS
// Call these from sock.ev.on('group-participants.update')
// ============================================================

export async function onMemberJoin(ctx, joinedJid) {
    // Normalize — Baileys may pass an object
    if (typeof joinedJid === 'object') joinedJid = joinedJid.id || joinedJid.jid || String(joinedJid);
    const { sock, db, chatJid, groupParticipants } = ctx;
    const settings = await _getGroupSettings(db, chatJid);
    const template = settings?.welcome_msg || DEFAULT_WELCOME;

    let groupName = 'the group';
    try {
        const meta = await sock.groupMetadata(chatJid);
        groupName  = meta.subject || groupName;
    } catch {}

    const num     = toTag(joinedJid, groupParticipants).slice(1); // strip leading @ — used bare below too
    const message = template
        .replace(/{name}/g,  `@${num}`)
        .replace(/{group}/g, groupName)
        .replace(/{number}/g, num);

    try {
        await sock.sendMessage(chatJid, {
            text:     message,
            mentions: [joinedJid],
        });
    } catch {}
}

export async function onMemberLeave(ctx, leftJid) {
    // Normalize — Baileys may pass an object
    if (typeof leftJid === 'object') leftJid = leftJid.id || leftJid.jid || String(leftJid);
    const { sock, db, chatJid } = ctx;
    const settings = await _getGroupSettings(db, chatJid);
    const template = settings?.leave_msg || DEFAULT_LEAVE;

    let groupName = 'the group';
    let meta = null;
    try {
        meta = await sock.groupMetadata(chatJid);
        groupName = meta.subject || groupName;
    } catch {}

    const num     = toTag(leftJid, meta?.participants || []).slice(1);
    const message = template
        .replace(/{name}/g,  `@${num}`)
        .replace(/{group}/g, groupName)
        .replace(/{number}/g, num);

    try {
        await sock.sendMessage(chatJid, { text: message });
    } catch {}
}


// ============================================================
// COMMAND IMPLEMENTATIONS
// ============================================================

async function _cmdCrown(ctx, senderRank, senderLevel, args, mentionedJid) {
    const { sock, db, chatJid } = ctx;

    const title = args[0]?.toLowerCase();
    if (!title || !CROWNBLE_TITLES.includes(title)) {
        return (
            `👑 *.crown [title] @user*\n\n` +
            `Valid titles:\n` +
            CROWNBLE_TITLES.map(t => `• ${t}`).join('\n')
        );
    }

    if (!mentionedJid) return `⚠️ _Tag someone to crown. Example: *.crown queen @user*_`;

    // Queens cannot crown other Queens (only King can)
    if (title === 'queen' && senderRank !== 'king') {
        return `👑 _Only the King may crown a Queen._`;
    }

    const targetRank = await getRank(db, mentionedJid, ctx.groupParticipants, false, ctx.chatJid);
    if (targetRank === 'king') return `👑 _The King is untouchable._`;

    const num = toTag(mentionedJid, ctx.groupParticipants).slice(1);
    const niceTitle = title.charAt(0).toUpperCase() + title.slice(1);

    // Already holds this title — nothing changes, so nothing is announced.
    if (targetRank === title) return `_@${num} is already ${niceTitle}._`;

    // Baron writes a group-scoped row (group_jid = this group);
    // every other title writes a global row (group_jid NULL) — see
    // the bot_ranks migration in setupCommandsTables for why. The
    // ON CONFLICT target must match: (jid) WHERE group_jid IS NULL
    // for global titles, (jid, group_jid) for baron, since a plain
    // ON CONFLICT (jid) no longer matches any real constraint after
    // that migration.
    if (title === 'baron') {
        await db.query(`
            INSERT INTO bot_ranks (jid, rank, group_jid, granted_by, granted_at)
            VALUES ($1, 'baron', $2, $3, NOW())
            ON CONFLICT (jid, group_jid) WHERE group_jid IS NOT NULL DO UPDATE
            SET rank = 'baron', granted_by = $3, granted_at = NOW()
        `, [mentionedJid, ctx.chatJid, ctx.senderJid]);
    } else {
        await db.query(`
            INSERT INTO bot_ranks (jid, rank, group_jid, granted_by, granted_at)
            VALUES ($1, $2, NULL, $3, NOW())
            ON CONFLICT (jid) WHERE group_jid IS NULL DO UPDATE
            SET rank = $2, granted_by = $3, granted_at = NOW()
        `, [mentionedJid, title, ctx.senderJid]);
    }

    // Baron IS admin — same rank, two names (see .promote) — so
    // crowning baron specifically also grants real WA admin. Every
    // other title (queen, lord, duchess, etc.) is DB-only: it never
    // grants or revokes WA admin. If the target already holds WA
    // admin from an earlier .promote/.crown baron, crowning them a
    // different title leaves that admin status untouched — they end
    // up admin AND queen (for example) simultaneously, just no
    // longer ranked baron specifically.
    if (title === 'baron') {
        try {
            await sock.groupParticipantsUpdate(chatJid, [mentionedJid], 'promote');
        } catch (e) {
            // DB row is already written — don't fail the whole command
            // over a WA-side hiccup (e.g. Ariel not admin in this
            // group), just flag it so the split doesn't go unnoticed.
            const badge = rankBadge(title);
            return `${badge} *@${num}* has been crowned *Baron* of Niflheim, but WA admin could not be granted — make sure Ariel is a group admin.`;
        }
    }

    const badge = rankBadge(title);
    const announcement =
        `👑 ${toScript('By royal decree,')} @${num} ${toScript('has been crowned')}\n\n` +
        `${badge.split(' ')[0]} ${toScript(`${niceTitle} of Niflheim`)} ${badge.split(' ')[0]}`;
    if (await _announce(ctx, announcement)) return REPLY_HANDLED;
    return `${badge} *@${num}* has been crowned *${niceTitle}* of Niflheim. 👑`;
}

async function _cmdDethrone(ctx, senderRank, senderLevel, mentionedJid) {
    const { sock, db, chatJid } = ctx;

    if (!mentionedJid) return `⚠️ _Tag someone to dethrone._`;

    const targetRank = await getRank(db, mentionedJid, ctx.groupParticipants, false, chatJid);
    const check      = canActOn(senderRank, targetRank);
    if (!check.allowed) return check.reason;

    // Delete only the specific row that actually resolved to
    // targetRank, not every row for this jid. Someone can hold both
    // a global row (e.g. crowned Prince) and a separate group-scoped
    // baron row at once — a blanket DELETE WHERE jid=$1 would wipe
    // both, silently stripping a rank .dethrone was never asked to
    // touch. If they're baron here specifically via the group-scoped
    // row, remove only that; otherwise remove their global row.
    const num = toTag(mentionedJid, ctx.groupParticipants).slice(1);
    const hadGroupRow = (await db.query(
        `SELECT 1 FROM bot_ranks WHERE (jid = $1 OR phone = $1 OR lid = $1) AND group_jid = $2`,
        [mentionedJid, chatJid]
    )).rows.length > 0;
    const hadGlobalRow = (await db.query(
        `SELECT 1 FROM bot_ranks WHERE (jid = $1 OR phone = $1 OR lid = $1) AND group_jid IS NULL`,
        [mentionedJid]
    )).rows.length > 0;
    // Nothing to strip (no title row, and not a WA-admin Baron) = no-op, no announcement.
    if (!hadGroupRow && !hadGlobalRow && targetRank !== 'baron') {
        return `_@${num} doesn't hold a title to remove._`;
    }

    // Strip only the row that resolved to targetRank: a Prince who is
    // also a Baron here loses Prince only; the Baron row stays (.demote
    // is what removes that).
    if (targetRank === 'baron') {
        await db.query(
            `DELETE FROM bot_ranks WHERE (jid = $1 OR phone = $1 OR lid = $1) AND group_jid = $2`,
            [mentionedJid, chatJid]
        );
    } else {
        await db.query(
            `DELETE FROM bot_ranks WHERE (jid = $1 OR phone = $1 OR lid = $1) AND group_jid IS NULL`,
            [mentionedJid]
        );
    }

    // Mirror of .crown: dethroning a Baron also revokes real WA
    // admin, since baron/admin are the same rank. Dethroning any
    // other title is DB-only — it was never granted through WA
    // admin in the first place (unless they separately hold admin
    // from a past baron crown/promote, in which case this correctly
    // leaves that untouched, matching how crowning them didn't touch
    // it either).
    if (targetRank === 'baron') {
        try {
            await sock.groupParticipantsUpdate(chatJid, [mentionedJid], 'demote');
        } catch (e) {
            return `⚔️ *@${num}* has been dethroned, but WA admin could not be revoked — make sure Ariel is a group admin.`;
        }
    }

    const lostTitle = targetRank.charAt(0).toUpperCase() + targetRank.slice(1);
    const announcement =
        `⚔️ @${num} ${toFraktur('has been stripped of the title of')}\n\n` +
        `${toFraktur(lostTitle)} — ${toFraktur('dethroned.')} 🥀`;
    if (await _announce(ctx, announcement)) return REPLY_HANDLED;
    return `⚔️ *@${num}* has been dethroned.`;
}

async function _cmdPromote(ctx, senderRank, senderLevel, mentionedJid) {
    const { sock, db, chatJid, msg } = ctx;

    // Baron+ can promote
    if (senderLevel < RANK_LEVEL['baron']) {
        return `⚠️ _You don't have permission to promote._`;
    }
    if (!mentionedJid) return `⚠️ _Tag someone to promote._`;

    const targetRank = await getRank(db, mentionedJid, ctx.groupParticipants, false, ctx.chatJid);
    const check      = canActOn(senderRank, targetRank);
    if (!check.allowed) return check.reason;

    // Same action as .crown baron for the WA-admin side — but unlike
    // .crown baron, .promote must never overwrite an existing higher
    // rank. canActOn only checks the ACTOR outranks the target, not
    // whether the target already outranks baron — a King promoting a
    // Prince passes that check fine, so without this guard it would
    // silently downgrade the Prince's bot_ranks row to baron. Grant
    // WA admin regardless (harmless/idempotent if already admin), but
    // only touch the DB row if they're not already baron-or-above.
    try {
        await sock.groupParticipantsUpdate(chatJid, [mentionedJid], 'promote');
    } catch (e) {
        return `⚠️ _Could not promote — make sure Ariel is a group admin._`;
    }

    const num = toTag(mentionedJid, ctx.groupParticipants).slice(1);

    await db.query(`
        INSERT INTO bot_ranks (jid, rank, group_jid, granted_by, granted_at)
        VALUES ($1, 'baron', $2, $3, NOW())
        ON CONFLICT (jid, group_jid) WHERE group_jid IS NOT NULL DO UPDATE
        SET rank = 'baron', granted_by = $3, granted_at = NOW()
    `, [mentionedJid, chatJid, ctx.senderJid]);

    return `🛡️ *@${num}* has been promoted to group admin.`;
}

async function _cmdDemote(ctx, senderRank, senderLevel, mentionedJid) {
    const { sock, db, chatJid } = ctx;

    // Baron+ can demote
    if (senderLevel < RANK_LEVEL['baron']) {
        return `⚠️ _You don't have permission to demote._`;
    }
    if (!mentionedJid) return `⚠️ _Tag someone to demote._`;

    const targetRank = await getRank(db, mentionedJid, ctx.groupParticipants, false, ctx.chatJid);
    const check      = canActOn(senderRank, targetRank);
    if (!check.allowed) return check.reason;

    try {
        await sock.groupParticipantsUpdate(chatJid, [mentionedJid], 'demote');
    } catch (e) {
        return `⚠️ _Could not demote — make sure Ariel is a group admin._`;
    }

    // Mirror of .promote: revoking WA admin also clears the
    // group-scoped baron row here, since they're the same rank in
    // this group. Baron rows are per-group now — scope the delete to
    // chatJid so this doesn't reach into a baron row from a different
    // group. If the target is actually crowned something else (queen,
    // lord, etc, a global row) that also happened to hold WA admin,
    // leave that alone — demoting WA admin doesn't strip a
    // higher/different crowned title, only the baron identity
    // specifically.
    await db.query(
        `DELETE FROM bot_ranks WHERE (jid = $1 OR phone = $1 OR lid = $1) AND group_jid = $2`,
        [mentionedJid, chatJid]
    );

    const num = toTag(mentionedJid, ctx.groupParticipants).slice(1);
    return `📉 *@${num}* has been demoted.`;
}

async function _cmdWarn(ctx, senderRank, senderLevel, mentionedJid) {
    const { sock, db, chatJid, msg } = ctx;

    // Baron+ can warn
    if (senderLevel < RANK_LEVEL['baron']) {
        return `⚠️ _You don't have permission to warn._`;
    }
    if (!mentionedJid) return `⚠️ _Tag someone to warn._`;

    const targetRank = await getRank(db, mentionedJid, ctx.groupParticipants, false, ctx.chatJid);
    const check      = canActOn(senderRank, targetRank);
    if (!check.allowed) return check.reason;

    // Upsert warning
    const res = await db.query(`
        INSERT INTO warnings (group_jid, user_jid, count, warned_by, updated_at)
        VALUES ($1, $2, 1, $3, NOW())
        ON CONFLICT (group_jid, user_jid) DO UPDATE
        SET count     = warnings.count + 1,
            warned_by = $3,
            updated_at = NOW()
        RETURNING count
    `, [chatJid, mentionedJid, ctx.senderJid]);

    const count = res.rows[0].count;
    const num   = toTag(mentionedJid, ctx.groupParticipants).slice(1);

    if (count >= MAX_WARNINGS) {
        // Auto-kick
        try {
            await sock.groupParticipantsUpdate(chatJid, [mentionedJid], 'remove');
        } catch {}
        // Reset warnings after kick
        await db.query(
            'DELETE FROM warnings WHERE group_jid = $1 AND user_jid = $2',
            [chatJid, mentionedJid]
        );
        return (
            `⚠️ *@${num}* — Warning ${count}/${MAX_WARNINGS}\n\n` +
            `🚨 *Maximum warnings reached. @${num} has been removed from the group.*`
        );
    }

    const bars    = '🔴'.repeat(count) + '⚫'.repeat(MAX_WARNINGS - count);
    return (
        `⚠️ *@${num}* has been warned.\n\n` +
        `${bars}\n` +
        `*${count}/${MAX_WARNINGS}* warnings\n\n` +
        `_${MAX_WARNINGS - count} more warning(s) will result in removal._`
    );
}

async function _cmdWarnings(ctx, senderLevel, mentionedJid) {
    const { db, chatJid } = ctx;

    // Anyone can check warnings
    const targetJid = mentionedJid || ctx.senderJid;
    const num       = toTag(targetJid, ctx.groupParticipants).slice(1);

    const res = await db.query(
        'SELECT count FROM warnings WHERE group_jid = $1 AND user_jid = $2',
        [chatJid, targetJid]
    );

    const count = res.rows[0]?.count || 0;
    const bars  = '🔴'.repeat(count) + '⚫'.repeat(MAX_WARNINGS - count);

    return (
        `📋 *Warnings — @${num}*\n\n` +
        `${bars}\n` +
        `*${count}/${MAX_WARNINGS}*`
    );
}

async function _cmdClearWarns(ctx, senderRank, senderLevel, mentionedJid) {
    const { db, chatJid } = ctx;

    if (senderLevel < RANK_LEVEL['baron']) {
        return `⚠️ _You don't have permission to clear warnings._`;
    }
    if (!mentionedJid) return `⚠️ _Tag someone to clear warnings for._`;

    const targetRank = await getRank(db, mentionedJid, ctx.groupParticipants, false, ctx.chatJid);
    const check      = canActOn(senderRank, targetRank);
    if (!check.allowed) return check.reason;

    await db.query(
        'DELETE FROM warnings WHERE group_jid = $1 AND user_jid = $2',
        [chatJid, mentionedJid]
    );

    const num = toTag(mentionedJid, ctx.groupParticipants).slice(1);
    return `✅ _Warnings cleared for @${num}._`;
}

async function _cmdKick(ctx, senderRank, senderLevel, mentionedJid) {
    const { sock, db, chatJid } = ctx;

    if (senderLevel < RANK_LEVEL['baron']) {
        return `⚠️ _You don't have permission to kick._`;
    }
    if (!mentionedJid) return `⚠️ _Tag someone to kick._`;

    const targetRank = await getRank(db, mentionedJid, ctx.groupParticipants, false, ctx.chatJid);
    const check      = canActOn(senderRank, targetRank);
    if (!check.allowed) return check.reason;

    try {
        await sock.groupParticipantsUpdate(chatJid, [mentionedJid], 'remove');
        const num = toTag(mentionedJid, ctx.groupParticipants).slice(1);
        return `🚪 *@${num}* has been removed from the group.`;
    } catch (e) {
        return `⚠️ _Could not kick — make sure Ariel is a group admin._`;
    }
}

// ── .close / .open ────────────────────────────────────────────
// Toggles WhatsApp's "Send messages: only admins" group setting.
// Baron+ (which includes real WA group admins via getRank). The bot
// itself must be a group admin for WhatsApp to accept the change.
async function _cmdGroupLock(ctx, senderLevel, close) {
    const { sock, chatJid, groupParticipants } = ctx;

    if (!chatJid.endsWith('@g.us')) return `⚠️ _This only works in groups._`;
    if (senderLevel < RANK_LEVEL['baron']) {
        return `⚠️ _Only group admins can ${close ? 'close' : 'open'} the group._`;
    }
    if (groupParticipants?.length && !isBotGroupAdmin(sock, groupParticipants)) {
        return `⚠️ _Make Ariel a group admin first — WhatsApp won't let her ${close ? 'close' : 'open'} the group otherwise._`;
    }

    try {
        await sock.groupSettingUpdate(chatJid, close ? 'announcement' : 'not_announcement');
        return close
            ? `🔒 *Group closed.* Only admins can send messages now.\n_Use .open to reopen._`
            : `🔓 *Group opened.* Everyone can send messages again.`;
    } catch (e) {
        return `⚠️ _Could not ${close ? 'close' : 'open'} the group — make sure Ariel is a group admin._`;
    }
}

// ── .antilink ─────────────────────────────────────────────────
// Per-group link protection. Enforcement lives in index.js
// (enforceAntilink), which reads getAntilinkMode() on every group
// message; this command only sets the mode.
//   .antilink on      -> delete link messages
//   .antilink warn    -> delete + add a warning
//   .antilink kick    -> delete + remove the sender
//   .antilink off     -> disabled
//   .antilink         -> show current status
// Group admins / Baron+ are always exempt from enforcement.
const ANTILINK_MODES = { on: 'delete', delete: 'delete', warn: 'warn', kick: 'kick', off: 'off' };

export async function getAntilinkMode(db, groupJid) {
    try {
        const res = await db.query('SELECT antilink FROM group_settings WHERE group_jid = $1', [groupJid]);
        const row = res.rows?.[0] ?? res[0];
        const mode = (row?.antilink || 'off').toLowerCase();
        return ANTILINK_MODES[mode] ? (mode === 'on' ? 'delete' : mode) : 'off';
    } catch {
        return 'off';
    }
}

async function _cmdAntilink(ctx, senderLevel, args) {
    const { sock, db, chatJid, groupParticipants } = ctx;

    if (!chatJid.endsWith('@g.us')) return `⚠️ _This only works in groups._`;
    if (senderLevel < RANK_LEVEL['baron']) {
        return `⚠️ _Only group admins can change antilink settings._`;
    }

    const arg = (args[0] || '').toLowerCase();
    const current = await getAntilinkMode(db, chatJid);
    const label = { off: 'OFF', delete: 'ON (delete links)', warn: 'ON (delete + warn)', kick: 'ON (delete + kick)' };

    if (!arg || arg === 'status') {
        return `🔗 *Antilink:* ${label[current]}\n\n_Usage: .antilink on | warn | kick | off_`;
    }
    if (!(arg in ANTILINK_MODES)) {
        return `_Usage: .antilink on | warn | kick | off_`;
    }

    const mode = ANTILINK_MODES[arg];
    await db.query(`
        INSERT INTO group_settings (group_jid, antilink, updated_at)
        VALUES ($1, $2, NOW())
        ON CONFLICT (group_jid) DO UPDATE
        SET antilink = $2, updated_at = NOW()
    `, [chatJid, mode]);

    if (mode === 'off') return `🔗 *Antilink is now OFF* for this group.`;

    const botWarn = (groupParticipants?.length && !isBotGroupAdmin(sock, groupParticipants))
        ? `\n\n⚠️ _Ariel isn't a group admin yet — she can't delete messages or kick until she is._`
        : '';
    return `🔗 *Antilink is now ${label[mode]}* for this group.\n_Admins are exempt._${botWarn}`;
}

// ── Antilink enforcement ──────────────────────────────────────
// Called from index.js on every group message (after mute/ignore and
// once group metadata is loaded). Returns true if the message was
// handled (a link was found and acted on) so the caller can stop.
// Exempt: group admins (LID-safe), Baron+ bot ranks, the bot itself.
const LINK_REGEX = new RegExp(
    '(?:https?:\\/\\/|www\\.)\\S+' +                                   // http(s):// or www.
    '|\\b(?:chat\\.whatsapp\\.com|wa\\.me|t\\.me|discord\\.gg|discord\\.com\\/invite|bit\\.ly|tinyurl\\.com)\\/\\S*' + // common invite/shorteners without scheme
    '|\\b[a-z0-9-]+(?:\\.[a-z0-9-]+)*\\.(?:com|net|org|io|gg|me|co|xyz|info|ly|link|app|site|online|club|ru|to|cc|tv)\\b(?:\\/\\S*)?',
    'i'
);

export function messageContainsLink(msg) {
    const m = msg?.message || {};
    const pieces = [
        m.conversation,
        m.extendedTextMessage?.text,
        m.imageMessage?.caption,
        m.videoMessage?.caption,
        m.documentMessage?.caption,
        // Rich link previews carry the URL even when text is oddly formatted
        m.extendedTextMessage?.matchedText,
    ].filter(Boolean);
    return pieces.some(t => LINK_REGEX.test(t));
}

export async function enforceAntilink(ctx) {
    const { sock, db, msg, chatJid, senderJid, groupParticipants } = ctx;

    if (!chatJid?.endsWith('@g.us') || msg?.key?.fromMe) return false;

    const mode = await getAntilinkMode(db, chatJid);
    if (mode === 'off') return false;
    if (!messageContainsLink(msg)) return false;

    // Exempt admins / Baron+ — must use the LID-safe check on BOTH the
    // resolved sender and the raw participant JID WhatsApp sent.
    const rawJid = msg.key.participant || msg.key.remoteJid;
    if (isGroupAdmin(senderJid, groupParticipants) || isGroupAdmin(rawJid, groupParticipants)) return false;
    const rank = await getRank(db, senderJid, groupParticipants, true, chatJid);
    if (getRankLevel(rank) >= RANK_LEVEL['baron']) return false;

    // Without admin the bot can't delete anything — bail quietly rather than spam.
    if (groupParticipants?.length && !isBotGroupAdmin(sock, groupParticipants)) return false;

    const tag = toTag(senderJid, groupParticipants);
    const mentions = senderJid?.endsWith('@s.whatsapp.net') ? [senderJid] : [];

    try { await sock.sendMessage(chatJid, { delete: msg.key }); } catch {}

    try {
        if (mode === 'kick') {
            await sock.groupParticipantsUpdate(chatJid, [senderJid], 'remove');
            await sock.sendMessage(chatJid, {
                text: `🔗 *Antilink:* ${tag} posted a link and has been removed.`, mentions,
            });
        } else if (mode === 'warn') {
            const res = await db.query(`
                INSERT INTO warnings (group_jid, user_jid, count, warned_by, updated_at)
                VALUES ($1, $2, 1, 'antilink', NOW())
                ON CONFLICT (group_jid, user_jid) DO UPDATE
                SET count = warnings.count + 1, warned_by = 'antilink', updated_at = NOW()
                RETURNING count
            `, [chatJid, senderJid]);
            const count = res.rows[0].count;
            if (count >= MAX_WARNINGS) {
                try { await sock.groupParticipantsUpdate(chatJid, [senderJid], 'remove'); } catch {}
                await db.query('DELETE FROM warnings WHERE group_jid = $1 AND user_jid = $2', [chatJid, senderJid]);
                await sock.sendMessage(chatJid, {
                    text: `🔗 *Antilink:* ${tag} — warning ${count}/${MAX_WARNINGS}. 🚨 Removed from the group.`, mentions,
                });
            } else {
                await sock.sendMessage(chatJid, {
                    text: `🔗 *Antilink:* ${tag}, links aren't allowed here. Warning ${count}/${MAX_WARNINGS}.`, mentions,
                });
            }
        } else {
            await sock.sendMessage(chatJid, {
                text: `🔗 *Antilink:* ${tag}, links aren't allowed in this group.`, mentions,
            });
        }
    } catch (e) {
        console.warn(`[ANTILINK] enforcement failed in ${chatJid}: ${e.message}`);
    }
    return true;
}

async function _cmdMute(ctx, senderRank, senderLevel, mentionedJid, args) {
    const { db, chatJid } = ctx;

    if (senderLevel < RANK_LEVEL['baron']) {
        return `⚠️ _You don't have permission to mute._`;
    }
    if (!mentionedJid) return `⚠️ _Tag someone to mute._`;

    const targetRank = await getRank(db, mentionedJid, ctx.groupParticipants, false, ctx.chatJid);
    const check      = canActOn(senderRank, targetRank);
    if (!check.allowed) return check.reason;

    // Full enforcement (deleting their messages) handled in index.js,
    // which reads this flag before processing any inbound message.
    await db.query(`
        INSERT INTO moderation (group_jid, user_jid, muted, updated_by, updated_at)
        VALUES ($1, $2, TRUE, $3, NOW())
        ON CONFLICT (group_jid, user_jid) DO UPDATE
        SET muted      = TRUE,
            updated_by = $3,
            updated_at = NOW()
    `, [chatJid, mentionedJid, ctx.senderJid]);

    const num = toTag(mentionedJid, ctx.groupParticipants).slice(1);
    return `🔇 *@${num}* has been muted. Their messages will be deleted.`;
}

async function _cmdUnmute(ctx, senderRank, senderLevel, mentionedJid) {
    const { db, chatJid } = ctx;

    if (senderLevel < RANK_LEVEL['baron']) {
        return `⚠️ _You don't have permission to unmute._`;
    }
    if (!mentionedJid) return `⚠️ _Tag someone to unmute._`;

    const targetRank = await getRank(db, mentionedJid, ctx.groupParticipants, false, ctx.chatJid);
    const check      = canActOn(senderRank, targetRank);
    if (!check.allowed) return check.reason;

    await db.query(`
        UPDATE moderation
        SET muted = FALSE, updated_by = $3, updated_at = NOW()
        WHERE group_jid = $1 AND user_jid = $2
    `, [chatJid, mentionedJid, ctx.senderJid]);

    const num = toTag(mentionedJid, ctx.groupParticipants).slice(1);
    return `🔊 *@${num}* has been unmuted.`;
}

async function _cmdIgnore(ctx, senderRank, senderLevel, mentionedJid) {
    const { db, chatJid } = ctx;

    if (senderLevel < RANK_LEVEL['baron']) {
        return `⚠️ _You don't have permission to ignore._`;
    }
    if (!mentionedJid) return `⚠️ _Tag someone to ignore._`;

    const targetRank = await getRank(db, mentionedJid, ctx.groupParticipants, false, ctx.chatJid);
    const check      = canActOn(senderRank, targetRank);
    if (!check.allowed) return check.reason;

    // Silently dropped, not deleted — see isIgnored() / isMuted() split
    // in index.js's mute check.
    await db.query(`
        INSERT INTO moderation (group_jid, user_jid, ignored, updated_by, updated_at)
        VALUES ($1, $2, TRUE, $3, NOW())
        ON CONFLICT (group_jid, user_jid) DO UPDATE
        SET ignored    = TRUE,
            updated_by = $3,
            updated_at = NOW()
    `, [chatJid, mentionedJid, ctx.senderJid]);

    const num = toTag(mentionedJid, ctx.groupParticipants).slice(1);
    return `🙈 *@${num}* is now being ignored. Their messages won't be processed.`;
}

async function _cmdUnignore(ctx, senderRank, senderLevel, mentionedJid) {
    const { db, chatJid } = ctx;

    if (senderLevel < RANK_LEVEL['baron']) {
        return `⚠️ _You don't have permission to unignore._`;
    }
    if (!mentionedJid) return `⚠️ _Tag someone to unignore._`;

    const targetRank = await getRank(db, mentionedJid, ctx.groupParticipants, false, ctx.chatJid);
    const check      = canActOn(senderRank, targetRank);
    if (!check.allowed) return check.reason;

    await db.query(`
        UPDATE moderation
        SET ignored = FALSE, updated_by = $3, updated_at = NOW()
        WHERE group_jid = $1 AND user_jid = $2
    `, [chatJid, mentionedJid, ctx.senderJid]);

    const num = toTag(mentionedJid, ctx.groupParticipants).slice(1);
    return `👀 *@${num}* is no longer ignored.`;
}

async function _cmdTagAll(ctx, senderLevel, args) {
    const { sock, chatJid, msg, senderJid, groupParticipants } = ctx;

    // Admin/Baron gate — Admin and Baron are the same rank under two
    // names (whichever path a given group set them up through), so
    // this checks both ways of arriving at that identity: WA admin
    // status directly, or the DB-crowned rank via senderLevel. Either
    // one passing means they hold the rank — same as .pin's gate.
    const rawJid = msg.key.participant || msg.key.remoteJid;
    const hasAdmin = isGroupAdmin(senderJid, groupParticipants) || isGroupAdmin(rawJid, groupParticipants);
    if (!hasAdmin && senderLevel < RANK_LEVEL['baron']) {
        return `⚠️ _Only group admins can use .tagall._`;
    }

    const message = args.join(' ').trim() || '📢 Attention!';

    try {
        const meta    = await sock.groupMetadata(chatJid);
        const members = meta.participants.map(p => p.id);
        const tags    = members.map(id => toTag(id, meta.participants)).join(' ');
        await sock.sendMessage(chatJid, {
            text:     `📢 *${message}*\n\n${tags}`,
            mentions: members,
        });
        return null; // already sent
    } catch (e) {
        return `⚠️ _Could not tag all — ${e.message}_`;
    }
}

async function _cmdSetPrefix(ctx, senderLevel, args) {
    const { db, chatJid, groupPrefixCache } = ctx;

    if (senderLevel < RANK_LEVEL['king']) {
        return `👑 _Only the King can change the command prefix._`;
    }

    const newPrefix = args[0];

    if (!newPrefix) {
        const res = await db.query('SELECT prefix FROM group_settings WHERE group_jid = $1', [chatJid]);
        const current = res.rows[0]?.prefix || '.';
        return `_Current prefix: \`${current}\`_\n_Usage: .setprefix <symbol>_ — e.g. \`!\`, \`-\`, \`?\`\n_Use_ \`${current}setprefix .\` _to reset to default._`;
    }

    if (/\s/.test(newPrefix) || newPrefix.length > 3) {
        return `⚠️ _Prefix must be 1-3 characters, no spaces._`;
    }

    // Storing NULL means "use the default '.'" — keeps group_settings clean
    // and matches the convention the other .set* resets already use.
    const stored = newPrefix === '.' ? null : newPrefix;

    await db.query(`
        INSERT INTO group_settings (group_jid, prefix, updated_at)
        VALUES ($1, $2, NOW())
        ON CONFLICT (group_jid) DO UPDATE
        SET prefix = $2, updated_at = NOW()
    `, [chatJid, stored]);

    delete groupPrefixCache?.[chatJid];

    if (!stored) {
        return `✅ _Prefix reset to default:_ \`-\``;
    }
    return (
        `✅ *Prefix changed to:* \`${newPrefix}\`\n` +
        `_Commands now start with_ \`${newPrefix}\` _instead of_ \`-\`. ` +
        `_Example:_ \`${newPrefix}menu\``
    );
}

async function _cmdSetWelcome(ctx, senderLevel, args) {
    const { db, chatJid } = ctx;

    if (senderLevel < RANK_LEVEL['lord']) {
        return `⚠️ _Only Lords and above can set welcome messages._`;
    }

    const message = args.join(' ').trim();

    if (!message) {
        // Reset to default
        await db.query(`
            INSERT INTO group_settings (group_jid, welcome_msg, updated_at)
            VALUES ($1, NULL, NOW())
            ON CONFLICT (group_jid) DO UPDATE
            SET welcome_msg = NULL, updated_at = NOW()
        `, [chatJid]);
        return `✅ _Welcome message reset to default._\n\n_Default:_ ${DEFAULT_WELCOME}`;
    }

    await db.query(`
        INSERT INTO group_settings (group_jid, welcome_msg, updated_at)
        VALUES ($1, $2, NOW())
        ON CONFLICT (group_jid) DO UPDATE
        SET welcome_msg = $2, updated_at = NOW()
    `, [chatJid, message]);

    return (
        `✅ *Welcome message set!*\n\n` +
        `_Preview:_\n${_previewTemplate(message)}\n\n` +
        `_Variables: {name} {group} {number}_`
    );
}

async function _cmdSetLeave(ctx, senderLevel, args) {
    const { db, chatJid } = ctx;

    if (senderLevel < RANK_LEVEL['lord']) {
        return `⚠️ _Only Lords and above can set leave messages._`;
    }

    const message = args.join(' ').trim();

    if (!message) {
        await db.query(`
            INSERT INTO group_settings (group_jid, leave_msg, updated_at)
            VALUES ($1, NULL, NOW())
            ON CONFLICT (group_jid) DO UPDATE
            SET leave_msg = NULL, updated_at = NOW()
        `, [chatJid]);
        return `✅ _Leave message reset to default._\n\n_Default:_ ${DEFAULT_LEAVE}`;
    }

    await db.query(`
        INSERT INTO group_settings (group_jid, leave_msg, updated_at)
        VALUES ($1, $2, NOW())
        ON CONFLICT (group_jid) DO UPDATE
        SET leave_msg = $2, updated_at = NOW()
    `, [chatJid, message]);

    return (
        `✅ *Leave message set!*\n\n` +
        `_Preview:_\n${_previewTemplate(message)}\n\n` +
        `_Variables: {name} {group} {number}_`
    );
}

async function _cmdSetRules(ctx, senderRank, senderLevel, args) {
    const { db, chatJid } = ctx;

    // Lord+ via command. Barons set rules manually (via .pin or direct message)
    if (senderLevel < RANK_LEVEL['lord']) {
        return `⚠️ _Only Lords and above can use .setrules._`;
    }

    const rules = args.join(' ').trim();

    if (!rules) {
        await db.query(`
            INSERT INTO group_settings (group_jid, rules, updated_at)
            VALUES ($1, NULL, NOW())
            ON CONFLICT (group_jid) DO UPDATE
            SET rules = NULL, updated_at = NOW()
        `, [chatJid]);
        return `✅ _Rules reset to default._`;
    }

    await db.query(`
        INSERT INTO group_settings (group_jid, rules, updated_at)
        VALUES ($1, $2, NOW())
        ON CONFLICT (group_jid) DO UPDATE
        SET rules = $2, updated_at = NOW()
    `, [chatJid, rules]);

    return `✅ *Rules updated!*\n\nType *.rules* to view them.`;
}

async function _cmdRules(ctx) {
    const { db, chatJid } = ctx;
    const settings = await _getGroupSettings(db, chatJid);
    return settings?.rules || DEFAULT_RULES;
}

async function _cmdPin(ctx, senderLevel, args) {
    const { sock, chatJid, msg } = ctx;

    if (senderLevel < RANK_LEVEL['baron']) {
        return `⚠️ _You don't have permission to pin messages._`;
    }

    // Pin the quoted message if replying, otherwise pin the text
    const quotedCtx = msg.message?.extendedTextMessage?.contextInfo;
    if (quotedCtx?.stanzaId) {
        try {
            await sock.sendMessage(chatJid, {
                pin: { type: 1, time: 604800 }, // 7 days
            }, { quoted: msg });
            return `📌 _Message pinned._`;
        } catch {
            return `⚠️ _Could not pin — make sure Ariel is a group admin._`;
        }
    }

    const pinText = args.join(' ').trim();
    if (!pinText) return `⚠️ _Reply to a message or provide text to pin._`;

    // Send the message then pin it
    try {
        const sent = await sock.sendMessage(chatJid, { text: `📌 *${pinText}*` });
        return null;
    } catch {
        return `⚠️ _Pin failed._`;
    }
}

// Fetch the group's profile photo and PROVE it's a usable image before
// anything uses it as a thumbnail. Tries the full-size photo first, then
// the small preview. The old code never checked the HTTP status or that
// the bytes decode, so an error page / junk response was sent as the
// "thumbnail" and WhatsApp fell back to the grey default icon.
async function _fetchGroupPhoto(sock, jid) {
    const errors = [];
    for (const kind of ['image', 'preview']) {
        try {
            const url = await sock.profilePictureUrl(jid, kind);
            if (!url) { errors.push(`${kind}: no url`); continue; }
            const res = await fetch(url);
            if (!res.ok) { errors.push(`${kind}: HTTP ${res.status}`); continue; }
            const buf  = Buffer.from(await res.arrayBuffer());
            const info = await sharp(buf).metadata(); // throws if not a real image
            if (!info.width || !info.height) { errors.push(`${kind}: not an image`); continue; }
            console.log(`[INVITE:thumb] ok via '${kind}': ${info.width}x${info.height} ${info.format} ${buf.length}B`);
            return { buf, width: info.width, height: info.height, format: info.format, via: kind, errors };
        } catch (e) {
            errors.push(`${kind}: ${e.message}`);
        }
    }
    console.log(`[INVITE:thumb] no usable photo — ${errors.join(' | ')}`);
    return { buf: null, errors };
}

async function _cmdInvite(ctx, args = []) {
    const { sock, chatJid } = ctx;
    // Default = text message with a large link preview: big photo,
    // forwardable and copyable, but no "Join group" button (the version
    // confirmed working on the phone).
    // `.invite card` = native group-invite card (has the Join group button,
    //                  but the photo isn't rendering yet).
    // `.invite test [a-e]` = try individual styles.
    const useCard = (args[0] || '').toLowerCase() === 'card';
    const testMode = (args[0] || '').toLowerCase() === 'test';

    if (!chatJid.endsWith('@g.us')) {
        return `⚠️ _.invite only works inside a group._`;
    }

    try {
        const meta = await sock.groupMetadata(chatJid);
        let code;
        try {
            code = await sock.groupInviteCode(chatJid);
        } catch (inviteErr) {
            if (inviteErr.message === 'item-not-found') {
                // groupInviteCode does a GET for an existing invite item — if
                // this group never had a link generated (nobody tapped
                // "Invite via link" in the app), there's nothing to fetch.
                // groupRevokeInvite does a SET instead, which creates one if
                // it doesn't exist yet and returns it. Safe to use as a
                // fallback here since we only reach it when GET found nothing.
                code = await sock.groupRevokeInvite(chatJid);
            } else {
                throw inviteErr;
            }
        }

        const inviteLink = `https://chat.whatsapp.com/${code}`;

        // Group photo, validated. `thumb` is a square JPEG (or undefined
        // if there's no usable photo) — never junk bytes.
        // Tune THUMB_PX if WhatsApp shows it blurry or won't send it.
        const THUMB_PX = 640;
        const photo = await _fetchGroupPhoto(sock, chatJid);
        let thumb;
        if (photo.buf) {
            try {
                thumb = await sharp(photo.buf)
                    .resize(THUMB_PX, THUMB_PX, { fit: 'cover' })
                    .jpeg({ quality: 80 })
                    .toBuffer();
            } catch (e) {
                console.log(`[INVITE:thumb] re-encode failed: ${e.message}`);
            }
        }

        // Text message + large link preview (forwardable, no button).
        const sendLinkPreview = async () => {
            // Style D from .preview: native linkPreview big card (shows for everyone, unlike externalAdReply).
            await sendCard(sock, chatJid, {
                url:   inviteLink,
                title: meta.subject,
                body:  'Tap to join the group',
                text:  inviteLink,
                ...(thumb ? { image: thumb } : {}),
                big:   true,
                shape: 'auto',
            });
        };

        // .invite test          -> photo diagnostic + list of letters
        // .invite test <a-e>    -> sends just that one style, so one
        //                          run on the phone shows how WhatsApp
        //                          actually renders it.
        if (testMode) {
            const letter = (args[1] || '').toLowerCase();
            const say = (t) => sock.sendMessage(chatJid, { text: t });
            const kb  = (buf) => buf ? `${Math.round(buf.length / 1024)}KB` : 'none';
            const card = async (jpeg) => {
                const waMsg = generateWAMessageFromContent(chatJid, {
                    groupInviteMessage: {
                        inviteCode:       code,
                        inviteExpiration: Math.floor(Date.now() / 1000) + 3 * 86400,
                        groupJid:         chatJid,
                        groupName:        meta.subject,
                        ...(jpeg ? { jpegThumbnail: jpeg } : {}),
                    },
                }, { userJid: sock.user.id });
                await sock.relayMessage(chatJid, waMsg.message, { messageId: waMsg.key.id });
            };
            const variants = {
                a: ['native card, original photo untouched', () => card(photo.buf || undefined)],
                b: ['native card, small 192px photo', async () => {
                    const small = photo.buf
                        ? await sharp(photo.buf).resize(192, 192, { fit: 'cover' }).jpeg({ quality: 80 }).toBuffer()
                        : undefined;
                    await card(small);
                }],
                c: ['link message, big preview', () => sendLinkPreview()],
                d: ['plain link only', () => sock.sendMessage(chatJid, { text: inviteLink })],
                e: ['square photo + caption', async () => {
                    if (!thumb) return say('_No usable group photo, so this style can\'t be sent._');
                    await sock.sendMessage(chatJid, {
                        image: thumb,
                        caption: `*${meta.subject}*\nGroup chat invite\n${inviteLink}`,
                    });
                }],
            };
            const v = variants[letter];
            if (!v) {
                await say(
                    `🔎 *Invite test*\n` +
                    (photo.buf
                        ? `photo: OK via '${photo.via}' ${photo.width}x${photo.height} ${photo.format} ${kb(photo.buf)}\nthumb640: ${kb(thumb)}`
                        : `photo: FAILED — ${photo.errors.join(' | ') || 'unknown'}`) +
                    `\n\nSend one of:\n` +
                    Object.entries(variants).map(([k, [name]]) => `*.invite test ${k}* — ${name}`).join('\n')
                );
                return null;
            }
            await say(`${letter.toUpperCase()} — ${v[0]}`);
            await v[1]();
            return null;
        }

        if (!useCard) {
            await sendLinkPreview();
            return null; // already sent
        }

        // Default: the native group-invite card (big square photo, group
        // name, "Join group" button), built by hand and sent with
        // relayMessage instead of sock.sendMessage({ groupInvite }).
        // sendMessage's groupInvite path fetches its own tiny 'preview'
        // profile picture and overwrites our jpegThumbnail (the "mini
        // image"); building the message ourselves keeps our square photo.
        //
        // inviteExpiration is REQUIRED — leave it out and WhatsApp reads
        // it as already expired ("Invite expired", grey icon, no button).
        // It's only the card's display window; the link itself doesn't
        // expire. Raise INVITE_TTL_DAYS for longer-lived cards, or just
        // run .invite again.
        const INVITE_TTL_DAYS = 3;
        try {
            const waMsg = generateWAMessageFromContent(chatJid, {
                groupInviteMessage: {
                    inviteCode:       code,
                    inviteExpiration: Math.floor(Date.now() / 1000) + INVITE_TTL_DAYS * 86400,
                    groupJid:         chatJid,
                    groupName:        meta.subject,
                    ...(thumb ? { jpegThumbnail: thumb } : {}),
                },
            }, { userJid: sock.user.id });
            await sock.relayMessage(chatJid, waMsg.message, { messageId: waMsg.key.id });
        } catch (cardErr) {
            console.log(`[INVITE] native card failed (${cardErr.message}) — sending link preview instead`);
            await sendLinkPreview();
        }
        return null; // already sent
    } catch (e) {
        // Reached only if groupRevokeInvite also failed, or some other error
        // hit before we got that far. Dump enough to diagnose without
        // guessing — this is a real, unexpected failure at this point.
        console.error('[INVITE] groupInviteCode failed:', e.message);
        console.error('[INVITE] sock.user:', JSON.stringify(sock.user));
        try {
            const meta = await sock.groupMetadata(chatJid);
            const me = meta.participants.find(p =>
                p.id === sock.user?.id || p.lid === sock.user?.id ||
                p.id === sock.user?.lid || p.lid === sock.user?.lid
            );
            console.error('[INVITE] self participant record:', JSON.stringify(me));
        } catch (metaErr) {
            console.error('[INVITE] self-check groupMetadata also failed:', metaErr.message);
        }
        return `⚠️ _Could not generate invite — make sure Ariel is a group admin. (${e.message})_`;
    }
}

// Mathematical Bold Fraktur transform — used for the .ranks header
// and section titles. Only touches A-Z/a-z/0-9; anything else (@,
// spaces, punctuation, emoji, existing non-Latin names) passes
// through unchanged, since Fraktur has no glyphs for those and
// forcing a lookup on them would just drop or mangle the character.
const _FRAKTUR_BOLD_UPPER_START = 0x1D56C; // 𝕬
const _FRAKTUR_BOLD_LOWER_START = 0x1D586; // 𝖆
const _FRAKTUR_BOLD_DIGIT_START = 0x1D7CE; // 𝟎 (Mathematical Bold digits — Fraktur itself defines no digits)
function frakturBold(str) {
    return String(str).split('').map(ch => {
        const code = ch.charCodeAt(0);
        if (code >= 65 && code <= 90)  return String.fromCodePoint(_FRAKTUR_BOLD_UPPER_START + (code - 65));
        if (code >= 97 && code <= 122) return String.fromCodePoint(_FRAKTUR_BOLD_LOWER_START + (code - 97));
        if (code >= 48 && code <= 57)  return String.fromCodePoint(_FRAKTUR_BOLD_DIGIT_START + (code - 48));
        return ch;
    }).join('');
}

async function _cmdRanks(ctx) {
    const { db, chatJid, sock, groupParticipants } = ctx;

    // Global titles (group_jid NULL) show everywhere; baron rows only for
    // THIS group. WhatsApp admins of this group count as Barons too
    // (baron == admin), even with no row. Each person is listed once,
    // under the highest rank they hold in this group.
    const res = await db.query(
        `SELECT jid, phone, lid, rank FROM bot_ranks
         WHERE group_jid IS NULL OR group_jid = $1`,
        [chatJid]
    );

    const parts = groupParticipants || [];
    const keyOf = (jid, extra = []) => {
        for (const id of [jid, ...extra]) {
            if (!id) continue;
            const p = parts.find(x => _participantMatches(x, id));
            if (p) return _jidUser(p.phoneNumber || p.id || p.lid || id);
        }
        return _jidUser(jid);
    };

    const best = new Map(); // key -> { jid, rank }
    const consider = (key, jid, rank) => {
        const lvl = RANK_LEVEL[rank] ?? 0;
        const cur = best.get(key);
        if (!cur || lvl > (RANK_LEVEL[cur.rank] ?? 0)) best.set(key, { jid, rank });
    };

    for (const row of res.rows) {
        const r = String(row.rank || '').toLowerCase();
        if (!(r in RANK_LEVEL) || r === 'player' || r === 'guest') continue;
        consider(keyOf(row.jid, [row.phone, row.lid]), row.jid, r);
    }

    const botIds = [sock?.user?.id, sock?.user?.lid, sock?.user?.jid].filter(Boolean);
    for (const p of parts) {
        if (p.admin !== 'admin' && p.admin !== 'superadmin') continue;
        if (botIds.some(id => _participantMatches(p, id))) continue;
        const jid = p.phoneNumber || p.id || p.lid;
        consider(keyOf(jid), jid, 'baron');
    }

    if (!best.size) return `_No ranks assigned yet._`;

    const byRank = new Map();
    for (const { jid, rank } of best.values()) {
        if (!byRank.has(rank)) byRank.set(rank, []);
        byRank.get(rank).push(jid);
    }

    const rankOrder = Object.keys(RANK_LEVEL).sort((a, b) => RANK_LEVEL[b] - RANK_LEVEL[a]);

    const lines = [`👑 *${frakturBold('Niflheim Ranks')}*\n`];
    for (const rankName of rankOrder) {
        const jids = byRank.get(rankName);
        if (!jids || !jids.length) continue;
        const titleCased = rankName.charAt(0).toUpperCase() + rankName.slice(1);
        lines.push(`${frakturBold(titleCased)}... (${RANK_LEVEL[rankName]}% authority)`);
        jids.forEach((jid, idx) => {
            lines.push(`${idx + 1}. @${toTag(jid, groupParticipants).slice(1)}`);
        });
        lines.push('');
    }

    return lines.join('\n').trimEnd();
}

async function _cmdWhois(ctx, mentionedJid) {
    const { db, senderJid, groupParticipants, chatJid } = ctx;

    const targetJid  = mentionedJid || senderJid;
    const targetRank = await getRank(db, targetJid, groupParticipants, false, chatJid);
    const num        = toTag(targetJid, groupParticipants).slice(1);

    return (
        `👤 *@${num}*\n\n` +
        `${rankBadge(targetRank)}`
    );
}


// ============================================================
// ACTIVITY TRACKING — .active / .inactive / .setactive
// ============================================================
// In-memory cache, kept warm in the background instead of being
// queried live when .active/.inactive are asked. trackActivity()
// updates it directly (no read-back — we already know the new
// count), and .setactive updates the threshold slot directly too.
// A group is lazily hydrated from DB once, on first touch, then
// stays warm from memory alone for the life of the process.
//
// Counts are tracked per calendar day (UTC) so .active/.inactive
// can report a rolling ACTIVE_WINDOW_DAYS window — summing only the
// last N days' buckets — instead of an all-time total. Old days are
// simply excluded from the sum; nothing needs to be deleted for the
// window itself to behave correctly (a cleanup of very old rows is
// still worth doing periodically, but isn't required for correctness).
const ACTIVE_WINDOW_DAYS = 7;

const _activityCache = new Map(); // groupJid -> { daily: Map<userJid, Map<dayStr, count>>, threshold: number|null, hydrated: bool }

function _getActivityBucket(groupJid) {
    let bucket = _activityCache.get(groupJid);
    if (!bucket) {
        bucket = { daily: new Map(), threshold: null, hydrated: false };
        _activityCache.set(groupJid, bucket);
    }
    return bucket;
}

// UTC day string, e.g. "2026-08-16" — stable key for both the DB
// DATE column and the in-memory per-day map.
function _dayKey(date = new Date()) {
    return date.toISOString().slice(0, 10);
}

function _windowDayKeys(days = ACTIVE_WINDOW_DAYS) {
    const keys = [];
    const now = Date.now();
    for (let i = 0; i < days; i++) {
        keys.push(_dayKey(new Date(now - i * 86_400_000)));
    }
    return keys;
}

// Sum of a user's counts across the trailing window, from memory.
function _windowCount(bucket, userJid, windowKeys) {
    const perDay = bucket.daily.get(userJid);
    if (!perDay) return 0;
    let total = 0;
    for (const day of windowKeys) total += perDay.get(day) || 0;
    return total;
}

// One-time hydration from DB for a group the cache hasn't seen yet
// (e.g. right after a restart). Everything after this is memory-only.
// Concurrent callers (trackActivity fires fire-and-forget, so two
// messages can land back-to-back before the first hydration finishes)
// share the same in-flight promise instead of racing separate reads
// that could stomp each other's increments.
async function _hydrateActivityBucket(db, groupJid) {
    const bucket = _getActivityBucket(groupJid);
    if (bucket.hydrated) return bucket;
    if (bucket._hydrating) return bucket._hydrating;

    bucket._hydrating = (async () => {
        try {
            // Only pull the days we actually need for the window, plus a
            // little slack — no reason to load ancient history into memory.
            const [dailyRes, settings] = await Promise.all([
                db.query(
                    `SELECT user_jid, day, msg_count FROM activity_daily
                     WHERE group_jid = $1 AND day >= (CURRENT_DATE - $2::int)`,
                    [groupJid, ACTIVE_WINDOW_DAYS + 1]
                ),
                _getGroupSettings(db, groupJid),
            ]);
            for (const row of dailyRes.rows) {
                const dayStr = (row.day instanceof Date ? _dayKey(row.day) : String(row.day).slice(0, 10));
                if (!bucket.daily.has(row.user_jid)) bucket.daily.set(row.user_jid, new Map());
                bucket.daily.get(row.user_jid).set(dayStr, row.msg_count);
            }
            bucket.threshold = settings?.active_threshold ?? DEFAULT_ACTIVE_THRESHOLD;
            bucket.hydrated = true;
        } catch (e) {
            // Don't mark hydrated on failure (a transient DB blip, e.g. a
            // cold-start connection hiccup on Render's free tier) — leave
            // it false so the NEXT call retries instead of being stuck
            // forever returning this same rejected promise. Swallow here
            // so .active/.inactive degrade to "0 messages so far" instead
            // of throwing and going silent.
            console.error(`⚠️ _hydrateActivityBucket failed for ${groupJid}: ${e.message}`);
        } finally {
            delete bucket._hydrating;
        }
        return bucket;
    })();

    return bucket._hydrating;
}

// Called on every non-muted group message from index.js.
// Fire-and-forget — never blocks the message pipeline. Updates the
// DB (source of truth, survives restarts) AND the in-memory cache
// directly, so .active/.inactive never need to query for this.
export async function trackActivity(db, groupJid, userJid) {
    if (!groupJid || !userJid) return;

    // Hydrate BEFORE writing — if this is the first touch since
    // restart, hydration needs to see pre-increment DB state. Doing
    // it after the write would double-count this message (hydration
    // would pull the already-incremented row, then +1 on top of it).
    // No-ops once bucket.hydrated is true, so this is cheap after
    // the first call per group.
    const bucket = await _hydrateActivityBucket(db, groupJid);
    const today = _dayKey();

    await Promise.all([
        db.query(`
            INSERT INTO activity_counts (group_jid, user_jid, msg_count, updated_at)
            VALUES ($1, $2, 1, NOW())
            ON CONFLICT (group_jid, user_jid) DO UPDATE
            SET msg_count = activity_counts.msg_count + 1, updated_at = NOW()
        `, [groupJid, userJid]),
        db.query(`
            INSERT INTO activity_daily (group_jid, user_jid, day, msg_count)
            VALUES ($1, $2, CURRENT_DATE, 1)
            ON CONFLICT (group_jid, user_jid, day) DO UPDATE
            SET msg_count = activity_daily.msg_count + 1
        `, [groupJid, userJid]),
    ]);

    if (!bucket.daily.has(userJid)) bucket.daily.set(userJid, new Map());
    const perDay = bucket.daily.get(userJid);
    perDay.set(today, (perDay.get(today) || 0) + 1);
}

async function _getActiveThreshold(db, groupJid) {
    const bucket = await _hydrateActivityBucket(db, groupJid);
    return bucket.threshold ?? DEFAULT_ACTIVE_THRESHOLD;
}

// Builds one canonical roster — every group member resolved to the
// SAME identity key that trackActivity() writes under (the resolved
// phone jid) — with their window message count attached. .active and
// .inactive both derive from this single list and the same >/<=
// comparison, so a person can only ever land in exactly one of them.
// Before this, .active read keys already present in bucket.daily
// (always phone jids) while .inactive read groupParticipants' raw
// p.id (sometimes an @lid) — two different keys for the same person,
// which is how someone ended up counted in both lists at once.
function _buildActivityRoster(bucket, groupParticipants, windowKeys) {
    const seen = new Set();
    const roster = [];
    for (const p of groupParticipants) {
        const resolved = _resolveToPhoneJid(p.id, groupParticipants) || p.id;
        if (seen.has(resolved)) continue; // dedupe: p.id and p.lid can both point here
        seen.add(resolved);
        roster.push({ jid: resolved, count: _windowCount(bucket, resolved, windowKeys) });
    }
    return roster;
}

// ── .active [message] ────────────────────────────────────────
// Lists everyone in the group whose message count over the last
// ACTIVE_WINDOW_DAYS days is STRICTLY MORE than the group's active
// threshold (default 5, set via .setactive). Reads entirely from the
// in-memory cache — no DB call, aside from a one-time hydration.
async function _cmdActive(ctx, args) {
    const { db, chatJid, groupParticipants } = ctx;

    if (!groupParticipants?.length) return `⚠️ _Could not read group member list._`;

    const bucket = await _hydrateActivityBucket(db, chatJid);
    const threshold = bucket.threshold ?? DEFAULT_ACTIVE_THRESHOLD;
    const windowKeys = _windowDayKeys();

    const rows = _buildActivityRoster(bucket, groupParticipants, windowKeys)
        .filter(r => r.count > threshold)
        .sort((a, b) => b.count - a.count);

    const label = args.join(' ').trim();
    const header = label
        ? `*${label}*\n\n`
        : `*Active members (>${threshold} msgs in ${ACTIVE_WINDOW_DAYS}d):*\n\n`;

    if (!rows.length) return `${header}_No one has crossed the threshold yet._`;

    const lines = rows.map((r, i) => {
        const num = toTag(r.jid, groupParticipants).slice(1);
        return `${i + 1}. @${num} (${r.count})`;
    });

    return header + lines.join('\n');
}

// ── .inactive ────────────────────────────────────────────────
// Everyone in the group whose message count is <= the threshold —
// i.e. they have NOT sent MORE than x messages (includes members
// with zero tracked messages in the window). Same roster and same
// threshold as .active, so nobody appears in both lists.
async function _cmdInactive(ctx) {
    const { db, chatJid, groupParticipants } = ctx;

    if (!groupParticipants?.length) return `⚠️ _Could not read group member list._`;

    const bucket = await _hydrateActivityBucket(db, chatJid);
    const threshold = bucket.threshold ?? DEFAULT_ACTIVE_THRESHOLD;
    const windowKeys = _windowDayKeys();

    const rows = _buildActivityRoster(bucket, groupParticipants, windowKeys)
        .filter(r => r.count <= threshold)
        .sort((a, b) => b.count - a.count);

    if (!rows.length) return `_Everyone in the group is active._`;

    const lines = rows.map((r, i) => {
        const num = toTag(r.jid, groupParticipants).slice(1);
        return `${i + 1}. @${num} (${r.count})`;
    });

    return `*Inactive members (≤${threshold} msgs in ${ACTIVE_WINDOW_DAYS}d):*\n\n` + lines.join('\n');
}

// ── .setactive <x> — King only ──────────────────────────────
async function _cmdSetActive(ctx, senderRank, args) {
    const { db, chatJid } = ctx;

    if (senderRank !== 'king') return `👑 _Only the King can set the active threshold._`;

    const x = parseInt(args[0], 10);
    if (!args.length || isNaN(x) || x < 1) {
        const current = await _getActiveThreshold(db, chatJid);
        return `🛠️ *.setactive <x>*\n\nCurrent threshold: *${current}* messages.`;
    }

    await db.query(`
        INSERT INTO group_settings (group_jid, active_threshold, updated_at)
        VALUES ($1, $2, NOW())
        ON CONFLICT (group_jid) DO UPDATE
        SET active_threshold = $2, updated_at = NOW()
    `, [chatJid, x]);

    // Update cache directly so .active/.inactive reflect it immediately
    _getActivityBucket(chatJid).threshold = x;

    return `✅ _Active threshold set to ${x} messages._`;
}


// ============================================================
// .online — presence-based
// ============================================================
// Baileys only surfaces presence for JIDs we've subscribed to, so
// this subscribes to every group member (best-effort) and reports
// whoever has a cached "available" status inside ONLINE_WINDOW_MS.
// Freshly-subscribed members may not show up until their client
// pushes an update, so results reflect "known online", not exhaustive.
async function _cmdOnline(ctx) {
    const { chatJid, groupParticipants, presenceCache } = ctx;

    if (!groupParticipants?.length) return `⚠️ _Could not read group member list._`;

    // No subscribe call here — presence is subscribed once in the
    // background per group (see index.js) and the cache fills in
    // passively via the presence.update listener. This just reads
    // whatever's already cached, instantly.
    const now = Date.now();
    const online = groupParticipants
        .map(p => p.id)
        .filter(jid => {
            const cached = presenceCache?.[jid];
            return cached
                && cached.status === 'available'
                && (now - cached.ts) < ONLINE_WINDOW_MS;
        });

    if (!online.length) {
        return `🟢 *Online Now*\n\n_No members currently detected online. Presence may still be warming up for this group._`;
    }

    const lines = online.map((jid, i) => `${i + 1}. ${toTag(jid, groupParticipants)}`);
    return `🟢 *Online Now (${online.length})*\n\n` + lines.join('\n');
}


// ============================================================
// .admin — list group admins + baron-tier
// ============================================================
async function _cmdAdmin(ctx) {
    const { db, chatJid, groupParticipants } = ctx;

    if (!groupParticipants?.length) return `⚠️ _Could not read group member list._`;

    const admins = groupParticipants.filter(p => p.admin === 'admin' || p.admin === 'superadmin');

    // Barons crowned via bot rank (not necessarily WA admins). Baron
    // is per-group now (see the bot_ranks group_jid migration) — a
    // Baron crowned in a different group must not show up here. This
    // used to query every baron row system-wide, so a person crowned
    // Baron anywhere showed as an "Extra Baron" in every group's
    // .admin listing, not just theirs.
    const res = await db.query(`SELECT jid FROM bot_ranks WHERE rank = 'baron' AND group_jid = $1`, [chatJid]);
    const baronJids = new Set(res.rows.map(r => r.jid));
    const extraBarons = [...baronJids].filter(jid => !isGroupAdmin(jid, groupParticipants));

    if (!admins.length && !extraBarons.length) return `_No admins found in this group._`;

    const lines = [`🛡️ *Group Admins*\n`];
    admins.forEach((p, i) => lines.push(`${i + 1}. ${toTag(p.phoneNumber || p.id, groupParticipants)}`));

    if (extraBarons.length) {
        lines.push(`\n*Extra Barons*`);
        extraBarons.forEach((jid, i) => lines.push(`${i + 1}. ${toTag(jid, groupParticipants)}`));
    }

    return lines.join('\n');
}


// ============================================================
// .ascmd / .assigncmd <cmd> <rank> — King/Queen only
// ============================================================
// Globally reassigns a command's minimum rank. Anyone at the given
// rank OR HIGHER can then use it — e.g. assigning "jester" means
// jester, lord, baron-above-jester-level..., up through king, can
// all use it (standard rank-level comparison, not an exact match).
// This is a system-wide override; it persists in bot_ranks-adjacent
// command_ranks table and survives restarts.
async function _cmdAssignCmd(ctx, senderRank, senderLevel, args) {
    const { db } = ctx;

    if (senderLevel < ROYALTY_MIN_LEVEL) {
        return `👑 _Only the King or Queen can assign command ranks._`;
    }

    let [rawCmd, rawRank] = args;
    if (!rawCmd || !rawRank) {
        return `🔧 *.ascmd <cmd> <rank>*\n\nExample: *.ascmd .kick jester*\n\nAssigns a command to a rank — that rank and everyone above it can then use it, globally.`;
    }

    const cmd  = rawCmd.startsWith('.') ? rawCmd.toLowerCase() : `.${rawCmd.toLowerCase()}`;
    const rank = rawRank.toLowerCase();

    if (!(rank in RANK_LEVEL)) {
        return `⚠️ _Unknown rank "${rank}". Valid: ${Object.keys(RANK_LEVEL).join(', ')}_`;
    }

    await db.query(`
        INSERT INTO command_ranks (cmd, min_rank, assigned_by, assigned_at)
        VALUES ($1, $2, $3, NOW())
        ON CONFLICT (cmd) DO UPDATE
        SET min_rank = $2, assigned_by = $3, assigned_at = NOW()
    `, [cmd, rank, ctx.senderJid]);

    // Invalidate cache so the new assignment takes effect immediately
    _cmdRankCache = null;

    return `🔒 *${cmd}* is now assigned to ${rankBadge(rank)} and above.`;
}


// ============================================================
// .new rank <name> <power> / .delrank <name> — King/Queen only
// ============================================================
const _cap = n => n.charAt(0).toUpperCase() + n.slice(1);

// "Above / below" listing for a power value, highest first.
function _rankLadder(name, power) {
    const others = Object.entries(RANK_LEVEL).filter(([n]) => n !== name);
    const line   = ([n, l]) => `• ${rankBadge(n)} (${l})`;
    const above  = others.filter(([, l]) => l > power).sort((a, b) => b[1] - a[1]);
    const same   = others.filter(([, l]) => l === power);
    const below  = others.filter(([, l]) => l < power).sort((a, b) => b[1] - a[1]);
    return (
        `⬆️ *Above:*\n${above.length ? above.map(line).join('\n') : '• —'}\n\n` +
        (same.length ? `↔️ *Same level:*\n${same.map(line).join('\n')}\n\n` : '') +
        `⬇️ *Below:*\n${below.length ? below.map(line).join('\n') : '• —'}`
    );
}

async function _cmdNewRank(ctx, senderRank, senderLevel, args) {
    const { db } = ctx;
    if (senderLevel < ROYALTY_MIN_LEVEL) {
        return `👑 _Only the King or Queen can create ranks._`;
    }
    const name  = (args[1] || '').toLowerCase();
    const power = Number(args[2]);
    const usage =
        `🔧 *.new rank <name> <power>*\n\n` +
        `Example: *.new rank squire 55*\n` +
        `Power is 1–99. A higher number outranks a lower one (the King is 100).\n` +
        `Use *.delrank <name>* to remove a custom rank.`;
    if (!name || args[2] === undefined) return usage;
    if (!/^[a-z]{2,16}$/.test(name)) return `⚠️ _Rank names are 2–16 letters, no spaces or numbers._`;
    if (!Number.isInteger(power) || power < 1 || power > 99) return `⚠️ _Power must be a whole number from 1 to 99._`;
    if (name in RANK_LEVEL) {
        return `⚠️ _The rank "${name}" already exists${BUILTIN_RANKS.has(name) ? ' (built-in)' : ''}._`;
    }
    const realLevel = getRankLevel(senderRank);
    if (senderRank !== 'king' && power >= realLevel) {
        return `👑 _You can only create ranks below your own level (${realLevel})._`;
    }

    await db.query(
        `INSERT INTO custom_ranks (name, level, created_by) VALUES ($1, $2, $3)`,
        [name, power, ctx.senderJid]
    );
    RANK_LEVEL[name] = power;
    if (!CROWNBLE_TITLES.includes(name)) CROWNBLE_TITLES.push(name);

    return `✅ *New rank created: ${_cap(name)}* — power ${power}\n\n${_rankLadder(name, power)}\n\n_Give it with .crown ${name} @user · restrict a command to it with .ascmd <cmd> ${name}_`;
}

async function _cmdDelRank(ctx, senderRank, senderLevel, args) {
    const { db } = ctx;
    if (senderLevel < ROYALTY_MIN_LEVEL) {
        return `👑 _Only the King or Queen can delete ranks._`;
    }
    const name = (args[0] || '').toLowerCase();
    if (!name) return `🔧 *.delrank <name>*\n\nDeletes a custom rank made with .new rank. Built-in ranks can't be deleted.`;
    if (BUILTIN_RANKS.has(name)) return `🔒 _${_cap(name)} is a built-in rank and can't be deleted._`;
    if (!(name in RANK_LEVEL)) return `⚠️ _There's no custom rank called "${name}"._`;
    if (senderRank !== 'king' && RANK_LEVEL[name] >= getRankLevel(senderRank)) {
        return `👑 _You can't delete a rank at or above your own level._`;
    }

    // A command assigned to a deleted rank would fall to level 0 and become
    // open to everyone, so make the admin reassign those first.
    const assigned = await db.query('SELECT cmd FROM command_ranks WHERE LOWER(min_rank) = $1', [name]);
    if (assigned.rows.length) {
        return `🔒 _Can't delete ${_cap(name)} yet — these commands are assigned to it. Reassign them with .ascmd first:_\n${assigned.rows.map(r => `• ${r.cmd}`).join('\n')}`;
    }

    // Anyone holding it drops back to their normal rank (baron if WA admin, else player).
    const holders = await db.query('DELETE FROM bot_ranks WHERE LOWER(rank) = $1', [name]);
    await db.query('DELETE FROM custom_ranks WHERE name = $1', [name]);
    delete RANK_LEVEL[name];
    const ci = CROWNBLE_TITLES.indexOf(name);
    if (ci !== -1) CROWNBLE_TITLES.splice(ci, 1);

    return `🗑️ *Rank deleted: ${_cap(name)}*` +
        (holders.rowCount ? `\n_${holders.rowCount} holder${holders.rowCount === 1 ? '' : 's'} dropped back to their normal rank._` : '');
}


// ============================================================
// INTERNAL HELPERS
// ============================================================

async function _getGroupSettings(db, groupJid) {
    try {
        const res = await db.query(
            'SELECT * FROM group_settings WHERE group_jid = $1', [groupJid]
        );
        return res.rows[0] || null;
    } catch { return null; }
}

function _previewTemplate(template) {
    return template
        .replace(/{name}/g,   '@ExampleUser')
        .replace(/{group}/g,  'Niflheim')
        .replace(/{number}/g, '234XXXXXXXXX');
}


// ============================================================
// MUTE CHECK
// Call this at the top of handleMessage() in index.js
// Returns true if user is muted (message should be ignored)
// ============================================================

export async function isMuted(db, groupJid, userJid) {
    try {
        const res = await db.query(
            'SELECT muted FROM moderation WHERE group_jid = $1 AND user_jid = $2',
            [groupJid, userJid]
        );
        return res.rows[0]?.muted === true;
    } catch { return false; }
}

export async function isIgnored(db, groupJid, userJid) {
    try {
        const res = await db.query(
            'SELECT ignored FROM moderation WHERE group_jid = $1 AND user_jid = $2',
            [groupJid, userJid]
        );
        return res.rows[0]?.ignored === true;
    } catch { return false; }
}


// ============================================================
// HOW TO WIRE INTO index.js
// ============================================================
//
// 1. Import at top of index.js:
//      import { setupCommandsTables, handleBotCommand,
//               onMemberJoin, onMemberLeave, isMuted, isIgnored } from './commands.js';
//
// 2. After DB connects, call:
//      await setupCommandsTables(db);
//
// 3. In handleMessage(), before the game layer:
//      if (await isMuted(db, chatJid, senderJid)) return;
//
//      const botReply = await handleBotCommand({
//          sock, db, msg, chatJid, senderJid, text,
//          mentionedJid, groupParticipants, presenceCache,
//      });
//      if (botReply) {
//          await sendAny(sock, chatJid, botReply, msg);
//          return;
//      }
//      // ... rest of message handling
//
// 3b. Track activity for .active/.inactive (fire-and-forget, before
//     the mute check ideally so muted users still don't get skipped
//     — call after mute check as shown, or wherever you'd like):
//      trackActivity(db, chatJid, senderJid).catch(() => {});
//
// 3c. Presence cache for .online — declare once at module scope
//     (e.g. `const presenceCache = {};`) and listen for updates:
//      sock.ev.on('presence.update', ({ id, presences }) => {
//          for (const [jid, p] of Object.entries(presences || {})) {
//              presenceCache[jid] = { status: p.lastKnownPresence, ts: Date.now(), chatJid: id };
//          }
//      });
//
// 4. Add group participant listener:
//      sock.ev.on('group-participants.update', async ({ id, participants, action }) => {
//          const ctx = { sock, db, chatJid: id, groupParticipants: [] };
//          if (action === 'add')    for (const jid of participants) await onMemberJoin(ctx, jid);
//          if (action === 'remove') for (const jid of participants) await onMemberLeave(ctx, jid);
//      });
//
// 5. Pass groupParticipants for accurate WA admin detection:
//      const meta = await sock.groupMetadata(chatJid);
//      const groupParticipants = meta.participants;
//
// ============================================================


// ── _cmdSpawn ─────────────────────────────────────────────────
// .spawn [name] [zone]  — King/Queen only
// Injects a Pokémon into a zone. Players have 1% chance per step
// to encounter it. Persists until caught or defeated.
async function _cmdSpawn(ctx, senderRank, senderLevel, args) {
    const { db, chatJid } = ctx;

    const POKEAPI = 'https://pokeapi.co/api/v2/pokemon';

    let pokemonName = null;
    let zone        = args[args.length - 1] || null;

    if (args.length === 0) {
        // Random — pick from pokeapi range 1-1025
        const id = Math.floor(Math.random() * 1025) + 1;
        pokemonName = String(id);
    } else if (args.length === 1) {
        pokemonName = args[0].toLowerCase();
        zone        = null;
    } else {
        pokemonName = args[0].toLowerCase();
        zone        = args[args.length - 1].toLowerCase();
    }

    // Fetch Pokémon data
    let data;
    try {
        const res = await fetch(`${POKEAPI}/${pokemonName}`);
        if (!res.ok) return `⚠️ _Pokémon "${pokemonName}" not found._`;
        data = await res.json();
    } catch {
        return `⚠️ _Failed to fetch Pokémon data._`;
    }

    const name   = data.name;
    const sprite = data.sprites?.other?.['official-artwork']?.front_default
                || data.sprites?.front_default || '';
    const types  = data.types.map(t =>
        t.type.name.charAt(0).toUpperCase() + t.type.name.slice(1)
    ).join('/');
    const hp     = data.stats.find(s => s.stat.name === 'hp')?.base_stat || 45;

    const payload = JSON.stringify({ name, sprite, types, base_hp: hp, source: 'spawn' });
    const now     = new Date().toISOString();

    await db.query(
        `INSERT INTO zone_spawns (zone, pokemon_name, pokemon_data, spawned_by, spawned_at, status)
         VALUES ($1, $2, $3, $4, $5, 'active')`,
        [zone || 'any', name, payload, ctx.senderJid, now]
    );

    return (
        `__IMG__${sprite}__CAP__` +
        `🌟 *A wild ${name.charAt(0).toUpperCase() + name.slice(1)} has appeared!*\n` +
        `📍 Zone: _${zone || 'current'}_\n` +
        `🔷 Type: ${types}\n\n` +
        `_It lurks in the zone... any traveller may encounter it._`
    );
}


// ── _cmdSpawnP ────────────────────────────────────────────────
// .spawnp [name]  — King/Queen only
// Prefetches and caches Pokémon data for fast future spawns.
async function _cmdSpawnP(ctx, senderRank, senderLevel, args) {
    const POKEAPI = 'https://pokeapi.co/api/v2/pokemon';
    const target  = args[0]?.toLowerCase() || String(Math.floor(Math.random() * 1025) + 1);

    let data, speciesData;
    try {
        const res = await fetch(`${POKEAPI}/${target}`);
        if (!res.ok) return `⚠️ _Pokémon "${target}" not found._`;
        data = await res.json();
    } catch {
        return `⚠️ _Failed to fetch Pokémon data._`;
    }

    // Fetch species for flavor text
    try {
        const sres = await fetch(data.species.url);
        speciesData = await sres.json();
    } catch { speciesData = null; }

    const name   = data.name;
    const sprite = data.sprites?.other?.['official-artwork']?.front_default
                || data.sprites?.front_default || '';
    const types  = data.types.map(t =>
        t.type.name.charAt(0).toUpperCase() + t.type.name.slice(1)
    ).join('/');
    const hp     = data.stats.find(s => s.stat.name === 'hp')?.base_stat || 45;
    const atk    = data.stats.find(s => s.stat.name === 'attack')?.base_stat || 45;
    const def    = data.stats.find(s => s.stat.name === 'defense')?.base_stat || 45;
    const spd    = data.stats.find(s => s.stat.name === 'speed')?.base_stat || 45;

    // Get English flavor text
    const flavorEntry = speciesData?.flavor_text_entries?.find(e => e.language.name === 'en');
    const flavor = flavorEntry
        ? flavorEntry.flavor_text.replace(/\f|\n/g, ' ').trim()
        : '';

    const displayName = name.split('-').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');

    // Cache in DB for Python side to use
    try {
        await ctx.db.query(
            `INSERT INTO pokemon_cache (key, data) VALUES ($1, $2)
             ON CONFLICT (key) DO UPDATE SET data = $2`,
            [name, JSON.stringify({ name, sprite, types, base_hp: hp, base_atk: atk, base_def: def, base_spd: spd })]
        );
    } catch { /* cache best-effort */ }

    return (
        `__IMG__${sprite}__CAP__` +
        `*${displayName}*\n` +
        `🔷 ${types}\n\n` +
        `_${flavor}_\n\n` +
        `_Data cached. Use .spawn ${name} [zone] to inject it._`
    );
}


// ── _cmdMenu ──────────────────────────────────────────────────
function _cmdMenu() {
    const HEADER = (
        "╭━━★彡 𝚴𝐈ҒԼ𝚮𝚵𝐈𝚳 彡★━━╮\n" +
        "┃  𖤓 Prefix: .\n" +
        "┃  𖤓 Name: Ariel\n" +
        "┃  𖤓 Creator: Ice King\n" +
        "╰━━━━━━━━━━━━━╯\n" +
        "*Use .pmenu for the pokemon menu*\n\n"
    );

    const body = (
        HEADER +
        "*💬 INTERACTION 💬*\n" +
        "┣ ✦ .hug\n┣ ✦ .kiss\n┣ ✦ .slap\n┣ ✦ .pat\n" +
        "┣ ✦ .dance\n┣ ✦ .smile\n┣ ✦ .laugh\n┣ ✦ .cry\n" +
        "┣ ✦ .blush\n┣ ✦ .stare\n┣ ✦ .pout\n┣ ✦ .roar\n" +
        "┣ ✦ .punch\n┣ ✦ .bonk\n┣ ✦ .tickle\n┣ ✦ .lick\n" +
        "┣ ✦ .shrug\n┣ ✦ .shoot\n┣ ✦ .spin\n┣ ✦ .think\n" +
        "┣ ✦ .clap\n┣ ✦ .run\n┣ ✦ .sleep\n┣ ✦ .kidnap\n" +
        "┗━━━━━━━━━━━\n\n" +
        "*😂 FUN 😂*\n" +
        "┣ ✦ .ship\n┣ ✦ .joke\n┣ ✦ .truth\n┣ ✦ .dare\n" +
        "┣ ✦ .wyr\n┣ ✦ .meme\n┣ ✦ .shootmeme\n┣ ✦ .coolmeme\n" +
        "┣ ✦ .sadmeme\n┣ ✦ .triggered\n" +
        "┗━━━━━━━━━━━\n\n" +
        "*🔍 SEARCH 🔍*\n" +
        "┣ ✦ .pint [query]\n┣ ✦ .wallpaper [query]\n┣ ✦ .play [song/video name]\n┣ ✦ .lyrics [song]\n" +
        "┗━━━━━━━━━━━\n\n" +
        "*🤖 AI 🤖*\n" +
        "┣ ✦ .gpt [question]\n┣ ✦ .tldr [text]\n┣ ✦ .copilot [question]\n" +
        "┗━━━━━━━━━━━\n\n" +
        "*🔄 CONVERTER 🔄*\n" +
        "┣ ✦ .sticker\n┣ ✦ .sp [pack name]\n┣ ✦ .toimg\n┣ ✦ .tb (reply to a voice note)\n┣ ✦ .tts [text]\n┣ ✦ .say [question]\n┣ ✦ .voice on/off\n┣ ✦ .translate [text]\n" +
        "┗━━━━━━━━━━━\n\n" +
        "*🛠️ UTILITY 🛠️*\n" +
        "┣ ✦ .ping\n┣ ✦ .uptime\n┣ ✦ .stats\n┣ ✦ .owner\n" +
        "┣ ✦ .whois [@user]\n┣ ✦ .ranks\n┣ ✦ .rules\n┣ ✦ .help [cmd]\n" +
        "┣ ✦ .preview\n┣ ✦ .active [msg]\n┣ ✦ .inactive\n┣ ✦ .online\n┣ ✦ .admin\n" +
        "┗━━━━━━━━━━━\n\n" +
        "*🔧 ADMIN 🔧*\n" +
        "┣ ✦ .warn @user\n┣ ✦ .warnings [@user]\n┣ ✦ .clearwarns @user (.resetwarn)\n" +
        "┣ ✦ .kick @user\n┣ ✦ .mute @user\n┣ ✦ .unmute @user\n" +
        "┣ ✦ .antilink [on/warn/kick/off]\n┣ ✦ .close\n┣ ✦ .open\n" +
        "┣ ✦ .ignore @user\n┣ ✦ .unignore @user\n" +
        "┣ ✦ .promote @user\n┣ ✦ .demote @user\n┣ ✦ .tagall [msg]\n" +
        "┣ ✦ .setwelcome [msg]\n┣ ✦ .setleave [msg]\n┣ ✦ .setrules [msg]\n" +
        "┣ ✦ .pin [msg]\n┣ ✦ .linkgroup/.linkgc [no.]\n┣ ✦ .unlinkgroup/.unlinkgc [no.]\n┣ ✦ .ignoregroup/.ignoregc [no.]\n┣ ✦ .unignoregroup/.unignoregc [no.]\n┣ ✦ .groups · .linkedgroups\n┣ ✦ .arielstatus\n" +
        "┣ ✦ .setactive <x>\n" +
        "┗━━━━━━━━━━━\n\n" +
        "*👑 ROYALTY 👑*\n" +
        "┣ ✦ .crown [title] @user\n┣ ✦ .dethrone @user\n┣ ✦ .ascmd <cmd> <rank>\n┣ ✦ .new rank <name> <power>\n┣ ✦ .delrank <name>\n" +
        "┗━━━━━━━━━━━"
    );

    return `__IMG__https://i.ibb.co/Kj0WDD9J/Ariel-16-Satoru-Ariel.jpg__CAP__${body}`;
}


// ── _cmdPmenu ─────────────────────────────────────────────────
function _cmdPmenu(ctx) {
    const HEADER = (
        "╭━━★彡 𝚴𝐈ҒԼ𝚮𝚵𝐈𝚳 彡★━━╮\n" +
        "┃  𖤓 Prefix: .\n" +
        "┃  𖤓 Name: Ariel\n" +
        "┃  𖤓 Creator: Ice King\n" +
        "╰━━━━━━━━━━━━━╯\n\n"
    );

    const body = (
        HEADER +
        "*⚔️ EXPLORE ⚔️*\n" +
        "┣ ✦ .catch\n┣ ✦ .flee\n┣ ✦ .skills\n┣ ✦ .setskill [name]\n" +
        "┗━━━━━━━━━━━\n\n" +
        "*🗺️ NAVIGATION 🗺️*\n" +
        "┣ ✦ .minimap\n┣ ✦ .location\n" +
        "┗━━━━━━━━━━━\n\n" +
        "*👤 PROFILE 👤*\n" +
        "┣ ✦ .status\n┣ ✦ .pokedex\n┣ ✦ .party\n┣ ✦ .bal\n" +
        "┣ ✦ .resetprofile\n┣ ✦ .hud [1-3]\n" +
        "┗━━━━━━━━━━━"
    );

    return `__IMG__https://i.ibb.co/Kj0WDD9J/Ariel-16-Satoru-Ariel.jpg__CAP__${body}`;
}
	
	

