# ============================================================
# ARIEL — RPG_MOVEMENT.PY  (Layer 5 of the movement/location rewrite)
#
# Wires Layer 4 (rpg_intent.extract_intent) and Layer 3
# (rpg_passages.py) together into one entry point, called from
# rpg_engine.handle_rpg_action's "move" branch — see that function's
# docstring for the full cutover note.
#
# CUTOVER COMPLETE: the old travel_target handling this replaced
# (router/rpg.py's old "Free-text travel" block, rpg_engine.py's
# narrate_result TRAVEL prompt block, rpg_locations.py's
# resolve_travel_target/can_travel_to/reachable_destinations) has
# been removed, not left alongside this — per decision #4, no two
# systems deciding movement at once.
# ============================================================

import re
from dataclasses import dataclass
import rpg_passages as rp
import rpg_destinations
from rpg_places import Place


@dataclass
class MoveResult:
    """What handle_move_intent() decides, for the router to turn
    into a reply. Mirrors rpg_passages.MoveOutcome's shape but adds
    the fields the router actually needs to build a message (the
    resolved place's display name, whether arrival narration should
    run)."""
    moved: bool
    place_id: str | None
    place_name: str | None
    newly_created: bool
    reason: str | None = None   # shown to the player when moved=False
    arrival_reply: str | None = None  # narrator's real arrival prose,
        # when this move ran it (ordinary moves to an existing place,
        # and newly-created speculative places already had their own
        # narration call). None only for the "not recognized"/db-less
        # early-return paths, which never reach narration at all.
    # Journey fields (None / unset for an ordinary one-hop move):
    #   legs_left   None = not a journey leg; N>0 = still en route;
    #               0 = this leg arrived at the journey's destination
    legs_left: int | None = None
    origin_name: str | None = None
    journey_dest_name: str | None = None


def resolve_destination_name(db, name: str, current_place_id: str) -> dict | None:
    """
    Resolves a player's own words for a destination to a real,
    already-existing Place — checking, in order:
      1. Exact (name, parent=current_place) match — a sibling/child
         place already known from here (movement doc 4.4: "no fuzzy
         string matching for identity" — exact only, at this step).
      2. Exact name match ANYWHERE in the tree (a player naming a
         place they've been before, not necessarily adjacent to
         where they are now) — still exact, not fuzzy.
    Returns the DB place dict, or None if nothing exists by that
    exact name anywhere. A miss here does NOT mean "invalid" — it
    means Layer 4's classification of this as a real, non-speculative
    "move" (plausible=None) was about a place that turns out not to
    exist, which the caller should treat as a plain "nowhere by that
    name" case, not a plausibility judgment (that's only for
    plausible=True/False destinations).
    """
    local_match = db.find_place_by_name_and_parent(name, current_place_id)
    if local_match:
        return local_match

    # Global-by-name fallback: SQLite/Postgres, exact match, no
    # substring/LIKE — matches movement doc 4.4's identity rule.
    rows = db._fetchall(db._ex(
        "SELECT id FROM rpg_places WHERE name = ?", (name,)
    ))
    if rows:
        return db.get_place(rows[0][0])
    return None


def move_player_to(session, db, place: dict):
    """
    Layer 5's replacement for RpgSession.travel_to() — same
    responsibilities (update location_id/location label, clear
    scene_objects), but resolves the display name against the NEW
    Place store instead of rpg_locations.location_name, so a player
    can be moved into a narrator-invented place that only exists in
    rpg_places, not in the old hardcoded CAPITAL_LOCATIONS dict.

    Does not call db.save() / session.save() itself — same contract
    as the old travel_to(), caller saves once after every state
    change in the turn, not once per helper.
    """
    if session.location_id and session.location_id != place["id"]:
        session.flags["_prev_location_id"] = session.location_id
    session.location_id = place["id"]
    session.location = place["name"] or place["id"]
    session.scene_objects = []


def handle_move_intent(session, db, intent: dict, handle_rpg_action_fn,
                       call_groq_fn=None) -> MoveResult:
    """
    The Layer 5 entry point. `intent` is Layer 4's extract_intent()
    output for a message already classified as type="move". Handles
    all four movement-doc cases by delegating to rpg_passages:

      - destination resolves to a real existing place -> move there
        (ordinary travel, the common case)
      - plausible is True/False (speculative passage) -> case 2/3,
        resolve_speculative_passage()
      - destination doesn't resolve AND plausible is None (player
        named an ordinary-sounding place that just doesn't exist
        anywhere) -> plain "nowhere by that name", nothing created;
        distinct from case 3's LLM-judged implausibility

    Does NOT run arrival narration itself (that's the router's job,
    same as it is today — this function only decides WHERE the
    player ends up and whether the move happened, mirroring
    rpg_passages.MoveOutcome's "narrator writes prose from the
    outcome" principle from movement doc 4.1).

    UPDATE (Flag 4 fix): this now DOES call handle_rpg_action_fn for
    ordinary moves to an already-existing place (previously only the
    speculative/newly-created branch did). See move_result.arrival_
    reply — the router still owns building the final player-facing
    text, this just makes sure real narration exists to build it from.

    call_groq_fn is forwarded from the CALLER's own handle_rpg_action
    invocation, not re-defaulted here. Both narration call sites below
    pass it through explicitly to handle_rpg_action_fn (the module-
    level handle_rpg_action, called recursively). Without this, those
    recursive calls would silently fall back to handle_rpg_action's
    own default (the real network call_groq) regardless of what the
    outer turn was actually using — invisible in production (real
    calls all the way down either way) but breaks any test/override
    that stubs call_groq_fn, since the override would silently stop
    at the recursion boundary.
    """
    destination_text = intent.get("destination")
    plausible = intent.get("plausible")
    current_place = db.get_place(session.location_id)

    if current_place is None:
        # Session's location_id doesn't exist in the new Place store
        # at all — most likely this session hasn't been migrated onto
        # the new system yet (still holds an old CAPITAL_LOCATIONS
        # id with no rpg_places row). Not this module's job to fix;
        # surface it plainly rather than guessing.
        return MoveResult(
            moved=False, place_id=None, place_name=None, newly_created=False,
            reason="Your current location isn't recognized by the world system yet.",
        )

    # Closed world: Townia is fully hand-authored (rpg_places_seed). The
    # narrator must not invent places here, so a speculative destination
    # is treated as an ordinary one: it can still match a real place
    # (nearby or down the road), otherwise it's a plain "Nowhere called
    # X". Pangea and everywhere else keep the speculative/invention path.
    if current_place.get("dimension_id") == "townia_dim":
        plausible = None

    # A destination that names a REAL nearby place always wins, even if
    # the intent extractor flagged it speculative ("I look for the
    # library"). Without this, the speculative path below would create
    # a brand-new invented duplicate of a place that already exists.
    if plausible is not None:
        early = rpg_destinations.resolve_destination(
            db, destination_text, current_place,
            previous_place_id=session.flags.get("_prev_location_id"),
        )
        if early["place"] and not early["already_here"]:
            plausible = None
        elif not early["place"] and not early["ambiguous"]:
            # Not nearby, but maybe a real place down the road.
            if rpg_destinations.resolve_far_destination(
                    db, destination_text, current_place)["place"]:
                plausible = None

    if plausible is not None:
        # Speculative passage — decision #3, LLM-alone judgment,
        # already made by Layer 4. This function applies it.
        outcome = rp.resolve_speculative_passage(
            db, from_place=current_place, attempted_name=destination_text,
            plausible=plausible,
        )
        if not outcome.accepted:
            return MoveResult(
                moved=False, place_id=None, place_name=None, newly_created=False,
                reason=outcome.reason,
            )
        # Accepted speculative passage with no destination generated
        # yet (movement doc case 4: real exit, unbuilt destination) —
        # generate it now, on first use, via the narrator, then move
        # the player there and persist it permanently.
        world_state = session.to_world_state_dict(db)
        narration = handle_rpg_action_fn(
            f"I go through: {destination_text}", world_state, db=db,
            call_groq_fn=call_groq_fn,
        )
        new_place = rp.resolve_unbuilt_exit(
            db,
            passage_from_id=current_place["id"],
            passage_to_placeholder_name=destination_text,
            generated_description=narration.get("reply", destination_text),
        )
        session.flags.pop("_journey", None)
        move_player_to(session, db, new_place.to_dict())
        # `narration` above was generated FROM THE OLD LOCATION (that's
        # what makes it a plausible description of somewhere new, not a
        # description of where the player already was) — it's the
        # source text for the new place, not real arrival narration
        # grounded in it. Still worth running the same scene-effect
        # application (new_npcs/new_scene_objects it may have reported)
        # and using its "choices" as a starting point, since it's the
        # only narration this turn produced — but it does NOT replace a
        # proper arrival beat grounded in the new place's own
        # world_state, so the router still shows it via arrival_reply
        # the same as an ordinary move, keeping both paths consistent.
        session.apply_engine_result(narration, db)
        session.flags["_choices"] = narration.get("choices", [])
        return MoveResult(
            moved=True, place_id=new_place.id, place_name=new_place.name,
            newly_created=True, arrival_reply=narration.get("reply"),
        )

    # Ordinary, non-speculative move — resolve against real existing
    # places first (dedup/identity, decision #2's exact-match half).
    match = rpg_destinations.resolve_destination(
        db, destination_text, current_place,
        previous_place_id=session.flags.get("_prev_location_id"),
    )
    if match["already_here"]:
        return MoveResult(
            moved=False, place_id=current_place["id"], place_name=current_place["name"],
            newly_created=False,
            reason=f"You're already at {current_place['name'] or 'this place'}.",
        )
    existing = match["place"]
    if existing:
        session.flags.pop("_journey", None)
        move_player_to(session, db, existing)
        # Arrival narration — the actual Flag 4 fix. An ordinary move
        # to an already-existing place used to end here with a bare
        # "You make your way to X.", no description, no NPCs, no scene
        # objects, and the PREVIOUS scene's stale choices left in
        # session.flags["_choices"] (a fresh location with nothing to
        # choose from, offering options for somewhere else entirely).
        # Running the arrival through the same narration pipeline an
        # ordinary action uses fixes all of that in one call: real
        # prose grounded in the new place's own description, fresh
        # choices, and prose the scene-noun extraction pass (rpg_scene)
        # can actually seed from — none of that ledger's automatic
        # bookkeeping fires on a location with nothing narrated yet.
        arrival = handle_rpg_action_fn(
            "I arrive and take in my surroundings.",
            session.to_world_state_dict(db), db=db,
            call_groq_fn=call_groq_fn,
        )
        session.apply_engine_result(arrival, db)
        session.flags["_choices"] = arrival.get("choices", [])
        return MoveResult(
            moved=True, place_id=existing["id"], place_name=existing["name"],
            newly_created=False, arrival_reply=arrival.get("reply"),
        )
    if match["ambiguous"]:
        return MoveResult(
            moved=False, place_id=None, place_name=None, newly_created=False,
            reason="Which one do you mean: " + " or ".join(match["ambiguous"]) + "?",
        )

    # Not nearby — but is it a real place further down the road? Then
    # this starts a journey: one leg now, the rest one leg per turn.
    far = rpg_destinations.resolve_far_destination(db, destination_text, current_place)
    if far["ambiguous"]:
        return MoveResult(
            moved=False, place_id=None, place_name=None, newly_created=False,
            reason="Which one do you mean: " + " or ".join(far["ambiguous"]) + "?",
        )
    if far["place"]:
        first_hop = db.get_place(far["route"][0])
        if first_hop:
            return _journey_step(session, db, first_hop, far["place"],
                                 handle_rpg_action_fn, call_groq_fn)

    # Named a place that doesn't exist anywhere, and it wasn't judged
    # speculative either — a plain miss, nothing created, nothing
    # rejected-and-remembered (that's only for judged-implausible
    # attempts, see resolve_speculative_passage).
    return MoveResult(
        moved=False, place_id=None, place_name=None, newly_created=False,
        reason=f'Nowhere called "{destination_text}" is known from here.',
    )


# ============================================================
# JOURNEYS — far destinations, one leg per turn
#
# session.flags["_journey"] = {"dest_id": ..., "dest_name": ...}
# Only the DESTINATION is stored, never the path: every leg re-routes
# from wherever the player actually is, so wandering off, side
# trips and world edits can't leave a stale path behind. The journey
# ends on arrival, when no road remains, or when the player makes a
# different move.
# ============================================================

_CONTINUE_RE = re.compile(
    r"^(continue( the)?( journey| travel(l)?ing| trip)?|keep going|go on|"
    r"carry on|press on|onward(s)?|proceed|keep travel(l)?ing)$"
)


def is_continue_text(text) -> bool:
    s = re.sub(r"[^a-z ]+", " ", str(text or "").lower())
    return bool(_CONTINUE_RE.match(" ".join(s.split())))


def _legs(n: int) -> str:
    return f"{n} leg{'s' if n != 1 else ''}"


def _journey_step(session, db, next_place: dict, dest: dict,
                  handle_rpg_action_fn, call_groq_fn=None) -> MoveResult:
    """Moves the player ONE hop along the road to `dest`, narrates the
    arrival, and updates/clears session.flags["_journey"]."""
    origin = session.location
    move_player_to(session, db, next_place)

    kwargs = {"db": db}
    if call_groq_fn is not None:
        kwargs["call_groq_fn"] = call_groq_fn
    arrival = handle_rpg_action_fn(
        "I arrive and take in my surroundings.",
        session.to_world_state_dict(db), **kwargs,
    )
    session.apply_engine_result(arrival, db)
    session.flags["_choices"] = arrival.get("choices", [])

    remaining = rpg_destinations.route_to(db, next_place["id"], dest["id"])
    legs_left = len(remaining) if remaining else 0
    if legs_left:
        session.flags["_journey"] = {
            "dest_id": dest["id"], "dest_name": dest["name"] or dest["id"],
        }
    else:
        session.flags.pop("_journey", None)

    return MoveResult(
        moved=True, place_id=next_place["id"], place_name=next_place["name"],
        newly_created=False, arrival_reply=arrival.get("reply"),
        legs_left=legs_left, origin_name=origin,
        journey_dest_name=dest["name"] or dest["id"],
    )


def continue_journey(session, db, handle_rpg_action_fn, call_groq_fn=None) -> MoveResult:
    """Advance the active journey by one leg."""
    def _stop(reason):
        session.flags.pop("_journey", None)
        return MoveResult(moved=False, place_id=None, place_name=None,
                          newly_created=False, reason=reason)

    j = session.flags.get("_journey")
    if not j:
        return _stop("You aren't on a journey.")
    dest = db.get_place(j.get("dest_id"))
    if dest is None:
        return _stop("You've lost track of where you were headed.")
    if session.location_id == dest["id"]:
        return _stop(f"You're already at {dest['name'] or 'your destination'}.")
    route = rpg_destinations.route_to(db, session.location_id, dest["id"])
    if not route:
        return _stop(f"You can't find the way to {dest['name'] or 'there'} from here.")
    nxt = db.get_place(route[0])
    if nxt is None:
        return _stop("The road ahead has vanished.")
    return _journey_step(session, db, nxt, dest, handle_rpg_action_fn, call_groq_fn)


def format_journey_reply(mr: MoveResult) -> str:
    """Player-facing text for one journey leg. The footer is written by
    code, never the narrator, so the leg count is always true."""
    where = mr.place_name or "your next stop"
    head = (f"You leave {mr.origin_name} and arrive at {where}."
            if mr.origin_name else f"You arrive at {where}.")
    if mr.legs_left:
        foot = ("Your journey is still underway as the destination is quite far.\n"
                f"({mr.journey_dest_name}: {_legs(mr.legs_left)} away)")
    else:
        foot = f"📍 You have arrived at {mr.journey_dest_name}."
    return "\n\n".join(x for x in (head, mr.arrival_reply, foot) if x)


def with_continue_choice(session, choices: list) -> list:
    """While a journey is active, 'Continue journey' is always choice 1.
    Code-injected so the narrator can't forget it."""
    j = session.flags.get("_journey")
    if j and session.location_id == j.get("dest_id"):
        session.flags.pop("_journey", None)
        j = None
    if not j:
        return choices
    rest = [c for c in (choices or []) if not is_continue_text(c)]
    return ["Continue journey"] + rest[:3]
