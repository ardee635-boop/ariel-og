"""Session 7D: integration scenarios for all four sabotages.

Scripted timelines on the fake clock (every command carries its own receive
time), plus one run on the real world-clock thread. Uses realistic WhatsApp
JIDs so the "no real identity in any group message" check means something.
"""
import sys as _s, pathlib as _p
_s.path.insert(0, str(_p.Path(__file__).resolve().parent))
import amongus_testlinks  # noqa: E402,F401


import itertools
import re
import sys
import threading
import time
import types
import unittest
from pathlib import Path
from unittest import mock


BOT_ROOT = Path(__file__).resolve().parents[1]
ENGINE_DIR = BOT_ROOT / "engine"
ROUTER_DIR = ENGINE_DIR / "router"
sys.path[:0] = [str(ENGINE_DIR), str(ENGINE_DIR / "pokemon"), str(ENGINE_DIR / "core")]

router_package = types.ModuleType("router")
router_package.__path__ = [str(ROUTER_DIR)]
sys.modules.setdefault("router", router_package)

from router import amongus_config as C  # noqa: E402
from router import amongus_puzzles as PZ  # noqa: E402
from router.amongus_game import Game, PlayerState  # noqa: E402
from router.amongus_map import get_map, get_station_rooms  # noqa: E402
from router.amongus_movement import MovementEngine  # noqa: E402


GAME_GROUP = "120363000000000001@g.us"

# colour -> role. Two impostors so one can watch the other.
ROLES = {
    "Red": "crewmate",
    "Blue": "crewmate",
    "Yellow": "crewmate",
    "White": "crewmate",
    "Cyan": "crewmate",
    "Lime": "crewmate",
    "Green": "scientist",
    "Pink": "impostor",
    "Black": "impostor",
}
JID = {
    color: f"23480000{index:04d}@s.whatsapp.net"
    for index, color in enumerate(ROLES, start=1)
}
JID_PATTERN = re.compile(r"\d{8,}@(s\.whatsapp\.net|lid|g\.us)")


class FakeManager:
    def __init__(self):
        self.sent = []
        self.broadcasts = []
        self.locks = []

    def _push_dm(self, player, message, **kwargs):
        self.sent.append((player, message))

    def _broadcast(self, message, **kwargs):
        self.broadcasts.append(message)

    def _set_comms_restriction(self, locked, group_jid=None):
        self.locks.append((locked, group_jid))
        return True


class FixedRng:
    def __init__(self, value):
        self.value = value

    def uniform(self, low, high):
        return self.value


def make_game(oxygen_seconds=35, reactor_seconds=35):
    game = Game.__new__(Game)
    game.manager = FakeManager()
    game.group_jid = GAME_GROUP
    game.map = get_map()
    game.map_id = game.map.id
    game.events = []
    game.players = {}
    game._bodies = {}
    game._corpses = {}
    game._reported_crime_scenes = []
    game._sabotages = {}
    game._ensure_sabotage_registry()
    game._team_tasks = []
    game._task_sequence = 0
    game._interaction_sequence = 0
    game._closed_task_prompts = {}
    game.over = False
    game.tick_count = 0
    game.lock = threading.RLock()
    game._stop_event = threading.Event()
    game._timers = set()
    game._meeting = None
    for color, role in ROLES.items():
        player = PlayerState(JID[color], role, color, game.map)
        player.room_entered_at = 0.0
        player.stopped_since = 0.0
        player.room = "CAFETERIA"
        player.reference_room = "CAFETERIA"
        player.tasks = []
        game.players[player.jid] = player
    game.color_to_jid = {p.color.lower(): p.jid for p in game.players.values()}
    game.movement = MovementEngine(game)
    game._sabotages["oxygen"].rng = FixedRng(oxygen_seconds)
    game._sabotages["reactor"].rng = FixedRng(reactor_seconds)
    return game


BOT_MESSAGE = "(a bot message)"


def cmd(game, color, text, at):
    # Session 09 pkg 3: `scan` only counts as a reply to a bot message.
    quoted = BOT_MESSAGE if text.strip().lower() in ("scan", ".scan") else None
    return game.handle(
        JID[color], text, received_at_ms=round(at * 1000), quoted_text=quoted
    )


def player(game, color):
    return game.players[JID[color]]


def put(game, color, room):
    p = player(game, color)
    p.room = room
    p.reference_room = room
    p.stopped_since = p.stopped_since if p.stopped_since is not None else 0.0


def state(game, name):
    return game._sabotages[name]["state"]


def dms(game, color):
    return [text for who, text in game.manager.sent if who == JID[color]]


def sabotage(game, name, at, color="Pink"):
    return game._cmd_sabotage(player(game, color), name, at)


def repair_lights(game, color, at):
    """Solve Lights through the real `.task` flow."""
    ring = PZ.get_pattern("ring")
    start = PZ.apply_switch(PZ.solved_state(ring), ring, 0)
    put(game, color, "ELECTRICAL")
    with mock.patch.object(PZ, "pick_pattern", return_value=ring), \
            mock.patch.object(PZ, "scramble", return_value=start):
        cmd(game, color, ".task", at)
    return cmd(game, color, ".task answer 1", at + 1)


def repair_comms(game, color, at):
    """Solve Communications through the real `.task` flow."""
    put(game, color, "COMMUNICATIONS")
    cmd(game, color, ".task", at)
    active = player(game, color).task_in_progress
    phrase = PZ.get_phrase(active["metadata"]["phrase_id"]).text
    return cmd(game, color, f".task answer {phrase}", at + 1)


def seat_pair(game, name, first, second, at):
    a, b = get_station_rooms(name)
    put(game, first, a)
    put(game, second, b)
    r1 = cmd(game, first, ".task", at)
    r2 = cmd(game, second, ".task", at + 0.1)
    return r1, r2


def scan_pair(game, first, second, at):
    cmd(game, first, "scan", at)
    return cmd(game, second, "scan", at + 0.5)


def repair_paired(game, name, first, second, at):
    seat_pair(game, name, first, second, at)
    return scan_pair(game, first, second, at + 1)


def repair_any(game, name, at):
    """Repair `name` with its own dedicated crew (so repairs never overlap)."""
    if name == "lights":
        return repair_lights(game, "Green", at)
    if name == "communications":
        return repair_comms(game, "Cyan", at)
    if name == "oxygen":
        return repair_paired(game, "oxygen", "Red", "Blue", at)
    return repair_paired(game, "reactor", "Yellow", "White", at)


def all_four_active(game, at=100.0):
    for name in ("lights", "communications", "oxygen", "reactor"):
        sabotage(game, name, at)
    for name in ("lights", "communications", "oxygen", "reactor"):
        assert state(game, name) == "active", name


def group_text(game):
    return "\n".join(game.manager.broadcasts)


class SabotageIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.game = make_game()

    def tearDown(self):
        self.game.close()

    # 1. All four active; repair in a different order each run -----------
    def test_all_four_repair_in_every_order_each_repair_affects_only_itself(self):
        names = ["lights", "communications", "oxygen", "reactor"]
        for order in itertools.permutations(names):
            game = make_game()
            try:
                all_four_active(game, 100.0)
                remaining = set(names)
                at = 102.0
                for name in order:
                    before = {n: game._sabotages[n]["deadline"] for n in remaining}
                    repair_any(game, name, at)
                    at += 4.0
                    remaining.discard(name)
                    self.assertEqual(state(game, name), "repaired", (order, name))
                    for other in remaining:
                        self.assertEqual(state(game, other), "active", (order, name, other))
                        self.assertEqual(game._sabotages[other]["deadline"], before[other])
                self.assertFalse(game.over, order)
                self.assertEqual(
                    sum(e["type"] == "sabotage_repaired" for e in game.events), 4
                )
            finally:
                game.close()

    # 2. Lights during a kill --------------------------------------------
    def test_lights_during_a_kill_masks_witnesses_not_impostors_status_is_real(self):
        game = self.game
        for color in ("Red", "Blue", "Black"):
            put(game, color, "MEDBAY")
        put(game, "Pink", "CAFETERIA")
        sabotage(game, "lights", 100.0)

        cmd(game, "Pink", ".m medbay", 101.0)
        game.movement.advance_all(130.0)
        self.assertEqual(player(game, "Pink").room, "MEDBAY")

        crew_view = " ".join(dms(game, "Blue"))
        self.assertIn("Someone", crew_view)
        self.assertNotIn("Pink", crew_view)
        imp_view = " ".join(dms(game, "Black"))
        self.assertIn("Pink", imp_view)
        self.assertNotIn("Someone", imp_view)

        cmd(game, "Pink", ".kill red", 131.0)
        game.movement.advance_all(140.0)
        game._advance_sabotages(140.0)
        if player(game, "Red").alive:
            game._resolve_kill(player(game, "Pink"), player(game, "Red"), now=140.0)
        self.assertFalse(player(game, "Red").alive)

        status = cmd(game, "Blue", ".status", 141.0)
        self.assertIn("Pink", status)
        self.assertIn("Black", status)
        self.assertIn("Red", status)  # the body
        # No killer name leaks into the witness's distress notice.
        self.assertIn("distress", " ".join(dms(game, "Blue")))
        self.assertNotIn("killed by", " ".join(dms(game, "Blue")))

    # 3. Communications during a kill, report, meeting ----------------------
    def test_communications_during_kill_and_report_meeting_works_report_follows(self):
        game = self.game
        for color in ("Red", "Blue"):
            put(game, color, "MEDBAY")
        put(game, "Pink", "MEDBAY")
        put(game, "Green", "STORAGE")
        player(game, "Green").stopped_since = 0.0
        sabotage(game, "communications", 100.0)
        self.assertEqual(game.manager.locks[-1], (True, GAME_GROUP))

        game._resolve_kill(player(game, "Pink"), player(game, "Red"), now=105.0)
        game._advance_sabotages(106.0)
        self.assertFalse(player(game, "Red").alive)
        self.assertTrue(any("distress" in t for t in dms(game, "Blue")))
        self.assertFalse(any("arrived" in t for t in dms(game, "Blue")))

        cmd(game, "Blue", ".status", 107.0)
        cmd(game, "Blue", ".report", 108.0)
        self.assertIsNotNone(game._meeting)
        self.assertEqual(game.manager.locks[-1], (False, GAME_GROUP))  # discussion

        game._resolve_meeting(now=170.0)
        self.assertEqual(state(game, "communications"), "active")
        self.assertEqual(game.manager.locks[-1], (True, GAME_GROUP))  # re-locked
        self.assertEqual(
            [m for m in game.manager.broadcasts if "activity report" in m], []
        )

        repair_comms(game, "Cyan", 200.0)
        reports = [m for m in game.manager.broadcasts if "activity report" in m]
        self.assertEqual(len(reports), 1)
        self.assertIn("not proof of guilt", reports[0])
        self.assertEqual(game.manager.locks[-1], (False, GAME_GROUP))

    # 4. O2 and Reactor with one pair ------------------------------------------
    def test_one_pair_cannot_cover_both_stations_reactor_fails_if_nobody_else(self):
        game = make_game(oxygen_seconds=35, reactor_seconds=40)
        sabotage(game, "oxygen", 100.0)
        sabotage(game, "reactor", 100.0)
        repair_paired(game, "oxygen", "Red", "Blue", 101.0)
        self.assertEqual(state(game, "oxygen"), "repaired")
        self.assertEqual(state(game, "reactor"), "active")
        # Red and Blue are still at the O2 stations; nobody is at the reactor.
        self.assertIsNone(
            game._sabotages["reactor"].pair.station_of(JID["Red"])
        )
        cmd(game, "Red", "scan", 120.0)
        cmd(game, "Blue", "scan", 120.5)
        self.assertEqual(state(game, "reactor"), "active")
        game._advance_sabotages(140.01)
        self.assertEqual(state(game, "reactor"), "failed")
        self.assertTrue(game.over)
        game.close()

    def test_one_pair_leaving_one_station_for_the_other_cancels_and_a_second_pair_hands_over(self):
        game = make_game(oxygen_seconds=35, reactor_seconds=40)
        sabotage(game, "oxygen", 100.0)
        sabotage(game, "reactor", 100.0)
        seat_pair(game, "oxygen", "Red", "Blue", 101.0)
        cmd(game, "Red", "scan", 105.0)
        # Red walks off towards the reactor: the O2 attempt is cancelled.
        cmd(game, "Red", ".m upper engine", 105.5)
        game._advance_sabotages(106.0)
        o2 = game._sabotages["oxygen"]
        self.assertEqual(o2.pair.scans, {})
        self.assertIsNone(o2.pair.station_of(JID["Red"]))
        self.assertIn("Waiting for partner", dms(game, "Blue")[-1])
        # A second pair takes the reactor; a third player takes Red's O2 seat.
        repair_paired(game, "reactor", "Yellow", "White", 108.0)
        self.assertEqual(state(game, "reactor"), "repaired")
        a, _ = get_station_rooms("oxygen")
        put(game, "Lime", a)
        cmd(game, "Lime", ".task", 112.0)
        cmd(game, "Lime", "scan", 113.0)
        cmd(game, "Blue", "scan", 113.5)
        self.assertEqual(state(game, "oxygen"), "repaired")
        self.assertFalse(game.over)
        game.close()

    # 5. Meeting during timed sabotage ---------------------------------------------
    def test_meeting_pauses_timed_deadlines_cooldowns_keep_running(self):
        game = self.game
        all_four_active(game, 100.0)
        cooldowns = {n: game._sabotages[n]["cooldown_until"] for n in game._sabotages}
        o2_deadline = game._sabotages["oxygen"]["deadline"]
        cmd(game, "Red", ".meeting", 110.0)
        self.assertIsNotNone(game._meeting)
        game._advance_sabotages(500.0)
        self.assertEqual(state(game, "oxygen"), "active")
        self.assertEqual(state(game, "reactor"), "active")
        self.assertFalse(game.over)
        game._resolve_meeting(now=170.0)
        self.assertAlmostEqual(game._sabotages["oxygen"]["deadline"], 170.0 + (o2_deadline - 110.0))
        for name, until in cooldowns.items():
            self.assertEqual(game._sabotages[name]["cooldown_until"], until)
        # The paused 20s/10s warnings still fire once after the resume.
        game._advance_sabotages(170.0 + (o2_deadline - 110.0) - 9.0)
        self.assertEqual(
            sum("O₂: 10s remaining" in m for m in game.manager.broadcasts), 1
        )
        # Cooldown display for an impostor lists all four.
        text = cmd(game, "Pink", ".cooldown", 171.0)
        for label in ("Lights", "Communications", "Oxygen", "Reactor"):
            self.assertIn(f"{label} sabotage", text)

    # 6. Near-simultaneous scans at the deadline ----------------------------------------
    def test_scans_one_tick_before_same_tick_and_one_tick_after_the_deadline(self):
        for offset, outcome in ((-0.001, "repaired"), (0.0, "failed"), (0.001, "failed")):  # strict-before (pkg 3)
            game = make_game()
            try:
                sabotage(game, "oxygen", 100.0)
                deadline = game._sabotages["oxygen"]["deadline"]
                seat_pair(game, "oxygen", "Red", "Blue", 101.0)
                cmd(game, "Red", "scan", deadline - 1.0)
                cmd(game, "Blue", "scan", deadline + offset)
                self.assertEqual(state(game, "oxygen"), outcome, offset)
                self.assertEqual(game.over, outcome == "failed", offset)
            finally:
                game.close()

    def test_world_tick_exactly_at_the_deadline_does_not_fail_it(self):
        game = self.game
        sabotage(game, "oxygen", 100.0)
        deadline = game._sabotages["oxygen"]["deadline"]
        game._advance_sabotages(deadline)
        self.assertEqual(state(game, "oxygen"), "active")
        game._advance_sabotages(deadline + 0.001)
        self.assertEqual(state(game, "oxygen"), "failed")

    # 7. Player leaves or dies mid-repair, each type ----------------------------------------
    def test_death_and_departure_mid_repair_for_every_sabotage_type(self):
        for how in ("dies", "leaves"):
            game = make_game()
            try:
                all_four_active(game, 100.0)
                # Lights and Communications: private interactions.
                ring = PZ.get_pattern("ring")
                start = PZ.apply_switch(PZ.solved_state(ring), ring, 0)
                put(game, "Green", "ELECTRICAL")
                with mock.patch.object(PZ, "pick_pattern", return_value=ring), \
                        mock.patch.object(PZ, "scramble", return_value=start):
                    cmd(game, "Green", ".task", 101.0)
                put(game, "Cyan", "COMMUNICATIONS")
                cmd(game, "Cyan", ".task", 101.0)
                seat_pair(game, "oxygen", "Red", "Blue", 101.0)
                seat_pair(game, "reactor", "Yellow", "White", 101.0)
                victims = ("Green", "Cyan", "Red", "Yellow")
                for color in victims:
                    self.assertTrue(
                        player(game, color).task_in_progress
                        or any(color_jid == JID[color]
                               for s in ("oxygen", "reactor")
                               for color_jid in game._sabotages[s].pair.occupants.values())
                    )
                for color in victims:
                    if how == "dies":
                        player(game, color).alive = False
                        if player(game, color).task_in_progress:
                            game._cancel_task_interaction(player(game, color), "death", 102.0)
                    else:
                        game.mark_departed(JID[color], 102.0)
                game._advance_sabotages(103.0)
                for name in ("lights", "communications", "oxygen", "reactor"):
                    self.assertEqual(state(game, name), "active", (how, name))
                self.assertEqual(game._sabotages["lights"]["repair_interactions"], {})
                self.assertEqual(game._sabotages["communications"]["repair_interactions"], {})
                for name, gone in (("oxygen", "Red"), ("reactor", "Yellow")):
                    self.assertNotIn(
                        JID[gone], game._sabotages[name].pair.occupants.values(), (how, name)
                    )
                    self.assertEqual(game._sabotages[name].pair.scans, {})
                # Replacements can take over Lights while time remains.
                repair_lights(game, "Lime", 104.0)
                self.assertEqual(state(game, "lights"), "repaired")
            finally:
                game.close()

    def test_replacements_finish_paired_repairs_after_a_death_or_departure(self):
        game = make_game()
        all_four_active(game, 100.0)
        seat_pair(game, "oxygen", "Red", "Blue", 101.0)
        player(game, "Red").alive = False
        game._advance_sabotages(102.0)
        put(game, "Lime", get_station_rooms("oxygen")[0])
        cmd(game, "Lime", ".task", 103.0)
        scan_pair(game, "Lime", "Blue", 104.0)
        self.assertEqual(state(game, "oxygen"), "repaired")
        seat_pair(game, "reactor", "Yellow", "White", 105.0)
        game.mark_departed(JID["Yellow"], 106.0)
        put(game, "Cyan", get_station_rooms("reactor")[0])
        cmd(game, "Cyan", ".task", 107.0)
        scan_pair(game, "Cyan", "White", 108.0)
        self.assertEqual(state(game, "reactor"), "repaired")
        game.close()

    # 8. Game end with everything pending -------------------------------------------------------
    def _pending_everything(self, game):
        all_four_active(game, 100.0)
        ring = PZ.get_pattern("ring")
        start = PZ.apply_switch(PZ.solved_state(ring), ring, 0)
        put(game, "Green", "ELECTRICAL")
        with mock.patch.object(PZ, "pick_pattern", return_value=ring), \
                mock.patch.object(PZ, "scramble", return_value=start):
            cmd(game, "Green", ".task", 101.0)
        put(game, "Cyan", "COMMUNICATIONS")
        cmd(game, "Cyan", ".task", 101.0)
        seat_pair(game, "oxygen", "Red", "Blue", 101.0)
        cmd(game, "Red", "scan", 102.0)  # a pending half-scan
        seat_pair(game, "reactor", "Yellow", "White", 101.0)

    def assert_nothing_acts_afterwards(self, game):
        self.assertTrue(game.over)
        self.assertEqual(game._timers, set())
        for name in ("lights", "communications", "oxygen", "reactor"):
            self.assertNotEqual(state(game, name), "active", name)
            self.assertEqual(game._sabotages[name]["repair_interactions"], {})
        for p in game.players.values():
            self.assertIsNone(p.task_in_progress)
        for name in ("oxygen", "reactor"):
            self.assertIsNone(game._sabotages[name].pair)
        self.assertEqual(game.manager.locks[-1][0], False)
        broadcasts, sent, events = (
            len(game.manager.broadcasts), len(game.manager.sent), len(game.events)
        )
        game._advance_sabotages(10_000.0)
        for color in ROLES:
            cmd(game, color, "scan", 10_000.0)
            cmd(game, color, ".task", 10_001.0)
            cmd(game, color, ".sabotage lights", 10_002.0)
        self.assertEqual(len(game.manager.broadcasts), broadcasts)
        self.assertEqual(len(game.manager.sent), sent)
        self.assertEqual(len(game.events), events)

    def test_game_end_by_win_cancels_everything(self):
        game = make_game()
        self._pending_everything(game)
        for color in ("Red", "Blue", "Yellow", "White", "Cyan", "Lime"):
            player(game, color).alive = False
        game._resolve_win_check()
        self.assertIn("Impostors win", game.manager.broadcasts[-1])
        self.assert_nothing_acts_afterwards(game)

    def test_game_end_by_sabotage_failure_cancels_everything_else(self):
        game = make_game()
        self._pending_everything(game)
        game._advance_sabotages(game._sabotages["oxygen"]["deadline"] + 0.5)
        self.assertEqual(state(game, "oxygen"), "failed")
        self.assertIn("O₂ depleted — Impostors win", game.manager.broadcasts[-1])
        self.assert_nothing_acts_afterwards(game)

    def test_host_ending_the_game_cancels_everything(self):
        game = make_game()
        self._pending_everything(game)
        game._end_game("🛑 The host ended the game.")
        self.assert_nothing_acts_afterwards(game)

    # Sign-off checks -------------------------------------------------------------------------------
    def test_no_group_message_contains_a_real_whatsapp_identity(self):
        game = self.game
        all_four_active(game, 100.0)
        for color in ("Red", "Blue"):
            put(game, color, "MEDBAY")
        put(game, "Pink", "MEDBAY")
        game._resolve_kill(player(game, "Pink"), player(game, "Red"), now=105.0)
        repair_lights(game, "Green", 110.0)
        repair_comms(game, "Cyan", 115.0)
        repair_paired(game, "oxygen", "Blue", "Lime", 120.0)
        game._advance_sabotages(140.0)  # reactor fails
        self.assertTrue(game.over)
        self.assertTrue(game.manager.broadcasts)
        for message in game.manager.broadcasts:
            self.assertIsNone(JID_PATTERN.search(message), message)
            for color in ROLES:
                self.assertNotIn(JID[color].split("@")[0], message)

    def test_debug_repair_commands_are_gone(self):
        for attr in ("DEBUG_REPAIR_ENABLED", "DEBUG_COMMS_REPAIR_ENABLED"):
            self.assertFalse(hasattr(C, attr))
        source = (ROUTER_DIR / "amongus_game.py").read_text(encoding="utf-8")
        self.assertNotIn("debugrepair", source.lower())
        self.assertNotIn("debugcommsrepair", source.lower())
        self.assertNotIn("TEMP-DEBUG", source)
        self.assertNotIn(".meltdown", source.lower())

    def test_cooldown_commands_list_every_sabotage_cooldown(self):
        game = self.game
        sabotage(game, "lights", 100.0)
        for text in (cmd(game, "Pink", ".cooldown", 101.0), cmd(game, "Pink", ".cds", 101.0)):
            self.assertIn("Lights sabotage: 179s", text)
            self.assertIn("Communications sabotage: Ready", text)
            self.assertIn("Oxygen sabotage: Ready", text)
            self.assertIn("Reactor sabotage: Ready", text)
        self.assertNotIn("sabotage", cmd(game, "Red", ".cooldown", 101.0).lower())


class RealWorldClockTests(unittest.TestCase):
    """One run on the real tick thread (not the fake clock)."""

    def run_clock(self, game):
        thread = threading.Thread(target=game._run_world_clock, daemon=True)
        thread.start()
        return thread

    def test_deadline_fails_on_the_real_clock_with_no_command_needed(self):
        game = make_game(oxygen_seconds=1.2)
        try:
            thread = self.run_clock(game)
            sabotage(game, "oxygen", time.time())
            deadline = time.time() + 6
            while not game.over and time.time() < deadline:
                time.sleep(0.1)
            self.assertTrue(game.over)
            self.assertEqual(state(game, "oxygen"), "failed")
            thread.join(timeout=3)
            self.assertFalse(thread.is_alive())
        finally:
            game.close()

    def test_a_valid_pair_on_the_real_clock_repairs_and_the_deadline_never_fires(self):
        game = make_game(reactor_seconds=2.5)
        try:
            thread = self.run_clock(game)
            now = time.time()
            sabotage(game, "reactor", now)
            a, b = get_station_rooms("reactor")
            put(game, "Red", a)
            put(game, "Blue", b)
            game.handle(JID["Red"], ".task")
            game.handle(JID["Blue"], ".task")
            game.handle(JID["Red"], "scan", quoted_text=BOT_MESSAGE)
            game.handle(JID["Blue"], "scan", quoted_text=BOT_MESSAGE)
            self.assertEqual(state(game, "reactor"), "repaired")
            time.sleep(3.5)  # well past the old deadline, two or more ticks
            self.assertFalse(game.over)
            self.assertEqual(state(game, "reactor"), "repaired")
            game.close()
            thread.join(timeout=3)
            self.assertFalse(thread.is_alive())
        finally:
            game.close()


if __name__ == "__main__":
    unittest.main()
