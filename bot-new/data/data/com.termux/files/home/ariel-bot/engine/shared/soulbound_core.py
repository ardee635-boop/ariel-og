# ─────────────────────────────────────────────────────────────
# Soulbound conversion — Pokémon / Isekai / Digimon → universal
# Soulbound schema. Phase 1 (data layer).
#
# NOT wired into any live game path yet — battle.py/data_pokemon.py
# still run the old formulas. This is additive scaffolding only,
# built alongside the live bot. See soulbound_integration_checklist.md
# for the phased plan; old code (calc_damage(), data_pokemon.py's
# star/stat logic) gets removed in Phase 3, once this is verified.
#
# Schema (player_classes_system.md section 1):
#   name, series, level, stats{STR,INT,DEF,SPD,DEX,WIS,CHA},
#   grades{same 7 keys, S/A/B/C/D}, skills[], traits[]
# ─────────────────────────────────────────────────────────────
# NOTE: split into soulbound_core.py (shared), pokemon/soulbound_pokemon.py, rpg/soulbound_rpg.py, rpg/statuses.py, rpg/loadout.py. Digimon support was removed.

"""Ariel: soulbound core (split from soulbound.py)."""


# ─────────────────────────────────────────────────────────────
# Growth per level — universal, one table for all series
# (player_classes_system.md §3, locked/confirmed in the doc, not
# a placeholder). A Soulbound's stat at any level = Level 1 value
# + (grade's growth-per-level × (current level - 1)).
# ─────────────────────────────────────────────────────────────

GROWTH_PER_LEVEL = {
    "S": 2.0,
    "A": 1.6,
    "B": 1.2,
    "C": 0.8,
    "D": 0.5,
}

def stats_at_level(soulbound: dict, level: int) -> dict:
    """
    Returns a NEW stats dict scaled to `level`, using the universal
    growth-per-grade table. soulbound["stats"]/["grades"] are always
    the Level 1 values (that's what the converters produce) — this
    is the function that actually applies level scaling on top,
    same formula/table for every series, no exceptions (per doc).
    """
    level1_stats = soulbound["stats"]
    grades = soulbound["grades"]
    levels_above_1 = max(0, level - 1)
    return {
        stat: level1_stats[stat] + GROWTH_PER_LEVEL.get(grades.get(stat, "D"), 0.5) * levels_above_1
        for stat in level1_stats
    }

# ─────────────────────────────────────────────────────────────
# Secondary stats bridge
#
# secondary_stats.py works on a plain {"STR": x, ...} dict — this
# just pulls that dict out of a finished Soulbound object so
# callers don't need to know the Soulbound schema themselves.
# secondary_stats.py is NOT imported at module load time (only
# inside these functions) so soulbound.py keeps working even in
# contexts where that file hasn't been deployed alongside it yet.
# ─────────────────────────────────────────────────────────────

def get_secondary_stats(soulbound: dict, stack=None) -> dict:
    """
    Every non-contested secondary stat (HP, Armor, Regen, Status
    Resists, etc.) for a Soulbound, as one dict. `stack`, if given,
    is a secondary_stats.ModifierStack (permanent gear/traits — see
    design discussion on ModifierStack lifetime/persistence).
    Contested stats (Evasion/Block/Counter/Crit Chance/Escape)
    require an opponent and are NOT included here — use
    get_contested_stat() below for those.
    """
    from secondary_stats import compute_all_self_secondaries
    return compute_all_self_secondaries(soulbound["stats"], stack)

def get_contested_stat(name: str, defender: dict, attacker: dict,
                        defender_stack=None, attacker_stack=None) -> float:
    """
    Resolves one contested percentage stat (Block/Evasion/Counter/
    Crit Chance/Escape) between two Soulbounds. `name` is the
    secondary_stats.py stat name (e.g. "crit_chance"). Returns a
    0-100 percentage, ready to roll against directly.
    """
    from secondary_stats import resolve_contested
    return resolve_contested(
        name, defender["stats"], attacker["stats"],
        defender_stack, attacker_stack,
    )
