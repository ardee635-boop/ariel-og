// Stage 2 tests: ids, message extraction, identity resolution, ingest, the hook.
// Run:  node --test tests/js/ariel_stage2_test.mjs      (no database, no network, no WhatsApp)
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { normJid, phoneOf, identitiesOf, buildIdentitySet, dmChatKey } from '../../bot/ariel/ids.js';
import { extractMessage, clean } from '../../bot/ariel/extract.js';
import { createMemStore } from '../../bot/ariel/store/mem.js';
import { createPgStore } from '../../bot/ariel/store/pg.js';
import { createIngest } from '../../bot/ariel/ingest.js';
import { createHook } from '../../bot/ariel/hook.js';
import { createAdmin } from '../../bot/ariel/admin.js';
import { renderSql } from '../../bot/ariel/sqlutil.js';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const BOT = '2348081915376';
const BOT_JID = `${BOT}@s.whatsapp.net`;
const isBot = (j) => j === BOT || normJid(j) === BOT_JID || normJid(j) === '999@lid';

const JOEL_PN = '2348101845905@s.whatsapp.net';
const JOEL_LID = '111222333@lid';
const AMA_PN = '2347073047260@s.whatsapp.net';
const GROUP = '120363000000000001@g.us';

let n = 0;
const txt = (text, extra = {}) => ({
    key: { id: `M${++n}`, remoteJid: GROUP, participant: JOEL_PN, fromMe: false, ...extra.key },
    messageTimestamp: 1_790_000_000 + n,
    pushName: 'Joel',
    message: { conversation: text },
    ...extra.top,
});
const dmMsg = (from, text, id) => ({
    key: { id: id || `D${++n}`, remoteJid: from, fromMe: false },
    messageTimestamp: 1_790_000_000 + n, pushName: 'Joel', message: { conversation: text },
});

function rig({ enabled = () => true, prefix = async () => null, alt = async () => [], parts = async () => [] } = {}) {
    const store = createMemStore();
    const logs = [];
    const ingest = createIngest({ store, isBot, log: (l) => logs.push(l) });
    const hook = createHook({ ingest, isEnabled: enabled, isBot, getPrefix: prefix, altIds: alt, groupParticipants: parts, log: (l) => logs.push(l) });
    return { store, ingest, hook, logs, run: (msg) => hook.run({}, msg) };
}

// ── ids ─────────────────────────────────────────────────────
test('ids: device suffixes go, kinds are told apart, junk is refused', () => {
    assert.equal(normJid('2348101845905:12@s.whatsapp.net'), JOEL_PN);
    assert.equal(normJid('111222333:5@lid'), JOEL_LID);
    assert.equal(normJid('nonsense'), null);
    assert.equal(phoneOf(JOEL_PN), '2348101845905');
    assert.equal(phoneOf(JOEL_LID), null);
    assert.deepEqual(identitiesOf(JOEL_PN).map((i) => i.kind), ['jid', 'phone']);
    assert.deepEqual(identitiesOf(JOEL_LID).map((i) => i.kind), ['lid']);
    assert.deepEqual(identitiesOf(GROUP), []);
    assert.equal(dmChatKey(7), 'dm:7');
});

test('ids: one event never glues two phone numbers or two lids to one person', () => {
    const ok = buildIdentitySet([JOEL_LID, JOEL_PN, `${JOEL_PN.split('@')[0]}:3@s.whatsapp.net`]);
    assert.equal(ok.identities.length, 3);            // lid + jid + phone, device id deduped
    assert.deepEqual(ok.dropped, []);
    const bad = buildIdentitySet([JOEL_PN, AMA_PN, JOEL_LID, '999@lid']);
    assert.deepEqual(bad.identities.map((i) => i.value).sort(), ['111222333@lid', '2348101845905', JOEL_PN].sort());
    assert.deepEqual(bad.dropped.sort(), [AMA_PN, '999@lid'].sort());
});

// ── extraction ──────────────────────────────────────────────
test('extract: plain text, quote of Ariel, tag of Ariel, forward flag', () => {
    const e = extractMessage({
        key: { id: 'A1' }, messageTimestamp: 1_790_000_000,
        message: { extendedTextMessage: { text: 'abeg explain', contextInfo: {
            stanzaId: 'Q1', participant: `${BOT}:4@s.whatsapp.net`, mentionedJid: [BOT_JID, AMA_PN], isForwarded: true,
            quotedMessage: { conversation: 'the earlier line' } } } },
    }, { isBot });
    assert.equal(e.kind, 'message');
    assert.equal(e.body, 'abeg explain');
    assert.equal(e.replyTo, 'Q1');
    assert.equal(e.meta.quoted_ariel, true);
    assert.equal(e.meta.mentioned_ariel, true);
    assert.equal(e.meta.forwarded, true);
    assert.equal(e.meta.quoted_text, 'the earlier line');
    assert.equal(e.ts.getTime(), 1_790_000_000_000);
});

test('extract: media becomes a short label (+ caption), wrapped messages are opened', () => {
    const t = (message) => extractMessage({ key: { id: 'x' }, message }, { isBot });
    assert.equal(t({ imageMessage: { caption: 'my cat' } }).body, '[image] my cat');
    assert.equal(t({ imageMessage: {} }).body, '[image]');
    assert.equal(t({ stickerMessage: {} }).body, '[sticker]');
    assert.equal(t({ audioMessage: { ptt: true } }).body, '[voice]');
    assert.equal(t({ videoMessage: { gifPlayback: true } }).body, '[gif]');
    assert.equal(t({ ephemeralMessage: { message: { conversation: 'disappearing hello' } } }).body, 'disappearing hello');
    assert.equal(t({ viewOnceMessageV2: { message: { imageMessage: { caption: 'once' } } } }).body, '[image] once');
});

test('extract: reactions and key shares are skipped; edits and deletes are understood', () => {
    const t = (message) => extractMessage({ key: { id: 'x' }, message }, { isBot });
    assert.equal(t({ reactionMessage: { text: '😂' } }).skip, true);
    assert.equal(t({ senderKeyDistributionMessage: {} }).skip, true);
    assert.equal(t({}).skip, true);
    const del = t({ protocolMessage: { type: 0, key: { id: 'GONE' } } });
    assert.deepEqual([del.kind, del.targetId], ['revoke', 'GONE']);
    const edit = t({ protocolMessage: { type: 14, key: { id: 'OLD' }, editedMessage: { conversation: 'fixed text' } } });
    assert.deepEqual([edit.kind, edit.targetId, edit.body], ['edit', 'OLD', 'fixed text']);
    const enumEdit = t({ protocolMessage: { type: 'MESSAGE_EDIT', key: { id: 'OLD' }, editedMessage: { conversation: 'again' } } });
    assert.equal(enumEdit.kind, 'edit');
    assert.equal(t({ protocolMessage: { type: 3 } }).skip, true);   // e.g. ephemeral setting
});

test('extract: NUL bytes and lone surrogates are removed so Postgres accepts the text', () => {
    assert.equal(clean('a\u0000b'), 'ab');
    assert.doesNotMatch(clean('x\ud800y'), /\ud800/);
    assert.equal(clean('  hi \r\n there  '), 'hi \n there');
    assert.equal(clean('z'.repeat(5000)).length, 4000);
});

// ── identity resolution ─────────────────────────────────────
test('identity: the same human as @lid and as a phone id ends up as ONE person', async () => {
    const r = rig({ parts: async () => [{ id: JOEL_LID, lid: JOEL_LID, phoneNumber: JOEL_PN }] });
    // Seen first only as a lid DM, then as a phone DM: nothing proves they are one human yet.
    await r.run(dmMsg(JOEL_LID, 'a', 'x1'));
    await r.run(dmMsg(JOEL_PN, 'b', 'x2'));
    assert.equal(r.store.state.people.size, 2);
    // A group message from the lid: the member list supplies the phone, which proves it.
    await r.run(txt('both ids here', { key: { participant: JOEL_LID } }));
    assert.equal(r.store.state.people.size, 1, 'merged into one person');
    assert.equal(r.store.state.chats.size, 2, 'one DM chat (not two) + the group');
    const dm = [...r.store.state.chats.values()].find((c) => c.kind === 'dm');
    assert.match(dm.key, /^dm:\d+$/);
    const dmMsgs = r.store.state.messages.filter((m) => m.chat_id === dm.id);
    assert.deepEqual(dmMsgs.map((m) => m.body).sort(), ['a', 'b']);
});

test('identity: the oldest person id wins a merge, and every message follows it', async () => {
    const r = rig({ parts: async () => [{ id: JOEL_LID, lid: JOEL_LID, phoneNumber: JOEL_PN }] });
    await r.run(dmMsg(JOEL_LID, 'one', 'a'));
    await r.run(dmMsg(JOEL_PN, 'two', 'b'));
    const ids = [...r.store.state.people.keys()].sort((x, y) => x - y);
    await r.run(txt('three', { key: { participant: JOEL_LID } }));
    assert.deepEqual([...r.store.state.people.keys()], [ids[0]]);
    assert.ok(r.store.state.messages.every((m) => m.person_id === ids[0]));
    assert.ok(r.logs.some((l) => /merged person\(s\) \d+ into \d+/.test(l)));
    const mem = [...r.store.state.members.values()];
    assert.equal(mem.reduce((s, m) => s + m.msg_count, 0), 3);          // counts survive the merge
});

test('identity: a phone number that disagrees inside one event cannot merge two real people', async () => {
    const r = rig({ alt: async (_s, raw) => (raw === JOEL_PN ? [AMA_PN] : []) });   // bad data: Joel "is also" Ama
    await r.run(txt('hi'));
    assert.equal(r.store.state.people.size, 1);
    assert.ok(r.logs.some((l) => /conflicting ids/.test(l)));
    const ids = [...r.store.state.identities.keys()];
    assert.ok(!ids.includes('2347073047260'));
});

test('identity: Ariel herself never becomes a person (her phone, her lid, a tag of her)', async () => {
    const r = rig();
    await r.run(txt('x', { key: { participant: BOT_JID } }));
    await r.run(txt('y', { key: { participant: '999@lid' } }));
    assert.equal(r.store.state.people.size, 0);
    await r.run(txt('hey @bot', { top: { message: { extendedTextMessage: { text: 'hey', contextInfo: { mentionedJid: [BOT_JID] } } } } }));
    assert.equal(r.store.state.people.size, 1);
    assert.equal(r.store.state.messages[0].meta.mentioned_ariel, true);
    assert.equal(r.store.state.messages[0].meta.mentions, undefined, 'she is not listed as a mentioned person');
});

test('identity: two new messages from the same new sender at once create one person', async () => {
    const r = rig();
    await Promise.all([
        r.run(txt('first', { key: { participant: AMA_PN } })),
        r.run(txt('second', { key: { participant: AMA_PN } })),
        r.run(dmMsg(AMA_PN, 'dm too', 'D-ama')),
    ]);
    assert.equal(r.store.state.people.size, 1);
    assert.equal(r.store.state.messages.length, 3);
});

test('identity: a lost create-race leaves no empty duplicate person behind', async () => {
    const store = createMemStore();
    const real = store.addIdentities;
    // Simulate another process winning: right after we create our person, it claims the ids.
    store.addIdentities = async (pid, ids) => {
        if (!store.state.identities.size) {
            const other = await store.createPerson('other');
            await real(other, ids);
        }
        return real(pid, ids);
    };
    const ingest = createIngest({ store, isBot });
    const out = await ingest.handle({
        chat: { jid: GROUP, kind: 'group' }, sender: { ids: [JOEL_PN], pushName: 'Joel' },
        op: { kind: 'message', waId: 'R1', ts: new Date(), body: 'hi', meta: {} },
    });
    assert.equal(out.status, 'stored');
    assert.equal(store.state.people.size, 1);
});

test('identity: a failed merge rolls everything back (nothing half-linked)', async () => {
    const store = createMemStore();
    const ingest = createIngest({ store, isBot });
    const base = { chat: { jid: GROUP, kind: 'group' }, op: { kind: 'message', ts: new Date(), body: 'hi', meta: {} } };
    await ingest.handle({ ...base, sender: { ids: [JOEL_LID] }, op: { ...base.op, waId: 'a' } });
    await ingest.handle({ ...base, sender: { ids: [JOEL_PN] }, op: { ...base.op, waId: 'b' } });
    ingest.forget();
    const real = store.mergePeople;
    store.mergePeople = async () => { throw new Error('boom'); };
    await assert.rejects(ingest.handle({ ...base, sender: { ids: [JOEL_LID, JOEL_PN] }, op: { ...base.op, waId: 'c' } }), /boom/);
    store.mergePeople = real;
    assert.equal(store.state.people.size, 2);
    assert.equal(store.state.messages.length, 2);
});

// ── ingest: what gets stored ────────────────────────────────
test('ingest: stores the message with author, chat, reply-to and meta; repeats are ignored', async () => {
    const r = rig();
    const m = txt('hello world', { top: { message: { extendedTextMessage: { text: 'hello world', contextInfo: { stanzaId: 'PARENT' } } } } });
    const a = await r.run(m);
    const b = await r.run(m);                           // WhatsApp delivers the same message twice
    assert.equal(a.status, 'stored');
    assert.equal(b.status, 'duplicate');
    assert.equal(r.store.state.messages.length, 1);
    const row = r.store.state.messages[0];
    assert.equal(row.body, 'hello world');
    assert.equal(row.reply_to, 'PARENT');
    assert.equal(row.created_at.getTime(), m.messageTimestamp * 1000);
    assert.equal([...r.store.state.members.values()][0].msg_count, 1);
    assert.equal(r.store.state.people.get(row.person_id).display_name, 'Joel');
});

test('ingest: mentions are linked to people she already knows, strangers are not created', async () => {
    const r = rig();
    await r.run(txt('i am here', { key: { participant: AMA_PN }, top: { pushName: 'Ama' } }));
    await r.run(txt('hi @ama and @someone', { top: { message: { extendedTextMessage: {
        text: 'hi @2347073047260 and @2349999999999', contextInfo: { mentionedJid: [AMA_PN, '2349999999999@s.whatsapp.net'] } } } } }));
    assert.equal(r.store.state.people.size, 2, 'the stranger was not turned into a person');
    const row = r.store.state.messages.at(-1);
    assert.equal(row.meta.mentions.length, 1);
    assert.equal(row.meta.mentions[0].token, '2347073047260');
});

test('ingest: edit replaces the stored text; delete-for-everyone removes it; only the author can', async () => {
    const r = rig();
    await r.run(txt('teh text', { key: { id: 'E1' } }));
    await r.run({ key: { id: 'P1', remoteJid: GROUP, participant: JOEL_PN }, message: { protocolMessage: { type: 14, key: { id: 'E1' }, editedMessage: { conversation: 'the text' } } } });
    assert.equal(r.store.state.messages[0].body, 'the text');
    assert.equal(r.store.state.messages[0].meta.edited, true);
    // someone else tries to delete Joel's message
    await r.run({ key: { id: 'P2', remoteJid: GROUP, participant: AMA_PN }, pushName: 'Ama', message: { protocolMessage: { type: 0, key: { id: 'E1' } } } });
    assert.equal(r.store.state.messages.length, 1);
    await r.run({ key: { id: 'P3', remoteJid: GROUP, participant: JOEL_PN }, message: { protocolMessage: { type: 0, key: { id: 'E1' } } } });
    assert.equal(r.store.state.messages.length, 0);
});

test('ingest: one chat is kept in order even when the database answers at different speeds', async () => {
    const r = rig();
    const real = r.store.recordMessage;
    r.store.recordMessage = async (a) => { await new Promise((ok) => setTimeout(ok, a.body === 'one' ? 30 : 1)); return real(a); };
    await Promise.all(['one', 'two', 'three'].map((t) => r.run(txt(t))));
    assert.deepEqual(r.store.state.messages.map((m) => m.body), ['one', 'two', 'three']);
});

test('ingest: after the first message the steady state is a single statement per message', async () => {
    const r = rig();
    await r.run(txt('warm up'));
    const before = r.store.state.calls;
    await r.run(txt('second'));
    await r.run(txt('third'));
    assert.equal(r.store.state.calls - before, 2);
});

// ── the hook ────────────────────────────────────────────────
test('hook: chats that are switched off store nothing, and nothing is even looked up', async () => {
    let looked = 0;
    const r = rig({ enabled: () => false, alt: async () => { looked++; return []; } });
    const out = await r.run(txt('private'));
    assert.deepEqual([out.status, out.reason], ['skipped', 'chat-off']);
    assert.equal(r.store.state.messages.length, 0);
    assert.equal(looked, 0);
});

test('hook: the switches decide per chat and per kind (DM vs group)', async () => {
    const r = rig({ enabled: (jid, isDM) => (isDM ? false : jid === GROUP) });
    await r.run(txt('in group'));
    await r.run(dmMsg(JOEL_PN, 'in dm'));
    await r.run(txt('other group', { key: { remoteJid: '120363999@g.us' } }));
    assert.deepEqual(r.store.state.messages.map((m) => m.body), ['in group']);
});

test('hook: commands (default "." or the group\'s own prefix) never reach Ariel', async () => {
    const r = rig();
    await r.run(txt('.rpg attack'));
    await r.run(txt('.'));
    await r.run(dmMsg(JOEL_PN, '.hug @x'));
    await r.run(txt('normal words'));
    assert.deepEqual(r.store.state.messages.map((m) => m.body), ['normal words']);

    const r2 = rig({ prefix: async () => '!' });
    await r2.run(txt('!rpg attack'));
    await r2.run(txt('.not a command here'));          // with a custom prefix "." is just a character
    await r2.run({ ...txt('x'), message: { imageMessage: { caption: '!sticker' } } });   // captions count too
    assert.deepEqual(r2.store.state.messages.map((m) => m.body), ['.not a command here']);
});

test('hook: Ariel\'s own sends, other chat types and empty messages are ignored', async () => {
    const r = rig();
    assert.equal((await r.run(txt('mine', { key: { fromMe: true } }))).status, 'skipped');
    assert.equal((await r.run(txt('status', { key: { remoteJid: 'status@broadcast' } }))).reason, 'not-a-chat');
    assert.equal((await r.run({ key: { id: 'z', remoteJid: GROUP } })).reason, 'self-or-empty');
    assert.equal(r.store.state.messages.length, 0);
});

test('hook: a group sender who only shows as @lid is matched through the member list (and a failing lookup is harmless)', async () => {
    const r = rig({ parts: async () => [{ id: AMA_PN, lid: '55566677@lid' }, { id: JOEL_LID, lid: JOEL_LID, phoneNumber: JOEL_PN }] });
    await r.run(txt('from lid', { key: { participant: '55566677@lid' } }));
    assert.ok(r.store.state.identities.has(AMA_PN), 'phone found through the participant list');
    const bad = rig({ parts: async () => { throw new Error('rate limited'); } });
    const out = await bad.run(txt('still stored', { key: { participant: '77@lid' } }));
    assert.equal(out.status, 'stored');
});

test('hook: DM that arrives as @lid uses the alternate phone id Baileys provides', async () => {
    const r = rig();
    const m = dmMsg(JOEL_LID, 'hi', 'alt1');
    m.key.remoteJidAlt = JOEL_PN;
    await r.run(m);
    const dm = [...r.store.state.chats.values()][0];
    assert.equal(dm.settings.send_jid, JOEL_LID, 'replies go to the id the message came from');
    assert.deepEqual([...r.store.state.identities.keys()].sort(), [JOEL_LID, JOEL_PN, '2348101845905'].sort());
});

test('hook: database trouble never throws, pauses itself, and says how to fix a missing schema', async () => {
    let t = 1_000_000;
    const store = createMemStore();
    store.tx = async () => { throw new Error('relation "ariel.person_identities" does not exist'); };
    const logs = [];
    const ingest = createIngest({ store, isBot, log: (l) => logs.push(l) });
    const hook = createHook({ ingest, isEnabled: () => true, isBot, getPrefix: async () => null, altIds: async () => [], groupParticipants: async () => [], log: (l) => logs.push(l), now: () => t });
    const out = await hook.run({}, txt('hello'));
    assert.equal(out.status, 'error');
    assert.match(logs.join('\n'), /ariel-migrate/);
    assert.equal((await hook.run({}, txt('again'))).reason, 'paused');
    t += 5 * 60_000 + 1;
    assert.equal((await hook.run({}, txt('later'))).status, 'error', 'tries again after the pause');
    assert.equal(hook.status.errors, 2);
});

// ── admin command ───────────────────────────────────────────
test('admin: .ariel status / people answer, other text is not theirs, no phone numbers shown', async () => {
    const seen = [];
    const query = async (sql) => {
        seen.push(sql);
        if (/from ariel\.people p\s+order by/.test(sql)) return { rows: [{ id: 1, name: 'Joel', ids: 3, kinds: 'jid+lid+phone', msgs: 12 }] };
        return { rows: [{ people: 4, identities: 9, linked: 2, dms: 1, groups: 2, msgs: 100, msgs24: 30, latest: new Date() }] };
    };
    const a = createAdmin({ query, hookStatus: { errors: 0, lastError: null, pausedUntil: 0 }, counters: { stored: 5, duplicate: 1, edited: 0, deleted: 0, merged: 1 }, enabledInfo: () => ({ dmOn: true, groupsOn: 2 }) });
    assert.match(await a.handle('.ariel status'), /4 \(9 ids, 2 seen as both/);
    assert.match(await a.handle('.ariel'), /ingest/);
    const people = await a.handle('.ARIEL   people');
    assert.match(people, /Joel — 12 msgs, 3 ids \(jid\+lid\+phone\)/);
    assert.doesNotMatch(people, /\d{9,}/);
    assert.match(await a.handle('.ariel wat'), /Usage/);
    assert.equal(await a.handle('.arielstatus'), null);
    assert.equal(await a.handle('hello ariel'), null);
});

// ── SQL: placeholders match, schema pieces exist ────────────
test('pg store: every statement has exactly as many parameters as placeholders', async () => {
    const calls = [];
    const query = async (text, params) => {
        calls.push({ text, params });
        const need = Math.max(0, ...[...text.matchAll(/\$(\d+)/g)].map((m) => Number(m[1])));
        assert.equal(params.length, need, `placeholder/param mismatch in:\n${text}`);
        return { rows: [{ id: 1, inserted: 1, person_id: 1, value: 'x' }] };
    };
    const store = createPgStore({ query, tx: async (fn) => fn({ query }) });
    await store.identityRows(['a']);
    await store.createPerson('n');
    await store.addIdentities(1, [{ kind: 'lid', value: 'a@lid' }]);
    await store.mergePeople(1, 2);
    await store.ensureChat({ key: 'k', kind: 'group', settings: { chat_on: true } });
    await store.recordMessage({ chatId: 1, personId: 1, waId: 'w', replyTo: null, body: 'b', meta: {}, ts: new Date(), displayName: 'x' });
    await store.editMessage({ chatId: 1, personId: 1, waId: 'w', body: 'b' });
    await store.deleteMessage({ chatId: 1, personId: 1, waId: 'w' });
    await store.setChatEnabled('g@g.us', 'group', true);
    await store.tx(async (ops) => { await ops.identityRows(['a']); });
    assert.ok(calls.length >= 10);
    assert.ok(calls.every((c) => !/\bschema\b|public\./.test(c.text)), 'always schema-qualified as ariel.*');
});

test('sql 002: adds messages.meta and merge_people, touches every table that points at a person', () => {
    const sql = renderSql(fs.readFileSync(path.join(ROOT, 'bot/ariel/sql/002_ingest.sql'), 'utf8'));
    assert.match(sql, /add column if not exists meta jsonb/);
    assert.match(sql, /create or replace function ariel\.merge_people/);
    for (const t of ['person_identities', 'chat_members', 'messages', 'memories', 'initiatives', 'feedback_signals', 'person_state', 'relationships', 'summaries']) {
        assert.match(sql, new RegExp(`ariel\\.${t}`), `merge_people does not mention ${t}`);
    }
    // every table with a person reference in the schema must be handled by the merge
    const schema = fs.readFileSync(path.join(ROOT, 'bot/ariel/sql/001_schema.sql'), 'utf8');
    const tablesWithPerson = [...schema.matchAll(/create table if not exists ariel\.(\w+) \(([\s\S]*?)\n\);/g)]
        .filter(([, , body]) => /references ariel\.people/.test(body)).map(([, name]) => name);
    for (const t of tablesWithPerson) assert.match(sql, new RegExp(`ariel\\.${t}`), `schema has ${t}.person_id but merge_people ignores it`);
    assert.equal(sql.includes('{{'), false);
});

test('check.sql covers the merge, and is limited to rows it creates itself', () => {
    const sql = fs.readFileSync(path.join(ROOT, 'bot/ariel/sql/check.sql'), 'utf8');
    assert.match(sql, /ariel merge checks passed/);
    assert.match(sql, /ariel privacy checks passed/);
    assert.match(sql, /MERGE check/);
});
