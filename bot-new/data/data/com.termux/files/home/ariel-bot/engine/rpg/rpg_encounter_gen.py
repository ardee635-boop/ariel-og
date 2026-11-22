"""RPG: rpg encounter gen (split from rpg_battle.py)."""
import random
import rpg_map
from soulbound_rpg import fetch_isekai_monster, isekai_to_soulbound
from soulbound_core import stats_at_level, get_secondary_stats
from loadout import build_loadout
from rpg_weapon_data import RANDOM_MONSTER_POOL, WEAPON_TABLES, _FREEFORM_TECHNIQUE


def _skill_to_move_data(skill: dict) -> dict:
    return {
        "name": skill["name"],
        "power": skill.get("damage", 0),
        "accuracy": skill.get("accuracy", 100),
        "type": skill.get("element", "normal"),
        "category": "special" if skill.get("scaling") == "INT" else "physical",
    }

def _monster_move_data(skill: dict) -> dict:
    """Same shape as _skill_to_move_data, but for a converted Open5e
    skill (skills.isekai_action_to_skill's schema — already has the
    keys we need, just different field names for element/scaling)."""
    return {
        "name": skill.get("name", "Strike"),
        "power": skill.get("damage", 0),
        "accuracy": skill.get("accuracy", 100),
        "type": skill.get("element", "normal").lower(),
        "category": "special" if skill.get("scaling") == "INT" else "physical",
    }

_FALLBACK_MONSTER_SKILL = {
    "name": "Strike", "damage": 5, "scaling": "STR", "accuracy": 90, "element": "normal",
}

def build_player_combatant(session_soulbound: dict, level: int, weapon_key: str | None = None) -> tuple[dict, str] | tuple[None, str]:
    """
    Builds a temp soulbound-shaped combatant for sim purposes: same
    stats as the player's real sheet (scaled to `level`), but
    skills[] set from WEAPON_TABLES[weapon_key] regardless of what
    the real sheet has — sim doesn't read/depend on the player's
    actual acquired skills yet, same "sim is a standalone testbed"
    scoping as before, just generalized from sword-only to any of
    WEAPON_TABLES.

    weapon_key=None -> random pick from WEAPON_TABLES (mirrors
    build_monster_combatant's name=None -> random monster pattern,
    per direction: ".rpg sim now gives a random weapon" when no
    weapon is named, same shape as the existing random-monster path).
    An explicitly-given weapon_key not in WEAPON_TABLES returns an
    error string, same pattern as build_monster_combatant's bad-name
    handling — the caller (start_sim) relays it unchanged.

    Returns (combatant, chosen_weapon_key) on success, or
    (None, error_message) on an invalid explicit weapon_key.
    """
    chosen_weapon = weapon_key or random.choice(list(WEAPON_TABLES.keys()))
    if chosen_weapon not in WEAPON_TABLES:
        known = ", ".join(WEAPON_TABLES.keys())
        return None, f"Unknown weapon {weapon_key!r} — choose one of: {known}."

    base = dict(session_soulbound)
    stats = stats_at_level(base, level) if "grades" in base and base["grades"] else base["stats"]
    combatant_sb = {
        "name": base.get("name", "You"),
        "series": "player",
        "level": level,
        "stats": stats,
        "grades": base.get("grades", {}),
        "skills": WEAPON_TABLES[chosen_weapon],
        "traits": [],
    }
    combatant = {"soulbound": combatant_sb, "stats": stats, "types": [], "name": combatant_sb["name"],
                 "weapon": chosen_weapon,
                 "loadout": build_loadout(combatant_sb["skills"], single_weapon_group=True,
                                           weapon_display_name=chosen_weapon)}
    return combatant, chosen_weapon

def build_story_player_combatant(session_soulbound: dict, level: int,
                                  weapon_key: str | None = None) -> tuple[dict, str] | tuple[None, str]:
    """
    Real-".rpg" counterpart to build_player_combatant — same stat
    scaling, but skills[] is NOT the full WEAPON_TABLES[weapon_key]
    list. Per design: picking up a weapon and being classed doesn't
    mean you've learned Riposte or Sunder — you get whichever of that
    weapon's named skills actually appear in the character's own
    soulbound["skills"] (populated by leveling/training, not by
    class grant), plus freeform always, since anyone can attempt an
    improvised technique regardless of training (see
    _FREEFORM_TECHNIQUE — narrator's prose judges how it lands,
    damage/accuracy sit at the same plain baseline for everyone).

    A freshly-classed character with no learned skills yet ends up
    with ONLY freeform available — that's expected, not a bug: per
    the Excalibur framing, you can't use a skill you were never
    taught just because you're holding the weapon it belongs to.

    weapon_key=None -> genuinely unarmed (no class ever granted a
    weapon, or none is currently .equip'd) — resolves to fighting
    bare-handed, freeform-only, NOT a random WEAPON_TABLES pick. This
    is the one real behavioral difference from build_player_combatant
    (sim), which does randomize on None since sim has no concept of
    "this character doesn't own a weapon."

    Returns (combatant, chosen_weapon_key) always — unlike
    build_player_combatant (sim), there's no invalid-weapon error
    path here; a weapon with no WEAPON_TABLES entry (or no weapon at
    all) just resolves to freeform-only skills (see below).
    """
    # Unlike build_player_combatant (sim), None is never randomized
    # into a weapon here — see docstring above. "unarmed" is a real
    # label (not a WEAPON_TABLES key) so battle_state/loadout display
    # something sensible instead of a bare None.
    chosen_weapon = weapon_key or "unarmed"
    # An unrecognized weapon word (e.g. "axe" — Axeman exists as a
    # class, but no AXE_SKILLS table has been written yet) isn't
    # rejected either: real .inv/.equip only ever hands the player
    # real weapon names (see trials.CLASS_STARTING_WEAPON), so this
    # can only mean "no named skills defined for this weapon yet,"
    # not an invalid weapon. Same fallback path as "unarmed" — an
    # empty skill table, freeform-only below.
    base = dict(session_soulbound)
    stats = stats_at_level(base, level) if "grades" in base and base["grades"] else base["stats"]

    learned = set(base.get("skills", []))
    weapon_table = WEAPON_TABLES.get(chosen_weapon, [])
    weapon_skills = [s for s in weapon_table if s["key"] in learned]
    # Freeform always available regardless of what's been learned —
    # see _FREEFORM_TECHNIQUE's own comment for why this isn't
    # gated like the named skills are.
    combat_skills = weapon_skills + [_FREEFORM_TECHNIQUE]

    combatant_sb = {
        "name": base.get("name", "You"),
        "series": "player",
        "level": level,
        "stats": stats,
        "grades": base.get("grades", {}),
        "skills": combat_skills,
        "traits": [],
    }
    combatant = {"soulbound": combatant_sb, "stats": stats, "types": [], "name": combatant_sb["name"],
                 "weapon": chosen_weapon,
                 "loadout": build_loadout(combatant_sb["skills"], single_weapon_group=True,
                                           weapon_display_name=chosen_weapon)}
    return combatant, chosen_weapon

def build_monster_combatant(name: str | None, level: int | None, player_level: int,
                             player_stats: dict) -> tuple[dict, str] | tuple[None, str]:
    """
    Fetches + converts an Open5e creature into a sim-ready
    combatant. Returns (combatant, error_message) — combatant is
    None if the fetch/convert failed, in which case error_message
    explains why (caller returns it straight to the player).

    name=None -> random pick from RANDOM_MONSTER_POOL.
    level=None -> defaults to player_level (per spec: "Empty gives
    random monster and my lvl").

    player_stats is the player's OWN level-scaled stats dict — used
    only to compute the {Strong}/{Fast} tags below (a comparison,
    not a stat mutation), so the player can eyeball a fight's odds
    before committing to it, per direction: "what's special about
    them in front so I'll know my evaluation."
    """
    chosen_name = name or random.choice(RANDOM_MONSTER_POOL)

    raw = fetch_isekai_monster(chosen_name)
    if not raw:
        return None, f"Couldn't find a monster called \"{chosen_name}\" on Open5e. Try another name."

    monster_sb = isekai_to_soulbound(raw)
    final_level = level if level is not None else player_level
    final_level = max(1, final_level)
    stats = stats_at_level(monster_sb, final_level)
    monster_sb["level"] = final_level

    tags = []
    if stats.get("STR", 0) > player_stats.get("STR", 0):
        tags.append("Strong")
    if stats.get("SPD", 0) > player_stats.get("SPD", 0):
        tags.append("Fast")

    combatant = {
        "soulbound": monster_sb,
        "stats": stats,
        "types": [],
        "name": monster_sb["name"],
        "tags": tags,
        "loadout": build_loadout(monster_sb.get("skills", [])),
    }
    return combatant, ""

# ── Story-driven encounter generation ──────────────────────
#
# Separate from build_monster_combatant/RANDOM_MONSTER_POOL above
# (that path is ".rpg sim"'s free-pick-any-Open5e-creature testbed).
# This path is for combat_start-triggered REAL fights: the monster
# is drawn only from the current location's hand-authored
# monster_pool (see rpg_map.encounter_pool) — never an
# arbitrary name — then leveled/rarity-rolled on top. Per design:
# "story dependent" — the narrator doesn't invent creature stats,
# it just names which pool creature the scene's opponent is (or
# nothing at all, if generate_encounter is what decides that too).

RARITY_TABLE = [
    # (name, weight out of 100, stat multiplier, can_be_named)
    ("common",    60, 1.00, False),
    ("uncommon",  25, 1.10, False),
    ("rare",      10, 1.25, True),
    ("epic",       4, 1.50, True),
    ("legendary",  1, 2.00, True),
]

NAMED_VARIANT_PREFIXES = ["Alpha", "Elder", "Ancient", "Savage", "Dread"]

def roll_rarity() -> tuple[str, float, bool]:
    """
    Returns (rarity_name, stat_multiplier, can_be_named) per
    RARITY_TABLE's weights (60/25/10/4/1 out of 100 — see design
    notes). Pure roll, no area/level input — rarity is independent
    of which area you're in, only the monster POOL and level cap
    are area-specific.
    """
    roll = random.uniform(0, 100)
    cumulative = 0.0
    for name, weight, multiplier, can_be_named in RARITY_TABLE:
        cumulative += weight
        if roll < cumulative:
            return name, multiplier, can_be_named
    return RARITY_TABLE[0][0], RARITY_TABLE[0][2], RARITY_TABLE[0][3]

def generate_encounter(location_id: str, player_level: int, player_stats: dict) -> tuple[dict, str] | tuple[None, str]:
    """
    Builds a real story-fight opponent for `location_id`, using ONLY
    that location's hand-authored monster_pool (rpg_locations.
    encounter_pool) — returns (None, error) if the location has no
    pool defined (nowhere to spawn an encounter, e.g. a town interior).

    Level is randomly rolled 1..max_level (per "Random 1 to area
    max" design decision) — NOT tied to player_level directly,
    though player_level is still passed through to
    build_monster_combatant purely for the {Strong}/{Fast} comparison
    tags, same as build_monster_combatant's existing contract.

    Rarity (see roll_rarity) then applies a flat stat multiplier on
    top of that level's base stats, and — for rare/epic/legendary
    only — a chance (50%) of a named variant prefix (e.g. "Alpha
    Wolf") rather than the bare species name. Common/uncommon never
    get a named variant, per "rare and above" design decision.
    """
    pool_data = rpg_map.encounter_pool(location_id)
    if not pool_data:
        return None, f"No encounters can happen at this location."

    chosen_name = random.choice(pool_data["monster_pool"])
    rolled_level = random.randint(1, pool_data["max_level"])

    combatant, error = build_monster_combatant(chosen_name, rolled_level, player_level, player_stats)
    if combatant is None:
        return None, error

    rarity_name, multiplier, can_be_named = roll_rarity()
    if multiplier != 1.0:
        combatant["stats"] = {stat: value * multiplier for stat, value in combatant["stats"].items()}

    display_name = combatant["name"]
    if can_be_named and random.random() < 0.5:
        display_name = f"{random.choice(NAMED_VARIANT_PREFIXES)} {display_name}"
        combatant["name"] = display_name

    combatant["rarity"] = rarity_name
    return combatant, ""

def _max_hp(combatant: dict) -> int:
    secondary = get_secondary_stats(combatant["soulbound"])
    return max(1, int(secondary.get("hp", 20)))

def start_battle(session_soulbound: dict, player_level: int, monster_name: str | None,
              monster_level: int | None, weapon_key: str | None = None) -> dict | str:
    """
    Builds a fresh battle state dict, or returns a plain string error
    (bad monster name, or bad weapon name) for the caller to relay
    unchanged.

    weapon_key=None -> random weapon pick from WEAPON_TABLES; an
    explicit weapon_key uses that weapon, or errors out if it isn't
    a known key.
    """
    player, weapon_result = build_player_combatant(session_soulbound, player_level, weapon_key)
    if player is None:
        return weapon_result  # weapon_result is the error string here
    print(f"[BATTLE_DEBUG] start_battle: requested weapon_key={weapon_key!r} -> "
          f"chosen weapon={weapon_result!r} (skills={[s['key'] for s in player['soulbound']['skills']]})",
          flush=True)
    monster, err = build_monster_combatant(monster_name, monster_level, player_level,
                                            player["stats"])
    if monster is None:
        return err

    return _assemble_battle_state(player, monster, weapon_result)

def start_story_battle(session_soulbound: dict, player_level: int, location_id: str,
                        weapon_key: str | None = None) -> dict | str:
    """
    Real ".rpg" combat_start entry point (see router/rpg.py) — same
    shape/contract as start_battle above, but the monster comes from
    rpg_map.encounter_pool via generate_encounter, NOT an
    arbitrary name. This is what keeps real encounters "story
    dependent" (only this location's hand-authored pool, area-tier
    level cap, rarity roll) rather than letting combat_start spawn
    any Open5e creature the narrator happens to name.

    Returns a plain string error if location_id has no monster_pool
    defined (nowhere to spawn an encounter) or the weapon_key is bad
    — same error-relay contract as start_battle.
    """
    player, weapon_result = build_story_player_combatant(session_soulbound, player_level, weapon_key)
    if player is None:
        return weapon_result

    monster, err = generate_encounter(location_id, player_level, player["stats"])
    if monster is None:
        return err

    return _assemble_battle_state(player, monster, weapon_result)

def _assemble_battle_state(player: dict, monster: dict, weapon_result: str) -> dict:
    """
    Shared state-dict assembly for start_battle/start_story_battle —
    both build `player`/`monster` combatants their own way (arbitrary
    Open5e name+level vs. area-pool+rarity roll), then hand off here
    so the actual battle state SHAPE never drifts between the two
    entry points.
    """
    state = {
        "player": player,
        "monster": monster,
        "weapon": weapon_result,  # the actual chosen weapon key — needed by
                                   # _CLASSIFY_SYSTEM/unavailable-action text/
                                   # _decide_order to know which skill table
                                   # and reach/ranged property is in play
        "player_hp": _max_hp(player),
        "player_max_hp": _max_hp(player),
        "monster_hp": _max_hp(monster),
        "monster_max_hp": _max_hp(monster),
        "turn": 0,
        "log": [],
        "finished": False,
        # Persistent structured combat state — grapples, disarms,
        # prone/knockdown, bleeding, or anything else the narrator
        # declares as an ongoing condition. Mirrors .rpg's
        # new_scene_objects/removed_scene_objects pattern: the
        # narrator itself declares what starts/stops existing each
        # turn, and this list is fed back to it explicitly next turn
        # instead of relying on it remembering one prior paragraph.
        # Each entry: {"holder": "player"|"monster"|"both", "text": str}
        "conditions": [],
        # Equipment/gear damage now lives on the combatant dicts
        # themselves as state["monster"]["loadout"] / state["player"]
        # ["loadout"] (built once at combatant-build time by
        # soulbound.build_loadout — see build_monster_combatant/
        # build_player_combatant above), NOT a separate flat state
        # field here. This replaced an earlier flat monster_equipment
        # dict ({item_name: condition}, no body location) after a
        # design discussion: per-body-part slots (left_hand/
        # right_hand/head/chest/legs) let a disarm target ONE side
        # precisely instead of guessing which skill(s) an item name
        # maps to, and open a real flank mechanic (an attack aimed at
        # a specific side can read THAT slot's condition) — see
        # soulbound.py's loadout system for the full design.
        # Blinded is a CONTESTED-ACCURACY debuff, not an
        # equipment-style item — no partial states (no "half-
        # blinded"), just on/off per side, cleared the same way it
        # was granted: a later narrated exchange reports it resolved
        # (eyes cleared, blinked it away) via removed_conditions,
        # same as any other `conditions` entry — unlike monster_
        # equipment, this ISN'T meant to be permanent-for-the-sim,
        # since sand in the eyes is a temporary disadvantage a real
        # fighter recovers from, not a destroyed physical object.
        "player_blinded": False,
        "monster_blinded": False,
        # General status-effect state (bleed/poison/burn/freeze/
        # paralysis) — see soulbound.py's status-effect system
        # (apply_status/tick_statuses/eligible_statuses_for_hit/
        # roll_status_application). Each dict maps status name ->
        # {"turns_left", "tick_damage", "resist_stat"}, ticked once
        # per run_turn() call independent of that turn's hit/miss.
        "player_status": {},
        "monster_status": {},
        # Flank mechanic — set by _narrate_exchange when the player's
        # action is described as targeting a specific hand side (see
        # FLANK in _NARRATE_SYSTEM), consumed one-shot by the NEXT
        # _apply_player_hit call (same one-turn-delayed pattern as
        # player_blinded/monster_staggered — narration only knows
        # what was targeted AFTER a hit already resolved, so it can
        # only ever apply forward).
        "last_targeted_slot": None,
        # Stagger — mace-specific mechanic (MACE_SKILLS' stagger_chance,
        # rolled per-hit). Same shape/lifetime as player_blinded/
        # monster_blinded (one-turn accuracy debuff via stagger_stack,
        # NOT a damage-tick status — see stagger_stack's docstring for
        # why it's kept separate from the bleed/poison/etc pipeline
        # above), cleared automatically after being consumed on the
        # staggered side's next attack roll rather than needing an
        # explicit narrator-reported clear like blinding does — a
        # concussive stagger is a single missed beat, not an ongoing
        # condition someone "clears" through in-fiction action.
        "player_staggered": False,
        "monster_staggered": False,
        # Per-limb status — left_arm/right_arm/left_leg/right_leg for
        # each side, reported via limb_changes in _NARRATE_SYSTEM (see
        # LIMB STATUS section there). Only slots with an active
        # "disabled" or "bound" entry are present — a free limb is
        # simply absent from the dict, same sparse-storage pattern as
        # monster["loadout"] using per-slot entries only where damage
        # exists. Read by _fight_context_for_split to judge whether a
        # chained action leaves the opponent a real reaction window
        # (a fully bound fighter — every limb slot "bound" at once —
        # cannot react or reposition at all).
        "limb_status": {"player": {}, "monster": {}},
        # Shared distance between the two fighters — "melee" | "near" |
        # "far". One value for the whole exchange, not per-side (you
        # can't be at melee range of someone who's at far range of
        # you — distance is inherently mutual). Defaults to "melee"
        # since most duels start close. Updated via "new_distance" in
        # _NARRATE_SYSTEM whenever THIS exchange's narration actually
        # describes movement changing it (closing in, retreating,
        # being knocked back, kiting) — read by _decide_order (which
        # already reasoned about "distance" in its prompt before this
        # field existed, just never had a real value to check) and by
        # _fight_context_for_split (closing-and-striking is a real
        # two-beat action from far range, but not from melee range
        # already).
        "distance": "melee",
        # Per-fighter posture — free text like "conditions" (airborne,
        # off-balance with weapon driven into the ground, prone,
        # pinned under something, dangling off a ledge — unbounded,
        # same reasoning as why "conditions" isn't a closed enum
        # either), PLUS a simple "can this fighter reposition right
        # now" flag, since that flag is the one fact _decide_order and
        # _fight_context_for_split actually need to act on — the
        # prose is for narration continuity/flavor, the flag is what's
        # mechanically load-bearing. Each entry:
        # {"text": str, "can_reposition": bool}. Absent/None for a
        # side means normal footing, nothing noteworthy. Airborne
        # postures are NOT allowed to persist past one exchange —
        # gravity forces a landing/resolution by the very next
        # _NARRATE_SYSTEM call regardless of what happened (see
        # POSTURE section there) — grounded states like off-balance or
        # prone have no such auto-expiry and stay until narratively
        # resolved (getting back up, steadying oneself), same
        # lifetime pattern as "conditions".
        "posture": {"player": None, "monster": None},
        # Grounded next-move suggestions from the most recent
        # narration — see _NARRATE_SYSTEM's "RECOMMENDED ACTIONS"
        # section and .rpg's own session.flags["_choices"]/
        # _with_choices for the pattern this mirrors. Empty until the
        # first turn resolves (render_start shows its own static
        # examples instead, for a fight with zero exchanges yet).
        "choices": [],
    }
    return state
