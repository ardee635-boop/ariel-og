# Niflheim Among Us — Build Plan & Sessions

*Companion to Master Design & Merge Note v4. Status: design approved for build; Stage 1 leftovers resolved below. Newer user decisions override older proposals.*

## 0. Decisions closing out Stage 1

These are proposals to lock in so build can start. Change any of them before Session 1.

- **`.goback` timing:** return time equals seconds travelled since leaving the reference room. Position is stored as "N seconds along corridor X→Y", so the return trip is N seconds, not the time remaining to the original destination.
- **`.stop` while stationary:** harmless reply ("You're not moving."); the camping timer is untouched.
- **Timestamps:** all two-second windows (room events, paired scans, kill resolution) use the bot's own receive time, not WhatsApp delivery time.
- **Ghosts and camping:** ghosts never trigger camping awareness for living players and are never the "nearby observer".
- **Ghost chat command:** `.say` (replaces old `.c`).
- **Meeting vs. sabotage deadlines (decided for Session 6):** active O₂/Reactor countdowns pause until the meeting ends. Cooldowns keep running.
- **Camping during Communications sabotage:** a pending trigger is suppressed, not delayed; a fresh stop after repair starts a new timer.
- **Reactor:** deadline 30–40s random, same pairing mechanic as O₂, stations set from the final map.
- **Scientist assignment:** one Scientist at 7+ players, chosen randomly from Crewmates; none below 7. Tune later.

## 1. Architecture rules (apply to every session)

1. **World clock, not message-driven.** One authoritative world with a tick loop (about 1s). Movement, camping, cooldowns, deadlines and vent timers advance on ticks, never on a player's next command.
2. **Event log with timestamps.** Every world event is recorded with a time. Awareness is computed from the log and presence, never from notification order.
3. **Per-game state object, keyed by group.** No global lobby or game. Multiple groups can't collide.
4. **Per-player knowledge.** Authoritative state is separate from what each player has been told.
5. **One lock per game** around tick and command handling.
6. **Privacy by default.** Secret commands answer in DM only. Group output goes through a single sanitised broadcast path.
7. **All tuning numbers live in one config module** (cooldowns, durations, windows, task counts).
8. **Everything stops cleanly on game end.** No timer or pending event may act after the game is over.

## 2. Sessions

Each session ends with something runnable and a short test checklist. Don't start the next until the checklist passes.

### Session 1 — Core: map, world clock, lobby and game shell

- Final map module from Gemini: rooms, corridors with lengths, vent links, station rooms.
- Per-group lobby and game objects; join, leave, start, 4–20 players, impostor count, colour assignment.
- Config module; tick loop; per-game lock; clean shutdown.
- Router integration and Pokémon-mode isolation.
- **Test:** two groups run lobbies at once; a game starts and ticks with no commands sent.

### Session 2 — Movement and the living world

**Status: complete in the Session 2 handoff ZIP.**

- [x] Position model (in room, or N seconds along a corridor).
- [x] `.m`, `.stop`, `.goback` with the reference-room rules.
- [x] Departure boundary, arrival notices, two-second room-event window, simultaneous arrivals.
- [x] Corridor encounters.
- [x] **Test:** scripted timelines for crossing, passing, simultaneous arrival, stop mid-corridor, goback from mid-corridor and redirect.

### Session 3 — Awareness: status, camping, following, crime scenes

**Status: complete in `SESSION_3_HANDOFF.md`.**

- [x] `.status`, camping trigger, reset and once-per-stop warning.
- [x] `.follow`, `.unfollow`, 25s reveal, trail loss and end notices.
- [x] Body presence, witness records, `.cscene` with persistent reported history.
- [x] **Test:** camping waits for an observer; follow survives a room change and ends on a vent or a still action.

### Session 4 — Roles, kills, vents, privacy layer

**Status: complete in `SESSION_4_HANDOFF.md`.**

- [x] Role assignment, private impostor-team reveal, Scientist at 7+ players.
- [x] Tick-resolved kill with the 4s recheck, 30s successful-kill cooldown, colour targeting, witness records and vague distress notice.
- [x] Vent entry, instant travel, exit, 15s cap, local-only awareness and cooldown display.
- [x] Scientist-only `.vitals` / `.witness`; `.cooldown` / `.CDs`; secret commands remain DM-only.
- [x] **Test:** moving killer/target cancels; meetings cancel pending kills; vent overstay ejects; role details stay private.

### Session 5 — Tasks and task interactions

**Status: complete in `SESSION_5_HANDOFF.md`.**

- [x] Task assignment (lobby size + 1 per Crewmate), non-scoring Impostor fakes, 30s cooldown, one task per `.task`.
- [x] Interaction lifecycle: one-minute inactivity, `.task next`, quote-reply targeting, duplicate rejection, movement/leave cancellation.
- [x] Varied task interactions; Ghosts can complete available crew tasks with a 50s cooldown.
- [x] Team task progress and Crewmate win condition.
- [x] **Test:** stale completion rejected; leaving cancels the interaction; ghost completions count.

### Session 6 — Meetings, voting, ghosts

**Status: implemented and regression-tested; WhatsApp admin-role changes are not automated.**

- [x] `.report` only exposes bodies the reporter witnessed; `.meeting` and reports start the 60-second vote.
- [x] Movement, active sabotage deadlines, and task-interaction expiry pause during meetings; cooldowns continue.
- [x] Private, changeable votes; skip and ties; departed players removed from voting; results reveal the ejected colour/role, not individual votes.
- [x] Ghosts move at half travel time, can use `.say` by DM, and are isolated from the living group by message deletion.
- [x] Host can link a separate Ghosts group; non-Ghost messages there and Ghost messages in the living game group are deleted; the link resets at game end.
- [x] **Test:** pending kill interruption (Session 4), sabotage and movement pause, private/deleted votes, report witness filtering, Ghost travel/privacy and group reset.
- **WhatsApp setup:** the Ghosts group must be linked to the bot; the bot needs admin permission for message deletion. The code gates messages but does not promote/demote WhatsApp group admins.

### Session 7 — Sabotage

**Status: complete (7A–7D).** See `SESSION_7A_HANDOFF.md` and `SESSION_7D_HANDOFF.md`.

- [x] Shared per-game sabotage registry, independent states and cooldowns.
- [x] Impostor-only `.sabotage <name>` activation, with private cooldown refusal.
- [x] World-clock deadline/warning hooks, meeting deadline pause, repair interaction lifecycle and game-end cleanup.
- [x] Lights and Communications repair mechanics (Part 7B).
- [x] O₂/Reactor paired scans and map stations (Part 7C).
- [x] Cross-sabotage integration and full sign-off (Part 7D).

### Session 8 — Full-match simulation and hardening

**Status: implemented; see `SESSION_8_HANDOFF.md`.** Simulator, all endings, departure and `.endgame` cases are tested; restart-mid-match lock recovery is open.

- Scripted bot-driven full matches, lobby to victory, with randomised commands.
- Edge cases: restarts mid-game, players leaving, simultaneous events, game end with timers pending.
- Win conditions and sabotage-failure endings finalised.
- Spec-versus-behaviour checklist signed off.

## 3. Open items to settle before or during build

- Restricted info commands during Communications sabotage.
- Persistence after restart: recommended to end the game cleanly rather than resume.
- Vent cooldown starts at vent exit or automatic ejection (chosen for Session 4).
- Vitals labels an ejected player as `Dead — Ejected`; corpse statuses remain Unreported, Witnessed, or Reported.

## 4. Working rules

- One session per working block; each starts from this note.
- Any rule change is written here first, then coded.
- Old code is reference only; nothing is reused unless it passes the new tests.

## 5. Session 2 implementation handoff

This update supersedes the earlier “do not jump into coding” status for Session 2 only. The latest user instruction authorized work on the second session; later sessions are not included.

- A move keeps the player in the source room for one world-clock tick (1 second), then records the departure boundary.
- Corridor position is continuous and stored in travel-seconds from the current endpoint; `.stop` freezes that exact position.
- `.goback` chooses the fastest route from the exact corridor position to the reference room. A redirect does not replace the reference room until the player reaches a room.
- Room arrival/departure events are timestamped with the bot's `Date.now()` receive time. Events within 2 seconds are paired, including simultaneous arrivals.
- Corridor encounters use a 2-second travel-distance radius (the configured two-tick observation span).
- Existing vent transit continues to resolve on the world clock. Reporting while in a corridor no longer moves the player into a room.
- Session 2 tests cover room-boundary timing, stop/restart position, return and redirect, approach privacy, simultaneous arrivals, the two-second event window and corridor encounters.
- Run with `npm run test:amongus`; this runs the Session 1 and Session 2 suites.

**At the time of this Session 2 handoff:** Session 3 was not included or authorized; the user's later authorization is recorded in section 6.

## 6. Session 3 implementation handoff

The user authorized Session 3 after the Session 2 handoff. Its implementation and regression tests are in `SESSION_3_HANDOFF.md`. Later sessions remain outside this slice.

## 7. Session 4 implementation handoff

The user authorized Session 4 after the Session 3 handoff. Implementation details, decisions, and verification are recorded in `SESSION_4_HANDOFF.md`. Sessions 5–8 remain out of scope until authorized.

## 8. Session 5 implementation handoff

The user authorized Session 5 after the Session 4 handoff. Implementation details, decisions, and verification are recorded in `SESSION_5_HANDOFF.md`. Session 6 is the current completed slice; Session 7 and Session 8 remain.

## 9. Session 6 implementation handoff

Session 6 implementation details, the selected meeting-pause rule, WhatsApp setup requirements, and verification results are recorded in `SESSION_6_HANDOFF.md`. The older master-design note's Stage 1 status predates Sessions 3–6; this build plan and its handoffs are the current implementation record.

## 10. Session 7A implementation handoff

The shared sabotage framework is implemented and regression-tested. Type-specific repair rules remain in Parts 7B and 7C; activation of O₂/Reactor does not yet start a deadline until their Part 7C behavior is wired in.

## 11. Sessions 7B–8 implementation handoffs

Session 7 finished in `SESSION_7D_HANDOFF.md`. Session 8 (simulation, hardening, final victory text, `.endgame`) is in `SESSION_8_HANDOFF.md`. The tests are the source of truth for behaviour.
