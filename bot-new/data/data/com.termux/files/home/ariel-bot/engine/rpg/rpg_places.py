# ============================================================
# ARIEL — RPG_PLACES.PY  (Layer 1 of the movement/location rewrite)
#
# Replaces rpg_locations.py's seven separate dicts (DIMENSIONS,
# CONTINENTS, REGIONS, NATIONS, STATES, AREAS, CAPITAL_LOCATIONS)
# with ONE node shape used at every tier, Dimension through Feature.
# A Landmark and a Continent are the same kind of object now — just
# at different tiers — per the "every card has [ancestry] from
# Dimension" decision (see rpg-movement-rebuild.md, session addendum).
#
# THIS FILE DOES NOT REPLACE rpg_locations.py YET. Per decision #4
# (full rewrite, new modules alongside the old, cutover at the end)
# — nothing here is wired into router/rpg.py or rpg_engine.py until
# every layer (persistence, passages, intent pipeline, router
# integration, data migration) is built and the old system is
# deliberately swapped out in one cutover. Building this in place of
# rpg_locations.py now would mean running a half-migrated engine,
# which decision #4 explicitly rules out.
#
# Passages (edges — the old "connections" lists) are NOT part of
# this node on purpose. Per the movement doc's "places and passages
# are separate things," edges are their own structure — see Layer 3,
# not yet built. A Place here is a node ONLY.
#
# TIER ORDER (World.md, locked):
#   dimension -> continent -> region -> nation -> state -> area ->
#   district -> location -> landmark -> feature
# ============================================================

from dataclasses import dataclass, field, asdict

TIER_ORDER = (
    "dimension", "continent", "region", "nation", "state",
    "area", "district", "location", "landmark", "feature",
)

# The ancestor-chain field name a Place of a given tier's PARENT
# would be stored under. E.g. a "location" Place's parent is an
# "area" or "district" Place, recorded as this Place's own
# area_id/district_id field (see Place.ancestor_field_for below).
_ANCESTOR_FIELD = {
    "dimension": "dimension_id",
    "continent": "continent_id",
    "region": "region_id",
    "nation": "nation_id",
    "state": "state_id",
    "area": "area_id",
    "district": "district_id",
    "location": "location_id",
    "landmark": "landmark_id",
    # "feature" has no ancestor field of its own — nothing sits
    # below a Feature in this hierarchy, so nothing ever points up
    # AT a Feature the way things point up at a Location.
}


@dataclass
class Place:
    """
    One node, used at every tier from Dimension to Feature.

    Ancestor-chain fields (dimension_id ... landmark_id) hold this
    Place's FULL lineage back to the root Dimension, set once at
    creation from build_place() below — never re-derived by walking
    parent_id at read time. A field is None both when that tier is a
    real, unset World.md placeholder ("---") ABOVE this Place's own
    tier, and when that tier is BELOW this Place's own tier (doesn't
    apply yet) — the two cases are distinguished by tier + which
    fields are populated, not by a separate flag; see
    Place.placeholder_tiers() for the World.md-facing distinction.
    """

    id: str
    tier: str                      # one of TIER_ORDER
    name: str | None                # None = real unset placeholder, never a fake name
    parent_id: str | None           # direct parent only; None ONLY for the single root Dimension

    # Full ancestor chain — every tier from Dimension down to (but
    # not including) this Place's own tier. Populated by
    # build_place(); never hand-filled elsewhere.
    dimension_id: str | None = None
    continent_id: str | None = None
    region_id: str | None = None
    nation_id: str | None = None
    state_id: str | None = None
    area_id: str | None = None
    district_id: str | None = None
    location_id: str | None = None
    landmark_id: str | None = None

    description: str | None = None

    # Area-tier only (World.md: type/subdivision don't apply to any
    # other tier — left None everywhere else, never padded).
    area_type: str | None = None        # "settlement" | "forest" | "cave" | "dungeon" | ...
    settlement_size: str | None = None  # "city" | "town" | "village" — only if area_type == "settlement"
    subdivision: str | None = None      # "district" | "ring" | "ward" | None

    # Location-tier only.
    offers_trial: str | None = None
    monster_pool: str | None = None
    max_level: int | None = None

    # True for anything the narrator creates mid-session. Permanent
    # either way (decision #1 — nothing is ever pruned), but this
    # distinguishes hand-authored seed data from invented places for
    # dedup (decision #2) and for .resetworld's hardcoded-vs-invented
    # wipe/reseed split (Layer 2).
    invented: bool = False

    def ancestor_chain(self) -> dict[str, str | None]:
        """This Place's own ancestor-chain fields as a plain dict,
        for persistence (Layer 2) or building a display card."""
        return {
            f: getattr(self, f)
            for f in _ANCESTOR_FIELD.values()
        }

    def own_ancestor_field(self) -> str | None:
        """The ancestor-chain field name THIS Place's id would be
        recorded under on a CHILD of this Place. None for a Feature
        (nothing nests below it)."""
        return _ANCESTOR_FIELD.get(self.tier)

    def to_dict(self) -> dict:
        return asdict(self)


def build_place(
    *,
    id: str,
    tier: str,
    name: str | None,
    parent: "Place | None",
    **extra,
) -> Place:
    """
    Constructs a Place with its full ancestor chain automatically
    derived from its parent — the ONLY way a Place should be built.
    Never hand-fill dimension_id/continent_id/etc. directly; that
    defeats the point of this function and risks a chain that
    doesn't actually match the real tree.

    `parent` is None only for the single root Dimension. Every other
    tier must supply its real parent Place object (not just an id),
    since the chain is copied FROM the parent's own resolved chain,
    not re-derived from scratch.
    """
    if tier not in TIER_ORDER:
        raise ValueError(f"Unknown tier {tier!r} — must be one of {TIER_ORDER}")

    if parent is None:
        if tier != "dimension":
            raise ValueError(
                f"Only a 'dimension'-tier Place may have parent=None; got tier={tier!r}"
            )
        chain = {f: None for f in _ANCESTOR_FIELD.values()}
        parent_id = None
    else:
        expected_idx = TIER_ORDER.index(tier) - 1
        parent_idx = TIER_ORDER.index(parent.tier)
        if parent_idx != expected_idx:
            # World.md allows exactly ONE optional rung to be skipped
            # immediately above certain tiers — e.g. District, when
            # an Area's subdivision is None, so a Location attaches
            # straight to its Area instead. That's the ONLY
            # legitimate skip: the parent must be exactly ONE tier
            # shallower than expected, never more. Skipping further
            # (e.g. a Location attaching directly under a Nation,
            # bypassing State/Area/District all at once) is not a
            # real World.md case and is almost certainly a bug.
            if parent_idx != expected_idx - 1:
                raise ValueError(
                    f"Place tier {tier!r} cannot have a parent of tier "
                    f"{parent.tier!r} (expected {TIER_ORDER[expected_idx]!r}, "
                    f"or {TIER_ORDER[expected_idx - 1]!r} if this rung is "
                    f"deliberately skipped)"
                )
        chain = parent.ancestor_chain()
        own_field = parent.own_ancestor_field()
        if own_field:
            chain[own_field] = parent.id
        parent_id = parent.id

    return Place(
        id=id,
        tier=tier,
        name=name,
        parent_id=parent_id,
        description=extra.pop("description", None),
        area_type=extra.pop("area_type", None),
        settlement_size=extra.pop("settlement_size", None),
        subdivision=extra.pop("subdivision", None),
        offers_trial=extra.pop("offers_trial", None),
        monster_pool=extra.pop("monster_pool", None),
        max_level=extra.pop("max_level", None),
        invented=extra.pop("invented", False),
        **chain,
    )
