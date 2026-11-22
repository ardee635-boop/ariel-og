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

from router.amongus_game import Game, PlayerState  # noqa: E402
from router.amongus_map import get_map  # noqa: E402
from router.amongus_movement import MovementEngine  # noqa: E402


class FakeManager:
    def __init__(self):
        self.sent = []

    def _push_dm(self, player, message, **kwargs):
        self.sent.append((player, message))


def make_game():
    game = Game.__new__(Game)
    game.manager = FakeManager()
    game.map = get_map()
    game.map_id = game.map.id
    game.events = []
    game.players = {}
    game._bodies = {}
    game.over = False
    game.lock = threading.RLock()
    game._stop_event = threading.Event()
    game._timers = set()
    for index, (jid, color) in enumerate(
        (("red", "Red"), ("blue", "Blue"), ("green", "Green"), ("pink", "Pink"))
    ):
        player = PlayerState(jid, "crewmate", color, game.map)
        player.room_entered_at = 0.0
        player.stopped_since = 0.0
        game.players[jid] = player
    game.movement = MovementEngine(game)
    return game


def command(game, sender, text, at):
    return game.handle(sender, text, received_at_ms=round(at * 1000))


class AmongUsSessionTwoTests(unittest.TestCase):
    def test_room_boundary_stop_exact_position_and_restart(self):
        game = make_game()
        try:
            response = command(game, "red", ".m storage", 1000.0)
            self.assertIn("about 6s", response)  # five corridor seconds + one exit tick
            player = game.players["red"]
            observer_messages = [text for target, text in game.manager.sent if target == "blue"]
            self.assertFalse(any("left" in text for text in observer_messages))
            self.assertTrue(player.settled)
            self.assertEqual(player.room, "CAFETERIA")

            game.movement.advance_all(1000.999)
            self.assertTrue(player.settled)
            self.assertFalse(any(e["type"] == "room_departure" for e in game.events))

            game.movement.advance_all(1001.0)
            self.assertFalse(player.settled)
            self.assertEqual(player.corridor_from, "CAFETERIA")
            self.assertEqual(player.corridor_to, "STORAGE")
            self.assertTrue(
                any(
                    target == "blue" and "Red" in text and "left" in text
                    and "Storage" not in text
                    for target, text in game.manager.sent
                )
            )

            where = command(game, "red", ".where", 1003.25)
            self.assertIn("2.25s along the corridor", where)
            command(game, "red", ".stop", 1003.25)
            self.assertFalse(player.path)
            self.assertAlmostEqual(player.corridor_progress_at_start, 2.25)
            self.assertFalse(player.settled)

            game.movement.advance_all(1010.0)
            self.assertAlmostEqual(player.corridor_progress_at_start, 2.25)
            command(game, "red", ".m cafeteria", 1010.0)
            game.movement.advance_all(1012.249)
            self.assertFalse(player.settled)
            game.movement.advance_all(1012.25)
            self.assertTrue(player.settled)
            self.assertEqual(player.room, "CAFETERIA")
            self.assertEqual(player.reference_room, "CAFETERIA")
        finally:
            game.close()

    def test_goback_uses_corridor_position_and_redirect_keeps_reference(self):
        game = make_game()
        try:
            player = game.players["red"]
            command(game, "red", ".m storage", 2000.0)
            game.movement.advance_all(2003.5)
            self.assertAlmostEqual(
                game.movement._corridor_position(player, 2003.5)["progress"],
                2.5,
            )

            response = command(game, "red", ".goback", 2003.5)
            self.assertIn("Returning to *Cafeteria*", response)
            self.assertTrue(player.returning)
            self.assertEqual(player.reference_room, "CAFETERIA")
            self.assertAlmostEqual(
                player.hop_duration,
                2.5,
            )

            response = command(game, "red", ".goback", 2003.75)
            self.assertIn("already going back", response)
            command(game, "red", ".m electrical", 2003.75)
            self.assertFalse(player.returning)
            self.assertEqual(player.reference_room, "CAFETERIA")

            # Redirecting does not change the return target until a room is
            # physically reached; .goback therefore still returns to Cafeteria.
            command(game, "red", ".goback", 2003.75)
            self.assertTrue(player.returning)
            self.assertEqual(player.reference_room, "CAFETERIA")
            self.assertEqual(player.path[0], "CAFETERIA")
            game.movement.advance_all(2006.0)
            self.assertTrue(player.settled)
            self.assertEqual(player.room, "CAFETERIA")
            self.assertFalse(player.returning)
        finally:
            game.close()

    def test_arrival_awareness_is_event_based_not_approach_based(self):
        game = make_game()
        try:
            game.players["green"].room = "MEDBAY"
            game.players["pink"].room = "MEDBAY"
            game.players["green"].reference_room = "MEDBAY"
            game.players["pink"].reference_room = "MEDBAY"

            command(game, "red", ".m medbay", 3000.0)
            command(game, "blue", ".m medbay", 3001.0)
            game.movement.advance_all(3005.0)

            blue_messages = [
                text for target, text in game.manager.sent if target == "blue"
            ]
            self.assertFalse(any("Red arrived in Medbay" in text for text in blue_messages))
            self.assertFalse(game.players["blue"].settled)
            self.assertTrue(game.players["red"].settled)

            game.movement.advance_all(3006.0)
            blue_messages = [
                text for target, text in game.manager.sent if target == "blue"
            ]
            self.assertTrue(any("Red arrived beside you." in text for text in blue_messages))
            self.assertTrue(game.players["blue"].settled)
            self.assertTrue(
                any(
                    target == "green" and "Red" in text and "arrived" in text
                    for target, text in game.manager.sent
                )
            )
        finally:
            game.close()

    def test_simultaneous_arrivals_use_one_shared_room_snapshot(self):
        game = make_game()
        try:
            game.players["blue"].room = "SECURITY"
            game.players["blue"].reference_room = "SECURITY"
            command(game, "red", ".m medbay", 3500.0)
            command(game, "blue", ".m medbay", 3500.0)
            game.movement.advance_all(3505.0)

            red_messages = [
                text for target, text in game.manager.sent if target == "red"
            ]
            blue_messages = [
                text for target, text in game.manager.sent if target == "blue"
            ]
            self.assertTrue(any("Blue arrived beside you." in text for text in red_messages))
            self.assertTrue(any("Red arrived beside you." in text for text in blue_messages))
            arrivals = [
                event for event in game.events
                if event["type"] == "room_arrival" and event["room"] == "MEDBAY"
            ]
            self.assertEqual(len(arrivals), 2)
            self.assertEqual(arrivals[0]["at"], arrivals[1]["at"])
        finally:
            game.close()

    def test_nearby_departures_are_shared_within_the_two_second_window(self):
        game = make_game()
        try:
            command(game, "red", ".m medbay", 3600.0)
            command(game, "blue", ".m storage", 3601.0)
            game.movement.advance_all(3602.0)

            red_messages = [
                text for target, text in game.manager.sent if target == "red"
            ]
            blue_messages = [
                text for target, text in game.manager.sent if target == "blue"
            ]
            self.assertTrue(
                any("Blue" in text and "left" in text and "Cafeteria" in text
                    for text in red_messages)
            )
            self.assertTrue(
                any("Red" in text and "left" in text and "Cafeteria" in text
                    for text in blue_messages)
            )
        finally:
            game.close()

    def test_corridor_encounter_notifies_both_travellers(self):
        game = make_game()
        try:
            game.players["blue"].room = "MEDBAY"
            game.players["blue"].reference_room = "MEDBAY"
            command(game, "red", ".m medbay", 4000.0)
            command(game, "blue", ".m cafeteria", 4000.0)
            game.movement.advance_all(4003.0)

            red_messages = [
                text for target, text in game.manager.sent if target == "red"
            ]
            blue_messages = [
                text for target, text in game.manager.sent if target == "blue"
            ]
            self.assertTrue(any("encountered" in text and "Blue" in text for text in red_messages))
            self.assertTrue(any("encountered" in text and "Red" in text for text in blue_messages))
            self.assertEqual(
                sum(event["type"] == "corridor_encounter" for event in game.events),
                1,
            )
        finally:
            game.close()

    def test_stop_while_stationary_does_not_reset_stop_time(self):
        game = make_game()
        try:
            player = game.players["red"]
            player.stopped_since = 123.0
            response = command(game, "red", ".stop", 5000.0)
            self.assertIn("not moving", response)
            self.assertEqual(player.stopped_since, 123.0)
        finally:
            game.close()

    def test_existing_vent_arrival_still_uses_the_world_clock(self):
        game = make_game()
        try:
            player = game.players["red"]
            player.settled = False
            player.in_vent_until = 6001.0
            player.vent_dest = "MEDBAY"
            game.movement.advance_all(6000.0)
            self.assertEqual(player.room, "CAFETERIA")
            game.movement.advance_all(6001.0)
            self.assertEqual(player.room, "MEDBAY")
            self.assertTrue(player.settled)
            self.assertIsNone(player.in_vent_until)
        finally:
            game.close()

    def test_reporting_from_a_corridor_does_not_teleport_player(self):
        game = make_game()
        try:
            player = game.players["red"]
            command(game, "red", ".m storage", 7000.0)
            game.movement.advance_all(7002.5)
            progress = game.movement._corridor_position(player, 7002.5)["progress"]
            game._bodies["CAFETERIA"] = ["victim"]

            response = command(game, "red", ".report", 7002.5)
            self.assertIn("need to be in a room", response)
            self.assertFalse(player.settled)
            self.assertAlmostEqual(
                game.movement._corridor_position(player, 7002.5)["progress"],
                progress,
            )
        finally:
            game.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
