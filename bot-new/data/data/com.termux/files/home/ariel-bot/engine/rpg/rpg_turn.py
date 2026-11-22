"""RPG: rpg turn (split from rpg_battle.py)."""
import random
from statuses import eligible_statuses_for_hit, roll_status_application, apply_status, tick_statuses
from loadout import loadout_weapon_skill_keys, loadout_armor_penalty
from rpg_llm import extract_json
from rpg_action_parse import ACTION_COMBAT, ACTION_NON_COMBAT, ACTION_UNAVAILABLE, _MONSTER_WIS_BASELINE, _classify_action_type, _classify_skill_key, _hp_bar, _monster_hesitation_chance, _monster_pick_skill, combined_debuff_stack, split_action_text
from rpg_turn_order import INTERRUPT_BROKEN, INTERRUPT_PARTIAL, _decide_order, _resolve_hit, check_interrupt
from rpg_weapon_data import DAGGER_BLEED_MULTIPLIER, MAX_TURNS, SWORD_SKILLS, WEAPON_TABLES, _FREEFORM_TECHNIQUE


# ── Prose narration (replaces the old fixed bullet-line log) ───
#
# Player-freedom fix, part 2: even a correctly-resolved exchange
# used to always print the same "> You use *X* — N damage." bullets.
# This asks the model to narrate the whole exchange as flowing prose
# (Korri/Bart-style), given the already-decided mechanical facts —
# the model narrates HOW it happened, never re-decides WHAT happened
# or the numbers involved.

_NARRATE_SYSTEM = """You narrate one exchange of an ongoing combat \
roleplay duel as a tabletop RPG narrator — vivid, flowing prose, 2-4 \
sentences, third person. You are given: the character's own described \
action in quotes (their actual words for what they do), the mechanical \
outcome (hit/miss, damage numbers, who acted first), both fighters' \
current HP out of their max, and the full current structured combat \
state (conditions, limb status, distance, posture) — this structured \
state, not any memory of past prose, is the authoritative record of \
what's currently true in the fight.

This is not an isolated blow — it's one beat in a continuing fight. Show \
the fight progressing, not just resetting to neutral each turn:
- Reflect each fighter's condition in how they move and act. Someone at \
low HP should stagger, favor a wound, breathe hard, or fight more \
desperately/recklessly — not act exactly as fresh as at full health.
- Build the scene from the CURRENT STRUCTURED STATE given below \
(conditions, limb status, distance, posture) — that state is what's \
actually true right now, not anything you might recall or imagine about \
earlier exchanges. If nothing in the structured state describes a wound, \
restraint, or unusual position, don't invent one out of thin air.
- Let the intensity and stakes escalate as HP drops on either side — a \
fight at 5/20 HP should read differently than one at 20/20.
- The character's action may be a specific, elaborate physical technique \
(a leg sweep, a knee strike, a feint into a follow-up swing, a grapple) \
rather than one of their named sword skills. For these, use your own \
physical judgment to decide and describe HOW the given hit/miss result \
plays out at the level of detail the player described — a clean solid \
connection, a glancing graze, the opponent getting an arm up to block \
part of it, a blade skidding off armor/hide, etc. You are not just \
reporting a number, you are the referee for what actually happened \
physically. Stay consistent with the hit/miss and damage number given — \
you're choosing HOW it landed or didn't, never whether it did.

PERSISTENT CONDITIONS: you are given a list of ongoing physical \
conditions currently in effect (e.g. "the Orc is grappled by Korri's off \
hand", "the Orc's shortsword was knocked to the ground", "Korri is \
bleeding from the shoulder"). These are the ONLY conditions that persist \
between exchanges — nothing else carries over automatically. Respect \
them: if the Orc is grappled, its options are constrained accordingly \
this turn; if a weapon is on the ground, it isn't in anyone's hand until \
someone picks it up.
- If THIS exchange creates a new ongoing condition (a grapple, a disarm, \
a knockdown, a wound that would keep bleeding, an object now on the \
ground), list it in "new_conditions" as \
{"holder": "player"|"monster"|"both", "text": "<short factual \
description>"}. Only genuinely ongoing physical states — not routine \
narration flavor.
- If THIS exchange ends/resolves an existing condition (the grapple is \
broken, the weapon is picked back up, the bleeding is bound), list its \
exact existing text in "removed_conditions".
- Leave both empty if nothing changes.

EQUIPMENT DAMAGE: separately from conditions above, if THIS exchange's \
narration describes a specific piece of the MONSTER's gear (a weapon, \
armor, shield, helmet, etc — NOT the player's) being damaged or destroyed, \
report it in "equipment_changes" as {"slot": "left_hand" | "right_hand" | \
"head" | "chest" | "legs", "state": "cracked" | "broken"}. Use "left_hand"/\
"right_hand" for a WEAPON being damaged (the hand/side holding it — if the \
narration doesn't make the side clear, use "right_hand" as the default \
primary hand). Use "head"/"chest"/"legs" for ARMOR on that body part. Use \
"cracked" for damaged-but-still-usable (a dent, a chip, a crack that \
doesn't stop it working). Use "broken" only for genuinely destroyed/\
unusable (shattered, snapped in half, splintered to pieces). If the SAME \
slot is damaged further in a later exchange (a cracked weapon finally \
snapping), report it again with the new state — this is the ONLY way the \
fight remembers gear damage between exchanges, so if your narration \
describes it, you MUST report it here in the SAME response, every time, \
for every distinct slot — never leave it implicit in the prose alone. \
Leave the list empty if no monster gear was damaged this exchange.

LIMB STATUS: separately from conditions and equipment above, if THIS \
exchange's narration describes one of either fighter's limbs being \
disabled, bound, bruised, injured, or severed, report it in \
"limb_changes" as {"holder": "player" | "monster", "slot": "left_arm" | \
"right_arm" | "left_leg" | "right_leg", "status": "disabled" | "bound" | \
"free" | null, "injury": "bruised" | "injured" | "severed" | "healed" | \
null}. "status" and "injury" are TWO INDEPENDENT axes on the same limb — \
set whichever one(s) actually changed this exchange, leave the other null \
if it didn't change (a limb can be freshly bruised without being bound, \
freshly bound without any injury, or both at once):
- "status: disabled" means that limb itself can no longer be used to \
attack or block with (a sealing technique, a numbed arm) — the rest of \
the body still moves and acts completely normally. A disabled arm \
doesn't stop the fighter from dodging, repositioning, or striking with \
the other arm or legs.
- "status: bound" means that limb is anchored/restrained at that point \
(rope, chains, an earth hold, a grapple) — the limb is the anchor, but \
the real effect is on the fighter's ability to reposition their whole \
body. If ALL of a fighter's relevant limbs end up "bound" at once (e.g. \
a full-body bind like being encased or wrapped head to toe), infer from \
that alone that the fighter cannot move or dodge AT ALL this exchange or \
until freed — there isn't a separate "fully immobilized" signal; total \
immobilization is just every limb slot bound simultaneously. A single \
bound leg still leaves the rest of the body able to twist, block, or \
strike, just without normal footwork.
- "status: free" reports a limb's disabled/bound state no longer applies \
(cut loose, feeling returns, the seal breaks) — this is the ONLY way \
status is cleared, so report it explicitly the exchange it happens.
- "injury" tracks physical damage severity to that specific limb, \
separately from status, and normally only escalates: "bruised" (minor, \
still fully usable, just hurts) -> "injured" (a real wound — a deep cut, \
a wrenched joint — meaningfully hindered but the fighter can still use it \
with effort) -> "severed" (the limb is physically gone/destroyed — \
treat this as effectively permanent, since a severed limb doesn't \
regrow in a normal fight). Only report a HIGHER injury tier than what's \
already recorded for that limb unless the narration explicitly describes \
healing/regeneration (a real magical or narrative reason the limb \
recovers) — if so, use "healed" to clear the injury entirely, or report \
a genuinely lower tier if the recovery is partial. Don't invent an \
injury tier casually just because a limb was hit — only report it when \
the narration specifically describes lasting physical harm to that \
limb, not routine damage already covered by HP loss.
- Only include an entry here if THIS exchange's narration actually \
describes a change to that limb's status and/or injury. Leave the list \
empty if nothing about any limb changed.

DISTANCE: there is ONE shared distance between the two fighters — \
"melee" (close enough to strike with hand weapons), "near" (a short gap, \
closeable in one quick step/lunge), or "far" (real separation, needs a \
deliberate approach or sprint to close). If THIS exchange's narration \
describes movement that changes it — someone closing in, retreating, \
creating space, being knocked back, kiting away — report the new value \
in "new_distance" as "melee" | "near" | "far". Leave it null if nothing \
this exchange changed the distance (most exchanges won't). A fighter \
whose LEGS are currently bound or severed (see LIMB STATUS above) cannot \
change the distance on their own initiative — don't report a new \
distance based solely on that fighter's stated intent to close/retreat \
if their legs are bound/severed, though the OTHER fighter closing the \
gap on them, or a throw/knockback effect, can still change it.

POSTURE: separately from all the above, if THIS exchange's narration \
puts either fighter into (or out of) a notable physical position — \
airborne, off-balance (overextended, weapon driven into the ground and \
momentarily stuck, stumbling), prone/knocked down, pinned, dangling, or \
anything else unusual — report it in "posture_changes" as {"holder": \
"player" | "monster", "text": "<short factual description>" | null, \
"can_reposition": true | false}. Set "text" to null (with \
"can_reposition": true) to report a fighter returning to normal footing \
— this is the ONLY way posture is cleared, same as conditions/limbs. \
"can_reposition" is the mechanically important part: false means that \
fighter cannot dodge, retreat, or reposition their whole body this \
exchange (airborne with nothing to push off of, prone and still getting \
up, pinned) — true means they're described as unusual but still capable \
of moving normally despite it. AIRBORNE IS NEVER PERMANENT: if a fighter \
is airborne this exchange, the VERY NEXT exchange's narration MUST \
either land them back to normal footing or convert it to a grounded \
posture (off-balance, prone from a hard landing, etc) — gravity resolves \
it within one exchange no matter what either side does, you cannot report \
"airborne" for the same fighter two exchanges in a row. Off-balance/prone/ \
pinned have no such forced expiry — they persist exactly like any other \
condition until something in the narration resolves them. Leave the list \
empty if posture didn't change for either fighter this exchange.

FLANK: if THIS exchange's narration describes the player specifically \
targeting one SIDE of the monster (its left side/arm/flank, or its right \
side/arm/flank), set "targeted_slot" to "left_hand" | "right_hand" | null \
(null if no specific side was targeted, or if a body part other than a \
side — head/chest/legs — was targeted instead). This does not need an \
equipment_changes entry to go with it — a targeted attack that DIDN'T \
break anything can still set this.

BLINDING: if THIS exchange's narration describes either fighter's vision \
being meaningfully obstructed (sand/dust/dirt thrown in the eyes, a hood \
yanked down, blood in the eyes, a bright flash) such that their ability to \
AIM would realistically suffer, set "blinded" to "player" | "monster" | \
"both" | null (null/omit if nothing like this happened). This is a \
temporary disadvantage, not a permanent injury — if a LATER exchange's \
narration shows the blinded fighter clearing their vision, blinking it \
away, wiping their eyes clear, etc, set "blinded_cleared" the same way \
(player/monster/both/null) that exchange. Being staggered, hurt, or \
simply losing an exchange does NOT count as blinded — only an actual \
described obstruction of sight.

STATUS EFFECTS (bleed/poison/burn/freeze/paralysis): the facts given to \
you may already state that a fighter "is now afflicted with" a status, or \
that status damage was dealt this turn, or that a status "is no longer" \
active — these are pre-decided by the game engine, NOT something you \
invent, choose, or apply yourself. Your only job is to narrate whatever \
the facts already say happened (blood welling from a fresh gash for \
bleed, a sickly green tinge for poison, etc), matching the fighter's \
condition in your prose the way you already do for HP/wounds. Never \
narrate a status being inflicted, resisted, or cured unless the facts \
explicitly say so this exchange.

ELEMENT: the facts given to you state the actual element of each attack this \
exchange (e.g. "the actual element of this attack is normal"). This is the \
ONLY element that attack has — it is pre-decided by the game engine, NOT \
something you infer from wording. A fighter's own action text may contain a \
word that sounds elemental ("fire arrow", "ice-cold strike", "lightning \
fast") purely as a figure of speech or verb choice (e.g. "fire" meaning "to \
shoot"), and this does NOT make the attack that element — if the facts say \
an attack is "normal", narrate it as a mundane, non-elemental strike no \
matter what wording the action text used, for BOTH the player and the \
monster. Never invent, upgrade, or carry forward an elemental quality (a \
flaming weapon, a frozen blade, a burning wound) that the facts did not \
state for THIS exchange — and never treat something you narrated in a past \
exchange as having established a permanent elemental property going \
forward unless the facts continue to confirm it each time.

Use the character's actual name, never the word "player". Do not contradict \
any number given, and do not invent a different action than the one \
described. If the character's own action text contains an in-character \
mutter/aside in quotes, you may reference that they said something briefly, \
but do NOT quote it back at length verbatim — paraphrase it in a few words \
or skip it, since the actual mechanical action is what matters here. Do not \
use bullet points, headers, or markdown formatting in the narration text — \
plain narrative prose only. Weave in HP numbers naturally where relevant. \
Always finish narration as complete sentences — never cut off mid-sentence.

END EVERY NARRATION with a sentence hinting at the opponent's state or its \
likely next move — this is not optional flavor, it's the same technique \
good tabletop narration always uses: give the player something concrete \
to react to, not just a report of what already happened. Ground it in \
what's TRUE right now, from the facts given:
- If the monster is winding up, overextended, staggered, or otherwise \
signals what it's about to try, say so plainly (e.g. "the goblin plants \
its feet, readying another downward cut" or "it circles wide, favoring \
its wounded leg").
- If the monster COULDN'T act this exchange (hesitated, was staggered/\
broken out of its attack — check the facts for this explicitly), say so \
as a real observation, not a vague mood line (e.g. "the goblin hangs back, \
uncertain, sizing you up instead of striking" or "it stumbles, still \
reeling, unable to press its advantage").
- Never invent a FUTURE fact that hasn't happened yet (don't claim it "hits \
you" here — that's next turn's job) — only foreshadow intent/posture/state, \
the way an attentive fighter would actually read their opponent.

RECOMMENDED ACTIONS: after narrating, suggest 2-3 things the character \
could plausibly do next — grounded ONLY in what THIS exchange just \
established (an opening left by a miss or stagger, a threat visibly \
building, an ongoing condition in play, a weapon now on the ground, an \
opponent overextended). Never generic filler ("attack", "defend") and \
never reused from a previous turn — a suggestion is stale the instant a \
new exchange has happened. Each is a short imperative phrase (3-6 words), \
e.g. "Press the opening at his knee", "Break free of the grapple", "Retreat \
before he recovers". These are suggestions, not the only options — the \
player can always describe something else entirely.

SPECIAL EVENT: reserved ONLY for a genuinely major narrative interruption \
from OUTSIDE this fight entirely — something far bigger than either \
fighter, e.g. a god or vastly stronger being descends, a third/bigger \
monster crashes in and drags attention away, a natural disaster splits \
the scene apart. This is NOT for ordinary combat drama (a fighter nearly \
winning or losing, a dramatic turn of phrase, a brutal hit) — it is \
reserved for something that would obviously suspend the fight for any \
onlooker, and should be rare. When this genuinely applies, set \
"special_event" to true and "special_event_resolution" to either \
"resume" (the fight breaks off but its consequences — wounds, damage \
already dealt — carry into whatever happens next) or "abandon" (the \
fight is over for good and nothing about it carries forward — e.g. the \
opponent is destroyed or removed from the scene by the interrupting \
force). Leave both of these null/false on every other exchange — this \
should almost never fire.

Respond ONLY with JSON, no other text:
{"narration": "<2-4 sentences of prose, ending with the opponent-state/next-move hint>",
 "new_conditions": [{"holder": "player" | "monster" | "both", "text": "<short description>"}],
 "removed_conditions": ["<exact existing condition text>"],
 "equipment_changes": [{"slot": "left_hand" | "right_hand" | "head" | "chest" | "legs", "state": "cracked" | "broken"}],
 "limb_changes": [{"holder": "player" | "monster", "slot": "left_arm" | "right_arm" | "left_leg" | "right_leg", "status": "disabled" | "bound" | "free" | null, "injury": "bruised" | "injured" | "severed" | "healed" | null}],
 "new_distance": "melee" | "near" | "far" | null,
 "posture_changes": [{"holder": "player" | "monster", "text": "<description>" | null, "can_reposition": true | false}],
 "targeted_slot": "left_hand" | "right_hand" | null,
 "blinded": "player" | "monster" | "both" | null,
 "blinded_cleared": "player" | "monster" | "both" | null,
 "special_event": false,
 "special_event_resolution": null,
 "choices": ["<short suggested action 1>", "<short suggested action 2>"]}
"""

# Safety-net only — NOT the primary mechanism (that's the mandatory
# equipment_changes rule in _NARRATE_SYSTEM above). This catches the
# case where narration prose describes MONSTER gear breaking but the
# model reported NO equipment_changes at all that exchange. It can
# only catch total omission, not partial mis-reporting (e.g. it
# can't tell "reported the helmet but missed the gauntlets" — there's
# no reliable way to match prose mentions to specific item names
# without guessing), so equipment_changes being non-empty always
# wins; this only fires when the list came back completely empty.
_WEAPON_BREAK_WORDS = ("shatter", "shatters", "shattered", "shattering",
                       "splinter", "splinters", "splintered", "splintering",
                       "destroy", "destroys", "destroyed", "destroying",
                       "snap", "snaps", "snapped", "breaks", "broken",
                       "crack", "cracks", "cracked", "dent", "dented",
                       "knock away", "knocked away", "knocked from",
                       "knocked out of")

def _mentions_weapon_break(text: str) -> bool:
    lowered = text.lower()
    return any(phrase in lowered for phrase in _WEAPON_BREAK_WORDS)

def _narrate_exchange(facts: str, hp_status: str,
                       conditions: list, call_groq_fn, current_distance: str = "melee",
                       current_posture: dict | None = None) -> tuple[str, list, list, list, set, set, str | None, list, str | None, list, bool, str | None]:
    """
    Narrates the exchange, updates persistent combat conditions
    (grapples, disarms, wounds, etc), tracks per-slot monster
    equipment damage, tracks blinding and flank targeting, AND
    suggests 2-3 grounded next moves — mirroring .rpg's own choices
    mechanism (session.flags["_choices"], rendered by _with_choices
    every turn) instead of rpg_sim's old behavior of only ever
    showing example actions once, at battle start, generic and
    disconnected from the live fight.

    Returns (narration_text, updated_conditions_list, choices_list,
    equipment_updates_list, blinded_set, blinded_cleared_set,
    targeted_slot, limb_changes_list, new_distance_value,
    posture_changes_list, special_event, special_event_resolution).
    equipment_updates_list is a list of {"slot": str,
    "state": "cracked"|"broken"} dicts — the caller (run_turn) merges
    these into monster["loadout"][slot]["condition"], so a later
    re-report of the same slot (cracked -> broken) simply overwrites
    it rather than needing separate handling here.
    blinded_set / blinded_cleared_set are subsets of {"player",
    "monster"} — "both" from the model is expanded to both members
    here so the caller never has to special-case it.
    targeted_slot is "left_hand"/"right_hand"/None — the flank
    mechanic signal (see FLANK in _NARRATE_SYSTEM).
    limb_changes_list is a list of {"holder": "player"|"monster",
    "slot": "left_arm"|"right_arm"|"left_leg"|"right_leg",
    "status": "disabled"|"bound"|"free"|None,
    "injury": "bruised"|"injured"|"severed"|"healed"|None} dicts —
    status and injury are independent axes, either may be None if
    unchanged this exchange. The caller merges these into
    state["limb_status"][holder][slot] = {"status": ..., "injury":
    ...} (only present keys stored — a "free"/"healed" report clears
    that one axis, not the whole entry), same overwrite-on-re-report
    pattern as equipment.
    new_distance_value is "melee"|"near"|"far"|None — None means this
    exchange didn't change it, caller keeps state["distance"] as-is.
    posture_changes_list is a list of {"holder": "player"|"monster",
    "text": str|None, "can_reposition": bool} dicts — caller merges
    into state["posture"][holder] = {"text":..., "can_reposition":...}
    or None if text is None (normal footing, cleared).
    special_event/special_event_resolution — see _NARRATE_SYSTEM's
    SPECIAL EVENT block; special_event_resolution is
    "resume"|"abandon"|None. "resume" doesn't reload/continue this
    fight later — the caller (run_turn/router) extracts its lasting
    consequences (HP, wounds) via extract_interrupted_battle_summary
    and folds THAT into the next scene's context instead.

    Falls back to (facts, conditions unchanged, [], [], set(), set(),
    None, [], None, [], False, None) if narration is
    unavailable/malformed — never blocks the turn or silently drops
    existing conditions on a parse failure.
    """
    if call_groq_fn is None:
        return facts, conditions, [], [], set(), set(), None, [], None, [], False, None

    current_posture = current_posture or {"player": None, "monster": None}
    user_parts = [f"Current state: {hp_status}"]
    user_parts.append(f"Current distance between fighters: {current_distance}")
    posture_lines = []
    for side in ("player", "monster"):
        p = current_posture.get(side)
        if p:
            posture_lines.append(f"- ({side}) {p['text']} [can_reposition: {p['can_reposition']}]")
    if posture_lines:
        user_parts.append("Current posture:\n" + "\n".join(posture_lines))
    else:
        user_parts.append("Current posture: both fighters on normal footing.")
    if conditions:
        cond_lines = "\n".join(f'- ({c["holder"]}) {c["text"]}' for c in conditions)
        user_parts.append(f"Ongoing conditions currently in effect:\n{cond_lines}")
    else:
        user_parts.append("Ongoing conditions currently in effect: none.")
    user_parts.append(f"This exchange: {facts}")
    user = "\n\n".join(user_parts)

    reply = call_groq_fn(_NARRATE_SYSTEM, user, max_tokens=550, temperature=0.9, json_mode=True)
    if not reply:
        return facts, conditions, [], [], set(), set(), None, [], None, [], False, None
    try:
        parsed = extract_json(reply)
        if parsed is None:
            raise ValueError("no JSON object found")
        narration = str(parsed.get("narration", "")).strip()
        if not narration:
            return facts, conditions, [], [], set(), set(), None, [], None, [], False, None

        updated = list(conditions)
        removed = parsed.get("removed_conditions", [])
        if isinstance(removed, list):
            removed_texts = {str(t).strip() for t in removed if str(t).strip()}
            updated = [c for c in updated if c["text"] not in removed_texts]

        new_conditions = parsed.get("new_conditions", [])
        if isinstance(new_conditions, list):
            for c in new_conditions:
                if not isinstance(c, dict):
                    continue
                holder = str(c.get("holder", "")).strip().lower()
                text = str(c.get("text", "")).strip()
                if holder in ("player", "monster", "both") and text:
                    updated.append({"holder": holder, "text": text})

        equipment_changes = parsed.get("equipment_changes", [])
        clean_equipment = []
        valid_slots = ("left_hand", "right_hand", "head", "chest", "legs")
        if isinstance(equipment_changes, list):
            for e in equipment_changes:
                if not isinstance(e, dict):
                    continue
                slot = str(e.get("slot", "")).strip().lower()
                cond_state = str(e.get("state", "")).strip().lower()
                if slot in valid_slots and cond_state in ("cracked", "broken"):
                    clean_equipment.append({"slot": slot, "state": cond_state})

        # Safety net: only fires on TOTAL omission (see comment
        # above _WEAPON_BREAK_WORDS) — if the model reported anything
        # at all via equipment_changes, trust it and skip this. Can't
        # infer WHICH slot without guessing (same reasoning as
        # before, just relocated from item names to slots), so this
        # only flags for visibility, never forces a guessed slot.
        if not clean_equipment and _mentions_weapon_break(narration) and _mentions_weapon_break(facts):
            print(f"[SIM_DEBUG] _narrate_exchange: SAFETY NET — narration/facts mention "
                  f"gear damage but equipment_changes was EMPTY. Cannot safely infer WHICH "
                  f"slot without guessing, so no state was forced; flagging for visibility. "
                  f"narration={narration!r} facts={facts!r}", flush=True)

        limb_changes = parsed.get("limb_changes", [])
        clean_limbs = []
        valid_limb_slots = ("left_arm", "right_arm", "left_leg", "right_leg")
        valid_statuses = ("disabled", "bound", "free")
        valid_injuries = ("bruised", "injured", "severed", "healed")
        if isinstance(limb_changes, list):
            for lc in limb_changes:
                if not isinstance(lc, dict):
                    continue
                holder = str(lc.get("holder", "")).strip().lower()
                slot = str(lc.get("slot", "")).strip().lower()
                raw_status = lc.get("status")
                raw_injury = lc.get("injury")
                status = str(raw_status).strip().lower() if raw_status else None
                injury = str(raw_injury).strip().lower() if raw_injury else None
                if status not in valid_statuses:
                    status = None
                if injury not in valid_injuries:
                    injury = None
                if holder in ("player", "monster") and slot in valid_limb_slots \
                        and (status is not None or injury is not None):
                    clean_limbs.append({"holder": holder, "slot": slot, "status": status, "injury": injury})

        targeted_slot = str(parsed.get("targeted_slot") or "").strip().lower()
        if targeted_slot not in ("left_hand", "right_hand"):
            targeted_slot = None

        def _expand_holder(value) -> set:
            v = str(value).strip().lower() if value else ""
            if v == "both":
                return {"player", "monster"}
            if v in ("player", "monster"):
                return {v}
            return set()

        blinded_set = _expand_holder(parsed.get("blinded"))
        blinded_cleared_set = _expand_holder(parsed.get("blinded_cleared"))

        choices = parsed.get("choices", [])
        clean_choices = []
        if isinstance(choices, list):
            clean_choices = [str(c).strip() for c in choices if str(c).strip()][:3]

        new_distance = str(parsed.get("new_distance") or "").strip().lower()
        if new_distance not in ("melee", "near", "far"):
            new_distance = None

        posture_changes = parsed.get("posture_changes", [])
        clean_posture = []
        if isinstance(posture_changes, list):
            for pc in posture_changes:
                if not isinstance(pc, dict):
                    continue
                holder = str(pc.get("holder", "")).strip().lower()
                if holder not in ("player", "monster"):
                    continue
                raw_text = pc.get("text")
                text = str(raw_text).strip() if raw_text else None
                can_reposition = bool(pc.get("can_reposition", True))
                clean_posture.append({"holder": holder, "text": text, "can_reposition": can_reposition})

        # special_event: only meaningful alongside a valid resolution
        # — a bare true with no resolution, or a resolution without
        # special_event being true, is discarded outright rather than
        # guessed at. No tag tracking — see
        # extract_interrupted_battle_summary's header comment for why
        # a resumable-by-tag fight isn't the design here.
        special_event = bool(parsed.get("special_event"))
        special_event_resolution = parsed.get("special_event_resolution")
        if special_event_resolution not in ("resume", "abandon"):
            special_event = False
            special_event_resolution = None
        if not special_event:
            special_event_resolution = None

        return (narration, updated, clean_choices, clean_equipment, blinded_set, blinded_cleared_set,
                targeted_slot, clean_limbs, new_distance, clean_posture,
                special_event, special_event_resolution)
    except (AttributeError, ValueError):
        return facts, conditions, [], [], set(), set(), None, [], None, [], False, None

def _resolve_one_sub_action(state: dict, action_text: str, call_groq_fn, db,
                             facts: list, power_multiplier: float = 1.0) -> None:
    """
    Resolves ONE sub-action's mechanics (classify -> skill match ->
    order -> hit/miss) and appends plain facts describing it, exactly
    the logic run_turn used to do inline for its one-and-only action.
    Extracted unchanged so a single-action message (the overwhelming
    common case) still runs through this exact code path with zero
    behavior change — run_turn just now calls it in a loop instead of
    once inline.

    power_multiplier: 1.0 for a normal/clean sub-action. A sub-action
    that survived an INTERRUPT_PARTIAL check (see check_interrupt)
    passes something <1.0 here to reduce the player's own damage on
    this specific sub-action only — the monster's damage is never
    scaled by this, only whatever the player was disrupted while
    attempting.
    """
    player = state["player"]
    monster = state["monster"]
    p_name = player.get("name", "You")
    weapon_key = state.get("weapon", "sword")

    action_type = _classify_action_type(action_text, call_groq_fn, weapon_key)
    if action_type == ACTION_COMBAT:
        skills_by_key = {s["key"]: s for s in WEAPON_TABLES.get(weapon_key, SWORD_SKILLS)}
        skill_key = _classify_skill_key(action_text, call_groq_fn, weapon_key)
        p_skill = skills_by_key[skill_key] if skill_key else _FREEFORM_TECHNIQUE
    else:
        # Both NON_COMBAT and UNAVAILABLE roll no player damage —
        # they differ only in the fact line appended below (why
        # nothing happened), not in the mechanics from here on.
        p_skill = None

    m_skill = _monster_pick_skill(monster["soulbound"], loadout=monster.get("loadout"))
    m_desc = f"attacks with {m_skill.get('name', 'a strike')}"

    p_spd = player["stats"].get("SPD", 0)
    m_spd = monster["stats"].get("SPD", 0)
    order = _decide_order(action_text, action_type, p_skill, p_spd, m_desc, m_skill, m_spd, call_groq_fn,
                           distance=state.get("distance", "melee"),
                           monster_posture=state.get("posture", {}).get("monster"),
                           player_posture=state.get("posture", {}).get("player"))

    def _apply_player_hit():
        # Flank mechanic: if the PREVIOUS turn's narration flagged the
        # player as targeting a specific hand side (state[
        # "last_targeted_slot"] — set one turn late, same pattern as
        # player_blinded/monster_staggered, since _narrate_exchange
        # only knows what was targeted AFTER this hit already
        # resolved), read THAT slot's condition specifically instead
        # of averaging across all armor. This is deliberately about
        # HAND slots (left_hand/right_hand — where a weapon lives),
        # not armor slots (head/chest/legs) — per the original design
        # request: "attacks are easier to dodge on the left flank if
        # the gear is on your left" was about weapon-side, not body
        # armor. A broken/cracked weapon on the targeted side makes
        # THIS hit more effective (harder for the monster to use that
        # side to parry/block), via the same DEF-softening lever as
        # armor, just reading a hand slot instead of a body slot.
        targeted_slot = state.get("last_targeted_slot")
        if targeted_slot in ("left_hand", "right_hand"):
            hand_entry = (monster.get("loadout") or {}).get(targeted_slot) or {}
            hand_cond = hand_entry.get("condition")
            armor_mult = 0.82 if hand_cond == "broken" else (0.93 if hand_cond == "cracked" else 1.0)
            state["last_targeted_slot"] = None  # consumed by THIS attack roll, one-shot
        else:
            armor_mult = loadout_armor_penalty(monster.get("loadout", {}))
        real_def = monster["stats"].get("DEF", 0)
        if armor_mult != 1.0:
            # Temporarily scale DEF for this one damage roll only,
            # then restore — never permanently mutate the monster's
            # real stat block. armor_mult < 1.0 always, so this only
            # ever softens defense, never accidentally buffing it.
            monster["stats"]["DEF"] = real_def * armor_mult
        attacker_stack = combined_debuff_stack(
            blinded=state.get("player_blinded", False), staggered=state.get("player_staggered", False))
        if state.get("player_staggered"):
            state["player_staggered"] = False  # consumed by THIS attack roll, one-shot
            print(f"[SIM_DEBUG] _apply_player_hit: player_staggered CONSUMED this attack "
                  f"(-40% DEX applied, then cleared)", flush=True)
        try:
            dmg, _ = _resolve_hit(player, p_skill, monster, db, is_monster_skill=False,
                                   attacker_stack=attacker_stack)
        finally:
            monster["stats"]["DEF"] = real_def
        if dmg == -1:
            p_element = p_skill.get("element", "normal")
            facts.append(f"{p_name} attacks like this: \"{action_text}\" — but the attempt misses entirely. "
                         f"(The actual element of this attack is {p_element} — this is the ONLY element to narrate, "
                         f"regardless of any element-sounding word in {p_name}'s own action text.)")
        else:
            if power_multiplier != 1.0:
                original_dmg = dmg
                dmg = max(0, int(dmg * power_multiplier))
                print(f"[SIM_DEBUG] _resolve_one_sub_action: power_multiplier={power_multiplier} "
                      f"applied — dmg {original_dmg} -> {dmg}", flush=True)
            state["monster_hp"] = max(0, state["monster_hp"] - dmg)
            weakened_note = " (thrown off, landing weaker than intended)" if power_multiplier < 1.0 else ""
            p_element = p_skill.get("element", "normal")
            facts.append(f"{p_name} attacks like this: \"{action_text}\" — it connects with {monster['name']} for {dmg} HP of damage{weakened_note}. "
                         f"(The actual element of this attack is {p_element} — this is the ONLY element to narrate, regardless of any element-sounding word in {p_name}'s own action text.)")
            for status in eligible_statuses_for_hit(p_skill):
                weapon_mult = DAGGER_BLEED_MULTIPLIER if (status == "bleed" and state.get("weapon") == "dagger") else 1.0
                if roll_status_application(status, dmg, state["monster_max_hp"], weapon_multiplier=weapon_mult):
                    apply_status(state.setdefault("monster_status", {}), status, dmg)
                    facts.append(f"The hit is bad enough that {monster['name']} is now afflicted with {status}.")
                    print(f"[SIM_DEBUG] _apply_player_hit: STATUS APPLIED monster<-{status} "
                          f"(triggering_dmg={dmg}, monster_max_hp={state['monster_max_hp']}, "
                          f"weapon_mult={weapon_mult})", flush=True)
            stagger_chance = p_skill.get("stagger_chance", 0.0)
            if stagger_chance and not state.get("monster_staggered"):
                roll = random.random()
                if roll < stagger_chance:
                    state["monster_staggered"] = True
                    facts.append(f"The blow is heavy enough to stagger {monster['name']}, throwing off its footing.")
                    print(f"[SIM_DEBUG] _apply_player_hit: MONSTER STAGGERED "
                          f"(stagger_chance={stagger_chance}, roll={roll:.3f})", flush=True)

    def _apply_monster_hit():
        # WIS-driven hesitation, checked BEFORE the attack roll —
        # see _monster_hesitation_chance. A low-WIS monster almost
        # always proceeds (small floor chance only); a high-WIS one
        # sometimes holds back and reassesses instead of attacking,
        # distinct from a normal accuracy-based miss (this means the
        # monster never even swung, not that it swung and whiffed).
        monster_wis = monster["stats"].get("WIS", _MONSTER_WIS_BASELINE)
        hesitate_chance = _monster_hesitation_chance(monster_wis)
        roll = random.random() * 100
        if roll < hesitate_chance:
            facts.append(f"{monster['name']} hangs back and reassesses instead of attacking this exchange.")
            print(f"[SIM_DEBUG] _apply_monster_hit: HESITATED — monster_wis={monster_wis} "
                  f"hesitate_chance={hesitate_chance:.1f}% roll={roll:.1f} -> no attack attempted", flush=True)
            return 0

        dmg, name = _resolve_hit(monster, m_skill, player, db, is_monster_skill=True,
                                  attacker_stack=combined_debuff_stack(
                                      blinded=state.get("monster_blinded", False),
                                      staggered=state.get("monster_staggered", False)))
        if state.get("monster_staggered"):
            state["monster_staggered"] = False  # consumed by THIS attack roll, one-shot
            print(f"[SIM_DEBUG] _apply_monster_hit: monster_staggered CONSUMED this attack "
                  f"(-40% DEX applied, then cleared)", flush=True)
        if dmg == -1:
            m_element = m_skill.get("element", "normal")
            facts.append(f"{monster['name']} attacks with {name} but misses {p_name} entirely. "
                         f"(The actual element of this attack is {m_element} — this is the ONLY element to narrate.)")
        else:
            state["player_hp"] = max(0, state["player_hp"] - dmg)
            m_element = m_skill.get("element", "normal")
            facts.append(f"{monster['name']} attacks with {name} and it connects with {p_name} for {dmg} HP of damage. "
                         f"(The actual element of this attack is {m_element} — this is the ONLY element to narrate.)")
            for status in eligible_statuses_for_hit(m_skill):
                if roll_status_application(status, dmg, state["player_max_hp"]):
                    apply_status(state.setdefault("player_status", {}), status, dmg)
                    facts.append(f"The hit is bad enough that {p_name} is now afflicted with {status}.")
                    print(f"[SIM_DEBUG] _apply_monster_hit: STATUS APPLIED player<-{status} "
                          f"(triggering_dmg={dmg}, player_max_hp={state['player_max_hp']})", flush=True)
        return dmg

    if action_type == ACTION_NON_COMBAT:
        facts.append(f"{p_name} does this: \"{action_text}\" — not an attack, no damage roll on their side this exchange.")
    elif action_type == ACTION_UNAVAILABLE:
        weapon_key = state.get("weapon", "sword")
        facts.append(f"{p_name} attempts this: \"{action_text}\" — but it fails outright, since {p_name} "
                     f"has no such weapon, spell, or ability available right now (only a {weapon_key} and their "
                     f"own body). No damage roll on their side this exchange.")

    # ── Single uniform rule, same for every action_type: ──
    # "player_first" means the player's action succeeds in full
    # before the opponent's can land — for combat that's a normal
    # hit-then-hit sequence; for non_combat it means the monster's
    # attack simply fails to reach (a clean dodge/retreat/block),
    # because there is no partial/mitigated tier — .rpg itself has
    # no such tier either; an action either resolves or it doesn't.
    monster_hit_dmg = 0
    if order == "player_first":
        if action_type == ACTION_COMBAT:
            print(f"[SIM_DEBUG] run_turn branch: player_first + COMBAT "
                  f"-> player hits, then monster if alive", flush=True)
            facts.append(f"{p_name} is faster and acts first.")
            _apply_player_hit()
            if state["monster_hp"] > 0:
                monster_hit_dmg = _apply_monster_hit()
        elif action_type == ACTION_UNAVAILABLE:
            # A failed attempt at something the player doesn't have
            # is NOT a successful defensive action — it shouldn't
            # also grant a free dodge. The monster still gets its
            # normal attack this exchange, same as opponent_first
            # would give, since fumbling for a power you don't have
            # wastes the moment rather than protecting it.
            print(f"[SIM_DEBUG] run_turn branch: player_first + UNAVAILABLE "
                  f"-> player's failed attempt wastes the opening, monster still attacks", flush=True)
            monster_hit_dmg = _apply_monster_hit()
        else:
            print(f"[SIM_DEBUG] run_turn branch: player_first + NON_COMBAT "
                  f"-> no player hit, monster's attack simply fails to reach", flush=True)
            facts.append(f"{p_name}'s action succeeds before {monster['name']} can capitalize on it — the attack fails to reach.")

    elif order == "opponent_first":
        print(f"[SIM_DEBUG] run_turn branch: opponent_first (action_type={action_type}) "
              f"-> monster hits, then player if COMBAT and alive", flush=True)
        facts.append(f"{monster['name']} is faster and acts first.")
        monster_hit_dmg = _apply_monster_hit()
        if state["player_hp"] > 0 and action_type == ACTION_COMBAT:
            _apply_player_hit()

    elif order == "player_reactive" and action_type == ACTION_COMBAT:
        print(f"[SIM_DEBUG] run_turn branch: player_reactive + COMBAT "
              f"-> monster hits first, player counters if alive", flush=True)
        # Player's action only connects as a REACTION to the
        # opponent's attack — resolve opponent first, then let the
        # player's action land only if there was something to react to.
        monster_hit_dmg = _apply_monster_hit()
        if state["player_hp"] > 0:
            facts.append(f"{p_name}'s action answers the attack directly, as a reactive counter.")
            _apply_player_hit()

    elif order == "opponent_reactive" and action_type == ACTION_COMBAT:
        print(f"[SIM_DEBUG] run_turn branch: opponent_reactive + COMBAT "
              f"-> player hits first, monster counters if alive", flush=True)
        _apply_player_hit()
        if state["monster_hp"] > 0:
            facts.append(f"{monster['name']} reacts and counters {p_name}'s attack with {m_skill.get('name', 'a counter')}.")
            monster_hit_dmg = _apply_monster_hit()

    elif order == "clash" and action_type == ACTION_COMBAT:
        print(f"[SIM_DEBUG] run_turn branch: clash + COMBAT "
              f"-> both hit unconditionally", flush=True)
        facts.append(f"{p_name} and {monster['name']} both commit at the same instant — a clash.")
        _apply_player_hit()
        monster_hit_dmg = _apply_monster_hit()

    else:
        # Any leftover combination (e.g. a reactive/clash order paired
        # with a non_combat action_type, which the LLM shouldn't
        # produce but isn't guaranteed not to) — safest default is a
        # normal monster action against a player who didn't attack,
        # same as opponent_first would give, never a forced clash.
        print(f"[SIM_DEBUG] run_turn branch: *** FELL INTO LEFTOVER ELSE *** "
              f"order={order!r} action_type={action_type!r} -> only monster hits, "
              f"PLAYER'S ACTION WAS NEVER RESOLVED AT ALL THIS TURN", flush=True)
        monster_hit_dmg = _apply_monster_hit()

    state["_last_sub_action_monster_dmg"] = monster_hit_dmg

def run_turn(state: dict, action_text: str, call_groq_fn, db=None) -> dict:
    """
    Resolves one full exchange. Mirrors .rpg's own shape
    (extract_action -> resolve_action -> narrate_result): one light
    classification (combat vs non_combat) gates whether the player's
    side rolls any damage at all — there is no separate taxonomy of
    non-combat sub-types with their own bespoke resolution math.
    Combat actions get matched to a specific sword skill; non-combat
    actions never do and never deal damage. A single order-check
    (_decide_order) then decides who acts first / whether it's a
    clash / whether either side's action is reactive, applied
    uniformly regardless of what type the player's action was.

    A message may contain MULTIPLE chained sub-actions (see
    split_action_text) — each resolves in full sequence against the
    then-current HP/state, with an interrupt check (see
    check_interrupt) between them: if the monster just landed a hit
    on the player, that hit may weaken (PARTIAL) or outright cancel
    (BROKEN) whichever sub-action was about to happen next. A single
    ordinary action is just a list of length 1 — this loop runs
    exactly once for it, identical to the old single-action behavior.

    Mutates `state` in place, returns it.
    """
    if state["finished"]:
        return state

    print(f"\n[SIM_DEBUG] ===== run_turn START: action_text={action_text!r} "
          f"turn={state['turn']} =====", flush=True)

    player = state["player"]
    monster = state["monster"]
    p_name = player.get("name", "You")
    facts = []  # plain mechanical facts, fed to the narrator — not shown raw to the player

    sub_actions = split_action_text(action_text, call_groq_fn, state)
    print(f"[SIM_DEBUG] run_turn: resolved sub_actions={sub_actions!r}", flush=True)

    power_multiplier = 1.0
    for i, sub_action in enumerate(sub_actions):
        if state["player_hp"] <= 0 or state["monster_hp"] <= 0:
            # Fight already decided mid-chain (e.g. sub-action 1's
            # counter-hit finished the monster, or the monster's hit
            # dropped the player to 0) — remaining sub-actions in the
            # SAME message never happened; nothing left to react to.
            print(f"[SIM_DEBUG] run_turn: fight decided mid-chain at "
                  f"sub_action {i+1}/{len(sub_actions)} — remaining "
                  f"sub-actions not resolved", flush=True)
            break

        if power_multiplier == 0.0:
            # BROKEN from the previous sub-action's interrupt check —
            # this sub-action doesn't happen at all. Still worth a
            # fact line so the narrator can describe the failed
            # follow-through rather than silently skipping it.
            facts.append(f"{p_name} tries to follow up with \"{sub_action}\", "
                         f"but the last hit knocked the attempt apart before it could happen.")
            print(f"[SIM_DEBUG] run_turn: sub_action {i+1}/{len(sub_actions)} "
                  f"={sub_action!r} SKIPPED — broken by prior interrupt", flush=True)
            power_multiplier = 1.0  # reset for whatever comes after, if anything does
            continue

        _resolve_one_sub_action(state, sub_action, call_groq_fn, db, facts, power_multiplier)
        power_multiplier = 1.0  # only ever applies to the ONE sub-action it was computed for

        # Interrupt check between sub-actions only — no point checking
        # after the last one, since there's nothing left to interrupt.
        if i < len(sub_actions) - 1 and state["player_hp"] > 0:
            monster_dmg_this_step = state.pop("_last_sub_action_monster_dmg", 0)
            outcome = check_interrupt(monster_dmg_this_step, state["player_max_hp"],
                                       player["stats"].get("DEF", 0))
            if outcome == INTERRUPT_BROKEN:
                power_multiplier = 0.0
            elif outcome == INTERRUPT_PARTIAL:
                power_multiplier = 0.5  # next sub-action lands at half strength

    state.pop("_last_sub_action_monster_dmg", None)

    # Status ticks — once per turn, independent of this turn's
    # hit/miss (a bleeding target keeps bleeding even on a turn where
    # nobody lands a fresh hit). Applied AFTER the sub-action loop but
    # BEFORE the win/loss check below, so a tick can finish a fight
    # (e.g. poison delivering the killing blow) and gets reflected in
    # this turn's result rather than only showing up next turn.
    if state["monster_hp"] > 0:
        monster_tick_dmg, monster_expired = tick_statuses(state.get("monster_status", {}), monster)
        if monster_tick_dmg > 0:
            state["monster_hp"] = max(0, state["monster_hp"] - monster_tick_dmg)
            facts.append(f"{monster['name']}'s active status effects deal {monster_tick_dmg} HP of damage this turn.")
            print(f"[SIM_DEBUG] run_turn: monster status tick — {monster_tick_dmg} dmg, "
                  f"monster_hp now {state['monster_hp']}, expired={monster_expired}", flush=True)
        for expired in monster_expired:
            facts.append(f"{monster['name']} is no longer afflicted with {expired}.")
    if state["player_hp"] > 0:
        player_tick_dmg, player_expired = tick_statuses(state.get("player_status", {}), player)
        if player_tick_dmg > 0:
            state["player_hp"] = max(0, state["player_hp"] - player_tick_dmg)
            facts.append(f"{p_name}'s active status effects deal {player_tick_dmg} HP of damage this turn.")
            print(f"[SIM_DEBUG] run_turn: player status tick — {player_tick_dmg} dmg, "
                  f"player_hp now {state['player_hp']}, expired={player_expired}", flush=True)
        for expired in player_expired:
            facts.append(f"{p_name} is no longer afflicted with {expired}.")

    if state["monster_hp"] <= 0 and state["player_hp"] <= 0:
        facts.append(f"Both {p_name} and {monster['name']} fall at the same time — mutual defeat.")
        state["finished"] = True
        state["result"] = "draw"
    elif state["monster_hp"] <= 0:
        facts.append(f"{monster['name']} is defeated. {p_name} wins.")
        state["finished"] = True
        state["result"] = "win"
    elif state["player_hp"] <= 0:
        facts.append(f"{p_name} is defeated by {monster['name']}.")
        state["finished"] = True
        state["result"] = "loss"

    state["turn"] += 1
    if not state["finished"] and state["turn"] >= MAX_TURNS:
        facts.append("The turn limit is reached — the fight ends in a draw.")
        state["finished"] = True
        state["result"] = "draw"

    # ── One narration call per exchange, in place of fixed bullets. ──
    # Carries current HP, persistent combat conditions (grapples,
    # disarms, wounds — see start_sim's "conditions" field), and the
    # previous exchange's narration, so the story reflects wounds and
    # builds on what actually happened instead of resetting to neutral
    # each turn. Previous-paragraph continuity (state["log"][-1] fed
    # back as raw prose) was removed — it was a redundant, unreliable
    # second "what's currently true" signal now that conditions/
    # limb_status/distance/posture are the actual source of truth,
    # and letting the model treat an old telegraph line as fact risked
    # contradicting the structured state. state["log"] itself is kept
    # as a transcript, just no longer read back into narration.
    facts_block = " ".join(facts)
    hp_status = (f"{p_name}: {state['player_hp']}/{state['player_max_hp']} HP. "
                 f"{monster['name']}: {state['monster_hp']}/{state['monster_max_hp']} HP.")
    narration_reply_would_be_none = call_groq_fn is None
    narration, updated_conditions, choices, equipment_updates, blinded_set, blinded_cleared_set, targeted_slot, limb_updates, new_distance, posture_updates, special_event, special_event_resolution = _narrate_exchange(
        facts_block, hp_status, state["conditions"], call_groq_fn,
        current_distance=state.get("distance", "melee"),
        current_posture=state.get("posture", {"player": None, "monster": None}))
    narration_fell_back = (narration == facts_block)
    state["conditions"] = updated_conditions
    state["choices"] = choices
    state["last_targeted_slot"] = targeted_slot  # read by _apply_player_hit next call for the flank mechanic
    if new_distance is not None and new_distance != state.get("distance"):
        print(f"[SIM_DEBUG] run_turn: distance {state.get('distance')!r} -> {new_distance!r}", flush=True)
        state["distance"] = new_distance
    if posture_updates:
        posture = state.setdefault("posture", {"player": None, "monster": None})
        for update in posture_updates:
            holder = update["holder"]
            prev = posture.get(holder)
            if update["text"] is None:
                posture[holder] = None
            else:
                posture[holder] = {"text": update["text"], "can_reposition": update["can_reposition"]}
            print(f"[SIM_DEBUG] run_turn: posture[{holder!r}] {prev!r} -> {posture[holder]!r}", flush=True)
    # Gravity safety net: the prompt tells the model airborne can't
    # persist two exchanges running, but if it's ever reported two
    # turns in a row anyway (model slip), force it back to grounded
    # here rather than silently letting a fighter float indefinitely
    # — same "don't trust the LLM to always self-correct" caution as
    # the equipment safety net above.
    for side in ("player", "monster"):
        entry = state.get("posture", {}).get(side)
        if entry and "airborne" in entry.get("text", "").lower():
            was_airborne_last_turn = state.get(f"_{side}_airborne_last_turn", False)
            if was_airborne_last_turn:
                print(f"[SIM_DEBUG] run_turn: SAFETY NET — {side} reported airborne "
                      f"TWO exchanges running, forcing back to grounded.", flush=True)
                state["posture"][side] = {"text": "just landed, regaining footing", "can_reposition": True}
                state[f"_{side}_airborne_last_turn"] = False
            else:
                state[f"_{side}_airborne_last_turn"] = True
        else:
            state[f"_{side}_airborne_last_turn"] = False
    if equipment_updates:
        loadout = monster.setdefault("loadout", {})
        for update in equipment_updates:
            slot = update["slot"]
            entry = loadout.get(slot) or {}
            prev_state = entry.get("condition")
            entry["condition"] = update["state"]
            loadout[slot] = entry
            print(f"[SIM_DEBUG] run_turn: monster loadout[{slot!r}] "
                  f"{prev_state!r} -> {update['state']!r}", flush=True)
        usable = loadout_weapon_skill_keys(loadout)
        if not usable and any((loadout.get(s) or {}).get("condition") == "broken" for s in ("left_hand", "right_hand")):
            print(f"[SIM_DEBUG] run_turn: {monster['name']}'s slotted weapon(s) now broken — "
                  f"falls back to unslotted/natural attacks only (or bare-strike if none). "
                  f"loadout={loadout!r}", flush=True)
        armor_mult = loadout_armor_penalty(loadout)
        if armor_mult != 1.0:
            print(f"[SIM_DEBUG] run_turn: monster armor penalty now {armor_mult:.3f}x DEF "
                  f"(applied per-hit in _apply_player_hit). loadout={loadout!r}", flush=True)
    if limb_updates:
        limb_status = state.setdefault("limb_status", {"player": {}, "monster": {}})
        for update in limb_updates:
            holder = update["holder"]
            slot = update["slot"]
            new_status = update.get("status")
            new_injury = update.get("injury")
            side_status = limb_status.setdefault(holder, {})
            entry = side_status.get(slot, {})
            prev = dict(entry)

            if new_status is not None:
                if new_status == "free":
                    entry.pop("status", None)
                else:
                    entry["status"] = new_status

            if new_injury is not None:
                if new_injury == "healed":
                    entry.pop("injury", None)
                else:
                    entry["injury"] = new_injury

            if entry:
                side_status[slot] = entry
            else:
                side_status.pop(slot, None)

            print(f"[SIM_DEBUG] run_turn: limb_status[{holder!r}][{slot!r}] "
                  f"{prev!r} -> {entry!r}", flush=True)
    # blinded_cleared applied BEFORE blinded_set, so a single
    # exchange that both clears an old blind and reports a fresh one
    # (unusual, but not impossible narratively) nets out correctly —
    # clear-then-reapply, not reapply-then-clear.
    for side in blinded_cleared_set:
        if state.get(f"{side}_blinded"):
            state[f"{side}_blinded"] = False
            print(f"[SIM_DEBUG] run_turn: {side}_blinded CLEARED this turn.", flush=True)
    for side in blinded_set:
        if not state.get(f"{side}_blinded"):
            state[f"{side}_blinded"] = True
            print(f"[SIM_DEBUG] run_turn: {side}_blinded SET this turn — "
                  f"-50% DEX (accuracy) on {side}'s next attack roll(s) until cleared.", flush=True)
    state["log"].append(narration)
    # special_event is a one-shot signal FOR THE ROUTER, not persisted
    # combat state — the router (see router/rpg.py's active-battle
    # intercept) reads it off this returned dict THIS call only, to
    # decide whether to extract-and-abandon the fight instead of the
    # normal save_battle. It is deliberately NOT re-saved into the
    # persisted battle state afterward (nothing downstream needs a
    # stale "an event happened 3 turns ago" flag lingering).
    state["special_event"] = special_event
    state["special_event_resolution"] = special_event_resolution
    print(f"[SIM_DEBUG] run_turn END: facts_block={facts_block!r}\n"
          f"[SIM_DEBUG]   narration_fell_back_to_raw_facts={narration_fell_back} "
          f"(True means the narrate call failed/was empty)\n"
          f"[SIM_DEBUG]   final narration sent to player={narration!r}\n"
          f"[SIM_DEBUG]   suggested next-move choices={choices!r}\n"
          f"[SIM_DEBUG] ===== run_turn END =====\n", flush=True)
    return state

_ZERO_WIDTH_SPACE = "\u200b"

_READ_MORE_PAD = _ZERO_WIDTH_SPACE * 700

def _with_choices(body: str, choices: list[str]) -> str:
    """
    Mirrors .rpg's own _with_choices (router/rpg.py) EXACTLY — same
    700-char zero-width-space read-more pad, same numbered format,
    same "Reply with .rpg <no.>" pattern (adapted to .rpg sim's own
    command name). An earlier version of this rendered choices as
    plain bullets with no pad at all — that wasn't a stylistic
    choice, it was simply missing the actual mechanism .rpg already
    uses, rebuilt (incorrectly) from scratch instead of copied.

    Falls back to plain body when there's nothing to show, same as
    .rpg's version — no pad, no choices header, for an empty list.
    """
    if not choices:
        return body
    choices_block = "\n".join(f"{i}. {text}" for i, text in enumerate(choices, start=1))
    return (
        f"{body}\n"
        f"{_READ_MORE_PAD}\n"
        "*You could:*\n\n"
        f"{choices_block}\n\n"
        "Reply with *.rpg sim <no.>* to pick one, or type your own "
        "action with *.rpg sim <what you do>*."
    )

def render_turn(state: dict) -> str:
    """Formats the most recent turn's narration + an HP status line."""
    lines = state["log"][-1:]
    body = "\n\n".join(lines)
    if state["finished"]:
        return body

    p_bar = _hp_bar(state["player_hp"], state["player_max_hp"])
    m_bar = _hp_bar(state["monster_hp"], state["monster_max_hp"])
    status = (
        f"\n\nYou: {p_bar} {state['player_hp']}/{state['player_max_hp']}\n"
        f"{state['monster']['name']}: {m_bar} {state['monster_hp']}/{state['monster_max_hp']}"
    )
    full_body = body + status
    choices = state.get("choices", [])
    if not choices:
        # No choices to show this turn (e.g. narration call failed) —
        # still need the plain "reply with..." footer .rpg sim always
        # had, since _with_choices only adds that line as part of
        # the numbered-choices block.
        full_body += "\n\nReply with *.rpg sim <what you do>*, or *.rpg sim end* to stop."
    return _with_choices(full_body, choices)

def render_start(state: dict) -> str:
    monster = state["monster"]
    p_bar = _hp_bar(state["player_hp"], state["player_max_hp"])
    m_bar = _hp_bar(state["monster_hp"], state["monster_max_hp"])
    tags = monster.get("tags", [])
    tag_str = "".join(f"{{{t}}} " for t in tags)
    weapon_key = state.get("weapon", "sword")
    return (
        f"⚔️ *Sim battle started: You vs. {tag_str}{monster['name']} "
        f"(Lv. {monster['soulbound']['level']})*\n"
        f"🗡️ *Weapon: {weapon_key}*\n\n"
        f"You: {p_bar} {state['player_hp']}/{state['player_max_hp']}\n"
        f"{monster['name']}: {m_bar} {state['monster_hp']}/{state['monster_max_hp']}\n\n"
        "Reply with *.rpg sim <what you do>* — attack, defend, retreat, "
        "taunt, anything — e.g. \"I slash at it\" or \"I step back and "
        "keep my distance\".\n"
        "Send *.rpg sim end* anytime to stop."
    )
