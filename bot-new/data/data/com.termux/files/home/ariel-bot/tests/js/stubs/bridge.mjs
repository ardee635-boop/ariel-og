// Stand-in for bot/bridge.js. Records every call (including the pool flags the real one would send to Python)
// and answers deterministically from the message text, so each reply-handling branch of handleMessage can be hit.
import { isPoolOn } from '../../../bot/groups.js';
export const pendingCallbacks = {};
export function startPython() {}
const G = () => globalThis.__golden;
export async function callPython(sender, text, mentionedJid = null, groupJid = null, quotedText = null, pushName = null) {
    const pools = groupJid ? ['pokemon', 'amongus', 'normal', 'rpg', 'chat'].map(p => isPoolOn(groupJid, p) ? 1 : 0).join('') : '-----';
    G().log.push(['py', sender, text, mentionedJid, groupJid, quotedText, pushName, pools]);
    if (G().fault === 'python') throw new Error('bridge crashed');
    const t = (text || '').toLowerCase();
    if (t.includes('pytimeout')) return { response: null, outbox: [], error: 'Game engine timed out.' };
    if (t.includes('pynull')) return { response: null, outbox: [] };
    if (t.includes('pyoutbox')) return { response: 'PY(outbox)', outbox: [
        { message: 'OUT1', group_jid: groupJid }, { message: 'OUT1' }, { message: 'OUT2 all', tag_all: true }, { message: 'OUT3 hidden', tag_all: true, hide_tags: true }] };
    if (t.includes('pysticker')) return { response: 'PY(sticker)', outbox: [], sticker: 'happy' };
    if (t.includes('pyimg')) return { response: '__IMG__|assets/none.png|caption here', outbox: [] };
    if (t.includes('pyhud')) return { response: '__HUD__|HUD TEXT|extra', outbox: [] };
    if (t.includes('pylist')) return { response: '__LIST__|Pick one|Title|a:A,b:B', outbox: [] };
    return { response: `PY[${text}]`, outbox: [] };
}
export async function callPythonAction(sender, type, payload) {
    G().log.push(['pyaction', sender, type, payload]);
    return { ok: true };
}
