// node tests/js/wcg_game_test.mjs [--transcript]  — engine tests for .wcg (fake clock, fake socket, real dictionary).
import assert from 'node:assert/strict';
import { WcgManager, tierFor, TIERS, LOBBY_MS, REVEAL_MS, loadWords, loadBigWords, parseBigList } from '../../bot/lib/wcg_game.js';

const TRANSCRIPT = process.argv.includes('--transcript');
const words = loadWords();
const common = loadWords(new URL('../../bot/lib/wcg_common.txt', import.meta.url));
const G = 'g@g.us', MICA = '111@s', JED = '222@s', MIR = '333@s';
const name = { [MICA]: 'mica', [JED]: 'jed', [MIR]: 'miracle' };

function world(seed = 7) {
    let s = seed; const rand = () => (s = (s * 16807) % 2147483647) / 2147483647;   // deterministic
    let now = 0, id = 0; const timers = new Map(); const out = [];
    const setT = (fn, ms) => { timers.set(++id, { at: now + ms, fn }); return id; };
    const clearT = (i) => timers.delete(i);
    const io = { send: async (chat, text, o = {}) => { out.push({ at: now, text, ...o }); if (TRANSCRIPT) console.log(`  [${(now / 1000).toFixed(0).padStart(3)}s] 🤖 ${text.replace(/@(\d+)/g, (_, n) => '@' + (name[n + '@s'] ?? n)).replace(/\n/g, '\n         ')}\n`); } };
    const m = new WcgManager(io, { rand, setT, clearT, words, common });
    const tick = async (ms) => {
        const end = now + ms;
        for (;;) {
            const due = [...timers.entries()].filter(([, t]) => t.at <= end).sort((a, b) => a[1].at - b[1].at)[0];
            if (!due) break;
            now = due[1].at; timers.delete(due[0]); await due[1].fn();
        }
        now = end;
    };
    const say = async (who, text) => {
        if (TRANSCRIPT) console.log(`  [${(now / 1000).toFixed(0).padStart(3)}s] ${name[who]}: ${text}`);
        if (text.startsWith('.wcg')) return m.command(G, who, text.split(' ').slice(1));
        return m.answer(G, who, text);
    };
    return { m, out, tick, say, last: () => out[out.length - 1], g: () => m.games.get(G), clock: () => now };
}

// ── tiers: 3 rounds per level, final tier sticks
assert.deepEqual(tierFor(1), { minLen: 3, ms: 60_000 });
assert.deepEqual(tierFor(3), TIERS[0]); assert.deepEqual(tierFor(4), { minLen: 4, ms: 45_000 });
assert.deepEqual(tierFor(7), { minLen: 5, ms: 30_000 }); assert.deepEqual(tierFor(10), { minLen: 6, ms: 15_000 });
assert.deepEqual(tierFor(13), { minLen: 7, ms: 10_000 }); assert.deepEqual(tierFor(99), TIERS[4]);

// ── lobby with one player cancels
{
    const w = world();
    await w.say(MICA, '.wcg start'); await w.tick(LOBBY_MS);
    assert.match(w.last().text, /not enough players/); assert.equal(w.g(), undefined);
}

// ── full game
{
    const w = world();
    await w.say(MICA, '.wcg start');
    assert.match(w.last().text, /Lobby open for 20s/);
    await w.say(JED, '.wcg join'); await w.say(MIR, '.wcg join');
    await w.say(JED, '.wcg join'); assert.match(w.last().text, /already in/);
    await w.tick(LOBBY_MS - 1); assert.equal(w.g().phase, 'lobby');
    await w.tick(1); assert.equal(w.g().phase, 'reveal'); assert.match(w.last().text, /turn order/);
    await w.say(MIR, '.wcg end'); assert.match(w.last().text, /Only the host/);   // non-host can't end
    await w.tick(REVEAL_MS); assert.equal(w.g().phase, 'play');
    assert.match(w.out.find(o => /started/.test(o.text)).text, /3\+ letters, 60s per turn/);

    // rejections do not eliminate and keep the clock running
    let cur = w.g().current, letter = w.g().last.slice(-1);
    const wrong = words.find(x => x[0] !== letter && x.length > 3);
    await w.say(cur, wrong); assert.match(w.last().text, /does not start with/);
    await w.say(cur, letter + 'q'); assert.match(w.last().text, /(too short|not in the dictionary)/);
    await w.say(cur, letter + 'zzzzzz'); assert.match(w.last().text, /not in the dictionary/);
    const other = [MICA, JED, MIR].find(p => p !== cur);
    assert.equal(await w.say(other, 'hello'), false);                     // not your turn: ignored
    assert.equal(w.g().current, cur);

    // play 9 rounds (27 words) with auto-picked words; verify tier banners
    const seen = new Set();
    for (let i = 0; i < 27; i++) {
        const g = w.g(); const t = tierFor(g.round);
        const word = w.m.suggest(g.last.slice(-1), t.minLen, g.used);
        await w.say(g.current, word);
        assert.match(w.last().text, new RegExp(`✅ \\*${word}\\*`));
        seen.add(w.g().round);
    }
    assert.equal(w.g().round, 10);
    assert.ok(w.out.some(o => /Round 4.*4\+ letters, 45s/s.test(o.text)));
    assert.ok(w.out.some(o => /Round 7.*5\+ letters, 30s/s.test(o.text)));
    assert.ok(w.out.some(o => /Round 10.*6\+ letters, 15s/s.test(o.text)));

    // repeat word is rejected
    const g = w.g(); const dup = [...g.used].find(x => x[0] === g.last.slice(-1) && x.length >= 6);
    if (dup) { await w.say(g.current, dup); assert.match(w.last().text, /already used/); }

    // AFK: current player times out after 15s at this tier -> eliminated, remark + suggestion, baton passed
    const victim = w.g().current;
    await w.tick(14_999); assert.equal(w.g().current, victim);
    await w.tick(1);
    assert.match(w.last().text, /is out/); assert.match(w.last().text, /You could have said/);
    assert.ok(!w.g().order.includes(victim)); assert.equal(w.g().order.length, 2);
    assert.notEqual(w.g().current, victim);

    // second AFK -> last player standing wins and the game is cleaned up
    const loser = w.g().current; const winner = w.g().order.find(p => p !== loser);
    await w.tick(15_000);
    assert.match(w.last().text, new RegExp(`${winner.split('@')[0]} wins`));
    assert.equal(w.g(), undefined);
}

// ── host ends mid-game; stale timers do nothing
{
    const w = world(3);
    await w.say(MICA, '.wcg start'); await w.say(JED, '.wcg join');
    await w.tick(LOBBY_MS + REVEAL_MS);
    const n = w.out.length;
    await w.say(MICA, '.wcg end'); assert.match(w.last().text, /Word Chain ended/); assert.equal(w.g(), undefined);
    await w.tick(120_000); assert.equal(w.out.length, n + 1);
    await w.say(JED, '.wcg join'); assert.match(w.last().text, /No lobby open/);
}

// ── answering in time cancels the old timer (no double elimination)
{
    const w = world(5);
    await w.say(MICA, '.wcg start'); await w.say(JED, '.wcg join');
    await w.tick(LOBBY_MS + REVEAL_MS);
    const g = w.g(); await w.say(g.current, w.m.suggest(g.last.slice(-1), 3, g.used));
    await w.tick(59_000); assert.equal(w.g().order.length, 2);
}
// ── big dictionary: download ok / bad file / network error all behave
{
    const quiet = () => {};
    const big = Array.from({ length: 120_000 }, (_, i) => 'w' + 'abcdefghij'.repeat(1) + String.fromCharCode(97 + (i % 26)) + String.fromCharCode(97 + ((i / 26 | 0) % 26)) + String.fromCharCode(97 + ((i / 676 | 0) % 26)) + String.fromCharCode(97 + ((i / 17576 | 0) % 26))).join('\n');
    const tmp = new URL('file:///tmp/wcg_big_test_cache.txt'); try { (await import('node:fs')).unlinkSync(tmp); } catch {}
    assert.equal(parseBigList('hello\nworld'), null);                                   // too small = rejected
    const okFetch = async () => ({ ok: true, text: async () => big });
    const list = await loadBigWords({ fetchFn: okFetch, cache: tmp, log: quiet }); assert.ok(list.length >= 100_000);
    const noNet = async () => { throw new Error('offline'); };
    assert.ok((await loadBigWords({ fetchFn: noNet, cache: tmp, log: quiet })).length >= 100_000);   // served from cache
    (await import('node:fs')).unlinkSync(tmp);
    assert.equal(await loadBigWords({ fetchFn: noNet, cache: tmp, log: quiet }), null);               // offline + no cache -> keep built-in
    assert.equal(await loadBigWords({ fetchFn: async () => ({ ok: false, status: 404 }), cache: tmp, log: quiet }), null);
    assert.equal(await loadBigWords({ fetchFn: async () => ({ ok: true, text: async () => '<html>nope</html>' }), cache: tmp, log: quiet }), null);
    const w = world(); w.m.setWords(['zzzz', 'zzzzz']); assert.ok(w.m.dict.has('zzzz') && !w.m.dict.has('apple'));
}
console.log(TRANSCRIPT ? '\nALL WCG TESTS PASSED' : 'ALL WCG TESTS PASSED');
