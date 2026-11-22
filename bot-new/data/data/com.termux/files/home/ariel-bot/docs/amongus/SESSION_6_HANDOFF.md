# Niflheim Among Us — Session 6 Handoff

Session 6 adds meetings, private voting, witnessed-body reporting, Ghost movement and a separate Ghosts-group gate on top of Sessions 1–5.

## Delivered

- `.report` is accepted only in a room and only for a body the reporting player witnessed. It reports those witnessed bodies without revealing other bodies in the room, then calls a meeting. `.meeting` starts an emergency meeting.
- Meetings run for 60 seconds. Movement is frozen, pending kills are cancelled, active sabotage deadlines pause, and active task-interaction expiry is extended by the meeting duration. Player cooldowns continue to count down.
- Living, non-departed players eligible at meeting start can vote by DM or in the game group. Votes are private, can be changed, accept colours or `skip`, and are acknowledged by DM. Group vote messages are deleted. Ties and a top `skip` result eject nobody; no votes eject nobody. Departed voters and targets are excluded.
- Meeting results identify the ejected colour and whether they were an Impostor; they do not reveal voter identities or per-player votes.
- Ghosts can move through the same map at half normal travel time. Movement and room-event notifications stay within the same life-state cohort; Ghosts cannot use living meetings or votes.
- A host can set a separate Ghosts group with `.setghostgroup` from that group. Ghost messages in the living game group and non-Ghost messages in the Ghosts group are deleted. `.say <message>` sent to the bot by a Ghost relays only to the Ghosts group. Ghost-group routing resets when the game ends.
- The WhatsApp DM handler now forwards Among Us commands and quoted task replies to the game engine.

## WhatsApp setup and boundaries

- The Ghosts group must already be linked to the bot so its messages reach the handler and private relay messages can be sent. The bot must be a group admin to delete messages; if it is not, the game logic still accepts a vote but the original group message may remain visible.
- The code enforces Ghost-group privacy with an application-level message gate. It does **not** automatically promote Ghosts or demote non-Ghosts in WhatsApp's actual group-admin roster.
- The handoff ZIP contains only changed/new files, with their paths preserved under `services/ariel-bot/`, so it can be overlaid on the existing project.

## Verification

Run from `services/ariel-bot`:

```bash
npm run test:amongus
```

The Session 1–6 regression suites pass (48 tests total). Session 6 adds coverage for witnessed-only reports, private/changeable votes, skip/tie outcomes, departed voters/targets, paused movement and sabotage deadlines, half-time Ghost travel, Ghost-group routing, and link reset.

## Remaining

- Actual WhatsApp group-admin role changes are not part of this slice; decide whether to add them or keep the safer message-deletion gate.
- Session 7 is sabotage: Lights, Communications, O₂ and Reactor states, repairs and paired scans. The selected meeting rule is already recorded in the build plan: countdowns pause during meetings; cooldowns do not.
