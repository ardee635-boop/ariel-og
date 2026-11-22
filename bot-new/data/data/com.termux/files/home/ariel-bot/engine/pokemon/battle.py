# ============================================================
# NIFLHEIM — battle.py
# Pokémon-style turn-based wild battle system.
#
# Session state flow:
#   encounter → battle_menu → (after move) → battle_menu
#                                           → victory
#                                           → blackout
#                                           → fled
#
# Called from router/handle.py when session.state == "encounter"
# or "battle_menu".
# ============================================================

import random
import math
from models import OwnedPokemon
import battle_log
from stats import StageStack, STAGE_KEYS, effective
from pokeapi import get_move, type_multiplier

# ── Quest hooks (populated by router/quests.py at runtime) ────
def _quest_on_defeat(player, wild): pass
def _quest_on_catch(player, species: str): pass

def register_quest_hooks(on_defeat, on_catch):
    global _quest_on_defeat, _quest_on_catch
    _quest_on_defeat = on_defeat
    _quest_on_catch  = on_catch

# ── Constants ─────────────────────────────────────────────────
POKEBALL_MODIFIER = 1.0   # standard Pokéball

# ── Status type affinity ──────────────────────────────────────
# Base tick damage per status (% of max HP per turn)
STATUS_BASE_SEVERITY = {
    "burn":      0.05,
    "poison":    0.05,
    "bleed":     0.04,
    "paralysis": 0.00,   # no tick — speed reduction only
    "sleep":     0.00,
    "freeze":    0.00,
}

STATUS_TYPE_AFFINITY = {
    "burn":      ["fire"],
    "freeze":    ["ice"],
    "poison":    ["poison", "steel"],
    "paralysis": ["electric"],
    "bleed":     [],
    "sleep":     [],
}

STATUS_ICONS = {
    "burn": "🔥", "poison": "☠️", "bleed": "🩸",
    "paralysis": "⚡", "sleep": "💤", "freeze": "🧊",
}


def status_tick_damage(target, status: str) -> int:
    """
    Returns HP to deduct from status tick.
    Type affinity reduces severity:
      full match  → severity × 0.60
      partial     → severity × 0.80
      no match    → full severity
    """
    base = STATUS_BASE_SEVERITY.get(status, 0)
    if base == 0:
        return 0
    max_hp = (target.max_hp if isinstance(target, OwnedPokemon)
              else target.get("max_hp", 1))
    affinity_types = STATUS_TYPE_AFFINITY.get(status, [])
    target_types   = (target.types if isinstance(target, OwnedPokemon)
                      else target.get("types", []))
    if affinity_types:
        matches = sum(1 for t in target_types if t in affinity_types)
        if matches >= len(target_types):
            base *= 0.60
        elif matches > 0:
            base *= 0.80
    return max(1, int(max_hp * base))


def apply_status_tick(target, log: list):
    """Apply end-of-turn status tick to target. Appends to log."""
    status = (target.status if isinstance(target, OwnedPokemon)
              else target.get("status"))
    if not status:
        return
    dmg = status_tick_damage(target, status)
    if dmg == 0:
        return
    name = (target.nickname if isinstance(target, OwnedPokemon)
            else target.get("name", "?").capitalize())
    if isinstance(target, OwnedPokemon):
        target.take_damage(dmg)
        remaining = f"{target.hp}/{target.max_hp}"
    else:
        target["hp"] = max(0, target["hp"] - dmg)
        remaining = f"{target['hp']}/{target['max_hp']}"
    icon = STATUS_ICONS.get(status, "💢")
    log.append(f"{icon} *{name}* is hurt by {status}! -{dmg} HP ({remaining})")


# ── Statuses that prevent action (freeze / sleep) ──────────────
# % chance per turn to recover and act normally
STATUS_WAKE_CHANCE = {
    "sleep":  33,
    "freeze": 20,
}

STATUS_PREVENT_MSG = {
    "sleep":  "is fast asleep!",
    "freeze": "is frozen solid!",
}

STATUS_CURE_MSG = {
    "sleep":  "woke up!",
    "freeze": "thawed out!",
}

def _status_prevents_action(target, log: list) -> bool:
    """
    Check freeze/sleep before a combatant acts.
    Rolls the wake/thaw chance — if it succeeds, clears the status and
    the combatant acts normally this turn. If not, appends a message
    and returns True (caller should skip the action, no PP cost).
    """
    status = (target.status if isinstance(target, OwnedPokemon)
              else target.get("status"))
    if status not in STATUS_WAKE_CHANCE:
        return False
    name = (target.nickname if isinstance(target, OwnedPokemon)
            else target.get("name", "?").capitalize())
    icon = STATUS_ICONS.get(status, "💢")
    if random.randint(1, 100) <= STATUS_WAKE_CHANCE[status]:
        if isinstance(target, OwnedPokemon):
            target.status = None
        else:
            target["status"] = None
        log.append(f"{icon} *{name}* {STATUS_CURE_MSG[status]}")
        return False
    log.append(f"{icon} *{name}* {STATUS_PREVENT_MSG[status]}")
    return True


# ── Stat modifier system (Phase 3 cutover — replaces stage dicts) ──
# Old system: -6..+6 "stages" per PokéAPI stat name (attack/defense/
# special-attack/etc), a fixed multiplier table.
# New system: secondary_stats.ModifierStack per combatant, one flat
# or percent Modifier per buff/debuff, keyed on Soulbound stat names
# (STR/INT/DEF/SPD/DEX/WIS/CHA) — NOT the old PokéAPI names. Applied
# in acquisition order (secondary_stats.py §4), not stage-table
# lookup. See design discussion on ModifierStack lifetime: these are
# battle-only (temporary), created fresh per battle_state, discarded
# on battle end — never persisted to the Soulbound itself.

def _init_modifier_stack():
    """Per-battle stat stages (-6..+6) for one combatant."""
    return StageStack()


STAT_STAGE_NAMES = {
    "attack": "Attack", "defense": "Defense",
    "special-attack": "Sp. Atk", "special-defense": "Sp. Def",
    "speed": "Speed", "accuracy": "Accuracy", "evasion": "Evasion",
}


def apply_stat_changes(stack, stat_changes: list, target_name: str, log: list,
                        source: str = "move", duration: int | None = None):
    """Apply PokéAPI stat_changes ({stat, change}) as stage changes (±6 cap)."""
    for sc in stat_changes:
        stat   = sc.get("stat")
        change = sc.get("change", 0)
        if stat not in STAGE_KEYS or change == 0:
            continue
        applied = stack.change(stat, change)
        label = STAT_STAGE_NAMES.get(stat, stat)
        if applied == 0:
            log.append(f"> {target_name}'s {label} won't go {'higher' if change > 0 else 'lower'}!")
            continue
        n = abs(applied)
        if applied > 0:
            arrow = "rose" if n == 1 else "rose sharply" if n == 2 else "rose drastically"
        else:
            arrow = "fell" if n == 1 else "fell sharply" if n == 2 else "fell drastically"
        log.append(f"> {target_name}'s {label} {arrow}!")


# ── Secondary effect map (move type → status) ─────────────────
# Used when move has effect_chance but no stat_changes
_EFFECT_STATUS_MAP = {
    "fire":     "burn",
    "electric": "paralysis",
    "ice":      "freeze",
    "poison":   "poison",
    "grass":    "poison",   # e.g. Poison Powder via grass moves — approx
}

# Effect-text keywords that override the type map — lets grass moves
# like Sleep Powder / Spore inflict sleep instead of the grass default
_EFFECT_TEXT_STATUS = [
    ("sleep", "sleep"),
    ("fall asleep", "sleep"),
]

def apply_secondary_effect(move_data: dict, target, target_name: str, log: list):
    """
    Roll effect_chance and apply status if it hits.
    target: OwnedPokemon or wild dict.
    """
    chance = move_data.get("effect_chance")
    if not chance:
        return
    if random.randint(1, 100) > chance:
        return
    # Already has a status?
    current = (target.status if isinstance(target, OwnedPokemon)
               else target.get("status"))
    if current:
        return
    move_type   = move_data.get("type", "")
    effect_text = (move_data.get("effect") or "").lower()
    status = None
    for keyword, mapped_status in _EFFECT_TEXT_STATUS:
        if keyword in effect_text:
            status = mapped_status
            break
    if not status:
        status = _EFFECT_STATUS_MAP.get(move_type)
    if not status:
        return
    icon = STATUS_ICONS.get(status, "💢")
    if isinstance(target, OwnedPokemon):
        target.status = status
    else:
        target["status"] = status
    log.append(f"> {icon} *{target_name}* was inflicted with {status}!")


# ── Status move fallback map ────────────────────────────────────
# PokéAPI returns empty stat_changes for most status moves.
# This map provides the fallback: move-name → list of {stat, change}
# matching the same format as PokéAPI stat_changes.
MOVE_EFFECT_MAP: dict[str, list[dict]] = {
    # Opponent debuffs
    "leer":          [{"stat": "defense",        "change": -1}],
    "growl":         [{"stat": "attack",         "change": -1}],
    "tail-whip":     [{"stat": "defense",        "change": -1}],
    "string-shot":   [{"stat": "speed",          "change": -1}],
    "smokescreen":   [{"stat": "accuracy",       "change": -1}],
    "sand-attack":   [{"stat": "accuracy",       "change": -1}],
    "scary-face":    [{"stat": "speed",          "change": -2}],
    "charm":         [{"stat": "attack",         "change": -2}],
    "screech":       [{"stat": "defense",        "change": -2}],
    "feather-dance": [{"stat": "attack",         "change": -2}],
    "metal-sound":   [{"stat": "special-defense","change": -2}],
    "fake-tears":    [{"stat": "special-defense","change": -2}],
    "tickle":        [{"stat": "attack",         "change": -1},
                      {"stat": "defense",        "change": -1}],
    # Self buffs
    "swords-dance":  [{"stat": "attack",         "change":  2}],
    "agility":       [{"stat": "speed",          "change":  2}],
    "harden":        [{"stat": "defense",        "change":  1}],
    "withdraw":      [{"stat": "defense",        "change":  1}],
    "defense-curl":  [{"stat": "defense",        "change":  1}],
    "growth":        [{"stat": "attack",         "change":  1},
                      {"stat": "special-attack", "change":  1}],
    "amnesia":       [{"stat": "special-defense","change":  2}],
    "calm-mind":     [{"stat": "special-attack", "change":  1},
                      {"stat": "special-defense","change":  1}],
    "nasty-plot":    [{"stat": "special-attack", "change":  2}],
    "minimize":      [{"stat": "evasion",        "change":  2}],
    "double-team":   [{"stat": "evasion",        "change":  1}],
    "sharpen":       [{"stat": "attack",         "change":  1}],
    "meditate":      [{"stat": "attack",         "change":  1}],
    "barrier":       [{"stat": "defense",        "change":  2}],
    "acid-armor":    [{"stat": "defense",        "change":  2}],
    "iron-defense":  [{"stat": "defense",        "change":  2}],
    "cosmic-power":  [{"stat": "defense",        "change":  1},
                      {"stat": "special-defense","change":  1}],
    "bulk-up":       [{"stat": "attack",         "change":  1},
                      {"stat": "defense",        "change":  1}],
    "dragon-dance":  [{"stat": "attack",         "change":  1},
                      {"stat": "speed",          "change":  1}],
    "quiver-dance":  [{"stat": "special-attack", "change":  1},
                      {"stat": "special-defense","change":  1},
                      {"stat": "speed",          "change":  1}],
    "shell-smash":   [{"stat": "attack",         "change":  2},
                      {"stat": "special-attack", "change":  2},
                      {"stat": "speed",          "change":  2},
                      {"stat": "defense",        "change": -1},
                      {"stat": "special-defense","change": -1}],
    "coil":          [{"stat": "attack",         "change":  1},
                      {"stat": "defense",        "change":  1},
                      {"stat": "accuracy",       "change":  1}],
}

# Self-targeting stat moves (buffs apply to user, debuffs NOT to opponent)
# Already handled by SELF_DEBUFF_MOVES for damaging moves.
# For pure status moves, any move NOT in this set and with negative changes
# targets the opponent; positive changes always target self.
_STATUS_SELF_BUFF_MOVES = {
    "swords-dance", "agility", "harden", "withdraw", "defense-curl",
    "growth", "amnesia", "calm-mind", "nasty-plot", "minimize",
    "double-team", "sharpen", "meditate", "barrier", "acid-armor",
    "iron-defense", "cosmic-power", "bulk-up", "dragon-dance",
    "quiver-dance", "shell-smash", "coil",
}

# ── Flinch moves ────────────────────────────────────────────────
# move-name → flinch chance (%). Only applies if attacker moves first.
FLINCH_MOVES: dict = {
    "bite":           30,
    "headbutt":       30,
    "stomp":          30,
    "rolling-kick":   30,
    "snore":          30,
    "twister":        20,
    "rock-slide":     30,
    "waterfall":      20,
    "zen-headbutt":   20,
    "iron-head":      30,
    "air-slash":      30,
    "dragon-rush":    20,
    "fake-out":      100,
    "extrasensory":   10,
    "needle-arm":     30,
    "astonish":       30,
    "sky-attack":     30,
    "hyper-fang":     10,
    "thunder-fang":   10,
    "ice-fang":       10,
    "fire-fang":      10,
    "rock-smash":     50,
    "icicle-crash":   30,
    "bulldoze":       30,
    "dark-pulse":     20,
    "force-palm":     30,
    "tri-attack":     20,
}

# ── Multi-secondary-effect moves ────────────────────────────────
# Moves with two independent secondary effects (each rolled separately).
# Format: move-name → list of {type, ...}
MULTI_EFFECT_MAP: dict = {
    "fire-fang":    [
        {"type": "status", "status": "burn",      "chance": 10},
        {"type": "flinch",                         "chance": 10},
    ],
    "ice-fang":     [
        {"type": "status", "status": "freeze",    "chance": 10},
        {"type": "flinch",                         "chance": 10},
    ],
    "thunder-fang": [
        {"type": "status", "status": "paralysis", "chance": 10},
        {"type": "flinch",                         "chance": 10},
    ],
    "tri-attack":   [
        {"type": "status", "status": "burn",      "chance":  7},
        {"type": "status", "status": "freeze",    "chance":  7},
        {"type": "status", "status": "paralysis", "chance":  7},
    ],
}

# ── Self-debuff moves ───────────────────────────────────────────
# Moves whose negative stat_changes apply to the USER, not the target
# (PokéAPI lists these the same as opponent-targeted drops, so the
# distinction needs to be hardcoded).
SELF_DEBUFF_MOVES = {
    "close-combat", "superpower", "draco-meteor", "leaf-storm",
    "overheat", "psycho-boost", "v-create", "head-smash",
}


# ── Effectiveness labels ──────────────────────────────────────
_EFF = {
    0.0:  ("🚫", "It has no effect…"),
    0.25: ("💨", "It's not very effective…"),
    0.5:  ("💨", "It's not very effective…"),
    1.0:  ("",   ""),
    2.0:  ("🔥", "It's super effective!"),
    4.0:  ("💥", "It's extremely effective!!"),
}


# ── Damage formula ────────────────────────────────────────────

def _apply_stack_to_primary(stat_name: str, base_value: float, stack) -> float:
    """Stat value after stat stages. stat_name is a PokéAPI stat name."""
    return effective(stat_name, base_value, stack)


_LEGACY_STAT_NAMES = {"STR": "attack", "INT": "special-attack", "DEF": "defense",
                      "SPD": "speed"}


def _get_stats(combatant) -> dict:
    """Level stats (PokéAPI names) for an OwnedPokemon or a wild dict."""
    if isinstance(combatant, OwnedPokemon):
        return combatant.stats
    stats = combatant.get("stats", {})
    if "attack" not in stats and "STR" in stats:     # in-flight pre-update encounter
        stats = {_LEGACY_STAT_NAMES.get(k, k): v for k, v in stats.items()}
        stats["special-defense"] = stats.get("defense", 45)
        combatant["stats"] = stats
    return stats


def calc_damage(attacker, move_data: dict, defender, db,
                attacker_stack=None, defender_stack=None) -> tuple[int, float, bool]:
    """Standard Pokémon damage from PokéAPI stats.
    Returns (damage, type_mult, crit). damage -1 = missed, 0 = no damage
    (status move or immune)."""
    from stats import damage as _damage, roll_crit, accuracy_threshold

    power    = move_data.get("power") or 0
    category = move_data.get("category", "physical")
    if power <= 0 or category == "status":
        return 0, 1.0, False

    move_type = move_data.get("type", "normal")
    special   = category == "special"
    atk_key   = "special-attack" if special else "attack"
    def_key   = "special-defense" if special else "defense"

    atk_stats = _get_stats(attacker)
    def_stats = _get_stats(defender)
    atk = _apply_stack_to_primary(atk_key, atk_stats.get(atk_key, 0), attacker_stack)
    dfn = _apply_stack_to_primary(def_key, def_stats.get(def_key, 0), defender_stack)

    defender_types = (defender.types if isinstance(defender, OwnedPokemon)
                      else defender.get("types", []))
    attacker_types = (attacker.types if isinstance(attacker, OwnedPokemon)
                      else attacker.get("types", []))
    type_mult = type_multiplier(db, move_type, defender_types)
    stab      = 1.5 if move_type in attacker_types else 1.0

    # Accuracy: move accuracy x accuracy/evasion stages
    acc = move_data.get("accuracy") or 100
    threshold = accuracy_threshold(
        acc,
        attacker_stack.stage("accuracy") if attacker_stack else 0,
        defender_stack.stage("evasion") if defender_stack else 0)
    if random.randint(1, 100) > threshold:
        return -1, type_mult, False

    level  = (attacker.level if isinstance(attacker, OwnedPokemon)
              else attacker.get("level", 5))
    status = (attacker.status if isinstance(attacker, OwnedPokemon)
              else attacker.get("status"))
    crit = roll_crit()
    dmg  = _damage(level, power, atk, dfn, stab=stab, type_mult=type_mult,
                   crit=crit, burned_physical=(status == "burn" and not special))
    return dmg, type_mult, (crit and dmg > 0)


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


# ── HP bar ────────────────────────────────────────────────────

def _hp_bar(current, maximum, width=10) -> str:
    if maximum <= 0:
        return "░" * width
    filled = int(round((current / maximum) * width))
    filled = max(0, min(width, filled))
    bar    = "█" * filled + "░" * (width - filled)
    pct    = int((current / maximum) * 100)
    if pct > 50:
        color = "🟩"
    elif pct > 20:
        color = "🟨"
    else:
        color = "🟥"
    return f"{color} {bar} {current}/{maximum}"


# ── Battle HUD (message 2: HP status + moves + commands) ──────

def battle_hud(active: OwnedPokemon, wild: dict) -> str:
    moves_text = ""
    for m in active.moves:
        moves_text += f"  -{m['name'].replace('-',' ')}  ({m['pp']}/{m['max_pp']} PP)\n"
    if not moves_text:
        moves_text = "  _(no moves)_\n"

    return (
        f"*Moves:*\n{moves_text}\n"
        f".heal · .catch · .use · .flee · .switch [name/no]"
    )


def _mon_render_dict(mon, is_wild: bool = False) -> dict:
    """Normalize either an OwnedPokemon or a wild dict into the shape
    battle_render.render() expects."""
    if isinstance(mon, dict):
        return {
            "name":       mon.get("name", "???").capitalize(),
            "level":      mon.get("level", 1),
            "hp":         max(0, mon.get("hp", 0)),
            "max_hp":     mon.get("max_hp", 1) or 1,
            "status":     mon.get("status"),
            "sprite":     mon.get("sprite", ""),
            "types":      mon.get("types", []),
            # Wild/trainer mons don't track XP — omitted so the render
            # skips the XP bar rather than showing a fake empty one.
            "xp":         None,
            "xp_to_next": None,
        }
    return {
        "name":       mon.nickname,
        "level":      mon.level,
        "hp":         max(0, mon.hp),
        "max_hp":     mon.max_hp,
        "status":     mon.status,
        "sprite":     mon.sprite,
        "types":      getattr(mon, "types", []),
        "xp":         getattr(mon, "xp", None),
        "xp_to_next": getattr(mon, "xp_to_next", None),
    }


STAR_GLYPH = "✧"


def _hp_stanza(owner_prefix: str, nickname: str, stars: int, cur: int, mx: int) -> str:
    """One HP block: '{owner_prefix} {nickname} [{stars}✧]\nHP: cur/max'."""
    return f"{owner_prefix} {nickname} [{stars}{STAR_GLYPH}]\nHP: {max(0, cur)}/{mx}"


def _opponent_owner_prefix(label: str) -> str:
    """Turns the existing card corner label ('WILD', a trainer name, an
    opposing player's name for PvP) into the '@owner's'/'Wild' prefix
    used in the HP stanza. Reuses _battle_label's output rather than
    re-deriving opponent identity from scratch."""
    if not label or label.upper() == "WILD":
        return "Wild"
    return f"@{label}'s"


def battle_image_caption(player_name: str, active: OwnedPokemon, wild: dict,
                          label: str = "WILD") -> str:
    """Builds the caption text that goes under the battle card image:
      [Player HP]
      [Enemy HP]
      Read more...
      [Available skills]
      [Available Commands]
    The turn's battle log (what happened) stays in the two separate
    messages sent before the image — it is NOT repeated in the caption.
    player_name: the trainer's own name, for the '@name's <nickname>'
    line. label: same corner-tag value used elsewhere ('WILD' or a
    trainer/opponent name) — reformatted into the opponent's owner
    prefix via _opponent_owner_prefix."""
    player_stanza = _hp_stanza(f"@{player_name}'s", active.nickname,
                                active.stars, active.hp, active.max_hp)

    wild_stars  = wild.get("stars", 1)
    wild_name   = (wild.get("name") or "???").capitalize()
    wild_hp     = max(0, wild.get("hp", 0))
    wild_max_hp = wild.get("max_hp", 1) or 1
    enemy_stanza = _hp_stanza(_opponent_owner_prefix(label), wild_name,
                               wild_stars, wild_hp, wild_max_hp)

    moves_text = ""
    for m in active.moves:
        moves_text += f"  -{m['name'].replace('-',' ')}  ({m['pp']}/{m['max_pp']} PP)\n"
    if not moves_text:
        moves_text = "  _(no moves)_\n"

    return (
        f"{player_stanza}\n\n"
        f"{enemy_stanza}\n\n"
        f"Read more...\n\n"
        f"*Skills:*\n{moves_text}\n"
        f"*Commands:*\n.heal · .catch · .use · .flee · .switch [name/no]"
    )


def battle_image_marker(player_name: str, active: OwnedPokemon, wild: dict,
                         log_lines: list[str] = None,
                         monster_log_lines: list[str] = None,
                         label: str = "WILD",
                         caption: str = None) -> str:
    """Renders the battle card PNG and returns the __IMG__...__CAP__...
    marker string, ready to be used as (or prepended to) a reply.
    player_name: trainer's own name, for the caption's HP stanza.
    label: corner tag on the card — "WILD" for wild encounters, or a
    trainer/gym-leader name for trainer battles (gym.py / arena.py)."""
    import battle_render
    import os, time

    out_dir = os.path.join(__import__("paths").ROOT, ".battle_cards")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"{active.nickname}_{int(time.time()*1000)}.png")

    player_mon = _mon_render_dict(active)
    enemy_mon  = _mon_render_dict(wild, is_wild=True)

    # render() rewrites .png -> .jpg internally (JPEG export) and returns
    # the actual path it saved to — must use that return value, not the
    # original out_path, or the __IMG__ marker points at a .png file that
    # was never written. index.js's fs.readFileSync then always fails,
    # silently falling back to caption-only text with no image, every time.
    real_path = battle_render.render(player_mon, enemy_mon, out_path, label=label)
    caption = caption or battle_image_caption(player_name, active, wild, label=label)
    return f"__IMG__{real_path}__CAP__{caption}"


def switch_card(new_active, wild: dict) -> str:
    """Info card shown when a new Pokémon enters battle."""
    types  = "/".join(t.capitalize() for t in getattr(new_active, "types", []))
    sprite = getattr(new_active, "sprite", "") or ""
    img    = f"__IMG__{sprite}__CAP__Go! {new_active.nickname}!\n" if sprite else ""
    return (
        f"{img}"
        f"Go! *{new_active.nickname}*!\n"
        f"☰ Type: {types}  |  Lv.{new_active.level}\n"
        f"HP: {new_active.hp}/{new_active.max_hp}"
    )


# ── Battle turn result — (action log, monster log, HUD) triple ─

def battle_turn_result(player_name: str, active: OwnedPokemon, wild: dict,
                       log_lines: list[str] = None,
                       monster_log_lines: list[str] = None,
                       faint_msg: str = None,
                       label: str = "WILD") -> tuple:
    """
    Returns:
      3-tuple (action_log, monster_log, hud)              — normal turn
      4-tuple (action_log, monster_log, faint_msg, None)  — faint/swap, no HUD

    hud is now the __IMG__...__CAP__... battle card marker (image
    replaces the old text-only HUD entirely) rather than plain text.
    player_name: trainer's own name, passed through to the caption.
    label: corner tag on the card — defaults to "WILD"; callers in a
    trainer/gym context should pass the trainer's name instead.
    """
    log_text     = "\n".join(log_lines) if log_lines else "..."
    monster_text = "\n".join(monster_log_lines) if monster_log_lines else ""
    if faint_msg is not None:
        return log_text, monster_text, faint_msg, None
    hud = battle_image_marker(player_name, active, wild, log_lines, monster_log_lines, label=label)
    return log_text, monster_text, hud


# ── XP calculation ────────────────────────────────────────────

def distribute_xp(participants: list[tuple[OwnedPokemon, int]],
                  wild: dict, total_out: list = None) -> list[str]:
    """
    participants: list of (OwnedPokemon, damage_dealt)
    Returns list of display strings (level-up notices etc).
    """
    wild_base_xp = wild.get("base_experience", 50) or 50
    wild_level   = wild.get("level", 5)
    total_dmg    = sum(d for _, d in participants if d > 0)
    msgs = []

    for poke, dmg in participants:
        if poke.is_fainted() or dmg <= 0:
            continue
        share   = dmg / total_dmg if total_dmg > 0 else 1.0 / len(participants)
        xp_gain = max(1, int(wild_base_xp * wild_level * share / 5))
        level_msgs = poke.gain_xp(xp_gain)
        if total_out is not None:
            total_out[0] += xp_gain
        else:
            msgs.append(f"  {poke.nickname} gained *{xp_gain} XP*!")
        msgs.extend(level_msgs)

    return msgs


# ── Catch formula ─────────────────────────────────────────────

def attempt_catch(wild: dict, ball_multiplier: float = POKEBALL_MODIFIER) -> tuple[bool, int]:
    """
    Returns (caught, shake_count 0-3).
    Standard Pokéball formula.
    """
    max_hp  = wild.get("max_hp", 1) or 1
    hp      = max(1, wild.get("hp", 1))
    rate    = wild.get("catch_rate", 45) or 45

    a = ((3 * max_hp - 2 * hp) * rate * ball_multiplier) / (3 * max_hp)
    a = max(1, min(255, a))
    b = int(65536 / ((255 / a) ** 0.1875))

    shakes = 0
    for _ in range(4):
        if random.randint(0, 65535) < b:
            shakes += 1
        else:
            break

    caught = shakes == 4
    return caught, shakes


# ── Wild move picker ──────────────────────────────────────────

def wild_pick_move(wild: dict, db=None, defender_types: list | None = None) -> dict | None:
    """
    Picks a move for any AI-controlled side (wild, trainer, Ariel).
    Weighted rather than pure-random: damaging moves are favored over
    status moves, and among damaging moves, ones that are actually
    effective against the current target are favored further. Status
    moves still have a real (lower) chance to come up — real trainers
    do use buffs/debuffs — this just stops AI from stalling on them
    as often as attacking.
    """
    moves = wild.get("moves", [])
    if not moves:
        return None
    available = [m for m in moves if m.get("pp", 1) > 0]
    if not available:
        return None
    if len(available) == 1:
        return available[0]

    if not db:
        return random.choice(available)

    weights = []
    for m in available:
        move_data = get_move(db, m["name"])
        if not move_data:
            weights.append(1.0)
            continue
        category = move_data.get("category", "physical")
        if category == "status":
            weights.append(1.0)
            continue

        weight = 3.0  # base weight for any damaging move over status
        if defender_types:
            mult = type_multiplier(db, move_data.get("type", "normal"), defender_types)
            if mult >= 2.0:
                weight = 6.0
            elif mult <= 0.5:
                weight = 1.5  # still possible, just deprioritized
        weights.append(weight)

    return random.choices(available, weights=weights, k=1)[0]


# ── Star reveal ───────────────────────────────────────────────

def star_reveal_screen(owned: OwnedPokemon) -> str:
    from data_pokemon import STAR_LABEL, STAR_PRESTIGE
    label    = STAR_LABEL.get(owned.stars, "★")
    prestige = STAR_PRESTIGE.get(owned.stars, "")
    pline    = f"\n✨ *{prestige}*" if prestige else ""
    types    = "/".join(t.capitalize() for t in owned.types)

    return (
        f"__IMG__{owned.sprite}__CAP__Gotcha! {owned.nickname} was caught!\n"
        f"╭━━❰ 🌟 CAUGHT! ❱━━╮\n"
        f"┃ *{owned.nickname}*  Lv.{owned.level}\n"
        f"┃ Type: {types}\n"
        f"┃ {label}{pline}\n"
        f"┃\n"
        f"┃ HP: {owned.hp}/{owned.max_hp}\n"
        f"╰━━━━━━━━━━━━━━━━━━━╯\n"
        f"_Added to your party!_"
    )


# ── resolve_turn — shared PvE + PvP attack resolver ──────────
#
# Both BattleEngine (_player_attacks / _wild_attacks) and
# PvPSession.do_turn call this.  Neither caller needs to know
# the damage formula — they only decide what to do with the result.
#
# Parameters
# ----------
# attacker      : OwnedPokemon or wild dict
# defender      : OwnedPokemon or wild dict
# move_obj      : {"name", "pp", "max_pp"} from the attacker's moves list
#                 pp is decremented here
# attacker_stack: secondary_stats.ModifierStack for attacker (buffs/debuffs)
# defender_stack: secondary_stats.ModifierStack for defender (buffs/debuffs)
# db            : database handle (for get_move / type_multiplier)
# log           : list[str] — lines appended in-place
# moved_first   : bool — whether attacker is faster (for flinch eligibility)
# flinch_flag   : callable(bool) — called with True if defender flinches
#                 (caller stores the flinch flag however it likes)
#
# Returns
# -------
# "status"   — status move, no damage
# "missed"   — accuracy roll failed
# "hit"      — damage dealt, defender still alive
# "fainted"  — defender HP reached 0

def resolve_turn(
    attacker, defender,
    move_obj: dict,
    attacker_stack, defender_stack,
    db,
    log: list,
    moved_first: bool = True,
    flinch_flag=None,       # callable(True) or None
) -> str:
    move_obj["pp"] = max(0, move_obj["pp"] - 1)
    move_display   = move_obj["name"].replace("-", " ").title()

    # ── Status prevents action ────────────────────────────────
    if _status_prevents_action(attacker, log):
        return "status_blocked"

    # Attacker / defender display names
    def _disp(c):
        if isinstance(c, OwnedPokemon):
            return c.nickname
        n = c["name"].capitalize()
        return n if c.get("trainer_owned") else f"Wild {n}"
    atk_name = _disp(attacker)
    def_name = _disp(defender)

    # Fetch move data
    move_data = get_move(db, move_obj["name"]) if db else None
    if not move_data:
        move_data = {
            "name":     move_obj["name"],
            "type":     "normal",
            "category": "physical",
            "power":    40,
            "accuracy": 100,
        }

    category = move_data.get("category", "physical")
    move_key = move_obj["name"].lower()

    # ── Status moves ──────────────────────────────────────────
    if category == "status":
        log.append(f"{atk_name} used {move_display}!")
        stat_changes = move_data.get("stat_changes", []) or MOVE_EFFECT_MAP.get(move_key, [])
        if stat_changes:
            is_self_buff = move_key in _STATUS_SELF_BUFF_MOVES
            for sc in stat_changes:
                change = sc.get("change", 0)
                if change < 0 and not is_self_buff:
                    apply_stat_changes(defender_stack, [sc], def_name, log, source=f"{move_key}:debuff")
                else:
                    apply_stat_changes(attacker_stack, [sc], atk_name, log, source=f"{move_key}:buff")
        else:
            log.append("> But nothing happened!")
        return "status"

    # ── Damage calc ───────────────────────────────────────────
    raw_dmg, type_mult, was_crit = calc_damage(
        attacker, move_data, defender, db,
        attacker_stack=attacker_stack, defender_stack=defender_stack,
    )

    if raw_dmg == -1:
        log.extend(battle_log.action_block(atk_name, move_display, missed=True))
        return "missed"

    dmg = raw_dmg

    # Apply damage
    if isinstance(defender, OwnedPokemon):
        defender.take_damage(dmg)
    else:
        defender["hp"] = max(0, defender["hp"] - dmg)

    log.extend(battle_log.action_block(atk_name, move_display, dmg=dmg, eff=type_mult, crit=was_crit))

    # ── Secondary effects ─────────────────────────────────────
    if move_key in MULTI_EFFECT_MAP:
        current_status = (defender.status if isinstance(defender, OwnedPokemon)
                          else defender.get("status"))
        for eff in MULTI_EFFECT_MAP[move_key]:
            if random.randint(1, 100) > eff["chance"]:
                continue
            if eff["type"] == "flinch" and moved_first:
                if flinch_flag:
                    flinch_flag(True)
                log.append(f"> *{def_name}* flinched!")
            elif eff["type"] == "status" and not current_status:
                icon = STATUS_ICONS.get(eff["status"], "💢")
                if isinstance(defender, OwnedPokemon):
                    defender.status = eff["status"]
                else:
                    defender["status"] = eff["status"]
                current_status = eff["status"]
                log.append(f"> {icon} *{def_name}* was inflicted with {eff['status']}!")
    else:
        apply_secondary_effect(move_data, defender, def_name, log)
        if moved_first and move_key in FLINCH_MOVES:
            if random.randint(1, 100) <= FLINCH_MOVES[move_key]:
                if flinch_flag:
                    flinch_flag(True)
                log.append(f"> *{def_name}* flinched!")

    # Stat changes on hit
    effect_chance = move_data.get("effect_chance")
    stat_changes  = move_data.get("stat_changes", [])
    if stat_changes:
        if not effect_chance or random.randint(1, 100) <= effect_chance:
            for sc in stat_changes:
                if sc.get("change", 0) < 0:
                    if move_key in SELF_DEBUFF_MOVES:
                        apply_stat_changes(attacker_stack, [sc], atk_name, log, source=f"{move_key}:selfdebuff")
                    else:
                        apply_stat_changes(defender_stack, [sc], def_name, log, source=f"{move_key}:debuff")

    # ── Faint check ───────────────────────────────────────────
    def_hp = (defender.hp if isinstance(defender, OwnedPokemon)
              else defender.get("hp", 1))
    if def_hp <= 0:
        if not isinstance(defender, OwnedPokemon):
            defender["hp"] = 0
        log.append(f"{def_name} fainted!")
        return "fainted"

    return "hit"


# ── BattleEngine — the main class ─────────────────────────────

class BattleEngine:
    """
    Stateless helper — takes session + player + db, returns reply string.
    All state lives in session.battle_state dict.
    """

    def __init__(self, db, sender: str = ""):
        self.db     = db
        self.sender = sender

    @staticmethod
    def _battle_label(session, wild: dict) -> str:
        """Corner tag for the battle card: trainer name for gym/arena
        battles, 'WILD' otherwise."""
        ctx = getattr(session, "battle_context", None)
        if ctx in ("trainer", "gym"):
            name = getattr(session, "arena_trainer_name", None)
            if name:
                return name
        return "WILD"

    @staticmethod
    def _is_wild(session, wild: dict) -> bool:
        """True for plain wild encounters (not arena/gym/dungeon-trainer)."""
        return (getattr(session, "battle_context", None) not in ("trainer", "gym")
                and not wild.get("trainer_owned"))

    @staticmethod
    def _pve_rows(active, wild):
        return battle_log.pve_hp_rows(
            active.nickname, active.hp, active.max_hp,
            wild["name"].capitalize(), wild.get("hp", 0), wild.get("max_hp", 1) or 1)

    def _pve_frame(self, active, wild, blocks, commands=True, tail=()):
        # a trailing "X fainted!" line is its own paragraph in the note
        split = []
        for b in blocks:
            if b and b[-1].endswith(" fainted!") and len(b) > 1:
                split += [b[:-1], [b[-1]]]
            elif b:
                split.append(b)
        return battle_log.log_frame(
            battle_log.join_blocks(split),
            self._pve_rows(active, wild),
            battle_log.PVE_COMMANDS if commands else None,
            list(tail), blank_between_hp=True)

    # ── Public entry points ───────────────────────────────────

    def on_encounter(self, session, player) -> str:
        """Called when encounter is set. Initialises battle state."""
        wild = session.encounter_monster
        if not wild:
            return "_Nothing appeared._"

        active = player.active_pokemon()
        if not active:
            return "_You have no Pokémon to battle with!_"

        session.battle_state = {
            "wild":         wild,
            "participants": {},   # {nickname: damage_dealt}
            "turn":         1,
            "player_stack": _init_modifier_stack(),
            "wild_stack":   _init_modifier_stack(),
        }
        # Register active Pokémon
        session.battle_state["participants"][active.nickname] = 0
        session.state = "battle_menu"

        if self._is_wild(session, wild):
            cap = battle_log.pve_start_caption(self._pve_rows(active, wild))
            return battle_image_marker(player.name, active, wild, label="WILD", caption=cap)

        return battle_turn_result(player.name, active, wild,
                             [f"A wild *{wild['name'].capitalize()}* appeared!",
                              f"Go! *{active.nickname}*!"],
                             monster_log_lines=None)


    @staticmethod
    def _normalize_phrase(text: str) -> str:
        """Replace dashes with spaces, strip other symbols, lowercase, collapse spaces."""
        import re
        stripped = re.sub(r"[^a-zA-Z0-9 ]", " ", text).lower().strip()
        return " ".join(stripped.split())

    def _resolve_skill(self, player, active, raw_input: str) -> str:
        """
        Match raw_input to a move via substring search.
        1. Move name — appears anywhere in input (dash-insensitive)
        2. Skill nicknames — phrase appears anywhere in input
        3. Legacy flat dict fallback
        """
        norm_input = self._normalize_phrase(raw_input)
        poke_key   = f"{active.name}_{active.nickname.lower()}"

        # 1. Move name substring match
        for m in active.moves:
            norm_move = self._normalize_phrase(m["name"])
            if norm_move and norm_move in norm_input:
                return m["name"]

        # 2. Per-poke skill nicknames — substring match
        db      = player.get_flag("skill_nicknames", {})
        poke_db = db.get(poke_key, {})
        for skill_name, phrases in poke_db.items():
            for phrase in phrases:
                norm_phrase = self._normalize_phrase(phrase)
                if norm_phrase and norm_phrase in norm_input:
                    return skill_name

        # 3. Legacy flat dict fallback
        legacy = {k: v for k, v in db.items() if isinstance(v, str)}
        for k, v in legacy.items():
            if k in norm_input:
                return v

        return None

        # No match — caller handles rejection
        return None

    def on_command(self, session, player, cmd, args) -> str:
        """Route a battle command. Returns reply string."""
        if session.state not in ("battle_menu", "encounter"):
            return None

        bs   = getattr(session, "battle_state", None)
        wild = session.encounter_monster or getattr(session, "monster", None)
        if not bs or not wild:
            session.state = "exploring"
            return "_No active battle._"

        active = player.active_pokemon()
        if not active or active.is_fainted():
            # Auto-switch to next available
            idx = player.first_conscious()
            if idx is None:
                return self._blackout(session, player)
            player.set_active(idx)
            active = player.active_pokemon()

        # Route commands
        if cmd == ".flee":
            return self._flee(session, player, bs, wild)

        if cmd == ".catch":
            return self._catch(session, player, bs, wild, args)

        if cmd == ".switch":
            return self._switch(session, player, bs, wild, args)

        if cmd == ".heal":
            return self._heal(session, player, bs, wild, active, args)

        # Resolve skill nickname → move name
        # Full input (cmd + args) so multi-word phrases work
        full_input = (cmd.lstrip(".") + (" " + " ".join(args) if args else "")).strip()
        move_name = self._resolve_skill(player, active, full_input)
        if move_name is None:
            return None
        return self._use_move(session, player, bs, wild, active, move_name)

    # ── Move ──────────────────────────────────────────────────

    def _use_move(self, session, player, bs, wild, active, move_name) -> str:
        # Find matching move on active Pokémon
        move_obj = next(
            (m for m in active.moves
             if m["name"].lower().replace("-", "") == move_name.replace("-", "")),
            None
        )
        if not move_obj:
            available = ", ".join(f"-{m['name']}" for m in active.moves)
            return f"❓ Unknown move. Your moves: {available}"

        if move_obj["pp"] <= 0:
            return f"❌ *{move_obj['name']}* has no PP left!"

        player_log  = []
        monster_log = []
        bs["turn"] += 1

        # Fetch move data from API/cache
        move_data = get_move(self.db, move_obj["name"])
        if not move_data:
            move_data = {
                "name":     move_obj["name"],
                "type":     "normal",
                "category": "physical",
                "power":    40,
                "accuracy": 100,
                "pp":       move_obj["pp"],
            }

        # Priority + speed check — who goes first?
        move_priority = move_data.get("priority", 0)
        p_stack       = bs.get("player_stack") or _init_modifier_stack()
        w_stack       = bs.get("wild_stack") or _init_modifier_stack()

        # Paralysis applies a flat -50% speed penalty (was -2 stages,
        # i.e. 0.5x, under the old system — same net effect, applied
        # as a temporary modifier now instead of a stage adjustment).
        PARALYSIS_SPEED_MULT = 0.5

        active_stats = _get_stats(active)
        p_spd = _apply_stack_to_primary("speed", active_stats.get("speed", 0), p_stack)
        if active.status == "paralysis":
            p_spd *= PARALYSIS_SPEED_MULT
        active_spd = int(p_spd)

        w_spd = _apply_stack_to_primary("speed", _get_stats(wild).get("speed", 0), w_stack)
        if wild.get("status") == "paralysis":
            w_spd *= PARALYSIS_SPEED_MULT
        wild_spd = int(w_spd)

        # Wild always uses priority 0 (no move data lookup for wild)
        if move_priority > 0:
            player_first = True   # e.g. Quick Attack always goes first
        elif move_priority < 0:
            player_first = False  # e.g. Counter always goes last
        else:
            player_first = active_spd >= wild_spd  # tie goes to player

        bs["_player_moved_first"] = player_first
        bs["wild_flinched"] = False

        if player_first:
            result = self._player_attacks(active, move_obj, move_data, wild, bs, player_log)
            if result == "fainted":
                return self._victory(session, player, bs, wild, player_log)
            if not active.is_fainted() and not bs.get("wild_flinched"):
                # Trainer switch check (only on trainer's turn, after player moves first)
                switch_msg = None
                if self._trainer_should_switch(session, player, wild, bs, move_data):
                    switch_msg = self._trainer_do_switch(session, player, bs, wild, monster_log)
                    wild = session.monster  # update local ref
                if switch_msg:
                    monster_log.append(switch_msg)
                else:
                    self._wild_attacks(wild, active, bs, monster_log)
            elif bs.get("wild_flinched"):
                pass  # wild skips — flinch message already in player_log
        else:
            # Trainer switch check (trainer moves first — switch instead of attack)
            switch_msg = None
            if self._trainer_should_switch(session, player, wild, bs, move_data):
                switch_msg = self._trainer_do_switch(session, player, bs, wild, monster_log)
                wild = session.monster  # update local ref
            if switch_msg:
                monster_log.append(switch_msg)
            else:
                self._wild_attacks(wild, active, bs, monster_log)
            if active.is_fainted():
                idx = player.first_conscious()
                if idx is None:
                    return self._blackout(session, player, wild=wild, blocks=[player_log, monster_log])
                player.set_active(idx)
                new_active = player.active_pokemon()
                label = self._battle_label(session, wild)
                faint_hud = battle_image_marker(player.name, new_active, wild, label=label)
                faint_msg = f"*{active.nickname}* fainted!\nGo! *{new_active.nickname}*!\n\n{faint_hud}"
                return battle_turn_result(player.name, new_active, wild, monster_log, [], faint_msg, label=label)
            result = self._player_attacks(active, move_obj, move_data, wild, bs, player_log)
            if result == "fainted":
                return self._victory(session, player, bs, wild, player_log)

        # Check active fainted after wild attack
        if active.is_fainted():
            idx = player.first_conscious()
            if idx is None:
                return self._blackout(session, player, wild=wild, blocks=[player_log, monster_log])
            player.set_active(idx)
            new_active = player.active_pokemon()
            label = self._battle_label(session, wild)
            faint_hud = battle_image_marker(player.name, new_active, wild, label=label)
            faint_msg = f"*{active.nickname}* fainted!\nGo! *{new_active.nickname}*!\n\n{faint_hud}"
            return battle_turn_result(player.name, new_active, wild, player_log, monster_log, faint_msg, label=label)

        # Wild fled check
        if bs.get("wild_fled"):
            session.clear_encounter()
            session.transition("exploring")
            from router.explore import resume_journey_if_paused
            resume_suffix = resume_journey_if_paused(self.sender, player, self.db)
            log_text, monster_text, hud = battle_turn_result(
                player.name, active, wild, player_log, monster_log,
                label=self._battle_label(session, wild)
            )
            if resume_suffix:
                log_text += resume_suffix
            return log_text, monster_text, hud

        # End-of-turn status ticks (append to monster_log as post-turn events)
        apply_status_tick(wild, monster_log)
        if wild["hp"] <= 0:
            wild["hp"] = 0
            return self._victory(session, player, bs, wild, player_log)
        apply_status_tick(active, monster_log)
        if active.is_fainted():
            idx = player.first_conscious()
            if idx is None:
                return self._blackout(session, player, wild=wild, blocks=[player_log, monster_log])
            player.set_active(idx)
            new_active = player.active_pokemon()
            label = self._battle_label(session, wild)
            faint_hud = battle_image_marker(player.name, new_active, wild, label=label)
            faint_msg = f"*{active.nickname}* fainted from status!\nGo! *{new_active.nickname}*!\n\n{faint_hud}"
            return battle_turn_result(player.name, new_active, wild, player_log, monster_log, faint_msg, label=label)

        if self._is_wild(session, wild):
            return self._pve_frame(active, wild, [player_log, monster_log])
        return battle_turn_result(player.name, active, wild, player_log, monster_log, label=self._battle_label(session, wild))

    def _player_attacks(self, active, move_obj, move_data, wild, bs, log) -> str | None:
        p_stack = bs.get("player_stack") or _init_modifier_stack()
        w_stack = bs.get("wild_stack") or _init_modifier_stack()
        moved_first = bs.get("_player_moved_first", True)

        def _set_flinch(_):
            bs["wild_flinched"] = True

        result = resolve_turn(
            active, wild, move_obj,
            attacker_stack=p_stack, defender_stack=w_stack,
            db=self.db, log=log,
            moved_first=moved_first,
            flinch_flag=_set_flinch,
        )

        if result == "status_blocked":
            return None
        if result in ("status", "missed"):
            return None
        if result == "hit":
            # Track damage for XP distribution
            bs["participants"][active.nickname] = (
                bs["participants"].get(active.nickname, 0) + 1
            )
            return None
        if result == "fainted":
            bs["participants"][active.nickname] = (
                bs["participants"].get(active.nickname, 0) + 1
            )
            return "fainted"
        return None

    def _trainer_should_switch(self, session, player, wild, bs, move_data=None) -> bool:
        """
        Decide if the trainer should switch this turn instead of attacking.
        Only applies to trainer battles (arena, gym, Ariel).
        Checks type disadvantage or low HP. Cooldown of 3 turns between switches.
        """
        if not wild.get("trainer_owned"):
            return False
        is_trainer_battle = session.battle_context in ("trainer", "gym")
        if not is_trainer_battle:
            return False

        # Need at least one other living mon to switch to
        team = getattr(session, "arena_trainer_team", [])
        current_idx = getattr(session, "arena_trainer_index", 0)
        has_bench = any(
            m.get("hp", 0) > 0 and i != current_idx
            for i, m in enumerate(team)
        )
        if not has_bench:
            return False

        # Switch cooldown — don't swap again within 3 turns
        last_switch_turn = bs.get("trainer_last_switch_turn", -999)
        if bs["turn"] - last_switch_turn < 3:
            return False

        # Determine switch probability based on context
        if session.battle_context == "gym":
            switch_rate = 0.70
        else:
            switch_rate = 0.50

        # Whimsical switch — a small independent chance to swap for no
        # tactical reason at all, just personality. Checked before the
        # trigger conditions below, so it can fire even on a favorable
        # matchup / full HP.
        if session.battle_context == "gym":
            whim_rate = 0.06
        else:
            whim_rate = 0.03

        if random.random() < whim_rate:
            bs["trainer_switch_whimsical"] = True
            return True
        bs["trainer_switch_whimsical"] = False

        # Trigger conditions
        active = player.active_pokemon()
        wild_types = wild.get("types", ["normal"])
        player_types = getattr(active, "types", ["normal"])

        from pokeapi import type_multiplier

        if move_data and move_data.get("category") != "status":
            # Real move in hand — judge actual effectiveness of what the
            # player just used, not a guess from typing alone.
            move_type = move_data.get("type", "normal")
            effectiveness = type_multiplier(self.db, move_type, wild_types)
        else:
            # No usable move data (e.g. status move, or called before a
            # move is known) — fall back to the player's best-case typing,
            # checking both types rather than only the first.
            effectiveness = max(
                (type_multiplier(self.db, t, wild_types) for t in player_types),
                default=1.0,
            )

        hp_pct = wild["hp"] / wild.get("max_hp", wild["hp"]) if wild.get("max_hp") else 1.0

        should = False
        if effectiveness >= 2.0:   # taking super effective
            should = True
        elif hp_pct < 0.30:        # below 30% HP
            should = True

        if not should:
            return False

        return random.random() < switch_rate

    def _trainer_do_switch(self, session, player, bs, wild, log) -> str | None:
        """
        Swap trainer's current mon for the best available bench mon.
        Best = highest type advantage against the player's current active.
        Returns a switch message string, or None if no switch happened.
        Updates session.monster, session.encounter_monster, bs["wild"].
        """
        from pokeapi import type_multiplier

        team = getattr(session, "arena_trainer_team", [])
        current_idx = getattr(session, "arena_trainer_index", 0)
        active = player.active_pokemon()
        player_types = getattr(active, "types", ["normal"])
        p_type = player_types[0] if player_types else "normal"

        # Score each bench mon by type advantage against player
        living_bench = [
            i for i, mon in enumerate(team)
            if i != current_idx and mon.get("hp", 0) > 0
        ]

        # Whimsical switches occasionally skip the counter-pick entirely
        # and just grab someone at random — sells "felt like it" instead
        # of always looking calculated. Tactical switches always stay
        # optimal.
        if bs.get("trainer_switch_whimsical") and living_bench and random.random() < 0.10:
            best_idx = random.choice(living_bench)
        else:
            best_idx  = None
            best_score = -1.0
            for i in living_bench:
                mon = team[i]
                mon_types = mon.get("types", ["normal"])
                # How effective is the trainer mon's type against the player?
                score = type_multiplier(self.db, mon_types[0], player_types)
                if score > best_score:
                    best_score = score
                    best_idx   = i

        if best_idx is None:
            return None

        old_mon  = wild
        new_mon  = team[best_idx]
        session.arena_trainer_index = best_idx
        session.monster             = new_mon
        session.encounter_monster   = new_mon
        bs["wild"]                  = new_mon
        bs["wild_stack"]             = _init_modifier_stack()
        bs["trainer_last_switch_turn"] = bs["turn"]

        trainer_name = getattr(session, "arena_trainer_name", "Trainer")
        old_name = (old_mon.get("nickname") or old_mon.get("name", "???")).capitalize()
        new_name = (new_mon.get("nickname") or new_mon.get("name", "???")).capitalize()
        new_lvl  = new_mon.get("level", "?")

        return (
            f"*{trainer_name}* calls back *{old_name}*!\n"
            f"*{trainer_name}* sends out *{new_name}* (Lv{new_lvl})!"
        )

    def _wild_attacks(self, wild, active: OwnedPokemon, bs, log):
        if bs.get("wild_flinched"):
            return  # already handled in _use_move
        if _status_prevents_action(wild, log):
            return

        wild_name  = wild["name"].capitalize()
        max_hp     = wild.get("max_hp") or wild.get("hp", 1)
        cur_hp     = wild.get("hp", 0)
        hp_pct     = cur_hp / max_hp if max_hp else 1.0

        # ── Flee (HP < 10%, desperation scales with how low + stars) ──
        if hp_pct < 0.10:
            # Base 5% at just-under-10% HP, scaling up to 25% as HP nears 0.
            # (hp_pct 0.10 -> ~5%, hp_pct 0.0 -> ~25%, before stars)
            desperation = (0.10 - hp_pct) / 0.10  # 0.0 -> 1.0 as HP drops to 0
            base_chance = 5 + (desperation * 20)
            stars       = wild.get("stars", 1)
            flee_chance = base_chance + (stars * 2)
            if random.uniform(0, 100) <= flee_chance:
                log.append(f"Wild *{wild_name}* fled!")
                bs["wild_fled"] = True
                return

        # ── Rage (HP drops below 30%) ─────────────────────────
        # Old system: +1 Attack stage (capped at +6), reapplied/topped-
        # up each turn via the stage dict's own ceiling. New system:
        # ModifierStack has no stage ceiling concept, so rage is one
        # percent modifier applied ONCE (source="rage", so a second
        # trigger doesn't stack a duplicate — remove_by_source then
        # re-add keeps it idempotent per rage-intensity level below).
        w_stack = bs.get("wild_stack") or _init_modifier_stack()
        if hp_pct < 0.30 and not bs.get("wild_raging"):
            if random.randint(1, 100) <= 20:
                bs["wild_raging"] = True
                bs["wild_rage_stacks"] = 1
                w_stack.change("attack", 1)
                log.append(f"Wild *{wild_name}* is in a rage! Its Attack rose!")
        elif bs.get("wild_raging"):
            # Keep boosting each turn while raging, up to a cap
            # (old system capped at +6 stages = 4x; mirrored here as
            # a cap on how many times rage can re-intensify)
            stacks = bs.get("wild_rage_stacks", 1)
            if stacks < 6:
                stacks += 1
                bs["wild_rage_stacks"] = stacks
                w_stack.change("attack", 1)
                log.append(f"Wild *{wild_name}*'s rage grows! Attack rose!")

        # ── Struggle (all PP depleted) ────────────────────────
        wild_move = wild_pick_move(wild, db=self.db, defender_types=active.types)
        if not wild_move:
            # Struggle — typeless, power 50, 25% recoil
            p_stack  = bs.get("player_stack") or _init_modifier_stack()
            w_stack  = bs.get("wild_stack") or _init_modifier_stack()
            struggle_data = {
                "name": "struggle", "type": "typeless",
                "category": "physical", "power": 50, "accuracy": 100,
            }
            raw_dmg, _, _ = calc_damage(
                wild, struggle_data, active, self.db,
                attacker_stack=w_stack, defender_stack=p_stack,
            )
            if raw_dmg > 0:
                recoil = max(1, raw_dmg // 4)
                active.take_damage(raw_dmg)
                wild["hp"] = max(0, wild["hp"] - recoil)
                log.append(f"Wild *{wild_name}* used *Struggle*!")
                log.append(f"> Dealt *{raw_dmg} dmg* to *{active.nickname}*")
                log.append(f"> *{wild_name}* took *{recoil} recoil dmg*!")
            return

        p_stack = bs.get("player_stack") or _init_modifier_stack()
        w_stack = bs.get("wild_stack") or _init_modifier_stack()

        resolve_turn(
            wild, active, wild_move,
            attacker_stack=w_stack, defender_stack=p_stack,
            db=self.db, log=log,
            moved_first=not bs.get("_player_moved_first", True),
            flinch_flag=None,  # wild can't flinch the player
        )

    # ── Victory ───────────────────────────────────────────────

    # ── Wild item drops ───────────────────────────────────────

    def _victory(self, session, player, bs, wild, log) -> tuple:
        """
        Returns a tuple routed through _split_battle_result:
          Wild:    2-tuple (move_log, victory_msg)
          Trainer next mon:  3-tuple (move_log, intro_msg, hud)
          Trainer round won: 2-tuple (move_log, round_msg)
        """
        wild_name = wild["name"].capitalize()

        session.clear_encounter()
        session.battle_state = None

        # ── Arena / Gym trainer battle ──────────────────────────
        is_arena = session.battle_context == "trainer"
        is_gym   = session.battle_context == "gym"
        if (is_arena or is_gym) and wild.get("trainer_owned"):
            # XP for trainer mons — still reward, just don't show coins line
            participants = []
            for poke in player.party:
                dmg = bs["participants"].get(poke.nickname, 0)
                if dmg > 0 or poke.nickname in bs["participants"]:
                    participants.append((poke, dmg))
            xp_msgs = distribute_xp(participants, wild)

            player.rank_kills = getattr(player, "rank_kills", 0) + 1
            player.pve_wins   = getattr(player, "pve_wins", 0) + 1
            try:
                _quest_on_defeat(player, wild)
            except Exception:
                pass

            next_mon = session.arena_next_trainer_mon()
            if next_mon:
                # Still more trainer mons — rebuild battle and show HUD
                trainer  = session.arena_trainer_name
                mon_name = next_mon["name"].capitalize()
                mon_lvl  = next_mon["level"]
                from arena import arena_dots
                dots = arena_dots(player.party, session.arena_trainer_team, trainer)
                session.battle_state = {
                    "wild":          next_mon,
                    "participants":  {},
                    "turn":          1,
                    "player_stack":  _init_modifier_stack(),
                    "wild_stack":    _init_modifier_stack(),
                }
                session.state = "battle_menu"
                active = player.active_pokemon()
                sprite = next_mon.get("sprite", "") or ""
                img    = f"__IMG__{sprite}__CAP__{trainer} sends out {mon_name}!\n" if sprite else ""
                # move_log: attack line + faint + XP
                faint_line   = f"*{wild_name}* fainted!"
                xp_block     = "\n".join(xp_msgs) if xp_msgs else ""
                move_log     = "\n".join(log) if log else faint_line
                if xp_block:
                    move_log += f"\n{faint_line}\n{xp_block}"
                else:
                    move_log += f"\n{faint_line}"
                intro_msg = (
                    f"{dots}\n\n"
                    f"{img}"
                    f"*{trainer}* sends out *{mon_name}* (Lv{mon_lvl})!"
                )
                # 3-tuple: attack+faint+xp | intro | hud
                return move_log, intro_msg, battle_hud(active, next_mon)
            else:
                # All trainer mons down — round won
                trainer = session.arena_trainer_name
                try:
                    if is_gym:
                        from gym import gym_round_won
                        round_msg = gym_round_won(self.db, self.sender, player, session)
                    elif self.db.get_meta(self.sender, "dungeon_elite_battle"):
                        # Dungeon Elite Encounter, fully defeated — start
                        # the global 5-minute cooldown. See
                        # dungeon_session.py's mark_elite_defeated() and
                        # router/dungeon.py's _resolve_elite_node().
                        elite_meta = self.db.get_meta(self.sender, "dungeon_elite_battle")
                        self.db.delete_meta(self.sender, "dungeon_elite_battle")
                        try:
                            import json as _json
                            elite_info = _json.loads(elite_meta) if isinstance(elite_meta, str) else elite_meta
                            elite_dungeon_id = elite_info.get("dungeon_id")
                            elite_floor       = elite_info.get("floor")
                        except (TypeError, ValueError, AttributeError):
                            elite_dungeon_id, elite_floor = None, None

                        if elite_dungeon_id is not None and elite_floor is not None:
                            from dungeon_session import mark_elite_defeated
                            mark_elite_defeated(self.db, elite_dungeon_id, elite_floor)

                        from combat_session import STATE_EXPLORING
                        session.clear_arena()
                        session.end_battle()
                        session.transition(STATE_EXPLORING)
                        round_msg = (
                            f"⚔️ *You defeated the {trainer}!*\n"
                            "━━━━━━━━━━━━━━━━\n"
                            "_It won't reappear here for a while._"
                        )
                        faint_line = f"*{wild_name}* fainted!"
                        xp_block   = "\n".join(xp_msgs) if xp_msgs else ""
                        move_log   = "\n".join(log) if log else faint_line
                        if xp_block:
                            move_log += f"\n{faint_line}\n{xp_block}"
                        else:
                            move_log += f"\n{faint_line}"
                        return move_log, round_msg
                    else:
                        from arena import arena_round_won
                        round_msg = arena_round_won(self.db, self.sender, player, session)
                except Exception:
                    round_msg = "✅ *Trainer defeated!*"

                if is_gym:
                    gauntlet_over = not self.db.get_meta(self.sender, "gym_round")
                else:
                    gauntlet_over = not self.db.get_meta(self.sender, "arena_round")
                if gauntlet_over:
                    session.clear_arena()
                session.end_battle()
                if not gauntlet_over:
                    if is_gym:
                        from combat_session import STATE_GYM
                        session.battle_context = "gym"
                        session.transition(STATE_GYM)
                    else:
                        from combat_session import STATE_ARENA
                        session.battle_context = "trainer"
                        session.transition(STATE_ARENA)
                faint_line = f"*{wild_name}* fainted!"
                xp_block   = "\n".join(xp_msgs) if xp_msgs else ""
                move_log   = "\n".join(log) if log else faint_line
                if xp_block:
                    move_log += f"\n{faint_line}\n{xp_block}"
                else:
                    move_log += f"\n{faint_line}"
                return move_log, round_msg

        # ── Wild battle victory ────────────────────────────────
        participants = []
        for poke in player.party:
            dmg = bs["participants"].get(poke.nickname, 0)
            if dmg > 0 or poke.nickname in bs["participants"]:
                participants.append((poke, dmg))
        xp_total = [0]
        xp_msgs = distribute_xp(participants, wild, total_out=xp_total)

        stars      = wild.get("stars", 1)
        multiplier = {1:1.0,2:1.2,3:1.5,4:1.8,5:2.2,
                      6:2.6,7:3.1,8:3.6,9:4.3,10:5.0}.get(stars, 1.0)
        coins      = int(wild.get("level", 1) * 5 * multiplier)
        player.coins = getattr(player, "coins", 0) + coins

        player.rank_kills = getattr(player, "rank_kills", 0) + 1
        player.pve_wins   = getattr(player, "pve_wins", 0) + 1

        try:
            _quest_on_defeat(player, wild)
        except Exception:
            pass

        _active = player.active_pokemon() or (participants[0][0] if participants else None)
        if _active is not None:
            rewards = battle_log.rewards_block("You", coins=coins, xp=xp_total[0])
            tail = battle_log.pve_win_lines(wild_name) + [rewards]
            if xp_msgs:                       # level-up notices etc.
                tail.append("\n".join(m.strip() for m in xp_msgs))
            wild["hp"] = 0
            frame = self._pve_frame(_active, wild, [log], commands=False, tail=tail)
            from router.explore import resume_journey_if_paused
            return frame + resume_journey_if_paused(self.sender, player, self.db)

        victory_lines = [f"Wild *{wild_name}* fainted! 🎉", ""]
        victory_lines.extend(xp_msgs)
        victory_lines.append(f"You gained *{coins}₡*")

        move_log = "\n".join(log) if log else f"Wild *{wild_name}* fainted!"
        victory_msg = "\n".join(victory_lines)

        from router.explore import resume_journey_if_paused
        victory_msg += resume_journey_if_paused(self.sender, player, self.db)

        return move_log, victory_msg

    # ── Blackout ──────────────────────────────────────────────

    def _blackout(self, session, player, wild=None, blocks=None) -> str:
        frame = None
        if wild is not None and self._is_wild(session, wild):
            fallen = player.active_pokemon() or (player.party[0] if player.party else None)
            if fallen is not None:
                frame = self._pve_frame(fallen, wild, blocks or [], commands=False,
                                        tail=battle_log.pve_lose_lines(fallen.nickname))
        # ── Arena/Gym loss — drop out, no warp penalty ─────────
        is_arena = session.battle_context == "trainer"
        is_gym   = session.battle_context == "gym"
        if is_arena or is_gym:
            try:
                if is_gym:
                    from gym import gym_loss
                    msg = gym_loss(self.db, self.sender, player, session)
                else:
                    from arena import arena_loss
                    msg = arena_loss(self.db, self.sender, player, session)
            except Exception:
                msg = "💀 *You were defeated and dropped from the fight.*"
            session.clear_arena()
            session.end_battle()
            session.transition("exploring")
            # Still heal party
            for poke in player.party:
                poke.hp = poke.max_hp
            return msg

        # Full heal all party
        for poke in player.party:
            poke.hp = poke.max_hp

        # XP penalty — lose 20% of current progress, floor 0
        xp_lost = int(player.xp * 0.20)
        player.xp = max(0, player.xp - xp_lost)

        # Coin penalty — lose 20% of 25% of total coins
        coin_lost = int(player.coins * 0.25 * 0.20)
        player.coins = max(0, player.coins - coin_lost)

        # Warp to oak_town
        player.zone   = "oak_town"
        player.zone_x = 12
        player.zone_y = 11

        session.clear_encounter()
        session.battle_state = None

        # If this loss happened mid-.explore, the player just got
        # warped to Oak Town — resuming the old journey toward its
        # original destination wouldn't make sense anymore (they're
        # not even in the same zone it was heading from). End it
        # outright instead of resuming.
        from explore_session import ExploreSession
        _exp_session = ExploreSession.load(self.db, self.sender)
        if _exp_session.is_active() and _exp_session.paused_for_battle:
            _exp_session.end()
            _exp_session.save(self.db)

        penalty = (
            f"_...You blacked out._\n\n"
            f"You were warped back to *Oak Town*.\n"
            f"Your Pokémon have been fully healed.\n"
            f"-{xp_lost} XP  ·  -{coin_lost}₡"
        )
        if frame:
            return frame + "\n\n" + penalty
        return f"💀 *All Pokémon fainted!*\n\n" + penalty

    # ── Flee ──────────────────────────────────────────────────

    def _flee(self, session, player, bs, wild) -> str:
        active = player.active_pokemon()
        active_spd = active.stat("speed") if active else 50
        wild_spd   = _get_stats(wild).get("speed", 45)

        flee_chance = ((active_spd * 128) // max(1, wild_spd) + 30) % 256
        if random.randint(0, 255) < flee_chance:
            session.clear_encounter()
            session.battle_state = None
            from router.explore import resume_journey_if_paused
            resume_suffix = resume_journey_if_paused(self.sender, player, self.db)
            if self._is_wild(session, wild):
                return "You got away safely!\n\nBattle ended." + resume_suffix
            return "💨 *Got away safely!*" + resume_suffix
        else:
            log = ["Couldn't escape!"]
            self._wild_attacks(wild, active, bs, log)
            label = self._battle_label(session, wild)
            wild_mode = self._is_wild(session, wild)
            if active and active.is_fainted():
                idx = player.first_conscious()
                if idx is None:
                    return self._blackout(session, player, wild=wild, blocks=[log])
                player.set_active(idx)
                new_active = player.active_pokemon()
                log.append(f"{active.nickname} fainted!" if wild_mode else f"*{active.nickname}* fainted!")
                if wild_mode:
                    return self._pve_frame(new_active, wild, [log])
                return battle_turn_result(player.name, new_active, wild, log, [], label=label)
            if wild_mode:
                return self._pve_frame(active, wild, [log])
            return battle_turn_result(player.name, active, wild, log, [], label=label)

    # ── Catch ─────────────────────────────────────────────────

    def _catch(self, session, player, bs, wild, args=None) -> str:
        if wild.get("trainer_owned"):
            active = player.active_pokemon()
            return battle_turn_result(player.name, active, wild,
                                       ["_You can't catch another trainer's Pokémon!_"], [],
                                       label=self._battle_label(session, wild))

        from data_items import POKEBALLS
        GUARANTEED_BALLS = {"Master Ball", "Park Ball"}  # never auto-selected

        ball = None
        if args:
            query = " ".join(args).strip().lower().replace("é", "e").replace(" ", "")
            for name in POKEBALLS:
                norm = name.lower().replace("é", "e").replace(" ", "")
                if norm == query or norm == query + "ball":
                    ball = name
                    break
            if ball is None:
                return battle_turn_result(player.name, player.active_pokemon(), wild,
                                           [f"No ball matching '{' '.join(args)}'."], [])
            if not player.has_item(ball):
                return battle_turn_result(player.name, player.active_pokemon(), wild,
                                           [f"You have no {ball}s!"], [])
        else:
            if player.has_item("Poké Ball"):
                ball = "Poké Ball"
            else:
                owned = sorted(
                    (n for n in POKEBALLS if n not in GUARANTEED_BALLS and player.has_item(n)),
                    key=lambda n: POKEBALLS[n],
                )
                ball = owned[0] if owned else None

        if not ball:
            active = player.active_pokemon()
            return battle_turn_result(player.name, active, wild, ["You have no Poké Balls!"], [])

        player.use_item(ball)

        caught, shakes = attempt_catch(wild, ball_multiplier=POKEBALLS.get(ball, 1.0))

        shake_text = "…" * shakes
        if not caught:
            wobble = ["The Pokéball wobbled!", "Oh no! It broke free!",
                      "Aww! It appeared to be caught!", "Darn! The Pokémon broke free!"]
            fail_msg = random.choice(wobble)
            log = [f"🔴 {shake_text}", fail_msg]

            active = player.active_pokemon()
            self._wild_attacks(wild, active, bs, log)
            if active and active.is_fainted():
                idx = player.first_conscious()
                if idx is None:
                    return self._blackout(session, player)
                player.set_active(idx)
            return battle_turn_result(player.name, player.active_pokemon(), wild, log, [])

        # Caught!
        from pokeapi import get_full
        api_data = get_full(self.db, wild["name"])
        if not api_data:
            # Fallback: build minimal api_data from wild dict. wild no
            # longer carries "base_stats" (Phase 3 cutover) — falls
            # back to old-style PokéAPI stat names derived from the
            # Soulbound stats instead, since OwnedPokemon.__init__
            # expects PokéAPI-shaped api_data going into
            # pokemon_to_soulbound(), not pre-converted Soulbound
            # stats. This fallback path only fires when get_full()
            # itself fails (network/cache issue), so it's rare.
            wild_stats = wild.get("stats", {})
            api_data = {
                "id":          wild.get("id", 0),
                "name":        wild["name"],
                "types":       wild.get("types", ["normal"]),
                "sprite":      wild.get("sprite", ""),
                "base_stats":  wild.get("base_stats") or dict(_get_stats(wild)),
                "default_moves": [m["name"] for m in wild.get("moves", [])],
                "catch_rate":  wild.get("catch_rate", 45),
                "base_experience": wild.get("base_experience", 50),
                "flavor_text": "",
                "evolution_chain_url": "",
                "is_legendary": False,
                "is_mythical":  False,
                "generation":   "generation-i",
            }

        owned = OwnedPokemon(api_data, level=wild["level"],
                             stars=wild.get("stars", 1), db=self.db)

        in_party = len(player.party) < 6
        player.add_to_party(owned)
        player.see_pokemon(wild["name"])
        player.catch_pokemon(wild["name"])

        # Quest progress hook — catch_species
        try:
            _quest_on_catch(player, wild["name"])
        except Exception:
            pass

        slot = len(player.party) - 1 if in_party else len(player.box) - 1
        player.set_flag("caught_naming_slot", slot)
        player.set_flag("caught_naming_box", not in_party)
        player.story_stage = "caught_naming"

        session.clear_encounter()
        session.battle_state = None

        loc = "your party" if in_party else "PC"
        reveal = star_reveal_screen(owned)
        naming_prompt = (
            f"\n{'Your party is full — ' if not in_party else ''}"
            f"*{owned.nickname}* added to {loc}!\n\n"
            f"Would you like to give it a nickname?\n"
            f"*.name [nickname]* · *.skip*"
        )

        from router.explore import resume_journey_if_paused
        resume_suffix = resume_journey_if_paused(self.sender, player, self.db)

        return reveal + naming_prompt + resume_suffix

    # ── Heal ──────────────────────────────────────────────────

    def _heal(self, session, player, bs, wild, active: OwnedPokemon, args=None) -> str:
        from data_items import HEALING_ITEMS
        HP_PRIORITY = ["Max Potion", "Hyper Potion", "Super Potion", "Potion"]
        label = self._battle_label(session, wild)

        item = None
        if args:
            query = " ".join(args).strip().lower()
            for name in HEALING_ITEMS:
                if HEALING_ITEMS[name].get("effect") in ("hp", "hp_full") and name.lower() == query:
                    item = name
                    break
            if item is None:
                return battle_turn_result(player.name, player.active_pokemon(), wild,
                                           [f"No healing item matching '{' '.join(args)}'."], [], label=label)
            if not player.has_item(item):
                return battle_turn_result(player.name, player.active_pokemon(), wild,
                                           [f"You have no {item}s!"], [], label=label)
        else:
            for name in HP_PRIORITY:
                if player.has_item(name):
                    item = name
                    break

        if not item:
            log = ["You have no Potions!"]
            self._wild_attacks(wild, active, bs, log)
            if active.is_fainted():
                idx = player.first_conscious()
                if idx is None:
                    return self._blackout(session, player)
                player.set_active(idx)
            return battle_turn_result(player.name, player.active_pokemon(), wild, log, [], label=label)

        player.use_item(item)
        info = HEALING_ITEMS.get(item, {})
        if info.get("effect") == "hp_full":
            healed = active.max_hp - active.hp
            active.hp = active.max_hp
        else:
            healed = active.heal(info.get("value", 20))

        log = [f"Used a *{item}*! {active.nickname} recovered *{healed} HP*!"]

        # Wild gets a free attack
        self._wild_attacks(wild, active, bs, log)
        if active.is_fainted():
            idx = player.first_conscious()
            if idx is None:
                return self._blackout(session, player)
            player.set_active(idx)
            log.append(f"*{active.nickname}* fainted!")
            return battle_turn_result(player.name, player.active_pokemon(), wild, log, [], label=label)

        return battle_turn_result(player.name, active, wild, log, [], label=label)

    # ── Switch ────────────────────────────────────────────────

    def _switch(self, session, player, bs, wild, args) -> str:
        if not args:
            lines = [
                f"  {i+1}. {p.nickname} Lv.{p.level} — {'💀 fainted' if p.is_fainted() else f'{p.hp}/{p.max_hp} HP'}"
                f"{' <active>' if i == player.active_slot else ''}"
                for i, p in enumerate(player.party)
            ]
            return "Your party:\n" + "\n".join(lines) + "\n\n_.switch [name or number]_"

        target = args[0]
        idx    = None

        # By number
        if target.isdigit():
            n = int(target) - 1
            if 0 <= n < len(player.party):
                idx = n
        else:
            # By name
            for i, p in enumerate(player.party):
                if p.nickname.lower() == target.lower() or p.name.lower() == target.lower():
                    idx = i
                    break

        if idx is None:
            return f"❌ Pokémon *{target}* not found in your party."

        target_poke = player.party[idx]
        if target_poke.is_fainted():
            return f"❌ *{target_poke.nickname}* has fainted and can't battle!"
        if idx == player.active_slot:
            return f"*{target_poke.nickname}* is already in battle!"

        old_name = player.active_pokemon().nickname if player.active_pokemon() else "?"
        player.set_active(idx)
        new_active = player.active_pokemon()

        # Register new participant
        if new_active.nickname not in bs["participants"]:
            bs["participants"][new_active.nickname] = 0

        log = [f"*{old_name}*, come back!"]
        # Wild gets a free attack on the switch
        self._wild_attacks(wild, new_active, bs, log)
        label = self._battle_label(session, wild)

        if new_active.is_fainted():
            idx2 = player.first_conscious()
            if idx2 is None:
                return self._blackout(session, player)
            player.set_active(idx2)
            log.append(f"*{new_active.nickname}* fainted!")
            return battle_turn_result(player.name, player.active_pokemon(), wild, log, [], label=label)

        # Show switch card as monster_log (queued after action_log)
        card = switch_card(new_active, wild)
        return battle_turn_result(player.name, new_active, wild, log, [card], label=label)

# placeholder - will be replaced

