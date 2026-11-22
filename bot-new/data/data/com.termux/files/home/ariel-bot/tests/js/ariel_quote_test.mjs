// Quoting: every reply quotes the message it answers (config.quoteChance, default 1).
// Run:  node --test tests/js/ariel_quote_test.mjs      (no database, no network)
import test from 'node:test';
import assert from 'node:assert/strict';
import { createConversation } from '../../bot/ariel/conversation.js';

function rig({ kind, roll, config = {} }) {
    const t = Date.parse('2026-11-01T10:00:00Z');
    const rows = []; const sent = [];
    const store = { recentMessages: async () => rows, chatSettings: async () => ({}), latestSummaries: async () => [], getArielState: async () => ({}) };
    const send = { say: async (a) => { sent.push(a); return a.bubbles.length; }, react: async () => true };
    const ai = { chat: async () => ({ text: 'ACTION: reply\nsure' }) };
    const batcher = { touch: (k, w, c, fn) => setImmediate(fn), has: () => false, cancel() {} };
    const conv = createConversation({ store, ai, core: { core: ['You are Ariel.'], aliases: ['ariel'] }, send, batcher, now: () => t, log: () => {}, rand: () => roll, config });
    const jid = kind === 'group' ? 'g@g.us' : 'x@s.whatsapp.net';
    return async function say(body) {
        const waId = `W${rows.length + 1}`;
        rows.push({ id: rows.length + 1, wa_message_id: waId, person_id: 1, name: 'P1', body, meta: {}, created_at: new Date(t) });
        conv.onStored({ ev: { chat: { kind, jid }, op: { ts: new Date(t), waId, body, meta: {}, replyTo: null, mentionJids: [] } }, out: { chatId: 1, personId: 1 } });
        for (let i = 0; i < 30 && !sent.length; i++) await new Promise((r) => setTimeout(r, 5));
        return { sent, waId };
    };
}

test('default: every reply quotes the message it answers, in groups and DMs', async () => {
    for (const kind of ['group', 'dm']) {
        const { sent, waId } = await rig({ kind, roll: 0.99 })(kind === 'group' ? 'hey ariel' : 'hey');
        assert.equal(sent[0].quoteWaId, waId, kind);
    }
});
test('quoteChance can be lowered or set to 0', async () => {
    const { sent } = await rig({ kind: 'group', roll: 0.5, config: { quoteChance: { group: 0.3 } } })('hey ariel');
    assert.equal(sent[0].quoteWaId, null);
    const z = await rig({ kind: 'group', roll: 0, config: { quoteChance: { group: 0 } } })('hey ariel');
    assert.equal(z.sent[0].quoteWaId, null);
});
