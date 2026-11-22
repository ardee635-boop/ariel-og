"""Pure puzzle data and logic for Among Us sabotage repairs.

No game state and no transport live here. Session 7B-1b-i adds the Lights
circuit puzzle; Session 7B-2b-ii adds the Communications phrase puzzle (phrase
set, accepted variants, scrambler and answer normaliser) to this same module.

Circuit conventions: a state is a tuple of bools (True = on) and switches are
numbered from 0 here. The UI layer shows them as 1..N. Pressing a switch
toggles every switch in that pattern's entry for it. The puzzle is solved
when every switch is on.
"""

from collections import deque
from dataclasses import dataclass
import random
import re
import unicodedata

CIRCUIT_SIZE = 5


@dataclass(frozen=True)
class CircuitPattern:
    id: str
    name: str
    toggles: tuple  # toggles[i] = indices flipped when switch i is pressed

    @property
    def size(self):
        return len(self.toggles)


def _pattern(pattern_id, name, toggles):
    return CircuitPattern(
        pattern_id,
        name,
        tuple(tuple(sorted(set(entry))) for entry in toggles),
    )


_N = CIRCUIT_SIZE

# Every pattern is invertible over GF(2), so every starting state is
# solvable, not only ones reached by scrambling from solved.
CIRCUIT_PATTERNS = (
    _pattern("ring", "Ring", [(i, (i - 1) % _N, (i + 1) % _N) for i in range(_N)]),
    _pattern("chain", "Chain", [(0, 1), (1, 2), (2, 3), (3, 4), (4,)]),
    _pattern("hub", "Hub", [(0, 2), (1, 2), (0, 1, 2, 3, 4), (3, 2), (4, 2)]),
    _pattern("skip", "Skip", [(0, 2, 3), (1, 3, 4), (2, 4, 0), (3, 0, 1), (4, 1, 2)]),
    _pattern("ladder", "Ladder", [(0, 1, 3), (1, 0, 2), (2, 1, 4), (3, 0, 4), (4, 2, 3)]),
)
_PATTERNS_BY_ID = {pattern.id: pattern for pattern in CIRCUIT_PATTERNS}


def get_pattern(pattern_id):
    return _PATTERNS_BY_ID[pattern_id]


def pick_pattern(rng=None):
    return (rng or random).choice(CIRCUIT_PATTERNS)


def solved_state(pattern):
    return (True,) * pattern.size


def apply_switch(state, pattern, index):
    """Return the new state after pressing switch `index` (0-based)."""
    if not 0 <= index < pattern.size:
        raise ValueError(f"switch {index} out of range for {pattern.id}")
    if len(state) != pattern.size:
        raise ValueError("state size does not match pattern")
    flipped = set(pattern.toggles[index])
    return tuple((not v) if i in flipped else v for i, v in enumerate(state))


def is_solved(state):
    return len(state) > 0 and all(state)


def scramble(pattern, rng=None, min_off=2):
    """A solvable, not-yet-solved starting state with at least `min_off` off."""
    rng = rng or random
    for _ in range(50):
        state = solved_state(pattern)
        for index in rng.sample(range(pattern.size), rng.randint(2, pattern.size)):
            state = apply_switch(state, pattern, index)
        if sum(1 for v in state if not v) >= min_off:
            return state
    # Deterministic fallback; patterns are invertible so this is solvable.
    state = apply_switch(solved_state(pattern), pattern, 0)
    return apply_switch(state, pattern, 2)


def min_presses(state, pattern):
    """Fewest presses to solve `state`, or None if unsolvable (breadth-first)."""
    state = tuple(state)
    if is_solved(state):
        return 0
    seen = {state}
    queue = deque([(state, 0)])
    while queue:
        current, depth = queue.popleft()
        for index in range(pattern.size):
            nxt = apply_switch(current, pattern, index)
            if nxt in seen:
                continue
            if is_solved(nxt):
                return depth + 1
            seen.add(nxt)
            queue.append((nxt, depth + 1))
    return None


# ── Communications phrase puzzle (7B-2b-ii) ────────────────
#
# The bot posts the words of a phrase in scrambled order; the player replies
# with the intended phrase. Answers ignore case, spacing, punctuation, accents
# and stray symbols. Only the listed variants count as equivalent: anything
# with a different meaning (negation, other room, missing word) is wrong.

@dataclass(frozen=True)
class PhrasePuzzle:
    id: str
    text: str          # canonical phrase shown as the expected answer
    variants: tuple    # extra accepted wordings with the same meaning

    @property
    def words(self):
        return tuple(self.text.split())

    @property
    def accepted(self):
        """Normalised accepted answers (canonical plus variants)."""
        return frozenset(
            normalize_phrase(form) for form in (self.text, *self.variants)
        )


def normalize_phrase(value):
    """Reduce an answer to lowercase letters and digits only.

    "&" counts as "and"; accents are folded; everything else that is not a
    letter or digit (spaces, punctuation, emoji, stray symbols) is dropped.
    """
    text = str(value or "").replace("&", " and ")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]", "", text.lower())


PHRASE_PUZZLES = (
    PhrasePuzzle(
        "signal", "the signal is coming through",
        ("the signal comes through", "signal is coming through"),
    ),
    PhrasePuzzle(
        "cafeteria", "all crew report to the cafeteria",
        ("all crewmates report to the cafeteria",
         "all crew report to cafeteria",
         "everyone report to the cafeteria"),
    ),
    PhrasePuzzle(
        "oxygen", "check the oxygen levels now",
        ("check oxygen levels now", "check the o2 levels now"),
    ),
    PhrasePuzzle(
        "tonight", "nobody leaves the ship tonight",
        ("no one leaves the ship tonight",),
    ),
    PhrasePuzzle(
        "reactor", "the reactor is running hot",
        ("reactor is running hot", "the reactor runs hot"),
    ),
    PhrasePuzzle(
        "alone", "we are not alone out here",
        ("we're not alone out here",),
    ),
    PhrasePuzzle(
        "lights", "keep the lights on and stay calm",
        ("keep the lights on stay calm",),
    ),
    PhrasePuzzle(
        "vents", "someone is hiding in the vents",
        ("somebody is hiding in the vents", "someone is hiding in the vent"),
    ),
    PhrasePuzzle(
        "storage", "meet me by the storage room",
        ("meet me in the storage room", "meet me at the storage room"),
    ),
    PhrasePuzzle(
        "power", "the ship is running out of power",
        ("the ship is running low on power",),
    ),
    PhrasePuzzle(
        "vote", "trust no one until the vote",
        ("trust nobody until the vote",),
    ),
    PhrasePuzzle(
        "engine", "i saw them near the engine",
        ("i saw them by the engine",),
    ),
    PhrasePuzzle(
        "split", "do not split up tonight",
        ("don't split up tonight",),
    ),
)
_PHRASES_BY_ID = {phrase.id: phrase for phrase in PHRASE_PUZZLES}


def get_phrase(phrase_id):
    return _PHRASES_BY_ID[phrase_id]


def check_phrase(phrase, answer):
    """True if answer matches the phrase or one of its listed variants."""
    if isinstance(phrase, str):
        phrase = get_phrase(phrase)
    guess = normalize_phrase(answer)
    return bool(guess) and guess in phrase.accepted


def scramble_phrase(phrase, rng=None):
    """Return the phrase's words shuffled so they do not already form an answer.

    Result is a list of upper-case words; join with `format_scramble`.
    """
    if isinstance(phrase, str):
        phrase = get_phrase(phrase)
    rng = rng or random
    words = list(phrase.words)
    accepted = phrase.accepted
    for _ in range(100):
        rng.shuffle(words)
        if normalize_phrase("".join(words)) not in accepted:
            return [word.upper() for word in words]
    # Deterministic fallback: reverse (never valid for these phrases).
    fallback = list(reversed(phrase.words))
    if normalize_phrase("".join(fallback)) in accepted:
        fallback = fallback[1:] + fallback[:1]
    return [word.upper() for word in fallback]


def format_scramble(words):
    return " • ".join(words)


def pick_phrase(rng=None, exclude_ids=()):
    """Pick a phrase, avoiding exclude_ids unless that would leave none."""
    pool = [p for p in PHRASE_PUZZLES if p.id not in set(exclude_ids)]
    return (rng or random).choice(pool or PHRASE_PUZZLES)


def make_phrase_puzzle(rng=None, exclude_ids=()):
    """Build one scrambled-phrase puzzle ready to post.

    Returns {"id", "scrambled", "expected"}; check replies with
    `check_phrase(puzzle["id"], reply)`.
    """
    rng = rng or random
    phrase = pick_phrase(rng, exclude_ids)
    return {
        "id": phrase.id,
        "scrambled": format_scramble(scramble_phrase(phrase, rng)),
        "expected": phrase.text,
    }

