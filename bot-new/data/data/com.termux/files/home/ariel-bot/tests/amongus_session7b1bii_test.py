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


def command(game, sender, text, at, quoted=None):
    return game.handle(
        sender, text, received_at_ms=round(at * 1000), quoted_text=quoted
    )


def move_to(game, jid, room):
    game.players[jid].room = room
    game.players[jid].reference_room = room


def start_scene(game, jids=("red", "blue")):
    for jid in jids:
        move_to(game, jid, "ELECTRICAL")
    game._cmd_sabotage(game.players["pink"], "lights", now=100)


class AmongUsSessionSevenB1biiTests(unittest.TestCase):
    def test_task_at_electrical_starts_puzzle_and_posts_to_group(self):
        game = make_game()
        try:
            start_scene(game)
            reply = command(game, "red", ".task", 110.0)
            self.assertIn("Lights circuit", reply)
            self.assertIn("[Task Ref:", reply)
            active = game.players["red"].task_in_progress
            self.assertEqual(active["kind"], "sabotage_repair")
            self.assertEqual(active["sabotage"], "lights")
            self.assertTrue(
                any("*Red* is working on the *Lights* circuit" in m
                    for m in game.manager.broadcasts)
            )
        finally:
            close_game(game)

    def test_task_elsewhere_or_without_lights_does_not_start_puzzle(self):
        game = make_game()
        try:
            move_to(game, "red", "ELECTRICAL")
            reply = command(game, "red", ".task", 110.0)  # Lights idle
            self.assertNotIn("Lights circuit", reply or "")
            self.assertIsNone(game.players["red"].task_in_progress)

            game._cmd_sabotage(game.players["pink"], "lights", now=120)
            reply = command(game, "green", ".task", 130.0)  # in Cafeteria
            self.assertNotIn("Lights circuit", reply or "")
            self.assertIsNone(game.players["green"].task_in_progress)
        finally:
            close_game(game)

    def test_two_players_get_separate_puzzles(self):
        game = make_game()
        try:
            start_scene(game)
            ring = puzzles.get_pattern("ring")
            states = iter(
                [
                    puzzles.apply_switch(puzzles.solved_state(ring), ring, 0),
                    puzzles.apply_switch(puzzles.solved_state(ring), ring, 2),
                ]
            )
            with mock.patch.object(puzzles, "pick_pattern", return_value=ring), \
                    mock.patch.object(puzzles, "scramble", side_effect=lambda *a, **k: next(states)):
                command(game, "red", ".task", 110.0)
                command(game, "blue", ".task", 111.0)

            red = game.players["red"].task_in_progress
            blue = game.players["blue"].task_in_progress
            self.assertNotEqual(red["interaction_ref"], blue["interaction_ref"])
            blue_before = list(blue["metadata"]["state"])

            reply = command(game, "red", ".task answer 2", 112.0)
            self.assertIn("Lights circuit", reply)
            self.assertEqual(red["metadata"]["presses"], 1)
            self.assertEqual(blue["metadata"]["state"], blue_before)
            self.assertEqual(blue["metadata"]["presses"], 0)
            self.assertEqual(game._sabotages["lights"]["state"], "active")
        finally:
            close_game(game)

    def test_selection_applies_the_pattern_and_shows_new_state(self):
        game = make_game()
        try:
            start_scene(game, ("red",))
            chain = puzzles.get_pattern("chain")
            start = puzzles.apply_switch(puzzles.solved_state(chain), chain, 1)
            with mock.patch.object(puzzles, "pick_pattern", return_value=chain), \
                    mock.patch.object(puzzles, "scramble", return_value=start):
                command(game, "red", ".task", 110.0)
            red = game.players["red"].task_in_progress
            ref = red["interaction_ref"]
            reply = command(
                game, "red", "3", 115.0, quoted=f"[Task Ref: {ref}]"
            )
            expected = puzzles.apply_switch(start, chain, 2)
            self.assertEqual(tuple(red["metadata"]["state"]), expected)
            self.assertIn(f"[Task Ref: {ref}]", reply)
            self.assertEqual(red["expires_at"], 115.0 + C.TASK_INTERACTION_TIMEOUT_SECONDS)
            self.assertIn("1 to 5", command(game, "red", ".task answer 9", 116.0))
            self.assertIn("1 to 5", command(game, "red", ".task answer x", 117.0))
            self.assertEqual(red["metadata"]["presses"], 1)
        finally:
            close_game(game)

    def test_solving_the_circuit_is_recorded_and_repairs(self):
        game = make_game()
        try:
            start_scene(game, ("red",))
            ring = puzzles.get_pattern("ring")
            start = puzzles.apply_switch(puzzles.solved_state(ring), ring, 0)
            with mock.patch.object(puzzles, "pick_pattern", return_value=ring), \
                    mock.patch.object(puzzles, "scramble", return_value=start):
                command(game, "red", ".task", 110.0)
            reply = command(game, "red", ".task answer 1", 112.0)
            self.assertIn("Circuit aligned", reply)
            self.assertIn("circuit_solved", [e["type"] for e in game.events])
            self.assertEqual(game._sabotages["lights"]["state"], "repaired")
        finally:
            close_game(game)

    def test_second_task_gets_standard_already_in_progress_reply(self):
        game = make_game()
        try:
            start_scene(game, ("red",))
            command(game, "red", ".task", 110.0)
            ref = game.players["red"].task_in_progress["interaction_ref"]
            again = command(game, "red", ".task", 115.0)
            self.assertIn("already have an active task in progress", again)
            self.assertEqual(
                game.players["red"].task_in_progress["interaction_ref"], ref
            )
            self.assertEqual(len(game._sabotages["lights"]["repair_interactions"]), 1)
        finally:
            close_game(game)

    def test_idle_minute_cancels_only_that_players_attempt(self):
        game = make_game()
        try:
            start_scene(game)
            command(game, "red", ".task", 110.0)
            command(game, "blue", ".task", 150.0)

            game._expire_task_interactions(170.0)  # red idle 60s, blue idle 20s
            self.assertIsNone(game.players["red"].task_in_progress)
            self.assertIsNotNone(game.players["blue"].task_in_progress)
            self.assertEqual(game._sabotages["lights"]["state"], "active")
            self.assertEqual(
                list(game._sabotages["lights"]["repair_interactions"]),
                ["blue"],
            )
            # A cancelled player can start a fresh attempt.
            self.assertIn("Lights circuit", command(game, "red", ".task", 171.0))
        finally:
            close_game(game)

    def test_task_next_abandons_the_puzzle_for_another_task(self):
        game = make_game()
        try:
            start_scene(game, ("red",))
            game.players["red"].tasks = [
                {"id": "t1", "name": "Fix Wiring", "room": "ELECTRICAL", "done": False}
            ]
            command(game, "red", ".task", 110.0)
            reply = command(game, "red", ".task next", 112.0)
            self.assertIn("Fix Wiring", reply)
            self.assertEqual(game._sabotages["lights"]["repair_interactions"], {})
            self.assertEqual(game._sabotages["lights"]["state"], "active")
        finally:
            close_game(game)


if __name__ == "__main__":
    unittest.main()
