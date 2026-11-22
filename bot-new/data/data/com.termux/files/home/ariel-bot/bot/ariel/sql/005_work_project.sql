-- Work Mode stage 6c: project memory — notes, decisions and to-dos kept per chat. Idempotent.
-- Durable on purpose (unlike work_events): small, human-meaningful records, capped per chat by the app.
create table if not exists ariel.work_project_items (
  id          bigint generated always as identity primary key,
  chat_jid    text not null,
  user_id     text not null,
  kind        text not null check (kind in ('note','decision','todo')),
  title       text not null,
  body        text not null default '',
  status      text not null default 'active'
              check (status in ('active','superseded','open','doing','done','dropped')),
  task_id     bigint,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);
create index if not exists work_project_chat_kind on ariel.work_project_items (chat_jid, kind, status, updated_at desc);

-- Same lock-down as 001/003: not reachable through Supabase's public API roles.
alter table ariel.work_project_items enable row level security;
do $$
begin
  if exists (select 1 from pg_roles where rolname = 'anon') then
    execute 'revoke all on ariel.work_project_items from anon';
  end if;
  if exists (select 1 from pg_roles where rolname = 'authenticated') then
    execute 'revoke all on ariel.work_project_items from authenticated';
  end if;
end $$;
