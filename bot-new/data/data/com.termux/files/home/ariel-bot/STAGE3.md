# Ariel stage 3 — conversation engine

Unzip over the repo root. No new migration. Changed: `entry.js` (old Python DM chat call removed),
`wire.js`, `hook.js`, `ingest.js`, `admin.js`, `store/pg.js`, `store/mem.js`. New: `core.json`, `config.js`,
`batcher.js`, `parse.js`, `prompt.js`, `send.js`, `conversation.js`.

## Needs from stage 1
`bot/ariel/providers/index.js` must export `ai` (or default) with `ai.chat({role, messages, maxTokens, temperature})`
returning text (or `{text}`), and the routing table needs a `converse` role. If it doesn't load, ingest keeps
working and the log says `replies are off: <reason>`.

## Switches
`ARIEL_REPLY=off` stops replies (ingest continues). `ARIEL_INGEST=off` stops everything.

## On your phone
1. `.chat on` in a test group. Tag her, quote one of her messages, or say "Ariel": she answers.
2. Chat without addressing her: she stays quiet (group joining in is stage 6).
3. `.chatdm on`, DM her: every message is eligible. Send three fast ones: she answers once.
4. Delete a message before she answers: she skips it.
5. `.ariel status` shows replies / reacts / silent / errors.
