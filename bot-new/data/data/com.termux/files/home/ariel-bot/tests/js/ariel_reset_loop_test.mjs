// `.ariel reset` (context_from) and the loop breaker.
// Run:  node --test tests/js/ariel_reset_loop_test.mjs      (no database, no network)
import test from 'node:test';
import assert from 'node:assert/strict';
import { createConversation } from '../../bot/ariel/conversation.js';

function rig({ settings = {}, replies }) {
    const t0 = Date.parse('2026-11-01T10:00:00Z');
    let n = 0; const sent = []; const prompts = [];
    const mk = (personId, body, mins) => ({ id: ++n, wa_message_id: `W${n}`, person_id: personId, name: personId ? 'Korii' : null, body, meta: {}, created_at: new Date(t0 + mins * 60_000) });
    const rows = [
        mk(1, 'Yo', 0), mk(null, 'Yo Korii, move?', 1), mk(1, 'Move?', 2), mk(null, 'Yo Korii, tag turn.', 3), mk(1, 'No', 4),
    ];
    const store = { recentMessages: async () => rows, chatSettings: async () => settings, latestSummaries: async () => [], getArielState: async () => ({}) };
    const send = { say: async (a) => { sent.push(a); return a.bubbles.length; }, react: async () => true };
    const ai = { chat: async ({ messages }) => { const u = messages[1].content; prompts.push(u); return { text: replies(u) }; } };
    const batcher = { touch: (k, w, c, fn) => setImmediate(fn), has: () => false, cancel() {} };
    const conv = createConversation({ store, ai, core: { core: ['You are Ariel.'], aliases: ['ariel'] }, send, batcher, now: () => t0 + 10 * 60_000, log: () => {} });
    async function say(body) {
        const row = mk(1, body, 9); rows.push(row);
        conv.onStored({ ev: { chat: { kind: 'group', jid: 'g@g.us' }, op: { ts: row.created_at, waId: row.wa_message_id, body, meta: {}, replyTo: null, mentionJids: [] } }, out: { chatId: 1, personId: 1 } });
        for (let i = 0; i < 40 && !sent.length; i++) await new Promise((r) => setTimeout(r, 5));
        await new Promise((r) => setTimeout(r, 15));
    }
    return { say, sent, prompts, conv };
}

test('loop breaker: a third copy of the same move is redrafted without her own recent lines', async () => {
    const r = rig({ replies: (u) => (u.includes('tag turn') ? 'ACTION: reply\nYo Korii, tag move.' : 'ACTION: reply\nwhat') });
    await r.say('ariel');
    assert.equal(r.sent.length, 1);
    assert.equal(r.sent[0].bubbles[0], 'what');
    assert.equal(r.conv.counters.loopBroken, 1);
    assert.ok(!r.prompts[r.prompts.length - 1].includes('tag turn'), 'her own old lines are gone from the last prompt');
});

test('reset: nothing before context_from reaches the prompt', async () => {
    const r = rig({ settings: { context_from: '2026-11-01T10:06:00Z' }, replies: () => 'ACTION: reply\nhm' });
    await r.say('ariel');
    assert.equal(r.prompts.length, 1);
    assert.ok(!r.prompts[0].includes('tag turn') && !r.prompts[0].includes('Move?'), 'old messages are ignored');
    assert.ok(r.prompts[0].includes('ariel'), 'new messages still count');
});

test('no reset set: old messages are still read', async () => {
    const r = rig({ replies: () => 'ACTION: reply\nhm' });
    await r.say('ariel');
    assert.ok(r.prompts[0].includes('tag turn'));
});
