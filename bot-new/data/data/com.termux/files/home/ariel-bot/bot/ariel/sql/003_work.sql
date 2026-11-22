-- ============================================================
-- Ariel Work Mode — schema v1 (idempotent, safe to re-run)
-- Tables live in the `ariel` schema next to the chat tables.
-- ============================================================
create schema if not exists ariel;

-- Which chats have Work Mode switched on. Survives restarts.
create table if not exists ariel.work_mode (
  chat_jid      text primary key,
  active        boolean not null default false,
  activated_by  text,
  activated_at  timestamptz,
  updated_at    timestamptz not null default now()
);

-- One work session per chat. `recent` is TEMPORARY context (last few turns, capped);
-- `notes` is the persistent project notes / decisions list.
create table if not exists ariel.work_sessions (
  chat_jid    text primary key,
  user_id     text not null,
  recent      jsonb not null default '[]'::jsonb,
  notes       jsonb not null default '[]'::jsonb,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);

create table if not exists ariel.work_tasks (
  id               bigint generated always as identity primary key,
  user_id          text not null,
  chat_jid         text not null,
  source_msg_id    text,
  description      text not null,
  kind             text not null default 'simple',
  status           text not null default 'pending'
                   check (status in ('pending','planning','running','waiting_approval','paused','completed','failed','cancelled')),
  plan             jsonb not null default '[]'::jsonb,
  current_step     integer not null default 0,
  completed_steps  jsonb not null default '[]'::jsonb,
  pending_steps    jsonb not null default '[]'::jsonb,
  provider         text,
  model            text,
  tokens_in        bigint not null default 0,
  tokens_out       bigint not null default 0,
  token_budget     integer,
  result           text,
  error            text,
  pause_reason     text,
  locked_by        text,
  lease_until      timestamptz,
  created_at       timestamptz not null default now(),
  started_at       timestamptz,
  completed_at     timestamptz,
  updated_at       timestamptz not null default now()
);

-- The same WhatsApp message can be delivered twice; it must never become two tasks.
create unique index if not exists work_tasks_source_uq
  on ariel.work_tasks (chat_jid, source_msg_id) where source_msg_id is not null;
create index if not exists work_tasks_chat_status on ariel.work_tasks (chat_jid, status);
create index if not exists work_tasks_user_created on ariel.work_tasks (user_id, created_at desc);

-- Execution history, provider switches, tool actions. Payloads are clipped by the app
-- and pruned after N days (Work Mode settings) — model replies are not kept forever.
create table if not exists ariel.work_events (
  id       bigint generated always as identity primary key,
  task_id  bigint not null references ariel.work_tasks(id) on delete cascade,
  ts       timestamptz not null default now(),
  kind     text not null,
  data     jsonb not null default '{}'::jsonb
);
create index if not exists work_events_task on ariel.work_events (task_id, id);
create index if not exists work_events_ts on ariel.work_events (ts);

-- Same lock-down as 001: nothing here is reachable through Supabase's public API roles.
do $$
declare t text;
begin
  foreach t in array array['work_mode','work_sessions','work_tasks','work_events'] loop
    execute format('alter table ariel.%I enable row level security', t);
  end loop;
  if exists (select 1 from pg_roles where rolname = 'anon') then
    execute 'revoke all on all tables in schema ariel from anon';
  end if;
  if exists (select 1 from pg_roles where rolname = 'authenticated') then
    execute 'revoke all on all tables in schema ariel from authenticated';
  end if;
end $$;
