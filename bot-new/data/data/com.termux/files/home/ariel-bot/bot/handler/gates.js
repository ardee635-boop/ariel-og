// bot/handler/gates.js - Link gate, ignored-group gate, per-command rank override, pool toggle commands, normal-pool gate, mute/ignore enforcement.
// Moved verbatim out of handleMessage (handler.js, original lines 1065-1196).
// run(ctx) returns CONTINUE to fall through to the next step, or ends handling of the message (return / return value).
import { isMuted, getRank, getRankLevel, getCommandOverrideRank, rankBadge, isIgnored } from '../commands.js';
import { botState } from '../lib/state.js';
import { PHONE_NUMBER } from '../lib/env.js';
import { GAME_WORLDS, NORMAL_FUN_COMMANDS, POOL_NAMES, isPoolOn, saveGroupPools, setPool } from '../groups.js';
import { sendText } from '../lib/send.js';
import { _getDB } from '../lib/db.js';
import { CONTINUE } from './_common.js';

export async function run(ctx) {
    let { sock, msg, chatJid, senderJid, lower, isKingSender } = ctx;

    // ── LINK GATE (Layer 0) ──────────────────────────────────────
    // Every command in an unlinked group is ignored except the small
    // bootstrap/courtesy set below. This must run before ANY command
    // dispatch — previously ~30 commands (including owner-only ones
    // like .broadcast/.resetgroups/.clearauth, plus the entire
    // interaction/GIF pool) ran before the old link-check at the
    // bottom of this function, meaning they worked in any random
    // unlinked group. That old check (`if (!allowedGroups.includes
    // (chatJid)) return;`) is left in place further down as a
    // defense-in-depth backstop for anything not yet covered here.
    const LINK_GATE_EXEMPT = new Set([
        '.linkgroup',   // must work in an unlinked group to link it
        '.linkgc',
        '.ping',        // courtesy — lets an admin sanity-check the bot is alive pre-link
    ]);
    const lowerCmdOnly = lower.split(' ')[0];
    if (!botState.allowedGroups.includes(chatJid) && !LINK_GATE_EXEMPT.has(lowerCmdOnly)) {
        return;
    }

    // Ignored group: block every command except .ignore/.unignore
    // themselves, so a group can still be unignored from inside itself,
    // not only remotely by number from elsewhere.
    const IGNORE_GATE_EXEMPT = new Set(['.ignore', '.unignore', '.ignoregroup', '.unignoregroup', '.ignoregc', '.unignoregc']);
    if (botState.ignoredGroups.includes(chatJid) && !IGNORE_GATE_EXEMPT.has(lowerCmdOnly)) {
        return;
    }

    // ── .ascmd gate — applies to commands handled in this file too ──────
    // commands.js enforces .ascmd for its own commands; this covers the rest
    // (.linkgroup, .unlinkgroup, .ignore, .pfp, ...). An override REPLACES a
    // command's built-in rank floor, and the King always passes.
    let _cmdOverride = null;
    if (lowerCmdOnly.length > 1 && lowerCmdOnly.startsWith('.')) {
        try {
            const _gdb = await _getDB();
            // .linkgc and .linkgroup (etc.) are the same command to .ascmd
            const _ALIAS = { '.linkgc': '.linkgroup', '.unlinkgc': '.unlinkgroup', '.ignoregc': '.ignoregroup', '.unignoregc': '.unignoregroup',
                             '.linkgroup': '.linkgc', '.unlinkgroup': '.unlinkgc', '.ignoregroup': '.ignoregc', '.unignoregroup': '.unignoregc' };
            _cmdOverride = await getCommandOverrideRank(_gdb, lowerCmdOnly)
                || (_ALIAS[lowerCmdOnly] ? await getCommandOverrideRank(_gdb, _ALIAS[lowerCmdOnly]) : null);
            if (_cmdOverride && !isKingSender) {
                let _gParts = [];
                if (chatJid.endsWith('@g.us')) {
                    try { _gParts = (await sock.groupMetadata(chatJid)).participants; } catch { }
                }
                const _gRank = await getRank(_gdb, senderJid, _gParts, true, chatJid.endsWith('@g.us') ? chatJid : null);
                if (getRankLevel(_gRank) < getRankLevel(_cmdOverride)) {
                    await sendText(sock, chatJid, `🔒 _${lowerCmdOnly} requires ${rankBadge(_cmdOverride)} or higher._`, msg);
                    return;
                }
            }
        } catch (e) { console.warn(`[ASCMD] gate check failed: ${e.message}`); }
    }

    // ── Pool toggles (Layer 1) — .pokemon/.amongus/.chat/.normal/.rpg on/off ──
    const POOL_LABELS = {
        pokemon: 'Pokémon', amongus: 'Among Us', chat: 'Chat', normal: 'Normal', rpg: 'RPG', niflheim: 'Niflheim',
    };
    // Per-pool minimum rank. Every pool here is Baron+ EXCEPT rpg,
    // which is King-only — a deliberate divergence, not an oversight:
    // .rpg on/off used to be a per-sender, unpersisted, ungated
    // toggle living entirely in router/rpg.py's in-memory set(),
    // which meant (a) it reset on every restart and (b) anyone could
    // flip it for themselves. Folding it into this shared pool
    // mechanism fixes persistence (same bot_auth-backed groupPools
    // used by the others) and makes it per-group like the others,
    // but the King-only rank floor here is what actually restricts
    // WHO can flip it, since that was the real ask.
    const POOL_MIN_RANK = {
        pokemon: 'baron', amongus: 'baron', chat: 'baron', normal: 'baron', rpg: 'king', niflheim: 'baron',
    };
    const poolToggleMatch = lowerCmdOnly.startsWith('.') ? lowerCmdOnly.slice(1) : '';
    const poolToggleArg   = lower.split(' ')[1];
    if (POOL_NAMES.includes(poolToggleMatch) && (poolToggleArg === 'on' || poolToggleArg === 'off')) {
        const poolName = poolToggleMatch;
        const minRank  = POOL_MIN_RANK[poolName];

        if (minRank === 'king') {
            if (!isKingSender) {
                await sendText(sock, chatJid, `🧩 _Only the King can toggle the RPG pool._`, msg);
                return;
            }
        } else {
            const db = await _getDB();
            let groupParticipants = [];
            try {
                const meta = await sock.groupMetadata(chatJid);
                groupParticipants = meta.participants;
            } catch {}
            const senderRank = await getRank(db, senderJid, groupParticipants, true, chatJid);
            if (getRankLevel(senderRank) < getRankLevel('baron')) {
                await sendText(sock, chatJid, `🧩 _Only group admins (Baron+) can toggle pools._`, msg);
                return;
            }
        }

        const turnOn = poolToggleArg === 'on';
        // One world per group: switching a game world ON switches the other
        // game worlds OFF in this group (flags only — their internals are untouched).
        const switchedOff = [];
        if (turnOn && GAME_WORLDS.includes(poolName)) {
            for (const w of GAME_WORLDS) {
                if (w !== poolName && isPoolOn(chatJid, w)) {
                    setPool(chatJid, w, false);
                    switchedOff.push(POOL_LABELS[w]);
                }
            }
        }
        setPool(chatJid, poolName, turnOn);
        await saveGroupPools();
        const label = POOL_LABELS[poolName];
        const offNote = switchedOff.length ? ` ${switchedOff.join(', ')} ${switchedOff.length > 1 ? 'were' : 'was'} switched OFF (one world per group).` : '';
        await sendText(sock, chatJid, `🧩 *${label} pool is now ${turnOn ? 'ON' : 'OFF'}* for this group.${offNote}`, msg);
        return;
    }

    // ── Normal pool gate (fun/roleplay commands) ──────────────────
    // Social/roleplay/fun commands: hugs, slaps, memes, truth-or-dare,
    // tic-tac-toe, notes, etc. Silently no-ops if the group hasn't
    // turned the pool on with .normal on. Deliberately excludes
    // .sticker/.s/.toimg/.translate/.tt/.pint/.wallpaper/.copilot —
    // those are utility/converter commands and live in Normal too,
    // just handled elsewhere rather than in this set.
    // .sleep is shared with the King-only mine sleep-window feature
    // (".sleep <window>", handled earlier and returns before reaching
    // here) — only bare ".sleep" (the fun gif) is actually gated below.
    // NOTE: .silentchat is unrelated to this pool entirely — see the
    // ambient-reaction logic inside the isSilentGroup() block instead,
    // where Ariel reacts on her own initiative in a silent-linked
    // group. This gate is only for members explicitly typing a fun
    // command in an ordinary linked group.
    if (NORMAL_FUN_COMMANDS.has(lowerCmdOnly) && !isPoolOn(chatJid, 'normal')) {
        return;
    }

    // -- Per-user mute / ignore (moved up from below the utility commands) --
    // This check used to sit after ~1,300 lines of utility commands, so a muted
    // or ignored user's .ping/.uptime/.owner/.sticker/... still got answered.
    // Muted: delete the message for everyone (bot needs group admin), then drop
    // it. Ignored: just drop it, no delete.
    if (chatJid.endsWith('@g.us') && botState.allowedGroups.includes(chatJid)
        && senderJid.split('@')[0] !== PHONE_NUMBER) {
        const _modDb = await _getDB();
        if (await isMuted(_modDb, chatJid, senderJid)) {
            try {
                await sock.sendMessage(chatJid, { delete: msg.key });
            } catch (e) {
                console.warn(`[MUTE] Could not delete message from ${senderJid} in ${chatJid}: ${e.message}`);
            }
            return;
        }
        if (await isIgnored(_modDb, chatJid, senderJid)) return;
    }
    ctx.lowerCmdOnly = lowerCmdOnly;
    ctx._cmdOverride = _cmdOverride;
    return CONTINUE;
}
