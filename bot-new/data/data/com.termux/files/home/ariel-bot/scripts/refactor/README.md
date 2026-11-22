# One-off refactor tools (kept so the next cut can reuse them)

Both cuts work the same way: slice a huge function into per-feature files **verbatim, by AST statement boundaries**, then
prove nothing changed (AST-identical moved statements, every identifier resolves, then the golden tests).

* `js_plan.cjs`      - `node --expose-internals --no-warnings scripts/refactor/js_plan.cjs bot/handler.js`: lists the top-level statements of
                       `handleMessage` (line ranges, what each declares, how many `return`s). Uses the acorn parser bundled inside Node.
* `cut_handler.cjs`  - the generator used for `bot/handler.js` -> `bot/handler/*.js` (16 steps). Edit the `GROUPS` table (first/last statement
                       line of each step) to reuse it for another file. It backs the original up to `/tmp/handler_orig.js` first and reads from
                       that backup, so it can be re-run.
* `rpg_cut_plan.py`, `cut_rpg.py` - the Python equivalent used for `router/rpg.py` -> `router/rpg_cmds/*.py` (backs up to `/tmp/rpg_orig.py`).

Paths are hard-coded for the machine they were written on; treat them as templates.
