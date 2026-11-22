"""Session 09 package 6a - Communications restriction: ordinary game-group
messages are deleted (no announcement-only lock), only Among Us commands and
the repairer's phrase answer survive, answers are accepted in the group only,
a meeting lifts the restriction, and the bot-side record is told when the
restriction starts and ends."""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import amongus_session7d_test as T7  # noqa: E402
from router import amongus_config as C  # noqa: E402
from router import amongus_puzzles as PZ  # noqa: E402
from router.amongus import (  # noqa: E402
    AmongUsCoordinator,
    AmongUsManager,
    COMMS_ANSWER_IN_GROUP_TEXT,
    DELETE_INCOMING_MESSAGE,
)

GROUP = T7.GAME_GROUP
JID = T7.JID
BOT_ROOT = Path(__file__).resolve().parents[1]


def new_match():
    """A real manager wrapped around the 7D game, with a recording router."""
    router = mock.Mock()
    manager = AmongUsManager(router, GROUP)
    game = T7.make_game()
    game.manager = manager
    manager.game = game
    manager.lobby = mock.Mock(players=list(game.players), host=JID["Red"], group_jid=GROUP)
    return router, manager, game


def say(manager, color, text, group=True, quoted=None, at=100.0):
    return manager._pre_dispatch(
        JID[color],
        text,
        group_jid=GROUP if group else None,
        received_at_ms=round(at * 1000),
        quoted_text=quoted,
    )


def actions(router):
    return [
        c.kwargs["group_action"]
        for c in router._direct_send.call_args_list
        if c.kwargs.get("group_action")
    ]


def group_texts(router):
    return [
        c.args[0]
        for c in router._direct_send.call_args_list
        if c.args and not c.kwargs.get("allow_dm") and not c.kwargs.get("group_action")
    ]


def start_repair(game, color="Cyan", at=110.0):
    """Cyan walks to Communications and starts the repair; returns the DM text."""
    T7.put(game, color, "COMMUNICATIONS")
    return T7.cmd(game, color, ".task", at)


def phrase_of(game, color="Cyan"):
    active = T7.player(game, color).task_in_progress
    return PZ.get_phrase(active["metadata"]["phrase_id"]).text


class RestrictionSignals(unittest.TestCase):
    def setUp(self):
        self.router, self.manager, self.game = new_match()

    def tearDown(self):
        self.game.close()

    def test_no_announcement_lock_is_ever_requested(self):
        T7.sabotage(self.game, "communications", 100.0)
        T7.repair_comms(self.game, "Cyan", 120.0)
        self.assertEqual(actions(self.router), ["restrict", "unrestrict"])
        self.assertNotIn("lock", actions(self.router))
        self.assertNotIn("unlock", actions(self.router))

    def test_old_lock_names_are_gone(self):
        source = (BOT_ROOT / "engine/router/amongus_game.py").read_text()
        self.assertNotIn("_set_group_lock", source)
        self.assertFalse(hasattr(C, "COMMS_GROUP_LOCK_ENABLED"))
        js = (BOT_ROOT / "bot/bridge.js").read_text()
        self.assertNotIn("groupSettingUpdate", js)
        self.assertNotIn('"announcement"', js)
        self.assertNotIn("'announcement'", js)

    def test_meeting_lifts_and_restores_the_restriction(self):
        game = self.game
        T7.sabotage(game, "communications", 100.0)
        self.assertTrue(game.comms_restriction_active())
        game._cmd_call_meeting(T7.player(game, "Red"), "emergency", 101.0)
        self.assertFalse(game.comms_restriction_active())
        game._resolve_meeting(now=191.0)
        self.assertTrue(game.comms_restriction_active())
        self.assertEqual(actions(self.router), ["restrict", "unrestrict", "restrict"])

    def test_match_end_clears_the_restriction(self):
        game = self.game
        T7.sabotage(game, "communications", 100.0)
        game._finish("🎉 *Crewmates win!*", "crewmates")
        self.assertEqual(actions(self.router)[-1], "unrestrict")
        self.assertFalse(game.comms_restriction_active())


class DeletionRule(unittest.TestCase):
    def setUp(self):
        self.router, self.manager, self.game = new_match()

    def tearDown(self):
        self.game.close()

    def test_nothing_is_deleted_while_communications_is_up(self):
        self.assertIsNot(say(self.manager, "Blue", "hello everyone"), DELETE_INCOMING_MESSAGE)

    def test_ordinary_chat_is_deleted_while_communications_is_down(self):
        T7.sabotage(self.game, "communications", 100.0)
        self.assertIs(say(self.manager, "Blue", "hello everyone"), DELETE_INCOMING_MESSAGE)
        self.assertIs(say(self.manager, "Blue", "pink is sus"), DELETE_INCOMING_MESSAGE)

    def test_other_bot_commands_are_deleted_too(self):
        T7.sabotage(self.game, "communications", 100.0)
        self.assertIs(say(self.manager, "Blue", ".catch pikachu"), DELETE_INCOMING_MESSAGE)

    def test_non_players_are_deleted_too(self):
        T7.sabotage(self.game, "communications", 100.0)
        out = self.manager._pre_dispatch(
            "2349999999999@s.whatsapp.net", "hi", group_jid=GROUP
        )
        self.assertIs(out, DELETE_INCOMING_MESSAGE)

    def test_among_us_commands_are_kept(self):
        T7.sabotage(self.game, "communications", 100.0)
        for text in (".vote Pink", ".amenu", ".players", ".task", ".GC", ".status"):
            self.assertIsNot(say(self.manager, "Blue", text), DELETE_INCOMING_MESSAGE, text)

    def test_meeting_allows_normal_discussion(self):
        game = self.game
        T7.sabotage(game, "communications", 100.0)
        game._cmd_call_meeting(T7.player(game, "Red"), "emergency", 101.0)
        self.assertIsNot(say(self.manager, "Blue", "it was Pink"), DELETE_INCOMING_MESSAGE)
        game._resolve_meeting(now=191.0)
        self.assertIs(say(self.manager, "Blue", "it was Pink"), DELETE_INCOMING_MESSAGE)

    def test_repair_lifts_the_deletion(self):
        game = self.game
        T7.sabotage(game, "communications", 100.0)
        T7.repair_comms(game, "Cyan", 120.0)
        self.assertIsNot(say(self.manager, "Blue", "finally"), DELETE_INCOMING_MESSAGE)

    def test_coordinator_forwards_group_text_only_while_restricted(self):
        coord = AmongUsCoordinator(self.router)
        coord._groups[GROUP] = self.manager
        self.assertFalse(coord.should_intercept_group(JID["Blue"], "hello", GROUP))
        T7.sabotage(self.game, "communications", 100.0)
        self.assertTrue(coord.should_intercept_group(JID["Blue"], "hello", GROUP))
        self.assertFalse(coord.should_intercept_group(JID["Blue"], "hello", "other@g.us"))


class GroupAnswers(unittest.TestCase):
    def setUp(self):
        self.router, self.manager, self.game = new_match()
        T7.sabotage(self.game, "communications", 100.0)
        self.dm = start_repair(self.game)
        self.ref = T7.player(self.game, "Cyan").task_in_progress["interaction_ref"]
        self.quoted = f"📡 Scrambled transmission ... [Task Ref: {self.ref}]"

    def tearDown(self):
        self.game.close()

    def test_scrambled_phrase_is_posted_in_the_group_with_a_task_ref(self):
        notice = next(t for t in group_texts(self.router) if "Unscramble: *" in t)
        self.assertIn(f"[Task Ref: {self.ref}]", notice)
        self.assertIn("in the game group", notice)
        self.assertIn("Unscramble: *", notice)
        self.assertNotIn("privately", notice)

    def test_dm_tells_the_player_to_answer_in_the_group(self):
        self.assertIn("in the game group", self.dm)
        self.assertNotIn("[Task Ref", self.dm)

    def test_dm_answers_are_refused_and_do_not_count(self):
        out = say(self.manager, "Cyan", f".task answer {phrase_of(self.game)}", group=False)
        self.assertEqual(out, COMMS_ANSWER_IN_GROUP_TEXT)
        self.assertEqual(T7.state(self.game, "communications"), "active")
        self.assertEqual(T7.player(self.game, "Cyan").task_in_progress["metadata"]["attempts"], 0)

    def test_dm_quote_reply_is_refused_too(self):
        out = say(self.manager, "Cyan", phrase_of(self.game), group=False, quoted=self.quoted)
        self.assertEqual(out, COMMS_ANSWER_IN_GROUP_TEXT)
        self.assertEqual(T7.state(self.game, "communications"), "active")

    def test_wrong_group_reply_is_kept_and_leaves_comms_down(self):
        out = say(self.manager, "Cyan", "totally wrong words", quoted=self.quoted)
        self.assertIsNot(out, DELETE_INCOMING_MESSAGE)
        self.assertTrue(out.startswith("*Cyan:*"))
        self.assertIn("not the intended phrase", out)
        self.assertEqual(T7.state(self.game, "communications"), "active")
        self.assertTrue(self.game.comms_restriction_active())

    def test_correct_group_reply_repairs_communications(self):
        out = say(self.manager, "Cyan", phrase_of(self.game), quoted=self.quoted)
        self.assertTrue(out.startswith("*Cyan:*"))
        self.assertIn("Communications repaired", out)
        self.assertEqual(T7.state(self.game, "communications"), "repaired")
        self.assertEqual(actions(self.router)[-1], "unrestrict")

    def test_answer_ignores_case_spacing_and_punctuation(self):
        messy = "  " + phrase_of(self.game).upper().replace(" ", "  ") + "!!! "
        out = say(self.manager, "Cyan", messy, quoted=self.quoted)
        self.assertIn("Communications repaired", out)

    def test_task_answer_command_in_the_group_repairs_communications(self):
        out = say(self.manager, "Cyan", f".task answer {phrase_of(self.game)}")
        self.assertIn("Communications repaired", out)
        self.assertEqual(T7.state(self.game, "communications"), "repaired")

    def test_a_different_player_replying_to_the_phrase_is_deleted(self):
        out = say(self.manager, "Blue", phrase_of(self.game), quoted=self.quoted)
        self.assertIs(out, DELETE_INCOMING_MESSAGE)
        self.assertEqual(T7.state(self.game, "communications"), "active")

    def test_a_plain_non_reply_from_the_repairer_is_deleted(self):
        out = say(self.manager, "Cyan", phrase_of(self.game))
        self.assertIs(out, DELETE_INCOMING_MESSAGE)
        self.assertEqual(T7.state(self.game, "communications"), "active")

    def test_group_answer_during_a_meeting_is_not_accepted(self):
        game = self.game
        game._cmd_call_meeting(T7.player(game, "Red"), "emergency", 115.0)
        out = say(self.manager, "Cyan", f".task answer {phrase_of(game)}", at=116.0)
        self.assertIsNot(out, DELETE_INCOMING_MESSAGE)
        self.assertEqual(T7.state(game, "communications"), "active")

    def test_a_game_command_in_the_group_is_still_private_without_an_interaction(self):
        out = say(self.manager, "Blue", ".task answer something")
        self.assertIn("private", out.lower())


if __name__ == "__main__":
    unittest.main()
