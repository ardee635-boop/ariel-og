-- Run by `scripts/ariel-migrate.js --check` inside a transaction that is
-- ALWAYS rolled back. Raises an exception if a privacy rule is broken.
set local search_path = ariel, public, extensions;

do $$
declare
  a bigint; b bigint;
  dm_a bigint; grp bigint; grp2 bigint;
  n integer;
begin
  insert into ariel.people (display_name) values ('check-A') returning id into a;
  insert into ariel.people (display_name) values ('check-B') returning id into b;
  insert into ariel.chats (kind, wa_jid) values ('dm',    'check-dm-a')  returning id into dm_a;
  insert into ariel.chats (kind, wa_jid) values ('group', 'check-grp')   returning id into grp;
  insert into ariel.chats (kind, wa_jid) values ('group', 'check-grp2')  returning id into grp2;
  insert into ariel.chat_members (chat_id, person_id) values (dm_a, a), (grp, a), (grp, b), (grp2, b);

  insert into ariel.memories (scope, person_id, chat_id, visibility, kind, content, importance) values
    ('person', a,    dm_a, 'private',  'fact', 'A said this in a DM',        2),
    ('person', a,    grp,  'group_ok', 'fact', 'A said this in the group',   2),
    ('person', b,    grp,  'private',  'fact', 'B private fact',             2),
    ('group',  null, grp,  'group_ok', 'joke', 'inside joke of group one',   2),
    ('group',  null, grp2, 'group_ok', 'joke', 'inside joke of group two',   2),
    ('global', null, null, 'group_ok', 'rule', 'global rule for everyone',   2);
  update ariel.memories set expires_at = now() - interval '1 day' where content = 'inside joke of group two';

  -- DM with A: A's private + group_ok facts, global; never B's, never group memories.
  select count(*) into n from ariel.retrieve_memories(dm_a, array[a], null, null, 50);
  if n <> 3 then raise exception 'DM check: expected 3 rows, got %', n; end if;
  if exists (select 1 from ariel.retrieve_memories(dm_a, array[a], null, null, 50)
             where content in ('B private fact', 'inside joke of group one')) then
    raise exception 'DM check: leaked B or group memory into a DM';
  end if;

  -- Group with A and B: A's group_ok only (NOT her DM fact), B's private hidden, group + global ok.
  if exists (select 1 from ariel.retrieve_memories(grp, array[a, b], null, null, 50)
             where content in ('A said this in a DM', 'B private fact')) then
    raise exception 'GROUP check: leaked a private person memory into a group';
  end if;
  select count(*) into n from ariel.retrieve_memories(grp, array[a, b], null, null, 50);
  if n <> 3 then raise exception 'GROUP check: expected 3 rows (A group_ok, group, global), got %', n; end if;

  -- A person who is not a member of the chat never surfaces, even if passed in.
  select count(*) into n from ariel.retrieve_memories(grp2, array[a], null, null, 50)
   where scope = 'person';
  if n <> 0 then raise exception 'MEMBER check: non-member person memories surfaced'; end if;

  -- Another group's memories never appear (and expired ones are dropped).
  if exists (select 1 from ariel.retrieve_memories(grp2, array[b], null, null, 50)
             where content like 'inside joke%') then
    raise exception 'GROUP2 check: wrong or expired group memory surfaced';
  end if;

  -- Unknown chat id fails closed.
  select count(*) into n from ariel.retrieve_memories(-1, array[a, b], null, null, 50);
  if n <> 0 then raise exception 'UNKNOWN chat check: expected 0 rows, got %', n; end if;

  -- Full-text query narrows results.
  select count(*) into n from ariel.retrieve_memories(dm_a, array[a], 'DM', null, 50);
  if n <> 1 then raise exception 'FTS check: expected 1 row for query "DM", got %', n; end if;

  -- Retrieval refreshes last_used.
  if not exists (select 1 from ariel.memories where content = 'A said this in a DM' and use_count >= 1 and last_used is not null) then
    raise exception 'USE check: last_used / use_count not refreshed';
  end if;

  raise notice 'ariel privacy checks passed';
end $$;

-- ── stage 2: merging two people who turn out to be one human ──
do $$
declare
  a bigint; b bigint; c bigint; d bigint;
  dm_a bigint; dm_b bigint; grp bigint; dm_c bigint;
  n integer;
begin
  insert into ariel.people (display_name, boundaries) values ('merge-A', '{"x": 1}') returning id into a;
  insert into ariel.people (display_name, boundaries) values ('merge-B', '{"stop_initiative": true}') returning id into b;
  insert into ariel.person_identities (person_id, kind, value) values
    (a, 'lid',   'mergecheck-a@lid'),
    (b, 'phone', '99900000001'),
    (b, 'jid',   '99900000001@s.whatsapp.net');
  insert into ariel.chats (kind, wa_jid) values ('dm', 'dm:' || a::text) returning id into dm_a;
  insert into ariel.chats (kind, wa_jid) values ('dm', 'dm:' || b::text) returning id into dm_b;
  insert into ariel.chats (kind, wa_jid) values ('group', 'mergecheck-grp') returning id into grp;
  insert into ariel.chat_members (chat_id, person_id, msg_count) values (dm_a, a, 2), (dm_b, b, 3), (grp, a, 5), (grp, b, 7);
  insert into ariel.messages (chat_id, person_id, wa_message_id, body) values
    (dm_a, a, 'm1', 'one'), (dm_a, a, 'm2', 'two'),
    (dm_b, b, 'm2', 'two again'), (dm_b, b, 'm3', 'three'),
    (grp,  b, 'g1', 'group message');
  insert into ariel.memories (scope, person_id, chat_id, visibility, kind, content)
    values ('person', b, dm_b, 'private', 'fact', 'b private memory');

  perform ariel.merge_people(a, b);

  if exists (select 1 from ariel.people where id = b) then raise exception 'MERGE check: duplicate person still exists'; end if;
  select count(*) into n from ariel.person_identities where person_id = a;
  if n <> 3 then raise exception 'MERGE check: expected 3 ids on the kept person, got %', n; end if;
  if exists (select 1 from ariel.chats where id = dm_b) then raise exception 'MERGE check: duplicate DM chat still exists'; end if;
  select count(*) into n from ariel.messages where chat_id = dm_a;
  if n <> 3 then raise exception 'MERGE check: expected 3 DM messages (one repeat removed), got %', n; end if;
  if exists (select 1 from ariel.messages where chat_id in (dm_a, grp) and (person_id is null or person_id = b)) then
    raise exception 'MERGE check: a message lost its author';
  end if;
  select msg_count into n from ariel.chat_members where chat_id = grp and person_id = a;
  if n <> 12 then raise exception 'MERGE check: group message count should be 12, got %', n; end if;
  select msg_count into n from ariel.chat_members where chat_id = dm_a and person_id = a;
  if n <> 5 then raise exception 'MERGE check: DM message count should be 5, got %', n; end if;
  if not exists (select 1 from ariel.memories where content = 'b private memory' and person_id = a and chat_id = dm_a) then
    raise exception 'MERGE check: memory did not follow the merge';
  end if;
  if not exists (select 1 from ariel.people where id = a and boundaries ? 'stop_initiative' and boundaries ? 'x') then
    raise exception 'MERGE check: boundaries were not combined';
  end if;

  -- The kept person has no DM chat yet: the duplicate's DM chat is renamed to it.
  insert into ariel.people (display_name) values ('merge-C') returning id into c;
  insert into ariel.people (display_name) values ('merge-D') returning id into d;
  insert into ariel.chats (kind, wa_jid) values ('dm', 'dm:' || c::text) returning id into dm_c;
  insert into ariel.chat_members (chat_id, person_id, msg_count) values (dm_c, c, 4);
  perform ariel.merge_people(d, c);
  if not exists (select 1 from ariel.chats where id = dm_c and wa_jid = 'dm:' || d::text) then
    raise exception 'MERGE check: DM chat was not renamed to the kept person';
  end if;
  if not exists (select 1 from ariel.chat_members where chat_id = dm_c and person_id = d and msg_count = 4) then
    raise exception 'MERGE check: DM membership did not move';
  end if;

  -- Running it again, or against a person that is already gone, does nothing.
  perform ariel.merge_people(a, b);
  perform ariel.merge_people(a, a);

  raise notice 'ariel merge checks passed';
end $$;
