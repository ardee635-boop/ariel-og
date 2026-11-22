# ============================================================
# NIFLHEIM — stats.py
# Direct PokéAPI calculations for the Pokémon engine: base stats ->
# level stats, stat stages, accuracy stages, damage, crit.
# Pure functions, no soulbound / shared-engine imports.
# ============================================================

import random

STAT_KEYS = ("hp", "attack", "defense", "special-attack", "special-defense", "speed")
STAGE_KEYS = ("attack", "defense", "special-attack", "special-defense",
              "speed", "accuracy", "evasion")

IV_DEFAULT = 31
EV_DEFAULT = 0
CRIT_CHANCE = 1 / 24
CRIT_MULT = 1.5


# ── Level stats ───────────────────────────────────────────────

def calc_hp(base: int, level: int, iv: int = IV_DEFAULT, ev: int = EV_DEFAULT) -> int:
    return ((2 * base + iv + ev // 4) * level) // 100 + level + 10


def calc_stat(base: int, level: int, iv: int = IV_DEFAULT, ev: int = EV_DEFAULT,
              nature: float = 1.0) -> int:
    return int((((2 * base + iv + ev // 4) * level) // 100 + 5) * nature)


def compute_stats(base_stats: dict, level: int) -> dict:
    """PokéAPI base_stats -> {hp, attack, defense, special-attack,
    special-defense, speed} at this level (IV 31, EV 0, neutral nature)."""
    out = {"hp": calc_hp(base_stats.get("hp", 45), level)}
    for k in STAT_KEYS[1:]:
        out[k] = calc_stat(base_stats.get(k, 45), level)
    return out


# ── Stages (-6..+6) ───────────────────────────────────────────

def stage_mult(stage: int) -> float:
    """Attack/Defense/Sp.Atk/Sp.Def/Speed."""
    return (2 + stage) / 2 if stage >= 0 else 2 / (2 - stage)


def acc_mult(stage: int) -> float:
    """Accuracy/evasion (net stage)."""
    return (3 + stage) / 3 if stage >= 0 else 3 / (3 - stage)


class StageStack:
    """Per-battle stat stages for one combatant. Discarded at battle end."""

    def __init__(self):
        self.stages = {k: 0 for k in STAGE_KEYS}

    def stage(self, stat: str) -> int:
        return self.stages.get(stat, 0)

    def change(self, stat: str, delta: int) -> int:
        """Apply delta, clamped to ±6. Returns the change actually applied."""
        if stat not in self.stages:
            return 0
        before = self.stages[stat]
        self.stages[stat] = max(-6, min(6, before + delta))
        return self.stages[stat] - before

    def set(self, stat: str, value: int):
        if stat in self.stages:
            self.stages[stat] = max(-6, min(6, value))


def effective(stat_name: str, base_value: float, stack) -> float:
    """Stat value after stages (stack may be None)."""
    if stack is None:
        return base_value
    return base_value * stage_mult(stack.stage(stat_name))


# ── Damage ────────────────────────────────────────────────────

def damage(level: int, power: int, attack: float, defense: float, *,
           stab: float = 1.0, type_mult: float = 1.0,
           crit: bool = False, burned_physical: bool = False) -> int:
    """Standard Pokémon damage formula. 0 when the type is immune."""
    if type_mult == 0:
        return 0
    if burned_physical:
        attack *= 0.5
    base = ((2 * level / 5 + 2) * power * attack / max(1, defense)) / 50 + 2
    total = base * stab * type_mult * (CRIT_MULT if crit else 1.0) * random.uniform(0.85, 1.0)
    return max(1, int(total))


def roll_crit() -> bool:
    return random.random() < CRIT_CHANCE


def accuracy_threshold(move_accuracy: int, acc_stage: int, eva_stage: int) -> int:
    net = max(-6, min(6, acc_stage - eva_stage))
    return int(move_accuracy * acc_mult(net))


# ── Moves ─────────────────────────────────────────────────────

def moves_for_level(api_data: dict, level: int) -> list[str]:
    """Last 4 level-up moves learnable at <= level (PokéAPI learnset).
    Falls back to the cached first-4 'default_moves' for older cache entries."""
    learnset = api_data.get("learnset")
    if learnset:
        known: list[str] = []
        for name, lv in learnset:
            if lv <= level:
                if name in known:
                    known.remove(name)
                known.append(name)
        if known:
            return known[-4:]
    return list(api_data.get("default_moves", []))[:4]


def move_entry(name: str, db=None) -> dict:
    """{name, pp, max_pp} with PP straight from PokéAPI when a db is available."""
    pp = 20
    if db is not None:
        try:
            from pokeapi import get_move
            d = get_move(db, name)
            if d and d.get("pp"):
                pp = int(d["pp"])
        except Exception:
            pass
    return {"name": name, "pp": pp, "max_pp": pp}
