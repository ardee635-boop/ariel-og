"""Ariel: loadout (split from soulbound.py)."""
import random


# ─────────────────────────────────────────────────────────────
# Per-body-part LOADOUT system — replaces the earlier flat
# monster_equipment dict ({item_name: condition}, no location
# concept). Built from a live design discussion:
#
#   "wouldn't it be better to invent the gear on a particular body
#   part instead? [flat-item] would constrict to one weapon, mine
#   would be universal. It's even useful in battle — some attacks
#   are easier to dodge on the left flank if the gear is on your
#   left."
#
# This fixes TWO problems the flat version had at once:
#   1. A monster's attack-skill choice was a pure random.choice()
#      over its ENTIRE Open5e skill list every turn, with no concept
#      of "which weapon is it currently holding" — so a single fight
#      could see a monster narrated as switching hammer/spear/axe
#      turn to turn with zero continuity. Pinning each weapon-skill
#      to a SLOT, assigned ONCE at combatant-build time (see
#      build_loadout below), means the skill pool available each
#      turn is whatever's still equipped in that slot, not the raw
#      full list.
#   2. Disarming "the weapon" couldn't precisely suppress the right
#      skill without guessing keywords against skill names (the old
#      _item_role classifier) — now the slot IS the mapping: break
#      left_hand, and only the skill assigned to left_hand goes
#      away. No guessing.
#
# Slots: left_hand, right_hand (weapons — a monster/player can dual-
# wield or have an off-hand item), head, chest, legs (armor). Chosen
# specifically because left/right are split separately (per
# direction) — this is what makes the flank mechanic possible at
# all: an attack described as targeting a specific side can read
# that side's slot condition for a bonus/penalty, something a flat
# item-name dict had no way to represent (no side either way).
#
# Natural attacks (bite, claw, slam, tail whip, etc — no real
# wielded item) get NO slot at all and remain always-available
# regardless of loadout state, same as before (a monster's teeth
# don't "break" the way a weapon does within this system's scope).
# ─────────────────────────────────────────────────────────────

WEAPON_WORDS = ("bow", "sword", "scimitar", "blade", "dagger", "axe", "spear",
                 "mace", "club", "staff", "wand", "hammer", "flail", "whip",
                 "shortbow", "longbow", "crossbow", "javelin", "shortsword",
                 "trident", "rapier", "pike", "lance", "sickle")

ARMOR_WORDS = ("armor", "armour", "helmet", "helm", "gauntlet", "gauntlets",
                "shield", "greaves", "boots", "chestplate", "chest plate",
                "plate", "mail", "pauldron", "bracer", "bracers")

NATURAL_WORDS = ("bite", "claw", "claws", "fang", "fangs", "sting", "gore",
                   "slam", "tail", "talon", "talons", "horn", "horns",
                   "pincer", "pincers", "tentacle", "beak")

WEAPON_SLOTS = ("left_hand", "right_hand")

ARMOR_SLOTS = ("head", "chest", "legs")

def _skill_role(skill: dict) -> str:
    """
    Classifies a skill dict as 'weapon', 'armor', 'natural', or
    'unknown'. Checks the explicit "is_weapon_item" flag FIRST —
    rpg_sim.py's WEAPON_TABLES (SWORD_SKILLS/DAGGER_SKILLS/etc) tags
    every entry with this at table-definition time, since their
    flavor names ("Riposte", "Quick Cut", "Flurry") don't reliably
    contain a literal weapon-type keyword the way item names like
    "chest armor" or "shortbow" do (verified: keyword-only matching
    caught just 4/20 player skills correctly before this flag was
    added — structural tagging by table membership is always
    correct, keyword-guessing a stylized skill name often isn't).
    Falls back to keyword matching against skill["name"] for
    anything WITHOUT that flag (Open5e monster skills, which have no
    equivalent structural tag — a monster's attack list isn't
    grouped by "weapon type" the way rpg_sim's tables are, so keyword
    matching against real Open5e attack names like "Greataxe"/
    "Javelin"/"Bite" is the best available signal there).
    Deliberately conservative on the keyword path (curated-list
    match; unmatched falls to 'unknown' and is left unslotted/
    always-available rather than guessed, since a wrong guess in
    either direction is worse than no effect). 'natural' is checked
    explicitly (bite/claw/etc) so those don't accidentally match a
    weapon/armor word and get wrongly slotted — a monster's "Bite"
    attack should never be disarmable.
    """
    if skill.get("is_weapon_item"):
        return "weapon"
    lowered = str(skill.get("name", "")).lower()
    if any(w in lowered for w in NATURAL_WORDS):
        return "natural"
    if any(w in lowered for w in WEAPON_WORDS):
        return "weapon"
    if any(w in lowered for w in ARMOR_WORDS):
        return "armor"
    return "unknown"

def build_loadout(skills: list[dict], seed_random=None, single_weapon_group: bool = False,
                   weapon_display_name: str | None = None) -> dict:
    """
    Called ONCE at combatant-build time (not per-turn) — assigns
    weapon-classified skill(s) to hand slots (left_hand/right_hand),
    and synthesizes a matching armor entry per body slot (head/
    chest/legs) so there's something for the flank/armor-penalty
    mechanics to read even though Open5e data has no armor-as-a-
    skill concept. A slot that would go unfilled (no weapon skill to
    assign, e.g. a monster whose only attacks are natural) is simply
    left empty ({} for that slot) — natural attacks never require a
    slot to remain usable.

    single_weapon_group=True is for rpg_sim.py's PLAYER weapon
    tables specifically (SWORD_SKILLS/DAGGER_SKILLS/etc) — a table
    like SWORD_SKILLS represents ONE physical weapon (a sword) with
    FOUR different techniques (slash/thrust/riposte/sunder) using
    it, not four separate weapons. In this mode ALL weapon-tagged
    skills go into right_hand together as a "skill_keys" LIST (every
    technique lives on the one equipped item, so breaking that one
    slot correctly takes away all of them at once) — left_hand stays
    empty (no off-hand weapon exists for the player yet). This was a
    real bug caught during testing: without this flag, the default
    "one skill per slot, only first 2 fill" behavior below silently
    dropped 2 of the sword's 4 techniques (thrust/sunder) from the
    loadout entirely, since only 2 hand slots exist but 4 skills
    were all tagged as separate weapon items.

    single_weapon_group=False (default) is for MONSTER Open5e skill
    lists, where each skill genuinely CAN represent a different
    physical weapon (a Greataxe attack and a Javelin attack really
    are two different items an orc might carry) — original behavior
    unchanged: if TWO weapon skills exist, they go into left_hand
    and right_hand respectively (dual-wielding). If THREE OR MORE
    exist, only the first two (by list order) get slotted; the rest
    are left unslotted and always-available — deliberate scope
    choice (a monster with many weapon options realistically can't
    lose access to all of them from a single two-handed disarm).

    seed_random lets a caller pass random.Random() for determinism
    in tests; defaults to the shared random module.

    Returns {"left_hand": {"skill_key"|"skill_keys":..,"item":..,
    "condition":"intact"} | {}, "right_hand": {...} | {},
    "head": {...}|{}, "chest": {...}|{}, "legs": {...}|{}}.
    Callers reading a slot's skill(s) should check for BOTH
    "skill_key" (monster mode, one skill) and "skill_keys" (player
    mode, a list) — see loadout_weapon_skill_keys below, which
    already handles both.
    """
    rng = seed_random or random
    weapon_skills = [s for s in skills if _skill_role(s) == "weapon"]

    loadout = {slot: {} for slot in WEAPON_SLOTS + ARMOR_SLOTS}

    if single_weapon_group:
        if weapon_skills:
            loadout["right_hand"] = {
                "skill_keys": [s.get("key") or s.get("name") for s in weapon_skills],
                "item": weapon_display_name or weapon_skills[0].get("name", "weapon"),
                "condition": "intact",
            }
    else:
        rng.shuffle(weapon_skills)
        for slot, skill in zip(WEAPON_SLOTS, weapon_skills[:2]):
            loadout[slot] = {
                "skill_key": skill.get("key") or skill.get("name"),
                "item": skill.get("name", slot),
                "condition": "intact",
            }

    # Synthesize armor per body slot — Open5e attack data carries no
    # armor-as-item concept, so these start as generic placeholders
    # ("head armor"/"chest armor"/"leg armor") rather than left
    # empty, so armor_penalty/flank mechanics always have something
    # real to break during a fight, even for a monster whose Open5e
    # data is 100% natural attacks (a wolf still has fur/hide to
    # protect its flanks conceptually, for this system's purposes).
    for slot in ARMOR_SLOTS:
        loadout[slot] = {"item": f"{slot.replace('_', ' ')} armor", "condition": "intact"}
    return loadout

def loadout_weapon_skill_keys(loadout: dict) -> set[str]:
    """
    Returns the set of skill keys/names currently still usable from
    hand slots — i.e. NOT 'broken'. A 'cracked' weapon stays usable
    (same cracked-but-functional rule as the old flat system), only
    'broken' removes it. Empty slots ({}) contribute nothing.
    Handles BOTH loadout shapes build_loadout can produce: a single
    "skill_key" (monster/default mode, one skill per slot) and a
    "skill_keys" list (player/single_weapon_group mode, all
    techniques sharing one equipped weapon item — see build_loadout's
    single_weapon_group docstring). Skills with NO slot at all
    (natural attacks, or 3rd+ weapon skills beyond the two hand
    slots in monster mode) are NOT covered by this function — the
    caller must separately keep those always-available; this only
    tells you about SLOTTED weapon skills.
    """
    usable = set()
    for slot in WEAPON_SLOTS:
        entry = loadout.get(slot) or {}
        if not entry or entry.get("condition") == "broken":
            continue
        if "skill_keys" in entry:
            usable.update(entry["skill_keys"])
        elif "skill_key" in entry:
            usable.add(entry["skill_key"])
    return usable

def loadout_armor_penalty(loadout: dict, target_slot: str | None = None) -> float:
    """
    Returns a DEF multiplier (1.0 = no penalty) from armor condition.
    If target_slot is given (an attack narrated as targeting a
    specific side — "left flank", "its head", etc — see rpg_sim.py's
    flank-detection in the narrate/order path), only THAT slot's
    condition is read — this is the actual flank mechanic: a broken
    LEFT-side item means an attack aimed at the left is more
    effective, not a global softening. If target_slot is None (no
    specific side named, the common case), falls back to averaging
    across all armor slots — same "some defense lost" behavior the
    old flat system had for an untargeted hit, just now derived from
    slot data instead of a flat per-item multiply.
    Same 0.82/0.93 broken/cracked multipliers and 0.25 floor as the
    old monster_armor_penalty — unchanged tuning, just relocated.
    """
    def _slot_mult(entry: dict) -> float:
        cond = entry.get("condition")
        if cond == "broken":
            return 0.82
        if cond == "cracked":
            return 0.93
        return 1.0

    if target_slot and target_slot in ARMOR_SLOTS:
        return max(0.25, _slot_mult(loadout.get(target_slot) or {}))

    mults = [_slot_mult(loadout.get(slot) or {}) for slot in ARMOR_SLOTS if loadout.get(slot)]
    if not mults:
        return 1.0
    combined = 1.0
    for m in mults:
        combined *= m
    return max(0.25, combined)
