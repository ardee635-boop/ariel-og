"""Ariel: statuses (split from soulbound.py)."""
import random


# ─────────────────────────────────────────────────────────────
# General status-effect system — shared by any caller (rpg_sim.py
# now, rpg_engine.py's real battle system later), not duplicated
# per-caller. Built from a live design discussion:
#
# LAYER 1 — ELIGIBILITY (hard yes/no gate, checked FIRST, before any
# roll): a status can only be caused by an attack that has a real
# causal mechanism for it. A plain sword slash cannot freeze — a
# blade has no physical mechanism to lower temperature — regardless
# of how hard or skillfully it's swung. This is NOT a probability,
# it's a category check on what the attack actually IS:
#   - Elemental statuses (poison/burn/freeze/shock) require the
#     skill's OWN element to match (skill["element"], already
#     populated by isekai_action_to_skill/pokemon_move_to_skill from
#     real source data — Open5e's extra_damage_type for monsters).
#     A goblin bite with element="Poison" is eligible for poison
#     ONLY, nothing else — the gate is data-driven, not guessed.
#   - Bleed is different: it's caused by physical trauma itself
#     (a laceration/puncture), not an element — eligible whenever
#     damage_class == "Physical", independent of element. This is
#     why bleed sits in its own bucket below instead of the
#     elemental map.
#   - A "Normal"-element physical hit (bludgeoning/piercing/slashing
#     — plain sword/claw/bite damage with no special damage type) is
#     eligible for bleed only, nothing elemental — matches the
#     "cut from a blade can't freeze unless special conditions are
#     met" instruction exactly: the special condition IS having a
#     non-Normal element in the first place (an enchanted/frost
#     blade would need its OWN skill data reflecting that, e.g. a
#     player skill explicitly given element="Ice").
#
# LAYER 2 — APPLICATION CHANCE (only rolled if Layer 1 passes):
# chance scales PURELY off how much damage this hit actually dealt,
# relative to the target's max HP — a bigger cut/hit has a higher
# chance to cause bleed/poison/etc, a graze barely any. Skill/action
# type has NO separate influence beyond whatever damage number it
# produced (confirmed in design discussion — damage dealt is the
# only input, not skill category on top of it).
#   chance% = min(ceiling, (damage / target_max_hp) * 100 * multiplier)
# Ceiling stops any single hit from being a guaranteed lock even
# near a kill shot (explicit request: "can't just attack and
# inflict a random status" — deterministic-every-hit would violate
# that just as much as truly random would if there were no ceiling).
# Multiplier is a per-status tuning knob, defaults to 1.0 (same
# curve for all statuses) unless deliberately differentiated later.
# Both numbers are explicit picks, easy to retune — same spirit as
# monster_armor_penalty's 0.82/0.93 and its 0.25 floor.
#
# Resist (secondary_stats.STATUS_RESIST_STATS) is DELIBERATELY left
# untouched by this layer — per the existing, already-documented
# design in secondary_stats.py ("Resist reduces tick damage, not
# chance to be inflicted, duration unaffected"), which this system
# does not reverse. Resist only ever touches Layer 3 tick magnitude.
#
# LAYER 3 — TICKING STATE: once applied, a status persists across
# turns independent of whether either side attacks that turn — the
# caller ticks it once per turn (see apply_status/tick_statuses
# below), each tick's damage reduced by the target's matching
# resist stat, duration counting down regardless of resist.
# ─────────────────────────────────────────────────────────────

# Elemental element -> status it can cause. "Normal" is deliberately
# absent — plain physical damage has no elemental status, only the
# separate bleed bucket below.
_ELEMENT_TO_STATUS = {
    "Fire": "burn",
    "Ice": "freeze",
    "Poison": "poison",
    "Electric": "paralysis",
}

# Per-status tick behavior: how much of the ORIGINAL triggering hit's
# damage each tick deals (before resist), and how many turns it lasts.
# Placeholder curve, explicit/tunable — not balance-tested.
_STATUS_TICK_PROFILE = {
    "bleed":     {"tick_pct_of_hit": 0.25, "duration": 3, "resist_stat": None},
    "poison":    {"tick_pct_of_hit": 0.30, "duration": 3, "resist_stat": "poison_resist"},
    "burn":      {"tick_pct_of_hit": 0.35, "duration": 2, "resist_stat": "burn_resist"},
    "freeze":    {"tick_pct_of_hit": 0.15, "duration": 2, "resist_stat": "freeze_resist"},
    "paralysis": {"tick_pct_of_hit": 0.10, "duration": 2, "resist_stat": "paralysis_resist"},
}

# bleed has resist_stat=None — deliberate: STATUS_RESIST_STATS has no
# "bleed_resist" entry (only burn/poison/freeze/paralysis/etc. exist
# there — see secondary_stats.py), since bleed is a physical-trauma
# effect, not one of the elemental/mental resists that table covers.
# Rather than inventing an unlisted resist stat, bleed ticks at full
# magnitude, unreduced — consistent with not silently adding scope
# to a table that was already deliberately curated.

_APPLICATION_CEILING = 65.0  # % — explicit pick, easy to retune

_APPLICATION_MULTIPLIER = 1.0  # per-status override multiplier, default flat

def eligible_statuses_for_hit(skill: dict) -> list[str]:
    """
    LAYER 1 — returns the list of statuses this specific skill/attack
    could ever cause, by category (not a chance — see module comment
    above). Reads skill["element"] and skill["damage_class"] where
    present (universal schema, from isekai_action_to_skill /
    pokemon_move_to_skill) — no guessing from action text.

    Also accepts the simpler ad hoc skill shape used by rpg_sim.py's
    hand-authored player weapon skills (SWORD_SKILLS/DAGGER_SKILLS/
    SPEAR_SKILLS/BOW_SKILLS/_FREEFORM_TECHNIQUE), which carry a
    lowercase "element" and no "damage_class" key at all — those are
    edged/piercing melee or ranged techniques by construction (every
    entry in those tables is a real physical strike), so the absence
    of "damage_class" is treated as Physical, NOT as "not eligible
    for bleed". A skill that explicitly sets damage_class to
    something else — "Magical"/"Mixed" (universal schema) or "blunt"
    (MACE_SKILLS specifically — blunt trauma bruises/cracks/staggers,
    it doesn't lacerate, so mace hits are deliberately excluded from
    bleed here) — is respected and does NOT get the Physical
    fallback.

    Empty list means this attack has no plausible mechanism for any
    status (e.g. a Normal-element non-physical utility skill).
    """
    eligible = []
    element = str(skill.get("element", "Normal")).strip().title()
    if element in _ELEMENT_TO_STATUS:
        eligible.append(_ELEMENT_TO_STATUS[element])
    damage_class = skill.get("damage_class")
    is_physical = (damage_class == "Physical") or (damage_class is None)
    if is_physical:
        eligible.append("bleed")
    return eligible

def roll_status_application(status: str, damage_dealt: float, target_max_hp: float,
                             weapon_multiplier: float = 1.0) -> bool:
    """
    LAYER 2 — given the status already passed the Layer 1 eligibility
    gate, rolls whether it actually applies this hit. Chance is
    purely damage-relative (bigger hit = higher chance), clamped to
    _APPLICATION_CEILING so no single hit is ever a guaranteed lock.
    Resist is intentionally NOT consulted here — see module comment.

    weapon_multiplier is a per-ATTACKER-WEAPON override (distinct
    from _APPLICATION_MULTIPLIER, which is a per-STATUS-TYPE global
    default) — e.g. a dagger's higher bleed chance (see rpg_sim.py's
    DAGGER_BLEED_MULTIPLIER): a dagger is specifically built for
    precision cuts to vital/vascular spots, so its bleed odds should
    be higher than a blunt or heavy weapon dealing the exact same
    damage number. Defaults to 1.0 (no change) for any caller that
    doesn't have a weapon-specific reason to adjust it.
    """
    if target_max_hp <= 0:
        return False
    raw_chance = (damage_dealt / target_max_hp) * 100 * _APPLICATION_MULTIPLIER * weapon_multiplier
    chance = max(0.0, min(_APPLICATION_CEILING, raw_chance))
    return random.uniform(0, 100) < chance

def apply_status(status_state: dict, status: str, triggering_damage: float) -> dict:
    """
    LAYER 3 setup — adds/refreshes one status entry on a side's
    status_state dict (caller owns e.g. state["monster_status"] /
    state["player_status"], same per-side-dict pattern as
    monster_equipment). Re-applying an already-active status
    REFRESHES duration and updates triggering_damage (a fresh bigger
    hit replaces the old tick basis) rather than stacking multiple
    instances — simplest rule, avoids unbounded stacking from
    repeated hits.
    Returns the updated status_state (also mutated in place).
    """
    profile = _STATUS_TICK_PROFILE.get(status)
    if profile is None:
        return status_state
    status_state[status] = {
        "turns_left": profile["duration"],
        "tick_damage": triggering_damage * profile["tick_pct_of_hit"],
        "resist_stat": profile["resist_stat"],
    }
    return status_state

def tick_statuses(status_state: dict, target_soulbound: dict | None = None) -> tuple[int, list[str]]:
    """
    LAYER 3 ticking — call once per turn per side (independent of
    whether that side was hit this turn — statuses tick on their
    own). Returns (total_tick_damage_this_turn, expired_status_names).
    Expired entries are removed from status_state in place.
    If target_soulbound is given and a status has a resist_stat,
    that stat reduces (never increases) this tick's damage — resist
    affects magnitude only, never duration (STATUS_RESIST_STATS'
    documented behavior, unchanged here).
    """
    total_damage = 0
    expired = []
    for status, entry in list(status_state.items()):
        tick_dmg = entry["tick_damage"]
        resist_stat = entry.get("resist_stat")
        if resist_stat and target_soulbound is not None:
            from secondary_stats import compute_self_secondary
            resist_pct = compute_self_secondary(resist_stat, target_soulbound["stats"])
            tick_dmg *= max(0.0, 1.0 - resist_pct / 100.0)
        total_damage += round(tick_dmg)
        entry["turns_left"] -= 1
        if entry["turns_left"] <= 0:
            expired.append(status)
            del status_state[status]
    return total_damage, expired
