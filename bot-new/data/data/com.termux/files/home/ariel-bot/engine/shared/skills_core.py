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
# Digimon explicitly out of scope here (user: "forget anything digi")
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
# NOTE: split into skills_core.py (shared), pokemon/skills_pokemon.py, rpg/skills_rpg.py.

"""Ariel: skills core (split from skills.py)."""


# ─────────────────────────────────────────────────────────────
# Canonical element chart
#
# Canonical set = PokéAPI's 18 types, MINUS Ghost and Fairy as
# top-level categories, PLUS Life/Death/Light as new top-level
# categories. Ghost and Fairy still exist as sub-type labels that
# fold under Death and Light (same relationship as Cold -> Ice).
# ─────────────────────────────────────────────────────────────

CANONICAL_ELEMENTS = [
    "Normal", "Fire", "Water", "Electric", "Grass", "Ice",
    "Fighting", "Poison", "Ground", "Flying", "Psychic", "Bug",
    "Rock", "Dragon", "Dark", "Steel",
    "Life", "Death", "Light",  # new additions
]

def _empty_skill() -> dict:
    """Base skill shape — every converter fills this in, never omits a key."""
    return {
        "name": "",
        "description": "",
        "damage_class": "Physical",
        "role": "Single-Target",
        "purpose": "Damage",
        "element": "Normal",
        "effects": [],
        "damage": 0,
        "scaling": "STR",
        "accuracy": 100,
        "use_condition": "always",
        "acquire_condition": None,  # still open/deferred, per design discussion
    }
