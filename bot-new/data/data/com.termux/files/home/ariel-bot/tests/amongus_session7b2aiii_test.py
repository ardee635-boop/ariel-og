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


def comms_on(game, at=900):
    game._cmd_sabotage(game.players["pink"], "communications", now=at)


def camping_events(game):
    return [e for e in game.events if e["type"] == "camping_awareness"]


class AmongUsSessionSevenB2aiiiTests(unittest.TestCase):
    def test_arrival_and_departure_notices_suppressed_but_mover_still_told(self):
        game = make_game()
        try:
            move_to(game, "blue", "MEDBAY")
            comms_on(game)
            command(game, "red", ".m medbay", 1000.0)
            game.movement.advance_all(1010.0)

            for jid in ("blue", "green", "pink"):
                passive = [
                    t for t in messages(game, jid)
                    if "arrived in" in t or "left *" in t or "passing" in t
                ]
                self.assertEqual(passive, [], jid)
            self.assertFalse(any("Nearby room update" in t
                                 for _, t in game.manager.sent))
            self.assertTrue(any("You have arrived at Medbay" in t
                                for t in messages(game, "red")))
            arrivals = [e for e in game.events if e["type"] == "room_arrival"]
            departures = [e for e in game.events if e["type"] == "room_departure"]
            self.assertTrue(arrivals and all(e["suppressed"] for e in arrivals))
            self.assertTrue(departures and all(e["suppressed"] for e in departures))
        finally:
            close_game(game)

    def test_notices_return_to_normal_after_repair_with_no_replay(self):
        game = make_game()
        try:
            move_to(game, "blue", "MEDBAY")
            comms_on(game)
            command(game, "red", ".m medbay", 1000.0)
            game.movement.advance_all(1010.0)
            game._repair_sabotage("communications", game.players["green"], now=1011.0)
            self.assertFalse(any("Red" in t for t in messages(game, "blue")))

            command(game, "green", ".m medbay", 1100.0)
            game.movement.advance_all(1110.0)
            blue = messages(game, "blue")
            self.assertTrue(any("Green arrived beside you." in t for t in blue))
            self.assertFalse(any("*Red*" in t for t in blue))
            green_arrival = [e for e in game.events
                             if e["type"] == "room_arrival" and e["actor"] == "Green"]
            self.assertFalse(green_arrival[-1]["suppressed"])
        finally:
            close_game(game)

    def test_no_nearby_update_pairing_across_the_repair_boundary(self):
        game = make_game()
        try:
            comms_on(game)
            command(game, "red", ".m medbay", 1000.0)
            game.movement.advance_all(1001.0)  # suppressed departure at ~1001
            game._repair_sabotage("communications", game.players["green"], now=1001.5)
            command(game, "blue", ".m medbay", 1001.6)
            game.movement.advance_all(1010.0)
            # The suppressed departure is never reported, even by pairing.
            self.assertFalse(any("Red left" in t for _, t in game.manager.sent))
            self.assertFalse(any("*Red* left" in t for _, t in game.manager.sent))
        finally:
            close_game(game)

    def test_corridor_encounter_recorded_not_announced_and_no_replay(self):
        game = make_game()
        try:
            comms_on(game)
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
            self.assertFalse(any("encountered" in t for _, t in game.manager.sent))
            enc = [e for e in game.events if e["type"] == "corridor_encounter"]
            self.assertEqual(len(enc), 1)
            self.assertTrue(enc[0]["suppressed"])

            game._repair_sabotage("communications", game.players["green"], now=1001.0)
            game.movement._detect_corridor_encounters(1001.5)  # same ongoing pair
            self.assertFalse(any("encountered" in t for _, t in game.manager.sent))
            self.assertEqual(
                len([e for e in game.events if e["type"] == "corridor_encounter"]), 1
            )
        finally:
            close_game(game)

    def test_camping_never_fires_during_communications(self):
        game = make_game()
        try:
            comms_on(game, 10)
            game.movement.advance_all(70.0)
            game.movement.advance_all(200.0)
            self.assertEqual(camping_events(game), [])
            self.assertFalse(any("onto you" in t.lower() for _, t in game.manager.sent))
        finally:
            close_game(game)

    def test_pending_camping_trigger_is_dropped_not_delayed(self):
        game = make_game()
        try:
            # Everyone has been stationary together since t=0; at t=50 a
            # trigger is about to be due. Outage runs 50..110.
            game.movement.advance_all(50.0)
            comms_on(game, 50)
            game.movement.advance_all(100.0)
            game._repair_sabotage("communications", game.players["green"], now=110.0)
            game.movement.advance_all(111.0)
            game.movement.advance_all(300.0)
            self.assertEqual(camping_events(game), [])
            self.assertFalse(any("onto you" in t.lower() for _, t in game.manager.sent))
        finally:
            close_game(game)

    def test_fresh_stop_after_repair_starts_a_new_camping_timer(self):
        game = make_game()
        try:
            comms_on(game, 50)
            game._repair_sabotage("communications", game.players["green"], now=110.0)
            command(game, "red", ".m medbay", 130.0)
            command(game, "blue", ".m medbay", 130.0)
            t = 130.0
            while t < 400.0:
                t += 1.0
                game.movement.advance_all(t)
            events = camping_events(game)
            self.assertTrue(events)
            self.assertTrue(all(e["at"] > 130.0 for e in events))
            self.assertTrue({e["actor"] for e in events} <= {"Red", "Blue"})
        finally:
            close_game(game)

    def test_follow_and_movement_still_work_during_communications(self):
        game = make_game()
        try:
            comms_on(game)
            self.assertIn("following *blue*", (command(game, "red", ".follow blue", 1000.0) or "").lower())
            self.assertEqual(game.players["red"].following, "blue")
            command(game, "blue", ".m medbay", 1001.0)
            game.movement.advance_all(1002.0)
            self.assertTrue(any("is leaving" in t for t in messages(game, "red")))
            game.movement.advance_all(1020.0)
            self.assertEqual(game.players["blue"].room, "MEDBAY")
            self.assertTrue(any("has arrived at *Medbay*" in t
                                for t in messages(game, "red")))
        finally:
            close_game(game)

    def test_vent_use_notice_suppressed_during_outage_only(self):
        game = make_game()
        try:
            room = next(r for r, dests in game.map.vents.items() if dests)
            for jid in ("red", "blue", "green", "pink"):
                move_to(game, jid, room)
            comms_on(game)
            game._cmd_vent(game.players["pink"], "in", now=1000.0)
            self.assertFalse(any("has used a vent" in t for _, t in game.manager.sent))
            game._exit_vent(game.players["pink"], 1005.0, automatic=False)
            self.assertFalse(any("arrived from a vent" in t
                                 for j, t in game.manager.sent if j != "pink"))
            self.assertTrue(any("arrived from a vent" in t
                                for t in messages(game, "pink")))

            game._repair_sabotage("communications", game.players["red"], now=1010.0)
            game.players["pink"].vent_cooldown_until = 0.0
            game._cmd_vent(game.players["pink"], "in", now=1100.0)
            self.assertTrue(any("has used a vent" in t for t in messages(game, "red")))
        finally:
            close_game(game)

    def test_lights_alone_does_not_suppress_anything(self):
        game = make_game()
        try:
            game._cmd_sabotage(game.players["pink"], "lights", now=900)
            command(game, "red", ".m medbay", 1000.0)
            game.movement.advance_all(1001.0)
            self.assertTrue(any("left *Cafeteria*" in t for t in messages(game, "blue")))
        finally:
            close_game(game)

    def test_status_and_where_unaffected(self):
        game = make_game()
        try:
            comms_on(game)
            status = game._cmd_status(game.players["blue"], now=1000.0)
            self.assertIn("Red", status)
        finally:
            close_game(game)


if __name__ == "__main__":
    unittest.main()
