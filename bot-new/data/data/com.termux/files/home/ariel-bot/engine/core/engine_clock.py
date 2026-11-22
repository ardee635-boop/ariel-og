# ============================================================
# RAPHAEL – ENGINE_CLOCK.PY
# Universal 3x game time — same for all players
# Real 24hrs = 3 full game day/night cycles (8hrs each)
# ============================================================

import time
from datetime import datetime, timezone

# ── Constants ─────────────────────────────────────────────────
GAME_SPEED      = 3        # 3x real time
CYCLE_HOURS     = 8        # one full day/night cycle in game hours
DAWN_HOUR       = 6        # game hour when day starts
DUSK_HOUR       = 20       # game hour when night starts


def get_game_time():
    """
    Returns current game time as a dict.
    All players share this — it's server-based, not per-player.
    """
    real_seconds  = time.time()
    game_seconds  = real_seconds * GAME_SPEED
    game_hour     = int((game_seconds / 3600) % 24)
    game_minute   = int((game_seconds % 3600) / 60)
    game_day      = int(game_seconds / 86400) + 1  # day count since epoch

    is_day   = DAWN_HOUR <= game_hour < DUSK_HOUR
    is_night = not is_day

    # Time of day label
    if 5 <= game_hour < 9:
        time_label = "Dawn"
    elif 9 <= game_hour < 17:
        time_label = "Day"
    elif 17 <= game_hour < 20:
        time_label = "Dusk"
    elif 20 <= game_hour < 23:
        time_label = "Evening"
    else:
        time_label = "Night"

    return {
        "hour":       game_hour,
        "minute":     game_minute,
        "day":        game_day,
        "is_day":     is_day,
        "is_night":   is_night,
        "label":      time_label,
        "formatted":  f"{game_hour:02d}:{game_minute:02d}",
    }


def get_monster_multiplier():
    """
    Returns stat multiplier for monsters based on time of day.
    Night = stronger enemies.
    """
    t = get_game_time()
    if t["is_night"]:
        return 1.20   # +20% stats at night
    return 1.0


def get_time_display():
    """Clean single-line time display for HUD/status."""
    t = get_game_time()
    icon = "🌙" if t["is_night"] else "☀️"
    return f"{icon} {t['label']} · {t['formatted']} (Day {t['day']})"


def get_zone_atmosphere(zone_name):
    """
    Returns atmospheric flavor text based on zone + time.
    Used in exploration messages.
    """
    t = get_game_time()

    NIGHT_FLAVORS = {
        "Jotun Forest": "The forest is dark. Eyes watch from the shadows.",
        "Crystal Lake": "The lake surface is perfectly still. Something moves beneath.",
        "Scorched Woods": "The burnt trees creak in the windless dark.",
        "Sacred Plains": "The shrine glows faintly against the black sky.",
        "Barshkands": "The water is black and opaque. You hear things.",
    }
    DAY_FLAVORS = {
        "Jotun Forest": "Shafts of light pierce the canopy. Birds call in the distance.",
        "Crystal Lake": "The water shimmers. It is peaceful here.",
        "Scorched Woods": "The air smells of old ash. Nothing grows.",
        "Sacred Plains": "The wind moves through tall grass. The shrine stands silent.",
        "Barshkands": "The coast stretches wide. The water is warm and shallow.",
    }

    flavors = NIGHT_FLAVORS if t["is_night"] else DAY_FLAVORS
    default_night = "The darkness is thick here."
    default_day   = "The path ahead is quiet."

    if t["is_night"]:
        return flavors.get(zone_name, default_night)
    return flavors.get(zone_name, default_day)
