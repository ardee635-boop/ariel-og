#!/usr/bin/env node
// Runs the real ingest code against your real Supabase, inside a transaction that is
// ALWAYS rolled back (nothing is saved). It proves the SQL itself works: identity
// linking, the person merge, DM chat folding, dedupe, edit and delete.
//   node --env-file=.env scripts/ariel-ingest-check.js
import assert from 'node:assert/strict';
import { createIngest } from '../bot/ariel/ingest.js';
import { createPgStore } from '../bot/ariel/store/pg.js';

const db = await import('../bot/ariel/db.js');
const client = await db.getPool().connect();
let n = 0;
const ok = (m) => console.log(`✓ ${m}`);

try {
    await client.query('begin');
    await client.query('set local search_path = ariel, public, extensions');

    // One connection, nested "transactions" become savepoints, so the outer rollback undoes everything.
    const q = (t, p) => client.query(t, p);
    const store = createPgStore({
        query: q,
        tx: async (fn) => {
            const sp = `sp_${++n}`;
            await client.query(`savepoint ${sp}`);
            try { const r = await fn(client); await client.query(`release savepoint ${sp}`); return r; }
            catch (e) { await client.query(`rollback to savepoint ${sp}`); throw e; }
        },
    });
    const ingest = createIngest({ store, isBot: () => false, log: (l) => console.log('  ', l) });

    const LID = 'ingestcheck-1@lid';
    const PN = '99900001111@s.whatsapp.net';
    const GRP = 'ingestcheck-group@g.us';
    const msg = (chat, ids, waId, body, extra = {}) => ({
        chat, sender: { ids, pushName: 'Check Person' },
        op: { kind: 'message', waId, ts: new Date(), body, replyTo: null, meta: { type: 'text' }, mentionJids: [], ...extra },
    });
    const dm = (jid) => ({ jid, kind: 'dm' });
    const group = { jid: GRP, kind: 'group', name: 'Ingest check group' };

    // 1. the same human, first as a @lid DM and then as a phone DM: two people for now
    assert.equal((await ingest.handle(msg(dm(LID), [LID], 'ic-1', 'dm via lid'))).status, 'stored');
    assert.equal((await ingest.handle(msg(dm(PN), [PN], 'ic-2', 'dm via phone'))).status, 'stored');
    let r = await client.query(`select count(distinct person_id)::int as n from ariel.person_identities where value = any($1)`, [[LID, PN, '99900001111']]);
    assert.equal(r.rows[0].n, 2);
    ok('lid and phone ids start as two people (nothing links them yet)');

    // 2. a group message carries both ids -> they are merged into one
    assert.equal((await ingest.handle(msg(group, [LID, PN], 'ic-3', 'group hello'))).status, 'stored');
    r = await client.query(`select count(distinct person_id)::int as n from ariel.person_identities where value = any($1)`, [[LID, PN, '99900001111']]);
    assert.equal(r.rows[0].n, 1);
    ok('a message carrying both ids merged the two people');

    // 3. one DM chat, holding both DM messages; counts add up
    r = await client.query(`select count(distinct m.chat_id)::int as chats, count(*)::int as msgs
                              from ariel.messages m where m.wa_message_id in ('ic-1', 'ic-2')`);
    assert.deepEqual([r.rows[0].chats, r.rows[0].msgs], [1, 2]);
    r = await client.query(`select cm.msg_count::int as c from ariel.chat_members cm
                              join ariel.messages m on m.chat_id = cm.chat_id and m.person_id = cm.person_id
                             where m.wa_message_id = 'ic-1' limit 1`);
    assert.equal(r.rows[0].c, 2);
    ok('one DM chat, both messages in it, member count 2');

    // 4. the same WhatsApp message again is ignored
    ingest.forget();
    assert.equal((await ingest.handle(msg(group, [LID, PN], 'ic-3', 'group hello'))).status, 'duplicate');
    r = await client.query(`select count(*)::int as n from ariel.messages where wa_message_id = 'ic-3'`);
    assert.equal(r.rows[0].n, 1);
    ok('a repeated WhatsApp message id is stored once');

    // 5. edit, then delete-for-everyone
    await ingest.handle({ chat: group, sender: { ids: [PN] }, op: { kind: 'edit', waId: 'ic-e', ts: new Date(), targetId: 'ic-3', body: 'group hello (edited)' } });
    r = await client.query(`select body, meta->>'edited' as edited from ariel.messages where wa_message_id = 'ic-3'`);
    assert.deepEqual([r.rows[0].body, r.rows[0].edited], ['group hello (edited)', 'true']);
    ok('an edit replaced the stored text');
    await ingest.handle({ chat: group, sender: { ids: [PN] }, op: { kind: 'revoke', waId: 'ic-r', ts: new Date(), targetId: 'ic-3' } });
    r = await client.query(`select count(*)::int as n from ariel.messages where wa_message_id = 'ic-3'`);
    assert.equal(r.rows[0].n, 0);
    ok('delete-for-everyone removed the message');

    // 6. the group row carries its name and the on-switch
    r = await client.query(`select settings from ariel.chats where wa_jid = $1`, [GRP]);
    assert.equal(r.rows[0].settings.chat_on, true);
    assert.equal(r.rows[0].settings.name, 'Ingest check group');
    ok('chat settings written (chat_on, name)');

    console.log('\n✓ ingest checks passed (nothing was saved)');
} catch (e) {
    console.error('\n✗', e.message);
    process.exitCode = 1;
} finally {
    await client.query('rollback').catch(() => {});
    client.release();
    await db.endPool();
}
