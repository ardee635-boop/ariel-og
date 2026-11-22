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
from router.amongus_sabotage import CommunicationsSabotage  # noqa: E402
from router import amongus_config as C  # noqa: E402


GAME_GROUP = "game@g.us"


class FakeManager:
    def __init__(self):
        self.sent = []
        self.broadcasts = []

    def _push_dm(self, player, message, **kwargs):
        self.sent.append((player, message))

    def _broadcast(self, message, **kwargs):
        self.broadcasts.append(message)


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


class AmongUsSessionSevenB2aiTests(unittest.TestCase):
    def test_communications_activates_once_refuses_with_cooldown_never_times_out(self):
        game = make_game()
        try:
            impostor = game.players["pink"]
            comms = game._sabotages["communications"]
            self.assertIsInstance(comms, CommunicationsSabotage)

            self.assertIsNone(game._cmd_sabotage(impostor, "communications", now=100))
            self.assertEqual(comms["state"], "active")
            self.assertIsNone(comms["deadline"])
            self.assertEqual(comms["cooldown_until"], 100 + 3 * 60)
            self.assertEqual(
                sum("COMMUNICATIONS SABOTAGED!" in m
                    for m in game.manager.broadcasts),
                1,
            )

            self.assertIn(
                "already active", game._cmd_sabotage(impostor, "communications", now=110)
            )
            game._advance_sabotages(100 + 3600)
            self.assertEqual(comms["state"], "active")
            self.assertFalse(game.over)

            game._repair_sabotage("communications", game.players["red"], now=200)
            self.assertIn(
                "cooldown: 80s", game._cmd_sabotage(impostor, "communications", now=200)
            )
            self.assertIsNone(game._cmd_sabotage(impostor, "comms", now=280))
        finally:
            close_game(game)

    def test_non_impostor_cannot_activate(self):
        game = make_game()
        try:
            self.assertIsNone(game._cmd_sabotage(game.players["red"], "communications", now=100))
            self.assertEqual(comms_state(game), "idle")
        finally:
            close_game(game)

    def test_repair_clears_communications_and_lights_stays_active(self):
        game = make_game()
        try:
            impostor = game.players["pink"]
            game._cmd_sabotage(impostor, "lights", now=100)
            game._cmd_sabotage(impostor, "communications", now=100)

            self.assertTrue(game._repair_sabotage("communications", game.players["red"], now=110))
            self.assertEqual(comms_state(game), "repaired")
            self.assertEqual(game._sabotages["lights"]["state"], "active")
            self.assertFalse(game._repair_sabotage("communications", game.players["red"], now=111))
        finally:
            close_game(game)

    def test_debug_repair_command_no_longer_exists(self):
        game = make_game()
        try:
            game._cmd_sabotage(game.players["pink"], "communications", now=100)
            reply = game.handle("red", ".debugcommsrepair", received_at_ms=110_000)
            self.assertIsNone(reply)  # unknown commands are silent (Session 09 pkg 8)
            self.assertEqual(comms_state(game), "active")
            self.assertFalse(hasattr(C, "DEBUG_COMMS_REPAIR_ENABLED"))
        finally:
            close_game(game)

    def test_repairing_lights_leaves_communications_active(self):
        game = make_game()
        try:
            impostor = game.players["pink"]
            game._cmd_sabotage(impostor, "lights", now=100)
            game._cmd_sabotage(impostor, "communications", now=100)
            game._repair_sabotage("lights", game.players["red"], now=110)
            self.assertEqual(comms_state(game), "active")
            self.assertEqual(
                game._sabotages["communications"]["cooldown_until"], 100 + 180
            )
        finally:
            close_game(game)

    def test_game_end_cancels_communications_and_nothing_is_sent_afterwards(self):
        game = make_game()
        try:
            game._cmd_sabotage(game.players["pink"], "communications", now=100)
            game._end_game("test over")
            self.assertEqual(comms_state(game), "idle")
            sent = len(game.manager.broadcasts)
            game._advance_sabotages(10_000)
            self.assertEqual(len(game.manager.broadcasts), sent)
        finally:
            close_game(game)


if __name__ == "__main__":
    unittest.main()
