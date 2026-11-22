"""Session 09 package 4 - sabotage delivery: group + DM to every player
(Ghosts included) with a runtime group link, activation never names the
Impostor, per-map station registry."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import amongus_session7d_test as T7  # noqa: E402
from router import amongus_map as M  # noqa: E402


class LinkManager(T7.FakeManager):
    """Records which DMs asked for the group link."""

    def __init__(self):
        super().__init__()
        self.linked = []

    def _push_dm_with_link(self, player, message):
        self.linked.append((player, message))
        self.sent.append((player, message))


def new_game():
    game = T7.make_game()
    game.manager = LinkManager()
    return game


class Registry(unittest.TestCase):
    def test_registry_is_valid_and_per_map(self):
        M.validate_station_registry()
        self.assertEqual(M.get_station_rooms("reactor"), ("UPPER_ENGINE", "LOWER_ENGINE"))
        self.assertEqual(M.get_station_rooms("oxygen"), ("O2", "ADMIN"))
        self.assertEqual(M.get_station_rooms("lights"), ("ELECTRICAL",))
        self.assertEqual(M.get_station_rooms("communications"), ("COMMUNICATIONS",))
        self.assertEqual(
            [len(M.get_stations(n)) for n in ("lights", "communications", "oxygen", "reactor")],
            [1, 1, 2, 2],
        )

    def test_unknown_map_is_refused(self):
        with self.assertRaises(ValueError):
            M.get_stations("reactor", "no-such-map")

    def test_bad_room_is_rejected(self):
        M.SABOTAGE_STATIONS_BY_MAP[M.MAP_ID]["lights"] = (("x", "X", "NOWHERE"),)
        try:
            with self.assertRaises(ValueError):
                M.validate_station_registry()
        finally:
            M.SABOTAGE_STATIONS_BY_MAP[M.MAP_ID]["lights"] = (
                ("lights_repair", "Lights repair", "ELECTRICAL"),
            )
        M.validate_station_registry()


class Delivery(unittest.TestCase):
    def setUp(self):
        self.game = new_game()

    def tearDown(self):
        self.game.close()

    def activate(self, name, at=100.0):
        T7.sabotage(self.game, name, at)

    def test_activation_text_lists_required_stations(self):
        text = self.game._sabotage_activation_text("reactor")
        self.assertIn("☢️ *REACTOR SABOTAGED!*", text)
        self.assertIn("*Required stations:*", text)
        self.assertIn("- Reactor station — Upper Engine", text)
        self.assertIn("- Reactor station — Lower Engine", text)
        one = self.game._sabotage_activation_text("lights")
        self.assertIn("- Lights repair — Electrical", one)
        self.assertEqual(one.count("\n- "), 1)

    def test_activation_never_names_the_impostor(self):
        for name in ("lights", "communications", "oxygen", "reactor"):
            game = new_game()
            try:
                T7.sabotage(game, name, 100.0)
                public = list(game.manager.broadcasts) + [
                    m for who, m in game.manager.sent
                    if who != T7.JID["Pink"]
                ]
                for text in public:
                    for color in ("Pink", "Black"):
                        self.assertNotIn(color, text, (name, text))
                    self.assertNotIn(" by ", text)
            finally:
                game.close()

    def test_group_and_every_dm_including_ghosts_and_impostors(self):
        self.game.players[T7.JID["Red"]].alive = False   # a Ghost
        self.game.players[T7.JID["Blue"]].departed = True
        self.activate("reactor")
        group = [b for b in self.game.manager.broadcasts if "REACTOR SABOTAGED" in b]
        self.assertEqual(len(group), 1)
        linked = {who for who, m in self.game.manager.linked if "REACTOR SABOTAGED" in m}
        expected = {
            p.jid for p in self.game.players.values() if not p.departed
        }
        self.assertEqual(linked, expected)
        self.assertIn(T7.JID["Red"], linked)       # ghost
        self.assertIn(T7.JID["Pink"], linked)      # impostor
        self.assertNotIn(T7.JID["Blue"], linked)   # departed

    def test_only_the_triggering_impostor_gets_a_confirmation(self):
        self.activate("communications")
        mine = [m for who, m in self.game.manager.sent if who == T7.JID["Pink"]]
        self.assertIn("Communications sabotage initiated.", mine)
        others = [
            m for who, m in self.game.manager.sent
            if who != T7.JID["Pink"] and "initiated" in m
        ]
        self.assertEqual(others, [])
        self.assertNotIn("initiated", " ".join(self.game.manager.broadcasts))

    def test_warnings_and_repair_reach_group_and_dms(self):
        self.activate("oxygen")
        deadline = self.game._sabotages["oxygen"]["deadline"]
        self.game._advance_sabotages(deadline - 20)
        self.game._advance_sabotages(deadline - 10)
        for n in (20, 10):
            text = f"⚠️ *O₂: {n}s remaining.*\nReach the required station(s) and finish the repair."
            self.assertIn(text, self.game.manager.broadcasts)
            self.assertEqual(
                sum(1 for _w, m in self.game.manager.linked if m == text),
                len([p for p in self.game.players.values() if not p.departed]),
            )
        T7.repair_paired(self.game, "oxygen", "Red", "Blue", deadline - 15)
        self.assertIn("✅ *O₂ sabotage repaired.* The ship is safe for now.", self.game.manager.broadcasts)
        self.assertTrue(any("repaired" in m for _w, m in self.game.manager.linked))

    def test_falls_back_to_plain_dm_when_manager_has_no_link_support(self):
        game = T7.make_game()    # plain FakeManager without _push_dm_with_link
        try:
            T7.sabotage(game, "lights", 100.0)
            self.assertTrue(any("LIGHTS SABOTAGED" in m for _w, m in game.manager.sent))
        finally:
            game.close()


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
