# broken/ (dump site)

Code that is broken, dead, half-finished, or "might be useful later" goes here instead of being deleted.

Rules:
- **Nothing in here is ever imported or run.** It is not on the Python `sys.path`, not loaded by `bot/`, and `.dockerignore` keeps it out of the image.
- Move a file here with a one-line note in the table below (what it was, why it's here, what's wrong).
- To revive something: move it back, then fix it.

| File | From | Why it's here |
|------|------|---------------|
| `rpg_locations.py` | `engine/rpg/` | The OLD location source (seven hardcoded dicts). Replaced by `rpg_places.py` + `rpg_map.py` + the places DB. Nothing imports it; only comments mention it. Some docstrings in `rpg_session.py` still describe it. |
| `lab.py` | `engine/router/` | The old in-WhatsApp Professor Oak lab / starter-choice flow (`LabMixin`). Not wired into the router any more (the site's `grant_starter` handler seems to have replaced it) and nothing imports it. It also imported `egg.LEGACY_IDS` and `egg.egg_gift_oak_line`, which no longer exist. |

## Known bugs that live in files that are still in use (not moved, just listed)

| Where | What is wrong |
|-------|---------------|
| `engine/core/db_core.py` | `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` fails on SQLite (non-fatal, fine on Postgres) |
