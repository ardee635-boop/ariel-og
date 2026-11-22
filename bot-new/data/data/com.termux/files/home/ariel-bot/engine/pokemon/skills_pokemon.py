"""Ariel: skills pokemon (split from skills.py)."""
from skills_core import _empty_skill


# ─────────────────────────────────────────────────────────────
# Skills — unified skill schema + converters.
#
# ONE schema, used for BOTH creature skills (Pokémon moves, Open5e
# actions) AND Class skills (hand-authored) — per design discussion,
# Soulbounds and Classes are the same shape, skills[] included.
#
# NOT wired into any live game path yet. soulbound.py's converters
# still return skills: [] — this module is additive, built to be
# called FROM there next, not yet connected.
#
# — this file only covers Pokémon + Isekai.
#
# Schema (locked in design discussion):
#   name, description, damage_class (Physical/Magical/Mixed),
#   role (Single-Target/AOE/Self/Ally/Party),
#   purpose (Damage/Heal/Buff/Debuff/Status/Utility),
#   element (canonical — see ELEMENT_CHART below),
#   effects (list), damage (numeric), scaling (which stat),
#   accuracy, use_condition (always/cooldown/reaction/etc),
#   acquire_condition (still open/deferred — always None for now)
# ─────────────────────────────────────────────────────────────

# PokéAPI "power" (0–150ish) was calibrated for the old multiplicative
# ratio formula ((2L/5+2)*Power*(Atk/Def)/50+2). The new additive
# formula (scaling_stat + damage) needs power rescaled down so a
# move's damage is a meaningful add-on to the scaling stat, not
# roughly equal to it (Flamethrower=90 vs Charizard INT~131 was
# causing near-one-shot damage). Divisor is a pick — tune once real
# level-curve stat ranges exist (same caveat as K constant / defense
# mitigation curve).
POKEMON_POWER_SCALE = 8

# PokéAPI type -> canonical element. Only Ghost/Fairy actually
# remap; everything else is already a canonical name (identity
# mapping), listed explicitly so the chart is the single source
# of truth rather than "assume passthrough."
_POKEMON_TYPE_TO_ELEMENT = {
    "normal": "Normal", "fire": "Fire", "water": "Water",
    "electric": "Electric", "grass": "Grass", "ice": "Ice",
    "fighting": "Fighting", "poison": "Poison", "ground": "Ground",
    "flying": "Flying", "psychic": "Psychic", "bug": "Bug",
    "rock": "Rock", "dragon": "Dragon", "dark": "Dark", "steel": "Steel",
    "ghost": "Death",   # sub-type folds under Death
    "fairy": "Light",   # sub-type folds under Light
}

def element_from_pokemon_type(type_name: str) -> str:
    """Maps a raw PokéAPI type string onto the canonical element list."""
    return _POKEMON_TYPE_TO_ELEMENT.get((type_name or "").lower(), "Normal")

# ─────────────────────────────────────────────────────────────
# Pokémon moves -> skill schema
# ─────────────────────────────────────────────────────────────

def pokemon_move_to_skill(move_data: dict) -> dict:
    """
    Converts a pokeapi.py get_move() result into the universal
    skill schema.

    get_move() already returns: name, type, category
    (physical/special/status), power, accuracy, pp, priority,
    effect_chance, effect (text), stat_changes — this is the
    easiest of the two converters since the source data is
    already clean and structured, no keyword-matching needed.

    Mapping:
        name          <- name
        description   <- effect (short_effect text from PokéAPI)
        damage_class  <- category: "physical"->Physical,
                         "special"->Magical, "status"->Mixed
                         (status moves don't deal damage, "Mixed"
                         is a placeholder rather than inventing a
                         4th damage_class value)
        element       <- type, via element_from_pokemon_type()
        damage        <- power (0 for status moves)
        scaling       <- STR if category=="physical", INT if
                         "special"; status moves default to INT
                         (most status moves are more "special"-
                         flavored — a placeholder, not a rule)
        accuracy      <- accuracy
        purpose       <- inferred: power>0 -> Damage; else, if
                         stat_changes has any entry -> Debuff
                         (PokéAPI's stat_changes doesn't say WHO
                         the change targets — self vs opponent —
                         that needs the move's `target` field,
                         which get_move() doesn't currently fetch;
                         placeholder treats all as Debuff until
                         that field is added — a real gap, not
                         silently correct); otherwise Utility
        effects       <- [effect text] if effect_chance is set,
                         else []. Just wraps the existing `effect`
                         text as a single-item list for now —
                         proper structured effects (Burn, Poison,
                         etc as a canonical list) is the doc's
                         still-open "one canonical effect list"
                         item, not resolved here
        role          <- Single-Target (default; PokéAPI's `target`
                         field, not currently fetched, would give
                         a real AOE/self/etc signal — placeholder)
        use_condition <- "always" (Pokémon moves have no cooldown/
                         reaction concept — PP is a resource, not
                         a use_condition, left unmapped for now)
        acquire_condition <- None (still open/deferred)
    """
    skill = _empty_skill()

    skill["name"] = move_data.get("name", "unknown").replace("-", " ").title()
    skill["description"] = move_data.get("effect", "")

    category = move_data.get("category", "physical")
    if category == "physical":
        skill["damage_class"] = "Physical"
        skill["scaling"] = "STR"
    elif category == "special":
        skill["damage_class"] = "Magical"
        skill["scaling"] = "INT"
    else:  # "status"
        skill["damage_class"] = "Mixed"
        skill["scaling"] = "INT"

    skill["element"] = element_from_pokemon_type(move_data.get("type", ""))
    skill["damage"] = round((move_data.get("power") or 0) / POKEMON_POWER_SCALE, 1)
    skill["accuracy"] = move_data.get("accuracy") or 100

    stat_changes = move_data.get("stat_changes", [])
    if skill["damage"] > 0:
        skill["purpose"] = "Damage"
    elif stat_changes:
        # placeholder — see docstring, target direction not available yet
        skill["purpose"] = "Debuff"
    else:
        skill["purpose"] = "Utility"

    effect_chance = move_data.get("effect_chance")
    if effect_chance and move_data.get("effect"):
        skill["effects"] = [move_data["effect"]]

    return skill
