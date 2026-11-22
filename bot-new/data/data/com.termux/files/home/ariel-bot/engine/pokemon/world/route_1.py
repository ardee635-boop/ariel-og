# ============================================================
# NIFLHEIM — route_1.py
# Route 1 — connects Oak Town (east) to Greenwood Town (west)
# 32×12 grid
# ============================================================

ZONE = {
    "id":           "route_1",
    "name":         "Route 1",
    "zone_type":     "route",
    "danger":       "🟢 Mild",
    "safe":         False,
    "width":        32,
    "height":       12,
    "spawn":        (30, 6),
    "monster_zone": "Route 1",

    "grid": [
        # Row 00
        ["TT","TT","TT","TT","TT","TT","TT","TT","TT","TT","TT","TT","TT","TT","TT","TT","TT","TT","TT","TT","TT","TT","TT","TT","TT","TT","TT","TT","TT","TT","TT","TT"],
        # Row 01
        ["TT","GG","GG","GG","TT","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","GG","GG","GG","TT","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","TT","TT"],
        # Row 02
        ["TT","GG","GG","GG","TT","RR","SG","RR","RR","RR","RR","RR","RR","RR","RR","RR","GG","GG","GG","TT","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","CC","TT"],
        # Row 03
        ["TT","RR","RR","RR","TT","RR","RR","RR","GG","GG","GG","GG","RR","RR","RR","RR","GG","GG","GG","TT","RR","RR","RR","TT","TT","TT","TT","TT","TT","TT","TT","TT"],
        # Row 04
        ["TT","RR","RR","RR","TT","RR","RR","RR","GG","GG","GG","GG","RR","RR","RR","RR","RR","RR","RR","TT","RR","RR","RR","TT","TT","TT","TT","TT","TT","TT","TT","TT"],
        # Row 05
        ["EX","RR","RR","RR","RR","RR","RR","RR","GG","GG","GG","GG","RR","RR","RR","RR","RR","RR","RR","TT","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","EX"],
        # Row 06
        ["EX","RR","RR","RR","RR","RR","RR","RR","GG","GG","GG","GG","RR","RR","RR","RR","RR","RR","RR","TT","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","EX"],
        # Row 07
        ["TT","TT","TT","TT","TT","TT","TT","RR","RR","RR","RR","RR","RR","TT","TT","TT","TT","RR","RR","TT","TT","TT","TT","TT","TT","TT","RR","RR","RR","TT","TT","TT"],
        # Row 08
        ["TT","TT","TT","TT","TT","TT","TT","RR","RR","RR","RR","RR","RR","TT","TT","TT","TT","RR","RR","TT","TT","TT","TT","TT","TT","TT","RR","RR","RR","TT","TT","TT"],
        # Row 09
        ["TT","GG","GG","GG","GG","GG","GG","RR","RR","RR","RR","RR","RR","TT","GG","GG","GG","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","TT","TT","TT"],
        # Row 10
        ["TT","GG","GG","GG","GG","GG","GG","RR","RR","RR","RR","RR","RR","TT","GG","GG","GG","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","TT","TT","TT"],
        # Row 11
        ["TT","TT","TT","TT","TT","TT","TT","TT","TT","TT","TT","TT","TT","TT","TT","TT","TT","TT","TT","TT","TT","TT","TT","TT","TT","TT","TT","TT","TT","TT","TT","TT"],
    ],

    # ── Tile exits ────────────────────────────────────────────
    "exits": {
        "5,0":  {"to_zone": "greenwood_town", "to_exit": "greenwood_east_a"},
        "6,0":  {"to_zone": "greenwood_town", "to_exit": "greenwood_east_b"},
        "5,31": {"to_zone": "oak_town",       "to_exit": "oaktown_west_a"},
        "6,31": {"to_zone": "oak_town",       "to_exit": "oaktown_west_b"},
    },

    # ── Exit positions (arrival points from other zones) ──────
    "exit_positions": {
        "route1_east_a": (30, 5),
        "route1_east_b": (30, 6),
        "route1_west_a": (1, 5),
        "route1_west_b": (1, 6),
    },

    # ── NPCs ──────────────────────────────────────────────────
    "npcs": {},

    # ── Signs ─────────────────────────────────────────────────
    "signs": {
        "2,6": "➡ Oak Town  |  ⬅ Greenwood Town\n_Watch the tall grass._",
    },
}
