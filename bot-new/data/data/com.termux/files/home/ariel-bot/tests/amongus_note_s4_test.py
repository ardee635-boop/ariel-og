"""Command-sheet note, Session 4: impostor and follow wording (section D)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import amongus_session4_test as T  # noqa: E402  (red/blue/green/pink, no roles set)


class ImpostorText(unittest.TestCase):
    def setUp(self):
        self.game = T.make_game()
        self.addCleanup(self.game.close)
        for p in self.game.players.values():
            p.room = "CAFETERIA"
        self.game.players["red"].role = "impostor"

    def msgs(self, who):
        return T.messages_for(self.game, who)

    def test_kill_begin_victim_and_witness_text(self):
        out = T.command(self.game, "red", ".kill Blue", 10000)
        self.assertRegex(
            out,
            r"^🔪 Attempting to eliminate \*Blue\*\. Stay still for \d+s; movement cancels the attempt\.$",
        )
        self.game.players["green"].following = "red"          # makes Green a witness (follower nearby)
        self.game.movement.advance_all(10005)
        self.assertFalse(self.game.players["blue"].alive)
        self.assertEqual(
            self.msgs("blue")[-1],
            "💀 You've been eliminated.\nYou're now a Ghost. Use *.say <message>* to talk to other ghosts.",
        )
        self.assertNotIn("Red", self.msgs("blue")[-1])         # killer not revealed
        self.assertIn("😱 You witnessed a murder involving *Blue*.", self.msgs("green"))

    def test_cancel_reasons(self):
        killer, blue = self.game.players["red"], self.game.players["blue"]
        T.command(self.game, "red", ".kill Blue", 10000)
        self.game._cancel_pending_kills_for(killer, "movement", 10001)
        self.assertEqual(self.msgs("red")[-1], "⚠️ Your pending kill was cancelled because you moved.")
        T.command(self.game, "red", ".kill Blue", 10002)
        self.game._cancel_pending_kills_for(blue, "movement", 10003)
        self.assertEqual(self.msgs("red")[-1], "⚠️ Your pending kill was cancelled because Blue moved.")
        T.command(self.game, "red", ".kill Blue", 10004)
        self.game._cancel_all_pending_kills("meeting", 10005)
        self.assertEqual(self.msgs("red")[-1], "⚠️ Your pending kill was cancelled because a meeting was called.")
        self.assertIsNone(killer.pending_kill)

    def test_vent_in_text(self):
        self.game.players["red"].room = "ELECTRICAL"
        out = T.command(self.game, "red", ".vent in", 30000)
        self.assertRegex(out, r"^🌀 You entered the vent at \*Electrical\*\. You have \d+s before automatic ejection\.$")

    def test_follow_text(self):
        out = T.command(self.game, "blue", ".follow Green", 1000)
        self.assertEqual(out, "🚶 You are now following *Green*.\nUse *.unfollow* to stop.")
        T.command(self.game, "blue", ".unfollow", 1001)
        self.assertIn("_You stopped following Green._", self.msgs("blue"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
