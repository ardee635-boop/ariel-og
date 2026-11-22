"""Session 09 package 1 - timing: 5 s kill wait, 30 s cooldown, 90 s meeting
with the 10-seconds-left warning at 80 s."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import amongus_session6_test as base  # noqa: E402  (reuses its fixtures)
from router import amongus_config as C  # noqa: E402


class TimingConstants(unittest.TestCase):
    def test_constants(self):
        self.assertEqual(C.KILL_RESOLUTION_SECONDS, 5)
        self.assertEqual(C.KILL_COOLDOWN_SECONDS, 30)
        self.assertEqual(C.MEETING_DURATION_SECONDS, 90)
        self.assertEqual(C.MEETING_VOTING_OPENS_SECONDS, 60)
        self.assertEqual(C.MEETING_WARNING_SECONDS, 80)
        self.assertEqual(C.MEETING_VOTE_SECONDS, 90)


class MeetingTimeline(unittest.TestCase):
    def _warnings(self, game):
        return [b for b in game.manager.broadcasts if "10 seconds remaining" in b["message"]]

    def test_no_warning_before_80s_one_warning_at_80s(self):
        game = base.make_game()
        try:
            game._cmd_call_meeting(game.players["red"], "emergency", now=100)
            game._advance_meeting(100 + 79)
            self.assertEqual(self._warnings(game), [])
            game._advance_meeting(100 + 80)
            game._advance_meeting(100 + 85)
            self.assertEqual(len(self._warnings(game)), 1)
            self.assertIsNotNone(game._meeting)  # not resolved before 90 s
        finally:
            base.close_game(game)

    def test_meeting_ends_at_90s(self):
        game = base.make_game()
        try:
            game._cmd_call_meeting(game.players["red"], "emergency", now=100)
            self.assertEqual(game._meeting["ends_at"], 190)
            game._advance_meeting(189)
            self.assertIsNotNone(game._meeting)
            game._advance_meeting(190)
            self.assertIsNone(game._meeting)
        finally:
            base.close_game(game)

    def test_vote_accepted_at_89s_rejected_after_90s(self):
        game = base.make_game()
        try:
            game._cmd_call_meeting(game.players["red"], "emergency", now=100)
            ok = game._cmd_vote(game.players["red"], "skip", public=False, now=189)
            self.assertIn("registered", ok)
            late = game._cmd_vote(game.players["blue"], "skip", public=False, now=190)
            self.assertIn("closed", late)
        finally:
            base.close_game(game)


class KillWait(unittest.TestCase):
    def test_kill_message_and_resolve_time(self):
        game = base.make_game()
        try:
            killer = next(p for p in game.players.values() if p.role == "impostor")
            victim = next(p for p in game.players.values() if p.role != "impostor")
            victim.room = killer.room
            killer.settled = victim.settled = True
            reply = game._cmd_kill(killer, victim.color, now=50)
            self.assertIn("Stay still for 5s", reply)
            self.assertEqual(killer.pending_kill["resolve_at"], 55)
        finally:
            base.close_game(game)


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
