"""Command-sheet note, Session 3: task wording (section C)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import amongus_session5_test as T  # noqa: E402  (red: Fix Wiring + Empty Garbage in Cafeteria; pink impostor)


class TaskText(unittest.TestCase):
    def setUp(self):
        self.game = T.make_game()
        self.addCleanup(T.close_game, self.game)

    def say(self, who, text, at, **kw):
        return T.command(self.game, who, text, at, **kw)

    def test_tasks_here_list(self):
        out = self.say("red", ".task", 1000)
        self.assertEqual(
            out,
            "*Tasks here: Cafeteria*\n1. Fix Wiring\n2. Empty Garbage\n\nSend *.task <number>* to start one.",
        )
        self.assertEqual(self.say("green", ".task", 1000), "_Nothing to do here._")

    def test_task_start_prompt(self):
        out = self.say("red", ".task 1", 1000)
        lines = out.splitlines()
        self.assertTrue(lines[0].startswith("🧩 *Fix Wiring*"))
        self.assertIn("Reply to this message with your answer, or send *.task answer <answer>*.", lines)
        self.assertIn("_This interaction expires after 60s without activity._", lines)
        self.assertRegex(lines[-1], r"^\[Task Ref: I\d+\]$")
        self.assertNotIn("`", out)

    def test_wrong_then_right_answer(self):
        self.say("red", ".task 2", 1000)
        wrong = self.say("red", ".task answer nonsense", 1001)
        self.assertEqual(wrong, "❌ _That answer doesn't match. Try again before the timer expires._")
        self.assertEqual(self.game._team_task_progress(), (0, 4))              # nothing awarded
        answer = self.game.players["red"].task_in_progress["expected"]
        done = self.say("red", f".task answer {answer}", 1002)
        self.assertEqual(
            done,
            "✅ *Empty Garbage* complete.\nTasks remaining: 1\nTeam progress: 1/4.",
        )

    def test_last_task_adds_all_complete_line(self):
        for i, name in enumerate(("Fix Wiring", "Empty Garbage")):
            self.say("red", ".task 1", 1000 + i * 40)
            ans = self.game.players["red"].task_in_progress["expected"]
            out = self.say("red", f".task answer {ans}", 1001 + i * 40)
        self.assertEqual(
            out,
            "✅ *Empty Garbage* complete.\nTasks remaining: 0\nAll your assigned tasks are complete.\nTeam progress: 2/4.",
        )

    def test_impostor_fake_task_wording_stays_distinct(self):
        self.say("pink", ".task 1", 1000)
        ans = self.game.players["pink"].task_in_progress["expected"]
        out = self.say("pink", f".task answer {ans}", 1001)
        self.assertEqual(out, "✅ *Swipe Card* logged. 0 fake task(s) remain.")
        self.assertEqual(self.game._team_task_progress(), (0, 4))              # fakes never score

    def test_tasks_list_layout(self):
        out = self.say("red", ".tasks", 1000)
        self.assertEqual(
            out,
            "📋 *TASKS LIST*\n\n*Your tasks*\n1. Fix Wiring — Cafeteria\n2. Empty Garbage — Cafeteria\n\n*Finished tasks*\nNone",
        )
        self.say("red", ".task 1", 1000)
        ans = self.game.players["red"].task_in_progress["expected"]
        self.say("red", f".task answer {ans}", 1001)
        after = self.say("red", ".tasks", 1002)
        self.assertIn("*Your tasks*\n1. Empty Garbage — Cafeteria", after)
        self.assertTrue(after.endswith("*Finished tasks*\n- ~Fix Wiring~"))
        self.assertTrue(self.say("pink", ".tasks", 1000).splitlines()[2] == "*Fake tasks*")

    def test_task_next_tells_the_player_the_old_one_was_dropped(self):
        self.say("red", ".task 1", 1000)
        before = len(self.game.manager.sent)
        nxt = self.say("red", ".task next", 1001)
        self.assertIn("*Empty Garbage*", nxt)
        dms = [m for t, m in self.game.manager.sent[before:] if t == "red"]
        self.assertIn("↪️ Previous task interaction abandoned. The task remains unfinished.", dms)
        self.assertEqual(self.game.players["red"].task_in_progress["task_id"], "T0002")
        self.assertFalse(self.game.players["red"].tasks[0]["done"])             # not falsely completed

    def test_timeout_text(self):
        self.say("red", ".task 1", 3000)
        self.game.movement.advance_all(3060)
        dms = [m for t, m in self.game.manager.sent if t == "red"]
        self.assertIn(
            "⏱️ Your task interaction expired after 60 seconds without activity. The task remains unfinished.",
            dms,
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
