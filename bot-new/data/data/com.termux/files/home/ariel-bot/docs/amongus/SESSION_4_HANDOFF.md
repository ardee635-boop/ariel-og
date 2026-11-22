# Niflheim Among Us — Session 4 Handoff

## Delivered

Session 4 adds the role, kill, vent, investigation, and cooldown layer on top of Sessions 1–3:

- Games with 7 or more players assign one random Crewmate as Scientist; smaller games do not. Scientists count as crew for tasks and victory checks. Role details, including fellow Impostors, are sent by DM; the group receives only the player and Impostor counts.
- `.kill <colour>` starts a four-second pending kill resolved by the world clock. Movement by either participant cancels it; a meeting also cancels pending kills. A successful kill starts the Impostor's 30-second cooldown. Color targeting, room witnesses, persistent corpse records, vague distress notices, and the existing direct murder-witness notice are retained. The victim is not told the killer's identity.
- `.vent in` enters a vent; `.vent <destination>` travels instantly through a connected vent; `.vent out` exits. Vent travel does not reset the 15-second maximum. The Impostor is auto-ejected at the current vent on timeout. Entry is noticed only by living players in the room, and emergence only by living players in the destination room. Vent cooldown is 30 seconds from exit or automatic ejection.
- `.vitals` and `.witness` are Scientist-only, with 20- and 75-second cooldowns. Vitals reports Alive, Dead — Unreported, Dead — Witnessed, Dead — Reported, or Dead — Ejected. Witness records persist after a body report; the reporter is marked. Neither investigation command reveals the killer, room, or death time.
- `.cooldown` and `.CDs` show applicable role cooldowns. `.cooldown fix` and `.repair` retain access to the older Meltdown repair action.
- In-game commands continue to be rejected in the group chat except for public voting; the existing manager privacy gate is unchanged.

## Verification

Run from `services/ariel-bot`:

```sh
npm run test:amongus
```

All 30 Among Us tests pass: Session 1 (4), Session 2 (9), Session 3 (9), Session 4 (8). Session 4 covers role thresholds and private role delivery, vitals/witness output and cooldowns, world-tick kill resolution, movement and meeting cancellation, vent awareness/travel/timeout, and the group-chat privacy gate.

## Decisions and limits

- The design left the exact start of the vent cooldown open; this implementation starts it when the player exits or is ejected.
- Ejection is shown as `Dead — Ejected`, distinct from corpse statuses.
- Dead players remain restricted to `.say`; they cannot use Scientist investigation commands.
- This session does not replace the legacy task timer with Session 5's task-interaction lifecycle, nor complete Session 6 meetings/ghost-group rules or Session 7 sabotage. Existing behavior outside these session slices still needs the planned end-to-end reconciliation.
