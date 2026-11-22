"""Package 13: player-facing text from design note v5.3, section 22."""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "engine"))
import amongus_session9_pkg5_test as P5  # noqa: E402
import amongus_session7d_test as T7  # noqa: E402
from router import amongus_config as C  # noqa: E402


class V53Text(unittest.TestCase):
    def setUp(self):
        step = mock.patch.object(C, "EJECTION_REVEAL_STEP_SECONDS", 0.0)
        step.start()
        self.addCleanup(step.stop)
        self.game = P5.new_game()
        self.addCleanup(self.game.close)

    def test_status_layout_has_no_nested_asterisks(self):
        game = self.game
        red = T7.player(game, "Red")
        text = game._cmd_status(red, now=P5.T)
        lines = text.splitlines()
        self.assertEqual(lines[0], "📍 *YOUR STATUS*")
        self.assertTrue(lines[1].startswith("Role: "))
        self.assertTrue(lines[2] in ("Status: Alive", "Status: Ghost"))
        self.assertTrue(any(l.startswith("Players with you: ") for l in lines))
        self.assertTrue(any(l.startswith("Bodies here: ") for l in lines))
        self.assertIn("Cooldowns: use *.cds*", lines)
        self.assertIn("Match: In progress", lines)
        self.assertNotIn("**", text)                         # still no nested asterisks

    def test_where_and_tasks_list(self):
        game = self.game
        red = T7.player(game, "Red")
        red.settled = True
        out = game.movement.where(red, P5.T)
        self.assertTrue(out.startswith("📍 *Your location*\n*"))
        self.assertEqual(len(out.splitlines()), 2)
        blue = T7.player(game, "Blue")
        self.assertIn("TASKS LIST", game._cmd_tasks_all(blue))

    def test_voting_open_and_staged_no_ejection(self):
        game = self.game
        P5.call_meeting(game)
        game._advance_meeting(P5.OPEN)
        self.assertIn("Voting is open", game.manager.broadcasts[-1])
        game._resolve_meeting(P5.END)
        tail = game.manager.broadcasts[-4:]
        self.assertEqual(tail[1:3], ["...", "......."])
        self.assertEqual(tail[3], "No one was ejected.\nCarry on...")


if __name__ == "__main__":
    unittest.main(verbosity=2)
