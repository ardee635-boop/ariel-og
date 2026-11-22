// node --no-warnings --import ./tests/js/register.mjs tests/js/amongus_image_file_test.mjs
// Stage pictures are local files written by the engine; only files inside the stage cache may be sent from disk.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
const cache = fs.mkdtempSync(path.join(os.tmpdir(), 'stage-'));
process.env.AMONGUS_STAGE_CACHE = cache;
await import('./harness.mjs');
const { isStageFile, sendImage } = await import('../../bot/lib/send.js');

const good = path.join(cache, 'stage_abc.jpg'); fs.writeFileSync(good, Buffer.from([1, 2, 3]));
const outside = path.join(os.tmpdir(), 'evil.jpg'); fs.writeFileSync(outside, Buffer.from([9]));
assert.equal(isStageFile(good), true);
assert.equal(isStageFile(outside), false, 'outside the cache folder');
assert.equal(isStageFile(path.join(cache, '..', 'evil.jpg')), false, 'traversal');
assert.equal(isStageFile(path.join(cache, 'missing.jpg')), false, 'missing file');
assert.equal(isStageFile(path.join(cache, 'x.txt')), false, 'wrong type');
assert.equal(isStageFile('https://example.test/a.jpg'), false, 'urls are not files');
assert.equal(isStageFile(null), false);

const sent = [];
const sock = { sendMessage: async (jid, content) => { sent.push([jid, content]); return {}; } };
await sendImage(sock, '1@s.whatsapp.net', good, 'cap');
assert.ok(Buffer.isBuffer(sent[0][1].image), 'local file goes out as bytes'); assert.equal(sent[0][1].caption, 'cap');
await sendImage(sock, '1@s.whatsapp.net', 'https://example.test/a.jpg', 'cap2');
assert.deepEqual(sent[1][1].image, { url: 'https://example.test/a.jpg' }, 'urls unchanged');
process.stdout.write('AMONG US IMAGE FILE TESTS PASSED\n');
