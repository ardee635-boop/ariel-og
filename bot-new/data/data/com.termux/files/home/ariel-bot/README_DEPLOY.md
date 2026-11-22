# What's in this drop

Everything from the "scene objects are real" fix through arrival
narration, choice filtering, and the shared corpse store. Built and
tested against your `whatsapp-bot-2026-09-21_16-55-51.zip`.

## File destinations (one is renamed — don't miss this)

Copy each file to the SAME path it already has in your repo, except:

    router_rpg.py  ->  router/rpg.py   (renamed only because this
                                         upload can't contain folders)

Everything else keeps its name:

    rpg_scene.py        NEW FILE — the scene-object store + noun
                         extraction + choice filtering. Nothing
                         imports this yet until the other files below
                         are also updated.
    rpg_session.py       modified
    rpg_engine.py         modified
    rpg_engine_test.py    modified (existing tests updated, not
                           weakened — see "What changed in the test
                           file" below)
    bridge.py             modified (one small addition)
    router/rpg.py          modified (renamed to router_rpg.py here)
    rpg_map.py            modified (one new function)
    rpg_movement.py        modified
    database.py            modified (one new table + helpers)

## Before you deploy: run this

    python3 rpg_engine_test.py

Expect `ALL TESTS PASSED` and exit 0. This is your existing test
file — updated, still 24 checks, not replaced with anything weaker.
If this doesn't pass after copying the files in, something didn't
copy cleanly — stop and check before going further.

## What actually changed, in the order it was built

**1. The core bug (scene objects aren't real).** `rpg_scene.py` is a
new module: a store for anything the narrator describes — a squirrel,
a fountain, a pen, a corpse — with stacking counts (two cups = one
entry, count 2), weight classes (tiny/light/heavy/fixed — controls
what can be picked up), and turn-based expiry for short-lived things
like a creature that wanders off. `rpg_session.py` and `rpg_engine.py`
now route pickup/hold/validation through it instead of exact-string
matching, which also fixed a silent bug where "the cup" never matched
a stored "cup" and pickups quietly failed.

**2. Noun extraction.** After the narrator writes its reply, a small
SECOND model call reads just that text and records what it says is
physically present. This is what makes a described-but-unrecorded
thing (a squirrel, a fountain) actually real for the next action. Runs
AFTER the reply is already sent to the player (see `bridge.py`'s
addition) so it never slows down what they see — bounded to 5 seconds,
and if it's slow or fails, nothing is recorded that turn rather than
corrupting anything.

**3. Combat against a scene creature.** Per your "settlements have a
ward" rule: a recorded creature (a squirrel, not just an NPC) can now
be attacked, but inside a warded settlement damage is clamped so it's
never lethal. Outside settlements / against real NPCs, undamaged —
full stakes as before.

**4. Choice filtering.** The narrator's 3 numbered options are now
also judged by the extraction pass: a choice that fits the place (a
library plausibly having a librarian) is kept AND that thing becomes
real; a choice that contradicts what's actually there (an instructor
at a location whose own notes say no one is present) gets swapped for
a safe fallback before a player can tap it. The already-sent reply
can't be edited, but the numbered-tap resolution can, and is.

**5. Arrival narration — the actual Flag 4 fix.** Ordinary moves to an
existing place used to end with a bare "You make your way to X." and
the PREVIOUS scene's stale choices. Now every move runs a real
narration call on arrival, so the new place gets a description, fresh
choices, and scene objects the extraction pass can seed from.

**6. `*TRAVEL LOG*` header.** Every move reply — success or failure —
now opens with a plain, code-written line that no LLM ever touches:

    *TRAVEL LOG* moved: the town square -> the church
    *TRAVEL LOG* not moved: <reason>

Everything after that line is narrator prose. If you ever wonder
whether a location change is real, this line is the answer — it can't
be wrong the way narrated text can be.

**7. Shared corpse store.** A new DB table
(`rpg_persistent_scene_objects`) holds things that should outlast one
player's own scene and be visible to everyone — currently just
corpses. If Alice kills a wolf, Bob showing up later at the same spot
sees the corpse too, even though nothing happened in Bob's own
session. Separate from the pre-existing `rpg_world_objects` table
(that one's for hand-authored fixtures like the gate barrel — kept
untouched, still unused by anything, same as before this drop).

## Known limits, unchanged from what we discussed

- Wording gap: "stone pillar" vs. an already-recorded "pillar" is
  treated as two different things, not merged. Would need fuzzier
  matching to fix; flagged, not built.
- No real-model testing — everything above ran against scripted fake
  LLM responses to prove the plumbing. How `gpt-oss-20b` actually
  behaves on the extraction/choice-judging prompts still needs a real
  beta pass.
- A failed shared-object write (the corpse table) is logged and
  swallowed, not surfaced to the player — they'd just not see the
  corpse that turn.

## What changed in the test file

`rpg_engine_test.py`: two edits, both fixes, neither weakens a check.
- Test 10 used to assert scene_objects equals an exact old-shape dict;
  entries now carry more fields (id/count/weight/etc.), so it asserts
  the same behavior (one entry, right name, right description,
  matchable) instead of a byte-exact dict.
- Test 7 (Fireball combat) was already flaky before any of this —
  85% accuracy meant it failed about 1 run in 8 for reasons unrelated
  to what it checks. Seeded the random roll so it's deterministic.

## New test files (not required to deploy, useful if you want to verify locally)

Ten files were built during this work, covering roughly 140
assertions across every piece above — the scene store, pickup/weight
gates, extraction, the deferred-write timing, creature combat, choice
filtering, arrival narration, and the shared corpse store, each
against the real router/DB where relevant, not just in isolation. Ask
if you want these included — they were left out of this drop since
they're development tools, not something the bot needs at runtime.
