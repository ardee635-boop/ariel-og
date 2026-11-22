"""Lobby map selection: `.lobby map`, random default, new maps are playable graphs."""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import amongus_sim as S  # noqa: E402,F401
from router import amongus_map as M  # noqa: E402
from router import amongus_stage as STAGE  # noqa: E402


class MapData(unittest.TestCase):
    def test_every_map_is_connected_and_consistent(self):
        for map_id in M.MAP_ORDER:
            d = M.get_map(map_id)
            seen, stack = {d.start_room}, [d.start_room]
            while stack:
                for nbr in d.edges[stack.pop()]:
                    if nbr not in seen:
                        seen.add(nbr)
                        stack.append(nbr)
            self.assertEqual(seen, set(d.rooms), map_id)
            self.assertEqual(set(d.tasks), set(d.rooms), map_id)
            for room, outs in d.vents.items():
                self.assertIn(room, d.rooms)
                self.assertTrue(set(outs) <= set(d.rooms))
            for name in ("lights", "communications", "oxygen", "reactor"):
                for room in M.get_station_rooms(name, map_id):
                    self.assertIn(room, d.rooms)

    def test_resolve(self):
        self.assertEqual(M.resolve_map("1"), "skeld")
        self.assertEqual(M.resolve_map("2"), "cyberia")
        self.assertEqual(M.resolve_map("Orbital Research Station"), "orbital")
        self.assertEqual(M.resolve_map("the skeld"), "skeld")
        self.assertIsNone(M.resolve_map("0"))
        self.assertIsNone(M.resolve_map("nope"))

    def test_random_and_pin(self):
        old = os.environ.pop("AMONGUS_FIXED_MAP", None)
        try:
            self.assertEqual({M.random_map_id() for _ in range(200)}, set(M.MAP_ORDER))
            os.environ["AMONGUS_FIXED_MAP"] = "orbital"
            self.assertEqual(M.random_map_id(), "orbital")
        finally:
            os.environ.pop("AMONGUS_FIXED_MAP", None)
            if old:
                os.environ["AMONGUS_FIXED_MAP"] = old

    def test_scene_background_falls_back_to_default(self):
        self.assertTrue(STAGE.stage_url("square", None, "emergency"))
        self.assertEqual(STAGE.stage_url("square", None, "nonexistent"),
                         STAGE.stage_url("square", None))


if __name__ == "__main__":
    unittest.main()
