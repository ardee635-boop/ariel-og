"""O₂ and Reactor sabotages (Session 7, Part 7C).

Both need two living players at two station rooms to send ``scan`` within
PAIRED_SCAN_WINDOW_SECONDS of each other before a deadline.

PairedSabotage sits on the Part 7A Sabotage base, so cooldowns, the 20s/10s
warnings, meeting pause/resume, failure and game-end cleanup are the shared
framework's. This module adds only the station slots, the scan window and
the repair/failure hand-off into the game. Glue entry points are at the
bottom; see SESSION_7C_HANDOFF.md.

All times are the bot's own receive time in seconds. Callers pass ``now``.
Everything here runs under the game lock (command handler, tick, timer).
"""

import random

from . import amongus_config as C
from . import amongus_map as M
from .amongus_sabotage import Sabotage

OXYGEN = "oxygen"
REACTOR = "reactor"
PAIRED_NAMES = (OXYGEN, REACTOR)
LABELS = {OXYGEN: "O₂", REACTOR: "Reactor"}
ALIASES = {"oxygen": OXYGEN, "o2": OXYGEN, "o₂": OXYGEN, "reactor": REACTOR}


def _display(room):
    return room.replace("_", " ").title()


class PairedScan:
    """Two station slots and the scan window. Pure logic, no game access."""

    def __init__(self, stations, window):
        self.stations = tuple(stations)
        self.window = float(window)
        self.occupants = {room: None for room in self.stations}
        self.scans = {}

    def station_of(self, jid):
        for room, occupant in self.occupants.items():
            if occupant == jid:
                return room
        return None

    def both_present(self):
        return all(self.occupants.values())

    def join(self, room, jid):
        occupant = self.occupants[room]
        if occupant == jid:
            return "already"
        if occupant is not None:
            return "taken"
        self.occupants[room] = jid
        return "joined"

    def leave(self, jid):
        """Free the player's station and cancel the pair's scan attempt."""
        room = self.station_of(jid)
        if room is None:
            return None
        self.occupants[room] = None
        self.scans.clear()
        return room

    def expire(self, now, margin=0.0):
        """Drop a lone scan whose window has closed. True if one was dropped."""
        if self.scans and float(now) - min(self.scans.values()) > self.window + margin:
            self.scans.clear()
            return True
        return False

    def scan(self, jid, at):
        room = self.station_of(jid)
        if room is None:
            return {"kind": "no_station", "missed": False}
        if not self.both_present():
            return {"kind": "waiting", "missed": False}
        missed = False
        for other_room, scanned_at in tuple(self.scans.items()):
            if abs(float(at) - scanned_at) > self.window:
                del self.scans[other_room]
                missed = True
        if room in self.scans:
            return {"kind": "duplicate", "missed": missed}
        self.scans[room] = float(at)
        if len(self.scans) == len(self.stations):
            times = dict(self.scans)
            self.scans.clear()
            return {"kind": "success", "missed": False, "times": times}
        return {"kind": "first", "missed": missed}


class PairedSabotage(Sabotage):
    """O₂ or Reactor: a 7A Sabotage with a deadline and a paired scan."""

    def __init__(self, name, cooldown_seconds, game=None, rng=None):
        super().__init__(name, cooldown_seconds)
        self.game = game
        self.label = LABELS[name]
        self.rng = rng or random
        self.pair = None
        self.countdown_token = None   # set while a `.ready` countdown runs

    # ── Lifecycle ──────────────────────────────────────────
    @property
    def active(self):
        return self["state"] == "active"

    @property
    def deadline(self):
        return self["deadline"]

    @property
    def paused(self):
        return self.get("paused_remaining") is not None

    def stations(self):
        return M.get_station_rooms(self["name"], self.game.map_id)

    def activate(self, now, deadline=None):
        if deadline is None:
            low, high = C.SABOTAGE_DEADLINE_RANGE_SECONDS
            deadline = float(now) + self.rng.uniform(low, high)
        if not super().activate(now, deadline=deadline):
            return False
        self.pair = PairedScan(self.stations(), C.PAIRED_SCAN_WINDOW_SECONDS)
        return True

    def activation_note(self):
        first, second = (_display(room) for room in self.stations())
        return (
            f"Two crew must reach *{first}* and *{second}* and send "
            "*scan* together before time runs out."
        )

    def repair(self, now):
        result = super().repair(now)
        if result:
            self.pair = None
            self.countdown_token = None
        return result

    def fail(self, now):
        result = super().fail(now)
        if result:
            self.pair = None
            self.countdown_token = None
        return result

    def cancel(self):
        result = super().cancel()
        self.pair = None
        self.countdown_token = None
        return result

    # ── Helpers ────────────────────────────────────────────
    def _event(self, event_type, at, **details):
        self.game._record_event(
            event_type, at=float(at), sabotage=self["name"], **details
        )

    def _dm(self, jid, message):
        self.game.manager._push_dm(jid, message)

    def _eligible_here(self, player, room):
        return bool(
            player
            and player.alive
            and not player.departed
            and player.room == room
            and player.settled
            and not player.path
            and player.in_vent_until is None
            and not player.task_in_progress
        )

    def _paused_now(self):
        return bool(getattr(self.game, "_meeting", None)) or self.paused

    # ── Station membership ─────────────────────────────────
    def reconcile(self, now):
        """Vacate any station whose occupant moved, died, vented or left."""
        if not self.active or self.pair is None:
            return
        for room, jid in tuple(self.pair.occupants.items()):
            if jid and not self._eligible_here(self.game.players.get(jid), room):
                self.vacate(jid, "left", now)

    def vacate(self, jid, reason, now):
        """Free a player's station and cancel the pair's current attempt."""
        if not self.active or self.pair is None:
            return False
        room = self.pair.leave(jid)
        if room is None:
            return False
        self.countdown_token = None
        player = self.game.players.get(jid)
        self._event(
            "paired_attempt_cancelled",
            now,
            actor=player.color if player else "unknown",
            room=room,
            reason=reason,
        )
        if player and player.alive and not player.departed:
            self._dm(
                jid,
                f"↩️ You left the *{_display(room)}* station. "
                "Your scan attempt was cancelled.",
            )
        for partner in self.pair.occupants.values():
            if partner:
                self._dm(partner, "Your partner left. Waiting for partner.")
        return True

    def join(self, player, now):
        """Take a station in the player's current room. Returns a reply."""
        if self.game.over:
            return None
        if not self.active:
            return "⚠️ _Nothing to repair here._"
        if self._paused_now():
            return "⏸️ _Sabotage repairs are paused during the meeting._"
        if not player.alive or player.departed:
            return "⚠️ _Only living players can repair this._"
        if player.role == "impostor" and not C.PAIRED_SABOTAGE_IMPOSTORS_CAN_REPAIR:
            return "⚠️ _You can't repair sabotage._"
        self.reconcile(now)
        room = player.room
        if room not in self.pair.stations:
            first, second = (_display(r) for r in self.pair.stations)
            return f"⚠️ _{self.label} needs a crew member at {first} or {second}._"
        if player.task_in_progress:
            return (
                "You already have an active task in progress. Type "
                '".task next" to abandon your current task and begin your next task.'
            )
        if not self._eligible_here(player, room):
            return "⚠️ _Can't use a station while moving or inside a vent._"
        result = self.pair.join(room, player.jid)
        if result == "taken":
            return f"⚠️ _Someone is already at the {_display(room)} station._"
        if result == "joined":
            end_follow = getattr(self.game, "_end_follow", None)
            if callable(end_follow):
                end_follow(player, "still", now)
            self._event("paired_station_joined", now, actor=player.color, room=room)
        if not self.pair.both_present():
            return "Waiting for partner."
        ready = self.ready_text()
        for partner_jid in self.pair.occupants.values():
            if partner_jid != player.jid:
                self._dm(partner_jid, ready)
        return ready

    def ready_text(self):
        """Message both seated players get once both stations are ready."""
        window = f"{C.PAIRED_SCAN_WINDOW_SECONDS:g}"
        if self["name"] == OXYGEN:
            return (
                "✅ Both stations are ready!\n\n"
                f"Both players must reply scan to the bot message within {window} "
                "seconds of each other to fix oxygen.\n\n"
                "Send .ready to begin the repair countdown."
            )
        return (
            "✅ Both stations are ready!\n\n"
            f"Both players must reply *scan* to a bot message within {window} "
            "seconds of each other to fix the reactor."
        )

    # ── Optional O₂ countdown ──────────────────────────────
    def ready(self, player, now):
        """`.ready`: send 3, 2, 1, SCAN NOW! to both seated players (O₂ only)."""
        if self.game.over:
            return None
        if self["name"] != OXYGEN:
            return "⚠️ _There is no countdown for this repair. Reply *scan* to a bot message._"
        if not self.active:
            return "⚠️ _Nothing to repair here._"
        if self._paused_now():
            return "⏸️ _Sabotage repairs are paused during the meeting._"
        self.reconcile(now)
        if self.pair is None or self.pair.station_of(player.jid) is None:
            return "⚠️ _You need to be at an oxygen station to start the countdown._"
        if not self.pair.both_present():
            return "Waiting for partner."
        if self.countdown_token is not None:
            return "⏳ _The countdown is already running._"
        token = object()
        self.countdown_token = token
        steps = ("3", "2", "1", "SCAN NOW!")
        self._event("paired_countdown_started", now, actor=player.color)

        def send(index):
            def run():
                if (
                    self.countdown_token is not token
                    or not self.active
                    or self.pair is None
                    or not self.pair.both_present()
                    or self._paused_now()
                ):
                    if self.countdown_token is token:
                        self.countdown_token = None
                    return
                for jid in self.pair.occupants.values():
                    if jid:
                        self._dm(jid, steps[index])
                if index == len(steps) - 1:
                    self.countdown_token = None
            return run

        send(0)()
        for index in range(1, len(steps)):
            self.game._schedule(
                index * C.READY_COUNTDOWN_STEP_SECONDS, send(index)
            )
        return None

    # ── Scanning ───────────────────────────────────────────
    def scan(self, player, now):
        now = float(now)
        if self.game.over:
            return None
        if not self.active:
            return "⚠️ _Nothing to scan._"
        if self._paused_now():
            return "⏸️ _Sabotage repairs are paused during the meeting._"
        deadline = self.deadline
        # Confirmed (06C/06D): both scans must land strictly before the
        # deadline; a scan stamped at the deadline is too late.
        if deadline is not None and now >= deadline:
            self.game._fail_sabotage(self["name"], deadline)
            return None
        self.reconcile(now)
        outcome = self.pair.scan(player.jid, now)
        kind = outcome["kind"]
        if outcome["missed"]:
            for jid in self.pair.occupants.values():
                if jid:
                    self._dm(jid, "⌛ Scan window missed. Send *scan* again together when both stations are ready.")
        if kind == "no_station":
            first, second = (_display(room) for room in self.pair.stations)
            return f"⚠️ _You're not at a repair station ({first} or {second})._"
        if kind == "waiting":
            return "Waiting for partner."
        if kind == "duplicate":
            return "📡 _Scan already sent. Waiting for your partner's scan._"
        if kind == "first":
            return "📡 _Scan sent. Waiting for your partner's scan..._"
        occupants = [jid for jid in self.pair.occupants.values() if jid]
        self._event("paired_scan_accepted", now, scans=outcome["times"])
        if self.game._repair_sabotage(self["name"], player, now):
            for jid in occupants:
                self._dm(jid, f"✅ Paired scan accepted. *{self.label}* is repaired.")
        return None

    # ── Time ───────────────────────────────────────────────
    def tick(self, now):
        """World-clock step: station reconciliation and lone-scan expiry.

        Deadlines and the 20s/10s warnings belong to the shared 7A tick.
        """
        if self.game.over or not self.active or self._paused_now():
            return
        now = float(now)
        self.reconcile(now)
        if self.pair is not None and self.pair.expire(
            now, C.PAIRED_SCAN_EXPIRY_MARGIN_SECONDS
        ):
            for jid in self.pair.occupants.values():
                if jid:
                    self._dm(jid, "⌛ Scan window missed. Send *scan* again together when both stations are ready.")


# ── Glue entry points (called from amongus_game.py) ────────
def is_scan_text(text):
    return (text or "").strip().lower() in {"scan", ".scan"}


def _active_paired(game):
    return [
        state for state in game._ensure_sabotage_registry().values()
        if isinstance(state, PairedSabotage) and state.active
    ]


def join_station(game, player, now):
    """`.task` in a station room during an active paired sabotage.

    Returns (handled, reply); (False, None) means fall through to the
    normal task flow.
    """
    for sabotage in _active_paired(game):
        if player.room in sabotage.pair.stations:
            return True, sabotage.join(player, now)
    return False, None


def player_at_station(game, player):
    return any(
        sabotage.pair is not None and sabotage.pair.station_of(player.jid)
        for sabotage in _active_paired(game)
    )


def is_ready_text(text):
    return (text or "").strip().lower() == ".ready"


def handle_ready(game, player, text, now):
    """`.ready`: optional O₂ countdown. Returns (handled, reply)."""
    if not is_ready_text(text):
        return False, None
    active = _active_paired(game)
    if not active:
        return False, None
    for sabotage in active:
        if sabotage.pair.station_of(player.jid):
            return True, sabotage.ready(player, now)
    oxygen = [s for s in active if s["name"] == OXYGEN]
    return True, (oxygen or active)[0].ready(player, now)


NOT_A_REPLY = (
    "⚠️ _Scan only counts as a reply. Reply *scan* to any bot message "
    "while both stations are ready._"
)


def handle_scan(game, player, text, now, quoted_text=None):
    """`scan` sent as a reply to a bot message. Returns (handled, reply).

    Confirmed (06D): a plain `scan` that is not a reply to a bot message is
    not accepted. The bridge only passes ``quoted_text`` when the quoted
    message came from the bot, so a non-empty value means "reply to the bot".
    """
    if not is_scan_text(text):
        return False, None
    active = _active_paired(game)
    if not active:
        return False, None
    if not quoted_text:
        return True, NOT_A_REPLY
    for sabotage in active:
        if sabotage.pair.station_of(player.jid):
            return True, sabotage.scan(player, now)
    return True, active[0].scan(player, now)


def tick_all(game, now):
    for sabotage in _active_paired(game):
        sabotage.tick(now)
        if game.over:
            return


def vacate_player(game, jid, reason, now):
    """Immediate hook for departure, death or movement."""
    for sabotage in _active_paired(game):
        sabotage.vacate(jid, reason, now)
