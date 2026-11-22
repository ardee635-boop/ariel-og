# Ariel stage 4 — memory

Unzip over the repo root. No migration (001 already has the tables and `retrieve_memories`).
Also fixes stage 3: `wire.js` now loads `providers/default.js` (the real export), not `index.js`.

## What it does
- **Explicit memory** (only messages addressed to her): "remember…", "forget…", "actually…". A pattern
  catches it, then the `extract` model confirms and writes the memory. She is told what changed and says it in her own words.
- **Where it lands:** DM -> private person memory. Group -> about the speaker, `group_ok`; shared jokes/rules -> group memory.
  Never under someone else's id. Global only for the owner (KING_NUMBER).
- **Forget** hard-deletes, limited in SQL to the speaker's own memories and this chat's group memories.
- **Update** writes the new fact and marks the old one superseded (kept 30 days).
- **Retrieval** goes only through `ariel.retrieve_memories`; the top 10 go into her prompt as "what you remember".
- If embeddings fail, memories are saved without a vector and filled in later (every 10 min). Search falls back to text.

## Check (needs your database, changes nothing)
`node --env-file=.env scripts/ariel-memory-check.js`
Tries to leak a DM memory into a group, delete someone else's memory, and create global memory as a non-owner.

## On your phone
1. DM: "ariel remember my birthday is 3 march". She confirms. `.ariel status` shows `memory: 1 saved`.
2. In a group (both of you present): ask "ariel when is my birthday". She must NOT know it.
3. In the group: "ariel remember i support arsenal". Ask again later: she knows.
4. "ariel actually i support chelsea", then "ariel forget that".
