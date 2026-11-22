"""Command-sheet note, Session 7: match-over and ghost wording (section G)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import amongus_session9_pkg5_test as P5  # noqa: E402
import amongus_session7d_test as T7  # noqa: E402


class MatchOver(unittest.TestCase):
    def setUp(self):
        self.game = P5.new_game()
        self.addCleanup(self.game.close)

    def final_group(self):
        return [m for m in self.game.manager.broadcasts if "win!" in m][-1]

    def result_for(self, color):
        return [m for who, m in self.game.manager.sent
                if who == P5.JID[color] and "Match over" in m]

    def test_group_message_is_headline_reason_blank_line_reveal(self):
        self.game._finish("🎉 *Crewmates win!*\nAll team tasks are complete.", "crewmates")
        lines = self.final_group().split("\n")
        self.assertEqual(lines[0], "🎉 *Crewmates win!*")
        self.assertEqual(lines[1], "All team tasks are complete.")
        self.assertEqual(lines[2], "")
        self.assertTrue(lines[3].startswith("🔪 The Impostor"))

    def test_each_ending_has_headline_and_reason_on_separate_lines(self):
        game = self.game
        game._resolve_win_check()           # nothing decided yet
        for p in game.players.values():
            if p.role == "impostor":
                p.alive = False
                p.death_reason = "ejected"
        game._resolve_win_check()
        self.assertIn("🎉 *Crewmates win!*\nEvery Impostor has been ejected.", self.final_group())

    def test_impostors_equal_or_outnumber(self):
        game = self.game
        for p in game.players.values():
            if p.role != "impostor":
                p.alive = False
        game._resolve_win_check()
        self.assertIn("🔪 *Impostors win!*\nThey equal or outnumber the crew.", self.final_group())

    def test_result_dm_shape(self):
        self.game._finish("🎉 *Crewmates win!*\nAll team tasks are complete.", "crewmates")
        (red,) = self.result_for("Red")
        self.assertEqual(
            red,
            "🏁 *Match over — Crewmates win!*\nYour role: *Crewmate* (Crewmates).\n🏆 *Your team won.*",
        )
        (pink,) = self.result_for("Pink")
        self.assertEqual(
            pink,
            "🏁 *Match over — Crewmates win!*\nYour role: *Impostor* (Impostors).\n💀 *Your team lost.*",
        )

    def test_scientist_role_name(self):
        self.game._finish("🔪 *Impostors win!*", "impostors")
        (green,) = self.result_for("Green")
        self.assertIn("Your role: *Scientist* (Crewmates).", green)
        self.assertIn("Impostors win!", green)

    def test_sabotage_failure_headlines(self):
        from router import amongus_game as G
        self.assertEqual(G.SABOTAGE_FAILURE_TEXT["reactor"], "☢️ *Reactor meltdown — Impostors win.*")
        self.assertEqual(
            G.SABOTAGE_FAILURE_TEXT["oxygen"],
            "🚨 *OXYGEN FAILURE!*\nThe oxygen supply has run out.\n*O₂ depleted — Impostors win.*",
        )


class GhostVote(unittest.TestCase):
    def test_ghost_vote_reply(self):
        game = P5.new_game()
        self.addCleanup(game.close)
        P5.call_meeting(game)
        blue = T7.player(game, "Blue")
        blue.alive = False
        self.assertEqual(game._cmd_vote(blue, "Red", public=False, now=P5.OPEN), "👻 _Ghosts cannot vote._")

    def test_departed_player_keeps_old_reply(self):
        game = P5.new_game()
        self.addCleanup(game.close)
        P5.call_meeting(game)
        blue = T7.player(game, "Blue")
        blue.alive = False
        blue.departed = True
        self.assertEqual(
            game._cmd_vote(blue, "Red", public=False, now=P5.OPEN),
            "⚠️ _Only active living players can vote._",
        )


if __name__ == "__main__":
    unittest.main()
