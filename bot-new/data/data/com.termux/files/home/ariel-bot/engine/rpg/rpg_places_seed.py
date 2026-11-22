# ============================================================
# ARIEL — RPG_PLACES_SEED.PY  (Layer 6 of the movement/location rewrite)
#
# Builds the full hand-authored world tree using rpg_places.build_place
# and persists it via database.py's rpg_places/rpg_passages tables.
# This is the ONLY place the hand-authored tree is defined from here
# on — rpg_locations.py's seven dicts are the OLD source and are not
# read by this module; every fact below was re-entered by hand from
# this session's decisions, not copy-pasted from the old file, per
# decision #4 ("even the hardcoded places should be rewritten, leave
# no stone unturned").
#
# This is also exactly what `.resetworld` calls to re-seed the
# hardcoded tier after wiping (database.py's reset_world() only
# wipes — it doesn't know how to rebuild; that's this module's job).
#
# CHANGES FROM THE OLD rpg_locations.py DATA (this session's
# decisions, not carried over silently):
#   - East District's Location is renamed/reframed as "the market" —
#     it's the real place you arrive at, not a district label with
#     "Shops"/"Business Quarter" landmark strings (both dropped,
#     redundant with the rename).
#   - West District: Coliseum and Adventurers' Guild PROMOTED to
#     their own Locations (fail promotion rule #1 — each is its own
#     place elsewhere in the district, not physically at a shared
#     Location the way a fountain sits in a square).
#   - noble_district DELETED entirely (explicit instruction) — it
#     only ever existed to hold the garden shop, which has moved.
#   - townia_garden_shop (Odalys, the greenhouse, full existing
#     description — UNCHANGED content) moved from noble_district to
#     south_district as its new parent.
#   - northern_gate's landmark list restructured: "the gate guards"
#     is an NPC, not a place — moved out, belongs in rpg_world_npcs,
#     NOT seeded here (this module only seeds Places/Passages). "the
#     north gate" becomes a real Landmark; "the outpost/guard tower"
#     becomes a Feature nested under it, since that's where the
#     guards are actually stationed. "Barrel of crude weapons" is an
#     interactive object, not a place — not seeded here either (it
#     belongs wherever scene_objects/gatherable items are seeded).
#   - townia_pet_shop's redundant self-referential "Pet Shop" landmark
#     (a Location naming itself as its own landmark) dropped.
#   - "Lodging" (south_district) left as a plain Landmark — nothing
#     about it met any of the four promotion criteria.
# ============================================================

from rpg_places import build_place, Place


def build_world_tree() -> list[Place]:
    """
    Returns every Place in the hand-authored tree, in an order safe
    to insert directly (parents always appear before children — the
    order this list is built in IS a valid insert order, not
    something the caller needs to sort). Does not touch the database
    itself — see seed_hardcoded_tree() below for that.
    """
    places: list[Place] = []

    def add(p: Place) -> Place:
        places.append(p)
        return p

    # ── Tiers 1-6: Dimension through Area ────────────────────────
    dimension = add(build_place(id="townia_dim", tier="dimension", name="Townia", parent=None))
    continent = add(build_place(id="continent_1", tier="continent", name=None, parent=dimension))
    region = add(build_place(id="region_1", tier="region", name=None, parent=continent))
    nation = add(build_place(id="nation_1", tier="nation", name=None, parent=region))
    state = add(build_place(id="state_1", tier="state", name=None, parent=nation))
    townia_area = add(build_place(
        id="townia", tier="area", name="Townia", parent=state,
        area_type="settlement", settlement_size="town", subdivision="district",
    ))
    dark_forest_area = add(build_place(
        id="dark_forest", tier="area", name="the Dark Forest", parent=state,
        area_type="forest", subdivision="ring",
    ))

    # ── Center District — square, church, library, shrine ───────
    center_district = add(build_place(id="center_district", tier="district", name="Center", parent=townia_area))
    square = add(build_place(
        id="townia_square", tier="location", name="the town square", parent=center_district,
        description=("The open heart of Townia. Paths lead off to the church, the library, "
                     "the shrine, the market, the West and South Districts, and the "
                     "northern gate."),
    ))
    add(build_place(
        id="townia_church", tier="location", name="the church", parent=center_district,
        description=("The Church of Beginnings, a quiet stone hall just off the square, "
                     "where those cursed with the Twin Gods' mark come to be guided."),
    ))
    add(build_place(
        id="townia_library", tier="location", name="the library", parent=center_district,
        description=("The town library, tall shelves of old books and a hush that swallows "
                     "footsteps. It is the site of the mage's trial."),
        offers_trial="mage",
    ))
    add(build_place(
        id="townia_shrine", tier="location", name="the shrine beyond the square",
        parent=center_district,
        description=("A small, quiet shrine tucked just past the square — worn "
                      "stone, old offerings, the noise of the town fading out "
                      "behind you."),
    ))

    # ── East District — now "the market" itself, per this session ──
    east_district = add(build_place(id="east_district", tier="district", name="East", parent=townia_area))
    market = add(build_place(
        id="townia_market", tier="location", name="the market", parent=east_district,
        description="The capital's market — stalls, traders, the noise of business.",
    ))
    add(build_place(
        id="townia_pet_shop", tier="location", name="the pet shop", parent=east_district,
        description="Rows of pens and cages, alive with restless animal noise.",
        offers_trial="summoner",
    ))

    # ── West District — Coliseum + Guild PROMOTED to real Locations ──
    west_district = add(build_place(id="west_district", tier="district", name="West", parent=townia_area))
    west_road = add(build_place(
        id="west_district_road", tier="location", name="the West District",
        parent=west_district,
        description="A road through Townia's West District, the Coliseum and the Adventurers' Guild both within sight.",
    ))
    coliseum = add(build_place(
        id="coliseum", tier="location", name="the Coliseum", parent=west_district,
        description="A real arena, its stands rising over the West District — the site of the warrior's trial.",
        offers_trial="warrior",
    ))
    add(build_place(
        id="coliseum_lobby", tier="landmark", name="the lobby", parent=coliseum,
        description="The Coliseum's entrance hall, where challengers wait to be called.",
    ))
    add(build_place(
        id="adventurers_guild", tier="location", name="the Adventurers' Guild",
        parent=west_district,
        description="Townia's guild hall — quest boards, worn maps, the low talk of travelers between jobs.",
    ))

    # ── South District — Lodging (landmark) + the garden shop (moved here) ──
    south_district = add(build_place(id="south_district", tier="district", name="South", parent=townia_area))
    add(build_place(
        id="south_district_road", tier="location", name="the South District",
        parent=south_district,
        description="Where travelers find lodging.",
    ))
    add(build_place(
        id="south_district_lodging", tier="location", name="Lodging",
        parent=south_district,
        description=("A warm common room of low beams, worn tables and the smell "
                     "of woodsmoke, with narrow stairs to the rooms above."),
    ))
    garden_shop = add(build_place(
        id="townia_garden_shop", tier="location", name="the garden shop",
        parent=south_district,
        description=("A small greenhouse tucked behind the hedgerows, tended "
                      "by an old gardener named Odalys. Rows of potted "
                      "saplings and drying herbs line the shelves — nothing "
                      "much happens here yet, but she's always glad for the "
                      "company."),
    ))
    add(build_place(
        id="townia_greenhouse", tier="landmark", name="the greenhouse",
        parent=garden_shop,
    ))

    # ── North — noble_district DELETED. northern_gate is the sole
    # North-side place, restructured with a real Landmark + Feature. ──
    north_district = add(build_place(id="north_district", tier="district", name="North", parent=townia_area))
    north_road = add(build_place(
        id="northern_gate", tier="location", name="the northern gate",
        parent=north_district,
        description=("The town's entrance, manned by two guards who watch cursed "
                      "children with open distrust. Before letting anyone pass, "
                      "they gesture to a barrel of crude weapons for the traveler "
                      "to pick from."),
    ))
    gate_landmark = add(build_place(
        id="north_gate_landmark", tier="landmark", name="the north gate",
        parent=north_road,
    ))
    add(build_place(
        id="north_gate_outpost", tier="feature", name="the outpost / guard tower",
        parent=gate_landmark,
        description="Where the gate guards are actually stationed, watching the road.",
    ))

    # ── Dark Forest — outer/inner/deep rings, unchanged from the old data ──
    outer = add(build_place(
        id="outer_forest", tier="district", name="Outer Ring", parent=dark_forest_area,
    ))
    outer_loc = add(build_place(
        id="outer_forest_road", tier="location", name="the Dark Forest — outer ring",
        parent=outer,
        description=("The outermost ring of the Dark Forest, circling Townia "
                      "just past the northern gate. A dirt track cuts north "
                      "through it, deeper into the trees."),
        max_level=5, monster_pool="Wolf, Boar, Giant Rat, Kobold, Goblin",
    ))
    inner = add(build_place(
        id="inner_forest", tier="district", name="Inner Ring", parent=dark_forest_area,
    ))
    inner_loc = add(build_place(
        id="inner_forest_road", tier="location", name="the Dark Forest — inner ring",
        parent=inner,
        description="Deeper into the Dark Forest. The trees grow thicker and the light dimmer than the outer ring.",
        max_level=10, monster_pool="Dire Wolf, Giant Boar, Black Bear, Giant Spider, Hobgoblin, Bugbear",
    ))
    deep = add(build_place(
        id="deep_forest", tier="district", name="Deep Forest", parent=dark_forest_area,
    ))
    deep_loc = add(build_place(
        id="deep_forest_road", tier="location", name="the Dark Forest — deep forest",
        parent=deep,
        description=("The innermost ring of the Dark Forest. The dirt track "
                      "continues north from here, straight to the edge of "
                      "the dimension itself — impassable, however far it's followed."),
        max_level=15, monster_pool="Brown Bear, Owlbear, Darkmantle, Giant Wolf Spider, Ogre, Gnoll",
    ))

    # ══════════════════════════════════════════════════════════════
    # TOWNIA ADDITIONS (Townia is a CLOSED world: the narrator may not
    # invent places here — everything a visitor can name exists below)
    # ══════════════════════════════════════════════════════════════
    t_area   = next(p for p in places if p.id == "townia")
    t_state  = next(p for p in places if p.id == "state_1")
    t_square = next(p for p in places if p.id == "townia_square")
    t_church = next(p for p in places if p.id == "townia_church")
    t_shrine = next(p for p in places if p.id == "townia_shrine")
    t_east   = next(p for p in places if p.id == "east_district")
    t_west   = next(p for p in places if p.id == "west_district")
    t_south  = next(p for p in places if p.id == "south_district")
    t_guild  = next(p for p in places if p.id == "adventurers_guild")

    # ── Center: landmarks ────────────────────────────────────────
    add(build_place(
        id="townia_waking_stone", tier="landmark", name="the waking stone", parent=t_square,
        description="A flat pale stone in the middle of the square, always faintly warm.",
    ))
    add(build_place(
        id="townia_bell_tower", tier="landmark", name="the bell tower", parent=t_church,
        description="A narrow stone tower above the church whose single bell rings at no fixed hour.",
    ))
    add(build_place(
        id="townia_twin_altar", tier="landmark", name="the twin altar", parent=t_shrine,
        description="A low altar split in two halves, one dark and one pale, with small offerings on both.",
    ))

    # ── East: apothecary, storehouse ─────────────────────────────
    add(build_place(
        id="townia_apothecary", tier="location", name="the apothecary", parent=t_east,
        description="Shelves of small glass jars and bundled herbs fill a narrow room that smells of mint and warm wax.",
    ))
    add(build_place(
        id="townia_storehouse", tier="location", name="the storehouse", parent=t_east,
        description="A long stone hall of numbered shelves and heavy wooden doors, cool and very still.",
    ))

    # ── West: training yard, smithy, quest board ─────────────────
    add(build_place(
        id="townia_training_yard", tier="location", name="the training yard", parent=t_west,
        description="A packed-earth yard ringed by straw dummies and racks of blunt practice weapons, the air thick with dust.",
    ))
    add(build_place(
        id="townia_smithy", tier="location", name="the smithy", parent=t_west,
        description="A low forge glowing orange, the ring of hammers loud against the quiet of the rest of town.",
    ))
    add(build_place(
        id="townia_quest_board", tier="landmark", name="the quest board", parent=t_guild,
        description="A broad board of weathered wood crowded with pinned notices.",
    ))

    # ── South: bathhouse, quiet garden (Lodging is promoted in the
    #    existing South District block — see the CHANGED note) ─────
    add(build_place(
        id="townia_bathhouse", tier="location", name="the bathhouse", parent=t_south,
        description="Warm stone, rising steam and the soft echo of water in a high-ceilinged room.",
    ))
    add(build_place(
        id="townia_quiet_garden", tier="location", name="the quiet garden", parent=t_south,
        description="A walled garden of benches and slow paths where nothing moves but leaves.",
    ))

    # ── The Wall: a district of four corner towers ───────────────
    t_wall = add(build_place(id="townia_wall", tier="district", name="Wall", parent=t_area))
    add(build_place(
        id="townia_tower_ne", tier="location", name="the northeast tower", parent=t_wall,
        description="A square stone tower at the town's northeast corner, wind whistling through its narrow slits.",
    ))
    add(build_place(
        id="townia_tower_se", tier="location", name="the southeast tower", parent=t_wall,
        description="A lookout at the southeast corner, where the wall turns and the town's rooftops spread out below.",
    ))
    add(build_place(
        id="townia_tower_sw", tier="location", name="the southwest tower", parent=t_wall,
        description="A squat tower at the southwest corner, its stairs worn smooth in the middle.",
    ))
    add(build_place(
        id="townia_tower_nw", tier="location", name="the northwest tower", parent=t_wall,
        description="A tall tower at the northwest corner, the road to the gate visible far below.",
    ))

    # ── Outside the wall: four new areas under state_1, siblings of
    #    the Dark Forest. subdivision is left unset, so each area's
    #    locations attach straight to the area (the district rung is
    #    skipped, which build_place allows). ───────────────────────
    lake_area = add(build_place(
        id="townia_lake", tier="area", name="the lake basin", parent=t_state, area_type="lake",
    ))
    lakeshore = add(build_place(
        id="townia_lakeshore", tier="location", name="the lakeshore", parent=lake_area,
        description="Still, dark water stretches out beyond a pebbled shore, mist hanging low over it.",
    ))
    add(build_place(
        id="townia_old_pier", tier="landmark", name="the old pier", parent=lakeshore,
        description="A weathered wooden pier running a short way out into the water.",
    ))

    falls_area = add(build_place(
        id="townia_waterfall", tier="area", name="the waterfall valley", parent=t_state, area_type="waterfall",
    ))
    add(build_place(
        id="townia_falls_pool", tier="location", name="the waterfall pool", parent=falls_area,
        description="A wide pool churns beneath a tall waterfall, the roar of it filling the air with cold spray.",
    ))
    add(build_place(
        id="townia_falls_cliff", tier="location", name="the cliff above the falls", parent=falls_area,
        description="A rocky ledge where the stream gathers before it drops, the whole valley spread out below.",
    ))

    ruin_area = add(build_place(
        id="townia_ruin", tier="area", name="the ruin grounds", parent=t_state, area_type="ruin",
    ))
    ruin_court = add(build_place(
        id="townia_ruin_court", tier="location", name="the ruined courtyard", parent=ruin_area,
        description="Broken stone walls enclose a wide courtyard where moss and weeds push up between the flagstones.",
    ))
    add(build_place(
        id="townia_broken_arch", tier="landmark", name="the broken arch", parent=ruin_court,
        description="A single tall archway still standing at the courtyard's edge.",
    ))
    add(build_place(
        id="townia_ruin_hall", tier="location", name="the ruined hall", parent=ruin_area,
        description="A roofless hall of toppled columns and cracked floors, its far end open to the sky.",
    ))

    dungeon_area = add(build_place(
        id="townia_dungeon", tier="area", name="the dungeon hill", parent=t_state, area_type="dungeon",
    ))
    add(build_place(
        id="townia_dungeon_entrance", tier="location", name="the dungeon entrance", parent=dungeon_area,
        description="A black stairway cuts down into the hillside, cold air breathing up from below.",
    ))
    add(build_place(
        id="townia_dungeon_upper", tier="location", name="the upper halls", parent=dungeon_area,
        description="Narrow stone passages lit by faint glimmers, every footstep echoing.",
    ))
    add(build_place(
        id="townia_dungeon_lower", tier="location", name="the lower halls", parent=dungeon_area,
        description="Wider, older corridors where the air is damp and the walls are slick.",
    ))
    add(build_place(
        id="townia_dungeon_chamber", tier="location", name="the deep chamber", parent=dungeon_area,
        description="A vast circular chamber at the dungeon's lowest point, its great doors standing open.",
    ))

    # ── Pangea — the mortal realm, its own dimension beside Townia's ──
    # Townia is a pocket OUTSIDE Pangea (lore.py), so Pangea is a second
    # top-level dimension, not a child of townia_dim. Only the five
    # continents exist so far; regions/nations/states below them are
    # added (unnamed where lore is silent) as areas get authored.
    pangea = add(build_place(id="pangea_dim", tier="dimension", name="Pangea", parent=None))
    for _cid, _cname in (
        ("pangea_central", "Central Continent"),
        ("pangea_north", "Northern Continent"),
        ("pangea_east", "Eastern Continent"),
        ("pangea_west", "Western Continent"),
        ("pangea_south", "Southern Continent"),
    ):
        add(build_place(id=_cid, tier="continent", name=_cname, parent=pangea))

    return places, {
        "square": square, "market": market, "west_road": west_road,
        "coliseum": coliseum, "south_road": None, "north_road": north_road,
        "outer_loc": outer_loc, "inner_loc": inner_loc, "deep_loc": deep_loc,
    }


def _passage_pairs():
    """Every connection to seed, as (from_id, to_id) — inserted BOTH
    directions by seed_hardcoded_tree() below, matching Layer 2's
    "undirected = two rows" convention. Listed once here, not twice,
    to avoid the two directions silently drifting apart later."""
    return [
        ("townia_square", "townia_church"),
        ("townia_square", "townia_library"),
        ("townia_square", "townia_shrine"),
        ("townia_square", "west_district_road"),
        ("townia_square", "townia_market"),
        ("townia_square", "south_district_road"),
        ("townia_square", "northern_gate"),
        ("townia_market", "townia_pet_shop"),
        ("west_district_road", "coliseum"),
        ("west_district_road", "adventurers_guild"),
        ("south_district_road", "townia_garden_shop"),
        ("northern_gate", "outer_forest_road"),
        ("outer_forest_road", "inner_forest_road"),
        ("inner_forest_road", "deep_forest_road"),
        # ── Townia additions ──────────────────────────────────────
        ("townia_market", "townia_apothecary"),
        ("townia_market", "townia_storehouse"),
        ("west_district_road", "townia_training_yard"),
        ("west_district_road", "townia_smithy"),
        ("south_district_road", "south_district_lodging"),   # Lodging, promoted to a location
        ("south_district_road", "townia_bathhouse"),
        ("south_district_road", "townia_quiet_garden"),
        # the Wall: each tower is entered from its nearest road, and the wall walk joins them in a ring
        ("townia_market", "townia_tower_ne"),
        ("south_district_road", "townia_tower_se"),
        ("west_district_road", "townia_tower_sw"),
        ("northern_gate", "townia_tower_nw"),
        ("townia_tower_ne", "townia_tower_se"),
        ("townia_tower_se", "townia_tower_sw"),
        ("townia_tower_sw", "townia_tower_nw"),
        ("townia_tower_nw", "townia_tower_ne"),
        # outside the wall, all reached through the Dark Forest rings
        ("outer_forest_road", "townia_lakeshore"),
        ("inner_forest_road", "townia_falls_pool"),
        ("townia_falls_pool", "townia_falls_cliff"),
        ("inner_forest_road", "townia_ruin_court"),
        ("townia_ruin_court", "townia_ruin_hall"),
        ("deep_forest_road", "townia_dungeon_entrance"),
        ("townia_dungeon_entrance", "townia_dungeon_upper"),
        ("townia_dungeon_upper", "townia_dungeon_lower"),
        ("townia_dungeon_lower", "townia_dungeon_chamber"),
    ]


def seed_hardcoded_tree(db):
    """
    The actual entry point — builds every Place via build_world_tree()
    and upserts it, then seeds every passage both directions. This is
    what `.resetworld` calls after database.reset_world() wipes
    everything, per Layer 2's contract (reset_world() only deletes;
    rebuilding the hand-authored tier is this function's job).

    Every Place here has invented=False (build_place()'s default) —
    this is the hand-authored tier, distinct from anything a player's
    session causes to be created later.

    Also seeds the hand-authored, carded NPCs (npc.py's NPC_CARDS)
    that live at fixed hardcoded locations — Odalys at the garden
    shop, the two gate guards at the northern gate. Per npc.py's own
    scope note, this does NOT include the elder (seeded reactively at
    registration time, since she's tied to a session event, not a
    place) or the pet shop keeper (per-player, generated on first
    visit) — both stay exactly as they already work today.
    """
    places, _ = build_world_tree()
    for place in places:
        db.upsert_place(place.to_dict())

    for from_id, to_id in _passage_pairs():
        db.add_passage(from_id, to_id, state="established", invented=False)
        db.add_passage(to_id, from_id, state="established", invented=False)

    import npc as _npc
    odalys = _npc.get_npc_card("townia_garden_shop_odalys")
    db.add_world_npc("townia_garden_shop", odalys["name"], hostile=odalys["hostile"])

    for guard_key in ("northern_gate_guard_1", "northern_gate_guard_2"):
        guard = _npc.get_npc_card(guard_key)
        db.add_world_npc("northern_gate", guard["name"], hostile=guard["hostile"])

    # The barrel of crude weapons — a real, shared, finite object
    # (see database.py's rpg_world_objects, added specifically for
    # this case, since neither rpg_world_npcs nor the per-player
    # scene_objects mechanism fit a hand-authored, shared, takeable
    # item). Quantity is a judgment call, not specified anywhere in
    # the source data — 5 is a reasonable finite stock for a gate
    # guard's spare-weapons barrel, not meant to be a balanced game
    # number, just a real number instead of unlimited by default.
    db.add_world_object("northern_gate", "a crude weapon from the barrel", quantity=5)
