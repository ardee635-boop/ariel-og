# Session 7A Handoff — Shared Sabotage Framework

**Status: complete.** This milestone builds the shared framework only. Lights and Communications repair puzzles are Part 7B; O₂/Reactor station selection, timed activation, and paired scans are Part 7C.

## Implemented

- Per-game registry with a separate `Sabotage` state object for Lights, Communications, O₂, and Reactor.
- Independent `idle`, `active`, `repaired`, and `failed` states, activation timestamps, cooldown deadlines, optional sabotage deadlines, and repair-interaction tracking.
- Impostor-only `.sabotage <name>` activation. The router accepts sabotage commands only in DMs; group messages retain the existing private-command rejection.
- Independent cooldowns in the shared config (Lights 3m, Communications 3m, O₂ 4m, Reactor 5m), with remaining time shown to impostors in `.cooldown` / `.cds`.
- Shared broadcast notices for activation and deadline warnings at the configured 20s and 10s thresholds. Deadline expiry uses world time, records a failure event, and ends the game.
- Meeting pause/resume for deadlines without changing cooldown timestamps.
- Shared repair interaction support using the Session 5 interaction slot: one attempt per player, one-minute inactivity expiry, answer handling, `.task next` switching, and cancellation on movement, venting, departure, death, repair, or game end.
- Game-end cleanup cancels pending timers and repair interactions. No later sabotage warning or failure can act after the game ends.
- Timestamped event-log records for sabotage activation, repair, failure, cancellation, and repair-interaction changes.

## Intentionally deferred

- `.sabotage oxygen` and `.sabotage reactor` create active framework states but do not yet start their 30–40s type-specific deadlines. Part 7C wires those deadlines together with paired scans.
- Part 7B adds Lights identity masking, the switch puzzle, Communications suppression/group-lock behavior, and phrase repair.
- The open design choices listed at the top of `Niflheim-Session-7-Sabotage.md` remain open. Part 7A does not require them.

## Verification

`npm run test:amongus` passes all Sessions 1–6 regression tests plus six Session 7A tests. The new tests cover:

- Simultaneous independent activation, repair isolation, and cooldown display after repair.
- Shared repair interactions, wrong-answer retry, duplicate prevention, inactivity expiry, and `.task next`.
- 20s/10s deadline warnings, failure on the deadline, and the game-ending path.
- Meeting deadline pause/resume while cooldown time continues.
- Timer and interaction cleanup when the game ends.

## Next

Choose Part 7B or Part 7C. Resolve the relevant open decisions in `Niflheim-Session-7-Sabotage.md` before implementing that part.
