# ARIEL Among Us - implementation log

Update zips are CUMULATIVE: every file changed since your original archive, at the same paths as the bot
(unzip the latest one over your ariel-bot folder; no need to apply earlier ones). `package.json` is included when the test script changes.

## Package 1 - Timing (done)
- Kill wait 4 s -> 5 s (30 s cooldown unchanged).
- Meeting is 90 s total; "10 seconds left" warning at 80 s.
  New constants: MEETING_DURATION_SECONDS, MEETING_VOTING_OPENS_SECONDS (60, enforced in pkg 5),
  MEETING_WARNING_SECONDS. MEETING_VOTE_SECONDS kept as an alias (= 90).
- Old assertions updated deliberately: session4 (kill 5 s), session8 (90 s meeting, warning at 80 s).
- New test: tests/amongus_session9_pkg1_test.py (added to `npm run test:amongus`).
- Result: all 22 Among Us test files OK.

## Package 2 - Endings (done)
- `_resolve_win_check(at)` now settles any sabotage deadline <= `at` first (earliest timestamp wins,
  exact tie -> Impostors). Failure is stamped at the deadline itself, not at the tick that noticed it.
- Impostor-outnumber is checked before task completion, so a same-moment tie goes to Impostors.
- Texts: "Reactor meltdown — Impostors win"; "🚨 OXYGEN FAILURE!" then "O₂ depleted — Impostors win"
  (both followed by the Impostor reveal; exactly one match-over message).
- Old assertions updated deliberately: 7a (failed_at = deadline, O2 text), 7c/7d (O2 text, ".meltdown" debug
  command check), 8 (ending texts).
- New test: tests/amongus_session9_pkg2_test.py. All 23 Among Us test files OK.
- Decision recorded (Package 6): ghost group pairing is by registration order: lobby group N uses ghost group N.

## Package 3 - Paired sabotage (done)
- Scan must land strictly before the deadline (a scan AT the deadline fails the sabotage). Both Reactor and O2.
- `scan` only counts as a reply to a bot message. The JS bridge only passes quoted text when the quoted
  message is from the bot, so DM `scan` replies now forward it (bot/handler/entry.js). A plain `scan`
  gets an explanation and is not counted.
- O2 ready message uses the confirmed wording; optional `.ready` sends 3, 2, 1, SCAN NOW! to both seated
  players and is cancelled if a station is vacated. Reactor has no countdown (06C).
  !! UNDECIDED: gap between the four countdown messages. Implemented as 1 s
  (READY_COUNTDOWN_STEP_SECONDS in amongus_config.py). Tell me if you want another spacing.
- Only living Crewmates repair (Impostors and Ghosts are refused) - covered by tests.
- `.ready` added to the DM command pattern in entry.js and to `.amenu`.
- Group+DM delivery of sabotage events to everyone incl. Ghosts is Package 4 (not here).
- Old assertions updated: 7c/7d (exact-deadline scan now fails; scans sent as replies; ready text).
- New test: tests/amongus_session9_pkg3_test.py. All 24 Among Us test files OK; entry.js passes `node --check`.
- JS changed this package: bot/handler/entry.js (restart the bot after applying).

## Package 4 - Sabotage delivery (done)
- Activation, 20 s / 10 s warnings and repair are sent to the game group AND to every non-departed player's DM
  (Ghosts and Impostors included). DMs ask the bot to append the real game-group link at send time.
- Activation never names the Impostor: `<emoji> *<NAME> SABOTAGED!*` + `Required stations:` list. Only the
  triggering Impostor gets a private `<Name> sabotage initiated.` DM.
- Group link: new optional `group_link_jid` on pushed DMs (engine/bridge.py -> bot/bridge.js). JS calls
  `groupInviteCode` (cached 10 min) and appends "Open the game group: <link>". Best effort: if the bot is not a
  group admin / lookup fails, the DM is still sent without the link. Needs a real-group check.
- Stations are now a per-map registry (`SABOTAGE_STATIONS_BY_MAP` in amongus_map.py): Lights 1, Comms 1, O2 2,
  Reactor 2; validated at import; Lights/Comms repair rooms read from it (old config constant removed).
- !! Not invented / still open: the "approved short effect description" line of the activation template has no
  approved wording, so it is omitted. Station labels ("Reactor station", "Oxygen station", "Lights repair",
  "Communications repair") and banner emojis (💡 📡 💨 ☢️) are my placeholders - tell me to change any.
- The failure/match-over message is NOT DM'd here; personal result DMs at match end come in Package 5.
- Old assertions updated: 7a / 7b1ai / 7b2ai ("... SABOTAGED!").
- New test: tests/amongus_session9_pkg4_test.py. All 25 Among Us test files OK.
- JS changed: bot/bridge.js. Python: engine/bridge.py, amongus.py, amongus_map.py, amongus_game.py, amongus_config.py.


## Package 5 - Meetings (done, except mini-previews)
- Timeline: discussion open for the whole 90 s; voting opens at 60 s; warning at 80 s; resolve at 90 s.
  A vote before 60 s gets `Voting opens at 60 seconds.` (a group vote is deleted and answered by DM).
- Meeting call: group message "MEETING CALLED / Reason / Discussion is open now" with the bot's DM link appended
  (`append_dm_link`, new field group->bot); every living player gets a DM with the real game-group link.
- Voting open (60 s): hidetag group announcement + DM link, and a DM to each voter explaining `.vote <colour>` / `.vote skip`.
- Ejection reveal: three group messages EJECTION_REVEAL_STEP_SECONDS (2 s) apart: `X was ejected.` + `...`, `.......`,
  then `X was an Impostor/a Scientist/a Crewmate.` + `1/2 Impostors remain.` / `All Impostors have been eliminated.`
  The ejection is final in game state at once; a win stops gameplay immediately and the single match-over message
  is delivered after the reveal. Delivery timers are not game timers, so ending the match does not cancel them.
- Vent: a player inside a vent when a meeting starts is pulled out into the vent's room and may vote.
- One reply for paused gameplay commands during a meeting (.m .stop .goback .vent .kill .task .follow .unfollow
  .report .meeting .sabotage .vitals .witness .ready). Informational commands and .vote/.say/.GC/.dm still work.
- `.say <message>` (DM, living players, meeting only): relayed to the group as `🗣️ *Colour:* text`. Ghost `.say` is unchanged.
- `.GC` / `.dm` (anywhere): reply with a real link. Python returns a `link_reply` action; bot/bridge.js resolves it
  (group invite link via groupInviteCode, DM link = wa.me/<BOT_NUMBER>). `.GC` picks the game group of the group you
  send it in, else your only game; "not in a game" / "more than one game" messages otherwise.
- Personal result DMs at match end (role, team, win/loss) for every non-departed player, incl. Ghosts; none when the host ends the match.
- Old assertions updated deliberately: votes in sessions 1/6/8 now happen at or after 60 s; the simulator's bots wait for
  voting to open and collapse the reveal gaps (`C.EJECTION_REVEAL_STEP_SECONDS = 0` in tests/amongus_sim.py);
  fake managers accept `**kwargs`. New test: tests/amongus_session9_pkg5_test.py. All 26 Among Us test files OK.
- JS changed: bot/bridge.js, bot/handler/entry.js (DM regex now includes gc|dm). Restart the bot after applying.
  Python: engine/bridge.py, engine/router/amongus.py, amongus_config.py, amongus_game.py, handle.py.

!! Not done / undecided (nothing invented):
- Mini-previews (meeting caller, ejection): no image assets exist yet (`preview-images/` is empty) and `.preview`'s card
  code was not touched. The reveal text is ready for an image to be attached later.
- Match-over group wording is unchanged (the existing "Crewmates win! ..." text); the 07 sample wording
  (`CREWMATES WIN!`, `The Impostors were:`) is still waiting for your approval.
- Meeting-call DMs go to living players only; Ghosts are not DM'd about meetings (not specified).
- `.GC` / `.dm` need the Among Us pool on in a group; in DMs they always work. `.dm` in a DM is now answered by Among Us.
- Needs a real-group check: group invite link lookup (bot must be admin), wa.me link, hidetag, delivery of the 2 s spacing.
- Not run here: tests/golden_handle_test.py (needs network) and the JS test suite (no node_modules); `node --check` passes.


## Package 6a - Communications restriction (done; not run here, see below)
Package 6 is split: 6a = Communications (this), 6b = registry commands + ghost-group pick (next).
- No more announcement-only lock. While Communications is down, every message in the game group that is not an
  Among Us command is DELETED (bot must be group admin). Kept: the commands listed in
  `COMMS_GROUP_ALLOWED_COMMANDS` (amongus_config.py) and the repairer's phrase answer. Applies to non-players too.
  A meeting lifts it; it returns after the meeting if Comms is still down; repair / match end / `.endgame` end it.
- Renames: `COMMS_GROUP_LOCK_ENABLED` -> `COMMS_RESTRICTION_ENABLED`, `COMMS_LOCK_LIFTED_DURING_MEETINGS` ->
  `COMMS_RESTRICTION_LIFTED_DURING_MEETINGS`, manager hook `_set_group_lock` -> `_set_comms_restriction`,
  `group_action` "lock"/"unlock" -> "restrict"/"unrestrict" (now a record signal only; no WhatsApp setting changes).
- Phrase answers are given in the GROUP: reply to the bot's scrambled-phrase message (hidetag, carries `[Task Ref]`)
  or `.task answer <phrase>` in the group. Group replies are prefixed `*Colour:*`. Only the player repairing can do it;
  any other non-command message is deleted. DM answers are refused with a pointer to the group and do not count as an
  attempt (enforced in the manager, so `Game.handle` itself is unchanged and tests that call it directly still work).
  The repairer's DM no longer carries a `[Task Ref]`.
- Restart safety (bot/bridge.js): the restricted group is written to `amongus_comms_restrictions.json` (in ROOT)
  BEFORE the restriction starts and removed when it ends. When the Python engine reports ready, any recorded group is
  stale (the match was lost): the record is cleared and each group gets one notice. Nothing in WhatsApp needs undoing.
  If the bot is not admin it posts one warning per group per process (best effort; skipped if admin status unknown).
- Forwarding: groups in the record count as Among Us groups when JS calls Python, and `should_intercept_group` is true
  for a restricted game group, so plain text reaches the filter even if the pool is off.
- Old assertions updated: 7d (hook name), 8 (`"unrestrict"`), simulator (a bot sends comms phrase answers in the group).
  New test: tests/amongus_session9_pkg6a_test.py (added to `npm run test:amongus`).
- NOT RUN: the update zips do not contain the unchanged modules (amongus_puzzles/comms/sabotage/movement), so the suite
  could not run here. Only a stubbed smoke check of the filter/routing and `py_compile` / `node --check` ran. Run
  `npm run test:amongus` first. Also search the tests I was not sent for the old names:
  `grep -rn "_set_group_lock\|COMMS_GROUP_LOCK\|COMMS_LOCK_LIFTED\|_group_locked\|Only the repairer" tests/`
  and for comms phrase answers sent through the manager as a DM (7b2ci etc.); those must go to the group now.
- Needs a real-group check: message deletion by the bot (admin), that plain text and quoted replies from the group
  reach Python (unseen group handler), that bot messages still appear, restart mid-outage (record cleared + notice).
- JS changed: bot/bridge.js (restart the bot). Python: amongus.py, amongus_game.py, amongus_config.py, bridge.py (docstring).
- Undecided (nothing invented): wording of the restart notice and the not-admin warning is mine; say if you want it changed.

## Package 6b - Group registry and ghost-group pick (done; 16 new tests pass on a stubbed harness only)
- Six owner-only commands, run in the group: `.set` / `.unset` `alobbygc` and `aghostgc`, plus `.alobbygcs` and
  `.ghostgcs` (lists work anywhere for the owner). Non-owners get "Only the bot owner can use that command."
  One role per group; `.unset` is refused while the group is in a live game; a duplicate `.set` is a no-op message.
- List format (your "Yh" on the proposal): numbered, `Group …<last 6 digits> — <status>`, no raw IDs.
  Status: lobby = in a game / lobby open / idle; ghost = in use / free. Empty list says none are registered.
  (No group-name lookup exists in the Python side, so the short ID is always used.)
- Storage: Python side, `amongus_group_registry.json` in the bot root (override with env `AMONGUS_REGISTRY_FILE`),
  atomic write, survives restarts and match ends. Deviation from the plan: I was not sent `bot/groups.js`, so the
  registry is not stored there. New file: engine/router/amongus_registry.py.
- Ghost pick at match start (recorded rule from Package 2): lobby group N uses ghost group N (registration order).
  An unregistered lobby group uses the ghost group only if exactly one is registered. A ghost group already in a live
  match is never reused. Otherwise none, and ghosts fall back to DMs as before.
- `.setghostgroup` is retired everywhere (manager, coordinator, `.amenu`, allowed-commands list, bridge.js).
- Owner check: `from core.permissions import is_king` called as `is_king(sender)`. I could not see that file, so the
  signature is a guess; it fails closed (nobody is owner) if the import or call fails. CHECK THIS FIRST.
- bridge.js: the registry commands now force the Among Us pool for that message (same trick `.setghostgroup` used).
- Old assertions updated: session 6 (`.setghostgroup` test replaced by a retirement check). New test:
  tests/amongus_session9_pkg6b_test.py (added to `npm run test:amongus`).
- Not seen: any other test using `.setghostgroup` (e.g. session 3) must be updated or removed.
  Search: `grep -rn "setghostgroup" tests/`.
- Needs a real-group check: owner commands in real groups, and ghost chat landing in the picked group.

## Package 6c - Package 6 cleanup and first full-suite run (done)
First time the update was overlaid on the full bot snapshot, so the whole suite could run. Source code unchanged; tests only.
- Result: all 28 Among Us test files OK (`npm run test:amongus`); `node --check` passes for bot/bridge.js and bot/handler/entry.js.
- `is_king(sender)` checked against engine/core/permissions.py: signature is correct (the 6b guess was right).
- Stale 6a names fixed in tests/amongus_session7b2bi_test.py and 7b2ci_test.py: `_set_group_lock` -> `_set_comms_restriction`,
  `COMMS_GROUP_LOCK_ENABLED` -> `COMMS_RESTRICTION_ENABLED`, group actions `lock`/`unlock` -> `restrict`/`unrestrict`,
  record events `group_locked`/`group_unlocked` -> `comms_restricted`/`comms_unrestricted`. Test names still say "lock"; behaviour checked is unchanged.
- 6b test (tests/amongus_session9_pkg6b_test.py) now bootstraps engine paths by importing amongus_session7d_test first, like the other suites
  (it only ran on the stubbed harness before; failed on `No module named 'models'` in the real tree).
- 6a test: `.lobby list` replaced by `.players` in the kept-commands check (the mocked router has no real lobby map); the "announcement"
  check now looks for the quoted setting name, since bridge.js contains the word in a comment.
- No other `.setghostgroup` / old-lock-name references remain outside the retirement checks.
- Not run (network/environment): tests/golden_handle_test.py. Run it on the device.
- Still open from 6a/6b: real-group checks (deletion as admin, restart mid-outage, owner commands, ghost chat in picked group).

## Package 7 - Acceptance suites S1-S16 (done)
New test: tests/amongus_session9_pkg7_test.py (21 tests, added to `npm run test:amongus`). Each scenario drives the real
manager and Game through real commands on the simulated clock (tests/amongus_sim.py). Result: all 29 Among Us test files OK;
`node --check` passes for bot/bridge.js and bot/handler/entry.js.

Results (simulator only; PASS here does not cover real WhatsApp behaviour):
| ID | Result | Note |
|---|---|---|
| S1 | PASS | kill waits 5 s (still alive at 4 s) and cooldown 30 s; vote before 60 s refused; 3-message reveal; one match-over; personal DMs |
| S2 | PASS | singular wording ("1/1 Impostor remains.", "The Impostor was"); tie goes to Impostors |
| S3 | PASS | activation never names the Impostor; only the saboteur gets "sabotage initiated"; Reactor timeout win |
| S4 | PASS | Impostor's vote acknowledgement identical to a crew member's; final DM reveals no voters |
| S5 | PASS | ghost `.say` stays out of the group and out of living DMs; ghost cannot vote. Half travel time is checked as the constant only |
| S6 | PASS | pending kill cancelled by the meeting; no elimination after it |
| S7 | PASS | task answer refused during the meeting; interaction survives it and finishes afterwards |
| S8 | PASS (weak) | checks no duplicate or erroring arrival notices only; the exact Session 02 ordering is not asserted |
| S9 | PASS | four sabotages active together; repairing Lights leaves the other three active; Impostor action changes nothing |
| S10 | PASS after a fix | FOUND AND FIXED: the confirmed line "The oxygen tank has been used up!" (06D) was missing; added between `OXYGEN FAILURE!` and the result line (amongus_game.py `SABOTAGE_FAILURE_TEXT`; pkg 2 test extended) |
| S11 | PASS | Reactor timeout; exactly one match-over; the exact-deadline rule itself is covered by the pkg 3 tests |
| S12 | PASS | plain `scan` explained and not counted; two reply-scans within 2 s repair; other sabotages unaffected |
| S13 | PASS | restriction lifts for the meeting, returns after it, ends on repair; at most one inactivity report |
| S14 | PASS | all tasks done -> crew win with reveal; `done` never completes a task |
| S15 | PASS | departed player's unfinished tasks leave the total, finished ones stay; last Impostor leaving gives one crew win; no DM to the departed |
| S16 | PARTIAL | `.endgame` cancels meeting, sabotages, restriction, timers and sends no result DMs. The restart-mid-Comms half lives on the JS side and is NOT covered here (see below) |

Also checked: whole-match fuzz on 4 + 3 seeds with every sabotage enabled (one match-over each, one result DM per player, silence
and no leftover timers afterwards, no real WhatsApp identity in any message, no activation naming an Impostor).

!! Not covered / still open:
- Real-WhatsApp-group acceptance run (Session 09 section 8): bot-as-admin message deletion during Comms, restart mid-outage,
  group invite link lookup, hidetag, 2 s reveal spacing, owner registry commands, ghost chat in the picked group. Record PASS/FAIL/BLOCKED there.
- Match-over wording: the bot still sends "Crewmates win! ..." / "Impostors win! ..." (not the 07 sample `CREWMATES WIN!` / `The Impostors were:`). Tests do not
  lock this wording; approve one and I will change it and the tests together.
- Session 08 card S10 also lists the 20 s / 10 s warnings; they are sent as "20s remaining" / "10s remaining" (placeholder wording).
- Mini-previews (meeting caller, ejection) are still not built (no images in `preview-images/`).
- Which ghost group a match uses when several are registered is implemented as registration order (Package 6b); still unconfirmed.
- Not run here: tests/golden_handle_test.py (network) and the JS suite (no node_modules). Run both on the device.
- Stale `__pycache__` can make a changed constant look unchanged; delete `__pycache__` folders if a test result looks wrong.

## Package 8 - Silent unknown commands, image-links folder, cleanup (done)
New test: tests/amongus_session9_pkg8_test.py (13 tests, added to `npm run test:amongus`). All 30 Among Us test files OK; `node --check` passes for bot/bridge.js.

1. Unknown commands are silent while the Among Us pool is on. Removed every "not a command" reply:
   - `Game.handle`: "Not a recognised in-game command" -> no reply. Ghosts: the "Ghosts can move with ..." hint -> no reply.
   - Manager: "Not a recognized Among Us command" and "The game is over. Start a new lobby" -> pass through (`NOT_HANDLED`), so the rest of the bot
     handles the text exactly as if Among Us were off (lobby phase, group, after a match).
   - Game group during a live match: only real Among Us commands get "Game commands are private"; anything else passes through untouched.
   - Kept on purpose (not unknown-command errors): the task hint for plain text while you are mid-task, and "Game commands are paused during the meeting".
   - Old assertions updated: 7b1biii, 7b2ai, 7c (they expected the error text; now expect no reply).
2. Image folder instead of `preview-images/`: `assets/amongus/image_links.json` holds DIRECT links (blank by default). `meeting_call` (caller's colour) rides on the
   meeting-call group message; `ejection` (ejected colour) rides on the third reveal message. Per-colour link, else `default`, else plain text as before.
   Re-read on change (no restart); override path with env `AMONGUS_IMAGE_LINKS`. New: engine/router/amongus_images.py, assets/amongus/README.md.
   Plumbing: `_broadcast(image_url=)` -> engine/bridge.py `_direct_send(image_url=)` -> bot/bridge.js `sendImage` (falls back to the text if the image fails). Restart the bot.
   Not verified here: a real image send in WhatsApp (needs your links and a live group). The `.preview` card code was not touched.
3. Cleanup: `cleanup_stale.sh` (run `sh cleanup_stale.sh` in the bot folder) removes all `__pycache__` folders, `bot/handler/web_cmds.js.bak`, `bot/media.js.bak`, and the empty
   mistyped `ests/` and `ngine/` folders. An overlay zip cannot delete files, hence the script. `*.bak` added to .gitignore. Left alone: `assets/cards/` and `.sprite_cache/`
   (empty runtime folders), `broken/` (has its own README). No unused Among Us config constants were found.
4. Decision recorded (ghost groups): lobby group N uses ghost group N (registration order) - as already implemented in Package 6b. Closed.


## Package 9 - Session 08 close-out: edge-case checklist (done)
New test: tests/amongus_session9_pkg9_test.py (19 tests, added to `npm run test:amongus`). All 31 Among Us test files OK; `node --check` passes for bot/bridge.js and bot/handler/entry.js.
One real bug found and fixed:
- BUG: a finished match (and the lobby it came from) kept claiming its players. After a match ended in group A, any later match in group B
  answered every private command with "You're in more than one Among Us game", and `.GC` was ambiguous. Fix: `AmongUsManager.contains_player`
  (engine/router/amongus.py) now counts only an OPEN lobby or a LIVE match. Nothing else changed; a player can still be in two live matches
  (Session 1 design) and is then asked to name the group.
- Old assertions updated deliberately: tests/amongus_session1_test.py (two hand-made `_meeting` dicts lacked a start time, so the world clock ended the
  match on them and the test passed only because ended matches kept their players; they are now cleared once checked) and tests/amongus_session9_pkg5_test.py
  (the mock lobbies now say `started=False`, i.e. a real open lobby).
Checklist coverage (Session 08 section 6): lobby replacement during a match, two-group isolation, finished-match release (the bug), two live matches,
state after restart (fresh manager leaves every text to the rest of the bot), colour resolution (case, spaces, unknown, self, partial, dead), pending kill vs
match end and vs movement, stale backstop timers (firing all of them is a no-op), `.stop` in a corridor leaves no stale arrival, camping once per stop,
follow ends on vent and when the follower starts a task, crime-scene history after a meeting, whole-match identity/leak fuzz.
Not covered (cannot be from here): cross-group routing and Pokemon-mode interference (tests/golden_handle_test.py needs network - run it on the device);
the JS half of restart safety (Comms restriction record in bot/bridge.js; no node_modules here); a real WhatsApp group run.
S8 CLOSED (user: "within a second"): arrivals into the same room within `C.SIMULTANEOUS_ARRIVAL_SECONDS` (1.0) are simultaneous - neither gets a "beside you"
notice for the other; both get the paired "Nearby room update". Files: amongus_config.py, amongus_movement.py; 2 new tests (21 in pkg9).
Still open, nothing invented: match-over wording (07 sample text vs current
"Crewmates win!"); 20 s / 10 s warning wording; mini-previews (no images yet).

## Package 10 - DM sender fix (JS) (done; found by reading bot/handler/entry.js)
SYMPTOM (your phone run): Among Us pushed notices arrived (role DM, camping notices) but replies to `.status`, `.where`, `.tasks`, `.m` never did.
CAUSE (very likely): the DM path sent Python the raw chat id. If the DM arrives as an `@lid` chat, Python does not know that id (players are registered by phone jid
from the group), so the reply is dropped silently; pushes go to the phone jid and still work.
FIX: bot/handler/entry.js maps an `@lid` DM to the phone jid (`msg.key.remoteJidAlt`, else `lidMap`) before calling Python for Among Us commands/task replies; the reply still goes to
the chat it came from. Non-Among-Us DMs are untouched. New JS test: tests/js/amongus_dm_test.mjs (5 cases; failed before the fix, passes now) - run `npm run test:amongus:js`.
TO CONFIRM ON THE PHONE: the bot console prints `[HANDLE] chatJid=...`; if your DMs show `@lid`, this was the cause. RESTART THE BOT (JS changed).
Not run: the full tests/js/golden_handler_test.mjs; card_test.mjs fails here independently of this change (externalAdReply).

## Package 11 - `.map` (done)
`.map` (DM, living players, Ghosts, during meetings, and lobby members before the start): sends the Skeld picture with a caption - the map name, YOUR own room (or "between X and Y",
or "inside a vent at X"), and your exits with travel seconds taken from the room graph - then "Use .m <room> to move." Never shows anyone else's position.
- The picture link lives in assets/amongus/image_links.json under `maps` -> `skeld` (set to https://i.ibb.co/fVwcF21P/The-Skeld-map.jpg). No link / image fails = the same text is sent alone.
- Python: amongus_game.py (`_cmd_map`), amongus.py (`_push_dm(image_url=)`, lobby `.map`), amongus_images.py (`map_link`), amongus_config.py (allowed in the Comms group list), `.amenu` text.
- JS (restart the bot): bot/bridge.js now lets a DM push carry an image (before, only group pushes could); bot/handler/entry.js DM regex includes `map`.
- New test: tests/amongus_session9_pkg10_test.py (6 tests). The JS push path itself is not covered (it lives inside the Python-process handler); `node --check` passes. Needs a real-phone check.
- NOT changed, needs the user: Electrical's connection. The code links Electrical to Security; the supplied picture's long bottom corridor looks like Lower Engine -> Electrical. Waiting for a yes/no before editing the room graph.
- Not built: the "you are here" dot on the image; a vent-only Impostor map.

## Package 12 - stage previews (done; picture look NOT seen - the build sandbox cannot reach your image hosts)
User rule: the stage picture is the BACKGROUND for the colour character. Square stage = MINI preview; landscape stage = FULL preview. Character sits on the LEFT (design note), near the bottom.
- New: engine/router/amongus_stage.py. Links in assets/amongus/image_links.json: `stage.square` / `stage.landscape` (each with `default` and optional `crewmate` / `impostor` backgrounds)
  and `characters` (colour -> character PNG). Set from your links: square = among-stage-square.jpg, landscape = amongus-stage-landscape.jpg, 11 characters.
- Where each is used (my choices - say if you want them different):
  MINI (square): meeting-call group message (caller's colour; NEVER role-specific, so an Impostor calling gives nothing away), the ejection reveal (ejected colour; background by the
  ejected player's role category), and `.status` (your own colour and role background; the status text becomes the picture's caption; Ghosts too).
  FULL (landscape): the role DM at match start (role-category background; Scientist counts as Crewmate).
- Never blocks the game: images are downloaded in a background thread when a lobby opens (`warm`) and cached in assets/amongus/.cache/; a composite is made only from files already on disk
  (Pillow, saved as JPEG, longest side <= 900 px) and reused. Not ready yet / offline / a character PNG with no transparency -> falls back to the old plain colour image (meeting, ejection) or plain text
  (`.status`, role DM). Nothing breaks.
- The layout numbers (character height share, left margin, bottom margin) are `LAYOUT` in amongus_stage.py - tune after you see the first picture.
- Same background for both roles for now (you sent one stage per size); add `crewmate` / `impostor` links under `stage` when you have role-specific stages.
- JS (restart): bot/lib/send.js `isStageFile` + `sendImage` can send a local cached file (only inside the stage cache folder); bot/bridge.js accepts such a file. .gitignore: assets/amongus/.cache/.
- Tests: tests/amongus_session9_pkg11_test.py (13, synthetic pictures, no network), tests/js/amongus_image_file_test.mjs (path safety + file vs URL). tests/amongus_sim.py sets AMONGUS_STAGE_OFFLINE=1.
- NOT verified: that your character PNGs are transparent cut-outs (opaque ones are skipped on purpose), and how the composite looks on your real pictures. First check on the phone.

## Package 13 - design note v5.3 text (done; Python only, no JS change, no restart of JS needed beyond a normal restart)
Source: ARIEL_AMONG_US_MASTER_DESIGN_NOTE_v5_3.md section 22. All 33 Among Us Python test files OK with AMONGUS_STAGE_OFFLINE=1 and no stage cache; JS tests OK.
- `.status`: Role / Status (Alive or Ghost) / Location / Players with you (list) / `Cooldowns: Use .cds to check` / Match (In progress, Meeting, Ended). Fixes the nested `*` bug. "Bodies here" and "Following you" lines kept (they drive witnessing and follow discovery).
- `.where`: "You are currently at the <room>." + "Use .tasks to see available tasks." `.map` caption: map name, your location, "N/M players left" (living / started; frozen list during Comms), then the old exits line and move hint.
- Final arrival: "You have arrived at X." [+ "Red arrived beside you."] + "Players: A, B, you" + `.tasks` and `.status` hints. Arrivals within SIMULTANEOUS_ARRIVAL_SECONDS (1 s) are named inside the arriving player's message; an earlier arrival still gets the paired "Nearby room update". Settled occupants now see "X arrived beside you."
- `.tasks`: TASKS LIST (Your tasks numbered per player / General tasks = active sabotage stations / Finished tasks struck through).
- Body DM exact text; meeting call (group + DM, emergency vs body report); "Voting has been opened"; "10 seconds remaining! Cast your votes to remove the Impostor."
- Meeting result: EJECTION_REVEAL_STEP_SECONDS 2 -> 4. Sequence: "Meeting has ended." / "..." / "......." / one merged result (no-ejection, not-the-Impostor, Impostor + remaining count); "Carry on..." is omitted when the result ends the match. Scientists are no longer named in the reveal.
- Tests: fake managers now accept `image_url` (seven files failed on the pkg12 archive for that reason); old wording assertions updated deliberately; new tests/amongus_session9_pkg13_test.py.
- Open / my choices: "players left" meaning; "General tasks" meaning; suspense texts reuse the dots; Scientist reveal; kill timer left at 5 s / 30 s cooldown (note says 4 s / 5 s - your package 1 decision kept). Nothing checked on a real phone.

## Note session N1 - lobby and setup text (done; Python only)
Source: command sheet, reply design section A. Files: engine/router/amongus.py, amongus_game.py (`_announce_roles`, start broadcast).
- `.amongus on`, `.lobby open` (adds Players n/MAX), `.join` ("Player N joined the lobby." + roster, no colours before start), `.leave`, `.lobby list` (none open), `.lobby test`, `.endgame` reworded per the draft.
- Role DM: "Your role: X / Colour / Starting room / [Fellow impostor(s), Impostor only] / goal / Use .amenu". Start group line: "Players: n · Impostors: k".
- Old-wording assertions updated deliberately in session1, session8, pkg7, pkg11 tests. New: tests/amongus_note_s1_test.py (3). All 35 Among Us Python tests pass with AMONGUS_STAGE_OFFLINE=1 and the stage cache removed (with the cache present, `.status` sends a picture and 4 older tests fail - environment, not code).
- Not done: lobby artwork, ship map after start (sheet decisions 11, 12).

## Note session N2 - movement and player-info text (done; Python only)
Source: command sheet, reply design section B. Files: engine/router/amongus_game.py (`_cmd_move`, `_rooms_list`, `_cmd_status`, `_cmd_progress`, `_cmd_players`, `_cmd_crime_scenes`, vitals/witness gate), amongus_movement.py (`stop`, `go_back`, `where`), amongus.py (`_lobby_map`).
- `.m` room list + start text, `.stop` hint, `.goback` "about Ns", `.where` as "📍 *Your location*", pre-match `.map`, `.status` as "📍 *YOUR STATUS*" (others only, Bodies here always shown, Cooldowns hint last), `.players` header, `.progress` with done/total, `.cscene` empty header, Scientist-only gate wording.
- Impostor `.progress`: fake % with a matching fake done/total (same shape as crew). Comms outage: header + garbled reading only, no counts.
- Old-wording assertions updated deliberately in session2, session3, 7b2aii, pkg9, pkg13 (pkg13's "no asterisks at all" status rule is now "no nested ** "). New: tests/amongus_note_s2_test.py (7) + a pre-match map test in note_s1. 36 Python test files pass with AMONGUS_STAGE_OFFLINE=1 and the stage cache removed.
- Not changed: in-match `.map` caption, `.cds`, arrival/passing/other-player DMs, vitals/witness output.

## Note session N3 - task text (done; Python only)
Source: command sheet, reply design section C. File: engine/router/amongus_game.py (`_start_task_interaction`, `_cancel_task_interaction`, answer handler, `_cmd_task`, `_cmd_tasks_all`).
- `.tasks`: bold section titles, "Finished tasks" always shown ("None" when empty). `.task`: "Tasks here: {Room}" + send hint. Prompt: `.task answer` command bold instead of backticks. Wrong answer, correct answer (Tasks remaining + Team progress), timeout text reworded.
- BEHAVIOUR FIX: `.task next` was cancelling with notify=False, so the "abandoned" DM was never sent. It now is, before the new prompt.
- Unchanged: impostor fake-task and Ghost completion wording, movement/vent/left-game/death cancel lines, all repair-puzzle text, error lines, room DMs.
- Old-wording assertion updated in session5 ("expired after 60 seconds"). New: tests/amongus_note_s3_test.py (8). 37 Python test files pass with AMONGUS_STAGE_OFFLINE=1 and stage cache removed.

## Note session N4 - impostor and follow text (done; Python only)
Source: command sheet, reply design section D. File: engine/router/amongus_game.py (kill start/cancel/resolve, `.vent in`, `.follow`).
- `.kill` start text, victim DM ("You're now a Ghost"), witness DM ("involving *{victim}*"), pending-kill cancel reasons (you moved / {colour} moved / a meeting was called), `.vent in`, `.follow` success.
- NOT changed: kill timer (KILL_DELAY_SECONDS, decision 2 still open), cooldowns, who counts as a witness, `.sabotage`, `.unfollow`, "Trailing..." DM, distress/corpse lines.
- Old-wording assertions updated: session3, 7b2aiii, pkg9 (tailing -> following), session4 (meeting cancel). New: tests/amongus_note_s4_test.py (4). 38 Python test files pass (AMONGUS_STAGE_OFFLINE=1, stage cache removed).

## Note session N5 - report, meeting and voting text (done; Python only)
Source: command sheet, reply design section E. File: engine/router/amongus_game.py (`_cmd_report`, `_cmd_call_meeting(report=...)`, `_meeting_voting_open`, `_meeting_warning`, `_announce_ejection`).
- DECISION 9 applied: the separate "📢 reported a witnessed body" group line is dropped; the body-report call now carries room + victim ("found a corpse in {Room}!", "Victim(s)"). Emergency call, voting open (group + DM), 10 s warning and "Meeting ended." reworded per the drafts; no-body error gained the warning emoji.
- Kept: staged "..." / "......." suspense and result lines (decision 5), voter DM headline ("found a corpse!"), DM link + mini-preview attachments, vote replies, paused-command text, all timings.
- Dropped by the draft: the "for example .vote {colour}" hint in the voting DM.
- Old-wording assertions updated in session6, pkg5, pkg7, pkg8, pkg13. New: tests/amongus_note_s5_test.py (5). 39 Python test files pass (AMONGUS_STAGE_OFFLINE=1, stage cache removed).

## Note session N6 - sabotage and repair text (done; Python only)
Source: command sheet, reply design section F. Files: engine/router/amongus_game.py (sabotage warning/repaired events, Lights prompt, `_start_sabotage_repair_interaction`, Communications group prompt), amongus_paired.py (scan-missed DM, 2 places).
- Warning: "⚠️ *{Name}: {n}s remaining.*" + "Reach the required station(s)..." (timings unchanged; O₂ now shows "O₂", not "Oxygen"). Repaired: "...sabotage repaired.* The ship is safe for now." Lights start prompt: bold `.task answer <number>`, no duplicate "Send a number" line. Communications group prompt rewritten ("Unscramble: ..." / "Only {Colour} can submit..."). Scan-missed text.
- NOT changed (moved to N7 with match-over): SABOTAGE_FAILURE_TEXT (Reactor meltdown / OXYGEN FAILURE) - current lines are marked user-confirmed 06C/06D; the draft differs. Also unchanged: announcements (no short descriptions), personal repair replies, Comms DM, all error lines, all timings.
- Old-wording assertions updated in 7a, 7b2ci, 7c, 7d, pkg4, pkg6a. New: tests/amongus_note_s6_test.py (6; the scan-missed check inspects source text). 40 Python test files pass (AMONGUS_STAGE_OFFLINE=1, stage cache removed).

## Note session N7 - match-over and ghost text (done; Python only)
Source: command sheet, reply design section G. File: engine/router/amongus_game.py (`SABOTAGE_FAILURE_TEXT`, `_finish`, `_send_result_dms`, `_resolve_win_check`, `_fail_sabotage` fallback, `_cmd_vote`).
- Group ending: headline, reason on its own line, blank line, Impostor reveal. Reasons are the existing wording (decision 1, per-ending wording, is NOT resolved): ejected / last Impostor left / tasks complete / equal or outnumber.
- Reactor and O2 failure headlines now follow the approved draft: "Reactor meltdown — Impostors win." and "OXYGEN FAILURE! / The oxygen supply has run out. / O₂ depleted — Impostors win." (replaces the 06C/06D confirmed lines; the draft was approved with "implement the note").
- Result DM: "Match over — {Crewmates|Impostors} win!" / "Your role: *{Role}* ({Team})." / won-lost line. Colour dropped from that line, article ("a/an") dropped from the role.
- Ghost `.vote` in a meeting: "👻 _Ghosts cannot vote._" (departed players keep the old "Only active living players can vote" reply).
- Checked, unchanged: not-in-game / left-game errors, group privacy notice, ghost chat line, "everyone left" line, world-clock error, all timings and win logic.
- Old-wording assertions updated in note_s6, pkg2, pkg5, pkg7. New: tests/amongus_note_s7_test.py (8). 41 Python test files pass (AMONGUS_STAGE_OFFLINE=1, stage cache removed); bugfix_regression and golden_handle also pass.
- Still open: N8 (assets) blocked on decisions 11, 12.

## Note session N8 - image slots (done; Python + JSON only)
Source: command sheet, section H decisions 11 and 12. Decision 11 (owner): the ship map goes to the GROUP only. Decision 12 (owner): no artwork supplied yet, so only the places for it were added.
- assets/amongus/image_links.json: new top-level `lobby` and `tasks_list` slots, both blank. `amongus_images.py`: `slot_link`, `lobby_link`, `tasks_list_link` (same rules as the other links: https only, blank/invalid = text only, re-read on change, no restart).
- `.lobby open`: with a `lobby` link the same text goes to the group as that image's caption; without one it is the plain text reply as before (amongus.py `_lobby_open`).
- `.lobby start`: the "Game live on {map}!" group message carries the `maps.<map id>` picture when set. Role DMs are not given the map. (amongus_game.py `_announce_roles`)
- `.tasks`: a living player's TASKS LIST goes to their DM with the `tasks_list` picture when set (returns None, like `.map`); ghost task list and the no-link case stay text. `_cmd_tasks_all` now wraps the unchanged text builder `_tasks_all_text`.
- No wording changed. New: tests/amongus_note_s8_test.py (10). 42 Python test files pass (AMONGUS_STAGE_OFFLINE=1, stage cache removed); bugfix_regression and golden_handle pass. The JS side already sends any `image_url` (bot/bridge.js), so no JS change.
- Not done: the pictures themselves; the TASKS LIST image should be sized for a caption of a few lines (the list can grow).

## Note session N9 - lobby maps (done; Python + JSON)
- New maps in `engine/router/amongus_map.py`: `cyberia` (Cyberia Facility, 13 rooms) and `orbital` (Orbital Research Station, 17 rooms), each with edges, vents, one task per room and sabotage stations. Room links and travel seconds were read off the supplied pictures and are gameplay values: adjust freely. The tiny camera room (top right) on Orbital is not modelled.
- `.lobby map` lists maps; `.lobby map <number|name>` (host only, before start) sets it. `.lobby open` now picks a RANDOM map (`M.random_map_id()`); `AMONGUS_FIXED_MAP=<id>` pins it.
- `image_links.json`: `lobby` and `tasks_list` filled; new stage backgrounds `stage.square.emergency / report / ejection` (used by meeting call, body report, ejection reveal; fall back to `default`). `maps.cyberia` / `maps.orbital` are blank until the two map pictures are hosted.
- Tests: `tests/amongus_maps_lobby_test.py` (4) + `amongus_testlinks.py` helper (pins Skeld, blanks single-picture slots). 43 Python test files pass.
