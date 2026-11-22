# ============================================================
# NIFLHEIM — router/dungeon.py
# Dungeon command logic: entry flow, .dive/.look/.hunt/.mine/.dig/
# .fish/.ambush/.trap/.advance/.goback/.forfeit/.goto, checkpoint
# and floor-progression handling.
#
# Mirrors router/explore.py's structure and conventions. Skeleton
# only — resolution logic (encounter rolls, reward grants, prose)
# is stubbed with TODOs; wire up against dungeon_data.py once a
# real dungeon (Cinder Hollow) is registered there.
# ============================================================

import threading

from dungeon_session import DungeonSession, elite_on_cooldown, elite_cooldown_remaining, mark_elite_defeated
from dungeon_data import get_dungeon, get_floor, roll_path_node, goto_distance, goto_seconds, trace_goto_route, GOTO_SECONDS_PER_NODE, NODE_FIXED, NODE_BATCH

# Importing per-dungeon data modules registers them into
# dungeon_data.DUNGEONS as a side effect (see that file's
# "Dungeon registry" section). Add new dungeons' data modules here
# as they're built.
import cindel_hollow_data  # noqa: F401 — registers "cinder_hollow"

try:
    # Same reusable pattern router/explore.py uses for proactive
    # pushes — see that file's _push() for why this is guarded.
    import router as _router
except ImportError:
    _router = None

try:
    # Same per-sender lock explore.py's arrival timer uses to
    # serialize against the main message-handling thread pool.
    from bridge import _get_sender_lock
except ImportError:
    _get_sender_lock = None


def _push(sender, message):
    direct_send = getattr(_router, "_direct_send", None) if _router else None
    if not direct_send:
        return
    direct_send(message, group_jid=sender, allow_dm=True)


# ── Entry flow ─────────────────────────────────────────────────
# Arriving at a dungeon (via overworld .dive onto its zone) does
# NOT auto-lock the player in — see dungeon_system_logic.md's
# "Dungeon entry flow". This is called from the OVERWORLD explore
# resolution once it detects the destination zone is a dungeon
# entrance, not from a .dungeon-prefixed command.

def handle_dungeon_arrival(sender, player, dungeon_id, db):
    """
    Player has reached a dungeon's threshold via normal overworld
    movement. Sets up the session at the threshold (not locked in
    yet) and returns the "Do you wish to enter?" prompt.
    """
    dungeon = get_dungeon(dungeon_id)
    if not dungeon:
        return None  # TODO: shouldn't happen once dungeons are registered — guard for now

    floor_1 = get_floor(dungeon_id, 1)
    entrance_node = floor_1.spine_entrance() if floor_1 else None

    session = DungeonSession.load(db, sender)
    session.arrive(dungeon_id, entrance_node)
    session.save(db)

    dungeon_name = dungeon.get("name", dungeon_id)
    return (
        f"You have arrived at {dungeon_name} (Dungeon)\n"
        f"Do you wish to enter?\n\n"
        f".yes\n"
        f".no"
    )


def handle_dungeon_confirm(sender, player, db):
    """Player answered .yes at the threshold."""
    session = DungeonSession.load(db, sender)
    if not session.at_threshold():
        return "There's nothing to confirm right now."

    session.confirm_entry()
    session.save(db)

    dungeon = get_dungeon(session.dungeon_id)
    dungeon_name = dungeon.get("name", session.dungeon_id) if dungeon else session.dungeon_id

    # TODO: pull the signboard/welcome fixed-node description instead
    # of a hardcoded line, once floor data is populated.
    return (
        f'Welcome to {dungeon_name}, reads the signboard.\n\n'
        f"{_command_list_text()}"
    )


def handle_dungeon_decline(sender, player, db):
    """Player answered .no at the threshold — leaves safely."""
    session = DungeonSession.load(db, sender)
    if not session.at_threshold():
        return "There's nothing to decline right now."
    session.decline_entry()
    session.save(db)
    return "You step back from the entrance."


def _command_list_text():
    # TODO: replace with the real, finalized command list/help text.
    return (
        ".dive — explore, avoiding fights\n"
        ".look — see what's here right now\n"
        ".hunt — stay and seek a fight\n"
        ".mine / .dig / .fish — gather\n"
        ".advance / .goback — move\n"
        ".goto <location> — fast-travel to a discovered subzone\n"
        ".forfeit — give up the run"
    )


# ── .dive ──────────────────────────────────────────────────────

def handle_dive(sender, player, db, save_fn, combat_session=None):
    """
    Repeatable, diminishing-returns scan of the player's current
    path segment. Better discovery odds than .hunt, lower encounter
    rate. See dungeon_system_logic.md for the fixed-vs-batch roll.

    Batch nodes are floor-wide — any batch content can roll
    regardless of branch. Fixed nodes are NOT floor-wide — each is
    assigned to a specific branch (see cinder_hollow_data.py's
    FLOOR_1_BRANCH_ASSIGNMENTS), so the fixed-roll candidate pool is
    restricted to whichever branch the player is currently on.
    """
    session = DungeonSession.load(db, sender)
    if not session.is_locked_in():
        return "You're not inside a dungeon."
    if session.paused_for_battle:
        return "You're in the middle of something — resolve that first."

    arrival_msg = check_goto_arrival(session, db)
    if arrival_msg:
        return arrival_msg
    if session.goto_in_progress():
        return "You're still on your way somewhere — use .stop to interrupt the journey."

    floor = get_floor(session.dungeon_id, session.floor)
    if not floor:
        return None  # TODO: shouldn't happen — guard for now

    branch = session.current_branch()
    if branch is None:
        # Standing on a spine node — spines never roll anything, fixed
        # or batch. .advance (choosing a direction) is required first;
        # .dive here is a no-op and does NOT count toward the
        # diminishing-returns dive counter.
        return "To advance, pick a path forward.\n.advance"

    session.increment_dive(session.floor)

    already_placed = set(session.node_positions.get(str(session.floor), {}).keys())
    branch_fixed_ids = [
        nid for nid in floor.fixed_ids_for_branch(branch)
        if nid not in already_placed
    ]

    # TODO: diminishing-returns curve — ~20 uses should approach
    # "found everything in this segment" per the design notes. Not
    # yet implemented; currently just rolls flat every time. Note
    # branch_fixed_ids naturally shrinks toward empty as nodes get
    # placed, which is A form of diminishing returns for the fixed
    # pool specifically, but doesn't touch encounter/batch odds.
    pool_kind, node = roll_path_node(floor, remaining_fixed_ids=branch_fixed_ids)

    if pool_kind == NODE_FIXED and node is not None:
        position = {"branch": list(branch), "depth": session.current_depth() + 1}
        session.advance_depth()
        session.record_discovery(session.floor, node.node_id, position=position)
        session.advance_to_node(node.node_id, position)
        session.save(db)

        if node.is_subzone:
            return _resolve_subzone_encounter(session, node, db)
        if node.encounter and node.encounter.get("tier") == "elite":
            return _resolve_elite_node(session, node, db, player, combat_session)
        # TODO: other non-subzone fixed node kinds (hazard, lore beat,
        # non-elite encounter pocket) resolution — route into battle/
        # trap/flavor as appropriate to node.tags.
        return node.description

    # NODE_BATCH — floor-wide, no branch restriction, so it doesn't
    # get its own persistent node_id/position the way fixed nodes do
    # (nothing to .goto back to — batch filler isn't a discoverable
    # place). Still advances depth so distance math for later fixed
    # finds on this branch stays consistent.
    session.advance_depth()
    session.save(db)
    # TODO: batch content generation — see dungeon_system_logic.md's
    # open question. Placeholder flavor line for now.
    return "You press deeper into the dark, nothing of note catching your eye."


def _resolve_subzone_encounter(session, node, db):
    """
    Handles Find vs. Enter messaging + reward scope for a discovered
    subzone. See dungeon_system_logic.md's "Discovery/consumption
    scope" and "Find vs. Enter messaging" sections.
    """
    already_found = node.node_id in session.discovered_for_floor(session.floor)

    # TODO: world-level scope (SCOPE_WORLD_ONE_SHOT / SCOPE_WORLD_REPEATABLE)
    # needs a WORLD-level (not per-player) discovery check against the
    # database, not just this player's session — e.g. "has ANY player
    # ever found the Ore Vein." Session-level `already_found` below only
    # covers per-player scope correctly; world scope needs its own
    # db-backed flag, not implemented in this skeleton yet.

    if not already_found:
        session.record_discovery(session.floor, node.node_id)
        session.save(db)
        # TODO: grant node.on_find reward.
        return f"You found {node.node_id}!\n\n{node.description}"

    # TODO: node.on_enter — for first_clear_bonus scope, roll
    # inferior-but-equal-tier loot here instead of nothing.
    return node.description


def _resolve_elite_node(session, node, db, player, combat_session):
    """
    Elite Encounter — repeatable, but gated by a global (all-players)
    5-minute cooldown that starts only once the Elite is actually
    defeated. See dungeon_system_logic.md / dungeon-system memory.

    combat_session: the player's CombatSession (combat_session.py) —
    needed to actually arm the fight. Mirrors arena.py's arena_enter().
    """
    if elite_on_cooldown(db, session.dungeon_id, session.floor):
        player_level = getattr(player, "level", None)
        elite_level = node.encounter.get("level")  # TODO: not yet populated in cinder_hollow_data.py

        base = (
            "You see the remains of an elite monster. "
            "It appears someone beat you to it."
        )
        if player_level is not None and elite_level is not None:
            if player_level < elite_level:
                base += "\n\n_Thank the heavens._"
            else:
                base += "\n\n_Tough luck, huh?_"
        return base

    # Not on cooldown — trigger the fight. Same set_meta + arm pattern
    # as arena.py's arena_enter(): a flag combat_session.py's win
    # resolution (battle.py's _victory) checks to know this round-won
    # branch is a dungeon Elite, not a regular trainer/gym fight.
    # See battle.py's "dungeon_elite_battle" branch in _victory().
    import json
    elite_name = node.encounter.get("name") or "Elite Guardian"
    team = node.encounter.get("team")
    if not team:
        # TODO: single-mon Elite roster not yet drafted for Cinder
        # Hollow — encounter["team"] is currently only populated for
        # the Chained Encounter Zone's Undead Miner, not this node.
        # Nothing to fight yet; bail out with the flavor description.
        return node.description

    db.set_meta(session.sender, "dungeon_elite_battle", json.dumps({
        "dungeon_id": session.dungeon_id,
        "floor": session.floor,
    }))
    combat_session.arm_trainer_battle(elite_name, team, round_num=1)
    session.paused_for_battle = True
    session.save(db)

    return f"⚔️ *{elite_name}* blocks your path!\n\n{node.description}"


# ── .look ──────────────────────────────────────────────────────

def handle_look(sender, player, db):
    """Single roll of what's visible right now — not repeatable-scan like .dive."""
    session = DungeonSession.load(db, sender)
    if not session.is_locked_in():
        return "You're not inside a dungeon."
    # TODO: single roll, zone-dependent result.
    return None


# ── .hunt ──────────────────────────────────────────────────────

def handle_hunt(sender, player, db):
    """Actively seek a fight — higher encounter/chained-fight rate, no forward movement."""
    session = DungeonSession.load(db, sender)
    if not session.is_locked_in():
        return "You're not inside a dungeon."
    # TODO: encounter roll, chained-fight roll (reuse arena_trainer_team
    # via combat_session.py's set_trainer_battle with battle_context="dungeon").
    return None


# ── Gathering: .mine / .dig / .fish ──────────────────────────────

def handle_mine(sender, player, db):
    session = DungeonSession.load(db, sender)
    if not session.is_locked_in():
        return "You're not inside a dungeon."
    # TODO: reliable if a vein was already discovered at this node, low odds otherwise.
    return None


def handle_dig(sender, player, db):
    session = DungeonSession.load(db, sender)
    if not session.is_locked_in():
        return "You're not inside a dungeon."
    # TODO: low flat odds anywhere.
    return None


def handle_fish(sender, player, db):
    session = DungeonSession.load(db, sender)
    if not session.is_locked_in():
        return "You're not inside a dungeon."
    # TODO: only works if current node has water (node.tags includes "water").
    return None


# ── Combat-adjacent: .ambush / .trap ─────────────────────────────
# Not fully defined yet — see dungeon_system_logic.md.

def handle_ambush(sender, player, db):
    session = DungeonSession.load(db, sender)
    if not session.is_locked_in():
        return "You're not inside a dungeon."
    # TODO: stealth/first-strike variant of .hunt — not yet defined.
    return None


def handle_trap(sender, player, db):
    session = DungeonSession.load(db, sender)
    if not session.is_locked_in():
        return "You're not inside a dungeon."
    # TODO: player-facing reaction to a passively-detected trap — relationship
    # to passive detection not yet clarified.
    return None


# ── Movement: .advance / .goback / .goto ─────────────────────────

def handle_advance(sender, player, db, args=None):
    """
    Move forward. From a spine node with more than one outgoing path
    (a fork), the player must choose a direction — that choice
    commits current_position to depth 0 on that branch and sticks
    until the next spine node is reached (see dungeon-system memory:
    ".goto timer" / branch commitment).
    """
    session = DungeonSession.load(db, sender)
    if not session.is_locked_in():
        return "You're not inside a dungeon."

    floor = get_floor(session.dungeon_id, session.floor)
    if not floor:
        return None  # TODO: shouldn't happen — guard for now

    # Already committed to a branch — .advance here means "go deeper
    # on the current branch," which is really just .dive placing the
    # next node. TODO: clarify whether .advance and .dive are meant
    # to be the same action once mid-branch, or .advance is purely
    # for the fork-choice / spine-to-spine step. Left unresolved —
    # only the fork-choice case is implemented below.
    if session.current_branch() is not None:
        return None  # TODO: mid-branch .advance behavior not yet defined

    # Standing on a spine node — find outgoing branches from here.
    outgoing = [b for b in floor.paths.keys() if b[0] == session.current_node]

    if not outgoing:
        return "There's nowhere forward from here."

    if len(outgoing) == 1:
        session.choose_branch(outgoing[0])
        session.save(db)
        return "You head onward."

    # Multiple outgoing branches — a fork, need an explicit choice.
    target_label = (args[0] if args else None)
    if not target_label:
        options = "\n".join(f"- {b[1]}" for b in outgoing)
        return f"Which way?\n{options}"

    chosen = next((b for b in outgoing if b[1] == target_label), None)
    if not chosen:
        return "That's not a direction you can go from here."

    session.choose_branch(chosen)
    session.save(db)
    return f"You head toward {chosen[1]}."


def handle_goback(sender, player, db):
    session = DungeonSession.load(db, sender)
    if not session.is_locked_in():
        return "You're not inside a dungeon."
    # TODO: retreat to the previous node.
    return None


def handle_goto(sender, player, args, db, combat_session=None):
    """
    Fast-travel to a previously discovered subzone. Not a teleport —
    this is real movement through the dungeon at 5 seconds/step (see
    dungeon-system memory, ".goto timer"). Since it's real movement,
    each step along the way can roll a fixed/batch node exactly like
    .dive would, if that waypoint hasn't been placed yet — arriving
    isn't the only thing that can happen during the trip.

    Proactively pushes each step's result via a threading.Timer
    (mirrors router/explore.py's _arm_arrival_timer) instead of
    silently waiting for the player's next message. Use .stop to
    interrupt the journey early — lands wherever elapsed time reached.
    """
    session = DungeonSession.load(db, sender)
    if not session.is_locked_in():
        return "You're not inside a dungeon."

    if session.goto_in_progress():
        return "You're already on your way somewhere — use .stop to interrupt the journey."

    target = args[0] if args else None
    if not target:
        discovered = session.discovered_for_floor(session.floor)
        if not discovered:
            return "You haven't discovered any locations to fast-travel to yet."
        return "Known locations:\n" + "\n".join(f"- {n}" for n in discovered)

    if target not in session.discovered_for_floor(session.floor):
        return "You haven't discovered that location yet."

    floor = get_floor(session.dungeon_id, session.floor)
    if not floor:
        return None  # TODO: shouldn't happen — guard for now

    target_position = session.position_of(session.floor, target)
    total_steps = goto_distance(
        floor,
        session.current_position, session.current_node,
        target_position, target,
    )
    if total_steps is None:
        return None  # TODO: shouldn't happen if position tracking is consistent — guard for now

    if total_steps == 0:
        return "You're already there."

    session.start_goto_journey(
        session.current_node, session.current_position,
        target, target_position,
        total_steps, GOTO_SECONDS_PER_NODE,
    )
    session.save(db)

    _arm_goto_step_timer(sender, db, GOTO_SECONDS_PER_NODE, combat_session)

    return (
        f"You set off toward {target}. ({total_steps * GOTO_SECONDS_PER_NODE}s)\n"
        f"_.stop to interrupt the journey early._"
    )


def handle_stop(sender, player, db):
    """
    Interrupt an in-progress .goto journey. Lands the player at
    whichever tile their elapsed travel time actually reached — NOT
    the destination, and not necessarily the origin either. If the
    journey had already fully elapsed, this behaves like a normal
    arrival (see _resolve_goto_step).
    """
    session = DungeonSession.load(db, sender)
    if not session.is_locked_in():
        return "You're not inside a dungeon."
    if not session.goto_in_progress():
        return "You're not traveling anywhere right now."

    return _resolve_goto_step(session, db, interrupted=True)


def _arm_goto_step_timer(sender, db, seconds, combat_session):
    """
    Proactively pushes each step of an in-progress .goto journey once
    it elapses, instead of waiting for the player's next message.
    Mirrors router/explore.py's _arm_arrival_timer exactly: re-derives
    state fresh at fire time (the journey may have been .stop'd or
    already resolved in the meantime), serializes DB access through
    the sender's existing lock, and stops re-arming while
    paused_for_battle (an encounter rolled mid-step) until that's
    resolved.
    """
    def _fire():
        lock = _get_sender_lock(sender) if _get_sender_lock else None
        if lock:
            lock.acquire()
        try:
            session = DungeonSession.load(db, sender)
            if not session.goto_in_progress():
                return  # already .stop'd or resolved via a passive check
            msg = _resolve_goto_step(session, db, interrupted=False, combat_session=combat_session)
            if msg:
                _push(sender, msg)
            # If the journey is still going (this step landed but more
            # remain) and isn't waiting on a battle reply, arm the next
            # step. paused_for_battle stops re-arming here; whatever
            # resolves the battle is responsible for re-arming once
            # the player is clear to keep moving (not yet wired up —
            # see paused_for_battle TODO below).
            session = DungeonSession.load(db, sender)
            if session.goto_in_progress() and not session.paused_for_battle:
                _arm_goto_step_timer(sender, db, seconds, combat_session)
        finally:
            if lock:
                lock.release()

    t = threading.Timer(seconds, _fire)
    t.daemon = True
    t.start()


def _resolve_goto_step(session, db, interrupted=False, combat_session=None):
    """
    Shared step-resolution logic for .stop, a timer-driven live push,
    and lazy catch-up if a live push was missed (process restart,
    etc.) — checked at the top of any dungeon command via
    check_goto_arrival(). Advances the player exactly ONE step's worth
    of elapsed time along the route (not straight to wherever the
    full elapsed time would land them — see note below), rolling a
    fixed/batch node at that waypoint if it hasn't been placed yet
    (this IS movement, so it rolls the same way .dive does), and
    clears the journey once the destination is reached.

    NOTE: interrupted (.stop) still needs "land wherever the FULL
    elapsed time reached," not just one step — see the branch below.
    """
    floor = get_floor(session.dungeon_id, session.floor)
    if not floor:
        return None  # TODO: shouldn't happen — guard for now

    journey = session.goto_journey
    route = trace_goto_route(
        floor,
        journey["from_position"], journey["from_node_id"],
        journey["to_position"], journey["to_node_id"],
    )
    if route is None:
        session.end_goto_journey()
        session.save(db)
        return None  # TODO: shouldn't happen — guard for now

    # .stop lands wherever the FULL elapsed time reached (may be
    # several steps at once, e.g. if the player was away and comes
    # back late). A timer-driven step or lazy catch-up without .stop
    # only advances by whatever's actually elapsed, same computation —
    # goto_elapsed_steps() already caps to total_steps either way, so
    # this is really the same landing logic for both; interrupted only
    # changes the wording of the message, not how far the player moves.
    elapsed_steps = session.goto_elapsed_steps()
    waypoint = route[elapsed_steps]
    arrived = elapsed_steps >= journey["total_steps"]

    roll_msg = None
    if not waypoint["label"]:
        branch = tuple(waypoint["position"]["branch"])
        # TODO: no reverse index exists yet mapping (branch, depth) ->
        # "is there already a fixed node placed here?" — node_positions
        # is keyed by node_id, not by position. Until that exists,
        # every unplaced-looking step through a branch re-rolls fresh,
        # which could in theory double-place a fixed node at a depth
        # that's secretly already taken by an earlier visit. Flagging
        # rather than guessing at the reverse-index shape.
        branch_fixed_ids = [
            nid for nid in floor.fixed_ids_for_branch(branch)
            if nid not in session.node_positions.get(str(session.floor), {})
        ]
        pool_kind, node = roll_path_node(floor, remaining_fixed_ids=branch_fixed_ids)
        if pool_kind == NODE_FIXED and node is not None:
            session.record_discovery(session.floor, node.node_id, position=dict(waypoint["position"]))
            if node.is_subzone:
                roll_msg = _resolve_subzone_encounter(session, node, db)
            elif node.encounter and node.encounter.get("tier") == "elite":
                roll_msg = _resolve_elite_node(session, node, db, None, combat_session)  # TODO: player not threaded through the timer path yet — level-relative Elite-remains line won't render on a mid-goto Elite hit
            else:
                # TODO: same non-elite fixed node resolution gap as .dive.
                roll_msg = node.description
        # NODE_BATCH: floor-wide flavor, nothing to report per-step —
        # same as .dive's batch branch, stays silent.

    if arrived or interrupted:
        session.end_goto_journey()
    if waypoint["label"] is not None:
        session.advance_to_node(waypoint["label"], None)
        landing_desc = f"the *{waypoint['label']}*"
    else:
        session.advance_to_node(journey["to_node_id"] if arrived else None, waypoint["position"])
        branch = tuple(waypoint["position"]["branch"])
        landing_desc = f"the *{floor.branch_root(branch)}* path"  # TODO: branches don't have proper display names yet — using the root spine node as a stand-in label

    if not arrived:
        # Still journeying — persist the advanced position but keep
        # goto_journey alive so the next step continues from here.
        # start_goto_journey isn't re-called; goto_journey's own
        # start_time/total_steps stay put, elapsed steps are computed
        # fresh next time from the ORIGINAL start_time, so this doesn't
        # double-count time already spent.
        pass
    session.save(db)

    if arrived:
        return f"You arrive at {journey['to_node_id']}."

    if interrupted:
        return f"You have stopped somewhere along {landing_desc}. What would you like to do?"

    # Timer-driven step or lazy catch-up mid-journey — only worth a
    # message if something actually happened (a roll fired); a quiet
    # batch/no-op step doesn't need to interrupt the player.
    return roll_msg


def check_goto_arrival(session, db):
    """
    Lazy safety net: if a .goto journey has fully elapsed by the time
    the player's next command comes in (e.g. the live-push timer
    didn't fire — process restart, etc.), resolve the arrival now
    instead of requiring an explicit .stop. The live-push timer (see
    _arm_goto_step_timer) is the PRIMARY mechanism; this is a
    fallback, not the main path. Returns the arrival message if one
    fired, else None (nothing to report, caller proceeds normally).
    """
    if not session.goto_in_progress():
        return None
    if not session.goto_has_arrived():
        return None
    return _resolve_goto_step(session, db, interrupted=False)


# ── .forfeit ──────────────────────────────────────────────────────

def handle_forfeit(sender, player, db):
    """
    Give up the run. Exact consequence vs. death/checkpoint not yet
    defined — currently bounces to the last checkpoint, matching
    death behavior, pending a real design decision.
    """
    session = DungeonSession.load(db, sender)
    if not session.is_locked_in():
        return "You're not inside a dungeon."

    # TODO: confirm forfeit should behave like death (return_to_checkpoint)
    # vs. a harsher/softer consequence — open question in the design notes.
    session.return_to_checkpoint()
    session.save(db)
    return "You give up the run and retreat to your last checkpoint."


# ── Floor progression ─────────────────────────────────────────────

def handle_advance_floor(sender, player, db):
    """
    Explicit next-floor command — NOT folded into .dive. Only usable
    once that floor's entrance has actually been found via diving.
    """
    session = DungeonSession.load(db, sender)
    if not session.is_locked_in():
        return "You're not inside a dungeon."

    # TODO: verify the next floor's entrance was actually discovered
    # this run before allowing this — currently unguarded.
    next_floor = session.floor + 1
    next_floor_data = get_floor(session.dungeon_id, next_floor)
    if not next_floor_data:
        return "There's nowhere further to go."

    session.advance_floor(next_floor, next_floor_data.spine_entrance())
    session.save(db)
    return f"You descend to Floor {next_floor}."


# ── Death / party wipe ─────────────────────────────────────────────

def handle_dungeon_death(sender, player, db):
    """
    Party wipe. Exact result (checkpoint vs. entrance, any penalty)
    not decided — see dungeon_system_logic.md's "Still undecided".
    Currently bounces to the floor's last checkpoint.
    """
    session = DungeonSession.load(db, sender)
    if not session.is_active():
        return None

    # TODO: confirm checkpoint-bounce is the real intended behavior,
    # and whether there's any additional penalty (item loss, etc.)
    session.return_to_checkpoint()
    session.save(db)
    return "Your party has fallen. You wake back at your last checkpoint."
