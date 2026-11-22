import random
import sys
import unittest
from pathlib import Path

BOT_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(BOT_ROOT / "engine" / "router")]

import amongus_puzzles as P  # noqa: E402


class AmongUsSessionSevenB2biiTests(unittest.TestCase):
    def test_library_is_well_formed(self):
        self.assertGreaterEqual(len(P.PHRASE_PUZZLES), 12)
        ids = [p.id for p in P.PHRASE_PUZZLES]
        self.assertEqual(len(ids), len(set(ids)))
        texts = [p.text for p in P.PHRASE_PUZZLES]
        self.assertEqual(len(texts), len(set(texts)))
        for p in P.PHRASE_PUZZLES:
            self.assertGreaterEqual(len(p.words), 4, p.id)
            self.assertEqual(p.text, p.text.lower(), p.id)
            self.assertIn(P.normalize_phrase(p.text), p.accepted)

    def test_no_accepted_answer_belongs_to_two_phrases(self):
        seen = {}
        for p in P.PHRASE_PUZZLES:
            for form in p.accepted:
                self.assertNotIn(form, seen, f"{p.id} clashes with {seen.get(form)}")
                seen[form] = p.id

    def test_normaliser_ignores_case_spacing_punctuation_and_stray_symbols(self):
        phrase = P.get_phrase("cafeteria")
        for answer in (
            "all crew report to the cafeteria",
            "ALL CREW REPORT TO THE CAFETERIA",
            "  All   crew report   to the cafeteria  ",
            "All crew, report to the cafeteria!!!",
            "all-crew_report/to.the*cafeteria",
            "🚀 all crew report to the cafeteria 🚀",
            "allcrewreporttothecafeteria",
            "All\ncrew\treport to the café­teria".replace("café", "cafe"),
        ):
            self.assertTrue(P.check_phrase(phrase, answer), answer)

    def test_accents_fold_and_ampersand_means_and(self):
        self.assertEqual(P.normalize_phrase("Café"), "cafe")
        self.assertEqual(P.normalize_phrase("a & b"), "aandb")
        self.assertEqual(P.normalize_phrase(None), "")
        self.assertEqual(P.normalize_phrase("   !!! "), "")
        phrase = P.get_phrase("lights")
        self.assertTrue(P.check_phrase(phrase, "Keep the lights on & stay calm"))

    def test_listed_variants_count_including_apostrophes(self):
        self.assertTrue(P.check_phrase("split", "Don't split up tonight."))
        self.assertTrue(P.check_phrase("split", "dont split up tonight"))
        self.assertTrue(P.check_phrase("split", "Do not split up tonight"))
        self.assertTrue(P.check_phrase("alone", "We're not alone out here"))
        self.assertTrue(P.check_phrase("tonight", "No one leaves the ship tonight"))
        self.assertTrue(P.check_phrase("oxygen", "check the O2 levels now"))
        self.assertTrue(P.check_phrase("storage", "Meet me AT the storage room"))

    def test_different_meanings_and_junk_are_rejected(self):
        wrong = {
            "signal": ["the signal is not coming through", "the signal is coming",
                       "signal coming through the", ""],
            "storage": ["meet me by the cafeteria", "meet me by the storage"],
            "tonight": ["somebody leaves the ship tonight", "nobody leaves the ship"],
            "vote": ["trust everyone until the vote", "trust no one"],
            "split": ["do split up tonight", "do not split up"],
        }
        for pid, answers in wrong.items():
            for answer in answers:
                self.assertFalse(P.check_phrase(pid, answer), (pid, answer))
        self.assertFalse(P.check_phrase("signal", None))
        self.assertFalse(P.check_phrase("signal", "!!!"))
        # One phrase's answer never repairs another's puzzle.
        self.assertFalse(P.check_phrase("signal", P.get_phrase("vote").text))

    def test_scramble_keeps_the_same_words_and_is_never_already_correct(self):
        rng = random.Random(11)
        for phrase in P.PHRASE_PUZZLES:
            for _ in range(200):
                words = P.scramble_phrase(phrase, rng)
                self.assertEqual(
                    sorted(w.lower() for w in words), sorted(phrase.words)
                )
                self.assertFalse(
                    P.check_phrase(phrase, " ".join(words)), (phrase.id, words)
                )
                self.assertFalse(
                    P.check_phrase(phrase, "".join(words)), (phrase.id, words)
                )

    def test_scramble_is_deterministic_for_a_seed_and_varies_across_seeds(self):
        phrase = P.get_phrase("reactor")
        a = P.scramble_phrase(phrase, random.Random(5))
        b = P.scramble_phrase(phrase, random.Random(5))
        self.assertEqual(a, b)
        seen = {tuple(P.scramble_phrase(phrase, random.Random(s))) for s in range(40)}
        self.assertGreater(len(seen), 5)

    def test_make_puzzle_shape_and_round_trip(self):
        rng = random.Random(3)
        puzzle = P.make_phrase_puzzle(rng)
        self.assertEqual(set(puzzle), {"id", "scrambled", "expected"})
        self.assertIn(" • ", puzzle["scrambled"])
        self.assertEqual(puzzle["scrambled"], puzzle["scrambled"].upper())
        self.assertTrue(P.check_phrase(puzzle["id"], puzzle["expected"]))
        self.assertFalse(P.check_phrase(puzzle["id"], puzzle["scrambled"]))

    def test_pick_covers_every_phrase_and_respects_exclusions(self):
        rng = random.Random(1)
        picked = {P.pick_phrase(rng).id for _ in range(600)}
        self.assertEqual(picked, {p.id for p in P.PHRASE_PUZZLES})
        for _ in range(200):
            self.assertNotEqual(P.pick_phrase(rng, exclude_ids=("signal",)).id, "signal")
        everything = tuple(p.id for p in P.PHRASE_PUZZLES)
        self.assertIn(P.pick_phrase(rng, exclude_ids=everything).id, everything)


if __name__ == "__main__":
    unittest.main()
