// node --no-warnings --import ./tests/js/register.mjs tests/js/invite_test.mjs — .invite must always answer, even when WhatsApp stalls.
import assert from 'node:assert/strict';
process.env.KING_NUMBER ||= '15551110003'; process.env.PHONE_NUMBER ||= '15550000000';
const { handleBotCommand } = await import('../../bot/commands.js');
const G = 'g@g.us';
const db = { query: async () => ({ rows: [] }) };
const mkSock = (o = {}) => { const sent = []; return { sent, user: { id: '1@s' }, groupMetadata: async () => ({ subject: 'Test GC', participants: [] }),
    groupInviteCode: async () => 'CODE123', groupRevokeInvite: async () => 'NEWCODE', profilePictureUrl: async () => { throw new Error('no photo'); },
    sendMessage: async (c, m) => { sent.push(m); }, relayMessage: async () => {}, ...o }; };
const call = (sock) => handleBotCommand({ sock, db, msg: { key: {}, message: {} }, chatJid: G, senderJid: process.env.KING_NUMBER + '@s.whatsapp.net', text: '.invite', mentionedJid: null, groupParticipants: [], isRegistered: true });
const link = (m) => (m.text || '').includes('chat.whatsapp.com/CODE123');

// 1. normal: no group photo -> link preview still sent
{ const s = mkSock(); await call(s); assert.equal(s.sent.length, 1); assert.ok(link(s.sent[0])); }
// 2. rich preview rejected by WhatsApp -> falls back to a plain link, never silence
{ let n = 0; const s = mkSock({ sendMessage: async (c, m) => { if (m.contextInfo) throw new Error('boom'); s.sent.push(m); } }); await call(s); assert.equal(s.sent.length, 1); assert.ok(link(s.sent[0])); }
// 3. group has no link yet -> revoke creates one
{ const s = mkSock({ groupInviteCode: async () => { throw new Error('item-not-found'); } }); await call(s); assert.ok((s.sent[0].text || '').includes('NEWCODE')); }
// 4. photo download hangs forever -> still answers (bounded wait)
{ const s = mkSock({ profilePictureUrl: () => new Promise(() => {}) }); const t = Date.now(); await call(s); assert.ok(link(s.sent[0])); assert.ok(Date.now() - t < 20000, 'took too long'); }
// 5. invite-code call hangs -> an error message, not silence
{ const s = mkSock({ groupInviteCode: () => new Promise(() => {}) }); const r = await Promise.race([call(s), new Promise(res => setTimeout(() => res('HUNG'), 40000))]); assert.match(String(r), /Could not generate invite/); assert.match(String(r), /timed out/); }
// 6. DM
{ const s = mkSock(); const r = await handleBotCommand({ sock: s, db, msg: { key: {}, message: {} }, chatJid: '1@s.whatsapp.net', senderJid: '1@s.whatsapp.net', text: '.invite', mentionedJid: null, groupParticipants: [], isRegistered: true }); assert.match(String(r), /only works inside a group/); }
console.log('INVITE TESTS PASSED');
// 7. the default message must be a plain, always-visible one (no ad-reply contextInfo that WhatsApp can swallow)
{ const s = mkSock(); await call(s); assert.equal(s.sent[0].contextInfo, undefined); assert.match(s.sent[0].text, /Tap to join/); }
// 8. `.invite preview` still gives the old big-preview style
{ const s = mkSock(); await handleBotCommand({ sock: s, db, msg: { key: {}, message: {} }, chatJid: G, senderJid: process.env.KING_NUMBER + '@s.whatsapp.net', text: '.invite preview', mentionedJid: null, groupParticipants: [], isRegistered: true }); assert.ok(s.sent[0].contextInfo?.externalAdReply); }
console.log('INVITE EXTRA TESTS PASSED');
