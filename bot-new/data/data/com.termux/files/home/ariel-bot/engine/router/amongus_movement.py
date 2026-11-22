"""Continuous, per-game movement for the Niflheim Among Us engine.

Room-edge weights are gameplay seconds. A player remains in the room for one
world-clock tick after issuing a move, then enters the corridor. Once in a
corridor, position is stored as elapsed travel seconds from one endpoint.
"""

from . import amongus_config as C
from . import amongus_map as M


def _display(room):
    return str(room).replace("_", " ").title()


class MovementEngine:
    """Owns movement transitions and location-based awareness for one game."""

    def __init__(self, game):
        self.game = game
        self._last_now = None
        self._paired_room_events = set()
        self._active_corridor_pairs = set()

    def advance_all(self, now):
        """Advance every active player through exact transition timestamps."""
        now = float(now)
        if self._last_now is not None and now < self._last_now:
            now = self._last_now

        for player in self.game.players.values():
            self._adopt_legacy_path(player)

        if getattr(self, "_paused_at", None) is not None:
            return now

        last_sample = self._last_now
        while True:
            deadlines = []
            for player in self.game.players.values():
                if getattr(player, "departed", False):
                    continue
                if player.in_vent_until is not None:
                    deadlines.append((player.in_vent_until, "vent_arrival", player))
                if player.path and player.pending_departure_at is not None:
                    deadlines.append((player.pending_departure_at, "departure", player))
                if (
                    player.path
                    and player.corridor_started_at is not None
                    and player.corridor_from is not None
                ):
                    remaining = max(
                        0.0,
                        player.corridor_length - player.corridor_progress_at_start,
                    )
                    deadlines.append(
                        (
                            player.corridor_started_at
                            + remaining / self._travel_rate(player),
                            "arrival",
                            player,
                        )
                    )

            due = [item for item in deadlines if item[0] <= now + 1e-9]
            next_sample = (
                last_sample + C.WORLD_TICK_SECONDS
                if last_sample is not None
                else None
            )
            if next_sample is not None and next_sample <= now + 1e-9:
                due.append((next_sample, "sample", None))
            if not due:
                break

            transition_at = min(item[0] for item in due)
            same_time = [
                item for item in due if abs(item[0] - transition_at) <= 1e-9
            ]
            departures = [item[2] for item in same_time if item[1] == "departure"]
            arrivals = [item[2] for item in same_time if item[1] == "arrival"]
            vent_arrivals = [
                item[2] for item in same_time if item[1] == "vent_arrival"
            ]
            is_sample = any(item[1] == "sample" for item in same_time)

            # At a boundary, people leaving are already out before simultaneous
            # arrivals are evaluated. The event-pair window below makes the
            # actors aware of one another independent of processing order.
            for player in departures:
                self._depart(player, transition_at)
            for player in vent_arrivals:
                self._finish_vent(player, transition_at)
            if arrivals:
                self._arrive_batch(arrivals, transition_at)
            self._detect_corridor_encounters(transition_at)
            self.game._advance_awareness(transition_at)
            if is_sample:
                last_sample = transition_at

        self._detect_corridor_encounters(now)
        self.game._advance_awareness(now)
        self._last_now = now
        return now

    def _finish_vent(self, player, at):
        if player.in_vent_until is None or player.in_vent_until > at:
            return
        self.game._exit_vent(player, at, automatic=True)

    def _adopt_legacy_path(self, player):
        """Keep the pre-Session-2 follow prototype from becoming a dead path."""
        if (
            not player.path
            or player.pending_departure_at is not None
            or player.corridor_from is not None
            or player.hop_started_at is None
            or not player.hop_duration
        ):
            return
        destination = player.path[0]
        duration = self.game.map.edges.get(player.room, {}).get(destination)
        if duration is None:
            return
        player.settled = False
        player.corridor_from = player.room
        player.corridor_to = destination
        player.corridor_length = float(duration)
        player.corridor_progress_at_start = 0.0
        player.corridor_started_at = float(player.hop_started_at)
        player.pending_departure_at = None

    def _depart(self, player, at):
        if not player.path or player.pending_departure_at is None:
            return
        room = player.room
        destination = player.path[0]
        length = self.game.map.edges.get(room, {}).get(destination)
        if length is None:
            self._clear_route(player, keep_corridor=False)
            return

        player.pending_departure_at = None
        player.settled = False
        player.corridor_from = room
        player.corridor_to = destination
        player.corridor_length = float(length)
        player.corridor_progress_at_start = 0.0
        player.corridor_started_at = float(at)
        player.hop_started_at = float(at)
        player.hop_duration = float(length)
        player.stopped_since = None
        player.camping_notified = False

        self._room_event("room_departure", player, room, at)
        self.game._on_player_departure(player, room, at)

    def _arrive_batch(self, players, at):
        arrivals = []
        room_observers = {}
        for player in players:
            if not player.path or player.corridor_to is None:
                continue
            destination = player.corridor_to
            room_observers[player.jid] = [
                observer.jid
                for observer in self.game.players.values()
                if observer.jid != player.jid
                and observer.alive == player.alive
                and not getattr(observer, "departed", False)
                and observer.settled
                and observer.room == destination
                # Someone who got here within the simultaneous-arrival window
                # arrived WITH this player, not before them.
                and (
                    observer.room_entered_at is None
                    or float(at) - float(observer.room_entered_at)
                    > C.SIMULTANEOUS_ARRIVAL_SECONDS + 1e-9
                )
            ]
            arrivals.append((player, destination, room_observers[player.jid]))

        room_events = []
        for player, destination, observers in arrivals:
            if player.path and player.path[0] == destination:
                player.path.pop(0)
            player.room = destination
            player.room_entered_at = float(at)
            player.pending_departure_at = None
            player.hop_started_at = None
            player.hop_duration = None

            is_final = not player.path
            if is_final:
                player.path = None
                player.settled = True
                player.reference_room = destination
                player.returning = False
                player.corridor_from = None
                player.corridor_to = None
                player.corridor_length = None
                player.corridor_progress_at_start = 0.0
                player.corridor_started_at = None
                player.stopped_since = float(at)
            else:
                next_room = player.path[0]
                length = self.game.map.edges[destination][next_room]
                player.settled = False
                player.corridor_from = destination
                player.corridor_to = next_room
                player.corridor_length = float(length)
                player.corridor_progress_at_start = 0.0
                player.corridor_started_at = float(at)
                player.hop_started_at = float(at)
                player.hop_duration = float(length)

            event = self._record_room_event(
                "room_arrival",
                player,
                destination,
                at,
                known_by=[player.jid, *observers],
            )
            room_events.append((event, observers, is_final))

        # Every arrival at this timestamp observes the same pre-arrival room
        # snapshot, so simultaneous entrants cannot see different worlds due
        # solely to iteration order.
        # Players who arrived in the same room within the simultaneous-arrival
        # window are named inside the arriving player's own message
        # ("X arrived beside you"). Whoever is named this way is recorded as
        # having been told, so the separate "Nearby room update" is not sent
        # for that direction; an earlier arrival who was not told by a message
        # of their own still gets the paired update.
        beside = {}
        for event, _observers, is_final in room_events:
            if not is_final or event.get("suppressed"):
                continue
            jid = event["actor_jid"]
            mover = self.game.players.get(jid)
            beside[jid] = []
            for other in self.game.players.values():
                if (
                    other.jid == jid
                    or mover is None
                    or other.alive != mover.alive
                    or getattr(other, "departed", False)
                    or not other.settled
                    or other.in_vent_until is not None
                    or other.room != event["room"]
                    or other.room_entered_at is None
                    or abs(float(at) - float(other.room_entered_at))
                    > C.SIMULTANEOUS_ARRIVAL_SECONDS + 1e-9
                ):
                    continue
                beside[jid].append(other.jid)
                for earlier in reversed(self.game.events):
                    if (
                        earlier.get("type") == "room_arrival"
                        and earlier.get("actor_jid") == other.jid
                        and earlier.get("room") == event["room"]
                    ):
                        known = earlier.setdefault("known_by", [])
                        if jid not in known:
                            known.append(jid)
                        break

        for event, observers, is_final in room_events:
            room = event["room"]
            actor_color = event["actor"]
            for observer_jid in ([] if event.get("suppressed") else observers):
                who = self.game._observed_name(observer_jid, actor_color)
                self.game.manager._push_dm(
                    observer_jid,
                    f"🚶 {who} arrived beside you.",
                )
            if is_final:
                mover_text = self._arrival_text(event, beside.get(event["actor_jid"], []))
            else:
                mover_text = f"🚶 You passed through {_display(room)}."
            self.game.manager._push_dm(event["actor_jid"], mover_text)
            self._pair_room_event(event)
            player = self.game.players.get(event["actor_jid"])
            if player:
                self.game._on_player_arrival(player, room, at)
                if is_final:
                    self.game._check_body_here(player, room)

    def _arrival_text(self, event, beside_jids):
        """The final-arrival message (design note v5.3, section 22.2)."""
        game = self.game
        jid = event["actor_jid"]
        room = event["room"]
        mover = game.players.get(jid)
        lines = [f"You have arrived at {_display(room)}."]
        if not event.get("suppressed"):
            for other_jid in beside_jids:
                other = game.players.get(other_jid)
                if other is not None:
                    lines.append(
                        f"{game._observed_name(jid, other.color)} arrived beside you."
                    )
        names = []
        for other in game.players.values():
            if (
                other.jid != jid
                and mover is not None
                and other.alive == mover.alive
                and not getattr(other, "departed", False)
                and other.settled
                and other.in_vent_until is None
                and other.room == room
            ):
                names.append(game._observed_name(jid, other.color))
        names.append("you")
        lines.append("Players: " + ", ".join(names))
        lines.append("Use .tasks to see available tasks.")
        lines.append("Use .status to observe the room.")
        return "\n".join(lines)

    def _record_room_event(self, event_type, player, room, at, known_by):
        event = self.game._record_event(
            event_type,
            at=float(at),
            actor=player.color,
            actor_jid=player.jid,
            room=room,
            known_by=list(dict.fromkeys(known_by)),
        )
        event["alive"] = bool(player.alive)
        # Remember that this observation was made under Lights, so it stays
        # masked in later reports even after repair.
        event["masked"] = self.game._lights_masking()
        # Likewise, mark observations whose passive notices were suppressed by
        # a Communications outage (used by the post-repair inactivity report).
        event["suppressed"] = self.game._comms_suppressing()
        return event

    def _room_event(self, event_type, player, room, at):
        observers = [
            other
            for other in self.game.players.values()
            if other.jid != player.jid
            and other.alive == player.alive
            and not getattr(other, "departed", False)
            and other.settled
            and other.room == room
        ]
        event = self._record_room_event(
            event_type,
            player,
            room,
            at,
            known_by=[player.jid, *(other.jid for other in observers)],
        )
        for observer in ([] if event.get("suppressed") else observers):
            who = self.game._observed_name(observer.jid, player.color)
            self.game.manager._push_dm(
                observer.jid, f"🚪 *{who}* left *{_display(room)}*."
            )
        self._pair_room_event(event)

    def _pair_room_event(self, event):
        if event is None or event.get("suppressed"):
            return
        for earlier in tuple(self.game.events):
            if (
                earlier is event
                or earlier.get("suppressed")
                or earlier.get("type") not in {"room_departure", "room_arrival"}
                or earlier.get("room") != event.get("room")
                or earlier.get("actor_jid") == event.get("actor_jid")
                or earlier.get("alive", True) != event.get("alive", True)
                or abs(float(earlier.get("at", 0)) - float(event.get("at", 0)))
                > C.ROOM_EVENT_AWARENESS_SECONDS
            ):
                continue
            key = tuple(sorted((id(earlier), id(event))))
            if key in self._paired_room_events:
                continue
            self._paired_room_events.add(key)

            earlier_actor = earlier.get("actor_jid")
            current_actor = event.get("actor_jid")
            if earlier_actor not in event.get("known_by", []):
                self.game.manager._push_dm(
                    earlier_actor,
                    "👀 Nearby room update: "
                    + self._describe_room_event(
                        event, self.game._observed_name(
                            earlier_actor, event.get("actor", "A player")
                        )
                    ),
                )
                event.setdefault("known_by", []).append(earlier_actor)
            if current_actor not in earlier.get("known_by", []):
                self.game.manager._push_dm(
                    current_actor,
                    "👀 Nearby room update: "
                    + self._describe_room_event(
                        earlier, self.game._observed_name(
                            current_actor, earlier.get("actor", "A player")
                        )
                    ),
                )
                earlier.setdefault("known_by", []).append(current_actor)

    @staticmethod
    def _describe_room_event(event, actor=None):
        actor = actor or event.get("actor", "A player")
        room = _display(event.get("room", ""))
        if event.get("type") == "room_departure":
            return f"{actor} left {room}."
        return f"{actor} arrived in {room}."

    def _corridor_position(self, player, now):
        if player.corridor_from is None or player.corridor_to is None:
            return None
        paused_at = getattr(self, "_paused_at", None)
        if paused_at is not None:
            now = min(float(now), float(paused_at))
        progress = float(player.corridor_progress_at_start or 0.0)
        if player.corridor_started_at is not None and player.path:
            progress += (
                max(0.0, float(now) - float(player.corridor_started_at))
                * self._travel_rate(player)
            )
        progress = min(float(player.corridor_length), progress)
        if player.corridor_from <= player.corridor_to:
            canonical = progress
        else:
            canonical = float(player.corridor_length) - progress
        return {
            "edge": tuple(sorted((player.corridor_from, player.corridor_to))),
            "progress": progress,
            "canonical": canonical,
            "length": float(player.corridor_length),
        }

    @staticmethod
    def _travel_rate(player):
        multiplier = (
            C.GHOST_TRAVEL_TIME_MULTIPLIER
            if not player.alive
            else 1.0
        )
        return 1.0 / max(float(multiplier), 1e-9)

    @staticmethod
    def _departure_delay(player):
        return (
            C.MOVEMENT_EXIT_DELAY_SECONDS
            * C.GHOST_TRAVEL_TIME_MULTIPLIER
            if not player.alive
            else C.MOVEMENT_EXIT_DELAY_SECONDS
        )

    @staticmethod
    def _travel_time(player, normal_seconds):
        return (
            float(normal_seconds) * C.GHOST_TRAVEL_TIME_MULTIPLIER
            if not player.alive
            else float(normal_seconds)
        )

    def _detect_corridor_encounters(self, now):
        occupants = []
        for player in self.game.players.values():
            if getattr(player, "departed", False) or player.in_vent_until is not None:
                continue
            position = self._corridor_position(player, now)
            if position is not None and not player.settled:
                occupants.append((player, position))

        current_pairs = set()
        radius = C.CORRIDOR_ENCOUNTER_RADIUS_SECONDS
        for index, (first, first_position) in enumerate(occupants):
            for second, second_position in occupants[index + 1:]:
                if first.alive != second.alive:
                    continue
                if first_position["edge"] != second_position["edge"]:
                    continue
                if abs(first_position["canonical"] - second_position["canonical"]) > radius:
                    continue
                pair = tuple(sorted((first.jid, second.jid)))
                current_pairs.add(pair)
                if pair in self._active_corridor_pairs:
                    continue
                self.game._record_event(
                    "corridor_encounter",
                    at=float(now),
                    players=sorted((first.color, second.color)),
                    corridor=list(first_position["edge"]),
                    masked=self.game._lights_masking(),
                    suppressed=self.game._comms_suppressing(),
                )
                if self.game._comms_suppressing():
                    continue  # recorded, not announced; no replay after repair
                corridor = " and ".join(_display(room) for room in first_position["edge"])
                self.game.manager._push_dm(
                    first.jid,
                    f"🚶 You encountered *{self.game._observed_name(first.jid, second.color)}* "
                    f"in the *{corridor}* corridor.",
                )
                self.game.manager._push_dm(
                    second.jid,
                    f"🚶 You encountered *{self.game._observed_name(second.jid, first.color)}* "
                    f"in the *{corridor}* corridor.",
                )
        self._active_corridor_pairs = current_pairs

    def _clear_route(self, player, keep_corridor):
        player.path = None
        player.pending_departure_at = None
        player.hop_started_at = None
        player.hop_duration = None
        player.returning = False
        if not keep_corridor:
            player.corridor_from = None
            player.corridor_to = None
            player.corridor_length = None
            player.corridor_progress_at_start = 0.0
            player.corridor_started_at = None
            player.settled = True

    @staticmethod
    def _path_cost(path, edges):
        if not path:
            return float("inf")
        return sum(edges[path[index]][path[index + 1]] for index in range(len(path) - 1))

    def _route_from_corridor(self, player, destination, now):
        position = self._corridor_position(player, now)
        if position is None:
            return None
        old_from = player.corridor_from
        old_to = player.corridor_to
        length = float(player.corridor_length)
        progress = position["progress"]

        via_from = M.shortest_path(old_from, destination, self.game.map_id)
        via_to = M.shortest_path(old_to, destination, self.game.map_id)
        options = [
            (
                progress + self._path_cost(via_from, self.game.map.edges),
                old_from,
                via_from,
            ),
            (
                (length - progress) + self._path_cost(via_to, self.game.map.edges),
                old_to,
                via_to,
            ),
        ]
        cost, endpoint, path = min(options, key=lambda item: (item[0], item[1]))
        if endpoint == old_from:
            player.corridor_from, player.corridor_to = old_to, old_from
            player.corridor_progress_at_start = length - progress
        else:
            player.corridor_from, player.corridor_to = old_from, old_to
            player.corridor_progress_at_start = progress

        player.corridor_length = length
        player.corridor_started_at = float(now)
        player.path = list(path)
        player.pending_departure_at = None
        player.settled = False
        player.returning = False
        player.stopped_since = None
        player.camping_notified = False
        self.game._cancel_pending_kills_for(player, "movement", now)
        self.game._cancel_task_interaction(player, "movement", now)
        player.hop_started_at = float(now)
        player.hop_duration = (
            length - player.corridor_progress_at_start
        ) / self._travel_rate(player)
        return self._travel_time(player, cost)

    def move(self, player, destination, now):
        if destination not in self.game.map.edges:
            return None, f"⚠️ _Unknown room: {_display(destination)}._"
        if player.in_vent_until is not None:
            return None, "⚠️ _You can't move while in a vent._"
        if player.path and not player.returning:
            return None, "⚠️ _You're already moving._"

        was_returning = bool(player.returning)
        if player.settled:
            if destination == player.room:
                if player.path:
                    self._clear_route(player, keep_corridor=False)
                    player.stopped_since = float(now)
                    player.camping_notified = False
                    return 0.0, f"_You're already in {_display(player.room)}._"
                return 0.0, f"_You're already in {_display(player.room)}._"

            route = M.shortest_path(player.room, destination, self.game.map_id)
            if not route or len(route) < 2:
                return None, "⚠️ _No route found._"
            if not was_returning:
                player.reference_room = player.room
            player.path = list(route[1:])
            departure_delay = self._departure_delay(player)
            player.pending_departure_at = float(now) + departure_delay
            player.stopped_since = None
            player.camping_notified = False
            player.corridor_from = None
            player.corridor_to = None
            player.corridor_length = None
            player.corridor_progress_at_start = 0.0
            player.corridor_started_at = None
            player.hop_started_at = None
            player.hop_duration = None
            player.settled = True
            player.returning = False
            total = self._travel_time(
                player, self._path_cost(route, self.game.map.edges)
            )
            self.game._cancel_pending_kills_for(player, "movement", now)
            self.game._cancel_task_interaction(player, "movement", now)
            return total + departure_delay, None

        # A new .m during .goback redirects from the exact current corridor
        # position; it must not rewrite the reference room mid-journey.
        total = self._route_from_corridor(player, destination, now)
        if total is None:
            return None, "⚠️ _No route found from your current position._"
        player.returning = False
        return total, None

    def stop(self, player, now):
        if player.in_vent_until is not None:
            return "⚠️ _You can't stop while in a vent._"
        if not player.path:
            return "_You're not moving._"

        if player.settled:
            # The player has not crossed the room boundary yet.
            self._clear_route(player, keep_corridor=False)
            player.stopped_since = float(now)
            player.camping_notified = False
            return (
                f"🛑 You stopped in *{_display(player.room)}*.\n"
                "Use *.where* to check your position."
            )

        position = self._corridor_position(player, now)
        if position is None:
            self._clear_route(player, keep_corridor=False)
            return "_You're not moving._"
        player.corridor_progress_at_start = position["progress"]
        player.corridor_started_at = None
        player.path = None
        player.pending_departure_at = None
        player.hop_started_at = None
        player.hop_duration = None
        player.settled = False
        player.returning = False
        player.stopped_since = float(now)
        player.camping_notified = False
        return (
            f"🛑 You stopped between *{_display(player.corridor_from)}* and "
            f"*{_display(player.corridor_to)}*.\n"
            "Use *.where* to check your position."
        )

    def go_back(self, player, now):
        target = player.reference_room or player.room
        if player.path and player.returning:
            return f"_You're already going back to {_display(target)}._"
        if player.settled and target == player.room:
            if player.path:
                self._clear_route(player, keep_corridor=False)
                player.stopped_since = float(now)
                player.camping_notified = False
            return f"_You're already in {_display(player.room)}._"
        if player.in_vent_until is not None:
            return "⚠️ _You can't go back while in a vent._"

        if player.settled:
            route = M.shortest_path(player.room, target, self.game.map_id)
            if not route or len(route) < 2:
                return f"_You're already in {_display(player.room)}._"
            player.path = list(route[1:])
            departure_delay = self._departure_delay(player)
            player.pending_departure_at = float(now) + departure_delay
            player.stopped_since = None
            player.camping_notified = False
            player.corridor_from = None
            player.corridor_to = None
            player.corridor_length = None
            player.corridor_progress_at_start = 0.0
            player.corridor_started_at = None
            player.hop_started_at = None
            player.hop_duration = None
            player.settled = True
            player.returning = True
            total = self._travel_time(
                player, self._path_cost(route, self.game.map.edges)
            )
            self.game._cancel_pending_kills_for(player, "movement", now)
            self.game._cancel_task_interaction(player, "movement", now)
            return f"↩️ Returning to *{_display(target)}* (about {total + departure_delay:g}s)."

        total = self._route_from_corridor(player, target, now)
        if total is None:
            return "⚠️ _No route back from your current position._"
        player.returning = True
        return f"↩️ Returning to *{_display(target)}* (about {total:g}s)."

    def where(self, player, now):
        head = "📍 *Your location*\n"
        if player.in_vent_until is not None:
            remaining = max(0, int(player.in_vent_until - now))
            return head + f"🌀 In a vent (~{remaining}s)."
        if player.settled:
            if player.path and player.pending_departure_at is not None:
                wait = max(0, int(player.pending_departure_at - now + 0.999))
                return (
                    head + f"*{_display(player.room)}*\n"
                    f"Leaving in about {wait}s."
                )
            return head + f"*{_display(player.room)}*"

        position = self._corridor_position(player, now)
        if position is None:
            return head + f"*{_display(player.room)}*"
        progress = position["progress"]
        state = "Stopped" if not player.path else "Travelling"
        return (
            head
            + f"Between *{_display(player.corridor_from)}* and *{_display(player.corridor_to)}*\n"
            f"{state} ({progress:g}s along the corridor)."
        )

    def pause(self, now):
        if getattr(self, "_paused_at", None) is None:
            self._paused_at = float(now)

    def resume(self, now):
        paused_at = getattr(self, "_paused_at", None)
        if paused_at is None:
            return 0.0
        elapsed = max(0.0, float(now) - float(paused_at))
        if elapsed:
            for player in self.game.players.values():
                for field in (
                    "pending_departure_at",
                    "corridor_started_at",
                    "in_vent_until",
                ):
                    value = getattr(player, field, None)
                    if value is not None:
                        setattr(player, field, float(value) + elapsed)
                for field in ("stopped_since", "follow_started_at"):
                    value = getattr(player, field, None)
                    if value is not None:
                        setattr(player, field, float(value) + elapsed)
        self._paused_at = None
        self._last_now = float(now)
        return elapsed
