// node --no-warnings --import ./tests/js/register.mjs tests/js/notes_test.mjs  — personal + public notes (lib + handler, fake socket, in-memory SQL).
import assert from 'node:assert/strict';
import * as H from './harness.mjs';
const { makePool, J } = H;
const N = await import('../../bot/lib/notes.js');
const { run, pendingEdits } = await import('../../bot/handler/notes.js');
const { setPool } = await import('../../bot/groups.js');
const { CONTINUE } = await import('../../bot/handler/_common.js');

// ── pure helpers
assert.deepEqual(N.parseSave('.note I am Ariel\nIm king'), { scope: 'personal', body: 'I am Ariel\nIm king' });
assert.deepEqual(N.parseSave('.pnote Group announcement\nMeeting is at 5 PM'), { scope: 'public', body: 'Group announcement\nMeeting is at 5 PM' });
assert.deepEqual(N.parseSave('.note\nstarts on next line'), { scope: 'personal', body: 'starts on next line' });
assert.equal(N.parseSave('.note').body, ''); assert.equal(N.parseSave('.notes'), null); assert.equal(N.parseSave('.pnotes 1'), null); assert.equal(N.parseSave('.noted x'), null);
assert.equal(N.parseNumber('1'), 1); assert.equal(N.parseNumber('#3'), 3); assert.equal(N.parseNumber('0'), null); assert.equal(N.parseNumber('x'), null); assert.equal(N.parseNumber('-1'), null);
assert.equal(N.userKey('234801:12@s.whatsapp.net'), '234801');
assert.equal(N.preview('a\nb'), 'a …'); assert.equal(N.preview('x'.repeat(80)).length, N.PREVIEW_CHARS);

// ── handler harness
const db = makePool();
const sent = []; let mid = 0;
const sock = { sendMessage: async (c, m, o) => { const key = { id: `BOT${++mid}`, remoteJid: c, fromMe: true }; sent.push({ ...m, _chat: c, _quoted: o?.quoted, key }); return { key }; } };
const G1 = J.GROUP, G2 = J.GROUP2, ALICE = J.U1, BOB = J.U2;
setPool(G1, 'normal', true); setPool(G2, 'normal', true);
let n = 0;
const send = async (from, chat, text, quotedId = null) => {
    const message = quotedId ? { extendedTextMessage: { text, contextInfo: { stanzaId: quotedId, participant: J.BOT } } } : { conversation: text };
    const msg = { key: { id: `U${++n}`, remoteJid: chat, participant: from }, message };
    let lower = text.toLowerCase().trim().replace(/\s+/g, ' ');
    const before = sent.length;
    const r = await run({ sock, db, msg, chatJid: chat, senderJid: from, text, lower });
    return { r, out: sent.slice(before) };
};
const say = async (...a) => { const { out } = await send(...a); assert.equal(out.length, 1, `one reply for ${a[2]}`); return out[0]; };

// save: one message with a line break = one note, kept verbatim
let o = await say(ALICE, G1, '.note I am Ariel\nIm king');
assert.match(o.text, /Note #1 saved/); assert.equal(o._quoted.key.id, `U${n}`); assert.equal(o.mentions, undefined, 'never pings anyone');
o = await say(ALICE, G1, '.note second note @15551110002 not a ping');
assert.match(o.text, /Note #2 saved/);
o = await say(ALICE, G1, '.notes');
assert.equal(o.text, '📝 *Your notes* (2/50)\n\n1. I am Ariel …\n2. second note @15551110002 not a ping\n\n_.notes <number> to read one_');
o = await say(ALICE, G1, '.notes 1');
assert.equal(o.text, '📝 *Note #1*\n\nI am Ariel\nIm king');
assert.match((await say(ALICE, G1, '.notes 9')).text, /no note #9.*1 to 2/);
assert.match((await say(ALICE, G1, '.notes abc')).text, /Usage/);
assert.match((await say(ALICE, G1, '.note')).text, /Usage: \.note/);

// privacy: personal notes are the owner's only, in every group; Bob sees nothing
assert.match((await say(BOB, G1, '.notes')).text, /No notes yet/);
o = await say(ALICE, G2, '.notes 1'); assert.match(o.text, /I am Ariel\nIm king/, 'personal notes follow the user across groups');
assert.match((await say(BOB, G1, '.notes 1')).text, /no note #1/);
assert.match((await say(BOB, G1, '.delnote 1')).text, /no note #1/);
assert.equal((await N.listNotes(db, 'personal', N.userKey(ALICE))).length, 2, "Bob could not delete Alice's note");

// public notes: per group, any member
assert.match((await say(ALICE, G1, '.pnote Group announcement\nMeeting is at 5 PM')).text, /Public note #1 saved/);
assert.match((await say(BOB, G1, '.pnote bobs public')).text, /Public note #2 saved/);
o = await say(BOB, G1, '.pnotes'); assert.match(o.text, /Group notes\* \(2\/50\)\n\n1\. Group announcement …\n2\. bobs public/);
assert.equal((await say(BOB, G1, '.pnotes 1')).text, '📌 *Public note #1*\n\nGroup announcement\nMeeting is at 5 PM');
assert.match((await say(BOB, G2, '.pnotes')).text, /No public notes yet/, 'another group never sees them');
assert.match((await say(BOB, G2, '.pnotes 1')).text, /no public note #1/);
assert.match((await say(BOB, G2, '.delpnote 1')).text, /no public note #1/);
assert.equal((await N.listNotes(db, 'public', G1)).length, 2);
assert.match((await say(ALICE, G1, '.pnotes')).text, /Group notes/);
assert.equal((await N.listNotes(db, 'public', N.userKey(ALICE))).length, 0, 'personal and public are separate stores');

// delete renumbers, edits/deletes target by stable id
const idBefore = (await N.listNotes(db, 'personal', N.userKey(ALICE))).map((x) => x.id);
assert.match((await say(ALICE, G1, '.delnote 1')).text, /Note #1 deleted/);
assert.equal((await say(ALICE, G1, '.notes 1')).text, '📝 *Note #1*\n\nsecond note @15551110002 not a ping');
assert.deepEqual((await N.listNotes(db, 'personal', N.userKey(ALICE))).map((x) => x.id), [idBefore[1]]);

// ── reply-based edit (personal)
o = await say(ALICE, G1, '.editnote 1');
assert.match(o.text, /Editing note #1\*\n\nsecond note @15551110002 not a ping\n\n_Reply to this message/);
const promptId = o.key.id;
assert.equal(pendingEdits.size, 1);
let r = await send(BOB, G1, 'bob hijack', promptId);  assert.equal(r.r, CONTINUE); assert.equal(r.out.length, 0, "someone else cannot finish Alice's edit");
r = await send(ALICE, G1, 'not a reply to the prompt'); assert.equal(r.r, CONTINUE);
r = await send(ALICE, G1, 'reply to another message', 'SOMEBOT'); assert.equal(r.r, CONTINUE);
r = await send(ALICE, G2, 'reply in wrong group', promptId); assert.equal(r.r, CONTINUE);
assert.equal((await N.listNotes(db, 'personal', N.userKey(ALICE)))[0].content, 'second note @15551110002 not a ping', 'nothing changed yet');
// the note is deleted and re-added between prompt and reply: edit must still hit the right (or no) record
r = await send(ALICE, G1, 'new line one\nnew line two', promptId);
assert.match(r.out[0].text, /Note #1 updated/);
assert.equal((await say(ALICE, G1, '.notes 1')).text, '📝 *Note #1*\n\nnew line one\nnew line two');
r = await send(ALICE, G1, 'second reply', promptId); assert.equal(r.r, CONTINUE, 'a finished edit cannot be replayed');
assert.equal(pendingEdits.size, 0);

// stale edit: expires, then an unrelated later reply cannot change the note
o = await say(ALICE, G1, '.editnote 1'); const staleId = o.key.id;
const realNow = Date.now; const t0 = realNow();
H.advanceClock(N.PENDING_EDIT_MS + 1000);
r = await send(ALICE, G1, 'too late', staleId); assert.equal(r.r, CONTINUE); assert.equal(r.out.length, 0);
assert.equal((await say(ALICE, G1, '.notes 1')).text, '📝 *Note #1*\n\nnew line one\nnew line two');

// starting a second edit cancels the first; deleted note -> edit says so
o = await say(ALICE, G1, '.editnote 1'); const first = o.key.id;
o = await say(ALICE, G1, '.editnote 1'); const second = o.key.id;
r = await send(ALICE, G1, 'via first', first); assert.equal(r.r, CONTINUE);
await say(ALICE, G1, '.delnote 1');
r = await send(ALICE, G1, 'via second', second); assert.match(r.out[0].text, /no longer exists/);
assert.equal((await N.listNotes(db, 'personal', N.userKey(ALICE))).length, 0);

// empty / too long replies keep the edit alive
await say(ALICE, G1, '.note keep me');
o = await say(ALICE, G1, '.editnote 1'); const keepId = o.key.id;
r = await send(ALICE, G1, 'x'.repeat(N.MAX_NOTE_CHARS + 1), keepId); assert.match(r.out[0].text, /Too long/);
r = await send(ALICE, G1, 'short again', keepId); assert.match(r.out[0].text, /updated/);

// ── reply-based edit (public): any member, but only via the right bot message, only in that group
o = await say(ALICE, G1, '.editpnote 2'); const pId = o.key.id;
assert.match(o.text, /Editing public note #2\*\n\nbobs public/);
r = await send(BOB, G2, 'wrong group', pId); assert.equal(r.r, CONTINUE);
r = await send(J.U3, G1, 'edited by carol\nline 2', pId); assert.match(r.out[0].text, /Public note #2 updated/);
assert.equal((await say(BOB, G1, '.pnotes 2')).text, '📌 *Public note #2*\n\nedited by carol\nline 2');
assert.match((await say(J.U3, G1, '.delpnote 1')).text, /Public note #1 deleted/);
assert.equal((await say(BOB, G1, '.pnotes 1')).text, '📌 *Public note #1*\n\nedited by carol\nline 2');

// ── limits
const big = await say(ALICE, G1, '.note ' + 'y'.repeat(N.MAX_NOTE_CHARS + 1)); assert.match(big.text, /Too long/);
for (let i = 0; i < N.MAX_PERSONAL_NOTES - 1; i++) await N.addNote(db, 'personal', N.userKey(ALICE), 'n' + i, 'x');   // already holds 1
assert.match((await say(ALICE, G1, '.note one too many')).text, /maximum of 50 notes/);
assert.equal((await N.listNotes(db, 'personal', N.userKey(ALICE))).length, 50);

// ── gating
setPool(G2, 'normal', false);
r = await send(ALICE, G2, '.notes'); assert.equal(r.r, CONTINUE); assert.equal(r.out.length, 0, 'normal pool off: silent');
r = await send(ALICE, J.U1, '.notes'); assert.equal(r.r, CONTINUE, 'not a group: ignored');
r = await send(ALICE, G1, 'hello there'); assert.equal(r.r, CONTINUE); assert.equal(r.out.length, 0, 'ordinary chat untouched');
r = await send(ALICE, G1, '.hug'); assert.equal(r.r, CONTINUE);
H.realConsole.log('ALL NOTES TESTS PASSED');
