import itertools
import random
import sys
import unittest
from pathlib import Path

BOT_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(BOT_ROOT / "engine" / "router")]

import amongus_puzzles as P  # noqa: E402


class AmongUsSessionSevenB1biTests(unittest.TestCase):
    def test_library_has_distinct_well_formed_patterns(self):
        self.assertGreaterEqual(len(P.CIRCUIT_PATTERNS), 4)
        ids = [p.id for p in P.CIRCUIT_PATTERNS]
        self.assertEqual(len(ids), len(set(ids)))
        for p in P.CIRCUIT_PATTERNS:
            self.assertEqual(p.size, P.CIRCUIT_SIZE)
            for i, entry in enumerate(p.toggles):
                self.assertIn(i, entry, f"{p.id}: switch {i} must toggle itself")
                self.assertTrue(all(0 <= j < p.size for j in entry))
        self.assertEqual(
            len({p.toggles for p in P.CIRCUIT_PATTERNS}), len(P.CIRCUIT_PATTERNS)
        )

    def test_apply_switch_changes_exactly_the_listed_switches(self):
        for p in P.CIRCUIT_PATTERNS:
            for start in itertools.product((True, False), repeat=p.size):
                for i in range(p.size):
                    after = P.apply_switch(start, p, i)
                    for j in range(p.size):
                        changed = after[j] != start[j]
                        self.assertEqual(changed, j in p.toggles[i], (p.id, i, j))
                    self.assertEqual(P.apply_switch(after, p, i), start)

    def test_apply_switch_validates_input(self):
        p = P.get_pattern("ring")
        with self.assertRaises(ValueError):
            P.apply_switch(P.solved_state(p), p, p.size)
        with self.assertRaises(ValueError):
            P.apply_switch((True, True), p, 0)

    def test_is_solved_only_when_every_switch_is_on(self):
        for p in P.CIRCUIT_PATTERNS:
            for state in itertools.product((True, False), repeat=p.size):
                self.assertEqual(P.is_solved(state), all(state))
        self.assertFalse(P.is_solved(()))

    def test_every_pattern_solves_from_every_state(self):
        for p in P.CIRCUIT_PATTERNS:
            for state in itertools.product((True, False), repeat=p.size):
                self.assertIsNotNone(P.min_presses(state, p), (p.id, state))
        self.assertEqual(P.min_presses(P.solved_state(P.get_pattern("hub")),
                                       P.get_pattern("hub")), 0)

    def test_scramble_is_unsolved_solvable_and_seed_stable(self):
        for p in P.CIRCUIT_PATTERNS:
            for seed in range(100):
                state = P.scramble(p, random.Random(seed))
                self.assertFalse(P.is_solved(state))
                self.assertGreaterEqual(sum(1 for v in state if not v), 2)
                self.assertIsNotNone(P.min_presses(state, p))
                self.assertEqual(state, P.scramble(p, random.Random(seed)))


if __name__ == "__main__":
    unittest.main()
