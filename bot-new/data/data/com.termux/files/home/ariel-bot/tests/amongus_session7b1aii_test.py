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


def command(game, sender, text, at):
    return game.handle(sender, text, received_at_ms=round(at * 1000))


def messages(game, jid):
    return [text for target, text in game.manager.sent if target == jid]


def move_to(game, jid, room):
    game.players[jid].room = room
    game.players[jid].reference_room = room


class AmongUsSessionSevenB1aiiTests(unittest.TestCase):
    def test_arrival_hides_who_from_crew_but_not_impostor(self):
        game = make_game()
        try:
            move_to(game, "blue", "MEDBAY")
            move_to(game, "pink", "MEDBAY")
            game._cmd_sabotage(game.players["pink"], "lights", now=900)

            command(game, "red", ".m medbay", 1000.0)
            game.movement.advance_all(1010.0)

            blue = messages(game, "blue")
            pink = messages(game, "pink")
            self.assertTrue(any("Someone arrived beside you." in t for t in blue))
            self.assertFalse(any("*Red*" in t for t in blue))
            self.assertTrue(any("Red arrived beside you." in t for t in pink))
        finally:
            close_game(game)

    def test_departure_hides_who_from_crew_but_not_impostor(self):
        game = make_game()
        try:
            game._cmd_sabotage(game.players["pink"], "lights", now=900)
            command(game, "red", ".m medbay", 1000.0)
            game.movement.advance_all(1001.0)

            self.assertTrue(
                any("*Someone* left *Cafeteria*" in t for t in messages(game, "blue"))
            )
            self.assertTrue(
                any("*Red* left *Cafeteria*" in t for t in messages(game, "pink"))
            )
            self.assertFalse(any("*Red*" in t for t in messages(game, "blue")))
        finally:
            close_game(game)

    def test_corridor_encounter_is_masked_for_crew_only(self):
        game = make_game()
        try:
            game._cmd_sabotage(game.players["pink"], "lights", now=900)
            for jid in ("red", "pink"):
                p = game.players[jid]
                p.room = None
                p.settled = False
                p.corridor_from = "CAFETERIA"
                p.corridor_to = "STORAGE"
                p.corridor_length = 5.0
                p.corridor_progress_at_start = 2.0
                p.corridor_started_at = None
            game.movement._detect_corridor_encounters(1000.0)

            self.assertTrue(
                any("encountered *Someone*" in t for t in messages(game, "red"))
            )
            self.assertTrue(
                any("encountered *Red*" in t for t in messages(game, "pink"))
            )
            enc = [e for e in game.events if e["type"] == "corridor_encounter"]
            self.assertTrue(enc and enc[0]["masked"])
        finally:
            close_game(game)

    def test_status_shows_real_occupants_during_lights(self):
        game = make_game()
        try:
            game._cmd_sabotage(game.players["pink"], "lights", now=900)
            status = game._cmd_status(game.players["blue"], now=1000.0)
            self.assertIn("Red", status)
            self.assertIn("Pink", status)
            self.assertNotIn("Someone", status)
        finally:
            close_game(game)

    def test_masked_events_stay_masked_after_repair_and_new_ones_are_not(self):
        game = make_game()
        try:
            move_to(game, "blue", "MEDBAY")
            game._cmd_sabotage(game.players["pink"], "lights", now=900)
            command(game, "red", ".m medbay", 1000.0)
            game.movement.advance_all(1010.0)
            game._repair_sabotage("lights", game.players["green"], now=1011.0)

            blue_before = list(messages(game, "blue"))
            self.assertTrue(any("Someone arrived beside you." in t for t in blue_before))

            command(game, "green", ".m medbay", 1100.0)
            game.movement.advance_all(1110.0)
            blue_after = messages(game, "blue")[len(blue_before):]
            self.assertTrue(any("Green arrived beside you." in t for t in blue_after))

            arrivals = [
                e for e in game.events
                if e["type"] == "room_arrival" and e["room"] == "MEDBAY"
            ]
            self.assertEqual([e["masked"] for e in arrivals], [True, False])
        finally:
            close_game(game)


if __name__ == "__main__":
    unittest.main()
