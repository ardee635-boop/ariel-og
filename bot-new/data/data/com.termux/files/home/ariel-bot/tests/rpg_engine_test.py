"""
Standalone proof that rpg_engine.py's pipeline works, using a fake
Groq stand-in (no network/API key needed) plus one REAL Soulbound
character built via the actual soulbound.py conversion function.

Run: python3 rpg_engine_test.py
"""

import sys
import json

sys.path.insert(0, ".")

from rpg_engine import handle_rpg_action
from database import Database

# Real DB (falls back to local SQLite, same as the rest of the game) —
# calc_damage() needs it for PokéAPI type-effectiveness lookups. Not
# mocked: using a fake db here would risk the same mistake made
# earlier in this project of simulating behavior against fake data.
db = Database()


# ============================================================
# FAKE GROQ — deterministic stand-in, same call signature the
# real one will have: (system, user) -> str
# ============================================================

class FakeGroq:
    """
    Mimics what a real LLM WOULD do for extraction and narration,
    but deterministically, so this test doesn't depend on network
    access or API keys. Behavior is hand-written per the same rules
    given in rpg_engine.py's system prompts.
    """

    def __call__(self, system: str, user: str, **kwargs) -> str:
        # **kwargs absorbs json_mode/max_tokens etc. that the real
        # call_groq accepts and rpg_engine.py already passes — this
        # stand-in doesn't need them, but must accept them to match
        # the real call signature. (Pre-existing gap, not caused by
        # the recent_history change — call_groq_fn was already being
        # called with json_mode=True before that.)
        if "strict parser" in system:
            return self._extract(user)
        else:
            return self._narrate(user)

    def _extract(self, raw_text: str) -> str:
        # Mimics the extraction system prompt's behavior: strip any
        # "and <someone> <verb>s ..." clause the player tacked on,
        # and classify type/target the same way the real prompt's
        # examples do — deterministic keyword rules here are fine
        # since this is a TEST STAND-IN proving the pipeline plumbing
        # works, not a claim that keyword rules are good enough for
        # the real extraction call (that's the real Groq model's job).
        import re
        m = re.split(r"\s+and\s+(he|she|they|it)\s+", raw_text, maxsplit=1, flags=re.I)
        action = m[0].strip()
        lowered = action.lower()

        combat_words = ["attack", "swing", "cast", "fight", "hit", "strike", "shoot", "lunge"]
        social_words = ["convince", "persuade", "intimidate", "negotiate", "lie to", "deceive"]
        physical_words = ["sneak", "climb", "pick the lock", "balance", "force the door"]
        interaction_words = ["talk", "ask", "trade", "give", "take", "greet"]

        if any(w in lowered for w in combat_words):
            action_type = "combat"
        elif any(w in lowered for w in social_words):
            action_type = "social"
        elif any(w in lowered for w in physical_words):
            action_type = "physical"
        elif any(w in lowered for w in interaction_words):
            action_type = "interaction"
        else:
            action_type = "narrative"

        # crude target extraction: only "at/to <name>" patterns, and
        # only for a plausible short noun phrase (stops at "beside",
        # "with", punctuation) — avoids swallowing unrelated trailing
        # words like "with Fireball" or "beside me" as if they were
        # the target's name.
        target = None
        tm = re.search(r"\b(?:at|to)\s+(the|a|an)?\s*([a-z][a-z]*(?:\s+[a-z]+){0,2}?)(?=\s+beside|\s+with|\s*$|,|\.|\s+and\b)", lowered)
        if tm and action_type != "narrative":
            candidate = ((tm.group(1) + " ") if tm.group(1) else "") + tm.group(2)
            candidate = candidate.strip()
            # reject obviously-not-a-name leftovers
            if candidate and candidate not in ("me", "myself", "it"):
                target = candidate

        return json.dumps({"action": action, "type": action_type, "target": target})

    def _narrate(self, context: str) -> str:
        # Simple deterministic narration reflecting the given context
        # — good enough to prove the pipeline passes the RIGHT data
        # through, which is the actual thing under test. Returns the
        # same {"narration", "choices"} JSON shape the real prompt
        # now requires (see rpg_engine.py's _narration_system()).
        if "MISSED" in context:
            narration = "The attack goes wide, missing entirely."
            choices = ["Press the attack again", "Retreat a step", "Look for an opening"]
        elif "dealt" in context:
            line = next(l for l in context.splitlines() if l.startswith("Mechanical result:"))
            narration = f"[NARRATED] {line.replace('Mechanical result: ', '')}"
            choices = ["Follow up with another strike", "Check on your target", "Hold your ground"]
        else:
            action_line = next(l for l in context.splitlines() if l.startswith("Validated action"))
            action_text = action_line.split(": ", 1)[1]
            narration = f"[NARRATED] You {action_text.lstrip('I ')}."
            choices = ["Keep going", "Stop and look around", "Try something else"]
        return json.dumps({"narration": narration, "choices": choices, "new_npcs": []})


fake_groq = FakeGroq()


# ============================================================
# BUILD A REAL SOULBOUND CHARACTER (not hardcoded stats — run
# through the actual conversion function from soulbound.py)
# ============================================================

from soulbound import pokemon_to_soulbound

# Minimal fake Pokémon data, shaped like what pokeapi.py would give
fake_pokemon_data = {
    "name": "Ice King's Charmander",
    "base_stats": {
        "hp": 39, "attack": 52, "defense": 43,
        "special-attack": 60, "special-defense": 50, "speed": 65,
    },
    "default_moves": [],  # no db handle in this test, skills added manually below
}

player_soulbound = pokemon_to_soulbound(fake_pokemon_data, db=None)

# Manually attach one skill (normally done via pokeapi.get_move() +
# skills.pokemon_move_to_skill() when a db is available — skipped
# here to keep the test standalone/offline)
player_soulbound["skills"] = [{
    "name": "Fireball",
    "damage": 32,
    "accuracy": 85,
    "scaling": "INT",
    "element": "Fire",
    "damage_class": "Magical",
    "purpose": "Damage",
    "use_condition": "always",
}]

print("=== Player Soulbound sheet (built via real pokemon_to_soulbound) ===")
print(json.dumps(player_soulbound, indent=2, default=str))
print()


# ============================================================
# TEST 1 — the Aloth example: proposed outcome must be stripped,
# AND the premise must be validated (there genuinely IS a man
# beside the player in this world_state)
# ============================================================

world_state_village = {
    "location": "Oak Town — town square",
    "npcs": [{"name": "a weathered old man", "hostile": False}],
    "player": {"soulbound": player_soulbound},
    "flags": {},
}

print("=" * 60)
print("TEST 1: village, man present, player tries to inject outcome")
print("=" * 60)
raw = "I talk to the man beside me and he tells me about the forbidden texts of Aloth"
result = handle_rpg_action(raw, world_state_village, db=db, call_groq_fn=fake_groq)
print(f"Raw input:        {raw}")
print(f"Extracted action: {result['extraction']['action']}")
print(f"Had outcome?      {result['extraction']['had_proposed_outcome']}")
print(f"Valid premise?    {result['validation']['valid']}")
print(f"Reply to player:  {result['reply']}")
assert "Aloth" not in result["reply"], "FAIL: fabricated lore leaked into narration!"
assert "forbidden texts" not in result["extraction"]["action"], "FAIL: outcome not stripped from action!"
assert result["validation"]["valid"] is True, "FAIL: should have been valid — the man IS present!"
print(">>> PASS: no fabricated lore reached the player's reply.\n")


# ============================================================
# TEST 2 — the cave example: same line, but world_state has NO
# npcs present. Premise validation must catch this BEFORE
# narration even runs.
# ============================================================

world_state_cave = {
    "location": "Cinder Hollow — cave entrance",
    "npcs": [],  # nobody here
    "player": {"soulbound": player_soulbound},
    "flags": {},
}

print("=" * 60)
print("TEST 2: empty cave, same line — premise should be rejected")
print("=" * 60)
result2 = handle_rpg_action(raw, world_state_cave, db=db, call_groq_fn=fake_groq)
print(f"Raw input:        {raw}")
print(f"Extracted action: {result2['extraction']['action']}")
print(f"Valid premise?    {result2['validation']['valid']}")
print(f"Reply to player:  {result2['reply']}")
assert result2["validation"]["valid"] is False, "FAIL: should have rejected — no one is present!"
assert "Aloth" not in result2["reply"]
assert result2["choices"] == [], "FAIL: an invalid/rejected action should never offer stale choices!"
print(">>> PASS: premise correctly rejected, no fabricated NPC interaction.\n")


# ============================================================
# TEST 3 — pure narrative action, no interaction, no combat —
# should sail through with no validation/resolution blocking it
# ============================================================

print("=" * 60)
print("TEST 3: pure flavor action — 'I look around the tavern'")
print("=" * 60)
result3 = handle_rpg_action("I look around the tavern", world_state_village, db=db, call_groq_fn=fake_groq)
print(f"Extracted action: {result3['extraction']['action']}")
print(f"Valid premise?    {result3['validation']['valid']}")
print(f"Mechanical?       {result3['resolution']['mechanical']}")
print(f"Reply to player:  {result3['reply']}")
assert result3["validation"]["valid"] is True
assert result3["resolution"]["mechanical"] is False
print(">>> PASS: flavor action passed straight through, no resolver invoked.\n")


# ============================================================
# TEST 4 — a REAL combat action, wired through the ACTUAL
# calc_damage() from battle.py (not reimplemented/mocked)
# ============================================================

world_state_combat = {
    "location": "Route 1 — tall grass",
    "npcs": [{
        "name": "a wild Rattata",
        "hostile": True,
        "stats": {"STR": 30, "INT": 25, "DEF": 28, "SPD": 40, "DEX": 30, "WIS": 20, "CHA": 15},
        "types": ["normal"],
    }],
    "player": {"soulbound": player_soulbound},
    "flags": {},
}

print("=" * 60)
print("TEST 4: real combat action through battle.py's calc_damage()")
print("=" * 60)
result4 = handle_rpg_action("I attack with Fireball", world_state_combat, db=db, call_groq_fn=fake_groq)
print(f"Extracted action: {result4['extraction']['action']}")
print(f"Mechanical?       {result4['resolution']['mechanical']}")
print(f"Skill used:       {result4['resolution']['skill_name']}")
print(f"Damage dealt:     {result4['resolution']['damage']}")
print(f"Reply to player:  {result4['reply']}")
assert result4["resolution"]["mechanical"] is True
assert result4["resolution"]["damage"] is not None
assert len(result4["choices"]) == 3, "FAIL: expected 3 fresh choices from this turn's narration!"
print(f"Choices offered:  {result4['choices']}")
print(">>> PASS: mechanical resolution ran through the SAME calc_damage() battle.py uses.\n")

print("=" * 60)
print("ALL TESTS PASSED")
print("=" * 60)


# ============================================================
# TEST 6 — recent_history actually reaches both LLM calls (the
# "war?" continuity bug: extract_action used to see ONLY the raw
# current message, with no idea a war was mentioned one turn ago).
# This test doesn't fake LLM comprehension (FakeGroq is a
# deterministic stand-in, not a real model) — it proves the
# PLUMBING: that world_state["history"] is what actually lands in
# front of both calls, which is the thing that was broken.
# ============================================================

class FakeGroqCapture(FakeGroq):
    """Records the raw user-message text each call receives, so the
    test can assert on it directly instead of trusting behavior."""
    def __init__(self):
        self.extract_user_seen = None
        self.narrate_user_seen = None

    def __call__(self, system: str, user: str, **kwargs) -> str:
        if "strict parser" in system:
            self.extract_user_seen = user
        else:
            self.narrate_user_seen = user
        return super().__call__(system, user, **kwargs)


print("=" * 60)
print("TEST 6: recent history reaches extract_action and narrate_result")
print("=" * 60)
fake_groq_capture = FakeGroqCapture()
world_state_with_history = {
    "location": "Townia — the town square",
    "npcs": [{"name": "the elder", "hostile": False}],
    "player": {"soulbound": player_soulbound},
    "flags": {},
    "history": [
        {"action": "I ask the elder what happened here",
         "reply": "The elder says the town was rebuilt after the war."},
    ],
}
result6 = handle_rpg_action("war?", world_state_with_history, db=db, call_groq_fn=fake_groq_capture)

assert fake_groq_capture.extract_user_seen is not None, "FAIL: extract_action was never called!"
assert "RECENT CONTEXT" in fake_groq_capture.extract_user_seen, \
    "FAIL: recent_history wasn't folded into extract_action's user message!"
assert "the war" in fake_groq_capture.extract_user_seen, \
    "FAIL: the actual prior turn text isn't present in what extract_action saw!"
assert "war?" in fake_groq_capture.extract_user_seen, \
    "FAIL: the current message got lost when history was prepended!"
print("extract_action saw:\n" + fake_groq_capture.extract_user_seen)
print(">>> PASS: extract_action received the prior turn, not just the bare fragment.")

assert fake_groq_capture.narrate_user_seen is not None, "FAIL: narrate_result was never called!"
assert "PAST EVENTS" in fake_groq_capture.narrate_user_seen, \
    "FAIL: recent history wasn't folded into narrate_result's context!"
assert "is GONE" in fake_groq_capture.narrate_user_seen, \
    "FAIL: the explicit past-vs-present separation warning is missing from the prompt!"
print(">>> PASS: narrate_result received recent history, clearly labeled as PAST, not current surroundings.\n")

print("=" * 60)
print("TEST 6b: no history present -> both calls still work unchanged")
print("=" * 60)
fake_groq_capture2 = FakeGroqCapture()
world_state_no_history = {
    "location": "Townia — the town square",
    "npcs": [],
    "player": {"soulbound": player_soulbound},
    "flags": {},
    # no "history" key at all — must not crash, must behave exactly
    # as before this change (world_state.get("history") -> None,
    # .get("history", [])[-2:] -> [])
}
result6b = handle_rpg_action("I look around", world_state_no_history, db=db, call_groq_fn=fake_groq_capture2)
assert "RECENT CONTEXT" not in fake_groq_capture2.extract_user_seen, \
    "FAIL: history block appeared even with no history in world_state!"
assert fake_groq_capture2.extract_user_seen == "I look around", \
    "FAIL: raw_text got mangled even with no history to add!"
assert result6b["validation"]["valid"] is True
print(">>> PASS: absence of history doesn't break or alter existing behavior.\n")

print("=" * 60)
print("ALL TESTS PASSED")
print("=" * 60)


# ============================================================
# TEST 5 — NPCs the narrator introduces must persist into
# world_state for the NEXT turn (the baker-in-transcript bug:
# previously the narrator could describe a baker in prose, but
# nothing wrote that baker into npcs[], so talking to them next
# turn always failed premise validation).
# ============================================================

class FakeGroqWithNewNpc(FakeGroq):
    """Same as FakeGroq, but the narration turn also reports a
    freshly-introduced NPC, proving new_npcs flows end-to-end."""
    def _narrate(self, context: str) -> str:
        return json.dumps({
            "narration": "[NARRATED] A baker calls out from her stall.",
            "choices": ["Talk to the baker", "Walk on", "Buy a pastry"],
            "new_npcs": [{"name": "a baker", "hostile": False}],
        })


print("=" * 60)
print("TEST 5: narrator introduces a baker -> must land in world_state")
print("=" * 60)
fake_groq_npc = FakeGroqWithNewNpc()
world_state_empty = {
    "location": "Townia — the town square",
    "npcs": [],
    "player": {"soulbound": player_soulbound},
    "flags": {},
}
result5 = handle_rpg_action("I look around the square", world_state_empty, db=db, call_groq_fn=fake_groq_npc)
print(f"Reply to player:  {result5['reply']}")
print(f"new_npcs:         {result5['new_npcs']}")
assert result5["new_npcs"] == [{"name": "a baker", "hostile": False}], "FAIL: baker wasn't reported!"

# Simulate what RpgSession.apply_engine_result() does: merge into npcs
world_state_empty["npcs"].extend(
    npc for npc in result5["new_npcs"]
    if npc["name"] not in [n["name"] for n in world_state_empty["npcs"]]
)

print("=" * 60)
print("TEST 5b: NOW talking to the baker should validate (she's real)")
print("=" * 60)
result5b = handle_rpg_action("I talk to the baker", world_state_empty, db=db, call_groq_fn=fake_groq)
print(f"Valid premise?    {result5b['validation']['valid']}")
print(f"Reply to player:  {result5b['reply']}")
assert result5b["validation"]["valid"] is True, "FAIL: baker should be a real, addressable NPC now!"
print(">>> PASS: narrator-introduced NPC persisted and was interactable next turn.\n")

print("=" * 60)
print("ALL TESTS PASSED")
print("=" * 60)


# ============================================================
# TEST 7 — npc_events: a combat hit that connects derives a
# mechanical npc_event (no AI judgment call), and it actually
# round-trips through the DB and back into the NEXT turn's
# narration context — proving the full loop, not just one piece.
# ============================================================

print("=" * 60)
print("TEST 7: combat hit derives npc_event, persists, and resurfaces")
print("=" * 60)

npc_events_sender = "test_sender_e2e"
npc_events_zone = "test_zone_e2e"
db._ex("DELETE FROM npc_events WHERE sender = ?", (npc_events_sender,))
db._commit()

world_state_e2e = {
    "location": "Route 1 — tall grass",
    "npcs": [{
        "name": "a wild Rattata",
        "hostile": True,
        "stats": {"STR": 30, "INT": 25, "DEF": 28, "SPD": 40, "DEX": 30, "WIS": 20, "CHA": 15},
        "types": ["normal"],
    }],
    "player": {"soulbound": player_soulbound},
    "flags": {},
}

# Fireball is 85% accuracy (battle.py rolls randint(1,100)), so ~1 run in
# 8 used to MISS here, derive no npc_event, and fail this test for reasons
# unrelated to what it checks. Seed the roll so this test is deterministic
# and always exercises the hit path it exists to prove.
import random as _random
_random.seed(1234)
result7 = handle_rpg_action("I attack with Fireball", world_state_e2e, db=db, call_groq_fn=fake_groq)
print(f"Damage dealt:     {result7['resolution']['damage']}")
print(f"npc_event:        {result7['npc_event']}")
assert result7["npc_event"] is not None, "FAIL: combat hit should have derived an npc_event!"
assert result7["npc_event"]["npc_name"] == "a wild Rattata", \
    f"FAIL: wrong target name: {result7['npc_event']['npc_name']}"
assert result7["npc_event"]["pinned"] is False
print(">>> PASS: mechanical trigger fired on a real connecting hit.")

# Simulate what RpgSession.apply_engine_result() does with it
db.add_npc_event(
    npc_events_sender, npc_events_zone,
    result7["npc_event"]["npc_name"], result7["npc_event"]["text"],
    pinned=result7["npc_event"].get("pinned", False),
)

# Next turn: to_world_state_dict()-equivalent enrichment — read the
# event back and confirm it surfaces in narrate_result's context.
events_back = db.get_npc_events(npc_events_sender, npc_events_zone, "a wild Rattata")
assert events_back, "FAIL: event didn't persist/read back from DB!"
print(f"Read back:        {events_back}")

world_state_next_turn = {
    "location": "Route 1 — tall grass",
    "npcs": [{"name": "a wild Rattata", "hostile": True, "events": events_back}],
    "player": {"soulbound": player_soulbound},
    "flags": {},
}
result7b = handle_rpg_action("I look at the rattata", world_state_next_turn, db=db, call_groq_fn=fake_groq_capture)
assert "What you remember about a wild Rattata" in fake_groq_capture.narrate_user_seen, \
    "FAIL: persisted npc_event never reached the next turn's narration context!"
print(">>> PASS: npc_event round-tripped from combat hit -> DB -> next turn's narration.\n")

db._ex("DELETE FROM npc_events WHERE sender = ?", (npc_events_sender,))
db._commit()

print("=" * 60)
print("ALL TESTS PASSED")
print("=" * 60)


# ============================================================
# TEST 8 — notable_npc_event: narrator-reported promise/betrayal,
# validated against present NPCs (same defensive discipline as
# trial_start/new_npcs — never trust an LLM-reported name blindly).
# ============================================================

class FakeGroqPromise(FakeGroq):
    """Narration turn reports a promise to a present NPC."""
    def _narrate(self, context: str) -> str:
        return json.dumps({
            "narration": '[NARRATED] "I promise I\'ll come back for you," you tell the elder.',
            "choices": ["Leave the village", "Stay a while longer", "Ask more questions"],
            "new_npcs": [],
            "notable_npc_event": {
                "npc_name": "the elder",
                "text": "promised to return to the village",
            },
        })


class FakeGroqHallucinatedPromise(FakeGroq):
    """Narration turn reports a promise to an NPC that ISN'T present
    — must be rejected, not trusted blindly."""
    def _narrate(self, context: str) -> str:
        return json.dumps({
            "narration": "[NARRATED] You look around.",
            "choices": ["Look further", "Move on", "Wait"],
            "new_npcs": [],
            "notable_npc_event": {
                "npc_name": "a ghost that was never introduced",
                "text": "made a pact with the player",
            },
        })


print("=" * 60)
print("TEST 8: notable_npc_event — promise to a present NPC is kept")
print("=" * 60)
world_state_promise = {
    "location": "Townia — the town square",
    "npcs": [{"name": "the elder", "hostile": False}],
    "player": {"soulbound": player_soulbound},
    "flags": {},
}
result8 = handle_rpg_action("I promise the elder I'll come back", world_state_promise,
                             db=db, call_groq_fn=FakeGroqPromise())
print(f"notable_npc_event: {result8['notable_npc_event']}")
assert result8["notable_npc_event"] is not None, "FAIL: promise to a present NPC should be kept!"
assert result8["notable_npc_event"]["npc_name"] == "the elder"
assert result8["notable_npc_event"]["pinned"] is True, "FAIL: promises/betrayals must always be pinned!"
print(">>> PASS: valid promise to a present NPC parsed and pinned.\n")

print("=" * 60)
print("TEST 8b: notable_npc_event naming an absent NPC is rejected")
print("=" * 60)
result8b = handle_rpg_action("I look around", world_state_promise,
                              db=db, call_groq_fn=FakeGroqHallucinatedPromise())
print(f"notable_npc_event: {result8b['notable_npc_event']}")
assert result8b["notable_npc_event"] is None, \
    "FAIL: notable_npc_event for an NPC not actually present should be discarded!"
print(">>> PASS: hallucinated NPC name correctly rejected, no false memory created.\n")

print("=" * 60)
print("ALL TESTS PASSED")
print("=" * 60)

# ============================================================
# TEST 9 — scene objects: narrator drops one, it surfaces on the
# NEXT turn's context, then a removal (pickup) actually removes it.
# This tests the ENGINE side only (world_state in/out) — the
# session-level plumbing (RpgSession.apply_engine_result actually
# mutating self.scene_objects, travel_to() clearing it) is
# per-player in-memory list logic with no DB/LLM involved, so it's
# covered directly against RpgSession in TEST 10 below instead of
# re-mocked here.
# ============================================================

class FakeGroqDropsObject(FakeGroq):
    """Narration turn reports a can being thrown into the scene."""
    def _narrate(self, context: str) -> str:
        return json.dumps({
            "narration": "[NARRATED] The can clatters to the ground near Rimuru.",
            "choices": ["Look at the can", "Walk away", "Apologize to Rimuru"],
            "new_npcs": [],
            "new_scene_objects": [{"name": "the can", "description": "thrown near Rimuru"}],
        })


class FakeGroqPicksUpObject(FakeGroq):
    """Narration turn reports the can being picked up."""
    def _narrate(self, context: str) -> str:
        return json.dumps({
            "narration": "[NARRATED] You pick up the can and pocket it.",
            "choices": ["Keep walking", "Ask Rimuru about it", "Throw it again"],
            "new_npcs": [],
            "removed_scene_objects": ["the can"],
        })


print("=" * 60)
print("TEST 9: narrator drops a scene object -> surfaces, then removed on pickup")
print("=" * 60)

world_state_drop = {
    "location": "Townia — the town square",
    "npcs": [{"name": "Rimuru", "hostile": False}],
    "player": {"soulbound": player_soulbound},
    "flags": {},
    "scene_objects": [],
}
result9 = handle_rpg_action("I throw a can at Rimuru", world_state_drop,
                             db=db, call_groq_fn=FakeGroqDropsObject())
print(f"new_scene_objects: {result9['new_scene_objects']}")
assert result9["new_scene_objects"] == [{"name": "the can", "description": "thrown near Rimuru"}], \
    f"FAIL: {result9['new_scene_objects']}"
print(">>> PASS: narrator-reported object captured correctly.")

# Simulate it now being in the scene for the next turn
world_state_with_can = {
    "location": "Townia — the town square",
    "npcs": [{"name": "Rimuru", "hostile": False}],
    "player": {"soulbound": player_soulbound},
    "flags": {},
    "scene_objects": result9["new_scene_objects"],
}
fake_groq_capture_obj = FakeGroqCapture()
handle_rpg_action("I look around", world_state_with_can, db=db, call_groq_fn=fake_groq_capture_obj)
assert "the can" in fake_groq_capture_obj.narrate_user_seen, \
    "FAIL: dropped object never resurfaced in the next turn's narration context!"
print(">>> PASS: dropped object resurfaced in next turn's context.")

result9b = handle_rpg_action("I pick up the can", world_state_with_can,
                              db=db, call_groq_fn=FakeGroqPicksUpObject())
print(f"removed_scene_objects: {result9b['removed_scene_objects']}")
assert result9b["removed_scene_objects"] == ["the can"], f"FAIL: {result9b['removed_scene_objects']}"
print(">>> PASS: pickup correctly reported for removal.\n")


# ============================================================
# TEST 10 — RpgSession: apply_engine_result actually mutates
# self.scene_objects (add/remove), and travel_to() clears it. This
# is the real per-player lifecycle the engine-level test above can't
# cover, since scene_objects lives on the session, not world_state
# alone.
# ============================================================

print("=" * 60)
print("TEST 10: RpgSession scene_objects lifecycle + travel clears it")
print("=" * 60)

from rpg_session import RpgSession

sess = RpgSession("test_sender_scene_objects")
sess.register("TestHero")
assert sess.scene_objects == [], "FAIL: fresh session should start with no scene objects"

# Simulate apply_engine_result adding one
fake_result_add = {
    "extraction": {"action": "I throw a can at Rimuru"},
    "reply": "The can clatters down.",
    "new_scene_objects": [{"name": "the can", "description": "thrown near Rimuru"}],
    "removed_scene_objects": [],
}
sess.apply_engine_result(fake_result_add, db)
# Entries carry id/count/weight/etc. now (rpg_scene.py) and the name is
# stored normalized ("the can" -> "can"), so assert the behavior, not a
# byte-exact dict. Still one row, still findable by the player's words,
# still carrying the narrator's description.
assert len(sess.scene_objects) == 1, f"FAIL: {sess.scene_objects}"
assert sess.scene_objects[0]["name"] == "can", f"FAIL: {sess.scene_objects}"
assert sess.scene_objects[0]["description"] == "thrown near Rimuru", f"FAIL: {sess.scene_objects}"
import rpg_scene as _rs
assert _rs.has(sess.scene_objects, "the can"), "FAIL: 'the can' should still match"
print(">>> PASS: apply_engine_result added the scene object.")

# Simulate a no-op turn — shouldn't duplicate
fake_result_noop = {
    "extraction": {"action": "I look around"},
    "reply": "Nothing changes.",
    "new_scene_objects": [],
    "removed_scene_objects": [],
}
sess.apply_engine_result(fake_result_noop, db)
assert len(sess.scene_objects) == 1, "FAIL: no-op turn shouldn't change scene object count"
print(">>> PASS: no-op turn left scene objects untouched.")

# Now travel — this MUST clear it (the real expiry trigger)
assert sess.location_id == "townia_square", f"unexpected starting location: {sess.location_id}"
sess.travel_to("townia_church")
assert sess.location_id == "townia_church"
assert sess.scene_objects == [], "FAIL: travel_to() should clear scene_objects but didn't!"
print(">>> PASS: travel_to() cleared scene objects — the expiry trigger works.")

# Pickup/removal test on a fresh object
sess.apply_engine_result(fake_result_add, db)
fake_result_remove = {
    "extraction": {"action": "I pick up the can"},
    "reply": "You pocket the can.",
    "new_scene_objects": [],
    "removed_scene_objects": ["the can"],
}
sess.apply_engine_result(fake_result_remove, db)
assert sess.scene_objects == [], f"FAIL: pickup should have removed it: {sess.scene_objects}"
print(">>> PASS: explicit pickup removed the scene object.\n")

print("=" * 60)
print("ALL TESTS PASSED")
print("=" * 60)


# ============================================================
# TEST 11 — Flag 1 fix: open/vague targets get "first contact"
# leniency at an empty scene (the actual bug — a player's first-ever
# interaction with a brand-new NPC was structurally impossible
# before this fix). Specific/named targets at an empty scene must
# STILL be rejected (TEST 2's exact concern — no false premises).
# Combat must still be rejected on empty regardless of target type.
# ============================================================

print("=" * 60)
print("TEST 11: Flag 1 — open target at empty scene now allowed")
print("=" * 60)

world_state_truly_empty = {
    "location": "an unnamed clearing",
    "npcs": [],
    "scene_objects": [],
    "player": {"soulbound": player_soulbound},
    "flags": {},
}

result11a = handle_rpg_action("I talk to someone", world_state_truly_empty,
                               db=db, call_groq_fn=fake_groq)
print(f"'I talk to someone' at empty scene -> valid: {result11a['validation']['valid']}")
assert result11a["validation"]["valid"] is True, \
    "FAIL: open-ended social gesture at an empty scene should be allowed (Flag 1 fix)!"
print(">>> PASS: open-ended first contact no longer structurally blocked.\n")

print("=" * 60)
print("TEST 11b: specific/named target at empty scene STILL rejected")
print("=" * 60)
result11b = handle_rpg_action("I talk to the elder", world_state_truly_empty,
                               db=db, call_groq_fn=fake_groq)
print(f"'I talk to the elder' at empty scene -> valid: {result11b['validation']['valid']}")
assert result11b["validation"]["valid"] is False, \
    "FAIL: a SPECIFIC named target at an empty scene must still be rejected (false premise)!"
print(">>> PASS: named target at an empty scene correctly still rejected — no false premise smuggled in.\n")

print("=" * 60)
print("TEST 11c: combat still rejected on empty scene, even with no named target")
print("=" * 60)
result11c = handle_rpg_action("I attack", world_state_truly_empty,
                               db=db, call_groq_fn=fake_groq)
print(f"'I attack' at empty scene -> valid: {result11c['validation']['valid']}")
assert result11c["validation"]["valid"] is False, \
    "FAIL: combat with nothing present should always be rejected, open target or not!"
print(">>> PASS: combat still correctly rejected on an empty scene.\n")

print("=" * 60)
print("ALL TESTS PASSED")
print("=" * 60)


# ============================================================
# TEST 12 — Flag 2 fix: a REJECTED action must never be added to
# session.history. Feeding a rejection message back into
# extract_action/narrate_result as if it were real narration
# corrupted the very next turn's continuity — this is what caused
# the null/garbage replies from the playthrough. Deterministic (no
# combat/random damage rolls involved), so no flakiness here.
# ============================================================

print("=" * 60)
print("TEST 12: rejected actions never enter session.history")
print("=" * 60)

from rpg_session import RpgSession

sess12 = RpgSession("test_sender_flag2")
sess12.register("Flag2Tester")
assert sess12.history == [], "FAIL: fresh session should start with empty history"

# A rejected action: named target ("the elder") at a genuinely empty
# scene — TEST 11b already proved this stays rejected at the
# validate_premise level; here we prove apply_engine_result does NOT
# record it into history.
fake_rejected_result = {
    "extraction": {"action": "I talk to the elder", "type": "interaction", "target": "the elder"},
    "validation": {"valid": False, "reason": "There's no one here."},
    "reply": "There's no one here.",
    "new_npcs": [],
    "new_scene_objects": [],
    "removed_scene_objects": [],
}
sess12.apply_engine_result(fake_rejected_result, db)
assert sess12.history == [], \
    f"FAIL: a REJECTED action should never be added to history! Got: {sess12.history}"
print(">>> PASS: rejected action correctly excluded from history.")

# A valid action right after — history should now have exactly ONE
# entry (the valid one), not two, proving the rejected one really
# was skipped rather than just delayed.
fake_valid_result = {
    "extraction": {"action": "I look around", "type": "narrative", "target": None},
    "validation": {"valid": True, "reason": None},
    "reply": "You see an empty square.",
    "new_npcs": [],
    "new_scene_objects": [],
    "removed_scene_objects": [],
}
sess12.apply_engine_result(fake_valid_result, db)
assert len(sess12.history) == 1, f"FAIL: expected exactly 1 history entry, got {len(sess12.history)}"
assert sess12.history[0]["action"] == "I look around"
print(">>> PASS: valid action recorded normally; rejected one still absent from history.\n")

print("=" * 60)
print("ALL TESTS PASSED")
print("=" * 60)
