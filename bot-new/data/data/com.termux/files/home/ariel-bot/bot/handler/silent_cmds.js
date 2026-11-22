// bot/handler/silent_cmds.js - Silent-cluster commands: silentlink/unlink/chat, label, ssteal, silent menus, mines, sleep windows.
// Moved verbatim out of handleMessage (handler.js, original lines 478-958).
// run(ctx) returns CONTINUE to fall through to the next step, or ends handling of the message (return / return value).
import { botState } from '../lib/state.js';
import { getOrderedGroups } from '../groups.js';
import { sendText } from '../lib/send.js';
import { _armMineTimer, _clearMineAutoResumeTimer, _disarmMineTimer, _parseDuration, _replyMaybeSilent } from '../silent/mines.js';
import { _normalizeWatchNumber, _sendAsArielSilently, isSilentGroup, saveMineWatchNumber, saveMines, saveSilentChatGroups, saveSilentGroups, saveSilentStealNumber, silentGroupLastSeen } from '../silent/silent.js';
import { _fmtMinutes, _isSleeping, _parseSleepWindow, saveSleepWindows } from '../silent/sleep.js';
import { CONTINUE } from './_common.js';

export async function run(ctx) {
    let { sock, msg, chatJid, text, lower, isKingSender } = ctx;

    if (lower.startsWith('.silentlink')) {
        if (!isKingSender) return;
        const parts = lower.split(' ');
        const idx = parseInt(parts[1], 10);
        if (!idx || idx < 1) {
            await _replyMaybeSilent(sock, chatJid, '_Usage: .silentlink <gc no.> — run .groups first to get the number._', msg);
            return;
        }
        try {
            const list = await getOrderedGroups(sock);
            const target = list[idx - 1];
            if (!target) {
                await _replyMaybeSilent(sock, chatJid, `_No group at position ${idx}. Run .groups again._`, msg);
                return;
            }
            if (!botState.silentGroups.includes(target.id)) {
                botState.silentGroups.push(target.id);
                await saveSilentGroups();
            }
            // Ariel "announces" herself in-character in the target group,
            // preceded by the same 3s typing indicator used for mines —
            // this is deliberate: it's the one message that establishes
            // her presence there, and it should look organic too.
            await _sendAsArielSilently(sock, target.id, '...');
            if (target.id !== chatJid) {
                await sendText(sock, chatJid, `🤫 _Silently linked to *${target.subject}*._`, msg);
            }
        } catch (e) {
            await _replyMaybeSilent(sock, chatJid, `⚠️ Couldn't silent-link: ${e.message}`, msg);
        }
        return;
    }

    if (lower.startsWith('.silentunlink')) {
        if (!isKingSender) return;
        const parts = lower.split(' ');
        const idx = parseInt(parts[1], 10);
        if (!idx || idx < 1) {
            await _replyMaybeSilent(sock, chatJid, '_Usage: .silentunlink <gc no.> — run .groups first to get the number._', msg);
            return;
        }
        try {
            const list = await getOrderedGroups(sock);
            const target = list[idx - 1];
            if (!target) {
                await _replyMaybeSilent(sock, chatJid, `_No group at position ${idx}. Run .groups again._`, msg);
                return;
            }
            if (!botState.silentGroups.includes(target.id)) {
                await _replyMaybeSilent(sock, chatJid, `_${target.subject} isn't silent-linked._`, msg);
                return;
            }
            // Stop any mines still targeting this group before it's
            // removed — otherwise they'd keep firing into a group Ariel
            // is no longer tracked as being silently present in.
            const stopped = botState.activeMines.filter(mn => mn.groupJid === target.id);
            if (stopped.length) {
                for (const mn of stopped) _disarmMineTimer(mn.id);
                botState.activeMines = botState.activeMines.filter(mn => mn.groupJid !== target.id);
                await saveMines();
            }
            botState.silentGroups = botState.silentGroups.filter(g => g !== target.id);
            await saveSilentGroups();
            // Plain send, no typing-indicator ceremony, no special
            // handling — just the exit line, same as any normal message.
            await sendText(sock, target.id, '...');
            if (target.id !== chatJid) {
                const stoppedNote = stopped.length ? ` (${stopped.length} mine${stopped.length > 1 ? 's' : ''} stopped)` : '';
                await sendText(sock, chatJid, `🤫 _Silently unlinked from *${target.subject}*.${stoppedNote}_`, msg);
            }
        } catch (e) {
            await _replyMaybeSilent(sock, chatJid, `⚠️ Couldn't silent-unlink: ${e.message}`, msg);
        }
        return;
    }

    // ── .silentchat on/off <gc no.> — enable/disable the Chat command ──
    // cluster (.hug/.kiss/.slap/etc) inside an already silent-linked
    // group. Same .groups-index UX as .silentlink/.silentunlink. The
    // target group must already be silent-linked — this only toggles
    // whether Chat commands additionally run there.
    if (lower.startsWith('.silentchat ')) {
        if (!isKingSender) return;
        const scParts = lower.split(' ');
        const scMode  = scParts[1]; // 'on' or 'off'
        const scIdx   = parseInt(scParts[2], 10);
        if ((scMode !== 'on' && scMode !== 'off') || !scIdx || scIdx < 1) {
            await _replyMaybeSilent(sock, chatJid, '_Usage: .silentchat on/off <gc no.> — run .groups first to get the number._', msg);
            return;
        }
        try {
            const list = await getOrderedGroups(sock);
            const target = list[scIdx - 1];
            if (!target) {
                await _replyMaybeSilent(sock, chatJid, `_No group at position ${scIdx}. Run .groups again._`, msg);
                return;
            }
            if (!botState.silentGroups.includes(target.id)) {
                await _replyMaybeSilent(sock, chatJid, `_${target.subject} isn't silent-linked yet — run .silentlink ${scIdx} first._`, msg);
                return;
            }
            const turnOn = scMode === 'on';
            if (turnOn) {
                if (!botState.silentChatGroups.includes(target.id)) botState.silentChatGroups.push(target.id);
            } else {
                botState.silentChatGroups = botState.silentChatGroups.filter(g => g !== target.id);
            }
            await saveSilentChatGroups();
            await _replyMaybeSilent(sock, chatJid, `🤫 *Silent-chat is now ${turnOn ? 'ON' : 'OFF'}* for *${target.subject}*.`, msg);
        } catch (e) {
            await _replyMaybeSilent(sock, chatJid, `⚠️ Couldn't toggle silent-chat: ${e.message}`, msg);
        }
        return;
    }

    // ── .label — choose the number used by the silent-link watcher ──
    // `.label none` turns the watcher off without affecting the mines
    // themselves. The value is persisted so it survives a reconnect/restart.
    if (lower === '.label' || lower.startsWith('.label ')) {
        if (!isKingSender) return;
        const labelArg = text.slice(text.toLowerCase().indexOf('.label') + 6).trim();
        if (!labelArg) {
            await _replyMaybeSilent(
                sock,
                chatJid,
                botState.mineWatchNumber
                    ? `🏷️ *Mine watch label:* \`${botState.mineWatchNumber}\`\n_.label <number> to change · .label none to disable_`
                    : '🏷️ *Mine watch label is disabled.*\n_.label <number> to enable it_',
                msg
            );
            return;
        }

        if (labelArg.toLowerCase() === 'none') {
            botState.mineWatchNumber = null;
        } else {
            botState.mineWatchNumber = _normalizeWatchNumber(labelArg);
            if (!botState.mineWatchNumber) {
                await _replyMaybeSilent(sock, chatJid, '_Usage: .label <phone number> or .label none_', msg);
                return;
            }
        }

        if (botState.mineWatchNumber) {
            for (const groupJid of Object.keys(silentGroupLastSeen)) {
                silentGroupLastSeen[groupJid] = Date.now();
            }
        }
        await saveMineWatchNumber();
        await _replyMaybeSilent(
            sock,
            chatJid,
            botState.mineWatchNumber
                ? `✅ *Mine watch number changed* to \`${botState.mineWatchNumber}\`.`
                : '✅ *Mine watch check cancelled.* Mines will no longer auto-pause for a missing reply.',
            msg
        );
        return;
    }

    // ── .ssteal / .silentsteal — configure automatic stealing ──
    // Usage: .ssteal <silent group no.> <target number>
    // The command is handled before the silent-group return so the owner can
    // configure it from inside a silent-linked group.
    if (lower === '.ssteal' || lower.startsWith('.ssteal ') ||
        lower === '.silentsteal' || lower.startsWith('.silentsteal ')) {
        if (!isKingSender) return;
        const commandName = lower.startsWith('.ssteal') ? '.ssteal' : '.silentsteal';
        const args = text.slice(text.toLowerCase().indexOf(commandName) + commandName.length).trim();
        if (!args) {
            await _replyMaybeSilent(
                sock,
                chatJid,
                botState.silentStealConfig?.groupJid
                    ? `🕵️ *Silent-steal:* group *${botState.silentStealConfig.groupLabel}* · target \`${botState.silentStealConfig.targetNumber}\`\n_.ssteal <group no.> <number> to change · .ssteal none to disable_`
                    : '🕵️ *Silent-steal is disabled.*\n_.ssteal <group no.> <number> to enable it_',
                msg
            );
            return;
        }

        if (args.toLowerCase() === 'none') {
            botState.silentStealConfig = null;
            await saveSilentStealNumber();
            await _replyMaybeSilent(sock, chatJid, '✅ *Silent-steal disabled.*', msg);
            return;
        }

        const parts = args.split(/\s+/);
        const groupIndex = parseInt(parts[0], 10);
        const targetNumber = _normalizeWatchNumber(parts.slice(1).join(' '));
        if (!groupIndex || groupIndex < 1 || !targetNumber) {
            await _replyMaybeSilent(
                sock,
                chatJid,
                '_Usage: .ssteal <silent group no.> <target number>  — or .ssteal none_',
                msg
            );
            return;
        }

        try {
            const groups = await getOrderedGroups(sock);
            const targetGroup = groups[groupIndex - 1];
            if (!targetGroup) {
                await _replyMaybeSilent(sock, chatJid, `_No group at position ${groupIndex}. Run .groups first._`, msg);
                return;
            }
            if (!isSilentGroup(targetGroup.id)) {
                await _replyMaybeSilent(
                    sock,
                    chatJid,
                    `_${targetGroup.subject} isn't silent-linked. Use .silentlink ${groupIndex} first._`,
                    msg
                );
                return;
            }

            botState.silentStealConfig = {
                groupJid: targetGroup.id,
                groupLabel: targetGroup.subject,
                targetNumber,
            };
            await saveSilentStealNumber();
            await _replyMaybeSilent(
                sock,
                chatJid,
                `✅ *Silent-steal enabled* in *${targetGroup.subject}* for \`${targetNumber}\`.\n_When that number sends, Ariel will run *.steal @${targetNumber}* and forward the normal result/cooldown. Messages containing *.sell* or *.wd* are skipped._`,
                msg
            );
        } catch (e) {
            await _replyMaybeSilent(sock, chatJid, `⚠️ Couldn't configure silent-steal: ${e.message}`, msg);
        }
        return;
    }

    // ── .silenttmenu / .smenu — silent-link command reference ──
    // NOTE: was aliased to ".amenu" before — that's a real, separate
    // Among Us menu command handled in Python (router/amongus.py's
    // _amenu()) and was being wrongly hijacked here. Renamed to
    // .smenu so .amenu reaches its actual Among Us menu again.
    if (lower === '.silenttmenu' || lower === '.smenu') {
        if (!isKingSender) return;
        await _replyMaybeSilent(
            sock,
            chatJid,
            `🤫 *Silent-link commands*\n\n` +
            `• *.groups* — all groups, marked 🔗 linked · 🤫 silent · 🙈 ignored\n` +
            `• *.linkedgroups* — only linked groups\n` +
            `• *.linkgc/.unlinkgc/.ignoregc/.unignoregc [no.]* — link, unlink, ignore, unignore\n` +
            `• *.silentlink <no.>* — silently link a group\n` +
            `• *.silentunlink <no.>* — remove a silent link\n` +
            `• *.silentchat on/off <no.>* — enable/disable Chat commands (.hug/.slap/etc) in a silent-linked group\n` +
            `• *.mine <gc no.> <text> <time> [label]* — start a mine\n` +
            `• *.mines* — list mines and pause status\n` +
            `• *.mine pause <label>* / *.mine resume <label>*\n` +
            `• *.unmine <no.>* — stop one mine\n` +
            `• *.sleep <start>-<end>* / *.sleeps* / *.unsleep <no.>*\n` +
            `• *.label <number>* — change the watched number\n` +
            `• *.label none* — cancel the watch check\n\n` +
            `• *.ssteal <group no.> <number>* — run .steal @number there\n` +
            `• *.silentsteal <group no.> <number>* — same command\n` +
            `• *.ssteal none* — disable automatic stealing\n\n` +
            `• Watched *.rush <label>* — silently echoes the exact rush command\n\n` +
            `_The silent-steal target is checked on every message. Messages containing .sell or .wd are skipped, while normal .steal success, failure, and cooldown replies are forwarded._`,
            msg
        );
        return;
    }

    // ── .royalmenu — the full King-only command reference ──────────
    // Successor to .silenttmenu/.smenu: everything in that menu, PLUS
    // the ungated King-only ops that live outside the silent-link
    // cluster (.hidetag/.broadcast/.linked/.resetgroups/.clearauth),
    // PLUS the global pool switches (.silent, .chatdm) added alongside
    // .chat/.normal/.silentchat. One place to see the whole King
    // surface instead of hunting across .silenttmenu/.smenu/.menu.
    if (lower === '.royalmenu') {
        if (!isKingSender) return;
        await _replyMaybeSilent(
            sock,
            chatJid,
            `👑 *Royal Menu — full King command reference*\n\n` +
            `*🧩 Pool switches*\n` +
            `• *.pokemon on/off* · *.amongus on/off* · *.normal on/off* — per-group (Baron+)\n` +
            `• *.chat on/off* — per-group (Baron+), Ariel chats with everyone in that group\n` +
            `• *.silent on/off* — global, King-only, gates everything below marked 🤫\n` +
            `• *.chatdm on/off* — global, King/Queen-only, Ariel chats back in any 1:1 DM (name/reply/greeting triggers)\n\n` +
            `*🤫 Silent-link ops* (need .silent on)\n` +
            `• *.groups* — all groups, marked 🔗 linked · 🤫 silent · 🙈 ignored\n` +
            `• *.linkedgroups* — only linked groups\n` +
            `• *.linkgc/.unlinkgc/.ignoregc/.unignoregc [no.]* — link, unlink, ignore, unignore\n` +
            `• *.silentlink <no.>* / *.silentunlink <no.>*\n` +
            `• *.silentchat on/off <no.>* — Chat commands in that silent group\n` +
            `• *.mine <gc no.> <text> <time> [label]* / *.mines* / *.unmine <no.>*\n` +
            `• *.mine pause/resume <label>*\n` +
            `• *.sleep <start>-<end>* / *.sleeps* / *.unsleep <no.>*\n` +
            `• *.label <number>* / *.label none*\n` +
            `• *.swork on/off <gc no.>* / *.swork label <gc no.> <time>* / *.swork watch <number>* / *.swork status* (alias .silentwork)\n` +
            `• *.scard on/off <gc no.>* / *.scard watch <number>* / *.scard clear* (alias .silentcard)\n` +
            `• *.silentwatch reset* — all work + card watch numbers back to pending\n` +
            `• *.ssteal <group no.> <number>* / *.silentsteal ...* / *.ssteal none*\n\n` +
            `*👑 Other King-only*\n` +
            `• *.linked* — list all linked groups\n` +
            `• *.resetgroups* — wipe linked-groups list\n` +
            `• *.clearauth* — clear WhatsApp auth and re-link\n` +
            `• *.hidetag <text>* — silent tag-all in this group (or reply to a message with *.hidetag* to tag-all with that message)\n` +
            `• *.broadcast <text>* — silent tag-all in every linked group (also works as a reply)\n\n` +
            `_Use *.menumenu* (aka .allmenu/.menus) to see an index of every menu command._`,
            msg
        );
        return;
    }

    if (lower.startsWith('.mine ')) {
        if (!isKingSender) return;

        // ── .mine pause <label> / .mine resume <label> ───────────────
        const mineParts = lower.split(' ');
        if (mineParts[1] === 'pause' || mineParts[1] === 'resume') {
            const isPause = mineParts[1] === 'pause';
            const labelArg = parseInt(mineParts[2], 10);
            if (!labelArg || labelArg < 1) {
                await _replyMaybeSilent(sock, chatJid,
                    `_Usage: .mine pause <mine no.>  or  .mine resume <mine no.>_`, msg);
                return;
            }
            const targets = botState.activeMines.filter(m => (m.label ?? 1) === labelArg);
            if (!targets.length) {
                await _replyMaybeSilent(sock, chatJid, `_No mines with label ${labelArg}._`, msg);
                return;
            }
            for (const m of targets) {
                m.paused = isPause;
                m.autoPaused = false;
                m.autoResumeAt = null;
                _clearMineAutoResumeTimer(m.groupJid, m.label ?? 1);
            }
            await saveMines();
            // When resuming, reset the lastSeen clock so the auto-timeout
            // doesn't immediately re-trigger before the watched number replies.
            if (!isPause) {
                for (const m of targets) {
                    silentGroupLastSeen[m.groupJid] = Date.now();
                }
            }
            const verb = isPause ? '⏸ Paused' : '▶️ Resumed';
            await _replyMaybeSilent(sock, chatJid,
                `⛏️ *${verb} mine ${labelArg}* — ${targets.length} mine${targets.length > 1 ? 's' : ''} affected.`, msg);
            return;
        }

        // ── .mine <gc no.> <text> <time> [mine no.] ─────────────────
        // e.g. .mine 1 .fish 10s 2   →  mine label 2 (defaults to 1)
        const rest = text.slice(text.toLowerCase().indexOf('.mine') + 5).trim();
        const m = /^(\d+)\s+(.+?)\s+(\d+(?:\.\d+)?\s*(?:ms|s|m|h))(?:\s+(\d+))?$/i.exec(rest);
        if (!m) {
            await _replyMaybeSilent(sock, chatJid,
                '_Usage: .mine <gc no.> (text) (time) [mine no.] — e.g. .mine 1 .fish 10s 2 (mine no. defaults to 1)_', msg);
            return;
        }
        const idx        = parseInt(m[1], 10);
        const mineText   = m[2].trim();
        const intervalMs = _parseDuration(m[3]);
        const mineLabel  = m[4] ? parseInt(m[4], 10) : 1;
        if (!intervalMs || intervalMs < 1000) {
            await _replyMaybeSilent(sock, chatJid, '_Interval must be at least 1s._', msg);
            return;
        }
        try {
            const list = await getOrderedGroups(sock);
            const target = list[idx - 1];
            if (!target) {
                await _replyMaybeSilent(sock, chatJid, `_No group at position ${idx}. Run .groups again._`, msg);
                return;
            }
            if (!isSilentGroup(target.id)) {
                await _replyMaybeSilent(sock, chatJid, `_${target.subject} isn't silent-linked. Use .silentlink ${idx} first._`, msg);
                return;
            }
            const mine = {
                id: `${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
                groupJid: target.id,
                groupLabel: target.subject,
                text: mineText,
                intervalMs,
                label: mineLabel,
                paused: false,
                startedAt: Date.now(),
            };
            botState.activeMines.push(mine);
            await saveMines();
            _armMineTimer(mine);
            const confirmMsg = `⛏️ *Mine ${mineLabel} started* in *${target.subject}* — sending "${mineText}" every ${m[3].trim()}.`;
            await _replyMaybeSilent(sock, chatJid, confirmMsg, msg);
        } catch (e) {
            await _replyMaybeSilent(sock, chatJid, `⚠️ Couldn't start mine: ${e.message}`, msg);
        }
        return;
    }

    if (lower === '.mines') {
        if (!isKingSender) return;
        if (!botState.activeMines.length) {
            await _replyMaybeSilent(sock, chatJid, '_No mines currently running._', msg);
            return;
        }
        const lines = botState.activeMines.map((mn, i) => {
            const secs       = Math.round(mn.intervalMs / 1000);
            const elapsedMin = Math.round((Date.now() - mn.startedAt) / 60000);
            const labelNote  = `[mine ${mn.label ?? 1}] `;
            const pausedNote = mn.paused
                ? (mn.autoPaused
                    ? ` ⏸ *auto-paused${mn.autoResumeAt ? ` · resumes ${new Date(mn.autoResumeAt).toLocaleTimeString('en-NG', { hour: '2-digit', minute: '2-digit' })}` : ''}*`
                    : ' ⏸ *paused*')
                : '';
            return `${i + 1}. ${labelNote}*${mn.groupLabel}* — "${mn.text}" every ${secs}s (running ${elapsedMin}m)${pausedNote}`;
        });
        await _replyMaybeSilent(sock, chatJid,
            `⛏️ *Active mines:*\n\n${lines.join('\n')}\n\n_.unmine <no.> to stop · .mine pause/resume <mine no.> to toggle_`, msg);
        return;
    }

    if (lower.startsWith('.unmine ')) {
        if (!isKingSender) return;
        const idx = parseInt(lower.split(' ')[1], 10);
        if (!idx || idx < 1 || idx > botState.activeMines.length) {
            await _replyMaybeSilent(sock, chatJid, '_Usage: .unmine <no.> — see .mines for the list._', msg);
            return;
        }
        const [removed] = botState.activeMines.splice(idx - 1, 1);
        _disarmMineTimer(removed.id);
        await saveMines();
        await _replyMaybeSilent(sock, chatJid, `⛏️ *Mine stopped* in *${removed.groupLabel}*.`, msg);
        return;
    }

    if (lower.startsWith('.sleep ')) {
        if (!isKingSender) return;
        const rawWindow = text.slice(text.toLowerCase().indexOf('.sleep') + 6).trim();
        const parsed = _parseSleepWindow(rawWindow);
        if (!parsed) {
            await _replyMaybeSilent(sock, chatJid, '_Usage: .sleep <start>-<end> — e.g. .sleep 11:00am-12:00pm or .sleep 23:00-06:00_', msg);
            return;
        }
        const window = {
            id: `${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
            label: rawWindow,
            startMin: parsed.startMin,
            endMin: parsed.endMin,
        };
        botState.sleepWindows.push(window);
        await saveSleepWindows();
        await _replyMaybeSilent(sock, chatJid, `😴 *Sleep window added:* ${_fmtMinutes(parsed.startMin)}–${_fmtMinutes(parsed.endMin)} — every mine everywhere goes fully quiet during this window.`, msg);
        return;
    }

    if (lower === '.sleeps') {
        if (!isKingSender) return;
        if (!botState.sleepWindows.length) {
            await _replyMaybeSilent(sock, chatJid, '_No sleep windows set._', msg);
            return;
        }
        const lines = botState.sleepWindows.map((w, i) => `${i + 1}. ${_fmtMinutes(w.startMin)}–${_fmtMinutes(w.endMin)}`);
        const activeNote = _isSleeping() ? '\n\n_😴 Currently inside a sleep window — mines are quiet right now._' : '';
        await _replyMaybeSilent(sock, chatJid, `😴 *Sleep windows:*\n\n${lines.join('\n')}\n\n_.unsleep <no.> to remove one_${activeNote}`, msg);
        return;
    }

    if (lower.startsWith('.unsleep ')) {
        if (!isKingSender) return;
        const idx = parseInt(lower.split(' ')[1], 10);
        if (!idx || idx < 1 || idx > botState.sleepWindows.length) {
            await _replyMaybeSilent(sock, chatJid, '_Usage: .unsleep <no.> — see .sleeps for the list._', msg);
            return;
        }
        const [removed] = botState.sleepWindows.splice(idx - 1, 1);
        await saveSleepWindows();
        await _replyMaybeSilent(sock, chatJid, `😴 *Sleep window removed:* ${_fmtMinutes(removed.startMin)}–${_fmtMinutes(removed.endMin)}.`, msg);
        return;
    }
    return CONTINUE;
}
