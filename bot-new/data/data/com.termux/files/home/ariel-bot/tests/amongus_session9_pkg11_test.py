"""Session 09 package 11 - stage previews: colour character on the stage background.

square stage = mini preview (meeting call, ejection, .status); landscape = full preview (role DM).
Pictures are synthetic (Pillow) and placed straight into the cache, so nothing touches the network.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import amongus_sim as S  # noqa: E402
from amongus_session9_pkg7_test import Base, advance, crew, impostors, place, spread  # noqa: E402
from PIL import Image  # noqa: E402
from router import amongus_images as IMG  # noqa: E402
from router import amongus_stage as ST  # noqa: E402

SQ, LS, SQ_IMP = "https://x.test/square.jpg", "https://x.test/land.jpg", "https://x.test/square_imp.jpg"
CHAR = "https://x.test/{}.png"
COLOURS = ["red", "blue", "green", "pink", "orange", "yellow", "black", "white", "purple", "brown", "cyan", "lime"]


def make_stage(path, size, rgb):
    Image.new("RGB", size, rgb).save(path, "JPEG")


def make_char(path, opaque=False):
    img = Image.new("RGBA", (200, 300), (255, 0, 0, 255) if opaque else (0, 0, 0, 0))
    if not opaque:
        for x in range(40, 160):
            for y in range(30, 270):
                img.putpixel((x, y), (255, 0, 0, 255))
    img.save(path, "PNG")


class StageBase(Base):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.links = Path(self.dir.name) / "links.json"
        os.environ["AMONGUS_IMAGE_LINKS"] = str(self.links)
        os.environ["AMONGUS_STAGE_CACHE"] = str(Path(self.dir.name) / "cache")
        self.addCleanup(lambda: [os.environ.pop(k, None) for k in ("AMONGUS_IMAGE_LINKS", "AMONGUS_STAGE_CACHE")])
        self.addCleanup(lambda: IMG._cache.update(path=None, mtime=None, data={}))
        self.write_links()
        IMG._cache.update(path=None, mtime=None, data={})

    def write_links(self, **over):
        data = {
            "stage": {"square": {"default": SQ, "impostor": SQ_IMP}, "landscape": {"default": LS}},
            "characters": {c: CHAR.format(c) for c in COLOURS},
            "meeting_call": {"default": "", "red": "https://x.test/raw_red.png"},
            "ejection": {"default": "", "red": "https://x.test/raw_red_ej.png"},
        }
        data.update(over)
        self.links.write_text(json.dumps(data))
        IMG._cache.update(mtime=None)

    def stock(self, opaque_chars=False):
        make_stage(ST._local(SQ), (600, 600), (10, 20, 80))
        make_stage(ST._local(SQ_IMP), (600, 600), (80, 10, 10))
        make_stage(ST._local(LS), (1200, 675), (10, 20, 80))
        for c in COLOURS:
            make_char(ST._local(CHAR.format(c)), opaque=opaque_chars)


class Compose(StageBase):
    def test_layout_puts_the_character_on_the_left_inside_the_stage(self):
        for size in ST.SIZES:
            x, y, w, h = ST.layout_box(size, 600, 600, 120, 240)
            self.assertLess(x, 600 * 0.2)
            self.assertGreaterEqual(y, 0)
            self.assertLessEqual(x + w, 600)
            self.assertLessEqual(y + h, 600)
        x, y, w, h = ST.layout_box("square", 600, 600, 5000, 100)   # absurdly wide character is capped
        self.assertLessEqual(w, 600 * 0.6 + 1)

    def test_square_and_landscape_composites_use_the_right_stage(self):
        self.stock()
        sq, ls = ST.compose("square", "red"), ST.compose("landscape", "red")
        self.assertTrue(sq and ls and sq != ls)
        a, b = Image.open(sq), Image.open(ls)
        self.assertEqual(a.size, (600, 600))
        self.assertEqual(b.size, (900, round(675 * 900 / 1200)))        # longest side capped at 900
        # background pixel far from the character is the stage colour; the character area is red
        self.assertEqual(a.getpixel((590, 5))[2] > 60, True)
        x, y, w, h = ST.layout_box("square", 600, 600, 120, 240)
        cx, cy = x + w // 2, y + h // 2
        r, g, bl = a.getpixel((cx, cy))
        self.assertGreater(r, 180)
        self.assertLess(bl, 90)

    def test_role_specific_background_else_default(self):
        self.stock()
        imp = Image.open(ST.compose("square", "red", "impostor")).getpixel((590, 5))
        crewm = Image.open(ST.compose("square", "red", "crewmate")).getpixel((590, 5))
        self.assertGreater(imp[0], 60)      # reddish impostor stage
        self.assertGreater(crewm[2], 60)    # default (blue) stage

    def test_result_is_cached_and_reused(self):
        self.stock()
        first = ST.compose("square", "blue")
        mtime = Path(first).stat().st_mtime_ns
        self.assertEqual(ST.compose("square", "blue"), first)
        self.assertEqual(Path(first).stat().st_mtime_ns, mtime)

    def test_never_composites_an_opaque_character_and_never_raises(self):
        self.stock(opaque_chars=True)
        self.assertIsNone(ST.compose("square", "red"))
        self.assertIsNone(ST.compose("square", "nobody"))
        self.assertIsNone(ST.compose("bogus", "red"))

    def test_nothing_downloaded_yet_means_none_not_a_wait(self):
        os.environ["AMONGUS_STAGE_OFFLINE"] = "1"
        self.assertIsNone(ST.compose("square", "red"))
        self.assertIsNone(ST.warm(COLOURS))                 # offline: no thread, no network

    def test_preview_kwargs_falls_back_to_the_plain_colour_link(self):
        self.assertEqual(ST.preview_kwargs("square", "red", None, kind="meeting_call"),
                         {"image_url": "https://x.test/raw_red.png"})
        self.assertEqual(ST.preview_kwargs("square", "red"), {})
        self.stock()
        self.assertTrue(ST.preview_kwargs("square", "red", None, kind="meeting_call")["image_url"].endswith(".jpg"))


class Wiring(StageBase):
    def capture(self, m):
        sent = []
        m.mgr._push_dm = lambda jid, msg, image_url=None: sent.append(("dm", jid, msg, image_url))
        orig = m.router._direct_send
        def spy(message, **kw):
            sent.append(("group" if str(kw.get("group_jid", "")).endswith("@g.us") else "send", kw.get("group_jid"), message, kw.get("image_url")))
            return orig(message, **kw)
        m.router._direct_send = spy
        return sent

    def test_status_leads_with_the_players_own_preview_when_ready(self):
        self.stock()
        m = self.new(5)
        p = crew(m)[0]
        spread(m)
        place(m, p, "CAFETERIA")
        sent = self.capture(m)
        out = m.send(p.jid, ".status")
        self.assertIsNone(out)
        kind, jid, text, url = sent[-1]
        self.assertEqual((kind, jid), ("dm", p.jid))
        self.assertIn("Status", text)
        self.assertTrue(url and url.endswith(".jpg") and Path(url).exists())

    def test_status_is_plain_text_when_no_picture_is_ready(self):
        m = self.new(5)
        p = crew(m)[0]
        spread(m)
        place(m, p, "CAFETERIA")
        self.assertIn("Status", m.send(p.jid, ".status"))

    def test_impostor_status_uses_the_impostor_background_and_a_ghost_gets_one_too(self):
        self.stock()
        m = self.new(6)
        imp = impostors(m)[0]
        sent = self.capture(m)
        m.send(imp.jid, ".status")
        self.assertEqual(Path(sent[-1][3]).name, Path(ST.compose("square", imp.color, "impostor")).name)
        ghost = crew(m)[0]
        ghost.alive = False
        m.send(ghost.jid, ".status")
        self.assertTrue(sent[-1][3])

    def test_meeting_call_uses_the_callers_preview_and_never_a_role_background(self):
        self.stock()
        m = self.new(5)
        caller = impostors(m)[0]          # an Impostor calling must not give the role away
        spread(m)
        place(m, caller, "CAFETERIA")
        sent = self.capture(m)
        m.send(caller.jid, ".meeting")
        group = [x for x in sent if x[0] == "group" and "called an emergency meeting!" in x[2]]
        self.assertTrue(group and group[0][3])
        self.assertEqual(Path(group[0][3]).name, Path(ST.compose("square", caller.color, None)).name)

    def test_ejection_reveal_carries_the_role_background(self):
        self.stock()
        m = self.new(5)
        imp = impostors(m)[0]
        c = crew(m)
        spread(m)
        sent = self.capture(m)
        m.send(c[0].jid, ".meeting")
        advance(m, 61)
        for v in c:
            if v.alive:
                m.send(v.jid, f".vote {imp.color}")
        advance(m, 40)
        reveal = [x for x in sent if "was an Impostor" in x[2]]
        self.assertTrue(reveal and reveal[0][3])
        self.assertEqual(Path(reveal[0][3]).name, Path(ST.compose("square", imp.color, "impostor")).name)

    def test_role_dm_uses_the_landscape_picture(self):
        self.stock()
        m = S.Match.__new__(S.Match)
        # build a match with a capture installed BEFORE roles are announced
        import random
        from router.amongus import AmongUsManager
        random.seed(5)
        m.router = S.SimRouter()
        calls = []
        orig = m.router._direct_send
        m.router._direct_send = lambda message, **kw: (calls.append((kw.get("group_jid"), message, kw.get("image_url"))), orig(message, **kw))[1]
        m.mgr = AmongUsManager(m.router, S.GROUP)
        m.mgr.game_kwargs = {"start_clock": False}
        m.jids = [S.jid_for(i) for i in range(1, 6)]
        m.t, m.replies, m.errors = S.T0, [], []
        for j in m.jids:
            m.mgr._pre_dispatch(j, ".amongus on")
        m.mgr._pre_dispatch(m.jids[0], ".lobby open", group_jid=S.GROUP)
        for j in m.jids[1:]:
            m.mgr._pre_dispatch(j, ".join", group_jid=S.GROUP)
        m.mgr._pre_dispatch(m.jids[0], ".lobby start", group_jid=S.GROUP)
        self.addCleanup(lambda: (m.mgr.game.close(), m.mgr._cancel_timer()))
        role_dms = [c for c in calls if "Your role:" in c[1]]
        self.assertEqual(len(role_dms), 5)
        for jid, text, url in role_dms:
            self.assertTrue(url and url.endswith(".jpg"), text)
            im = Image.open(url)
            self.assertEqual(im.size[0] / im.size[1] > 1.5, True)           # landscape


if __name__ == "__main__":
    unittest.main(verbosity=1)
