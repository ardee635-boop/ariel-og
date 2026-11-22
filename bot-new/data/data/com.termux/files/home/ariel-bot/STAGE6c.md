# Work Mode — stage 6c (project memory: notes, decisions, to-dos), on top of stages 7 and 8

Unzip over the repo root (after stage 8). **Needs a migration**: `node scripts/ariel-migrate.js` applies `005_work_project.sql`
(one table, `ariel.work_project_items`, RLS on, anon/authenticated revoked). No new dependency or env var.

## What it adds
The design's "project management" tools: create tasks, track progress, maintain notes, record decisions.
"Tasks" here are **to-dos** (so they are not confused with Work Mode's own tasks).

Tools the model can call (tools/project_tools.js), scoped to the chat of the running task:
- `note_add(title, body)`, `note_update(id, body, title?)`
- `decision_record(title, decision, why?, supersedes?)` — superseding marks the old decision `superseded` and keeps both
- `todo_add(title, details?)`, `todo_update(id, status, note?)` — open | doing | done | dropped
- `project_list(kind?, status?, query?)`, `project_get(id)`

Rules built into the tools:
- Every write is **read back from storage and compared**; a write that cannot be read back is reported as a failure.
- **No secrets**: text that looks like an API key, token or database URL with a password is refused (and the model is told why).
- Over-long text is refused, not silently cut. Per-chat cap `projectMaxItems` (500).
- A task can only see/change its own chat's items. Saved text is passed back to models labelled as data, never instructions.

Use by the agent:
- Requests such as "add a to-do…", "note that…", "record the decision…", "what did we decide" go through the tool loop.
- At the start of a tool task the model gets a small relevant slice (open to-dos, recent decisions, only notes sharing words with the
  request; max `projectContextItems`/`projectContextChars`). If that lookup fails (e.g. migration not run) the task simply runs without it.
- The final footer lists what was recorded, from tool results: `🗂️ project memory: todo #3 added · decision #1 recorded · todo #2 → done`.

WhatsApp: `.wproject` shows open to-dos, decisions and notes for the chat (also in `.whelp`).

## Settings
projectMaxItems 500, projectItemChars 2000, projectContextItems 5, projectContextChars 1500, projectListMax 20.

## Checks
node scripts/ariel-work-project-check.js            (30, offline)
node --env-file=.env scripts/ariel-work-project-check.js --db   same store suite on the real SQL, in a rolled-back transaction
All earlier suites still pass.

## Not verified here
The Postgres version of the store has not run against a real database (none in my environment). Run the `--db` check after migrating.
Models were scripted, so how well real Groq/Gemini decide *when* to use these tools is untested.
