"""Session 09 package 3 - paired sabotage: strict-before deadline, reply-only
scan, optional O2 `.ready` countdown, living-Crewmate-only repair."""
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import amongus_session7c_test as T  # noqa: E402
from router import amongus_config as C  # noqa: E402

BOT = "(a bot message)"


class Pkg3(T.PairedSabotageTests):
    # Re-running every inherited 7c test with the new rules is intentional.
    def test_scan_without_reply_is_rejected_and_does_not_count(self):
        self.start_oxygen(100.0)
        self.seat_pair(101.0)
        reply = self.game.handle("red", "scan", 105000)
        self.assertIn("reply", reply.lower())
        self.assertEqual(self.oxygen.pair.scans, {})
        self.assertIn("reply", self.game.handle("blue", ".scan", 105500).lower())
        self.assertEqual(self.oxygen["state"], "active")

    def test_two_replies_within_two_seconds_repair_oxygen(self):
        self.start_oxygen(100.0)
        self.seat_pair(101.0)
        self.game.handle("red", "scan", 105000, quoted_text="any bot message")
        self.game.handle("blue", "scan", 106500, quoted_text="a different bot message")
        self.assertEqual(self.oxygen["state"], "repaired")

    def test_one_reply_one_plain_does_not_repair(self):
        self.start_oxygen(100.0)
        self.seat_pair(101.0)
        self.game.handle("red", "scan", 105000, quoted_text=BOT)
        self.game.handle("blue", "scan", 105500)
        self.assertEqual(self.oxygen["state"], "active")

    def test_duplicate_reply_from_same_player_is_not_the_partner(self):
        self.start_oxygen(100.0)
        self.seat_pair(101.0)
        self.game.handle("red", "scan", 105000, quoted_text=BOT)
        self.game.handle("red", "scan", 105500, quoted_text=BOT)
        self.assertEqual(self.oxygen["state"], "active")

    def test_ready_message_text_for_oxygen_is_the_confirmed_wording(self):
        self.start_oxygen(100.0)
        T.put(self.game, "red", self.o2_a)
        T.put(self.game, "blue", self.o2_b)
        self.oxygen.join(self.game.players["red"], 101.0)
        reply = self.oxygen.join(self.game.players["blue"], 101.0)
        self.assertEqual(
            reply,
            "✅ Both stations are ready!\n\n"
            "Both players must reply scan to the bot message within 2 seconds of each other to fix oxygen.\n\n"
            "Send .ready to begin the repair countdown.",
        )
        self.assertEqual(T.last_dm(self.game, "red"), reply)

    def test_reactor_ready_text_has_no_countdown_offer(self):
        self.game._cmd_sabotage(self.pink, "reactor", 100.0)
        T.put(self.game, "red", self.re_a)
        T.put(self.game, "blue", self.re_b)
        self.reactor.join(self.game.players["red"], 101.0)
        reply = self.reactor.join(self.game.players["blue"], 101.0)
        self.assertNotIn(".ready", reply)
        self.assertIn("reactor", reply)

    def test_ready_sends_3_2_1_scan_now_to_both(self):
        self.start_oxygen(100.0)
        self.seat_pair(101.0)
        old = C.READY_COUNTDOWN_STEP_SECONDS
        C.READY_COUNTDOWN_STEP_SECONDS = 0.05
        try:
            self.assertIsNone(self.game.handle("red", ".ready", 102000))
            self.assertEqual(self.game.handle("blue", ".ready", 102100), "⏳ _The countdown is already running._")
            time.sleep(0.4)
        finally:
            C.READY_COUNTDOWN_STEP_SECONDS = old
        for jid in ("red", "blue"):
            got = [m for who, m in self.game.manager.sent if who == jid][-4:]
            self.assertEqual(got, ["3", "2", "1", "SCAN NOW!"], jid)
        self.assertIsNone(self.oxygen.countdown_token)

    def test_ready_is_not_required_for_repair(self):
        self.start_oxygen(100.0)
        self.seat_pair(101.0)
        self.game.handle("red", "scan", 105000, quoted_text=BOT)
        self.game.handle("blue", "scan", 105500, quoted_text=BOT)
        self.assertEqual(self.oxygen["state"], "repaired")

    def test_ready_before_both_stations_or_for_reactor(self):
        self.start_oxygen(100.0)
        T.put(self.game, "red", self.o2_a)
        self.oxygen.join(self.game.players["red"], 101.0)
        self.assertEqual(self.game.handle("red", ".ready", 102000), "Waiting for partner.")
        self.assertIn("oxygen station", self.game.handle("blue", ".ready", 102000))

    def test_reactor_has_no_countdown(self):
        self.game._cmd_sabotage(self.pink, "reactor", 100.0)
        T.put(self.game, "red", self.re_a)
        T.put(self.game, "blue", self.re_b)
        self.reactor.join(self.game.players["red"], 101.0)
        self.reactor.join(self.game.players["blue"], 101.0)
        self.assertIn("no countdown", self.game.handle("red", ".ready", 102000))

    def test_leaving_a_station_cancels_the_countdown(self):
        self.start_oxygen(100.0)
        self.seat_pair(101.0)
        old = C.READY_COUNTDOWN_STEP_SECONDS
        C.READY_COUNTDOWN_STEP_SECONDS = 0.1
        try:
            self.game.handle("red", ".ready", 102000)
            self.oxygen.vacate("red", "left", 102.0)
            time.sleep(0.5)
        finally:
            C.READY_COUNTDOWN_STEP_SECONDS = old
        got = [m for who, m in self.game.manager.sent if who == "blue"]
        self.assertNotIn("SCAN NOW!", got)

    def test_only_living_crewmates_repair(self):
        self.start_oxygen(100.0)
        T.put(self.game, "pink", self.o2_a)
        self.assertIn("can't repair", self.oxygen.join(self.game.players["pink"], 101.0))
        red = self.game.players["red"]
        red.alive = False
        T.put(self.game, "red", self.o2_a)
        self.assertIn("living", self.oxygen.join(red, 101.0))

    def test_scan_at_deadline_is_too_late_through_handle(self):
        deadline = self.start_oxygen(100.0)
        self.seat_pair(101.0)
        self.game.handle("red", "scan", int((deadline - 0.5) * 1000), quoted_text=BOT)
        self.game.handle("blue", "scan", int(deadline * 1000), quoted_text=BOT)
        self.assertEqual(self.oxygen["state"], "failed")
        self.assertIn("O₂ depleted — Impostors win", self.game.manager.broadcasts[-1])


# Keep only the new tests from this module's own class when run directly;
# the inherited 7c tests already ran in their own file.
for _name in [n for n in dir(Pkg3) if n.startswith("test_") and n not in Pkg3.__dict__]:
    setattr(Pkg3, _name, None)

if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
