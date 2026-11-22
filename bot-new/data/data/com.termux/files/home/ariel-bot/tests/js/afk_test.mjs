// node --no-warnings --import ./tests/js/register.mjs tests/js/afk_test.mjs  — .afk / .afknote helpers + handler (fake socket / db).
import assert from 'node:assert/strict';
import { announce, agoText, afkLine, backNotice, cleanReason, MAX_REASON, GOODBYES, WELCOME_BACKS, pickFallback, parseNote, notesText } from '../../bot/lib/afk.js';

assert.equal(announce('234801@s.whatsapp.net', 'eating'), '@234801 is now afk: eating');
assert.equal(announce('234801:12@s.whatsapp.net', ''), '@234801 is now afk.');
assert.equal(cleanReason('  gone   to\n sleep '), 'gone to sleep'); assert.equal(cleanReason('x'.repeat(500)).length, MAX_REASON);
assert.equal(agoText(10_000), 'just now'); assert.equal(agoText(5 * 60_000), '5m'); assert.equal(agoText(125 * 60_000), '2h 5m'); assert.equal(agoText(26 * 3600_000), '1d 2h');
assert.equal(afkLine('1@s', { reason: 'food' }), '@1 is afk\nReason: food');
assert.equal(afkLine('1@s', { reason: '' }), '@1 is afk\nReason: none');
assert.ok(GOODBYES.length >= 10 && WELCOME_BACKS.length >= 10);
assert.ok(GOODBYES.includes(pickFallback(() => 0)));
assert.match(backNotice('1@s', { since: 0 }, 300_000, () => 0), /@1.*5m|5m.*@1/);
for (const w of WELCOME_BACKS) { assert.ok(w.includes('{tag}')); assert.ok(/no longer afk|back|returns|re-entered|over|whole|wanderer|cleared|Afk/i.test(w)); }
assert.equal(parseNote('.afknote @2348011 _call me_'), 'call me'); assert.equal(parseNote('.afknote @2348011   call   me '), 'call me'); assert.equal(parseNote('.afknote @2348011'), '');
assert.match(notesText('1@s', [{ from: '2@s', text: 'hi', at: 0 }], 60_000), /^📨 Messages for @1:\n• @2: hi \(1m ago\)$/);

// ── handler
globalThis.__golden = { log: [] };                 // the stub bridge records calls here
const { setPool } = await import('../../bot/groups.js');
const G = 'g@g.us', G2 = 'g2@g.us', KING = '2348011@s.whatsapp.net', BOB = '2348022@s.whatsapp.net', LID = '99887766@lid';
const sent = []; const sock = { sendMessage: async (c, m, o) => { sent.push({ ...m, _chat: c, _quoted: o?.quoted }); } };
const rows = new Map();                            // fake bot_afk table shared across "restarts"
const db = { query: async (q, p) => {
    if (/^INSERT/.test(q)) rows.set(p[0], { num: p[0], jid: p[1], reason: p[2], since: p[3], aliases: p[4], notes: p[5] });
    if (/^DELETE/.test(q)) rows.delete(p[0]);
    if (/^SELECT/.test(q)) return { rows: [...rows.values()] };
    return { rows: [] };
} };
const parts = [{ id: KING, lid: LID }, { id: BOB }];
const mk = (sender, text, message = {}, raw, chat = G) => ({ sock, db, msg: { pushName: 'x', key: { id: 'MID', participant: raw }, message }, chatJid: chat, senderJid: sender, rawJid: raw || sender, text, lower: text.toLowerCase(), groupParticipants: parts });
const boot = async () => (await import('../../bot/handler/afk.js?boot=' + Math.random()));   // fresh module state = a restart
setPool(G, 'normal', true); setPool(G2, 'normal', true);

let { run, afkMap } = await boot();
await run(mk(KING, '.afk eating'));
assert.equal(sent.length, 1, 'one message only, no second LLM line');
assert.match(sent[0].text, /^@2348011 is now afk: eating\n/); assert.deepEqual(sent[0].mentions, [KING]); assert.equal(sent[0]._chat, G);
assert.ok(GOODBYES.includes(sent[0].text.split('\n')[1]));
assert.equal(globalThis.__golden.log.length, 0, 'no Python / LLM call');
assert.equal(rows.size, 1);

// ── restart: afk is reloaded from the table
({ run, afkMap } = await boot());
const ci = (c) => ({ extendedTextMessage: { contextInfo: c } });
const cases = {
    'normal @tag':      ci({ mentionedJid: [KING] }),
    'tag via LID':      ci({ mentionedJid: [LID] }),
    'reply to him':     ci({ stanzaId: 'ABC', participant: KING }),
    'reply via LID':    ci({ stanzaId: 'ABC', participant: LID }),
    'image caption tag': { imageMessage: { contextInfo: { mentionedJid: [KING] } } },
};
for (const [name, m] of Object.entries(cases)) {
    sent.length = 0; await run(mk(BOB, 'hey', m));
    assert.equal(sent[0]?.text, '@2348011 is afk\nReason: eating', name);
}
sent.length = 0; await run(mk(BOB, 'where is @2348011 now', {}));   assert.equal(sent[0].text, '@2348011 is afk\nReason: eating');
sent.length = 0; await run(mk(BOB, 'normal chat', {}));             assert.equal(sent.length, 0);
sent.length = 0; await run(mk(BOB, 'hi', ci({ mentionedJid: [BOB] }))); assert.equal(sent.length, 0);

// .tagall / .hidetag wake every afk member (the command message itself carries no mentions)
for (const c of ['.tagall hello', '.hidetag hello']) { sent.length = 0; await run(mk(BOB, c, {})); assert.equal(sent[0]?.text, '@2348011 is afk\nReason: eating', c); }
// ...but a tagall from the afk person himself is not an afk reply
// (he is welcomed back instead, see below)

// ── .afknote: stored, confirmed, and NEVER answered with the afk notice
sent.length = 0; await run(mk(BOB, '.afknote @2348011 _call me when free_', ci({ mentionedJid: [KING] })));
assert.equal(sent.length, 1); assert.match(sent[0].text, /^📝 Noted\. @2348011 will get it/); assert.ok(!/is afk/.test(sent[0].text));
sent.length = 0; await run(mk(BOB, '.afknote reply note', ci({ stanzaId: 'Q', participant: KING })));   // reply form
assert.match(sent[0].text, /Noted/);
sent.length = 0; await run(mk(BOB, '.afknote @2348011', ci({ mentionedJid: [KING] }))); assert.match(sent[0].text, /Usage/);
sent.length = 0; await run(mk(KING, '.afknote @2348022 hi', ci({ mentionedJid: [BOB] }))); /* KING is afk: gets welcomed back first */
assert.match(sent[0].text, /2348011/); assert.match(sent[1]?.text ?? '', /📨 Messages for @2348011:\n• @2348022: call me when free[\s\S]*• @2348022: reply note/);
assert.match(sent.at(-1).text, /is not afk right now/);
assert.equal(afkMap.size, 0); assert.equal(rows.size, 0);

// ── afk again (any group), come back from another group + LID identity, notes survive a restart
sent.length = 0; await run(mk(KING, '.afk nap', {}, undefined, G));
sent.length = 0; await run(mk(BOB, '.afknote @2348011 one note', ci({ mentionedJid: [KING] })));
({ run, afkMap } = await boot());
sent.length = 0; await run(mk(KING, 'im back', {}, LID, G2));
assert.equal(sent[0]._chat, G2); assert.ok(WELCOME_BACKS.some(w => sent[0].text === w.replaceAll('{tag}', '@2348011').replace('{time}', 'just now')), sent[0].text);
assert.deepEqual(sent[0].mentions, [KING]);
assert.match(sent[1].text, /one note/);
assert.equal(afkMap.size, 0); assert.equal(rows.size, 0);
({ run, afkMap } = await boot()); sent.length = 0; await run(mk(KING, 'more talk', {})); assert.equal(sent.length, 0);
console.log('ALL AFK TESTS PASSED');
