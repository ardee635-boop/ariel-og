# ============================================================
# NIFLHEIM — greenwood_town.py
# Greenwood Town — west of Route 1
# Gym Leader: Levin — Nature type, calm
# 12×14 grid (expanded to fit 3×3 gym crest)
#
# Gym crest tiles (open — b8 is the walkable entrance):
#   b1 b2 b3   ╔  ═  ╗
#   b4 b5 b6   ║  力  ║
#   b7 b8 b9   ╚  -  ╝
#
# Closed version uses c1–c9 (c8 = ═, impassable).
# Gym is always open — closed tiles kept for future use.
# ============================================================

# ── Gym state ─────────────────────────────────────────────────
# Toggle this to lock/unlock the gym on the map.
# True  → open   (b1–b9, b8 is walkable entrance)
# False → closed (c1–c9, all tiles impassable)
GYM_OPEN = True


def _gym_row(open_tiles: list, closed_tiles: list) -> list:
    """Return gym row based on GYM_OPEN flag."""
    return open_tiles if GYM_OPEN else closed_tiles


ZONE = {
    "id":    "greenwood_town",
    "name":  "Greenwood Town",
    "zone_type": "town",
    "safe":  True,
    "width":  12,
    "height": 14,
    "spawn":  (9, 5),

    "grid": [
        # Row 00  — north wall + north exits → Route 2
        ["TT","TT","TT","TT","TT","TT","TT","TT","EX","EX","TT","TT"],
        # Row 01
        ["TT","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","TT"],
        # Row 02  — gym top row:  b1 b2 b3
        ["TT","RR","RR","b1","b2","b3","RR","RR","RR","RR","RR","TT"],
        # Row 03  — gym mid row:  b4 b5 b6   |  mart + houses
        ["TT","HH","RR","b4","b5","b6","RR","PS","RR","RR","HH","TT"],
        # Row 04  — gym bot row:  b7 b8 b9
        ["TT","RR","RR","b7","b8","b9","RR","RR","RR","RR","RR","TT"],
        # Row 05
        ["TT","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","TT"],
        # Row 06  — east/west exits
        ["EX","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","EX"],
        # Row 07  — east/west exits
        ["EX","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","EX"],
        # Row 08  — sign row
        ["TT","RR","RR","RR","RR","RR","RR","SG","RR","RR","RR","TT"],
        # Row 09
        ["TT","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","TT"],
        # Row 10  — houses + Pokémon Center
        ["TT","HH","RR","RR","RR","RR","PC","RR","RR","RR","HH","TT"],
        # Row 11
        ["TT","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","TT"],
        # Row 12
        ["TT","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","TT"],
        # Row 13  — south wall + south exits
        ["TT","TT","TT","TT","TT","TT","EX","EX","TT","TT","TT","TT"],
    ],

    # ── Tile exits ────────────────────────────────────────────
    "exits": {
        # East → Route 1
        "6,11": {"to_zone": "route_1", "to_exit": "route1_west_a"},
        "7,11": {"to_zone": "route_1", "to_exit": "route1_west_b"},
        # West → Fauna (future zone)
        "6,0":  {"to_zone": "fauna", "to_exit": "fauna_east_a"},
        "7,0":  {"to_zone": "fauna", "to_exit": "fauna_east_b"},
        # South → Route 3 (future zone)
        "13,6": {"to_zone": "route_3", "to_exit": "route3_north_a"},
        "13,7": {"to_zone": "route_3", "to_exit": "route3_north_b"},
        # North → Route 2
        "0,8":  {"to_zone": "route_2", "to_exit": "route2_south_a"},
        "0,9":  {"to_zone": "route_2", "to_exit": "route2_south_b"},
    },

    # ── Exit positions (arrival points from other zones) ──────
    "exit_positions": {
        "greenwood_east_a": (10, 6),   # arriving from Route 1 west
        "greenwood_east_b": (10, 7),
        "greenwood_west_a": (1, 6),    # arriving from Fauna east
        "greenwood_west_b": (1, 7),
        "greenwood_south_a": (6, 12),  # arriving from Route 3 north
        "greenwood_south_b": (7, 12),
        "greenwood_north_a": (8, 1),   # arriving from Route 2 south
        "greenwood_north_b": (9, 1),
        # Note: south arrivals land one row above the EX tiles (row 12)
    },

    # ── NPCs ──────────────────────────────────────────────────
    "npcs": {},

    # ── Signs ─────────────────────────────────────────────────
    "signs": {
        "8,7": "📍 *Greenwood Town*\n🏟️ Gym — Levin · Nature type\n🛒 Pokémart — buy supplies\n🏥 Pokémon Center — heal your team\n🌿 _A town nestled deep in the forest._",
    },

    # ── Buildings ─────────────────────────────────────────────
    # b8 is the gym door — handled as "GY" entry in movement.py
    "buildings": {
        "PS": "greenwood_mart_interior",
        "PC": "greenwood_center_interior",
        "HH": "greenwood_house_interior",
    },

    # ── Gym state ─────────────────────────────────────────────
    # Exposed so movement.py can read it at runtime
    "gym_open": GYM_OPEN,
}

