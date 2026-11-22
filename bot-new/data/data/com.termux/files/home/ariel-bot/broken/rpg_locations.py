# ============================================================
# ARIEL — RPG_LOCATIONS.PY
# Location hierarchy for .rpg: Dimension -> Continent -> Region ->
# Nation -> State -> Area (Settlement[City/Town/Village] or
# Forest/Cave/Dungeon/etc.) -> District (only if the Area subdivides)
# -> Location -> Landmark (optional) -> Feature (optional).
#
# Locked in World.md (see project docs) after a real bug: the
# narrator described a player walking to "the shrine beyond the
# square," but the shrine had no backing location_id anywhere in this
# file — narration invented movement the state layer didn't track.
# The fix has two parts: (1) anything a player can be SENT TO or
# ENTER must be a real Location (own location_id, in
# CAPITAL_LOCATIONS) — see LANDMARK PROMOTION RULE below; (2) named
# things that live INSIDE a Location but aren't separately enterable
# (a fountain, a statue) are Landmarks — real/addressable enough that
# narration can't invent one that isn't listed, but lighter than a
# full Location (no own location_id, no NPC roster, no connections).
#
# LANDMARK PROMOTION RULE (from World.md) — default a named thing to
# Landmark; promote it to a full Location the moment ANY of these are
# true: it's not physically inside/at an existing Location (it's its
# own place elsewhere in the District/Area) — this alone is enough;
# it needs its own NPC roster; a quest needs to check the player is
# specifically AT it, not just in the Location it'd otherwise be
# attached to; it needs state/description independent of its parent
# Location. The shrine failed rule #1 (it's a separate place from the
# square, same District, not physically at it) so it's a Location
# below, not a Landmark.
#
# Same spirit as router/explore.py's ZONE_INFO (id -> display info
# dict), but a separate file/namespace since this is .rpg-specific
# (freeform narrative roleplay) and unrelated to the Pokémon-side
# .explore world. The two systems don't share zones or state.
#
# This is a HAND-AUTHORED, FIXED map (real districts, real names),
# unlike rpg_session.py's rpg_world_npcs table (which holds NPCs the
# narrator invents on the fly at whatever location the player is
# in) — locations here are known in advance; NPCs at them are not.
#
# Only one nation/state/area exist right now (placeholder names below,
# not yet decided) — the fields exist so a SECOND area/nation can be
# added later without a schema change, not because there's real
# content at those tiers yet. Don't invent names for these beyond the
# placeholders; that's content to fill in later, not something to
# guess at now. Per World.md's placeholder convention: Dimension
# through Area are universal tiers (unset = "---", never omitted);
# Location/Landmark/Feature are only present when meaningful, never
# padded with "---".
# ============================================================

DIMENSIONS = {
    "townia_dim": {"name": "Townia"},
}

CONTINENTS = {
    # none named yet — placeholder tier, per World.md's placeholder
    # convention this is "---" until something real is added here,
    # not a sign the tier is unused/unsupported.
}

REGIONS = {
    # none named yet — see CONTINENTS comment above.
}

NATIONS = {
    # nation_1 exists purely so STATES has something to link to via
    # nation_id — it's not actually named yet. No "name" key here on
    # purpose: location_path()'s nation.get("name", "---") falls back
    # to the real placeholder ("---"), not a fake display name. Per
    # the "unnamed thing shouldn't even exist" fix — a made-up name
    # like "Unnamed Nation" is worse than no name, since it reads as
    # a real answer instead of "not decided yet."
    "nation_1": {},
}

STATES = {
    # Same reasoning as NATIONS above — state_1 links AREAS to a
    # nation_id, nothing more. No "name" key until one's actually
    # chosen.
    "state_1": {"nation_id": "nation_1"},
}

# id -> {name, type, subdivision, state_id}
# "type" is the Area's own branch: "settlement" further resolves to a
# size label (city/town/village) via settlement_size below; any other
# type (forest/cave/dungeon/etc.) is flatter and has no size label.
# "subdivision" declares whether/how this Area splits into a middle
# rung, and which word that rung uses — "district" for a settlement,
# "ring" for the Dark Forest, or None if it doesn't subdivide at all.
# District is NOT assumed universal — narrator/travel logic must check
# this field before expecting or displaying a middle rung.
AREAS = {
    "townia": {
        "name": "Townia",
        "type": "settlement",
        "settlement_size": "town",
        "subdivision": "district",
        "state_id": "state_1",
    },
    "dark_forest": {
        "name": "the Dark Forest",
        "type": "forest",
        "subdivision": "ring",
        "state_id": "state_1",
    },
}

# location_id -> {name, area_id, district (label depends on the
# parent Area's subdivision word — "Center"/"West" for townia's
# "district" subdivision, "Outer Ring"/"Inner Ring"/"Deep Forest" for
# dark_forest's "ring" subdivision), connections, and optionally
# description, offers_trial, max_level, monster_pool}.
#
# "connections" lists other location ids reachable directly from
# here — used by the ".rpg go to <place>" travel command (see
# router/rpg.py). Every id here doubles as the key into
# rpg_world_npcs (via database.py's add_world_npc/get_world_npcs)
# and into npc_events (via zone_id) once travel writes new locations
# into RpgSession.
CAPITAL_LOCATIONS = {
    "townia_square": {
        "name": "Townia — the town square",
        "district": "Center",
        "area_id": "townia",
        "connections": ["townia_church", "townia_library",
                         "west_district", "east_district", "south_district",
                         "northern_gate", "noble_district", "townia_shrine"],
    },
    "townia_shrine": {
        "name": "Townia — the shrine beyond the square",
        "district": "Center",
        "area_id": "townia",
        "description": (
            "A small, quiet shrine tucked just past the square — worn "
            "stone, old offerings, the noise of the town fading out "
            "behind you."
        ),
        "connections": ["townia_square"],
    },
    "townia_church": {
        "name": "Townia — the church",
        "district": "Center",
        "area_id": "townia",
        "connections": ["townia_square"],
    },
    "townia_library": {
        "name": "Townia — the library",
        "district": "Center",
        "area_id": "townia",
        "connections": ["townia_square"],
        "offers_trial": "mage",
    },
    "west_district": {
        "name": "Townia — the West District",
        "district": "West",
        "area_id": "townia",
        "description": "Home to the Coliseum and the Adventurers' Guild.",
        "landmarks": ["Coliseum", "Adventurers' Guild"],
        "connections": ["townia_square"],
        "offers_trial": "warrior",
    },
    "east_district": {
        "name": "Townia — the East District",
        "district": "East",
        "area_id": "townia",
        "description": "The capital's shops and business quarter.",
        "landmarks": ["Shops", "Business Quarter"],
        "connections": ["townia_square", "townia_pet_shop"],
    },
    "townia_pet_shop": {
        "name": "Townia — the pet shop",
        "district": "East",
        "area_id": "townia",
        "description": "Rows of pens and cages, alive with restless animal noise.",
        "landmarks": ["Pet Shop"],
        "connections": ["east_district"],
        "offers_trial": "summoner",
    },
    "south_district": {
        "name": "Townia — the South District",
        "district": "South",
        "area_id": "townia",
        "description": "Where travelers find lodging.",
        "landmarks": ["Lodging"],
        "connections": ["townia_square"],
    },
    "noble_district": {
        "name": "Townia — the Noble District",
        "district": "North",
        "area_id": "townia",
        "connections": ["townia_square", "townia_garden_shop"],
    },
    "townia_garden_shop": {
        "name": "Townia — the garden shop",
        "district": "North",
        "area_id": "townia",
        "description": (
            "A small greenhouse tucked behind the Noble District's "
            "hedgerows, tended by an old gardener named Odalys. Rows "
            "of potted saplings and drying herbs line the shelves — "
            "nothing much happens here yet, but she's always glad "
            "for the company."
        ),
        "landmarks": ["Odalys the gardener", "Greenhouse"],
        "connections": ["noble_district"],
    },
    "northern_gate": {
        "name": "Townia — the northern gate",
        "district": "North",
        "area_id": "townia",
        "description": (
            "The town's entrance, manned by two guards who watch "
            "cursed children with open distrust. Before letting "
            "anyone pass, they gesture to a barrel of crude "
            "weapons for the traveler to pick from."
        ),
        "landmarks": ["The gate guards", "Barrel of crude weapons"],
        "connections": ["townia_square", "outer_forest"],
    },
    "outer_forest": {
        "name": "the Dark Forest — outer ring",
        "district": "Outer Ring",
        "area_id": "dark_forest",
        "description": (
            "The outermost ring of the Dark Forest, circling Townia "
            "just past the northern gate. A dirt track cuts north "
            "through it, deeper into the trees."
        ),
        "connections": ["northern_gate", "inner_forest"],
        "max_level": 5,
        "monster_pool": ["Wolf", "Boar", "Giant Rat", "Kobold", "Goblin"],
    },
    "inner_forest": {
        "name": "the Dark Forest — inner ring",
        "district": "Inner Ring",
        "area_id": "dark_forest",
        "description": (
            "Deeper into the Dark Forest. The trees grow thicker "
            "and the light dimmer than the outer ring."
        ),
        "connections": ["outer_forest", "deep_forest"],
        "max_level": 10,
        "monster_pool": ["Dire Wolf", "Giant Boar", "Black Bear",
                          "Giant Spider", "Hobgoblin", "Bugbear"],
    },
    "deep_forest": {
        "name": "the Dark Forest — deep forest",
        "district": "Deep Forest",
        "area_id": "dark_forest",
        "description": (
            "The innermost ring of the Dark Forest. The dirt track "
            "continues north from here, straight to the edge of "
            "the dimension itself — impassable, however far it's "
            "followed."
        ),
        "connections": ["inner_forest"],
        "max_level": 15,
        "monster_pool": ["Brown Bear", "Owlbear", "Darkmantle",
                          "Giant Wolf Spider", "Ogre", "Gnoll"],
    },
}


def location_details(location_id: str) -> dict:
    """
    Hand-authored grounding facts for a location — description and
    landmarks — for the narrator to build scenes from, instead of
    guessing purely from the display name. Returns {} for locations
    not in the registry (freeform/narrator-invented spots), same
    fallback spirit as location_name()/offered_trial(). Deliberately
    a separate accessor from location_name()/location_path() since
    those are used everywhere (including narrator-invisible internal
    bookkeeping) and don't need this heavier payload.

    NOTE: "landmarks" here is still the flat flavor-only string list
    (fountain, statue, etc. — not enterable, no own location_id) per
    World.md's Landmark tier definition. Kept under the same dict key
    the narrator (rpg_engine.py) and rpg_session.py already read from
    world_state["location_details"], so this rename doesn't require
    touching either of those call sites.
    """
    entry = CAPITAL_LOCATIONS.get(location_id)
    if not entry:
        return {}
    return {
        "description": entry.get("description"),
        "landmarks": entry.get("landmarks", []),
    }


def encounter_pool(location_id: str) -> dict | None:
    """
    Area-tier data for on-the-fly story encounters (see
    rpg_battle.generate_encounter) — the hand-authored SRD-name pool
    a location can spawn from, and the level cap a rolled monster is
    capped at (rolled 1..max_level, never above it, regardless of
    player level). Returns None for locations with no monster_pool
    defined (safe interior/town locations aren't meant to spawn
    encounters at all) rather than an empty dict, so callers can
    tell "no encounters possible here" apart from "encounters
    possible, pool just happens to be empty" (the latter shouldn't
    occur, but the distinction is what None vs {} is for).
    """
    entry = CAPITAL_LOCATIONS.get(location_id)
    if not entry or "monster_pool" not in entry:
        return None
    return {
        "max_level": entry.get("max_level", 1),
        "monster_pool": entry["monster_pool"],
    }


def location_name(location_id: str) -> str:
    """Display label for a location id — falls back to the raw id
    (title-cased) if it's not in the registry, so an unrecognized
    id never crashes a caller, just looks a bit rough."""
    entry = CAPITAL_LOCATIONS.get(location_id)
    if entry:
        return entry["name"]
    return location_id.replace("_", " ").title()


def offered_trial(location_id: str) -> str | None:
    """
    Which trial class (if any) this location's NPC can offer —
    "warrior" for the Coliseum, "mage" for the library, None
    everywhere else. Used to tell the narrator (rpg_engine.py) when
    it's allowed to recognize trial-acceptance intent and set
    trial_start in its JSON reply — a player can't "intend" a sword
    trial while standing in the library.
    """
    entry = CAPITAL_LOCATIONS.get(location_id)
    return entry.get("offers_trial") if entry else None


def area_subdivision_label(area_id: str) -> str | None:
    """
    The word this Area's middle rung uses — "district" for Townia,
    "ring" for the Dark Forest, or None if the Area doesn't subdivide
    at all. Title-cased for direct display (e.g. "District"/"Ring").
    Callers (narrator, location_path) must check this before
    expecting/displaying a middle rung — District is NOT universal
    across every Area, per World.md.
    """
    entry = AREAS.get(area_id)
    if not entry:
        return None
    sub = entry.get("subdivision")
    return sub.title() if sub else None


def location_path(location_id: str) -> dict:
    """
    Walks a location up through the full locked World.md hierarchy:
    Dimension -> Continent -> Region -> Nation -> State -> Area ->
    District -> Location.

    Per World.md's Map format: "area" is ALWAYS the broad type
    (Settlement/Forest/Cave/...), never the Area's own specific name.
    For settlement-type Areas only, "settlement_size_label" (e.g.
    "Town"/"City"/"Village") and "area_name" (e.g. "Townia") together
    give the second line ("Town: Townia") World.md's worked examples
    show right under "Area: Settlement". Non-settlement Areas (Forest,
    Cave, ...) get settlement_size_label=None — there's no second
    named line for them in the fixed 10-slot map; their own name has
    nowhere to display beyond "area"'s type value.

    Per World.md's placeholder convention: dimension/continent/region/
    nation/state/area are universal tiers, so an unresolved value is
    the literal string "---" (never omitted from the dict, even when
    unnamed) — NOT "Unknown". "district" is different: it's only
    filled in when the parent Area actually subdivides (per its
    subdivision field); otherwise it's "---" too, since at the Area
    tier itself "no district" is a real, known answer, not a missing
    lookup. An unrecognized location_id is the one real failure case
    and still returns "Unknown" for location/district so callers don't
    crash, but every macro tier still resolves through Townia's
    Dimension as a sane default rather than saying "Unknown" for
    tiers that aren't really in question.

    This is the disambiguation context: knowing the full path doesn't
    matter much with one Area, but "current location" (the last
    field) is what target resolution and scene objects actually key
    off — see world_registry-equivalent usage in rpg_session.py.
    """
    entry = CAPITAL_LOCATIONS.get(location_id)
    if not entry:
        return {
            "dimension": "---", "continent": "---", "region": "---",
            "nation": "---", "state": "---", "area": "---",
            "settlement_size_label": None, "area_name": "---",
            "district": "Unknown", "location": location_name(location_id),
        }

    area = AREAS.get(entry.get("area_id"), {})
    state = STATES.get(area.get("state_id"), {})
    nation = NATIONS.get(state.get("nation_id"), {})
    # Only one Dimension exists right now (Townia) — every location
    # in CAPITAL_LOCATIONS currently belongs to it. Falls back to
    # "---" rather than hardcoding, so adding a second Dimension later
    # doesn't silently mislabel anything.
    dimension = DIMENSIONS.get("townia_dim", {})

    sub_label = area_subdivision_label(entry.get("area_id"))
    district = entry.get("district") if sub_label else "---"

    # Per World.md's Map format: "Area" is always the broad TYPE
    # (Settlement/Forest/Cave/...), never the Area's own name — that
    # name only ever shows up on a second, settlement-only line whose
    # LABEL is the settlement's size word (Town/City/Village), not
    # "Area" again. Non-settlement types (Forest, Cave, ...) skip that
    # second line entirely; their specific name has nowhere else to
    # go in the fixed 10-slot map, so callers wanting a display string
    # for a non-settlement Area should fall back to area_name below
    # rather than expecting a second labeled line, same as the Dark
    # Forest worked example (no separate "Forest name" line, just
    # "Area: Forest" then straight to "Ring: Inner Ring").
    area_type = area.get("type", "")
    area_name = area.get("name", "---")
    settlement_size = None
    if area_type == "settlement":
        # Title-cased so it's ready to use directly as a display
        # label — "town" -> "Town", matching World.md's worked
        # examples ("Town: Townia") rather than a lowercase key name.
        settlement_size = (area.get("settlement_size") or "settlement").title()

    return {
        "dimension": dimension.get("name", "---"),
        "continent": "---",
        "region": "---",
        "nation": nation.get("name", "---"),
        "state": state.get("name", "---"),
        # Broad type only (e.g. "Settlement", "Forest") — per
        # World.md, this line is NEVER the Area's own specific name.
        "area": area_type.title() if area_type else "---",
        # Present only for settlement-type Areas — the LABEL to show
        # this under (e.g. "Town") and the specific name to pair with
        # it (e.g. "Townia"). None for non-settlement Areas, since
        # they have no second line at all per the Map format section.
        "settlement_size_label": settlement_size,
        "area_name": area_name,
        "district": district if district else "---",
        "location": entry["name"],
    }


# ── can_travel_to / reachable_destinations / resolve_travel_target
# REMOVED (movement-rebuild cutover). All three were the old
# deterministic travel machinery — reachability checks and substring-
# based destination matching against CAPITAL_LOCATIONS' "connections"
# lists. Movement is now handled by rpg_intent.extract_intent +
# rpg_movement.handle_move_intent, resolving against the real,
# DB-backed rpg_places/rpg_passages tree (see rpg_places.py,
# rpg_passages.py, rpg_places_seed.py) instead of this file's static
# dicts. Nothing in the live pipeline calls these three anymore as of
# this cutover — removed rather than left as dead code, per decision
# #4 ("no stone unturned").
