# ============================================================
# NIFLHEIM — oceana.py
# Oceana — spiral maze, dead end zone
# Connected west from Hydro Town (row 12)
# Something awaits at the center of the spiral
# 20×18 grid
# ============================================================

ZONE = {
    "id":           "oceana",
    "name":         "Oceana",
    "zone_type":    "route",
    "danger":       "🔴 Extreme",
    "safe":         False,
    "width":        20,
    "height":       18,
    "spawn":        (19, 8),
    "monster_zone": "Oceana",

    "grid": [
        # Row 00
        ["WW","WW","WW","WW","WW","WW","WW","WW","WW","WW","WW","WW","WW","WW","WW","WW","WW","WW","WW","WW"],
        # Row 01
        ["WW","WW","MM","MM","MM","MM","MM","MM","MM","MM","MM","MM","MM","MM","MM","MM","MM","WW","WW","WW"],
        # Row 02
        ["WW","WW","MM","WW","WW","WW","WW","WW","WW","WW","WW","WW","WW","WW","WW","WW","MM","WW","WW","WW"],
        # Row 03
        ["WW","WW","MM","WW","WW","WW","WW","WW","WW","WW","WW","WW","WW","WW","WW","WW","MM","WW","WW","WW"],
        # Row 04
        ["WW","WW","MM","WW","WW","MM","MM","MM","MM","MM","MM","MM","MM","MM","WW","WW","MM","WW","WW","WW"],
        # Row 05
        ["WW","WW","MM","WW","WW","MM","WW","WW","WW","WW","WW","WW","WW","MM","WW","WW","MM","WW","WW","WW"],
        # Row 06
        ["WW","WW","MM","WW","WW","MM","WW","WW","WW","WW","WW","WW","WW","MM","WW","WW","MM","WW","WW","WW"],
        # Row 07
        ["WW","WW","MM","WW","WW","MM","WW","WW","MM","MM","MM","WW","WW","MM","WW","WW","MM","WW","WW","WW"],
        # Row 08 — east entry from Hydro Town
        ["WW","WW","MM","WW","WW","MM","WW","WW","MM","WW","WW","WW","WW","MM","RR","RR","RR","RR","RR","EX"],
        # Row 09
        ["WW","WW","MM","WW","WW","MM","WW","WW","MM","WW","WW","WW","WW","MM","RR","RR","RR","RR","RR","EX"],
        # Row 10
        ["WW","WW","MM","WW","WW","MM","WW","WW","MM","MM","MM","WW","WW","MM","RR","RR","RR","RR","RR","EX"],
        # Row 11
        ["WW","WW","MM","WW","WW","MM","WW","WW","WW","WW","WW","WW","WW","MM","MM","MM","MM","WW","WW","WW"],
        # Row 12
        ["WW","WW","MM","WW","WW","MM","WW","WW","WW","WW","WW","WW","WW","WW","WW","WW","MM","WW","WW","WW"],
        # Row 13
        ["WW","WW","MM","WW","WW","MM","MM","MM","MM","MM","MM","MM","MM","MM","WW","WW","MM","WW","WW","WW"],
        # Row 14
        ["WW","WW","MM","WW","WW","WW","WW","WW","WW","WW","WW","WW","WW","WW","WW","WW","MM","WW","WW","WW"],
        # Row 15
        ["WW","WW","MM","WW","WW","WW","WW","WW","WW","WW","WW","WW","WW","WW","WW","WW","MM","WW","WW","WW"],
        # Row 16
        ["WW","WW","MM","MM","MM","MM","MM","MM","MM","MM","MM","MM","MM","MM","MM","MM","MM","WW","WW","WW"],
        # Row 17 — south wall
        ["WW","WW","WW","WW","WW","WW","WW","WW","WW","WW","WW","WW","WW","WW","WW","WW","WW","WW","WW","WW"],
    ],

    # ── Tile exits ────────────────────────────────────────────
    "exits": {
        "8,19":  {"to_zone": "hydro_town", "to_exit": "hydrotown_west_a"},
        "9,19":  {"to_zone": "hydro_town", "to_exit": "hydrotown_west_a"},
        "10,19": {"to_zone": "hydro_town", "to_exit": "hydrotown_west_a"},
    },

    # ── Exit positions (arrival points from other zones) ──────
    "exit_positions": {
        "oceana_east_a": (18, 8),
        "oceana_east_b": (18, 9),
        "oceana_east_c": (18, 10),
    },

    # ── NPCs / center event ───────────────────────────────────
    # TBD — something awaits at the center (9,8)
    "npcs": {},

    # ── Signs ─────────────────────────────────────────────────
    "signs": {},
}
