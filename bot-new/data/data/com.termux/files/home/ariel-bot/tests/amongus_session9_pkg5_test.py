"""Session 09 package 5 - meetings: discussion then voting at 60 s, early-vote
rejection, hidetag voting announcement, DM/group links, three-message ejection
reveal with the real role and Impostor count, vent pull-out, one "use meeting
chat" reply, living `.say`, `.GC` / `.dm`, personal result DMs."""
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import amongus_session7d_test as T7  # noqa: E402
from router import amongus_config as C  # noqa: E402
from router.amongus import (  # noqa: E402
    AmongUsCoordinator,
    AmongUsManager,
    DELETE_INCOMING_MESSAGE,
)

JID = T7.JID
T = 100.0           # meeting start
OPEN = T + 60       # voting opens
END = T + 90        # voting closes


class RecManager(T7.FakeManager):
    """Records broadcast options and which DMs asked for the group link."""

    def __init__(self):
        super().__init__()
        self.kwargs = []
        self.linked = []
        self.ghost_chat = []

    def _broadcast(self, message, **kwargs):
        self.broadcasts.append(message)
        self.kwargs.append(kwargs)

    def _push_dm_with_link(self, player, message):
        self.linked.append((player, message))
        self.sent.append((player, message))

    def _push_ghost_chat(self, game, sender_jid, message):
        self.ghost_chat.append((sender_jid, message))


def new_game():
    game = T7.make_game()
    game.manager = RecManager()
    return game


def call_meeting(game, color="Red", reason="emergency", at=T):
    return game._cmd_call_meeting(T7.player(game, color), reason, at)


REAL_REVEAL_STEP = C.EJECTION_REVEAL_STEP_SECONDS


class MeetingTimeline(unittest.TestCase):
    def setUp(self):
        # The staged result is delivered by real timers; collapse the gaps here
        # (the constant itself is checked against REAL_REVEAL_STEP).
        step = mock.patch.object(C, "EJECTION_REVEAL_STEP_SECONDS", 0.0)
        step.start()
        self.addCleanup(step.stop)
        self.game = new_game()

    def tearDown(self):
        self.game.close()

    def test_constants_match_the_design(self):
        self.assertEqual(C.MEETING_DURATION_SECONDS, 90)
        self.assertEqual(C.MEETING_VOTING_OPENS_SECONDS, 60)
        self.assertEqual(C.MEETING_WARNING_SECONDS, 80)
        self.assertEqual(C.MEETING_VOTING_WINDOW_SECONDS, 30)
        self.assertEqual(REAL_REVEAL_STEP, 4.0)   # design note v5.3, 22.6

    def test_call_announces_to_group_with_dm_link_and_to_living_dms(self):
        game = self.game
        T7.player(game, "Lime").alive = False       # a Ghost
        call_meeting(game, "Red", "report")
        text = game.manager.broadcasts[-1]
        self.assertIn("🚨 *Red found a corpse!*", text)
        self.assertIn("Meeting started. Discuss here or use *.say <message>* from DM.", text)
        self.assertTrue(game.manager.kwargs[-1].get("append_dm_link"))
        # Every living player's DM carries the real group link; Ghosts get none.
        linked = {who for who, _ in game.manager.linked}
        living = {p.jid for p in game.players.values() if p.alive}
        self.assertEqual(linked, living)
        sample = next(m for who, m in game.manager.linked if who == JID["Blue"])
        self.assertIn("🚨 *Red found a corpse!*", sample)
        self.assertIn("Use .say to participate from your DM,", sample)
        self.assertIn("or join directly:", sample)

    def test_emergency_reason_text(self):
        call_meeting(self.game, "Red", "emergency")
        self.assertIn("🚨 *Red called an emergency meeting!*", self.game.manager.broadcasts[-1])
        dm = next(m for who, m in self.game.manager.linked if who == JID["Blue"])
        self.assertIn("Red called an emergency meeting.", dm)

    def test_early_vote_rejected_until_60_seconds(self):
        game = self.game
        call_meeting(game)
        red = T7.player(game, "Red")
        reply = game._cmd_vote(red, "Blue", public=False, now=T + 59)
        self.assertEqual(reply, "⚠️ _Voting opens at 60 seconds._")
        self.assertEqual(game._meeting["votes"], {})
        ok = game._cmd_vote(red, "Blue", public=False, now=OPEN)
        self.assertIn("registered privately", ok)
        self.assertEqual(game._meeting["votes"][red.jid], JID["Blue"])

    def test_early_group_vote_is_deleted_and_answered_privately(self):
        game = self.game
        call_meeting(game)
        out = game.handle_gc_vote(JID["Red"], ".vote Blue", received_at_ms=round((T + 10) * 1000))
        self.assertEqual(out, DELETE_INCOMING_MESSAGE)
        self.assertEqual(game._meeting["votes"], {})
        self.assertIn("Voting opens at 60 seconds", game.manager.sent[-1][1])
        self.assertEqual(game.manager.sent[-1][0], JID["Red"])

    def test_vote_open_announcement_is_hidetag_with_dm_link(self):
        game = self.game
        call_meeting(game)
        before = len(game.manager.broadcasts)
        game._advance_meeting(T + 59)
        self.assertEqual(len(game.manager.broadcasts), before)  # nothing yet
        game._advance_meeting(OPEN)
        text = game.manager.broadcasts[-1]
        self.assertIn("Voting is open", text)
        self.assertIn(".vote <colour>", text)
        self.assertIn(".vote skip", text)
        self.assertIn("privately through DM", text)
        opts = game.manager.kwargs[-1]
        self.assertTrue(opts.get("tag_all"))
        self.assertTrue(opts.get("hide_tags"))
        self.assertTrue(opts.get("append_dm_link"))
        # Each voter's DM explains exactly how to vote.
        dm = [m for who, m in game.manager.sent if who == JID["Blue"] and "Voting is open" in m]
        self.assertEqual(len(dm), 1)
        self.assertIn(".vote", dm[0])
        self.assertIn(".vote skip", dm[0])
        self.assertIn("change your vote", dm[0])
        game._advance_meeting(OPEN + 5)  # not repeated
        self.assertEqual(
            sum("Voting is open" in m for m in game.manager.broadcasts), 1
        )

    def test_warning_at_80_seconds_once_and_close_at_90(self):
        game = self.game
        call_meeting(game)
        game._advance_meeting(T + 79)
        self.assertFalse(any("10 seconds remaining" in m for m in game.manager.broadcasts))
        game._advance_meeting(T + 80)
        game._advance_meeting(T + 85)
        self.assertEqual(
            sum("10 seconds remaining" in m for m in game.manager.broadcasts), 1
        )
        red = T7.player(game, "Red")
        self.assertIn("registered", game._cmd_vote(red, "skip", public=False, now=T + 89))
        game._advance_meeting(END)
        self.assertIsNone(game._meeting)
        self.assertTrue(any("No one was ejected" in m for m in game.manager.broadcasts))

    def test_vote_after_close_is_rejected(self):
        game = self.game
        call_meeting(game)
        red = T7.player(game, "Red")
        self.assertIn(
            "closed", game._cmd_vote(red, "skip", public=False, now=END + 1)
        )

    def test_changing_a_vote_keeps_one_entry(self):
        game = self.game
        call_meeting(game)
        red = T7.player(game, "Red")
        game._cmd_vote(red, "Blue", public=False, now=OPEN)
        reply = game._cmd_vote(red, "Green", public=True, now=OPEN + 1)
        self.assertEqual(reply, DELETE_INCOMING_MESSAGE)
        self.assertEqual(game._meeting["votes"], {red.jid: JID["Green"]})
        self.assertIn("vote was changed", game.manager.sent[-1][1])


class EjectionReveal(unittest.TestCase):
    def setUp(self):
        self.game = new_game()

    def tearDown(self):
        self.game.close()

    def eject(self, color, step=0.0):
        game = self.game
        with mock.patch.object(C, "EJECTION_REVEAL_STEP_SECONDS", step):
            call_meeting(game)
            for voter in ("Red", "Blue", "Yellow", "White"):
                if voter != color:
                    game._cmd_vote(T7.player(game, voter), color, public=False, now=OPEN)
            game._resolve_meeting(END)

    def reveal(self):
        """The three reveal messages, wherever they sit in the group log."""
        log = self.game.manager.broadcasts
        start = next(i for i, m in enumerate(log) if "Meeting ended" in m)
        return log[start:start + 4]

    def test_three_messages_in_order_with_role_and_count(self):
        self.eject("Pink")
        first, second, third, final = self.reveal()
        self.assertEqual(first, "⏱️ *Meeting ended.*")
        self.assertEqual(second, "...")
        self.assertEqual(third, ".......")
        self.assertEqual(
            final,
            "Pink was ejected.\nPink was an Impostor.\n1/2 Impostors remain.\nCarry on...",
        )
        self.assertFalse(T7.player(self.game, "Pink").alive)

    def test_scientist_and_crewmate_wording(self):
        self.eject("Green")
        self.assertIn("Green was ejected.\nGreen was not the Impostor.", self.reveal()[3])
        self.assertIn("2/2 Impostors remain.\nCarry on...", self.reveal()[3])
        game = new_game()
        try:
            with mock.patch.object(C, "EJECTION_REVEAL_STEP_SECONDS", 0.0):
                game._cmd_call_meeting(T7.player(game, "Red"), "emergency", T)
                game._cmd_vote(T7.player(game, "Blue"), "Red", public=False, now=OPEN)
                game._resolve_meeting(END)
            self.assertIn("Red was not the Impostor.", game.manager.broadcasts[-1])
        finally:
            game.close()

    def test_last_impostor_message(self):
        T7.player(self.game, "Black").alive = False
        self.eject("Pink")
        self.assertIn("All Impostors have been eliminated.", self.reveal()[3])
        self.assertNotIn("Carry on", self.reveal()[3])   # the victory supersedes it

    def test_no_roster_or_voter_identity_in_reveal(self):
        self.eject("Pink")
        for message in self.reveal():
            self.assertNotIn("voted", message)
            self.assertNotRegex(message, T7.JID_PATTERN)

    def test_messages_are_spaced_and_win_is_immediate(self):
        game = self.game
        T7.player(game, "Black").alive = False   # Pink is the last Impostor
        step = 0.12
        started = time.monotonic()
        stamps = []
        game.manager._broadcast = lambda m, **kw: (
            game.manager.broadcasts.append(m), stamps.append(time.monotonic() - started)
        )
        self.eject("Pink", step=step)
        # Gameplay stopped the instant the win was true...
        self.assertTrue(game.over)
        # ...while the reveal is still being delivered.
        self.assertLess(len(stamps), 6)  # meeting call + at most part of the result
        deadline = time.monotonic() + 3
        while len(stamps) < 6 and time.monotonic() < deadline:
            time.sleep(0.02)
        sent = game.manager.broadcasts[-5:]
        self.assertEqual(len(stamps), 6)   # call, 4 result messages, match-over
        self.assertIn("Meeting ended", sent[0])
        self.assertEqual(sent[1], "...")
        self.assertEqual(sent[2], ".......")
        self.assertIn("was an Impostor", sent[3])
        self.assertIn("Crewmates win", sent[4])         # exactly one match-over
        gaps = [b - a for a, b in zip(stamps[1:], stamps[2:])]
        for gap in gaps:
            self.assertGreaterEqual(gap, step * 0.7)
        self.assertEqual(sum("Crewmates win" in m for m in sent), 1)


class VentAndCommandGate(unittest.TestCase):
    def setUp(self):
        self.game = new_game()

    def tearDown(self):
        self.game.close()

    def test_player_in_vent_is_pulled_out_into_the_vents_room(self):
        game = self.game
        black = T7.player(game, "Black")
        black.in_vent_until = T + 10
        black.vent_room = "ADMIN"
        black.room = "CAFETERIA"
        call_meeting(game, "Red")
        self.assertIsNone(black.in_vent_until)
        self.assertEqual(black.room, "ADMIN")
        self.assertIn(black.jid, game._meeting["eligible"])
        self.assertIn(
            "registered",
            game._cmd_vote(black, "skip", public=False, now=OPEN),
        )

    def test_gameplay_commands_get_one_meeting_chat_reply(self):
        game = self.game
        call_meeting(game)
        replies = set()
        for color, text in (
            ("Red", ".m Admin"), ("Red", ".stop"), ("Red", ".goback"),
            ("Red", ".vent"), ("Pink", ".kill Red"), ("Red", ".task"),
            ("Red", ".follow Blue"), ("Red", ".unfollow"),
            ("Red", ".report"), ("Red", ".meeting"),
            ("Pink", ".sabotage lights"), ("Green", ".vitals"),
            ("Green", ".witness"), ("Red", ".ready"),
        ):
            replies.add(T7.cmd(game, color, text, T + 5))
        self.assertEqual(len(replies), 1, replies)
        text = next(iter(replies))
        self.assertIn("paused", text)
        self.assertIn(".say", text)
        self.assertIn(".vote", text)

    def test_informational_commands_still_work(self):
        game = self.game
        call_meeting(game)
        for text in (".players", ".where", ".cds"):
            reply = T7.cmd(game, "Red", text, T + 5)
            self.assertNotIn("paused during the meeting", str(reply), text)

    def test_vote_command_works_through_handle(self):
        game = self.game
        call_meeting(game)
        self.assertIn("opens at 60", T7.cmd(game, "Red", ".vote Blue", T + 5))
        self.assertIn("registered", T7.cmd(game, "Red", ".vote Blue", OPEN + 1))


class SayCommand(unittest.TestCase):
    def setUp(self):
        self.game = new_game()

    def tearDown(self):
        self.game.close()

    def test_say_relays_under_colour_only(self):
        game = self.game
        call_meeting(game)
        before = len(game.manager.broadcasts)
        out = T7.cmd(game, "Blue", ".say I was in Admin", T + 5)
        self.assertIsNone(out)
        self.assertEqual(len(game.manager.broadcasts), before + 1)
        line = game.manager.broadcasts[-1]
        self.assertEqual(line, "🗣️ *Blue:* I was in Admin")
        self.assertNotRegex(line, T7.JID_PATTERN)

    def test_say_works_during_discussion_before_voting(self):
        call_meeting(self.game)
        self.assertIsNone(T7.cmd(self.game, "Red", ".say hello", T + 1))

    def test_say_needs_a_message(self):
        call_meeting(self.game)
        self.assertIn("Use .say", T7.cmd(self.game, "Red", ".say", T + 1))

    def test_say_outside_a_meeting_is_refused(self):
        game = self.game
        reply = T7.cmd(game, "Red", ".say hi", 50)
        self.assertIn("meetings", reply)
        self.assertEqual(game.manager.broadcasts, [])

    def test_say_after_the_meeting_is_refused(self):
        game = self.game
        call_meeting(game)
        game._resolve_meeting(END)
        self.assertIn("meetings", T7.cmd(game, "Red", ".say too late", END + 1))

    def test_player_who_joined_the_dead_cannot_speak_in_the_meeting(self):
        game = self.game
        call_meeting(game)
        T7.player(game, "Lime").alive = False
        out = game._handle_ghost(T7.player(game, "Lime"), ".say boo", T + 5)
        self.assertIsNone(out)
        self.assertEqual(len(game.manager.ghost_chat), 1)       # ghost chat only
        self.assertFalse(any("boo" in m for m in game.manager.broadcasts))


class LinkCommands(unittest.TestCase):
    def setUp(self):
        self.router = mock.Mock()
        self.coord = AmongUsCoordinator(self.router)

    def start(self, group, players):
        manager = self.coord._manager_for(group)
        manager.lobby = mock.Mock(players=list(players), group_jid=group, started=False)
        return manager

    def test_dm_returns_link_action(self):
        out = self.coord.pre_dispatch("111@s.whatsapp.net", ".dm")
        self.assertEqual(out["__amongus_action__"], "link_reply")
        self.assertEqual(out["kind"], "dm")
        self.assertIsNone(out["group_jid"])

    def test_gc_in_dm_targets_the_players_game_group(self):
        self.start("g1@g.us", ["111@s.whatsapp.net"])
        out = self.coord.pre_dispatch("111@s.whatsapp.net", ".GC")
        self.assertEqual(out["kind"], "game_group")
        self.assertEqual(out["group_jid"], "g1@g.us")

    def test_gc_in_a_group_prefers_that_groups_game(self):
        self.start("g1@g.us", ["111@s.whatsapp.net"])
        self.start("g2@g.us", ["111@s.whatsapp.net"])
        out = self.coord.pre_dispatch("111@s.whatsapp.net", ".gc", group_jid="g2@g.us")
        self.assertEqual(out["group_jid"], "g2@g.us")
        ambiguous = self.coord.pre_dispatch("111@s.whatsapp.net", ".gc")
        self.assertIn("more than one", ambiguous)

    def test_gc_when_not_playing(self):
        out = self.coord.pre_dispatch("222@s.whatsapp.net", ".GC")
        self.assertIn("not in an Among Us game", out)

    def test_other_text_is_not_a_link_command(self):
        self.assertIsNone(self.coord._link_command("x", ".dm now", None))
        self.assertIsNone(self.coord._link_command("x", ".vote", None))

    def test_broadcast_passes_the_dm_link_request_to_the_transport(self):
        router = mock.Mock()
        manager = AmongUsManager(router, "g1@g.us")
        manager._broadcast("hello", append_dm_link=True)
        self.assertTrue(router._direct_send.call_args.kwargs["append_dm_link"])
        router._direct_send.reset_mock()
        manager._broadcast("plain")
        self.assertNotIn("append_dm_link", router._direct_send.call_args.kwargs)


class ResultDms(unittest.TestCase):
    def setUp(self):
        self.game = new_game()

    def tearDown(self):
        self.game.close()

    def result_for(self, color):
        return [m for who, m in self.game.manager.sent if who == JID[color] and "Match over" in m]

    def test_each_player_gets_a_personal_result_after_the_group_message(self):
        game = self.game
        game._finish("🎉 *Crewmates win!* All team tasks are complete.", "crewmates")
        self.assertEqual(len([m for m in game.manager.broadcasts if "Crewmates win" in m]), 1)
        (red,) = self.result_for("Red")
        self.assertIn("Crewmates win", red)
        self.assertIn("Your role: *Crewmate* (Crewmates).", red)
        self.assertIn("Your team won", red)
        (green,) = self.result_for("Green")
        self.assertIn("Your role: *Scientist* (Crewmates).", green)
        (pink,) = self.result_for("Pink")
        self.assertIn("Your role: *Impostor* (Impostors).", pink)
        self.assertIn("Your team lost", pink)

    def test_impostor_win_results(self):
        game = self.game
        game._finish("🔪 *Impostors win!*", "impostors")
        self.assertIn("Your team won", self.result_for("Black")[0])
        self.assertIn("Your team lost", self.result_for("Blue")[0])

    def test_departed_players_get_no_result_and_ghosts_do(self):
        game = self.game
        T7.player(game, "Lime").departed = True
        T7.player(game, "Cyan").alive = False
        game._finish("🎉 *Crewmates win!*", "crewmates")
        self.assertEqual(self.result_for("Lime"), [])
        self.assertEqual(len(self.result_for("Cyan")), 1)

    def test_sabotage_timeout_is_an_impostor_result(self):
        game = self.game
        T7.sabotage(game, "reactor", T)
        game._resolve_win_check(T + 60)
        self.assertTrue(game.over)
        self.assertIn("Your team won", self.result_for("Pink")[0])

    def test_host_ending_sends_no_result(self):
        game = self.game
        game._end_game("🛑 _The host ended the match._")
        self.assertFalse(any("Match over" in m for _, m in game.manager.sent))


if __name__ == "__main__":
    unittest.main()
