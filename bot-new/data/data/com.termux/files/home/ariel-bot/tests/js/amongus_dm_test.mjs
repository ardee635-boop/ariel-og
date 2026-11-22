// node --no-warnings --import ./tests/js/register.mjs tests/js/amongus_dm_test.mjs
// Among Us DMs must reach Python under the PLAYER'S PHONE JID (that is how the game
// registered them in the group). A DM that arrives as an @lid chat has to be mapped
// back to the phone JID, otherwise every command reply is silently dropped while
// pushed notices (sent to the phone JID) still arrive.
import assert from 'node:assert/strict';
import { J, golden } from './harness.mjs';
const { run } = await import('../../bot/handler/entry.js');
const { lidMap } = await import('../../bot/lib/cache.js');

const mkSock = () => { const sent = []; return { sent, user: { id: '1:1@s.whatsapp.net' }, sendMessage: async (c, m) => { sent.push([c, m]); } }; };
const dm = (remoteJid, text, extra = {}) => ({ key: { remoteJid, fromMe: false, id: 'X' + Math.random(), ...extra }, message: { conversation: text }, messageTimestamp: Math.floor(Date.now() / 1000) });
const pyCalls = () => golden.log.filter((e) => e[0] === 'py');

const PHONE = J.U1, LID = '99900000077@lid';

// 1. normal phone-JID DM: unchanged
{ golden.log.length = 0; const s = mkSock(); await run({ sock: s, msg: dm(PHONE, '.status') });
  const c = pyCalls(); assert.equal(c.length, 1); assert.equal(c[0][1], PHONE); assert.equal(s.sent[0][0], PHONE); }

// 2. @lid DM with the phone JID supplied by WhatsApp (remoteJidAlt): Python gets the phone JID, the reply still goes to the chat it came from
{ golden.log.length = 0; const s = mkSock(); await run({ sock: s, msg: dm(LID, '.where', { remoteJidAlt: PHONE }) });
  const c = pyCalls(); assert.equal(c.length, 1); assert.equal(c[0][1], PHONE, 'Python must see the phone JID'); assert.equal(s.sent[0][0], LID, 'reply goes back to the lid chat'); assert.equal(lidMap[LID], PHONE, 'mapping is remembered'); }

// 3. @lid DM, no alt, but the lid is already known from a group message
{ golden.log.length = 0; lidMap[LID] = PHONE; const s = mkSock(); await run({ sock: s, msg: dm(LID, '.tasks') });
  assert.equal(pyCalls()[0][1], PHONE); }

// 4. @lid with no mapping anywhere: falls back to the lid (cannot do better), still replies
{ golden.log.length = 0; delete lidMap[LID]; const s = mkSock(); await run({ sock: s, msg: dm(LID, '.status') });
  assert.equal(pyCalls()[0][1], LID); assert.equal(s.sent.length, 1); }

// 5. a non-Among-Us DM is left exactly as before (no remapping, no Python call when chat DM is off)
{ golden.log.length = 0; const s = mkSock(); await run({ sock: s, msg: dm(LID, 'hello there', { remoteJidAlt: PHONE }) });
  assert.equal(pyCalls().length, 0); }
process.stdout.write('AMONG US DM TESTS PASSED\n');
