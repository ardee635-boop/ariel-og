// bot/handler/games.js - `.spinbottle`, `.kidnap`, `.ttt`, `.copilot`, `.alpha`. (`.note` moved to handler/notes.js.)
// Moved verbatim out of handleMessage (handler.js, original lines 2375-2505).
// run(ctx) returns CONTINUE to fall through to the next step, or ends handling of the message (return / return value).
import { PHONE_NUMBER } from '../lib/env.js';
import { callPython } from '../bridge.js';
import { sendAny, sendText } from '../lib/send.js';
import { CONTINUE } from './_common.js';
import { alphaCommand, alphaPick, isAlphaMenu } from '../lib/alpha.js';
import { isPoolOn } from '../groups.js';

export async function run(ctx) {
    let { sock, msg, chatJid, text, senderJid, mentionedJid, lower } = ctx;

    // .alpha <language> — alphabet(s) of a language. A language with several alphabets sends a numbered menu;
    // the person replies to that menu with the number ("2", ".2", "2." all count).
    if (lower === '.alpha' || lower.startsWith('.alpha ')) {
        await sendText(sock, chatJid, alphaCommand(text.slice(6)), msg);
        return;
    }
    if (ctx.isBotQuote && isAlphaMenu(ctx.quotedText) && (!chatJid.endsWith('@g.us') || isPoolOn(chatJid, 'normal'))) {
        const picked = alphaPick(ctx.quotedText, text);
        if (picked) { await sendText(sock, chatJid, picked, msg); return; }
        if (picked === '') { await sendText(sock, chatJid, '_Reply with one of the numbers in the list._', msg); return; }
    }

    if (lower === '.spinbottle') {
        try {
            const meta    = await sock.groupMetadata(chatJid);
            const members = meta.participants.filter(p => !p.id.includes(PHONE_NUMBER));
            if (members.length < 2) { await sendText(sock, chatJid, '_Not enough members to spin._', msg); return; }
            const picked = members[Math.floor(Math.random() * members.length)];
            const num    = picked.id.split('@')[0];
            await sock.sendMessage(chatJid, {
                text: `🍾 *Spin the Bottle!*\n\nThe bottle spins...\n\nIt lands on → @${num}! 🎯`,
                mentions: [picked.id],
            }, { quoted: msg });
        } catch(e) {
            await sendText(sock, chatJid, '_Could not spin the bottle right now._', msg);
        }
        return;
    }

    if (lower.startsWith('.kidnap')) {
        const senderNum = senderJid.split('@')[0];
        const targetNum = mentionedJid ? mentionedJid.split('@')[0] : null;
        const targetTag = targetNum ? `@${targetNum}` : 'someone';
        const mentions  = [senderJid];
        if (mentionedJid) mentions.push(mentionedJid);
        const scenarios = [
            `🚨 *KIDNAP ALERT!*\n@${senderNum} has thrown ${targetTag} into a black van! 🚐💨`,
            `😱 *MISSING PERSON ALERT!*\n${targetTag} was last seen being dragged away by @${senderNum}!`,
            `🎭 @${senderNum} crept up behind ${targetTag} and... they're gone. Just gone.`,
        ];
        await sock.sendMessage(chatJid, {
            text: scenarios[Math.floor(Math.random() * scenarios.length)],
            mentions,
        }, { quoted: msg });
        return;
    }

    if (lower === '.ttt' || lower.startsWith('.ttt ')) {
        if (!global._tttGames) global._tttGames = {};
        const args = lower.split(' ').slice(1);
        const senderNum = senderJid.split('@')[0];
        if (args[0] === 'reset') {
            delete global._tttGames[chatJid];
            await sendText(sock, chatJid, '🔄 _Tic Tac Toe reset._', msg);
            return;
        }
        if (!global._tttGames[chatJid]) {
            global._tttGames[chatJid] = { board: Array(9).fill(' '), turn: 'X', players: {}, started: false };
        }
        const game = global._tttGames[chatJid];
        if (!game.players['X']) {
            game.players['X'] = senderNum;
            await sendText(sock, chatJid, `❎ *@${senderNum}* joined as *X*!\n_Waiting for O player… type *.ttt* to join._`, msg);
            return;
        }
        if (!game.players['O'] && senderNum !== game.players['X']) {
            game.players['O'] = senderNum;
            game.started = true;
        }
        if (!game.started) { await sendText(sock, chatJid, '_Waiting for a second player._', msg); return; }
        const myMark = game.players['X'] === senderNum ? 'X' : game.players['O'] === senderNum ? 'O' : null;
        if (!myMark) { await sendText(sock, chatJid, '_This game is full._', msg); return; }
        if (myMark !== game.turn) { await sendText(sock, chatJid, `_It's *${game.turn}*'s turn._`, msg); return; }
        const pos = parseInt(args[0]);
        if (isNaN(pos) || pos < 1 || pos > 9) {
            const b = game.board;
            const grid = `\`\`\`\n ${b[0]}|${b[1]}|${b[2]}\n-+-+-\n ${b[3]}|${b[4]}|${b[5]}\n-+-+-\n ${b[6]}|${b[7]}|${b[8]}\n\`\`\``;
            await sendText(sock, chatJid, `${grid}\n_Type *.ttt [1-9]* to place._`, msg);
            return;
        }
        if (game.board[pos - 1] !== ' ') { await sendText(sock, chatJid, '_That spot is taken._', msg); return; }
        game.board[pos - 1] = myMark;
        const wins = [[0,1,2],[3,4,5],[6,7,8],[0,3,6],[1,4,7],[2,5,8],[0,4,8],[2,4,6]];
        const b = game.board;
        const grid = `\`\`\`\n ${b[0]}|${b[1]}|${b[2]}\n-+-+-\n ${b[3]}|${b[4]}|${b[5]}\n-+-+-\n ${b[6]}|${b[7]}|${b[8]}\n\`\`\``;
        const won  = wins.some(([a,c,d]) => b[a] !== ' ' && b[a] === b[c] && b[c] === b[d]);
        const draw = b.every(c => c !== ' ');
        if (won) {
            await sendText(sock, chatJid, `${grid}\n\n🏆 *@${senderNum} wins!*\n_Type *.ttt reset* to play again._`, msg);
            delete global._tttGames[chatJid]; return;
        }
        if (draw) {
            await sendText(sock, chatJid, `${grid}\n\n🤝 *Draw!*\n_Type *.ttt reset* to play again._`, msg);
            delete global._tttGames[chatJid]; return;
        }
        game.turn = myMark === 'X' ? 'O' : 'X';
        await sendText(sock, chatJid, `${grid}\n_@${game.players[game.turn]}'s turn (${game.turn})._`, msg);
        return;
    }

    if (lower.startsWith('.copilot ')) {
        const question = text.slice(9).trim();
        if (!question) { await sendText(sock, chatJid, '_Usage: .copilot [question]_', msg); return; }
        const result = await callPython(senderJid, `.gpt ${question}`, mentionedJid, chatJid);
        if (result?.response) await sendAny(sock, chatJid, result.response, msg);
        return;
    }
    return CONTINUE;
}
