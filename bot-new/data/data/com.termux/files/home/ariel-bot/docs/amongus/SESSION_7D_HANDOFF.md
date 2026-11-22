# Niflheim Among Us — Session 7D Handoff (merge, 7C wiring, integration tests)

Part 7 is complete: 7A framework, 7B Lights and Communications, 7C O₂ and Reactor, 7D integration. `npm run test:amongus` passes all 20 suites (7C: 34 tests, 7D: 18). `tests/golden_handle_test.py` is unchanged (494 scenarios).

## What this session did

1. **Merged the zips.** Base = the 7A tree (`DOC-…WA0168.zip`), then the 7B overlay, then 7C. The Session 6 zip is the pre-7A tree and was not needed.
2. **Wired 7C onto the 7A framework** instead of the five edits in the old 7C handoff. `PairedSabotage` now subclasses the 7A `Sabotage`, so cooldowns, 20s/10s warnings, meeting pause/resume, failure and game-end cleanup are the shared framework's. 7C keeps only `PairedScan`, station join/vacate and the scan hand-off (`amongus_paired.py`). `make_sabotage(name, cooldown, game=)` builds it for `oxygen` and `reactor`.
   - `.task` (no argument) in a station room joins a station; plain `scan` / `.scan` is routed before ordinary commands (ghosts excluded).
   - Stations are reconciled on the shared tick; departure frees a seat immediately; starting another task vacates the seat.
   - The old Meltdown placeholder (`.repair`, `.cooldown fix`, `_meltdown`, `_check_meltdown_expired`) is removed. The Session 6 meeting test now uses O₂.
3. **Finished 7B-2c-ii:** `.debugcommsrepair` and `DEBUG_COMMS_REPAIR_ENABLED` are gone (and `.debugrepair` was already gone). The 7B-2a-i test was rewritten.
4. **7D:** `tests/amongus_session7d_test.py` — the eight scenarios on the fake clock (scenario 1 across all 24 repair orders), the sign-off checks, and two runs on the real world-clock thread.

## Bug found by 7D and fixed

`_resume_sabotage_deadlines` removed the `paused_remaining` key after a meeting. The next tick then hit a `KeyError`, and the world clock ended the match with an error. It now sets the key to `None`. Any game with an active O₂ or Reactor through a meeting would have hit this.

## Rule changes to confirm

- **Deadline tie goes to the crew.** A sabotage now fails only when the clock is strictly past the deadline, so a scan stamped exactly at the deadline counts. Two 7A tests were updated (failure now asserted at deadline + 0.01).
- **`.sabotage` is refused during a meeting** (any type).
- Carried over from the 7C handoff, still your call: impostors and ghosts cannot repair paired sabotages; O₂ stations = O2 + Admin; Reactor stations = Upper Engine + Lower Engine; Reactor deadline 30–40s (same as O₂).
- The group activation message for O₂/Reactor names both stations, not the deadline. It still says who triggered it, as 7A did.

## Open items (not blocking)

- Final map stations and Reactor timing are placeholders until the Gemini map is final.
- Session 8: final victory text for sabotage failure, full-match simulation, hardening.
- The planning notes' checklists are out of date (as you said); the tests are the source of truth.
