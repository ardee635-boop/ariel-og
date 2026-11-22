"""Ariel: skills rpg (split from skills.py)."""
from skills_core import _empty_skill


# Open5e / D&D damage type -> canonical element. Bludgeoning/
# Piercing/Slashing deliberately all collapse to Normal — no
# finer physical-damage distinction, per design discussion.
_DND_DAMAGE_TYPE_TO_ELEMENT = {
    "fire": "Fire",
    "cold": "Ice",
    "lightning": "Electric",
    "thunder": "Electric",
    "acid": "Poison",
    "poison": "Poison",
    "psychic": "Psychic",
    "force": "Psychic",
    "radiant": "Light",
    "necrotic": "Death",
    "bludgeoning": "Normal",
    "piercing": "Normal",
    "slashing": "Normal",
}

def element_from_dnd_damage_type(damage_type_name: str) -> str:
    """Maps a raw Open5e/D&D damage type string onto the canonical element list."""
    return _DND_DAMAGE_TYPE_TO_ELEMENT.get((damage_type_name or "").lower(), "Normal")

# ─────────────────────────────────────────────────────────────
# Open5e v2 actions -> skill schema
# ─────────────────────────────────────────────────────────────

def isekai_action_to_skill(action_data: dict) -> dict:
    """
    Converts ONE entry from an Open5e v2 creature's `actions` list
    into the universal skill schema.

    Confirmed real v2 action shape:
        {name, desc, action_type, attacks: [...], usage_limits, ...}
    `attacks` is empty for pure utility/ability actions (e.g.
    "Nimble Escape"), populated for real weapon/spell attacks.
    This is a cleaner signal than v1 ever gave.

    Mapping:
        name          <- name
        description   <- desc (already full-sentence flavor text,
                         no generation needed)
        use_condition <- derived from action_type + usage_limits:
                         REACTION -> "reaction"
                         BONUS_ACTION -> "bonus_action"
                         LEGENDARY_ACTION -> "legendary_action"
                         ACTION -> "always" unless usage_limits is
                         set, in which case usage_limits' type/param
                         is appended (e.g. "always (per day 1)")
        acquire_condition <- None (still open/deferred)

    If attacks is EMPTY (utility/non-damaging action):
        damage_class  <- "Mixed" (no weapon/spell type to read)
        purpose       <- "Utility"
        damage        <- 0
        element        <- "Normal" (no damage_type to read)
        scaling       <- "STR" (arbitrary default, unused since damage=0)
        accuracy      <- 100 (arbitrary default, unused)
        role          <- "Self" (most non-attack actions target the
                         user — Nimble Escape, Parry, etc — placeholder,
                         not verified against every action type)

    If attacks is POPULATED (real attack):
        Uses attacks[0] (an action can have multiple sub-attacks,
        e.g. "Multiattack" style entries with several damage lines
        — only the first is converted here; a real multi-hit skill
        model is future work, not done in this pass):
        damage_class  <- attack_type: "WEAPON"->Physical,
                         "SPELL"->Magical, else "Mixed"
        element       <- damage_type (or extra_damage_type if the
                         primary damage_type is null, which happens
                         on some entries), via
                         element_from_dnd_damage_type()
        damage        <- flat-converted from
                         damage_die_count/damage_die_type/damage_bonus
                         using an average-roll conversion (dX average
                         = (X+1)/2 per die) — this is the "dice vs
                         flat" Phase 0 question resolved as: convert
                         to flat AT CONVERSION TIME using average
                         roll, not stored as dice. Flagged as a
                         choice, not a confirmed doc decision — the
                         doc's Q3 was left open ("we'll use range ig"
                         per user), so this picks the average-of-range
                         interpretation.
        accuracy      <- to_hit_mod converted to an approximate %
                         via a flat d20-vs-mod heuristic
                         (50% + to_hit_mod*5, clamped 5-95) — D&D's
                         to-hit is a d20 roll vs. target AC, which
                         this system doesn't have, so this is a
                         rough approximation, not a real conversion
        scaling       <- "STR" if attack_type=="WEAPON" and reach is
                         set (melee), "DEX" if WEAPON and range is
                         set with no reach (ranged), "INT" if SPELL
        purpose       <- "Damage"
        role          <- "Single-Target" (Open5e doesn't structurally
                         mark AOE here — spells like fireball would
                         need parsing `desc` text for "each creature
                         in a X-foot radius" etc, not done)
        effects       <- built from extra_damage_die_count/type/bonus
                         if present (e.g. poison-on-hit secondary
                         damage) — appended as a short text entry,
                         not further structured
    """
    skill = _empty_skill()
    skill["name"] = action_data.get("name", "unknown")
    skill["description"] = action_data.get("desc", "")

    action_type = action_data.get("action_type", "ACTION")
    usage_limits = action_data.get("usage_limits")
    if action_type == "REACTION":
        skill["use_condition"] = "reaction"
    elif action_type == "BONUS_ACTION":
        skill["use_condition"] = "bonus_action"
    elif action_type == "LEGENDARY_ACTION":
        skill["use_condition"] = "legendary_action"
    else:
        skill["use_condition"] = "always"
    if usage_limits:
        limit_type = usage_limits.get("type", "")
        limit_param = usage_limits.get("param", "")
        skill["use_condition"] += f" ({limit_type.lower().replace('_', ' ')} {limit_param})".rstrip()

    attacks = action_data.get("attacks") or []
    if not attacks:
        skill["damage_class"] = "Mixed"
        skill["purpose"] = "Utility"
        skill["role"] = "Self"
        return skill

    atk = attacks[0]
    attack_type = atk.get("attack_type", "")
    if attack_type == "WEAPON":
        skill["damage_class"] = "Physical"
        skill["scaling"] = "DEX" if (atk.get("range") and not atk.get("reach")) else "STR"
    elif attack_type == "SPELL":
        skill["damage_class"] = "Magical"
        skill["scaling"] = "INT"
    else:
        skill["damage_class"] = "Mixed"
        skill["scaling"] = "STR"

    damage_type = atk.get("damage_type") or atk.get("extra_damage_type")
    damage_type_name = damage_type.get("name", "") if isinstance(damage_type, dict) else ""
    skill["element"] = element_from_dnd_damage_type(damage_type_name)

    die_count = atk.get("damage_die_count") or 0
    die_type = atk.get("damage_die_type") or ""  # e.g. "D6", "D8"
    die_bonus = atk.get("damage_bonus") or 0
    die_size = 0
    if die_type.upper().startswith("D"):
        try:
            die_size = int(die_type[1:])
        except ValueError:
            die_size = 0
    # BUG FIX: this was using die_size directly (the MAXIMUM possible
    # roll per die) instead of the AVERAGE roll the docstring above
    # actually specifies (dX average = (X+1)/2). For a 1d4 sling that
    # made "damage" = 1*4 = 4 instead of the intended 1*2.5 = 2.5 —
    # roughly 1.6x too high on a small die, and worse on bigger dice
    # (2d6: max-based gave 12, average-based should give 7). This
    # only affects Isekai/D&D-sourced skills (isekai_action_to_skill),
    # not Pokémon — pokemon_move_to_skill is a separate function this
    # doesn't touch.
    avg_per_die = (die_size + 1) / 2 if die_size else 0
    skill["damage"] = round(die_count * avg_per_die + die_bonus, 1)

    to_hit = atk.get("to_hit_mod") or 0
    skill["accuracy"] = max(5, min(95, round(50 + to_hit * 5)))

    skill["purpose"] = "Damage"
    skill["role"] = "Single-Target"

    extra_count = atk.get("extra_damage_die_count")
    extra_type_obj = atk.get("extra_damage_type")
    if extra_count and isinstance(extra_type_obj, dict):
        skill["effects"] = [f"+{extra_type_obj.get('name', 'extra')} damage on hit"]

    return skill
