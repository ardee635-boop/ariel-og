"""RPG: rpg resolve (split from rpg_engine.py)."""
import rpg_scene


# ── World state shape (Phase 0 — in-memory / dict based) ───────
#
# world_state = {
#     "location": "Cinder Hollow — cave entrance",
#     "npcs":     [{"name": "a grizzled miner", "hostile": False}],
#     "player":   <soulbound-schema dict, from soulbound.py>,
#     "flags":    {},   # arbitrary world facts, e.g. "torch_lit": True
# }
#
# This mirrors player_meta / ExploreSession's get/set pattern from
# the main game, just scoped to Ariel's own session key instead of
# reusing explore's.


# ============================================================
# STAGE 1 — ACTION EXTRACTION
# ============================================================
#
# extract_action/_EXTRACTION_SYSTEM REMOVED (movement-rebuild
# cutover, confirmed safe to delete — the "war?" short-fragment
# continuity behavior they protected is carried forward intact into
# rpg_intent.extract_intent, which handle_rpg_action calls instead;
# re-verified live before removal, not just carried over on faith).
# rpg_intent.py's extract_intent is what actually runs now — see
# handle_rpg_action's docstring below for the full cutover note.
#
# NOTE: rpg_engine_test.py still references extract_action directly
# (its own "war?" continuity test, written before this cutover) and
# will fail at that point if run as-is — this was a deliberate,
# discussed tradeoff, not an oversight. The behavior itself is
# intact; only that one old test's ability to demonstrate it is not.
# ============================================================


# ============================================================
# STAGE 2 — PREMISE VALIDATION
# ============================================================

def validate_premise(extraction: dict, world_state: dict) -> dict:
    """
    Checks whether the stated action's premise is actually true in
    the current world_state, WITHOUT using an LLM — this is a
    grounded, code-level check against real data, not a judgment
    call, so it can't be talked around.

    Uses extraction["type"]/["target"] from Stage 1's classification
    instead of re-guessing from keywords — combat/social/physical/
    interaction all imply "someone/something must be present";
    narrative never does.

    Returns {"valid": bool, "reason": str | None}
    """
    action = extraction["action"]
    action_type = extraction.get("type", "narrative")
    target = extraction.get("target")

    # combat/social/physical/interaction all require someone/something
    # to be present to act on; narrative never does (e.g. "look
    # around", "walk forward" have no target to validate).
    requires_target = action_type in ("combat", "social", "physical", "interaction")

    if not requires_target:
        return {"valid": True, "reason": None}

    npcs = world_state.get("npcs", [])
    scene_objects = world_state.get("scene_objects", [])

    _STOPWORDS = {"the", "a", "an", "beside", "me", "my", "near", "by", "here"}

    # Generic referential phrases never share literal words with an
    # NPC's actual name/title ("the nearest person" vs "an elder of
    # the church" — zero overlap despite obviously meaning the same
    # NPC) — these always resolve to whoever's present. They're also
    # the ONLY case allowed through when the scene is otherwise empty
    # (see below) — an open "I look for someone to talk to" doesn't
    # assert any specific person exists, so there's no false premise
    # to reject, unlike a definite reference (see next comment block).
    _REFERENTIAL_PHRASES = {
        "nearest person", "the nearest person", "anyone", "someone",
        "whoever is here", "whoever's here", "the person here",
        "the person", "him", "her", "them", "that person",
        "it", "that", "this",
    }

    def _content_words(s):
        return {w for w in s.lower().split() if w not in _STOPWORDS}

    is_open_target = (not target) or (target.strip().lower() in _REFERENTIAL_PHRASES)

    if not npcs and not scene_objects:
        # Combat is checked FIRST, even with an open/no target — you
        # can't validly attack "whoever's around" any more than you
        # can attack a named person who isn't there. This must come
        # before the open-target leniency below, or "I attack" (open
        # target, nothing present) would wrongly pass.
        if action_type == "combat":
            return {
                "valid": False,
                "reason": (
                    "The action implies attacking someone, but "
                    f"there is no one present at {world_state.get('location', 'this location')}."
                ),
            }
        # (creatures live in scene_objects, so this branch — npcs AND
        # scene_objects both empty — already correctly has nothing to
        # fight; the actual creature-as-target case is handled below,
        # in the "SOME npcs/objects present" gate.)

        # Nothing here at all. An OPEN target ("I talk to whoever's
        # around", or no target named) doesn't assert any specific
        # person/thing exists — that's a legitimate premise, and the
        # narrator can introduce someone or say the place is empty,
        # same as narrative actions already work. This is the actual
        # Flag 1 fix: a player's first-ever social gesture at a fresh
        # location is no longer structurally impossible.
        #
        # A SPECIFIC/named target ("I talk to the elder", "the man
        # beside me") DOES assert something specific exists — that's
        # the exact false-premise case this function exists to catch
        # (see module's original design: reject fabricated "he tells
        # me about X" premises). Allowing this through at an empty
        # scene would let a player smuggle in "the elder" (or worse,
        # a name with a false backstory attached) as if already
        # established, so it stays rejected here, unchanged from
        # before this fix.
        if is_open_target:
            return {"valid": True, "reason": None}
        return {
            "valid": False,
            "reason": (
                "The action implies interacting with someone/something specific, but "
                f"there is no one/nothing present at {world_state.get('location', 'this location')}."
            ),
        }

    # Combat with SOME npcs/objects present but zero NPCs specifically:
    # valid ONLY if a scene creature can stand in as the target (a
    # squirrel, a wolf — see rpg_scene.py). A scenery/item/corpse
    # can't be attacked as a combatant; "I attack the fountain" still
    # has nothing to fight back.
    creatures = [o for o in scene_objects if o.get("kind") == "creature"]
    if action_type == "combat" and not npcs:
        target_creature = None
        if creatures:
            if is_open_target:
                target_creature = creatures[0]
            elif target:
                hits = [o for o in creatures if o in rpg_scene.find(creatures, target)]
                target_creature = hits[0] if hits else None
        if target_creature is None:
            return {
                "valid": False,
                "reason": (
                    "The action implies attacking someone, but "
                    f"there is no one present at {world_state.get('location', 'this location')}."
                ),
            }
        return {"valid": True, "reason": None, "creature_target": target_creature}

    # Something IS present (npcs and/or scene_objects non-empty). If
    # a specific target was named, check it actually matches. Word-
    # overlap match, not plain substring: "the man" and "a weathered
    # old man" share no literal substring in either direction, but do
    # share the meaningful word "man" — so we compare stopword-
    # stripped word sets instead. Still not real NLU/coreference
    # (won't catch "him"/"the stranger" without a shared word, though
    # those are covered by _REFERENTIAL_PHRASES above), but catches
    # far more real phrasing than a raw substring check did.
    if target and not is_open_target:
        target_words = _content_words(target)
        if not target_words:
            return {"valid": True, "reason": None}  # nothing meaningful to compare — don't block on it

        found_npc = any(target_words & _content_words(npc["name"]) for npc in npcs)
        # Objects go through the scene store so "the cups" finds "cup"
        # and a stacked "2 cups" reads correctly in the miss message.
        found_object = rpg_scene.has(scene_objects, target)

        if not found_npc and not found_object:
            present_names = [npc["name"] for npc in npcs]
            if scene_objects:
                present_names.append(rpg_scene.names_for_context(scene_objects))
            names_str = ", ".join(present_names)
            return {
                "valid": False,
                "reason": (
                    f"There's no '{target}' here — present at "
                    f"{world_state.get('location', 'this location')}: {names_str}."
                ),
            }

    return {"valid": True, "reason": None}

# ============================================================
# STAGE 3 — MECHANICAL RESOLUTION
# ============================================================

def resolve_action(extraction: dict, world_state: dict, db=None,
                   validation: dict | None = None) -> dict:
    """
    Determines whether this action has a mechanical (combat) effect,
    and if so, resolves it via calc_damage() -- the SAME function
    battle.py already uses for structured PvE battles. Non-combat
    actions pass through untouched.

    Uses extraction["type"] from Stage 1's classification rather than
    re-scanning the action text for verbs.

    Returns {
        "mechanical": bool,
        "damage": int | None,     # -1 = miss, per calc_damage's contract
        "type_mult": float | None,
        "skill_name": str | None,
    }
    """
    action = extraction["action"]
    action_type = extraction.get("type", "narrative")
    target_name = extraction.get("target")

    if action_type != "combat":
        # Phase 0: social/physical checks (persuasion, stealth, etc.)
        # have no resolver yet — see known-gaps note. They currently
        # pass through as non-mechanical, same as narrative, rather
        # than silently pretending to resolve them.
        return {"mechanical": False, "damage": None, "type_mult": None,
                "skill_name": None, "target_name": None}

    player = world_state.get("player")
    npcs = world_state.get("npcs", [])

    # A scene creature (squirrel, wolf — see rpg_scene.py) can stand
    # in as the target when no NPC is present. validate_premise
    # already picked WHICH creature in its "creature_target" field —
    # trust that, rather than re-resolving it here and risking a
    # different pick than what was validated.
    creature_target = (validation or {}).get("creature_target")
    if creature_target is not None and not npcs:
        target = {
            # Generic, low-stakes stat block — this is flavor combat
            # against an unnamed animal/scenery creature, not a real
            # encounter (those come from rpg_battle's proper monster
            # pool). Numbers are deliberately modest so a level-1
            # player doesn't need a "real" fight to shoo off a squirrel.
            "name": creature_target["name"],
            "stats": {"STR": 15, "INT": 10, "DEF": 12, "SPD": 20,
                      "DEX": 15, "WIS": 8, "CHA": 5},
            "types": ["normal"],
            "hostile": False,
        }
    elif not player or not npcs:
        # Combat type but no valid attacker/target pair — this
        # should have already been caught by validate_premise, but
        # double-checking here rather than trusting upstream.
        return {"mechanical": True, "damage": -1, "type_mult": None,
                "skill_name": None, "target_name": None}
    else:
        target = None  # resolved just below, the existing NPC path

    # Resolve WHICH npc is the target: prefer an explicit name match
    # from extraction["target"] over Phase 0's old "just pick the
    # first npc" default. Same word-overlap matching as
    # validate_premise, for the same reason (plain substring misses
    # "the man" vs "a weathered old man"). Skipped entirely when a
    # creature target was already picked above.
    if target is None:
        target = npcs[0]
    if target_name and creature_target is None:
        _STOPWORDS = {"the", "a", "an", "beside", "me", "my", "near", "by", "here"}
        target_words = {w for w in target_name.lower().split() if w not in _STOPWORDS}
        for npc in npcs:
            npc_words = {w for w in npc["name"].lower().split() if w not in _STOPWORDS}
            if target_words & npc_words:
                target = npc
                break

    # Skill matching: exact/substring name match against the action
    # text, scored by match length so the MOST SPECIFIC matching
    # skill wins if several names overlap (e.g. "Fire Bolt" and
    # "Fire Bolt Rain" both matching "fire bolt" in the text —
    # prefer the longer, more specific match). Still not real NLU
    # (a synonym like "burn them" won't match a skill named
    # "Fireball"), but no longer just "first skill wins by
    # accident of list order".
    action_lower = action.lower()
    soulbound = player.get("soulbound", player)  # tolerate either shape
    skills = soulbound.get("skills", [])
    matched_skill = None
    best_len = 0
    for skill in skills:
        name_lower = skill["name"].strip().lower()
        if name_lower in action_lower and len(name_lower) > best_len:
            matched_skill = skill
            best_len = len(name_lower)

    if not matched_skill and skills:
        # No named skill found in the text at all (e.g. "I attack
        # with fire magic" when the skill is literally called
        # "Fireball") — fall back to the player's first skill rather
        # than failing the action outright. Flagged: a real fix
        # needs semantic skill matching, not just substring search.
        matched_skill = skills[0]

    if not matched_skill:
        return {"mechanical": True, "damage": -1, "type_mult": None,
                "skill_name": None, "target_name": target["name"]}

    move_data = {
        "name": matched_skill["name"],
        "power": matched_skill.get("damage", 0),
        "accuracy": matched_skill.get("accuracy", 100),
        "type": matched_skill.get("element", "normal").lower(),
        "category": "special" if matched_skill.get("scaling") == "INT" else "physical",
    }

    from rpg_damage import calc_damage
    damage, type_mult = calc_damage(soulbound, move_data, target, db)

    # Townia's ward: nothing dies within a settlement. Only matters for
    # the flavor-creature path — real NPC/monster encounters have their
    # own HP/death handling elsewhere and are untouched by this.
    # Clamp rather than zero the hit, so combat still has weight (the
    # squirrel yelps and bolts) without ever being a kill.
    if creature_target is not None and world_state.get("warded") and damage and damage > 0:
        damage = max(1, min(damage, 8))

    return {
        "mechanical": True,
        "damage": damage,
        "type_mult": type_mult,
        "skill_name": matched_skill["name"],
        # Resolved NPC name, not raw extraction["target"] text (which
        # can be null even when a real target was auto-picked, e.g.
        # "I attack with Fireball" against a single hostile NPC) —
        # this is what narrate_result's npc_event trigger keys off.
        "target_name": target["name"],
        "creature_target": creature_target is not None,
    }
