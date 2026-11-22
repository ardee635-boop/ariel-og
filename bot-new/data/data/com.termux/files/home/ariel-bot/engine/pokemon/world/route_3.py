# ============================================================
# NIFLHEIM — route_3.py
# Route 3 — connects Greenwood Town (north) to Thunderplains (south)
# 15×13 grid
# ============================================================

ZONE = {
    "id":           "route_3",
    "name":         "Route 3",
    "zone_type":     "route",
    "danger":       "🟡 Moderate",
    "safe":         False,
    "width":        15,
    "height":       13,
    "spawn":        (3, 1),
    "monster_zone": "Route 3",

    "grid": [
        # Row 00 — north exit → Greenwood Town
        ["TT","TT","TT","EX","EX","TT","TT","TT","TT","TT","TT","TT","TT","TT","TT"],
        # Row 01
        ["TT","GG","GG","RR","RR","GG","GG","GG","GG","GG","GG","TT","TT","TT","TT"],
        # Row 02
        ["TT","GG","GG","RR","RR","GG","GG","GG","GG","GG","GG","TT","TT","TT","TT"],
        # Row 03
        ["TT","TT","TT","RR","RR","SS","SS","SS","TT","TT","TT","TT","TT","TT","TT"],
        # Row 04
        ["TT","TT","TT","RR","RR","RR","RR","RR","GG","GG","GG","TT","TT","TT","TT"],
        # Row 05
        ["TT","TT","TT","SS","SS","RR","RR","RR","GG","GG","GG","TT","TT","TT","TT"],
        # Row 06
        ["TT","TT","TT","TT","TT","RR","RR","SS","SS","SS","SS","TT","TT","TT","TT"],
        # Row 07
        ["TT","TT","TT","TT","TT","GG","GG","RR","RR","RR","RR","TT","TT","TT","TT"],
        # Row 08
        ["TT","TT","TT","TT","TT","GG","GG","GG","GG","GG","RR","TT","TT","TT","TT"],
        # Row 09
        ["TT","TT","TT","TT","TT","GG","GG","GG","GG","GG","RR","TT","TT","TT","TT"],
        # Row 10
        ["TT","TT","TT","TT","TT","SS","GG","GG","GG","GG","RR","TT","TT","TT","TT"],
        # Row 11
        ["TT","TT","TT","TT","TT","SS","RR","RR","RR","RR","RR","RR","RR","TT","TT"],
        # Row 12 — south exit → Thunderplains
        ["TT","TT","TT","TT","TT","TT","TT","TT","TT","TT","TT","EX","EX","TT","TT"],
    ],

    # ── Tile exits ────────────────────────────────────────────
    "exits": {
        # North → Greenwood Town
        "0,3": {"to_zone": "greenwood_town", "to_exit": "greenwood_south_a"},
        "0,4": {"to_zone": "greenwood_town", "to_exit": "greenwood_south_b"},
        # South → Thunderplains
        "12,11": {"to_zone": "thunderplains", "to_exit": "thunderplains_north_a"},
        "12,12": {"to_zone": "thunderplains", "to_exit": "thunderplains_north_b"},
    },

    # ── Exit positions (arrival points from other zones) ──────
    "exit_positions": {
        "route3_north_a": (3, 0),   # arriving from Greenwood south
        "route3_north_b": (4, 0),
        "route3_south_a": (11, 11), # arriving from Thunderplains north
        "route3_south_b": (12, 11),
    },

    # ── NPCs ──────────────────────────────────────────────────
    "npcs": {},

    # ── Signs ─────────────────────────────────────────────────
    "signs": {},
}

