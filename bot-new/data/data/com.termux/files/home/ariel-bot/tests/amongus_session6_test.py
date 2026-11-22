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

from router.amongus import (  # noqa: E402
    DELETE_INCOMING_MESSAGE,
    AmongUsCoordinator,
    AmongUsManager,
    Lobby,
)
from router import amongus_config as _C  # noqa: E402
from router.amongus_config import MEETING_VOTE_SECONDS  # noqa: E402

_C.EJECTION_REVEAL_STEP_SECONDS = 0.0   # staged result gaps are real timers; collapse them here
from router.amongus_game import Game, PlayerState  # noqa: E402
from router.amongus_map import get_map  # noqa: E402
from router.amongus_movement import MovementEngine  # noqa: E402


GAME_GROUP = "game@g.us"
GHOST_GROUP = "ghosts@g.us"


class FakeManager:
    def __init__(self):
        self.sent = []
        self.broadcasts = []
        self.ghost_messages = []

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

    def _push_ghost_chat(self, game, sender, message):
        self.ghost_messages.append((sender, message))


class FakeRouter:
    def __init__(self):
        self.sent = []

    def _direct_send(self, message, group_jid=None, **kwargs):
        self.sent.append((group_jid, message, kwargs))


class FakeLobby:
    def __init__(self, players, group_jid=GAME_GROUP, host=None):
        self.players = list(players)
        self.group_jid = group_jid
        self.map_id = "skeld"
        self.host = host or self.players[0]
        self.started = True


def make_game(manager=None):
    game = Game.__new__(Game)
    game.manager = manager or FakeManager()
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
    return game


def close_game(game):
    game.close()


class AmongUsSessionSixTests(unittest.TestCase):
    def test_report_only_reports_bodies_the_player_witnessed(self):
        game = make_game()
        try:
            game._bodies["CAFETERIA"] = ["blue", "green"]
            game._corpses = {
                "blue": {
                    "victim_jid": "blue",
                    "victim_color": "Blue",
                    "room": "CAFETERIA",
                    "killer_jid": "pink",
                    "witnesses": ["red"],
                    "reported": False,
                },
                "green": {
                    "victim_jid": "green",
                    "victim_color": "Green",
                    "room": "CAFETERIA",
                    "killer_jid": "pink",
                    "witnesses": ["blue"],
                    "reported": False,
                },
            }

            self.assertIsNone(game._cmd_report(game.players["red"], now=100))
            self.assertTrue(game._corpses["blue"]["reported"])
            self.assertFalse(game._corpses["green"]["reported"])
            self.assertEqual(game._bodies["CAFETERIA"], ["green"])
            report_notice = next(
                item["message"]
                for item in game.manager.broadcasts
                if "found a corpse in" in item["message"]
            )
            self.assertIn("Blue", report_notice)
            self.assertNotIn("Green", report_notice)
            self.assertIsNotNone(game._meeting)
        finally:
            close_game(game)

    def test_report_rejects_unwitnessed_body_without_revealing_it(self):
        game = make_game()
        try:
            game._bodies["CAFETERIA"] = ["blue"]
            game._corpses["blue"] = {
                "victim_jid": "blue",
                "victim_color": "Blue",
                "room": "CAFETERIA",
                "killer_jid": "pink",
                "witnesses": [],
                "reported": False,
            }

            response = game._cmd_report(game.players["red"], now=100)
            self.assertIn("haven't witnessed", response)
            self.assertIsNone(game._meeting)
            self.assertEqual(game.manager.broadcasts, [])
            self.assertFalse(game._corpses["blue"]["reported"])
        finally:
            close_game(game)

    def test_votes_are_private_changeable_and_accept_colours(self):
        game = make_game()
        try:
            game._cmd_call_meeting(game.players["red"], "emergency", now=100)
            first = game.handle_gc_vote(
                "red",
                ".vote Green",
                received_at_ms=161_000,
            )
            self.assertEqual(first, DELETE_INCOMING_MESSAGE)
            self.assertEqual(game._meeting["votes"]["red"], "green")
            self.assertIn("vote is registered privately", game.manager.sent[-1][1])

            changed = game.handle_gc_vote(
                "red",
                ".vote Blue",
                received_at_ms=162_000,
            )
            self.assertEqual(changed, DELETE_INCOMING_MESSAGE)
            self.assertEqual(game._meeting["votes"]["red"], "blue")
            self.assertIn("vote was changed", game.manager.sent[-1][1])
            self.assertFalse(
                any(
                    "Green" in item["message"] or "Blue" in item["message"]
                    for item in game.manager.broadcasts
                )
            )

            game._resolve_meeting(now=100 + MEETING_VOTE_SECONDS)
            self.assertTrue(game.players["blue"].alive is False)
            result = game.manager.broadcasts[-1]["message"]
            self.assertIn("Blue was ejected.", result)
            self.assertNotIn("Red voted", result)
        finally:
            close_game(game)

    def test_skip_tied_with_a_player_prevents_ejection(self):
        game = make_game()
        try:
            game._cmd_call_meeting(game.players["red"], "emergency", now=100)
            game._cmd_vote(game.players["red"], "Blue", public=False, now=161)
            game._cmd_vote(game.players["blue"], "skip", public=False, now=162)
            game._resolve_meeting(now=100 + MEETING_VOTE_SECONDS)

            self.assertTrue(game.players["blue"].alive)
            self.assertIn("No one was ejected.", game.manager.broadcasts[-1]["message"])
        finally:
            close_game(game)

    def test_skip_with_the_most_votes_prevents_ejection(self):
        game = make_game()
        try:
            game._cmd_call_meeting(game.players["red"], "emergency", now=100)
            game._cmd_vote(game.players["red"], "skip", public=False, now=161)
            game._cmd_vote(game.players["blue"], "skip", public=False, now=162)
            game._cmd_vote(game.players["green"], "Blue", public=False, now=163)
            game._resolve_meeting(now=100 + MEETING_VOTE_SECONDS)

            self.assertTrue(game.players["blue"].alive)
            self.assertIn("No one was ejected.", game.manager.broadcasts[-1]["message"])
        finally:
            close_game(game)

    def test_departure_removes_voter_and_target_from_meeting(self):
        game = make_game()
        try:
            game._cmd_call_meeting(game.players["red"], "emergency", now=100)
            game._cmd_vote(game.players["red"], "Green", public=False, now=161)
            game.mark_departed("green", now=162)
            self.assertNotIn("green", game._meeting["votes"].values())
            self.assertIn(
                "active player's colour",
                game._cmd_vote(game.players["blue"], "Green", public=False, now=163),
            )
            game._resolve_meeting(now=100 + MEETING_VOTE_SECONDS)

            self.assertTrue(game.players["green"].alive)
            self.assertTrue(game.players["green"].departed)
            self.assertIn("No one was ejected.", game.manager.broadcasts[-1]["message"])
        finally:
            close_game(game)

    def test_meeting_pauses_movement_and_sabotage_deadline(self):
        game = make_game()
        try:
            player = game.players["red"]
            game.movement.move(player, "MEDBAY", 100)
            game.movement.advance_all(100.25)
            oxygen = game._get_sabotage("oxygen")
            oxygen.activate(100.25, deadline=110.25)

            game._cmd_call_meeting(player, "emergency", now=100.25)
            game.movement.advance_all(110)
            self.assertEqual(player.room, "CAFETERIA")
            self.assertIsNotNone(player.pending_departure_at)
            self.assertEqual(oxygen["paused_remaining"], 10)
            game._advance_sabotages(150)
            self.assertFalse(game.over)

            game._resolve_meeting(now=160.25)
            self.assertAlmostEqual(oxygen["deadline"], 170.25)
            self.assertAlmostEqual(player.pending_departure_at, 161.0)
            game.movement.advance_all(160.99)
            self.assertEqual(player.room, "CAFETERIA")
            game.movement.advance_all(161.0)
            self.assertFalse(player.settled)
        finally:
            close_game(game)

    def test_ghost_travel_time_is_half_and_ghost_can_move(self):
        game = make_game()
        try:
            ghost = game.players["blue"]
            ghost.alive = False
            living = game.players["red"]
            living_eta, error = game.movement.move(living, "MEDBAY", 100)
            self.assertIsNone(error)
            ghost_eta, error = game.movement.move(ghost, "MEDBAY", 100)
            self.assertIsNone(error)
            self.assertEqual(ghost_eta, living_eta / 2)

            game.movement.advance_all(100.5)
            self.assertIsNotNone(ghost.corridor_started_at)
            self.assertIsNotNone(living.pending_departure_at)
            game.movement.advance_all(102.5)
            self.assertEqual(ghost.room, "MEDBAY")
            self.assertEqual(living.room, "CAFETERIA")
        finally:
            close_game(game)

    def test_ghost_messages_are_kept_out_of_the_living_group(self):
        router = FakeRouter()
        manager = AmongUsManager(router, GAME_GROUP)
        game = make_game(manager)
        manager.game = game
        manager.lobby = FakeLobby(game.players, host="red")
        manager._ghosts_group_jid = GHOST_GROUP
        coordinator = AmongUsCoordinator(router)
        coordinator._groups[GAME_GROUP] = manager
        try:
            game.players["blue"].alive = False
            self.assertTrue(coordinator.should_intercept_group("blue", "hello", GAME_GROUP))
            self.assertEqual(
                coordinator.pre_dispatch("blue", "hello", GAME_GROUP),
                DELETE_INCOMING_MESSAGE,
            )
            self.assertIsNone(
                coordinator.pre_dispatch("blue", "hello", GHOST_GROUP)
            )
            self.assertEqual(
                coordinator.pre_dispatch("red", "hello", GHOST_GROUP),
                DELETE_INCOMING_MESSAGE,
            )

            game._end_game()
            self.assertEqual(coordinator.ghost_group_ids(), [])
            self.assertIsNone(manager._ghosts_group_jid)
        finally:
            close_game(game)

    def test_setghostgroup_is_retired_in_favour_of_the_registry(self):
        # Session 09 pkg 6b: `.setghostgroup` no longer exists; the owner's
        # `.set aghostgc` registry replaces it (see amongus_session9_pkg6b_test).
        router = FakeRouter()
        coordinator = AmongUsCoordinator(router)
        manager = AmongUsManager(router, GAME_GROUP)
        manager.lobby = FakeLobby(["red", "blue"], host="red")
        manager.game = make_game(manager)
        coordinator._groups[GAME_GROUP] = manager
        self.assertFalse(coordinator.should_intercept_group("red", ".setghostgroup", GHOST_GROUP))
        coordinator.pre_dispatch("red", ".setghostgroup", GHOST_GROUP)
        self.assertIsNone(manager._ghosts_group_jid)


if __name__ == "__main__":
    unittest.main()
