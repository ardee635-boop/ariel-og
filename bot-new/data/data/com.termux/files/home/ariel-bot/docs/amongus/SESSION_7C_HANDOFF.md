> **Superseded by SESSION_7D_HANDOFF.md.** 7C is now wired onto the 7A framework (no separate glue functions, no standalone registry). The sections below describe the original standalone module.

# Niflheim Among Us — Session 7C Handoff (O₂ and Reactor)

Part 7C is built as a standalone module so it cannot collide with Part 7A. It is **not wired into `amongus_game.py` yet**; the wiring is five small edits listed below, to be made once Part 7A's framework is in.

## Delivered

- `engine/router/amongus_paired.py`
  - `PairedScan`: two station slots, waiting state, the scan window, cancel and takeover. Pure logic, no game access.
  - `PairedSabotage`: one object each for O₂ and Reactor, with the Part 7A lifecycle fields (`name`, `state`, `activated_at`, `deadline`, `cooldown_until`). Random 30–40s deadline from config, 20s/10s warnings, repair, failure through `game._end_game`, and cleanup.
  - Glue functions: `activate`, `join_station`, `handle_scan`, `tick_all`, `vacate_player`, `cancel_all`, `cooldown_lines`.
- `engine/router/amongus_map.py`: `SABOTAGE_STATIONS` and `get_station_rooms()`. Sabotage code never names a room.
- `engine/router/amongus_config.py`: appended `PAIRED_SCAN_WINDOW_SECONDS`, `PAIRED_SCAN_EXPIRY_MARGIN_SECONDS`, `SABOTAGE_WARNING_SECONDS`, `PAIRED_SABOTAGE_IMPOSTORS_CAN_REPAIR`. If Part 7A also adds `SABOTAGE_WARNING_SECONDS`, keep one copy.
- `tests/amongus_session7c_test.py`: 30 tests. Sessions 1–6 still pass.

## How it behaves

- `.sabotage oxygen` (also `o2`) and `.sabotage reactor`: Impostor only. Per-sabotage cooldown starts on activation and keeps running through repairs and meetings. Both can be active at once; repairing one never touches the other.
- A player takes a station with `.task` in a station room. The first is told "Waiting for partner."; when the second arrives both are told to send `scan`.
- Both scans must be stamped within 2.0s of each other (exactly 2.0s counts). Outside that, the pair is told the window was missed and can retry. The deadline never resets.
- A scan stamped after the deadline fails the sabotage, so scans straddling the deadline fail it. Resolution uses the bot's receive timestamps, not tick order.
- A player who starts moving, dies, vents or leaves the game is dropped from the station on the next tick or scan. The pair's attempt cancels and anyone eligible can take over.
- Repair ends the sabotage at once. Failure ends the game with provisional text; Session 8 finalises it.
- Meetings: the module registers its state in `game._sabotages`, so the Session 6 pause and resume already freeze and restore the deadline. Scans and joins are rejected during a meeting, and warnings are tick-driven so none repeat after a resume.
- A game timer is also scheduled as a backstop, so the deadline fires even if the tick hook is not wired.

## Wiring needed in `amongus_game.py`

1. Import: `from . import amongus_paired as PAIRED`.
2. `.sabotage`: before the existing `reactor` branch, `handled, reply = PAIRED.activate(self, p, arg, command_at)`; return `reply` if handled. Remove or redirect the old Meltdown `reactor` branch.
3. `.task` with no argument: before the normal flow, `handled, reply = PAIRED.join_station(self, p, command_at)`; return `reply` if handled.
4. Non-dot text: `handled, reply = PAIRED.handle_scan(self, p, text, command_at)`; return `reply` if handled.
5. World clock: call `PAIRED.tick_all(self, now)` inside the tick. Also `PAIRED.cancel_all(self)` in `_end_game`, and optionally `PAIRED.vacate_player(...)` from `mark_departed`. For `.cooldown`, append `PAIRED.cooldown_lines(self, now)` for Impostors.

If Part 7A's base replaces `PairedSabotage`'s bookkeeping, keep `PairedScan` and the `join`, `scan`, `reconcile` and `_repair`/`_fail` logic.

## Decisions I made, please confirm

- **Station rooms (proposed):** O₂ = O2 + Admin (the old Meltdown pair); Reactor = Upper Engine + Lower Engine. Change `SABOTAGE_STATIONS` in the map module to alter.
- **Impostors cannot repair** (`PAIRED_SABOTAGE_IMPOSTORS_CAN_REPAIR = False`). The design was silent.
- **Ghosts cannot repair** paired sabotages (the design says "living interaction").
- **Exact tie goes to the crew:** a scan stamped exactly at the deadline counts.
- **Reactor deadline:** same 30–40s as O₂, still marked proposed in the design.
- **Joining:** uses `.task`, as Lights and Communications do. A player with an active task must finish or abandon it first.
- **Activation text:** the group announcement names the two stations but not the deadline.
