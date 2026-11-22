# ============================================================
# NIFLHEIM — CINDER_HOLLOW_DATA.PY
# Cinder Hollow's floor data, registered into dungeon_data.DUNGEONS.
# Fire/Dark/Ground, old forge-town theme — see cinder_hollow.md for
# full lore/roster notes; this file is the mechanical node graph
# only.
#
# Floor 1 is COMPLETE per the design docs (spine, paths, 20-node
# fixed pool all drafted). Floors 2-4 have confirmed topologies
# (triple fork / linear S-curve / ring loop) but no node breakdown
# yet — NOT included here until that design work is done.
# ============================================================

from dungeon_data import (
    DUNGEONS, DungeonFloor, FixedNode, BatchNode,
    SCOPE_WORLD_ONE_SHOT, SCOPE_WORLD_REPEATABLE, SCOPE_FIRST_CLEAR_BONUS,
)

# ── Floor 1 spine (guaranteed, never rolled) ─────────────────────
FLOOR_1_SPINE = [
    "entrance",
    "fork_former_habitation",
    "treasure_cart",       # North end
    "stairs_down",          # South end
]

# ── Floor 1 paths (critical-path step counts between spine nodes) ─
# Main Access Tunnel: entrance -> fork            (5 nodes)
# North Branch:       fork -> treasure_cart        (15 nodes)
# South Branch:       fork -> south_curve_junction  (9 nodes)
# South Curve:        south_curve_junction -> stairs_down (11 nodes)
#
# South Curve's junction isn't a named spine node in the source docs
# (South Branch and South Curve are drafted as two segments of one
# southbound route) — modeled here as an unnamed waypoint key so the
# path dict stays keyed on real endpoints. Revisit if South Curve
# needs its own spine entry later.
FLOOR_1_PATHS = {
    ("entrance", "fork_former_habitation"): 5,
    ("fork_former_habitation", "treasure_cart"): 15,
    ("fork_former_habitation", "south_curve_junction"): 9,
    ("south_curve_junction", "stairs_down"): 11,
}

# ── Floor 1 fixed pool (20 nodes, competes against batch) ─────────
FLOOR_1_FIXED = {

    # World-level subzones (5)
    "ore_vein": FixedNode(
        "ore_vein",
        "A vein of raw ore glints in the rock face, still warm to the touch.",
        is_subzone=True,
        scope=SCOPE_WORLD_ONE_SHOT,
        tags=["subzone", "gathering"],
    ),
    "hunting_ground_1": FixedNode(
        "hunting_ground_1",
        "The tunnel opens into a wide chamber — good ground for a hunt.",
        is_subzone=True,
        scope=SCOPE_WORLD_REPEATABLE,
        tags=["subzone", "hunting_ground"],
    ),
    "hunting_ground_2": FixedNode(
        "hunting_ground_2",
        "The tunnel opens into a wide chamber — good ground for a hunt.",
        is_subzone=True,
        scope=SCOPE_WORLD_REPEATABLE,
        tags=["subzone", "hunting_ground"],
    ),
    "hunting_ground_3": FixedNode(
        "hunting_ground_3",
        "The tunnel opens into a wide chamber — good ground for a hunt.",
        is_subzone=True,
        scope=SCOPE_WORLD_REPEATABLE,
        tags=["subzone", "hunting_ground"],
    ),
    "abandoned_cart_cache": FixedNode(
        "abandoned_cart_cache",
        "An abandoned mine cart, tipped on its side, still half-loaded.",
        is_subzone=True,
        scope=SCOPE_FIRST_CLEAR_BONUS,
        tags=["subzone", "cache"],
    ),

    # Encounters (3)
    "elite_encounter": FixedNode(
        "elite_encounter",
        "Something far stronger than anything else down here waits ahead.",
        encounter={
            "tier": "elite", "title": None, "level": 15,  # level is a placeholder, not locked in the design docs
            "name": "Cinder Hollow Overseer",  # placeholder name — not drafted in design docs, needed for a battle to display something
            # Placeholder single-mon team — real Elite roster/moveset not
            # yet drafted for Cinder Hollow. Needed so the battle trigger
            # path is exercisable; replace once real content exists.
            "team": [{"name": "Onix", "series": "Pokemon", "level": 15}],
        },
        tags=["encounter", "capstone"],
    ),
    "rare_encounter_pocket": FixedNode(
        "rare_encounter_pocket",
        "A rare sound echoes from just past the bend.",
        encounter={"tier": "rare"},
        tags=["encounter"],
    ),
    "uncommon_encounter_pocket": FixedNode(
        "uncommon_encounter_pocket",
        "Something uncommon stirs nearby.",
        encounter={"tier": "uncommon"},
        tags=["encounter"],
    ),

    # Battle-related (3 distinct nodes — see design notes: originally
    # drafted as 4 slots, one folded into Chained Encounter Zone)
    "chained_encounter_zone": FixedNode(
        "chained_encounter_zone",
        "The Undead Miner rises from the rubble, wishing to be put to "
        "rest after a good battle.",
        encounter={
            "tier": "mini_boss", "title": None, "name": "Undead Miner",
            # Undead Miner's own moveset not yet drafted — only his
            # fielded team is. See cinder_hollow.md for full movesets.
            "team": [
                {"name": "Sandygast", "series": "Pokemon"},
                {"name": "Buried Wraith", "series": "Fantasy"},
                {"name": "Bakemon", "series": "Digimon"},
                {"name": "Cairn Wisp", "series": "Fantasy"},
            ],
        },
        tags=["encounter", "chained", "mini_boss"],
    ),
    "ambush_point": FixedNode(
        "ambush_point",
        "The shadows here feel wrong — like something's already watching.",
        tags=["ambush"],
    ),
    "wounded_weakened_encounter": FixedNode(
        "wounded_weakened_encounter",
        "A Soulbound lies here, already weakened — an easier fight, if "
        "you're willing to take it.",
        encounter={"tier": None, "weakened": True},
        tags=["encounter", "weakened"],
    ),

    # Hazards/utility (3)
    "collapsed_support": FixedNode(
        "collapsed_support",
        "A support beam has given way, blocking part of the passage.",
        tags=["hazard", "trap"],
    ),
    "cave_in_chokepoint": FixedNode(
        "cave_in_chokepoint",
        "The passage narrows to a single collapsed gap — the only way "
        "through to the cart.",
        tags=["hazard", "trap", "chokepoint"],
    ),
    "water_pool": FixedNode(
        "water_pool",
        "Still, dark water pools here, fed by some unseen source.",
        tags=["water"],
    ),

    # Lore/flavor (3)
    "old_forge_remnant": FixedNode(
        "old_forge_remnant",
        "An old forge, long cold, tools still laid out as if someone "
        "meant to come back.",
        is_subzone=True,
        scope="world_one_shot_no_reward",  # true one-shot flavor beat, no mechanical reward — see open note below
        tags=["lore", "one_shot"],
    ),
    "old_miners_rest": FixedNode(
        "old_miners_rest",
        "A carved-out alcove — someone rested here once, a long time ago.",
        tags=["lore"],
    ),
    "old_rail_cart": FixedNode(
        "old_rail_cart",
        "A rusted rail cart sits inert on broken track, going nowhere now.",
        tags=["lore", "inert"],
    ),

    # System (2)
    "signboard_welcome": FixedNode(
        "signboard_welcome",
        "Welcome to Cinder Hollow, reads the signboard.",
        tags=["system", "signboard"],
    ),
    "checkpoint_fork": FixedNode(
        "checkpoint_fork",
        "The air feels a little safer here — a good place to rest.",
        tags=["system", "checkpoint"],
    ),
    # Second Checkpoint — placement (deeper, before Elite Encounter)
    # discussed but not locked. Included as a node so the shape
    # exists, but its position in FLOOR_1_PATHS is not yet decided —
    # do not wire this into placement logic until that's resolved.
    "checkpoint_second": FixedNode(
        "checkpoint_second",
        "The air feels a little safer here — a good place to rest.",
        tags=["system", "checkpoint"],
    ),
}

# NOTE on old_forge_remnant's scope: it's tagged "world_one_shot_no_reward"
# rather than SCOPE_WORLD_ONE_SHOT, since the design docs describe it as
# a pure one-shot LORE beat (not a reward drop like the Ore Vein). If a
# real reward gets attached to it later, switch this to SCOPE_WORLD_ONE_SHOT.

# ── Floor 1 fixed-node branch assignments ─────────────────────────
# Batch nodes are floor-wide (any batch content can roll anywhere on
# the floor, no branch restriction). Fixed nodes are NOT floor-wide —
# each one is assigned to a specific path/branch, per dungeon-system
# memory ("batch node covers the floor, fixed nodes assigned to
# paths"). This is a DRAFT placement — not locked in the source docs,
# reasoned from each node's own flavor text/tags where possible (e.g.
# cave_in_chokepoint's text says "the only way through to the cart" ->
# North Branch; Second Checkpoint's doc note says "deeper, before
# Elite" -> both placed on South Curve, the branch leading to the
# floor exit). Revise freely — this is a starting proposal, not a
# ruling. checkpoint_fork is deliberately NOT included here — it sits
# AT the fork spine node itself, not on any branch.
#
# 40 available slots across 4 branches (5+15+9+11), 19 assignable
# fixed nodes (20 minus checkpoint_fork) — leaves real room for batch
# filler in the gaps, consistent with "fixed competes against batch,
# doesn't replace it."
FLOOR_1_BRANCH_ASSIGNMENTS = {
    ("entrance", "fork_former_habitation"): [
        "signboard_welcome",      # right at the entrance
    ],
    ("fork_former_habitation", "treasure_cart"): [
        "ore_vein",
        "hunting_ground_1",
        "old_forge_remnant",
        "old_rail_cart",
        "cave_in_chokepoint",     # own text: "the only way through to the cart"
        "abandoned_cart_cache",   # sits at/near the cart itself
    ],
    ("fork_former_habitation", "south_curve_junction"): [
        "hunting_ground_2",
        "water_pool",
        "old_miners_rest",
        "wounded_weakened_encounter",
        "uncommon_encounter_pocket",
    ],
    ("south_curve_junction", "stairs_down"): [
        "hunting_ground_3",
        "collapsed_support",
        "ambush_point",
        "rare_encounter_pocket",
        "chained_encounter_zone",  # Undead Miner mini-boss — deeper, tougher branch
        "checkpoint_second",       # doc note: "deeper, before Elite"
        "elite_encounter",         # floor capstone, near the exit
    ],
}


def branch_for_fixed_node(node_id):
    """Which (from_spine_id, to_spine_id) branch a fixed node is assigned to, or None if unassigned (e.g. checkpoint_fork, which sits at the spine fork itself)."""
    for branch, node_ids in FLOOR_1_BRANCH_ASSIGNMENTS.items():
        if node_id in node_ids:
            return branch
    return None


# ── Floor 1 batch pool ─────────────────────────────────────────────
# Content generation method not yet decided (see dungeon_system_logic.md
# open question) — placeholder theme-tagged entries only, no real
# template/word-bank wiring yet.
FLOOR_1_BATCH = [
    BatchNode(theme_tags=["mine", "tunnel"]),
    BatchNode(theme_tags=["mine", "forge"]),
    BatchNode(theme_tags=["mine", "ash"]),
]

FLOOR_1 = DungeonFloor(
    floor_number=1,
    spine=FLOOR_1_SPINE,
    paths=FLOOR_1_PATHS,
    fixed_nodes=FLOOR_1_FIXED,
    batch_pool=FLOOR_1_BATCH,
    branch_assignments=FLOOR_1_BRANCH_ASSIGNMENTS,
)

# ── Trap pool ────────────────────────────────────────────────────
# Not chosen yet — design docs note traps should be environmental/
# industrial hazards (collapsed stonework, old forge machinery)
# rather than "designed" traps, given the forge-town/mining lore.
# Left empty until a real pool is drafted.
CINDER_HOLLOW_TRAP_POOL = []

# ── Encounter roster ────────────────────────────────────────────
# All non-boss encounters roll from ENCOUNTER_TABLES["cinder_hollow"]
# (17 species already built — Fire/Dark/Ground + hybrids) per the
# design docs. The separate "Floor 1 mine-theme roster" drafted in
# cinder_hollow.md (Diglett/Geodude/etc.) is NOT wired in here — the
# docs flag an unresolved mismatch between that roster and Cinder
# Hollow's established Fire/Dark/Ground theme. Resolve that design
# question before populating floor-specific encounter tables.

# ── Registration ─────────────────────────────────────────────────
DUNGEONS["cinder_hollow"] = {
    "name": "Cinder Hollow",
    "theme": "Fire/Dark/Ground",
    "floors": {
        1: FLOOR_1,
        # Floors 2-4: topology confirmed (triple fork / linear
        # S-curve / ring loop per the reference maps) but no node
        # breakdown drafted yet — not registered until that's done.
    },
    "trap_pool": CINDER_HOLLOW_TRAP_POOL,
}
