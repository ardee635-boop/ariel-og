# ============================================================
# NIFLHEIM — thunderplains.py
# Thunderplains — named wild route, electric + mixed
# Connects Route 3 (north) to Hydro Town (south)
# 20×12 grid
# ============================================================

ZONE = {
    "id":           "thunderplains",
    "name":         "Thunderplains",
    "zone_type":     "route",
    "danger":       "🟠 Dangerous",
    "safe":         False,
    "width":        20,
    "height":       12,
    "spawn":        (11, 0),
    "monster_zone": "Thunderplains",

    "grid": [
        # Row 00 — north exit at cols 11-12
        ["TT","TT","TT","TT","TT","TT","TT","TT","TT","TT","TT","EX","EX","TT","TT","TT","TT","TT","TT","TT"],
        # Row 01
        ["TT","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","SS","TT"],
        # Row 02
        ["TT","GG","GG","GG","GG","GG","GG","TT","RR","WW","WW","WW","WW","WW","RR","RR","RR","RR","SS","TT"],
        # Row 03
        ["TT","GG","GG","GG","GG","GG","GG","TT","RR","WW","WW","WW","WW","WW","RR","RR","RR","RR","RR","TT"],
        # Row 04
        ["TT","GG","GG","GG","GG","GG","GG","SS","RR","WW","WW","WW","WW","WW","RR","RR","GG","GG","GG","TT"],
        # Row 05
        ["TT","GG","GG","GG","GG","GG","GG","SS","RR","WW","WW","WW","WW","WW","RR","RR","GG","GG","GG","TT"],
        # Row 06
        ["TT","GG","GG","GG","GG","GG","GG","RR","RR","WW","WW","WW","WW","WW","RR","RR","GG","GG","GG","TT"],
        # Row 07
        ["TT","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","GG","GG","GG","TT"],
        # Row 08
        ["TT","RR","SS","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","TT"],
        # Row 09
        ["TT","RR","SS","SS","SS","RR","RR","RR","RR","RR","RR","RR","SS","SS","SS","SS","SS","SS","RR","TT"],
        # Row 10
        ["TT","TT","TT","TT","TT","TT","RR","RR","TT","TT","TT","TT","TT","TT","TT","TT","TT","TT","TT","TT"],
        # Row 11 — south exit at cols 6-7
        ["TT","TT","TT","TT","TT","TT","EX","EX","TT","TT","TT","TT","TT","TT","TT","TT","TT","TT","TT","TT"],
    ],

    # ── Tile exits ────────────────────────────────────────────
    "exits": {
        # North → Route 3
        "0,11": {"to_zone": "route_3", "to_exit": "route3_south_a"},
        "0,12": {"to_zone": "route_3", "to_exit": "route3_south_b"},
        # South → Hydro Town
        "11,6": {"to_zone": "hydro_town", "to_exit": "hydrotown_north_a"},
        "11,7": {"to_zone": "hydro_town", "to_exit": "hydrotown_north_b"},
    },

    # ── Exit positions (arrival points from other zones) ──────
    "exit_positions": {
        "thunderplains_north_a": (11, 0),   # arriving from Route 3 south
        "thunderplains_north_b": (12, 0),
        "thunderplains_south_a": (6, 10),   # arriving from Hydro Town north
        "thunderplains_south_b": (7, 10),
    },

    # ── NPCs ──────────────────────────────────────────────────
    "npcs": {},

    # ── Signs ─────────────────────────────────────────────────
    "signs": {},
}

