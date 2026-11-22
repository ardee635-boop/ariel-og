"""Session 09 package 6b - owner registry (.set/.unset alobbygc|aghostgc,
.alobbygcs, .ghostgcs): owner only, run in the group, one role per group,
persistent, .unset refused in a live game, and the ghost-group pick that
replaces .setghostgroup (lobby group N uses ghost group N)."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import amongus_session7d_test  # noqa: F401,E402  (sets up engine paths + router package stub)
from router.amongus import AmongUsCoordinator, AmongUsManager, NOT_HANDLED  # noqa: E402
from router.amongus_registry import GroupRegistry  # noqa: E402

OWNER = "2340000000001@s.whatsapp.net"
USER = "2340000000002@s.whatsapp.net"
L1, L2 = "120363000000000011@g.us", "120363000000000012@g.us"
G1, G2 = "120363000000000021@g.us", "120363000000000022@g.us"


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "registry.json"
        self.coord = self.make()

    def tearDown(self):
        self.dir.cleanup()

    def make(self):
        return AmongUsCoordinator(
            mock.Mock(), registry=GroupRegistry(self.path), owner_check=lambda s: s == OWNER
        )

    def run_cmd(self, text, group, sender=OWNER):
        return self.coord.pre_dispatch(sender, text, group_jid=group)


class Commands(Base):
    def test_owner_registers_and_lists_lobby_groups(self):
        self.assertIn("now a registered lobby", self.run_cmd(".set alobbygc", L1))
        self.run_cmd(".set alobbygc", L2)
        out = self.run_cmd(".alobbygcs", L1)
        self.assertIn("*Lobby groups*", out)
        self.assertIn("1. Group …000011 — idle", out)
        self.assertIn("2. Group …000012 — idle", out)
        self.assertNotIn("@g.us", out)
        self.assertNotIn("120363", out)

    def test_ghost_registry_and_empty_lists(self):
        self.assertIn("No ghost groups", self.run_cmd(".ghostgcs", L1))
        self.assertIn("No lobby groups", self.run_cmd(".alobbygcs", L1))
        self.run_cmd(".set aghostgc", G1)
        self.assertIn("1. Group …000021 — free", self.run_cmd(".ghostgcs", L1))

    def test_non_owner_is_refused_for_all_six(self):
        for text in (".set alobbygc", ".unset alobbygc", ".set aghostgc", ".unset aghostgc", ".alobbygcs", ".ghostgcs"):
            self.assertIn("Only the bot owner", self.run_cmd(text, L1, sender=USER), text)
        self.assertEqual(self.coord.registry.list("lobby"), [])

    def test_set_and_unset_must_be_run_in_a_group(self):
        self.assertIn("Run this in the group", self.coord.pre_dispatch(OWNER, ".set alobbygc"))
        self.assertIn("Run this in the group", self.coord.pre_dispatch(OWNER, ".unset aghostgc"))

    def test_one_group_cannot_hold_both_roles(self):
        self.run_cmd(".set alobbygc", L1)
        self.assertIn("can't be both", self.run_cmd(".set aghostgc", L1))
        self.assertEqual(self.coord.registry.list("ghost"), [])
        self.assertIn("already a registered lobby", self.run_cmd(".set alobbygc", L1))

    def test_unset_removes_and_reports_missing(self):
        self.run_cmd(".set aghostgc", G1)
        self.assertIn("no longer", self.run_cmd(".unset aghostgc", G1))
        self.assertIn("not a registered ghost", self.run_cmd(".unset aghostgc", G1))

    def test_registry_survives_a_restart_and_match_end(self):
        self.run_cmd(".set alobbygc", L1)
        self.run_cmd(".set aghostgc", G1)
        again = self.make()
        self.assertEqual(again.registry.list("lobby"), [L1])
        self.assertEqual(again.registry.list("ghost"), [G1])

    def test_unset_is_refused_in_a_live_game(self):
        self.run_cmd(".set alobbygc", L1)
        self.run_cmd(".set aghostgc", G1)
        manager = self.coord._manager_for(L1)
        manager.game = mock.Mock(over=False)
        manager._ghosts_group_jid = G1
        self.assertIn("live game", self.run_cmd(".unset alobbygc", L1))
        self.assertIn("live game", self.run_cmd(".unset aghostgc", G1))
        self.assertIn("in a game", self.run_cmd(".alobbygcs", L1))
        self.assertIn("in use", self.run_cmd(".ghostgcs", L1))
        manager.game.over = True
        self.assertIn("no longer", self.run_cmd(".unset alobbygc", L1))

    def test_other_text_is_not_handled_here(self):
        self.assertIs(self.coord._registry_command(OWNER, ".set nonsense", L1), NOT_HANDLED)
        self.assertIs(self.coord._registry_command(OWNER, "hello", L1), NOT_HANDLED)

    def test_owner_check_fails_closed(self):
        coord = AmongUsCoordinator(mock.Mock(), registry=GroupRegistry(self.path), owner_check=lambda s: 1 / 0)
        self.assertIn("Only the bot owner", coord.pre_dispatch(OWNER, ".set alobbygc", group_jid=L1))


class GhostPick(Base):
    def setUp(self):
        super().setUp()
        for jid in (L1, L2):
            self.run_cmd(".set alobbygc", jid)
        for jid in (G1, G2):
            self.run_cmd(".set aghostgc", jid)

    def test_lobby_group_n_uses_ghost_group_n(self):
        self.assertEqual(self.coord._pick_ghost_group(self.coord._manager_for(L1)), G1)
        self.assertEqual(self.coord._pick_ghost_group(self.coord._manager_for(L2)), G2)

    def test_single_ghost_group_is_used_by_an_unregistered_lobby(self):
        self.run_cmd(".unset aghostgc", G2)
        other = self.coord._manager_for("120363000000000099@g.us")
        self.assertEqual(self.coord._pick_ghost_group(other), G1)

    def test_ambiguous_or_missing_gives_none(self):
        other = self.coord._manager_for("120363000000000099@g.us")
        self.assertIsNone(self.coord._pick_ghost_group(other))     # two ghosts, unregistered lobby
        self.run_cmd(".unset aghostgc", G2)
        self.run_cmd(".unset aghostgc", G1)
        self.assertIsNone(self.coord._pick_ghost_group(self.coord._manager_for(L1)))

    def test_a_ghost_group_in_a_live_match_is_not_reused(self):
        busy = self.coord._manager_for(L2)
        busy.game = mock.Mock(over=False)
        busy._ghosts_group_jid = G1
        self.assertIsNone(self.coord._pick_ghost_group(self.coord._manager_for(L1)))

    def test_match_start_picks_from_the_registry(self):
        manager = self.coord._manager_for(L2)
        manager.lobby = mock.Mock(players=["a", "b", "c", "d", "e"], started=False, host="a")
        with mock.patch("router.amongus.MIN_PLAYERS", 1), mock.patch("router.amongus_game.Game") as game:
            manager._lobby_start("a")
        self.assertEqual(manager._ghosts_group_jid, G2)


class Retired(unittest.TestCase):
    def test_setghostgroup_is_gone(self):
        manager = AmongUsManager(mock.Mock(), L1)
        self.assertFalse(hasattr(manager, "_set_ghost_group"))
        src = (Path(__file__).resolve().parents[1] / "bot/bridge.js").read_text()
        self.assertNotIn("setghostgroup", src)


if __name__ == "__main__":
    unittest.main()
