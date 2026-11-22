# Niflheim Among Us — Session 2 Handoff

## Delivered

Session 2 implements movement and the living-world movement rules:

- `.m` starts a private move; players remain in the source room until the exit boundary.
- `.stop` freezes a player at the exact corridor position. A later `.m` resumes from there.
- `.goback` returns from the current position by the fastest route to the reference room. Redirecting during a return keeps that reference until a room is reached.
- Room arrivals/departures are logged by timestamp. Same-room events within two seconds are paired so the outcome does not depend on handler order.
- Arrivals use a shared snapshot for simultaneous entrants. Players still travelling toward the room are not treated as occupants.
- Travellers and stopped players can encounter one another in a corridor.
- Movement continues on the world clock. Existing vent arrivals remain clock-driven.
- Reporting from a corridor does not teleport a player back into the room.

## Configurable timing defaults

- Room exit boundary: one world-clock tick (currently 1 second).
- Room event awareness window: 2 seconds.
- Corridor encounter radius: 2 travel-seconds, matching the two-tick observation span.

The exit delay and encounter radius are implementation defaults because the source design did not assign exact values. They are centralized in `engine/router/amongus_config.py`.

## Verification

Run from the `services/ariel-bot` directory:

```sh
npm run test:amongus
```

Session 1: 4 tests passed. Session 2: 9 tests passed, covering boundary timing, corridor stop/restart, `.goback` and redirect, approach privacy, same-time arrivals, the two-second event window, corridor encounters, world-clock vent arrival, and reporting from a corridor.

## Still out of scope

Camping alerts, `.status`, following, crime-scene history, role perspectives, tasks, meetings, voting, sabotage, and full-match hardening remain for later sessions. Session 3 is the next planned slice; this handoff does not authorize it.
