# ARIEL AMONG US — COMMAND SHEET

What the code sends today (Package 13, full snapshot of 27 Oct). Among Us only.

**IMPLEMENTATION STATUS (after note session N6):** items 1-8 (lobby), 11-16, 18-21 (movement/info), 22-26 (tasks), 27, 28, 30 (impostor, partly) and 31, 32, 35 (reports/meetings/voting) and 36-39 (sabotage, partly) are in code; each has its final text in its "New" line. Item 17 (`.cds`) was not in the drafts. Items 9-10, 29, 33, 34 and 40 onward are still the Package 13 snapshot. Session plan: N1 lobby ✅ · N2 movement/info ✅ · N3 tasks ✅ · N4 impostor ✅ · N5 reports/meetings/voting ✅ · N6 sabotage ✅ · N7 match end/ghosts · N8 images. Details: `docs/amongus/NOTE_SESSIONS.md`.
Each command is one block: **DM** · **GROUP** · **Extra**, then two blank lines for your new text.
`—` means nothing is sent there. `{x}` is a live value. Wording in the Extra lines is also current code.

---

## QUICK MATRIX

| # | Command | DM | GROUP | Extra |
|---|---|:-:|:-:|---|
| **A. Lobby** | | | | |
| 1 | `.amongus on/off` | — (error only) | ✔ | Per GC, not per player. Group toggle may swallow it |
| 2 | `.lobby open` | — (error only) | ✔ | Lobby artwork slot (N8): sent only when `lobby` link is set |
| 3 | `.join` | — (error only) | ✔ | Roster is "Player N" |
| 4 | `.leave` | ✔ | ✔ | Host handover msg |
| 5 | `.lobby list` | — | ✔ | |
| 6 | `.lobby start` | role DMs | ✔ start msg | Ship map sent with the group start message only (N8, decision 11), when `maps` link is set |
| 7 | `.lobby test` | — | ✔ | Host solo test |
| 8 | `.endgame` | — | ✔ | No result DMs |
| 9 | `.amenu` | ✔ | ✔ | |
| 10 | `.GC` / `.dm` | ✔ | ✔ | Real links |
| **B. Movement** | | | | |
| 11 | `.m` | ✔ | — | Arrival + room awareness DMs |
| 12 | `.stop` | ✔ | — | |
| 13 | `.goback` | ✔ | — | |
| 14 | `.where` | ✔ | — | |
| 15 | `.map` | ✔ | — | Map image |
| **C. Info** | | | | |
| 16 | `.status` | ✔ | — | Stage-card image |
| 17 | `.cds` | ✔ | — | |
| 18 | `.players` | ✔ | — | Frozen in Comms |
| 19 | `.progress` | ✔ | — | Corrupt in Comms |
| 20 | `.cscene` | ✔ | — | |
| 21 | `.vitals` / `.witness` | ✔ | — | Scientist only |
| **D. Tasks** | | | | |
| 22 | `.tasks` | ✔ | — | Text only (note: image) |
| 23 | `.task` | ✔ | — | Lists tasks here |
| 24 | `.task <n>` | ✔ | — | Room sees "started" |
| 25 | `.task answer` / reply | ✔ | — | Room sees "completed" |
| 26 | `.task next` | ✔ | — | |
| **E. Impostor** | | | | |
| 27 | `.kill` | ✔ | — | Victim, witness, room DMs |
| 28 | `.vent` | ✔ | — | Room sees "used a vent" |
| 29 | `.sabotage` | ✔ | ✔ | World event to all |
| 30 | `.follow` / `.unfollow` | ✔ | — | |
| **F. Reports & meetings** | | | | |
| 31 | `.report` | ✔ | ✔ | Extra "reported" group line |
| 32 | `.meeting` | ✔ | ✔ | |
| 33 | `.say` | ✔ | ✔ | Relays to group |
| 34 | `.vote` | ✔ | ✔ | Shared state |
| 35 | Voting opens / 10 s / result | ✔ | ✔ | 4 s staged |
| **G. Sabotage events & repairs** | | | | |
| 36 | Sabotage announce / warn / repair / fail | ✔ | ✔ | |
| 37 | Lights repair | ✔ | — | |
| 38 | Comms repair | ✔ | ✔ | Answer in group |
| 39 | O₂ / Reactor paired scan | ✔ | — | |
| **H. End & ghosts** | | | | |
| 40 | Match over | ✔ result | ✔ | |
| 41 | Ghosts | ✔ | ghost group | |
| 42 | Errors & silence | ✔ | ✔ | |

---

# A. LOBBY (group commands)

### 1. `.amongus on` / `.amongus off` (Baron+, per group chat)
- **DM:** `⚠️ _.amongus on/off needs to be sent in the group chat, not a DM._`
- **GROUP:** ON → `🔪 *Among Us mode ON.*` / `.lobby open to host a game, or .join if one's already open.` / `_.amongus off to turn it off for this group._`
  OFF → `👋 *Among Us mode OFF.*` (group-wide: this GC's Among Us mode is off; it does not remove one player)
- **Extra:** per GC like the other pool commands, not per player. Per-player pause is `.pokemon on/off` (DM) only. In a group, the bot's JS toggle may swallow `.amongus on` before Python sees it.
- **New DM:**
- **New GROUP:** ✅ IMPLEMENTED (N1). ON → `🔪 *Among Us mode ON.*` / `Use *.lobby open* to host a game, or *.join* to enter an open lobby.` / `Use *.amongus off* to turn it off for this group.`

### 2. `.lobby open`
- **DM:** `⚠️ _.lobby open needs to be sent in the group chat, not a DM._`
- **GROUP:**
  ```
  🛰️ *Lobby #{id} opened.*
  Map: *{map}* (default)
  .join to enter ({MIN}-{MAX} players).
  Host: send *.lobby start* once ready.
  ```
- **Extra:** errors `⚠️ _A game is already running in this group._` / `⚠️ _A lobby's already open. .join it instead._`. **No lobby artwork sent** (note: large preview).
- **New DM:**
- **New GROUP:** ✅ IMPLEMENTED (N1). `🛰️ *Lobby #{id} opened.*` / `Map: *{map}*` / `Players: {n}/{MAX}` (host is already in, so it shows 1/{MAX}, not 0) / `Use *.join* to enter. The host can use *.lobby start* when at least {MIN} players have joined.`

### 3. `.join`
- **DM:** `⚠️ _.join must be sent in the game group chat._`
- **GROUP:** `✅ Joined. ({n}/{MAX})` + roster `1. Player 1 / 2. Player 2 …`
- **Extra:** errors `⚠️ _No open lobby right now. Ask someone to .lobby open._` / `_You're already in this lobby._` / `⚠️ _Lobby's full ({MAX} max)._`
- **New DM:**
- **New GROUP:** ✅ IMPLEMENTED (N1). `✅ *Player {n} joined the lobby.*` / `Players: {n}/{MAX}` / `*Lobby players*` + roster. Uses "Player N", never colours (colours are not assigned until start).

### 4. `.leave`
- **DM / GROUP:** `👋 _Left the lobby._`
- **Extra:** host leaves → `👋 Host left — *Player {n}* is now host.` + roster. Last leaves → `👋 _Last player left — lobby closed._`. Lobby inactivity → `_Lobby {id} has ended._`
- **New DM:**
- **New GROUP:** ✅ IMPLEMENTED (N1). `👋 You left the lobby.` (host handover / last-player / inactivity lines unchanged)

### 5. `.lobby list`
- **DM:** —
- **GROUP:**
  ```
  🛰️ *Lobby #{id}* — {n}/{MAX} players ({k} impostor(s) at this size)
  Map: *{map}*
  Host: Player {n}

  {roster}
  ```
- **Extra:** none open → `_No open lobby right now._`
- **New GROUP:** ✅ PARTLY (N1). None open → `🛰️ _There is no open lobby right now._` / `Use *.lobby open* to create one.` Open-lobby block unchanged.

### 6. `.lobby start` (host only)
- **DM (each player, role DM, with landscape stage image if ready):**
  - Impostor: `🔪 *You are the IMPOSTOR.*` / `Fellow impostor(s): {colours or none}` / `Your colour: *{colour}*` / `Starting room: *{room}*` / `Blend in, sabotage, eliminate.`
  - Scientist: `🧪 *You are the SCIENTIST (Crewmate).*` / colour / room / `Complete tasks and use .vitals or .witness to investigate.`
  - Crewmate: `👨‍🚀 *You are a CREWMATE.*` / colour / room / `Finish your tasks or vote out the impostor(s).`
- **GROUP:** `🚀 *Game live on {map}!* {n} players, {k} impostor(s).` / `Check your DM for your role.`
- **Extra:** errors `⚠️ _No open lobby._` / `⚠️ _Already started._` / `⚠️ _Only the host can start the game._` / `⚠️ _Need at least {MIN} players ({n}/{MIN})._`. **No quick command guide in the role DM. No ship map image sent.**
- **New DM:** ✅ IMPLEMENTED (N1). `🚀 *Your role: {IMPOSTOR | SCIENTIST (Crewmate) | CREWMATE}*` / `Colour: *{colour}*` / `Starting room: *{room}*` / Impostor only: `Fellow impostor(s): {colours or none}` / goal line (same wording as before) / `Use *.amenu* to view commands.`
- **New GROUP:** ✅ IMPLEMENTED (N1). `🚀 *Game live on {map}!*` / `Players: {n} · Impostors: {k}` / `Check your DM for your role and starting location.`

### 7. `.lobby test [crew|imp|sci]` (host)
- **DM:** —
- **GROUP:** `🧪 *Test mode* — you are the {ROLE}, with {n} silent dummy player(s) that don't move, task or vote.`
- **Extra:** `_Usage: .lobby test [crew|imp|sci]_`, `⚠️ _Only the host can start a test game._`
- **New GROUP:** ✅ IMPLEMENTED (N1). `🧪 *Test mode started.*` / `Role: *{ROLE}*` / `Dummy players: {n}` / `_Dummy players do not move, complete tasks, or vote._`

### 8. `.endgame` (host)
- **DM:** —
- **GROUP:** `🛑 _The host ended the match._`
- **Extra:** `⚠️ _There is no running game to end._` / `⚠️ _Only the host can end the game._`. Cancels meeting, sabotages, timers; no result DMs.
- **New GROUP:** ✅ IMPLEMENTED (N1). `🛑 *Match ended by the host.*` / `No winner was declared.`

### 9. `.amenu`
- **DM / GROUP:** same text:
  ```
  *Among Us — Commands*

  *Setup (group chat):*
  .amongus on / off  _(Baron+, for the whole group)_
  .lobby open
  .join / .leave
  .lobby list
  .lobby start  _(host only, {MIN}+ players)_
  .lobby test [crew|imp|sci]  _(host, solo test with dummies)_
  .endgame  _(host only, stops the match)_
  .pokemon on / off  — pause your Pokémon commands _(DM)_

  *In-game (DM Ariel):*
  .m  — list rooms
  .m <room or number>  — move
  .stop  — stop at your exact position
  .goback  — return to the reference room
  .where  — your current location
  .map    — the map and your exits
  .status  — people and bodies here
  .task  — list eligible tasks here
  .task <n>  — start a task interaction
  .task answer <answer>  — answer it in DM
  Reply to the task prompt or use .task next to switch tasks
  .tasks  — your tasks / available ghost tasks
  .progress  — task progress bar
  .players  — who's still alive
  .kill <colour>  — kill _(impostor)_
  .vent / .vent in / .vent <room> / .vent out  _(impostor)_
  .vitals / .witness  — Scientist only
  .sabotage lights|communications|oxygen|reactor  _(impostor)_
  scan  — reply scan to a bot message during O₂ / Reactor sabotage
  .ready  — optional O₂ repair countdown (3-2-1)
  .cooldown / .CDs  — your cooldowns
  .follow <colour> / .unfollow
  .cscene (.crimescene / .cs)  — reported crime-scene history
  .report  — report a body
  .meeting  — emergency meeting
  .vote <colour> / .vote skip  _(DM or GC)_
  .say <message>  — speak in a meeting as your colour (DM); ghosts: ghost chat
  .GC  — link to your game group
  .dm  — link to your DM with Ariel

  *Utility (anywhere):*
  .groupid  — get JID / LID of this chat
  ```
- **Extra:** note wants this split into General / Special commands.
- **New DM:**
- **New GROUP:**

### 10. `.GC` / `.dm`
- **DM / GROUP:** `.dm` → `💬 *Your DM with Ariel:*` + real link. `.GC` → `🎮 *Your game group:*` + real link.
- **Extra:** `⚠️ _You're not in an Among Us game._` / `⚠️ _You're in more than one Among Us game. Send .GC in the game group you mean._`
- **New:**

---

# B. MOVEMENT (DM)

### 11. `.m`
- **DM:**
  - No room → `*Rooms:*` + `1. {Room}` list
  - Start → `🚶 Heading to *{Room}* (~{n}s).`
  - **Arrival:**
    ```
    You have arrived at {Room}.
    {Name} arrived beside you.     ← only if they arrived within 1 s
    Players: {A}, {B}, you
    Use .tasks to see available tasks.
    Use .status to observe the room.
    ```
  - Passing a room → `🚶 You passed through {Room}.`
- **GROUP:** —
- **Extra (DMs to other players, by awareness):**
  - arrives: `🚶 {Name} arrived beside you.` · `*{who}* has arrived at *{Room}*.` · `🚶 You are passing through *{Room}*.`
  - leaves: `🚪 *{Name}* left *{Room}*.` · `*{who}* has left *{Room}*.`
  - nearby: `👀 Nearby room update: {A player} left/arrived in {Room}.`
  - corridor: `🚶 You encountered *{Name}* in the *{A–B}* corridor.`
  - lingering: `👀 *{Name}* seems to be lingering in *{Room}*.` · camping: `👀 *{Name}* has been stationary here for a while.` (camper: `👀 The other players are onto you. You've been here for a while.`)
  - Lights on: names show as "Someone".
  - errors: `⚠️ _Pick a number between 1 and {n}._` · `⚠️ _Unknown room._` + list · `⚠️ _You can't move while in a vent._` · `⚠️ _You're already moving._` · `_You're already in {Room}._` · `⚠️ _No route found._`
- **New DM:** ✅ IMPLEMENTED (N2). No room → `*Available rooms*` + numbered list + `Send *.m <room name or number>* to move.` (also under `⚠️ _Unknown room._`). Start → `🚶 Heading to *{Room}* (about {n}s).` / `Use *.stop* to stop at your current position.` Arrival text, passing-room text and all errors unchanged.
- **New other-player DMs:** Unchanged in N2.

### 12. `.stop`
- **DM:** `🛑 You stopped in *{Room}*.` or `🛑 You stopped between *{A}* and *{B}*.`
- **GROUP:** —
- **Extra:** `_You're not moving._` · `⚠️ _You can't stop while in a vent._`
- **New DM:** ✅ IMPLEMENTED (N2). `🛑 You stopped in *{Room}*.` or `🛑 You stopped between *{A}* and *{B}*.` + `Use *.where* to check your position.`

### 13. `.goback`
- **DM:** `↩️ Returning to *{Room}* (~{n}s).`
- **GROUP:** —
- **Extra:** `_You're already going back to {Room}._` · `⚠️ _You can't go back while in a vent._` · `⚠️ _No route back from your current position._`
- **New DM:** ✅ IMPLEMENTED (N2). `↩️ Returning to *{Room}* (about {n}s).`

### 14. `.where`
- **DM:** `You are currently at the {Room}.` / `Use .tasks to see available tasks.`
- **GROUP:** —
- **Extra:** waiting to leave `…; you'll leave in about {n}s.` · corridor `🚶 Travelling between *{A}* and *{B}* ({n}s along the corridor).` · vent `🌀 In a vent (~{n}s).`
- **New DM:** ✅ IMPLEMENTED (N2). `📍 *Your location*` then: `*{Room}*` · waiting to leave → `*{Room}*` / `Leaving in about {n}s.` · corridor → `Between *{A}* and *{B}*` / `{Travelling|Stopped} ({n}s along the corridor).` · vent → `🌀 In a vent (~{n}s).` The old "Use .tasks" hint line is gone (draft has none).

### 15. `.map`
- **DM:** map image with caption:
  ```
  {Map name}
  You are currently at the {Room}.     (or "between X and Y" / "inside a vent at X")
  {n}/{m} players left
  Exits: {Room} ({n}s), …
  Use .m <room> to move.
  ```
- **GROUP:** —
- **Extra:** no "you are here" dot. Before the match: `🗺️ *{MAP}*` / `_The match has not started yet. Your starting room is_ *{Room}*.`
- **New DM:** ✅ PARTLY (N2). Before the match only: `🗺️ *{Map}*` / `The match has not started yet. Your starting room is *{Room}*.` In-match `.map` caption unchanged.

---

# C. INFO (DM)

### 16. `.status`
- **DM:** stage-card image (caption = text):
  ```
  Role: {Crewmate | Impostor | Scientist}
  Status: {Alive | Ghost}
  Location: {Room or corridor}
  Players with you:
  - {Name}
  Cooldowns: Use .cds to check
  Match: {In progress | Meeting | Ended}
  Bodies here: {colours}        (or "No bodies are visible here.")
  Following you: {colour}       (only if followed)
  ```
- **GROUP:** —
- **Extra:** no `YOUR STATUS` title. In vent: `🌀 _You're inside a vent; there is no room status to check._` · you spot a follower: `👀 You noticed *{Name}* following you.` (they get `👀 *{Name}* noticed you following.`)
- **New DM:** ✅ IMPLEMENTED (N2). `📍 *YOUR STATUS*` / `Role:` / `Status:` / `Location:` / `Players with you: {others or None}` (you are no longer in the list) / `Bodies here: {colours or None}` / `Match:` / `Cooldowns: use *.cds*` / `Following you:` only if followed. Vent and follower-notice lines unchanged. Bodies line now always shows (also in corridors).

### 17. `.cds` / `.cooldown`
- **DM:**
  ```
  *Your Cooldowns*
  • Task: {n}s | Ready
  • Kill / Vent: …                  (Impostor)
  • Lights / Communications / Oxygen / Reactor sabotage: …   (Impostor)
  • Vitals / Witness: …             (Scientist)
  ```
  Ghost: `• Ghost task: …`
- **GROUP:** —
- **New DM:**

### 18. `.players`
- **DM:** `*Players ({n} alive):*` + `👨‍🚀 {Colour}` (dead: `~{Colour}~`)
- **GROUP:** —
- **Extra:** frozen at the pre-sabotage list during Comms.
- **New DM:** ✅ PARTLY (N2). Header is now `*Players still alive ({n}):*`. The list is unchanged: alive `👨‍🚀 {Colour}`, dead `~{Colour}~`. Comms still freezes it. NOTE: dead names still listed under a "still alive" header; say if you want them removed.

### 19. `.progress`
- **DM:** `*<[{percentage}%]>*`
- **GROUP:** —
- **Extra:** Impostors and Comms outages see a corrupted number.
- **New DM:** ✅ IMPLEMENTED (N2). `*Team task progress*` / `{done}/{total} tasks complete ({pct}%).` Impostor gets a fake % with a matching done/total. During Comms: header + the garbled `*<[..]>*` reading only, no task counts.

### 20. `.cscene` / `.crimescene` / `.cs`
- **DM:** `*Reported Crime Scenes*` / `1. {Room} — {Victim}`
- **GROUP:** —
- **Extra:** `_No reported crime scenes yet._`
- **New DM:** ✅ IMPLEMENTED (N2). Empty → `*Reported Crime Scenes*` / blank line / `_No reported crime scenes yet._` List format unchanged.

### 21. `.vitals` / `.witness` (Scientist)
- **DM:** Vitals → `*Vitals*` + `{Colour} — Dead — Ejected | Reported | Witnessed | Unreported`. Witness → `*Corpse witnesses*` + `*{Colour} (reporter)*` / `{Victim}: {witnesses or no witnesses recorded}`; none → `No corpse records.`
- **GROUP:** —
- **Extra:** `🔒 _This command is for the Scientist only._` · `⏳ _Vitals cooldown: {n}s._` · `⏳ _Witness cooldown: {n}s._`
- **New DM:** ✅ PARTLY (N2). Non-Scientist → `🔒 _This command is available to the Scientist only._` (both commands). Vitals/Witness output unchanged.

---

# D. TASKS (DM)

### 22. `.tasks`
- **DM:**
  ```
  📋 *TASKS LIST*

  Your tasks                ("Fake tasks" for an Impostor)
  1. {Task} — {Room}

  General tasks             (only while a sabotage is active)
  1. {Station label} — {Room}

  Finished tasks
  - ~{Task}~
  ```
- **GROUP:** —
- **Extra:** `All your assigned tasks are complete!` (Impostor: `All your fake tasks are logged.`). Ghost: `*Ghost tasks ({done}/{total} team tasks complete):*` + `{n}. {Task} — {Room} ({owner colour})`. Text only; note wants a big image.
- **New DM:** ✅ IMPLEMENTED (N3). Section titles are bold: `*Your tasks*` (`*Fake tasks*` for Impostor), `*General tasks*` (only during a sabotage), `*Finished tasks*` — which now always shows, with `None` when nothing is finished. Rest of the layout and the Ghost list unchanged. Text only; no image.

### 23. `.task` (list what is here)
- **DM:** `*Tasks here:*` / `1. {Task}` (ghost: `*Available ghost tasks:*`)
- **GROUP:** —
- **Extra:** `_Nothing to do here._` · `_No available team tasks remain._` · `⏳ _{label} cooldown: {n}s._`
- **New DM:** ✅ IMPLEMENTED (N3). `*Tasks here: {Room}*` + numbered list + `Send *.task <number>* to start one.` Ghost: `*Available ghost tasks*` + list + the same send line. Empty/cooldown lines unchanged.

### 24. `.task <n>` (start)
- **DM:**
  ```
  🧩 *{Task}*
  {puzzle prompt}

  Reply to this message with your answer, or send `.task answer <answer>`.
  _This interaction expires after 60s without activity._
  [Task Ref: I{n}]
  ```
- **GROUP:** —
- **Extra (room DM):** `🔧 *{Colour}* started *{Task}* in *{Room}*.` · `🔧 *{Colour}* began working on *{Task}* in *{Room}*.` Ghost start: `👻 The Crewmate task list has been updated.`
  Errors: `⚠️ _Invalid task number. Use `.task` to list eligible tasks._` · `⚠️ _You can only start an assigned task in its room._` · `⚠️ _That task is already in progress._` · `⚠️ _Can't start a task while moving or inside a vent._` · `⚠️ _Tasks can't be started or switched during a meeting._` · `You already have an active task in progress. Type ".task next" to abandon your current task and begin your next task.`
  **Puzzle prompts:**
  - Wiring: `🔌 Fix Wiring: left wires are RED, BLUE, GREEN, YELLOW. Right terminals are numbered top-to-bottom: 1=… Reply with the right-terminal numbers matching the left wires, in order.`
  - Engine/Reactor: `⚡ Restore the sequence in order: … Reply with the four digits in order.`
  - Course: `🧭 Chart this course in order: … Reply with the four directions.`
  - Asteroids: `☄️ Count the asteroids in this field: … Reply with the number.`
  - Upload: `📡 Upload checksum: add {a} + {b} + {c}. Reply with the total.`
  - Shields: `🛡️ Prime the active shield panels: … Reply with the panel letters.`
  - Card: `💳 Swipe the card through the reader. Reply `SWIPE` when done.`
  - Garbage: `🗑️ Pull the chute lever to empty the garbage. Reply `PULL`.`
  - Medical: `🩺 Hold still for the scan, then reply `SCAN`.`
  - Other: `🔧 Complete the task and reply `DONE`.`
- **New DM:** ✅ IMPLEMENTED (N3). Same prompt as before, but the command is now bold, not in backticks: `Reply to this message with your answer, or send *.task answer <answer>*.` `[Task Ref: I{n}]` stays (needed to match replies). Puzzle prompts, room DMs and errors unchanged.

### 25. `.task answer <answer>` / reply to prompt
- **DM:** wrong → `❌ _That answer doesn't match. Try again before the inactivity timer expires._` · right → `✅ *{Task}* complete. {n} of your tasks remain.` (or `All your assigned tasks are complete.`) + `Team progress: {done}/{total} tasks.` · Impostor fake → `✅ *{Task}* logged. {n} fake task(s) remain.`
- **GROUP:** —
- **Extra (room DM):** `✅ *{Colour}* completed *{Task}* in *{Room}*. Team tasks: {done}/{total}.` · `✅ *{Colour}* finished working on *{Task}*.`
  Ghost: `👻 ✅ Task complete. {n} team task(s) remain.` / `All team tasks are complete.` · owner `👻 A Ghost completed your *{Task}* task.` · other ghosts `👻 Team task progress was updated.`
  Errors: `⚠️ _Include an answer, or quote-reply with one._` · `⚠️ _Finish your move before completing the task._` · `⚠️ _Tasks can't be completed during a meeting._` · `_No active task interaction. Use `.task` to start one._` · `_That task prompt is stale. Start or check a task with `.task`._` · `_That task interaction is already complete; duplicate reply ignored._` · `_That reply belongs to an older task prompt. Reply to the current prompt._` · `📎 _Quote-reply to the task prompt, or use `.task answer <answer>`._` · plain text mid-task `📎 _Reply to your quoted task prompt, or use `.task answer <your answer>`._`
- **New DM:** ✅ IMPLEMENTED (N3). Wrong → `❌ _That answer doesn't match. Try again before the timer expires._` Right (crew) → `✅ *{Task}* complete.` / `Tasks remaining: {n}` / (if 0: `All your assigned tasks are complete.`) / `Team progress: {done}/{total}.` Impostor fake and Ghost wording unchanged. Repair-puzzle wrong-answer text unchanged.

### 26. `.task next` and interaction endings
- **DM:** `_No other eligible task is available here; your current interaction is still active._` · `↪️ The previous task interaction was abandoned.`
- **GROUP:** —
- **Extra (task ended early):** `⏱️ Your task interaction expired after a minute without activity.` · `🚶 Moving cancelled your task interaction; the task is still unfinished.` · `🌀 Entering the vent cancelled your task interaction.` · `👋 Leaving the game cancelled your active task interaction.` · `⚠️ Your task interaction was cancelled.`
  Repair versions: `⏱️ Your repair interaction expired…` · `🚶 Moving cancelled your repair interaction.` · `🌀 Entering the vent cancelled your repair interaction.` · `👋 Leaving the game cancelled your repair interaction.` · `💀 Your repair interaction ended when you died.` · `⚠️ Your repair interaction was cancelled.`
- **New DM:** ✅ IMPLEMENTED (N3). `.task next` now really sends `↪️ Previous task interaction abandoned. The task remains unfinished.` (before, the old text existed but was never sent on `.task next`), then the new prompt. Timeout → `⏱️ Your task interaction expired after 60 seconds without activity. The task remains unfinished.` Movement/vent/left-game/repair lines unchanged.

---

# E. IMPOSTOR (DM)

### 27. `.kill <colour>`
- **DM (killer):** `🔪 _Attempting to eliminate {Colour}. Stay still for 5s; movement cancels it._`
- **DM (victim, when it resolves):** `💀 You've been eliminated.` / `You're a ghost now — use *.say <message>* to talk to other ghosts.`
- **GROUP:** —
- **Extra:**
  - Witness DM: `😱 They killed a Crewmate (*{Colour}*). You witnessed a murder!`
  - Others in room DM: `⚠️ There seems to be distress in the room. Use .status to check.`
  - **Body found DM:** `You have found a corpse.` / `Use .report to call meeting`
  - Cancelled: `⚠️ Your movement cancelled the pending kill.` · `⚠️ {Colour} moved; your pending kill was cancelled.` · `🚨 The meeting interrupted your pending kill.`
  - Errors: `⚠️ _You must be in a room to kill._` · `⚠️ _Finish or stop moving before attempting a kill._` · `⚠️ _You can't kill during a meeting._` · `_You already have a kill resolving._` · `⏳ _Kill on cooldown ({n}s left)._` · `_No eligible Crewmate is here._` · `⚠️ _They're not here._` · `⚠️ _Too crowded — use .kill <colour> to choose a target._`. Non-Impostor: no reply.
  - No designed "kill succeeded" reply for the killer yet.
- **New killer DM:** ✅ IMPLEMENTED (N4). `🔪 Attempting to eliminate *{Colour}*. Stay still for {n}s; movement cancels the attempt.` ({n} is the live kill delay; timers NOT changed, decision 2 still open.) Cancels → `⚠️ Your pending kill was cancelled because {you moved | {Colour} moved | a meeting was called}.` No "kill succeeded" DM was designed, so none was added.
- **New victim DM:** ✅ IMPLEMENTED (N4). `💀 You've been eliminated.` / `You're now a Ghost. Use *.say <message>* to talk to other ghosts.` Killer is not named.
- **New witness / room DMs:** ✅ PARTLY (N4). Witness → `😱 You witnessed a murder involving *{Colour}*.` ({Colour} = the VICTIM, as before; the killer is not named). Distress, corpse-found and error lines unchanged.

### 28. `.vent`
- **DM:** status `*Vent available in {Room}.* Connections: {rooms}.` / `Use .vent in to enter.` (+ ` Vent cooldown: {n}s.`) · in `🌀 _You entered the vent at {Room}. You have 15s before automatic ejection._` · inside `🌀 *Inside the vent at {Room}.*` / `Connections: {rooms}` / `Use .vent <destination> or .vent out. Ejection in ~{n}s.` · travel `🌀 _You travelled through the vent to {Room}. {n}s remain before ejection._`
- **GROUP:** —
- **Extra:** room DM `🌀 *{Colour}* has used a vent.` · arrival `🌀 *{Name}* arrived from a vent.` · follower `🌀 *{Name}* entered a vent. You lost their trail.` · errors `_No vent here._` · `_You're already inside a vent._` · `⚠️ _That vent is not connected._` · `⚠️ _Use .vent in to enter a vent._` · `⚠️ _You're mid-move._` · `⏳ _Vent on cooldown ({n}s left)._`
- **New DM:** ✅ PARTLY (N4). `.vent in` → `🌀 You entered the vent at *{Room}*. You have {n}s before automatic ejection.` Other vent lines unchanged.

### 29. `.sabotage <lights|communications|oxygen|reactor>`
- **DM (Impostor):** `{Name} sabotage initiated.`
- **GROUP:** world event, see item 36.
- **Extra:** `⚠️ _Use .sabotage lights, .sabotage communications, .sabotage oxygen, or .sabotage reactor._` · `⏸️ _Sabotage is unavailable during a meeting._` · `⚠️ _{Name} sabotage is already active._` · `⏳ _{Name} sabotage cooldown: {n}s._` · non-Impostor: no reply.
- **New DM:** Not in the drafts; unchanged.

### 30. `.follow <colour>` / `.unfollow`
- **DM:** `🚶 Trailing *{Colour}*...` + `_You are now tailing {Colour}._` · ends `_You have lost their trail._` · `_You stopped following {Colour}._`
- **GROUP:** —
- **Extra:** target after 25 s `👀 You are being followed by *{Name}*.` · `👀 *{Name}* lost your trail.` · `👀 *{Name}* loses interest and stops following.` · while trailing `🚶 *{Colour}* is leaving *{Room}*.` / `🚶 Trailing...` / `📍 *{Colour}* has arrived at *{Room}*.` · errors `_Usage: .follow <colour>_` · `⚠️ _Can't follow them._` · `⚠️ _You need to be nearby to follow them._` · `_You're not following anyone._`
- **New DM:** ✅ PARTLY (N4). `.follow` → `🚶 You are now following *{Colour}*.` / `Use *.unfollow* to stop.` The separate `🚶 Trailing *{Colour}*...` DM (when the target is already moving) and all other follow lines are unchanged; the "noticed" lines already matched the draft.

---

# F. REPORTS & MEETINGS

### 31. `.report`
- **DM:** errors only: `⚠️ _Only a living player can report a body._` · `⚠️ _A meeting is already in progress._` · `_You need to be in a room to report a body._` · `_You haven't witnessed a reportable body here._`
- **GROUP:** first `📢 *{Colour}* reported a witnessed body in *{Room}*.` / `Victim(s): *{Colour}*.` then the body-report meeting call (item 32).
- **Extra:** only the player who witnessed the body can report it. The 📢 group line is not in the note.
- **New GROUP:** ✅ IMPLEMENTED (N5). The separate `📢 … reported a witnessed body` line is DROPPED (it was not in your original note); its room and victim now sit in the single meeting-call message (item 32). No-body error now `⚠️ _You haven't witnessed a reportable body here._`

### 32. `.meeting` and the meeting call
- **DM (to every living player, group link added):**
  - Emergency: `🚨 *{Colour} called an emergency meeting.*` / `Use .say to participate from your DM,` / `or join directly:` + group link
  - Body: `🚨 *{Colour} found a corpse!*` / (same two lines)
- **GROUP (caller's mini-preview, DM link added):**
  - Emergency: `🚨 *{Colour} called an emergency meeting!*` / `Interact with others here,` / `or participate from your DM using .say:`
  - Body: `🚨 *{Colour} found a corpse!*` / (same two lines)
- **Extra:** errors `⚠️ _A meeting's already in progress._` · `⚠️ _Only a living player can call a meeting._`. No limit on emergency meetings. A pending kill is cancelled; vent occupants are pulled out.
- **New DM:** Unchanged in N5 (voters keep `🚨 *{Colour} found a corpse!*` / `called an emergency meeting.` + `Use .say to participate from your DM,` / `or join directly:` + link).
- **New GROUP:** ✅ IMPLEMENTED (N5). Body: `🚨 *{Colour} found a corpse in {Room}!*` / `Victim: *{Victim}*` (`Victims:` if several) / blank / `Meeting started. Discuss here or use *.say <message>* from DM.` Emergency: `🚨 *{Colour} called an emergency meeting!*` / `Discuss the situation here, or use *.say <message>* in DM to speak as your colour.` The real DM link and the mini-preview image are still attached by the bot as before.

### 33. `.say <message>` (meeting)
- **DM:** errors `💬 _Use .say <message> to speak in the meeting._` · `⚠️ _Only players in this meeting can speak in it._` · `💬 _.say works during meetings. Ghosts use it in the Ghosts group._`
- **GROUP:** `🗣️ *{Colour}:* {message}`
- **Extra — paused commands during a meeting** (`.m .stop .goback .vent .kill .task .follow .unfollow .report .meeting .sabotage .vitals .witness .ready`) → DM:
  ```
  ⏸️ _Game commands are paused during the meeting._
  _Use the meeting chat: discuss in the game group, send_ *.say <message>* _here to speak as your colour, and_ *.vote <colour>* _or_ *.vote skip* _once voting opens._
  ```
- **New:**

### 34. `.vote <colour>` / `.vote skip`
- **DM:** `🗳️ _Your vote is registered privately._` · changed `🗳️ _Your vote was changed. Your latest vote replaces the previous one._`
- **GROUP:** same, plus the group version of errors.
- **Extra:** `⚠️ _No active meeting._` · `⚠️ _Voting opens at 60 seconds._` · `⚠️ _Voting has closed._` · `⚠️ _Only active living players can vote._` · `_Usage: .vote <colour> or .vote skip_` · `⚠️ _Choose an active player's colour or skip._` · group: `⚠️ _That vote wasn't accepted. Choose an active player's colour or skip; for details, send the vote in DM._`
- **New DM:** Not in the drafts; unchanged.
- **New GROUP:** Not in the drafts; unchanged.

### 35. Voting timeline and result
- **DM @60 s (each voter):**
  ```
  🗳️ *Voting has been opened*
  Use .vote [colour] (for example *.vote {example}*) or .vote skip, or leave your vote uncast.
  You can change your vote until time runs out.
  ```
- **GROUP @60 s (hidetag + DM link):**
  ```
  🗳️ *Voting has been opened*
  Use .vote [colour] or .vote skip, or leave your vote uncast.
  Vote here, or privately through the DM link:
  ```
- **GROUP @80 s:** `⏰ *10 seconds remaining!* Cast your votes to remove the Impostor.`
- **GROUP @90 s (4 s apart):** `⏱️ *Meeting has ended.*` → `...` → `.......` → merged result (ejection mini-preview if someone was ejected):
  - `No one was ejected.` / `Carry on...`
  - `{C} was ejected.` / `{C} was not the Impostor.` / `{n}/{m} Impostors remain.` / `Carry on...`
  - `{C} was ejected.` / `{C} was an Impostor.` / `{n}/{m} Impostors remain.` / `Carry on...`
- **Extra:** count lines `All Impostors have been eliminated.` · `The Impostor has been eliminated.` · `{n}/{m} Impostor(s) remain(s).` · if the ejection ends the match, "Carry on..." is dropped and the match-over message follows.
- **New DM:** ✅ IMPLEMENTED (N5). Voting open → `🗳️ *Voting is open.*` / `Use *.vote <colour>* or *.vote skip*. You can change your vote until voting closes.` (the "for example *.vote {colour}*" hint is gone).
- **New GROUP:** ✅ IMPLEMENTED (N5). Voting open → `🗳️ *Voting is open.*` / `Use *.vote <colour>* or *.vote skip*. You may also vote privately through DM.` (hidetag + DM link still attached). 10 s → `⏰ *10 seconds remaining!* Submit or change your vote before voting closes.` End → `⏱️ *Meeting ended.*` (was "Meeting has ended."). The `...` / `.......` suspense messages and the result lines are KEPT as they were, staged 4 s apart (decision 5 still open); they were not merged into one message.

---

# G. SABOTAGE EVENTS & REPAIRS

### 36. World event (GROUP + DM to every non-departed player, ghosts and Impostors too; DM copy gets the real group link)
- **Announce:**
  ```
  {emoji} *{NAME} SABOTAGED!*

  *Required stations:*
  - {Station label} — {Room}
  ```
  | Sabotage | Header | Stations |
  |---|---|---|
  | Lights | 💡 LIGHTS | Lights repair — Electrical |
  | Comms | 📡 COMMUNICATIONS | Communications repair — Communications |
  | O₂ | 💨 O₂ | Oxygen station — O2 · Oxygen station — Admin |
  | Reactor | ☢️ REACTOR | Reactor station — Upper Engine · Reactor station — Lower Engine |
- **Warnings (20 s and 10 s left):** `⚠️ *{Name} sabotage:* 20s remaining.` / `10s remaining.` (placeholder)
- **Repaired:** `✅ *{Name} sabotage repaired.*`
- **Failed:** Reactor `☢️ *Reactor meltdown — Impostors win*` · O₂ `🚨 *OXYGEN FAILURE!*` / `The oxygen tank has been used up!` / `*O₂ depleted — Impostors win*`
- **Extra:** no short-description line (none approved). Deadline is random 30–40 s for timed sabotages.
- **New announcement (per sabotage):** Unchanged in N6: `{emoji} *{NAME} SABOTAGED!*` / blank / `*Required stations:*` + station list. No short descriptions added (decision 3 still open).
- **New warnings / repaired / failed:** ✅ PARTLY (N6). Warning (20 s and 10 s, timings unchanged) → `⚠️ *{Name}: {n}s remaining.*` / `Reach the required station(s) and finish the repair.` Repaired → `✅ *{Name} sabotage repaired.* The ship is safe for now.` {Name} is Lights / Communications / O₂ / Reactor (the O₂ warning used to say "Oxygen"). FAILURE headlines NOT changed: the code marks the current Reactor and O₂ lines as your confirmed wording ("The oxygen tank has been used up!"), and the draft replaces them ("The oxygen supply has run out.", plus a full stop on the Reactor line). That decision belongs with match-over wording (N7); say which you want.

### 37. Lights repair (Electrical, DM)
- **DM:**
  ```
  🧩 *Lights repair*
  🔌 *Lights circuit* ({pattern} wiring)
  1🔴 2🟢 3🔴 …
  Goal: every switch 🟢. A switch can also flip others, so work out the wiring. Send a number from 1 to {n}.

  Reply to this message with a switch number (1-{n}), or send `.task answer <switch number>`.
  _This interaction expires after 60s without activity._
  [Task Ref: I{n}]
  ```
- **GROUP:** —
- **Extra:** room DM `🔧 *{Colour}* is working on the *Lights* circuit in *Electrical*.` · bad input `⚠️ _Send a switch number from 1 to {n}._` · solved `✅ _Circuit aligned. Lights repaired._`
- **New DM:** ✅ PARTLY (N6). The start prompt now reads `Reply to this message with a switch number from 1 to {n}, or use *.task answer <number>*.` (command bold, not in backticks; the circuit picture/goal text is shown as before, without repeating "Send a number from 1 to {n}." — that sentence stays on later press updates). I kept "Reply to this message" because a bare number is not accepted without a quote-reply or `.task answer`; the draft's "Send a switch number…" would have been inaccurate.

### 38. Communications repair
- **DM:** `🧩 *Communications repair*` / `📡 Unscramble the transmission:` / `*{SCRAMBLED}*` / `Answer *in the game group*: reply to the transmission message there, or send .task answer <phrase> there. Private answers are not accepted.` / `_This interaction expires after 60s without activity._`
- **GROUP:** `📡 *{Colour}* is repairing *Communications*.` / `Scrambled transmission: *{SCRAMBLED}*` / `_Only {Colour} can answer, here in the group: reply to this message with the phrase, or send .task answer <phrase>._` / `[Task Ref: I{n}]`
- **Extra:**
  - wrong: `❌ _That's not the intended phrase. Communications is still down; try again before the inactivity timer expires._` + `Transmission: *{SCRAMBLED}*`
  - right: `✅ _Transmission restored. Communications repaired._` (group, prefixed with the colour)
  - while down: non-command group messages are deleted (bot must be admin); lifted during meetings; `.players` frozen, `.progress` corrupted, passive awareness DMs dropped
  - after repair (GROUP): `📡 *Communications restored — activity report.*` / `Players inactive for over 60s during the outage:` / `• *{Colour}* — {where}, still for {n}s` / `_This is not proof of guilt._` (or `_Nobody stood still for over 60s._`)
- **New DM:** Unchanged in N6 (already says to answer in the game group; private answers refused).
- **New GROUP:** ✅ IMPLEMENTED (N6). `📡 *Communications repair*` / `Unscramble: *{SCRAMBLED}*` / `Only {Colour} can submit the answer in the game group. Reply to this transmission message or use *.task answer <phrase>*.` / `[Task Ref: I{n}]`. The old `📡 *{Colour}* is repairing *Communications*.` line is gone (the colour is in the "Only {Colour}" sentence).

### 39. O₂ / Reactor paired scan
- **DM:**
  - join a station (`.task`): `Waiting for partner.`
  - both seated, **O₂**: `✅ Both stations are ready!` / `Both players must reply scan to the bot message within 2 seconds of each other to fix oxygen.` / `Send .ready to begin the repair countdown.`
  - both seated, **Reactor**: `✅ Both stations are ready!` / `Both players must reply *scan* to a bot message within 2 seconds of each other to fix the reactor.`
  - `.ready` (O₂ only): `3` → `2` → `1` → `SCAN NOW!` (1 s apart, placeholder)
  - `scan`: first `📡 _Scan sent. Waiting for your partner's scan..._` · duplicate `📡 _Scan already sent. Waiting for your partner's scan._` · success `✅ Paired scan accepted. *{O₂|Reactor}* is repaired.` · missed `⌛ Scan window missed. Send *scan* again, together.`
  - leave a station: you `↩️ You left the *{Room}* station. Your scan attempt was cancelled.` · partner `Your partner left. Waiting for partner.`
- **GROUP:** — (events go through item 36)
- **Extra:** errors `⚠️ _Nothing to repair here._` · `⏸️ _Sabotage repairs are paused during the meeting._` · `⚠️ _Only living players can repair this._` · `⚠️ _You can't repair sabotage._` · `⚠️ _{label} needs a crew member at {A} or {B}._` · `⚠️ _Can't use a station while moving or inside a vent._` · `⚠️ _Someone is already at the {Room} station._` · `⚠️ _There is no countdown for this repair. Reply *scan* to a bot message._` · `⚠️ _You need to be at an oxygen station to start the countdown._` · `⏳ _The countdown is already running._` · `⚠️ _You're not at a repair station ({A} or {B})._` · plain `scan` that is not a reply is explained and not counted.
- **New DM:** ✅ PARTLY (N6). Missed window → `⌛ Scan window missed. Send *scan* again together when both stations are ready.` Everything else in item 39 unchanged.

---

# H. MATCH END, GHOSTS, ERRORS

### 40. Match over
- **DM (each player who didn't leave):**
  ```
  🏁 *Match over — {Crewmates win | Impostors win}.*
  You were *{Colour}*, {a Crewmate | the Impostor | the Scientist} ({Crewmates | Impostors}).
  🏆 *Your team won.*     or     💀 *Your team lost.*
  ```
- **GROUP:** headline then reveal
  - `🎉 *Crewmates win!* Every Impostor has been ejected.`
  - `🎉 *Crewmates win!* The last Impostor left the game.`
  - `🎉 *Crewmates win!* All team tasks are complete.`
  - `🔪 *Impostors win!* They equal or outnumber the crew.`
  - sabotage endings: see item 36
  - everyone left: `🏁 _The match ended: everyone left the game._`
  - reveal: `🔪 The Impostor was *{C}*.` / `🔪 The Impostors were *{A}*, *{B}*.`
- **Extra:** note format not applied: `🏆 CREWMATES WIN!` / `All Impostors have been eliminated.` / `The Impostors were:` / `Red`, and `🔴 IMPOSTORS WIN!` / `The Crewmates have been defeated.` / `The Impostor was: Red`. World-clock crash: `⚠️ _This match stopped because its world clock encountered an error._`
- **New DM:** ✅ IMPLEMENTED (N7). `🏁 *Match over — {Crewmates win! | Impostors win!}*` / `Your role: *{Crewmate | Scientist | Impostor}* ({Crewmates | Impostors}).` / `🏆 *Your team won.*` or `💀 *Your team lost.*` (the colour is no longer in this line).
- **New GROUP (per ending):** ✅ IMPLEMENTED (N7). Headline and reason on separate lines, a blank line, then the reveal: `🎉 *Crewmates win!*` / `Every Impostor has been ejected.` (or `The last Impostor left the game.` / `All team tasks are complete.`); `🔪 *Impostors win!*` / `They equal or outnumber the crew.`; Reactor `☢️ *Reactor meltdown — Impostors win.*`; O₂ `🚨 *OXYGEN FAILURE!*` / `The oxygen supply has run out.` / `*O₂ depleted — Impostors win.*`. "Everyone left" line unchanged. Reason wording is the existing wording, so decision 1 (per-ending wording) is still open.

### 41. Ghosts
- **DM:** allowed `.m .stop .goback .where .map .status .task .tasks .progress .cds .cooldown .say`; everything else ignored silently. Movement in a meeting: `⏸️ _Movement is paused during the meeting._` · `.say` with no text: `👻 _Use .say <message> to talk to other ghosts._`
- **GROUP (ghost group, or DM to each ghost if none):** `👻 *{Colour}:* {message}`
- **Extra:** ghosts can't vote; they travel at half time.
- **New:** ✅ IMPLEMENTED (N7). A ghost sending `.vote` during a meeting gets `👻 _Ghosts cannot vote._` (players who left keep `⚠️ _Only active living players can vote._`). Ghost chat line and ghost-allowed command list unchanged.

### 42. Errors and silence
- **DM:** `⚠️ _You're not in this game._` · `⚠️ _You have left this game._` · `⚠️ _You're in more than one Among Us game. Send this command in the correct game group so it reaches the right match._`
- **GROUP:** an Among Us command typed in the game group → `📩 _Game commands are private. Message Ariel directly; use .vote in the group during meetings._` Only `.vote` and the Comms answer work there.
- **Extra:** unknown commands get no reply at all.
- **New:** ✅ CHECKED (N7). Existing wording already matches the section G draft, so nothing changed.

---

# DECISIONS STILL NEEDED
1. Match-over wording per ending (item 40). 2. Kill timer: 5 s / 30 s (code) or 4 s / 5 s (note). 3. Short description per sabotage (item 36). 4. 20 s / 10 s warning wording. 5. Suspense messages 2 and 3 (now `...` and `.......`). 6. `YOUR STATUS` title on `.status`. 7. Meaning of "players left". 8. Role DM wording + quick command guide. 9. Keep or drop the 📢 group line on `.report`. 10. Final map name and station labels. 11. (decided N8: group only.) 12. (slots added N8; artwork links still to be pasted.)
---

# REPLY DESIGN DRAFTS — ORGANIZED ADDITIONS TO THIS COMMAND SHEET

**Status: APPROVED ("implement the note"). Sections A-G implemented (N1-N7).** These drafts fill gaps noted in the command sheet while preserving the original Package 13 snapshot above. They are design examples, not claims about current bot behavior. Dynamic values must be filled from live game state. Real group/DM links and map labels must come from the game configuration; never hard-code invented links.

## A. Lobby and setup reply designs — ✅ IMPLEMENTED (N1)

| Command / trigger | Surface | Proposed reply design / example | Notes |
|---|---|---|---|
| `.amongus on` | GROUP | `🔪 *Among Us mode ON.*\n\nUse *.lobby open* to host a game, or *.join* to enter an open lobby.\n\nUse *.amongus off* to turn it off for this group.` | Per-GC toggle (Baron+), not per player. DM gets the group-only error. Verify group toggle routing. |
| `.lobby open` succeeds | GROUP | `🛰️ *Lobby #{id} opened.*\nMap: *{map}*\nPlayers: 0/{MAX}\n\nUse *.join* to enter. The host can use *.lobby start* when at least {MIN} players have joined.` | Lobby artwork is a separate asset; send it only when available and approved. |
| `.join` succeeds | GROUP | `✅ *{Player/Colour} joined the lobby.*\nPlayers: {n}/{MAX}\n\n*Lobby players*\n{roster}` | Keep roster values dynamic. Do not expose hidden roles. |
| `.leave` during lobby | GROUP / DM | `👋 You left the lobby.` | If host leaves, follow with the existing host-handover message and updated roster. |
| `.lobby start` role delivery | DM | `🚀 *Your role: {ROLE}*\nColour: *{Colour}*\nStarting room: *{Room}*\n\n{role-specific objective}\n\nUse *.amenu* to view commands.` | Proposed quick guide link-in; role-specific objective must not reveal hidden information to others. |
| `.lobby start` succeeds | GROUP | `🚀 *Game live on {map}!*\nPlayers: {n} · Impostors: {k}\nCheck your DM for your role and starting location.` | Decide separately whether ship map is sent to group, DMs, or both. |
| `.lobby list` with no lobby | GROUP | `🛰️ _There is no open lobby right now._\nUse *.lobby open* to create one.` | Slightly more actionable version of current wording. |
| `.lobby test` succeeds | GROUP | `🧪 *Test mode started.*\nRole: *{ROLE}*\nDummy players: {n}\n_Dummy players do not move, complete tasks, or vote._` | Host-only; do not present as a normal multiplayer match. |
| `.endgame` succeeds | GROUP | `🛑 *Match ended by the host.*\nNo winner was declared.` | Current snapshot says no result DMs. Keep that unless separately changed. |

## B. Movement and player information reply designs — ✅ IMPLEMENTED (N2)

| Command / trigger | Surface | Proposed reply design / example | Notes |
|---|---|---|---|
| `.m` with no destination | DM | `*Available rooms*\n{numbered room list}\n\nSend *.m <room name or number>* to move.` | Room names and numbering must come from the selected map. |
| `.m <destination>` begins | DM | `🚶 Heading to *{Room}* (about {n}s).\nUse *.stop* to stop at your current position.` | Estimate must reflect the actual route and movement state. |
| `.stop` succeeds | DM | `🛑 You stopped {in *{Room}* | between *{A}* and *{B}*}.\nUse *.where* to check your position.` | Select the correct branch from the authoritative position. |
| `.goback` succeeds | DM | `↩️ Returning to *{Room}* (about {n}s).` | `{Room}` must be the defined reference room, not a guessed destination. |
| `.where` | DM | `📍 *Your location*\n{Room or corridor/vent state}\n{movement status, if any}` | Avoid exposing another player's hidden role or intent. |
| `.map` before match start | DM | `🗺️ *{Map}*\nThe match has not started yet. Your starting room is *{Room}*.` | Attach the approved map image if available. |
| `.status` | DM | `📍 *YOUR STATUS*\nRole: {Role}\nStatus: {Alive/Ghost}\nLocation: {Room or corridor}\nPlayers with you: {visible names or None}\nBodies here: {visible bodies or None}\nMatch: {In progress/Meeting/Ended}\nCooldowns: use *.cds*` | Title is a decision item; this draft proposes `YOUR STATUS`. Visibility rules take priority. |
| `.players` | DM | `*Players still alive ({n}):*\n{alive player list}` | During Communications sabotage, use the existing restricted/frozen behavior, if verified. |
| `.progress` | DM | `*Team task progress*\n{done}/{total} tasks complete ({percentage}%).` | Do not expose a reliable number to players who should see corrupted progress during Comms. |
| `.cscene` with no records | DM | `*Reported Crime Scenes*\n\n_No reported crime scenes yet._` | Show only persistent, reported crime scenes; do not imply the viewer knows the killer. |
| `.vitals` / `.witness` by non-Scientist | DM | `🔒 _This command is available to the Scientist only._` | Existing error already communicates this; retain if preferred. |

## C. Task interaction reply designs — ✅ IMPLEMENTED (N3)

| Command / trigger | Surface | Proposed reply design / example | Notes |
|---|---|---|---|
| `.tasks` | DM | `📋 *TASKS LIST*\n\n*Your tasks*\n{numbered tasks with room and status}\n\n*General tasks*\n{active sabotage repair tasks, if any}\n\n*Finished tasks*\n{completed task list or None}` | Text layout first; TASKS LIST artwork is a separate unresolved asset decision. |
| `.task` with tasks here | DM | `*Tasks here: {Room}*\n{numbered eligible tasks}\n\nSend *.task <number>* to start one.` | If none: `_Nothing to do here._` Do not make `.task` itself complete a puzzle. |
| `.task <n>` begins | DM | `🧩 *{Task}*\n{actual puzzle instructions}\n\nReply to this message with your answer, or send *.task answer <answer>*.\n_This interaction expires after 60s without activity._` | Must use the real puzzle prompt and answer validation. |
| Task answer is wrong | DM | `❌ _That answer doesn't match. Try again before the timer expires._` | Do not mark task complete or increase progress. |
| Task answer is correct | DM | `✅ *{Task}* complete.\nTasks remaining: {n}\nTeam progress: {done}/{total}.` | All values dynamic. Impostor fake-task wording remains distinct. |
| `.task next` abandons current task | DM | `↪️ Previous task interaction abandoned. The task remains unfinished.` | Must not falsely award completion. |
| Task interaction times out | DM | `⏱️ Your task interaction expired after 60 seconds without activity. The task remains unfinished.` | Consistent with the existing timeout design. |

## D. Impostor and following reply designs — ✅ IMPLEMENTED (N4)

| Command / trigger | Surface | Proposed reply design / example | Notes |
|---|---|---|---|
| `.kill <colour>` begins | DM to Impostor | `🔪 Attempting to eliminate *{Colour}*. Stay still for {timer}s; movement cancels the attempt.` | Timer is unresolved in the source notes; do not choose a final value until the decision is made. |
| Kill resolves | DM to victim | `💀 You've been eliminated.\nYou're now a Ghost. Use *.say <message>* to talk to other ghosts.` | Private message; do not reveal the killer automatically. |
| Kill witnessed | DM to witness | `😱 You witnessed a murder involving *{Colour}*.` | Only send if the game rules say this player actually witnessed it. |
| Kill attempt cancelled | DM to Impostor | `⚠️ Your pending kill was cancelled because {reason}.` | `{reason}` may be movement or a meeting interrupt; choose the correct one. |
| `.vent in` succeeds | DM to Impostor | `🌀 You entered the vent at *{Room}*. You have {n}s before automatic ejection.` | Use the live remaining time. |
| `.follow <colour>` succeeds | DM to follower | `🚶 You are now following *{Colour}*.\nUse *.unfollow* to stop.` | Do not tell the target immediately unless the awareness rule triggers. |
| Following is noticed | DM to target | `👀 You noticed *{Name}* following you.` | Trigger only when the defined notice condition is met. |

## E. Reports, meetings and voting reply designs — ✅ IMPLEMENTED (N5)

| Command / trigger | Surface | Proposed reply design / example | Notes |
|---|---|---|---|
| `.report` when no reportable body | DM | `⚠️ _You haven't witnessed a reportable body here._` | Preserve rule that only the eligible discoverer can report that body. |
| Body report succeeds | GROUP | `🚨 *{Colour} found a corpse in {Room}!*\nVictim: *{Victim}*\n\nMeeting started. Discuss here or use *.say <message>* from DM.` | Whether the separate `📢 reported a witnessed body` line stays is still undecided. |
| Emergency meeting succeeds | GROUP | `🚨 *{Colour} called an emergency meeting!*\nDiscuss the situation here, or use *.say <message>* in DM to speak as your colour.` | No body or killer information should be invented. |
| `.say` during meeting | GROUP | `🗣️ *{Colour}:* {message}` | Keep sender colour tied to the active player. |
| Voting opens | DM | `🗳️ *Voting is open.*\nUse *.vote <colour>* or *.vote skip*. You can change your vote until voting closes.` | Keep exact timing governed by the agreed meeting timeline. |
| Voting opens | GROUP | `🗳️ *Voting is open.*\nUse *.vote <colour>* or *.vote skip*. You may also vote privately through DM.` | Add the real DM link only when available. |
| Ten seconds remain | GROUP | `⏰ *10 seconds remaining!* Submit or change your vote before voting closes.` | Neutral wording; avoid telling players whom to vote for. |
| No one ejected | GROUP | `⏱️ *Meeting ended.*\nNo one was ejected.\nCarry on...` | Existing staged suspense messages may be retained if approved. |
| Player ejected | GROUP | `⏱️ *Meeting ended.*\n{Colour} was ejected.\n{Correct/Incorrect impostor reveal}\n{n}/{m} Impostors remain.` | The reveal branch must be based on actual role data. If match ends, send match-over flow instead of `Carry on...`. |

## F. Sabotage and repair reply designs — ✅ IMPLEMENTED (N6); failure headlines done in N7

| Command / trigger | Surface | Proposed reply design / example | Notes |
|---|---|---|---|
| Sabotage begins | GROUP + player DMs | `{emoji} *{SABOTAGE NAME} SABOTAGED!*\n\n{short effect description}\n\n*Required stations:*\n- {Station} — {Room}` | Short descriptions are not yet approved. Keep this generic until each sabotage description is decided. |
| Timed sabotage warning | GROUP + player DMs | `⚠️ *{SABOTAGE NAME}: {n}s remaining.*\nReach the required station(s) and finish the repair.` | Source has 20s and 10s placeholders; final timing/wording needs approval. |
| Sabotage repaired | GROUP + player DMs | `✅ *{SABOTAGE NAME} sabotage repaired.* The ship is safe for now.` | Use only when the repair is confirmed. |
| Reactor failure | GROUP + player DMs | `☢️ *Reactor meltdown — Impostors win.*` | Terminal outcome; stop other match timers. |
| O₂ failure | GROUP + player DMs | `🚨 *OXYGEN FAILURE!*\nThe oxygen supply has run out.\n*O₂ depleted — Impostors win.*` | Terminal outcome; stop other match timers. |
| Lights repair starts | DM | `🧩 *Lights repair*\n{switch puzzle}\n\nSend a switch number from 1 to {n}, or use *.task answer <number>*.\n_This interaction expires after 60s without activity._` | Must show actual generated switch pattern. |
| Communications repair starts | DM + GROUP | `📡 *Communications repair*\nUnscramble: *{SCRAMBLED}*\nOnly {Colour} can submit the answer in the game group. Reply to the transmission message or use *.task answer <phrase>*.` | Only the designated player can answer; private answers are not accepted under the current snapshot. |
| Paired scan misses window | DM to relevant players | `⌛ Scan window missed. Send *scan* again together when both stations are ready.` | Do not declare repair success unless both scans satisfy the timing rule. |

## G. Match end and Ghost reply designs — ✅ IMPLEMENTED (N7)

| Command / trigger | Surface | Proposed reply design / example | Notes |
|---|---|---|---|
| Match ends — player DM | DM to each player who did not leave | `🏁 *Match over — {Winning team} win!*\nYour role: *{Role}* ({Team}).\n{🏆 Your team won. / 💀 Your team lost.}` | Role and win/loss must be based on the final game state. |
| Match ends — Crewmates win | GROUP | `🎉 *Crewmates win!*\n{Reason for victory}\n\n{Impostor reveal}` | Use the correct reason: all Impostors ejected, last Impostor left, or all team tasks complete. |
| Match ends — Impostors win | GROUP | `🔪 *Impostors win!*\n{Reason for victory}\n\n{Impostor reveal}` | Include sabotage outcome when applicable. |
| Ghost chat message | Ghost group | `👻 *{Colour}:* {message}` | Living players must not receive ghost chat. If no ghost group exists, DM only ghosts as specified. |
| Ghost attempts to vote | DM | `👻 _Ghosts cannot vote._` | Proposed explicit reply; current snapshot says ghosts cannot vote but does not specify this reply. |
| Player is not in game / has left | DM | `⚠️ _You're not in this game._` / `⚠️ _You have left this game._` | Keep the existing wording unless a wording review changes it. |
| Private-only command used in game group | GROUP | `📩 _Game commands are private. Message Ariel directly; use .vote in the group during meetings._` | Preserve the allowed group exceptions for voting and Communications answers. |

## H. Decisions still open

These remain decisions, not silently resolved by the drafts above:

| Item | Open decision |
|---|---|
| 1 | Match-over wording per ending |
| 2 | Kill timer: command-sheet snapshot says 5 seconds; other design notes contain conflicting timing |
| 3 | Short description for each sabotage |
| 4 | Warning wording and exact 20s/10s warning behavior |
| 5 | Keep, revise, or remove the staged suspense messages `...` and `.......` |
| 6 | Approve or reject the `YOUR STATUS` title on `.status` |
| 7 | Exact meaning of `{n}/{m} players left` on map/status views |
| 8 | Final role DM wording and quick command guide |
| 9 | Keep or drop the separate `📢 reported a witnessed body` group line |
| 10 | Final map name, rooms, and station labels |
| 11 | ✅ DECIDED (N8): group only, attached to the "Game live" message |
| 12 | ✅ SLOTS ADDED (N8): `lobby` and `tasks_list` in image_links.json, blank for now. The artwork itself is still to be supplied (paste direct https links; no restart needed) |

---

**Editing rule:** The original command snapshot above is retained as source material. The tables in this addition are proposed player-facing designs for review; they do not replace source wording until approved. No placeholder reply is considered implemented merely because it appears here.

