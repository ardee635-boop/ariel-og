# Work Mode — stages 1-5c (cumulative)

Unzip over the repo root, then run `node --env-file=.env scripts/ariel-migrate.js` (adds 004_work_agent.sql: one column).

## 5a — file tools (bot/wmode/tools/)
sandbox.js (workspace-only paths, symlinks resolved, secrets/.git protected), index.js (registry),
fs_tools.js: read_file, list_dir, search_code, create_file, edit_file (verified on disk), delete_file (approval).

## 5b — commands (tools/cmd_tools.js)
run_command: no shell; one plain command; allowlist: node (--version, --check f, --test, f.js), npm (test, run <script>),
python3 (f.py, -m pytest|unittest|py_compile), git (status, diff, log, show). No -e/-c, no install, no npx.
Safe = version/syntax checks + read-only git (run freely). Running workspace code needs approval.
run_tests: detects npm test / node --test / python unittest|pytest, reports PASSED/FAILED from the real exit code.
Env is scrubbed (no API keys / DB url), 30 s timeout kills the whole process group, output clipped.
Not a container: approved code runs with the bot's OS permissions.

Settings (settings.js): workspaceDir, tool limits, commandTimeoutMs (WORK_COMMAND_TIMEOUT_MS),
commandOutputChars, autoApproveTests (default false).

## Checks
node scripts/ariel-work-tools-check.js   (59 checks, offline, temp folder)
node scripts/ariel-work-check.js         (stages 1-4, unchanged, still passes)

## 5c — the tool loop
bot/wmode/agent.js (prompt, JSON action parser, footer) + runAgent() in manager.js. Requests that mention files/workspace/tests
(settings.toolMode 'auto'|'always'|'never') run as: model replies with one JSON action -> tool runs -> result fed back, until {"final":...}.
- State is saved in work_tasks.agent (turns, pending approval); prompts are rebuilt from it, so a provider switch or restart loses nothing.
- Risky calls (running code, delete_file) set the task to waiting_approval. `.wapprove [id]` / `.wdeny [id]`. A denial is shown to the model.
  Waiting tasks survive restarts and are never auto-run by the recovery sweep. `.wcancel` works on them.
- Step cap agentMaxSteps (12): pauses with "step limit"; `.wresume` grants another batch. Token budget still applies.
- Final answers get a footer built from tool results (files created/edited/deleted, last test/command result, warning if
  files changed after the last run or nothing was run) — not from the model's words.
- Tool calls are logged in work_events. Planned (multi-step text) tasks are unchanged; a tool task skips the planner.
- Two non-JSON replies in a row end the task with an honest "not checked by tools" warning.

Check: node scripts/ariel-work-agent-check.js (27 checks). New settings: toolMode, agentMaxSteps (WORK_TOOL_MODE, WORK_AGENT_MAX_STEPS).
