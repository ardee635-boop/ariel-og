# Niflheim Among Us — Session 5 Handoff

Session 5 adds Crewmate and Impostor task lists, private task interactions, Ghost task assistance, task progress, and the Crewmate task victory condition on top of Sessions 1–4.

## Delivered

- Every player receives `lobby size + 1` assigned tasks. Impostors receive fake tasks for cover; fake tasks never count toward team progress. Repeated room assignments are allowed.
- A living player can start only an uncompleted task assigned to them in their current room. One active interaction is allowed at a time; `.task next` abandons it and starts another eligible task.
- Task prompts are sent privately. Players can answer by quoting the prompt or with `.task answer <answer>`. Each prompt carries a unique reference so stale and duplicate replies are rejected.
- Task interactions expire after 60 seconds without activity. An incorrect answer refreshes that idle timer. Moving, entering a vent, or leaving Among Us mode cancels the active interaction and releases its task claim.
- Successful living-player task completions start that player's 30-second task cooldown. Cooldowns keep their deadlines while the player moves or attends a meeting; rejected attempts during movement or meetings do not alter the deadline.
- Ghosts can claim any available, uncompleted Crewmate task regardless of assignment or room, and use an independent 50-second cooldown. Their work updates the owning player's list and shared team progress.
- Task-related game-group updates use hidden group mentions. Private prompts and answers stay in DMs.
- Task challenges vary by task: wiring match, sequence, course directions, asteroid count, checksum, shield panels, and fixed task actions.
- `.tasks`, `.progress`, `.cooldown` / `.CDs`, and the help menu reflect assigned tasks, Ghost availability, team progress, and task cooldowns.
- When every Crewmate task is complete, the Crewmates win.

## Decisions and limitations

- The 30-second living and 50-second Ghost cooldowns begin after a successful completion; merely opening or abandoning a task does not consume them.
- A wrong answer is activity and restarts the 60-second inactivity window.
- The task prompt is a regular WhatsApp message, not a poll. The engine invalidates its interaction state at timeout or cancellation, so a late quote is harmless, but the old prompt remains in chat history.
- Group task notices use hidden mentions without visible `@` text. They communicate task activity, not the task answer.
- Full player-departure reconciliation (such as how a departing player's incomplete assigned tasks affect the task victory total) is still part of Session 8 hardening. Session 5 cancels that player's active interaction when departure is detected.
- Meetings and Ghost group behaviour remain Session 6 work; task interactions are blocked during meetings, while cooldown deadlines continue.
- Sabotage-specific task interactions remain Session 7 work.

## Verification

The Session 5 regression suite covers task scaling and scoring, quote-reply completion, active-task messaging, `.task next`, stale and duplicate replies, inactivity expiry, movement and meeting rejections, cancellation on movement and departure, Ghost task access and cooldown, varied interaction types, and hidden-mention notices.

Run the complete suite from `services/ariel-bot`:

```bash
npm run test:amongus
```

The Session 5 ZIP is `Niflheim_Among_Us_Session_5.zip`. Sessions 6–8 are not included.
