"""Command-sheet note, Session 2: movement and player-info wording (section B)."""
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import amongus_session7b2aii_test as T  # noqa: E402  (game builder: red/blue/green crew, pink impostor)


class MovementInfoText(unittest.TestCase):
    def setUp(self):
        self.game = T.make_game()
        self.addCleanup(T.close_game, self.game)

    def say(self, who, text, ms=1_000):
        return self.game.handle(who, text, received_at_ms=ms)

    def test_room_list_and_move_start(self):
        out = self.say("red", ".m")
        self.assertTrue(out.startswith("*Available rooms*\n1. "))
        self.assertTrue(out.endswith("Send *.m <room name or number>* to move."))
        self.assertTrue(self.say("red", ".m nowhere").startswith("⚠️ _Unknown room._\n\n*Available rooms*"))
        go = self.say("red", ".m storage", 1_000)
        self.assertRegex(go, r"^🚶 Heading to \*Storage\* \(about \d+s\)\.\nUse \*\.stop\* to stop at your current position\.$")

    def test_stop_goback_where(self):
        self.say("red", ".m storage", 1_000)
        where = self.say("red", ".where", 2_000)
        self.assertTrue(where.startswith("📍 *Your location*\n"))
        self.assertRegex(where, r"(Between \*.+\* and \*.+\*\n(Travelling|Stopped) \(\S+s along the corridor\)\.|\*.+\*\nLeaving in about \d+s\.)")
        stop = self.say("red", ".stop", 4_000)
        self.assertTrue(stop.startswith("🛑 You stopped between *"))
        self.assertTrue(stop.endswith("Use *.where* to check your position."))
        back = self.say("red", ".goback", 4_500)
        self.assertRegex(back, r"^↩️ Returning to \*.+\* \(about \d+s\)\.$")
        idle = self.say("blue", ".where", 5_000)
        self.assertRegex(idle, r"^📍 \*Your location\*\n\*[^*]+\*$")

    def test_status_layout(self):
        text = self.say("red", ".status")
        lines = text.splitlines()
        self.assertEqual(lines[0], "📍 *YOUR STATUS*")
        self.assertEqual(
            [l.split(":")[0] for l in lines[1:]],
            ["Role", "Status", "Location", "Players with you", "Bodies here", "Match", "Cooldowns"],
        )
        self.assertIn("Bodies here: None", lines)
        self.assertEqual(lines[-1], "Cooldowns: use *.cds*")
        self.assertNotIn("**", text)

    def test_players_header_and_progress(self):
        self.assertTrue(self.say("red", ".players").startswith("*Players still alive (4):*"))
        self.game._team_tasks = [{"done": True}, {"done": False}, {"done": False}, {"done": False}]
        self.assertEqual(self.say("red", ".progress"), "*Team task progress*\n1/4 tasks complete (25%).")

    def test_impostor_progress_is_fake_but_same_shape(self):
        self.game._team_tasks = [{"done": False}] * 10
        out = self.say("pink", ".progress")
        self.assertRegex(out, r"^\*Team task progress\*\n\d+/10 tasks complete \(\d+%\)\.$")
        done, pct = map(int, __import__("re").findall(r"(\d+)/10 tasks complete \((\d+)%", out)[0])
        self.assertEqual(done, round(pct * 10 / 100))
        self.assertGreater(done, 0)                          # not the real 0

    def test_progress_during_comms_has_no_task_counts(self):
        self.game._team_tasks = [{"done": True}, {"done": False}]
        self.game._cmd_sabotage(self.game.players["pink"], "communications", now=100)
        self.game._comms_rng = random.Random(3)
        for _ in range(30):
            out = self.say("red", ".progress")
            self.assertTrue(out.startswith("*Team task progress*\n"))
            self.assertNotIn("tasks complete", out)

    def test_cscene_and_scientist_gate(self):
        self.assertEqual(self.say("red", ".cscene"), "*Reported Crime Scenes*\n\n_No reported crime scenes yet._")
        self.assertEqual(self.say("red", ".vitals"), "🔒 _This command is available to the Scientist only._")
        self.assertEqual(self.say("red", ".witness"), "🔒 _This command is available to the Scientist only._")


if __name__ == "__main__":
    unittest.main(verbosity=2)
