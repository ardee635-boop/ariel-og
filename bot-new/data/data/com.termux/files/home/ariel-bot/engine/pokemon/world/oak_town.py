# ============================================================
# NIFLHEIM – OAK_TOWN.PY
# Starter town — safe zone, no encounters
# ============================================================

ZONE = {
    "id":     "oak_town",
    "name":   "Oak Town",
    "zone_type": "town",
    "width":  20,
    "height": 12,

    # ── Grid ─────────────────────────────────────────────────
    # row,col (0-indexed)
    # TT=tree  RR=path  ~~=sea  HH=house  LL=lab  SG=sign
    #
    # B1  row 2  col 4
    # B2  row 2  col 9
    # B3  row 2  col 14
    # B4  row 7  col 4
    # B5  row 7  col 9   (player house)
    # Lab row 7  col 14

    "grid": [
        ["TT","TT","TT","TT","TT","TT","TT","TT","TT","TT","TT","TT","TT","TT","TT","TT","TT","TT","~~","~~"],
        ["TT","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","~~","~~"],
        ["TT","RR","RR","RR","PS","RR","RR","RR","RR","HH","RR","RR","RR","RR","HH","RR","RR","RR","~~","~~"],
        ["TT","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","~~","~~"],
        ["EX","RR","SG","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","~~","~~"],
        ["EX","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","~~","~~"],
        ["TT","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","~~","~~"],
        ["TT","RR","RR","RR","HH","RR","RR","RR","RR","HH","RR","RR","RR","RR","LL","RR","RR","RR","~~","~~"],
        ["TT","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","~~","~~"],
        ["TT","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","~~","~~"],
        ["TT","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","RR","~~","~~"],
        ["TT","TT","TT","TT","TT","TT","TT","TT","TT","TT","TT","TT","TT","TT","TT","TT","TT","TT","~~","~~"],
    ],

    # ── Player spawn ──────────────────────────────────────────
    "spawn": (12, 6),   # (col, row)

    # ── Tile exits ────────────────────────────────────────────
    "exits": {
        "4,0": {"to_zone": "route_1", "to_exit": "route1_east_a"},
        "5,0": {"to_zone": "route_1", "to_exit": "route1_east_b"},
    },

    # ── Exit positions (arrival points from other zones) ──────
    "exit_positions": {
        "oaktown_west_a": (1, 4),
        "oaktown_west_b": (1, 5),
    },

    # ── NPCs (keys = "row,col") ───────────────────────────────
    "npcs": {
        "3,4": {
            "id":     "oak_npc_1",
            "name":   "Townsperson",
            "dialog": [
                "Welcome to Oak Town, traveller!",
                "The Pokélab is just down the road — you can't miss it.",
            ],
        },
        "2,16": {
            "id":     "oak_npc_3",
            "name":   "Townsperson",
            "dialog": [
                "The sea stretches east as far as the eye can see.",
                "Nobody swims it. Not anymore.",
            ],
        },
        "8,9": {
            "id":     "oak_npc_5",
            "name":   "Rival",
            "dialog": [
                "Oh, you finally woke up.",
                "I'm heading to the lab first. Don't be slow.",
            ],
        },
        "7,15": {
            "id":     "prof_oak_assistant",
            "name":   "Lab Assistant",
            "dialog": [
                "The Professor is inside.",
                "He's been expecting a new trainer.",
            ],
        },
    },

    # ── Signposts (keys = "row,col") ──────────────────────────
    "signs": {
        "4,2":  "➡ Route 1\n_The wilds begin beyond this point._",
        "8,11": "📍 Oak Town\n_Population: 6_\n_A quiet town where it all begins._",
        "7,14": "𓏺🜔 Pokélab\n_Prof. Oak's research facility._\n_Starters given here._",
    },

    # ── Buildings ─────────────────────────────────────────────
    "buildings": {
        "HH": "oak_house_interior",
        "LL": "oak_lab_interior",
    },
}

