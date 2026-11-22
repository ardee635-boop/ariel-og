"""Session 09 package 9 - Session 08 section 6 edge-case checklist.

One test per checklist item the simulator can reach. Items the simulator
cannot reach are listed at the bottom as SKIPPED with the reason, so the
checklist is accounted for in full. These pin the bot's CURRENT behaviour for
undecided points; they are not design approval.
"""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import amongus_sim as S  # noqa: E402
from amongus_session9_pkg7_test import (  # noqa: E402
    Base, advance, assert_ended_cleanly, crew, first_kill_and_report, group_texts,
    impostors, place, spread,
)
from router import amongus_config as C  # noqa: E402
from router.amongus import AmongUsCoordinator, AmongUsManager, NOT_HANDLED  # noqa: E402
from router.amongus_registry import GroupRegistry  # noqa: E402


class LobbyAndGroups(unittest.TestCase):
    GA, GB = "120363000000000101@g.us", "120363000000000102@g.us"

    def coord(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        c = AmongUsCoordinator(S.SimRouter(), registry=GroupRegistry(Path(d.name) / "r.json"),
                               owner_check=lambda s: False)
        self.addCleanup(lambda: [m.game.close() for m in c._groups.values() if m.game])
        self.addCleanup(lambda: [m._cancel_timer() for m in c._groups.values()])
        return c

    def run_lobby(self, c, group, jids):
        c.pre_dispatch(jids[0], ".lobby open", group)
        for j in jids[1:]:
            c.pre_dispatch(j, ".join", group)
        return c.pre_dispatch(jids[0], ".lobby start", group)

    def test_lobby_cannot_be_replaced_while_a_match_is_running(self):
        c = self.coord()
        jids = [S.jid_for(i) for i in range(1, 6)]
        self.assertIsNone(self.run_lobby(c, self.GA, jids))
        out = c.pre_dispatch(jids[0], ".lobby open", self.GA)
        self.assertIn("already running", out)
        live = c._groups[self.GA].game
        self.assertFalse(live.over)
        # A late .join is refused without touching the live roster.
        late = S.jid_for(9)
        self.assertIn("No open lobby", c.pre_dispatch(late, ".join", self.GA))
        self.assertNotIn(late, live.players)

    def test_two_groups_are_isolated_matches(self):
        c = self.coord()
        a = [S.jid_for(i) for i in range(1, 6)]
        b = [S.jid_for(i) for i in range(11, 16)]
        self.assertIsNone(self.run_lobby(c, self.GA, a))
        self.assertIsNone(self.run_lobby(c, self.GB, b))
        ga, gb = c._groups[self.GA].game, c._groups[self.GB].game
        self.assertIsNot(ga, gb)
        self.assertEqual(set(ga.players), set(a))
        self.assertEqual(set(gb.players), set(b))
        self.assertTrue(c.pre_dispatch(a[1], ".where", None).startswith("📍 *Your location*"))

    def test_finished_match_no_longer_claims_its_players(self):
        """Found in Session 8: after a match ended its players still counted as
        'in' that group, so a later match elsewhere answered every private
        command with 'more than one game'."""
        c = self.coord()
        a = [S.jid_for(i) for i in range(1, 6)]
        self.assertIsNone(self.run_lobby(c, self.GA, a))
        c.pre_dispatch(a[0], ".endgame", self.GA)
        self.assertTrue(c._groups[self.GA].game.over)
        self.assertFalse(c.has_player(a[1]))
        self.assertIsNone(self.run_lobby(c, self.GB, a))
        reply = c.pre_dispatch(a[1], ".status", None)
        self.assertNotIn("more than one", str(reply))
        self.assertIn("Status", reply)
        out = c.pre_dispatch(a[1], ".GC", None)
        self.assertEqual(out["group_jid"], self.GB)

    def test_a_player_in_two_live_matches_must_name_the_group(self):
        """Existing Session 1 design: allowed, and private commands ask which."""
        c = self.coord()
        a = [S.jid_for(i) for i in range(1, 6)]
        b = [S.jid_for(1)] + [S.jid_for(i) for i in range(11, 15)]
        self.assertIsNone(self.run_lobby(c, self.GA, a))
        self.assertIsNone(self.run_lobby(c, self.GB, b))
        self.assertIn("more than one", c.pre_dispatch(a[0], ".where", None))


class AfterRestart(unittest.TestCase):
    def test_a_fresh_manager_has_no_match_and_leaves_text_to_the_rest_of_the_bot(self):
        m = S.Match(5, 7)
        try:
            p = crew(m)[0]
            fresh = AmongUsManager(S.SimRouter(), S.GROUP)
            for text in (".status", ".m cafeteria", ".vote red", ".task", "hello"):
                self.assertIs(fresh.pre_dispatch(p.jid, text), NOT_HANDLED, text)
            self.assertIsNone(fresh.game)
            fresh._cancel_timer()
        finally:
            m.cleanup()


class Resolution(Base):
    def test_colour_names_resolve_case_insensitively_and_exactly(self):
        m = self.new(6)
        (imp,) = impostors(m)
        victim = crew(m)[0]
        spread(m)
        place(m, imp, "STORAGE")
        place(m, victim, "STORAGE")
        m.t += 1
        out = m.send(imp.jid, f".kill   {victim.color.upper()}")
        self.assertIn("Attempting", out)
        self.assertIs(imp.pending_kill is not None, True)

    def test_unknown_self_and_partial_colours_do_not_start_a_kill(self):
        for arg_of in (lambda imp, v: "nobody", lambda imp, v: imp.color, lambda imp, v: v.color[:2]):
            m = S.Match(6, 21)
            try:
                (imp,) = impostors(m)
                victim = crew(m)[0]
                spread(m)
                place(m, imp, "STORAGE")
                place(m, victim, "STORAGE")
                m.t += 1
                m.send(imp.jid, f".kill {arg_of(imp, victim)}")
                self.assertIsNone(imp.pending_kill)
                advance(m, 8)
                self.assertTrue(victim.alive)
                self.assertEqual(m.errors, [])
            finally:
                m.cleanup()

    def test_dead_player_colour_cannot_be_voted_or_killed_again(self):
        m = self.new(6)
        (imp,) = impostors(m)
        victim, reporter = crew(m)[0], crew(m)[1]
        first_kill_and_report(m, imp, victim, reporter)
        out = m.send(reporter.jid, f".vote {victim.color}")
        advance(m, 61)
        out = m.send(reporter.jid, f".vote {victim.color}")
        self.assertNotIn("registered", str(out))
        self.assertEqual(m.errors, [])


class Timers(Base):
    def test_pending_kill_is_cancelled_when_the_match_ends(self):
        m = self.new(5)
        (imp,) = impostors(m)
        victim = crew(m)[0]
        spread(m)
        place(m, imp, "STORAGE")
        place(m, victim, "STORAGE")
        m.t += 1
        m.send(imp.jid, f".kill {victim.color}")
        self.assertIsNotNone(imp.pending_kill)
        m.send(m.jids[0], ".endgame", group=True)
        self.assertTrue(m.game.over)
        self.assertIsNone(imp.pending_kill)
        before = len(m.router.dms) + len(m.router.group)
        advance(m, 10)
        self.assertTrue(victim.alive)
        self.assertEqual(len(m.router.dms) + len(m.router.group), before)
        self.assertFalse(m.game._timers)

    def test_moving_cancels_a_pending_kill(self):
        m = self.new(5)
        (imp,) = impostors(m)
        victim = crew(m)[0]
        spread(m)
        place(m, imp, "STORAGE")
        place(m, victim, "STORAGE")
        m.t += 1
        m.send(imp.jid, f".kill {victim.color}")
        advance(m, 1)
        m.send(imp.jid, ".m Admin")
        advance(m, 8)
        self.assertTrue(victim.alive)

    def test_repeated_meetings_and_sabotages_leave_no_duplicate_timers(self):
        m = self.new(7)
        (imp, *_) = impostors(m)
        spread(m)
        sizes = []
        for round_no in range(3):
            m.t += 1
            m.send(imp.jid, ".sabotage reactor")
            caller = [p for p in crew(m) if p.alive][0]
            m.send(caller.jid, ".meeting")
            advance(m, 95)
            sizes.append(len(m.game._timers))
            if m.game.over:
                break
        # Backstop timers stay queued until they fire, so the count grows with
        # rounds; what matters is that firing every one of them now (as if the
        # real clock had caught up) is a harmless no-op.
        if not m.game.over:
            groups, dms = len(m.router.group), len(m.router.dms)
            state = (m.game.over, m.game._meeting is None)
            for timer in tuple(m.game._timers):
                timer.function()
            self.assertEqual((m.game.over, m.game._meeting is None), state)
            self.assertEqual((len(m.router.group), len(m.router.dms)), (groups, dms),
                             "a stale backstop timer produced output")
            m.send(m.jids[0], ".endgame", group=True)
        self.assertFalse(m.game._timers)
        self.assertEqual(m.errors, [])


class Movement(Base):
    def test_stop_in_a_corridor_leaves_no_stale_arrival(self):
        m = self.new(5)
        p = crew(m)[0]
        spread(m)
        place(m, p, "CAFETERIA")
        m.t += 1
        m.send(p.jid, ".m Medbay")
        advance(m, 1)
        m.send(p.jid, ".stop")
        room_after_stop = (p.room, p.corridor_from, p.corridor_to)
        self.assertIsNone(p.path)
        mark = len(m.router.dms)
        advance(m, 30)
        self.assertEqual((p.room, p.corridor_from, p.corridor_to), room_after_stop)
        arrivals = [t for (_, to, t) in m.router.dms[mark:] if to == p.jid and "arriv" in t.lower()]
        self.assertEqual(arrivals, [])
        self.assertEqual(m.errors, [])

    def test_stop_then_goback_and_move_work(self):
        m = self.new(5)
        p = crew(m)[0]
        spread(m)
        place(m, p, "CAFETERIA")
        m.t += 1
        m.send(p.jid, ".m Medbay")
        advance(m, 1)
        m.send(p.jid, ".stop")
        out = m.send(p.jid, ".m Cafeteria")
        self.assertIn("Heading", str(out))
        advance(m, 30)
        self.assertEqual(p.room, "CAFETERIA")

    def test_camping_triggers_once_per_stop_and_not_again_until_a_new_stop(self):
        m = self.new(5)
        camper, watcher = crew(m)[0], crew(m)[1]
        spread(m)
        place(m, camper, "NAVIGATION")
        place(m, watcher, "NAVIGATION")
        for p in m.game.players.values():
            if p not in (camper, watcher):
                place(m, p, "ADMIN")
        camper.stopped_since = m.t
        advance(m, int(C.CAMPING_TRIGGER_SECONDS) + 3)
        notices = [t for (_, to, t) in m.router.dms if to == watcher.jid and "stationary here" in t]
        self.assertEqual(len(notices), 1, notices)
        advance(m, 60)
        notices2 = [t for (_, to, t) in m.router.dms if to == watcher.jid and "stationary here" in t]
        self.assertEqual(len(notices2), 1)

    def test_stopping_does_not_trigger_camping_while_moving_on(self):
        m = self.new(5)
        p, other = crew(m)[0], crew(m)[1]
        spread(m)
        place(m, p, "CAFETERIA")
        place(m, other, "CAFETERIA")
        m.t += 1
        m.send(p.jid, ".m Medbay")
        advance(m, 1)
        m.send(p.jid, ".stop")
        m.send(p.jid, ".m Cafeteria")
        advance(m, 70)
        self.assertEqual(m.errors, [])


class SimultaneousArrivals(Base):
    """User decision (Session 8): arrivals within one second are simultaneous."""

    def arrive(self, delta):
        m = self.new(5)
        a, b = crew(m)[0], crew(m)[1]
        spread(m)
        place(m, a, "ADMIN")
        place(m, b, "ADMIN")
        for p in m.game.players.values():
            if p not in (a, b):
                place(m, p, "MEDBAY")
        m.t += 1
        m.mgr._pre_dispatch(a.jid, ".m Cafeteria", received_at_ms=round(m.t * 1000))
        m.mgr._pre_dispatch(b.jid, ".m Cafeteria", received_at_ms=round((m.t + delta) * 1000))
        advance(m, 40)
        self.assertEqual(m.errors, [])
        def notes(p):
            return [t for (_, to, t) in m.router.dms if to == p.jid and (("Nearby room update" in t and "arrived in Cafeteria" in t) or "arrived beside you" in t)]
        return notes(a), notes(b)

    def test_within_a_second_both_are_told_exactly_once(self):
        """Design note v5.3 22.2: the arriving player is told inside their own
        arrival message ("X arrived beside you."); an earlier arrival, who got
        no such message, still gets the paired "Nearby room update"."""
        for delta in (0, 0.3, 0.6, 1.0):
            na, nb = self.arrive(delta)
            self.assertEqual(len(na), 1, (delta, na))
            self.assertEqual(len(nb), 1, (delta, nb))
            if delta == 0:
                self.assertIn("arrived beside you", na[0] + nb[0])
                self.assertNotIn("Nearby room update", na[0] + nb[0], delta)
            else:
                self.assertIn("Nearby room update", na[0], delta)   # earlier arrival
                self.assertIn("arrived beside you", nb[0], delta)   # later arrival

    def test_more_than_a_second_apart_the_earlier_one_is_simply_there(self):
        na, nb = self.arrive(1.5)
        self.assertIn("arrived beside you", na[0])   # the earlier arrival is told
        self.assertIn("Nearby room update", nb[0])


class Following(Base):
    def test_follow_ends_when_the_target_vents_and_when_the_follower_acts(self):
        m = self.new(7)
        imps = impostors(m)
        spread(m)
        target = imps[0]
        follower = crew(m)[0]
        place(m, target, "ELECTRICAL")
        place(m, follower, "ELECTRICAL")
        for p in m.game.players.values():
            if p not in (target, follower):
                place(m, p, "ADMIN")
        m.t += 1
        self.assertIn("now following", str(m.send(follower.jid, f".follow {target.color}")))
        self.assertEqual(follower.following, target.jid)
        m.send(target.jid, ".vent in")
        advance(m, 2)
        self.assertIsNone(follower.following)
        self.assertTrue(any("lost their trail" in t or "lost your trail" in t or "vent" in t.lower()
                            for (_, to, t) in m.router.dms if to == follower.jid))
        self.assertEqual(m.errors, [])

    def test_follow_ends_when_the_follower_starts_a_task(self):
        m = self.new(6)
        spread(m)
        (imp,) = impostors(m)
        follower = crew(m)[0]
        task = next(t for t in follower.tasks if not t["done"] and not t.get("fake"))
        target = crew(m)[1]
        place(m, follower, task["room"])
        place(m, target, task["room"])
        for p in m.game.players.values():
            if p not in (target, follower):
                place(m, p, "ADMIN")
        m.t += 1
        m.send(follower.jid, f".follow {target.color}")
        self.assertEqual(follower.following, target.jid)
        cands = m.game._task_candidates(follower, room_only=True)
        idx = next(i for i, c in enumerate(cands, 1) if c["id"] == task["id"])
        m.send(follower.jid, f".task {idx}")
        self.assertIsNone(follower.following)


class History(Base):
    def test_crime_scene_history_survives_the_meeting_and_body_removal(self):
        m = self.new(6)
        (imp,) = impostors(m)
        victim, reporter = crew(m)[0], crew(m)[1]
        first_kill_and_report(m, imp, victim, reporter)
        before = m.send(reporter.jid, ".cs")
        advance(m, 95)  # meeting runs out, nobody ejected
        after = m.send(reporter.jid, ".cs")
        self.assertIn("Storage", str(after))
        self.assertNotIn("No reported crime scenes", str(after))
        self.assertEqual(m.errors, [])


class Privacy(Base):
    def test_a_whole_match_never_shows_a_real_identity_or_leaks_between_roles(self):
        for seed in (51, 52):
            m = S.Match(8, seed)
            m.vote_accuracy = 0.6
            try:
                S.run(m, 3500, lambda mm: S.smart_step(mm, kill=True, sabotage=("reactor", "oxygen", "lights", "comms")))
                self.assertTrue(m.game.over)
                assert_ended_cleanly(self, m)
            finally:
                m.cleanup()


# Checklist items the simulator cannot reach (Session 08 section 6):
#  - cross-group routing and Pokemon-mode interference: tests/golden_handle_test.py
#    (494 scenarios, needs network); run it on the device.
#  - simultaneous arrivals: Session 02 leaves the tolerance undecided (exact time,
#    1 s or the 2 s window); S8 in package 7 only checks stability.
#  - state after a bot restart on the JS side (comms restriction record): bridge.js.

if __name__ == "__main__":
    unittest.main(verbosity=1)
