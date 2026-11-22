"""Command-sheet note, Session 5: report, meeting call and voting wording (section E)."""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import amongus_session9_pkg5_test as P5  # noqa: E402
import amongus_session7d_test as T7  # noqa: E402
from router import amongus_config as C  # noqa: E402


class MeetingText(unittest.TestCase):
    def setUp(self):
        step = mock.patch.object(C, "EJECTION_REVEAL_STEP_SECONDS", 0.0)
        step.start()
        self.addCleanup(step.stop)
        self.game = P5.new_game()
        self.addCleanup(self.game.close)

    def test_report_with_no_body(self):
        red = T7.player(self.game, "Red")
        self.assertEqual(
            self.game._cmd_report(red, now=P5.T),
            "⚠️ _You haven't witnessed a reportable body here._",
        )

    def test_body_report_is_one_group_message_with_room_and_victim(self):
        before = len(self.game.manager.broadcasts)
        self.game._cmd_call_meeting(
            T7.player(self.game, "Red"), "report", P5.T,
            report={"room": "Storage", "victims": "Pink", "count": 1},
        )
        new = self.game.manager.broadcasts[before:]
        self.assertEqual(len(new), 1)                                   # no separate 📢 line
        self.assertEqual(
            new[0],
            "🚨 *Red found a corpse in Storage!*\nVictim: *Pink*\n\nMeeting started. Discuss here or use *.say <message>* from DM.",
        )
        self.assertTrue(self.game.manager.kwargs[-1].get("append_dm_link"))

    def test_two_victims_pluralised(self):
        self.game._cmd_call_meeting(
            T7.player(self.game, "Red"), "report", P5.T,
            report={"room": "Storage", "victims": "Pink, Blue", "count": 2},
        )
        self.assertIn("\nVictims: *Pink, Blue*\n", self.game.manager.broadcasts[-1])

    def test_emergency_meeting_text(self):
        P5.call_meeting(self.game, "Red", "emergency")
        self.assertEqual(
            self.game.manager.broadcasts[-1],
            "🚨 *Red called an emergency meeting!*\nDiscuss the situation here, or use *.say <message>* in DM to speak as your colour.",
        )

    def test_voting_open_warning_and_end(self):
        game = self.game
        P5.call_meeting(game)
        game._advance_meeting(P5.OPEN)
        self.assertEqual(
            game.manager.broadcasts[-1],
            "🗳️ *Voting is open.*\nUse *.vote <colour>* or *.vote skip*. You may also vote privately through DM.",
        )
        blue = T7.player(game, "Blue").jid
        dm = [m for who, m in game.manager.sent if who == blue and "Voting is open" in m]
        self.assertEqual(
            dm,
            ["🗳️ *Voting is open.*\nUse *.vote <colour>* or *.vote skip*. You can change your vote until voting closes."],
        )
        game._advance_meeting(P5.END - 10)
        self.assertEqual(
            game.manager.broadcasts[-1],
            "⏰ *10 seconds remaining!* Submit or change your vote before voting closes.",
        )
        game._resolve_meeting(P5.END)
        self.assertIn("⏱️ *Meeting ended.*", game.manager.broadcasts)
        self.assertIn("No one was ejected.\nCarry on...", game.manager.broadcasts)


if __name__ == "__main__":
    unittest.main(verbosity=2)
