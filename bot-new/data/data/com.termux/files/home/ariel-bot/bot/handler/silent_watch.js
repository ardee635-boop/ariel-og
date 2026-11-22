// bot/handler/silent_watch.js - Messages inside silent groups (watch-number handling, steals, idle chat reactions).
// Moved verbatim out of handleMessage (handler.js, original lines 966-1053).
// run(ctx) returns CONTINUE to fall through to the next step, or ends handling of the message (return / return value).
import { botState } from '../lib/state.js';
import { callPython } from '../bridge.js';
import { _extractRushCommand, _scheduleMineAutoResume } from '../silent/mines.js';
import { MINE_AUTO_RESUME_MS, SILENT_CHAT_FILLERS, SILENT_CHAT_IDLE_REACTION_CHANCE, _isSilentStealFundingCommand, _runSilentSteal, _sendAnyAsArielSilently, _sendAsArielSilently, _watchNumberMatches, isSilentChatGroup, isSilentGroup, saveMines, silentGroupLastSeen } from '../silent/silent.js';
import { _sendArielSticker } from '../chat/stickers.js';
import { CONTINUE } from './_common.js';

export async function run(ctx) {
    let { sock, msg, chatJid, text, senderJid, mentionedJid, quotedText, isBotTagged, isBotQuote } = ctx;

    // ── Track watched-number activity in silent groups ──────────────
    // Any message from the configured watch number resets the timeout clock.
    // If mines were auto-paused, that same message starts a 20-minute
    // countdown for each paused mine label in this group. A `.rush ...`
    // command found anywhere in the message is echoed exactly in canonical
    // `.rush <label>` form; other messages remain completely silent.
    if (isSilentGroup(chatJid)) {
        if (_watchNumberMatches(senderJid)) {
            const seenAt = Date.now();
            silentGroupLastSeen[chatJid] = seenAt;

            const pausedLabels = [...new Set(
                botState.activeMines
                    .filter(m => m.groupJid === chatJid && m.paused && m.autoPaused)
                    .map(m => m.label ?? 1)
            )];

            if (pausedLabels.length) {
                const resumeAt = seenAt + MINE_AUTO_RESUME_MS;
                for (const label of pausedLabels) {
                    for (const mine of botState.activeMines) {
                        if (mine.groupJid === chatJid &&
                            (mine.label ?? 1) === label &&
                            mine.paused &&
                            mine.autoPaused) {
                            mine.autoResumeAt = resumeAt;
                        }
                    }
                    _scheduleMineAutoResume(chatJid, label, resumeAt);
                }
                await saveMines();
            }

            const rushCommand = _extractRushCommand(text);
            if (rushCommand) {
                await _sendAsArielSilently(sock, chatJid, rushCommand);
            }

        }
        // The silent-steal target is independent from the mine watcher.
        // Funding commands are the one exception: give .sell/.wd a chance
        // to replenish the account instead of spending the attempt on steal.
        if (botState.silentStealConfig?.groupJid === chatJid &&
            _watchNumberMatches(senderJid, botState.silentStealConfig.targetNumber) &&
            !_isSilentStealFundingCommand(text)) {
            void _runSilentSteal(
                sock,
                chatJid,
                `${botState.silentStealConfig.targetNumber}@s.whatsapp.net`
            );
        }

        // ── .silentchat — real Ariel chat, ported into a silent group ──
        // Reuses the EXACT same trigger used by an ordinary linked
        // group (see the isBotTagged/isBotQuote → effectiveText →
        // callPython flow further down in this function): every
        // message is forwarded to Python, and Python's own
        // ariel_route() decides whether to respond (it matches the
        // word "ariel" anywhere, or responds because the message
        // quotes/tags the bot). JS does not pre-filter by text content
        // here. EXCEPTION: the .label-watched number is excluded from
        // this chat trigger entirely — that number is reserved for the
        // mine/silent-steal watcher above, not casual Ariel chat, so a
        // message from them here is ignored by .silentchat completely
        // (no reply, no filler). On top of the real chat trigger, a
        // small random chance also adds a bare "mmm"/"hmmm" filler on
        // messages that don't trigger a real reply, for ambient
        // presence. Requires .silent on (global) AND .silentchat on
        // for this specific group. Every send goes through the same
        // typing-indicator disguise as the rest of Ariel's silent
        // presence.
        if (botState.silentPoolOn && isSilentChatGroup(chatJid) && !_watchNumberMatches(senderJid)) {
            const lower_ = text.toLowerCase();
            const effectiveText = (isBotTagged || isBotQuote) && !lower_.includes('ariel')
                ? `ariel ${text}`.trim()
                : text;
            const pythonQuotedText = isBotQuote ? quotedText : null;
            const result = await callPython(senderJid, effectiveText, mentionedJid, chatJid, pythonQuotedText, msg.pushName || null);
            if (result?.response) {
                await _sendAnyAsArielSilently(sock, chatJid, result.response);
                // Previously dropped here — result.sticker was fetched from
                // Python (ariel.py's picker ran fine) but this branch never
                // forwarded it to a send call, so Ariel silently never sent
                // a sticker in any .silentchat-enabled group. Bare send (no
                // quotedMsg) matches this path's disguised/no-quote style.
                await _sendArielSticker(sock, chatJid, result.sticker);
            } else if (Math.random() < SILENT_CHAT_IDLE_REACTION_CHANCE) {
                const filler = SILENT_CHAT_FILLERS[Math.floor(Math.random() * SILENT_CHAT_FILLERS.length)];
                await _sendAsArielSilently(sock, chatJid, filler);
            }
        }

        return;
    }
    return CONTINUE;
}
