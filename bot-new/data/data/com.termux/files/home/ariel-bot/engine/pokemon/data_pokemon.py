# ============================================================
# DATA_POKEMON.PY  —  NIFLHEIM
# Starter definitions, star roll, stat multipliers,
# OwnedPokemon class, wild encounter tables
# ============================================================

import random
import time

# ─────────────────────────────────────────────────────────────
# STARTERS
# Five choices presented by Prof. Oak.
# All data beyond name/type/lore comes from PokéAPI at runtime.
# ─────────────────────────────────────────────────────────────

STARTERS = {
    "cyndaquil": {
        "type":    "Fire",
        "label":   "Cyndaquil",
        "element": "🔥",
        "lore": (
            "Timid at first, but once its back bursts into flame, there's no stopping it. "
            "The fire it breathes grows hotter the more it's pushed. "
            "Fierce, fast — a late bloomer that peaks at exactly the right moment."
        ),
    },
    "chikorita": {
        "type":    "Grass",
        "label":   "Chikorita",
        "element": "🌿",
        "lore": (
            "The leaf on its head releases a sweet scent that calms those around it. "
            "Don't mistake its gentleness for weakness — "
            "Chikorita endures what others cannot and outlasts them all."
        ),
    },
    "squirtle": {
        "type":    "Water",
        "label":   "Squirtle",
        "element": "💧",
        "lore": (
            "Calm water runs deep. "
            "Its shell has weathered more than it lets on. "
            "Reads a battle like a chess board — patient, precise, devastating."
        ),
    },
}

STARTER_NAMES = list(STARTERS.keys())


# ─────────────────────────────────────────────────────────────
# STAR SYSTEM
# Stars = prestige + stat multiplier + evolution odds
# Roll happens once at the moment Oak hands over the Pokémon
# ─────────────────────────────────────────────────────────────

STAR_WEIGHTS = [
    (1,  15.00),
    (2,  30.00),
    (3,  35.00),
    (4,  10.00),
    (5,   5.00),
    (6,   3.00),
    (7,   1.50),
    (8,   0.40),
    (9,   0.09),
    (10,  0.01),
]

_STARS    = [s for s, _ in STAR_WEIGHTS]
_WEIGHTS  = [w for _, w in STAR_WEIGHTS]


def roll_stars() -> int:
    """Weighted random star roll. Called once when a Pokémon is obtained."""
    return random.choices(_STARS, weights=_WEIGHTS, k=1)[0]


# Stat multiplier per star — kept reasonable, noticeable but not evil
STAR_MULTIPLIER = {
    1:  1.00,
    2:  1.08,
    3:  1.17,
    4:  1.27,
    5:  1.38,
    6:  1.50,
    7:  1.63,
    8:  1.76,
    9:  1.88,
    10: 2.00,
}

STAR_LABEL = {
    1:  "✧---------",
    2:  "✧✧--------",
    3:  "✧✧✧-------",
    4:  "✧✧✧✧------",
    5:  "✧✧✧✧✧-----",
    6:  "✧✧✧✧✧✧----",
    7:  "✧✧✧✧✧✧✧---",
    8:  "✧✧✧✧✧✧✧✧--",
    9:  "✧✧✧✧✧✧✧✧✧-",
    10: "✧✧✧✧✧✧✧✧✧✧",
}

STAR_PRESTIGE = {
    1:  "",
    2:  "",
    3:  "Bronze",
    4:  "Silver",
    5:  "Gold",
    6:  "Platinum",
    7:  "Diamond",
    8:  "Master",
    9:  "Legend",
    10: "Mythic",
}

# Evolution odds boost per star (flat bonus on top of base catch/evo logic)
STAR_EVO_BONUS = {
    1:  0.00,
    2:  0.05,
    3:  0.10,
    4:  0.18,
    5:  0.28,
    6:  0.40,
    7:  0.55,
    8:  0.70,
    9:  0.85,
    10: 1.00,   # guaranteed max evolution
}


def apply_star_stats(base_stats: dict, stars: int) -> dict:
    """
    Apply star multiplier to a raw base_stats dict from PokéAPI.
    Returns new dict with floored integer values.
    """
    mult = STAR_MULTIPLIER.get(stars, 1.0)
    return {k: int(v * mult) for k, v in base_stats.items()}


# ─────────────────────────────────────────────────────────────
# OWNED POKEMON
# Wraps PokéAPI data + star system + battle state.
# Created when a player receives or catches a Pokémon.
# ─────────────────────────────────────────────────────────────

class OwnedPokemon:
    def __init__(self, name: str, api_data: dict, stars: int | None = None):
        self.name         = name.lower()
        self.label        = api_data.get("name", name).capitalize()
        self.stars        = stars if stars is not None else roll_stars()
        self.level        = 5      # starters begin at level 5
        self.xp           = 0

        # API data
        self.types        = api_data.get("types", [])
        self.sprite       = api_data.get("sprite", "")
        self.abilities    = api_data.get("abilities", [])
        self.moves        = api_data.get("default_moves", [])   # list of move name strings
        self.base_exp     = api_data.get("base_exp", 50)
        self.flavor_text  = api_data.get("flavor_text", "")
        self.catch_rate   = api_data.get("catch_rate", 45)
        self.growth_rate  = api_data.get("growth_rate", "medium")
        self.evolution_chain_url = api_data.get("evolution_chain_url", "")
        self.is_legendary = api_data.get("is_legendary", False)
        self.is_mythical  = api_data.get("is_mythical", False)

        # Stats with star multiplier applied
        raw_stats         = api_data.get("base_stats", {})
        self.base_stats   = apply_star_stats(raw_stats, self.stars)

        self.max_hp       = self._calc_hp()
        self.hp           = self.max_hp

        # Battle state
        self.status       = None    # "poisoned" | "burned" | "paralyzed" | "asleep" | None
        self.fainted      = False

        # Nickname (optional, set by player)
        self.nickname     = ""

        # Caught timestamp
        self.caught_at    = int(time.time())

    # ── Stat calculation ─────────────────────────────────────

    def _calc_hp(self) -> int:
        """
        Gen 3+ HP formula scaled to our level system.
        HP = floor(((2 * base + iv) * level) / 100) + level + 10
        We simplify: no IVs, star multiplier already in base_stats.
        """
        base = self.base_stats.get("hp", 45)
        return int(((2 * base) * self.level) / 100) + self.level + 10

    def effective_stat(self, stat: str) -> int:
        """Return the effective battle stat at current level."""
        base = self.base_stats.get(stat, 45)
        return int(((2 * base) * self.level) / 100) + 5

    # ── Display ──────────────────────────────────────────────

    def star_display(self) -> str:
        return STAR_LABEL.get(self.stars, "?")

    def prestige(self) -> str:
        return STAR_PRESTIGE.get(self.stars, "")

    def type_display(self) -> str:
        return " / ".join(t.capitalize() for t in self.types)

    def display_name(self) -> str:
        return self.nickname if self.nickname else self.label

    def summary(self) -> str:
        prestige = self.prestige()
        prestige_str = f"  ·  *{prestige}*" if prestige else ""
        return (
            f"*{self.display_name()}*  Lv.{self.level}\n"
            f"{self.star_display()}{prestige_str}\n"
            f"Type: {self.type_display()}\n"
            f"HP: {self.hp}/{self.max_hp}\n"
            f"ATK: {self.effective_stat('attack')}  "
            f"DEF: {self.effective_stat('defense')}  "
            f"SPD: {self.effective_stat('speed')}"
        )

    # ── Battle ───────────────────────────────────────────────

    def take_damage(self, amount: int) -> int:
        actual = min(self.hp, max(0, amount))
        self.hp -= actual
        if self.hp <= 0:
            self.hp = 0
            self.fainted = True
        return actual

    def heal(self, amount: int) -> int:
        if self.fainted:
            return 0
        before = self.hp
        self.hp = min(self.max_hp, self.hp + amount)
        return self.hp - before

    def full_restore(self):
        self.hp = self.max_hp
        self.status = None
        self.fainted = False

    # ── Serialization ────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "name":               self.name,
            "label":              self.label,
            "stars":              self.stars,
            "level":              self.level,
            "xp":                 self.xp,
            "types":              self.types,
            "sprite":             self.sprite,
            "abilities":          self.abilities,
            "moves":              self.moves,
            "base_exp":           self.base_exp,
            "flavor_text":        self.flavor_text,
            "catch_rate":         self.catch_rate,
            "growth_rate":        self.growth_rate,
            "evolution_chain_url": self.evolution_chain_url,
            "is_legendary":       self.is_legendary,
            "is_mythical":        self.is_mythical,
            "base_stats":         self.base_stats,
            "max_hp":             self.max_hp,
            "hp":                 self.hp,
            "status":             self.status,
            "fainted":            self.fainted,
            "nickname":           self.nickname,
            "caught_at":          self.caught_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "OwnedPokemon":
        # Reconstruct without hitting API — all data already stored
        obj = object.__new__(cls)
        obj.name          = d["name"]
        obj.label         = d.get("label", d["name"].capitalize())
        obj.stars         = d.get("stars", 1)
        obj.level         = d.get("level", 5)
        obj.xp            = d.get("xp", 0)
        obj.types         = d.get("types", [])
        obj.sprite        = d.get("sprite", "")
        obj.abilities     = d.get("abilities", [])
        obj.moves         = d.get("moves", [])
        obj.base_exp      = d.get("base_exp", 50)
        obj.flavor_text   = d.get("flavor_text", "")
        obj.catch_rate    = d.get("catch_rate", 45)
        obj.growth_rate   = d.get("growth_rate", "medium")
        obj.evolution_chain_url = d.get("evolution_chain_url", "")
        obj.is_legendary  = d.get("is_legendary", False)
        obj.is_mythical   = d.get("is_mythical", False)
        obj.base_stats    = d.get("base_stats", {})
        obj.max_hp        = d.get("max_hp", 45)
        obj.hp            = d.get("hp", obj.max_hp)
        obj.status        = d.get("status", None)
        obj.fainted       = d.get("fainted", False)
        obj.nickname      = d.get("nickname", "")
        obj.caught_at     = d.get("caught_at", 0)
        return obj


# ─────────────────────────────────────────────────────────────
# WILD ENCOUNTER TABLES
# Per zone — Pokémon name + weight (higher = more common)
# Level range pulled from zone definition
# ─────────────────────────────────────────────────────────────

WILD_ENCOUNTERS = {
    "route_1": [
        ("weedle",     40),
        ("rattata",    35),
        ("caterpie",   15),
        ("pidgey",     10),
        ("spearow",     8),
        ("bellsprout",  5),
        ("mankey",      4),
    ],
    "route_2": [
        ("pidgey",   30),
        ("rattata",  25),
        ("nidoran-m", 20),
        ("nidoran-f", 15),
        ("caterpie",  10),
    ],
    # Expand as zones are added
}

WILD_LEVEL_RANGE = {
    "route_1": (1, 8),
    "route_2": (3, 7),
}


def roll_wild(zone: str) -> tuple[str, int] | None:
    """
    Roll a wild Pokémon for the given zone.
    Returns (pokemon_name, level) or None if zone has no table.
    """
    table = WILD_ENCOUNTERS.get(zone)
    if not table:
        return None

    names   = [n for n, _ in table]
    weights = [w for _, w in table]
    name    = random.choices(names, weights=weights, k=1)[0]

    lo, hi  = WILD_LEVEL_RANGE.get(zone, (2, 5))
    level   = random.randint(lo, hi)

    return name, level


# ─────────────────────────────────────────────────────────────
# STARTER SCREEN HELPER
# Used by npc.py / router.py to display Oak's choice prompt
# ─────────────────────────────────────────────────────────────

def starter_prompt_text() -> str:
    lines = ["*Prof. Oak gestures to five Poké Balls on the table.*\n"]
    for key, s in STARTERS.items():
        lines.append(f"{s['element']} *{s['label']}*  ·  {s['type']}")
        lines.append(f"_{s['lore']}_\n")
    lines.append("Which one calls to you?")
    lines.append("_Reply with the name._")
    return "\n".join(lines)


def starter_given_text(pokemon, nickname: str = None) -> str:
    prestige = pokemon.prestige() if hasattr(pokemon, "prestige") else ""
    prestige_line = f"*{prestige} pull!*\n" if prestige else ""
    display_name = nickname or getattr(pokemon, "nickname", None) or getattr(pokemon, "name", "your Pokémon")
    flavor = getattr(pokemon, "flavor_text", "") or ""
    flavor_line = f"_{flavor}_\n\n" if flavor.strip() else ""
    return (
        f"{prestige_line}"
        f"*{display_name}* was released from the Ball and looked up at you.\n"
        f"{'✧' * 6}\n\n"
        f"{flavor_line}"
        f"📖 You received the *Pokédex*.\n"
        f"🎒 You have *3 Poké Balls*.\n\n"
        f"_Old Man Bram steps aside. Route 1 is open._"
    )
