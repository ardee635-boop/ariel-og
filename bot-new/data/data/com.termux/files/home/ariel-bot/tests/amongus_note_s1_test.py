"""Command-sheet note, Session 1: lobby and setup wording (section A)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "engine"))
import amongus_sim as S  # noqa: E402


class LobbyText(unittest.TestCase):
    def lobby(self, n):
        m = S.Match.__new__(S.Match)
        import random
        from router.amongus import AmongUsManager
        random.seed(3)
        m.router = S.SimRouter()
        m.mgr = AmongUsManager(m.router, S.GROUP)
        m.mgr.game_kwargs = {"start_clock": False}
        m.jids = [S.jid_for(i) for i in range(1, n + 1)]
        m.t, m.replies, m.errors = S.T0, [], []
        return m

    def say(self, m, who, text):
        return m.mgr._pre_dispatch(m.jids[who], text, group_jid=S.GROUP)

    def test_on_open_join_leave_list(self):
        m = self.lobby(5)
        for j in m.jids:
            m.mgr._pre_dispatch(j, ".amongus on")
        on = m.mgr._pre_dispatch(m.jids[0], ".amongus on", group_jid=S.GROUP)
        self.assertIn("Use *.amongus off* to turn it off for this group.", on)
        self.assertEqual(
            self.say(m, 0, ".lobby list"),
            "🛰️ _There is no open lobby right now._\nUse *.lobby open* to create one.",
        )
        opened = self.say(m, 0, ".lobby open")
        self.assertIn("Players: 1/20", opened)
        self.assertIn("at least 4 players", opened)
        joined = self.say(m, 1, ".join")
        self.assertTrue(joined.startswith("✅ *Player 2 joined the lobby.*"))
        self.assertIn("Players: 2/20", joined)
        self.assertIn("*Lobby players*\n1. Player 1\n2. Player 2", joined)
        self.assertNotIn("@", joined)                       # no ids/colours leak
        self.assertEqual(self.say(m, 1, ".leave"), "👋 You left the lobby.")

    def test_start_role_dms_and_group_line(self):
        m = self.lobby(5)
        for j in m.jids:
            m.mgr._pre_dispatch(j, ".amongus on")
        self.say(m, 0, ".lobby open")
        for i in range(1, 5):
            self.say(m, i, ".join")
        dms = []
        orig = m.mgr._push_dm
        m.mgr._push_dm = lambda jid, msg, **kw: (dms.append((jid, msg)), orig(jid, msg, **kw))[1]
        self.say(m, 0, ".lobby start")
        self.assertEqual(len(dms), 5)
        for _, msg in dms:
            lines = msg.splitlines()
            self.assertTrue(lines[0].startswith("🚀 *Your role: "))
            self.assertTrue(lines[1].startswith("Colour: *"))
            self.assertTrue(lines[2].startswith("Starting room: *"))
            self.assertTrue(msg.endswith("Use *.amenu* to view commands."))
        imp = [msg for _, msg in dms if "IMPOSTOR" in msg.splitlines()[0]]
        crew = [msg for _, msg in dms if "IMPOSTOR" not in msg.splitlines()[0]]
        self.assertTrue(imp and all("Fellow impostor(s):" in x for x in imp))
        self.assertTrue(all("Fellow" not in x for x in crew))   # nothing leaks to crew
        live = m.router.group[-1][1]
        self.assertTrue(live.startswith("🚀 *Game live on "))
        self.assertIn("Players: 5 · Impostors: 1", live)
        self.assertIn("starting location", live)
        m.mgr.game.close()
        m.mgr._cancel_timer()

    def test_prematch_map_text(self):
        m = self.lobby(4)
        for j in m.jids:
            m.mgr._pre_dispatch(j, ".amongus on")
        self.say(m, 0, ".lobby open")
        self.say(m, 1, ".join")
        dms = []
        orig = m.mgr._push_dm
        m.mgr._push_dm = lambda jid, msg, **kw: (dms.append(msg), orig(jid, msg, **kw))[1]
        out = self.say(m, 1, ".map")
        caption = out if out is not None else dms[-1]         # image link set -> sent as DM caption
        lines = caption.splitlines()
        self.assertTrue(lines[0].startswith("🗺️ *") and lines[0].endswith("*"))
        self.assertTrue(lines[1].startswith("The match has not started yet. Your starting room is *"))
        self.assertNotIn("_", caption)                         # old italics removed

    def test_endgame_text(self):
        m = self.lobby(5)
        for j in m.jids:
            m.mgr._pre_dispatch(j, ".amongus on")
        self.say(m, 0, ".lobby open")
        for i in range(1, 5):
            self.say(m, i, ".join")
        self.say(m, 0, ".lobby start")
        self.addCleanup(lambda: (m.mgr.game.close(), m.mgr._cancel_timer()))
        self.say(m, 0, ".endgame")
        self.assertIn("🛑 *Match ended by the host.*\nNo winner was declared.", m.router.group[-1][1])


if __name__ == "__main__":
    unittest.main(verbosity=2)
