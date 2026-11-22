-- Work Mode stage 5c: the tool loop's saved state (turns, pending approval). Idempotent.
alter table ariel.work_tasks add column if not exists agent jsonb not null default '{}'::jsonb;
