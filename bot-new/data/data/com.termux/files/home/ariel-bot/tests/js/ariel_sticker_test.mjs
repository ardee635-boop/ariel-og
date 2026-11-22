// Stickers (20% of short replies become a sticker, 10% get one added) and typing time (10 characters ~ 1 second).
// Run:  node --test tests/js/ariel_sticker_test.mjs      (no database, no network)
import test from 'node:test';
import assert from 'node:assert/strict';
import { createConversation } from '../../bot/ariel/conversation.js';
import { createSender } from '../../bot/ariel/send.js';
import { createStickerPicker } from '../../bot/ariel/stickers.js';
import { withDefaults } from '../../bot/ariel/config.js';

// rolls: first = quote roll (0.99 = no quote), second = sticker roll
async function run({ roll, reply = 'ACTION: reply\nsure', pickTag = 'smug', noStickers = false }) {
    const t = Date.parse('2026-11-01T10:00:00Z');
    const rows = []; const events = [];
    const store = { recentMessages: async () => rows, chatSettings: async () => ({}), latestSummaries: async () => [], getArielState: async () => ({}) };
    const send = {
        say: async (a) => { events.push(['text', a.bubbles.join(' ')]); return a.bubbles.length; },
        react: async () => true,
        sticker: async (a) => { events.push(['sticker', a.tag, a.afterText ? 'after' : 'instead']); return true; },
    };
    const stickers = noStickers ? null : { pick: async () => pickTag };
    const ai = { chat: async () => ({ text: reply }) };
    const batcher = { touch: (k, w, c, fn) => setImmediate(fn), has: () => false, cancel() {} };
    const q = [0.99, roll];
    const conv = createConversation({ store, ai, core: { core: ['x'], aliases: ['ariel'] }, send, stickers, batcher, now: () => t, log: () => {}, rand: () => (q.length ? q.shift() : 0.99) });
    rows.push({ id: 1, wa_message_id: 'W1', person_id: 1, name: 'P1', body: 'hey ariel', meta: {}, created_at: new Date(t) });
    conv.onStored({ ev: { chat: { kind: 'dm', jid: 'x@s.whatsapp.net' }, op: { ts: new Date(t), waId: 'W1', body: 'hey ariel', meta: {}, replyTo: null, mentionJids: [] } }, out: { chatId: 1, personId: 1 } });
    for (let i = 0; i < 30 && !events.length; i++) await new Promise((r) => setTimeout(r, 5));
    await new Promise((r) => setTimeout(r, 10));
    return events;
}

test('roll under 0.20 on a short reply: sticker instead of text', async () => {
    assert.deepEqual(await run({ roll: 0.1 }), [['sticker', 'smug', 'instead']]);
});
test('roll 0.20-0.30: text, then a sticker after it', async () => {
    assert.deepEqual(await run({ roll: 0.25 }), [['text', 'sure'], ['sticker', 'smug', 'after']]);
});
test('roll over 0.30: plain text', async () => {
    assert.deepEqual(await run({ roll: 0.5 }), [['text', 'sure']]);
});
test('a long reply is never swapped for a sticker', async () => {
    const long = 'ACTION: reply\n' + 'word '.repeat(30);
    const ev = await run({ roll: 0.1, reply: long });
    assert.equal(ev.length, 1); assert.equal(ev[0][0], 'text');
});
test('picker finds nothing -> plain text; stickers off -> plain text', async () => {
    assert.deepEqual(await run({ roll: 0.1, pickTag: null }), [['text', 'sure']]);
    assert.deepEqual(await run({ roll: 0.1, noStickers: true }), [['text', 'sure']]);
});

test('picker returns only a tag that exists', async () => {
    const mk = (text) => createStickerPicker({ ai: { chat: async () => ({ text }) }, listTags: async () => ({ smug: 'smirk', blush: 'shy' }) });
    assert.equal(await mk('Smug').pick({ text: 'hi', mode: 'only' }), 'smug');
    assert.equal(await mk('NONE').pick({ text: 'hi', mode: 'only' }), null);
    assert.equal(await mk('angry').pick({ text: 'hi', mode: 'only' }), null);
    assert.equal(await createStickerPicker({ ai: { chat: async () => ({ text: 'smug' }) }, listTags: async () => ({}) }).pick({ text: 'hi', mode: 'only' }), null);
});

test('typing time: 10 characters is about 1 second, instant for tiny, capped at 5 s', async () => {
    const waits = [];
    const sock = { sendPresenceUpdate: async () => {}, sendMessage: async () => ({ key: { id: 'X' } }) };
    const s = createSender({ getSock: () => sock, getRaw: () => null, store: { recordOwn: async () => {} }, cfg: withDefaults(), sleep: async (ms) => { waits.push(ms); }, rand: () => 0.5 });
    const typing = async (len) => { waits.length = 0; await s.say({ chatId: 1, jid: 'j', bubbles: ['a'.repeat(len)] }); return waits[1]; };   // waits[0] = reading pause
    assert.equal(await typing(10), 1000);
    assert.equal(await typing(40), 4000);
    assert.equal(await typing(1), 100);
    assert.equal(await typing(400), 5000);
});
