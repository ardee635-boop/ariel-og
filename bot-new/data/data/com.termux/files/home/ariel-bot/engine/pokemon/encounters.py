# ============================================================
# NIFLHEIM — encounters.py
# Wild encounter system — trigger, battle, catch, rewards
# ============================================================
# NOTE: data tables moved to encounter_tables.py.

"""Pokemon: encounters (split from encounters.py)."""
import random
from encounter_tables import ALL_TYPES, BALL_CATCH_BONUS, BALL_TYPE_AFFINITY, BASE_ENCOUNTER_CHANCE, ENCOUNTER_TABLES, STAR_MULTIPLIER, STATUS_CATCH_BONUS, STEP_INCREMENT


def roll_encounter(grass_steps: int) -> bool:
    """Roll encounter chance based on consecutive grass steps."""
    chance = BASE_ENCOUNTER_CHANCE + (grass_steps * STEP_INCREMENT)
    chance = min(chance, 0.90)  # cap at 90%
    return random.random() < chance

def roll_wild_pokemon(zone: str, tile: str = "grass", player_level: int = None) -> tuple[str, int] | None:
    """
    Roll a wild Pokémon species and level for the given zone and tile type.

    Level distribution (when player_level is provided):
      93% — scaled to player ace level ±2-3, clamped to zone range
       5% — zone minimum level (low-level surprise)
       2% — zone maximum level (high-level threat)
    """
    table = ENCOUNTER_TABLES.get(zone)
    if not table:
        return None
    pool = table.get(tile, table.get("grass", []))
    if not pool:
        return None
    names   = [n for n, _ in pool]
    weights = [w for _, w in pool]
    name    = random.choices(names, weights=weights, k=1)[0]
    lo, hi  = table.get("level_range", [1, 5])

    if player_level is not None:
        roll = random.random()
        if roll < 0.02:
            # 2% — high-level threat
            level = hi
        elif roll < 0.07:
            # 5% — low-level surprise
            level = lo
        else:
            # 93% — scaled to player
            base  = player_level + random.randint(-3, 3)
            level = max(lo, min(hi, base))
    else:
        level = random.randint(lo, hi)

    return name, level

def build_wild_monster(api_data: dict, level: int, db=None) -> dict:
    """Wild monster built directly from PokéAPI data: base stats ->
    level stats (stats.py), level-up learnset moves, PP from PokéAPI.
    Stars are rolled for display only."""
    from data_pokemon import roll_stars
    from stats import compute_stats, moves_for_level, move_entry

    stars = roll_stars()
    base  = dict(api_data.get("base_stats", {}))
    stats = compute_stats(base, level)
    moves = [move_entry(m, db) for m in moves_for_level(api_data, level)]

    return {
        "name":            api_data["name"],
        "level":           level,
        "stars":           stars,
        "types":           api_data.get("types", []),
        "sprite":          api_data.get("sprite", ""),
        "base_stats":      base,
        "stats":           stats,
        "hp":              stats["hp"],
        "max_hp":          stats["hp"],
        "catch_rate":      api_data.get("catch_rate", 45),
        "base_experience": api_data.get("base_experience", api_data.get("base_exp", 50)),
        "status":          None,
        "catch_fail_penalty": 0,
        "moves":           moves,
    }

# ── Encounter HUD ─────────────────────────────────────────────

def _hp_bar(hp, max_hp, width=10):
    filled = int((hp / max_hp) * width) if max_hp > 0 else 0
    return f"{'█' * filled}{'░' * (width - filled)}"

def _pct(hp, max_hp):
    return int((hp / max_hp) * 100) if max_hp > 0 else 0

def encounter_screen(monster: dict) -> str:
    """Initial encounter screen — shown before player chooses fight/flee."""
    name    = monster["name"].capitalize()
    level   = monster["level"]
    types   = "/".join(t.capitalize() for t in monster["types"])
    hp      = monster["hp"]
    max_hp  = monster["max_hp"]
    bar     = _hp_bar(hp, max_hp)
    sprite  = monster.get("sprite", "")
    stars   = monster.get("stars", 1)
    star_s  = "⭐" * min(stars, 5) + ("🌟" * max(0, stars - 5))

    img_line = f"__IMG__{sprite}__CAP__Wild {name}!\n" if sprite else ""
    return (
        f"{img_line}"
        f"A wild *{name}* appeared!\n"
        f"☰ Type: {types}  |  Lv.{level}  {star_s}\n"
        f"₊✙⁺ HP: {hp}/{max_hp} {bar}\n\n"
        f".fight to engage\n"
        f".flee to escape"
    )

def battle_screen(player_pokemon, monster: dict) -> str:
    """Options screen shown between turns."""
    m_hp    = monster["hp"]
    m_max   = monster["max_hp"]
    m_name  = monster["name"].capitalize()
    p_hp    = player_pokemon.hp
    p_max   = player_pokemon.max_hp
    p_name  = player_pokemon.nickname
    m_bar   = _hp_bar(m_hp, m_max)
    p_bar   = _hp_bar(p_hp, p_max)
    # Invisible readmore spacer
    RM = "\u200b" * 700

    return (
        f"*{m_name}'s HP:* {m_hp}/{m_max} ({_pct(m_hp, m_max)}%) {m_bar}\n"
        f"*{p_name}'s HP:* {p_hp}/{p_max} ({_pct(p_hp, p_max)}%) {p_bar}\n"
        f"{RM}\n"
        f"Your options:\n"
        f".skills\n"
        f".catch\n"
        f".heal\n"
        f".use\n"
        f"_State a skill name to attack_"
    )

def skills_screen(pokemon) -> str:
    """Shows the player's Pokémon skill list with PP."""
    lines = [f"⚔️ *{pokemon.nickname}'s Skills*"]
    for m in pokemon.moves:
        name = m["name"].replace("-", " ").title()
        pp   = m["pp"]
        mpp  = m["max_pp"]
        lines.append(f"{name:<20} {pp}/{mpp}")
    return "\n".join(lines)

def victory_screen(monster: dict, player_pokemon, xp_gained: int,
                   coins_gained: int, level_msgs: list, learned: list) -> str:
    """Victory screen after defeating a wild Pokémon."""
    name  = monster["name"].capitalize()
    lines = [
        f"*{player_pokemon.nickname}* gained *{xp_gained} XP*!",
        f"+{coins_gained}₡",
    ]
    lines.extend(level_msgs)
    for move in learned:
        lines.append(f"*{player_pokemon.nickname}* has learned *{move}*!")
    lines.append(f"_Use .party to see {player_pokemon.nickname}'s details_")
    return "\n".join(lines)

# ── Reward calculation ────────────────────────────────────────

def calculate_rewards(monster: dict, player_pokemon) -> tuple[int, int]:
    """Returns (xp, coins)."""
    stars      = monster.get("stars", 1)
    level      = monster["level"]
    base_xp    = monster.get("base_xp", 50)
    multiplier = STAR_MULTIPLIER.get(stars, 1.0)
    xp         = int(base_xp * level * multiplier)
    coins      = int(level * 5 * multiplier)
    return xp, coins

# ── Catch system ─────────────────────────────────────────────

def calculate_catch_rate(monster: dict, ball: str) -> float:
    """
    Total catch rate = base + ball + HP bonus + status bonus - fail penalty
    HP bonus: up to +20% at 1 HP
    Status: capped at +15%
    Fail penalty: -5% per failed throw this encounter
    """
    base        = monster.get("catch_rate", 0.45)  # already normalised 0-1
    ball_bonus  = BALL_CATCH_BONUS.get(ball, 0.10)

    if ball == "Random Ball":
        # Rolls a random type each throw — bonus only applies if the
        # roll happens to match the wild Pokémon's type(s).
        rolled_type = random.choice(ALL_TYPES)
        if rolled_type not in monster.get("types", []):
            ball_bonus = 0.10   # missed the roll, falls back to Poké Ball rate
    else:
        # Type affinity check for elemental balls
        affinity = BALL_TYPE_AFFINITY.get(ball, [])
        if affinity and not any(t in affinity for t in monster.get("types", [])):
            ball_bonus = 0.10   # falls back to Poké Ball rate if wrong type

    # HP bonus — scales 0% (full HP) → 20% (1 HP)
    hp_pct      = monster["hp"] / monster["max_hp"] if monster["max_hp"] > 0 else 1
    hp_bonus    = (1 - hp_pct) * 0.20

    # Status bonus — capped at 15%
    status      = monster.get("status")
    status_bonus = min(STATUS_CATCH_BONUS.get(status, 0), 0.15)

    # Fail penalty
    fail_pen    = monster.get("catch_fail_penalty", 0)

    total = base + ball_bonus + hp_bonus + status_bonus - fail_pen
    return max(0.0, min(1.0, total))

def attempt_catch(monster: dict, ball: str) -> bool:
    """Returns True if catch succeeds."""
    rate = calculate_catch_rate(monster, ball)
    return random.random() < rate
