"""Ariel: soulbound pokemon (split from soulbound.py)."""


def _grade_from_stat(value: float) -> str:
    """
    Locked thresholds from player_classes_system.md section 3.
    NOTE: calibrated to Pokémon's 0-~150 base-stat range. Isekai's
    D&D-score range uses its own thresholds (see
    _grade_from_dnd_score below) — not this function.
    """
    if value >= 120:
        return "S"
    if value >= 100:
        return "A"
    if value >= 80:
        return "B"
    if value >= 60:
        return "C"
    return "D"

def pokemon_to_soulbound(pokemon_data: dict, db=None) -> dict:
    """
    Converts a get_pokemon()/get_full() dict (pokeapi.py) into the
    universal Soulbound schema.

    Mapping (PokéAPI has no native DEX/WIS/CHA — derived as a
    scaled blend of the 6 base stats until real per-series logic
    exists; open item, not final):
        STR ← attack
        INT ← special-attack
        DEF ← (defense + special-defense) / 2  [blended, per spec]
        SPD ← speed
        DEX ← avg(6 base stats) × 0.9
        WIS ← avg(6 base stats) × 0.6
        CHA ← avg(6 base stats) × 0.5

    Skills: pokemon_data["default_moves"] is a list of up to 4 move
    NAME strings (pokeapi.py's get_pokemon(), not full move objects).
    If `db` is given, each name is fetched via pokeapi.get_move() and
    converted through skills.pokemon_move_to_skill(). If `db` is
    None, skills stays empty (keeps this function usable without a
    DB handle, e.g. in tests) — this mirrors the get_full()/db
    dependency already present throughout pokeapi.py.
    """
    base = pokemon_data.get("base_stats", {})
    hp   = base.get("hp", 45)
    atk  = base.get("attack", 45)
    dfn  = base.get("defense", 45)
    spa  = base.get("special-attack", 45)
    spd_ = base.get("special-defense", 45)
    spe  = base.get("speed", 45)

    avg = (hp + atk + dfn + spa + spd_ + spe) / 6

    stats = {
        "STR": atk,
        "INT": spa,
        "DEF": (dfn + spd_) / 2,
        "SPD": spe,
        "DEX": avg * 0.9,
        "WIS": avg * 0.6,
        "CHA": avg * 0.5,
    }
    grades = {stat: _grade_from_stat(val) for stat, val in stats.items()}

    skills = []
    if db is not None:
        from pokeapi import get_move
        from skills_pokemon import pokemon_move_to_skill
        for move_name in pokemon_data.get("default_moves", []):
            move_data = get_move(db, move_name)
            if move_data:
                skills.append(pokemon_move_to_skill(move_data))

    return {
        "name":   pokemon_data.get("name", "unknown"),
        "series": "pokemon",
        "level":  1,
        "stats":  stats,
        "grades": grades,
        "skills": skills,
        "traits": [],
    }
