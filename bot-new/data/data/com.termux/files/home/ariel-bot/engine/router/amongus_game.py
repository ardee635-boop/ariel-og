# ============================================================
# NIFLHEIM — router/amongus_game.py
# Core game engine for an in-progress Among Us match.
# ============================================================

import logging
import math
import random
import re
import threading
import time

from . import amongus_comms as comms_display
from . import amongus_config as C
from .amongus_images import image_kwargs, map_link, tasks_list_link
from . import amongus_stage as STAGE
from . import amongus_map as M
from . import amongus_paired as PAIRED
from . import amongus_puzzles as puzzles
from .amongus_sabotage import SABOTAGE_NAMES, Sabotage, make_sabotage

KILL_DELAY_SECONDS       = C.KILL_RESOLUTION_SECONDS
KILL_COOLDOWN_SECONDS    = C.KILL_COOLDOWN_SECONDS
LINGER_THRESHOLD_SECONDS = C.LEGACY_LINGER_THRESHOLD_SECONDS
FOLLOW_REVEAL_SECONDS    = C.FOLLOW_REVEAL_SECONDS
MEETING_VOTE_SECONDS     = C.MEETING_VOTE_SECONDS


# Match-over headlines for timed sabotages (reply design F/G, note session N7).
SABOTAGE_FAILURE_TEXT = {
    "reactor": "☢️ *Reactor meltdown — Impostors win.*",
    "oxygen": (
        "🚨 *OXYGEN FAILURE!*\n"
        "The oxygen supply has run out.\n"
        "*O₂ depleted — Impostors win.*"
    ),
}


class PlayerState:
    def __init__(self, jid, role, color=None, map_data=None):
        map_data = map_data or M.get_map()
        self.jid              = jid
        self.color            = color
        self.role             = role          # "crewmate" | "scientist" | "impostor"
        self.alive            = True
        self.departed         = False
        self.room             = map_data.start_room
        self.path             = None          # remaining rooms to visit
        self.hop_started_at   = None
        self.hop_duration     = None
        self.settled          = True
        self.room_entered_at  = time.time()
        self.reference_room   = map_data.start_room
        self.pending_departure_at = None
        self.corridor_from    = None
        self.corridor_to      = None
        self.corridor_length  = None
        self.corridor_progress_at_start = 0.0
        self.corridor_started_at = None
        self.returning        = False
        self.stopped_since    = self.room_entered_at
        self.camping_notified = False
        self.tasks            = [
            {
                "id": f"LEGACY-{jid}-{index + 1}",
                "room": room,
                "name": name,
                "duration": dur,
                "done": False,
                "owner_jid": jid,
                "fake": role == "impostor",
                "claimed_by": None,
            }
            for index, (room, (name, dur)) in enumerate(map_data.tasks.items())
        ]
        self.task_in_progress = None
        self.task_cooldown_until = 0.0
        self.ghost_task_cooldown_until = 0.0
        self.kill_cooldown_until = 0.0
        self.pending_kill     = None
        self.in_vent_until    = None
        self.vent_dest        = None
        self.vent_room        = None
        self.vent_entered_at  = None
        self.vent_cooldown_until = 0.0
        self.vitals_cooldown_until = 0.0
        self.witness_cooldown_until = 0.0
        self.following        = None
        self.follow_started_at = None
        self.follow_discovered = False
        self.follow_move_active = False
        self.death_room = None
        self.death_reason = None

    def real_progress_pct(self):
        done = sum(1 for t in self.tasks if t["done"] and self.role != "impostor")
        return int(100 * done / len(self.tasks)) if self.tasks else 100


class Game:
    def __init__(self, manager, lobby, started_at_ms=None, start_clock=True):
        self.manager   = manager
        self.lobby     = lobby
        self.group_jid = lobby.group_jid
        self.over      = False
        self.lock      = threading.RLock()
        self._stop_event = threading.Event()
        self._timers   = set()
        self.tick_count = 0
        self.started_at = self._timestamp_seconds(started_at_ms)
        self.events    = []
        self.map = M.get_map(lobby.map_id)
        self.map_id = self.map.id
        self._meeting  = None
        self._sabotages = {
            name: make_sabotage(name, C.SABOTAGE_COOLDOWNS_SECONDS[name], game=self)
            for name in SABOTAGE_NAMES
        }
        self._bodies   = {}   # room -> [jid, ...]  (fixed: init here, not lazily)
        self._corpses = {}    # victim jid -> persistent corpse/witness record
        self._reported_crime_scenes = []
        self._team_tasks = []
        self._task_sequence = 0
        self._interaction_sequence = 0
        self._closed_task_prompts = {}

        members = list(lobby.players)
        from .amongus import _impostor_count
        test_role = getattr(lobby, "test_role", None)
        if test_role == "impostor":
            impostor_jids = {lobby.host}
        elif test_role:
            # Solo test as crew/scientist: the impostor is a passive dummy.
            others = [j for j in members if C.is_dummy(j)] or [j for j in members if j != lobby.host]
            impostor_jids = {others[0]}
        else:
            impostor_jids = set(random.sample(members, _impostor_count(len(members))))

        self.players = {
            jid: PlayerState(
                jid,
                "impostor" if jid in impostor_jids else "crewmate",
                C.PLAYER_COLORS[index],
                self.map,
            )
            for index, jid in enumerate(members)
        }
        if len(members) >= C.SCIENTIST_MIN_PLAYERS:
            crew = [player for player in self.players.values() if player.role == "crewmate"]
            if crew:
                random.choice(crew).role = "scientist"
        if test_role == "scientist" and lobby.host not in impostor_jids:
            self.players[lobby.host].role = "scientist"
        self._assign_tasks(len(members))
        if test_role and test_role != "impostor":
            # Dummies never task, so pre-finish theirs or a task win is impossible.
            for player in self.players.values():
                if C.is_dummy(player.jid) and player.role != "impostor":
                    for task in player.tasks:
                        task["done"] = True
        for player in self.players.values():
            player.room_entered_at = self.started_at
            player.stopped_since = self.started_at
        self.color_to_jid = {player.color.lower(): player.jid for player in self.players.values()}
        self._record_event("game_started", at=self.started_at, map_id=self.map_id)
        self._announce_roles()
        from .amongus_movement import MovementEngine
        self.movement = MovementEngine(self)
        self._clock_thread = None
        if start_clock:
            self._clock_thread = threading.Thread(
                target=self._run_world_clock,
                name=f"amongus-world-{self.group_jid}",
                daemon=True,
            )
            self._clock_thread.start()

    def _assign_tasks(self, lobby_size):
        """Assign lobby-scaled Crewmate tasks and non-scoring Impostor fakes."""
        templates = tuple(self.map.tasks.items())
        task_count = int(lobby_size) + 1
        self._team_tasks = []

        for player in self.players.values():
            player.tasks = []
            for room, (name, duration) in random.choices(templates, k=task_count):
                self._task_sequence += 1
                task = {
                    "id": f"T{self._task_sequence:04d}",
                    "room": room,
                    "name": name,
                    "duration": duration,
                    "done": False,
                    "owner_jid": player.jid,
                    "fake": player.role == "impostor",
                    "claimed_by": None,
                }
                player.tasks.append(task)
                if player.role != "impostor":
                    self._team_tasks.append(task)

    @staticmethod
    def _timestamp_seconds(received_at_ms=None):
        if received_at_ms is None:
            return time.time()
        try:
            return float(received_at_ms) / 1000.0
        except (TypeError, ValueError):
            return time.time()

    def _record_event(self, event_type, at=None, **details):
        event = {"type": event_type, "at": time.time() if at is None else at}
        event.update(details)
        self.events.append(event)
        return event

    def _run_world_clock(self):
        while not self._stop_event.wait(C.WORLD_TICK_SECONDS):
            try:
                with self.lock:
                    if self.over:
                        return
                    self._tick(time.time())
            except Exception:
                logging.getLogger(__name__).exception(
                    "Niflheim world clock failed for group %s", self.group_jid
                )
                with self.lock:
                    self._end_game(
                        "⚠️ _This match stopped because its world clock encountered an error._"
                    )
                return

    def _tick(self, now):
        """One world-clock step at world time ``now`` (caller holds the lock)."""
        if self.over:
            return
        self.tick_count += 1
        self.movement.advance_all(now)
        if not self.over:
            self._advance_sabotages(now)
        if not self.over:
            self._advance_meeting(now)
        self._resolve_win_check(now)

    def _schedule(self, delay_seconds, callback):
        timer_ref = {}

        def run():
            timer = timer_ref["timer"]
            with self.lock:
                self._timers.discard(timer)
                if not self.over:
                    callback()

        timer = threading.Timer(delay_seconds, run)
        timer.daemon = True
        timer_ref["timer"] = timer
        self._timers.add(timer)
        timer.start()
        return timer

    def _deliver(self, send, step=0.0):
        """Run ``send`` (a message send) after any earlier timed messages.

        Presentation only: it never touches game state, and its timers are
        deliberately NOT in ``self._timers`` so ending the match does not cancel
        a reveal that is still being delivered. ``step`` is the gap to leave
        before the next queued message (0 = none).
        """
        now = time.monotonic()
        start = max(getattr(self, "_delivery_ready_at", 0.0), now)
        self._delivery_ready_at = start + max(0.0, float(step))
        delay = start - now
        if delay <= 0.001:
            send()
            return
        timer = threading.Timer(delay, send)
        timer.daemon = True
        timer.start()

    def _end_game(self, announcement=None):
        if self.over:
            return
        self.over = True
        self._record_event("game_ended")
        self._stop_event.set()
        for timer in tuple(self._timers):
            timer.cancel()
        self._timers.clear()
        self._meeting = None
        reset_ghost_group = getattr(self.manager, "_reset_ghost_group", None)
        if callable(reset_ghost_group):
            reset_ghost_group(self)
        for player in getattr(self, "players", {}).values():
            for task in player.tasks:
                task["claimed_by"] = None
        for player in getattr(self, "players", {}).values():
            player.pending_kill = None
            if player.task_in_progress:
                self._cancel_task_interaction(
                    player, "game_ended", time.time(), notify=False
                )
        for state in getattr(self, "_sabotages", {}).values():
            if not isinstance(state, Sabotage):
                continue
            timer = state.get("timer")
            if timer is not None:
                timer.cancel()
                self._timers.discard(timer)
            if state.cancel():
                self._record_event(
                    "sabotage_cancelled",
                    actor=None,
                    sabotage=state["name"],
                )
        self._sync_comms_restriction()  # sabotages are cancelled, so the restriction ends
        if announcement:
            # Waits for a still-running ejection reveal, then goes out once.
            self._deliver(lambda: self.manager._broadcast(announcement))

    def close(self):
        """Stop the game's clock and pending callbacks without sending a message."""
        with self.lock:
            self._end_game()

    # ── Setup ──────────────────────────────────────────────
    def _announce_roles(self):
        impostors = [p for p in self.players.values() if p.role == "impostor"]
        room = self.map.start_room.replace("_", " ").title()
        for p in self.players.values():
            if p.role == "impostor":
                role = "IMPOSTOR"
                fellow = ", ".join(o.color for o in impostors if o.jid != p.jid) or "none"
                extra = f"Fellow impostor(s): {fellow}\n"
                goal = "Blend in, sabotage, eliminate."
            elif p.role == "scientist":
                role = "SCIENTIST (Crewmate)"
                extra = ""
                goal = "Complete tasks and use .vitals or .witness to investigate."
            else:
                role = "CREWMATE"
                extra = ""
                goal = "Finish your tasks or vote out the impostor(s)."
            msg = (
                f"🚀 *Your role: {role}*\n"
                f"Colour: *{p.color}*\n"
                f"Starting room: *{room}*\n"
                f"{extra}\n"
                f"{goal}\n\n"
                "Use *.amenu* to view commands."
            )
            self.manager._push_dm(
                p.jid, msg,
                image_card=True,
                **STAGE.preview_kwargs("landscape", p.color, self._role_category(p)),
            )
        n_imp = len(impostors)
        start_url = map_link(self.map_id)
        self.manager._broadcast(
            f"🚀 *Game live on {self.map.name}!*\n"
            f"Players: {len(self.players)} · Impostors: {n_imp}\n"
            "Check your DM for your role and starting location.",
            **({"image_url": start_url} if start_url else {}),
        )

    # ── Dispatch ───────────────────────────────────────────
    def handle(self, sender, text, received_at_ms=None, quoted_text=None):
        with self.lock:
            return self._handle_locked(sender, text, received_at_ms, quoted_text)

    def _handle_locked(self, sender, text, received_at_ms=None, quoted_text=None):
        p = self.players.get(sender)
        if not p:
            return "⚠️ _You're not in this game._"
        if getattr(p, "departed", False):
            return "⚠️ _You have left this game._"
        parts = text.split()
        cmd = parts[0].lower() if parts else ""
        command_at = self._timestamp_seconds(received_at_ms)
        self.movement.advance_all(command_at)
        if not self.over:
            self._advance_sabotages(command_at)
        if self.over:
            return None
        self._record_event(
            "command_received",
            at=command_at,
            actor=p.color,
            command=cmd,
        )
        if (
            PAIRED.is_scan_text(text)
            and p.alive
            and quoted_text
            and PAIRED.player_at_station(self, p)
        ):
            # A seated station player replying "scan" to any bot message.
            return PAIRED.handle_scan(self, p, text, command_at, quoted_text)[1]
        if self._task_ref(quoted_text):
            answer_text = text.strip()
            if answer_text.lower().startswith("ariel "):
                answer_text = answer_text[6:].strip()
            return self._cmd_task_reply(p, answer_text, quoted_text, command_at)
        if not p.alive:
            return self._handle_ghost(p, text, command_at, quoted_text)

        arg   = " ".join(parts[1:]).strip()

        handled, reply = PAIRED.handle_scan(self, p, text, command_at, quoted_text)
        if handled:
            return reply
        handled, reply = PAIRED.handle_ready(self, p, text, command_at)
        if handled:
            return reply

        if getattr(self, "_meeting", None) and cmd in self.MEETING_PAUSED_COMMANDS:
            return self.MEETING_PAUSED_TEXT
        if cmd == ".map":       return self._cmd_map(p, command_at)
        if cmd == ".say":       return self._cmd_say(p, text, command_at)
        if cmd == ".m":         return self._cmd_move(p, arg, command_at)
        if cmd == ".stop":
            self._end_follow(p, "still", command_at)
            return self.movement.stop(p, command_at)
        if cmd == ".goback":    return self.movement.go_back(p, command_at)
        if cmd == ".where":     return self._cmd_where(p, command_at)
        if cmd == ".status":    return self._status_reply(p, command_at)
        if cmd == ".kill":      return self._cmd_kill(p, arg, command_at)
        if cmd == ".task":      return self._cmd_task(p, arg, command_at, quoted_text)
        if cmd == ".tasks":     return self._cmd_tasks_all(p)
        if cmd == ".players":   return self._cmd_players()
        if cmd == ".progress":  return self._cmd_progress(p)
        if cmd == ".vent":      return self._cmd_vent(p, arg, command_at)
        if cmd == ".vitals":    return self._cmd_vitals(p, command_at)
        if cmd == ".witness":   return self._cmd_witness(p, command_at)
        if cmd == ".cds":       return self._cmd_cooldowns(p, command_at)
        if cmd == ".cooldown":  return self._cmd_cooldowns(p, command_at)
        if cmd == ".follow":    return self._cmd_follow(p, arg, command_at)
        if cmd == ".unfollow":  return self._cmd_unfollow(p)
        if cmd in {".cscene", ".crimescene", ".cs"}:
            return self._cmd_crime_scenes()
        if cmd == ".report":    return self._cmd_report(p, command_at)
        if cmd == ".meeting":   return self._cmd_call_meeting(p, "emergency", command_at)
        if cmd == ".vote":      return self._cmd_vote(
            p,
            arg,
            public=False,
            now=command_at,
        )
        if cmd == ".sabotage": return self._cmd_sabotage(p, arg, command_at)
        if p.task_in_progress and not cmd.startswith("."):
            return (
                "📎 _Reply to your quoted task prompt, or use "
                "`.task answer <your answer>`._"
            )
        return None  # unknown commands are ignored silently (no error reply)

    def handle_gc_vote(self, sender, text, received_at_ms=None):
        with self.lock:
            p = self.players.get(sender)
            if not p or not p.alive or getattr(p, "departed", False):
                return None
            parts = text.split()
            if parts and parts[0].lower() == ".vote":
                self._record_event(
                    "command_received",
                    at=self._timestamp_seconds(received_at_ms),
                    actor=p.color,
                    command=".vote",
                )
                return self._cmd_vote(
                    p,
                    " ".join(parts[1:]).strip(),
                    public=True,
                    now=self._timestamp_seconds(received_at_ms),
                )
            return None

    def _handle_ghost(self, p, text, now=None, quoted_text=None):
        now = time.time() if now is None else float(now)
        stripped = text.strip()
        if stripped.lower().startswith(".say "):
            msg = stripped[5:].strip()
            if not msg:
                return "👻 _Use .say <message> to talk to other ghosts._"
            self.manager._push_ghost_chat(self, p.jid, msg)
            return None
        parts = stripped.split()
        command = parts[0].lower() if parts else ""
        arg = " ".join(parts[1:]).strip()
        if self._meeting and command in {".m", ".stop", ".goback"}:
            return "⏸️ _Movement is paused during the meeting._"
        if command == ".m":
            return self._cmd_move(p, arg, now)
        if command == ".stop":
            return self.movement.stop(p, now)
        if command == ".goback":
            return self.movement.go_back(p, now)
        if command == ".where":
            return self._cmd_where(p, now)
        if command == ".map":
            return self._cmd_map(p, now)
        if command == ".status":
            return self._status_reply(p, now)
        if command == ".task":
            return self._cmd_task(p, arg, now, quoted_text)
        if command == ".tasks":
            return self._cmd_tasks_all(p)
        if command == ".progress":
            return self._cmd_progress(p)
        if command in {".cooldown", ".cds"}:
            return self._cmd_cooldowns(p, now)
        return None  # anything else is ignored silently (no error reply)

    def mark_departed(self, sender, now=None):
        """Remove an active player from the match and its meeting electorate."""
        with self.lock:
            player = self.players.get(sender)
            if not player or player.departed:
                return False
            at = time.time() if now is None else float(now)
            player.departed = True
            self.cancel_task_interaction(sender, "left_game")
            self._cancel_pending_kills_for(player, "departed", at)
            if player.path:
                self.movement.stop(player, at)
            player.in_vent_until = None
            PAIRED.vacate_player(self, sender, "left_game", at)
            self._drop_departed_tasks(player)
            if self._meeting:
                self._meeting["votes"].pop(sender, None)
                for voter, choice in tuple(self._meeting["votes"].items()):
                    if choice == sender:
                        self._meeting["votes"].pop(voter, None)
            self._record_event(
                "player_departed",
                at=at,
                actor=player.color,
            )
            self._resolve_win_check(at)
            return True

    def _drop_departed_tasks(self, player):
        """A departed Crewmate's unfinished tasks no longer count for the win.

        Nobody can finish them (living players only do their own tasks), so
        leaving them in the total would make a task win impossible. Tasks they
        already completed stay counted.
        """
        if player.role == "impostor":
            return
        gone = [t for t in player.tasks if not t.get("done")]
        for task in gone:
            task["claimed_by"] = None
        gone_ids = {id(t) for t in gone}
        self._team_tasks = [t for t in self._team_tasks if id(t) not in gone_ids]
        if gone:
            self._record_event(
                "tasks_dropped", actor=player.color, count=len(gone)
            )

    # ── Movement ───────────────────────────────────────────
    def _resolve_movement(self, p=None, now=None):
        """Compatibility wrapper; movement is advanced for the whole game."""
        self.movement.advance_all(time.time() if now is None else now)

    def _ping_room(self, mover, room, stage):
        """stage: 'final' | 'transit' | 'leave'"""
        room_display = room.replace("_", " ").title()

        quiet = self._comms_suppressing()
        if stage == "vent_arrival":
            self.manager._push_dm(
                mover.jid,
                f"🌀 You arrived from a vent in *{room_display}*.",
            )
            for other in self.players.values():
                if (
                    not quiet
                    and other.jid != mover.jid
                    and other.alive
                    and other.settled
                    and other.in_vent_until is None
                    and other.room == room
                ):
                    self.manager._push_dm(
                        other.jid,
                        f"🌀 *{self._observed_name(other.jid, mover.color)}* "
                        "arrived from a vent.",
                    )
            self._check_body_here(mover, room)
            return

        if stage == "leave":
            for other in self.players.values():
                if not quiet and other.jid != mover.jid and other.alive and other.settled and other.room == room:
                    who = self._observed_name(other.jid, mover.jid)
                    self.manager._push_dm(
                        other.jid, f"*{who}* has left *{room_display}*."
                    )
            return

        if stage == "final":
            msg_self   = f"✅ You have arrived at *{room_display}*."
            others_verb = "has arrived at"
        else:  # transit
            msg_self   = f"🚶 You are passing through *{room_display}*."
            others_verb = "is passing through"

        # Tell the mover
        self.manager._push_dm(mover.jid, msg_self)

        # Tell settled occupants + lingering check
        for other in self.players.values():
            if other.jid == mover.jid or not other.alive or not other.settled or other.room != room:
                continue
            if quiet:
                continue
            who = self._observed_name(other.jid, mover.jid)
            self.manager._push_dm(
                other.jid, f"*{who}* {others_verb} *{room_display}*."
            )
            if self._lingering_flag(other):
                self.manager._push_dm(
                    mover.jid,
                    f"👀 *{self._observed_name(mover.jid, other.color)}* seems to be lingering in *{room_display}*."
                )

        # Body check on final arrival only
        if stage == "final":
            self._check_body_here(mover, room)

    def _cmd_move(self, p, dest_raw, now=None):
        if not dest_raw:
            return self._rooms_list()

        # Number shortcut: .m 7 picks the 7th room from the list
        if dest_raw.strip().isdigit():
            idx = int(dest_raw.strip()) - 1
            if 0 <= idx < len(self.map.rooms):
                dest_raw = self.map.rooms[idx]
            else:
                return f"⚠️ _Pick a number between 1 and {len(self.map.rooms)}._"

        dest = dest_raw.strip().upper().replace(" ", "_")
        if dest not in self.map.edges:
            return "⚠️ _Unknown room._\n\n" + self._rooms_list()
        total_secs, error = self.movement.move(
            p,
            dest,
            time.time() if now is None else now,
        )
        if error:
            return error
        return (
            f"🚶 Heading to *{dest.replace('_',' ').title()}* (about {total_secs:g}s).\n"
            "Use *.stop* to stop at your current position."
        )

    def _rooms_list(self):
        lines = [f"{i+1}. {r.replace('_',' ').title()}" for i, r in enumerate(self.map.rooms)]
        return (
            "*Available rooms*\n" + "\n".join(lines)
            + "\n\nSend *.m <room name or number>* to move."
        )

    def _cmd_map(self, p, now=None):
        """`.map`: the picture of this map plus where YOU are and your exits.

        Only the caller's own position is given (never anyone else's). The
        picture is the direct link under ``maps`` in image_links.json; without
        one the same text is sent on its own.
        """
        now = time.time() if now is None else float(now)

        def title(room):
            return str(room).replace("_", " ").title()

        exits = None
        if p.in_vent_until is not None:
            where = f"inside a vent at the {title(p.vent_room or p.room)}"
        elif p.settled and p.room:
            where = f"at the {title(p.room)}"
            exits = self.map.edges.get(p.room, {})
        elif p.corridor_from and p.corridor_to:
            where = f"between the {title(p.corridor_from)} and the {title(p.corridor_to)}"
        else:
            where = f"at the {title(p.room)}"
        entries = self._players_entries_now()
        left = sum(1 for _jid, alive in entries if alive)
        lines = [
            self.map.name,
            f"You are currently {where}.",
            f"{left}/{len(entries)} players left",
        ]
        if exits:
            lines.append(
                "Exits: "
                + " · ".join(f"{title(r)} ({int(t)}s)" for r, t in sorted(exits.items()))
            )
        lines.append("Use .m <room> to move.")
        caption = "\n".join(lines)
        url = map_link(self.map_id)
        if url:
            self.manager._push_dm(p.jid, caption, image_url=url)
            return None
        return caption

    def _cmd_where(self, p, now=None):
        return self.movement.where(p, time.time() if now is None else now)

    def _same_area(self, first, second, now):
        if first.in_vent_until is not None or second.in_vent_until is not None:
            return False
        if (
            first.settled
            and second.settled
            and first.room == second.room
        ):
            return True
        first_position = self.movement._corridor_position(first, now)
        second_position = self.movement._corridor_position(second, now)
        return bool(
            first_position
            and second_position
            and first_position["edge"] == second_position["edge"]
        )

    def _nearby(self, first, second, now):
        if not self._same_area(first, second, now):
            return False
        if first.settled and second.settled and first.room == second.room:
            return True
        first_position = self.movement._corridor_position(first, now)
        second_position = self.movement._corridor_position(second, now)
        return bool(
            first_position
            and second_position
            and abs(first_position["canonical"] - second_position["canonical"])
            <= C.FOLLOW_PROXIMITY_RADIUS_SECONDS
        )

    def _advance_awareness(self, now):
        """Resolve camping and delayed follow reveals from authoritative world time."""
        if self.over:
            return
        self._resolve_due_kills(float(now))
        if self.over:
            return
        self._expire_task_interactions(float(now))
        if self.over:
            return

        for follower in self.players.values():
            if follower.following is None or follower.follow_started_at is None:
                continue
            target = self.players.get(follower.following)
            if not target or not target.alive:
                self._end_follow(follower, "lost")
                continue
            if target.in_vent_until is not None:
                self._end_follow(follower, "vent")
                continue
            if (
                not follower.follow_discovered
                and float(now) - float(follower.follow_started_at)
                >= C.FOLLOW_REVEAL_SECONDS
            ):
                follower.follow_discovered = True
                self.manager._push_dm(
                    target.jid,
                    f"👀 You are being followed by *{follower.color}*.",
                )
                self._record_event(
                    "follow_revealed",
                    at=float(now),
                    follower=follower.color,
                    target=target.color,
                )

        if self._comms_suppressing():
            # Camping awareness is off during Communications; drop, don't delay.
            self._drop_pending_camping()
            return
        for camper in self.players.values():
            if (
                camper.camping_notified
                or camper.stopped_since is None
                or camper.path
                or camper.in_vent_until is not None
                or float(now) - float(camper.stopped_since)
                < C.CAMPING_TRIGGER_SECONDS
            ):
                continue

            if camper.settled:
                stationary = camper.room
            elif camper.corridor_from is not None and camper.corridor_to is not None:
                position = self.movement._corridor_position(camper, now)
                stationary = position
            else:
                stationary = None
            if stationary is None:
                continue

            observers = [
                other for other in self.players.values()
                if other.jid != camper.jid
                and other.alive == camper.alive
                and self._same_area(camper, other, now)
            ]
            if not observers:
                continue

            camper.camping_notified = True
            self._record_event(
                "camping_awareness",
                at=float(now),
                actor=camper.color,
                observers=[other.color for other in observers],
                stopped_since=float(camper.stopped_since),
            )
            self.manager._push_dm(
                camper.jid,
                "👀 The other players are onto you. You've been here for a while.",
            )
            for observer in observers:
                self.manager._push_dm(
                    observer.jid,
                    f"👀 *{self._observed_name(observer.jid, camper.color)}* "
                    "has been stationary here for a while.",
                )

    def _resolve_due_kills(self, now):
        due = []
        for killer in self.players.values():
            pending = killer.pending_kill
            if not pending or float(now) + 1e-9 < pending["resolve_at"]:
                continue
            killer.pending_kill = None
            target = self.players.get(pending["target_jid"])
            if self._meeting:
                self.manager._push_dm(
                    killer.jid,
                    "⚠️ Your pending kill was cancelled because a meeting was called.",
                )
                self._record_event(
                    "pending_kill_cancelled",
                    at=float(now),
                    actor=killer.color,
                    target=target.color if target else "unknown",
                    reason="meeting",
                )
                continue
            due.append((killer, target))

        for killer, target in due:
            if target is not None:
                self._resolve_kill(killer, target, [], now=float(now))

    def _cancel_pending_kills_for(self, player, reason="movement", now=None):
        at = time.time() if now is None else float(now)
        for killer in self.players.values():
            pending = killer.pending_kill
            if not pending:
                continue
            if killer.jid != player.jid and pending["target_jid"] != player.jid:
                continue
            killer.pending_kill = None
            target = self.players.get(pending["target_jid"])
            if reason == "meeting":
                message = "⚠️ Your pending kill was cancelled because a meeting was called."
            elif killer.jid == player.jid:
                message = "⚠️ Your pending kill was cancelled because you moved."
            else:
                moved_color = player.color
                message = f"⚠️ Your pending kill was cancelled because {moved_color} moved."
            if killer.alive:
                self.manager._push_dm(killer.jid, message)
            self._record_event(
                "pending_kill_cancelled",
                at=at,
                actor=killer.color,
                target=target.color if target else "unknown",
                reason=reason,
            )

    def _cancel_all_pending_kills(self, reason, now=None):
        at = time.time() if now is None else float(now)
        for killer in self.players.values():
            pending = killer.pending_kill
            if not pending:
                continue
            target = self.players.get(pending["target_jid"])
            killer.pending_kill = None
            if killer.alive:
                self.manager._push_dm(
                    killer.jid,
                    "⚠️ Your pending kill was cancelled because a meeting was called."
                    if reason == "meeting"
                    else "⚠️ Your pending kill was cancelled.",
                )
            self._record_event(
                "pending_kill_cancelled",
                at=at,
                actor=killer.color,
                target=target.color if target else "unknown",
                reason=reason,
            )

    @staticmethod
    def _role_category(player):
        """Background category for a stage picture: Impostor or Crewmate (Scientist is a Crewmate)."""
        return "impostor" if player.role == "impostor" else "crewmate"

    def _status_reply(self, p, now=None):
        """`.status`, led by the player's own mini-preview when a stage picture is ready.

        With a picture the status text is the caption of a DM and nothing else is
        returned; without one the plain text is returned exactly as before.
        """
        text = self._cmd_status(p, now)
        if not isinstance(text, str):
            return text
        path = STAGE.compose("square", p.color, self._role_category(p))
        if not path:
            return text
        self.manager._push_dm(p.jid, text, image_url=path)
        return None

    def _cmd_status(self, p, now=None):
        now = time.time() if now is None else float(now)
        if p.in_vent_until is not None:
            return "🌀 _You're inside a vent; there is no room status to check._"

        if p.settled:
            area_text = p.room.replace('_', ' ').title()
            occupants = [
                other for other in self.players.values()
                if other.alive == p.alive
                and other.jid != p.jid
                and not getattr(other, "departed", False)
                and other.in_vent_until is None
                and other.settled
                and other.room == p.room
            ]
            bodies = list(self._bodies.get(p.room, []))
        else:
            position = self.movement._corridor_position(p, now)
            if position is None:
                return self.movement.where(p, now)
            first, second = position["edge"]
            area_text = (
                f"{first.replace('_', ' ').title()}–"
                f"{second.replace('_', ' ').title()} corridor"
            )
            occupants = [
                other for other in self.players.values()
                if other.alive == p.alive
                and other.jid != p.jid
                and not getattr(other, "departed", False)
                and self._nearby(p, other, now)
            ]
            bodies = []

        present = [p.color] + [other.color for other in occupants]
        role_label = {"impostor": "Impostor", "scientist": "Scientist"}.get(
            p.role, "Crewmate"
        )
        if self.over:
            match_state = "Ended"
        elif self._meeting:
            match_state = "Meeting"
        else:
            match_state = "In progress"
        others = present[1:]
        lines = [
            "📍 *YOUR STATUS*",
            f"Role: {role_label}",
            f"Status: {'Alive' if p.alive else 'Ghost'}",
            f"Location: {area_text}",
            "Players with you: " + (", ".join(others) if others else "None"),
        ]
        bodies_line = "Bodies here: None"
        if bodies:
            labels = []
            for victim_jid in bodies:
                corpse = self._corpses.get(victim_jid)
                victim = self.players.get(victim_jid)
                label = (
                    corpse.get("victim_color")
                    if corpse else (victim.color if victim else str(victim_jid))
                )
                labels.append(label)
                self._record_corpse_witness(victim_jid, p, now)
            bodies_line = "Bodies here: " + ", ".join(labels)
        lines.append(bodies_line)
        lines.append(f"Match: {match_state}")
        lines.append("Cooldowns: use *.cds*")

        revealed = []
        for follower in self.players.values():
            if (
                follower.following == p.jid
                and self._nearby(p, follower, now)
            ):
                revealed.append(follower)
                if not follower.follow_discovered:
                    follower.follow_discovered = True
                    self.manager._push_dm(
                        p.jid,
                        f"👀 You noticed *{follower.color}* following you.",
                    )
                    self.manager._push_dm(
                        follower.jid,
                        f"👀 *{p.color}* noticed you following.",
                    )
                    self._record_event(
                        "follow_discovered",
                        at=now,
                        follower=follower.color,
                        target=p.color,
                    )
        if revealed:
            lines.append("Following you: " + ", ".join(p.color for p in revealed) + ".")
        return "\n".join(lines)

    def _record_corpse_witness(self, victim_jid, witness, at=None):
        corpse = self._corpses.get(victim_jid)
        if corpse is None:
            victim = self.players.get(victim_jid)
            room = (
                getattr(victim, "death_room", None)
                or (victim.room if victim else None)
            )
            corpse = self._corpses.setdefault(
                victim_jid,
                {
                    "victim_jid": victim_jid,
                    "victim_color": victim.color if victim else str(victim_jid),
                    "room": room,
                    "killer_jid": None,
                    "witnesses": [],
                    "reported": False,
                },
            )
        if (
            corpse.get("reported")
            or witness.jid in {victim_jid, corpse.get("killer_jid")}
            or witness.jid in corpse["witnesses"]
        ):
            return False
        corpse["witnesses"].append(witness.jid)
        self._record_event(
            "corpse_witnessed",
            at=time.time() if at is None else float(at),
            victim=corpse["victim_color"],
            witness=witness.color,
            room=corpse.get("room"),
        )
        return True

    def _cmd_crime_scenes(self):
        if not self._reported_crime_scenes:
            return "*Reported Crime Scenes*\n\n_No reported crime scenes yet._"
        lines = ["*Reported Crime Scenes*"]
        for index, scene in enumerate(self._reported_crime_scenes, 1):
            room = scene["room"].replace("_", " ").title()
            lines.append(f"{index}. {room} — {scene['victim_color']}")
        return "\n".join(lines)

    def _vitals_status(self, player):
        if player.alive:
            return "Alive"
        if player.death_reason == "ejected":
            return "Dead — Ejected"
        corpse = self._corpses.get(player.jid)
        if corpse and corpse.get("reported"):
            return "Dead — Reported"
        if corpse and corpse.get("witnesses"):
            return "Dead — Witnessed"
        return "Dead — Unreported"

    def _vitals_roster(self):
        return [
            f"{player.color} — {self._vitals_status(player)}"
            for player in self.players.values()
        ]

    def _cmd_vitals(self, p, now=None):
        now = time.time() if now is None else float(now)
        if p.role != "scientist":
            return "🔒 _This command is available to the Scientist only._"
        remaining = p.vitals_cooldown_until - now
        if remaining > 0:
            return f"⏳ _Vitals cooldown: {math.ceil(remaining)}s._"
        p.vitals_cooldown_until = now + C.SCIENTIST_VITALS_COOLDOWN_SECONDS
        self._record_event("vitals_checked", at=now, actor=p.color)
        return "*Vitals*\n" + "\n".join(self._vitals_roster())

    def _cmd_witness(self, p, now=None):
        now = time.time() if now is None else float(now)
        if p.role != "scientist":
            return "🔒 _This command is available to the Scientist only._"
        remaining = p.witness_cooldown_until - now
        if remaining > 0:
            return f"⏳ _Witness cooldown: {math.ceil(remaining)}s._"
        p.witness_cooldown_until = now + C.SCIENTIST_WITNESS_COOLDOWN_SECONDS
        self._record_event("witness_checked", at=now, actor=p.color)

        lines = ["*Vitals & Witnesses*", *self._vitals_roster(), "", "*Corpse witnesses*"]
        if not self._corpses:
            lines.append("No corpse records.")
        for corpse in self._corpses.values():
            names = []
            reporter = corpse.get("reporter_jid")
            for witness_jid in corpse.get("witnesses", []):
                witness = self.players.get(witness_jid)
                if not witness:
                    continue
                label = witness.color
                names.append(f"*{label} (reporter)*" if witness_jid == reporter else label)
            lines.append(
                f"{corpse.get('victim_color', 'Unknown')}: "
                + (", ".join(names) if names else "no witnesses recorded")
            )
        return "\n".join(lines)

    def _cmd_cooldowns(self, p, now=None):
        now = time.time() if now is None else float(now)
        if not p.alive:
            entries = [("Ghost task", p.ghost_task_cooldown_until)]
        else:
            entries = [("Task", p.task_cooldown_until)]
        if p.alive and p.role == "impostor":
            entries.extend(
                [
                    ("Kill", p.kill_cooldown_until),
                    ("Vent", p.vent_cooldown_until),
                ]
            )
            for name in SABOTAGE_NAMES:
                sabotage = self._get_sabotage(name)
                entries.append(
                    (
                        f"{name.title()} sabotage",
                        float(sabotage["cooldown_until"]),
                    )
                )
        elif p.alive and p.role == "scientist":
            entries.extend(
                [
                    ("Vitals", p.vitals_cooldown_until),
                    ("Witness", p.witness_cooldown_until),
                ]
            )
        lines = ["*Your Cooldowns*"]
        for label, deadline in entries:
            remaining = float(deadline) - now
            value = f"{math.ceil(remaining)}s" if remaining > 0 else "Ready"
            lines.append(f"• {label}: {value}")
        return "\n".join(lines)

    def _lingering_flag(self, p):
        return p.settled and (time.time() - p.room_entered_at) >= LINGER_THRESHOLD_SECONDS

    # ── Kill ───────────────────────────────────────────────
    def _cmd_kill(self, p, arg, now=None):
        now = time.time() if now is None else float(now)
        if p.role != "impostor":
            return None
        if not p.settled or p.in_vent_until is not None:
            return "⚠️ _You must be in a room to kill._"
        if p.path:
            return "⚠️ _Finish or stop moving before attempting a kill._"
        if self._meeting:
            return "⚠️ _You can't kill during a meeting._"
        if p.pending_kill:
            return "_You already have a kill resolving._"
        if now < p.kill_cooldown_until:
            remaining = math.ceil(p.kill_cooldown_until - now)
            return f"⏳ _Kill on cooldown ({remaining}s left)._"

        occupants = [
            o for o in self.players.values()
            if o.alive and o.role != "impostor" and o.settled
            and o.room == p.room and o.jid != p.jid
        ]
        if not occupants:
            return "_No eligible Crewmate is here._"

        if arg:
            target = next(
                (
                    o for o in occupants
                    if o.jid == arg.strip()
                    or o.color.lower() == arg.strip().lower()
                ),
                None,
            )
            if not target:
                return "⚠️ _They're not here._"
        else:
            if len(occupants) > 1:
                return "⚠️ _Too crowded — use .kill <colour> to choose a target._"
            target = occupants[0]

        self._end_follow(p, "still", now)
        p.pending_kill = {
            "target_jid": target.jid,
            "started_at": now,
            "resolve_at": now + KILL_DELAY_SECONDS,
        }
        self._record_event(
            "kill_started",
            at=now,
            actor=p.color,
            target=target.color,
            resolves_at=now + KILL_DELAY_SECONDS,
        )
        return (
            f"🔪 Attempting to eliminate *{target.color}*. "
            f"Stay still for {KILL_DELAY_SECONDS}s; movement cancels the attempt."
        )

    def _resolve_kill(self, killer, target, crowd=None, now=None):
        if not killer.alive or not target.alive:
            return
        now = time.time() if now is None else float(now)
        if (
            self._meeting
            or killer.role != "impostor"
            or target.role == "impostor"
            or target.room != killer.room
            or not target.settled
            or not killer.settled
            or killer.in_vent_until is not None
            or target.in_vent_until is not None
        ):
            return  # one of them moved during the delay — whiff

        killer.kill_cooldown_until = now + KILL_COOLDOWN_SECONDS
        target.alive = False
        if (
            target.task_in_progress
            and target.task_in_progress.get("kind") == "sabotage_repair"
        ):
            self._cancel_task_interaction(target, "death", now)
        setattr(target, "death_room", killer.room)
        target.death_reason = "killed"
        self._bodies.setdefault(killer.room, []).append(target.jid)
        corpse = {
            "victim_jid": target.jid,
            "victim_color": target.color,
            "room": killer.room,
            "killer_jid": killer.jid,
            "witnesses": [],
            "reported": False,
        }
        self._corpses[target.jid] = corpse
        self._record_event(
            "kill_resolved",
            at=now,
            actor=killer.color,
            target=target.color,
            room=killer.room,
        )
        witnesses = [
            player for player in self.players.values()
            if player.alive
            and player.jid not in {killer.jid, target.jid}
            and player.settled
            and player.room == killer.room
        ]
        for witness in witnesses:
            self._record_corpse_witness(target.jid, witness, now)
            self.manager._push_dm(
                witness.jid,
                "⚠️ There seems to be distress in the room. Use .status to check.",
            )
        for follower in self.players.values():
            if (
                follower.following == killer.jid
                and follower.alive
                and self._nearby(follower, killer, now)
            ):
                self._record_corpse_witness(target.jid, follower, now)
                self.manager._push_dm(
                    follower.jid,
                    f"😱 You witnessed a murder involving *{target.color}*.",
                )
        self.manager._push_dm(
            target.jid,
            "💀 You've been eliminated.\n"
            "You're now a Ghost. Use *.say <message>* to talk to other ghosts."
        )
        self._end_follow(target, "lost", now)
        self._end_followers(target, "lost", now)
        self._resolve_win_check(now)

    def _check_body_here(self, mover, room):
        bodies = self._bodies.get(room)
        if bodies:
            now = time.time()
            for victim_jid in bodies:
                self._record_corpse_witness(victim_jid, mover, now)
            self.manager._push_dm(
                mover.jid,
                "You have found a corpse.\nUse .report to call meeting"
            )

    # ── Tasks ──────────────────────────────────────────────
    @staticmethod
    def _task_ref(text):
        if not text:
            return None
        match = re.search(r"\[Task Ref:\s*(I\d+)\]", str(text), re.IGNORECASE)
        return match.group(1).upper() if match else None

    @staticmethod
    def _normalize_task_answer(value):
        return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())

    def _find_task(self, task_id):
        for task in getattr(self, "_team_tasks", []):
            if task.get("id") == task_id:
                return task
        for player in self.players.values():
            for task in player.tasks:
                if task.get("id") == task_id:
                    return task
        return None

    def _task_candidates(self, player, room_only=True, exclude_task_id=None):
        if not player.alive:
            source = getattr(self, "_team_tasks", [])
        else:
            source = player.tasks
        return [
            task for task in source
            if not task.get("done")
            and (exclude_task_id is None or task.get("id") != exclude_task_id)
            and (not task.get("claimed_by") or task.get("claimed_by") == player.jid)
            and (not room_only or not player.alive or task.get("room") == player.room)
        ]

    def _make_task_challenge(self, task):
        """Return one varied, text-friendly WhatsApp interaction for this task."""
        name = task["name"].lower()
        if "wir" in name:
            left = ["RED", "BLUE", "GREEN", "YELLOW"]
            right = left[:]
            random.shuffle(right)
            positions = {color: index + 1 for index, color in enumerate(right)}
            answer = " ".join(str(positions[color]) for color in left)
            prompt = (
                "🔌 Fix Wiring: left wires are RED, BLUE, GREEN, YELLOW. "
                "Right terminals are numbered top-to-bottom: "
                + ", ".join(f"{i + 1}={color}" for i, color in enumerate(right))
                + ". Reply with the right-terminal numbers matching the left wires, in order."
            )
            return prompt, answer

        if "engine" in name or "reactor" in name:
            code = [str(random.randint(1, 4)) for _ in range(4)]
            return (
                "⚡ Restore the sequence in order: " + " → ".join(code)
                + ". Reply with the four digits in order.",
                " ".join(code),
            )

        if "course" in name:
            code = [random.choice(("N", "E", "S", "W")) for _ in range(4)]
            return (
                "🧭 Chart this course in order: " + " → ".join(code)
                + ". Reply with the four directions.",
                " ".join(code),
            )

        if "asteroid" in name:
            field = [random.choice(("☄️", "·")) for _ in range(8)]
            count = sum(icon == "☄️" for icon in field)
            return (
                "☄️ Count the asteroids in this field: " + " ".join(field)
                + ". Reply with the number.",
                str(count),
            )

        if "upload" in name or "data" in name:
            values = [random.randint(1, 9) for _ in range(3)]
            return (
                f"📡 Upload checksum: add {values[0]} + {values[1]} + {values[2]}. "
                "Reply with the total.",
                str(sum(values)),
            )

        if "shield" in name:
            active = sorted(random.sample(("A", "B", "C", "D"), 2))
            return (
                "🛡️ Prime the active shield panels: "
                + ", ".join(active)
                + ". Reply with the panel letters.",
                " ".join(active),
            )

        if "card" in name:
            return "💳 Swipe the card through the reader. Reply `SWIPE` when done.", "SWIPE"
        if "garbage" in name:
            return "🗑️ Pull the chute lever to empty the garbage. Reply `PULL`.", "PULL"
        if "scan" in name:
            return "🩺 Hold still for the scan, then reply `SCAN`.", "SCAN"
        return "🔧 Complete the task and reply `DONE`.", "DONE"

    def _task_notice(self, message):
        try:
            self.manager._broadcast(message, tag_all=True, hide_tags=True)
        except TypeError:
            # Compatibility with lightweight managers used by local harnesses.
            self.manager._broadcast(message)

    def _start_task_interaction(self, player, task, now):
        if player.alive and player.role == "impostor":
            task["fake"] = True
        if task.get("claimed_by") not in (None, player.jid):
            return "⚠️ _That task is already in progress._"
        task["claimed_by"] = player.jid
        self._interaction_sequence = getattr(self, "_interaction_sequence", 0) + 1
        interaction_ref = f"I{self._interaction_sequence:04d}"
        prompt, expected = self._make_task_challenge(task)
        player.task_in_progress = {
            "task_id": task["id"],
            "interaction_ref": interaction_ref,
            "expected": expected,
            "started_at": float(now),
            "last_activity_at": float(now),
            "expires_at": float(now) + C.TASK_INTERACTION_TIMEOUT_SECONDS,
        }
        self._end_follow(player, "still", now)
        self._record_event(
            "task_started",
            at=float(now),
            actor=player.color,
            task=task["name"],
            room=task["room"],
            interaction_ref=interaction_ref,
        )
        place = task["room"].replace("_", " ").title()
        if player.alive:
            notice = (
                f"🔧 *{player.color}* started *{task['name']}* in *{place}*."
                if not task.get("fake")
                else f"🔧 *{player.color}* began working on *{task['name']}* in *{place}*."
            )
        else:
            notice = "👻 The Crewmate task list has been updated."
        self._task_notice(notice)
        return (
            f"🧩 *{task['name']}*\n{prompt}\n\n"
            "Reply to this message with your answer, or send "
            "*.task answer <answer>*.\n"
            f"_This interaction expires after {C.TASK_INTERACTION_TIMEOUT_SECONDS}s without activity._\n"
            f"[Task Ref: {interaction_ref}]"
        )

    def _cancel_task_interaction(self, player, reason, now=None, notify=True):
        active = player.task_in_progress
        if not active:
            return False
        at = time.time() if now is None else float(now)
        kind = active.get("kind", "task")
        sabotage_name = active.get("sabotage")
        task = self._find_task(active.get("task_id")) if kind == "task" else None
        if task and task.get("claimed_by") == player.jid:
            task["claimed_by"] = None
        if kind == "sabotage_repair" and sabotage_name:
            sabotage = self._ensure_sabotage_registry().get(sabotage_name)
            if sabotage:
                sabotage["repair_interactions"].pop(player.jid, None)
        player.task_in_progress = None
        closed = getattr(self, "_closed_task_prompts", None)
        if closed is None:
            closed = self._closed_task_prompts = {}
        closed[active["interaction_ref"]] = reason
        self._record_event(
            (
                "sabotage_repair_cancelled"
                if kind == "sabotage_repair"
                else "task_interaction_cancelled"
            ),
            at=at,
            actor=player.color,
            task=task["name"] if task else None,
            sabotage=sabotage_name,
            reason=reason,
            interaction_ref=active["interaction_ref"],
        )
        if notify:
            if kind == "sabotage_repair":
                label = {
                    "expired": "⏱️ Your repair interaction expired after a minute without activity.",
                    "movement": "🚶 Moving cancelled your repair interaction.",
                    "vent": "🌀 Entering the vent cancelled your repair interaction.",
                    "left_game": "👋 Leaving the game cancelled your repair interaction.",
                    "death": "💀 Your repair interaction ended when you died.",
                }.get(reason, "⚠️ Your repair interaction was cancelled.")
                self.manager._push_dm(player.jid, label)
                return True
            label = {
                "expired": (
                    "⏱️ Your task interaction expired after "
                    f"{C.TASK_INTERACTION_TIMEOUT_SECONDS} seconds without activity. "
                    "The task remains unfinished."
                ),
                "movement": "🚶 Moving cancelled your task interaction; the task is still unfinished.",
                "vent": "🌀 Entering the vent cancelled your task interaction.",
                "left_game": "👋 Leaving the game cancelled your active task interaction.",
                "abandoned": (
                    "↪️ Previous task interaction abandoned. "
                    "The task remains unfinished."
                ),
            }.get(reason, "⚠️ Your task interaction was cancelled.")
            self.manager._push_dm(player.jid, label)
        return True

    def cancel_task_interaction(self, sender, reason="left_game"):
        with self.lock:
            player = self.players.get(sender)
            return bool(
                player
                and self._cancel_task_interaction(player, reason, time.time())
            )

    def _expire_task_interactions(self, now):
        for player in self.players.values():
            active = player.task_in_progress
            if active and float(now) >= float(active["expires_at"]):
                self._cancel_task_interaction(player, "expired", now)

    def _cmd_task_reply(self, player, answer_text, quoted_text=None, now=None):
        now = time.time() if now is None else float(now)
        active = player.task_in_progress
        quoted_ref = self._task_ref(quoted_text)
        if active is None:
            closed = getattr(self, "_closed_task_prompts", {})
            if quoted_ref and closed.get(quoted_ref) == "completed":
                return "_That task interaction is already complete; duplicate reply ignored._"
            if quoted_ref:
                return "_That task prompt is stale. Start or check a task with `.task`._"
            return "_No active task interaction. Use `.task` to start one._"
        if quoted_ref and quoted_ref != active["interaction_ref"]:
            closed = getattr(self, "_closed_task_prompts", {})
            if closed.get(quoted_ref) == "completed":
                return "_That task interaction is already complete; duplicate reply ignored._"
            return "_That reply belongs to an older task prompt. Reply to the current prompt._"
        if not quoted_ref and not answer_text.lower().startswith(".task answer "):
            return "📎 _Quote-reply to the task prompt, or use `.task answer <answer>`._"
        if self._meeting:
            return "⚠️ _Tasks can't be completed during a meeting._"
        if player.alive and (
            not player.settled or player.path or player.in_vent_until is not None
        ):
            return "⚠️ _Finish your move before completing the task._"

        if answer_text.lower().startswith(".task answer "):
            answer = answer_text[len(".task answer "):].strip()
        else:
            answer = answer_text.strip()
        if not answer:
            return "⚠️ _Include an answer, or quote-reply with one._"

        if active.get("kind") == "sabotage_repair":
            return self._cmd_sabotage_repair_reply(
                player, active, answer, now
            )

        task = self._find_task(active["task_id"])
        if not task or task.get("done"):
            self._cancel_task_interaction(player, "stale", now, notify=False)
            return "_That task is no longer available; duplicate completion was ignored._"
        if self._normalize_task_answer(answer) != self._normalize_task_answer(active["expected"]):
            active["last_activity_at"] = now
            active["expires_at"] = now + C.TASK_INTERACTION_TIMEOUT_SECONDS
            return (
                "❌ _That answer doesn't match. Try again before the timer expires._"
            )

        task["done"] = True
        task["claimed_by"] = None
        player.task_in_progress = None
        closed = getattr(self, "_closed_task_prompts", None)
        if closed is None:
            closed = self._closed_task_prompts = {}
        closed[active["interaction_ref"]] = "completed"
        if player.alive:
            player.task_cooldown_until = now + C.TASK_COOLDOWN_SECONDS
        else:
            player.ghost_task_cooldown_until = now + C.GHOST_TASK_COOLDOWN_SECONDS
        self._record_event(
            "task_completed",
            at=now,
            actor=player.color,
            task=task["name"],
            task_id=task["id"],
            ghost=not player.alive,
            fake=bool(task.get("fake")),
        )

        team_tasks = getattr(self, "_team_tasks", [])
        completed_team = sum(1 for item in team_tasks if item.get("done"))
        total_team = len(team_tasks)
        if task.get("fake"):
            remaining = sum(1 for item in player.tasks if not item.get("done"))
            reply = f"✅ *{task['name']}* logged. {remaining} fake task(s) remain."
            group_notice = (
                f"✅ *{player.color}* finished working on *{task['name']}*."
            )
        elif not player.alive:
            remaining = max(0, total_team - completed_team)
            reply = (
                "👻 ✅ Task complete. "
                + (
                    f"{remaining} team task(s) remain."
                    if remaining else "All team tasks are complete."
                )
            )
            group_notice = "👻 Team task progress was updated."
            owner = self.players.get(task.get("owner_jid"))
            if owner and owner.jid != player.jid:
                self.manager._push_dm(
                    owner.jid,
                    f"👻 A Ghost completed your *{task['name']}* task.",
                )
        else:
            remaining = sum(1 for item in player.tasks if not item.get("done"))
            reply = (
                f"✅ *{task['name']}* complete.\n"
                f"Tasks remaining: {remaining}"
            )
            if not remaining:
                reply += "\nAll your assigned tasks are complete."
            if total_team:
                reply += f"\nTeam progress: {completed_team}/{total_team}."
            group_notice = (
                f"✅ *{player.color}* completed *{task['name']}* in "
                f"*{task['room'].replace('_', ' ').title()}*. "
                f"Team tasks: {completed_team}/{total_team}."
            )
        self._task_notice(group_notice)
        self._resolve_win_check(now)
        return reply

    def _cmd_sabotage_repair_reply(self, player, active, answer, now):
        puzzle_kind = (active.get("metadata") or {}).get("puzzle")
        if puzzle_kind == "circuit":
            return self._circuit_press(player, active, answer, now)
        if puzzle_kind == "phrase":
            return self._phrase_answer(player, active, answer, now)
        if not self._normalize_task_answer(answer) == self._normalize_task_answer(
            active.get("expected", "")
        ):
            active["last_activity_at"] = now
            active["expires_at"] = now + C.TASK_INTERACTION_TIMEOUT_SECONDS
            return (
                "❌ _That repair answer doesn't match. Try again before "
                "the inactivity timer expires._"
            )
        name = active.get("sabotage")
        if not self._repair_sabotage(name, player, now):
            self._cancel_task_interaction(
                player, "stale", now, notify=False
            )
            return "_That repair is no longer available._"
        self._closed_task_prompts[active["interaction_ref"]] = "completed"
        return f"✅ _{name.title()} sabotage repaired._"

    def _cmd_task_next(self, player, now):
        active = player.task_in_progress
        if not active:
            cooldown_until = (
                player.task_cooldown_until
                if player.alive else player.ghost_task_cooldown_until
            )
            remaining = cooldown_until - now
            if remaining > 0:
                label = "Task" if player.alive else "Ghost task"
                return f"⏳ _{label} cooldown: {math.ceil(remaining)}s._"
        active_task_id = active["task_id"] if active else None
        candidates = self._task_candidates(
            player,
            room_only=player.alive,
            exclude_task_id=active_task_id,
        )
        if not candidates:
            return "_No other eligible task is available here; your current interaction is still active._"
        if active:
            self._cancel_task_interaction(player, "abandoned", now, notify=True)
        return self._start_task_interaction(player, candidates[0], now)

    def _cmd_task(self, p, arg, now=None, quoted_text=None):
        now = time.time() if now is None else float(now)
        action = arg.strip()
        action_lower = action.lower()
        if action_lower.startswith("answer "):
            return self._cmd_task_reply(
                p,
                ".task answer " + action.split(maxsplit=1)[1],
                quoted_text,
                now,
            )
        if action_lower == "answer":
            return "⚠️ _Usage: `.task answer <answer>`._"

        if self._meeting:
            return "⚠️ _Tasks can't be started or switched during a meeting._"
        if p.alive and (
            not p.settled or p.path or p.in_vent_until is not None
        ):
            return "⚠️ _Can't start a task while moving or inside a vent._"
        if action_lower == "next":
            return self._cmd_task_next(p, now)
        if p.task_in_progress:
            return (
                "You already have an active task in progress. Type "
                '".task next" to abandon your current task and begin your next task.'
            )

        if not action and self._lights_repair_available(p):
            return self._start_lights_puzzle(p, now)
        if not action and self._comms_repair_available(p):
            return self._start_comms_puzzle(p, now)
        if not action:
            handled, reply = PAIRED.join_station(self, p, now)
            if handled:
                return reply

        cooldown_until = (
            p.task_cooldown_until if p.alive else p.ghost_task_cooldown_until
        )
        remaining = cooldown_until - now
        if remaining > 0:
            label = "Task" if p.alive else "Ghost task"
            return f"⏳ _{label} cooldown: {math.ceil(remaining)}s._"

        candidates = self._task_candidates(p, room_only=p.alive)
        if not action:
            if not candidates:
                return (
                    "_Nothing to do here._"
                    if p.alive else "_No available team tasks remain._"
                )
            title = (
                f"Tasks here: {p.room.replace('_', ' ').title()}"
                if p.alive else "Available ghost tasks"
            )
            lines = [
                f"{i + 1}. {task['name']}"
                for i, task in enumerate(candidates)
            ]
            return (
                f"*{title}*\n" + "\n".join(lines)
                + "\n\nSend *.task <number>* to start one."
            )

        try:
            task = candidates[int(action) - 1]
        except (ValueError, IndexError):
            return "⚠️ _Invalid task number. Use `.task` to list eligible tasks._"
        if p.alive and task["room"] != p.room:
            return "⚠️ _You can only start an assigned task in its room._"
        return self._start_task_interaction(p, task, now)

    def _team_task_progress(self):
        tasks = getattr(self, "_team_tasks", [])
        if not tasks:
            return 0, 0
        return sum(1 for task in tasks if task.get("done")), len(tasks)

    def _cmd_progress(self, p):
        completed, total = self._team_task_progress()
        if p.role == "impostor":
            # Impostors never see the real figure: a plausible fake, with
            # done/total derived from it so the reply looks the same.
            percentage = random.randint(10, 90)
            completed = round(percentage * total / 100) if total else 0
        else:
            percentage = int(100 * completed / total) if total else 0
        if self._get_sabotage("communications").suppressing:
            # 7B-2a-ii: during the outage the reading may be wrong and may be
            # shown in another writing system or language.
            rng = getattr(self, "_comms_rng", None)
            return "*Team task progress*\n" + comms_display.garble_progress(percentage, rng)["text"]
        return (
            "*Team task progress*\n"
            f"{completed}/{total} tasks complete ({percentage}%)."
        )

    # ── Vent ───────────────────────────────────────────────
    def _cmd_vent(self, p, arg, now=None):
        now = time.time() if now is None else float(now)
        if p.role != "impostor":
            return None
        action = arg.strip()
        action_lower = action.lower()

        if p.in_vent_until is not None:
            current_vent = p.vent_room or p.vent_dest or p.room
            if not action:
                options = self.map.vents.get(current_vent, [])
                choices = ", ".join(room.replace("_", " ").title() for room in options)
                remaining = max(0, math.ceil(p.in_vent_until - now))
                return (
                    f"🌀 *Inside the vent at {current_vent.replace('_', ' ').title()}.*\n"
                    f"Connections: {choices or 'none'}\n"
                    f"Use `.vent <destination>` or `.vent out`. Ejection in ~{remaining}s."
                )
            if action_lower == "out":
                return self._exit_vent(p, now, automatic=False)
            if action_lower == "in":
                return "_You're already inside a vent._"

            options = self.map.vents.get(current_vent, [])
            destination = self._vent_destination(action, options)
            if destination is None:
                return (
                    "⚠️ _That vent is not connected._\n"
                    + (
                        "Connected vents: "
                        + ", ".join(room.replace("_", " ").title() for room in options)
                        if options else "No connected vents."
                    )
                )
            p.vent_room = destination
            self._record_event(
                "vent_travel",
                at=now,
                actor=p.color,
                from_room=current_vent,
                to_room=destination,
            )
            remaining = max(0, math.ceil(p.in_vent_until - now))
            return (
                f"🌀 _You travelled through the vent to "
                f"{destination.replace('_', ' ').title()}. "
                f"{remaining}s remain before ejection._"
            )

        if action_lower != "in":
            if not action:
                options = self.map.vents.get(p.room, [])
                if not options:
                    return "_No vent here._"
                remaining = max(0, math.ceil(p.vent_cooldown_until - now))
                cooldown = (
                    f" Vent cooldown: {remaining}s."
                    if remaining > 0 else ""
                )
                return (
                    f"*Vent available in {p.room.replace('_', ' ').title()}.* "
                    f"Connections: {', '.join(room.replace('_', ' ').title() for room in options)}.\n"
                    f"Use `.vent in` to enter.{cooldown}"
                )
            return "⚠️ _Use `.vent in` to enter a vent._"

        if not p.settled or p.path:
            return "⚠️ _You're mid-move._"
        remaining = p.vent_cooldown_until - now
        if remaining > 0:
            return f"⏳ _Vent on cooldown ({math.ceil(remaining)}s left)._"
        options = self.map.vents.get(p.room, [])
        if not options:
            return "_No vent here._"

        observers = [
            other for other in self.players.values()
            if other.alive
            and other.jid != p.jid
            and other.settled
            and other.in_vent_until is None
            and other.room == p.room
        ]
        self._end_follow(p, "still", now)
        self._end_followers(p, "vent", now)
        self._cancel_task_interaction(p, "vent", now)
        self._cancel_pending_kills_for(p, "vent", now)
        p.vent_room = p.room
        p.vent_entered_at = now
        p.in_vent_until = now + C.VENT_MAX_SECONDS
        p.vent_dest = None
        p.settled = False
        p.stopped_since = None
        p.camping_notified = False
        self._record_event(
            "vent_entered",
            at=now,
            actor=p.color,
            room=p.room,
        )
        for observer in ([] if self._comms_suppressing() else observers):
            self.manager._push_dm(
                observer.jid,
                f"🌀 *{p.color}* has used a vent.",
            )
        return (
            f"🌀 You entered the vent at *{p.room.replace('_', ' ').title()}*. "
            f"You have {C.VENT_MAX_SECONDS}s before automatic ejection."
        )

    def _vent_destination(self, raw, options):
        value = raw.strip()
        if value.isdigit():
            index = int(value) - 1
            return options[index] if 0 <= index < len(options) else None
        normalized = value.upper().replace(" ", "_")
        return next((room for room in options if room == normalized), None)

    def _exit_vent(self, p, now, automatic):
        room = p.vent_room or p.vent_dest or p.room
        p.room = room
        p.in_vent_until = None
        p.vent_dest = None
        p.vent_room = None
        p.vent_entered_at = None
        p.settled = True
        p.room_entered_at = float(now)
        p.reference_room = room
        p.stopped_since = float(now)
        p.camping_notified = False
        p.vent_cooldown_until = float(now) + C.VENT_COOLDOWN_SECONDS
        self._record_event(
            "vent_ejected" if automatic else "vent_exited",
            at=float(now),
            actor=p.color,
            room=room,
        )
        self._ping_room(p, room, stage="vent_arrival")
        return None

    # ── Follow ─────────────────────────────────────────────
    def _cmd_follow(self, p, arg, now=None):
        now = time.time() if now is None else float(now)
        if not arg:
            return "_Usage: .follow <colour>_"
        target_jid = self.color_to_jid.get(arg.strip().lower())
        if target_jid is None and arg.strip() in self.players:
            target_jid = arg.strip()
        target = self.players.get(target_jid)
        if not target or not target.alive or target.jid == p.jid:
            return "⚠️ _Can't follow them._"
        if target.in_vent_until is not None or not self._nearby(p, target, now):
            return "⚠️ _You need to be nearby to follow them._"
        if p.following:
            self._end_follow(p, "manual", now)

        p.following = target.jid
        p.follow_started_at = now
        p.follow_discovered = False
        p.follow_move_active = False
        self._record_event(
            "follow_started",
            at=now,
            follower=p.color,
            target=target.color,
        )

        if target.path:
            destination = target.path[-1]
            _, error = self.movement.move(p, destination, now)
            if not error:
                p.follow_move_active = True
                self.manager._push_dm(p.jid, f"🚶 Trailing *{target.color}*...")
        return (
            f"🚶 You are now following *{target.color}*.\n"
            "Use *.unfollow* to stop."
        )

    def _cmd_unfollow(self, p):
        if p.following is None:
            return "_You're not following anyone._"
        self._end_follow(p, "manual")
        return None

    def _end_follow(self, follower, reason, now=None):
        target_jid = follower.following
        if target_jid is None:
            return False
        target = self.players.get(target_jid)
        ended_at = time.time() if now is None else float(now)
        if (
            reason != "still"
            and follower.alive
            and follower.follow_move_active
            and follower.path
        ):
            self.movement.stop(follower, ended_at)
        follower.following = None
        follower.follow_started_at = None
        follower.follow_discovered = False
        follower.follow_move_active = False
        self._record_event(
            "follow_ended",
            at=ended_at,
            follower=follower.color,
            target=target.color if target else "unknown",
            reason=reason,
        )
        if reason == "vent":
            self.manager._push_dm(
                follower.jid,
                f"🌀 *{target.color if target else 'They'}* entered a vent. You lost their trail.",
            )
            if target and target.alive:
                self.manager._push_dm(
                    target.jid,
                    f"👀 *{follower.color}* lost your trail.",
                )
        elif reason == "lost":
            self.manager._push_dm(follower.jid, "_You have lost their trail._")
        else:
            self.manager._push_dm(
                follower.jid,
                f"_You stopped following {target.color if target else 'them'}._",
            )
            if target and target.alive:
                self.manager._push_dm(
                    target.jid,
                    f"👀 *{follower.color}* loses interest and stops following.",
                )
        return True

    def _end_followers(self, target, reason, now=None):
        for follower in tuple(self.players.values()):
            if follower.following == target.jid:
                self._end_follow(follower, reason, now)

    def _on_player_departure(self, target, room, at):
        for follower in self.players.values():
            if follower.following != target.jid:
                continue
            self.manager._push_dm(
                follower.jid,
                f"🚶 *{target.color}* is leaving *{room.replace('_', ' ').title()}*.",
            )
            if (
                follower.alive
                and follower.settled
                and follower.room == room
                and not follower.path
                and target.path
            ):
                _, error = self.movement.move(follower, target.path[-1], at)
                if not error:
                    follower.follow_move_active = True
                    self.manager._push_dm(follower.jid, "🚶 Trailing...")

    def _on_player_arrival(self, target, room, at):
        for follower in self.players.values():
            if follower.following == target.jid:
                self.manager._push_dm(
                    follower.jid,
                    f"📍 *{target.color}* has arrived at *{room.replace('_', ' ').title()}*.",
                )

    def _cmd_tasks_all(self, p):
        """`.tasks`: the text list, with the TASKS LIST picture when a link is set.

        Only a living player's own list gets the picture (ghost tasks stay text).
        """
        text = self._tasks_all_text(p)
        url = tasks_list_link()
        if url and p.alive and text.startswith("📋"):
            self.manager._push_dm(p.jid, text, image_url=url, image_card=True)
            return None
        return text

    def _tasks_all_text(self, p):
        """Show full personal task list across all rooms."""
        if not p.alive:
            available = self._task_candidates(p, room_only=False)
            if not available:
                return "_All available team tasks are complete or already in progress._"
            lines = []
            for index, task in enumerate(available, 1):
                owner = self.players.get(task.get("owner_jid"))
                owner_color = owner.color if owner else "Crewmate"
                room = task["room"].replace("_", " ").title()
                lines.append(f"{index}. {task['name']} — {room} ({owner_color})")
            completed, total = self._team_task_progress()
            return (
                f"*Ghost tasks ({completed}/{total} team tasks complete):*\n"
                + "\n".join(lines)
            )

        pending = [t for t in p.tasks if not t["done"]]
        done    = [t for t in p.tasks if t["done"]]

        def room_name(task):
            return task["room"].replace("_", " ").title()

        # Design note v5.3, 22.3: TASKS LIST with Your tasks / General tasks /
        # Finished tasks. Numbering is this player's own.
        title = "*Fake tasks*" if p.role == "impostor" else "*Your tasks*"
        lines = ["📋 *TASKS LIST*", "", title]
        if pending:
            lines += [
                f"{i}. {t['name']} — {room_name(t)}" for i, t in enumerate(pending, 1)
            ]
        elif p.role == "impostor":
            lines.append("All your fake tasks are logged.")
        else:
            lines.append("All your assigned tasks are complete!")

        general = []
        for sab_name in SABOTAGE_NAMES:
            if self._get_sabotage(sab_name)["state"] != "active":
                continue
            for _key, station_label, room in M.get_stations(sab_name, self.map_id):
                general.append(f"{station_label} — {room.replace('_', ' ').title()}")
        if general:
            lines += ["", "*General tasks*"]
            lines += [f"{i}. {text}" for i, text in enumerate(general, 1)]

        lines += ["", "*Finished tasks*"]
        lines += [f"- ~{t['name']}~" for t in done] if done else ["None"]
        return "\n".join(lines)

    def _players_entries_now(self):
        """Roster used for player counts; the Comms outage freezes it, as for `.players`."""
        frozen = self._get_sabotage("communications").frozen_players
        return frozen if frozen is not None else self._players_entries()

    def _players_entries(self):
        """Live (jid, alive) list of everyone still in the game."""
        return [
            (p.jid, bool(p.alive)) for p in self.players.values()
            if not getattr(p, "departed", False)
        ]

    def _cmd_players(self):
        """Show who's still alive.

        During Communications the list is the frozen pre-sabotage snapshot
        (7B-2a-ii): deaths and departures since then do not show, and no
        notice says so. It resumes updating once Communications is repaired.
        """
        frozen = self._get_sabotage("communications").frozen_players
        entries = frozen if frozen is not None else self._players_entries()
        def label(jid):
            player = self.players.get(jid)
            return player.color if player else "Unknown"

        alive = [label(jid) for jid, is_alive in entries if is_alive]
        dead = [label(jid) for jid, is_alive in entries if not is_alive]
        lines = [f"👨‍🚀 {name}" for name in alive]
        lines += [f"~{name}~" for name in dead]
        return f"*Players still alive ({len(alive)}):*\n" + "\n".join(lines)

    # ── Report ─────────────────────────────────────────────
    def _cmd_report(self, p, now=None):
        if not p.alive or getattr(p, "departed", False):
            return "⚠️ _Only a living player can report a body._"
        if getattr(self, "_meeting", None):
            return "⚠️ _A meeting is already in progress._"
        if not p.settled:
            return "_You need to be in a room to report a body._"
        at = time.time() if now is None else float(now)
        bodies = [
            victim_jid
            for victim_jid in self._bodies.get(p.room, [])
            if p.jid in self._corpses.get(victim_jid, {}).get("witnesses", [])
        ]
        if not bodies:
            return "⚠️ _You haven't witnessed a reportable body here._"

        for victim_jid in bodies:
            victim = self.players.get(victim_jid)
            corpse = self._corpses.get(victim_jid)
            if corpse is None:
                corpse = {
                    "victim_jid": victim_jid,
                    "victim_color": victim.color if victim else str(victim_jid),
                    "room": p.room,
                    "killer_jid": None,
                    "witnesses": [],
                    "reported": False,
                }
                self._corpses[victim_jid] = corpse
            if not corpse["reported"]:
                corpse["reported"] = True
                corpse["reporter_jid"] = p.jid
                scene = {
                    "victim_jid": victim_jid,
                    "victim_color": corpse["victim_color"],
                    "room": corpse["room"] or p.room,
                    "reported_at": at,
                }
                self._reported_crime_scenes.append(scene)
                self._record_event(
                    "crime_scene_reported",
                    at=at,
                    reporter=p.color,
                    victim=scene["victim_color"],
                    room=scene["room"],
                )

        victims = ", ".join(
            self._corpses[victim_jid]["victim_color"] for victim_jid in bodies
        )
        remaining_bodies = [
            victim_jid
            for victim_jid in self._bodies.get(p.room, [])
            if victim_jid not in bodies
        ]
        if remaining_bodies:
            self._bodies[p.room] = remaining_bodies
        else:
            self._bodies.pop(p.room, None)
        self._end_follow(p, "still", at)
        self._cmd_call_meeting(
            p, "report", at,
            report={
                "room": p.room.replace("_", " ").title(),
                "victims": victims,
                "count": len(bodies),
            },
        )
        return None

    def _roster_text(self):
        lines = []
        for pl in self.players.values():
            if getattr(pl, "departed", False):
                continue
            lines.append(f"~{pl.color}~" if not pl.alive else pl.color)
        return "\n".join(lines)

    # ── Meeting / Voting ───────────────────────────────────
    MEETING_REASON_TEXT = {
        "report": "report of a body",
        "emergency": "emergency meeting",
    }
    # Commands that do not change the game; everything else dotted is paused.
    MEETING_PAUSED_COMMANDS = {
        ".m", ".stop", ".goback", ".vent", ".kill", ".task", ".follow",
        ".unfollow", ".report", ".meeting", ".sabotage", ".vitals",
        ".witness", ".ready",
    }
    MEETING_PAUSED_TEXT = (
        "⏸️ _Game commands are paused during the meeting._\n"
        "_Use the meeting chat: discuss in the game group, send_ "
        "*.say <message>* _here to speak as your colour, and_ "
        "*.vote <colour>* _or_ *.vote skip* _once voting opens._"
    )

    def _push_with_link(self, jid, text):
        """DM a player; the bot appends the real game-group link when it can."""
        push = getattr(self.manager, "_push_dm_with_link", None) or self.manager._push_dm
        push(jid, text)

    def _meeting_voters(self, meeting=None):
        meeting = meeting or self._meeting
        return [
            player for player in self.players.values()
            if player.jid in meeting["eligible"]
            and player.alive and not getattr(player, "departed", False)
        ]

    def _cmd_call_meeting(self, caller, reason, now=None, report=None):
        if self._meeting:
            return "⚠️ _A meeting's already in progress._"
        if not caller.alive or getattr(caller, "departed", False):
            return "⚠️ _Only a living player can call a meeting._"
        now = time.time() if now is None else float(now)
        self._resolve_due_sabotage_deadlines(now)
        if self.over:
            return None
        self._end_follow(caller, "still", now)
        self._cancel_all_pending_kills("meeting", now)
        # A player inside a vent is pulled out into the vent's room and takes part.
        for player in self.players.values():
            if (
                player.alive
                and not getattr(player, "departed", False)
                and player.in_vent_until is not None
            ):
                self._exit_vent(player, now, automatic=True)
        self.movement.pause(now)
        self._pause_sabotage_deadlines(now)
        meeting = {
            "votes": {},
            "started_at": now,
            "ends_at": now + MEETING_VOTE_SECONDS,
            "opens_at": now + C.MEETING_VOTING_OPENS_SECONDS,
            "reason": reason,
            "caller": caller.jid,
            "eligible": {
                player.jid for player in self.players.values()
                if player.alive and not getattr(player, "departed", False)
            },
        }
        self._meeting = meeting
        self._sync_comms_restriction(now)
        reason_text = self.MEETING_REASON_TEXT.get(reason, str(reason))
        if reason == "report":
            headline = f"🚨 *{caller.color} found a corpse!*"
            if report:
                label = "Victim" if report.get("count", 1) == 1 else "Victims"
                group_text = (
                    f"🚨 *{caller.color} found a corpse in {report['room']}!*\n"
                    f"{label}: *{report['victims']}*\n\n"
                    "Meeting started. Discuss here or use *.say <message>* from DM."
                )
            else:
                group_text = (
                    f"{headline}\n"
                    "Meeting started. Discuss here or use *.say <message>* from DM."
                )
        else:
            headline = f"🚨 *{caller.color} called an emergency meeting!*"
            group_text = (
                f"{headline}\n"
                "Discuss the situation here, or use *.say <message>* "
                "in DM to speak as your colour."
            )
        self.manager._broadcast(
            group_text,
            append_dm_link=True,
            **STAGE.preview_kwargs(
                "square", caller.color, None, kind="meeting_call",
                scene="report" if reason == "report" else "emergency",
            ),
        )
        dm_headline = (
            headline if reason == "report"
            else f"🚨 *{caller.color} called an emergency meeting.*"
        )
        dm_text = (
            f"{dm_headline}\n"
            "Use .say to participate from your DM,\n"
            "or join directly:"
        )
        for voter in self._meeting_voters(meeting):
            self._push_with_link(voter.jid, dm_text)
        self._schedule(
            C.MEETING_VOTING_OPENS_SECONDS,
            lambda: self._meeting_voting_open(meeting),
        )
        self._schedule(
            max(0, C.MEETING_WARNING_SECONDS),
            lambda: self._meeting_warning(meeting),
        )
        self._schedule(
            MEETING_VOTE_SECONDS,
            lambda: self._resolve_meeting()
            if self._meeting is meeting else None,
        )
        return None

    def _meeting_voting_open(self, meeting):
        """Open voting once (timer or tick, whichever is first)."""
        if self._meeting is not meeting or meeting.get("voting_open"):
            return
        meeting["voting_open"] = True
        seconds = C.MEETING_VOTING_WINDOW_SECONDS
        self.manager._broadcast(
            "🗳️ *Voting is open.*\n"
            "Use *.vote <colour>* or *.vote skip*. "
            "You may also vote privately through DM.",
            tag_all=True,
            hide_tags=True,
            append_dm_link=True,
        )
        for voter in self._meeting_voters(meeting):
            self.manager._push_dm(
                voter.jid,
                "🗳️ *Voting is open.*\n"
                "Use *.vote <colour>* or *.vote skip*. "
                "You can change your vote until voting closes.",
            )

    def _meeting_warning(self, meeting):
        """Send the 10-second vote warning once (timer or tick, whichever is first)."""
        if self._meeting is not meeting or meeting.get("warned"):
            return
        self._meeting_voting_open(meeting)  # never warn before voting opened
        meeting["warned"] = True
        self.manager._broadcast(
            "⏰ *10 seconds remaining!* Submit or change your vote before voting closes."
        )

    def _advance_meeting(self, now):
        """Tick-driven voting open, warning and resolution, so a meeting never
        depends on a wall-clock timer alone (the timers remain as a backstop)."""
        meeting = self._meeting
        if not meeting:
            return
        now = float(now)
        if now >= meeting["started_at"] + C.MEETING_VOTING_OPENS_SECONDS:
            self._meeting_voting_open(meeting)
        if now >= meeting["started_at"] + C.MEETING_WARNING_SECONDS:
            self._meeting_warning(meeting)
        if now >= meeting["ends_at"]:
            self._resolve_meeting(meeting["ends_at"])

    def _cmd_say(self, p, text, now=None):
        """A living player's contribution to the meeting, relayed to the game
        group under their colour (their WhatsApp identity is never shown)."""
        meeting = self._meeting
        if not meeting:
            return "💬 _.say works during meetings. Ghosts use it in the Ghosts group._"
        if p.jid not in meeting["eligible"] or not p.alive:
            return "⚠️ _Only players in this meeting can speak in it._"
        message = text.strip()[4:].strip()
        if not message:
            return "💬 _Use .say <message> to speak in the meeting._"
        self.manager._broadcast(f"🗣️ *{p.color}:* {message}")
        return None

    def _cmd_vote(self, p, arg, public, now=None):
        if not self._meeting:
            return "⚠️ _No active meeting._"
        self._meeting.setdefault(
            "eligible",
            {
                player.jid for player in self.players.values()
                if player.alive and not getattr(player, "departed", False)
            },
        )
        self._meeting.setdefault(
            "ends_at",
            float(self._meeting.get("started_at", time.time()))
            + MEETING_VOTE_SECONDS,
        )
        self._meeting.setdefault(
            "opens_at",
            float(self._meeting.get("started_at", time.time()))
            + C.MEETING_VOTING_OPENS_SECONDS,
        )
        if not p.alive and not getattr(p, "departed", False):
            return "👻 _Ghosts cannot vote._"
        if (
            getattr(p, "departed", False)
            or p.jid not in self._meeting["eligible"]
        ):
            return "⚠️ _Only active living players can vote._"
        at = time.time() if now is None else float(now)
        if at >= float(self._meeting["ends_at"]):
            self._resolve_meeting(at)
            return "⚠️ _Voting has closed._"
        if at < float(self._meeting["opens_at"]):
            early = f"⚠️ _Voting opens at {C.MEETING_VOTING_OPENS_SECONDS} seconds._"
            if public:
                self.manager._push_dm(p.jid, early)
                from .amongus import DELETE_INCOMING_MESSAGE
                return DELETE_INCOMING_MESSAGE
            return early
        if not arg:
            return "_Usage: .vote <colour> or .vote skip_"
        raw_choice = arg.strip()
        if raw_choice.casefold() == "skip":
            choice = "skip"
        else:
            target = next(
                (
                    player for player in self.players.values()
                    if player.jid.casefold() == raw_choice.casefold()
                    or player.color.casefold() == raw_choice.casefold()
                ),
                None,
            )
            if (
                target is None
                or not target.alive
                or getattr(target, "departed", False)
            ):
                return (
                    "⚠️ _That vote wasn't accepted. Choose an active player's colour "
                    "or skip; for details, send the vote in DM._"
                    if public else "⚠️ _Choose an active player's colour or skip._"
                )
            choice = target.jid

        previous = self._meeting["votes"].get(p.jid)
        self._meeting["votes"][p.jid] = choice
        self._record_event(
            "vote_submitted",
            at=at,
            actor=p.color,
            changed=previous is not None,
        )
        acknowledgement = (
            "🗳️ _Your vote was changed. Your latest vote replaces the previous one._"
            if previous is not None
            else "🗳️ _Your vote is registered privately._"
        )
        if public:
            self.manager._push_dm(p.jid, acknowledgement)
            from .amongus import DELETE_INCOMING_MESSAGE
            return DELETE_INCOMING_MESSAGE
        return acknowledgement

    def _impostor_count_line(self):
        total = sum(1 for pl in self.players.values() if pl.role == "impostor")
        remaining = sum(
            1 for pl in self.players.values()
            if pl.role == "impostor" and pl.alive and not getattr(pl, "departed", False)
        )
        if remaining == 0:
            return (
                "All Impostors have been eliminated." if total != 1
                else "The Impostor has been eliminated."
            )
        return f"{remaining}/{total} Impostor{'s' if total != 1 else ''} remain{'s' if total == 1 else ''}."

    def _match_would_end(self):
        """True if the match is over or about to be (used to drop "Carry on...")."""
        if self.over:
            return True
        active = [
            p for p in self.players.values() if not getattr(p, "departed", False)
        ]
        alive = [p for p in active if p.alive]
        alive_imp = [p for p in alive if p.role == "impostor"]
        alive_crew = [p for p in alive if p.role != "impostor"]
        team_tasks = getattr(self, "_team_tasks", [])
        tasks_done = bool(team_tasks) and all(t.get("done") for t in team_tasks)
        return (
            not active or not alive_imp
            or len(alive_imp) >= len(alive_crew) or tasks_done
        )

    def _announce_ejection(self, ejected):
        """Staged meeting result (design note v5.3, section 22.6).

        Four group messages, EJECTION_REVEAL_STEP_SECONDS (4 s) apart: "Meeting
        has ended.", two suspense messages, then ONE merged result for the
        actual outcome (`ejected` is None when nobody was ejected). The
        ejection is already final in game state; only delivery is timed, so a
        win is decided at once and the match-over message follows the result.
        If that ends the match the result leaves out "Carry on...".
        The ejection mini-preview rides on the final message.
        """
        step = C.EJECTION_REVEAL_STEP_SECONDS
        extra = {}
        if ejected is None:
            outcome = ["No one was ejected."]
        else:
            if ejected.role == "impostor":
                role_line = f"{ejected.color} was an Impostor."
            else:
                role_line = f"{ejected.color} was not the Impostor."
            outcome = [
                f"{ejected.color} was ejected.",
                role_line,
                self._impostor_count_line(),
            ]
            extra = STAGE.preview_kwargs(
                "square", ejected.color, self._role_category(ejected),
                kind="ejection", scene="ejection",
            )

        def send_result(outcome=outcome, extra=extra):
            lines = list(outcome)
            if not self._match_would_end():
                lines.append("Carry on...")
            self.manager._broadcast("\n".join(lines), **extra)

        self._deliver(lambda: self.manager._broadcast("⏱️ *Meeting ended.*"), step)
        self._deliver(lambda: self.manager._broadcast("..."), step)
        self._deliver(lambda: self.manager._broadcast("......."), step)
        self._deliver(send_result, step)

    def _resolve_meeting(self, now=None):
        if not self._meeting:
            return
        at = time.time() if now is None else float(now)
        meeting = self._meeting
        self._meeting = None
        self._sync_comms_restriction(at)
        paused_for = self.movement.resume(at)
        if paused_for:
            for player in self.players.values():
                active = player.task_in_progress
                if active:
                    active["expires_at"] = float(active["expires_at"]) + paused_for
                    active["last_activity_at"] = (
                        float(active["last_activity_at"]) + paused_for
                    )
        self._resume_sabotage_deadlines(at)

        tally = {}
        for voter_jid, choice in meeting["votes"].items():
            voter = self.players.get(voter_jid)
            if (
                not voter
                or not voter.alive
                or getattr(voter, "departed", False)
                or voter_jid not in meeting["eligible"]
            ):
                continue
            if choice != "skip":
                target = self.players.get(choice)
                if (
                    not target
                    or not target.alive
                    or getattr(target, "departed", False)
                ):
                    continue
            tally[choice] = tally.get(choice, 0) + 1

        if not tally:
            self._announce_ejection(None)
            self._resolve_win_check(at)
            return

        top     = max(tally.values())
        leaders = [choice for choice, count in tally.items() if count == top]
        if len(leaders) > 1:
            self._announce_ejection(None)
            self._resolve_win_check(at)
            return
        if leaders[0] == "skip":
            self._announce_ejection(None)
            self._resolve_win_check(at)
            return

        ejected = self.players.get(leaders[0])
        if ejected:
            ejected.alive = False
            if (
                ejected.task_in_progress
                and ejected.task_in_progress.get("kind") == "sabotage_repair"
            ):
                self._cancel_task_interaction(ejected, "death", at)
            ejected.death_reason = "ejected"
            self._end_follow(ejected, "lost")
            self._end_followers(ejected, "lost")
            self._record_event(
                "player_ejected",
                at=at,
                actor=ejected.color,
                role=ejected.role,
            )
            self._announce_ejection(ejected)
        self._resolve_win_check(at)

    # ── Sabotage framework ─────────────────────────────────
    def _ensure_sabotage_registry(self):
        registry = getattr(self, "_sabotages", None)
        if registry is None:
            registry = self._sabotages = {}
        for name in SABOTAGE_NAMES:
            if name not in registry:
                registry[name] = make_sabotage(
                    name, C.SABOTAGE_COOLDOWNS_SECONDS[name], game=self
                )
        return registry

    def _get_sabotage(self, name):
        return self._ensure_sabotage_registry()[name]

    def _comms_restriction_wanted(self):
        if not C.COMMS_RESTRICTION_ENABLED or self.over:
            return False
        if not self._get_sabotage("communications").suppressing:
            return False
        if C.COMMS_RESTRICTION_LIFTED_DURING_MEETINGS and getattr(self, "_meeting", None):
            return False
        return True

    def _sync_comms_restriction(self, at=None):
        """Tell the transport when the Communications chat restriction starts
        or ends. The restriction itself (deleting non-game messages in the game
        group) is applied by the manager; this only records it on the bot side
        so a restart cannot leave it behind. A transport failure (bot not group
        admin) is handled on the bot side and never blocks the game.
        """
        want = self._comms_restriction_wanted()
        if want == bool(getattr(self, "_comms_restricted", False)):
            return False
        self._comms_restricted = want
        send = getattr(self.manager, "_set_comms_restriction", None)
        sent = bool(callable(send) and send(want, group_jid=self.group_jid))
        self._record_event(
            "comms_restricted" if want else "comms_unrestricted",
            at=at,
            transport=sent,
        )
        return True

    def comms_restriction_active(self):
        """True right now (live, not the last synced value) while ordinary
        messages in the game group are being deleted."""
        with self.lock:
            return not self.over and self._comms_restriction_wanted()

    def _comms_phrase_interaction(self, jid):
        player = self.players.get(jid)
        if not player or not player.alive or getattr(player, "departed", False):
            return None
        active = player.task_in_progress
        if (
            active
            and active.get("kind") == "sabotage_repair"
            and active.get("sabotage") == "communications"
            and (active.get("metadata") or {}).get("puzzle") == "phrase"
        ):
            return active
        return None

    def is_comms_phrase_answer(self, jid, text, quoted_text=None):
        """An answer-shaped message from a player repairing Communications:
        a reply to a bot task prompt, or `.task answer <phrase>`."""
        with self.lock:
            if not self._comms_phrase_interaction(jid):
                return False
            body = (text or "").strip()
            return bool(self._task_ref(quoted_text)) or body.lower().startswith(
                ".task answer "
            )

    def group_message_allowed(self, jid, text, quoted_text=None):
        """False when the message must be deleted from the game group.

        While Communications is down only Among Us commands are kept, plus the
        phrase answer of the player currently repairing. A meeting lifts the
        restriction (everything is allowed).
        """
        with self.lock:
            if self.over or not self._comms_restriction_wanted():
                return True
            words = (text or "").strip().split(None, 1)
            if words and words[0].lower() in C.COMMS_GROUP_ALLOWED_COMMANDS:
                return True
            return self.is_comms_phrase_answer(jid, text, quoted_text)

    def _comms_inactivity_report(self, activated_at, repaired_at):
        """One consolidated report after Communications is repaired.

        Lists living players who stood still for more than the threshold
        during the outage (measured from the later of their last stop and the
        outage start), with where they are. Not proof of guilt.
        """
        threshold = C.COMMS_INACTIVITY_REPORT_SECONDS
        rows = []
        for player in self.players.values():
            if (
                not player.alive
                or getattr(player, "departed", False)
                or player.in_vent_until is not None
                or player.stopped_since is None
                or player.path
            ):
                continue
            since = max(float(player.stopped_since), float(activated_at))
            idle = float(repaired_at) - since
            if idle <= threshold:
                continue
            if player.settled:
                where = player.room.replace("_", " ").title()
            elif player.corridor_from and player.corridor_to:
                where = (
                    f"the {player.corridor_from.replace('_', ' ').title()} – "
                    f"{player.corridor_to.replace('_', ' ').title()} corridor"
                )
            else:
                continue
            rows.append((idle, player.color, where))
        rows.sort(key=lambda row: (-row[0], row[1]))
        if rows:
            lines = [
                f"• *{color}* — {where}, still for {int(idle)}s"
                for idle, color, where in rows
            ]
            body = "\n".join(lines)
        else:
            body = "_Nobody stood still for over " f"{threshold}s._"
        self._record_event(
            "comms_inactivity_report",
            at=float(repaired_at),
            players=[color for _, color, _ in rows],
        )
        self.manager._broadcast(
            "📡 *Communications restored — activity report.*\n"
            f"Players inactive for over {threshold}s during the outage:\n"
            f"{body}\n"
            "_This is not proof of guilt._"
        )

    def _comms_suppressing(self):
        """True while Communications is down: passive notices are not sent.

        Events are still recorded (authoritative world state); only the
        automatic DMs to observers are dropped, with no replay after repair.
        """
        return self._get_sabotage("communications").suppressing

    def _drop_pending_camping(self):
        """Drop camping triggers instead of delaying them (7B-2a-iii).

        A fresh stop after repair resets camping_notified and starts a new
        timer, so a player already stationary is not flagged late.
        """
        for player in self.players.values():
            if player.stopped_since is not None:
                player.camping_notified = True

    def _lights_masking(self):
        """True while Lights is active and passive observations hide who."""
        return self._get_sabotage("lights")["state"] == "active"

    def _observed_name(self, observer_jid, actor_color):
        """Name an observer is shown for a passive observation of actor_color.

        Impostors always see true identities; everyone else sees "Someone"
        while Lights is active. Chosen at send time, so earlier observations
        stay masked after repair and new ones are not.
        """
        if not self._lights_masking():
            return actor_color
        observer = self.players.get(observer_jid)
        if observer is not None and observer.role == "impostor":
            return actor_color
        return "Someone"

    def _active_sabotage_states(self):
        states = []
        states.extend(
            state for state in getattr(self, "_sabotages", {}).values()
            if isinstance(state, dict) and state.get("state") == "active"
        )
        unique = []
        seen = set()
        for state in states:
            if id(state) not in seen:
                unique.append(state)
                seen.add(id(state))
        return unique

    def _pause_sabotage_deadlines(self, now):
        """Freeze active sabotage deadlines without touching their cooldowns."""
        for state in self._active_sabotage_states():
            deadline = state.get("deadline")
            if deadline is None or state.get("paused_remaining") is not None:
                continue
            state["paused_remaining"] = max(0.0, float(deadline) - float(now))
            state["deadline"] = None
            timer = state.pop("timer", None)
            if timer is not None:
                timer.cancel()
                self._timers.discard(timer)

    def _resolve_due_sabotage_deadlines(self, now, inclusive=False):
        """Fail every sabotage whose deadline has passed.

        ``inclusive`` is used when settling a simultaneous ending: a deadline
        equal to ``now`` counts as expired (exact ties go to the Impostors).
        """
        for state in self._active_sabotage_states():
            deadline = state.get("deadline")
            if deadline is None:
                continue
            if float(deadline) > float(now) or (
                float(deadline) == float(now) and not inclusive
            ):
                continue
            if isinstance(state, Sabotage):
                # The failure is stamped at the deadline, not at the (later)
                # moment the engine noticed it.
                self._fail_sabotage(state["name"], float(deadline))
                if self.over:
                    return
                continue
            callback = state.get("on_expire")
            if callable(callback):
                callback()
            if self.over:
                return

    def _resume_sabotage_deadlines(self, now):
        for state in self._active_sabotage_states():
            remaining = state.get("paused_remaining")
            if remaining is None:
                continue
            state["paused_remaining"] = None
            state["deadline"] = float(now) + max(0.0, float(remaining))
            if not isinstance(state, Sabotage):
                callback = state.get("on_expire")
                if callable(callback):
                    state["timer"] = self._schedule(remaining, callback)

    def _advance_sabotages(self, now):
        """Emit scheduled warnings and fail timed sabotages from world time."""
        if self.over:
            return
        at = float(now)
        self._resolve_due_sabotage_deadlines(at)
        if self.over:
            return
        for state in self._active_sabotage_states():
            if not isinstance(state, Sabotage):
                continue
            deadline = state.get("deadline")
            if deadline is None:
                continue
            remaining = float(deadline) - at
            if remaining <= 0:
                continue
            sent = state.setdefault("warnings_sent", set())
            for warning in C.SABOTAGE_WARNING_SECONDS:
                warning = int(warning)
                if remaining <= warning and warning not in sent:
                    sent.add(warning)
                    shown = self.SABOTAGE_DISPLAY_NAMES.get(
                        state["name"], state["name"].title()
                    )
                    self._sabotage_event(
                        f"⚠️ *{shown}: {warning}s remaining.*\n"
                        "Reach the required station(s) and finish the repair."
                    )
        PAIRED.tick_all(self, at)

    # ── Sabotage event delivery (06A) ──────────────────────
    SABOTAGE_BANNERS = {
        "lights": ("💡", "LIGHTS"),
        "communications": ("📡", "COMMUNICATIONS"),
        "oxygen": ("💨", "O₂"),
        "reactor": ("☢️", "REACTOR"),
    }

    SABOTAGE_DISPLAY_NAMES = {
        "lights": "Lights",
        "communications": "Communications",
        "oxygen": "O₂",
        "reactor": "Reactor",
    }

    def _sabotage_event(self, text):
        """Send one world-event notice to the game group and to every player's DM.

        Ghosts and Impostors get it too (06D); departed players do not. The DM
        copy carries the real game-group link, resolved by the bot at send time.
        The text never names the Impostor who triggered anything.
        """
        self.manager._broadcast(text)
        push = getattr(self.manager, "_push_dm_with_link", None) or self.manager._push_dm
        for player in self.players.values():
            if getattr(player, "departed", False):
                continue
            push(player.jid, text)

    def _sabotage_activation_text(self, name):
        emoji, label = self.SABOTAGE_BANNERS[name]
        stations = "\n".join(
            f"- {station_label} — {room.replace('_', ' ').title()}"
            for _key, station_label, room in M.get_stations(name, self.map_id)
        )
        return f"{emoji} *{label} SABOTAGED!*\n\n*Required stations:*\n{stations}"

    def _cmd_sabotage(self, p, arg="", now=None):
        if p.role != "impostor":
            return None
        now = time.time() if now is None else float(now)
        name = str(arg or "").strip().lower()
        if name in {"comms", "communication"}:
            name = "communications"
        if name in {"o2", "o₂"}:
            name = "oxygen"
        if name not in SABOTAGE_NAMES:
            return (
                "⚠️ _Use `.sabotage lights`, `.sabotage communications`, "
                "`.sabotage oxygen`, or `.sabotage reactor`._"
            )
        if self._meeting:
            return "⏸️ _Sabotage is unavailable during a meeting._"
        sabotage = self._get_sabotage(name)
        if sabotage["state"] == "active":
            return f"⚠️ _{name.title()} sabotage is already active._"
        remaining = float(sabotage["cooldown_until"]) - float(now)
        if remaining > 0:
            return (
                f"⏳ _{name.title()} sabotage cooldown: "
                f"{math.ceil(remaining)}s._"
            )
        sabotage.activate(now)
        if name == "communications":
            sabotage.freeze_players(self._players_entries())
            self._drop_pending_camping()
            self._sync_comms_restriction(now)
        self._record_event(
            "sabotage_activated",
            at=now,
            actor=p.color,
            sabotage=name,
            cooldown_until=sabotage["cooldown_until"],
        )
        # The announcement never names the Impostor (06A rule 11).
        self._sabotage_event(self._sabotage_activation_text(name))
        # Only the triggering Impostor gets a private confirmation.
        self.manager._push_dm(
            p.jid, f"{self.SABOTAGE_DISPLAY_NAMES[name]} sabotage initiated."
        )
        return None

    # ── Lights circuit puzzle (7B-1b-ii) ───────────────────
    def _lights_repair_available(self, p):
        return (
            p.alive
            and not getattr(p, "departed", False)
            and p.settled
            and p.room == M.get_station_rooms("lights", self.map_id)[0]
            and self._get_sabotage("lights")["state"] == "active"
        )

    @staticmethod
    def _render_circuit(pattern, state, hint=True):
        switches = "  ".join(
            f"{i + 1}{'🟢' if on else '🔴'}" for i, on in enumerate(state)
        )
        return (
            f"🔌 *Lights circuit* ({pattern.name} wiring)\n"
            f"{switches}\n"
            "Goal: every switch 🟢. A switch can also flip others, so "
            "work out the wiring."
            + (f" Send a number from 1 to {pattern.size}." if hint else "")
        )

    def _start_lights_puzzle(self, p, now):
        """One private circuit puzzle per player; state lives on the interaction."""
        pattern = puzzles.pick_pattern()
        state = puzzles.scramble(pattern)
        reply = self._start_sabotage_repair_interaction(
            p,
            "lights",
            self._render_circuit(pattern, state, hint=False),
            expected="",
            now=now,
            metadata={
                "puzzle": "circuit",
                "pattern": pattern.id,
                "state": list(state),
                "presses": 0,
            },
            answer_hint=f"a switch number from 1 to {pattern.size}",
            answer_format="<number>",
        )
        if p.task_in_progress and p.task_in_progress.get("kind") == "sabotage_repair":
            self._task_notice(
                f"🔧 *{p.color}* is working on the *Lights* circuit "
                "in *Electrical*."
            )
        return reply

    def _circuit_press(self, player, active, answer, now):
        meta = active["metadata"]
        pattern = puzzles.get_pattern(meta["pattern"])
        text = str(answer).strip()
        if not text.isdigit() or not 1 <= int(text) <= pattern.size:
            return f"⚠️ _Send a switch number from 1 to {pattern.size}._"
        if self._get_sabotage("lights")["state"] != "active":
            self._cancel_task_interaction(player, "stale", now, notify=False)
            return "_That repair is no longer available._"

        state = puzzles.apply_switch(tuple(meta["state"]), pattern, int(text) - 1)
        meta["state"] = list(state)
        meta["presses"] += 1
        active["last_activity_at"] = now
        active["expires_at"] = now + C.TASK_INTERACTION_TIMEOUT_SECONDS
        self._record_event(
            "circuit_press",
            at=now,
            actor=player.color,
            switch=int(text),
            interaction_ref=active["interaction_ref"],
        )
        if puzzles.is_solved(state):
            return self._on_circuit_solved(player, active, now)
        return (
            self._render_circuit(pattern, state)
            + f"\n[Task Ref: {active['interaction_ref']}]"
        )

    def _on_circuit_solved(self, player, active, now):
        """First solved circuit repairs Lights for everyone, exactly once."""
        self._record_event(
            "circuit_solved",
            at=now,
            actor=player.color,
            interaction_ref=active["interaction_ref"],
        )
        # _repair_sabotage clears every player's Lights repair interaction
        # (including this one) and announces the repair to the group once.
        if not self._repair_sabotage("lights", player, now):
            self._cancel_task_interaction(player, "stale", now, notify=False)
            return "_That repair is no longer available._"
        self._closed_task_prompts[active["interaction_ref"]] = "completed"
        return "✅ _Circuit aligned. Lights repaired._"

    # ── Communications phrase puzzle (7B-2c-i) ─────────────
    def _comms_repair_available(self, p):
        return (
            p.alive
            and not getattr(p, "departed", False)
            and p.settled
            and p.room == M.get_station_rooms("communications", self.map_id)[0]
            and self._get_sabotage("communications")["state"] == "active"
        )

    def _start_comms_puzzle(self, p, now):
        """Post a scrambled phrase in the game group; the player answers THERE.

        Ordinary group chat is being deleted while Communications is down, so
        the answer must be a reply to the group's transmission message, or
        `.task answer <phrase>` typed in the group. DM answers are not accepted
        (the manager refuses them). Each attempt gets its own phrase.
        """
        in_use = [
            (other.task_in_progress.get("metadata") or {}).get("phrase_id")
            for other in self.players.values()
            if other.task_in_progress
            and other.task_in_progress.get("kind") == "sabotage_repair"
            and other.task_in_progress.get("sabotage") == "communications"
        ]
        puzzle = puzzles.make_phrase_puzzle(
            getattr(self, "_phrase_rng", None), exclude_ids=in_use
        )
        reply = self._start_sabotage_repair_interaction(
            p,
            "communications",
            "📡 Unscramble the transmission:\n"
            f"*{puzzle['scrambled']}*",
            expected=puzzle["expected"],
            now=now,
            metadata={
                "puzzle": "phrase",
                "phrase_id": puzzle["id"],
                "scrambled": puzzle["scrambled"],
                "attempts": 0,
            },
            answer_hint="the intended phrase",
            answer_format="<phrase>",
        )
        if not (isinstance(reply, str) and reply.startswith("🧩 *Communications repair*")):
            return reply
        ref = p.task_in_progress["interaction_ref"]
        self._task_notice(
            "📡 *Communications repair*\n"
            f"Unscramble: *{puzzle['scrambled']}*\n"
            f"Only {p.color} can submit the answer in the game group. "
            "Reply to this transmission message or use *.task answer <phrase>*.\n"
            f"[Task Ref: {ref}]"
        )
        return (
            "🧩 *Communications repair*\n"
            "📡 Unscramble the transmission:\n"
            f"*{puzzle['scrambled']}*\n\n"
            "Answer *in the game group*: reply to the transmission message "
            "there, or send `.task answer <phrase>` there. "
            "Private answers are not accepted.\n"
            f"_This interaction expires after "
            f"{C.TASK_INTERACTION_TIMEOUT_SECONDS}s without activity._"
        )

    def _phrase_answer(self, player, active, answer, now):
        meta = active["metadata"]
        if self._get_sabotage("communications")["state"] != "active":
            self._cancel_task_interaction(player, "stale", now, notify=False)
            return "_That repair is no longer available._"
        meta["attempts"] += 1
        correct = puzzles.check_phrase(meta["phrase_id"], answer)
        self._record_event(
            "phrase_answer",
            at=now,
            actor=player.color,
            correct=correct,
            attempts=meta["attempts"],
            interaction_ref=active["interaction_ref"],
        )
        if not correct:
            active["last_activity_at"] = now
            active["expires_at"] = now + C.TASK_INTERACTION_TIMEOUT_SECONDS
            return (
                "❌ _That's not the intended phrase. Communications is still "
                "down; try again before the inactivity timer expires._\n"
                f"Transmission: *{meta['scrambled']}*"
            )
        if not self._repair_sabotage("communications", player, now):
            self._cancel_task_interaction(player, "stale", now, notify=False)
            return "_That repair is no longer available._"
        self._closed_task_prompts[active["interaction_ref"]] = "completed"
        return "✅ _Transmission restored. Communications repaired._"

    def _repair_sabotage(self, name, actor=None, now=None):
        at = time.time() if now is None else float(now)
        sabotage = self._get_sabotage(name)
        activated_at = sabotage["activated_at"]
        if not sabotage.repair(at):
            return False
        self._record_event(
            "sabotage_repaired",
            at=at,
            actor=getattr(actor, "color", None),
            sabotage=name,
        )
        for player in self.players.values():
            active = player.task_in_progress
            if (
                active
                and active.get("kind") == "sabotage_repair"
                and active.get("sabotage") == name
            ):
                self._cancel_task_interaction(
                    player, "repaired", at, notify=False
                )
        shown = self.SABOTAGE_DISPLAY_NAMES.get(name, name.title())
        self._sabotage_event(
            f"✅ *{shown} sabotage repaired.* The ship is safe for now."
        )
        if name == "communications":
            self._sync_comms_restriction(at)
            self._comms_inactivity_report(activated_at, at)
        return True

    def _fail_sabotage(self, name, now=None):
        at = time.time() if now is None else float(now)
        sabotage = self._get_sabotage(name)
        if not sabotage.fail(at):
            return False
        self._record_event(
            "sabotage_failed",
            at=at,
            sabotage=name,
        )
        self._finish(SABOTAGE_FAILURE_TEXT.get(
            name,
            f"💥 *{name.title()} sabotage failed.*\n"
            "The crew ran out of time.\n*Impostors win!*",
        ), "impostors")
        return True

    def _start_sabotage_repair_interaction(
        self,
        player,
        name,
        prompt,
        expected,
        now=None,
        metadata=None,
        answer_hint="your answer",
        answer_format="<your answer>",
    ):
        """Use the shared one-minute task-interaction slot for sabotage repair."""
        at = time.time() if now is None else float(now)
        sabotage = self._get_sabotage(name)
        if sabotage["state"] != "active":
            return "⚠️ _That sabotage is no longer active._"
        if self._meeting:
            return "⚠️ _Repairs can't be started during a meeting._"
        if player.alive and (
            not player.settled or player.path or player.in_vent_until is not None
        ):
            return "⚠️ _Finish moving before starting a repair._"
        if player.task_in_progress:
            return "⚠️ _You already have an active interaction. Use `.task next` to switch._"

        self._interaction_sequence = getattr(self, "_interaction_sequence", 0) + 1
        interaction_ref = f"I{self._interaction_sequence:04d}"
        active = {
            "kind": "sabotage_repair",
            "sabotage": name,
            "task_id": None,
            "interaction_ref": interaction_ref,
            "expected": str(expected),
            "metadata": metadata or {},
            "started_at": at,
            "last_activity_at": at,
            "expires_at": at + C.TASK_INTERACTION_TIMEOUT_SECONDS,
        }
        player.task_in_progress = active
        sabotage["repair_interactions"][player.jid] = interaction_ref
        self._end_follow(player, "still", at)
        self._record_event(
            "sabotage_repair_started",
            at=at,
            actor=player.color,
            sabotage=name,
            interaction_ref=interaction_ref,
        )
        return (
            f"🧩 *{name.title()} repair*\n{prompt}\n\n"
            f"Reply to this message with {answer_hint}, or use "
            f"*.task answer {answer_format}*.\n"
            f"_This interaction expires after "
            f"{C.TASK_INTERACTION_TIMEOUT_SECONDS}s without activity._\n"
            f"[Task Ref: {interaction_ref}]"
        )

    ROLE_NAMES = {
        "impostor": "Impostor",
        "scientist": "Scientist",
        "crewmate": "Crewmate",
    }

    def _finish(self, headline, winner="impostors"):
        """End the match with one announcement (result plus the Impostor
        reveal), then a personal result DM to every player still in the game."""
        impostors = [p.color for p in self.players.values() if p.role == "impostor"]
        reveal = (
            "🔪 The Impostor" + ("s were " if len(impostors) != 1 else " was ")
            + ", ".join(f"*{name}*" for name in impostors) + "."
        )
        self._end_game(f"{headline}\n\n{reveal}")
        self._send_result_dms(winner)

    def _send_result_dms(self, winner):
        crew_won = winner == "crewmates"
        outcome = "Crewmates win!" if crew_won else "Impostors win!"
        for player in self.players.values():
            if getattr(player, "departed", False):
                continue
            won = (player.role != "impostor") == crew_won
            team = "Impostors" if player.role == "impostor" else "Crewmates"
            role_text = self.ROLE_NAMES.get(player.role, "Crewmate")
            text = (
                f"🏁 *Match over — {outcome}*\n"
                f"Your role: *{role_text}* ({team}).\n"
                + ("🏆 *Your team won.*" if won else "💀 *Your team lost.*")
            )
            jid = player.jid
            self._deliver(lambda jid=jid, text=text: self.manager._push_dm(jid, text))

    def _resolve_win_check(self, at=None):
        """Check for a winner at world time ``at`` (None = no timestamp known).

        Simultaneous endings (Session 06F/09): the earliest timestamp wins and
        an exact tie goes to the Impostors. A sabotage whose deadline is at or
        before ``at`` has therefore already ended the match before any other
        ending stamped ``at`` can count, and Impostor endings are tested before
        Crewmate task completion.
        """
        if self.over:
            return
        if at is not None:
            self._resolve_due_sabotage_deadlines(at, inclusive=True)
            if self.over:
                return
        active = [
            p for p in self.players.values()
            if not getattr(p, "departed", False)
        ]
        alive = [p for p in active if p.alive]
        alive_imp    = [p for p in alive if p.role == "impostor"]
        alive_crew   = [p for p in alive if p.role != "impostor"]
        team_tasks = getattr(self, "_team_tasks", [])
        tasks_done = bool(team_tasks) and all(task.get("done") for task in team_tasks)

        if not active:
            self._end_game("🏁 _The match ended: everyone left the game._")
        elif not alive_imp:
            any_ejected = any(
                p.role == "impostor" and p.death_reason == "ejected"
                for p in self.players.values()
            )
            self._finish(
                "🎉 *Crewmates win!*\nEvery Impostor has been ejected."
                if any_ejected else
                "🎉 *Crewmates win!*\nThe last Impostor left the game.",
                "crewmates",
            )
        elif len(alive_imp) >= len(alive_crew):
            # Checked before task completion: an exact tie goes to Impostors.
            self._finish(
                "🔪 *Impostors win!*\nThey equal or outnumber the crew.", "impostors"
            )
        elif tasks_done:
            self._finish(
                "🎉 *Crewmates win!*\nAll team tasks are complete.", "crewmates"
            )
