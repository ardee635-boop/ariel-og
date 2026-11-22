# ============================================================
# NIFLHEIM — route_2.py
# Route 2 — north of Greenwood Town
# 10×15 grid
#
# Built from the T-junction map: two north/south exits, a central
# path with a side branch leading to a cave entrance, and a T-spawn
# marker on the return leg of the branch.
#
# Road tiles (RR) here are plain walkable path — no wild encounters,
# per design. Spawn table + level range already exist in
# data_pokemon.py under "route_2", ready for whenever the cave or a
# grass patch is added — this file's grid is road-only for now.
# ============================================================

ZONE = {
    "id":           "route_2",
    "name":         "Route 2",
    "zone_type":    "route",
    "danger":       "🟢 Low",
    "safe":         True,   # road-only, no wild encounters yet
    "width":        10,
    "height":       15,
    "spawn":        (5, 6),
    "monster_zone": "Route 2",

    "grid": [
        # Row 00 — north exit → (future zone north of Route 2)
        ["TT","TT","TT","TT","TT","EX","EX","TT","TT","TT"],
        # Row 01
        ["TT","TT","TT","TT","TT","RR","RR","TT","TT","TT"],
        # Row 02
        ["TT","TT","TT","TT","TT","RR","RR","TT","TT","TT"],
        # Row 03
        ["TT","TT","TT","TT","TT","RR","RR","TT","TT","TT"],
        # Row 04
        ["TT","TT","TT","TT","TT","RR","RR","TT","TT","TT"],
        # Row 05
        ["TT","TT","RR","RR","RR","RR","RR","TT","TT","TT"],
        # Row 06
        ["TT","TT","RR","RR","RR","RR","RR","TT","TT","TT"],
        # Row 07 — cave entrance branch
        ["TT","TT","RR","RR","TT","TT","TT","CV","TT","TT"],
        # Row 08
        ["TT","TT","RR","RR","TT","TT","TT","RR","TT","TT"],
        # Row 09
        ["TT","TT","RR","RR","TT","TT","TT","RR","TT","TT"],
        # Row 10
        ["TT","TT","RR","RR","RR","RR","RR","RR","TT","TT"],
        # Row 11
        ["TT","TT","RR","RR","RR","RR","RR","TT","TT","TT"],
        # Row 12 — T-junction (also the quicktravel/respawn landing point — see ZONE_SPAWNS in encounters.py)
        ["TT","TT","TT","TT","TT","RR","RR","TT","TT","TT"],
        # Row 13
        ["TT","TT","TT","TT","TT","RR","RR","TT","TT","TT"],
        # Row 14 — south exit → Greenwood Town
        ["TT","TT","TT","TT","TT","EX","EX","TT","TT","TT"],
    ],

    # ── Tile exits ────────────────────────────────────────────
    "exits": {
        # South → Greenwood Town
        "14,5": {"to_zone": "greenwood_town", "to_exit": "greenwood_north_a"},
        "14,6": {"to_zone": "greenwood_town", "to_exit": "greenwood_north_b"},
        # North exit left open — no zone built past here yet.
        # "0,5": {"to_zone": "???", "to_exit": "???"},
        # "0,6": {"to_zone": "???", "to_exit": "???"},
        # Cave entrance left open — new cave zone not built yet.
        # "7,7": {"to_zone": "???", "to_exit": "???"},
    },

    # ── Exit positions (arrival points from other zones) ──────
    "exit_positions": {
        "route2_south_a": (5, 13),  # arriving from Greenwood north
        "route2_south_b": (6, 13),
    },

    # ── NPCs ──────────────────────────────────────────────────
    "npcs": {},

    # ── Signs ─────────────────────────────────────────────────
    "signs": {},
}
