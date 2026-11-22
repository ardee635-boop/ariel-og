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

from router.amongus import AmongUsManager  # noqa: E402
from router.amongus_game import Game, PlayerState  # noqa: E402
from router.amongus_map import get_map  # noqa: E402
from router.amongus_movement import MovementEngine  # noqa: E402
from router import amongus_config as C  # noqa: E402


GAME_GROUP = "game@g.us"


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


class FakeRouter:
    def _direct_send(self, *args, **kwargs):
        return None


def make_game():
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
    game._meltdown = None
    game._sabotages = {}
    game._ensure_sabotage_registry()
    game._team_tasks = []
    game._task_sequence = 0
    game._interaction_sequence = 0
    game._closed_task_prompts = {}
    game.over = False
    game.lock = threading.RLock()
    game._stop_event = threading.Event()
    game._timers = set()
    game._meeting = None
    roles = {
        "red": "crewmate",
        "blue": "crewmate",
        "green": "scientist",
        "pink": "impostor",
    }
    colors = {"red": "Red", "blue": "Blue", "green": "Green", "pink": "Pink"}
    for jid, role in roles.items():
        player = PlayerState(jid, role, colors[jid], game.map)
        player.room_entered_at = 0.0
        player.stopped_since = 0.0
        player.room = "CAFETERIA"
        player.tasks = []
        game.players[jid] = player
    game.color_to_jid = {p.color.lower(): p.jid for p in game.players.values()}
    game.movement = MovementEngine(game)
    return game


def close_game(game):
    game.close()


def comms_state(game):
    return game._sabotages["communications"]["state"]


def comms_on(game, at=100):
    game._cmd_sabotage(game.players["pink"], "communications", now=at)


def reports(game):
    return [m for m in game.manager.broadcasts if "activity report" in m]


class AmongUsSessionSevenB2biTests(unittest.TestCase):
    def test_group_locks_on_activation_and_unlocks_on_repair_once_each(self):
        game = make_game()
        try:
            comms_on(game)
            self.assertEqual(game.manager.locks, [(True, GAME_GROUP)])
            game._advance_sabotages(150)  # ticks do not re-send
            self.assertEqual(len(game.manager.locks), 1)
            game._repair_sabotage("communications", game.players["red"], now=200)
            self.assertEqual(game.manager.locks, [(True, GAME_GROUP), (False, GAME_GROUP)])
            types_ = [e["type"] for e in game.events]
            self.assertIn("comms_restricted", types_)
            self.assertIn("comms_unrestricted", types_)
        finally:
            close_game(game)

    def test_lights_does_not_lock_the_group(self):
        game = make_game()
        try:
            game._cmd_sabotage(game.players["pink"], "lights", now=100)
            self.assertEqual(game.manager.locks, [])
        finally:
            close_game(game)

    def test_disabled_by_config(self):
        game = make_game()
        old = C.COMMS_RESTRICTION_ENABLED
        C.COMMS_RESTRICTION_ENABLED = False
        try:
            comms_on(game)
            self.assertEqual(game.manager.locks, [])
        finally:
            C.COMMS_RESTRICTION_ENABLED = old
            close_game(game)

    def test_meeting_lifts_lock_and_relocks_if_still_down(self):
        game = make_game()
        try:
            comms_on(game)
            game._cmd_call_meeting(game.players["red"], "emergency", 120)
            self.assertTrue(game._meeting)
            self.assertEqual(game.manager.locks[-1][0], False)
            game._resolve_meeting(190)
            self.assertEqual(game.manager.locks[-1][0], True)
            self.assertEqual([l for l, _ in game.manager.locks], [True, False, True])
        finally:
            close_game(game)

    def test_repair_during_meeting_does_not_relock_afterwards(self):
        game = make_game()
        try:
            comms_on(game)
            game._cmd_call_meeting(game.players["red"], "emergency", 120)
            game._repair_sabotage("communications", game.players["red"], now=130)
            game._resolve_meeting(190)
            self.assertEqual([l for l, _ in game.manager.locks], [True, False])
        finally:
            close_game(game)

    def test_game_end_while_locked_unlocks_and_nothing_more_is_sent(self):
        game = make_game()
        try:
            comms_on(game)
            game._end_game("over")
            self.assertEqual([l for l, _ in game.manager.locks], [True, False])
            sent = (len(game.manager.locks), len(game.manager.broadcasts))
            game._advance_sabotages(10_000)
            self.assertEqual((len(game.manager.locks), len(game.manager.broadcasts)), sent)
            self.assertEqual(reports(game), [])
        finally:
            close_game(game)

    def test_manager_transport_request_shape(self):
        calls = []
        ns = types.SimpleNamespace(
            router=types.SimpleNamespace(
                _direct_send=lambda msg, **kw: calls.append((msg, kw))
            ),
            group_jid=GAME_GROUP,
            lobby=None,
        )
        self.assertTrue(AmongUsManager._set_comms_restriction(ns, True))
        self.assertTrue(AmongUsManager._set_comms_restriction(ns, False))
        self.assertEqual(calls, [
            ("", {"group_jid": GAME_GROUP, "group_action": "restrict"}),
            ("", {"group_jid": GAME_GROUP, "group_action": "unrestrict"}),
        ])
        ns.router = types.SimpleNamespace()
        self.assertFalse(AmongUsManager._set_comms_restriction(ns, True))

    def test_report_lists_only_players_still_for_over_60s_during_outage(self):
        game = make_game()
        try:
            game.players["red"].stopped_since = 0.0      # before outage -> counts from 100
            game.players["blue"].stopped_since = 150.0   # 50s idle at repair
            game.players["green"].alive = False          # dead: excluded
            game.players["pink"].stopped_since = 120.0   # 80s idle
            move = game.players["pink"]
            comms_on(game, 100)
            game._repair_sabotage("communications", game.players["red"], now=200)
            rep = reports(game)
            self.assertEqual(len(rep), 1)
            text = rep[0]
            self.assertIn("*Red* — Cafeteria, still for 100s", text)
            self.assertIn("*Pink* — Cafeteria, still for 80s", text)
            self.assertLess(text.index("Red"), text.index("Pink"))  # longest first
            self.assertNotIn("Blue", text)
            self.assertNotIn("Green", text)
            self.assertIn("not proof of guilt", text.lower())
        finally:
            close_game(game)

    def test_report_with_nobody_inactive_and_in_corridor_and_vent(self):
        game = make_game()
        try:
            for p in game.players.values():
                p.stopped_since = 190.0
            comms_on(game, 100)
            game._repair_sabotage("communications", game.players["red"], now=200)
            self.assertIn("Nobody stood still", reports(game)[0])
        finally:
            close_game(game)

        game = make_game()
        try:
            red = game.players["red"]
            red.room = None
            red.settled = False
            red.corridor_from = "CAFETERIA"
            red.corridor_to = "MEDBAY"
            red.stopped_since = 0.0
            game.players["blue"].stopped_since = 0.0
            game.players["blue"].in_vent_until = 999.0   # in a vent: excluded
            comms_on(game, 100)
            game._repair_sabotage("communications", game.players["green"], now=200)
            text = reports(game)[0]
            self.assertIn("*Red* — the Cafeteria – Medbay corridor", text)
            self.assertNotIn("Blue", text)
        finally:
            close_game(game)

    def test_no_report_for_other_sabotages_and_only_one_per_repair(self):
        game = make_game()
        try:
            game._cmd_sabotage(game.players["pink"], "lights", now=100)
            game._repair_sabotage("lights", game.players["red"], now=200)
            self.assertEqual(reports(game), [])
            comms_on(game, 300)
            game._repair_sabotage("communications", game.players["red"], now=400)
            self.assertFalse(game._repair_sabotage("communications", game.players["red"], now=401))
            self.assertEqual(len(reports(game)), 1)
        finally:
            close_game(game)

    def test_report_does_not_replay_missed_movement(self):
        game = make_game()
        try:
            comms_on(game, 100)
            game.handle("red", ".m medbay", received_at_ms=110_000)
            game.movement.advance_all(150.0)
            game._repair_sabotage("communications", game.players["blue"], now=160)
            text = reports(game)[0]
            self.assertNotIn("arrived", text)
            self.assertNotIn("left", text)
        finally:
            close_game(game)


if __name__ == "__main__":
    unittest.main()
