"""RPG damage: copy of the combat formula without the Pokemon type chart/STAB (always 1.0 in RPG)."""
import random
from soulbound_core import get_contested_stat


def _apply_stack_to_primary(stat_name: str, base_value: float, stack) -> float:
    """
    Applies a secondary_stats.ModifierStack directly to a raw PRIMARY
    stat (STR/INT/DEF/SPD/DEX/WIS/CHA). NOT the same as
    compute_self_secondary() — that function only resolves named
    SECONDARY stats (hp, armor, crit_chance, etc. — it has no
    formula for raw primaries and raises KeyError if asked for one).
    This walks stack.modifiers in acquisition order, applying flat
    and percent modifiers as encountered (secondary_stats.py §4 —
    NOT grouped flat-phase-then-percent-phase), same rule
    compute_self_secondary uses internally for secondaries.
    """
    if not stack:
        return base_value
    value = base_value
    for mod in sorted(stack.modifiers, key=lambda m: m.acquired_at):
        if mod.target != stat_name:
            continue
        if mod.type == "flat":
            value += mod.value
        elif mod.type == "percent":
            value *= mod.value
    return value


def _get_stats(combatant) -> dict:
    """Stats accessor for RPG combatants (plain dicts: player soulbound sheets and monsters)."""
    return combatant.get("stats", {})


def _get_soulbound_skill(combatant, move_name: str) -> dict | None:
    """
    Looks up a converted skill (skills schema) by name from the combatant's
    soulbound["skills"] list. Returns None if not found. Matches loosely on a
    normalized name (hyphens to spaces, lowercase).
    """
    soulbound = combatant.get("soulbound")
    if not soulbound:
        return None
    target = move_name.replace("-", " ").strip().lower()
    for skill in soulbound.get("skills", []):
        if skill["name"].strip().lower() == target:
            return skill
    return None


def _defense_mitigation(defense_value: float) -> float:
    """
    Flat % damage reduction from DEF, NOT the old Atk/Def ratio.
    Diminishing-returns curve: def/(def+100) — a DEF of 100 blocks
    50%, DEF of 300 blocks 75%, approaches but never reaches 100%.
    Not from the design doc (doc doesn't specify a mitigation
    curve) — a pick, easy to retune once real stat ranges exist
    across the level curve (same caveat as the K constant in
    secondary_stats.py).
    """
    mitigation_pct = defense_value / (defense_value + 100)
    return 1.0 - mitigation_pct


def calc_damage(attacker, move_data: dict, defender, db=None,
                attacker_stack=None, defender_stack=None) -> tuple[int, float]:
    """
    RPG damage. Copy of the Pokemon-side formula (pokemon/battle.py) with the
    Pokemon-only parts removed: no type chart and no STAB. RPG combatants have
    empty type lists and every RPG skill is the "normal" element, so both were
    always 1.0 and the numbers are identical to the old shared version.

    Returns (damage, type_mult). type_mult is always 1.0, kept so existing
    callers that unpack a 2-tuple keep working. damage == -1 means a miss.

    Formula:
        damage = (scaling stat + skill damage) * crit * variance * DEF mitigation
      - skill: converted skill from soulbound["skills"], else move_data power
      - crit: contested roll (secondary_stats crit_chance vs evasion)
      - variance: +-3%
      - accuracy: skill accuracy, adjusted by attacker DEX vs defender DEX stacks
    """
    attacker_stats = _get_stats(attacker)
    defender_stats = _get_stats(defender)

    skill = _get_soulbound_skill(attacker, move_data.get("name", ""))

    if skill:
        base_damage = skill["damage"]
        scaling_stat = skill["scaling"]
        accuracy = skill["accuracy"]
    else:
        # No converted skill found: fall back to move_data's own power/accuracy.
        power = move_data.get("power", 0)
        if power == 0:
            return 0, 1.0
        base_damage = power
        category = move_data.get("category", "physical")
        scaling_stat = "INT" if category == "special" else "STR"
        accuracy = move_data.get("accuracy") or 100

    if base_damage <= 0:
        return 0, 1.0  # status/utility move, no damage component

    scaling_value = _apply_stack_to_primary(scaling_stat, attacker_stats.get(scaling_stat, 0), attacker_stack)
    defender_def  = _apply_stack_to_primary("DEF", defender_stats.get("DEF", 0), defender_stack)

    # Real contested crit roll (secondary_stats.py)
    attacker_sb = {"stats": attacker_stats}
    defender_sb = {"stats": defender_stats}
    crit_chance = get_contested_stat("crit_chance", defender_sb, attacker_sb,
                                     defender_stack, attacker_stack)
    crit = 2.0 if random.uniform(0, 100) < crit_chance else 1.0

    variance = random.uniform(0.97, 1.03)

    # Accuracy: DEX carries both accuracy and evasion
    atk_dex_base = attacker_stats.get("DEX", 1)
    atk_dex = _apply_stack_to_primary("DEX", atk_dex_base, attacker_stack)
    accuracy = accuracy * (atk_dex / max(1, atk_dex_base))

    def_dex_base = defender_stats.get("DEX", 1)
    def_dex = _apply_stack_to_primary("DEX", def_dex_base, defender_stack)
    accuracy = accuracy / (def_dex / max(1, def_dex_base))

    roll = random.randint(1, 100)
    threshold = max(5, min(100, int(accuracy)))
    if roll > threshold:
        print(f"[rpg_damage] MISS roll={roll} threshold={threshold} move={move_data.get('name')!r}", flush=True)
        return -1, 1.0   # -1 = missed

    total = (scaling_value + base_damage) * crit * variance
    damage = int(total * _defense_mitigation(defender_def))
    print(f"[rpg_damage] HIT move={move_data.get('name')!r} base={base_damage} scaling={scaling_value:.1f} "
          f"def={defender_def:.1f} crit={crit} final={max(1, damage)}", flush=True)
    return max(1, damage), 1.0
