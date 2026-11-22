"""RPG: rpg action parse (split from rpg_battle.py)."""
import random
from loadout import loadout_weapon_skill_keys
from rpg_llm import extract_json
from rpg_encounter_gen import _FALLBACK_MONSTER_SKILL
from rpg_weapon_data import SWORD_SKILLS, WEAPON_TABLES


# ── Action classification (flavor text -> combat or not) ───────
#
# Rebuilt to match how .rpg itself already works (extract_action /
# resolve_action in rpg_engine.py): a light classification used only
# to gate whether mechanical resolution applies at all — NOT a
# taxonomy of combat sub-categories with separate hand-written
# resolution math for each one. .rpg's resolve_action() checks
# exactly one thing — is action_type == "combat"? — and everything
# else (social/physical/interaction/narrative) just passes through
# as non-mechanical. This mirrors that: COMBAT or NON_COMBAT, full
# stop. No separate "defend" mitigation tier, no separate
# "reposition" evasion tier — those were bespoke categories .rpg
# itself doesn't have, invented for sim only, and they were the
# actual source of the mismatched-severity bugs (a taunt landing a
# full hit, a failed classify call defaulting into a forced attack).

ACTION_COMBAT = "combat"

ACTION_NON_COMBAT = "non_combat"

# The character only has a sword and whatever the 4 named
# SWORD_SKILLS/freeform melee cover — no spells, no ranged weapons,
# no summons, no equipment never established as theirs. An action
# invoking something outside that kit (fireball, "summon dragon", "I
# shoot my crossbow") isn't a combat action that happens to miss, and
# it isn't a non-attack either — it's an attempt at something the
# character doesn't actually have, and should fail as exactly that,
# narrated honestly rather than either working or being silently
# waved through as if it were a normal non-attack.
ACTION_UNAVAILABLE = "unavailable"

# ── Multi-action splitting ──────────────────────────────────────
#
# "I throw the bread at him and throw stone at him" is TWO player
# actions in one message, not one. Before this, the whole string
# went into _classify_action_type as a single blob — only the first
# (or whichever the model latched onto) ever actually resolved; the
# rest silently never happened, same category of bug as the
# truncation issue that made every action read as non_combat.
#
# This runs BEFORE _classify_action_type/_classify_skill_key, and
# those two are UNCHANGED — split_action_text always returns a list
# (length 1 for an ordinary single action), and each entry goes
# through the exact same per-action pipeline as before. A single
# action stays exactly as reliable as it already was; this only
# adds handling for the case that used to silently drop everything
# after the first action.
#
# Kept as a dedicated small model call (not folded into
# _classify_action_type) so a bad/empty reply here can safely fall
# back to "one action, the whole message" — the OLD, already-correct
# behavior — rather than risking a malformed split corrupting a
# message that was never actually a compound in the first place.

_SPLIT_SYSTEM_TEMPLATE = """A player in a combat roleplay duel just sent one \
message that may describe ONE action or SEVERAL actions performed in \
sequence.

Split it into an ordered list of individual action strings, each one a \
short phrase describing a single distinct thing the character does — \
preserve their own wording as closely as possible, don't rephrase or \
embellish, just divide.

CURRENT FIGHT CONTEXT (use this to judge reaction opportunity, not just \
the wording):
{fight_context}

THE CORE TEST: split the message into multiple actions ONLY when the \
opponent would have a REAL opportunity to react or intervene between \
them — meaning the opponent is capable of reacting at all (not \
staggered/grappled/disarmed/downed) AND the described actions are slow \
or separated enough (a fresh aim, a change of target, a described pause \
or repositioning) that a real gap exists. If either condition fails — \
the opponent has no window to act (staggered/grappled/downed/blinded), \
OR the described actions happen too fast/tightly together for any window \
to exist (a combo, a flurry, two things "in the same breath" or "right \
behind" each other) — treat it as ONE action, no matter how many verbs, \
strikes, or numbers are named.

This means: a slow opponent, or one already given a condition that \
prevents it from acting, makes it MORE likely a compound description is \
one action, since there's nothing for it to react to in between anyway. \
A fast, fully able opponent with a real beat described between two \
separate, deliberate acts (re-aiming at a new target, waiting for an \
opening) makes a split more likely.

IMMOBILIZING LIMBS — the fight context above may report the opponent as \
"bound" or "severed" at specific limbs, or fully bound/severed at all \
four. Distinguish these clearly (the context labels them explicitly, \
don't confuse them):
- "BOUND" or "SEVERED" at a limb both mean that limb can't be used to \
move/reposition/react right now — treat them the same for this purpose \
(severed is simply permanent, bound may end when freed). Any limb NOT \
listed as bound/severed is still free to act with. If the context \
reports the opponent bound/severed at ALL FOUR limbs, it cannot move, \
dodge, or react to anything at all right now — always treat multi-beat \
descriptions as ONE action regardless of wording.
- "disabled" or "injured" (bruised/injured, not severed) at a limb are \
DIFFERENT from bound/severed — they mean that limb is hindered or can't \
attack/block with, but this does NOT restrict overall movement, so \
these alone should NOT push you toward treating a compound action as \
one — judge those cases purely on the reaction-window test above, same \
as an opponent with no limb conditions at all.
- If only SOME limbs are bound/severed, check what each described beat \
targets: a beat aimed at the exact bound/severed limb (e.g. "its right \
leg" when the context says right leg bound or severed) has no real \
opponent reaction to interrupt it — lean toward ONE action even if \
phrased like a deliberate separate shot. A beat aimed at a different, \
still-free limb can still be a real separate action if the opponent \
otherwise has a window (not staggered/blinded/all limbs bound or \
severed) — one incapacitated limb doesn't protect the rest of the body.
- Free-text conditions (not the structured limb list) may also describe \
grapples, prone, or other restraint without naming a specific limb — \
treat those the same as a full-body bind (no reaction window at all) \
unless the wording clearly limits it to something narrower.

Supporting rules:
- If the message describes only ONE action, return a list with exactly \
that one string in it (the whole message, or the core action phrase — \
your judgment on trimming filler, but do NOT split a single action into \
pieces).
- A second verb describing the RESULT/OUTCOME of the first verb — not a \
separate thing the character does next — is ONE action, not two. \
"I slash at its neck and cut through its hide" is ONE action (the cut \
IS the slash landing, not a second attack) — same for "I sunder its arm \
and cleave through the bone", "I stab and pierce its chest", "I swing \
and connect with its skull".
- A clause introduced by "while", "as", or "during" almost always \
describes the SETTING or MANNER of the main action, not a separate step \
— e.g. "I nock an arrow while sidestepping and fire" is ONE action.
- A bare number of identical strikes at the same target ("100 punches", \
"two spin kicks") is flavor/intensity, not a literal instruction to \
resolve that many times — treat it as ONE action (a flurry/combo) unless \
something else in the message marks a real separate beat (a different \
target, an explicit pause, the opponent recovering in between).
- Markers like "another," "again," "a second [X]," or a new target named \
on the second verb suggest a genuinely separate act — but still check the \
core test above: even "another arrow" is only a real second action if the \
opponent in this fight_context is capable of reacting in between.
- Preserve the ORDER the player described them in — this is a sequence, \
first thing they do is first in the list.
- Cap at 5 actions even if more are described — if the message clearly \
lists more than 5 distinct things, include only the first 5 (the rest \
would be too much to resolve as one turn; that's a cost/latency limit, \
not a game rule).

Examples:
- "I nock an arrow while sidestepping and fire!" -> ["I nock an arrow \
while sidestepping and fire!"] (one action — sidestep is manner, and \
nothing describes a real gap)
- "I fire an arrow at its leg and fire another arrow at its other leg" \
(opponent able to act, no incapacitating condition) -> ["I fire an arrow \
at its leg", "fire another arrow at its other leg"] (two actions — a \
fresh aim at a new target is a real gap for an opponent that can use it)
- "I fire an arrow at its leg and fire another arrow at its other leg" \
(opponent currently staggered/grappled/downed) -> ["I fire an arrow at \
its leg and fire another arrow at its other leg"] (one action — the \
opponent has no window to react in between regardless of the wording)
- "I throw two spin kicks at the goblin's skull" -> ["I throw two spin \
kicks at the goblin's skull"] (one action — a tight combo, no described \
gap)
- "I unload 100 punches at its skull" -> ["I unload 100 punches at its \
skull"] (one action — the number is intensity/flavor, not a literal \
repeat count)
- "I fire at its left leg" then "I fire at its right leg" (context: \
opponent bound at right leg only) -> ["I fire at its left leg and fire \
at its right leg"] (one action — the second shot targets the exact bound \
limb, no real reaction to interrupt it)
- "I fire at its left leg" then "I fire at its right leg" (context: \
opponent bound at all four limbs) -> ["I fire at its left leg and fire \
at its right leg"] (one action — fully bound means no reaction window \
anywhere on it)

Respond ONLY with JSON, no other text:
{{"actions": ["<first action>", "<second action>", ...]}}
"""

def _fight_context_for_split(state: dict) -> str:
    """
    Compact, plain-language summary of whether/how well the MONSTER can
    currently react — the only side that matters for judging whether a
    chained player action leaves it a real window to intervene. Built
    fresh per call since staggered/blinded/conditions change every
    exchange.
    """
    monster = state.get("monster", {})
    player = state.get("player", {})
    lines = []

    incapacitated = []
    if state.get("monster_staggered"):
        incapacitated.append("staggered (recovering, can't act normally)")
    if state.get("monster_blinded"):
        incapacitated.append("blinded (can't aim/react to precise threats)")
    for cond in state.get("conditions", []):
        if cond.get("holder") in ("monster", "both"):
            incapacitated.append(cond.get("text", ""))

    if incapacitated:
        lines.append("Opponent is currently: " + "; ".join(c for c in incapacitated if c))
    else:
        lines.append("Opponent has no incapacitating condition right now — able to react normally.")

    monster_limbs = state.get("limb_status", {}).get("monster", {})
    all_limb_slots = ("left_arm", "right_arm", "left_leg", "right_leg")
    bound_slots = [s for s in all_limb_slots if monster_limbs.get(s, {}).get("status") == "bound"]
    disabled_slots = [s for s in all_limb_slots if monster_limbs.get(s, {}).get("status") == "disabled"]
    severed_slots = [s for s in all_limb_slots if monster_limbs.get(s, {}).get("injury") == "severed"]
    injured_slots = [s for s in all_limb_slots if monster_limbs.get(s, {}).get("injury") in ("bruised", "injured")]
    if bound_slots or severed_slots:
        fully_stuck = set(bound_slots) | set(severed_slots)
        if fully_stuck == set(all_limb_slots):
            lines.append("Opponent is BOUND/SEVERED at all four limbs — fully immobilized, cannot move, dodge, or reposition at all right now, regardless of how the player's action is phrased.")
        else:
            if bound_slots:
                named = ", ".join(s.replace("_", " ") for s in bound_slots)
                lines.append(f"Opponent is bound at: {named}. It cannot use those specific limbs to move/react, but any limb NOT listed here is still free — it can still act with those.")
            if severed_slots:
                named = ", ".join(s.replace("_", " ") for s in severed_slots)
                lines.append(f"Opponent has SEVERED limb(s): {named} — permanently unusable, treat exactly like bound for reaction purposes (that limb cannot move/react, ever, this fight).")
    if disabled_slots:
        named = ", ".join(s.replace("_", " ") for s in disabled_slots)
        lines.append(f"Opponent has disabled limb(s): {named} — those limbs can't attack or block with, but this does NOT affect overall movement/dodging (disabled is different from bound).")
    if injured_slots:
        named = ", ".join(f"{s.replace('_', ' ')} ({monster_limbs[s]['injury']})" for s in injured_slots)
        lines.append(f"Opponent has injured (not incapacitated) limb(s): {named} — hindered/painful but still usable, does not remove reaction ability on its own.")

    monster_posture = state.get("posture", {}).get("monster")
    if monster_posture:
        if monster_posture.get("can_reposition") is False:
            lines.append(f"Opponent's posture: {monster_posture.get('text')} — CANNOT reposition/dodge/react right now regardless of limb or condition status, treat this the same as being fully bound for reaction purposes.")
        else:
            lines.append(f"Opponent's posture: {monster_posture.get('text')} — notable, but still able to move/react normally despite it.")

    m_spd = monster.get("stats", {}).get("SPD")
    p_spd = player.get("stats", {}).get("SPD")
    if m_spd is not None and p_spd is not None:
        if m_spd >= p_spd:
            lines.append(f"Opponent SPD ({m_spd}) is equal to or faster than the player's ({p_spd}) — a normal reaction window between distinct beats is realistic.")
        else:
            lines.append(f"Opponent SPD ({m_spd}) is noticeably slower than the player's ({p_spd}) — tight/rapid combos are less likely to leave it a real window.")

    distance = state.get("distance", "melee")
    if distance == "far":
        lines.append("Current distance is FAR. Closing the gap and then attacking realistically takes more than one beat — a message like 'I close the distance and strike' is more likely TWO actions here (the opponent has a real window to act while you're still closing) than the same phrasing would be at melee range.")
    elif distance == "near":
        lines.append("Current distance is NEAR (a short gap, closable in one committed step/lunge). A single decisive action that both closes and strikes in one motion (a lunging attack) is plausible as ONE action; a more deliberate two-part approach (closing fully, THEN choosing an attack) leans toward two.")
    else:
        lines.append("Current distance is MELEE — already close enough to strike, no separate closing beat is needed for an attack.")

    return "\n".join(f"- {l}" for l in lines)

def split_action_text(action_text: str, call_groq_fn, state: dict | None = None) -> list[str]:
    """
    Returns an ordered list of individual action strings. Falls back
    to [action_text] (treat the whole message as ONE action) on any
    failure — this is the pre-existing, already-correct behavior for
    a genuinely single action, so a broken split call degrades to
    "no split happened" rather than corrupting anything.
    """
    if call_groq_fn is None or not action_text.strip():
        return [action_text]

    fight_context = _fight_context_for_split(state) if state else \
        "- No fight state available — assume opponent is able to react normally."
    split_system = _SPLIT_SYSTEM_TEMPLATE.format(fight_context=fight_context)

    reply = call_groq_fn(split_system, action_text, max_tokens=200,
                          temperature=0.0, json_mode=True)
    if not reply:
        print(f"[SIM_DEBUG] split_action_text: EMPTY/None reply from Groq "
              f"for action_text={action_text!r} -> treating as ONE action", flush=True)
        return [action_text]
    try:
        parsed = extract_json(reply)
        if parsed is None:
            print(f"[SIM_DEBUG] split_action_text: extract_json returned None "
                  f"for raw_reply={reply!r} -> treating as ONE action", flush=True)
            return [action_text]
        actions = parsed.get("actions", [])
        if not isinstance(actions, list) or not actions:
            print(f"[SIM_DEBUG] split_action_text: no usable 'actions' list "
                  f"in raw_reply={reply!r} -> treating as ONE action", flush=True)
            return [action_text]
        clean = [str(a).strip() for a in actions if str(a).strip()]
        if not clean:
            return [action_text]
        clean = clean[:5]  # hard cap enforced here too, not just trusted from the prompt
        print(f"[SIM_DEBUG] split_action_text: action_text={action_text!r} "
              f"raw_reply={reply!r} -> split into {clean!r}", flush=True)
        return clean
    except AttributeError as exc:
        print(f"[SIM_DEBUG] split_action_text: AttributeError parsing "
              f"raw_reply={reply!r}: {exc} -> treating as ONE action", flush=True)
        return [action_text]

_ACTION_SYSTEM_TEMPLATE = """Classify a player's freeform action in a {weapon_desc} \
roleplay duel into exactly ONE category:

- "combat": the player is trying to hit or damage the opponent using a \
{WEAPON_UPPER}, their bare hands/body, or an improvised physical technique (a \
sweep, grapple, thrown object actually near them, etc).
- "non_combat": anything else that's actually possible for a {weapon_key}-armed \
fighter — defending, blocking, retreating, creating distance, dodging, \
taunting, shouting, inspecting the enemy, picking something up, or any \
other non-attacking action.
- "unavailable": the action requires a tool, weapon, spell, or ability the \
character does NOT have — this character has ONLY a {weapon_key} and their own \
body, nothing else. This includes: any spell or magic (fireball, "cast", \
"conjure", elemental attacks, healing magic), any summon (a dragon, a \
demon, a creature, an ally), any ranged/other weapon never established as \
theirs ({other_weapons_examples}), or any other fantastical ability. A \
mundane thrown object that's plausibly just lying around (a stone, a \
piece of bread) is "combat", not "unavailable" — the line is "a normal \
person could physically do this with what's around them" vs "this \
requires a power/item the character was never established to have".

Short/terse phrasing is common and must still be classified confidently —
do not default to "non_combat" just because the message is short or lacks
elaboration:
- "attack", {skill_words} — this game's own named \
skill words — the name of any attack/strike/weapon technique alone, or any \
misspelling of one of these — all "combat". A bare attack verb or skill \
name IS a complete, valid combat declaration on its own; it does not need \
words like "at it" or "toward the opponent" attached to count.
- "step back", "back away", "block", "retreat", "dodge" alone (no weapon \
or strike mentioned) — all "non_combat".
- "fireball", "summon dragon", "cast a spell", any weapon type NOT \
{weapon_key} (no such weapon ever established) — all "unavailable".

If the message contains BOTH flavor text and a clear attack word/skill name \
anywhere in it (e.g. a muttered aside followed by an attack), classify \
as "combat" — the presence of an attack word anywhere in the message is \
sufficient, even amid other narration. If it contains BOTH a real \
{weapon_key} action AND an unavailable one (e.g. "I attack, then summon a \
dragon"), classify the WHOLE thing as "combat" — split_action_text should \
have already separated these into distinct sub-actions before this point, \
so by the time a single action reaches this classifier, treat any leftover \
mixed phrasing as combat if a real attack is present anywhere in it, since \
that's the mechanically significant part.

Respond ONLY with JSON, no other text:
{{"action_type": "combat" | "non_combat" | "unavailable"}}
"""

# Every OTHER weapon's flavor name, listed as "unavailable" examples for
# a given weapon's prompt — e.g. if the player has "sword", the examples
# shown are dagger/spear/mace/bow, never sword itself. Built once from
# WEAPON_TABLES so adding a 6th weapon later doesn't require editing this
# by hand.
_OTHER_WEAPON_EXAMPLES = {
    w: ", ".join(f'"{other}"' for other in WEAPON_TABLES if other != w)
    for w in WEAPON_TABLES
}

def _skill_words_for(weapon_key: str) -> str:
    skills = WEAPON_TABLES.get(weapon_key, SWORD_SKILLS)
    return ", ".join(f'"{s["key"]}"' for s in skills)

def _action_system_for(weapon_key: str) -> str:
    return _ACTION_SYSTEM_TEMPLATE.format(
        weapon_desc=_WEAPON_DESC.get(weapon_key, "melee combat"),
        weapon_key=weapon_key,
        WEAPON_UPPER=weapon_key.upper(),
        other_weapons_examples=_OTHER_WEAPON_EXAMPLES.get(weapon_key, "a bow, a gun, a crossbow"),
        skill_words=_skill_words_for(weapon_key),
    )

def _classify_action_type(action_text: str, call_groq_fn, weapon_key: str = "sword") -> str:
    """Falls back to "non_combat" if classification is unavailable/broken/
    malformed — mirrors .rpg's own _fallback(), which always defaults to
    the type that can't force a mechanical effect the player didn't
    actually ask for. This must NOT default to "combat": that was the
    live bug ("step back" got forced into a damage-dealing clash when
    classification failed). It also must not default to "unavailable" —
    a broken classify call shouldn't tell the player they can't do
    something they never even tried; "non_combat" (no damage, no
    rejection message either) is still the safest unknown-state default."""
    if call_groq_fn is None:
        return ACTION_NON_COMBAT

    user = f'Player action: "{action_text}"'
    action_system = _action_system_for(weapon_key)
    # max_tokens was 20 — too tight. {"action_type": "non_combat"} alone
    # is close to that many tokens once JSON punctuation/key overhead is
    # counted, so a normal, CORRECT response could get cut off before
    # the closing brace, throw a JSONDecodeError below, and silently
    # fall into the non_combat default — indistinguishable from the
    # model actually getting it wrong. This was likely the real cause
    # of "slash" reading as non_combat, not a prompt/judgment issue.
    # 40 wasn't nearly enough headroom once reasoning_effort tokens are
    # accounted for (see call_groq's comment) — 200 leaves real slack
    # even with a bit of reasoning before the actual JSON answer.
    reply = call_groq_fn(action_system, user, max_tokens=200, temperature=0.0, json_mode=True)
    if not reply:
        print(f"[SIM_DEBUG] classify_action_type: EMPTY/None reply from Groq "
              f"for action={action_text!r} -> defaulting non_combat", flush=True)
        return ACTION_NON_COMBAT
    try:
        parsed = extract_json(reply)
        if parsed is not None:
            action_type = str(parsed.get("action_type", "")).strip().lower()
            if action_type in (ACTION_COMBAT, ACTION_NON_COMBAT, ACTION_UNAVAILABLE):
                print(f"[SIM_DEBUG] classify_action_type: action={action_text!r} "
                      f"raw_reply={reply!r} -> {action_type}", flush=True)
                return action_type
            print(f"[SIM_DEBUG] classify_action_type: unrecognized value "
                  f"{action_type!r} in parsed reply {reply!r} -> defaulting non_combat", flush=True)
        else:
            print(f"[SIM_DEBUG] classify_action_type: extract_json returned None "
                  f"for raw_reply={reply!r} -> defaulting non_combat", flush=True)
    except AttributeError as exc:
        print(f"[SIM_DEBUG] classify_action_type: AttributeError parsing "
              f"raw_reply={reply!r}: {exc} -> defaulting non_combat", flush=True)
    return ACTION_NON_COMBAT

# ── Skill classification (flavor text -> which sword skill, or none) ──
# Only called once action_type has already been confirmed as "combat".
# The player has 4 real named skills (Slash/Thrust/Riposte/Sunder) with
# their own numbers — those should be used whenever the player invokes
# or clearly describes one. But real roleplay combat isn't limited to
# those 4 moves: a leg sweep, a knee strike, a feint-into-a-slash, etc.
# are legitimate techniques that AREN'T any named skill, and forcing
# them to pretend to be "Sword Slash" misrepresents what the player
# described. So this now has a genuine escape hatch — "freeform" — for
# anything that isn't actually one of the 4, instead of always forcing
# a pick among them.

_CLASSIFY_SYSTEM_TEMPLATE = """You are classifying a player's freeform combat action in a \
{weapon_desc} roleplay game.

The player has exactly {n} named skills, each with real fixed numbers behind \
the scenes. Your job is to decide: does this action actually invoke or \
clearly describe one of these {n} named skills, or is it a different \
physical technique entirely (a grapple, a sweep, a knee/elbow strike, a \
feint into a follow-up, an improvised move, anything not really one of \
the {n})?

Only pick a named skill if the action is genuinely that skill, or close \
enough to it that using its numbers wouldn't misrepresent what the player \
described (e.g. explicitly naming it, or a plain description that maps \
onto it directly). Compound or physical techniques that don't match any \
of the {n} — even if the weapon is involved somewhere in the description \
— should be "freeform", not force-mapped onto the closest sounding one.

Respond ONLY with JSON, no other text:
{{"skill_key": "<one of the provided keys, or \\"freeform\\" if it's not really any of them>"}}
"""

_WEAPON_DESC = {
    "sword": "sword-fighting",
    "dagger": "dagger-fighting",
    "spear": "spear-fighting",
    "mace": "mace-fighting",
    "bow": "archery",
    "shield": "shield-fighting",
}

def _classify_skill_key(action_text: str, call_groq_fn, weapon_key: str = "sword") -> str | None:
    """
    Asks the model which of the ACTIVE weapon's skills (WEAPON_TABLES
    [weapon_key], defaulting to "sword" for any caller that hasn't
    been updated to pass the real weapon yet) the player's action
    matches, or None if it's a freeform technique that isn't really
    any of the named skills for that weapon. Falls back to that
    weapon's first-listed skill (the plain baseline entry, same role
    "slash" played when this was sword-only) only on missing/invalid/
    unrecognized responses — a genuine "freeform" answer from the
    model is respected, not treated as a failure.
    """
    skills = WEAPON_TABLES.get(weapon_key, SWORD_SKILLS)
    skills_by_key = {s["key"]: s for s in skills}
    default_key = skills[0]["key"]

    if call_groq_fn is None:
        return default_key

    options = "\n".join(f'- "{s["key"]}": {s["name"]} — {s["description"]} '
                         f'(example: "{s["example"]}")' for s in skills)
    user = f"Known skills:\n{options}\n\nPlayer action: \"{action_text}\""
    system = _CLASSIFY_SYSTEM_TEMPLATE.format(
        weapon_desc=_WEAPON_DESC.get(weapon_key, "melee combat"), n=len(skills))

    reply = call_groq_fn(system, user, max_tokens=200, temperature=0.0, json_mode=True)
    if not reply:
        print(f"[SIM_DEBUG] classify_skill_key: EMPTY/None reply from Groq "
              f"for action={action_text!r} weapon={weapon_key!r} -> defaulting {default_key!r}", flush=True)
        return default_key
    try:
        parsed = extract_json(reply)
        if parsed is not None:
            key = str(parsed.get("skill_key", "")).strip().lower()
            print(f"[SIM_DEBUG] classify_skill_key: action={action_text!r} weapon={weapon_key!r} "
                  f"raw_reply={reply!r} -> skill_key={key!r}", flush=True)
            if key == "freeform":
                return None
            if key in skills_by_key:
                return key
            print(f"[SIM_DEBUG] classify_skill_key: {key!r} not in "
                  f"{weapon_key} skills -> defaulting {default_key!r}", flush=True)
        else:
            print(f"[SIM_DEBUG] classify_skill_key: extract_json returned None "
                  f"for raw_reply={reply!r} -> defaulting {default_key!r}", flush=True)
    except AttributeError as exc:
        print(f"[SIM_DEBUG] classify_skill_key: AttributeError parsing "
              f"raw_reply={reply!r}: {exc} -> defaulting {default_key!r}", flush=True)
    return default_key

# NOTE: the old flat _item_role/monster_weapon_destroyed/
# monster_armor_penalty functions that lived here have been REPLACED
# by soulbound.py's per-body-part loadout system (build_loadout,
# loadout_weapon_skill_keys, loadout_armor_penalty) — see that
# module's big comment block for why. state["monster_equipment"] is
# now state["monster_loadout"]; see start_sim/run_turn below.


def blinded_stack(source: str):
    """
    Builds a secondary_stats.ModifierStack that halves the blinded
    fighter's effective DEX (accuracy) for one damage roll — DEX is
    what calc_damage's accuracy formula reads ("DEX carries both
    accuracy and evasion now"), so a blinded attacker is meaningfully
    more likely to miss, not just flavor text.
    -50% is a clear, noticeable-but-not-guaranteed-miss effect (same
    "explicit pick, easy to retune" spirit as monster_armor_penalty's
    0.82/0.93 multipliers) — sand in the eyes should hurt your odds
    a lot without making every swing an automatic whiff.
    Only affects the blinded side's OWN accuracy as attacker — does
    NOT touch DEF/evasion as a defender, since being blinded doesn't
    make you easier to hit, just worse at hitting.
    """
    from secondary_stats import ModifierStack
    stack = ModifierStack()
    stack.add(source=source, target="DEX", type="percent", value=0.5)
    return stack

def stagger_stack(source: str):
    """
    Same mechanism/shape as blinded_stack (a one-shot ModifierStack
    DEX percent reduction), but deliberately kept as its own function
    rather than reusing blinded_stack directly — the two are
    conceptually different disruptions (vision loss vs concussive
    balance loss) that happen to use the same lever today; keeping
    them separate means retuning one (e.g. giving stagger a harsher
    -60% since it's the whole point of the mace weapon class) doesn't
    silently also change blinding's magnitude.
    -40% chosen slightly lighter than blinded's -50% — stagger is a
    single-hit disruption from ONE weapon class's specific skills
    (MACE_SKILLS' stagger_chance, rolled per-hit, see _apply_player_
    hit/_apply_monster_hit), not a sustained vision-loss condition,
    so a slightly smaller penalty felt right; explicit pick, easy to
    retune.
    """
    from secondary_stats import ModifierStack
    stack = ModifierStack()
    stack.add(source=source, target="DEX", type="percent", value=0.4)
    return stack

def combined_debuff_stack(blinded: bool, staggered: bool):
    """
    Builds ONE ModifierStack carrying whichever accuracy debuffs are
    currently active for a side (both can be true at once — e.g. a
    fighter blinded by sand who then also gets mace-staggered mid-
    fight), rather than the caller having to pick just one. Reuses
    blinded_stack()/stagger_stack()'s own .modifiers entries (merged
    onto one combined stack) instead of re-deriving their magic
    numbers here — retuning either function's percentage automatically
    flows through to this combined path too, nothing to keep in sync
    by hand.
    Returns None if neither is active — same "no stack needed" shape
    _resolve_hit/calc_damage already expect from blinded_stack's
    original None-when-not-blinded behavior.
    """
    if not blinded and not staggered:
        return None
    from secondary_stats import ModifierStack
    combined = ModifierStack()
    if blinded:
        combined.modifiers.extend(blinded_stack("blinded").modifiers)
    if staggered:
        combined.modifiers.extend(stagger_stack("staggered").modifiers)
    return combined

def _monster_pick_skill(monster_sb: dict, loadout: dict | None = None) -> dict:
    """
    Picks the monster's attack this turn from whatever's actually
    still usable per its loadout (see soulbound.build_loadout) —
    replaces the old weapon_destroyed=True/False total-fallback
    behavior. A skill counts as available if EITHER:
      (a) it's unslotted (a natural attack like Bite/Claw, or a 3rd+
          weapon skill beyond the two hand slots — see build_loadout's
          docstring on why only the first two weapon skills get
          slotted), or
      (b) it IS slotted, and that slot isn't 'broken' (a 'cracked'
          weapon stays usable, matching the cracked-but-functional
          rule everywhere else in this system).
    This is now PRECISE per-skill instead of all-or-nothing: breaking
    just the monster's left_hand weapon removes only that ONE skill,
    the right_hand weapon (if any) and all natural attacks remain
    fully available — direct fix for the "I disarmed it but it kept
    switching hammer/spear/greataxe" bug, since the monster's turn-
    to-turn pool is now genuinely constrained by what it's still
    holding, not re-rolled from its entire Open5e skill list.
    loadout=None (caller didn't build one) falls back to the
    original unrestricted behavior — safe default, never crashes.
    """
    all_skills = [s for s in monster_sb.get("skills", []) if s.get("damage", 0) > 0]
    if loadout is None:
        candidates = all_skills
    else:
        usable_keys = loadout_weapon_skill_keys(loadout)
        slotted_keys = set()
        for slot in ("left_hand", "right_hand"):
            entry = loadout.get(slot) or {}
            if "skill_key" in entry:
                slotted_keys.add(entry["skill_key"])
            elif "skill_keys" in entry:
                slotted_keys.update(entry["skill_keys"])
        candidates = [s for s in all_skills
                      if (s.get("key") or s.get("name")) not in slotted_keys
                      or (s.get("key") or s.get("name")) in usable_keys]
    if not candidates:
        return _FALLBACK_MONSTER_SKILL
    return random.choice(candidates)

# WIS-baseline for the hesitation curve below — Open5e ability scores
# for early/common creatures typically cluster around 8-10 WIS, so 8
# was picked as the "instinct, no hesitation" point. NOT the same
# WIS_BASELINE concept as anything on the player side — monsters
# don't have the player's VIT/flat-conversion system, this only
# feeds _monster_hesitation_chance below.
_MONSTER_WIS_BASELINE = 8

_MONSTER_HESITATION_PCT_PER_WIS_POINT = 4.0

_MONSTER_HESITATION_FLOOR_PCT = 3.0

_MONSTER_HESITATION_CAP_PCT = 40.0

def _monster_hesitation_chance(monster_wis: float) -> float:
    """
    Lower-WIS monsters fight on pure instinct and charge in almost
    every time; higher-WIS monsters are more calculating and
    sometimes hold back to assess rather than commit to an attack.
    Floored so even the most feral, mindless monster still has a
    small chance to hesitate (never a hard-guaranteed 100% attack
    rate), capped so even a very cunning one still attacks most of
    the time — hesitation is a real possibility, not the norm.
    """
    raw = (monster_wis - _MONSTER_WIS_BASELINE) * _MONSTER_HESITATION_PCT_PER_WIS_POINT
    return max(_MONSTER_HESITATION_FLOOR_PCT, min(_MONSTER_HESITATION_CAP_PCT, raw))

def _hp_bar(current: int, maximum: int, width: int = 10) -> str:
    if maximum <= 0:
        return "░" * width
    filled = max(0, min(width, round((current / maximum) * width)))
    return "█" * filled + "░" * (width - filled)
