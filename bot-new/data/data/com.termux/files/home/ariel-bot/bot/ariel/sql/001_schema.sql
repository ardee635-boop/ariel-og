-- ============================================================
-- Ariel AI — schema v1 (stage 1)
-- Idempotent: safe to re-run. {{EMBED_DIM}} is filled in by
-- scripts/ariel-migrate.js (default 768, fixed by the embedding model).
-- All objects live in the `ariel` schema, apart from the game tables.
-- ============================================================

create schema if not exists ariel;

-- pgvector: respect Supabase's `extensions` schema when it exists.
do $$
begin
  if exists (select 1 from pg_extension where extname = 'vector') then
    null;
  elsif exists (select 1 from pg_namespace where nspname = 'extensions') then
    create extension vector with schema extensions;
  else
    create extension vector;
  end if;
end $$;

-- SET LOCAL: lasts until the migration's transaction ends.
set local search_path = ariel, public, extensions;

-- ── people & identity ───────────────────────────────────────
create table if not exists ariel.people (
  id            bigint generated always as identity primary key,
  display_name  text,
  style         jsonb not null default '{}'::jsonb,
  boundaries    jsonb not null default '{}'::jsonb,
  first_seen    timestamptz not null default now(),
  last_seen     timestamptz not null default now()
);

-- Every WhatsApp id a person has used (jid, @lid, phone) -> one people row.
create table if not exists ariel.person_identities (
  id          bigint generated always as identity primary key,
  person_id   bigint not null references ariel.people(id) on delete cascade,
  kind        text not null check (kind in ('jid', 'lid', 'phone')),
  value       text not null unique,
  created_at  timestamptz not null default now()
);
create index if not exists person_identities_person_idx on ariel.person_identities (person_id);

-- ── chats ───────────────────────────────────────────────────
create table if not exists ariel.chats (
  id          bigint generated always as identity primary key,
  kind        text not null check (kind in ('dm', 'group')),
  wa_jid      text not null unique,
  settings    jsonb not null default '{}'::jsonb,   -- chat on, initiative on, quiet hours
  created_at  timestamptz not null default now()
);

create table if not exists ariel.chat_members (
  chat_id    bigint not null references ariel.chats(id) on delete cascade,
  person_id  bigint not null references ariel.people(id) on delete cascade,
  msg_count  integer not null default 0,
  last_seen  timestamptz not null default now(),
  primary key (chat_id, person_id)
);
create index if not exists chat_members_person_idx on ariel.chat_members (person_id);

-- ── messages (recent raw only; person_id NULL = Ariel) ──────
create table if not exists ariel.messages (
  id             bigint generated always as identity primary key,
  chat_id        bigint not null references ariel.chats(id) on delete cascade,
  person_id      bigint references ariel.people(id) on delete set null,
  wa_message_id  text,
  reply_to       text,
  body           text not null,
  fts            tsvector generated always as (to_tsvector('simple', coalesce(body, ''))) stored,
  created_at     timestamptz not null default now(),
  processed_at   timestamptz
);
create unique index if not exists messages_wa_id_uq on ariel.messages (chat_id, wa_message_id) where wa_message_id is not null;
create index if not exists messages_chat_time_idx on ariel.messages (chat_id, created_at desc);
create index if not exists messages_fts_idx on ariel.messages using gin (fts);
create index if not exists messages_cleanup_idx on ariel.messages (processed_at) where processed_at is not null;

-- ── summaries (meaning of closed conversation segments) ─────
create table if not exists ariel.summaries (
  id            bigint generated always as identity primary key,
  chat_id       bigint not null references ariel.chats(id) on delete cascade,
  period        tstzrange not null,
  body          text not null,
  topics        text[] not null default '{}',
  open_threads  jsonb not null default '[]'::jsonb,
  embedding     vector({{EMBED_DIM}}),
  fts           tsvector generated always as (to_tsvector('simple', coalesce(body, ''))) stored,
  verified_at   timestamptz,
  created_at    timestamptz not null default now()
);
create index if not exists summaries_chat_idx on ariel.summaries (chat_id, (upper(period)) desc);
create index if not exists summaries_fts_idx on ariel.summaries using gin (fts);
create index if not exists summaries_embedding_idx on ariel.summaries using hnsw (embedding vector_cosine_ops);

-- ── memories (all long-term memory, three scopes) ───────────
-- importance: 1 low, 2 normal, 3 high, 4 critical
create table if not exists ariel.memories (
  id             bigint generated always as identity primary key,
  scope          text not null check (scope in ('person', 'group', 'global')),
  person_id      bigint references ariel.people(id) on delete cascade,
  chat_id        bigint references ariel.chats(id),
  visibility     text not null default 'private' check (visibility in ('private', 'group_ok')),
  kind           text not null,
  content        text not null,
  importance     smallint not null default 2 check (importance between 1 and 4),
  confidence     real not null default 1,
  embedding      vector({{EMBED_DIM}}),
  fts            tsvector generated always as (to_tsvector('simple', coalesce(content, ''))) stored,
  use_count      integer not null default 0,
  last_used      timestamptz,
  expires_at     timestamptz,
  superseded_by  bigint references ariel.memories(id) on delete set null,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now(),
  constraint memories_scope_shape check (
       (scope = 'person' and person_id is not null)
    or (scope = 'group'  and chat_id is not null and person_id is null)
    or (scope = 'global' and person_id is null and chat_id is null)
  )
);
create index if not exists memories_person_idx on ariel.memories (person_id) where scope = 'person' and superseded_by is null;
create index if not exists memories_group_idx on ariel.memories (chat_id) where scope = 'group' and superseded_by is null;
create index if not exists memories_expiry_idx on ariel.memories (expires_at) where expires_at is not null;
create index if not exists memories_fts_idx on ariel.memories using gin (fts);
create index if not exists memories_embedding_idx on ariel.memories using hnsw (embedding vector_cosine_ops);

-- ── social picture ──────────────────────────────────────────
create table if not exists ariel.person_state (
  person_id        bigint primary key references ariel.people(id) on delete cascade,
  familiarity      real not null default 0,
  rapport          jsonb not null default '{}'::jsonb,
  last_interaction timestamptz,
  receptiveness    real not null default 0.5 check (receptiveness between 0 and 1)
);

create table if not exists ariel.relationships (
  id         bigint generated always as identity primary key,
  person_a   bigint not null references ariel.people(id) on delete cascade,
  person_b   bigint not null references ariel.people(id) on delete cascade,
  chat_id    bigint not null references ariel.chats(id) on delete cascade,
  kind       text not null,                 -- friend, rival, teasing, ...
  strength   real not null default 0,
  notes      text,
  updated_at timestamptz not null default now(),
  check (person_a < person_b),
  unique (chat_id, person_a, person_b)
);

-- ── Ariel herself ───────────────────────────────────────────
create table if not exists ariel.identity (
  key             text primary key,
  value           jsonb not null,
  evidence_count  integer not null default 0,
  version         integer not null default 1,
  updated_at      timestamptz not null default now()
);

create table if not exists ariel.ariel_state (
  id          smallint primary key default 1 check (id = 1),   -- exactly one row
  state       jsonb not null default '{}'::jsonb,
  updated_at  timestamptz not null default now()
);
insert into ariel.ariel_state (id) values (1) on conflict do nothing;

-- ── initiative & feedback ───────────────────────────────────
create table if not exists ariel.initiatives (
  id            bigint generated always as identity primary key,
  chat_id       bigint not null references ariel.chats(id) on delete cascade,
  person_id     bigint references ariel.people(id) on delete set null,
  kind          text not null,
  reason        text,
  status        text not null default 'planned',   -- planned, shadow, sent, skipped
  scheduled_for timestamptz,
  sent_at       timestamptz,
  outcome       jsonb,
  created_at    timestamptz not null default now()
);
create index if not exists initiatives_chat_idx on ariel.initiatives (chat_id, created_at desc);

create table if not exists ariel.feedback_signals (
  id          bigint generated always as identity primary key,
  person_id   bigint references ariel.people(id) on delete set null,
  kind        text not null,
  text        text,
  weight      real not null default 1,
  created_at  timestamptz not null default now()
);

-- ── operations ──────────────────────────────────────────────
create table if not exists ariel.jobs (
  id          bigint generated always as identity primary key,
  kind        text not null,
  payload     jsonb not null default '{}'::jsonb,
  run_at      timestamptz not null default now(),
  status      text not null default 'queued' check (status in ('queued', 'running', 'done', 'failed', 'dead')),
  attempts    integer not null default 0,
  last_error  text,
  locked_at   timestamptz,
  finished_at timestamptz,
  created_at  timestamptz not null default now()
);
create index if not exists jobs_claim_idx on ariel.jobs (run_at) where status = 'queued';

create table if not exists ariel.llm_usage (
  id          bigint generated always as identity primary key,
  ts          timestamptz not null default now(),
  provider    text not null,
  model       text not null,
  role        text not null,
  tokens_in   integer,
  tokens_out  integer,
  latency_ms  integer,
  ok          boolean not null,
  error       text,
  cost_usd    numeric(12, 6)
);
create index if not exists llm_usage_role_ts_idx on ariel.llm_usage (role, ts desc);

create table if not exists ariel.config (
  key         text primary key,
  value       jsonb not null,
  updated_at  timestamptz not null default now()
);

-- Migration bookkeeping (not one of the 16 design tables).
create table if not exists ariel._migrations (
  name        text primary key,
  checksum    text not null,
  embed_dim   integer,
  applied_at  timestamptz not null default now()
);

-- ── privacy: the ONLY way memories are read ─────────────────
-- Returns only:
--   * global memories
--   * group memories for THIS chat
--   * person memories for people present (and members of this chat);
--     in a group, only the group_ok ones
-- Hybrid ranking: full-text + vector (reciprocal rank fusion), boosted by
-- importance, past use and recency. Critical person memories for people
-- present are always included. Retrieval refreshes last_used / use_count.
-- Unknown chat id => no rows (fail closed).
create or replace function ariel.retrieve_memories(
  p_chat_id            bigint,
  p_present_person_ids bigint[],
  p_query_text         text,
  p_query_embedding    vector,
  p_k                  integer default 10
)
returns table (
  id          bigint,
  scope       text,
  person_id   bigint,
  visibility  text,
  kind        text,
  content     text,
  importance  smallint,
  score       double precision
)
language plpgsql
set search_path = ariel, public, extensions
as $$
#variable_conflict use_column
declare
  v_chat_kind text;
  v_tsq       tsquery;
  v_no_query  boolean;
begin
  select c.kind into v_chat_kind from ariel.chats c where c.id = p_chat_id;
  if v_chat_kind is null then
    return;
  end if;

  v_tsq := websearch_to_tsquery('simple', coalesce(p_query_text, ''));
  v_no_query := (numnode(v_tsq) = 0 and p_query_embedding is null);

  return query
  with allowed as (
    select m.id, m.scope, m.person_id, m.visibility, m.kind, m.content, m.importance,
           m.embedding, m.fts, m.use_count, m.last_used, m.created_at
    from ariel.memories m
    where m.superseded_by is null
      and (m.expires_at is null or m.expires_at > now())
      and (
            m.scope = 'global'
         or (m.scope = 'group' and m.chat_id = p_chat_id)
         or (m.scope = 'person'
             and m.person_id = any (coalesce(p_present_person_ids, '{}'::bigint[]))
             and exists (select 1 from ariel.chat_members cm
                         where cm.chat_id = p_chat_id and cm.person_id = m.person_id)
             and (v_chat_kind = 'dm' or m.visibility = 'group_ok'))
      )
  ),
  ft as (
    select s.id, s.rn from (
      select a.id, row_number() over (order by ts_rank_cd(a.fts, v_tsq) desc, a.id) as rn
      from allowed a
      where numnode(v_tsq) > 0 and a.fts @@ v_tsq
    ) s where s.rn <= 50
  ),
  ve as (
    select s.id, s.rn from (
      select a.id, row_number() over (order by a.embedding <=> p_query_embedding, a.id) as rn
      from allowed a
      where p_query_embedding is not null and a.embedding is not null
    ) s where s.rn <= 50
  ),
  scored as (
    select a.id, a.scope, a.person_id, a.visibility, a.kind, a.content, a.importance,
           (a.scope = 'person' and a.importance = 4) as is_critical,
           ( coalesce(1.0::double precision / (60 + ft.rn), 0)
           + coalesce(1.0::double precision / (60 + ve.rn), 0) )
           * (1 + 0.25 * (a.importance - 2))
           * (1 + 0.1 * ln(1 + a.use_count::double precision))
           * (0.7 + 0.3 * exp(-extract(epoch from (now() - coalesce(a.last_used, a.created_at))) / 86400.0 / 90.0))
           as score
    from allowed a
    left join ft on ft.id = a.id
    left join ve on ve.id = a.id
    where ft.id is not null or ve.id is not null
       or (a.scope = 'person' and a.importance = 4)
       or v_no_query
  ),
  ranked as (
    select s.*, row_number() over (order by s.score desc, s.id) as rn
    from scored s
    where not s.is_critical
  ),
  picked as (
    select s.id, s.scope, s.person_id, s.visibility, s.kind, s.content, s.importance, s.is_critical, s.score
    from scored s where s.is_critical
    union all
    select r.id, r.scope, r.person_id, r.visibility, r.kind, r.content, r.importance, r.is_critical, r.score
    from ranked r
    where r.rn <= greatest(p_k - (select count(*) from scored x where x.is_critical), 0)
  ),
  upd as (
    update ariel.memories mm
       set last_used = now(), use_count = mm.use_count + 1
      from picked pk
     where mm.id = pk.id
    returning mm.id
  )
  select pk.id, pk.scope, pk.person_id, pk.visibility, pk.kind, pk.content, pk.importance, pk.score
  from picked pk
  join upd on upd.id = pk.id
  order by pk.is_critical desc, pk.score desc;
end;
$$;

-- ── lock the schema away from Supabase's public API roles ───
do $$
declare t record;
begin
  for t in select tablename from pg_tables where schemaname = 'ariel' loop
    execute format('alter table ariel.%I enable row level security', t.tablename);
  end loop;
  if exists (select 1 from pg_roles where rolname = 'anon') then
    execute 'revoke all on schema ariel from anon';
    execute 'revoke all on all tables in schema ariel from anon';
  end if;
  if exists (select 1 from pg_roles where rolname = 'authenticated') then
    execute 'revoke all on schema ariel from authenticated';
    execute 'revoke all on all tables in schema ariel from authenticated';
  end if;
end $$;
