# ============================================================
# NIFLHEIM — world_registry.py
# Provides move(), get_zone(), get_zone_image(), GATES
# Built on top of map.py's zone loading system
# ============================================================

from map import load_zone, IMPASSABLE, is_safe_zone, ENCOUNTER_TILES

# ── Gate definitions ─────────────────────────────────────────
# Avalon city gates — level requirements and tolls
GATES = {
    "north": {
        "min_level":    1,
        "toll":         0,
        "guild_toll":   0,
        "guard_normal": "Safe travels.",
        "guard_broke":  "Move along.",
    },
    "south": {
        "min_level":    30,
        "toll":         50,
        "guild_toll":   25,
        "guard_normal": "Toll collected: {toll}G. Watch yourself out there.",
        "guard_broke":  "You can't afford the toll. Come back when you have coin.",
    },
    "east": {
        "min_level":    15,
        "toll":         20,
        "guild_toll":   10,
        "guard_normal": "Toll collected: {toll}G. Eastern road is dangerous.",
        "guard_broke":  "No coin, no passage. Eastern gate is closed to you.",
    },
    "west": {
        "min_level":    20,
        "toll":         30,
        "guild_toll":   15,
        "guard_normal": "Toll collected: {toll}G. The Scorched Woods are treacherous.",
        "guard_broke":  "You're broke. The guard turns you away.",
    },
}

# ── Zone image map ────────────────────────────────────────────
# Maps zone_id → a representative image URL for explore screen
_ZONE_IMAGES: dict[str, str] = {
    "route_1":      "https://i.ibb.co/placeholder/route1.jpg",
    "jotun_forest": "https://i.ibb.co/placeholder/jotun.jpg",
    "crystal_lake": "https://i.ibb.co/placeholder/crystal.jpg",
    "scorched_woods":"https://i.ibb.co/placeholder/scorched.jpg",
    "sacred_plains":"https://i.ibb.co/placeholder/plains.jpg",
    "barshkands":   "https://i.ibb.co/placeholder/barshkands.jpg",
}

# ── Direction deltas ─────────────────────────────────────────
_DELTA = {
    "1": (0, -1), "-1": (0, -1),   # north — row decreases
    "2": (0,  1), "-2": (0,  1),   # south — row increases
    "3": (-1, 0), "-3": (-1, 0),   # west  — col decreases
    "4": ( 1, 0), "-4": ( 1, 0),   # east  — col increases
}


def get_zone(zone_id: str) -> dict:
    """Load and return the zone dict for zone_id."""
    return load_zone(zone_id)


def get_zone_image(zone_x: int, zone_y: int, zone_id: str = "") -> str:
    """Return image URL for the current zone, or empty string."""
    return _ZONE_IMAGES.get(zone_id, "")


def move(player, direction: str) -> tuple[bool, str, dict]:
    """
    Attempt to move the player one tile in direction.

    Returns (success, barrier_message, zone_dict).
    On success:  (True,  "",             zone_dict)
    On failure:  (False, barrier_message, {})
    """
    zone_id = getattr(player, "zone", "route_1")
    zone    = load_zone(zone_id)
    grid    = zone.get("grid", [])
    height  = zone.get("height", len(grid))
    width   = zone.get("width",  len(grid[0]) if grid else 0)

    dc, dr = _DELTA.get(str(direction), (0, 0))
    new_col = player.zone_x + dc
    new_row = player.zone_y + dr

    # ── Zone transition check ─────────────────────────────────
    exits = zone.get("exits", {})
    exit_key = f"{new_row},{new_col}"
    if exit_key in exits:
        dest = exits[exit_key]
        player.zone   = dest["zone"]
        player.zone_x = dest["spawn"][0]
        player.zone_y = dest["spawn"][1]
        new_zone = load_zone(dest["zone"])
        new_zone["safe"] = is_safe_zone(dest["zone"])
        return True, "", new_zone

    # ── Threshold exit check ──────────────────────────────────
    for thresh in zone.get("thresholds", []):
        cond = thresh.get("condition")
        val  = thresh.get("value")
        in_range = True
        if "row_min" in thresh and "row_max" in thresh:
            in_range = thresh["row_min"] <= new_row <= thresh["row_max"]
        if "col_min" in thresh and "col_max" in thresh:
            in_range = in_range and thresh["col_min"] <= new_col <= thresh["col_max"]
        triggered = (
            (cond == "col_lt" and new_col < val) or
            (cond == "col_gt" and new_col > val) or
            (cond == "row_lt" and new_row < val) or
            (cond == "row_gt" and new_row > val)
        )
        if triggered and in_range:
            dest_zone = thresh.get("zone")
            spawn     = thresh.get("spawn", (0, 0))
            player.zone   = dest_zone
            player.zone_x = spawn[0]
            player.zone_y = spawn[1]
            new_zone = load_zone(dest_zone)
            new_zone["safe"] = is_safe_zone(dest_zone)
            return True, "", new_zone

    # ── Out of bounds ─────────────────────────────────────────
    if not (0 <= new_col < width and 0 <= new_row < height):
        return False, "_There is nothing that way._", {}

    # ── Tile passability ──────────────────────────────────────
    tile = grid[new_row][new_col] if grid else "TT"
    if tile in IMPASSABLE:
        return False, "_The way is blocked._", {}

    # ── Move accepted ─────────────────────────────────────────
    player.zone_x = new_col
    player.zone_y = new_row

    zone["safe"] = is_safe_zone(zone_id)
    return True, "", zone
