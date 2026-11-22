"""Command-sheet note, Session 6: sabotage and repair wording (section F)."""
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import amongus_session7b1bii_test as L  # noqa: E402  (lights scene: red/blue crew, pink impostor)
import amongus_session9_pkg4_test as D4  # noqa: E402
import amongus_session7d_test as T7  # noqa: E402

REACH = "Reach the required station(s) and finish the repair."


class SabotageText(unittest.TestCase):
    def test_warning_and_repaired_use_display_names(self):
        for name, shown in (("reactor", "Reactor"), ("lights", "Lights"), ("oxygen", "O₂")):
            game = D4.new_game()
            self.addCleanup(game.close)
            T7.sabotage(game, name, 100.0)
            deadline = game._sabotages[name].get("deadline")
            if deadline is None:                                   # Lights has no timer
                continue
            game._advance_sabotages(deadline - 20)
            game._advance_sabotages(deadline - 10)
            self.assertIn(f"⚠️ *{shown}: 20s remaining.*\n{REACH}", game.manager.broadcasts)
            self.assertIn(f"⚠️ *{shown}: 10s remaining.*\n{REACH}", game.manager.broadcasts)

    def test_repaired_text(self):
        game = D4.new_game()
        self.addCleanup(game.close)
        T7.sabotage(game, "reactor", 100.0)
        T7.repair_paired(game, "reactor", "Red", "Blue", 110.0)
        self.assertIn("✅ *Reactor sabotage repaired.* The ship is safe for now.", game.manager.broadcasts)

    def test_failure_headlines_moved_to_n7_wording(self):
        from router import amongus_game as G
        self.assertEqual(G.SABOTAGE_FAILURE_TEXT["reactor"], "☢️ *Reactor meltdown — Impostors win.*")
        self.assertIn("The oxygen supply has run out.", G.SABOTAGE_FAILURE_TEXT["oxygen"])


class RepairPrompts(unittest.TestCase):
    def test_lights_prompt(self):
        game = L.make_game()
        self.addCleanup(L.close_game, game)
        L.start_scene(game)
        out = L.command(game, "red", ".task", 110.0)
        lines = out.splitlines()
        self.assertEqual(lines[0], "🧩 *Lights repair*")
        self.assertTrue(lines[1].startswith("🔌 *Lights circuit* ("))
        self.assertEqual(out.count("Send a number from 1 to"), 0)         # hint appears once, below
        self.assertRegex(out, r"Reply to this message with a switch number from 1 to \d+, or use \*\.task answer <number>\*\.")
        self.assertIn("_This interaction expires after 60s without activity._", out)
        self.assertRegex(lines[-1], r"^\[Task Ref: I\d+\]$")
        again = L.command(game, "red", ".task answer 1", 111.0)           # later presses still say what to send
        self.assertRegex(again, r"Send a number from 1 to \d+\.")

    def test_comms_group_prompt(self):
        game = L.make_game()
        self.addCleanup(L.close_game, game)
        game.players["red"].room = "COMMUNICATIONS"
        game._cmd_sabotage(game.players["pink"], "communications", now=100)
        dm = L.command(game, "red", ".task", 110.0)
        self.assertIn("Answer *in the game group*", dm)                   # DM text unchanged
        notice = next(m for m in game.manager.broadcasts if "Unscramble: *" in m)
        self.assertTrue(notice.startswith("📡 *Communications repair*\nUnscramble: *"))
        self.assertIn("Only Red can submit the answer in the game group. Reply to this transmission message or use *.task answer <phrase>*.", notice)
        self.assertRegex(notice.splitlines()[-1], r"^\[Task Ref: I\d+\]$")

    def test_scan_missed_text(self):
        import inspect
        from router import amongus_paired as P
        src = inspect.getsource(P)
        self.assertEqual(src.count("Send *scan* again together when both stations are ready."), 2)
        self.assertNotIn("Send *scan* again, together.", src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
