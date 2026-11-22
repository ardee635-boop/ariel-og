// bot/handler/wcg.js - `.wcg` (Word Chain Game) and the plain-text words players type on their turn.
// Engine lives in ../lib/wcg_game.js. Runs right after .lang, so link / ignore / mute rules already applied.
// Returns CONTINUE for anything that is not ours.
import { CONTINUE } from './_common.js';
import { WcgManager, loadBigWords } from '../lib/wcg_game.js';
import { isPoolOn } from '../groups.js';

const mgr = new WcgManager({
    send: async (chat, text, { mentions, quoted } = {}) => {
        const sock = global.__wcgSock;
        const opts = quoted ? { quoted } : undefined;
        return sock.sendMessage(chat, mentions?.length ? { text, mentions } : { text }, opts);
    },
});
export { mgr as wcgManager };

// Upgrade to the big dictionary in the background (cached after the first download); the built-in list works meanwhile.
loadBigWords().then(list => { if (list) mgr.setWords(list); });

export async function run(ctx) {
    const { sock, msg, chatJid, senderJid, lower, text } = ctx;
    if (!chatJid.endsWith('@g.us')) return CONTINUE;
    const cmd = lower.split(' ')[0];
    const isCmd = cmd === '.wcg';
    // A plain word is only ours if a game is waiting on exactly this sender — normal chatter costs nothing.
    if (!isCmd && !mgr.isTurn(chatJid, senderJid)) return CONTINUE;
    if (!isPoolOn(chatJid, 'normal')) return CONTINUE;

    global.__wcgSock = sock;
    if (isCmd) {
        await mgr.command(chatJid, senderJid, lower.split(' ').slice(1), msg);
        return;
    }
    return (await mgr.answer(chatJid, senderJid, text, msg)) ? undefined : CONTINUE;
}
