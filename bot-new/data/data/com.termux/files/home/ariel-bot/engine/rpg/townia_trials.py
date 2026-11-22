# ============================================================
# ARIEL — TOWNIA_TRIALS.PY
# The class trials every cursed child can take in Townia before
# leaving. Warrior and Mage are fully built. Summoner's Phase 1 (pet
# picking) is built below — Phase 2 (affinity-building) and Phase 3
# (sealing) are NOT yet implemented, see the Summoner section's
# module comment. Priest and hidden classes still come later. Trial
# state is stored in RpgSession.flags["trial"] (see rpg_session.py)
# — same reserved-flags-key pattern _opening_choices already uses,
# not a new top-level field, so nothing else in the persisted schema
# needs to change to support this.
#
# Design constraints, from the actual discussion these mechanics
# were specified in:
#   - Every trial is retakeable unlimited times, pass or fail. The
#     elder always knows/remembers a player has attempted before —
#     that's flavor text the router/caller handles, not tracked here
#     as a hard limit.
#   - Warrior trial happens at the Coliseum against a real Soulbound
#     opponent (WARRIOR_OPPONENTS below, one named opponent per
#     weapon) — not a one-hit dummy.
#     Win condition: bring the opponent to <=15% HP. Seven weapons
#     on offer (sword/dagger/spear/axe/mace/shield/bow), each with
#     its own resolution mechanic (see WEAPON_MECHANIC below) but
#     all sharing the same underlying HP-attrition fight against
#     that weapon's named opponent, using the real secondary_stats.py
#     formulas (block_chance, physical_attack) — not a separate
#     one-off roll.
#   - Weapons map to classes, and clearing several weapons in one
#     trial visit (or across retries — cleared weapons persist on
#     the session) stacks multiple classes. Bow uniquely grants TWO
#     classes at once (Archer + Scout). Clearing all seven weapons
#     additionally grants Warrior + the Weapon Master skill.
#   - Mage: the elder "shows" a 3-5 line incantation (auto-deletes
#     after a random 9-15s window, WhatsApp-delete-style), player
#     must recast it from memory. Word-match only — punctuation and
#     spacing differences don't matter ("mana o mana" == "mana o'
#     mana"), but actual wrong/misspelled words fail the attempt.
#     If the player recasts correctly BEFORE the auto-delete fires,
#     the elder is surprised and skips the delete/prompt entirely —
#     instant pass. Unlimited retries; every 5th attempt the elder
#     suggests resting, but the player can insist and continue.
# ============================================================

import random
import re
import time

from secondary_stats import compute_self_secondary, resolve_contested

# ── Warrior trial data ──────────────────────────────────────────

WARRIOR_WEAPONS = ["sword", "dagger", "spear", "axe", "mace", "shield", "bow"]

# Weapon -> resolution mechanic. "fight" = direct HP-attrition combat
# roll each turn (sword/dagger/spear/axe/mace). "shield" and "bow"
# get their own dedicated multi-turn mechanics below.
WEAPON_MECHANIC = {
    "sword":  "fight",
    "dagger": "fight",
    "spear":  "fight",
    "axe":    "fight",
    "mace":   "fight",
    "shield": "shield",
    "bow":    "bow",
}

# Weapon -> class(es) granted on a pass. Bow is the one weapon that
# grants two classes at once (Archer + Scout) — everything else
# grants exactly one. Values are always a tuple so callers never
# need to special-case bow.
WEAPON_CLASS = {
    "sword":  ("Swordsman",),
    "dagger": ("Scout",),
    "spear":  ("Spearman",),
    "axe":    ("Axeman",),
    "mace":   ("Bludgeon",),
    "shield": ("Shieldbearer",),
    "bow":    ("Archer", "Scout"),
}

# Class -> the weapon a fresh Soulbound is handed into .inv the moment
# that class is confirmed (see router/rpg.py's "yes" branch). Mostly
# WEAPON_CLASS read in reverse, EXCEPT Scout: dagger and bow both
# grant Scout, but Scout's weapon is always dagger — a Scout is a
# dagger user by definition, regardless of which trial got them
# there (a bow-cleared Scout still doesn't carry a bow around; if
# they want one, that's what the Archer class handles). Set
# explicitly below so the reverse-comprehension can't silently flip
# it depending on WEAPON_CLASS's key order.
CLASS_STARTING_WEAPON = {
    cls: weapon
    for weapon, classes in WEAPON_CLASS.items()
    for cls in classes
}
CLASS_STARTING_WEAPON["Scout"] = "dagger"


def grant_starting_weapon(soulbound: dict, granted_classes: list) -> str | None:
    """
    Adds the class-appropriate starting weapon(s) to
    soulbound["inventory"] when a trial's class(es) are confirmed.
    Looks each granted class up in CLASS_STARTING_WEAPON — e.g. Bow
    trial grants Archer + Scout, which resolves to bow AND dagger,
    even though the player only fired arrows in the trial itself, per
    design: Scout is always a dagger user, Archer is always a bow
    user, regardless of which single trial unlocked both at once.

    Returns the list of weapon(s) actually added (for the
    confirmation message) — empty if none applied (e.g. Mage, which
    isn't in CLASS_STARTING_WEAPON at all).

    Does not auto-equip — see .equip. A freshly granted weapon sits
    in .inv until the player equips it themselves.
    """
    soulbound.setdefault("inventory", [])
    added = []
    for cls in granted_classes:
        weapon = CLASS_STARTING_WEAPON.get(cls)
        if weapon and weapon not in soulbound["inventory"]:
            soulbound["inventory"].append(weapon)
            added.append(weapon)
    return added

# Named opponent per weapon — every weapon trial fights a real,
# specific person, not an interchangeable dummy. Same flat stats
# across the board for now (entry-trial difficulty, not personality-
# tuned yet — a later pass could vary these per opponent). These are
# also legitimate NPCs the narrator should introduce/persist via
# rpg_engine.py's new_npcs mechanism when a trial starts — the name
# here is what the mechanical fight math uses; the narrator is free
# to describe them however it likes as long as it uses this name.
_FLAT_OPPONENT_STATS = {
    "STR": 10, "DEX": 10, "SPD": 10,
    "DEF": 10, "INT": 10, "WIS": 10, "CHA": 10,
}

WARRIOR_OPPONENTS = {
    "sword":  {"name": "Ethan",   "stats": dict(_FLAT_OPPONENT_STATS)},
    "dagger": {"name": "Ricardo", "stats": dict(_FLAT_OPPONENT_STATS)},
    "spear":  {"name": "Tron",    "stats": dict(_FLAT_OPPONENT_STATS)},
    "axe":    {"name": "Grath",   "stats": dict(_FLAT_OPPONENT_STATS)},
    "mace":   {"name": "Beorn",   "stats": dict(_FLAT_OPPONENT_STATS)},
    "shield": {"name": "Petra",   "stats": dict(_FLAT_OPPONENT_STATS)},
    "bow":    {"name": "Yumi",    "stats": dict(_FLAT_OPPONENT_STATS)},
}

# Win = opponent HP at or below this fraction of their max.
WIN_HP_FRACTION = 0.15

# Directional weighting used ONLY when the player calls a block
# vaguely (e.g. "block the attack") instead of naming a side — this
# is a DIRECTION roll (which side the incoming swing is treated as
# having come from), not a success/fail table. Once a direction is
# settled — whether picked by the player or rolled here — success
# still goes through the real block_chance contest below. Numbers
# don't need to sum to 100; anything not covered is a clean miss.
SHIELD_VAGUE_DIRECTION_WEIGHTS = {
    "front": 0.30,
    "left":  0.20,
    "right": 0.20,
    "behind": 0.05,
    "below": 0.01,
    "above": 0.10,
}

SHIELD_DIRECTIONS = ("front", "left", "right", "behind", "above", "below")

SHIELD_HITS_TO_WIN = 10
SHIELD_HITS_TO_LOSE = 3

BOW_HITS_TO_WIN = 10

# Rough synonym map so "above"/"overhead", "below"/"underneath" etc
# match the same way vague-vs-specific block direction parsing does.
_DIRECTION_SYNONYMS = {
    "front": {"front", "ahead", "forward"},
    "left":  {"left"},
    "right": {"right"},
    "behind": {"behind", "back", "rear"},
    "above": {"above", "overhead", "up", "top"},
    "below": {"below", "underneath", "under", "down", "low"},
}


def _opponent_max_hp(weapon: str) -> float:
    return compute_self_secondary("hp", WARRIOR_OPPONENTS[weapon]["stats"])


def _weighted_random_direction() -> str:
    directions = list(SHIELD_VAGUE_DIRECTION_WEIGHTS.keys())
    weights = list(SHIELD_VAGUE_DIRECTION_WEIGHTS.values())
    return random.choices(directions, weights=weights, k=1)[0]


def parse_block_direction(text: str) -> str | None:
    """
    Returns the direction word the player specifically named, or
    None if the text is vague/unrecognized (falls back to the
    weighted roll instead). Deliberately simple substring matching
    against _DIRECTION_SYNONYMS — good enough for free-text .rpg
    replies without needing full NLP.
    """
    low = text.lower()
    for canonical, synonyms in _DIRECTION_SYNONYMS.items():
        if any(word in low for word in synonyms):
            return canonical
    return None


def resolve_shield_block(reply_text: str, incoming_direction: str, player_stats: dict) -> dict:
    """
    One block attempt in the Shieldbearer trial.

    incoming_direction is the direction ALREADY narrated to the
    player this turn (rolled once, up front, by the caller via
    _weighted_random_direction() — see rpg.py's shielding phase) —
    this is the actual attack, not a second independent roll. It is
    always authoritative regardless of what the player replies with.

    - If the player names that SAME direction (or any direction —
      naming the WRONG one is simply a wrong guess, see below), the
      call is "specific."
    - If the call is vague (no direction named at all), the player
      is just declining to guess, and incoming_direction resolves
      the block on its own — matching by default, since there's
      nothing for the player's reply to conflict with.
    - Naming a direction that does NOT match incoming_direction is a
      wrong call — the player blocked the wrong side, so it's an
      automatic miss regardless of stats (you can't block a hit
      you're not even facing).
    - A block attempt that DOES match incoming_direction (named
      correctly, or vague/default) still has to clear a real
      contested roll to succeed: block_chance (defender/player) vs
      physical_attack (attacker/opponent), via
      secondary_stats.resolve_contested — same formula used
      everywhere else blocking matters in this game, not a
      trial-only special case.

    Returns {"direction": str, "was_specific": bool, "matched": bool,
    "blocked": bool, "block_chance": float} so the caller can narrate
    exactly what happened — "matched" distinguishes an automatic
    wrong-side miss from a stats-based miss on a correctly-called
    block.
    """
    specific = parse_block_direction(reply_text)
    matched = specific is None or specific == incoming_direction

    if not matched:
        return {
            "direction": incoming_direction,
            "was_specific": True,
            "matched": False,
            "blocked": False,
            "block_chance": 0.0,
        }

    chance = resolve_contested(
        "block_chance",
        defender_primaries=player_stats,
        attacker_primaries=WARRIOR_OPPONENTS["shield"]["stats"],
    )
    blocked = random.uniform(0, 100) < chance

    return {
        "direction": incoming_direction,
        "was_specific": specific is not None,
        "matched": True,
        "blocked": blocked,
        "block_chance": chance,
    }


# ── Bow trial data ────────────────────────────────────────────────

# Each shot is a fresh set of conditions the narrator states aloud;
# `correct_aim` is the phrase fragment a specific reply must contain
# to count as correctly compensating. Kept as simple keyword checks
# (same spirit as _DIRECTION_SYNONYMS above) rather than full NLP —
# consistent with how block-direction matching already works.
BOW_SHOT_CONDITIONS = [
    {
        "description": "The target is 30 paces off, drifting left, with a light crosswind from the east.",
        "correct_aim": {"left"},
    },
    {
        "description": "The target holds still at 20 paces, but a stiff wind blows in from the west.",
        "correct_aim": {"right"},
    },
    {
        "description": "The target creeps right at a crawl, no wind to speak of.",
        "correct_aim": {"right"},
    },
    {
        "description": "The target is close, just 10 paces, ducking low behind a barrel.",
        "correct_aim": {"low", "down", "under"},
    },
    {
        "description": "The target is far, near 50 paces, rising onto a raised platform.",
        "correct_aim": {"high", "up", "above"},
    },
]


def roll_bow_shot() -> dict:
    """Picks one random shot condition for the next arrow."""
    shot = dict(random.choice(BOW_SHOT_CONDITIONS))
    # Stored in session.flags, which is saved with json.dumps: a set is not
    # JSON-serializable (the bow trial used to crash on start). Keep it as a
    # sorted list here; resolve_bow_shot turns it back into a set to compare.
    shot["correct_aim"] = sorted(shot["correct_aim"])
    return shot


def resolve_bow_shot(reply_text: str, shot: dict) -> dict:
    """
    One shot attempt in the Archer/Scout trial.

    - Specific aim (reply contains a keyword matching shot's
      correct_aim set) -> guaranteed hit.
    - Specific aim that names a compensation but gets it WRONG
      (matches a different shot's keyword set, or a recognized
      direction word that isn't in this shot's correct set) -> miss.
    - Vague aim (no recognizable direction/compensation word at all)
      -> falls back to the same weighted-odds spirit as a vague
      shield block: a direction is rolled via
      _weighted_random_direction() and counted as a hit only if it
      happens to land in the shot's correct_aim set.

    No partial credit either way — binary hit/miss, matching the
    shield trial's resolution style.

    Returns {"hit": bool, "was_specific": bool}.
    """
    low = reply_text.lower()
    named = {word for word in
             {"left", "right", "up", "down", "high", "low", "above",
              "below", "under", "over"}
             if word in low}

    if named:
        hit = bool(named & set(shot["correct_aim"]))
        return {"hit": hit, "was_specific": True}

    rolled = _weighted_random_direction()
    # Map the 6-way block-style roll onto a hit/miss against this
    # shot's correct_aim set — same "outsourced to chance" spirit as
    # a vague shield block.
    rolled_words = _DIRECTION_SYNONYMS.get(rolled, {rolled})
    hit = bool(rolled_words & set(shot["correct_aim"]))
    return {"hit": hit, "was_specific": False}


def record_weapon_cleared(soulbound: dict, weapon: str) -> tuple:
    """
    Marks `weapon` cleared on soulbound["cleared_weapons"] (idempotent
    — safe to call again on a weapon already cleared) and returns the
    class(es) just granted for THIS weapon, per WEAPON_CLASS, PLUS
    ("Warrior", "Weapon Master") appended if this clear was the 7th
    and final weapon — the "clear all seven" bonus. Caller folds the
    returned tuple into pending_class/pending_class_extra same as any
    other grant; no separate code path needed for the all-weapons
    case.
    """
    soulbound.setdefault("cleared_weapons", [])
    if weapon not in soulbound["cleared_weapons"]:
        soulbound["cleared_weapons"].append(weapon)

    gained = list(WEAPON_CLASS[weapon])
    if set(soulbound["cleared_weapons"]) >= set(WARRIOR_WEAPONS):
        if "Warrior" not in gained:
            gained.append("Warrior")
        # Weapon Master is a skill, not a class — caller should also
        # add it to soulbound["skills"] when granting; flagged via
        # the sentinel below rather than silently mixing skill names
        # into the class list.
        gained.append("__skill__Weapon Master")
    return tuple(gained)


def resolve_fight_exchange(player_stats: dict) -> dict:
    """
    One exchange in a direct-fight weapon trial (sword/dagger/spear/
    axe/mace). Player's physical_attack lands on the opponent's
    physical_defense-scaled HP pool each call — caller is
    responsible for tracking remaining opponent HP across calls in
    session.flags["trial"]["opponent_hp"] and checking it against
    WIN_HP_FRACTION * _opponent_max_hp().

    Returns {"damage": float} — a straightforward attack roll using
    the player's real physical_attack secondary, no separate formula
    invented for this trial.
    """
    attack = compute_self_secondary("physical_attack", player_stats)
    # Light randomness so identical stats don't produce identical
    # damage every exchange — +/-15% spread around the raw attack
    # value.
    damage = attack * random.uniform(0.85, 1.15)
    return {"damage": damage}


# ── Mage trial data ──────────────────────────────────────────────

# Each entry is a 3-5 line incantation. Picked at random per
# attempt (not fixed per player) — see module docstring, "not
# fixed, but quite long."
INCANTATIONS = [
    (
        "Mana o' mana, hear my call,\n"
        "Rise from the well where the old lights fall,\n"
        "Bend to my will, however small,\n"
        "Mana o' mana, answer all."
    ),
    (
        "Spark and ember, wind and stone,\n"
        "None of the four are mine alone,\n"
        "Lend me the thread, I'll give it back,\n"
        "Mana o' mana, along this track."
    ),
    (
        "By the well no eye has seen,\n"
        "By the space between what is and been,\n"
        "I ask, not take — mana o' mana,\n"
        "Come to a hand that's asking clean."
    ),
]

# 9-15s inclusive, per the exact range specified.
MIN_DELETE_SECONDS = 9
MAX_DELETE_SECONDS = 15

REST_SUGGESTION_EVERY = 5  # elder suggests resting every 5th attempt


def _normalize_incantation(text: str) -> str:
    """
    Strips everything except letters/numbers/spaces, collapses
    whitespace, lowercases — so "Mana o' mana..." and "mana o mana"
    and "MANA O MANA" all normalize identically, per the exact
    stated rule: punctuation and spacing don't matter, but actual
    wrong words (including typos) do.
    """
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def incantation_matches(shown: str, recast: str) -> bool:
    return _normalize_incantation(shown) == _normalize_incantation(recast)


def start_mage_incantation() -> dict:
    """
    Picks a random incantation and a random 9-15s delete window.
    Returns the trial-state dict to store at
    session.flags["trial"]["incantation_data"] — shown_at/delete_at
    are unix timestamps so the check survives the stateless
    request/response cycle (see module docstring — no blocking
    sleep, the actual delete+prompt fires via a threading.Timer
    armed by the router, same pattern router/explore.py's
    _arm_arrival_timer already uses).
    """
    incantation = random.choice(INCANTATIONS)
    now = time.time()
    delete_delay = random.randint(MIN_DELETE_SECONDS, MAX_DELETE_SECONDS)
    return {
        "incantation": incantation,
        "shown_at": now,
        "delete_at": now + delete_delay,
        "delete_fired": False,  # set True once the timer's auto-delete
                                 # message has actually been sent, so a
                                 # late-arriving early-pass check doesn't
                                 # double-fire it
    }


# ── Summoner trial data (Phase 1 — pet picking) ─────────────────
# Phase 1 only. Phase 2 (affinity-building) and Phase 3 (sealing) are
# NOT built yet — deliberately scoped out, see project notes. This
# block only covers: species list -> species sub-list -> per-player
# trait roll on a chosen slot -> commit via ".rpg <species> <no.>".
#
# Design constraints, from the actual discussion these mechanics were
# specified in:
#   - 9 species, each with a FIXED, hardcoded sub-list of 10 pets
#     (SUMMONER_BLURBS below) — same blurb text shown to every
#     player, never generated at runtime.
#   - What's NOT hardcoded is trait data: the moment a player opens a
#     species' sub-list, each of that species' 10 slots gets a FRESH
#     trait roll FOR THAT PLAYER (see roll_summoner_pet below). Two
#     different players opening "cats" see identical blurbs, but
#     slot 3's real trait data can differ between them.
#   - Each pet has exactly 3 traits: 1 drawn from that species'
#     subset (SUMMONER_SPECIES_TRAITS) + 2 drawn fully at random from
#     the full 50-trait bank (SUMMONER_TRAIT_BANK). The species trait
#     can NEVER be dominant — dominance is a random pick between the
#     2 fully-random traits only; the other random trait + the
#     species trait are both secondary.
#   - Rolled trait data persists per-player only through Phase 1
#     browsing and (once built) Phase 2 — discarded/rerollable once
#     Phase 2 resolves. Storage mechanism for that persistence is
#     intentionally NOT decided here — this module just rolls the
#     data; the caller (router/rpg.py, same pattern as the Warrior/
#     Mage trial dict already stored at session.flags["trial"])
#     decides where it lives.

# Every playable species, in canonical order. Also doubles as the
# valid-species check for ".rpg <species> <no.>" parsing.
SUMMONER_SPECIES = [
    "cat", "dog", "bird", "salamander", "sheep",
    "rodent", "rabbit", "fox", "ferret",
]

# The full 50-trait personality bank. Every trait here has an
# implied reward/penalize behavior (not yet formalized into code —
# see project notes "full speed-category tagging" and "repetition-
# fatigue" as still-open items); this list exists right now purely
# as the pool roll_summoner_pet() draws from.
SUMMONER_TRAIT_BANK = [
    "Excitable", "Skittish", "Aloof", "Stubborn", "Anxious",
    "Territorial", "Playful/Mischievous", "Prideful", "Clingy",
    "Grumpy/Standoffish", "Curious", "Protective", "Skeptical",
    "Energetic", "Lazy/Docile", "Vain", "Melancholic", "Competitive",
    "Nurturing", "Impulsive", "Loyal-but-jealous", "Perceptive",
    "Cowardly", "Obstinate-but-fair", "Bashful", "Boisterous",
    "Possessive", "Forgetful", "Sentimental", "Restless",
    "Gentle giant", "Scrappy", "Watchful", "Naive", "Calculating",
    "Homesick/Displaced", "Show-off", "Contrarian",
    "Devoted-once-earned", "Finicky", "Brave/Reckless", "Wistful",
    "Copycat", "Guarded", "Affectionate-but-fickle", "Analytical",
    "Old soul", "Feral edge", "People-pleaser", "Independent",
]

# Species -> subset of SUMMONER_TRAIT_BANK its species-linked trait
# is drawn from. This trait can NEVER be dominant on any pet of that
# species — see roll_summoner_pet()'s dominance rule.
SUMMONER_SPECIES_TRAITS = {
    "cat":        ["Aloof", "Independent", "Curious", "Vain", "Watchful", "Territorial", "Guarded"],
    "dog":        ["Loyal-but-jealous", "Devoted-once-earned", "Boisterous", "Protective", "Playful/Mischievous", "People-pleaser", "Energetic"],
    "bird":       ["Skittish", "Restless", "Show-off", "Perceptive", "Vain", "Excitable", "Watchful"],
    "salamander": ["Old soul", "Lazy/Docile", "Guarded", "Melancholic", "Homesick/Displaced", "Watchful"],
    "sheep":      ["Anxious", "Bashful", "Copycat", "People-pleaser", "Skittish", "Clingy", "Gentle giant"],
    "rodent":     ["Excitable", "Forgetful", "Restless", "Skittish", "Sentimental", "Impulsive", "Naive"],
    "rabbit":     ["Anxious", "Skittish", "Bashful", "Gentle giant", "Cowardly", "Clingy", "Affectionate-but-fickle"],
    "fox":        ["Contrarian", "Calculating", "Scrappy", "Feral edge", "Independent", "Playful/Mischievous", "Guarded"],
    "ferret":     ["Feral edge", "Impulsive", "Playful/Mischievous", "Boisterous", "Restless", "Contrarian", "Naive"],
}

# Fixed, hardcoded blurb text — 10 per species, same wording shown
# to every player regardless of what traits they roll for that slot.
# Written to plain/everyday visual language only (no breed/color
# jargon) with a behavior beat that MAY suggest a trait, but is not
# required to match whatever actually rolls dominant for a given
# player — pure flavor, mismatch is expected and fine.
SUMMONER_BLURBS = {
    "cat": [
        "Grey cat with bold black stripes and gold eyes, fur slightly ruffled at the neck. Tail flicks lazily against a wooden crate, catching the light. Doesn't look up when you approach.",
        "Fluffy white cat, fur soft and a little wild at the edges, one eye blue and one eye green. Curled into a tight ball in a warm patch of sunlight, breathing slow and even.",
        "Black and white cat with a torn left ear and a white streak down its nose. Perched on the highest shelf in the shop, tail wrapped neatly around its paws, watching the door.",
        "Chunky orange cat, fur puffed out like it's been rolling in hay. Flopped completely on its back in the middle of the walkway, paws in the air, snoring loud enough to hear from the counter.",
        "Sleek brown cat with pale, almost silvery blue eyes and dark ears, paws, and tail tip. Sits bolt upright and still, only its ears moving, twitching toward every creak and footstep.",
        "Cat with uneven patches of brown, black, and cream fur, batting a loose thread hanging off the wire of its pen, over and over, completely absorbed.",
        "Small, dark grey kitten with oversized paws it hasn't grown into yet. Mid-pounce on nothing in particular, tumbles sideways over its own tail, gets right back up.",
        "Silver-grey cat, coat a little dull and patchy in places, one whisker bent at an odd angle. Tucked into the darkest, farthest corner of the shop, barely visible.",
        "Pale cream cat with striking mismatched eyes — one amber, one pale grey — and a thin scar above the left one. Sits perfectly still, staring at a fixed point on the wall.",
        "Bright orange, black, and white patchy cat with a small kink near the tip of its tail. Paces in slow, tight circles around its pen, murmuring soft meows at nothing.",
    ],
    "dog": [
        "Brown dog with floppy ears and a white patch on its chest. Sits close by the gate, watching every person who walks past.",
        "Black dog with a short, thick coat and one white paw. Sprawled across the doorway, blocking it, tail thumping slowly.",
        "Golden-furred dog with a long snout and bright amber eyes. Paces back and forth along the same short stretch of fence, over and over.",
        "Small white dog with brown spots and short legs. Barks once at everyone who enters, then goes quiet and stares.",
        "Grey dog with a thick, shaggy coat and a scar across its nose. Lies with its head on its paws, eyes tracking movement without lifting its head.",
        "Tan dog with long legs and a narrow face. Bounces on its front paws whenever someone gets close, tail a blur.",
        "Black and brown dog with a torn ear and rough fur. Sits slightly apart from the others, chewing on nothing.",
        "Cream-colored dog with a round face and short fur. Leans its full weight against the bars, eyes half-closed.",
        "Reddish-brown dog with a bushy tail and pointed ears. Freezes mid-motion the second anyone speaks, ears swiveling toward the sound.",
        "White dog with grey patches and a slightly crooked tail. Circles the same spot again and again before finally sitting.",
    ],
    "bird": [
        "Small blue bird with a sharp yellow beak. Hops from perch to perch without ever landing for long.",
        "Grey bird with black-tipped wings. Sits completely still on the highest branch, watching the door.",
        "Bright red bird with a short tail. Flutters against the cage wire, over and over, at nothing in particular.",
        "Brown speckled bird with a round body. Tucks its head under one wing, motionless.",
        "White bird with a black stripe across each eye. Tilts its head sharply at every new sound, feathers puffed.",
        "Green bird with a curved beak. Chews steadily on a twig, dropping the pieces one by one.",
        "Yellow bird with black wingtips. Sings the same short phrase, again and again, without pause.",
        "Dark grey bird with a long tail. Perches low, close to the ground, refusing to move higher.",
        "Orange-chested bird with a stubby beak. Puffs up twice its size whenever a hand comes near the cage.",
        "Black bird with a faint blue sheen on its feathers. Watches its own reflection in a small mirror, unmoving.",
    ],
    "salamander": [
        "Dark green salamander with orange spots down its back. Sits half-submerged in a shallow dish, barely moving.",
        "Pale yellow salamander with black speckles. Presses itself flat against the coolest corner of the tank.",
        "Deep blue-black salamander with smooth, damp-looking skin. Stays completely still for long stretches, then moves all at once.",
        "Brown salamander with a wide, flat head. Burrows halfway under a piece of bark, only its tail visible.",
        "Orange salamander with dark bands across its back. Climbs slowly up the glass, one careful step at a time.",
        "Grey salamander with a pale underbelly. Floats motionless at the water's surface, eyes just above the line.",
        "Black salamander with tiny yellow flecks. Curls into a loose spiral in the corner, unresponsive to tapping.",
        "Rust-colored salamander with a thick tail. Digs steadily at the same spot in the substrate.",
        "Mottled green-brown salamander, hard to spot against the tank's rocks. Doesn't move at all unless directly touched.",
        "Pale pink-grey salamander with dark eyes. Follows the movement of anything passing the glass, head turning slowly.",
    ],
    "sheep": [
        "White sheep with a black face and thick, curled wool. Stands pressed against the pen wall, close to the others.",
        "Grey sheep with short wool and dark legs. Chews slowly, watching the door without lifting its head.",
        "Cream sheep with a slightly matted coat. Bolts to the back of the pen the moment the gate creaks.",
        "Black-faced sheep with pale wool. Leans its head against the fence rail, eyes half-shut.",
        "Brown-spotted sheep with short legs. Follows right behind whichever sheep moves first, never leading.",
        "White sheep with unusually long wool covering its eyes. Bumps gently into the fence, seemingly unbothered.",
        "Grey-and-white sheep with a stocky build. Stomps one front hoof repeatedly when anyone gets close.",
        "Pale tan sheep with a short tail. Stands slightly apart from the group, facing the wall.",
        "Black sheep with a white patch on its forehead. Nudges at the gate latch again and again with its nose.",
        "Thick-wooled white sheep, wool bunched heavily at the shoulders. Lies down the moment it's left alone, gets up the moment someone approaches.",
    ],
    "rodent": [
        "Small grey rodent with round ears. Darts from one corner of the cage to the other, never stopping in the open.",
        "Brown rodent with a white belly. Stuffs bits of bedding into its cheeks, over and over, well past what it could need.",
        "Black rodent with tiny paws. Freezes completely the moment the cage is touched, only its nose twitching.",
        "Tan rodent with a short tail. Climbs the bars methodically, corner to corner, without pause.",
        "White rodent with pink-tinged ears. Digs a shallow hole, abandons it, starts a new one nearby.",
        "Grey-brown rodent with a long tail. Sits up on its hind legs at every small sound, then drops back down.",
        "Spotted rodent, brown and white patches. Hoards bits of food in one pile, then moves the whole pile somewhere else.",
        "Small black rodent with a stubby tail. Runs in place against the wheel without actually stepping on properly.",
        "Golden-brown rodent with a rounder body. Grooms the same patch of fur repeatedly, longer than seems needed.",
        "Pale grey rodent with dark eyes. Squeezes into the smallest gap in the cage decor and stays there.",
    ],
    "rabbit": [
        "White rabbit with long ears, one tip folded slightly. Freezes mid-hop the instant anyone speaks.",
        "Brown rabbit with a short, fluffy tail. Thumps one back foot hard against the floor, again and again.",
        "Grey rabbit with darker ears. Presses itself into the very back corner of the pen, unmoving.",
        "Black-and-white rabbit with a round face. Hops toward the front of the pen, then immediately retreats.",
        "Tan rabbit with long fur along its back. Grooms the same spot on its own leg repeatedly.",
        "Pale grey rabbit with pink-tinged ears. Stays completely still except for a constantly twitching nose.",
        "Brown-spotted rabbit with short ears. Digs briefly at the pen floor, then stops and stares at nothing.",
        "White rabbit with a single black ear. Nudges at the water bottle, retreats, comes back to nudge it again.",
        "Reddish-brown rabbit with a stocky build. Sits low to the ground, ears flat against its back.",
        "Cream rabbit with darker patches near the eyes. Bolts sideways at the smallest movement outside the pen.",
    ],
    "fox": [
        "Reddish-orange fox with a white-tipped tail. Watches you closely, ears forward, without moving an inch.",
        "Grey fox with black-tipped ears. Paws at the latch of its enclosure, testing it every few minutes.",
        "Pale orange fox with a dark stripe down its back. Lies low, chin on its paws, eyes tracking everything.",
        "Reddish fox with unusually large ears. Circles the edge of its pen in the same tight loop, again and again.",
        "Grey-brown fox with a bushy tail. Sits perfectly still until you look away, then moves closer.",
        "Dark red fox with black legs and a white chest. Digs briefly at one spot, glances up, keeps digging.",
        "Silver-grey fox with amber eyes. Tilts its head at every word spoken nearby, unblinking.",
        "Orange fox with a notably long, thick tail. Rubs against the enclosure wall, back and forth, unbothered by an audience.",
        "Pale fox with darker legs and muzzle. Stays just out of arm's reach no matter where you stand.",
        "Reddish fox with a scar across one ear. Growls low once, then goes completely silent and still.",
    ],
    "ferret": [
        "Brown ferret with a cream underbelly. Squeezes into the smallest gap in its enclosure and stays wedged there.",
        "Black-masked ferret with white paws. Steals a small object, hides it, comes back for another.",
        "Pale cream ferret with dark eyes. Bounces sideways at the glass the moment anyone approaches, then retreats.",
        "Dark brown ferret with a long, thin body. Weaves rapidly between two spots in the enclosure, never resting between.",
        "Grey ferret with a black-tipped tail. Digs at the same corner, stops, immediately starts digging again elsewhere.",
        "Cream-and-brown patterned ferret. Climbs directly up the enclosure wall, drops, climbs again.",
        "Black ferret with a white throat patch. Stays coiled in a tight ball, one eye cracked open.",
        "Light brown ferret with a stub-like tail. Chews at the enclosure bars steadily, without pause.",
        "Silver-grey ferret with dark legs. Darts behind an object the second it's touched, peeks back out seconds later.",
        "Deep brown ferret with a lighter face. Pulls bedding into a pile, flattens it, pulls it apart again.",
    ],
}


# Species -> plural display label for the sub-list header. Hand-
# authored rather than generated (e.g. naive "+s" breaks on "fox" ->
# "foxs" instead of "foxes") — same "hardcode it, don't derive it
# cleverly" spirit as the rest of this trial's fixed content.
SUMMONER_SPECIES_LABEL = {
    "cat": "Cats", "dog": "Dogs", "bird": "Birds",
    "salamander": "Salamanders", "sheep": "Sheep", "rodent": "Rodents",
    "rabbit": "Rabbits", "fox": "Foxes", "ferret": "Ferrets",
}


def render_species_list_payload() -> dict:
    """
    Builds the structured payload for the Phase 1 species picker as a
    native WhatsApp list message (tap-to-select bottom sheet), per the
    design doc's LOCKED presentation flow. 9 species fits comfortably
    under WhatsApp's 10-row-total cap, so no pagination/shelving is
    needed at this roster size (see the technical note in the design
    doc — this is a WhatsApp-wide limit, not something we control).

    Returns {"title", "description", "button_text", "rows": [...]}.
    Each row's "id" is a plain lowercase species key that comes back
    verbatim as the tap-reply text (WhatsApp list taps resolve to the
    row's title text in a normal incoming message, same as any other
    text reply) — so the existing ".rpg <species>" bare-name handling
    in router/rpg.py needs no changes to accept it; a tap on "Cat"
    arrives exactly like a player typing "cat".

    The caller (router/rpg.py) is responsible for turning this into
    the marker string index.js's sendAny() looks for — this function
    only builds the data, not the wire format, matching the existing
    split between townia_trials.py (data) and the router (transport).
    """
    return {
        "title": "🐾 The Pet Shop",
        "description": "Pick a species to see what's on offer.",
        "button_text": "Browse",
        "rows": [
            {"id": species, "title": SUMMONER_SPECIES_LABEL[species]}
            for species in SUMMONER_SPECIES
        ],
    }


def render_species_sublist(species: str) -> str:
    """
    Builds the plain-text sub-list message for one species — intro,
    "Reply with" line, a forced WhatsApp "Read more" collapse
    (stacked invisible-character blank lines), the 10 numbered
    blurbs, then the "Reply with" line again at the bottom. Matches
    the exact format locked in the project's design discussion.
    Raises KeyError if `species` isn't a real entry — callers should
    validate against SUMMONER_SPECIES first (see SUMMONER_SPECIES
    check pattern used by the Warrior trial's weapon validation).
    """
    blurbs = SUMMONER_BLURBS[species]
    label = SUMMONER_SPECIES_LABEL[species]
    reply_line = f"Reply with .rpg {species} <no.> to choose one."
    collapse = "\u200e\n" * 18  # invisible-char blank lines -> forces WhatsApp's "Read more"
    numbered = "\n\n".join(f"{i+1}. {text}" for i, text in enumerate(blurbs))
    return (
        f"🐾 {label} — 10 available\n"
        f"{reply_line}\n"
        f"{collapse}"
        f"{numbered}\n\n"
        f"{reply_line}"
    )


def roll_summoner_pet(species: str) -> dict:
    """
    Rolls fresh trait data for ONE pet slot of the given species —
    called once per slot, per player, at sub-list-open time (see
    module docstring — NOT stored on the hardcoded blurb, generated
    fresh every time this is called).

    Returns {"species_trait": str, "random_traits": [str, str],
    "dominant": str, "secondary": [str, str]}.

    Dominance rule (LOCKED): the species-linked trait can NEVER be
    dominant. Dominance is a random pick between the 2 fully-random
    traits only; the other fully-random trait becomes the second
    secondary trait alongside the species one.

    The 2 "fully random" traits are drawn from the bank EXCLUDING
    whichever trait was already picked as species_trait — a species
    subset trait (e.g. Cat's "Curious") is also a member of the full
    50-trait bank, so without this exclusion the random draw could
    coincidentally re-pick the same trait name, collapsing
    species_trait and a "random" trait into one, which could then
    let that trait become dominant — directly violating the rule
    above. Caught by roll_summoner_pet's own test suite, not assumed
    safe by construction.
    """
    species_trait = random.choice(SUMMONER_SPECIES_TRAITS[species])
    trait_pool = [t for t in SUMMONER_TRAIT_BANK if t != species_trait]
    random_traits = random.sample(trait_pool, 2)
    dominant = random.choice(random_traits)
    other_random = random_traits[0] if random_traits[1] == dominant else random_traits[1]
    return {
        "species_trait": species_trait,
        "random_traits": random_traits,
        "dominant": dominant,
        "secondary": [species_trait, other_random],
    }


def roll_summoner_sublist(species: str) -> list:
    """
    Rolls trait data for all 10 slots of one species in one call —
    what the router should call the first time a player opens a
    given species' sub-list this session. Returns a list of 10
    dicts, each shaped like roll_summoner_pet()'s return value, in
    slot order (index 0 == blurb 1, etc.).
    """
    return [roll_summoner_pet(species) for _ in range(10)]
