# Niflheim Among Us — Session 3 Handoff

## Delivered

Session 3 adds awareness and persistent crime-scene state to the Session 1–2 engine:

- `.status` privately reports the caller's current room or nearby corridor occupants and visible bodies. Checking an unreported body records the caller as a witness. It does not reveal players' past locations.
- Camping awareness is evaluated by the per-game world clock. A player must remain in one place for 60 seconds; awareness waits for an eligible observer in the same room or corridor, fires once per continuous stop, and resets after movement or a new stop. Living players do not count ghosts as observers.
- `.follow <colour>` starts only when the target is nearby. The follower trails room changes, receives arrival/departure notices, and is revealed after 25 seconds unless `.status` reveals them earlier. `.unfollow` ends the tail; a vent or a still-required action ends it with a reason-specific notice.
- Active corpses retain room, victim, killer and witness metadata. Reporting a body records the reporter, removes that body from the active room list, and appends a permanent reported-scene entry. `.cscene`, `.crimescene` and `.cs` list reported scenes only.
- Kill notifications no longer tell the victim or nearby players the killer's identity. Players in the room receive a vague distress notice; an active follower who witnesses the target kill receives the murder notice.
- `.amenu` and the Among Us test script include the new commands and Session 3 suite.

## Verification

Run from `services/ariel-bot`:

```sh
npm run test:amongus
```

All 22 Among Us tests pass: Session 1 (4), Session 2 (9), Session 3 (9). Session 3 covers status/body witness recording, observer-gated and once-per-stop camping, stop-timer reset, shared-corridor awareness, following across a room change, early and timed follower reveals, vent/still-action trail termination, and reported-scene persistence through meeting resolution.

## Not included

This handoff does not implement Session 4 role assignment/Scientist commands or the later task, voting, ghost-group, and sabotage specifications. Existing legacy mechanics outside the Session 3 slice have not been fully reconciled with the master design.
