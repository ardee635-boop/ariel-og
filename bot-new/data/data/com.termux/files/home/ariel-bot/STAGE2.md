# Ariel stage 2 — ingest and identity

Unzip over the repo root (same layout as stage 1). Two existing files change:
`bot/handler/entry.js` and `bot/groups.js` (diff in `stage2-integration.patch`).

## Apply
1. `node --env-file=.env scripts/ariel-migrate.js`          (applies 002; 001 is unchanged)
2. `node --env-file=.env scripts/ariel-migrate.js --check`   (privacy + merge checks, rolled back)
3. `node --env-file=.env scripts/ariel-ingest-check.js`      (real ingest SQL, rolled back)
4. Deploy. Kill switch: `ARIEL_INGEST=off`.

## Tests (no database)
`node --test tests/js/ariel_stage2_test.mjs tests/js/ariel_stage1_test.mjs`

## On your phone
- `.chat on` in a test group, talk for a minute, then `.ariel status` (King only).
- `.ariel people` shows names, message counts and which id kinds each person has.
- Send a message, edit it, delete it for everyone: status counts edits/deletes.
- Send `.rpg` or any command: it must NOT show up in the stored count.
- `.chatdm on`, DM the bot from a second phone, `.ariel status` again.

## Not in this stage
No replies, no model calls. The old `callPython` DM path in entry.js is untouched.
