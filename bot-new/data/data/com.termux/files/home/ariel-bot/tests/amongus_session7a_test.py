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
from router.amongus_sabotage import SABOTAGE_NAMES, Sabotage  # noqa: E402
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
    game._sabotages = {
        name: Sabotage(name, C.SABOTAGE_COOLDOWNS_SECONDS[name])
        for name in SABOTAGE_NAMES
    }
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


class AmongUsSessionSevenATests(unittest.TestCase):
    def test_sabotage_command_stays_private_and_activates_from_dm(self):
        game = make_game()
        try:
            router_manager = AmongUsManager(FakeRouter(), GAME_GROUP)
            router_manager.amongus_on.add("pink")
            router_manager.game = game

            group_reply = router_manager._dispatch(
                "pink", ".sabotage lights", GAME_GROUP
            )
            self.assertIn("commands are private", group_reply)
            self.assertEqual(game._sabotages["lights"]["state"], "idle")

            dm_reply = router_manager._dispatch(
                "pink", ".sabotage lights", None, received_at_ms=100_000
            )
            self.assertIsNone(dm_reply)
            self.assertEqual(game._sabotages["lights"]["state"], "active")
            self.assertTrue(
                any("LIGHTS SABOTAGED!" in message
                    for message in game.manager.broadcasts)
            )
            self.assertTrue(
                all("pink" not in message and GAME_GROUP not in message
                    for message in game.manager.broadcasts)
            )
        finally:
            close_game(game)

    def test_sabotages_have_independent_activation_cooldowns_and_repairs(self):
        game = make_game()
        try:
            impostor = game.players["pink"]
            self.assertIsNone(game._cmd_sabotage(impostor, "lights", now=100))
            self.assertIsNone(
                game._cmd_sabotage(impostor, "communications", now=100)
            )
            self.assertEqual(
                [name for name, state in game._sabotages.items()
                 if state["state"] == "active"],
                ["lights", "communications"],
            )

            self.assertTrue(
                game._repair_sabotage("lights", game.players["red"], now=110)
            )
            self.assertEqual(game._sabotages["lights"]["state"], "repaired")
            self.assertEqual(game._sabotages["communications"]["state"], "active")
            cooldowns = game._cmd_cooldowns(impostor, now=120)
            self.assertIn("Lights sabotage: 160s", cooldowns)
            self.assertIn("Communications sabotage: 160s", cooldowns)
            self.assertIn("sabotage_activated", [event["type"] for event in game.events])
            self.assertIn("sabotage_repaired", [event["type"] for event in game.events])

            refusal = game._cmd_sabotage(impostor, "lights", now=120)
            self.assertIn("cooldown: 160s", refusal)
        finally:
            close_game(game)

    def test_repair_uses_shared_task_interaction_and_timeout_lifecycle(self):
        game = make_game()
        try:
            impostor = game.players["pink"]
            player = game.players["red"]
            game._cmd_sabotage(impostor, "lights", now=100)
            prompt = game._start_sabotage_repair_interaction(
                player, "lights", "Reply YES to confirm.", "YES", now=101
            )
            self.assertIn("[Task Ref:", prompt)
            self.assertEqual(
                player.task_in_progress["kind"], "sabotage_repair"
            )
            self.assertEqual(
                game._start_sabotage_repair_interaction(
                    player, "lights", "Another prompt", "YES", now=102
                ),
                "⚠️ _You already have an active interaction. Use `.task next` to switch._",
            )

            wrong = game._cmd_task_reply(
                player, ".task answer NO", now=103
            )
            self.assertIn("doesn't match", wrong)
            self.assertEqual(player.task_in_progress["expires_at"], 163)

            right = game._cmd_task_reply(
                player, ".task answer YES", now=104
            )
            self.assertIn("repaired", right)
            self.assertIsNone(player.task_in_progress)
            self.assertEqual(game._sabotages["lights"]["state"], "repaired")
        finally:
            close_game(game)

    def test_timeout_cancels_only_the_repair_attempt(self):
        game = make_game()
        try:
            game._cmd_sabotage(game.players["pink"], "communications", now=100)
            player = game.players["red"]
            game._start_sabotage_repair_interaction(
                player, "communications", "Reply OK.", "OK", now=101
            )

            game._expire_task_interactions(161)

            self.assertIsNone(player.task_in_progress)
            self.assertEqual(game._sabotages["communications"]["state"], "active")
            self.assertEqual(
                game._sabotages["communications"]["repair_interactions"], {}
            )
            self.assertTrue(
                any(event["type"] == "sabotage_repair_cancelled"
                    for event in game.events)
            )
        finally:
            close_game(game)

    def test_task_next_can_switch_away_from_a_repair_interaction(self):
        game = make_game()
        try:
            game._cmd_sabotage(game.players["pink"], "lights", now=100)
            player = game.players["red"]
            player.tasks = [
                {
                    "id": "T001",
                    "room": "CAFETERIA",
                    "name": "Swipe Card",
                    "duration": 1,
                    "done": False,
                    "owner_jid": player.jid,
                    "fake": False,
                    "claimed_by": None,
                }
            ]
            game._team_tasks = player.tasks
            game._start_sabotage_repair_interaction(
                player, "lights", "Reply OK.", "OK", now=101
            )

            response = game._cmd_task_next(player, now=102)

            self.assertIn("Swipe Card", response)
            self.assertEqual(
                player.task_in_progress.get("kind", "task"), "task"
            )
            self.assertEqual(game._sabotages["lights"]["state"], "active")
            self.assertEqual(game._sabotages["lights"]["repair_interactions"], {})
        finally:
            close_game(game)

    def test_timed_sabotage_warns_and_fails_from_world_time(self):
        game = make_game()
        try:
            sabotage = game._sabotages["oxygen"]
            sabotage.activate(100, deadline=140)

            game._advance_sabotages(120)
            game._advance_sabotages(130)
            self.assertEqual(
                game.manager.broadcasts,
                [
                    "⚠️ *O₂: 20s remaining.*\nReach the required station(s) and finish the repair.",
                    "⚠️ *O₂: 10s remaining.*\nReach the required station(s) and finish the repair.",
                ],
            )
            game._advance_sabotages(140)
            # Exactly at the deadline still counts for the crew (7C tie rule).
            self.assertFalse(game.over)
            game._advance_sabotages(140.01)

            self.assertTrue(game.over)
            self.assertEqual(sabotage["state"], "failed")
            # Session 09 pkg 2: a failure is stamped at the deadline itself.
            self.assertEqual(sabotage["failed_at"], 140.0)
            self.assertIn("sabotage_failed", [event["type"] for event in game.events])
            self.assertIn("game_ended", [event["type"] for event in game.events])
            self.assertIn("o₂ depleted — impostors win", game.manager.broadcasts[-1].lower())
        finally:
            close_game(game)

    def test_meeting_pauses_deadline_but_not_cooldown(self):
        game = make_game()
        try:
            sabotage = game._sabotages["reactor"]
            sabotage.activate(100, deadline=140)
            game._advance_sabotages(120)

            game._cmd_call_meeting(game.players["red"], "emergency", now=121)
            self.assertEqual(sabotage["paused_remaining"], 19)
            cooldown_until = sabotage["cooldown_until"]
            game._advance_sabotages(150)
            self.assertEqual(sabotage["state"], "active")

            game._resolve_meeting(now=181)
            self.assertEqual(sabotage["deadline"], 200)
            self.assertEqual(sabotage["cooldown_until"], cooldown_until)
            game._advance_sabotages(199.99)
            self.assertEqual(sabotage["state"], "active")
            game._advance_sabotages(200)
            self.assertEqual(sabotage["state"], "active")
            game._advance_sabotages(200.01)
            self.assertEqual(sabotage["state"], "failed")
        finally:
            close_game(game)

    def test_game_end_cancels_sabotage_interactions_and_timers(self):
        game = make_game()
        try:
            sabotage = game._sabotages["lights"]
            sabotage.activate(100)
            game._start_sabotage_repair_interaction(
                game.players["red"], "lights", "Reply OK.", "OK", now=101
            )
            timer = game._schedule(
                60, lambda: game.manager._broadcast("late timer")
            )

            game._end_game("Game ended.")
            broadcast_count = len(game.manager.broadcasts)
            game._advance_sabotages(1000)
            timer.join(timeout=0.1)

            self.assertFalse(timer.is_alive())
            self.assertEqual(sabotage["state"], "idle")
            self.assertIsNone(sabotage["deadline"])
            self.assertIsNone(game.players["red"].task_in_progress)
            self.assertEqual(len(game.manager.broadcasts), broadcast_count)
            self.assertFalse(game._timers)
        finally:
            close_game(game)


if __name__ == "__main__":
    unittest.main()
