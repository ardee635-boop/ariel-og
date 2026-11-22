// Stage 8 tests: style controls, feedback, mood, reflection, persona, and how they plug into the conversation.
// Run:  node --test tests/js/ariel_stage8_test.mjs      (no database, no network, no WhatsApp)
import test from 'node:test';
import assert from 'node:assert/strict';

import { STYLE_DEFAULTS, normaliseStyle, stepStyle, styleLimits, styleWords, calmCaps } from '../../bot/ariel/style.js';
import { detectFeedback, createFeedback } from '../../bot/ariel/feedback.js';
import { drifted, applyVibe, moodWords, createMood } from '../../bot/ariel/mood.js';
import { createReflection } from '../../bot/ariel/reflect.js';
import { createPersona } from '../../bot/ariel/persona.js';
import { createMemSelfStore } from '../../bot/ariel/store/self.js';
import { buildContext, systemText } from '../../bot/ariel/prompt.js';
import { createConversation } from '../../bot/ariel/conversation.js';
import { createJobs } from '../../bot/ariel/jobs.js';
import { createSummariser } from '../../bot/ariel/summarise.js';
import { withDefaults } from '../../bot/ariel/config.js';

const cfg = withDefaults();
const DAY = 86400_000;
const jsonAi = (fn) => ({ chat: async (req) => ({ text: JSON.stringify(fn(req)) }) });

// ── style ───────────────────────────────────────────────────
test('style: values snap to allowed steps, one step at a time, ends hold', () => {
    assert.deepEqual(normaliseStyle({}), STYLE_DEFAULTS);
    assert.equal(normaliseStyle({ expressiveness: 9 }).expressiveness, 3);
    assert.equal(normaliseStyle({ expressiveness: 1.3 }).expressiveness, 1.5);
    assert.equal(normaliseStyle({ length: 'x', emoji: -4 }).length, 2);
    assert.equal(normaliseStyle({ emoji: -4 }).emoji, 0);
    assert.equal(stepStyle({ expressiveness: 2.5 }, 'expressiveness', +1), 3);
    assert.equal(stepStyle({ expressiveness: 3 }, 'expressiveness', +1), 3);
    assert.equal(stepStyle({ length: 2 }, 'length', -1), 1);
    assert.equal(stepStyle({ emoji: 0 }, 'emoji', -1), 0);
});

test('style: limits follow the settings; default equals the old behaviour; words have no numbers', () => {
    assert.deepEqual(styleLimits({}, cfg), { maxEmoji: 2, maxBubbles: 4, maxBubbleChars: 700, maxShouting: 1 });
    assert.equal(styleLimits({ length: 1 }, cfg).maxBubbles, 2);
    assert.equal(styleLimits({ emoji: 0 }, cfg).maxEmoji, 0);
    assert.ok(styleLimits({ length: 3 }, cfg).maxBubbles > 4);
    for (const s of [{}, { expressiveness: 0, length: 1, emoji: 0 }, { expressiveness: 3, length: 3, emoji: 3 }]) assert.ok(!/\d/.test(styleWords(s)), styleWords(s));
});

test('style: shouting and aLtErNaTiNg caps are calmed in code', () => {
    assert.deepEqual(calmCaps(['WHAT is THIS lol OK'], 1), ['WHAT is this lol OK']);
    assert.deepEqual(calmCaps(['hElLo wOrLd'], 1), ['hello world']);
    assert.deepEqual(calmCaps(['NOPE WAIT', 'STOP IT'], 1), ['NOPE wait', 'stop IT']);   // one shouted word for the whole reply
    assert.deepEqual(calmCaps(['lol i love AI and the UK'], 0), ['lol i love AI and the UK']);                // short acronyms stay
});

// ── feedback detection ──────────────────────────────────────
test('feedback: what counts as a remark about her, and what does not', () => {
    const yes = [
        ['you sound robotic', 'robotic'], ['u dey sound like robot', 'robotic'], ['you are boring', 'robotic'], ['your replies are too short', 'too_short'],
        ['you are too wordy abeg', 'too_long'], ['keep it short', 'too_long'], ['stop using so many emojis', 'emoji_less'], ['too many emojis', 'emoji_less'],
        ['use more emojis', 'emoji_more'], ['you are cringe', 'overdone'], ['ariel you dey overdo am', 'overdone'], ['you keep repeating yourself', 'repetitive'],
    ];
    for (const [t, k] of yes) assert.deepEqual(detectFeedback(t), [k], t);
    const no = ['this movie is so robotic', 'did you see that cringe video', 'you are too much 😂', 'why you no reply', '.chat on', 'emojis are cool', 'the match was too long',
        'you saw the essay he wrote?', '', 'x'.repeat(300) + ' you sound robotic'];
    for (const t of no) assert.deepEqual(detectFeedback(t), [], t);
    assert.deepEqual(detectFeedback('your replies are too short, you sound too long'), []);        // contradicts itself: neither
});

// ── feedback -> style review ────────────────────────────────
function fbRig(clock = { t: Date.now() }) {
    const self = createMemSelfStore();
    self.state.clock = () => clock.t;
    const fb = createFeedback({ self, cfg, now: () => clock.t });
    const sig = (person, kind, daysAgo = 1) => self.state.feedback.push({ id: ++self.state.seq, person_id: person, kind, text: 'x', weight: 1, created_at: new Date(clock.t - daysAgo * DAY) });
    return { self, fb, sig, clock };
}

test('feedback: the same person saying it twice in a row counts once', async () => {
    const { self, fb } = fbRig();
    assert.equal(await fb.observe({ personId: 1, body: 'you sound robotic' }), 1);
    assert.equal(await fb.observe({ personId: 1, body: 'seriously you sound robotic' }), 0);
    assert.equal(await fb.observe({ personId: 2, body: 'you sound robotic' }), 1);
    assert.equal(self.state.feedback.length, 2);
    assert.equal(await fb.observe({ personId: null, body: 'you sound robotic' }), 0);
});

test('style review: 3 remarks from 2 people in 7 days moves ONE step', async () => {
    const { self, fb, sig } = fbRig();
    sig(1, 'robotic', 1); sig(2, 'robotic', 2); sig(1, 'robotic', 3);
    const r = await fb.review();
    assert.equal(r.moves.length, 1);
    assert.equal((await fb.getStyle()).values.expressiveness, 3);                    // 2.5 -> 3
    assert.equal((await self.getLog()).length, 1);
    assert.equal((await self.getLog())[0].evidence.length, 3);
});

test('style review: one angry person, two remarks, or old remarks change nothing', async () => {
    const a = fbRig(); a.sig(1, 'robotic'); a.sig(1, 'robotic', 2); a.sig(1, 'robotic', 3);
    assert.equal((await a.fb.review()).moves.length, 0);                              // 3 remarks but ONE person
    const b = fbRig(); b.sig(1, 'too_long'); b.sig(2, 'too_long');
    assert.equal((await b.fb.review()).moves.length, 0);                              // only 2
    const c = fbRig(); c.sig(1, 'emoji_less', 9); c.sig(2, 'emoji_less', 10); c.sig(3, 'emoji_less', 11);
    assert.equal((await c.fb.review()).moves.length, 0);                              // older than 7 days
});

test('style review: disagreement changes nothing; ten remarks still move only one step; used remarks are not reused', async () => {
    const a = fbRig();
    a.sig(1, 'robotic'); a.sig(2, 'robotic'); a.sig(3, 'robotic'); a.sig(4, 'overdone'); a.sig(5, 'overdone');
    assert.equal((await a.fb.review()).moves.length, 0);
    const b = fbRig();
    for (let i = 1; i <= 10; i++) b.sig(i, 'too_long', 1);
    assert.equal((await b.fb.review()).moves.length, 1);
    assert.equal((await b.fb.getStyle()).values.length, 1);
    assert.equal((await b.fb.review()).moves.length, 0);                              // same remarks: already used
    assert.equal((await b.fb.getStyle()).values.length, 1);
    b.clock.t += 1000; b.sig(11, 'too_long', 0); b.sig(12, 'too_long', 0); b.sig(13, 'too_long', 0);
    assert.equal((await b.fb.review()).moves.length, 0);                              // already at the end of the range
});

test('style review: independent settings move independently; old remarks are purged', async () => {
    const { self, fb, sig } = fbRig();
    sig(1, 'emoji_less'); sig(2, 'emoji_less'); sig(3, 'emoji_less'); sig(1, 'too_short'); sig(2, 'too_short'); sig(3, 'too_short');
    sig(9, 'repetitive', 70);
    const r = await fb.review();
    const v = (await fb.getStyle()).values;
    assert.equal(r.moves.length, 2);
    assert.equal(v.emoji, 1); assert.equal(v.length, 3); assert.equal(v.expressiveness, 2.5);
    assert.equal(r.purged, 1);
    assert.equal(self.state.feedback.length, 6);
});

test('style: owner can set by hand (snapped) and reset', async () => {
    const { fb } = fbRig();
    assert.equal((await fb.setByHand('emoji', 7)).emoji, 3);
    assert.equal((await fb.setByHand('expressiveness', 1.1)).expressiveness, 1);
    await assert.rejects(() => fb.setByHand('spice', 1), /unknown setting/);
    await assert.rejects(() => fb.setByHand('emoji', 'lots'), /number/);
    await fb.reset();
    assert.deepEqual((await fb.getStyle()).values, STYLE_DEFAULTS);
});

// ── mood ────────────────────────────────────────────────────
test('mood: conversations nudge it, time brings it back to neutral', () => {
    const t0 = 1_800_000_000_000;
    let st = applyVibe({}, { vibe: 'positive', messages: 30 }, t0);
    assert.ok(st.mood > 0.15 && st.mood <= 0.8);
    assert.equal(moodWords(st, t0).includes('mood'), false);                      // one nice chat is not a "mood" yet
    st = applyVibe(st, { vibe: 'playful', messages: 30 }, t0);
    assert.ok(st.energy < 0.7);
    assert.match(moodWords(st, t0), /good mood/);
    assert.equal(moodWords(st, t0 + 4 * 24 * 3600_000), '');                        // 4 days later: back to normal
    const d = drifted(st, t0 + 36 * 3600_000);
    assert.ok(Math.abs(d.mood) < Math.abs(st.mood) / 3);
    let low = {};
    for (let i = 0; i < 6; i++) low = applyVibe(low, { vibe: 'hostile', messages: 40 }, t0);
    assert.ok(low.mood >= -0.8);
    assert.match(moodWords(low, t0), /low|off/);
    assert.match(moodWords({ mood: 0, energy: 0.1, at: t0 }, t0), /low on energy/);
    assert.equal(applyVibe({}, { vibe: 'weird', messages: 2 }, t0).mood, 0);        // unknown vibe = neutral
});

test('mood: recordSegment persists and leaves other state (interests) alone', async () => {
    const self = createMemSelfStore();
    await self.mergeState({ interests: ['football'] });
    const mood = createMood({ self });
    await mood.recordSegment({ vibe: 'playful', messages: 12 });
    const st = await self.getState();
    assert.deepEqual(st.interests, ['football']);
    assert.ok(st.mood > 0 && st.last_vibe === 'playful');
});

// ── reflection ──────────────────────────────────────────────
function refRig({ names = ['Chidi', 'Amaka'], n = 9, ai } = {}) {
    const self = createMemSelfStore();
    const now = Date.now();
    self.state.clock = () => now;
    self.state.names = names;
    for (let i = 1; i <= n; i++) self.state.summaries.push({ id: i, chat_id: (i % 3) + 1, body: `They talked about lofi beats and banter, part ${i}.`, topics: ['music'], kind: i % 2 ? 'group' : 'dm', ended: new Date(now - i * 2 * DAY).toISOString() });
    const refl = createReflection({ self, ai, cfg, now: () => now });
    return { self, refl, now };
}
const add = (o = {}) => ({ op: 'add', kind: 'interest', text: 'She keeps coming back to lofi music.', keyword: 'lofi', episodes: ['S1', 'S2', 'S3'], reason: 'came up a lot', ...o });

test('reflection: starts in dry-run, proposals are logged, nothing changes', async () => {
    const { self, refl } = refRig({ ai: jsonAi(() => ({ changes: [add()] })) });
    const r = await refl.run();
    assert.equal(r.live, false);
    assert.equal(r.proposed.length, 1); assert.equal(r.applied.length, 0);
    assert.equal((await self.listIdentity()).length, 0);
    const log = await self.getLog();
    assert.equal(log[0].status, 'proposed'); assert.deepEqual(log[0].evidence, [1, 2, 3]);
});

test('reflection: live applies, logs the evidence, and feeds her interests to the join check', async () => {
    const { self, refl } = refRig({ ai: jsonAi(() => ({ changes: [add()] })) });
    await self.setConfig('reflect.live', true);
    const r = await refl.run();
    assert.equal(r.applied.length, 1);
    const items = await self.listIdentity();
    assert.equal(items.length, 1);
    assert.equal(items[0].key, 'interest:lofi'); assert.equal(items[0].evidence_count, 3); assert.equal(items[0].version, 1);
    assert.deepEqual((await self.getState()).interests, ['lofi']);
    assert.equal((await self.getConfig('reflect.last')).applied, 1);
});

test('reflection: every rule is checked in code, whatever the model says', async () => {
    const bad = [
        add({ episodes: ['S1', 'S2'] }),                                   // only 2 episodes
        add({ episodes: ['S1', 'S1', 'S1'] }),                             // the same episode three times
        add({ episodes: ['S1', 'S2', 'S99'] }),                            // an episode that does not exist
        add({ text: "Chidi makes her laugh the most.", keyword: 'chidi jokes' }),   // about a person
        add({ text: 'She loves talking about politics.', keyword: 'politics' }),   // hot-button
        add({ kind: 'preference', text: 'I grew up in Enugu and I work nights.', keyword: null }),   // invented life story
        add({ keyword: '' }),                                              // interest without a keyword
        add({ kind: 'secret', text: 'x y z w' }),                          // unknown kind
        add({ op: 'delete' }),                                             // unknown op
        add({ text: 'Call 2348012345678 for beats', keyword: 'beats' }),   // number
    ];
    const { self, refl } = refRig({ ai: jsonAi(() => ({ changes: bad })) });
    await self.setConfig('reflect.live', true);
    const r = await refl.run();
    assert.equal(r.applied.length, 0);
    assert.ok(r.rejected.length >= 8, JSON.stringify(r.rejected));
    assert.equal((await self.listIdentity()).length, 0);
});

test('reflection: three episodes from ONE chat (maybe a private DM) never become a trait she shows everywhere', async () => {
    const { self, refl } = refRig({ ai: jsonAi(() => ({ changes: [add({ episodes: ['S3', 'S6', 'S9'] })] })) });     // ids 3, 6, 9 all belong to chat 1
    await self.setConfig('reflect.live', true);
    const r = await refl.run();
    assert.equal(r.applied.length, 0);
    assert.match(r.rejected[0].why, /all from 1 chat/);
    const ok = refRig({ ai: jsonAi(() => ({ changes: [add({ episodes: ['S3', 'S4', 'S5'] })] })) });                 // chats 1, 2, 3
    await ok.self.setConfig('reflect.live', true);
    assert.equal((await ok.refl.run()).applied.length, 1);
});

test('reflection: at most 2 changes a week, counted across runs', async () => {
    const mk = (kw, eps) => add({ text: `She enjoys ${kw}.`, keyword: kw, episodes: eps });
    const { self, refl } = refRig({ ai: jsonAi(() => ({ changes: [mk('lofi', ['S1', 'S2', 'S3']), mk('banter', ['S1', 'S2', 'S3', 'S4']), mk('gaming', ['S2', 'S3', 'S4'])] })) });
    await self.setConfig('reflect.live', true);
    const r = await refl.run();
    assert.equal(r.applied.length, 2);
    assert.deepEqual(r.applied.map((x) => x.key).sort(), ['interest:banter', 'interest:lofi']);     // the best supported two
    assert.ok(r.rejected.some((x) => /weekly limit/.test(x.why)));
    const again = await refl.run();                                      // same week
    assert.equal(again.applied.length, 0);
    assert.match(again.skipped, /already used/);
    assert.equal((await self.listIdentity()).length, 2);
});

test('reflection: updating merges evidence and bumps the version; nothing new is not a change', async () => {
    const { self, refl } = refRig({ ai: jsonAi(() => ({ changes: [add({ op: 'update', key: 'interest:lofi', text: 'She really likes lofi and chill beats.', episodes: ['S3', 'S4', 'S5'] })] })) });
    await self.upsertIdentity({ key: 'interest:lofi', evidenceCount: 3, value: { kind: 'interest', text: 'She likes lofi.', keyword: 'lofi', evidence: [1, 2, 3], first_at: '2026-10-01T00:00:00.000Z', last_support: '2026-10-20T00:00:00.000Z' } });
    await self.setConfig('reflect.live', true);
    const r = await refl.run();
    assert.equal(r.applied.length, 1);
    const it = (await self.listIdentity())[0];
    assert.deepEqual(it.value.evidence.sort(), [1, 2, 3, 4, 5]);
    assert.equal(it.evidence_count, 5); assert.equal(it.version, 2);
    assert.equal(it.value.first_at, '2026-10-01T00:00:00.000Z');
    const same = refRig({ ai: jsonAi(() => ({ changes: [add({ op: 'add' })] })) });     // the interest already exists
    await same.self.upsertIdentity({ key: 'interest:lofi', evidenceCount: 3, value: { kind: 'interest', text: 'She keeps coming back to lofi music.', keyword: 'lofi', evidence: [1, 2, 3] } });
    await same.self.setConfig('reflect.live', true);
    assert.equal((await same.refl.run()).applied.length, 0);
});

test('reflection: full categories refuse new items; quiet weeks skip the model; bad model output retries', async () => {
    let calls = 0;
    const full = refRig({ ai: jsonAi(() => { calls++; return { changes: [add({ keyword: 'zzz topic' })] }; }) });
    for (let i = 0; i < 8; i++) await full.self.upsertIdentity({ key: `interest:i${i}`, evidenceCount: 3, value: { kind: 'interest', text: `t${i}`, keyword: `k${i}`, evidence: [1, 2, 3] } });
    await full.self.setConfig('reflect.live', true);
    const r = await full.refl.run();
    assert.ok(r.rejected.some((x) => /full/.test(x.why)));
    const quiet = refRig({ n: 2, ai: jsonAi(() => { calls = 100; return { changes: [] }; }) });
    assert.match((await quiet.refl.run()).skipped, /only 2 conversation/);
    assert.notEqual(calls, 100);
    const junk = refRig({ ai: { chat: async () => ({ text: 'sorry, no' }) } });
    await assert.rejects(() => junk.refl.run(), /no usable JSON/);
});

test('reflection: items fade after a long time without support; owner can drop one', async () => {
    const { self, refl, now } = refRig({ ai: jsonAi(() => ({ changes: [] })) });
    await self.upsertIdentity({ key: 'interest:old', evidenceCount: 3, value: { kind: 'interest', text: 'old thing', keyword: 'old', evidence: [1, 2, 3], last_support: new Date(now - 200 * DAY).toISOString() } });
    await self.upsertIdentity({ key: 'interest:new', evidenceCount: 3, value: { kind: 'interest', text: 'new thing', keyword: 'new', evidence: [1, 2, 3], last_support: new Date(now - 5 * DAY).toISOString() } });
    await self.setConfig('reflect.live', true);
    const r = await refl.run();
    assert.equal(r.retired.length, 1);
    assert.deepEqual((await self.listIdentity()).map((x) => x.key), ['interest:new']);
    assert.deepEqual((await self.getState()).interests, ['new']);
    assert.equal(await refl.drop('interest:new'), true);
    assert.equal(await refl.drop('interest:new'), false);
    assert.deepEqual((await self.getState()).interests, []);
});

// ── persona + prompt ────────────────────────────────────────
test('persona: tastes, mood and style reach the prompt (no numbers); defaults when nothing is stored', async () => {
    const self = createMemSelfStore();
    const t = Date.now();
    const persona = createPersona({ self, cfg, now: () => t });
    const base = await persona.get();
    assert.match(base.text, /lively and expressive/);
    assert.ok(!/\d/.test(base.text));
    assert.deepEqual(base.limits, styleLimits({}, cfg));

    await self.upsertIdentity({ key: 'interest:lofi', evidenceCount: 3, value: { kind: 'interest', text: 'likes lofi', keyword: 'lofi' } });
    await self.upsertIdentity({ key: 'opinion:x', evidenceCount: 3, value: { kind: 'opinion', text: 'Banter beats polite small talk.' } });
    await self.setConfig('style', { values: { emoji: 0, length: 1 }, changed: {} });
    await self.mergeState({ mood: 0.6, energy: 0.65, at: t });
    persona.refresh();
    const p = await persona.get();
    assert.match(p.text, /into: lofi/); assert.match(p.text, /Banter beats/); assert.match(p.text, /really good mood/);
    assert.equal(p.limits.maxEmoji, 0); assert.equal(p.limits.maxBubbles, 2);
    assert.ok(!/_log/.test(p.text));
});

test('persona: a broken database never blocks a reply', async () => {
    const self = { listIdentity: async () => { throw new Error('db down'); }, getState: async () => ({}), getConfig: async () => null };
    const persona = createPersona({ self, cfg });
    const p = await persona.get();
    assert.equal(p.text, ''); assert.equal(p.limits.maxEmoji, 2);
});

test('prompt: her block sits after the situation; core text is unchanged unless you add daily_life', () => {
    const core = { core: ['You are Ariel.', 'Be real.'], aliases: ['ariel'] };
    assert.equal(systemText(core), 'You are Ariel.\n\nBe real.');
    const rows = [{ id: 1, wa_message_id: 'W1', person_id: 7, name: 'Joel', body: 'hey', meta: {}, created_at: new Date() }];
    const ctx = buildContext({ core, rows, chat: { kind: 'dm' }, self: 'HOW YOU ARE LATELY\n- x' });
    assert.ok(ctx.user.indexOf('Where:') < ctx.user.indexOf('HOW YOU ARE LATELY'));
    assert.ok(ctx.user.indexOf('HOW YOU ARE LATELY') < ctx.user.indexOf('<chat>'));
    assert.ok(!buildContext({ core, rows, chat: { kind: 'dm' } }).user.includes('HOW YOU ARE'));
    const withLife = systemText({ ...core, daily_life: ['likes tea in the morning', 'is always a bit sleepy on Mondays'] });
    assert.match(withLife, /at most one in a whole conversation/); assert.match(withLife, /likes tea in the morning; is always a bit sleepy/);
    assert.equal(systemText({ ...core, daily_life: [] }), systemText(core));
});

// ── conversation integration ────────────────────────────────
function convRig({ aiText, persona, feedback }) {
    const rows = [{ id: 1, wa_message_id: 'W1', person_id: 7, name: 'Joel', body: 'you sound robotic', meta: {}, created_at: new Date() }];
    const store = { recentMessages: async () => rows, chatSettings: async () => ({}), latestSummaries: async () => [], getArielState: async () => ({}) };
    const sent = []; const prompts = [];
    const send = { say: async (a) => { sent.push(a); return a.bubbles.length; }, react: async () => true };
    const ai = { chat: async (req) => { prompts.push(req); return { text: aiText }; } };
    const batcher = { touch: (k, w, c, fn) => setImmediate(fn), has: () => false, cancel() {} };
    const conv = createConversation({ store, ai, core: { core: ['You are Ariel.'], aliases: ['ariel'] }, send, persona, feedback, batcher, log: (l) => { if (process.env.DBG) console.log(l); } });
    const ev = { chat: { kind: 'dm', jid: 'x@s.whatsapp.net' }, op: { ts: new Date(), waId: 'W1', body: 'you sound robotic', meta: {} } };
    return { conv, sent, prompts, fire: async () => {
        conv.onStored({ ev, out: { chatId: 1, personId: 7 } });
        for (let i = 0; i < 100 && !sent.length; i++) await new Promise((r) => setTimeout(r, 10));     // wait for the reply, not a fixed time
        await new Promise((r) => setTimeout(r, 20));
    } };
}

test('conversation: style caps are enforced on what she writes; her block is in the prompt; the remark is stored', async () => {
    const self = createMemSelfStore();
    const t = Date.now();
    await self.setConfig('style', { values: { emoji: 1, length: 1, expressiveness: 2.5 }, changed: {} });
    const persona = createPersona({ self, cfg, now: () => t });
    const feedback = createFeedback({ self, cfg });
    const r = convRig({ aiText: 'ACTION: reply\nHAHA OKAY WOW 😂😂😂\n---\nsecond one 🔥\n---\nthird\n---\nfourth', persona, feedback });
    await r.fire();
    assert.equal(r.sent.length, 1);
    const bubbles = r.sent[0].bubbles;
    assert.equal(bubbles.length, 2);                                           // length 1 -> at most 2 bubbles
    const emoji = bubbles.join(' ').match(/\p{Extended_Pictographic}/gu) || [];
    assert.equal(emoji.length, 1);                                             // emoji setting 1
    assert.equal((bubbles.join(' ').match(/\b[A-Z]{4,}\b/g) || []).length, 1); // one shouted word at most
    assert.match(r.prompts[0].messages[1].content, /How you are lately/);
    assert.equal(r.prompts[0].messages[0].content, 'You are Ariel.');          // her fixed core is untouched (cacheable)
    assert.equal(self.state.feedback.length, 1);
    assert.equal(self.state.feedback[0].kind, 'robotic');
});

test('conversation: without stage 8 modules she behaves exactly as before', async () => {
    const r = convRig({ aiText: 'ACTION: reply\nok 😂😂😂😂', persona: null, feedback: null });
    await r.fire();
    assert.equal(r.sent[0].bubbles[0].match(/\p{Extended_Pictographic}/gu).length, 2);
    assert.ok(!r.prompts[0].messages[1].content.includes('How you are lately'));
});

test('conversation: a failing feedback store never blocks the reply', async () => {
    const feedback = { observe: async () => { throw new Error('db down'); } };
    const r = convRig({ aiText: 'ACTION: reply\nfair', persona: null, feedback });
    await r.fire();
    assert.equal(r.sent.length, 1);
});

// ── scheduling ──────────────────────────────────────────────
test('jobs: the review runs daily and reflection on Sunday (Lagos), only when wired', async () => {
    const run = async (iso, handlers) => {
        const q = [];
        const maint = { enqueue: async (j) => { q.push(j.kind); return 1; }, hasKey: async () => false };
        const jobs = createJobs({ maint, cfg, handlers, now: () => Date.parse(iso) });
        await jobs.tick();
        return q;
    };
    const all = { style_review() {}, reflect() {}, consolidate() {}, segment_close() {} };
    const sun = await run('2026-11-01T05:00:00Z', all);            // Sunday 06:00 Lagos
    assert.ok(sun.includes('reflect') && sun.includes('style_review') && sun.includes('consolidate'));
    const mon = await run('2026-11-02T05:00:00Z', all);
    assert.ok(mon.includes('style_review') && !mon.includes('reflect'));
    const early = await run('2026-11-01T01:30:00Z', all);          // 02:30 Lagos: too early
    assert.ok(!early.includes('reflect') && !early.includes('style_review'));
    const old = await run('2026-11-01T05:00:00Z', { consolidate() {}, segment_close() {} });
    assert.ok(!old.includes('reflect') && !old.includes('style_review'));
});

test('summariser: the conversation vibe reaches her mood, and a mood failure never blocks the save', async () => {
    const rows = ['hey', 'how far', 'lol that was funny', 'ok see you', 'bye'].map((b, i) => ({ id: i + 1, person_id: 1 + (i % 2), name: i % 2 ? 'Amaka' : 'Joel', body: `${b} and some more words to be non-trivial`, created_at: new Date(Date.now() - (9 - i) * 60_000) }));
    const heard = [];
    const maint = {
        findOpenSegments: async () => [], segmentMessages: async () => rows, markProcessed: async () => {}, chatInfo: async () => ({ id: 1, kind: 'group' }),
        saveSegment: async () => ({ memoryIds: [] }),
    };
    const store = { findSimilar: async () => null, touchMemory: async () => {} };
    const ai = {
        chat: async () => ({ text: JSON.stringify({ summary: 'They joked around.', topics: ['jokes'], memories: [], vibe: 'playful' }) }),
        embed: async (t) => ({ vectors: t.map(() => [1, 0]) }),
    };
    const mood = { recordSegment: async (x) => { heard.push(x); } };
    await createSummariser({ maint, store, ai, cfg, mood }).summarise({ payload: { chat_id: 1, from_id: 1, to_id: 5 } });
    assert.deepEqual(heard, [{ vibe: 'playful', messages: 5 }]);
    const bad = { recordSegment: async () => { throw new Error('boom'); } };
    await createSummariser({ maint, store, ai, cfg, mood: bad }).summarise({ payload: { chat_id: 1, from_id: 1, to_id: 5 } });   // must not throw
});

// ── owner commands ──────────────────────────────────────────
import { createSelfCommands } from '../../bot/ariel/selfcmds.js';

function cmdRig(aiFn = () => ({ changes: [] })) {
    const self = createMemSelfStore();
    const now = Date.now();
    self.state.clock = () => now;
    for (let i = 1; i <= 5; i++) self.state.summaries.push({ id: i, chat_id: (i % 3) + 1, body: `lofi and banter ${i}`, topics: [], kind: 'dm', ended: new Date(now - i * DAY).toISOString() });
    const feedback = createFeedback({ self, cfg, now: () => now });
    const persona = createPersona({ self, cfg, now: () => now });
    const reflection = createReflection({ self, ai: jsonAi(aiFn), cfg, now: () => now });
    const mood = createMood({ self, now: () => now });
    return { self, cmds: createSelfCommands({ self, feedback, persona, reflection, mood }), feedback };
}

test('commands: style shows, sets by hand, rejects nonsense, resets', async () => {
    const { cmds } = cmdRig();
    assert.match(await cmds.style(''), /expressiveness 2.5\/3/);
    assert.match(await cmds.style('emoji 0'), /emoji is now 0/);
    assert.match(await cmds.style(''), /emoji 0\/3/);
    assert.match(await cmds.style('spice 3'), /unknown setting/);
    assert.match(await cmds.style('reset'), /defaults/);
    assert.match(await cmds.style(''), /emoji 2\/3/);
});

test('commands: feedback summary counts remarks and people', async () => {
    const { cmds, feedback } = cmdRig();
    assert.match(await cmds.feedback(), /nothing yet/);
    await feedback.observe({ personId: 1, body: 'you sound robotic' });
    await feedback.observe({ personId: 2, body: 'you sound robotic' });
    assert.match(await cmds.feedback(), /robotic: 2 from 2 people/);
});

test('commands: reflect is dry by default, live on request, self lists and drops', async () => {
    const { cmds, self } = cmdRig(() => ({ changes: [add()] }));
    assert.match(await cmds.self(''), /nothing yet/);
    const dry = await cmds.reflect('');
    assert.match(dry, /dry-run\): 0 applied, 1 proposed/);
    assert.equal((await self.listIdentity()).length, 0);
    assert.match(await cmds.reflect('live'), /LIVE/);
    const live = await cmds.reflect('');
    assert.match(live, /LIVE\): 1 applied/);
    const list = await cmds.self('');
    assert.match(list, /1\. interest: She keeps coming back to lofi music/); assert.match(list, /LIVE/); assert.match(list, /recent changes/);
    assert.match(await cmds.self('drop 9'), /Usage/);
    assert.match(await cmds.self('drop 1'), /Dropped/);
    assert.match(await cmds.self(''), /nothing yet/);
    assert.match(await cmds.reflect('dry'), /dry-run/);
});
