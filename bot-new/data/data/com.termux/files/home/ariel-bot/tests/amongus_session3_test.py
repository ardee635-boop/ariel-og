import sys
import threading
import time
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

from router.amongus_game import Game, PlayerState  # noqa: E402
from router.amongus_map import get_map  # noqa: E402
from router.amongus_movement import MovementEngine  # noqa: E402


class FakeManager:
    def __init__(self):
        self.sent = []
        self.broadcasts = []

    def _push_dm(self, player, message, **kwargs):
        self.sent.append((player, message))

    def _broadcast(self, message, **kwargs):
        self.broadcasts.append(message)


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
    game.over = False
    game.lock = threading.RLock()
    game._stop_event = threading.Event()
    game._timers = set()
    game._meeting = None
    for jid, color in (
        ("red", "Red"),
        ("blue", "Blue"),
        ("green", "Green"),
        ("pink", "Pink"),
    ):
        player = PlayerState(jid, "crewmate", color, game.map)
        player.room_entered_at = 0.0
        player.stopped_since = 0.0
        game.players[jid] = player
    game.color_to_jid = {p.color.lower(): p.jid for p in game.players.values()}
    game.movement = MovementEngine(game)
    return game


def command(game, sender, text, at):
    return game.handle(sender, text, received_at_ms=round(at * 1000))


def messages_for(game, player):
    return [text for target, text in game.manager.sent if target == player]


class AmongUsSessionThreeTests(unittest.TestCase):
    def test_status_shows_current_room_and_marks_body_witness(self):
        game = make_game()
        try:
            game.players["green"].room = "ADMIN"
            game.players["pink"].room = "ELECTRICAL"
            victim = game.players["blue"]
            victim.alive = False
            victim.death_room = "CAFETERIA"
            game._bodies["CAFETERIA"] = ["blue"]
            game._corpses["blue"] = {
                "victim_jid": "blue",
                "victim_color": "Blue",
                "room": "CAFETERIA",
                "killer_jid": "pink",
                "witnesses": [],
                "reported": False,
            }

            status = command(game, "red", ".status", 10.0)

            self.assertIn("Status", status)
            self.assertIn("Players with you: None", status)
            self.assertNotIn("Green", status)
            self.assertIn("Bodies here: Blue", status)
            self.assertEqual(game._corpses["blue"]["witnesses"], ["red"])
            self.assertEqual(
                sum(event["type"] == "corpse_witnessed" for event in game.events),
                1,
            )
        finally:
            game.close()

    def test_camping_waits_for_observer_and_warns_only_once(self):
        game = make_game()
        try:
            red = game.players["red"]
            red.stopped_since = 0.0
            for jid, room in (
                ("blue", "ADMIN"),
                ("green", "ELECTRICAL"),
                ("pink", "WEAPONS"),
            ):
                game.players[jid].room = room
                game.players[jid].stopped_since = 0.0

            game.movement.advance_all(60.0)
            self.assertFalse(any(e["type"] == "camping_awareness" for e in game.events))
            self.assertFalse(any("other players are onto you" in text.lower()
                                 for text in messages_for(game, "red")))

            blue = game.players["blue"]
            blue.room = "CAFETERIA"
            blue.stopped_since = 60.0
            game.movement.advance_all(60.1)
            game.movement.advance_all(62.0)

            self.assertTrue(red.camping_notified)
            self.assertEqual(
                sum(e["type"] == "camping_awareness" for e in game.events),
                1,
            )
            self.assertEqual(
                sum("other players are onto you" in text.lower()
                    for text in messages_for(game, "red")),
                1,
            )
            self.assertTrue(
                any("Red" in text and "stationary" in text
                    for text in messages_for(game, "blue"))
            )
        finally:
            game.close()

    def test_camping_timer_resets_after_new_stop_location(self):
        game = make_game()
        try:
            red = game.players["red"]
            red.stopped_since = 0.0
            red.camping_notified = True
            for jid, room in (
                ("blue", "ADMIN"),
                ("green", "ELECTRICAL"),
                ("pink", "WEAPONS"),
            ):
                game.players[jid].room = room
                game.players[jid].stopped_since = 0.0

            command(game, "red", ".m storage", 10.0)
            self.assertIsNone(red.stopped_since)
            self.assertFalse(red.camping_notified)
            game.movement.advance_all(11.0)
            command(game, "red", ".stop", 13.5)

            self.assertEqual(red.stopped_since, 13.5)
            self.assertFalse(red.camping_notified)
            game.movement.advance_all(73.4)
            self.assertFalse(any(e["type"] == "camping_awareness" for e in game.events))
        finally:
            game.close()

    def test_camping_observer_can_be_elsewhere_on_same_corridor(self):
        game = make_game()
        try:
            red = game.players["red"]
            blue = game.players["blue"]
            red.settled = False
            red.path = None
            red.corridor_from = "CAFETERIA"
            red.corridor_to = "STORAGE"
            red.corridor_length = 5.0
            red.corridor_progress_at_start = 2.5
            red.corridor_started_at = None
            red.stopped_since = 0.0

            blue.settled = False
            blue.path = None
            blue.corridor_from = "CAFETERIA"
            blue.corridor_to = "STORAGE"
            blue.corridor_length = 5.0
            blue.corridor_progress_at_start = 0.0
            blue.corridor_started_at = None
            blue.stopped_since = 70.0
            for jid, room in (("green", "ADMIN"), ("pink", "ELECTRICAL")):
                game.players[jid].room = room

            game.movement.advance_all(60.0)

            self.assertTrue(red.camping_notified)
            self.assertEqual(
                sum(e["type"] == "camping_awareness" for e in game.events),
                1,
            )
        finally:
            game.close()

    def test_follow_tracks_target_across_room_change(self):
        game = make_game()
        try:
            for player in game.players.values():
                player.stopped_since = 1000.0
            game.players["green"].room = "ADMIN"
            game.players["pink"].room = "ELECTRICAL"

            response = command(game, "red", ".follow blue", 1000.0)
            self.assertIn("following *Blue*", response)
            self.assertEqual(game.players["red"].following, "blue")

            command(game, "blue", ".m admin", 1001.0)
            game.movement.advance_all(1002.0)
            self.assertEqual(game.players["red"].following, "blue")
            self.assertTrue(game.players["red"].path)

            game.movement.advance_all(1009.0)
            self.assertTrue(game.players["blue"].settled)
            self.assertTrue(game.players["red"].settled)
            self.assertEqual(game.players["blue"].room, "ADMIN")
            self.assertEqual(game.players["red"].room, "ADMIN")
            self.assertEqual(game.players["red"].following, "blue")
            self.assertTrue(
                any("arrived at" in text for text in messages_for(game, "red"))
            )
        finally:
            game.close()

    def test_status_reveals_nearby_follower_before_25_seconds(self):
        game = make_game()
        try:
            for player in game.players.values():
                player.stopped_since = 2000.0
            game.players["green"].room = "ADMIN"
            game.players["pink"].room = "ELECTRICAL"

            command(game, "red", ".follow blue", 2000.0)
            status = command(game, "blue", ".status", 2001.0)

            self.assertIn("Following you: Red", status)
            self.assertTrue(game.players["red"].follow_discovered)
            self.assertTrue(
                any("noticed" in text.lower() and "Red" in text
                    for text in messages_for(game, "blue"))
            )
            game.movement.advance_all(2030.0)
            self.assertFalse(
                any("you are being followed" in text.lower()
                    for text in messages_for(game, "blue"))
            )
        finally:
            game.close()

    def test_follow_reveals_after_25_seconds_and_unfollow_notifies_target(self):
        game = make_game()
        try:
            for player in game.players.values():
                player.stopped_since = 3000.0
            game.players["green"].room = "ADMIN"
            game.players["pink"].room = "ELECTRICAL"

            command(game, "red", ".follow blue", 3000.0)
            game.movement.advance_all(3024.9)
            self.assertFalse(
                any("you are being followed" in text.lower()
                    for text in messages_for(game, "blue"))
            )
            game.movement.advance_all(3025.0)
            self.assertTrue(
                any("you are being followed by" in text.lower()
                    for text in messages_for(game, "blue"))
            )

            command(game, "red", ".unfollow", 3026.0)
            self.assertIsNone(game.players["red"].following)
            self.assertTrue(
                any("loses interest" in text.lower()
                    for text in messages_for(game, "blue"))
            )
        finally:
            game.close()

    def test_follow_ends_on_vent_or_still_action(self):
        game = make_game()
        try:
            for player in game.players.values():
                player.stopped_since = 4000.0
            game.players["green"].room = "ADMIN"
            game.players["pink"].room = "ELECTRICAL"
            blue = game.players["blue"]
            blue.room = "ELECTRICAL"
            blue.role = "impostor"
            red = game.players["red"]
            red.room = "ELECTRICAL"
            red.reference_room = "ELECTRICAL"

            command(game, "red", ".follow blue", 4000.0)
            command(game, "blue", ".vent in", 4001.0)
            self.assertIsNone(red.following)
            self.assertTrue(
                any("lost their trail" in text.lower()
                    for text in messages_for(game, "red"))
            )

            blue.in_vent_until = None
            blue.vent_dest = None
            blue.settled = True
            blue.room = "CAFETERIA"
            red.room = "CAFETERIA"
            red.settled = True
            red.stopped_since = 4100.0
            blue.stopped_since = 4100.0
            command(game, "red", ".follow blue", 4100.0)
            command(game, "red", ".task 1", 4101.0)
            self.assertIsNone(red.following)
        finally:
            game.close()

    def test_reported_crime_scene_persists_and_witnesses_are_retained(self):
        game = make_game()
        try:
            for player in game.players.values():
                player.stopped_since = time.time()
            killer = game.players["red"]
            victim = game.players["blue"]
            killer.role = "impostor"

            game._resolve_kill(killer, victim, [])
            self.assertFalse(victim.alive)
            self.assertEqual(game._bodies["CAFETERIA"], ["blue"])
            self.assertEqual(
                set(game._corpses["blue"]["witnesses"]),
                {"green", "pink"},
            )
            victim_messages = messages_for(game, "blue")
            self.assertFalse(any("Red" in text or "red" in text for text in victim_messages))

            status = command(game, "green", ".status", time.time())
            self.assertIn("Bodies here: Blue", status)
            command(game, "green", ".report", time.time() + 0.1)
            self.assertNotIn("CAFETERIA", game._bodies)

            scenes = command(game, "green", ".cscene", time.time() + 0.2)
            self.assertIn("Cafeteria — Blue", scenes)
            self.assertIn("green", game._corpses["blue"]["witnesses"])
            self.assertTrue(game._corpses["blue"]["reported"])

            game._resolve_meeting()
            self.assertIn("Cafeteria — Blue", game._cmd_crime_scenes())
        finally:
            game.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
