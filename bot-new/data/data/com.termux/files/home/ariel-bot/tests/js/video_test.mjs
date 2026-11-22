// node tests/js/video_test.mjs  — needs ffmpeg. GIF reactions must go out as REAL mp4, and .sticker's video path must give a webp.
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import fs from 'node:fs'; import os from 'node:os'; import path from 'node:path';
import { kindOf, videoToStickerWebp } from '../../bot/lib/video.js';
import { sendReaction } from '../../bot/reactions.js';

const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'vtest_'));
execFileSync('ffmpeg', ['-loglevel', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc=size=321x241:rate=10:duration=2', path.join(dir, 't.gif')]);
execFileSync('ffmpeg', ['-loglevel', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc=size=640x360:rate=25:duration=3', '-pix_fmt', 'yuv420p', path.join(dir, 't.mp4')]);
const gif = fs.readFileSync(path.join(dir, 't.gif')), mp4 = fs.readFileSync(path.join(dir, 't.mp4'));

let body = gif;
globalThis.fetch = async () => ({ ok: true, arrayBuffer: async () => body.buffer.slice(body.byteOffset, body.byteOffset + body.length) });
const sent = []; const sock = { sendMessage: async (c, m) => { sent.push(m); } };

await sendReaction(sock, 'g@g.us', 'http://x/a.gif', 'cap', ['1@s'], null);
assert.ok(sent[0].video && sent[0].gifPlayback); assert.equal(kindOf(sent[0].video), 'mp4', 'gif must be converted to mp4');

body = mp4; sent.length = 0;                                   // already mp4: sent untouched
await sendReaction(sock, 'g@g.us', 'http://x/b.mp4', 'cap', [], null);
assert.equal(sent[0].video.length, mp4.length);

body = Buffer.from('<html>nope</html>'); sent.length = 0;      // junk: falls back to the image path, never throws
await sendReaction(sock, 'g@g.us', 'http://x/c.gif', 'cap', [], null);
assert.ok(sent[0].image);

const st = await videoToStickerWebp(mp4);
assert.equal(kindOf(st), 'webp'); assert.ok(st.length <= 500 * 1024);
fs.rmSync(dir, { recursive: true, force: true });
console.log('VIDEO TESTS PASSED');
