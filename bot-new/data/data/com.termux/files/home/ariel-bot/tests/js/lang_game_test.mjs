// node tests/js/lang_game_test.mjs   — engine tests for the .lang game (fake clock, fake socket).
import assert from 'node:assert/strict';
import { LangManager, checkAnswer, WORD_TIMEOUT_MS, LOBBY_MS, RULES_MS, TIMED_MS } from '../../bot/lib/lang_game.js';
import { LANGUAGES } from '../../bot/lib/lang_words.js';

// ── word list sanity: one syllable per kana (small ゃゅょ merge into the previous kana)
for (const w of LANGUAGES.japanese.words) {
    const morae = [...w.kana].filter(c => !'ゃゅょ'.includes(c)).length;
    assert.equal(w.syl.length, morae, `${w.kana} has ${morae} kana but ${w.syl.length} syllables`);
}
const sakura = { kana: 'さくら', syl: ['sa', 'ku', 'ra'], display: 'Sakura', en: 'cherry blossom' };

// ── answer checking
assert.deepEqual(checkAnswer(sakura, 'sa ku ri').marks, [true, true, false]);
assert.equal(checkAnswer(sakura, 'SA KU RA').full, true);
assert.equal(checkAnswer(sakura, 'sa ku ra ra').full, false);
assert.deepEqual(checkAnswer(sakura, 'ku sa ra').marks, [false, false, true]);   // position matters
assert.deepEqual(checkAnswer(sakura, 'sakura').marks, [false]);                    // unspaced = 1 syllable
assert.equal(checkAnswer({ ...sakura, syl: ['shi', 'chi', 'tsu'] }, 'si ti tu').full, true);

// ── harness
function world() {
    let now = 0, id = 0; const timers = new Map(); const out = [];
    const setT = (fn, ms) => { timers.set(++id, { at: now + ms, fn }); return id; };
    const clearT = (i) => timers.delete(i);
    const io = { send: async (chat, text, o = {}) => { out.push({ chat, text, ...o }); }, participants: async () => ['a@s', 'b@s', 'c@s', 'z@s'] };
    const m = new LangManager(io, { rand: () => 0, setT, clearT });
    const tick = async (ms) => {
        const end = now + ms;
        for (;;) {
            const due = [...timers.entries()].filter(([, t]) => t.at <= end).sort((a, b) => a[1].at - b[1].at)[0];
            if (!due) break;
            now = due[1].at; timers.delete(due[0]); await due[1].fn();
        }
        now = end;
    };
    return { m, out, tick, last: () => out[out.length - 1], timers };
}
const G = 'g@g.us';
const cur = (m, key) => m.solo.get(key).round.deck.cur;

// ── solo: scoring exactly like the design example, then word bonus
{
    const w = world();
    await w.m.command(G, 'bryan@s', ['start']);
    const s = w.m.solo.get(`${G}|bryan@s`);
    s.round.deck.cur = sakura;                       // force the word
    await w.m.answer(G, 'bryan@s', 'sa ku ri');
    assert.match(w.last().text, /sa✅ ku✅ ri❌\s+\+2/); assert.equal(s.player.score, 2);
    await w.m.answer(G, 'bryan@s', 'sa ke ri');
    assert.match(w.last().text, /\(Alr got\)/); assert.equal(s.player.score, 2);
    await w.m.answer(G, 'bryan@s', 'sa ku ra');       // adds ra (+1) and the +5
    assert.equal(s.player.score, 8);
    assert.match(w.last().text, /Prev: さくら ✅ \(Sakura — cherry blossom\)/);
    assert.match(w.last().text, /Current: .+ — .+/);
    assert.match(w.last().text, /Current: /);
}
// ── solo: bail, timeout (fail, keeps going), end; two people at once
{
    const w = world();
    await w.m.command(G, 'a@s', ['start', 'japanese']);
    await w.m.command(G, 'b@s', ['start']);
    assert.equal(w.m.solo.size, 2);
    const wordA = cur(w.m, `${G}|a@s`);
    assert.equal(await w.m.bail(G, 'a@s'), true);
    assert.match(w.last().text, new RegExp(`Prev: ${wordA.kana} ❌ \\(${wordA.display} — `));
    await w.tick(WORD_TIMEOUT_MS - 1000);
    await w.m.answer(G, 'b@s', 'sa');                       // b replies at 59s, restarting b's minute
    assert.equal(w.m.solo.size, 2);                         // nobody timed out yet
    await w.tick(2000);                                     // a has now been silent for 61s
    assert.equal(w.m.solo.has(`${G}|a@s`), false);          // a: 1 minute silent -> run ends
    assert.match(w.out.find(o => /no reply for 1 minute/.test(o.text)).text, /final score/);
    assert.equal(w.m.solo.has(`${G}|b@s`), true);
    await w.m.command(G, 'b@s', ['end']);
    assert.equal(w.m.solo.size, 0);
    assert.equal(await w.m.answer(G, 'a@s', 'x'), false);
}
// ── tournament: lobby -> rules (hidetag) -> run; modes; ranking; end
{
    const w = world();
    await w.m.command(G, 'a@s', ['tournament']);
    await w.m.command(G, 'b@s', ['join']);
    await w.m.command(G, 'c@s', ['join']);
    await w.m.command(G, 'c@s', ['timed']);
    await w.m.command(G, 'c@s', ['infinite']);
    await w.tick(LOBBY_MS + 1);
    const rules = w.last();
    assert.equal(rules.hide, true); assert.ok(rules.mentions.includes('z@s'));   // everyone is tagged
    assert.match(rules.text, /Rules:/); assert.match(rules.text, /Mode: \*infinite\*/);
    await w.tick(RULES_MS + 1);
    const t = w.m.tours.get(G); assert.equal(t.phase, 'running');
    t.round.deck.cur = sakura;
    await w.m.answer(G, 'a@s', 'sa ku ri');                    // a: 2
    await w.m.answer(G, 'b@s', 'sa ku ra');                    // b: 3 + 5, word ends
    assert.match(w.last().text, /Prev: さくら ✅/);
    assert.match(w.last().text, /1\. @b - 8 points\n2\. @a - 2 points\n3\. @c - 0 points/);
    assert.equal(await w.m.answer(G, 'zz@s', 'x'), false);     // non-player ignored
    await w.m.command(G, 'zz@s', ['end']);                      // non-player cannot end it
    assert.ok(w.m.tours.has(G));
    await w.m.command(G, 'a@s', ['end']);                       // infinite: any player can
    assert.ok(!w.m.tours.has(G));
    const fin = w.last().text;
    assert.match(fin, /\*1st\* @b - 8 points 🥇 🥇 🥇\n\*2nd\* @a - 2 points 🏅 🏅\n\*3rd\* @c - 0 points ✨/);
}
// ── tournament: fixed length = 25 + 10/player, timed = 3 min, ties share rank, <2 players cancels
{
    const w = world();
    await w.m.command(G, 'a@s', ['tournament']);
    await w.m.command(G, 'b@s', ['join']);
    await w.tick(LOBBY_MS + RULES_MS + 2);
    const t = w.m.tours.get(G); assert.equal(t.total, 45);
    for (let i = 0; i < 45; i++) { await w.m.bail(G, 'a@s'); }
    assert.ok(!w.m.tours.has(G)); assert.match(w.last().text, /Tournament over/);
    assert.match(w.last().text, /\*1st\* @a - 0 points 🥇 🥇 🥇\n\*1st\* @b - 0 points 🥇 🥇 🥇/);
}
{
    const w = world();
    await w.m.command(G, 'a@s', ['tournament']);
    await w.m.command(G, 'a@s', ['timed']);
    await w.m.command(G, 'b@s', ['join']);
    await w.tick(LOBBY_MS + RULES_MS + 2);
    await w.tick(TIMED_MS + 1);
    assert.ok(!w.m.tours.has(G)); assert.match(w.last().text, /Time!/);
}
{
    const w = world();
    await w.m.command(G, 'a@s', ['tournament']);
    await w.tick(LOBBY_MS + 1);
    assert.ok(!w.m.tours.has(G)); assert.match(w.last().text, /at least 2 players/);
}
// ── .lang end works in every mode (fixed / timed too), but only for players
for (const mode of ['fixed', 'timed']) {
    const w = world();
    await w.m.command(G, 'a@s', ['tournament']);
    await w.m.command(G, 'a@s', [mode]);
    await w.m.command(G, 'b@s', ['join']);
    await w.tick(LOBBY_MS + RULES_MS + 2);
    await w.m.command(G, 'zz@s', ['end']); assert.ok(w.m.tours.has(G));
    await w.m.command(G, 'b@s', ['end']);
    assert.ok(!w.m.tours.has(G)); assert.match(w.last().text, /Ended by a player[\s\S]*Tournament over/);
}
console.log('lang game: all tests passed');
