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
    game._meltdown = None
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


class FakeLobby:
    def __init__(self, players):
        self.players = players
        self.group_jid = "test-group"
        self.map_id = "skeld"


class AmongUsSessionFourTests(unittest.TestCase):
    def test_scientist_role_threshold_and_private_assignment(self):
        manager = FakeManager()
        small = Game(manager, FakeLobby([f"s{i}" for i in range(6)]), started_at_ms=1000)
        try:
            self.assertEqual(
                sum(player.role == "scientist" for player in small.players.values()),
                0,
            )
        finally:
            small.close()

        manager = FakeManager()
        full = Game(manager, FakeLobby([f"p{i}" for i in range(7)]), started_at_ms=2000)
        try:
            scientists = [p for p in full.players.values() if p.role == "scientist"]
            self.assertEqual(len(scientists), 1)
            scientist = scientists[0]
            self.assertTrue(
                any(
                    recipient == scientist.jid and "SCIENTIST" in text
                    for recipient, text in manager.sent
                )
            )
            self.assertTrue(
                all("SCIENTIST" not in text for text in manager.broadcasts)
            )
        finally:
            full.close()

    def test_vitals_and_witness_privacy_status_and_cooldowns(self):
        game = make_game()
        try:
            scientist = game.players["green"]
            scientist.role = "scientist"
            game.players["blue"].alive = False
            game.players["blue"].death_reason = "killed"
            game.players["red"].alive = False
            game.players["red"].death_reason = "killed"
            game.players["pink"].alive = False
            game.players["pink"].death_reason = "killed"
            game._corpses = {
                "blue": {
                    "victim_jid": "blue",
                    "victim_color": "Blue",
                    "room": "CAFETERIA",
                    "killer_jid": "red",
                    "witnesses": [],
                    "reported": False,
                },
                "red": {
                    "victim_jid": "red",
                    "victim_color": "Red",
                    "room": "ADMIN",
                    "killer_jid": "pink",
                    "witnesses": ["green"],
                    "reported": False,
                },
                "pink": {
                    "victim_jid": "pink",
                    "victim_color": "Pink",
                    "room": "ELECTRICAL",
                    "killer_jid": "blue",
                    "witnesses": ["green", "red"],
                    "reporter_jid": "green",
                    "reported": True,
                },
            }

            vitals = command(game, "green", ".vitals", 5000)
            self.assertIn("Blue — Dead — Unreported", vitals)
            self.assertIn("Red — Dead — Witnessed", vitals)
            self.assertIn("Pink — Dead — Reported", vitals)
            self.assertIn("Green — Alive", vitals)
            self.assertNotIn("CAFETERIA", vitals)
            self.assertNotIn("killer", vitals.lower())
            self.assertIn("19s", command(game, "green", ".vitals", 5001))

            witness = command(game, "green", ".witness", 5000)
            self.assertIn("*Green (reporter)*", witness)
            self.assertIn("Red", witness)
            self.assertNotIn("ELECTRICAL", witness)
            self.assertNotIn("killer", witness.lower())
            self.assertIn("1s", command(game, "green", ".witness", 5074))
            self.assertIn("*Vitals & Witnesses*", command(game, "green", ".witness", 5075))

            game.players["blue"].alive = True
            self.assertIn(
                "Scientist only",
                command(game, "blue", ".vitals", 5100),
            )
        finally:
            game.close()

    def test_pending_kill_resolves_on_world_tick_with_witness_and_cooldown(self):
        game = make_game()
        try:
            killer = game.players["red"]
            target = game.players["blue"]
            witness = game.players["green"]
            killer.role = "impostor"
            for player in game.players.values():
                player.room = "CAFETERIA"

            response = command(game, "red", ".kill Blue", 10000)
            self.assertIn("5s", response)
            self.assertTrue(target.alive)
            self.assertIsNotNone(killer.pending_kill)

            game.movement.advance_all(10005)  # 5 s kill wait (Session 09 pkg 1)
            self.assertFalse(target.alive)
            self.assertEqual(killer.kill_cooldown_until, 10035)
            self.assertIn("green", game._corpses["blue"]["witnesses"])
            self.assertTrue(
                any("distress" in text.lower() for text in messages_for(game, "green"))
            )
            self.assertNotIn("Red", messages_for(game, "blue")[-1])
            self.assertIn("29s", game._cmd_kill(killer, "Pink", now=10006))
        finally:
            game.close()

    def test_kill_is_cancelled_when_either_player_moves(self):
        for moving_jid in ("red", "blue"):
            game = make_game()
            try:
                killer = game.players["red"]
                target = game.players["blue"]
                killer.role = "impostor"
                for player in game.players.values():
                    player.room = "CAFETERIA"
                command(game, "red", ".kill Blue", 20000)
                result = game.movement.move(game.players[moving_jid], "MEDBAY", 20001)
                self.assertIsNone(result[1])
                self.assertIsNone(killer.pending_kill)
                self.assertTrue(target.alive)
                game.movement.advance_all(20005)
                self.assertTrue(target.alive)
            finally:
                game.close()

    def test_meeting_cancels_pending_kill_without_starting_cooldown(self):
        game = make_game()
        try:
            killer = game.players["red"]
            killer.role = "impostor"
            for player in game.players.values():
                player.room = "CAFETERIA"
            command(game, "red", ".kill Blue", 25000)

            command(game, "green", ".meeting", 25001)
            self.assertIsNone(killer.pending_kill)
            self.assertEqual(killer.kill_cooldown_until, 0)
            self.assertTrue(game.players["blue"].alive)
            self.assertTrue(
                any("because a meeting was called" in text.lower()
                    for text in messages_for(game, "red"))
            )
        finally:
            game.close()

    def test_vent_travel_is_private_instant_and_does_not_reset_deadline(self):
        game = make_game()
        try:
            impostor = game.players["red"]
            impostor.role = "impostor"
            impostor.room = "ELECTRICAL"
            game.players["pink"].room = "ELECTRICAL"
            game.players["blue"].room = "MEDBAY"
            game.players["green"].room = "ADMIN"

            command(game, "red", ".vent in", 30000)
            original_deadline = impostor.in_vent_until
            self.assertEqual(original_deadline, 30015)
            self.assertEqual(impostor.vent_room, "ELECTRICAL")
            self.assertTrue(any("used a vent" in text for text in messages_for(game, "pink")))
            self.assertFalse(game.manager.broadcasts)

            command(game, "red", ".vent medbay", 30002)
            self.assertEqual(impostor.vent_room, "MEDBAY")
            self.assertEqual(impostor.in_vent_until, original_deadline)
            command(game, "red", ".vent out", 30003)
            self.assertEqual(impostor.room, "MEDBAY")
            self.assertIsNone(impostor.in_vent_until)
            self.assertEqual(impostor.vent_cooldown_until, 30033)
            self.assertTrue(
                any("arrived from a vent" in text for text in messages_for(game, "blue"))
            )
            self.assertFalse(
                any("arrived from a vent" in text for text in messages_for(game, "pink"))
            )
            self.assertIn("cooldown", command(game, "red", ".vent in", 30010).lower())
        finally:
            game.close()

    def test_vent_timeout_ejects_at_current_vent_and_starts_cooldown(self):
        game = make_game()
        try:
            impostor = game.players["red"]
            impostor.role = "impostor"
            impostor.room = "ELECTRICAL"
            command(game, "red", ".vent in", 40000)
            command(game, "red", ".vent SECURITY", 40002)

            game.movement.advance_all(40015)
            self.assertEqual(impostor.room, "SECURITY")
            self.assertTrue(impostor.settled)
            self.assertIsNone(impostor.in_vent_until)
            self.assertEqual(impostor.vent_cooldown_until, 40045)
            self.assertTrue(
                any(event["type"] == "vent_ejected" for event in game.events)
            )
        finally:
            game.close()

    def test_group_dispatch_blocks_scientist_and_cooldown_details(self):
        game = make_game()
        try:
            game.players["green"].role = "scientist"
            manager = AmongUsManager(None, "group")
            manager.amongus_on.add("green")
            manager.game = game

            public_reply = manager._dispatch("green", ".witness", "group", 5000000)
            self.assertIn("private", public_reply.lower())
            self.assertNotIn("Vitals & Witnesses", public_reply)
            self.assertEqual(game.players["green"].witness_cooldown_until, 0)

            private_reply = manager._dispatch("green", ".cds", None, 5000000)
            self.assertIn("Vitals", private_reply)
            self.assertIn("Witness", private_reply)

            game.players["red"].role = "impostor"
            cooldowns = manager._dispatch("red", ".cooldown", None, 5000000)
            self.assertIn("Kill: Ready", cooldowns)
            self.assertIn("Vent: Ready", cooldowns)
        finally:
            game.close()


if __name__ == "__main__":
    unittest.main()
