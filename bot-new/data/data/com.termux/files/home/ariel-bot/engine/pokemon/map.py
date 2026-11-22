# ============================================================
# NIFLHEIM – MAP.PY
# Zone tile map system
# ============================================================

import importlib
import os
import sys

# ── Terrain symbols ───────────────────────────────────────────
TERRAIN_SYMBOL = {
    "TT": "𐂷",
    "JF": "𐂷",
    "WW": "ᯓ",
    "DD": "ᯓ",
    "~~": "ᯓ",
    "UU": "ᯓ",
    "LS": "ᯓ",
    "BA": "ᯓ",
    "SK": "ᯓ",
    "CR": "ᯓ",
    "SP": "ᯓ",
    "SW": "ᯓ",
    "HH": "合",
    "PS": "⛃𓏺",
    "AV": "合",
    "PT": "合",
    "AC": "合",
    "BO": "合",
    "OR": "合",
    "TH": "合",
    "MM": "▲",
    "CP": "▲",
    "MR": "▲",
    "CY": "▲",
    "RR": " -  ",
    "GG": "☁︎",
    "PP": "☁︎",
    "SC": "☁︎",
    "SS": "⚬｡",
    "SN": "⚬｡",
    "AG": "⚬｡",
    "OB": "⚬｡",
    "XX": "↟↟",
    "CC": "﴾﴿",
    "ZZ": "﴾﴿",
    "DE": "﴾﴿",
    "DW": "﴾﴿",
    "AS": "﴾﴿",
    "NN": "𓏻Იֶָ",
    "FG": "𓏻Იֶָ",
    "BB": "✦",
    "WT": "╭-",
    "WR": "-╮",
    "WB": "╰-",
    "WK": "-╯",
    "WH": "--",
    "WV": "|",
    "LL": "𓏺🜔",
    "GV": "愛",
    "LT": "愛",
    "IT": "愛",
    "MV": "愛",
    "NP": "웃",
    "SG": "Ϝꟻ",
    # ── Gym crest tiles (3×3 box) ─────────────────────────────
    # Open gym (- bottom = RR entrance)
    "b1": "╔ ",   # top-left
    "b2": " ═ ",  # top-mid
    "b3": " ╗",   # top-right
    "b4": " ║ ",   # mid-left
    "b5": "力", # mid-center
    "b6": " ║",  # mid-right
    "b7": "╚ ",   # bot-left
    "b8": " -   ",  # bot-mid  (open — walkable entrance)
    "b9": " ╝",   # bot-right
    # Closed gym (═ bottom = blocked)
    "c1": "╔ ",   # top-left
    "c2": " ═ ",  # top-mid
    "c3": " ╗",   # top-right
    "c4": "║ ",   # mid-left
    "c5": "力", # mid-center
    "c6": " ║",  # mid-right
    "c7": "╚ ",   # bot-left
    "c8": " ═ ",  # bot-mid  (closed — impassable)
    "c9": " ╝",   # bot-right
    "PC": " ✙",   # Pokémon Center
    "PS": "⛃𓏺",  # Pokémart
    "PL": " ⚲ ",
    "UK": "·",
    "AR": "·",   # arrow placeholder — replaced at render time
}

PLAYER_MARKER = " ⚲ "

# ── Impassable tiles ──────────────────────────────────────────
IMPASSABLE = {
    "TT", "MM", "WW", "DD", "~~", "BB", "BA", "SK", "PS", "SS",
    "WT", "WR", "WB", "WK", "WH", "WV",
    "CR", "SP", "UU", "LS", "JF", "CP", "MR",
    # Gym crest — all walls impassable; b8 is the open door (passable)
    "b1", "b2", "b3", "b4", "b5", "b6", "b7", "b9",
    # Closed gym — all tiles impassable including c8
    "c1", "c2", "c3", "c4", "c5", "c6", "c7", "c8", "c9",
}

# ── Safe zones (no encounters) ────────────────────────────────
# Legacy fallback set — kept for any zone file that predates the
# zone_type field. New code should prefer is_safe_zone(zone_id),
# which derives safety from zone_type ("town"/"city") so a zone
# only needs to be tagged once instead of also being listed here.
SAFE_ZONES = {"oak_town", "greenwood_town"}


def is_safe_zone(zone_id: str) -> bool:
    """A zone is safe (no wild encounters, town-gated features) if its
    zone_type is 'town' or 'city'. Falls back to the legacy SAFE_ZONES
    set for any zone file that hasn't been tagged with zone_type yet."""
    zone = load_zone(zone_id)
    zone_type = zone.get("zone_type")
    if zone_type is not None:
        return zone_type in ("town", "city")
    return zone_id in SAFE_ZONES

# ── Encounter tiles ───────────────────────────────────────────
ENCOUNTER_TILES = {
    "GG", "PP", "SC", "NN", "XX", "CC", "UU", "LS", "JF",
}

# ── Zone cache ────────────────────────────────────────────────
_ZONE_CACHE:  dict = {}   # zone_id -> ZONE dict
_ZONE_MTIME:  dict = {}   # zone_id -> last mtime


def _zone_file_path(zone_id: str) -> str | None:
    """Return the .py file path for a zone, or None if not found."""
    from paths import ROOT, WORLD_DIR
    for d in (WORLD_DIR, os.path.join(ROOT, "zones")):
        p = os.path.join(d, f"{zone_id}.py")
        if os.path.exists(p):
            return p
    return None


def load_zone(zone_id: str) -> dict:
    fpath = _zone_file_path(zone_id)
    mtime = os.path.getmtime(fpath) if fpath else None

    # Return cached version only if file hasn't changed
    if zone_id in _ZONE_CACHE:
        if mtime is None or mtime == _ZONE_MTIME.get(zone_id):
            return _ZONE_CACHE[zone_id]
        # File changed — bust cache
        _ZONE_CACHE.pop(zone_id, None)
        sys.modules.pop(zone_id, None)

    from paths import ROOT, WORLD_DIR
    for d in (WORLD_DIR, os.path.join(ROOT, "zones")):
        if d not in sys.path:
            sys.path.insert(0, d)

    try:
        sys.modules.pop(zone_id, None)
        mod  = importlib.import_module(zone_id)
        zone = mod.ZONE
        _ZONE_CACHE[zone_id]  = zone
        _ZONE_MTIME[zone_id]  = mtime
        return zone
    except Exception as e:
        print(f"[MAP] Failed to load zone '{zone_id}': {e}")
        return _fallback_zone(zone_id)


def _fallback_zone(zone_id: str) -> dict:
    return {
        "id":     zone_id,
        "name":   zone_id.replace("_", " ").title(),
        "width":  9,
        "height": 9,
        "grid":   [["TT"] * 9 for _ in range(9)],
        "spawn":  (4, 4),
        "exits":  {},
        "thresholds": [],
        "npcs":   {},
        "signs":  {},
    }


# ── Tile helpers ──────────────────────────────────────────────

def get_tile(zone_id: str, row: int, col: int) -> str:
    zone = load_zone(zone_id)
    grid = zone["grid"]
    if 0 <= row < len(grid) and 0 <= col < len(grid[row]):
        return grid[row][col]
    return "TT"


def is_passable(zone_id: str, row: int, col: int) -> bool:
    return get_tile(zone_id, row, col) not in IMPASSABLE


def is_encounter_tile(zone_id: str, row: int, col: int) -> bool:
    if is_safe_zone(zone_id):
        return False
    return get_tile(zone_id, row, col) in ENCOUNTER_TILES


def get_zone_name(zone_id: str) -> str:
    return load_zone(zone_id).get("name", zone_id.replace("_", " ").title())


# ── Zone transitions ──────────────────────────────────────────

def check_exit(zone_id: str, row: int, col: int) -> dict | None:
    zone = load_zone(zone_id)
    return zone.get("exits", {}).get(f"{row},{col}")


def check_threshold_exit(zone_id: str, row: int, col: int) -> dict | None:
    zone = load_zone(zone_id)
    for t in zone.get("thresholds", []):
        cond = t["condition"]
        if cond == "col_lt" and col < t["value"]: return t
        if cond == "col_gt" and col > t["value"]: return t
        if cond == "row_lt" and row < t["value"]: return t
        if cond == "row_gt" and row > t["value"]: return t
    return None


# ── NPC / sign lookup ─────────────────────────────────────────

def get_npc(zone_id: str, row: int, col: int) -> dict | None:
    return load_zone(zone_id).get("npcs", {}).get(f"{row},{col}")


def get_sign(zone_id: str, row: int, col: int) -> str | None:
    return load_zone(zone_id).get("signs", {}).get(f"{row},{col}")


# ── NPC symbol logic ──────────────────────────────────────────

def _npc_symbol(row_codes: list, idx: int) -> str:
    for j in range(idx):
        if row_codes[j] == "NP":
            return "𓏺웃"
    return "웃"


# ── Row renderer ──────────────────────────────────────────────

SEP = "  "

def render_row(row_codes: list) -> str:
    symbols = []
    for i, code in enumerate(row_codes):
        if code == "NP":
            symbols.append(_npc_symbol(row_codes, i))
        else:
            symbols.append(TERRAIN_SYMBOL.get(code, "·"))
    return SEP.join(symbols)


# ── Minimap renderer ──────────────────────────────────────────

RADIUS = 4  # 9x9 viewport

# ── Objective targets per story stage ────────────────────────
_OBJECTIVE_TILES = {
    "new":        {"oak_town": (14, 7)},
    "at_lab":     {"oak_town": (14, 7)},
    "choosing":   {"oak_town": (14, 7)},
    "confirming": {"oak_town": (14, 7)},
    "naming":     {"oak_town": (14, 7)},
    "has_starter":{"oak_town": (14, 7)},
    "route_1":    {"oak_town": (0, 5)},
}

_ARROW_SYMS = {"N": " ⇡ ", "S": " ￬ ", "W": " ❮ ", "E": " ❯ "}

def _astar(grid, start, goal):
    import heapq
    H = len(grid)
    W = len(grid[0]) if H else 0

    def passable(c, r):
        if c < 0 or r < 0 or r >= H or c >= W:
            return False
        return grid[r][c] not in IMPASSABLE

    def h(a, b):
        return abs(a[0] - b[0]) + abs(a[1] - b[1])

    heap = [(0, start)]
    came = {}
    g    = {start: 0}

    while heap:
        _, cur = heapq.heappop(heap)
        if cur == goal:
            path = []
            while cur in came:
                path.append(cur)
                cur = came[cur]
            path.reverse()
            return path
        for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0)):
            nb = (cur[0] + dx, cur[1] + dy)
            if not passable(*nb) and nb != goal:
                continue
            tg = g[cur] + 1
            if tg < g.get(nb, float("inf")):
                came[nb] = cur
                g[nb]    = tg
                heapq.heappush(heap, (tg + h(nb, goal), nb))
    return []


def _get_undiscovered_arrows(zone_id: str, cx: int, cy: int, visited: list) -> dict:
    """
    Returns {(dr, dc): symbol} for every unique undiscovered destination
    zone reachable via a direct exit from the current zone. One marker
    per destination zone, even if that zone has a multi-tile doorway —
    all exit tiles sharing a to_zone collapse to a single direction
    (their average position), so a 2-wide doorway doesn't produce two
    overlapping arrows.
    """
    zone  = load_zone(zone_id)
    exits = zone.get("exits", {})

    # Group exit tiles by destination zone, skip already-visited ones
    by_dest: dict[str, list[tuple[int, int]]] = {}
    for key, info in exits.items():
        to_zone = info.get("to_zone")
        if not to_zone or to_zone in visited:
            continue
        try:
            row, col = (int(v) for v in key.split(","))
        except (ValueError, AttributeError):
            continue
        by_dest.setdefault(to_zone, []).append((col, row))

    arrows: dict[tuple[int, int], str] = {}
    for to_zone, tiles in by_dest.items():
        ax = sum(t[0] for t in tiles) / len(tiles)
        ay = sum(t[1] for t in tiles) / len(tiles)
        dx, dy = ax - cx, ay - cy
        if abs(dx) >= abs(dy):
            symbol = _ARROW_SYMS["E"] if dx > 0 else _ARROW_SYMS["W"]
            pos    = (0, RADIUS) if dx > 0 else (0, -RADIUS)
        else:
            symbol = _ARROW_SYMS["S"] if dy > 0 else _ARROW_SYMS["N"]
            pos    = (RADIUS, 0) if dy > 0 else (-RADIUS, 0)
        arrows[pos] = symbol

    return arrows


def render_minimap(player) -> str:
    zone_id     = player.zone
    cy          = player.zone_y
    cx          = player.zone_x
    zone        = load_zone(zone_id)
    grid        = zone["grid"]
    H           = len(grid)
    W           = len(grid[0]) if H else 0

    def tile(r, c):
        if 0 <= r < H and 0 <= c < W:
            t = grid[r][c]
            # EX tiles render as path on the minimap
            return "RR" if t == "EX" else t
        # Show road (not trees) for OOB tiles adjacent to an EX tile
        if c < 0 and 0 <= r < H and grid[r][0] == "EX":
            return "RR"
        if c >= W and 0 <= r < H and grid[r][W - 1] == "EX":
            return "RR"
        if r < 0 and 0 <= c < W and grid[0][c] == "EX":
            return "RR"
        if r >= H and 0 <= c < W and grid[H - 1][c] == "EX":
            return "RR"
        return "TT"

    visited = player.get_flag("visited_zones", []) if hasattr(player, "get_flag") else []
    arrow_positions = _get_undiscovered_arrows(zone_id, cx, cy, visited)

    rows = []
    for dr in range(-RADIUS, RADIUS + 1):
        symbols = []
        for dc in range(-RADIUS, RADIUS + 1):
            if dr == 0 and dc == 0:
                symbols.append(TERRAIN_SYMBOL.get("PL", "·"))
            elif (dr, dc) in arrow_positions:
                symbols.append(arrow_positions[(dr, dc)].strip())
            else:
                code = tile(cy + dr, cx + dc)
                if code == "NP":
                    row_codes = [tile(cy + dr, cx + c) for c in range(-RADIUS, RADIUS + 1)]
                    symbols.append(_npc_symbol(row_codes, dc + RADIUS))
                else:
                    symbols.append(TERRAIN_SYMBOL.get(code, "·"))
        rows.append(SEP.join(symbols))

    name      = zone.get("name", zone_id.replace("_", " ").title())
    zone_type = zone.get("zone_type", "route")
    label     = "Town" if zone_type == "town" else "Route"
    map_str   = "\n".join(rows)

    return (
        f"{map_str}\n"
        f"({name} · {label})\n"
        f"1 up        3 left\n"
        f"2 down    4 right"
    )

