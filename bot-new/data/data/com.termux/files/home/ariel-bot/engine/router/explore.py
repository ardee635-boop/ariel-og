# ============================================================
# NIFLHEIM — router/explore.py
# .explore / .end / .zone command logic (Phase 5)
# ============================================================

import random
import threading

from explore_session import ExploreSession, PendingMenu
from encounter_tables import EXPLORE_DESTINATIONS, ZONE_BORDER_TIME, ENCOUNTER_TABLES

try:
    # bridge.py owns the live WhatsApp send function. explore.py used
    # to reach for it via `import router as _router; _router._direct_send`,
    # but that's a naming collision: bridge.py's `_router` is its own
    # CommandRouter *instance* (`_router = CommandRouter(_db)`), and
    # `_router._direct_send = _direct_send` attaches the function to
    # THAT instance — not to the `router` package/module that
    # `import router as _router` actually gives you here. The two
    # "_router"s are different objects, so the old lookup always found
    # nothing and _push() silently no-op'd on every real deploy. Import
    # the function directly from bridge instead, same pattern already
    # used for _get_sender_lock below.
    from bridge import _direct_send
except ImportError:
    _direct_send = None

try:
    # Same per-sender lock bridge.py already uses to serialize a
    # sender's own messages against each other (concurrent DB access
    # across threads is a real, already-handled concern in this
    # codebase — reusing it here rather than inventing new locking).
    from bridge import _get_sender_lock
except ImportError:
    _get_sender_lock = None


def _push(target_jid, message):
    """
    Proactively send `message` to `target_jid` without waiting for the
    player's next inbound message — mirrors index.js's .mine mechanism
    (a real timer that pushes via the live WhatsApp socket) rather than
    the passive tick-catchup used everywhere else in this file.

    target_jid should be the chat the journey started in (a group JID,
    normally — see session.group_jid in explore_session.py) so the
    arrival lands back where the player was playing, not their DM.
    allow_dm=True is still passed so a genuinely DM-started journey
    (group_jid unset, falls back to sender) still gets through
    index.js's isAllowedDM check; it's a no-op for group targets,
    which already pass via isAllowedGroup regardless of this flag.

    Calls bridge.py's _direct_send directly (imported at module load,
    see note above) which writes a __push__ line to stdout; index.js
    is already listening for that and forwards it via activeSockRef.
    """
    if not _direct_send:
        return  # not running under the live bridge — no-op (e.g. tests)
    _direct_send(message, group_jid=target_jid, allow_dm=True)

DIRECTION_ALIASES = {
    "n": "north", "north": "north",
    "s": "south", "south": "south",
    "e": "east",  "east":  "east",
    "w": "west",  "west":  "west",
}

# Minimal zone info used by .explore/.zone until the full zone-data
# registry (world_registry.py) is extended — placeholder for this slice.
ZONE_INFO = {
    "oak_town": {
        "name": "Oak Town", "status": "Town", "danger_tier": 0,
    },
    "ashfall_village": {
        "name": "Ashfall Village", "status": "Town", "danger_tier": 1,
        "description": "A quiet farming-town breeze settles in as the "
                        "path opens up ahead. Ashfall Village stretches "
                        "out before you.",
        "poke_center": True,
        "gyms": "Ash Gym",
        "arenas": "None",
        "dungeons": "None",
        "specialty": "Ash Herbs (use .info to know more)",
        "actions": [".shop", ".bar", ".rest", ".pheal", ".gossip"],
    },
    "ember_path": {
        "name": "Ember Path", "status": "Route", "danger_tier": 1,
        "description": "Scorched earth crunches underfoot as embers "
                        "drift lazily through the warm air.",
        "actions": [".hunt", ".explore [direction]"],
    },
    "cinder_hollow": {
        "name": "Cinder Hollow", "status": "Dungeon", "danger_tier": 2,
        "description": "The air here is thick with ash and heat — "
                        "something stirs in the gloom ahead.",
        "actions": [".hunt", ".explore [direction]"],
    },
    "elmwood_trail": {
        "name": "Elmwood Trail", "status": "Route", "danger_tier": 1,
        "description": "Tall grass sways along a well-worn dirt path, "
                        "the scent of hay drifting in from somewhere "
                        "nearby.",
        "actions": [".hunt", ".explore [direction]"],
    },
    "elmwood_farm": {
        "name": "Elmwood Farm", "status": "Route", "danger_tier": 1,
        "description": "Fenced fields stretch out on either side, "
                        "grazing Pokémon barely glancing up as you pass.",
        "actions": [".hunt", ".explore [direction]"],
    },
    "elmwood": {
        "name": "Elmwood", "status": "Town", "danger_tier": 0,
        "description": "A cozy farming town built around its harvest — "
                        "the smell of fresh bread hangs in the air.",
        "poke_center": True,
        "gyms": "None",
        "arenas": "None",
        "dungeons": "None",
        "specialty": "TBD (use .info to know more)",
        "actions": [".shop", ".bar", ".rest", ".pheal", ".gossip"],
    },
}


TICK_SECONDS = 3
# How often the background timer wakes up to check whether a tick/
# arrival is due, vs. TICK_SECONDS (how often an event actually rolls).
# Same relationship as checking your mailbox once an hour for mail that
# only arrives once a day — most checks find nothing new, but nothing
# waits longer than CHECK_INTERVAL_SECONDS to be noticed once it lands.
CHECK_INTERVAL_SECONDS = 1

# Event odds per tick, checked in order — first match wins.
# (Section 3: wild encounter / item find / fork discovery)
TICK_ENCOUNTER_CHANCE = 0.12
TICK_ITEM_CHANCE      = 0.08
# Fork discovery deferred — needs Phase 6 per-player discovery
# tracking to know what's still undiscovered; not rolled yet.


def _roll_tick_event(zone):
    """
    One tick's roll for the given (current effective) zone. Returns
    a dict describing the event, or None if nothing happened.
    Encounter difficulty uses the CURRENT zone's own level_range,
    not the journey's origin/destination (Section 16).
    """
    roll = random.random()
    if roll < TICK_ENCOUNTER_CHANCE:
        table = ENCOUNTER_TABLES.get(zone)
        if table:
            pool = table.get("grass", [])
            if pool:
                names   = [n for n, _ in pool]
                weights = [w for _, w in pool]
                name    = random.choices(names, weights=weights, k=1)[0]
                lo, hi  = table.get("level_range", [1, 5])
                level   = random.randint(lo, hi)
                return {"type": "encounter", "name": name, "level": level}
        return None
    if roll < TICK_ENCOUNTER_CHANCE + TICK_ITEM_CHANCE:
        # Field find — a basic Poké Ball, same item players buy from the
        # shop (router/shop.py's inventory pattern), so .inv/.use treat
        # it identically either way.
        return {"type": "item", "name": "Poké Ball", "qty": 1}
    return None


def _resolve_direction(raw):
    if not raw:
        return None
    return DIRECTION_ALIASES.get(raw.strip().lower())


def _discovered_for(player, zone, direction):
    """Set of destination ids this player has personally reached for zone+direction."""
    zone_map = player.discovered_connections.get(zone, {})
    return set(zone_map.get(direction, []))


def _mark_discovered(player, zone, direction, destination):
    zone_map = player.discovered_connections.setdefault(zone, {})
    found = zone_map.setdefault(direction, [])
    if destination not in found:
        found.append(destination)


def _roll_destination(zone, direction):
    """Weighted pick among EXPLORE_DESTINATIONS[zone][direction]. None = dead-end."""
    options = EXPLORE_DESTINATIONS.get(zone, {}).get(direction)
    if not options:
        return None
    names   = [o["to"] for o in options]
    weights = [o["weight"] for o in options]
    picked  = random.choices(names, weights=weights, k=1)[0]
    for o in options:
        if o["to"] == picked:
            return o["to"], o["time_s"]
    return None


def _roll_undiscovered(options, discovered):
    """Weighted pick among only the options not yet in `discovered`."""
    remaining = [o for o in options if o["to"] not in discovered]
    if not remaining:
        return None
    names   = [o["to"] for o in remaining]
    weights = [o["weight"] for o in remaining]
    picked  = random.choices(names, weights=weights, k=1)[0]
    for o in remaining:
        if o["to"] == picked:
            return o["to"], o["time_s"]
    return None


def handle_explore(sender, player, args, db, save_fn, group_jid=None, router=None):
    session = ExploreSession.load(db, sender)

    # Same gap .zone had: is_active() only checks whether a session
    # row exists, not whether its travel time already elapsed. Without
    # resolving arrival first, a finished-but-unresolved journey would
    # either block a new .explore forever with "already traveling", or
    # (if something else happened to clear it later) let a brand new
    # journey silently overwrite one that should have arrived. Resolve
    # first, same pattern as handle_end/handle_zone.
    if session.is_active() and session.has_arrived():
        handle_journey_tick(sender, player, db, save_fn, force_arrival=True, router=router)
        session = ExploreSession.load(db, sender)

    if session.is_active():
        return (
            "You're already traveling. Use .end to stop.\n"
            f"Current zone: {ZONE_INFO.get(session.current_zone, {}).get('name', session.current_zone)}"
        )

    origin = player.zone
    first_arg = args[0] if args else None

    # Numbered menu pick (e.g. ".explore 2") — uses the stored pending
    # menu (Section 18 fix) rather than re-guessing which direction it
    # was for.
    if first_arg and first_arg.strip().isdigit():
        return _handle_menu_pick(sender, player, origin, int(first_arg.strip()), db, group_jid, router)

    direction = _resolve_direction(first_arg)
    if not direction:
        return "Usage: .explore <north/south/east/west>"

    # A fresh directional explore supersedes any stale pending menu.
    PendingMenu(sender).save(db)

    options = EXPLORE_DESTINATIONS.get(origin, {}).get(direction)

    if not options:
        # Dead-end: touch the border, bounce straight back.
        border_time = ZONE_BORDER_TIME.get(origin, 5)
        origin_name = ZONE_INFO.get(origin, {}).get("name", origin)
        return (
            f'"Looks like a dead end..." You murmur as you stare at '
            f'the cliff before you.\n'
            f"You decide to head back to {origin_name}.\n"
            f"Current zone: {origin_name}"
        )

    discovered = _discovered_for(player, origin, direction)

    # Section 18: repeat-explore menu — only shown once the player has
    # found at least one option here AND at least one remains unfound.
    if len(options) > 1 and discovered and len(discovered) < len(options):
        menu = PendingMenu(sender)
        menu.set(origin, direction)
        menu.save(db)
        return _build_menu(player, origin, direction, options, discovered)

    # First-ever visit to this zone+direction, OR every option already
    # discovered (nothing left to surprise the player with) — silent
    # weighted pick same as Section 3/7.
    if discovered and len(discovered) >= len(options):
        result = _roll_destination(origin, direction)
    elif not discovered:
        result = _roll_destination(origin, direction)
    else:
        result = _roll_undiscovered(options, discovered)

    return _start_journey(sender, session, origin, direction, result, db, group_jid, router)


def _build_menu(player, origin, direction, options, discovered):
    lines = [
        "You are about to head out on your adventure, but you notice "
        "a new uncharted path. Where would you like to go next?",
        "",
    ]
    numbered = []
    for o in options:
        if o["to"] in discovered:
            numbered.append(o["to"])
    numbered.append("__unknown__")  # sentinel for "Explore the unknown"

    for i, entry in enumerate(numbered, start=1):
        if entry == "__unknown__":
            lines.append(f'{i}. Explore the unknown\n   ↳ reply with .explore {i}')
        else:
            name = ZONE_INFO.get(entry, {}).get("name", entry)
            lines.append(f'{i}. Go to "{name}"\n   ↳ reply with .explore {i}')

    # Stash the menu ordering so the numbered pick can be resolved
    # deterministically — reuses player_meta the same way ExploreSession
    # does, keyed per zone+direction so multiple pending menus can't clash.
    return "\n".join(lines)


def _handle_menu_pick(sender, player, origin, choice_num, db, group_jid=None, router=None):
    """
    Resolves a numbered ".explore N" reply against the stored pending
    menu (Section 18 fix) — no guessing which direction it was for.
    """
    menu = PendingMenu.load(db, sender)
    if not menu.is_active() or menu.zone != origin:
        return "That number doesn't match anything right now. Try .explore <direction>."

    direction = menu.direction
    options   = EXPLORE_DESTINATIONS.get(origin, {}).get(direction, [])
    discovered = _discovered_for(player, origin, direction)

    numbered = [o["to"] for o in options if o["to"] in discovered]
    numbered.append("__unknown__")

    if not (1 <= choice_num <= len(numbered)):
        return "That number doesn't match anything right now. Try .explore <direction>."

    picked = numbered[choice_num - 1]
    if picked == "__unknown__":
        result = _roll_undiscovered(options, discovered)
    else:
        match = next((o for o in options if o["to"] == picked), None)
        result = (match["to"], match["time_s"]) if match else None

    menu.clear()
    menu.save(db)

    session = ExploreSession.load(db, sender)
    return _start_journey(sender, session, origin, direction, result, db, group_jid, router)


def _arm_arrival_timer(sender, db, seconds, router=None):
    """
    Proactively pushes the arrival (or next due tick event) once this
    journey's travel time elapses, instead of waiting for the player's
    next message. Mirrors index.js's .mine timer pattern on the JS
    side; here it's a threading.Timer inside Python's long-running
    subprocess (confirmed alive for the process's full lifetime, same
    as combat_session.py's existing encounter timers).

    Re-derives everything fresh at fire time rather than trusting
    closure-captured state — the journey may have been .end'd, or
    already resolved by a passive tick-catchup, in the meantime.
    DB access is serialized through the sender's existing lock to
    avoid racing the main message-handling thread pool.

    `router` is the one deliberate exception to "re-derive everything
    fresh": CombatSession lives in-memory only (router.sessions[sender],
    see router/__init__.py's _session()) — there's nothing in the DB
    to re-derive it from. It's captured in this closure at arm-time
    instead. If the process restarts, this closure and the whole timer
    chain die together anyway (same as everything else in this
    function), so a stale reference here isn't a new failure mode.
    """
    def _fire():
        lock = _get_sender_lock(sender) if _get_sender_lock else None
        if lock:
            lock.acquire()
        try:
            player = db.load(sender)
            if not player:
                return
            session = ExploreSession.load(db, sender)
            if not session.is_active():
                return  # already ended/resolved via a passive check
            msg = handle_journey_tick(sender, player, db, lambda: db.save(sender, player), router=router)
            if msg:
                # Push back to the chat the journey started in, not the
                # player's DM — session.group_jid is captured once at
                # journey start (see explore_session.py) specifically to
                # avoid this. Falls back to sender only for sessions
                # saved before this field existed, or a journey that
                # genuinely started in a DM.
                target = session.group_jid or sender
                _push(target, msg)
        except Exception as e:
            # A bad tick (bug, transient DB hiccup, whatever) must not
            # silently end the whole check-in chain — without this,
            # one exception here means the session sits "active" in
            # the DB forever with nothing checking on it again until
            # the player happens to send a command themselves.
            import sys
            print(f"[EXPLORE TIMER] tick failed for {sender}: {e}", file=sys.stderr, flush=True)
        finally:
            if lock:
                lock.release()

        # Re-arm outside the try/except and outside the lock: even if
        # the tick above failed, we still want another check in
        # CHECK_INTERVAL_SECONDS rather than giving up on the journey.
        # (This still can't survive the whole process going to sleep —
        # a daemon thread dies with the process; that part needs an
        # always-on host, not a code fix.)
        try:
            session = ExploreSession.load(db, sender)
            if session.is_active() and not session.paused_for_battle:
                _arm_arrival_timer(sender, db, CHECK_INTERVAL_SECONDS, router)
        except Exception as e:
            import sys
            print(f"[EXPLORE TIMER] re-arm failed for {sender}: {e}", file=sys.stderr, flush=True)

    t = threading.Timer(seconds, _fire)
    t.daemon = True
    t.start()


def _start_journey(sender, session, origin, direction, result, db, group_jid=None, router=None):
    if result is None:
        border_time = ZONE_BORDER_TIME.get(origin, 5)
        origin_name = ZONE_INFO.get(origin, {}).get("name", origin)
        return (
            f'"Looks like a dead end..." You murmur as you stare at '
            f'the cliff before you.\n'
            f"You decide to head back to {origin_name}.\n"
            f"Current zone: {origin_name}"
        )

    destination, time_s = result
    session.start(origin, direction, destination, time_s, group_jid)
    session.save(db)

    # Proactive push (Section 3 fix) — mirrors index.js's .mine timer
    # so arrival/events show up without the player sending anything.
    _arm_arrival_timer(sender, db, min(CHECK_INTERVAL_SECONDS, time_s), router)

    origin_name = ZONE_INFO.get(origin, {}).get("name", origin)
    return (
        f"You leave {origin_name}, heading {direction}...\n\n"
        f"Travel time: {int(time_s)}s\n"
        f"Use .end to stop\n"
        f"Use .zone to see more details"
    )


def handle_end(sender, player, db, save_fn, router=None):
    session = ExploreSession.load(db, sender)

    if not session.is_active():
        return "You're not currently traveling."

    # Natural arrival already elapsed — treat as a real arrival, not a cancel.
    if session.has_arrived():
        return handle_journey_tick(sender, player, db, save_fn, force_arrival=True, router=router)

    landing_zone = session.current_zone
    session.end()
    session.save(db)

    landing_name = ZONE_INFO.get(landing_zone, {}).get("name", landing_zone)
    return (
        "You stop and turn back before reaching your destination.\n\n"
        f"Current zone: {landing_name}"
    )


def handle_journey_tick(sender, player, db, save_fn, force_arrival=False, router=None):
    """
    Called on a player's next command while a journey is active (or by
    .end once time has elapsed). WhatsApp has no persistent connection
    (Section 3), so there's no live background loop pushing ticks —
    instead, this catches up every 3s tick that elapsed since the last
    check, in order, stopping early if an encounter fires (the journey
    pauses for battle/catch/flee — Section 2's reused .hunt mechanism)
    or once arrival time is reached.

    `router` gives access to the in-memory CombatSession
    (router.sessions[sender], see router/__init__.py's _session()) so
    a rolled encounter can actually be spawned into a real battle, the
    same way router/movement.py's legacy grass-tile encounters do —
    not just printed as flavor text. Without a router reference (e.g.
    a caller that predates this wiring), the encounter still pauses
    the journey exactly as before but can't start a real battle.

    Returns a message string if there's something to show the player
    (an event or an arrival), or None if nothing happened yet.
    """
    session = ExploreSession.load(db, sender)
    if not session.is_active():
        return None

    # Already paused on an unresolved encounter — don't roll further
    # ticks or spawn a second encounter on top of it. This is called
    # on every non-explore/dungeon command (see handle.py's dispatch),
    # so without this guard any command the player sends before
    # resolving .fight/.catch/.flee re-enters this loop and re-rolls,
    # silently burning pending ticks and re-printing the encounter.
    # ticks_processed is deliberately left where it was — the ticks
    # that would've rolled during the pause are just caught up for
    # real once handle_journey_resume() runs.
    import sys as _sys
    print(f"[EXPLORE TICK DEBUG] sender={sender} paused_for_battle={session.paused_for_battle} "
          f"ticks_processed={session.ticks_processed} elapsed={session.elapsed():.2f} "
          f"total_time_s={session.total_time_s} force_arrival={force_arrival}",
          file=_sys.stderr, flush=True)
    if session.paused_for_battle:
        return None

    pending = session.pending_ticks(TICK_SECONDS)
    for _ in range(pending):
        session.ticks_processed += 1
        event = _roll_tick_event(session.current_zone)
        if event and event["type"] == "encounter":
            session.paused_for_battle = True
            session.save(db)

            # Actually spawn the encounter into a real battle, same
            # mechanism router/movement.py's legacy grass-tile
            # encounters use — roll_wild_pokemon() for species/level,
            # get_full() for PokéAPI data, build_wild_monster() for
            # the dict shape battle.py expects, then set_encounter()
            # on the player's CombatSession to actually transition
            # into STATE_ENCOUNTER so .fight/.catch/.flee do something.
            if router is not None:
                try:
                    from encounters import roll_wild_pokemon, build_wild_monster
                    from pokeapi import get_full
                    result = roll_wild_pokemon(session.current_zone, "grass", player.level)
                    if result:
                        species, level = result
                        api_data = get_full(db, species)
                        if api_data:
                            monster = build_wild_monster(api_data, level, db=db)
                            player.see_pokemon(species)
                            combat_session = router._session(sender)
                            combat_session.set_encounter(monster, session.direction)
                            return (
                                f"A wild {event['name'].title()} appeared!\n"
                                f"Lv. {event['level']}\n\n"
                                f"Your journey is paused. What will you do?\n"
                                f".fight — engage\n"
                                f".catch — throw a ball\n"
                                f".flee — run and continue traveling"
                            )
                except Exception as e:
                    import sys
                    print(f"[EXPLORE ENCOUNTER] spawn failed for {sender}: {e}", file=sys.stderr, flush=True)
                    # Falls through to the flavor-text-only message
                    # below rather than losing the encounter silently —
                    # paused_for_battle is already True, so the player
                    # at least sees something happened even if the
                    # real battle failed to spawn.

            # No router (e.g. a caller that predates this wiring) or
            # the spawn attempt above failed — same message as before,
            # journey still pauses, but .fight/.catch won't have a
            # real battle to act on until the player is back on a
            # synchronous path that does pass router.
            return (
                f"A wild {event['name'].title()} appeared!\n"
                f"Lv. {event['level']}\n\n"
                f"Your journey is paused. What will you do?\n"
                f".fight — engage\n"
                f".catch — throw a ball\n"
                f".flee — run and continue traveling"
            )
        if event and event["type"] == "item":
            item_name = event["name"]
            qty = event.get("qty", 1)
            player.inventory[item_name] = player.inventory.get(item_name, 0) + qty
            session.save(db)
            save_fn()
            return (
                "While traveling, you spot something glinting "
                "in the grass...\n\n"
                f"You found a {item_name}! (.inv to check)"
            )

    if not (force_arrival or session.has_arrived()):
        session.save(db)
        return None

    destination = session.destination_zone
    origin_name = ZONE_INFO.get(session.origin_zone, {}).get("name", session.origin_zone)
    dest_info   = ZONE_INFO.get(destination, {})
    dest_name   = dest_info.get("name", destination)
    flavor      = dest_info.get("description", "")

    player.zone = destination
    _mark_discovered(player, session.origin_zone, session.direction, destination)
    db.mark_zone_discovered(destination)  # Phase 7 — global tier 1→2 flip
    session.end()
    session.save(db)
    save_fn()

    msg = (
        f"You have left {origin_name}...\n\n"
        f"...you are now in {dest_name}.\n\n"
    )
    if flavor:
        msg += f"{flavor}\n\n"
    msg += "Use .zone to see more info"
    return msg


def handle_journey_resume(sender, player, db):
    """
    Called once a mid-journey encounter resolves (win/catch/flee) to
    put the player back into transit. Remaining time keeps counting
    from where it left off — the journey is not auto-completed.
    """
    session = ExploreSession.load(db, sender)
    if not session.is_active():
        return None
    session.paused_for_battle = False
    session.save(db)
    # Re-arm the proactive push timer now that the journey isn't
    # waiting on a battle reply anymore — it stopped re-arming itself
    # while paused_for_battle was True.
    remaining = session.remaining()
    if remaining > 0:
        _arm_arrival_timer(sender, db, min(CHECK_INTERVAL_SECONDS, remaining))
    return "You resume your journey forward"


def resume_journey_if_paused(sender, player, db):
    """
    Safe hook for any wild/trainer battle-resolution path (win, catch,
    faint, flee — arena/gym/PvP/dungeon are NOT included) to call right
    after saving the player. No-ops instantly for every battle type
    that isn't an explore-tick encounter, since it only acts when
    ExploreSession.paused_for_battle is actually True — so it's safe to
    sprinkle into every resolution point without needing to first
    figure out whether that particular battle came from .explore.

    Returns a string to append to the battle result (e.g. "\\n\\nYou
    resume your journey forward"), or "" if there's nothing to resume.
    """
    session = ExploreSession.load(db, sender)
    if not (session.is_active() and session.paused_for_battle):
        return ""
    resume_msg = handle_journey_resume(sender, player, db)
    return f"\n\n{resume_msg}" if resume_msg else ""


def handle_zone(sender, player, db, router=None):
    """Standard zone info card — current zone, whether traveling or not."""
    session = ExploreSession.load(db, sender)

    # .zone was excluded from the passive tick-catchup dispatch in
    # handle.py (it's meant to handle its own tick logic explicitly,
    # like .explore/.end do) but never actually got that logic — a
    # finished journey's arrival was never resolved here, leaving
    # session.current_zone frozen at the origin zone forever. Resolve
    # a completed arrival here the same way handle_end does, before
    # reading current_zone.
    if session.is_active() and session.has_arrived():
        from .explore import handle_journey_tick
        handle_journey_tick(sender, player, db, lambda: db.save(sender, player), force_arrival=True, router=router)
        session = ExploreSession.load(db, sender)

    zone_id = session.current_zone if session.is_active() else player.zone
    info    = ZONE_INFO.get(zone_id, {})

    lines = [f"Name: {info.get('name', zone_id)}", f"Status: {info.get('status', 'Unknown')}"]

    if info.get("description"):
        lines += ["", "Description:", info["description"]]

    if info.get("status") in ("Town", "City"):
        lines += [
            "",
            f"Poke Center: {'Yes' if info.get('poke_center') else 'No'}",
            f"Gyms: {info.get('gyms', 'None')}",
            f"Arenas: {info.get('arenas', 'None')}",
            f"Dungeons: {info.get('dungeons', 'None')}",
        ]
        if info.get("specialty"):
            lines.append(f"Specialty: {info['specialty']}")

    connections = _connections_line(player, zone_id)
    if connections:
        lines += ["", f"Connections: {connections}"]

    actions = info.get("actions")
    if actions:
        lines += ["", "Available actions:"] + actions

    return "\n".join(lines)


def _connections_line(player, zone_id):
    """
    Per-player discovery-aware connections: known destinations by name,
    undiscovered-but-defined directions as '???', nothing defined omitted.

    One entry per DIRECTION, not per branch option. A direction can have
    multiple weighted destinations behind it (e.g. oak_town's north
    splits 50/50 between ashfall_village and elmwood_trail) — those are
    collapsed into a single line for that direction rather than one
    line per possible destination, so the connections list shows
    "??? (north)" once, not twice.
    """
    table = EXPLORE_DESTINATIONS.get(zone_id, {})
    if not table:
        return None

    parts = []
    for direction, options in table.items():
        discovered = _discovered_for(player, zone_id, direction)
        undiscovered = [o for o in options if o["to"] not in discovered]
        if not undiscovered:
            # every branch behind this direction has been found —
            # list them all by name
            names = [ZONE_INFO.get(o["to"], {}).get("name", o["to"]) for o in options]
            label = " / ".join(names)
        else:
            # at least one branch behind this direction is still a
            # mystery — the whole direction reads as unexplored
            label = "???"
        parts.append(f"{label} ({direction})")
    return ", ".join(parts) if parts else None
