// node --no-warnings --import ./tests/js/register.mjs tests/js/card_test.mjs — .preview link card.
import assert from 'node:assert/strict';
import { sendCard, squareThumb, MENU_IMG, DEFAULT_URL } from '../../bot/lib/card.js';
globalThis.fetch = async () => ({ ok: true, arrayBuffer: async () => new ArrayBuffer(8) });
const mk = (o = {}) => { const sent = []; return { sent, sendMessage: async (c, m, x) => { if (o.fail && m.contextInfo) throw new Error('boom'); sent.push({ c, m, x }); } }; };

{ const s = mk(); await sendCard(s, 'g@g.us', { title: 'Sage', body: 'Balance', url: 'https://example.com', text: 'hello', quoted: { k: 1 } });
  const ad = s.sent[0].m.contextInfo.externalAdReply;
  assert.equal(ad.title, 'Sage'); assert.equal(ad.body, 'Balance'); assert.equal(ad.sourceUrl, 'https://example.com');
  assert.equal(ad.renderLargerThumbnail, false); assert.equal(ad.showAdAttribution, false); assert.ok(ad.thumbnail);
  assert.equal(s.sent[0].m.text, 'hello'); assert.deepEqual(s.sent[0].x, { quoted: { k: 1 } }); }
{ const s = mk(); await sendCard(s, 'g@g.us', {}); const ad = s.sent[0].m.contextInfo.externalAdReply; assert.equal(ad.title, 'Ariel'); assert.equal(ad.sourceUrl, DEFAULT_URL); }
{ const s = mk({ fail: true }); await sendCard(s, 'g@g.us', { title: 'T', text: 'body text' }); assert.equal(s.sent.length, 1); assert.equal(s.sent[0].m.text, 'body text'); assert.equal(s.sent[0].m.contextInfo, undefined); }   // card rejected -> plain text, never silence
{ globalThis.fetch = async () => { throw new Error('offline'); }; assert.equal(await squareThumb('http://x/none.jpg'), null);
  const s = mk(); await sendCard(s, 'g@g.us', { title: 'T', image: 'http://x/none.jpg', text: 'x' }); assert.equal(s.sent[0].m.contextInfo.externalAdReply.thumbnail, undefined); }   // no picture -> card still goes out
assert.match(MENU_IMG, /^https:\/\//);
console.log('CARD TESTS PASSED');
