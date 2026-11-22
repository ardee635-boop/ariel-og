"""Session 09 package 10 - `.map`: the Skeld picture + the caller's own position and exits."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import amongus_sim as S  # noqa: E402
from amongus_session9_pkg7_test import Base, advance, crew, impostors, place, spread  # noqa: E402
from router import amongus_images as IMG  # noqa: E402
from router import amongus_map as M  # noqa: E402

URL = "https://example.test/skeld.jpg"


class MapCmd(Base):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        path = Path(self.dir.name) / "links.json"
        path.write_text(json.dumps({"maps": {"skeld": URL}}))
        os.environ["AMONGUS_IMAGE_LINKS"] = str(path)
        IMG._cache.update(path=None, mtime=None, data={})
        self.addCleanup(self.dir.cleanup)
        self.addCleanup(lambda: os.environ.pop("AMONGUS_IMAGE_LINKS", None))
        self.addCleanup(lambda: IMG._cache.update(path=None, mtime=None, data={}))

    def pushes(self, m, jid):
        return [x for x in m.router.dm_extra if x[0] == jid] if hasattr(m.router, "dm_extra") else []

    def test_link_is_read_from_the_maps_section(self):
        self.assertEqual(IMG.map_link("skeld"), URL)
        self.assertIsNone(IMG.map_link("nowhere"))

    def test_map_sends_picture_with_own_room_and_exits(self):
        m = self.new(5)
        p = crew(m)[0]
        spread(m)
        place(m, p, "CAFETERIA")
        sent = []
        orig = m.mgr._push_dm
        m.mgr._push_dm = lambda jid, msg, image_url=None: sent.append((jid, msg, image_url))
        out = m.send(p.jid, ".map")
        self.assertIsNone(out)
        self.assertEqual(len(sent), 1)
        jid, caption, url = sent[0]
        self.assertEqual((jid, url), (p.jid, URL))
        self.assertIn("The Skeld", caption)
        self.assertIn("You are currently at the Cafeteria.", caption)
        for room, secs in M.get_map().edges["CAFETERIA"].items():
            self.assertIn(f"{room.replace('_', ' ').title()} ({int(secs)}s)", caption)
        self.assertNotIn("@", caption)                       # no identities
        for other in m.game.players.values():                # nobody else's position
            if other.jid != p.jid:
                self.assertNotIn(other.color, caption)
        m.mgr._push_dm = orig

    def test_without_a_link_the_same_text_comes_back_as_the_reply(self):
        os.environ["AMONGUS_IMAGE_LINKS"] = str(Path(self.dir.name) / "missing.json")
        IMG._cache.update(path=None, mtime=None, data={})
        m = self.new(5)
        p = crew(m)[0]
        spread(m)
        place(m, p, "MEDBAY")
        out = m.send(p.jid, ".map")
        self.assertIn("You are currently at the Medbay.", out)
        self.assertIn("Use .m <room> to move.", out)

    def test_in_a_corridor_and_in_a_vent(self):
        m = self.new(7)
        p = crew(m)[0]
        spread(m)
        place(m, p, "CAFETERIA")
        m.t += 1
        m.send(p.jid, ".m Medbay")
        advance(m, 2)
        sent = []
        m.mgr._push_dm = lambda jid, msg, image_url=None: sent.append(msg)
        m.send(p.jid, ".map")
        self.assertRegex(sent[-1], r"You are currently (between the|inside a vent at the|at the) ")
        imp = impostors(m)[0]
        place(m, imp, "ELECTRICAL")
        m.send(imp.jid, ".vent in")
        m.send(imp.jid, ".map")
        self.assertIn("inside a vent at the Electrical", sent[-1])
        self.assertNotIn("Exits:", sent[-1])

    def test_works_for_a_ghost_and_during_a_meeting(self):
        m = self.new(6)
        sent = []
        m.mgr._push_dm = lambda jid, msg, image_url=None: sent.append((jid, msg))
        spread(m)
        ghost = crew(m)[0]
        ghost.alive = False
        m.send(ghost.jid, ".map")
        self.assertTrue(sent and "The Skeld" in sent[-1][1])
        living = crew(m)[1]
        m.send(living.jid, ".meeting")
        self.assertTrue(m.game._meeting)
        n = len(sent)
        m.send(living.jid, ".map")
        self.assertEqual(len(sent), n + 1)                  # not blocked by the meeting
        self.assertEqual(m.errors, [])

    def test_before_the_match_a_lobby_member_gets_the_picture(self):
        from router.amongus import AmongUsManager
        mgr = AmongUsManager(S.SimRouter(), S.GROUP)
        self.addCleanup(mgr._cancel_timer)
        a, b = S.jid_for(1), S.jid_for(2)
        mgr._pre_dispatch(a, ".amongus on")
        mgr._pre_dispatch(a, ".lobby open", group_jid=S.GROUP)
        sent = []
        mgr._push_dm = lambda jid, msg, image_url=None: sent.append((jid, msg, image_url))
        self.assertIsNone(mgr._pre_dispatch(a, ".map"))
        self.assertEqual(sent[0][0], a)
        self.assertEqual(sent[0][2], URL)
        self.assertIn("has not started", sent[0][1])
        from router.amongus import NOT_HANDLED
        self.assertIs(mgr._pre_dispatch(b, ".map"), NOT_HANDLED)   # not in the lobby


if __name__ == "__main__":
    unittest.main(verbosity=1)
