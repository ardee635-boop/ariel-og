# Niflheim Among Us — Session 8 Handoff (full-match simulation and hardening)

`npm run test:amongus` now runs 21 suites. All pass, including the new Session 8 suite (17 tests, about 2s). `tests/golden_handle_test.py` is unchanged (494 scenarios). `rpg_engine_test.py` and `golden_rpg_test.py` fail the same way on the untouched Session 7 zip (import path / environment), so they are unrelated.

## What was built

- **Match simulator** (`tests/amongus_sim.py`). Drives the real `AmongUsManager` and `Game` from `.lobby open` through victory on a simulated clock: no sleeping, no wall-clock timers. Scripted bots (a command fuzzer, a goal-directed crew, a killing/sabotaging impostor) and per-step invariant checks.
- **`tests/amongus_session8_test.py`**: every ending reached through real commands, departure cases, `.endgame`, and randomised matches (40 fuzz seeds, 30 mixed seeds) with fixed seeds so failures reproduce. I mutation-checked it: reverting each fix below makes the suite fail.
- **Testability changes in the engine**: `Game._tick(now)` (the world-clock body, extracted unchanged), `Game(..., start_clock=False)`, and `manager.game_kwargs`. Production behaviour is the same.

## Bugs found and fixed

1. **`.players` leaked every player's real WhatsApp ID** to whoever asked (only group messages go through the sanitiser; replies and DMs do not). It now shows colours. The same fix covers the roster text and one legacy "lingering" DM that interpolated a JID.
2. **Meetings depended on a wall-clock timer.** The 60s vote and the 10s warning now also run from the world tick (timer kept as a backstop, whichever fires first wins, warning sent once). This is what makes meetings simulatable and removes a timer-only dependency.
3. **A departed Crewmate's unfinished tasks made a task win impossible** when nobody was dead to finish them. They now leave the team total on departure; tasks they already finished stay counted.
4. **Mid-match `.leave` fired the lobby "Host left, Player N is now host" broadcast.** Ignored once the lobby has started.

## Added

- **`.endgame`** (host only, group or DM). The design's checklist expected it but it did not exist. It cancels meetings, sabotages, interactions and timers, and unlocks the group.
- **Final victory text**, one message per ending with the Impostor reveal:
  - Crew by ejection: "Every Impostor has been ejected." / by departure: "The last Impostor left the game." (it used to say "ejected" either way)
  - Crew by tasks; Impostors by outnumbering
  - Sabotage failure: "*Reactor sabotage failed.* The crew ran out of time — *Impostors win!*" (was "Crewmates lose.")
  - Nobody left: neutral "everyone left the game" message
- Priority if endings coincide: no Impostors, then tasks, then outnumbering. Exactly one announcement is sent.

## Decisions to confirm

- The Impostor reveal at the end of every match, and the exact wording above.
- Unfinished tasks of a departed Crewmate leave the total (the alternative is to let ghosts finish them, which still leaves living-only matches stuck).
- `.players` shows colours, not IDs. Two 7B-2a-ii assertions were updated to expect `~Blue~` / `~Green~`.
- Still open from 7C/7D: Impostors and ghosts cannot repair paired sabotages; O₂ = O2 + Admin, Reactor = Upper + Lower Engine; both 30–40s.

## Not done / open

- **Restart mid-match:** state is in memory and not resumed (as recommended in the design). Hazard: a Communications outage locks the WhatsApp group, and the lock is a persistent group setting. If the bot restarts during an outage, the group stays locked until an admin unlocks it. Fixing it needs the bot to remember locked groups and unlock them at startup, which lives on the JS side and is not covered by the simulator.
- Real WhatsApp behaviour (admin rights for deletion/locking, delivery delays) is not exercised; the simulator uses the bot's receive timestamps, as the design specifies.
- Final map stations and Reactor timing are still placeholders until the Gemini map is final.
