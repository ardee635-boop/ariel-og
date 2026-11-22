// Back-and-forth in groups: after she answers someone, their next plain message counts as for her (for a short while).
// Run:  node --test tests/js/ariel_followup_test.mjs      (no database, no network)
import test from 'node:test';
import assert from 'node:assert/strict';
import { createConversation } from '../../bot/ariel/conversation.js';

function rig({ kind = 'group' } = {}) {
    let t = Date.parse('2026-11-01T10:00:00Z');
    const rows = []; const sent = []; let n = 0;
    const store = { recentMessages: async () => rows, chatSettings: async () => ({}), latestSummaries: async () => [], getArielState: async () => ({}) };
    const send = { say: async (a) => { sent.push(a); return a.bubbles.length; }, react: async () => true };
    const ai = { chat: async () => ({ text: 'ACTION: reply\nsure' }) };
    const batcher = { touch: (k, w, c, fn) => setImmediate(fn), has: () => false, cancel() {} };
    const conv = createConversation({ store, ai, core: { core: ['You are Ariel.'], aliases: ['ariel'] }, send, batcher, now: () => t, log: () => {} });
    const jid = kind === 'group' ? 'g@g.us' : 'x@s.whatsapp.net';
    async function say(personId, body, { meta = {}, replyTo = null, mentionJids = [] } = {}) {
        const waId = `W${++n}`;
        rows.push({ id: n, wa_message_id: waId, person_id: personId, name: `P${personId}`, body, meta, created_at: new Date(t) });
        const before = sent.length;
        conv.onStored({ ev: { chat: { kind, jid }, op: { ts: new Date(t), waId, body, meta, replyTo, mentionJids } }, out: { chatId: 1, personId } });
        for (let i = 0; i < 30 && sent.length === before; i++) await new Promise((r) => setTimeout(r, 5));
        await new Promise((r) => setTimeout(r, 10));
        return sent.length > before;
    }
    return { say, sent, conv, tick: (ms) => { t += ms; } };
}

test('she answers the same person\'s next plain message right after she answered them', async () => {
    const r = rig();
    assert.equal(await r.say(1, 'Hey ariel'), true);            // her name
    r.tick(20_000);
    assert.equal(await r.say(1, 'How hot is it?'), true);       // no name, but a follow-up
    assert.equal(r.conv.counters.followUps, 1);
});

test('someone else\'s plain message does not count', async () => {
    const r = rig();
    await r.say(1, 'Hey ariel');
    r.tick(5_000);
    assert.equal(await r.say(2, 'lol same'), false);
});

test('it stops when they answer another message, tag someone else, or wait too long', async () => {
    const r = rig();
    await r.say(1, 'Hey ariel');
    r.tick(5_000);
    assert.equal(await r.say(1, 'yeah you too', { replyTo: 'W-someone-else' }), false);
    assert.equal(await r.say(1, 'hey @bob look', { mentionJids: ['123@s.whatsapp.net'] }), false);
    r.tick(95_000);
    assert.equal(await r.say(1, 'anyway'), false);              // past 90 s
});

test('quoting her still works as a follow-up', async () => {
    const r = rig();
    await r.say(1, 'Hey ariel');
    r.tick(5_000);
    assert.equal(await r.say(1, 'what?', { replyTo: 'W-her', meta: { quoted_ariel: true } }), true);
});

test('at most 3 follow-ups in a row, and her name starts it again', async () => {
    const r = rig();
    await r.say(1, 'Hey ariel');
    for (let i = 0; i < 3; i++) { r.tick(5_000); assert.equal(await r.say(1, `more ${i}`), true); }
    r.tick(5_000);
    assert.equal(await r.say(1, 'and more'), false);            // 4th is too many
    assert.equal(await r.say(1, 'ariel?'), true);               // addressing her resets
    r.tick(5_000);
    assert.equal(await r.say(1, 'ok then'), true);
});

test('ARIEL_FOLLOWUP=off turns it off', async () => {
    const r = rig();
    process.env.ARIEL_FOLLOWUP = 'off';
    try {
        await r.say(1, 'Hey ariel');
        r.tick(5_000);
        assert.equal(await r.say(1, 'How hot is it?'), false);
    } finally { delete process.env.ARIEL_FOLLOWUP; }
});

test('DMs are unchanged (she always answers there)', async () => {
    const r = rig({ kind: 'dm' });
    assert.equal(await r.say(1, 'hi'), true);
    r.tick(10_000);
    assert.equal(await r.say(1, 'how are you'), true);
    assert.equal(r.conv.counters.followUps, 0);
});
