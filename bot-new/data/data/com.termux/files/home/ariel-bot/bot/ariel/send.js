// Sends bubbles the way a person types: a short "reading" pause, "typing…" for a time that
// follows the length, small gaps between bubbles, and a quote only when asked to.
import { clean } from './extract.js';

const sleepReal = (ms) => new Promise((r) => setTimeout(r, ms));

export function createSender({ getSock, getRaw, store, cfg, sendSticker = null, sleep = sleepReal, rand = Math.random, log = () => {} }) {
    const between = (a, b) => a + rand() * (b - a);
    const T = cfg.typing;

    async function say({ chatId, jid, bubbles, quoteWaId = null }) {
        const sock = getSock();
        if (!sock) throw new Error('no socket');
        let sent = 0;
        await sleep(between(T.readMinMs, T.readMaxMs));
        try {
            for (let i = 0; i < bubbles.length; i++) {
                const text = bubbles[i];
                await sock.sendPresenceUpdate('composing', jid).catch(() => {});
                const ms = Math.min(T.maxMs, Math.max(T.minMs, text.length * T.msPerChar * between(0.75, 1.25)));
                await sleep(ms);
                const quoted = i === 0 && quoteWaId ? getRaw(quoteWaId) : null;
                const res = await sock.sendMessage(jid, { text }, quoted ? { quoted } : undefined);
                sent++;
                try {
                    await store.recordOwn({ chatId, waId: res?.key?.id || null, replyTo: quoted ? quoteWaId : null, body: clean(text), ts: new Date() });
                } catch (e) { log(`[ARIEL] could not store her own message: ${e.message}`); }
                if (i < bubbles.length - 1) {
                    await sock.sendPresenceUpdate('paused', jid).catch(() => {});
                    await sleep(between(T.gapMinMs, T.gapMaxMs));
                }
            }
        } finally {
            await sock.sendPresenceUpdate('paused', jid).catch(() => {});
        }
        return sent;
    }

    // A sticker from her library. `sendSticker(jid, tag, quotedRaw)` is injected (it fetches and sends the .webp).
    async function sticker({ chatId, jid, tag, quoteWaId = null, afterText = false }) {
        if (!sendSticker || !tag) return false;
        await sleep(afterText ? between(T.gapMinMs, T.gapMaxMs) : between(T.readMinMs, T.readMaxMs));
        const quoted = quoteWaId ? getRaw(quoteWaId) : null;
        const res = await sendSticker(jid, tag, quoted);
        if (!res) return false;
        try {
            await store.recordOwn({ chatId, waId: res?.key?.id || null, replyTo: quoted ? quoteWaId : null, body: '[sticker]', ts: new Date() });
        } catch (e) { log(`[ARIEL] could not store her own sticker: ${e.message}`); }
        return true;
    }

    async function react({ chatId, jid, emoji, targetWaId }) {
        const sock = getSock();
        const target = targetWaId ? getRaw(targetWaId) : null;
        if (!sock || !target?.key) return false;
        await sleep(between(T.readMinMs, T.readMaxMs));
        await sock.sendMessage(jid, { react: { text: emoji, key: target.key } });
        return true;
    }

    return { say, react, sticker };
}
