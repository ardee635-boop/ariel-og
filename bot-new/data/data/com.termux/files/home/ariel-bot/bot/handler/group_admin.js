// bot/handler/group_admin.js - `.linkgc` / `.unlinkgc` / `.ignoregc` / `.unignoregc` / `.ignore` / `.unignore`.
// Moved verbatim out of handleMessage (handler.js, original lines 1204-1314).
// run(ctx) returns CONTINUE to fall through to the next step, or ends handling of the message (return / return value).
import { getRank, getRankLevel } from '../commands.js';
import { sendHidetag, toFraktur, toScript } from '../fancy.js';
import { botState } from '../lib/state.js';
import { getOrderedGroups, saveGroups, saveIgnoredGroups } from '../groups.js';
import { sendText } from '../lib/send.js';
import { _getDB } from '../lib/db.js';
import { log } from '../lib/log.js';
import { CONTINUE } from './_common.js';

export async function run(ctx) {
    let { sock, msg, chatJid, senderJid, lower, lowerCmdOnly, _cmdOverride } = ctx;

    // ── Group admin: link / unlink / ignore / unignore ─────────────
    // Each works on THIS group (no argument) or on any group by its .groups
    // number:  .linkgroup/.linkgc · .unlinkgroup/.unlinkgc ·
    //          .ignoregroup/.ignoregc · .unignoregroup/.unignoregc
    // (the older ".ignore <no.>" / ".unignore <no.>" still work). Floor is
    // Lord+ unless .ascmd has assigned the command a different rank.
    const _gaMap = {
        '.linkgroup': 'link',     '.linkgc': 'link',
        '.unlinkgroup': 'unlink', '.unlinkgc': 'unlink',
        '.ignoregroup': 'ignore', '.ignoregc': 'ignore',
        '.unignoregroup': 'unignore', '.unignoregc': 'unignore',
    };
    const _gaArg = lower.split(' ')[1];
    let _gaAction = _gaMap[lowerCmdOnly] || null;
    if (!_gaAction && (lowerCmdOnly === '.ignore' || lowerCmdOnly === '.unignore')
        && _gaArg && String(parseInt(_gaArg, 10)) === _gaArg) {
        // numeric only — ".ignore @user" belongs to the per-user handler in commands.js
        _gaAction = lowerCmdOnly === '.ignore' ? 'ignore' : 'unignore';
    }
    if (_gaAction) {
        const db = await _getDB();
        let groupParticipants = [], hereSubject = chatJid;
        try {
            const meta = await sock.groupMetadata(chatJid);
            groupParticipants = meta.participants;
            hereSubject = meta.subject || chatJid;
        } catch {}
        const senderRank = await getRank(db, senderJid, groupParticipants, true);
        if (!_cmdOverride && getRankLevel(senderRank) < getRankLevel('lord')) {
            await sendText(sock, chatJid, `👑 _Only royalty (King–Lord) can ${_gaAction} a group._`, msg);
            return;
        }

        let targetId, label;
        if (_gaArg === undefined) {
            if (!chatJid.endsWith('@g.us')) return;
            targetId = chatJid; label = hereSubject;
        } else {
            const idx = parseInt(_gaArg, 10);
            if (String(idx) !== _gaArg || idx < 1) {
                await sendText(sock, chatJid, `_Usage: ${lowerCmdOnly} [no.] — run .groups first to get the number._`, msg);
                return;
            }
            const t = (await getOrderedGroups(sock))[idx - 1];
            if (!t) {
                await sendText(sock, chatJid, `_No group at position ${idx}. Run .groups again._`, msg);
                return;
            }
            targetId = t.id; label = t.subject;
        }
        const here = targetId === chatJid;

        if (_gaAction === 'link') {
            if (botState.allowedGroups.includes(targetId)) {
                await sendText(sock, chatJid, `✦ _Already active${here ? ' in this group' : ` in ${label}`}._`);
                return;
            }
            botState.allowedGroups.push(targetId);
            await saveGroups(botState.allowedGroups);
            log('🔗', `Linked: ${targetId}`);
            await sendText(sock, targetId, '✅ *Ariel activated!* Type *.menu* to begin.');
            if (!here) await sendText(sock, chatJid, `🔗 *Linked ${label}.*`, msg);
            return;
        }
        if (_gaAction === 'unlink') {
            if (!botState.allowedGroups.includes(targetId)) {
                await sendText(sock, chatJid, `_${here ? 'This group' : label} isn't linked._`, msg);
                return;
            }
            botState.allowedGroups = botState.allowedGroups.filter(g => g !== targetId);
            await saveGroups(botState.allowedGroups);
            if (here) {
                await sendText(sock, chatJid, '🚪 *Ariel deactivated.*');
            } else {
                try {
                    await sock.sendMessage(targetId, { text: `🚪 *Ariel has been unlinked from this group.*\n_Contact the owner to re-link._` });
                } catch {}
                await sendText(sock, chatJid, `🚪 *Unlinked from ${label}.*`, msg);
            }
            return;
        }
        if (_gaAction === 'ignore') {
            if (botState.ignoredGroups.includes(targetId)) {
                await sendText(sock, chatJid, `_${here ? 'This group is' : `${label} is`} already ignored._`, msg);
                return;
            }
            if (!botState.allowedGroups.includes(targetId)) {
                await sendText(sock, chatJid, `_${here ? 'This group isn\'t' : `${label} isn't`} linked, so there's nothing to ignore._`, msg);
                return;
            }
            botState.ignoredGroups.push(targetId);
            await saveIgnoredGroups(botState.ignoredGroups);
            // Banishment notice — a hidden tag-everyone in the group itself.
            try {
                await sendHidetag(sock, targetId,
                    `⛓️ ${toFraktur('The King of Niflheim has branded all of you heretics!')}\n\n` +
                    `🔥 ${toFraktur('You have been exiled from Niflheim.')}`);
            } catch (e) { console.warn(`[IGNORE] banishment hidetag failed: ${e.message}`); }
            if (!here) await sendText(sock, chatJid, `🙈 *${label}* is now ignored.`, msg);
            return;
        }
        // unignore
        if (!botState.ignoredGroups.includes(targetId)) {
            await sendText(sock, chatJid, `_${here ? 'This group isn\'t' : `${label} isn't`} ignored._`, msg);
            return;
        }
        botState.ignoredGroups = botState.ignoredGroups.filter(g => g !== targetId);
        await saveIgnoredGroups(botState.ignoredGroups);
        // Pardon notice — a hidden tag-everyone in the group itself.
        try {
            await sendHidetag(sock, targetId,
                `🕊️ ${toScript('The King of Niflheim has forgiven you.')}\n\n` +
                `✨ ${toScript('Your exile is lifted — welcome back to Niflheim.')}`);
        } catch (e) { console.warn(`[IGNORE] pardon hidetag failed: ${e.message}`); }
        if (!here) await sendText(sock, chatJid, `👀 *${label}* is no longer ignored.`, msg);
        return;
    }
    return CONTINUE;
}
