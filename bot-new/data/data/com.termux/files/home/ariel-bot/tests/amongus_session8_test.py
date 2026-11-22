"""Session 8: full-match simulation and hardening.

Whole matches, lobby to victory, on a simulated clock (tests/amongus_sim.py).
Each ending is reached through real commands, and randomised matches check
that nothing crashes, nothing leaks a player's real identity, and nothing
acts after the game is over.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import amongus_sim as S  # noqa: E402


def last_group(match):
    return match.router.group[-1][1] if match.router.group else ""


def impostors(match):
    return [p for p in match.game.players.values() if p.role == "impostor"]


def crew(match):
    return [p for p in match.game.players.values() if p.role != "impostor"]


def assert_silent_after_end(test, match, seconds=130):
    """Nothing is sent, scheduled or changed once the game is over."""
    test.assertTrue(match.game.over)
    ended_at = match.t
    groups, dms = len(match.router.group), len(match.router.dms)
    for _ in range(int(seconds)):
        match.tick()
    test.assertEqual(len(match.router.group), groups, "group message after end")
    test.assertEqual(len(match.router.dms), dms, "DM after end")
    test.assertFalse(match.game._timers)
    test.assertTrue(match.t > ended_at)


class EndingTests(unittest.TestCase):
    def tearDown(self):
        getattr(self, "match", None) and self.match.cleanup()

    def test_task_victory_full_match(self):
        for seed in (1, 2, 3):
            m = self.match = S.Match(6, seed)
            S.run(m, 4000, lambda mm: S.smart_step(mm, kill=False, sabotage=None))
            self.assertTrue(m.game.over, f"seed {seed} never finished")
            self.assertIn("All team tasks are complete", last_group(m))
            self.assertIn("Impostor", last_group(m))
            assert_silent_after_end(self, m)
            m.cleanup()

    def test_impostors_win_by_outnumbering(self):
        for seed in (4, 5, 6):
            m = self.match = S.Match(6, seed)
            S.run(m, 4000, lambda mm: S.smart_step(mm, kill=True, crew_acts=False))
            self.assertTrue(m.game.over, f"seed {seed} never finished")
            self.assertIn("Impostors win", last_group(m))
            self.assertIn("outnumber", last_group(m))
            assert_silent_after_end(self, m)
            m.cleanup()

    def test_ejecting_the_impostor_wins(self):
        m = self.match = S.Match(5, 7)
        (imp,) = impostors(m)
        caller = crew(m)[0]
        m.tick()
        m.send(caller.jid, ".meeting")
        self.assertTrue(m.game._meeting)
        for _ in range(61):  # voting opens at 60 s (Session 09 pkg 5)
            m.tick()
        for p in crew(m):
            m.send(p.jid, f".vote {imp.color}")
        for _ in range(31):  # 90 s meeting (Session 09 pkg 1)
            m.tick()
        self.assertTrue(m.game.over)
        self.assertIn("Every Impostor has been ejected", last_group(m))
        self.assertIn(imp.color, last_group(m))
        assert_silent_after_end(self, m)

    def test_meeting_resolves_from_ticks_alone(self):
        m = self.match = S.Match(5, 8)
        m.tick()
        m.send(crew(m)[0].jid, ".meeting")
        for _ in range(78):  # warning at 80 s (Session 09 pkg 1)
            m.tick()
        self.assertFalse(any("10 seconds remaining" in t for _, t in m.router.group))
        for _ in range(4):
            m.tick()
        self.assertEqual(
            sum("10 seconds remaining" in t for _, t in m.router.group), 1,
            "the 10s warning is sent exactly once",
        )
        for _ in range(10):
            m.tick()
        self.assertIsNone(m.game._meeting)
        self.assertTrue(any("No one was ejected" in t for _, t in m.router.group))

    def test_sabotage_failure_ends_the_match(self):
        for name in ("reactor", "o2", "lights", "comms"):
            m = self.match = S.Match(6, 9)
            imp = impostors(m)[0]
            m.tick()
            m.send(imp.jid, f".sabotage {name}")
            for _ in range(60):
                m.tick()
            if name in ("reactor", "o2"):
                self.assertTrue(m.game.over, name)
                self.assertTrue(
                    "Reactor meltdown — Impostors win" in last_group(m)
                    or "O₂ depleted — Impostors win" in last_group(m),
                    last_group(m),
                )
                self.assertIn("Impostors win", last_group(m))
                self.assertIn(imp.color, last_group(m))
                assert_silent_after_end(self, m)
            else:
                self.assertFalse(m.game.over, f"{name} must not end the game")
            m.cleanup()

    def test_simultaneous_endings_have_a_fixed_priority(self):
        # Last impostor gone AND tasks done on the same tick: crew win, once.
        m = self.match = S.Match(5, 10)
        for t in m.game._team_tasks:
            t["done"] = True
        imp = impostors(m)[0]
        imp.alive = False
        imp.death_reason = "ejected"
        m.tick()
        self.assertTrue(m.game.over)
        self.assertEqual(
            sum("win" in t for _, t in m.router.group), 1,
            "exactly one victory announcement",
        )
        self.assertIn("Crewmates win", last_group(m))


class DepartureTests(unittest.TestCase):
    def tearDown(self):
        getattr(self, "match", None) and self.match.cleanup()

    def test_departed_crew_tasks_leave_the_total(self):
        m = self.match = S.Match(6, 11)
        leaver = crew(m)[0]
        mine = [t for t in leaver.tasks if not t["done"]]
        total_before = len(m.game._team_tasks)
        m.tick()
        m.send(leaver.jid, ".leave", group=True)
        self.assertTrue(leaver.departed)
        self.assertEqual(len(m.game._team_tasks), total_before - len(mine))
        self.assertFalse(
            any(t in m.game._team_tasks for t in mine),
            "no orphaned task can block the team win",
        )

    def test_remaining_crew_can_still_win_by_tasks_after_a_departure(self):
        m = self.match = S.Match(6, 12)
        m.tick()
        m.send(crew(m)[0].jid, ".leave", group=True)
        S.run(m, 4000, lambda mm: S.smart_step(mm, kill=False, sabotage=None))
        self.assertTrue(m.game.over)
        self.assertIn("All team tasks are complete", last_group(m))

    def test_last_impostor_leaving_gives_the_crew_the_win(self):
        m = self.match = S.Match(5, 13)
        (imp,) = impostors(m)
        m.tick()
        m.send(imp.jid, ".leave", group=True)
        self.assertTrue(m.game.over)
        self.assertIn("Crewmates win", last_group(m))
        self.assertIn("left the game", last_group(m))
        self.assertNotIn("ejected", last_group(m))

    def test_no_one_left_ends_quietly(self):
        # Reachable only defensively: an impostor leaving ends the match first
        # when played in order, so force the empty-roster state directly.
        m = self.match = S.Match(5, 14)
        m.tick()
        for p in m.game.players.values():
            p.departed = True
        m.tick()
        self.assertTrue(m.game.over)
        self.assertIn("everyone left", last_group(m))
        self.assertNotIn("win", last_group(m).lower())

    def test_leaving_mid_game_sends_no_lobby_host_message(self):
        m = self.match = S.Match(6, 15)
        m.tick()
        m.send(m.jids[0], ".leave", group=True)  # the host
        self.assertFalse(
            any("is now host" in t for _, t in m.router.group),
            "lobby host handover must not fire during a match",
        )

    def test_departure_mid_sabotage_and_mid_meeting_is_safe(self):
        m = self.match = S.Match(8, 16)
        imp = impostors(m)[0]
        m.tick()
        m.send(imp.jid, ".sabotage o2")
        victim = crew(m)[0]
        m.send(victim.jid, ".task", group=False)
        m.send(victim.jid, ".leave", group=True)
        m.send(crew(m)[1].jid, ".meeting")
        m.send(crew(m)[2].jid, ".leave", group=True)
        S.run(m, 120, lambda mm: None)
        S.check_invariants(m, S.new_seen())


class EndGameCommandTests(unittest.TestCase):
    def tearDown(self):
        getattr(self, "match", None) and self.match.cleanup()

    def test_only_the_host_can_end_it(self):
        m = self.match = S.Match(6, 17)
        m.tick()
        reply = m.send(m.jids[1], ".endgame")
        self.assertIn("Only the host", reply)
        self.assertFalse(m.game.over)

    def test_endgame_with_everything_pending_leaves_nothing_behind(self):
        m = self.match = S.Match(8, 18)
        imps = impostors(m)
        m.tick()
        m.send(imps[0].jid, ".sabotage reactor")
        m.send(imps[0].jid, ".sabotage lights")
        m.send(imps[0].jid, ".sabotage comms")
        for p in crew(m)[:3]:
            m.send(p.jid, ".task")
        m.send(crew(m)[3].jid, ".meeting")
        m.tick()
        m.send(m.jids[0], ".endgame")
        self.assertTrue(m.game.over)
        self.assertIn("ended by the host", last_group(m))
        S.check_invariants(m, S.new_seen())
        assert_silent_after_end(self, m)
        # the group is not left locked by a Communications outage
        locks = [a for _, a in m.router.actions]
        self.assertTrue(not locks or locks[-1] == "unrestrict", locks)

    def test_endgame_with_no_game(self):
        m = self.match = S.Match(5, 19)
        m.send(m.jids[0], ".endgame")
        reply = m.send(m.jids[0], ".endgame")
        self.assertIn("no running game", reply)


class SimulationTests(unittest.TestCase):
    """Randomised whole matches. Seeds are fixed so failures reproduce."""

    def _run_seed(self, seed, step):
        n = 4 + seed % 9
        m = S.Match(n, seed)
        seen = S.new_seen()
        try:
            for _ in range(1500):
                m.tick()
                if m.game.over:
                    break
                step(m, seed)
                S.check_invariants(m, seen)
                if m.game.over:
                    break
            S.check_invariants(m, seen)
        finally:
            m.cleanup()
        return m, seen

    def test_command_fuzz(self):
        for seed in range(40):
            m, seen = self._run_seed(
                seed,
                lambda mm, sd: S.fuzz_step(mm, allow_leave=(sd % 3 == 0)),
            )
            self.assertFalse(seen.get("leaks"), f"seed {seed}: {seen.get('leaks')}")

    def test_mixed_smart_matches_always_reach_a_valid_ending(self):
        endings = set()
        for seed in range(100, 130):
            def step(mm, sd):
                S.smart_step(
                    mm,
                    kill=(sd % 2 == 0),
                    sabotage=(None, ["lights", "comms"], ["reactor", "o2"])[sd % 3],
                )
                if sd % 5 == 0:
                    S.fuzz_step(mm, 0.03)

            m = S.Match(4 + seed % 9, seed)
            m.vote_accuracy = 0.6
            seen = S.new_seen()
            for _ in range(5000):
                m.tick()
                if m.game.over:
                    break
                step(m, seed)
                S.check_invariants(m, seen)
                if m.game.over:
                    break
            S.check_invariants(m, seen)
            self.assertFalse(seen.get("leaks"), f"seed {seed}")
            self.assertTrue(m.game.over, f"seed {seed}: match never ended")
            endings.add(
                next(
                    key for key in (
                        "All team tasks", "Every Impostor", "left the game",
                        "outnumber", "Reactor meltdown", "O₂ depleted", "everyone left",
                    )
                    if key in last_group(m)
                )
            )
            assert_silent_after_end(self, m, 70)
            m.cleanup()
        self.assertGreaterEqual(len(endings), 3, endings)


if __name__ == "__main__":
    unittest.main(verbosity=1)
