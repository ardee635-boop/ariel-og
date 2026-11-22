# ─────────────────────────────────────────────────────────────
# Secondary stats & modifier system — Phase 3 groundwork.
#
# General system: works for Soulbounds AND player classes, since
# both share the same 7 primary stat names (STR/DEX/SPD/DEF/INT/
# WIS/CHA). Not wired into battle.py yet — see
# docs/secondary_stats_system.md for the full spec and open items.
#
# NOT tied to any one series/source — this reads a plain
# {"STR": x, "DEX": x, ...} dict, same shape soulbound.py's
# converters already output in Soulbound["stats"].
#
# v2: percentage-type secondaries (Block, Evasion, Counter, Crit
# Chance, all Status Resists, Taming, Escape) are now resolved
# CONTESTED — defender's stat vs. attacker's opposing stat — not
# clamped in a vacuum against a fixed ceiling. See §3/§4 of the
# spec doc for why the old flat-clamp model was replaced.
# ─────────────────────────────────────────────────────────────

from dataclasses import dataclass, field


# ── Secondary stat formulas (raw blend — pre-contest, pre-modifier) ──
# Each secondary = list of (primary_name, weight) pairs, applied to
# the primary's CURRENT (possibly modified) value.

SECONDARY_FORMULAS: dict[str, list[tuple[str, float]]] = {
    # Combat
    "stamina":             [("DEF", 0.60), ("STR", 0.40)],
    "physical_attack":     [("STR", 1.00)],
    "magic_attack":        [("INT", 0.80), ("WIS", 0.20)],
    "physical_defense":    [("DEF", 0.80), ("STR", 0.20)],
    "magic_defense":       [("WIS", 0.60), ("DEF", 0.40)],
    "initiative":          [("SPD", 0.70), ("DEX", 0.30)],
    "attack_speed":        [("SPD", 0.70), ("DEX", 0.30)],
    "movement_speed":      [("SPD", 1.00)],

    # Accuracy & Criticals
    "accuracy":            [("DEX", 0.80), ("WIS", 0.20)],
    "evasion":             [("SPD", 0.60), ("DEX", 0.40)],
    "crit_chance":         [("SPD", 0.30), ("DEX", 0.70)],
    # crit_damage deliberately NOT here — pure magnitude multiplier
    # once a crit has already happened, stays modifier-only (skills/
    # gear/traits), same reasoning as armor/magic pen and the steals.

    # Offensive bonuses (non-removed ones)
    "healing_power":       [("WIS", 0.70), ("INT", 0.30)],
    "reflect_damage":      [("DEF", 0.70), ("WIS", 0.30)],

    # Defensive
    "armor":               [("DEF", 1.00)],
    "magic_resist":        [("WIS", 0.70), ("DEF", 0.30)],
    "block_chance":        [("DEF", 0.70), ("DEX", 0.30)],
    "counter_chance":      [("DEX", 0.60), ("SPD", 0.40)],
    "damage_reduction":    [("DEF", 0.80), ("WIS", 0.20)],
    "shield_strength":     [("DEF", 0.50), ("INT", 0.50)],

    # Recovery
    "hp_regen":            [("DEF", 0.70), ("WIS", 0.30)],
    "mana_regen":          [("WIS", 0.70), ("INT", 0.30)],
    "stamina_regen":       [("DEF", 0.50), ("SPD", 0.50)],

    # Utility
    "perception":          [("WIS", 0.80), ("INT", 0.20)],
    "detection":           [("WIS", 0.70), ("DEX", 0.30)],
    "stealth":             [("DEX", 0.70), ("SPD", 0.30)],
    "carry_capacity":      [("STR", 0.80), ("DEF", 0.20)],
    "jump_height":         [("STR", 0.60), ("SPD", 0.40)],
    "swim_speed":          [("SPD", 0.60), ("STR", 0.40)],
    "climb_speed":         [("STR", 0.50), ("DEX", 0.50)],
    "fly_speed":           [("SPD", 0.80), ("DEX", 0.20)],

    # Status resistance
    "burn_resist":         [("DEF", 0.70), ("WIS", 0.30)],
    "poison_resist":       [("DEF", 0.80), ("WIS", 0.20)],
    "freeze_resist":       [("DEF", 0.50), ("WIS", 0.50)],
    "paralysis_resist":    [("WIS", 0.60), ("SPD", 0.40)],
    "sleep_resist":        [("WIS", 0.80), ("INT", 0.20)],
    "confusion_resist":    [("WIS", 0.60), ("INT", 0.40)],
    "fear_resist":         [("CHA", 0.60), ("WIS", 0.40)],
    "charm_resist":        [("WIS", 0.50), ("CHA", 0.50)],
    "blind_resist":        [("WIS", 0.80), ("DEX", 0.20)],
    "silence_resist":      [("WIS", 0.70), ("CHA", 0.30)],
    "knockback_resist":    [("STR", 0.60), ("DEF", 0.40)],

    # Summoning (Summoner class facing)
    "summon_power":        [("CHA", 0.60), ("INT", 0.40)],
    "summon_hp":            [("CHA", 0.50), ("DEF", 0.50)],
    "summon_damage":       [("CHA", 0.60), ("INT", 0.40)],
    "summon_duration":     [("CHA", 0.70), ("WIS", 0.30)],
    "bond_strength":       [("CHA", 0.70), ("WIS", 0.30)],
    "max_soul_energy":     [("CHA", 0.60), ("DEF", 0.40)],

    # Hidden stats
    "threat":              [("STR", 0.50), ("CHA", 0.50)],
    "leadership":          [("CHA", 0.70), ("WIS", 0.30)],
    "taming_chance":       [("CHA", 0.60), ("WIS", 0.40)],
    "escape_chance":       [("SPD", 0.70), ("DEX", 0.30)],
    # "luck" intentionally absent — flat/equipment/buffs only.
}

# Modifier-only stats: no primary-stat formula, value comes purely
# from skills/gear/traits/buffs granting them directly. Pure
# magnitude multipliers with no natural opposing side to contest
# against — that's what put them here, not "percentage" per se.
MODIFIER_ONLY_STATS = {
    "crit_damage",
    "armor_penetration", "magic_penetration",
    "life_steal", "mana_steal",
    "luck",
}

# Flat-conversion stats: NOT a weighted blend like SECONDARY_FORMULAS
# (no percentage split of one combined total) — each listed primary
# independently grants a flat amount per full "unit_size" spent,
# floor division, no partial credit for a remainder. See
# compute_flat_conversion() below for how this is actually applied.
#
# name -> list of (primary_name, unit_size, amount_per_unit)
#   e.g. ("VIT", 1, 100) = +100 per 1 VIT  (VIT // 1 * 100)
#        ("DEF", 3, 100) = +100 per 3 DEF  (DEF // 3 * 100)
FLAT_CONVERSION_FORMULAS: dict[str, list[tuple[str, int, float]]] = {
    "hp":   [("VIT", 1, 50), ("DEF", 3, 50), ("STR", 3, 50)],
    "mana": [("INT", 1, 100), ("WIS", 3, 100), ("VIT", 2, 100)],
}

# ── Contested pairs ──────────────────────────────────────────────
# name -> (defender_secondary, attacker_secondary, K)
# Resolved as: defender_raw / (defender_raw + attacker_raw + K)
# Self-normalizing — can never reach 100% regardless of how far
# primary stats power-creep, since the attacker's own growth pushes
# back automatically. K is the only real tuning knob (lower K =
# sharper swings on a mismatch, higher K = flatter/closer to even).
# Placeholder K=20 across the board — not balance-tested, revisit
# once real primary ranges exist across the level curve.
CONTESTED_PAIRS: dict[str, tuple[str, str, float]] = {
    "evasion":          ("evasion", "accuracy", 20.0),
    "block_chance":     ("block_chance", "physical_attack", 20.0),
    "counter_chance":   ("counter_chance", "initiative", 20.0),
    "crit_chance":       ("crit_chance", "evasion", 20.0),
    "escape_chance":    ("escape_chance", "initiative", 20.0),
}
# Taming Chance is NOT a universal contested secondary — corrected
# this session. For every class except Summoner, taming odds come
# from the capture item (ball tier/type — flat, item-dependent,
# same mechanic as the existing POKEBALL_MODIFIER system in
# battle.py's attempt_catch()), not from a stat blend at all.
# Only Summoner gets a stat-driven contested taming roll — see
# resolve_taming_chance() below, which branches on class instead of
# living in the universal CONTESTED_PAIRS table.
SUMMONER_TAMING_PAIR = ("taming_chance", "wis_raw", 20.0)
# Status resists (burn/poison/freeze/etc.) are NOT contested — see
# STATUS_RESIST_STATS below. "Resist" means damage-taken reduction
# on an already-inflicted status, not a chance-to-be-inflicted roll.
# That's a straight self-only blend (like Damage Reduction/Armor),
# not an attacker-vs-defender contest — there's no opposing "how
# good is this attacker at inflicting status" stat to contest
# against.

# Status resists apply as a % reduction to ONLY the status's tick
# damage. Duration is NOT affected by Resist — a burn lasts its
# full number of turns regardless of Resist, it just hurts less
# each tick (locked this session — earlier draft had Resist
# reducing duration too; corrected to damage-only, simpler rule).
# Self-only secondary, clamped 0-100% since it reduces a real
# number rather than gating an event.
STATUS_RESIST_STATS = {
    "burn_resist", "poison_resist", "freeze_resist", "paralysis_resist",
    "sleep_resist", "confusion_resist", "fear_resist", "charm_resist",
    "blind_resist", "silence_resist", "knockback_resist",
}
RESIST_CLAMP = (0.0, 100.0)  # can't reduce more than 100% of tick damage



# ── Modifiers ────────────────────────────────────────────────────

@dataclass
class Modifier:
    """
    One stat modifier from any source (skill, gear, trait, buff).
    See docs/secondary_stats_system.md §4 for the full spec.
    """
    source: str
    target: str
    type: str               # "flat" | "percent"
    value: float
    acquired_at: int
    duration: int | None = None


@dataclass
class ModifierStack:
    """
    Ordered collection of modifiers for one entity (Soulbound or
    class instance). Order of application = acquired_at order,
    NOT grouped by flat-then-percent — see spec §4.
    """
    modifiers: list[Modifier] = field(default_factory=list)
    _next_seq: int = 0

    def add(self, source: str, target: str, type: str, value: float,
             duration: int | None = None) -> Modifier:
        mod = Modifier(
            source=source, target=target, type=type, value=value,
            acquired_at=self._next_seq, duration=duration,
        )
        self.modifiers.append(mod)
        self._next_seq += 1
        return mod

    def remove_by_source(self, source: str):
        self.modifiers = [m for m in self.modifiers if m.source != source]

    def tick(self):
        alive = []
        for m in self.modifiers:
            if m.duration is None:
                alive.append(m)
                continue
            m.duration -= 1
            if m.duration > 0:
                alive.append(m)
        self.modifiers = alive

    def for_target(self, target: str) -> list[Modifier]:
        return sorted(
            (m for m in self.modifiers if m.target == target),
            key=lambda m: m.acquired_at,
        )


def apply_modifiers(base_value: float, target: str, stack: ModifierStack) -> float:
    """
    Walks all modifiers targeting `target`, in acquisition order,
    one linear pass. Flat modifiers add to the running total,
    percent modifiers multiply it — same order they were acquired,
    no flat-phase/percent-phase split. Two +20% modifiers on the
    same stat compound (base * 1.2 * 1.2), they do not sum to +40%.
    """
    running = base_value
    for mod in stack.for_target(target):
        if mod.type == "flat":
            running += mod.value
        elif mod.type == "percent":
            running *= (1 + mod.value)
        else:
            raise ValueError(f"Unknown modifier type: {mod.type!r} on {mod.source}")
    return running


# ── Raw (uncontested) blend — building block for both self-only
#    secondaries AND the two sides of a contested pair ──────────

def compute_primary(name: str, base_primaries: dict[str, float],
                     stack: ModifierStack | None = None) -> float:
    """Primary stat value, with modifiers applied if a stack is given."""
    value = base_primaries.get(name, 0.0)
    if stack is not None:
        value = apply_modifiers(value, name, stack)
    return value


def compute_flat_conversion(name: str, base_primaries: dict[str, float],
                             stack: ModifierStack | None) -> float:
    """
    A FLAT_CONVERSION_FORMULAS secondary (hp, mana): each listed
    primary independently contributes floor(value / unit_size) *
    amount_per_unit — NOT a weighted blend/percentage split like
    SECONDARY_FORMULAS. Modifiers targeting the secondary itself
    still apply on top, same as any other secondary.
    """
    total = 0.0
    for prim, unit_size, amount_per_unit in FLAT_CONVERSION_FORMULAS[name]:
        value = compute_primary(prim, base_primaries, stack)
        total += (int(value) // unit_size) * amount_per_unit
    return apply_modifiers(total, name, stack) if stack is not None else total


def _raw_blend(name: str, base_primaries: dict[str, float],
                stack: ModifierStack | None) -> float:
    """
    Pre-contest, pre-clamp blend for one secondary: SECONDARY_FORMULAS
    weighted sum of (possibly modified) primaries, then any modifiers
    targeting the secondary itself. Modifier-only stats return 0
    here — their whole value comes from apply_modifiers.
    """
    if name == "wis_raw":  # synthetic pass-through, used by contested pairs
        return compute_primary("WIS", base_primaries, stack)

    if name in FLAT_CONVERSION_FORMULAS:
        return compute_flat_conversion(name, base_primaries, stack)

    if name in MODIFIER_ONLY_STATS:
        base = 0.0
    else:
        formula = SECONDARY_FORMULAS.get(name)
        if formula is None:
            raise KeyError(
                f"No formula for secondary stat '{name}' — add it to "
                f"SECONDARY_FORMULAS or MODIFIER_ONLY_STATS."
            )
        base = sum(
            compute_primary(prim, base_primaries, stack) * weight
            for prim, weight in formula
        )

    return apply_modifiers(base, name, stack) if stack is not None else base


# ── Public entry points ─────────────────────────────────────────

def compute_self_secondary(name: str, base_primaries: dict[str, float],
                            stack: ModifierStack | None = None) -> float:
    """
    Computes a non-contested secondary (HP, Armor, Regen, Perception,
    Status Resists, etc.) — the raw blend + modifiers, no opposing
    side.

    Status Resists (burn_resist, poison_resist, etc.) are a % applied
    to reduce ONLY the status's tick damage — duration is untouched,
    a burn lasts its full length regardless of Resist, it just deals
    less damage per tick. Not a chance-to-be-inflicted roll, so
    they're clamped 0-100% here (can't reduce more than the full
    amount) rather than resolved contested.
    """
    if name in CONTESTED_PAIRS:
        raise ValueError(
            f"'{name}' is a contested stat — use resolve_contested() "
            f"with an attacker, not compute_self_secondary()."
        )
    value = _raw_blend(name, base_primaries, stack)
    if name in STATUS_RESIST_STATS:
        lo, hi = RESIST_CLAMP
        value = max(lo, min(hi, value))
    return value


def resolve_contested(name: str,
                       defender_primaries: dict[str, float],
                       attacker_primaries: dict[str, float],
                       defender_stack: ModifierStack | None = None,
                       attacker_stack: ModifierStack | None = None) -> float:
    """
    Resolves a contested percentage stat (Block, Evasion, Counter,
    Crit Chance, Escape) as:

        defender_raw / (defender_raw + attacker_raw + K) * 100

    Self-normalizing — mathematically can't reach 100% no matter how
    large primary stats get, since the attacker's own value pushes
    back automatically. Equal opponents land near even (~40-50%
    depending on K); a mismatch swings toward whoever's stronger.

    Status Resists are NOT contested — they're self-only, see
    compute_self_secondary().

    Returns a percentage (0-100), ready to roll against directly.
    """
    if name not in CONTESTED_PAIRS:
        raise ValueError(
            f"'{name}' is not a contested stat — use "
            f"compute_self_secondary() instead."
        )
    defender_stat, attacker_stat, k = CONTESTED_PAIRS[name]

    defender_raw = _raw_blend(defender_stat, defender_primaries, defender_stack)
    attacker_raw = _raw_blend(attacker_stat, attacker_primaries, attacker_stack)

    denom = defender_raw + attacker_raw + k
    if denom <= 0:
        return 0.0
    return (defender_raw / denom) * 100.0


def resolve_taming_chance(target_primaries: dict[str, float],
                           item_flat_chance: float,
                           is_summoner: bool = False,
                           summoner_primaries: dict[str, float] | None = None,
                           target_stack: ModifierStack | None = None,
                           summoner_stack: ModifierStack | None = None) -> float:
    """
    Taming Chance is class-conditional, not a universal contested
    stat (corrected this session):

    - Non-Summoner classes: flat, item-dependent — whatever the
      capture item/ball provides (`item_flat_chance`), same shape as
      the existing POKEBALL_MODIFIER system in battle.py's
      attempt_catch(). No stat blend involved at all.
    - Summoner: stat-driven contested roll (Summoner's own relevant
      stat vs. the target's raw WIS), via SUMMONER_TAMING_PAIR.
      `summoner_primaries` is required in this branch.

    Returns a percentage (0-100).
    """
    if not is_summoner:
        return max(0.0, min(100.0, item_flat_chance))

    if summoner_primaries is None:
        raise ValueError("summoner_primaries required when is_summoner=True")

    summoner_stat, target_stat, k = SUMMONER_TAMING_PAIR
    summoner_raw = _raw_blend(summoner_stat, summoner_primaries, summoner_stack)
    target_raw = _raw_blend(target_stat, target_primaries, target_stack)

    denom = summoner_raw + target_raw + k
    if denom <= 0:
        return 0.0
    return (summoner_raw / denom) * 100.0


def compute_all_self_secondaries(base_primaries: dict[str, float],
                                  stack: ModifierStack | None = None) -> dict[str, float]:
    """
    Every non-contested secondary in one call (formula-based +
    flat-conversion + modifier-only, minus anything in
    CONTESTED_PAIRS — those need an opponent and must go through
    resolve_contested() instead).
    """
    all_names = (
        set(SECONDARY_FORMULAS) | set(FLAT_CONVERSION_FORMULAS) | MODIFIER_ONLY_STATS
    ) - set(CONTESTED_PAIRS)
    return {name: compute_self_secondary(name, base_primaries, stack) for name in all_names}
