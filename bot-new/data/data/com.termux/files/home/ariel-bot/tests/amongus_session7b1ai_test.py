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
from router.amongus_sabotage import LightsSabotage  # noqa: E402
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


class AmongUsSessionSevenB1aiTests(unittest.TestCase):
    def test_lights_activates_once_refuses_with_cooldown_and_never_times_out(self):
        game = make_game()
        try:
            impostor = game.players["pink"]
            lights = game._sabotages["lights"]
            self.assertIsInstance(lights, LightsSabotage)

            self.assertIsNone(game._cmd_sabotage(impostor, "lights", now=100))
            self.assertEqual(lights["state"], "active")
            self.assertIsNone(lights["deadline"])
            self.assertEqual(lights["cooldown_until"], 100 + 3 * 60)

            again = game._cmd_sabotage(impostor, "lights", now=110)
            self.assertIn("already active", again)

            game._advance_sabotages(100 + 3600)
            self.assertEqual(lights["state"], "active")
            self.assertFalse(game.over)
            self.assertEqual(
                [m for m in game.manager.broadcasts if "LIGHTS SABOTAGED!" in m].__len__(),
                1,
            )

            game._repair_sabotage("lights", game.players["red"], now=3800)
            refusal = game._cmd_sabotage(impostor, "lights", now=3800)
            self.assertIsNone(refusal)  # cooldown long expired after repair
            self.assertEqual(lights["state"], "active")
        finally:
            close_game(game)

    def test_cooldown_refusal_shows_remaining_time_after_repair(self):
        game = make_game()
        try:
            impostor = game.players["pink"]
            game._cmd_sabotage(impostor, "lights", now=100)
            game._repair_sabotage("lights", game.players["red"], now=120)
            refusal = game._cmd_sabotage(impostor, "lights", now=130)
            self.assertIn("cooldown: 150s", refusal)
        finally:
            close_game(game)

    def test_repair_clears_only_lights(self):
        game = make_game()
        try:
            impostor = game.players["pink"]
            game._cmd_sabotage(impostor, "lights", now=100)
            game._cmd_sabotage(impostor, "communications", now=100)

            self.assertTrue(
                game._repair_sabotage("lights", game.players["red"], now=110)
            )
            self.assertEqual(game._sabotages["lights"]["state"], "repaired")
            self.assertEqual(game._sabotages["communications"]["state"], "active")
            self.assertFalse(
                game._repair_sabotage("lights", game.players["red"], now=111)
            )
        finally:
            close_game(game)

    def test_game_end_cancels_lights_and_nothing_is_sent_afterwards(self):
        game = make_game()
        try:
            game._cmd_sabotage(game.players["pink"], "lights", now=100)
            game._end_game("test over")
            self.assertEqual(game._sabotages["lights"]["state"], "idle")
            self.assertIsNone(game._sabotages["lights"]["timer"])
            sent = len(game.manager.broadcasts)
            game._advance_sabotages(10_000)
            self.assertEqual(len(game.manager.broadcasts), sent)
        finally:
            close_game(game)


if __name__ == "__main__":
    unittest.main()
