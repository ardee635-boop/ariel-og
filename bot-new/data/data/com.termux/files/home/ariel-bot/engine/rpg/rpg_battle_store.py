"""RPG: rpg battle store (split from rpg_battle.py)."""
import json
from rpg_weapon_data import BATTLE_META_KEY


# ── DB load/save (mirrors rpg_session.py's pattern exactly) ────

def load_battle(db, sender) -> dict | None:
    raw = db.get_meta(sender, BATTLE_META_KEY)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None

def save_battle(db, sender, state: dict):
    db.set_meta(sender, BATTLE_META_KEY, json.dumps(state))

def delete_battle(db, sender):
    db.delete_meta(sender, BATTLE_META_KEY)

# ── Interrupted-fight consequence extraction — for "special_event"
# interrupts (see _NARRATE_SYSTEM's SPECIAL EVENT block and
# router/rpg.py's special_event handling) whose resolution is
# "resume". Per design: an interrupt like this doesn't mean "reload
# this exact duel and keep swinging at the same opponent" — the
# story is moving on to something else entirely (a god's arrival,
# the Culling Games beginning). What DOES carry forward is the
# LASTING CONSEQUENCES already established: the player's current
# wounds/HP, how much damage the opponent had already taken, any
# ongoing conditions. This function reads the interrupted battle
# state ONE TIME and returns that as a short plain-text summary for
# the overworld narrator's context on the NEXT scene — it does NOT
# preserve the battle state itself for a literal turn-by-turn
# continuation. There is no load_frozen_battle/resume-the-duel path
# — once summarized, the interrupted fight is done; only its
# consequences persist, carried as ordinary narrative fact from here
# on (same as any other world_state detail), not as live combat state.

def extract_interrupted_battle_summary(state: dict) -> str:
    """
    One-shot: call this when a special_event fires with resolution
    "resume", BEFORE the battle state is discarded (see router/
    rpg.py — the live battle slot is deleted either way; this is
    what's kept in its place). Returns a short plain-text sentence
    describing what was still true when the interrupt happened, e.g.
    "Interrupted mid-fight against Alastor: you'd landed a solid hit
    (Alastor: 32/50 HP), and their blade grazed your cheek before
    the fight was cut short." Meant to be appended to the player's
    persistent notable-events/world-state context (the same
    mechanism notable_npc_event already uses — see rpg_engine.py) so
    the NEXT scene narrates with these consequences already in
    place, without replaying the fight itself.
    """
    player_hp = state.get("player_hp", state.get("player_max_hp", 0))
    player_max = state.get("player_max_hp", player_hp)
    monster = state.get("monster", {})
    monster_name = monster.get("name", "the opponent")
    monster_hp = state.get("monster_hp", state.get("monster_max_hp", 0))
    monster_max = state.get("monster_max_hp", monster_hp)

    parts = [f"Interrupted mid-fight against {monster_name}:"]
    parts.append(f"you were at {player_hp:.0f}/{player_max:.0f} HP")
    parts.append(f"and {monster_name} was at {monster_hp:.0f}/{monster_max:.0f} HP")

    conditions = state.get("conditions", [])
    if conditions:
        cond_texts = "; ".join(c["text"] for c in conditions if isinstance(c, dict) and c.get("text"))
        if cond_texts:
            parts.append(f"— ongoing at the time: {cond_texts}")

    return " ".join(parts) + "."
