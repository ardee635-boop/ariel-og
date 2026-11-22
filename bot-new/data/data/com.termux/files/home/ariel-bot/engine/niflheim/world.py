# Niflheim world: fixed map from data/locations.json. One destination per exit (no random destinations).
import json
import os

from . import config as cfg

_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
DIRECTIONS = ("north", "east", "south", "west")
ALIASES = {"n": "north", "north": "north", "e": "east", "east": "east",
           "s": "south", "south": "south", "w": "west", "west": "west"}
TYPE_LABEL = {"town": "Town", "hub": "Hub", "place": "Place"}
_locs = None


def locations(reload=False):
    global _locs
    if _locs is None or reload:
        with open(os.path.join(_DATA_DIR, "locations.json"), "r", encoding="utf-8") as f:
            data = json.load(f)
        _locs = {l["id"]: l for l in data["locations"]}
    return _locs


def get(loc_id):
    return locations().get(loc_id)


def resolve_direction(raw):
    return ALIASES.get((raw or "").strip().lower())


def exit_dest(loc, direction):
    return (loc.get("exits") or {}).get(direction)


def is_town(loc_id):
    loc = get(loc_id)
    return bool(loc) and loc.get("type") == "town"


def border_time(loc_id):
    loc = get(loc_id)
    table = cfg.get("travel", {}).get("border_time", {})
    return float(table.get(loc.get("type") if loc else "place", 7))


def travel_time(origin_id, dest_id):
    """Journey time = border time of the origin + border time of the destination (config)."""
    return border_time(origin_id) + border_time(dest_id)


def requirements_met(player, loc):
    """🔒 mechanism. Session 1 has no requirements. Supported keys: level, item.
    Any other key (boss, session, ...) counts as NOT met until a later session implements it."""
    for key, val in (loc.get("requires") or {}).items():
        if key == "level":
            ok = player.get("level", 1) >= int(val)
        elif key == "item":
            ok = player.get("inventory", {}).get(val, 0) > 0
        else:
            ok = False
        if not ok:
            return False
    return True


def exit_label(player, loc, direction):
    """Name if the player has reached that location, else '???'; plus 🔒 if its requirements are unmet."""
    dest_id = exit_dest(loc, direction)
    if not dest_id:
        return None
    dest = get(dest_id)
    label = dest["name"] if dest_id in player.get("discovered", []) else "???"
    if dest and not requirements_met(player, dest):
        label += " 🔒"
    return label


def exits_lines(player, loc):
    lines = []
    for d in DIRECTIONS:
        label = exit_label(player, loc, d)
        if label:
            lines.append(f"┣ {d.capitalize()}: {label}")
    return lines
