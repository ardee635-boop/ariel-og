"""Pokemon: encounter tables (split from encounters.py)."""


# ── Star reward multipliers ───────────────────────────────────
STAR_MULTIPLIER = {
    1: 1.0, 2: 1.2, 3: 1.5, 4: 1.8,  5: 2.2,
    6: 2.6, 7: 3.1, 8: 3.6, 9: 4.3, 10: 5.0,
}

# ── Status catch bonuses ──────────────────────────────────────
STATUS_CATCH_BONUS = {
    None:        0.00,
    "burn":      0.05,
    "bleed":     0.04,
    "poison":    0.05,
    "paralysis": 0.08,
    "sleep":     0.15,
    "freeze":    0.15,
}

# ── Ball catch bonuses ────────────────────────────────────────
BALL_CATCH_BONUS = {
    "Poké Ball":   0.10,
    "Great Ball":  0.25,
    "Ultra Ball":  0.40,
    "Master Ball": 1.00,
    # Elemental type balls — one per type, +0.15 vs matching type
    "Pyro Ball":    0.15,
    "Cryo Ball":    0.15,
    "Atmo Ball":    0.15,
    "Floro Ball":   0.15,
    "Volt Ball":    0.15,
    "Aether Ball":  0.15,
    "Aqua Ball":    0.15,
    "Brawn Ball":   0.15,
    "Toxic Ball":   0.15,
    "Terra Ball":   0.15,
    "Psy Ball":     0.15,
    "Swarm Ball":   0.15,
    "Crag Ball":    0.15,
    "Phantom Ball": 0.15,
    "Wyrm Ball":    0.15,
    "Umbra Ball":   0.15,
    "Alloy Ball":   0.15,
    "Fae Ball":     0.15,
    "Random Ball":  0.15,   # bonus applies vs a type rolled at throw time
}

# Special ball type affinity — bonus only applies to matching type(s).
# Cryo Ball covers both ice and water (frost/frozen-water theming).
BALL_TYPE_AFFINITY = {
    "Pyro Ball":    ["fire"],
    "Cryo Ball":    ["ice", "water"],
    "Atmo Ball":    ["flying"],
    "Floro Ball":   ["grass"],
    "Volt Ball":    ["electric"],
    "Aether Ball":  ["normal"],
    "Aqua Ball":    ["water"],
    "Brawn Ball":   ["fighting"],
    "Toxic Ball":   ["poison"],
    "Terra Ball":   ["ground"],
    "Psy Ball":     ["psychic"],
    "Swarm Ball":   ["bug"],
    "Crag Ball":    ["rock"],
    "Phantom Ball": ["ghost"],
    "Wyrm Ball":    ["dragon"],
    "Umbra Ball":   ["dark"],
    "Alloy Ball":   ["steel"],
    "Fae Ball":     ["fairy"],
    # Random Ball has no fixed affinity — resolved at throw time by
    # rolling a random type and checking against that roll instead.
}

ALL_TYPES = [
    "normal", "fire", "water", "electric", "grass", "ice",
    "fighting", "poison", "ground", "flying", "psychic", "bug",
    "rock", "ghost", "dragon", "dark", "steel", "fairy",
]

# ── Encounter tables ──────────────────────────────────────────

# Zone spawn positions — (col, row) — middle of a walkable RR area
# Used by .quicktravel and registration to place players
ZONE_SPAWNS = {
    "oak_town":      (12, 11),
    "greenwood_town":(10, 10),
    "fauna":         (1,  5),
    "route_1":       (25, 5),
    "route_2":       (6, 12),
    "route_3":       (6, 12),
    "thunderplains": (9, 17),
    "oceana":        (16, 9),   # port area
}

ENCOUNTER_TABLES = {
    "fauna": {
        "grass": [
            # Very Common
            ("caterpie",      40),
            ("weedle",        38),
            ("oddish",        35),
            ("bellsprout",    32),
            ("spinarak",      30),
            ("wurmple",       28),
            ("exeggcute",     25),
            # Common
            ("paras",         20),
            ("venonat",       18),
            ("ekans",         16),
            ("nidoran-f",     15),
            ("nidoran-m",     15),
            ("hoppip",        14),
            ("sunkern",       13),
            ("ledyba",        12),
            # Uncommon
            ("metapod",       10),
            ("kakuna",        10),
            ("gloom",          9),
            ("weepinbell",     9),
            ("bayleef",        8),
            ("chikorita",      8),
            ("natu",           7),
            ("aipom",          7),
            ("butterfree",     7),
            ("beedrill",       7),
            ("roselia",        6),
            ("sunflora",       6),
            # Rare
            ("parasect",       5),
            ("venomoth",       5),
            ("tangela",        4),
            ("victreebel",     3),
            ("ariados",        3),
            ("bulbasaur",      3),
            ("yanma",          3),
            ("tropius",        2),
            ("scyther",        2),
            # Very Rare
            ("pinsir",         2),
            ("heracross",      2),
            ("celebi",         1),
        ],
        "level_range": [8, 20],
    },
    "thunderplains": {
        "grass": [
            # Common — Electric
            ("helioptile",    30),
            ("joltik",        28),
            ("pawmo",         25),
            ("raichu",        20),
            # Common — Ground
            ("diglett",       26),
            ("sandile",       22),
            ("phanpy",        20),
            # Uncommon — Electric
            ("emolga",        12),
            ("togedemaru",    11),
            ("stunfisk",      10),
            ("toxtricity",     9),
            ("pawmot",         9),
            ("magneton",       8),
            # Uncommon — Ground
            ("trapinch",      14),
            ("baltoy",        13),
            ("numel",         12),
            ("cacnea",        11),
            ("hippopotas",    10),
            ("drilbur",       10),
            ("mudbray",        9),
            ("silicobra",      9),
            ("nincada",        8),
            # Rare — Electric
            ("galvantula",     4),
            ("heliolisk",      4),
            ("kilowattrel",    3),
            ("morpeko",        3),
            ("electabuzz",     3),
            # Rare — Ground
            ("gligar",         4),
            ("onix",           4),
            ("marowak",        3),
            # Very Rare
            ("sandy-shocks",   1),
            ("iron-thorns",    1),
            ("vikavolt",       1),
            ("jolteon",        1),
        ],
    },
        "route_3": {
        "grass": [
            # Common
            ("rattata",       35),
            ("sentret",       30),
            ("caterpie",      28),
            ("weedle",        28),
            ("ledyba",        25),
            ("diglett",       22),
            ("sandshrew",     20),
            # Uncommon
            ("spinarak",      12),
            ("venonat",       12),
            ("geodude",       10),
            ("cubone",         9),
            ("jigglypuff",     8),
            # Rare
            ("scyther",        4),
            ("pinsir",         4),
            ("rhyhorn",        3),
            ("lickitung",      3),
            # Very Rare
            ("marowak",        2),
            ("larvitar",       1),
            ("chansey",        1),
        ],
    },
        "route_1": {
        "grass": [
            # Common
            ("weedle",      40),
            ("rattata",     35),
            ("caterpie",    20),
            ("pidgey",      20),
            ("meowth",      18),
            ("sentret",     18),
            ("venonat",     16),
            ("diglett",     15),
            ("sandshrew",   15),
            ("exeggcute",   14),
            # Uncommon
            ("spearow",     12),
            ("oddish",      10),
            ("paras",       10),
            ("bellsprout",   8),
            ("ekans",        8),
            ("tangela",      8),
            ("hoppip",       8),
            ("ledyba",       8),
            ("spinarak",     8),
            ("geodude",      7),
            # Rare
            ("mankey",       6),
            ("jigglypuff",   5),
            ("nidoran-f",    4),
            ("nidoran-m",    4),
            ("lickitung",    4),
            ("rhyhorn",      3),
            ("pinsir",       3),
            ("eevee",        2),
            ("chansey",      2),
            # Very rare
            ("scyther",      2),
        ],
        "water": [
            ("magikarp",   60),
            ("poliwag",    30),
            ("tentacool",  10),
        ],
        "level_range": [1, 8],
    },
    "oceana": {
        "grass": [
            ("wingull",       35),
            ("azurill",       32),
        ],
        "water": [
            # Very Common
            ("magikarp",      65),
            ("tentacool",     60),
            ("poliwag",       58),
            ("krabby",        55),
            ("horsea",        52),
            ("goldeen",       50),
            ("wooper",        48),
            ("lotad",         45),
            ("basculin",      42),
            # Common
            ("staryu",        38),
            ("shellder",      36),
            ("psyduck",       34),
            ("slowpoke",      32),
            ("corphish",      30),
            ("wingull",       28),
            ("barboach",      27),
            ("spheal",        26),
            ("tympole",       25),
            ("frillish",      24),
            # Uncommon
            ("marill",        18),
            ("chinchou",      17),
            ("remoraid",      16),
            ("carvanha",      15),
            ("wailmer",       15),
            ("feebas",        14),
            ("clamperl",      14),
            ("finneon",       13),
            ("buizel",        13),
            ("shellos",       12),
            ("surskit",       12),
            ("palpitoad",     11),
            ("sealeo",        11),
            ("luvdisc",       10),
            ("panpour",       10),
            ("mantyke",       10),
            ("alomomola",      9),
            ("dewgong",        9),
            # Rare
            ("poliwhirl",      8),
            ("slowbro",        7),
            ("seel",           7),
            ("lapras",         6),
            ("squirtle",       6),
            ("totodile",       6),
            ("mudkip",         5),
            ("oshawott",       5),
            ("popplio",        5),
            ("wailord",        5),
            ("seismitoad",     5),
            ("walrein",        4),
            ("jellicent",      4),
            ("mantine",        4),
            ("qwilfish",       4),
            ("simipour",       4),
            ("wishiwashi",     4),
            # Very Rare
            ("vaporeon",       3),
            ("gyarados",       3),
            ("milotic",        3),
            ("kingdra",        3),
            ("dragalge",       2),
            ("sharpedo",       2),
            ("starmie",        2),
            ("lanturn",        2),
            ("empoleon",       2),
            ("samurott",       2),
            ("cloyster",       2),
            ("toxapex",        2),
            ("golisopod",      2),
            ("araquanid",      2),
            ("pyukumuku",      2),
            # Ultra Rare
            ("suicune",        1),
            ("kyogre",         1),
            ("manaphy",        1),
            ("palkia",         1),
            ("lugia",          1),
            ("tirtouga",       1),
            ("relicanth",      1),
            ("clawitzer",      1),
            ("barraskewda",    1),
            ("basculegion",    1),
            ("overqwil",       1),
            ("dewpider",       1),
            ("frogadier",      1),
            ("greninja",       1),
            ("primarina",      1),
            ("dhelmise",       1),
            ("cramorant",      1),
            ("bruxish",        1),
            ("kingler",        1),
            ("crawdaunt",      1),
        ],
        "level_range": [5, 22],
    },
    "ember_path": {
        "grass": [
            # Very Common
            ("vulpix",        40),
            ("sandshrew",     38),
            ("cubone",        35),
            ("houndour",      30),
            ("larvitar",      28),
            # Common
            ("growlithe",     20),
            ("numel",         18),
            ("skorupi",       16),
            ("baltoy",        15),
            ("drilbur",       14),
            # Uncommon — hybrids
            ("houndoom",       9),   # fire/dark
            ("mudbray",        9),   # ground
            ("torkoal",        8),
            ("phanpy",         8),
            ("nincada",        7),   # ground/bug, borderline hybrid
            # Rare — hybrids
            ("salandit",       4),   # poison/fire, close enough flavor
            ("gligar",         3),   # ground/flying
            ("sandile",        3),   # ground/dark — direct hybrid hit
            ("krokorok",       2),
            # Very Rare
            ("darumaka",       2),
            ("typhlosion",     1),
        ],
        "level_range": [2, 6],
    },
    "cinder_hollow": {
        "grass": [
            # Very Common
            ("houndour",      38),
            ("sandile",       35),
            ("cubone",        32),
            ("numel",         28),
            # Common
            ("houndoom",      20),
            ("krokorok",      18),
            ("torkoal",       16),
            ("gligar",        15),
            ("skorupi",       14),
            # Uncommon
            ("drilbur",       10),
            ("excadrill",      8),
            ("marowak",        8),
            ("gliscor",        6),
            ("salandit",       6),
            # Rare — hybrids
            ("krookodile",     4),   # ground/dark
            ("camerupt",       3),
            ("salazzle",       3),
            # Very Rare
            ("typhlosion",     2),
            ("tyranitar",      1),
        ],
        "level_range": [5, 10],
    },
    "elmwood_trail": {
        "grass": [
            # Very Common
            ("bellsprout",    40),
            ("hoppip",        38),
            ("lillipup",      35),
            ("rattata",       32),
            # Common
            ("mankey",        20),
            ("bunnelby",      18),
            ("sunkern",       16),
            ("skiddo",        15),
            # Uncommon
            ("nidoran-f",     10),
            ("nidoran-m",     10),
            ("machop",         8),
            ("cottonee",       7),
            # Rare
            ("primeape",       3),
            ("makuhita",       2),
        ],
        "level_range": [2, 6],
    },
    "elmwood_farm": {
        "grass": [
            # Very Common
            ("tauros",        35),
            ("miltank",       32),
            ("lillipup",      30),
            ("bellsprout",    28),
            # Common
            ("mankey",        20),
            ("skiddo",        18),
            ("bunnelby",      16),
            ("herdier",       12),
            # Uncommon
            ("machop",        10),
            ("primeape",       6),
            ("girafarig",      6),
            # Rare
            ("machoke",        3),
            ("makuhita",       3),
            ("hariyama",       1),
        ],
        "level_range": [4, 9],
    },
}

# ── Zone border-crossing time (Phase 4 — .explore travel time) ─
# Total travel time between two zones = origin border + destination
# border. Placeholder-by-type defaults; override per-zone as needed.
ZONE_BORDER_TIME = {
    "oak_town":        5,   # town
    "ashfall_village": 5,   # town
    "ember_path":      7,   # route
    "cinder_hollow":   10,  # dungeon
    "elmwood_trail":   20,  # route (override — not the 7s default)
    "elmwood_farm":    20,  # route (override — not the 7s default)
    "elmwood":         15,  # town (override — not the 5s default)
}

# ── .explore destination tables (Phase 4, weighted random) ─────
# Shape: { zone: { direction: [ {"to", "weight", "time_s"}, ... ] } }
# time_s = ZONE_BORDER_TIME[origin] + ZONE_BORDER_TIME[to]
EXPLORE_DESTINATIONS = {
    "oak_town": {
        "north": [
            {"to": "ashfall_village", "weight": 50, "time_s": 10},
            {"to": "elmwood_trail",   "weight": 50, "time_s": 25},
        ],
        # west is the existing frozen Route 1 link (Phase 1) — not
        # part of this table yet
        # east: undecided, not dead-ended yet
    },
    "ashfall_village": {
        "north": [
            {"to": "ember_path", "weight": 100, "time_s": 12},
        ],
        "south": [
            {"to": "oak_town", "weight": 100, "time_s": 10},
        ],
        # east/west: no destination defined — dead-end fallback,
        # round trip takes ZONE_BORDER_TIME["ashfall_village"]
        # (5s) each way
    },
    "ember_path": {
        "north": [
            {"to": "cinder_hollow", "weight": 100, "time_s": 17},
        ],
        "south": [
            {"to": "ashfall_village", "weight": 100, "time_s": 12},
        ],
        # east/west: no destination defined — dead-end fallback,
        # round trip takes ZONE_BORDER_TIME["ember_path"]
        # (7s) each way
    },
    "cinder_hollow": {
        "south": [
            {"to": "ember_path", "weight": 100, "time_s": 17},
        ],
        # north/east/west: not yet defined — expand later
    },
    "elmwood_trail": {
        "north": [
            {"to": "elmwood_farm", "weight": 100, "time_s": 40},
        ],
        "south": [
            {"to": "oak_town", "weight": 100, "time_s": 25},
        ],
    },
    "elmwood_farm": {
        "north": [
            {"to": "elmwood", "weight": 100, "time_s": 35},
        ],
        "south": [
            {"to": "elmwood_trail", "weight": 100, "time_s": 40},
        ],
    },
    "elmwood": {
        "south": [
            {"to": "elmwood_farm", "weight": 100, "time_s": 35},
        ],
        # north/east/west: not yet defined — expand later
    },
}

# ── Encounter chance system ───────────────────────────────────
BASE_ENCOUNTER_CHANCE = 0.15   # 15% base per grass step

STEP_INCREMENT        = 0.04   # +4% per consecutive grass step

RESPITE_STEPS         = 1      # free steps after an encounter
