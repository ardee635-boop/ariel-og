# Work Mode — stage 8 (WhatsApp interface), on top of stage 7

Unzip stage 7, then this, over the repo root. No migration, no new dependency, no new env var.

## What changed
- **bot/wmode/wa.js (new)** — everything the user sees, with no Baileys/database imports, so it is tested offline.
  `index.js` is now only glue: King check, lazy setup, `sendText`, typing presence, one interface per live socket
  (a reconnect gets a fresh one). Behaviour of .wchat / .wtasks / .wpause / .wresume / .wcancel / .wapprove / .wdeny is unchanged.
- **New commands**: `.whelp` (list), `.wtask [id]` (plan with ✅/⬜, tool calls, tokens used / budget, last model, what to send next),
  `.wlog [id]` (real event history: model calls, provider switches, tools, approvals, review). Both only see the current chat's tasks.
- **Progress without spam**: tool/step lines are merged into at most one message per `progressMinMs` (8 s), `progressMaxLines` (6) per
  message, `progressMaxMessages` (10) per task; plans and approval requests go out at once. The final answer is always sent.
- **Typing indicator** while a task runs (refreshed every `typingRefreshMs`), switched off when it ends, waits for approval or crashes.
- **WhatsApp formatting** of model answers: `**bold**`/`# headings` → `*bold*`, links → `text (url)`, `* item` → `- item`.
  Code (fenced and inline) is never touched. Ariel's own notices and the "checked by Ariel" footer are not reformatted.
- **Safer long messages**: splitting inside a ``` block closes it and reopens it in the next message.
- `.wchat on` resumption of pending tasks now also uses the throttled progress and typing.

## Settings
progressMinMs, progressMaxLines, progressMaxMessages, typing, typingRefreshMs, logLines (settings.js / `work_settings` config).

## Checks (offline)
node scripts/ariel-work-wa-check.js   (44)   parsing, formatting, chunking, throttling, views, and the whole command flow
The six earlier suites still pass unchanged. `index.js` was also import-checked with the Baileys package stubbed.

## Not verified here
Real WhatsApp delivery: typing presence and message cadence were tested against fakes. After deploying, send one multi-step request
and watch that progress arrives in 1–3 messages, not one per tool call.
