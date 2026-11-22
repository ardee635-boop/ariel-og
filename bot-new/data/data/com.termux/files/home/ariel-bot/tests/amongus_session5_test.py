import sys as _s, pathlib as _p
_s.path.insert(0, str(_p.Path(__file__).resolve().parent))
import amongus_testlinks  # noqa: E402,F401
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

from router.amongus import AmongUsManager, Lobby  # noqa: E402
from router.amongus_game import Game, PlayerState  # noqa: E402
from router.amongus_map import get_map  # noqa: E402
from router.amongus_movement import MovementEngine  # noqa: E402


class FakeManager:
    def __init__(self):
        self.sent = []
        self.broadcasts = []

    def _push_dm(self, player, message, **kwargs):
        self.sent.append((player, message))

    def _broadcast(self, message, group_jid=None, tag_all=False, hide_tags=False, **kwargs):
        self.broadcasts.append(
            {
                "message": message,
                "group_jid": group_jid,
                "tag_all": tag_all,
                "hide_tags": hide_tags,
            }
        )


def make_game():
    game = Game.__new__(Game)
    game.manager = FakeManager()
    game.map = get_map()
    game.map_id = game.map.id
    game.events = []
    game.players = {}
    game._bodies = {}
    game._corpses = {}
    game._reported_crime_scenes = []
    game._meltdown = None
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
    for jid in roles:
        player = PlayerState(jid, roles[jid], colors[jid], game.map)
        player.room_entered_at = 0.0
        player.stopped_since = 0.0
        player.room = "CAFETERIA"
        player.tasks = []
        game.players[jid] = player

    game.color_to_jid = {p.color.lower(): p.jid for p in game.players.values()}
    game.movement = MovementEngine(game)

    def add_task(owner, task_id, name, room="CAFETERIA", fake=False):
        task = {
            "id": task_id,
            "room": room,
            "name": name,
            "duration": 5,
            "done": False,
            "owner_jid": owner,
            "fake": fake,
            "claimed_by": None,
        }
        game.players[owner].tasks.append(task)
        if not fake:
            game._team_tasks.append(task)
        return task

    add_task("red", "T0001", "Fix Wiring")
    add_task("red", "T0002", "Empty Garbage")
    add_task("blue", "T0003", "Submit Scan")
    add_task("green", "T0004", "Upload Data", room="MEDBAY")
    add_task("pink", "F0001", "Swipe Card", fake=True)
    return game


def command(game, sender, text, at, quoted_text=None):
    return game.handle(
        sender,
        text,
        received_at_ms=round(at * 1000),
        quoted_text=quoted_text,
    )


def close_game(game):
    game.close()


class FakeLobby:
    def __init__(self, players):
        self.players = players
        self.group_jid = "test-group"
        self.map_id = "skeld"


class AmongUsSessionFiveTests(unittest.TestCase):
    def test_tasks_scale_to_lobby_size_and_impostor_fakes_do_not_score(self):
        small = Game(
            FakeManager(),
            FakeLobby([f"s{i}" for i in range(4)]),
            started_at_ms=1000,
        )
        try:
            crew = [player for player in small.players.values() if player.role != "impostor"]
            impostors = [player for player in small.players.values() if player.role == "impostor"]
            self.assertEqual(len(crew), 3)
            self.assertEqual(len(impostors), 1)
            self.assertTrue(all(len(player.tasks) == 5 for player in crew))
            self.assertEqual(len(small._team_tasks), 15)
            self.assertTrue(all(task["fake"] for task in impostors[0].tasks))
            self.assertNotIn(impostors[0].tasks[0], small._team_tasks)

            for task in small._team_tasks:
                task["done"] = True
            small._resolve_win_check()
            self.assertTrue(small.over)
            self.assertTrue(
                any("Crewmates win" in item["message"]
                    for item in small.manager.broadcasts)
            )
        finally:
            close_game(small)

        large = Game(
            FakeManager(),
            FakeLobby([f"l{i}" for i in range(20)]),
            started_at_ms=2000,
        )
        try:
            crew = [player for player in large.players.values() if player.role != "impostor"]
            self.assertTrue(all(len(player.tasks) == 21 for player in crew))
            self.assertTrue(all(len({task["room"] for task in player.tasks}) < 21
                                for player in crew))
            self.assertEqual(len(large._team_tasks), len(crew) * 21)
        finally:
            close_game(large)

    def test_task_challenge_answer_can_quote_reply_and_sets_cooldown(self):
        game = make_game()
        try:
            prompt = command(game, "red", ".task 1", 1000)
            self.assertIn("[Task Ref: I0001]", prompt)
            self.assertIn("Reply to this message", prompt)
            task = game.players["red"].tasks[0]
            self.assertEqual(task["claimed_by"], "red")

            active_message = command(game, "red", ".task 2", 1001)
            self.assertIn("You already have an active task", active_message)
            wrong = command(game, "red", ".task answer definitely-wrong", 1002)
            self.assertIn("doesn't match", wrong)
            self.assertFalse(task["done"])

            expected = game.players["red"].task_in_progress["expected"]
            manager = AmongUsManager(None, "test-group")
            manager.amongus_on.add("red")
            manager.game = game
            reply = manager._dispatch(
                "red",
                f"ariel {expected}",
                None,
                round(1003 * 1000),
                prompt,
            )
            self.assertIn("*Fix Wiring* complete", reply)
            self.assertTrue(task["done"])
            self.assertIsNone(game.players["red"].task_in_progress)
            self.assertEqual(game.players["red"].task_cooldown_until, 1033)
            self.assertEqual(game._team_task_progress(), (1, 4))

            notice = game.manager.broadcasts[-1]
            self.assertTrue(notice["tag_all"])
            self.assertTrue(notice["hide_tags"])
            self.assertIn("Team tasks: 1/4", notice["message"])
            self.assertIn("27s", command(game, "red", ".task 1", 1006))
        finally:
            close_game(game)

    def test_task_next_rejects_old_quote_and_duplicate_completion(self):
        game = make_game()
        try:
            old_prompt = command(game, "red", ".task 1", 2000)
            next_prompt = command(game, "red", ".task next", 2001)
            self.assertIn("[Task Ref: I0002]", next_prompt)
            self.assertEqual(game.players["red"].task_in_progress["task_id"], "T0002")

            old_reply = command(
                game,
                "red",
                "ariel PULL",
                2002,
                quoted_text=old_prompt,
            )
            self.assertIn("older task prompt", old_reply)
            self.assertEqual(game.players["red"].task_in_progress["task_id"], "T0002")

            answer = game.players["red"].task_in_progress["expected"]
            completed = command(
                game,
                "red",
                f".task answer {answer}",
                2003,
            )
            self.assertIn("*Empty Garbage* complete", completed)
            duplicate = command(
                game,
                "red",
                f"ariel {answer}",
                2004,
                quoted_text=next_prompt,
            )
            self.assertIn("already complete", duplicate)
            self.assertEqual(game._team_task_progress(), (1, 4))
        finally:
            close_game(game)

    def test_inactivity_expires_interaction_and_old_reply_is_stale(self):
        game = make_game()
        try:
            prompt = command(game, "red", ".task 1", 3000)
            task = game.players["red"].tasks[0]
            game.movement.advance_all(3060)
            self.assertIsNone(game.players["red"].task_in_progress)
            self.assertIsNone(task["claimed_by"])
            self.assertTrue(
                any("expired after 60 seconds" in message.lower()
                    for target, message in game.manager.sent if target == "red")
            )
            stale = command(
                game,
                "red",
                "ariel 1 2 3 4",
                3061,
                quoted_text=prompt,
            )
            self.assertIn("stale", stale.lower())
            self.assertFalse(task["done"])
        finally:
            close_game(game)

    def test_movement_and_meeting_reject_task_attempts_without_changing_cooldown(self):
        game = make_game()
        try:
            player = game.players["red"]
            player.task_cooldown_until = 4000
            player.path = ["MEDBAY"]
            moving = command(game, "red", ".task 1", 3500)
            self.assertIn("moving", moving.lower())
            self.assertEqual(player.task_cooldown_until, 4000)

            player.path = None
            player.settled = True
            game._meeting = {"votes": {}, "started_at": 3500}
            meeting = command(game, "red", ".task 1", 3501)
            self.assertIn("meeting", meeting.lower())
            self.assertEqual(player.task_cooldown_until, 4000)
            self.assertIsNone(player.task_in_progress)
        finally:
            close_game(game)

    def test_movement_and_leaving_cancel_active_interactions(self):
        game = make_game()
        try:
            command(game, "red", ".task 1", 5000)
            result = game.movement.move(game.players["red"], "MEDBAY", 5001)
            self.assertIsNone(result[1])
            self.assertIsNone(game.players["red"].task_in_progress)
            self.assertFalse(game.players["red"].tasks[0]["done"])
        finally:
            close_game(game)

        game = make_game()
        try:
            command(game, "red", ".task 1", 6000)
            manager = AmongUsManager(None, "test-group")
            manager.game = game
            manager.lobby = Lobby("test-group", "red")
            manager.lobby.started = True
            manager.amongus_on.add("red")
            manager.pre_dispatch("red", ".amongus off", "test-group")
            self.assertIsNone(game.players["red"].task_in_progress)
            self.assertIsNone(game.players["red"].tasks[0]["claimed_by"])
        finally:
            close_game(game)

    def test_ghost_can_complete_any_available_task_with_50_second_cooldown(self):
        game = make_game()
        try:
            ghost = game.players["blue"]
            ghost.alive = False
            ghost.room = "O2"
            task = game.players["red"].tasks[0]
            self.assertNotIn(task, ghost.tasks)

            prompt = command(game, "blue", ".task 1", 7000)
            self.assertIn("Ghost tasks", command(game, "blue", ".tasks", 7001))
            expected = ghost.task_in_progress["expected"]
            result = command(game, "blue", f".task answer {expected}", 7002)
            self.assertIn("Task complete", result)
            self.assertTrue(task["done"])
            self.assertEqual(ghost.ghost_task_cooldown_until, 7052)
            self.assertIn("49s", command(game, "blue", ".task 1", 7003))
            self.assertIn("Ghost task: 49s", command(game, "blue", ".cooldown", 7003))
            self.assertIn("[Task Ref:", prompt)
        finally:
            close_game(game)

    def test_task_interaction_types_include_fixed_and_puzzle_tasks(self):
        game = make_game()
        try:
            prompt = command(game, "red", ".task 1", 8000)
            self.assertIn("Fix Wiring", prompt)
            self.assertIn("Right terminals", prompt)
            game._cancel_task_interaction(game.players["red"], "abandoned", 8001, notify=False)

            prompt = command(game, "red", ".task 2", 8002)
            self.assertIn("Reply `PULL`", prompt)
            self.assertEqual(
                game.players["red"].task_in_progress["expected"],
                "PULL",
            )
        finally:
            close_game(game)


if __name__ == "__main__":
    unittest.main()
