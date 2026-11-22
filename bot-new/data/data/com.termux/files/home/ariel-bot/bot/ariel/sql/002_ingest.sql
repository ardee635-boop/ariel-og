-- ============================================================
-- Ariel AI — schema v2 (stage 2: ingest and identity)
-- Idempotent: safe to re-run.
--   * messages.meta   : how a message was addressed (tag / quote of Ariel),
--                       who it mentions, its kind (text, image, ...)
--   * merge_people()  : when two ids turn out to be one human, fold the
--                       duplicate person into the older one without losing anything
-- DM chats are keyed by person ('dm:<person id>'), so one human who shows up as
-- both a phone id and a @lid still has exactly one DM chat. The id to send to
-- is kept in chats.settings.send_jid.
-- ============================================================

set local search_path = ariel, public, extensions;

alter table ariel.messages add column if not exists meta jsonb not null default '{}'::jsonb;

create or replace function ariel.merge_people(p_keep bigint, p_drop bigint)
returns void
language plpgsql
set search_path = ariel, public, extensions
as $$
#variable_conflict use_column
declare
  v_keep_dm bigint;
  v_drop_dm bigint;
begin
  if p_keep is null or p_drop is null or p_keep = p_drop then
    return;
  end if;
  if not exists (select 1 from ariel.people where id = p_keep) then
    raise exception 'merge_people: keep person % does not exist', p_keep;
  end if;
  if not exists (select 1 from ariel.people where id = p_drop) then
    return;   -- someone else already merged it
  end if;

  -- Lock both rows in id order so two merges can't deadlock each other.
  perform 1 from ariel.people where id in (p_keep, p_drop) order by id for update;

  -- Every id the duplicate used now belongs to the person we keep.
  update ariel.person_identities set person_id = p_keep where person_id = p_drop;

  -- DM chats: one per person. Fold the duplicate's DM chat into the kept one.
  select id into v_keep_dm from ariel.chats where wa_jid = 'dm:' || p_keep::text;
  select id into v_drop_dm from ariel.chats where wa_jid = 'dm:' || p_drop::text;
  if v_drop_dm is not null then
    if v_keep_dm is null then
      update ariel.chats set wa_jid = 'dm:' || p_keep::text where id = v_drop_dm;
    else
      -- the same WhatsApp message stored twice (once per half-known person): keep one
      delete from ariel.messages d
       where d.chat_id = v_drop_dm
         and d.wa_message_id is not null
         and exists (select 1 from ariel.messages k
                      where k.chat_id = v_keep_dm and k.wa_message_id = d.wa_message_id);
      update ariel.messages   set chat_id = v_keep_dm where chat_id = v_drop_dm;
      update ariel.summaries  set chat_id = v_keep_dm where chat_id = v_drop_dm;
      update ariel.memories   set chat_id = v_keep_dm where chat_id = v_drop_dm;  -- no cascade on this FK
      update ariel.initiatives set chat_id = v_keep_dm where chat_id = v_drop_dm;
      update ariel.chats k
         set settings = d.settings || k.settings
        from ariel.chats d
       where k.id = v_keep_dm and d.id = v_drop_dm;
      -- carry the duplicate's message count over before its member row goes away
      update ariel.chat_members k
         set msg_count = k.msg_count + d.msg_count,
             last_seen = greatest(k.last_seen, d.last_seen)
        from ariel.chat_members d
       where d.chat_id = v_drop_dm and d.person_id = p_drop
         and k.chat_id = v_keep_dm and k.person_id = p_keep;
      delete from ariel.chats where id = v_drop_dm;   -- cascades the leftover member row
    end if;
  end if;

  -- Membership in every other chat: add the counts when both were members.
  update ariel.chat_members k
     set msg_count = k.msg_count + d.msg_count,
         last_seen = greatest(k.last_seen, d.last_seen)
    from ariel.chat_members d
   where d.person_id = p_drop and k.person_id = p_keep and k.chat_id = d.chat_id;
  delete from ariel.chat_members d
   where d.person_id = p_drop
     and exists (select 1 from ariel.chat_members k
                  where k.person_id = p_keep and k.chat_id = d.chat_id);
  update ariel.chat_members set person_id = p_keep where person_id = p_drop;

  -- Things that point at a person.
  update ariel.messages          set person_id = p_keep where person_id = p_drop;
  update ariel.memories          set person_id = p_keep where person_id = p_drop;
  update ariel.initiatives       set person_id = p_keep where person_id = p_drop;
  update ariel.feedback_signals  set person_id = p_keep where person_id = p_drop;

  if exists (select 1 from ariel.person_state where person_id = p_keep) then
    update ariel.person_state k
       set familiarity      = greatest(k.familiarity, d.familiarity),
           rapport          = d.rapport || k.rapport,
           last_interaction = greatest(k.last_interaction, d.last_interaction)
      from ariel.person_state d
     where k.person_id = p_keep and d.person_id = p_drop;
    delete from ariel.person_state where person_id = p_drop;
  else
    update ariel.person_state set person_id = p_keep where person_id = p_drop;
  end if;

  -- Person-to-person notes are derived data: rebuilt from future conversations.
  delete from ariel.relationships where person_a = p_drop or person_b = p_drop;

  update ariel.people k
     set first_seen   = least(k.first_seen, d.first_seen),
         last_seen    = greatest(k.last_seen, d.last_seen),
         display_name = coalesce(k.display_name, d.display_name),
         style        = d.style || k.style,
         boundaries   = d.boundaries || k.boundaries
    from ariel.people d
   where k.id = p_keep and d.id = p_drop;

  delete from ariel.people where id = p_drop;
end;
$$;
