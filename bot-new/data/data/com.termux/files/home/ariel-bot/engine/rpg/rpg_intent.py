# ============================================================
# ARIEL — RPG_INTENT.PY  (Layer 4 of the movement/location rewrite)
#
# Extends rpg_engine.py's extract_action/_EXTRACTION_SYSTEM with a
# "move" type, per rpg-movement-rebuild.md 4.1: "The intent step is
# an extension of the existing extract_action call, adding a move
# type and a destination in the player's own words, so it adds no
# LLM hop."
#
# CUTOVER COMPLETE: rpg_engine.handle_rpg_action now calls
# extract_intent (this file) instead of extract_action for every
# turn — see that function's docstring. The old extract_action/
# _EXTRACTION_SYSTEM in rpg_engine.py are UNCHANGED/still present
# (other code may still reference them), but handle_rpg_action itself
# no longer calls them — this file's extract_intent is what actually
# runs live now.
#
# This module calls the LLM exactly ONCE per player action, same as
# the original extract_action — classification, destination-in-
# player's-own-words, AND (when relevant) plausibility/dedup judgment
# for a speculative passage all come out of that single call. Per
# decision #3, plausibility is LLM-only — this module does not
# second-guess the model's plausible=true/false with any code-side
# fact-check.
# ============================================================

from rpg_llm import extract_json


_INTENT_SYSTEM = """You are a strict parser for a tabletop-style roleplay game.

The player will send a message describing what their character does.
Players sometimes ALSO write outcomes, NPC dialogue, or world events as
if they already happened — these are proposals, not facts, and must be
discarded.

Extract ONLY the character's own stated action or intent. Ignore and
drop anything the player wrote about what another character, NPC, or
the world does/says/becomes as a RESULT of that action.

You must also classify the action's TYPE, since different types are
resolved differently downstream:
- "combat"       — attacking, casting a damaging/offensive ability,
                    any action meant to harm or incapacitate a target
- "social"       — persuading, deceiving, intimidating, negotiating —
                    trying to change what an NPC thinks/does through
                    dialogue or force of personality
- "physical"     — a non-combat physical feat with real chance of
                    failure: sneaking, climbing, picking a lock,
                    balancing, forcing a door
- "interaction"  — talking, trading, giving/taking an item, asking a
                    question — engaging with someone/something present
                    but with no real success/failure roll needed
- "move"         — a clear, deliberate intent to go somewhere else —
                    a named place, a direction, or an implied nearby
                    destination ("let's head to the coliseum", "I go
                    back to the square", "I walk toward the noise").
                    Do NOT use for vague/incidental movement with no
                    real destination (pacing, stepping back in
                    combat, closing distance to attack — that's
                    "narrative" or "combat" depending on context).
- "narrative"     — pure flavor/observation with no mechanical
                    stakes at all: looking around, thinking,
                    describing one's own feelings, incidental motion
                    with no real destination.

Also flag TARGET: the name of the specific NPC/object/direction the
action is aimed at, if any, exactly as the player referred to it (or
null if there isn't one — e.g. "I look around" has no target).

If TYPE is "move", also flag DESTINATION: the place the player wants
to go, exactly in their own words (e.g. "the coliseum", "back to the
square", "north") — never resolved or corrected by you, just
extracted as said. Use null for every other type.

If TYPE is "move" AND the destination is NOT an obvious, already-
established place (i.e. the player is trying something speculative —
"is there a door behind the shelf", "I check if the wall has a gap",
"I look for another way out") rather than naming a known place or an
ordinary direction, also judge PLAUSIBLE: whether a passage like that
existing here is reasonable given the kind of place this is (a locked
door inside a lived-in house is plausible; a portal appearing in a
plain stone corridor is not). Use null for PLAUSIBLE when the
destination is just a normal named place or direction — plausibility
judgment is ONLY for speculative/uncertain passages, not ordinary
travel.

You may be given RECENT CONTEXT: the last 1-2 turns of what the
player did and what happened as a result. Use it ONLY to resolve
short/ambiguous messages (a fragment, a pronoun, a one-word reply
like "war?" or "him") by figuring out what they're actually
referring to. Never let it override or reinterpret a CURRENT message
that is already clear on its own.

Respond ONLY with JSON, no other text:
{"action": "<trimmed to just the character's own action>",
 "type": "combat" | "social" | "physical" | "interaction" | "move" | "narrative",
 "target": "<string or null>",
 "destination": "<string or null, only for type=move>",
 "plausible": true | false | null}

Examples:
Input: "I talk to the man beside me and he tells me about the forbidden texts of Aloth"
Output: {"action": "I talk to the man beside me", "type": "interaction", "target": "the man beside me", "destination": null, "plausible": null}

Input: "I swing my sword at the goblin and kill it instantly"
Output: {"action": "I swing my sword at the goblin", "type": "combat", "target": "the goblin", "destination": null, "plausible": null}

Input: "I try to convince the merchant to lower his price"
Output: {"action": "I try to convince the merchant to lower his price", "type": "social", "target": "the merchant", "destination": null, "plausible": null}

Input: "I attempt to sneak past the sleeping dragon"
Output: {"action": "I attempt to sneak past the sleeping dragon", "type": "physical", "target": "the sleeping dragon", "destination": null, "plausible": null}

Input: "I look around the tavern"
Output: {"action": "I look around the tavern", "type": "narrative", "target": null, "destination": null, "plausible": null}

Input: "let's head to the coliseum"
Output: {"action": "let's head to the coliseum", "type": "move", "target": null, "destination": "the coliseum", "plausible": null}

Input: "I'd like to go to the west district"
Output: {"action": "I'd like to go to the west district", "type": "move", "target": null, "destination": "the west district", "plausible": null}

Input: "I check if there's a hidden door behind the bookshelf"
Output: {"action": "I check if there's a hidden door behind the bookshelf", "type": "move", "target": null, "destination": "a hidden door behind the bookshelf", "plausible": true}

Input: "I look for a portal in the empty stone corridor"
Output: {"action": "I look for a portal in the empty stone corridor", "type": "move", "target": null, "destination": "a portal", "plausible": false}
"""


def extract_intent(raw_text: str, call_groq_fn, recent_history=None, max_tokens: int = 220) -> dict:
    """
    Superset of rpg_engine.extract_action — same fallback shape, same
    call signature style, plus "move" as a recognized type and the
    destination/plausible fields movement needs. See module docstring
    for why this is a separate module rather than an edit to
    extract_action directly (decision #4 — no piecemeal cutover).

    Returns {"action": str, "type": str, "target": str | None,
              "destination": str | None, "plausible": bool | None,
              "raw": str, "had_proposed_outcome": bool}
    """
    def _fallback(had_outcome=None):
        return {
            "action": raw_text.strip(), "type": "narrative", "target": None,
            "destination": None, "plausible": None,
            "raw": raw_text, "had_proposed_outcome": had_outcome,
        }

    if call_groq_fn is None:
        return _fallback()

    if recent_history:
        lines = []
        for turn in recent_history[-2:]:
            lines.append(f"Player did: {turn.get('action', '')}")
            lines.append(f"What happened: {turn.get('reply', '')}")
        lines.append(f"Current message: {raw_text}")
        user_message = "RECENT CONTEXT:\n" + "\n".join(lines)
    else:
        user_message = raw_text

    reply = call_groq_fn(_INTENT_SYSTEM, user_message, max_tokens=max_tokens, json_mode=True)
    if not reply:
        return _fallback()

    try:
        parsed = extract_json(reply)
        if parsed is None:
            raise ValueError("no JSON object found")
        action = parsed.get("action", "").strip()
        action_type = parsed.get("type", "narrative").strip().lower()
        target = parsed.get("target")
        if target is not None:
            target = str(target).strip() or None
        destination = parsed.get("destination")
        if destination is not None:
            destination = str(destination).strip() or None
        plausible = parsed.get("plausible")
        if plausible is not None:
            plausible = bool(plausible)
    except (AttributeError, ValueError):
        return _fallback()

    if action_type not in ("combat", "social", "physical", "interaction", "move", "narrative"):
        action_type = "narrative"

    # A "move" classification with no destination at all is
    # meaningless — treat it the same as a malformed reply rather
    # than letting Layer 5 try to resolve a null place.
    if action_type == "move" and not destination:
        action_type = "narrative"

    # plausible should only ever be set for type=move — if the model
    # sets it on any other type (malformed reply), drop it rather
    # than let a stray plausibility judgment leak into an unrelated
    # action.
    if action_type != "move":
        plausible = None

    had_outcome = action.strip().lower() != raw_text.strip().lower()
    return {
        "action": action, "type": action_type, "target": target,
        "destination": destination, "plausible": plausible,
        "raw": raw_text, "had_proposed_outcome": had_outcome,
    }
