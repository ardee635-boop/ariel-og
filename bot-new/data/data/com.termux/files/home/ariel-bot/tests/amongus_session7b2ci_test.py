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
        self.broadcast_kwargs = []

    def _push_dm(self, player, message, **kwargs):
        self.sent.append((player, message))

    def _broadcast(self, message, **kwargs):
        self.broadcasts.append(message)
        self.broadcast_kwargs.append(kwargs)

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


import random as _random

from router import amongus_puzzles as PZ  # noqa: E402


def command(game, sender, text, at, quoted=None):
    return game.handle(sender, text, received_at_ms=round(at * 1000),
                       **({"quoted_text": quoted} if quoted else {}))


def to_comms_room(game, jid):
    p = game.players[jid]
    p.room = "COMMUNICATIONS"
    p.reference_room = "COMMUNICATIONS"


def comms_on(game, at=100):
    game._cmd_sabotage(game.players["pink"], "communications", now=at)


def scrambled_from(reply):
    return next(part for part in reply.split("*") if " • " in part)


class AmongUsSessionSevenB2ciTests(unittest.TestCase):
    def test_task_in_communications_posts_scramble_in_group_with_hidetag(self):
        game = make_game()
        try:
            to_comms_room(game, "red")
            comms_on(game)
            reply = command(game, "red", ".task", 110.0)
            self.assertIn("Communications repair", reply)
            scr = scrambled_from(reply)
            self.assertIn(" • ", scr)
            post = [(m, k) for m, k in zip(game.manager.broadcasts,
                                            game.manager.broadcast_kwargs)
                    if "Unscramble: *" in m]
            self.assertEqual(len(post), 1)
            msg, kwargs = post[0]
            self.assertIn(scr, msg)
            self.assertTrue(kwargs.get("hide_tags") and kwargs.get("tag_all"))
            self.assertIn("Red", msg)
            self.assertEqual(
                game.players["red"].task_in_progress["metadata"]["puzzle"], "phrase"
            )
        finally:
            close_game(game)

    def test_nothing_starts_outside_the_room_or_without_an_outage(self):
        game = make_game()
        try:
            # right room, no outage
            to_comms_room(game, "red")
            self.assertNotIn("Communications repair", command(game, "red", ".task", 110.0) or "")
            self.assertIsNone(game.players["red"].task_in_progress)
            # outage, wrong room
            comms_on(game)
            self.assertNotIn("Communications repair", command(game, "blue", ".task", 111.0) or "")
            self.assertIsNone(game.players["blue"].task_in_progress)
            # ghosts cannot repair
            game.players["red"].alive = False
            self.assertNotIn("Communications repair", command(game, "red", ".task", 112.0) or "")
        finally:
            close_game(game)

    def test_correct_phrase_repairs_immediately_and_unlocks(self):
        game = make_game()
        try:
            to_comms_room(game, "red")
            comms_on(game)
            command(game, "red", ".task", 110.0)
            expected = PZ.get_phrase(
                game.players["red"].task_in_progress["metadata"]["phrase_id"]
            ).text
            reply = command(game, "red", f".task answer {expected}", 115.0)
            self.assertIn("Communications repaired", reply)
            self.assertEqual(game._sabotages["communications"]["state"], "repaired")
            self.assertIsNone(game.players["red"].task_in_progress)
            self.assertEqual(game.manager.locks[-1][0], False)
            self.assertEqual(len([m for m in game.manager.broadcasts
                                  if "activity report" in m]), 1)
        finally:
            close_game(game)

    def test_variant_with_different_punctuation_repairs(self):
        game = make_game()
        try:
            to_comms_room(game, "red")
            comms_on(game)
            command(game, "red", ".task", 110.0)
            active = game.players["red"].task_in_progress
            phrase = PZ.get_phrase(active["metadata"]["phrase_id"])
            variant = (phrase.variants or (phrase.text,))[0]
            noisy = "  ✨ " + variant.upper().replace(" ", " ,, ") + " !!! "
            reply = command(game, "red", ".task answer " + noisy, 115.0)
            self.assertIn("repaired", reply)
        finally:
            close_game(game)

    def test_wrong_phrase_keeps_it_active_allows_retry_and_resets_timer(self):
        game = make_game()
        try:
            to_comms_room(game, "red")
            comms_on(game)
            command(game, "red", ".task", 110.0)
            active = game.players["red"].task_in_progress
            reply = command(game, "red", ".task answer totally wrong", 150.0)
            self.assertIn("not the intended phrase", reply)
            self.assertIn(active["metadata"]["scrambled"], reply)
            self.assertEqual(game._sabotages["communications"]["state"], "active")
            self.assertEqual(active["expires_at"], 150.0 + C.TASK_INTERACTION_TIMEOUT_SECONDS)
            # The scrambled text itself is not an answer.
            reply = command(game, "red", ".task answer " + active["metadata"]["scrambled"], 151.0)
            self.assertIn("not the intended phrase", reply)
            good = PZ.get_phrase(active["metadata"]["phrase_id"]).text
            self.assertIn("repaired", command(game, "red", ".task answer " + good, 160.0))
            attempts = [e for e in game.events if e["type"] == "phrase_answer"]
            self.assertEqual([e["correct"] for e in attempts], [False, False, True])
        finally:
            close_game(game)

    def test_one_minute_inactivity_cancels_only_that_attempt(self):
        game = make_game()
        try:
            to_comms_room(game, "red")
            to_comms_room(game, "blue")
            comms_on(game)
            command(game, "red", ".task", 110.0)
            command(game, "blue", ".task", 140.0)
            game._expire_task_interactions(171.0)
            self.assertIsNone(game.players["red"].task_in_progress)   # 110+60 passed
            self.assertIsNotNone(game.players["blue"].task_in_progress)  # until 200
            self.assertEqual(game._sabotages["communications"]["state"], "active")
            self.assertEqual(
                list(game._sabotages["communications"]["repair_interactions"]), ["blue"]
            )
        finally:
            close_game(game)

    def test_no_duplicate_interaction_per_player_and_task_next_switches(self):
        game = make_game()
        try:
            to_comms_room(game, "red")
            comms_on(game)
            command(game, "red", ".task", 110.0)
            first = game.players["red"].task_in_progress["interaction_ref"]
            again = command(game, "red", ".task", 111.0)
            self.assertIn("already have an active task", again)
            self.assertEqual(game.players["red"].task_in_progress["interaction_ref"], first)
            self.assertEqual(
                len(game._sabotages["communications"]["repair_interactions"]), 1
            )
        finally:
            close_game(game)

    def test_two_players_get_different_phrases_and_one_repair_clears_the_other(self):
        game = make_game()
        try:
            for jid in ("red", "blue"):
                to_comms_room(game, jid)
            comms_on(game)
            game._phrase_rng = _random.Random(2)
            command(game, "red", ".task", 110.0)
            command(game, "blue", ".task", 111.0)
            red = game.players["red"].task_in_progress
            blue = game.players["blue"].task_in_progress
            self.assertNotEqual(red["metadata"]["phrase_id"], blue["metadata"]["phrase_id"])

            good = PZ.get_phrase(blue["metadata"]["phrase_id"]).text
            self.assertIn("repaired", command(game, "blue", ".task answer " + good, 120.0))
            self.assertIsNone(game.players["red"].task_in_progress)
            self.assertEqual(game._sabotages["communications"]["repair_interactions"], {})
            late = PZ.get_phrase(red["metadata"]["phrase_id"]).text
            self.assertNotIn("repaired", command(game, "red", ".task answer " + late, 121.0) or "")
        finally:
            close_game(game)

    def test_movement_cancels_the_attempt_and_comms_stays_active(self):
        game = make_game()
        try:
            to_comms_room(game, "red")
            comms_on(game)
            command(game, "red", ".task", 110.0)
            command(game, "red", ".m storage", 111.0)
            self.assertIsNone(game.players["red"].task_in_progress)
            self.assertEqual(game._sabotages["communications"]["state"], "active")
            self.assertEqual(game._sabotages["communications"]["repair_interactions"], {})
        finally:
            close_game(game)

    def test_lights_repair_still_works_and_does_not_touch_comms(self):
        game = make_game()
        try:
            game.players["red"].room = "ELECTRICAL"
            game.players["red"].reference_room = "ELECTRICAL"
            to_comms_room(game, "blue")
            game._cmd_sabotage(game.players["pink"], "lights", now=100)
            comms_on(game)
            self.assertIn("Lights repair", command(game, "red", ".task", 110.0))
            self.assertIn("Communications repair", command(game, "blue", ".task", 111.0))
        finally:
            close_game(game)

    def test_repair_needs_no_debug_command_and_game_end_cancels(self):
        game = make_game()
        try:
            to_comms_room(game, "red")
            comms_on(game)
            command(game, "red", ".task", 110.0)
            game._end_game("over")
            self.assertIsNone(game.players["red"].task_in_progress)
            self.assertEqual(game._sabotages["communications"]["state"], "idle")
        finally:
            close_game(game)


if __name__ == "__main__":
    unittest.main()
