# Work Mode — `.cchat` (creative brainstorming), on top of stages 1-8 + 6c

Unzip over the repo root. No migration, no dependency, no env var.

`.cchat <message>` — a brainstorming partner (King only, like every Work command). One model call per message on a new
`work_creative` role (Gemini first, Groq fallback, temperature 0.95), with the last 10 messages of that chat remembered in
memory (cleared by a restart, `.cchat clear`, or 2 h idle). No tools, no tasks, no database writes, no token budget.
Replies get the model name as a footer so you can see who answered.

- bot/wmode/creative.js (new): the prompt + short history. The prompt asks for several genuinely different ideas, honest pushback, concrete detail.
- providers.js: `creative` kind -> `work_creative` role. settings.js: creativeTurns, creativeChars, creativeIdleMs.
- wa.js / index.js: the command, `.whelp` line, wiring.

Check: node scripts/ariel-work-creative-check.js (24, offline)
