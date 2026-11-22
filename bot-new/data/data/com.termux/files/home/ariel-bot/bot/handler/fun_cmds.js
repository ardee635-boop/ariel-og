// bot/handler/fun_cmds.js - Local image commands, memes, neko actions, joke/truth/dare/wyr.
// Moved verbatim out of handleMessage (handler.js, original lines 1658-1878).
// run(ctx) returns CONTINUE to fall through to the next step, or ends handling of the message (return / return value).
import { sendReaction } from '../reactions.js';
import { sendImage, sendText } from '../lib/send.js';
import { CONTINUE } from './_common.js';

export async function run(ctx) {
    let { sock, msg, chatJid, senderJid, mentionedJid, lower } = ctx;

    const LOCAL_IMAGES = {
    '.kidnap': [
    'https://i.ibb.co/TBgmGmvF/Kidnap-2.gif'
],

'.hug': [
    'https://i.ibb.co/HLXHFvWy/Hug-9.gif',
    'https://i.ibb.co/RTWCgc4S/Hug-7.gif',
    'https://i.ibb.co/R4Pc8tfG/Hug-5.gif',
    'https://i.ibb.co/99R2m7GD/Hug-4.gif',
    'https://i.ibb.co/pjmTdgTZ/Hug-2.gif',
    'https://i.ibb.co/2YH82tBt/Hug-3.gif'
],

'.run': [
    'https://i.ibb.co/5gRNqkDr/Run-4.gif',
    'https://i.ibb.co/rPf2B7K/Run-3.gif',
    'https://i.ibb.co/LzKW5JGG/Run-1.gif',
    'https://i.ibb.co/k2Fz2k47/run-2.gif'
],

'.dance': [
    'https://i.ibb.co/Z6s9Nc6v/Dance-6.gif',
    'https://i.ibb.co/MyvN8d8p/Dance-4.gif',
    'https://i.ibb.co/7xqj8CWP/Dance-5.gif',
    'https://i.ibb.co/j9Jg58bk/Dance-3.gif',
    'https://i.ibb.co/5XHKQxYX/Dance-2.gif'
],

'.stare': [
    'https://i.ibb.co/N6P5df5K/Stare-6.gif',
    'https://i.ibb.co/zWR54Th6/Stare-3.gif',
    'https://i.ibb.co/N6dBMPpT/Stare-5.gif',
    'https://i.ibb.co/wFygc2yf/Stare-4.gif',
    'https://i.ibb.co/8LtcdHXf/Stare-2.gif',
    'https://i.ibb.co/whWBRsfq/Stare-1.gif'
],

'.pout': [
    'https://i.ibb.co/7xFKHk08/Pout-1.gif'
],

'.laugh': [
    'https://i.ibb.co/Hpk2dRZF/Laugh-3.gif',
    'https://i.ibb.co/xqD2gpSs/Laugh-2.gif',
    'https://i.ibb.co/8Dyz2szy/Laugh-1.gif'
],

'.cry': [
    'https://i.ibb.co/V0kS8Vjg/Cry-9.gif',
    'https://i.ibb.co/Vcj1cQs6/Cry-8.gif',
    'https://i.ibb.co/21TGc9z6/Cry-7.gif',
    'https://i.ibb.co/TBbHjCV4/Cry-6.gif',
    'https://i.ibb.co/kCk7TLV/Cry-4.gif',
    'https://i.ibb.co/TBjd64Xm/Cry-3.gif',
    'https://i.ibb.co/0yM2WWhp/Cry-2.gif',
    'https://i.ibb.co/dsfqVvXz/Cry-1.gif'
],

'.punch': [
    'https://i.ibb.co/jNdGQb7/Punch-5.gif',
    'https://i.ibb.co/zW7SBmWN/Punch-4.gif',
    'https://i.ibb.co/JjkXc5GK/Punch-3.gif',
    'https://i.ibb.co/ymWRnYqm/Punch-2.gif',
    'https://i.ibb.co/ks5fxC18/Punch-1.gif'
],

'.smile': [
    'https://i.ibb.co/rfvcz3x3/Smile-3.gif',
    'https://i.ibb.co/ZRjkmZc1/Smile-2.gif'
],

'.blush': [
    'https://i.ibb.co/k66XhTKy/Blush-2.gif',
    'https://i.ibb.co/Mx1bj185/Blush-1.gif'
],

'.roar': [
    'https://i.ibb.co/99yK96C7/Roar-1.gif'
],

'.slap': [
    'https://i.ibb.co/Z6RgDtCb/Slap-1.gif'
],

'.sleep': [
    'https://i.ibb.co/gb6tjM1V/Sleep-1.gif'
],

'.kiss': [
    'https://i.ibb.co/LX8QHjZS/Kiss-1.gif'
],

'.pat': [
    'https://i.ibb.co/YF4C35PJ/Pat-4.gif',
    'https://i.ibb.co/N2HCPXhp/Pat-3.gif',
    'https://i.ibb.co/cXMxBHMS/Pat-2.gif',
    'https://i.ibb.co/fVfKZky4/Pat-1.gif'
]
};

    const localCmd = lower.split(' ')[0];
    if (LOCAL_IMAGES[localCmd]) {
        const pool      = LOCAL_IMAGES[localCmd];
        const imgUrl    = pool[Math.floor(Math.random() * pool.length)];
        const action    = localCmd.slice(1);
        const senderNum = senderJid.split('@')[0];
        const targetNum = mentionedJid ? mentionedJid.split('@')[0] : null;
        const targetTag = targetNum ? `@${targetNum}` : '';
        const mentions  = [senderJid];
        if (mentionedJid) mentions.push(mentionedJid);
        const caption = `@${senderNum} *${action}s* ${targetTag}`.trim();
        await sendReaction(sock, chatJid, imgUrl, caption, mentions, msg);
        return;
    }

    // ── Fun / reaction commands via nekos.best ────────────────
    const NEKO_ACTIONS = {
        '.lick':'nom','.punch':'punch','.bonk':'bonk','.tickle':'tickle','.shrug':'shrug',
        '.shoot':'shoot','.spin':'spin','.think':'think','.clap':'clap',
    };

    if (['.meme','.shootmeme','.sadmeme','.coolmeme'].includes(lower)) {
        const subMap = {
            '.meme':'memes','.shootmeme':'dankmemes','.sadmeme':'me_irl','.coolmeme':'wholesomememes',
        };
        const sub = subMap[lower] || 'memes';
        try {
            const res  = await fetch(`https://meme-api.com/gimme/${sub}`);
            const data = await res.json();
            if (data?.url) {
                await sendImage(sock, chatJid, data.url, `😂 *${data.title}*\nr/${data.subreddit}`, msg);
            } else {
                await sendText(sock, chatJid, '_Could not fetch a meme._', msg);
            }
        } catch(e) {
            await sendText(sock, chatJid, '_Meme service unavailable._', msg);
        }
        return;
    }

    if (lower === '.triggered') {
        const senderNum = senderJid.split('@')[0];
        try {
            const res  = await fetch(`https://some-random-api.com/canvas/triggered?avatar=https://i.pravatar.cc/150?u=${senderNum}`);
            const buf  = Buffer.from(await res.arrayBuffer());
            await sock.sendMessage(chatJid, { image: buf, caption: '😡 *TRIGGERED*' }, { quoted: msg });
        } catch(e) {
            await sendText(sock, chatJid, '😡 *TRIGGERED*', msg);
        }
        return;
    }

    const nekoCmd = lower.split(' ')[0];
    if (NEKO_ACTIONS[nekoCmd]) {
        const action    = NEKO_ACTIONS[nekoCmd];
        const senderNum = senderJid.split('@')[0];
        const targetNum = mentionedJid ? mentionedJid.split('@')[0] : null;
        const targetTag = targetNum ? `@${targetNum}` : 'everyone';
        const mentions  = [senderJid];
        if (mentionedJid) mentions.push(mentionedJid);
        try {
            const res  = await fetch(`https://nekos.best/api/v2/${action}`);
            const data = await res.json();
            const gif  = data?.results?.[0]?.url;
            const from = data?.results?.[0]?.anime_name || '';
            const caption = `@${senderNum} *${action}s* ${targetTag}${from ? `\n_${from}_` : ''}`;
            if (gif) {
                await sendReaction(sock, chatJid, gif, caption, mentions, msg);
            } else {
                await sendText(sock, chatJid, caption, msg);
            }
        } catch(e) {
            await sendText(sock, chatJid, `_Ariel couldn't fetch that right now._`, msg);
        }
        return;
    }

    if (lower === '.joke') {
        try {
            const res  = await fetch('https://official-joke-api.appspot.com/random_joke');
            const data = await res.json();
            await sendText(sock, chatJid, `😄 *${data.setup}*\n\n${data.punchline}`, msg);
        } catch(e) {
            await sendText(sock, chatJid, '_Could not fetch a joke right now._', msg);
        }
        return;
    }

    if (lower === '.truth') {
        try {
            const res  = await fetch('https://api.truthordarebot.xyz/v1/truth');
            const data = await res.json();
            await sendText(sock, chatJid, `🤔 *Truth:*\n${data.question}`, msg);
        } catch(e) {
            await sendText(sock, chatJid, '_Could not fetch a truth right now._', msg);
        }
        return;
    }

    if (lower === '.dare') {
        try {
            const res  = await fetch('https://api.truthordarebot.xyz/v1/dare');
            const data = await res.json();
            await sendText(sock, chatJid, `😈 *Dare:*\n${data.question}`, msg);
        } catch(e) {
            await sendText(sock, chatJid, '_Could not fetch a dare right now._', msg);
        }
        return;
    }

    if (lower === '.wyr') {
        try {
            const res  = await fetch('https://api.truthordarebot.xyz/v1/wyr');
            const data = await res.json();
            await sendText(sock, chatJid, `🤷 *Would You Rather...*\n${data.question}`, msg);
        } catch(e) {
            await sendText(sock, chatJid, '_Could not fetch a WYR right now._', msg);
        }
        return;
    }
    return CONTINUE;
}
