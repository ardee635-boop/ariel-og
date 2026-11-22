# ============================================================
# ARIEL — RPG.PY (core resolution engine, Phase 0)
# ============================================================
#
# Pipeline for every `.rpg <free text>` message:
#   1. extract_intent()      -> split player's stated ACTION from
#                                any OUTCOME they wrote for the
#                                world/NPCs (discarded, never fed
#                                forward as fact); also classifies a
#                                "move" type for movement (see
#                                rpg_intent.py, the movement-rebuild
#                                cutover — replaces the old
#                                extract_action, removed)
#   2. validate_premise()    -> check the action's premise against
#                                world_state (is there really a man
#                                beside them? are they really in a
#                                cave alone?)
#   3. resolve_action()      -> if the action has a mechanical
#                                effect (combat), call the SAME
#                                calc_damage() battle.py already
#                                uses. Non-mechanical actions skip
#                                straight to narration.
#   4. narrate_result()      -> LLM call, but constrained: it is
#                                handed the validated premise +
#                                mechanical result as hard fact and
#                                told never to override either.
#
# This file borrows the Groq-call convention from npc.py
# (_call_groq / GROQ_MODEL) rather than inventing a new one.
#
# NOTHING here is wired into router/ yet — this is the standalone
# engine, meant to be proven with rpg_engine_test.py before any
# WhatsApp command touches it.
# ============================================================
# NOTE: split into rpg_llm.py (Groq calls), rpg_resolve.py (premise + action resolution), rpg_narrate.py (narration); this file keeps handle_rpg_action().

"""RPG: rpg engine (split from rpg_engine.py)."""
from rpg_llm import call_groq
from rpg_narrate import narrate_result
from rpg_resolve import resolve_action, validate_premise


# ============================================================
# FULL PIPELINE — convenience wrapper
# ============================================================

def handle_rpg_action(raw_text: str, world_state: dict, db=None, call_groq_fn=call_groq) -> dict:
    """
    Runs the full four-stage pipeline. Returns a dict with every
    intermediate result (useful for testing/debugging), plus the
    final "reply" text a player would actually see.

    "trial_start"/"trial_weapon" (None unless the narrator recognized
    genuine trial-acceptance intent at a location that offers one —
    see rpg_session.to_world_state_dict()'s "offers_trial" and
    narrate_result()'s validation of it) are the router's (rpg.py)
    signal to switch session.flags["trial"] into the right phase.
    Nothing in THIS file writes session state — router remains the
    only place that mutates RpgSession, same separation as before.

    MOVEMENT CUTOVER (movement-rebuild doc decisions #1/#4/#5, this
    session): Stage 1 now uses rpg_intent.extract_intent instead of
    extract_action — a superset that adds a "move" type. When a turn
    classifies as "move", this function does NOT run
    validate_premise/resolve_action/narrate_result at all — movement
    is handled entirely by rpg_movement.handle_move_intent (Layer 5),
    which does its own narration via a recursive call back into this
    same function (for the "look around" arrival description) rather
    than through narrate_result's old TRAVEL block. narrate_result's
    TRAVEL prompt block, the "travel_target" JSON field, and its
    reachable_locations validation (formerly lines ~866-876, ~921,
    ~1344-1358 in this file) are REMOVED — this replaces them, not
    supplements them, per decision #4 (no piecemeal cutover, no two
    systems deciding movement at once).

    This does mean a "move" turn no longer gets validate_premise's
    NPC/scene-object grounding check, resolve_action's combat check,
    or narrate_result's other same-turn fields (new_npcs,
    notable_npc_event, combat_start, etc.) — those never applied to
    genuine travel anyway (an action can't be BOTH a move and a
    combat_start in the same turn under the old system either,
    they're mutually exclusive types), so nothing is lost that a
    move turn actually used.
    """
    from rpg_intent import extract_intent
    extraction = extract_intent(raw_text, call_groq_fn,
                                 recent_history=world_state.get("history"))

    if extraction["type"] == "move":
        # db is required for movement (Layer 3/5 need real Place/
        # Passage rows) — if it's missing, degrade to the safest
        # available behavior (treat as narrative) rather than crash,
        # matching extract_action's own "no call_groq_fn" fallback
        # philosophy elsewhere in this file.
        if db is None:
            return {
                "extraction": extraction, "validation": {"valid": True, "reason": None},
                "resolution": {"mechanical": False, "damage": None, "type_mult": None, "skill_name": None},
                "reply": "You're not sure how to get there right now.",
                "trial_start": None, "trial_weapon": None, "choices": [],
                "new_npcs": [], "npc_event": None, "notable_npc_event": None,
                "new_scene_objects": [], "removed_scene_objects": [],
                "item_taken": None, "item_taken_from_hand": None, "item_held": None,
            }

        import rpg_movement
        session = world_state.get("_session")
        if session is None:
            # world_state must carry the live session object for
            # movement to actually apply state changes — see
            # rpg_session.to_world_state_dict()'s "_session" key,
            # added as part of this cutover specifically so
            # handle_move_intent has something to mutate.
            return {
                "extraction": extraction, "validation": {"valid": True, "reason": None},
                "resolution": {"mechanical": False, "damage": None, "type_mult": None, "skill_name": None},
                "reply": "You're not sure how to get there right now.",
                "trial_start": None, "trial_weapon": None, "choices": [],
                "new_npcs": [], "npc_event": None, "notable_npc_event": None,
                "new_scene_objects": [], "removed_scene_objects": [],
                "item_taken": None, "item_taken_from_hand": None, "item_held": None,
            }

        _origin_location = session.location  # BEFORE the move mutates it
        move_result = rpg_movement.handle_move_intent(
            session, db, extraction, handle_rpg_action, call_groq_fn=call_groq_fn)
        # TRAVEL LOG — a fixed, code-written header on every move reply
        # so the player can always tell "the deterministic movement
        # engine decided this" from "the LLM narrator wrote this text".
        # Two purposes: (1) transparency — this line is NEVER written
        # or touched by an LLM, so its content is a hard guarantee, not
        # a claim the model could get wrong or invent; (2) it's also
        # the actual bug report — Flag 2/4 were the model inventing
        # things or losing the scene on arrival, and a wrong TRAVEL LOG
        # would be the tell that this fix itself has regressed.
        if move_result.moved and move_result.legs_left is not None:
            # One leg of a multi-leg journey: code-written head/footer
            # (see rpg_movement.format_journey_reply), not the TRAVEL LOG.
            reply = rpg_movement.format_journey_reply(move_result)
        elif move_result.moved:
            log_line = (
                f"*TRAVEL LOG* moved: {_origin_location} -> {move_result.place_name}"
                f"{' (newly created)' if move_result.newly_created else ''}"
            )
            if move_result.arrival_reply:
                reply = f"{log_line}\n\n{move_result.arrival_reply}"
            else:
                # Only reachable if narration itself failed/returned
                # nothing usable — still moved, still tell the truth.
                reply = f"{log_line}\n\n> You arrive at {move_result.place_name}."
        else:
            log_line = f"*TRAVEL LOG* not moved: {move_result.reason or 'unknown reason'}"
            reply = f"{log_line}"

        return {
            "extraction": extraction, "validation": {"valid": True, "reason": None},
            "resolution": {"mechanical": False, "damage": None, "type_mult": None, "skill_name": None},
            "reply": reply,
            "trial_start": None, "trial_weapon": None,
            "choices": session.flags.get("_choices", []),
            "new_npcs": [], "npc_event": None, "notable_npc_event": None,
            "new_scene_objects": [], "removed_scene_objects": [],
            "item_taken": None, "item_taken_from_hand": None, "item_held": None,
        }

    validation = validate_premise(extraction, world_state)

    if not validation["valid"]:
        resolution = {"mechanical": False, "damage": None, "type_mult": None, "skill_name": None}
    else:
        resolution = resolve_action(extraction, world_state, db, validation)

    narration = narrate_result(extraction["action"], validation, resolution, world_state, call_groq_fn)

    return {
        "extraction": extraction,
        "validation": validation,
        "resolution": resolution,
        "reply": narration["reply"],
        "trial_start": narration.get("trial_start"),
        "trial_weapon": narration.get("trial_weapon"),
        "choices": narration["choices"],
        "new_npcs": narration["new_npcs"],
        "npc_event": narration.get("npc_event"),
        "notable_npc_event": narration.get("notable_npc_event"),
        "new_scene_objects": narration.get("new_scene_objects", []),
        "removed_scene_objects": narration.get("removed_scene_objects", []),
        "item_taken": narration.get("item_taken"),
        "item_taken_from_hand": narration.get("item_taken_from_hand"),
        "item_held": narration.get("item_held"),
    }
