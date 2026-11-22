"""Command-sheet note, Session 8: image slots (lobby artwork, ship map at start, TASKS LIST)."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import amongus_sim as S  # noqa: E402
import amongus_session9_pkg5_test as P5  # noqa: E402
import amongus_session7d_test as T7  # noqa: E402
from router import amongus_images as IMG  # noqa: E402

LOBBY = "https://example.test/lobby.png"
TASKS = "https://example.test/tasks.png"
MAP = "https://example.test/skeld.jpg"


def use_links(case, data):
    tmp = tempfile.TemporaryDirectory()
    path = Path(tmp.name) / "links.json"
    path.write_text(json.dumps(data))
    os.environ["AMONGUS_IMAGE_LINKS"] = str(path)
    IMG._cache.update(path=None, mtime=None, data={})
    case.addCleanup(tmp.cleanup)
    case.addCleanup(lambda: os.environ.pop("AMONGUS_IMAGE_LINKS", None))
    case.addCleanup(lambda: IMG._cache.update(path=None, mtime=None, data={}))


class Slots(unittest.TestCase):
    def test_slots_read_and_blank_is_none(self):
        use_links(self, {"lobby": LOBBY, "tasks_list": ""})
        self.assertEqual(IMG.lobby_link(), LOBBY)
        self.assertIsNone(IMG.tasks_list_link())

    def test_malformed_link_is_ignored(self):
        use_links(self, {"lobby": "not a url", "tasks_list": TASKS})
        self.assertIsNone(IMG.lobby_link())
        self.assertEqual(IMG.tasks_list_link(), TASKS)

    def test_shipped_json_has_slots(self):
        data = json.loads((Path(__file__).resolve().parents[1] / "assets/amongus/image_links.json").read_text())
        for key in ("lobby", "tasks_list"):
            self.assertIn(key, data)
            self.assertTrue(data[key] == "" or data[key].startswith("https://"))


class RecRouter(S.SimRouter):
    def __init__(self):
        super().__init__()
        self.calls = []

    def _direct_send(self, message, group_jid=None, allow_dm=False, **kw):
        self.calls.append((message, group_jid, allow_dm, kw))
        super()._direct_send(message, group_jid=group_jid, allow_dm=allow_dm, **kw)


class LobbyFlow(unittest.TestCase):
    def mgr(self):
        from router.amongus import AmongUsManager
        router = RecRouter()
        m = AmongUsManager(router, S.GROUP)
        m.game_kwargs = {"start_clock": False}
        self.addCleanup(lambda: m.game and m.game.close())
        return m, router, [S.jid_for(i) for i in range(1, 6)]

    def test_lobby_open_without_link_is_plain_text_reply(self):
        use_links(self, {})
        m, router, jids = self.mgr()
        out = m._pre_dispatch(jids[0], ".lobby open", group_jid=S.GROUP)
        self.assertIn("Lobby #", out)
        self.assertEqual(router.calls, [])

    def test_lobby_open_with_link_sends_artwork_to_the_group(self):
        use_links(self, {"lobby": LOBBY})
        m, router, jids = self.mgr()
        out = m._pre_dispatch(jids[0], ".lobby open", group_jid=S.GROUP)
        self.assertIsNone(out)
        ((text, group, dm, kw),) = router.calls
        self.assertIn("🛰️ *Lobby #", text)
        self.assertEqual((group, dm, kw.get("image_url")), (S.GROUP, False, LOBBY))

    def test_start_sends_ship_map_to_group_only(self):
        use_links(self, {"maps": {"skeld": MAP}})
        m, router, jids = self.mgr()
        m._pre_dispatch(jids[0], ".lobby open", group_jid=S.GROUP)
        for j in jids[1:]:
            m._pre_dispatch(j, ".join", group_jid=S.GROUP)
        router.calls.clear()
        m._pre_dispatch(jids[0], ".lobby start", group_jid=S.GROUP)
        live = [c for c in router.calls if "Game live on" in c[0]]
        self.assertEqual(len(live), 1)
        self.assertEqual(live[0][3].get("image_url"), MAP)
        self.assertFalse(live[0][2])
        dms = [c for c in router.calls if c[2]]
        self.assertTrue(dms)
        self.assertNotIn(MAP, [c[3].get("image_url") for c in dms])

    def test_start_without_map_link_has_no_image(self):
        use_links(self, {})
        m, router, jids = self.mgr()
        m._pre_dispatch(jids[0], ".lobby open", group_jid=S.GROUP)
        for j in jids[1:]:
            m._pre_dispatch(j, ".join", group_jid=S.GROUP)
        router.calls.clear()
        m._pre_dispatch(jids[0], ".lobby start", group_jid=S.GROUP)
        live = [c for c in router.calls if "Game live on" in c[0]]
        self.assertNotIn("image_url", live[0][3])


class TasksPicture(unittest.TestCase):
    def setUp(self):
        self.game = P5.new_game()
        self.addCleanup(self.game.close)
        self.pushed = []
        self.game.manager._push_dm = lambda jid, msg, **kw: self.pushed.append((jid, msg, kw))

    def test_living_player_gets_picture_with_the_same_text(self):
        use_links(self, {"tasks_list": TASKS})
        red = T7.player(self.game, "Red")
        out = self.game._cmd_tasks_all(red)
        self.assertIsNone(out)
        ((jid, text, kw),) = self.pushed
        self.assertEqual((jid, kw), (red.jid, {"image_url": TASKS, "image_card": True}))
        self.assertTrue(text.startswith("📋 *TASKS LIST*"))
        self.assertEqual(text, self.game._tasks_all_text(red))

    def test_no_link_returns_text(self):
        use_links(self, {})
        red = T7.player(self.game, "Red")
        out = self.game._cmd_tasks_all(red)
        self.assertTrue(out.startswith("📋 *TASKS LIST*"))
        self.assertEqual(self.pushed, [])

    def test_ghost_list_stays_text(self):
        use_links(self, {"tasks_list": TASKS})
        blue = T7.player(self.game, "Blue")
        blue.alive = False
        out = self.game._cmd_tasks_all(blue)
        self.assertIsInstance(out, str)
        self.assertEqual(self.pushed, [])


if __name__ == "__main__":
    unittest.main()
