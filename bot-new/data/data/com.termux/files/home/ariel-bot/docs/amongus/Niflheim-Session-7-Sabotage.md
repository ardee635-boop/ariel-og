# Niflheim Among Us — Session 7 Note: Sabotage (4 parts)

*Companion to the Build Plan and Master Design & Merge Note v4. Newer user decisions override older proposals. Each part ends runnable with its own checklist; don't start the next until it passes.*

## Current status

**Part 7A complete and regression-tested.** The code now has a per-game sabotage registry, independent cooldown/state, `.sabotage <name>` activation, configurable warning thresholds, world-clock deadline resolution, shared repair-interaction lifecycle, meeting deadline pause/resume, and game-end cleanup. The 7A handoff is `SESSION_7A_HANDOFF.md`.

Part-specific repair mechanics are not included yet: Lights and Communications are Part 7B; timed O₂/Reactor activation and paired scans are Part 7C. Until then, the framework accepts their activation but does not start their type-specific deadlines.

## Order

| Part | Covers | Needs | Blocked by |
| --- | --- | --- | --- |
| 7A | Shared framework | Sessions 1–6 | Meeting vs. deadline rule |
| 7B | Lights, Communications | 7A | Restricted commands during Comms; puzzle libraries |
| 7C | O₂, Reactor | 7A | Final map stations; reactor timing |
| 7D | Integration tests, sign-off | 7A–7C | Nothing new |

7B and 7C are independent once 7A passes, so either can go first.

## Open decisions (settle before the part that needs them)

- Do O₂ and Reactor countdowns pause during meetings? Recommended: yes, matching movement and task pause. Cooldowns keep running either way.
- Which info commands (`.players`, `.progress`) are restricted during Communications sabotage? Only a proposal so far.
- Station rooms for O₂ and Reactor come from the final Gemini map. The current map is a placeholder.
- Reactor deadline proposed at 30–40 seconds, same as O₂.
- Lights circuit patterns and Communications phrases (with accepted variants) still need to be written.

---

## Part 7A — Shared framework

Gives every sabotage the same lifecycle so 7B and 7C only add what is specific to each.

**Rules**

- Multiple sabotages can be active at once. No one-at-a-time limit.
- Each has its own state, cooldown, deadline (if any) and repair. Fixing one never fixes or resets another.
- Cooldowns start on activation and keep running while active and during meetings: Lights 3 min, Reactor 5 min, Communications 3 min, O₂ 4 min.
- Impostors trigger remotely with `.sabotage <name>`. Repair needs travel to the repair location.
- Group announcements go through the single sanitised broadcast path: activation, 20s left, 10s left, final result. No per-second messages.
- The world clock drives deadlines and warnings; they never wait on a player's next command.
- Game end cancels every sabotage timer, repair interaction and pending scan (architecture rule 8).
- A sabotage failure ends the game. Final victory text is finished in Session 8.

**Build**

1. `Sabotage` base object: name, state (idle, active, repaired, failed), activated_at, deadline, cooldown_until, repair hooks.
2. Registry on the game object, one instance per sabotage type.
3. Cooldowns, deadline ranges and warning times in `au_config`.
4. `.sabotage` command: impostor-only, DM only, cooldown check, replies with remaining cooldown on refusal.
5. Tick hook for deadlines and warnings; shared repair interaction slot reusing the Session 5 lifecycle (one-minute idle cancel, `.task next`, no duplicates per player).
6. Event-log entries for activation, repair and failure, with timestamps.
7. Cleanup on repair, failure and game end.

**Checklist**

- [x] Two sabotages active together; repairing one leaves the other active.
- [x] Cooldown displays correctly and keeps running while active and during a meeting.
- [x] Sabotage activated then game ended: no running timer, nothing sent afterwards.
- [x] Repair interaction timeout, duplicate prevention and `.task next` switching reuse the Session 5 lifecycle.
- [x] Deadline warning/failure hooks use world time; meetings pause deadlines without pausing cooldowns.

---

## Part 7B — Lights and Communications

The two sabotages with no deadline; each stays active until repaired.

**Lights rules**

- Triggered remotely, 3 min cooldown from activation, no automatic timeout.
- New passive observations (entering, leaving, passing) keep the event but hide who. Impostors still see true identities.
- `.status` still shows real current-room occupants during Lights.
- After repair, new observations return to normal; past observations stay remembered.
- Repair at Electrical: arrive, use `.task`, bot posts a switch puzzle in the game group.
- Predefined circuit patterns; selecting a switch changes others per the pattern.
- Each player has a separate interaction; selections don't affect each other.
- First successful completion repairs Lights for everyone, counts once, deletes all active repair polls.
- Abandoning or timing out cancels only that player's attempt. No duplicate repair interactions per player.

**Communications rules**

- Triggered remotely, 3 min cooldown, active until repaired.
- Game group locked to player messages; bot system messages still appear.
- Camping awareness off. Passive arrival, departure and corridor-encounter notices suppressed. A pending camping trigger is dropped, not delayed.
- `.follow`, movement, kills, meetings, voting, timers and repairs continue.
- After repair: no replay of missed movement. One consolidated report of players inactive for more than 60 seconds, with locations and durations. Not proof of guilt.
- Repair at Communications: `.task` posts a scrambled phrase with hidetag; player replies with the intended phrase.
- Correct answer repairs immediately; wrong answer leaves it active and allows another try.
- Answers ignore punctuation, case, spacing and stray symbols. Listed equivalent variants count; different meanings don't.

**Build**

1. Lights: sabotage object, observation-masking flag read by the awareness layer, per-player switch-puzzle interactions, pattern library, first-success repair and poll cleanup.
2. Communications: sabotage object, group-lock call via the transport (needs bot admin), suppression flags for passive notices and camping, inactivity report, phrase puzzle with answer normaliser.
3. Puzzle data in its own module: circuit patterns and phrase sets with accepted variants.

**Checklist**

- Two players repair Lights at once: one repair counts, all polls deleted.
- One player abandons: Lights stays active, the other attempt continues.
- Observations made during Lights stay masked after repair; new ones are not.
- During Communications: no passive notices, camping never fires, `.follow` works.
- After repair: one consolidated report, no replay of missed updates.
- Wrong phrase leaves Communications active; a correct variant with different punctuation repairs it.

**Decisions needed:** restricted info commands during Comms, circuit pattern list, phrase list. Group lock depends on the bot being group admin.

---

## Part 7C — O₂ and Reactor

Both need two players at two stations to send `scan` within two seconds of each other before a deadline.

**Shared pair-scan rules**

- Only one active player per station interaction.
- First player at a station is told "Waiting for partner." When a partner reaches the other station, both are told to send `scan` as plain text.
- Both scans must land within 2 seconds, on the bot's own receive time, not WhatsApp delivery time.
- A failed pair can retry while time remains. The deadline never resets.
- If either player leaves before both scans are accepted, that pair's attempt cancels immediately.
- If a player dies or leaves the game, their interaction ends and another eligible player can take over while time remains.
- Immediate resolution, no grace period. Valid paired scans before the deadline repair it. Deadline first, or scans straddling it, fails it.
- Repairing one doesn't touch other active sabotages.
- Announcements: activation, 20s left, 10s left, final result.

| | O₂ | Reactor |
| --- | --- | --- |
| Command | `.sabotage oxygen` | `.sabotage reactor` |
| Cooldown | 4 min | 5 min |
| Deadline | Random 30–40s | Random 30–40s (proposed) |
| Stations | Two rooms, final map | Two rooms, final map |
| Failure | Game-ending | Game-ending |

**Build**

1. `PairedScan` component shared by both: two station slots, waiting state, scan-window check, cancel and takeover.
2. O₂ and Reactor objects that pick a deadline from the config range on activation and register 20s/10s warnings.
3. Station rooms read from the map module, not hard-coded in sabotage code.
4. Failure handling that ends the game through the shared path and cancels everything else.

**Checklist**

- Valid pair repairs before the deadline and ends it immediately.
- Scans 1.9s apart succeed; 2.1s apart fail with retry allowed.
- Scans straddling the deadline fail the sabotage.
- One player leaves mid-attempt: attempt cancels, a new player can take the station.
- A player dies at a station: interaction ends, a replacement can take over.
- Deadline expiry with no scans fails the sabotage and ends the game cleanly.

**Decisions needed:** station rooms (final map), reactor deadline, meeting pause rule.

---

## Part 7D — Integration tests and sign-off

No new rules. Proves the four sabotages work together with scripted timelines on the fake clock.

**Scenarios**

1. All four active at once; repair in a different order each run; each repair affects only its own sabotage.
2. Lights active during a kill: witnesses see masked identities, the impostor sees true ones, `.status` shows real occupants.
3. Communications active during a kill and report: passive notices suppressed, meeting still works, inactivity report sent after repair.
4. O₂ and Reactor active together with one pair of players: they can only be at one station at a time, so one must fail or be handed over.
5. Meeting called during an active timed sabotage, under the rule chosen in 7A.
6. Near-simultaneous scans at the deadline: one tick before, same tick, one tick after.
7. Player leaves or dies mid-repair, for each sabotage type.
8. Game ends (win, failure, host `.endgame`) with sabotages and interactions pending: nothing acts afterwards.

**Sign-off**

- All 7A, 7B and 7C checklist items pass.
- The eight scenarios pass on the fake clock, plus one run on the real tick thread.
- Existing golden handle test still passes unchanged.
- No group message contains a real WhatsApp identity.
- Open decisions written back into the build plan, then Session 8 starts.
