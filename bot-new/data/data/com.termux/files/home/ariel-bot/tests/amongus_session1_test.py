import sys as _s, pathlib as _p
_s.path.insert(0, str(_p.Path(__file__).resolve().parent))
import amongus_testlinks  # noqa: E402,F401
import sys
import time
import types
import unittest
from pathlib import Path


BOT_ROOT = Path(__file__).resolve().parents[1]
ENGINE_DIR = BOT_ROOT / "engine"
ROUTER_DIR = ENGINE_DIR / "router"
sys.path[:0] = [
    str(ENGINE_DIR),
    str(ENGINE_DIR / "pokemon"),
    str(ENGINE_DIR / "core"),
]

# Import only the Among Us modules. The full Ariel router initializes RPG,
# Pokémon, and database integrations, which these engine tests do not need.
router_package = types.ModuleType("router")
router_package.__path__ = [str(ROUTER_DIR)]
sys.modules.setdefault("router", router_package)

from router.amongus import (  # noqa: E402
    DELETE_INCOMING_MESSAGE,
    AmongUsCoordinator,
    NOT_HANDLED,
    _impostor_count,
)
from router import amongus_map  # noqa: E402
from router.amongus_config import PLAYER_COLORS  # noqa: E402
from router.handle import HandleMixin  # noqa: E402


class FakeRouter:
    def __init__(self):
        self.sent = []

    def _direct_send(self, message, group_jid=None, **kwargs):
        self.sent.append((group_jid, message, kwargs))


class FakeChat:
    def record_names(self, _sender):
        pass


class HandleHarness(HandleMixin):
    def __init__(self, coordinator):
        self.amongus = coordinator
        self.chat = FakeChat()


class AmongUsSessionOneTests(unittest.TestCase):
    def setUp(self):
        self.router = FakeRouter()
        self.coordinator = AmongUsCoordinator(self.router)

    def tearDown(self):
        for manager in tuple(self.coordinator._groups.values()):
            manager._cancel_timer()
            if manager.game:
                manager.game.close()

    def _open_four_player_game(self, group_jid, start_at_ms, players=None):
        players = players or [
            f"{group_jid}-player-{index}" for index in range(1, 5)
        ]
        for index, player in enumerate(players):
            self.coordinator.pre_dispatch(player, ".amongus on", group_jid)
            if index == 0:
                response = self.coordinator.pre_dispatch(
                    player, ".lobby open", group_jid
                )
                self.assertIn("opened", response.lower())
            else:
                response = self.coordinator.pre_dispatch(player, ".join", group_jid)
                self.assertIn("joined the lobby", response)

        response = self.coordinator.pre_dispatch(
            players[0],
            ".lobby start",
            group_jid,
            received_at_ms=start_at_ms,
        )
        self.assertIsNone(response)
        manager = self.coordinator._groups[group_jid]
        self.assertIsNotNone(manager.game)
        return manager, players

    def test_impostor_brackets_and_color_capacity(self):
        self.assertEqual(_impostor_count(4), 1)
        self.assertEqual(_impostor_count(6), 1)
        self.assertEqual(_impostor_count(7), 2)
        self.assertEqual(_impostor_count(13), 2)
        self.assertEqual(_impostor_count(14), 3)
        self.assertEqual(_impostor_count(20), 3)
        self.assertEqual(len(PLAYER_COLORS), 20)
        self.assertEqual(len({color.lower() for color in PLAYER_COLORS}), 20)

    def test_skeld_is_the_default_map(self):
        default_map = amongus_map.get_map()
        self.assertEqual(amongus_map.DEFAULT_MAP_ID, "skeld")
        self.assertEqual(default_map.name, "The Skeld")
        self.assertEqual(default_map.start_room, "CAFETERIA")
        self.assertEqual(len(default_map.rooms), 14)
        self.assertTrue(default_map.travel_times_approximate)
        for room in default_map.rooms:
            for destination in default_map.rooms:
                self.assertIsNotNone(amongus_map.shortest_path(room, destination))
        with self.assertRaises(ValueError):
            amongus_map.get_map("unknown-map")

    def test_lobby_minimum_capacity_and_leave(self):
        group_jid = "capacity-group"
        players = [f"capacity-player-{index}" for index in range(1, 22)]

        self.coordinator.pre_dispatch(players[0], ".amongus on", group_jid)
        self.coordinator.pre_dispatch(players[0], ".lobby open", group_jid)
        too_few = self.coordinator.pre_dispatch(players[0], ".lobby start", group_jid)
        self.assertIn("Need at least 4", too_few)

        for player in players[1:20]:
            self.coordinator.pre_dispatch(player, ".amongus on", group_jid)
            self.assertIn(
                "joined the lobby",
                self.coordinator.pre_dispatch(player, ".join", group_jid),
            )
        self.coordinator.pre_dispatch(players[20], ".amongus on", group_jid)
        full = self.coordinator.pre_dispatch(players[20], ".join", group_jid)
        self.assertIn("20 max", full)

        self.coordinator.pre_dispatch(players[19], ".leave", group_jid)
        self.assertEqual(len(self.coordinator._groups[group_jid].lobby.players), 19)
        self.assertIn(
            "joined the lobby",
            self.coordinator.pre_dispatch(players[20], ".join", group_jid),
        )
        started = self.coordinator.pre_dispatch(players[0], ".lobby start", group_jid)
        self.assertIsNone(started)

        game = self.coordinator._groups[group_jid].game
        self.assertEqual(len(game.players), 20)
        self.assertEqual(sum(p.role == "impostor" for p in game.players.values()), 3)
        self.assertEqual(len({p.color for p in game.players.values()}), 20)

    def test_group_state_isolation_and_autonomous_world_clock(self):
        start_at_ms = 1_700_000_000_000
        first, first_players = self._open_four_player_game("group-one", start_at_ms)
        second_players = [
            first_players[0],
            "group-two-player-2",
            "group-two-player-3",
            "group-two-player-4",
        ]
        second, _ = self._open_four_player_game(
            "group-two",
            start_at_ms,
            players=second_players,
        )

        self.assertIsNot(first, second)
        self.assertNotEqual(first.lobby.id, second.lobby.id)
        self.assertEqual(first.lobby.group_jid, "group-one")
        self.assertEqual(second.lobby.group_jid, "group-two")
        self.assertIn(
            "The Skeld",
            self.coordinator.pre_dispatch(
                first_players[0], ".lobby list", group_jid="group-one"
            ),
        )
        self.assertEqual(first.game.map_id, "skeld")
        self.assertEqual(first.game.map.name, "The Skeld")
        self.assertEqual(len(first.game.players), 4)
        self.assertEqual(len(second.game.players), 4)
        self.assertEqual(len({p.color for p in first.game.players.values()}), 4)
        self.assertEqual(len({p.color for p in second.game.players.values()}), 4)
        self.assertEqual(first.game.events[0]["at"], start_at_ms / 1000)
        self.assertEqual(first.game.events[0]["type"], "game_started")

        first_ticks = first.game.tick_count
        second_ticks = second.game.tick_count
        time.sleep(1.25)
        self.assertGreater(first.game.tick_count, first_ticks)
        self.assertGreater(second.game.tick_count, second_ticks)

        first_event_count = len(first.game.events)
        second_event_count = len(second.game.events)
        ambiguous = self.coordinator.pre_dispatch(
            first_players[0], ".where", group_jid=None
        )
        self.assertIn("more than one", ambiguous)
        self.assertEqual(len(first.game.events), first_event_count)
        self.assertEqual(len(second.game.events), second_event_count)

        # A group message disambiguates the shared player back to that match.
        private_only = self.coordinator.pre_dispatch(
            first_players[0],
            ".where",
            group_jid="group-two",
            received_at_ms=start_at_ms + 1_500,
        )
        self.assertIn("private", private_only)
        self.assertEqual(len(first.game.events), first_event_count)
        self.assertEqual(len(second.game.events), second_event_count)

        first.game._meeting = {"votes": {}, "opens_at": 0}
        second.game._meeting = {"votes": {}, "opens_at": 0}
        public_vote = self.coordinator.pre_dispatch(
            first_players[0],
            ".vote skip",
            group_jid="group-two",
            received_at_ms=start_at_ms + 1_500,
        )
        self.assertEqual(public_vote, DELETE_INCOMING_MESSAGE)
        self.assertEqual(first.game._meeting["votes"], {})
        self.assertEqual(second.game._meeting["votes"][first_players[0]], "skip")
        self.assertEqual(
            second.game.events[-1]["at"],
            (start_at_ms + 1_500) / 1000,
        )
        # The hand-made meeting dicts above are not real meetings (no start
        # time): remove them so the world clock does not end the match on them.
        first.game._meeting = None
        second.game._meeting = None

        handle = HandleHarness(self.coordinator)
        dm_response = handle.handle(
            first_players[1],
            ".where",
            group_jid=f"{first_players[1]}@s.whatsapp.net",
            is_group=False,
            received_at_ms=start_at_ms + 1_750,
        )
        self.assertIn("Cafeteria", dm_response)
        group_response = handle.handle(
            first_players[1],
            ".where",
            group_jid="group-one",
            is_group=True,
            pool_amongus=True,
            received_at_ms=start_at_ms + 1_800,
        )
        self.assertIn("private", group_response)

        first_color = first.game.players[first_players[0]].color
        first._broadcast(f"Public update about {first_players[0]}.")
        public_update = self.router.sent[-1][1]
        self.assertNotIn(first_players[0], public_update)
        self.assertIn(first_color, public_update)

        # A private command resolves to the only game this player belongs to.
        response = self.coordinator.pre_dispatch(
            first_players[1],
            ".where",
            group_jid=None,
            received_at_ms=start_at_ms + 2_000,
        )
        self.assertIn("Cafeteria", response)
        command_event = first.game.events[-1]
        self.assertEqual(command_event["at"], (start_at_ms + 2_000) / 1000)
        self.assertEqual(command_event["actor"], first.game.players[first_players[1]].color)

        # Closing a game stops its clock; pending ticks cannot act afterward.
        first.game.close()
        stopped_at = first.game.tick_count
        time.sleep(1.1)
        self.assertEqual(first.game.tick_count, stopped_at)
        self.assertTrue(first.game.over)
        self.assertTrue(second.game.tick_count > 0)

        self.assertIsNot(
            self.coordinator.pre_dispatch(
                second_players[0], ".where", group_jid=None
            ),
            NOT_HANDLED,
        )

        group_messages = [
            message
            for target, message, _ in self.router.sent
            if target in {"group-one", "group-two"}
        ]
        for player in first_players + second_players:
            for message in group_messages:
                self.assertNotIn(player, message)


if __name__ == "__main__":
    unittest.main(verbosity=2)
