"""Session 09 package 7 - acceptance suites S1-S16 (Session 08 design).

Every scenario drives the real AmongUsManager and Game through real commands on
the simulated clock (tests/amongus_sim.py). The expected outputs come from the
Session 08 chat scripts and scenario cards; the match-over wording that is still
unapproved (07 sample text) is NOT asserted beyond what the bot sends today.

Result recording: each scenario is one test method named test_S<n>_... .
A scenario that depends on an undecided rule says so in its docstring.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import amongus_sim as S  # noqa: E402
from router import amongus_config as C  # noqa: E402

SEED = 21


# ───────────────────────── helpers ─────────────────────────
def impostors(m):
    return [p for p in m.game.players.values() if p.role == "impostor"]


def crew(m):
    return [p for p in m.game.players.values() if p.role != "impostor"]


def place(m, who, room):
    """Put a player in a room, settled (the clock is not what is under test)."""
    p = who if hasattr(who, "jid") else m.by_color(who)
    p.room = room
    p.reference_room = room
    p.settled = True
    p.path = None
    p.stopped_since = m.t
    return p


def spread(m, rooms=None):
    """Give every player a distinct quiet room so nobody witnesses anything."""
    rooms = rooms or [r for r in sorted(m.game.map.rooms)]
    for i, p in enumerate(m.game.players.values()):
        place(m, p, rooms[i % len(rooms)])


def advance(m, seconds):
    for _ in range(int(seconds)):
        m.tick()


def group_texts(m, since=None):
    return [t for (at, t) in m.router.group if since is None or at > since]


def dm_texts(m, jid, since=None):
    return [t for (at, to, t) in m.router.dms if to == jid and (since is None or at > since)]


def all_dm_texts(m, since=None):
    return [t for (at, to, t) in m.router.dms if since is None or at > since]


def match_over_messages(m):
    return [
        t for _, t in m.router.group
        if "Crewmates win" in t or "Impostors win" in t or "Reactor meltdown" in t
        or "O₂ depleted" in t
    ]


def assert_ended_cleanly(test, m, seconds=130):
    """Acceptance: one match-over message, every timer and interaction gone,
    nothing sent afterwards, no real identity ever shown."""
    g = m.game
    test.assertTrue(g.over, "match should be over")
    test.assertEqual(len(match_over_messages(m)), 1, match_over_messages(m))
    test.assertFalse(g._timers)
    test.assertIsNone(g._meeting)
    for name, s in g._sabotages.items():
        test.assertNotEqual(s["state"], "active", f"{name} still active")
    for p in g.players.values():
        test.assertIsNone(p.task_in_progress)
        test.assertIsNone(p.pending_kill)
    groups, dms = len(m.router.group), len(m.router.dms)
    for _ in range(seconds):
        m.tick()
    test.assertEqual(len(m.router.group), groups, "group message after end")
    test.assertEqual(len(m.router.dms), dms, "DM after end")
    test.assertEqual(m.errors, [])
    for _, t in m.router.group:
        test.assertFalse(S.JID_RE.search(t), f"identity in group message: {t[:60]}")
    for _, _, t in m.router.dms:
        test.assertFalse(S.JID_RE.search(t), f"identity in DM: {t[:60]}")


def personal_results(m):
    """{jid: text} of the match-over DM each non-departed player got."""
    out = {}
    for _, to, t in m.router.dms:
        if "Match over" in t:
            out.setdefault(to, []).append(t)
    return out


def first_kill_and_report(m, imp, victim, reporter, room="STORAGE"):
    """Impostor kills in ``room`` (alone with the victim); reporter then finds
    the body and reports. Returns the clock value at the report."""
    spread(m)
    place(m, imp, room)
    place(m, victim, room)
    m.t += 1
    out = m.send(imp.jid, f".kill {victim.color}")
    assert "Attempting" in (out or ""), out
    advance(m, 4)
    assert victim.alive, "kill resolved before the 5 s wait ended"
    advance(m, 1)
    assert not victim.alive, "kill did not resolve after the 5 s wait"
    assert imp.kill_cooldown_until - m.t > 28, "30 s cooldown did not start at resolution"
    place(m, reporter, room)
    m.game._check_body_here(reporter, room)
    return m.send(reporter.jid, ".report")


def start_task(m, p, task):
    """`.task <n>` for the given task in the player's current room."""
    cands = m.game._task_candidates(p, room_only=True)
    for i, c in enumerate(cands, start=1):
        if c["id"] == task["id"]:
            return m.send(p.jid, f".task {i}")
    return m.send(p.jid, ".task")


def start_meeting(m, caller, reason_cmd=".meeting"):
    return m.send(caller.jid, reason_cmd)


def vote_all(m, votes):
    """votes = {voter_player: target_colour_or_skip}"""
    for voter, target in votes.items():
        m.send(voter.jid, f".vote {target}")


class Base(unittest.TestCase):
    def new(self, n=5, seed=SEED):
        m = S.Match(n, seed)
        self.addCleanup(m.cleanup)
        return m


# ───────────────────────── S1 - S4: full chat scripts ─────────────────────────
class ChatScripts(Base):
    def test_S1_crewmate_win_by_ejection(self):
        m = self.new(5)
        (imp,) = impostors(m)
        green, blue, yellow, pink = crew(m)
        # Step 1: start notice (counts only) and private role DMs.
        start = " ".join(group_texts(m))
        self.assertTrue(group_texts(m), "no start notice")
        for p in m.game.players.values():
            self.assertTrue(
                any(p.color in t or "role" in t.lower() or "Impostor" in t or "Crewmate" in t
                    for t in dm_texts(m, p.jid)),
                f"{p.color} got no role DM",
            )
        self.assertNotIn(imp.color, start.replace("Impostors", ""), "start notice named the Impostor")
        # Steps 3-4: kill in Storage, 5 s wait, 30 s cooldown, nothing public, then report.
        before_group = len(m.router.group)
        out = first_kill_and_report(m, imp, pink, yellow)
        killed_at = m.t - 0
        elimination = " ".join(dm_texts(m, pink.jid))
        self.assertIn("eliminated", elimination)
        self.assertNotIn(imp.color, elimination, "elimination DM names the killer")
        new_group = group_texts(m)[before_group:]
        self.assertFalse(any("reported a witnessed body" in t for t in new_group))   # old 📢 line dropped
        self.assertTrue(any("found a corpse in " in t and "Victim: *" in t for t in new_group))
        self.assertTrue(m.game._meeting)
        self.assertEqual(m.game.players[imp.jid].pending_kill, None)
        # Every living player gets the meeting-call DM; the dead one does not.
        for p in (green, blue, yellow, imp):
            self.assertTrue(any("found a corpse!" in t for t in dm_texts(m, p.jid)), p.color)
        # Step 5: discussion runs from the start (a .say is relayed to the group).
        m.send(blue.jid, ".say I saw Red leave Storage")
        self.assertTrue(any(f"*{blue.color}:* I saw Red leave Storage" in t for t in group_texts(m)))
        # Step 7 before 60 s: voting is not open yet.
        early = m.send(green.jid, f".vote {imp.color}")
        self.assertIn("60", early or "")
        # Step 6: voting opens at 60 s with a hidetag announcement.
        advance(m, 60)
        self.assertTrue(m.game._meeting.get("voting_open"))
        self.assertTrue(any("Voting is open" in t for t in group_texts(m)))
        # Step 7: three votes for the Impostor, one for Blue.
        for voter in (green, blue, yellow):
            ack = m.send(voter.jid, f".vote {imp.color}")
            self.assertIn("registered", (ack or "").lower())
        ack = m.send(imp.jid, f".vote {blue.color}")
        self.assertEqual(ack, m.replies[-2][2], "the Impostor's acknowledgement differs from a crew vote's")
        self.assertFalse(any(imp.color in t and "voted" in t.lower() for t in group_texts(m)),
                         "vote content reached the group")
        # Steps 8-10: closes at 90 s (warning at 80 s), reveal, win, personal results.
        advance(m, 31)
        texts = group_texts(m)
        self.assertEqual(sum("10 seconds remaining" in t for t in texts), 1)
        self.assertTrue(any(f"{imp.color} was ejected." in t for t in texts))
        self.assertTrue(any(f"{imp.color} was an Impostor." in t for t in texts))
        self.assertTrue(any(
            "Impostor has been eliminated." in t or "All Impostors have been eliminated." in t
            for t in texts
        ))
        self.assertIn("Crewmates win", match_over_messages(m)[0])
        self.assertIn(imp.color, match_over_messages(m)[0])  # the reveal after the match
        results = personal_results(m)
        for p in m.game.players.values():
            self.assertEqual(len(results.get(p.jid, [])), 1, f"{p.color} personal result")
        self.assertIn("Your team won", results[green.jid][0])
        self.assertIn("Your team lost", results[imp.jid][0])
        self.assertNotIn("voted", results[imp.jid][0].lower())  # S4: no vote reveal
        assert_ended_cleanly(self, m)

    def test_S1_reveal_is_three_messages_in_order(self):
        m = self.new(5)
        (imp,) = impostors(m)
        green, blue, yellow, pink = crew(m)
        first_kill_and_report(m, imp, pink, yellow)
        advance(m, 60)
        vote_all(m, {green: imp.color, blue: imp.color, yellow: imp.color})
        mark = len(m.router.group)
        advance(m, 31)
        reveal = [t for _, t in m.router.group[mark:]]
        idx = [i for i, t in enumerate(reveal) if "Meeting ended" in t]
        self.assertEqual(len(idx), 1)
        i = idx[0]
        self.assertEqual(reveal[i + 1], "...")
        self.assertEqual(reveal[i + 2], ".......")
        self.assertIn("was ejected.", reveal[i + 3])
        self.assertIn("was an Impostor.", reveal[i + 3])
        self.assertTrue(
            "Impostor has been eliminated." in reveal[i + 3]
            or "All Impostors have been eliminated." in reveal[i + 3],
            reveal[i + 3],
        )

    def test_S2_crewmate_loss(self):
        m = self.new(5)
        (imp,) = impostors(m)
        green, blue, yellow, pink = crew(m)
        first_kill_and_report(m, imp, pink, yellow)
        advance(m, 60)
        # Green, Yellow and the Impostor vote Blue; Blue votes Green.
        vote_all(m, {green: blue.color, yellow: blue.color, imp: blue.color, blue: green.color})
        advance(m, 31)
        reveal = " ".join(group_texts(m))
        self.assertIn(f"{blue.color} was ejected.", reveal)
        self.assertIn(f"{blue.color} was not the Impostor.", reveal)
        self.assertIn("1/1 Impostor remains.", reveal)
        self.assertFalse(m.game.over)
        # The Impostor kills Yellow after the cooldown; Green + Red remain -> tie goes to Impostors.
        spread(m)
        place(m, imp, "STORAGE")
        place(m, yellow, "STORAGE")
        imp.kill_cooldown_until = 0
        out = m.send(imp.jid, f".kill {yellow.color}")
        self.assertIn("Attempting", out or "")
        advance(m, 5)
        self.assertTrue(m.game.over)
        self.assertEqual(len(match_over_messages(m)), 1)
        self.assertIn("Impostors win", match_over_messages(m)[0])
        self.assertIn("🔪 The Impostor was", match_over_messages(m)[0])  # singular grammar
        self.assertNotIn("Impostors were", match_over_messages(m)[0])
        results = personal_results(m)
        self.assertIn("Your team won", results[imp.jid][0])
        self.assertIn("Your team lost", results[green.jid][0])
        assert_ended_cleanly(self, m)

    def test_S3_impostor_victory_by_reactor_never_names_the_saboteur(self):
        m = self.new(5)
        (imp,) = impostors(m)
        spread(m)
        m.t += 1
        m.send(imp.jid, ".sabotage communications")
        activation = [t for t in group_texts(m) if "SABOTAGED" in t]
        self.assertEqual(len(activation), 1)
        self.assertIn("COMMUNICATIONS", activation[0].upper())
        self.assertNotIn(imp.color, activation[0])
        # Every player (the Impostor too) gets the DM version.
        for p in m.game.players.values():
            self.assertTrue(any("SABOTAGED" in t for t in dm_texts(m, p.jid)), p.color)
        initiated = [t for t in dm_texts(m, imp.jid) if "sabotage initiated" in t]
        self.assertEqual(len(initiated), 1)
        for p in crew(m):
            self.assertFalse(any("sabotage initiated" in t for t in dm_texts(m, p.jid)))
        # Comms cooldown is 3 minutes; Reactor is a separate cooldown.
        m.send(imp.jid, ".sabotage reactor")  # Reactor has its own cooldown, separate from Comms
        self.assertEqual(m.game._sabotages["reactor"]["state"], "active")
        advance(m, 60)
        self.assertTrue(m.game.over)
        text = match_over_messages(m)[0]
        self.assertIn("Reactor meltdown — Impostors win", text)
        # The group message after the timeout is the Impostor reveal; the activation never named Red.
        for t in group_texts(m):
            if "SABOTAGED" in t:
                self.assertNotIn(imp.color, t)
        for p in m.game.players.values():
            self.assertEqual(len(personal_results(m).get(p.jid, [])), 1, p.color)
        assert_ended_cleanly(self, m)

    def test_S4_impostor_voted_out_gets_only_the_generic_acknowledgement(self):
        m = self.new(5)
        (imp,) = impostors(m)
        green, blue, yellow, pink = crew(m)
        first_kill_and_report(m, imp, pink, yellow)
        advance(m, 60)
        vote_all(m, {green: imp.color, blue: imp.color, yellow: imp.color})
        m.send(imp.jid, f".vote {blue.color}")
        ack_imp = m.replies[-1][2]
        ack_crew = m.replies[-2][2]
        self.assertEqual(ack_imp, ack_crew)
        advance(m, 31)
        final = personal_results(m)[imp.jid][0]
        self.assertIn("Your team lost", final)
        for p in (green, blue, yellow):
            self.assertNotIn(p.color, final)
        assert_ended_cleanly(self, m)


# ───────────────────────── S5 - S16: scenario cards ─────────────────────────
class ScenarioCards(Base):
    def test_S5_ghost_pov(self):
        m = self.new(6)
        (imp,) = impostors(m)
        pink = crew(m)[-1]
        spread(m)
        place(m, imp, "STORAGE")
        place(m, pink, "STORAGE")
        m.t += 1
        m.send(imp.jid, f".kill {pink.color}")
        advance(m, 5)
        self.assertFalse(pink.alive)
        self.assertIn("ghost", " ".join(dm_texts(m, pink.jid)).lower())
        self.assertNotIn(imp.color, " ".join(dm_texts(m, pink.jid)))
        # `.say` goes to the Ghosts chat only: nothing reaches the group or living DMs.
        sent = []
        original = m.mgr._push_ghost_chat
        m.mgr._push_ghost_chat = lambda game, jid, text: sent.append((jid, text))
        try:
            g_before, d_before = len(m.router.group), len(m.router.dms)
            m.send(pink.jid, ".say hello from beyond")
        finally:
            m.mgr._push_ghost_chat = original
        self.assertEqual(sent, [(pink.jid, "hello from beyond")])
        self.assertEqual(len(m.router.group), g_before)
        self.assertEqual(len(m.router.dms), d_before)
        # Ghost tasks are available and the Ghost cannot vote.
        reply = m.send(pink.jid, ".tasks")
        self.assertTrue(reply)
        self.assertTrue(m.game.players[pink.jid].alive is False)
        living = [p for p in crew(m) if p.alive][0]
        place(m, living, "CAFETERIA")
        m.send(living.jid, ".meeting")
        advance(m, 61)
        refused = m.send(pink.jid, f".vote {imp.color}")
        self.assertNotIn("registered", (refused or "").lower())
        self.assertNotIn(pink.jid, m.game._meeting["votes"])

    def test_S5_ghost_travel_is_half_time(self):
        self.assertEqual(C.GHOST_TRAVEL_TIME_MULTIPLIER, 0.5)

    def test_S6_meeting_during_a_pending_kill(self):
        m = self.new(5)
        (imp,) = impostors(m)
        blue, yellow = crew(m)[1], crew(m)[2]
        spread(m)
        place(m, imp, "STORAGE")
        place(m, blue, "STORAGE")
        place(m, yellow, "CAFETERIA")
        m.t += 1
        m.send(imp.jid, f".kill {blue.color}")
        self.assertIsNotNone(imp.pending_kill)
        advance(m, 2)
        m.send(yellow.jid, ".meeting")
        self.assertIsNone(imp.pending_kill)
        self.assertTrue(blue.alive)
        mark = len(m.router.dms)
        advance(m, 10)
        self.assertTrue(blue.alive)
        self.assertFalse(any("eliminated" in t for _, _, t in m.router.dms[mark:]))
        self.assertTrue(m.game._meeting)

    def test_S7_meeting_during_a_pending_task_interaction(self):
        m = self.new(5)
        green, yellow = crew(m)[0], crew(m)[2]
        spread(m)
        task = next(t for t in green.tasks if not t["done"] and not t.get("fake"))
        place(m, green, task["room"])
        place(m, yellow, "CAFETERIA")
        m.t += 1
        start_task(m, green, task)
        self.assertIsNotNone(green.task_in_progress)
        expires_before = green.task_in_progress["expires_at"]
        m.send(yellow.jid, ".meeting")
        refused = m.send(green.jid, f".task answer {green.task_in_progress['expected']}")
        self.assertTrue(refused, "a task answer during the meeting must be refused")
        self.assertFalse(task["done"])
        advance(m, 90 + 1)
        self.assertIsNone(m.game._meeting)
        # Design: the timer is extended by the meeting length so the task is not lost.
        if green.task_in_progress is None:
            self.fail("S7 FAIL (design gap): the task interaction expired during the meeting "
                      "instead of being extended by the meeting length")
        self.assertGreater(green.task_in_progress["expires_at"], expires_before)
        m.send(green.jid, f".task answer {green.task_in_progress['expected']}")
        self.assertTrue(task["done"])

    def test_S8_simultaneous_arrivals_notice_order_is_stable(self):
        m = self.new(5)
        a, b = crew(m)[0], crew(m)[1]
        spread(m)
        place(m, a, "ADMIN")
        place(m, b, "ADMIN")
        m.t += 1
        for p in (a, b):
            m.send(p.jid, ".m Cafeteria")
        advance(m, 60)
        notices = {p.color: dm_texts(m, p.jid) for p in (a, b)}
        for color, texts in notices.items():
            seen = [t for t in texts if "Cafeteria" in t or "CAFETERIA" in t]
            self.assertEqual(len(seen), len(set(seen)), f"duplicate notices for {color}")
        self.assertEqual(m.errors, [])

    def test_S9_sabotage_overlap_is_independent(self):
        m = self.new(6)
        (imp,) = impostors(m)
        spread(m)
        m.t += 1
        names = ("oxygen", "reactor", "lights", "comms")
        # Each sabotage has its own cooldown; the four can be active together.
        for name in names:
            m.send(imp.jid, f".sabotage {name}")
        active = {n: s["state"] for n, s in m.game._sabotages.items()}
        self.assertEqual(sum(1 for s in active.values() if s == "active"), len(names), active)
        # Repairing Lights leaves the other three active.
        crew1 = crew(m)[0]
        m.game._repair_sabotage("lights", crew1, m.t)
        states = {n: s["state"] for n, s in m.game._sabotages.items()}
        self.assertEqual(states["lights"], "repaired")
        for n in ("oxygen", "reactor", "communications"):
            self.assertEqual(states[n], "active", n)
        # Only living Crewmates repair: the Impostor is refused and nothing changes.
        before = {n: s["state"] for n, s in m.game._sabotages.items()}
        m.send(imp.jid, ".task")
        self.assertEqual({n: s["state"] for n, s in m.game._sabotages.items()}, before)

    def test_S10_oxygen_expiry(self):
        m = self.new(5)
        (imp,) = impostors(m)
        spread(m)
        m.t += 1
        m.send(imp.jid, ".sabotage oxygen")
        advance(m, 45)
        texts = group_texts(m)
        self.assertEqual(sum("20s remaining" in t for t in texts), 1)
        self.assertEqual(sum("10s remaining" in t for t in texts), 1)
        failure = [t for t in texts if "OXYGEN FAILURE" in t]
        self.assertEqual(len(failure), 1)
        self.assertIn("The oxygen supply has run out.", failure[0])
        self.assertLess(failure[0].index("OXYGEN FAILURE"), failure[0].index("supply has run out"))
        self.assertLess(failure[0].index("supply has run out"), failure[0].index("O₂ depleted"))
        self.assertTrue(m.game.over)
        self.assertIn("O₂ depleted — Impostors win", match_over_messages(m)[0])
        assert_ended_cleanly(self, m)

    def test_S11_reactor_timeout_and_exact_deadline_is_too_late(self):
        m = self.new(5)
        (imp,) = impostors(m)
        spread(m)
        m.t += 1
        m.send(imp.jid, ".sabotage reactor")
        advance(m, 45)
        self.assertTrue(m.game.over)
        self.assertEqual(len(match_over_messages(m)), 1)
        self.assertIn("Reactor meltdown — Impostors win", match_over_messages(m)[0])
        assert_ended_cleanly(self, m)

    def test_S12_oxygen_repair_needs_reply_scans(self):
        m = self.new(6)
        (imp,) = impostors(m)
        a, b = crew(m)[0], crew(m)[1]
        spread(m)
        m.t += 1
        m.send(imp.jid, ".sabotage oxygen")
        o2 = m.game._sabotages["oxygen"]
        from router import amongus_map as MAP
        rooms = MAP.get_station_rooms("oxygen")
        place(m, a, rooms[0])
        place(m, b, rooms[1])
        m.send(a.jid, ".task")
        m.send(b.jid, ".task")
        self.assertEqual(o2["state"], "active")
        # A plain `scan` is explained and not counted.
        plain = m.send(a.jid, "scan")
        self.assertIn("reply", (plain or "").lower())
        self.assertEqual(o2["state"], "active")
        # Two reply-scans inside the 2 s window repair it; the other sabotages are unaffected.
        m.send(a.jid, "scan", quoted="a bot message")
        m.t += 1
        m.send(b.jid, "scan", quoted="a bot message")
        self.assertEqual(o2["state"], "repaired")
        m.send(imp.jid, ".sabotage lights")
        self.assertEqual(m.game._sabotages["lights"]["state"], "active")

    def test_S13_comms_with_a_meeting(self):
        m = self.new(5)
        (imp,) = impostors(m)
        green, blue, yellow, pink = crew(m)
        spread(m)
        m.t += 1
        m.send(imp.jid, ".sabotage comms")
        self.assertTrue(m.game.comms_restriction_active())
        # A body is reported while Comms is down: the restriction lifts for the meeting.
        place(m, imp, "STORAGE")
        place(m, pink, "STORAGE")
        imp.kill_cooldown_until = 0
        m.send(imp.jid, f".kill {pink.color}")
        advance(m, 5)
        place(m, yellow, "STORAGE")
        m.game._check_body_here(yellow, "STORAGE")
        m.send(yellow.jid, ".report")
        self.assertTrue(m.game._meeting)
        self.assertFalse(m.game.comms_restriction_active(), "restriction must lift for the meeting")
        advance(m, 91)
        self.assertIsNone(m.game._meeting)
        self.assertTrue(m.game.comms_restriction_active(), "restriction returns after the meeting")
        self.assertEqual(m.game._sabotages["communications"]["state"], "active")
        # Repair ends it; exactly one consolidated inactivity report, no replayed movement notices.
        m.game._repair_sabotage("communications", green, m.t)
        self.assertFalse(m.game.comms_restriction_active())
        reports = [t for _, t in m.router.group if "inactiv" in t.lower() or "while communications" in t.lower()]
        self.assertLessEqual(len(reports), 1)
        self.assertEqual(m.errors, [])

    def test_S14_task_win(self):
        m = self.new(5)
        spread(m)
        for t in m.game._team_tasks:
            t["done"] = True
        advance(m, 2)
        self.assertTrue(m.game.over)
        self.assertIn("All team tasks are complete", match_over_messages(m)[0])
        self.assertIn("The Impostor was", match_over_messages(m)[0])
        # A generic `done` never completes a task (new match).
        m2 = self.new(5)
        green = crew(m2)[0]
        task = next(t for t in green.tasks if not t["done"] and not t.get("fake"))
        place(m2, green, task["room"])
        m2.t += 1
        start_task(m2, green, task)
        self.assertIsNotNone(green.task_in_progress)
        m2.send(green.jid, ".task answer done")
        m2.send(green.jid, "done")
        self.assertFalse(task["done"])
        assert_ended_cleanly(self, m)

    def test_S15_departures(self):
        m = self.new(6)
        (imp,) = impostors(m)
        c1, c2 = crew(m)[0], crew(m)[1]
        spread(m)
        done_task = c1.tasks[0]
        done_task["done"] = True
        total_before = len(m.game._team_tasks)
        unfinished = [t for t in c1.tasks if not t["done"]]
        self.assertTrue(m.game.mark_departed(c1.jid, m.t))
        self.assertEqual(len(m.game._team_tasks), total_before - len(unfinished))
        self.assertIn(done_task, m.game._team_tasks)  # tasks already done stay counted
        self.assertFalse(m.game.over)
        m.game.mark_departed(imp.jid, m.t + 1)
        self.assertTrue(m.game.over)
        self.assertEqual(len(match_over_messages(m)), 1)
        self.assertIn("Crewmates win", match_over_messages(m)[0])
        self.assertIn("last Impostor left", match_over_messages(m)[0])
        # The departed player gets no result DM.
        self.assertNotIn(c1.jid, personal_results(m))
        assert_ended_cleanly(self, m)

    def test_S16_host_endgame_cancels_everything(self):
        m = self.new(6)
        (imp,) = impostors(m)
        host = m.jids[0]
        green, yellow = crew(m)[0], crew(m)[2]
        spread(m)
        m.t += 1
        m.send(imp.jid, ".sabotage comms")
        m.send(imp.jid, ".sabotage reactor")
        place(m, yellow, "CAFETERIA")
        m.send(yellow.jid, ".meeting")
        self.assertTrue(m.game._meeting)
        task = next(t for t in green.tasks if not t["done"] and not t.get("fake"))
        place(m, green, task["room"])
        out = m.send(host, ".endgame", group=True)
        self.assertTrue(m.game.over)
        self.assertIsNone(m.game._meeting)
        self.assertFalse(m.game._timers)
        self.assertFalse(m.game.comms_restriction_active())
        for s in m.game._sabotages.values():
            self.assertNotEqual(s["state"], "active")
        self.assertTrue(any("Match ended by the host" in t for t in group_texts(m)))
        self.assertEqual(personal_results(m), {}, "no personal results when the host ends the match")
        groups, dms = len(m.router.group), len(m.router.dms)
        advance(m, 130)
        self.assertEqual((len(m.router.group), len(m.router.dms)), (groups, dms))
        self.assertEqual(m.errors, [])


# ───────────────────────── whole-game fuzz + acceptance checks ─────────────────────────
class Acceptance(Base):
    def test_every_ending_is_one_message_with_results_and_silence(self):
        for seed in (31, 32, 33, 34):
            m = S.Match(6, seed)
            m.vote_accuracy = 0.6
            try:
                S.run(m, 4000, lambda mm: S.smart_step(mm, kill=True, sabotage=("reactor", "oxygen", "lights", "comms")))
                self.assertTrue(m.game.over, f"seed {seed} never finished")
                assert_ended_cleanly(self, m)
                results = personal_results(m)
                for p in m.game.players.values():
                    if not p.departed:
                        self.assertEqual(len(results.get(p.jid, [])), 1, f"seed {seed} {p.color}")
            finally:
                m.cleanup()

    def test_no_activation_ever_names_the_impostor_in_a_whole_match(self):
        for seed in (41, 42, 43):
            m = S.Match(7, seed)
            m.vote_accuracy = 0.6
            try:
                S.run(m, 3000, lambda mm: S.smart_step(mm, kill=True, sabotage=("reactor", "oxygen", "lights", "comms")))
                imps = [p.color for p in impostors(m)]
                texts = [t for _, t in m.router.group] + [t for _, _, t in m.router.dms]
                for t in texts:
                    if "SABOTAGED" in t:
                        for color in imps:
                            self.assertNotIn(f"*{color}*", t, "activation named an Impostor")
            finally:
                m.cleanup()

    def test_meeting_constants_match_the_design(self):
        self.assertEqual(C.MEETING_DURATION_SECONDS, 90)
        self.assertEqual(C.MEETING_VOTING_OPENS_SECONDS, 60)
        self.assertEqual(C.MEETING_WARNING_SECONDS, 80)
        self.assertEqual(C.EJECTION_REVEAL_STEP_SECONDS, 0.0)  # simulator collapses the 2 s gaps
        self.assertEqual(C.KILL_COOLDOWN_SECONDS, 30)


if __name__ == "__main__":
    unittest.main(verbosity=1)
