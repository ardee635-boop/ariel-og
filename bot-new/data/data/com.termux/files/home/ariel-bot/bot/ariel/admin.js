// `.ariel status` / `.ariel people` — owner-only checks you can run from your phone.
// Shows names and counts only, never phone numbers.

const ago = (d) => {
    if (!d) return 'never';
    const s = Math.max(0, Math.round((Date.now() - new Date(d).getTime()) / 1000));
    if (s < 90) return `${s}s ago`;
    if (s < 5400) return `${Math.round(s / 60)} min ago`;
    if (s < 129600) return `${Math.round(s / 3600)} h ago`;
    return `${Math.round(s / 86400)} d ago`;
};

export function createAdmin({ query, hookStatus, counters, enabledInfo = () => ({}), extraLines = () => [], commands = {} }) {
    async function status() {
        const r = await query(
            `select
               (select count(*) from ariel.people) as people,
               (select count(*) from ariel.person_identities) as identities,
               (select count(*) from ariel.people p
                 where exists (select 1 from ariel.person_identities i where i.person_id = p.id and i.kind = 'lid')
                   and exists (select 1 from ariel.person_identities i where i.person_id = p.id and i.kind = 'phone')) as linked,
               (select count(*) from ariel.chats where kind = 'dm') as dms,
               (select count(*) from ariel.chats where kind = 'group') as groups,
               (select count(*) from ariel.messages) as msgs,
               (select count(*) from ariel.messages where created_at > now() - interval '24 hours') as msgs24,
               (select max(created_at) from ariel.messages) as latest`);
        const x = r.rows[0];
        const h = hookStatus;
        const e = enabledInfo();
        const lines = [
            '🧠 *Ariel — ingest, chat, memory (stage 5)*',
            `chats: ${x.groups} groups, ${x.dms} DMs`,
            `people: ${x.people} (${x.identities} ids, ${x.linked} seen as both @lid and phone)`,
            `messages stored: ${x.msgs} (${x.msgs24} in the last 24 h), latest ${ago(x.latest)}`,
            `since boot: ${counters.stored} stored, ${counters.duplicate} repeats, ${counters.edited} edits, ${counters.deleted} deletes, ${counters.merged} merges`,
            `errors since boot: ${h.errors}${h.lastError ? ` (last: ${h.lastError})` : ''}`,
        ];
        if (h.pausedUntil > Date.now()) lines.push(`⏸ ingest paused for ${Math.ceil((h.pausedUntil - Date.now()) / 1000)} s`);
        lines.push(...(await extraLines()));
        if (e.dmOn !== undefined) lines.push(`DM chat: ${e.dmOn ? 'on' : 'off'} · groups on: ${e.groupsOn ?? '?'}`);
        return lines.join('\n');
    }

    async function people() {
        const r = await query(
            `select p.id,
                    coalesce(nullif(p.display_name, ''), '(no name)') as name,
                    (select count(*) from ariel.person_identities i where i.person_id = p.id) as ids,
                    coalesce((select string_agg(distinct i.kind, '+' order by i.kind)
                                from ariel.person_identities i where i.person_id = p.id), '') as kinds,
                    coalesce((select sum(m.msg_count) from ariel.chat_members m where m.person_id = p.id), 0) as msgs
               from ariel.people p
              order by msgs desc, p.id
              limit 10`);
        if (!r.rows.length) return '🧠 No people stored yet.';
        const rows = r.rows.map((p) => `• ${p.name} — ${p.msgs} msgs, ${p.ids} id${p.ids === 1 ? '' : 's'} (${p.kinds})`);
        return ['🧠 *Top people*', ...rows].join('\n');
    }

    // Returns the reply text, or null when the text isn't an `.ariel` command.
    async function handle(text, ctx = {}) {
        const t = String(text || '').trim().toLowerCase().replace(/\s+/g, ' ');
        if (t !== '.ariel' && !t.startsWith('.ariel ')) return null;
        const sub = t.slice(6).trim();
        if (sub === '' || sub === 'status') return status();
        if (sub === 'people') return people();
        const [cmd, ...rest] = sub.split(' ');
        if (commands[cmd]) return commands[cmd](rest.join(' '), ctx);
        return `🧠 _Usage: .ariel status | people${Object.keys(commands).map((c) => ` | ${c}`).join('')}_`;
    }

    return { handle };
}
