# ============================================================
# ARIEL — RPG_PASSAGES.PY  (Layer 3 of the movement/location rewrite)
#
# The four movement cases from rpg-movement-rebuild.md section 4.3,
# built against Layer 1 (rpg_places.Place) and Layer 2 (database.py's
# rpg_places/rpg_passages tables). Called from rpg_movement.py
# (Layer 5), which is wired into rpg_engine.handle_rpg_action's
# "move" branch — the old travel_target system this replaced has
# been removed, not left running alongside it (decision #4).
#
# This module does NOT call an LLM itself. It's the "code validates
# and applies" half of the pipeline (movement doc 4.1) — it takes a
# classifier's OUTPUT (an intent dict Layer 4 produces) and turns it
# into real Place/Passage rows, or a rejection. Layer 4
# (rpg_intent.py) is what actually calls the LLM to produce that
# intent dict in the first place.
# ============================================================

from dataclasses import dataclass
from rpg_places import Place, build_place, TIER_ORDER


# ── Result shapes ─────────────────────────────────────────────

@dataclass
class MoveOutcome:
    """What resolve_move() decides. The narrator writes prose from
    THIS outcome (movement doc 4.1: "narrator writes prose from the
    OUTCOME, no state fields") — it never re-decides plausibility or
    identity itself."""
    accepted: bool
    place_id: str | None          # the resolved/created destination's id, if accepted
    newly_created: bool           # True if this Place didn't exist before this call
    reason: str | None = None     # for accepted=False — why (shown to narrator/player)


# ── Case 1: narrator invents a place ──────────────────────────

def register_invented_place(
    db,
    *,
    name: str,
    description: str,
    from_place: dict,
    tier: str = "location",
) -> Place:
    """
    Movement doc case 1: 'a smithy' — exists the moment it's
    narrated. Registers id + description + a passage back to
    wherever the player currently is.

    Dedup (decision #2) happens BEFORE this is called — see
    resolve_move() below, which checks find_place_by_name_and_parent
    first and only calls this on a genuine miss. This function always
    creates; it never checks for an existing match itself, so it must
    not be called directly from Layer 4/5 without that check first.

    Per movement doc 4.4 "description ownership": description is
    stored once, right here, and is never rewritten later even if the
    narrator describes the same place differently on a future visit.
    """
    parent_id = from_place["id"]
    new_id = _generate_place_id(name, parent_id)

    place_obj = Place(
        id=new_id,
        tier=tier,
        name=name,
        parent_id=parent_id,
        description=description,
        invented=True,
        **_inherit_chain_dict(from_place, tier),
    )
    db.upsert_place(place_obj.to_dict())

    # Passage back to where the player came from — both directions,
    # per Layer 2's "undirected = two rows" convention. Established,
    # not "open", since the destination exists in full right now,
    # not lazily.
    db.add_passage(parent_id, new_id, state="established", invented=True)
    db.add_passage(new_id, parent_id, state="established", invented=True)

    return place_obj


# ── Case 2: speculative passage ("a door within a door") ───────

def resolve_speculative_passage(
    db,
    *,
    from_place: dict,
    attempted_name: str,
    plausible: bool,
    llm_reasoning: str | None = None,
) -> MoveOutcome:
    """
    Movement doc case 2. Per decision #3, plausibility itself is
    judged ENTIRELY by the LLM before this function is even called —
    `plausible` here is that already-made judgment, not something
    this function re-derives. This function's only job is to apply
    the consequence of that judgment to real state, and to make the
    outcome STICKY (movement doc 4.3's "reject" case + this session's
    dedup discussion): a rejected speculative passage is persisted as
    a real Place row (tier="feature", so it doesn't pollute Location-
    level dedup/travel resolution) plus a passage row with
    state="absent", so the exact same implausible attempt from the
    exact same place isn't re-judged by the LLM every single time —
    see check_known_rejection(), which Layer 4 must call BEFORE
    asking the LLM again for the same (from_place, name) pair.
    """
    from_id = from_place["id"]

    if not plausible:
        rejected_id = _generate_place_id(attempted_name, from_id)
        rejected_place = Place(
            id=rejected_id,
            tier="feature",
            name=attempted_name,
            parent_id=from_id,
            description=llm_reasoning,
            invented=True,
            **_inherit_chain_dict(from_place, "feature"),
        )
        db.upsert_place(rejected_place.to_dict())
        db.add_passage(from_id, rejected_id, state="absent", invented=True)
        return MoveOutcome(
            accepted=False, place_id=None, newly_created=False,
            reason=llm_reasoning or "That doesn't seem possible here.",
        )

    # Accepted speculative passage: per movement doc case 4 ("real
    # exit, unbuilt destination"), the destination isn't generated
    # HERE — accepting the passage's plausibility is a separate step
    # from generating what's on the other side of it, which only
    # happens on first actual use (see resolve_unbuilt_exit below).
    # This function only marks the passage itself as real.
    return MoveOutcome(accepted=True, place_id=None, newly_created=False)


def check_known_rejection(db, from_id: str, attempted_name: str) -> bool:
    """
    True if this exact (from_place, name) speculative attempt was
    already rejected before — Layer 4 should check this BEFORE
    spending an LLM call on plausibility again. Matches on name only
    within from_id's scope, same dedup shape as decision #2 (name +
    parent), since a rejected passage doesn't have a real place_id of
    its own to key against.
    """
    existing = db.find_place_by_name_and_parent(attempted_name, from_id)
    if existing is None:
        return False
    passages = db.get_passages_from(from_id)
    return any(p["to_id"] == existing["id"] and p["state"] == "absent" for p in passages)


# ── Case 3: impossible passage (rejected outright) ──────────────
#
# No separate function — this is the plausible=False branch of
# resolve_speculative_passage() above. The movement doc lists it as
# its own case because the NARRATION differs (case 2 might get a
# hedged "maybe" outcome from an ambiguous LLM call, case 3 is a
# clean no) — but structurally both are "LLM said not plausible",
# same code path, same MoveOutcome(accepted=False, ...) shape.


# ── Case 4: real exit, unbuilt destination ──────────────────────

def resolve_unbuilt_exit(
    db,
    *,
    passage_from_id: str,
    passage_to_placeholder_name: str,
    generated_description: str,
    tier: str = "location",
) -> Place:
    """
    Movement doc case 4: 'walking out the door' — the passage itself
    was already real (state="open"), but nothing existed on the
    other side until first use. This is called the FIRST time a
    player actually walks through an "open" passage; the generated
    Place is then stored permanently (decision #1), and the passage
    is upgraded from "open" to "established" so no future player
    regenerates a different place behind the same door.
    """
    from_place = db.get_place(passage_from_id)
    new_place = register_invented_place(
        db,
        name=passage_to_placeholder_name,
        description=generated_description,
        from_place=from_place,
        tier=tier,
    )
    # Upgrade the existing "open" passage rows to "established" now
    # that a real destination exists behind them, rather than leaving
    # a stale "open" row alongside the new "established" one to the
    # actually-generated place.
    db.add_passage(passage_from_id, new_place.id, state="established", invented=True)
    db.add_passage(new_place.id, passage_from_id, state="established", invented=True)
    return new_place


# ── Dedup (decision #2) ─────────────────────────────────────────

def find_existing_or_none(db, name: str, parent_id: str) -> dict | None:
    """
    Exact (name, parent_id) dedup — decision #2's first pass. Per
    decision #2, when this misses but a near-match plausibly exists
    (e.g. 'the smithy' vs 'the old smithy' at the same parent), that
    ambiguity is NOT resolved here with fuzzy string logic — it's
    handed to the LLM as part of Layer 4's classification ("is this
    the same place as X, already known here, or a new one?"). This
    function only ever does the exact-match half.
    """
    return db.find_place_by_name_and_parent(name, parent_id)


# ── Internal helpers ─────────────────────────────────────────────

def _generate_place_id(name: str, parent_id: str) -> str:
    import re, time
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return f"{parent_id}__{slug}_{int(time.time() * 1000) % 100000}"


def _inherit_chain_dict(parent_place_dict: dict, child_tier: str) -> dict:
    """Builds the ancestor-chain kwargs for a NEW child Place from its
    parent's already-persisted dict (as returned by db.get_place),
    mirroring what build_place() does for in-memory Place objects —
    needed here because register_invented_place works off a DB dict,
    not a live Place object, when the parent was looked up fresh."""
    chain_fields = ("dimension_id", "continent_id", "region_id", "nation_id",
                     "state_id", "area_id", "district_id", "location_id",
                     "landmark_id")
    chain = {f: parent_place_dict.get(f) for f in chain_fields}
    own_field_map = {
        "dimension": "dimension_id", "continent": "continent_id",
        "region": "region_id", "nation": "nation_id", "state": "state_id",
        "area": "area_id", "district": "district_id",
        "location": "location_id", "landmark": "landmark_id",
    }
    own_field = own_field_map.get(parent_place_dict["tier"])
    if own_field:
        chain[own_field] = parent_place_dict["id"]
    return chain
