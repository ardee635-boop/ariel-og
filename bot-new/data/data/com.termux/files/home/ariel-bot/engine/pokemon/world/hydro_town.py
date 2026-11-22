# ============================================================
# NIFLHEIM — hydro_town.py
# Hydro Town — water-dominated settlement
# Gym Leader: Eren — Water type, calm & understanding
# 23×23 grid
#
# Gym crest tiles (open — b8 is the walkable entrance, cols 13-15):
#   b1 b2 b3   ╔  ═  ╗
#   b4 b5 b6   ║  力  ║
#   b7 b8 b9   ╚  -  ╝
# ============================================================

GYM_OPEN = True

def _gym_row(open_tiles, closed_tiles):
    return open_tiles if GYM_OPEN else closed_tiles

ZONE = {
    "id":           "hydro_town",
    "name":         "Hydro Town",
    "zone_type":    "city",
    "danger":       "🟢 Safe",
    "safe":         True,
    "width":        23,
    "height":       23,
    "spawn":        (11, 0),
    "monster_zone": None,

    "grid": [
        # Row 00 — north exit cols 11-12
        ["WW","WW","WW","WW","WW","WW","WW","RR","RR","WW","WW","EX","EX","WW","WW","WW","WW","WW","WW","WW","WW","WW","WW"],
        # Row 01 — top-left island
        ["WW","RR","RR","RR","RR","RR","WW","WW","WW","WW","WW","RR","RR","WW","WW","WW","WW","WW","RR","RR","RR","RR","RR"],
        # Row 02 — PS top-left, PS top-right
        ["WW","RR","PS","RR","RR","RR","WW","WW","WW","WW","WW","RR","RR","WW","WW","WW","WW","WW","RR","RR","PS","RR","RR"],
        # Row 03
        ["WW","RR","RR","RR","RR","RR","RR","RR","RR","WW","WW","RR","RR","WW","WW","RR","RR","RR","RR","RR","RR","RR","RR"],
        # Row 04
        ["WW","WW","WW","WW","WW","WW","WW","RR","RR","WW","WW","RR","RR","WW","WW","RR","RR","WW","WW","WW","WW","WW","WW"],
        # Row 05 — houses row 1
        ["WW","WW","WW","WW","WW","WW","RR","HH","RR","RR","HH","RR","RR","HH","RR","RR","RR","WW","WW","WW","WW","WW","WW"],
        # Row 06 — path between house rows
        ["WW","WW","WW","WW","WW","WW","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","WW","WW","WW","WW","WW","WW"],
        # Row 07 — houses row 2
        ["WW","WW","WW","WW","WW","WW","RR","HH","RR","RR","HH","RR","RR","HH","RR","RR","RR","WW","WW","WW","WW","WW","WW"],
        # Row 08
        ["WW","WW","WW","WW","WW","WW","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","WW","WW","WW","WW","WW","WW"],
        # Row 09
        ["WW","WW","WW","WW","WW","WW","WW","RR","RR","WW","WW","RR","RR","WW","WW","RR","RR","WW","WW","WW","WW","WW","WW"],
        # Row 10
        ["WW","RR","RR","RR","RR","RR","RR","RR","RR","WW","WW","RR","RR","WW","WW","RR","RR","RR","RR","RR","RR","RR","RR"],
        # Row 11 — PC left land
        ["WW","RR","PC","RR","RR","RR","WW","WW","WW","WW","WW","RR","RR","WW","WW","WW","WW","WW","RR","RR","RR","RR","RR"],
        # Row 12 — west exit col 0
        ["EX","RR","RR","RR","RR","RR","WW","WW","WW","WW","WW","RR","RR","WW","WW","WW","WW","WW","RR","RR","RR","RR","RR"],
        # Row 13
        ["WW","WW","WW","WW","WW","WW","WW","WW","WW","WW","WW","RR","RR","WW","WW","WW","WW","WW","WW","WW","WW","WW","WW"],
        # Row 14
        ["WW","WW","WW","WW","WW","WW","WW","WW","WW","WW","WW","RR","RR","WW","WW","WW","WW","WW","WW","WW","WW","WW","WW"],
        # Row 15
        ["WW","WW","WW","WW","WW","WW","WW","WW","WW","WW","WW","RR","RR","WW","WW","WW","WW","WW","WW","WW","WW","WW","WW"],
        # Row 16 — gym top row
        ["WW","WW","WW","WW","WW","WW","WW","WW","WW","WW","RR","RR","RR","b1","b2","b3","WW","WW","WW","WW","WW","WW","WW"],
        # Row 17 — gym mid row
        ["WW","WW","WW","WW","WW","WW","WW","WW","WW","WW","RR","RR","RR","b4","b5","b6","WW","WW","WW","WW","WW","WW","WW"],
        # Row 18 — gym bot row
        ["WW","WW","WW","WW","WW","WW","WW","WW","WW","WW","RR","RR","RR","b7","b8","b9","WW","WW","WW","WW","WW","WW","WW"],
        # Row 19 — path below gym
        ["WW","WW","WW","WW","WW","WW","WW","WW","WW","WW","RR","RR","RR","RR","RR","RR","WW","WW","WW","WW","WW","WW","WW"],
        # Row 20
        ["WW","WW","WW","WW","WW","WW","WW","WW","WW","WW","RR","RR","RR","RR","RR","RR","WW","WW","WW","WW","WW","WW","WW"],
        # Row 21
        ["WW","WW","WW","WW","WW","WW","WW","WW","WW","WW","RR","RR","RR","RR","RR","RR","WW","WW","WW","WW","WW","WW","WW"],
        # Row 22 — south wall
        ["WW","WW","WW","WW","WW","WW","WW","WW","WW","WW","WW","WW","WW","WW","WW","WW","WW","WW","WW","WW","WW","WW","WW"],
    ],

    # ── Tile exits ────────────────────────────────────────────
    "exits": {
        # North → Thunderplains
        "0,11": {"to_zone": "thunderplains", "to_exit": "thunderplains_south_a"},
        "0,12": {"to_zone": "thunderplains", "to_exit": "thunderplains_south_b"},
        # West → Oceana (future)
        "12,0": {"to_zone": "oceana", "to_exit": "oceana_east_a"},
    },

    # ── Exit positions (arrival points from other zones) ──────
    "exit_positions": {
        "hydrotown_north_a": (11, 0),
        "hydrotown_north_b": (12, 0),
        "hydrotown_west_a":  (1, 12),
    },

    # ── NPCs ──────────────────────────────────────────────────
    "npcs": {},

    # ── Signs ─────────────────────────────────────────────────
    "signs": {},

    # ── Buildings ─────────────────────────────────────────────
    "buildings": {
        "PS": "hydro_mart_interior",
        "PC": "hydro_center_interior",
        "HH": "hydro_house_interior",
    },

    # ── Gym state ─────────────────────────────────────────────
    "gym_open": GYM_OPEN,
}
