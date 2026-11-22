// bot/handler/lang.js - `.lang` (solo / tournament), `.bail`, and replies that answer a running round.
// Engine lives in ../lib/lang_game.js. Runs right after the gates, so link / ignore / mute rules
// already applied. Returns CONTINUE for anything that is not ours.
import { CONTINUE } from './_common.js';
import { LangManager } from '../lib/lang_game.js';
import { isPoolOn } from '../groups.js';

const mgr = new LangManager({
    send: async (chat, text, { mentions, quoted, hide } = {}) => {
        const sock = global.__langSock;
        const opts = quoted ? { quoted } : undefined;
        return sock.sendMessage(chat, mentions?.length ? { text, mentions } : { text }, opts);
    },
    participants: async (chat) => (await global.__langSock.groupMetadata(chat)).participants.map(p => p.id),
});
export { mgr as langManager };

export async function run(ctx) {
    const { sock, msg, chatJid, senderJid, lower, text, isBotQuote } = ctx;
    if (!chatJid.endsWith('@g.us')) return CONTINUE;
    const cmd = lower.split(' ')[0];
    const isCmd = cmd === '.lang' || cmd === '.bail';
    // Anything that is not a .lang/.bail command is only ours if it is a reply to the bot
    // from someone with a running game — cheap checks first so normal chatter costs nothing.
    if (!isCmd && !(isBotQuote && (mgr.tours.has(chatJid) || mgr.solo.size))) return CONTINUE;
    if (!isPoolOn(chatJid, 'normal')) return CONTINUE;

    global.__langSock = sock;
    if (cmd === '.lang') {
        await mgr.command(chatJid, senderJid, lower.split(' ').slice(1), msg);
        return;
    }
    if (cmd === '.bail') {
        return (await mgr.bail(chatJid, senderJid, msg)) ? undefined : CONTINUE;
    }
    return (await mgr.answer(chatJid, senderJid, text, msg)) ? undefined : CONTINUE;
}
