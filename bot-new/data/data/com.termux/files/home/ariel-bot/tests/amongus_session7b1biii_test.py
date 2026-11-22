import sys
import threading
import types
import unittest
from unittest import mock
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
from router import amongus_puzzles as puzzles  # noqa: E402
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


def command(game, sender, text, at):
    return game.handle(sender, text, received_at_ms=round(at * 1000))


def move_to(game, jid, room):
    game.players[jid].room = room
    game.players[jid].reference_room = room


def start_puzzles(game, jids, presses_to_solve=0):
    """Activate Lights and give each player a one-press-from-solved ring."""
    ring = puzzles.get_pattern("ring")
    start = puzzles.apply_switch(puzzles.solved_state(ring), ring, presses_to_solve)
    for jid in jids:
        move_to(game, jid, "ELECTRICAL")
    game._cmd_sabotage(game.players["pink"], "lights", now=100)
    with mock.patch.object(puzzles, "pick_pattern", return_value=ring), \
            mock.patch.object(puzzles, "scramble", return_value=start):
        for i, jid in enumerate(jids):
            command(game, jid, ".task", 110.0 + i)


def repairs(game):
    return [e for e in game.events if e["type"] == "sabotage_repaired"]


class AmongUsSessionSevenB1biiiTests(unittest.TestCase):
    def test_first_solve_repairs_lights_for_everyone(self):
        game = make_game()
        try:
            start_puzzles(game, ["red", "blue"])
            reply = command(game, "red", ".task answer 1", 120.0)
            self.assertIn("Lights repaired", reply)
            self.assertEqual(game._sabotages["lights"]["state"], "repaired")
            self.assertEqual(len(repairs(game)), 1)
            self.assertEqual(
                sum("Lights sabotage repaired" in m for m in game.manager.broadcasts),
                1,
            )
            # Passive observations are no longer masked.
            self.assertFalse(game._lights_masking())
        finally:
            close_game(game)

    def test_all_repair_interactions_are_cleaned_up(self):
        game = make_game()
        try:
            start_puzzles(game, ["red", "blue", "green"])
            command(game, "blue", ".task answer 1", 120.0)
            for jid in ("red", "blue", "green"):
                self.assertIsNone(game.players[jid].task_in_progress)
            self.assertEqual(game._sabotages["lights"]["repair_interactions"], {})
        finally:
            close_game(game)

    def test_two_players_solving_at_once_counts_one_repair(self):
        game = make_game()
        try:
            start_puzzles(game, ["red", "blue"])
            first = command(game, "red", ".task answer 1", 120.0)
            second = command(game, "blue", ".task answer 1", 120.0)
            self.assertIn("Lights repaired", first)
            self.assertNotIn("Lights repaired", second)
            self.assertEqual(len(repairs(game)), 1)
            self.assertEqual(
                [e["type"] for e in game.events].count("circuit_solved"), 1
            )
        finally:
            close_game(game)

    def test_abandoning_leaves_lights_active_and_other_attempt_continues(self):
        game = make_game()
        try:
            start_puzzles(game, ["red", "blue"])
            game._cancel_task_interaction(game.players["red"], "abandoned", 125.0)
            self.assertEqual(game._sabotages["lights"]["state"], "active")
            self.assertIsNotNone(game.players["blue"].task_in_progress)
            reply = command(game, "blue", ".task answer 1", 126.0)
            self.assertIn("Lights repaired", reply)
            self.assertEqual(len(repairs(game)), 1)
        finally:
            close_game(game)

    def test_stale_reply_after_repair_does_not_repair_again(self):
        game = make_game()
        try:
            start_puzzles(game, ["red", "blue"])
            ref = game.players["blue"].task_in_progress["interaction_ref"]
            command(game, "red", ".task answer 1", 120.0)
            reply = game.handle(
                "blue", "1", received_at_ms=121_000, quoted_text=f"[Task Ref: {ref}]"
            )
            self.assertIn("stale", reply)
            self.assertEqual(len(repairs(game)), 1)
        finally:
            close_game(game)

    def test_debug_repair_command_no_longer_exists(self):
        game = make_game()
        try:
            game._cmd_sabotage(game.players["pink"], "lights", now=100)
            reply = command(game, "red", ".debugrepair lights", 110.0)
            self.assertIsNone(reply)  # unknown commands are silent (Session 09 pkg 8)
            self.assertEqual(game._sabotages["lights"]["state"], "active")
            self.assertFalse(hasattr(game, "_cmd_debug_repair"))
            self.assertFalse(hasattr(C, "DEBUG_REPAIR_ENABLED"))
        finally:
            close_game(game)

    def test_lights_can_be_sabotaged_again_after_cooldown(self):
        game = make_game()
        try:
            start_puzzles(game, ["red"])
            command(game, "red", ".task answer 1", 120.0)
            self.assertIn(
                "cooldown", game._cmd_sabotage(game.players["pink"], "lights", now=130)
            )
            self.assertIsNone(
                game._cmd_sabotage(game.players["pink"], "lights", now=100 + 180)
            )
            self.assertEqual(game._sabotages["lights"]["state"], "active")
        finally:
            close_game(game)


if __name__ == "__main__":
    unittest.main()
