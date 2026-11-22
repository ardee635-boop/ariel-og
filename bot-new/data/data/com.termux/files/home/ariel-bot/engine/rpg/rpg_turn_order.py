"""RPG: rpg turn order (split from rpg_battle.py)."""
import random
from rpg_damage import calc_damage
from rpg_llm import extract_json
from rpg_action_parse import ACTION_COMBAT
from rpg_encounter_gen import _monster_move_data, _skill_to_move_data


# ── Turn order reasoning (clash / sequence / reactive) ──────────
#
# Real combat isn't "player always resolves, then monster always
# resolves" — see design discussion: a fast SPD stat doesn't matter
# if the action itself is slow to execute (a two-handed wind-up
# beats a quick jab on paper but loses if the hand is occupied
# drawing the weapon), two similar-commitment attacks against each
# other are simultaneous (a clash — both land, engine order is not
# a real advantage), and a reactive action (Riposte) only resolves
# off the OTHER side's action, not on its own clock.
#
# This is intentionally an LLM reasoning call, not a numeric
# threshold — "does a hand being occupied change the read" is
# exactly the kind of judgment call a fixed formula gets wrong.
_ORDER_SYSTEM = """You referee turn order for one exchange in a melee/ranged \
combat roleplay duel. Two combatants each declare an action for this exchange. The \
player's action may or may not be an attack — it could be a defensive move, \
a retreat, or something non-mechanical (a taunt, a shout, etc). Decide, \
using real physical logic (weapon commitment, wind-up, whether a \
hand/weapon is already occupied or being drawn, the CURRENT DISTANCE given \
below, reach, and the raw speed stat given for each side as a tiebreaker), \
what actually happens:

- "player_first" — the player's action is clearly quicker to execute and \
resolves before the opponent can act. If it would incapacitate or fully \
evade, the opponent's action may not connect.
- "opponent_first" — same, but the opponent is quicker.
- "clash" — both actions are similar enough in commitment/speed that they \
happen at the same instant — both resolve independently, neither gets an \
ordering advantage. Only sensible when the player's action is itself an \
attack.
- "player_reactive" — the player's action is explicitly a counter/reaction \
(e.g. a riposte, a parry) that only makes sense as a response to the \
opponent's action. It resolves after seeing what the opponent did, and \
only actually connects if the opponent's action was a direct attack it \
could react to.
- "opponent_reactive" — same, but for the opponent's action.

A raw speed-stat advantage (given below) can be *outweighed* by what the \
action actually requires physically — a faster fighter still loses \
priority if their action needs more setup (drawing a weapon, winding up \
a huge swing) than the slower fighter's simpler action. A retreat or a \
solid block/brace should very often win priority against a monster's slow \
wind-up.

DISTANCE matters directly: at "far" distance, a melee weapon attack \
realistically CANNOT land this exchange without first closing the gap — \
the melee side should lose priority (or the attack simply doesn't reach) \
unless their stated action is itself about closing the distance. A \
RANGED attacker at "far" or "near" distance has a real advantage — they \
don't need to close anything. At "melee" distance, a ranged weapon is at \
a disadvantage (awkward to aim/loose at point-blank) and a melee weapon \
is fully effective. "near" is in between — closable in one committed \
step/lunge, so a fast melee attacker can still often win priority against \
a slower ranged one even from "near".

POSTURE, if given below, can override everything else: a fighter whose \
posture says can_reposition is false (airborne with nothing to push off \
of, prone and still rising, pinned) cannot dodge, retreat, or otherwise \
win priority through evasion this exchange — their own attack can still \
land if it doesn't require repositioning, but they should never be ruled \
to have dodged or out-maneuvered the other side while in that state. An \
opponent facing a fighter with can_reposition false has an easier time \
landing a hit that requires no special timing.

Respond ONLY with JSON, no other text:
{"order": "player_first" | "opponent_first" | "clash" | "player_reactive" | "opponent_reactive"}
"""

def _decide_order(player_action_text: str, action_type: str, player_skill: dict | None,
                   player_spd: float, monster_action_desc: str, monster_skill: dict,
                   monster_spd: float, call_groq_fn, distance: str = "melee",
                   monster_posture: dict | None = None, player_posture: dict | None = None) -> str:
    """
    Falls back to "clash" for combat actions, "player_first" for
    non_combat actions on missing/malformed responses — a non-attack
    that fails to classify shouldn't default into a forced mutual
    trade the player never chose to make.
    """
    default = "clash" if action_type == ACTION_COMBAT else "player_first"
    if call_groq_fn is None:
        return default

    if player_skill is not None:
        reach_note = ""
        if player_skill.get("reach"):
            reach_note = " [this weapon has REACH — keeps distance, strikes before a closing opponent arrives]"
        elif player_skill.get("ranged"):
            reach_note = " [this is a RANGED weapon — needs distance to use effectively, at a disadvantage once an opponent closes to melee]"
        player_desc = (f"(committed skill: {player_skill['name']} — "
                        f"{player_skill['description']}, SPD stat: {player_spd}{reach_note})")
    else:
        player_desc = f"(non-attack action, SPD stat: {player_spd})"

    monster_reach_note = ""
    if monster_skill.get("reach"):
        monster_reach_note = " [this weapon has REACH — keeps distance, strikes before a closing opponent arrives]"
    elif monster_skill.get("ranged"):
        monster_reach_note = " [this is a RANGED weapon — needs distance to use effectively, at a disadvantage once an opponent closes to melee]"

    posture_lines = []
    if player_posture:
        posture_lines.append(f"Player posture: {player_posture.get('text')} [can_reposition: {player_posture.get('can_reposition')}]")
    if monster_posture:
        posture_lines.append(f"Opponent posture: {monster_posture.get('text')} [can_reposition: {monster_posture.get('can_reposition')}]")
    posture_block = ("\n" + "\n".join(posture_lines) + "\n") if posture_lines else ""

    user = (
        f"Current distance between fighters: {distance}\n"
        f"{posture_block}\n"
        f"Player's action: \"{player_action_text}\" {player_desc}\n\n"
        f"Opponent's action: \"{monster_action_desc}\" "
        f"(committed skill: {monster_skill.get('name', 'Strike')} — "
        f"{monster_skill.get('description', 'a basic attack')}, "
        f"SPD stat: {monster_spd}{monster_reach_note})"
    )
    reply = call_groq_fn(_ORDER_SYSTEM, user, max_tokens=200, temperature=0.2, json_mode=True)
    if not reply:
        print(f"[SIM_DEBUG] decide_order: EMPTY/None reply from Groq "
              f"for player_action={player_action_text!r} action_type={action_type} "
              f"-> defaulting {default!r}", flush=True)
        return default
    try:
        parsed = extract_json(reply)
        if parsed is not None:
            order = str(parsed.get("order", "")).strip().lower()
            print(f"[SIM_DEBUG] decide_order: player_action={player_action_text!r} "
                  f"action_type={action_type} raw_reply={reply!r} -> order={order!r}", flush=True)
            if order in ("player_first", "opponent_first", "clash",
                         "player_reactive", "opponent_reactive"):
                return order
            print(f"[SIM_DEBUG] decide_order: {order!r} not a recognized order "
                  f"-> defaulting {default!r}", flush=True)
        else:
            print(f"[SIM_DEBUG] decide_order: extract_json returned None "
                  f"for raw_reply={reply!r} -> defaulting {default!r}", flush=True)
    except AttributeError as exc:
        print(f"[SIM_DEBUG] decide_order: AttributeError parsing "
              f"raw_reply={reply!r}: {exc} -> defaulting {default!r}", flush=True)
    return default

def _resolve_hit(attacker: dict, skill_or_move: dict, defender: dict, db, is_monster_skill: bool,
                  attacker_stack=None):
    """
    One damage roll -> (damage_or_-1, display_name). attacker_stack
    is an optional secondary_stats.ModifierStack (e.g. a blinded
    accuracy debuff — see blinded_stack()) applied to the ATTACKER's
    primary stats before the roll, same mechanism DEF-penalty from
    broken armor uses on the defender side (see monster_armor_penalty
    / _apply_player_hit) — just the existing calc_damage stack param,
    not a parallel system.
    """
    move_data = _monster_move_data(skill_or_move) if is_monster_skill else _skill_to_move_data(skill_or_move)
    dmg, _ = calc_damage(attacker, move_data, defender, db, attacker_stack=attacker_stack)
    side = "monster" if is_monster_skill else "player"
    print(f"[SIM_DEBUG] resolve_hit ({side}): skill={skill_or_move.get('name', 'Strike')!r} "
          f"move_data={move_data!r} attacker_stats={attacker.get('stats')} "
          f"attacker_stack_mods={[(m.target, m.type, m.value) for m in attacker_stack.modifiers] if attacker_stack else None} "
          f"-> dmg={dmg} ({'MISS' if dmg == -1 else 'HIT'})", flush=True)
    return dmg, skill_or_move.get("name", "Strike")

# ── Interrupt check ─────────────────────────────────────────────
#
# Answers: when a hit lands on the PLAYER in the middle of a chained
# or reactive compound action (e.g. "raise shield to block AND lunge
# at its flank", or a monster's counter landing between two chained
# player actions), does that hit disrupt whatever the player was
# about to do next?
#
# Two independent, stackable rolls — each with one clear job, same
# division of labor as accuracy vs damage in calc_damage:
#   1) SEVERITY check: did this hit even trigger an interrupt at all?
#      Based on damage taken as a % of the player's max HP — a graze
#      barely threatens follow-through, a haymaker plausibly does.
#   2) RECOVERY check: if it did interrupt, does the player push
#      through weakened (PARTIAL) or lose the action entirely
#      (BROKEN)? Gated by the player's own DEF — more toughness
#      steadily improves the odds of staying PARTIAL, mirroring
#      DEF's existing mitigation role in calc_damage (a percentage
#      edge, never an outright guarantee).
#
# NOT wired into run_turn yet — deliberately built and testable in
# isolation first, per direction ("do all one at a time"). Multi-
# action detection/splitting (the thing that would actually call
# this between sub-actions) is a separate, not-yet-built piece.

INTERRUPT_NONE = "none"        # no interrupt — next action proceeds untouched

INTERRUPT_PARTIAL = "partial"  # next action proceeds, weakened

INTERRUPT_BROKEN = "broken"    # next action is cancelled outright

# (min % of player's max HP taken in one hit, chance to trigger an interrupt)
# Ordered highest threshold first — first matching band wins.
_INTERRUPT_SEVERITY_BANDS = [
    (0.60, 0.99),
    (0.50, 0.70),
    (0.30, 0.50),
]

# DEF's per-point swing toward PARTIAL over BROKEN, once an interrupt
# has already been triggered. Capped at 90% so DEF alone can never
# make an interrupt fully harmless (BROKEN stays at least a 10%
# possibility no matter how tanky the build).
_INTERRUPT_DEF_PARTIAL_PCT_PER_POINT = 1.5

_INTERRUPT_DEF_PARTIAL_CAP_PCT = 90.0

def check_interrupt(damage_taken: int, defender_max_hp: int, defender_def: float) -> str:
    """
    Pure, deterministic, no LLM involved — same design principle as
    calc_damage's accuracy/damage rolls. Given a hit that just landed
    on the player (or whoever is about to attempt a follow-up
    action), returns one of INTERRUPT_NONE / _PARTIAL / _BROKEN.

    damage_taken: the hit that just landed (already post-mitigation —
        the real number applied to HP, not a raw pre-mitigation value).
    defender_max_hp: the max HP of whoever got hit (the one about to
        attempt the follow-up action).
    defender_def: that same character's DEF stat.
    """
    if damage_taken <= 0 or defender_max_hp <= 0:
        return INTERRUPT_NONE

    severity_pct = damage_taken / defender_max_hp

    trigger_chance = 0.0
    for threshold, chance in _INTERRUPT_SEVERITY_BANDS:
        if severity_pct >= threshold:
            trigger_chance = chance
            break  # highest matching band wins, don't fall through to a lower one

    roll = random.random()
    triggered = roll < trigger_chance
    print(f"[SIM_DEBUG] check_interrupt: damage_taken={damage_taken} "
          f"defender_max_hp={defender_max_hp} severity_pct={severity_pct:.1%} "
          f"trigger_chance={trigger_chance:.0%} roll={roll:.3f} "
          f"-> {'TRIGGERED' if triggered else 'not triggered'}", flush=True)

    if not triggered:
        return INTERRUPT_NONE

    partial_chance_pct = min(
        _INTERRUPT_DEF_PARTIAL_CAP_PCT,
        defender_def * _INTERRUPT_DEF_PARTIAL_PCT_PER_POINT,
    )
    recovery_roll = random.random() * 100
    outcome = INTERRUPT_PARTIAL if recovery_roll < partial_chance_pct else INTERRUPT_BROKEN
    print(f"[SIM_DEBUG] check_interrupt: interrupt triggered, recovery check — "
          f"defender_def={defender_def} partial_chance_pct={partial_chance_pct:.1f}% "
          f"recovery_roll={recovery_roll:.1f} -> {outcome.upper()}", flush=True)
    return outcome
