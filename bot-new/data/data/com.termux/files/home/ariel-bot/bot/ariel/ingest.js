// Ingest: resolve the sender to ONE person, find the chat, store the message.
// Knows nothing about Baileys or pg; talks to a store (store/pg.js or store/mem.js).
//
// ev = {
//   chat:   { jid, kind: 'dm' | 'group', name? },
//   sender: { ids: [rawJid, ...], pushName? },          // every id we know for this sender
//   op:     { kind: 'message', waId, ts, body, replyTo, meta, mentionJids }
//         | { kind: 'edit',    waId, ts, targetId, body }
//         | { kind: 'revoke',  waId, ts, targetId },
// }
import { buildIdentitySet, dmChatKey, normJid, identitiesOf } from './ids.js';
import { clean } from './extract.js';

export function createIngest({ store, isBot = () => false, log = () => {} }) {
    const identCache = new Map();   // identity value -> person id
    const chatCache = new Map();    // chat key -> { id, sig }
    let resolveLock = Promise.resolve();
    const queues = new Map();       // chat jid -> promise tail (keeps one chat in order)

    const counters = { stored: 0, duplicate: 0, edited: 0, deleted: 0, skipped: 0, merged: 0, created: 0 };

    // ── identity ────────────────────────────────────────────
    // Run resolution one at a time inside this process so two messages from a brand-new
    // sender can't both create a person. (Across processes the re-check below catches it.)
    function locked(fn) {
        const run = resolveLock.then(fn, fn);
        resolveLock = run.then(() => {}, () => {});
        return run;
    }

    async function resolvePerson(identities, displayName) {
        const values = identities.map((i) => i.value);
        const hit = values.map((v) => identCache.get(v));
        if (hit.every((h) => h !== undefined) && new Set(hit).size === 1) return hit[0];

        return locked(async () => {
            let result;
            for (let attempt = 0; ; attempt++) {
                try {
                    result = await store.tx((ops) => resolveInTx(ops, identities, values, displayName));
                    break;
                } catch (e) {
                    // deadlock / serialization failure when two merges cross: try once more
                    if (attempt === 0 && (e.code === '40P01' || e.code === '40001')) continue;
                    throw e;
                }
            }
            if (result.merged.length) {
                // ids moved between people: nothing cached is trustworthy any more
                identCache.clear();
                chatCache.clear();
                counters.merged += result.merged.length;
                log(`[ARIEL] merged person(s) ${result.merged.join(', ')} into ${result.personId}`);
            }
            if (result.created) counters.created++;
            for (const v of values) identCache.set(v, result.personId);
            return result.personId;
        });
    }

    async function resolveInTx(ops, identities, values, displayName) {
        let rows = await ops.identityRows(values);
        let people = [...new Set(rows.map((r) => r.person_id))].sort((a, b) => a - b);
        let created = false;

        if (!people.length) {
            const id = await ops.createPerson(displayName);
            await ops.addIdentities(id, identities);
            // Another process may have created the same person a moment ago: look again.
            rows = await ops.identityRows(values);
            people = [...new Set(rows.map((r) => r.person_id))].sort((a, b) => a - b);
            if (people.includes(id)) created = true;
            else await ops.mergePeople(people[0], id);      // we lost the race: drop our empty row
        } else {
            // Link any ids we hadn't seen to the person who already owns the rest.
            await ops.addIdentities(people[0], identities);
        }
        const keep = people[0];
        const merged = [];
        for (const other of people.slice(1)) {
            await ops.mergePeople(keep, other);             // the oldest person id wins
            merged.push(other);
        }
        return { personId: keep, merged, created };
    }

    // ── chat ────────────────────────────────────────────────
    async function resolveChat(chat, personId) {
        const key = chat.kind === 'dm' ? dmChatKey(personId) : chat.jid;
        const settings = { chat_on: true };
        if (chat.kind === 'dm') settings.send_jid = chat.jid;      // where to actually send to
        else if (chat.name) settings.name = clean(chat.name, 120);
        const sig = JSON.stringify(settings);
        const c = chatCache.get(key);
        if (c && c.sig === sig) return c.id;
        const id = await store.ensureChat({ key, kind: chat.kind, settings });
        chatCache.set(key, { id, sig });
        return id;
    }

    // ── mentions: only people we already know ────────────────
    async function mentionRefs(jids) {
        const refs = [];
        const wanted = new Map();       // identity value -> token (digits shown as @digits)
        for (const j of jids || []) {
            const n = normJid(j);
            if (!n || isBot(n)) continue;
            for (const i of identitiesOf(n)) wanted.set(i.value, n.split('@')[0]);
        }
        if (!wanted.size) return refs;
        const rows = await store.identityRows([...wanted.keys()]);
        const seen = new Set();
        for (const r of rows) {
            const token = wanted.get(r.value);
            const k = `${token}:${r.person_id}`;
            if (seen.has(k)) continue;
            seen.add(k);
            refs.push({ token, person_id: r.person_id });
        }
        return refs;
    }

    // ── main entry ──────────────────────────────────────────
    async function process(ev) {
        const { identities, dropped } = buildIdentitySet(ev.sender?.ids);
        if (dropped.length) log(`[ARIEL] ignored conflicting ids for one sender: ${dropped.join(', ')}`);
        if (!identities.length) return skip('no-sender');
        if (identities.some((i) => isBot(i.value))) return skip('bot');

        const name = clean(ev.sender?.pushName || '', 80);
        const personId = await resolvePerson(identities, name);
        const chatId = await resolveChat(ev.chat, personId);
        const op = ev.op;

        if (op.kind === 'revoke') {
            const r = await store.deleteMessage({ chatId, personId, waId: op.targetId });
            if (r.deleted) counters.deleted++;
            return { status: r.deleted ? 'deleted' : 'unchanged', personId, chatId };
        }
        if (op.kind === 'edit') {
            const r = await store.editMessage({ chatId, personId, waId: op.targetId, body: op.body });
            if (r.updated) counters.edited++;
            return { status: r.updated ? 'edited' : 'unchanged', personId, chatId };
        }

        const meta = { ...(op.meta || {}) };
        const mentions = await mentionRefs(op.mentionJids);
        if (mentions.length) meta.mentions = mentions;
        const r = await store.recordMessage({
            chatId, personId, waId: op.waId, replyTo: op.replyTo || null,
            body: op.body, meta, ts: op.ts, displayName: name,
        });
        if (r.inserted) counters.stored++; else counters.duplicate++;
        return { status: r.inserted ? 'stored' : 'duplicate', personId, chatId, message: { waId: op.waId, body: op.body, meta, ts: op.ts } };
    }

    function skip(reason) { counters.skipped++; return { status: 'skipped', reason }; }

    // Messages in one chat are handled in order; different chats run side by side.
    function handle(ev) {
        const key = ev.chat.jid;
        const tail = queues.get(key) || Promise.resolve();
        const run = tail.then(() => process(ev), () => process(ev));
        const settled = run.catch(() => {});
        queues.set(key, settled);
        settled.then(() => { if (queues.get(key) === settled) queues.delete(key); });
        return run;
    }

    // Everything a restart or a manual re-link would have to forget.
    function forget() { identCache.clear(); chatCache.clear(); }

    return { handle, forget, counters };
}
