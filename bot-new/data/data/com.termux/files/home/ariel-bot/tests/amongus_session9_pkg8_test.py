"""Session 09 package 8 - unknown commands are silent; image-link folder.

1. While the Among Us pool is on, a command that does not exist gets NO reply
   from Among Us (no error text) anywhere: in a match, as a Ghost, in the lobby
   phase, in the game group, after a match.
2. Mini-preview images come only from direct links in assets/amongus/image_links.json.
"""
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import amongus_sim as S  # noqa: E402
from router import amongus_images as IMG  # noqa: E402
from router.amongus import NOT_HANDLED  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
JUNK = (".foo", ".debugrepair lights", ".notacommand 1 2", "hello there", ".amongus2", "scan")


class Base(unittest.TestCase):
    def new(self, n=5, seed=11):
        m = S.Match(n, seed)
        self.addCleanup(m.cleanup)
        return m


class UnknownCommandsAreSilent(Base):
    def test_no_error_text_is_left_in_the_source(self):
        for rel in ("engine/router/amongus.py", "engine/router/amongus_game.py"):
            text = (ROOT / rel).read_text(encoding="utf-8")
            for phrase in ("Not a recognized", "Not a recognised", "Try .amenu", "Ghosts can move with"):
                self.assertNotIn(phrase, text, f"{phrase!r} still in {rel}")

    def test_living_player_dm_gets_nothing(self):
        m = self.new()
        p = next(x for x in m.game.players.values() if x.role != "impostor")
        for text in JUNK:
            self.assertIsNone(m.mgr._pre_dispatch(p.jid, text), text)
        self.assertEqual(m.errors, [])

    def test_ghost_gets_nothing(self):
        m = self.new()
        p = next(x for x in m.game.players.values() if x.role != "impostor")
        p.alive = False
        for text in JUNK:
            self.assertIsNone(m.mgr._pre_dispatch(p.jid, text), text)

    def test_a_real_command_still_answers(self):
        m = self.new()
        p = next(x for x in m.game.players.values() if x.role != "impostor")
        self.assertTrue(m.mgr._pre_dispatch(p.jid, ".status"))
        self.assertTrue(m.mgr._pre_dispatch(p.jid, ".amenu"))

    def test_task_hint_for_plain_text_during_a_task_is_kept(self):
        m = self.new()
        p = next(x for x in m.game.players.values() if x.role != "impostor")
        task = next(t for t in p.tasks if not t["done"] and not t.get("fake"))
        p.room = task["room"]
        p.task_in_progress = {"task_id": task["id"], "interaction_ref": "I0001", "expected": "x",
                              "started_at": m.t, "last_activity_at": m.t, "expires_at": m.t + 60}
        self.assertIn("Reply to your quoted task prompt", m.mgr._pre_dispatch(p.jid, "hello there") or "")
        self.assertIsNone(m.mgr._pre_dispatch(p.jid, ".foo"))

    def test_group_unknown_command_passes_through_and_real_one_gets_the_private_notice(self):
        m = self.new()
        p = next(x for x in m.game.players.values() if x.role != "impostor")
        for text in (".foo", "hello there", ".pokedex"):
            out = m.mgr._pre_dispatch(p.jid, text, group_jid=S.GROUP)
            self.assertIs(out, NOT_HANDLED, text)
        self.assertIn("private", m.mgr._pre_dispatch(p.jid, ".status", group_jid=S.GROUP))

    def test_lobby_phase_and_after_the_match_pass_through(self):
        # lobby open, game not started
        r = S.SimRouter()
        from router.amongus import AmongUsManager
        mgr = AmongUsManager(r, S.GROUP)
        self.addCleanup(mgr._cancel_timer)
        jid = S.jid_for(1)
        mgr._pre_dispatch(jid, ".amongus on")
        for text in JUNK:
            self.assertIs(mgr._pre_dispatch(jid, text), NOT_HANDLED, text)
        # after a finished match
        m = self.new()
        m.game.close()
        p = next(iter(m.game.players.values()))
        for text in (".foo", ".m cafeteria"):
            self.assertIs(m.mgr._pre_dispatch(p.jid, text), NOT_HANDLED, text)


class ImageLinks(Base):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        self.tmp.close()
        self.addCleanup(os.unlink, self.tmp.name)
        self.old = os.environ.get("AMONGUS_IMAGE_LINKS")
        os.environ["AMONGUS_IMAGE_LINKS"] = self.tmp.name
        self.addCleanup(self._restore)

    def _restore(self):
        if self.old is None:
            os.environ.pop("AMONGUS_IMAGE_LINKS", None)
        else:
            os.environ["AMONGUS_IMAGE_LINKS"] = self.old

    def write(self, data):
        Path(self.tmp.name).write_text(json.dumps(data), encoding="utf-8")
        IMG._cache.update(mtime=None)  # force a re-read within the same mtime tick

    def test_shipped_file_is_valid_and_every_entry_is_blank_or_a_real_link(self):
        data = json.loads((ROOT / "assets" / "amongus" / "image_links.json").read_text(encoding="utf-8"))
        for kind in IMG.KINDS:
            self.assertIn("default", data[kind])
            self.assertEqual(len(data[kind]), 21)  # default + 20 colours
            self.assertTrue(all(v == "" or IMG._valid(v) for v in data[kind].values()))
        self.assertTrue(all(v == "" or IMG._valid(v) for v in data.get("maps", {}).values()))

    def test_lookup_order_and_validation(self):
        self.write({"meeting_call": {"default": "https://x.test/d.png", "red": "https://x.test/r.png",
                                     "blue": "not a link", "green": "  https://x.test/g.png  "}})
        self.assertEqual(IMG.image_link("meeting_call", "Red"), "https://x.test/r.png")
        self.assertEqual(IMG.image_link("meeting_call", "Blue"), "https://x.test/d.png")  # bad -> default
        self.assertEqual(IMG.image_link("meeting_call", "Green"), "https://x.test/g.png")
        self.assertEqual(IMG.image_link("meeting_call", "Pink"), "https://x.test/d.png")
        self.assertIsNone(IMG.image_link("ejection", "Red"))
        self.assertEqual(IMG.image_kwargs("ejection", "Red"), {})

    def test_missing_or_broken_file_means_no_image(self):
        Path(self.tmp.name).write_text("{not json", encoding="utf-8")
        IMG._cache.update(mtime=None)
        self.assertIsNone(IMG.image_link("meeting_call", "Red"))
        os.environ["AMONGUS_IMAGE_LINKS"] = self.tmp.name + ".missing"
        self.assertIsNone(IMG.image_link("meeting_call", "Red"))

    def _record(self, m):
        seen = []
        original = m.mgr._broadcast

        def spy(message, **kw):
            seen.append((message, kw))
            return original(message, **kw)

        m.mgr._broadcast = spy
        m.game.manager = m.mgr
        return seen

    def test_meeting_call_and_ejection_carry_the_links(self):
        m = self.new()
        imp = next(p for p in m.game.players.values() if p.role == "impostor")
        crew = [p for p in m.game.players.values() if p.role != "impostor"]
        caller = crew[0]
        self.write({
            "meeting_call": {caller.color.lower(): "https://x.test/call.png"},
            "ejection": {"default": "https://x.test/eject.png"},
        })
        seen = self._record(m)
        m.send(caller.jid, ".meeting")
        call = [x for x in seen if "called an emergency meeting!" in x[0]]
        self.assertEqual(call[0][1].get("image_url"), "https://x.test/call.png")
        for _ in range(60):
            m.tick()
        for p in crew:
            m.send(p.jid, f".vote {imp.color}")
        for _ in range(31):
            m.tick()
        reveal = [x for x in seen if "Meeting ended" in x[0] or x[0] in ("...", ".......") or "was an Impostor" in x[0]]
        self.assertEqual(len(reveal), 4)
        self.assertEqual([("image_url" in kw) for _, kw in reveal], [False, False, False, True])
        self.assertEqual(reveal[3][1]["image_url"], "https://x.test/eject.png")

    def test_no_links_means_no_image_argument_at_all(self):
        m = self.new()
        caller = next(p for p in m.game.players.values() if p.role != "impostor")
        self.write({"meeting_call": {"default": ""}, "ejection": {"default": ""}})
        seen = self._record(m)
        m.send(caller.jid, ".meeting")
        self.assertTrue(seen)
        self.assertTrue(all("image_url" not in kw for _, kw in seen))

    def test_bridge_files_pass_the_field_along(self):
        self.assertIn('"image_url": image_url', (ROOT / "engine" / "bridge.py").read_text(encoding="utf-8"))
        js = (ROOT / "bot" / "bridge.js").read_text(encoding="utf-8")
        self.assertIn("item.image_url", js)
        self.assertRegex(js, r"sendImage\(botState\.activeSockRef, targetJid, item\.image_url")


if __name__ == "__main__":
    unittest.main(verbosity=1)
