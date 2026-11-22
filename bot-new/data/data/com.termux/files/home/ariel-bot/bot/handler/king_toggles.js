// bot/handler/king_toggles.js - King-only toggles (`.silent on/off`, `.chatdm`, `.forcechatoff`), silent work/card/watch shortcuts and the silent-pool gate.
// Moved verbatim out of handleMessage (handler.js, original lines 300-426).
// run(ctx) returns CONTINUE to fall through to the next step, or ends handling of the message (return / return value).
import { getRank, getRankLevel } from '../commands.js';
import { handleWorkMessage, handleWorkCommand, handleCardCommand, handleWatchCommand, handleActiveCommand } from '../work.js';
import { botState } from '../lib/state.js';
import { saveChatDm, saveGroupPools, saveSilentPool, setPool } from '../groups.js';
import { _replyMaybeSilent } from '../silent/mines.js';
import { _getDB } from '../lib/db.js';
import { saveSilentChatGroups } from '../silent/silent.js';
import { CONTINUE } from './_common.js';

export async function run(ctx) {
    let { sock, msg, chatJid, text, senderJid, isBotTagged, isBotQuote, lower, isKingSender, lowerCmdOnlyPre } = ctx;

    // ── .work / .card auto-play (lives alongside .mine/.label) ─────
    // Host/card-bot messages feed the watcher; King commands configure it.
    // Commands: .silentwork/.swork, .silentcard/.scard, .silentwatch reset.
    if (chatJid.endsWith('@g.us')) {
        await handleWorkMessage(chatJid, senderJid, text, {
            toUs: isBotQuote || isBotTagged,   // host answers each player by quoting their .work
            say: (t) => _replyMaybeSilent(sock, chatJid, t, msg),
        });
    }
    const _isWorkCmd  = lowerCmdOnlyPre === '.silentwork'  || lowerCmdOnlyPre === '.swork';
    const _isCardCmd  = lowerCmdOnlyPre === '.silentcard'  || lowerCmdOnlyPre === '.scard';
    const _isWatchCmd = lowerCmdOnlyPre === '.silentwatch';
    const _isActiveCmd = lowerCmdOnlyPre === '.silentactive' || lowerCmdOnlyPre === '.sactive';
    if (isKingSender && botState.silentPoolOn && (_isWorkCmd || _isCardCmd || _isWatchCmd || _isActiveCmd)) {
        // Same reply path as .mine/.label: a normal reply in the linked group
        // you typed it in (disguised only if that group is silent-linked).
        const _wReply = (t) => _replyMaybeSilent(sock, chatJid, t, msg);
        try {
            if (_isWorkCmd) await handleWorkCommand(sock, chatJid, text, _wReply);
            else if (_isCardCmd) await handleCardCommand(sock, chatJid, text, _wReply);
            else if (_isActiveCmd) await handleActiveCommand(sock, chatJid, text, _wReply);
            else await handleWatchCommand(text, _wReply);
        } catch (e) {
            await _wReply(`⚠️ ${e.message}`);
        }
        return;
    }

    // ── .silent on/off — global King-only switch for the whole ─────
    // King-only ops cluster below (.silentlink, .ssteal, .mine,
    // .hidetag, .broadcast, etc). Not per-group — see loadSilentPool.
    if (lower === '.silent on' || lower === '.silent off') {
        if (!isKingSender) return;
        botState.silentPoolOn = lower.endsWith(' on');
        await saveSilentPool();
        await _replyMaybeSilent(sock, chatJid, `🧩 *Silent pool is now ${botState.silentPoolOn ? 'ON' : 'OFF'}* (global).`, msg);
        return;
    }

    // ── .chatdm on/off — global, King/Queen-only, Ariel chat in DMs ──
    // Single toggle for Ariel actually holding conversations in 1:1
    // DMs (replaces the old separate .chatdm + .chatbot pair — see
    // chatDmOn's comment above). Group-only: not reachable from a DM
    // itself, since royalty rank needs a DB lookup (Queen isn't a
    // hardcoded number like King, so this can't reuse the bare
    // isKingSender check above — needs an actual rank fetch, same as
    // the per-group pool toggles below but gated higher: King(100) or
    // Queen(90), nothing lower).
    if (lower === '.chatdm on' || lower === '.chatdm off') {
        const db = await _getDB();
        let groupParticipants = [];
        try {
            const meta = await sock.groupMetadata(chatJid);
            groupParticipants = meta.participants;
        } catch {}
        const senderRank = await getRank(db, senderJid, groupParticipants, true);
        if (getRankLevel(senderRank) < getRankLevel('queen')) {
            await _replyMaybeSilent(sock, chatJid, `🧩 _Only the King or Queen can toggle Chat-in-DMs._`, msg);
            return;
        }
        botState.chatDmOn = lower.endsWith(' on');
        await saveChatDm();
        await _replyMaybeSilent(sock, chatJid, `🧩 *Chat-in-DMs is now ${botState.chatDmOn ? 'ON' : 'OFF'}* (global).`, msg);
        return;
    }

    // ── .forcechatoff — King-only emergency kill-switch ─────────────
    // Forces off every flag that can make Ariel hold an unprompted
    // conversation, in one shot, no matter what state each one is
    // currently in. Built for exactly the situation that motivated
    // it: Ariel was replying to every message in a group (turned out
    // to be .chat left on) and nobody wanted to hunt down which of
    // several separate toggles was responsible or wait to confirm
    // before acting. Deliberately idempotent — safe to run even if
    // some of these are already off, and safe to run more than once.
    // Covers, in this group specifically (chatdm is the one global
    // exception — it has no per-group form to force off):
    //   .chatdm     — global DM conversation flag (chatDmOn)
    //   .chat       — per-group conversation flag (groupPools[chatJid].chat)
    //   .silentchat — removes this group from the silent-chat list
    // .chatbot doesn't exist anymore — it was folded into .chatdm.
    if (lower === '.forcechatoff') {
        if (!isKingSender) return;

        botState.chatDmOn = false;
        await saveChatDm();

        setPool(chatJid, 'chat', false);
        await saveGroupPools();

        const wasSilentChat = botState.silentChatGroups.includes(chatJid);
        if (wasSilentChat) {
            botState.silentChatGroups = botState.silentChatGroups.filter(g => g !== chatJid);
            await saveSilentChatGroups();
        }

        await _replyMaybeSilent(
            sock, chatJid,
            `🛑 *All chat triggers forced OFF.*\n` +
            `• Chat-in-DMs (global): OFF\n` +
            `• .chat (this group): OFF\n` +
            `• .silentchat (this group): ${wasSilentChat ? 'OFF (was on)' : 'already off'}`,
            msg
        );
        return;
    }
    // .silent itself must always be reachable so the King can turn the
    // cluster back on — every other command in this cluster is gated.
    // NOTE: bare ".sleep" (no args) is excluded on purpose — it's also
    // the Chat-pool fun gif command (see LOCAL_IMAGES below) and must
    // fall through when Silent is off. ".sleep <window>" (has args),
    // ".sleeps", and ".unsleep" ARE part of the King-only mine
    // sleep-window feature and are gated separately just below, since
    // they share a prefix with the Chat command and can't go in the
    // simple prefix-list check.
    const hasSleepWindowArgs = lower.startsWith('.sleep ') && lower.trim() !== '.sleep';
    if (!botState.silentPoolOn && (hasSleepWindowArgs || lower === '.sleeps' || lowerCmdOnlyPre === '.unsleep')) {
        if (!isKingSender) return; // let it fall through to the ordinary King-check message below if any
        await _replyMaybeSilent(sock, chatJid, '_Silent pool is off — turn it on with .silent on._', msg);
        return;
    }
    // .silent and .royalmenu (a help/reference command) must always be
    // reachable regardless of pool state — every operational command
    // in this cluster is gated below.
    if (!botState.silentPoolOn && lowerCmdOnlyPre !== '.silent' && lowerCmdOnlyPre !== '.royalmenu') {
        const SILENT_CLUSTER_PREFIXES = [
            '.silentlink', '.silentunlink', '.silentchat', '.ssteal', '.silentsteal',
            '.silenttmenu', '.smenu', '.mine', '.mines', '.unmine',
            '.broadcast',
        ];
        if (SILENT_CLUSTER_PREFIXES.includes(lowerCmdOnlyPre)) return;
    }
    return CONTINUE;
}
