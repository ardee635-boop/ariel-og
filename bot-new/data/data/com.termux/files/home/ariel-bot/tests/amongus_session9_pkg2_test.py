"""Session 09 package 2 - endings: earliest timestamp wins, exact tie to
Impostors; confirmed Reactor / O2 result texts."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import amongus_session7d_test as base7  # noqa: E402
from router.amongus_game import SABOTAGE_FAILURE_TEXT  # noqa: E402


def new_game():
    game = base7.make_game()
    game._team_tasks = [{"id": f"T{i}", "name": f"Task {i}", "done": False} for i in range(3)]
    return game


def arm(game, name, deadline):
    game._ensure_sabotage_registry()
    sab = game._sabotages[name]
    sab.activate(deadline - 30, deadline=deadline)
    return sab


class Texts(unittest.TestCase):
    def test_texts(self):
        self.assertIn("Reactor meltdown — Impostors win", SABOTAGE_FAILURE_TEXT["reactor"])
        o2 = SABOTAGE_FAILURE_TEXT["oxygen"]
        self.assertTrue(o2.startswith("🚨 *OXYGEN FAILURE!*"))
        self.assertIn("The oxygen supply has run out.", o2)  # N7 draft wording (was 06D "tank has been used up")
        self.assertLess(o2.index("OXYGEN FAILURE!"), o2.index("supply has run out"))
        self.assertLess(o2.index("supply has run out"), o2.index("O₂ depleted — Impostors win"))
        self.assertIn("O₂ depleted — Impostors win", o2)

    def test_reactor_failure_is_broadcast_once_with_reveal(self):
        game = new_game()
        try:
            arm(game, "reactor", 100.0)
            game._tick(101.0)
            msgs = game.manager.broadcasts
            self.assertEqual(sum("Reactor meltdown — Impostors win" in m for m in msgs), 1)
            self.assertIn("Impostor", msgs[-1])
            game._tick(102.0)
            self.assertEqual(len(game.manager.broadcasts), len(msgs))
        finally:
            game.close()


class SimultaneousEndings(unittest.TestCase):
    def test_sabotage_deadline_earlier_than_task_completion_impostors_win(self):
        game = new_game()
        try:
            arm(game, "reactor", 100.0)
            for t in game._team_tasks:
                t["done"] = True            # final task finishes at t=100.5
            game._resolve_win_check(100.5)
            self.assertTrue(game.over)
            self.assertIn("Reactor meltdown", game.manager.broadcasts[-1])
            self.assertEqual(game._sabotages["reactor"]["failed_at"], 100.0)
        finally:
            game.close()

    def test_task_completion_earlier_than_deadline_crew_wins(self):
        game = new_game()
        try:
            arm(game, "reactor", 100.0)
            for t in game._team_tasks:
                t["done"] = True
            game._resolve_win_check(99.5)
            self.assertTrue(game.over)
            self.assertIn("Crewmates win", game.manager.broadcasts[-1])
        finally:
            game.close()

    def test_exact_tie_goes_to_impostors(self):
        game = new_game()
        try:
            arm(game, "oxygen", 100.0)
            for t in game._team_tasks:
                t["done"] = True
            game._resolve_win_check(100.0)
            self.assertTrue(game.over)
            self.assertIn("O₂ depleted — Impostors win", game.manager.broadcasts[-1])
        finally:
            game.close()

    def test_outnumber_and_tasks_done_same_moment_goes_to_impostors(self):
        game = new_game()
        try:
            for t in game._team_tasks:
                t["done"] = True
            crew = [p for p in game.players.values() if p.role != "impostor"]
            imps = [p for p in game.players.values() if p.role == "impostor"]
            for p in crew[len(imps):]:
                p.alive = False
            game._resolve_win_check(10.0)
            self.assertIn("Impostors win", game.manager.broadcasts[-1])
        finally:
            game.close()

    def test_ejection_of_last_impostor_is_crew_win(self):
        game = new_game()
        try:
            for p in game.players.values():
                if p.role == "impostor":
                    p.alive = False
                    p.death_reason = "ejected"
            game._resolve_win_check(10.0)
            self.assertIn("Crewmates win", game.manager.broadcasts[-1])
        finally:
            game.close()


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
