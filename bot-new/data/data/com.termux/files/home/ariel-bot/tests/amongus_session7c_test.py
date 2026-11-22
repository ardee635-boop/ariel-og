import random
import sys
import threading
import types
import unittest
from pathlib import Path


BOT_ROOT = Path(__file__).resolve().parents[1]
ENGINE_DIR = BOT_ROOT / "engine"
ROUTER_DIR = ENGINE_DIR / "router"
sys.path[:0] = [str(ENGINE_DIR), str(ENGINE_DIR / "pokemon"), str(ENGINE_DIR / "core")]

router_package = types.ModuleType("router")
router_package.__path__ = [str(ROUTER_DIR)]
sys.modules.setdefault("router", router_package)

from router import amongus_config as C  # noqa: E402
from router import amongus_paired as P  # noqa: E402
from router.amongus_game import Game, PlayerState  # noqa: E402
from router.amongus_map import get_map, get_station_rooms  # noqa: E402
from router.amongus_movement import MovementEngine  # noqa: E402


class FakeManager:
    def __init__(self):
        self.sent = []
        self.broadcasts = []

    def _push_dm(self, player, message, **kwargs):
        self.sent.append((player, message))

    def _broadcast(self, message, group_jid=None, tag_all=False, hide_tags=False, **kwargs):
        self.broadcasts.append(message)


ROLES = {
    "red": "crewmate",
    "blue": "crewmate",
    "green": "crewmate",
    "yellow": "crewmate",
    "orange": "scientist",
    "pink": "impostor",
}


def make_game():
    game = Game.__new__(Game)
    game.manager = FakeManager()
    game.group_jid = "game@g.us"
    game.map = get_map()
    game.map_id = game.map.id
    game.events = []
    game.players = {}
    game._bodies = {}
    game._corpses = {}
    game._reported_crime_scenes = []
    game._meltdown = None
    game._sabotages = {}
    game._team_tasks = []
    game._task_sequence = 0
    game._interaction_sequence = 0
    game._closed_task_prompts = {}
    game.over = False
    game.lock = threading.RLock()
    game._stop_event = threading.Event()
    game._timers = set()
    game._meeting = None
    for jid, role in ROLES.items():
        player = PlayerState(jid, role, jid.title(), game.map)
        player.room_entered_at = 0.0
        player.stopped_since = 0.0
        player.room = "CAFETERIA"
        player.tasks = []
        game.players[jid] = player
    game.color_to_jid = {p.color.lower(): p.jid for p in game.players.values()}
    game.movement = MovementEngine(game)
    return game


def put(game, jid, room):
    game.players[jid].room = room


def last_dm(game, jid):
    messages = [m for who, m in game.manager.sent if who == jid]
    return messages[-1] if messages else None


class FixedRng:
    def __init__(self, value):
        self.value = value

    def uniform(self, low, high):
        return self.value


class PairedScanUnitTests(unittest.TestCase):
    def make_pair(self):
        pair = P.PairedScan(("A", "B"), 2.0)
        pair.join("A", "x")
        pair.join("B", "y")
        return pair

    def test_scans_inside_window_succeed_and_outside_fail(self):
        pair = self.make_pair()
        self.assertEqual(pair.scan("x", 10.0)["kind"], "first")
        self.assertEqual(pair.scan("y", 11.9)["kind"], "success")
        pair = self.make_pair()
        pair.scan("x", 10.0)
        self.assertEqual(pair.scan("y", 12.0)["kind"], "success")
        pair = self.make_pair()
        pair.scan("x", 10.0)
        late = pair.scan("y", 12.1)
        self.assertEqual(late["kind"], "first")
        self.assertTrue(late["missed"])
        self.assertEqual(pair.scan("x", 12.5)["kind"], "success")

    def test_waiting_duplicate_and_unknown_player(self):
        pair = P.PairedScan(("A", "B"), 2.0)
        pair.join("A", "x")
        self.assertEqual(pair.scan("x", 1.0)["kind"], "waiting")
        self.assertEqual(pair.scan("nobody", 1.0)["kind"], "no_station")
        pair.join("B", "y")
        pair.scan("x", 5.0)
        self.assertEqual(pair.scan("x", 5.5)["kind"], "duplicate")

    def test_leave_cancels_the_attempt_and_takeover_works(self):
        pair = self.make_pair()
        pair.scan("x", 5.0)
        self.assertEqual(pair.leave("x"), "A")
        self.assertEqual(pair.scans, {})
        self.assertEqual(pair.join("A", "z"), "joined")
        self.assertEqual(pair.join("A", "w"), "taken")


ACTIVE, IDLE, REPAIRED, FAILED = "active", "idle", "repaired", "failed"


class PairedSabotageTests(unittest.TestCase):
    def setUp(self):
        self.game = make_game()
        self.oxygen = self.game._get_sabotage("oxygen")
        self.reactor = self.game._get_sabotage("reactor")
        self.oxygen.rng = FixedRng(35)
        self.reactor.rng = FixedRng(35)
        self.pink = self.game.players["pink"]
        self.o2_a, self.o2_b = get_station_rooms("oxygen")
        self.re_a, self.re_b = get_station_rooms("reactor")

    def tearDown(self):
        self.game.close()

    def start_oxygen(self, now=100.0):
        self.assertIsNone(self.game._cmd_sabotage(self.pink, "oxygen", now))
        return now + 35

    def seat_pair(self, now, first="red", second="blue", sabotage=None, rooms=None):
        sabotage = sabotage or self.oxygen
        a, b = rooms or (self.o2_a, self.o2_b)
        put(self.game, first, a)
        put(self.game, second, b)
        self.assertEqual(sabotage.join(self.game.players[first], now), "Waiting for partner.")
        self.assertIn("both stations are ready", sabotage.join(self.game.players[second], now).lower())

    # ── Setup and stations ─────────────────────────────────
    def test_stations_come_from_the_map_and_exist(self):
        rooms = get_map().rooms
        for name in P.PAIRED_NAMES:
            stations = get_station_rooms(name)
            self.assertEqual(len(set(stations)), 2)
            self.assertTrue(all(room in rooms for room in stations))
        source = (ROUTER_DIR / "amongus_paired.py").read_text(encoding="utf-8")
        for room in rooms:
            self.assertNotIn(f'"{room}"', source)

    def test_registry_builds_paired_objects_for_oxygen_and_reactor(self):
        self.assertIsInstance(self.oxygen, P.PairedSabotage)
        self.assertIsInstance(self.reactor, P.PairedSabotage)
        self.assertNotIsInstance(self.game._get_sabotage("lights"), P.PairedSabotage)

    def test_deadline_is_drawn_from_the_configured_range(self):
        low, high = C.SABOTAGE_DEADLINE_RANGE_SECONDS
        for name in P.PAIRED_NAMES:
            for seed in range(20):
                game = make_game()
                try:
                    sabotage = game._get_sabotage(name)
                    sabotage.rng = random.Random(seed)
                    game._cmd_sabotage(game.players["pink"], name, 0.0)
                    self.assertTrue(low <= sabotage.deadline <= high)
                finally:
                    game.close()

    def test_only_impostors_activate_and_cooldowns_match_the_design(self):
        self.assertIsNone(self.game._cmd_sabotage(self.game.players["red"], "oxygen", 1.0))
        self.assertEqual(self.oxygen["state"], IDLE)
        self.start_oxygen(100.0)
        self.assertEqual(self.oxygen["cooldown_until"], 100.0 + 4 * 60)
        self.game._cmd_sabotage(self.pink, "reactor", 100.0)
        self.assertEqual(self.reactor["cooldown_until"], 100.0 + 5 * 60)
        self.assertIn("already active", self.game._cmd_sabotage(self.pink, "o2", 101.0))

    def test_activation_announces_the_two_stations_but_not_the_deadline(self):
        self.start_oxygen(100.0)
        note = self.game.manager.broadcasts[-1]
        for room in (self.o2_a, self.o2_b):
            self.assertIn(room.replace("_", " ").title(), note)
        self.assertNotIn("35", note)

    def test_cooldown_command_lists_both_paired_cooldowns(self):
        self.start_oxygen(100.0)
        text = self.game._cmd_cooldowns(self.pink, 110.0)
        self.assertIn("Oxygen sabotage: 230s", text)
        self.assertIn("Reactor sabotage: Ready", text)

    # ── Repair ─────────────────────────────────────────────
    def test_valid_pair_repairs_and_ends_the_sabotage_immediately(self):
        deadline = self.start_oxygen(100.0)
        self.seat_pair(101.0)
        self.assertIn("Scan sent", self.oxygen.scan(self.game.players["red"], 105.0))
        self.assertEqual(self.oxygen["state"], ACTIVE)
        self.assertIsNone(self.oxygen.scan(self.game.players["blue"], 106.0))
        self.assertEqual(self.oxygen["state"], REPAIRED)
        self.assertFalse(self.game.over)
        self.assertIsNone(self.oxygen.pair)
        self.assertIn("✅ *O₂ sabotage repaired.* The ship is safe for now.", self.game.manager.broadcasts)
        self.assertLess(106.0, deadline)
        self.game._advance_sabotages(deadline + 5)
        self.assertFalse(self.game.over)

    def test_scan_exactly_at_the_deadline_is_too_late(self):
        # Confirmed (06C/06D): both scans strictly before the deadline.
        deadline = self.start_oxygen(100.0)
        self.seat_pair(101.0)
        self.oxygen.scan(self.game.players["red"], deadline - 1.0)
        self.oxygen.scan(self.game.players["blue"], deadline)
        self.assertEqual(self.oxygen["state"], FAILED)

    def test_scan_through_handle_at_the_deadline_is_too_late(self):
        deadline = self.start_oxygen(100.0)
        self.seat_pair(101.0)
        self.game.handle("red", "scan", int((deadline - 1.0) * 1000), quoted_text="(bot)")
        self.game.handle("blue", "scan", int(deadline * 1000), quoted_text="(bot)")
        self.assertEqual(self.oxygen["state"], FAILED)
        self.assertTrue(self.game.over)

    def test_scans_a_tick_either_side_of_the_deadline(self):
        for offset, expected in ((-1.0, REPAIRED), (0.0, FAILED), (1.0, FAILED)):  # strict-before (pkg 3)
            game = make_game()
            try:
                sabotage = game._get_sabotage("oxygen")
                sabotage.rng = FixedRng(35)
                game._cmd_sabotage(game.players["pink"], "oxygen", 100.0)
                a, b = get_station_rooms("oxygen")
                put(game, "red", a)
                put(game, "blue", b)
                sabotage.join(game.players["red"], 101.0)
                sabotage.join(game.players["blue"], 101.0)
                deadline = sabotage.deadline
                sabotage.scan(game.players["red"], deadline - 1.0 if offset >= 0 else deadline - 2.0)
                sabotage.scan(game.players["blue"], deadline + offset)
                self.assertEqual(sabotage["state"], expected, offset)
                self.assertEqual(game.over, expected == FAILED)
            finally:
                game.close()

    def test_scans_straddling_the_deadline_fail_the_sabotage(self):
        deadline = self.start_oxygen(100.0)
        self.seat_pair(101.0)
        self.oxygen.scan(self.game.players["red"], deadline - 0.5)
        self.oxygen.scan(self.game.players["blue"], deadline + 0.5)
        self.assertEqual(self.oxygen["state"], FAILED)
        self.assertTrue(self.game.over)

    def test_scans_2_1_seconds_apart_fail_the_pair_but_allow_a_retry(self):
        self.start_oxygen(100.0)
        self.seat_pair(101.0)
        self.oxygen.scan(self.game.players["red"], 110.0)
        self.oxygen.scan(self.game.players["blue"], 112.1)
        self.assertEqual(self.oxygen["state"], ACTIVE)
        self.assertIn("missed", last_dm(self.game, "red"))
        self.oxygen.scan(self.game.players["red"], 113.0)
        self.assertEqual(self.oxygen["state"], REPAIRED)

    def test_scans_1_9_seconds_apart_succeed(self):
        self.start_oxygen(100.0)
        self.seat_pair(101.0)
        self.oxygen.scan(self.game.players["red"], 110.0)
        self.oxygen.scan(self.game.players["blue"], 111.9)
        self.assertEqual(self.oxygen["state"], REPAIRED)

    def test_lone_scan_expires_on_the_tick(self):
        self.start_oxygen(100.0)
        self.seat_pair(101.0)
        self.oxygen.scan(self.game.players["red"], 110.0)
        self.oxygen.tick(112.5)
        self.assertEqual(self.oxygen.pair.scans, {self.o2_a: 110.0})
        self.oxygen.tick(113.5)
        self.assertEqual(self.oxygen.pair.scans, {})
        self.assertIn("missed", last_dm(self.game, "blue"))

    # ── Leaving, death, takeover ───────────────────────────
    def test_leaving_mid_attempt_cancels_it_and_a_new_player_takes_over(self):
        self.start_oxygen(100.0)
        self.seat_pair(101.0)
        self.oxygen.scan(self.game.players["red"], 110.0)
        self.game.players["blue"].path = ["CAFETERIA"]
        self.game._advance_sabotages(111.0)
        self.assertEqual(self.oxygen.pair.scans, {})
        self.assertIsNone(self.oxygen.pair.occupants[self.o2_b])
        self.assertIn("Waiting for partner", last_dm(self.game, "red"))
        put(self.game, "green", self.o2_b)
        self.assertIn("scan", self.oxygen.join(self.game.players["green"], 112.0))
        self.oxygen.scan(self.game.players["red"], 113.0)
        self.oxygen.scan(self.game.players["green"], 113.5)
        self.assertEqual(self.oxygen["state"], REPAIRED)

    def test_a_stale_scan_from_a_player_who_just_left_does_not_count(self):
        self.start_oxygen(100.0)
        self.seat_pair(101.0)
        self.oxygen.scan(self.game.players["red"], 110.0)
        self.game.players["red"].path = ["CAFETERIA"]
        self.assertIn("not at a repair station", self.oxygen.scan(self.game.players["red"], 110.5))
        put(self.game, "green", self.o2_a)
        self.game.players["red"].path = None
        self.oxygen.join(self.game.players["green"], 111.0)
        self.oxygen.scan(self.game.players["blue"], 111.5)
        self.assertEqual(self.oxygen["state"], ACTIVE)

    def test_death_at_a_station_ends_the_interaction_and_allows_replacement(self):
        self.start_oxygen(100.0)
        self.seat_pair(101.0)
        self.game.players["red"].alive = False
        self.game._advance_sabotages(102.0)
        self.assertIsNone(self.oxygen.pair.occupants[self.o2_a])
        put(self.game, "yellow", self.o2_a)
        self.oxygen.join(self.game.players["yellow"], 103.0)
        self.oxygen.scan(self.game.players["yellow"], 104.0)
        self.oxygen.scan(self.game.players["blue"], 104.5)
        self.assertEqual(self.oxygen["state"], REPAIRED)

    def test_departure_frees_the_station_immediately(self):
        self.start_oxygen(100.0)
        self.seat_pair(101.0)
        self.game.mark_departed("red", 102.0)
        self.assertIsNone(self.oxygen.pair.occupants[self.o2_a])
        self.assertEqual(self.oxygen.pair.scans, {})
        self.assertEqual(self.oxygen.scan(self.game.players["blue"], 102.5), "Waiting for partner.")

    def test_starting_another_task_vacates_the_seat(self):
        self.start_oxygen(100.0)
        self.seat_pair(101.0)
        self.game.players["red"].task_in_progress = {
            "kind": "task", "task_id": None, "interaction_ref": "I9999"
        }
        self.game._advance_sabotages(102.0)
        self.assertIsNone(self.oxygen.pair.occupants[self.o2_a])

    # ── Access rules ───────────────────────────────────────
    def test_station_rules_for_ghosts_impostors_busy_and_taken_stations(self):
        self.start_oxygen(100.0)
        put(self.game, "red", self.o2_a)
        put(self.game, "pink", self.o2_b)
        put(self.game, "blue", self.o2_a)
        self.game.players["yellow"].alive = False
        put(self.game, "yellow", self.o2_b)
        self.assertEqual(self.oxygen.join(self.game.players["red"], 101.0), "Waiting for partner.")
        self.assertIn("can't repair", self.oxygen.join(self.game.players["pink"], 101.0))
        self.assertIn("living", self.oxygen.join(self.game.players["yellow"], 101.0))
        self.assertIn("already at", self.oxygen.join(self.game.players["blue"], 101.0))
        self.assertEqual(self.oxygen.join(self.game.players["red"], 102.0), "Waiting for partner.")
        self.game.players["green"].room = "CAFETERIA"
        self.assertIn("needs a crew member", self.oxygen.join(self.game.players["green"], 103.0))
        self.game.players["orange"].room = self.o2_b
        self.game.players["orange"].task_in_progress = {
            "kind": "task", "task_id": "T1", "interaction_ref": "I0001"
        }
        self.assertIn("active task", self.oxygen.join(self.game.players["orange"], 103.0))

    def test_cannot_join_while_moving_or_in_a_vent(self):
        self.start_oxygen(100.0)
        put(self.game, "red", self.o2_a)
        self.game.players["red"].path = ["CAFETERIA"]
        self.assertIn("moving", self.oxygen.join(self.game.players["red"], 101.0))
        self.game.players["red"].path = None
        self.game.players["red"].in_vent_until = 500.0
        self.assertIn("vent", self.oxygen.join(self.game.players["red"], 101.0))

    # ── Command routing ────────────────────────────────────
    def test_task_and_scan_commands_route_through_handle(self):
        self.start_oxygen(100.0)
        put(self.game, "red", self.o2_a)
        put(self.game, "blue", self.o2_b)
        self.assertEqual(self.game.handle("red", ".task", 101000), "Waiting for partner.")
        self.assertIn("scan", self.game.handle("blue", ".task", 101500))
        self.assertIn("Scan sent", self.game.handle("red", "scan", 105000, quoted_text="(bot)"))
        self.assertIsNone(self.game.handle("blue", ".scan", 106000, quoted_text="(bot)"))
        self.assertEqual(self.oxygen["state"], REPAIRED)

    def test_scan_text_is_ignored_when_no_paired_sabotage_is_active(self):
        self.assertIsNone(self.game.handle("red", "scan", 100000))  # silent (Session 09 pkg 8)

    # ── Time ───────────────────────────────────────────────
    def test_deadline_expiry_with_no_scans_fails_and_ends_the_game_cleanly(self):
        deadline = self.start_oxygen(100.0)
        self.game._advance_sabotages(deadline)
        self.assertEqual(self.oxygen["state"], ACTIVE)
        self.game._advance_sabotages(deadline + 0.1)
        self.assertEqual(self.oxygen["state"], FAILED)
        self.assertTrue(self.game.over)
        self.assertEqual(self.game._timers, set())
        count = len(self.game.manager.broadcasts)
        self.game._advance_sabotages(deadline + 5)
        self.assertEqual(len(self.game.manager.broadcasts), count)
        self.assertIn("OXYGEN FAILURE!", self.game.manager.broadcasts[-1])
        self.assertIn("O₂ depleted — Impostors win", self.game.manager.broadcasts[-1])

    def test_warnings_fire_once_each_and_never_per_second(self):
        self.start_oxygen(100.0)
        for second in range(0, 36):
            self.game._advance_sabotages(100.0 + second)
        warnings = [m for m in self.game.manager.broadcasts if "remaining" in m]
        self.assertEqual(
            warnings,
            ["⚠️ *O₂: 20s remaining.*\nReach the required station(s) and finish the repair.", "⚠️ *O₂: 10s remaining.*\nReach the required station(s) and finish the repair."],
        )

    # ── Meetings ───────────────────────────────────────────
    def test_meeting_pauses_the_deadline_and_resumes_it_with_cooldown_running(self):
        self.start_oxygen(100.0)
        self.seat_pair(101.0)
        self.oxygen.scan(self.game.players["red"], 110.0)
        self.game._pause_sabotage_deadlines(120.0)
        self.assertIsNone(self.oxygen.deadline)
        self.assertEqual(self.oxygen["paused_remaining"], 15.0)
        self.game._meeting = {"votes": {}}
        self.assertIn("paused", self.oxygen.scan(self.game.players["blue"], 125.0))
        self.assertIn("paused", self.oxygen.join(self.game.players["green"], 125.0))
        self.game._advance_sabotages(300.0)
        self.assertEqual(self.oxygen["state"], ACTIVE)
        cooldown_until = self.oxygen["cooldown_until"]
        self.assertEqual(cooldown_until - 180.0, 160.0)
        self.game._meeting = None
        self.game._resume_sabotage_deadlines(180.0)
        self.assertEqual(self.oxygen.deadline, 195.0)
        self.assertEqual(self.oxygen["cooldown_until"], cooldown_until)

    def test_sabotage_cannot_be_triggered_during_a_meeting(self):
        self.game._meeting = {"votes": {}}
        self.assertIn("meeting", self.game._cmd_sabotage(self.pink, "oxygen", 100.0))
        self.assertEqual(self.oxygen["state"], IDLE)

    def test_meeting_call_resolves_an_already_expired_deadline(self):
        deadline = self.start_oxygen(100.0)
        self.game._resolve_due_sabotage_deadlines(deadline + 1.0)
        self.assertEqual(self.oxygen["state"], FAILED)
        self.assertTrue(self.game.over)

    # ── Independence of sabotages ──────────────────────────
    def test_repairing_one_sabotage_leaves_the_other_active_on_its_own_timer(self):
        self.game._cmd_sabotage(self.pink, "oxygen", 100.0)
        self.game._cmd_sabotage(self.pink, "reactor", 100.0)
        reactor_deadline = self.reactor.deadline
        self.seat_pair(101.0)
        self.oxygen.scan(self.game.players["red"], 105.0)
        self.oxygen.scan(self.game.players["blue"], 105.5)
        self.assertEqual(self.oxygen["state"], REPAIRED)
        self.assertEqual(self.reactor["state"], ACTIVE)
        self.assertEqual(self.reactor.deadline, reactor_deadline)
        self.assertIsNotNone(self.reactor.pair)

    def test_game_end_cancels_both_and_nothing_acts_afterwards(self):
        self.game._cmd_sabotage(self.pink, "oxygen", 100.0)
        self.game._cmd_sabotage(self.pink, "reactor", 100.0)
        self.seat_pair(101.0)
        self.game._end_game("done")
        for sabotage in (self.oxygen, self.reactor):
            self.assertEqual(sabotage["state"], IDLE)
            self.assertIsNone(sabotage.pair)
        count = len(self.game.manager.broadcasts)
        self.game._advance_sabotages(500.0)
        self.assertIsNone(self.oxygen.scan(self.game.players["red"], 500.0))
        self.assertEqual(len(self.game.manager.broadcasts), count)

    def test_reactor_uses_its_own_stations(self):
        self.game._cmd_sabotage(self.pink, "reactor", 100.0)
        self.seat_pair(101.0, sabotage=self.reactor, rooms=(self.re_a, self.re_b))
        self.reactor.scan(self.game.players["red"], 110.0)
        self.reactor.scan(self.game.players["blue"], 110.5)
        self.assertEqual(self.reactor["state"], REPAIRED)


if __name__ == "__main__":
    unittest.main()
