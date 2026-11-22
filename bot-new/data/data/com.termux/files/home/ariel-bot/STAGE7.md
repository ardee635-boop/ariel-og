# Work Mode — stage 7 (verification), cumulative with 1-6b

Unzip over the repo root. No migration, no new dependency, no new command.

## What it adds (bot/wmode/verify.js + a hook in manager.js runAgent)
1. **Check before "done".** If the model changed code (js/ts/py/sh/json/sql/html/css/yml) and nothing was run afterwards,
   its final answer is not accepted the first time: it is sent back with an "(Ariel)" note to run tests or a syntax check.
   Once only (verifyNudges). Notes/markdown/text never trigger it. A run from BEFORE the last edit does not count.
2. **Unbacked claims.** "all tests pass", "works as expected", "verified"... with no passing run after the last change
   adds `⚠️ unbacked claim: ...` to the footer (says FAILED if the last check failed).
3. **Independent review.** After code changes, one call on the `review` role (Gemini first, Groq fallback) sees the code
   written, the real check results and the final answer, and returns ok / concerns. Shown in the footer:
   `🔎 independent review by gemini/...: no problems found (a review is not a test)` or the listed concerns.
   If the reviewer ends up being the same model as the author, the footer says so.
   A review never pauses or fails a task: no quota, low budget (reviewMinTokens), or an unusable reply = "review skipped (reason)".
   Reviewed once per task (saved in task.agent.reviewed).

All footer lines come from tool results and the reviewer's JSON, not from the author's words.
Research already had source checks (stage 6b); unchanged.

## Settings (settings.js; env in brackets)
verify true [WORK_VERIFY], verifyNudges 1, review true [WORK_REVIEW], reviewMinTokens 1500, reviewChars 6000.

## Checks (offline)
node scripts/ariel-work-verify-check.js   (28)
The five earlier suites still pass unchanged.

## Limits, honestly
- A review is another model's opinion on shown code, not a test. It can miss bugs or invent concerns.
- The nudge costs one tool-call slot (counts toward agentMaxSteps) and one model call.
- Not run against live Groq/Gemini: the reviewer's reply format is enforced by the parser, but real models may
  answer off-format sometimes; that shows as "review skipped (reviewer reply was not usable)".
