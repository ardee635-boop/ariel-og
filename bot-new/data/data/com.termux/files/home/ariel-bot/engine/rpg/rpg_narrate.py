"""RPG: rpg narrate (split from rpg_engine.py)."""
import re
import rpg_scene
from rpg_llm import GROQ_NARRATION_MODEL, call_groq, extract_json


try:
    from lore import QUICK_REF as _LORE
except ImportError:
    _LORE = None  # lore.py not present — narration still works, just

# ============================================================
# STAGE 4 — NARRATION
# ============================================================

def _lore_block() -> str:
    """
    Compact world-grounding context built from lore.py's QUICK_REF,
    not the full prose lore files — full lore per call would bloat
    every narration request with mostly-irrelevant detail. This is
    the actual "does the model know about the world" fix: without
    it, Ariel has zero knowledge Niflheim, Pangea, the System, or
    Baelzebub even exist, and will either stay vague or invent
    conflicting lore on the fly. Returns "" if lore.py isn't present
    (e.g. not yet deployed), so narration still works without it.
    """
    if _LORE is None:
        return ""

    primordials = ", ".join(_LORE["primordials"])
    return f"""
WORLD KNOWLEDGE (for grounding — reference naturally when relevant,
don't info-dump lore the player hasn't asked about or encountered):
- World: {_LORE['world']}
- Mortal realm: {_LORE['mortal_realm']} | Realm of gods: {_LORE['god_realm']}
- The Twin Gods: {', '.join(_LORE['twin_gods'])}
- The Fallen: {_LORE['fallen']}
- The System: {_LORE['system']}
- The twelve Primordials: {primordials}
- The player character: {_LORE['cursed_children']}

SECRET LORE — do not reveal unprompted:
{_LORE['secret_lore']['luminaria_truth']}
{_LORE['secret_lore']['who_can_know']}
You may use this for internal consistency (how a Light-pantheon NPC
who canonically knows the truth would act, what they'd let slip
under pressure, what they'd never say) — but ordinary narration,
ordinary NPCs, and ordinary mortal characters must treat Luminaria
as the genuine, legitimate Goddess of Light. Never state this secret
as established fact in narration unless the scene has actually
earned that reveal — a player investigating deep Light-church lore,
a canonical NPC confessing, an artifact/event explicitly surfacing
it. Default to the public version: beloved, radiant, legitimate.
"""

def _narration_system(offers_trial: str | None = None) -> str:
    trial_block = ""
    if offers_trial == "warrior":
        trial_block = f"""
TRIAL AVAILABLE HERE: The player is somewhere that can offer the
Warrior class trial (the Coliseum) — recognize when their action
reads as accepting/starting it (e.g. "I step into the ring", "I'm
ready to fight", "let's do this", talking to the instructor and
agreeing to test themselves). When you recognize this, set
"trial_start" to "warrior" in your JSON reply. If the SAME message
also names a specific weapon on offer ({', '.join(
        ['sword', 'dagger', 'spear', 'axe', 'mace', 'shield', 'bow']
    )}) — e.g. "I pick up the sword and step into the ring" — also
set "trial_weapon" to that weapon so both are recognized in one
beat; otherwise leave "trial_weapon" null and narrate the instructor
presenting the weapon rack instead. Do NOT set trial_start for
ambiguous or exploratory actions ("I look around the Coliseum",
"I ask about the trial") — only for a clear acceptance."""
    elif offers_trial == "mage":
        trial_block = """
TRIAL AVAILABLE HERE: The player is somewhere that can offer the
Mage class trial (the library) — recognize when their action reads
as accepting/starting it (e.g. "I'm ready to learn", "teach me",
agreeing after the elder/instructor offers). When you recognize
this, set "trial_start" to "mage" in your JSON reply (leave
"trial_weapon" null — it's not used for the mage trial). Do NOT set
trial_start for ambiguous or exploratory actions — only for a clear
acceptance."""
    elif offers_trial == "summoner":
        trial_block = """
TRIAL AVAILABLE HERE: The player is somewhere that can offer the
Summoner class trial (the pet shop) — recognize when their action
reads as accepting/starting it (e.g. "I'll take the trial", "show me
the pets", "I want to bond with one", agreeing after the shopkeeper
offers). When you recognize this, set "trial_start" to "summoner" in
your JSON reply (leave "trial_weapon" null — it's not used for the
summoner trial). Do NOT set trial_start for ambiguous or exploratory
actions ("I look around the shop", "just browsing", "I ask about the
animals") — only for a clear acceptance of the TRIAL itself, not mere
interest in seeing the pets."""

    return f"""You are Ariel, the game master for a persistent solo roleplay world.

VOICE: Ariel is playful, confident, emotionally present — never a
neutral narrator. Show this in word choice, asides, tone. Re-establish
it every turn; don't assume it carries over.
{_lore_block()}
RULES YOU MUST FOLLOW:
- Narrate ONLY the validated action and mechanical result given below —
  never invent what the ACTION accomplishes or how an NPC responds
  beyond what's provided. You MAY freely add flavor as your narration
  needs it — a passing baker, a stray cat, a fountain, a fallen pillar,
  a corpse, anything that makes the scene feel real. This is
  encouraged, not just tolerated: an unnamed background detail becomes
  real and interactable the moment you narrate it, the same way a
  named NPC does — nothing here is ever silently discarded. You don't
  need to track or format this yourself beyond the existing fields
  below (new_npcs for addressable characters, new_scene_objects for
  physical things); just narrate naturally and describe what's really
  there.
- CURRENT LOCATION's NPCs/Objects lists are the ONLY source of truth
  for who/what is physically present THIS turn — this overrides PAST
  EVENTS, no exceptions. If a character/animal/object appeared before
  but isn't listed now (including "none"), they're NOT here — the
  player has moved on. Don't describe, voice, or reference them, even
  briefly, even if PAST EVENTS feels unfinished. "NPCs physically here
  right now: none" means genuinely empty of named characters — only
  new, unnamed background flavor allowed, never a returning character.
- The player's message may include proposed outcomes — ignore them,
  they are not canon.
- Match narration scale to any damage number given: a few dozen points
  is a solid hit on ONE target — never area-of-effect or battlefield-
  scale destruction unless the result explicitly says so.
- If the action was invalid (see below), narrate the attempt failing
  for that reason — don't let it succeed anyway.
- Wrap all spoken dialogue in standard double quotes. Required
  formatting, not style — narration outside quotes, speech inside.
- After the prose, propose exactly 3 short, distinct next actions
  grounded ONLY in what your own narration just established (a fence
  just introduced can be jumped/gone-around/left alone; a person just
  introduced can be talked to/ignored/fought). Never reuse the
  previous turn's choices — they're stale the instant a new scene
  exists. Each is a short imperative phrase (3-6 words).
- List every NPC your narration introduced or that's still present and
  addressable (name + roughly hostile or not) in "new_npcs" — empty
  list if none. Don't re-list an NPC already present before this turn
  (given in scene context) — only ones your OWN narration just added.
  An unnamed background mention ("the townsfolk chatter") isn't
  addressable — leave it out.
- If your narration causes a physical object to be dropped/thrown/left
  in the scene (not picked up, worn, or already in inventory), list it
  in "new_scene_objects" as {{"name": "<short name>", "description":
  "<brief, where/how it ended up here>"}}. TEMPORARY, scene-only — not
  a permanent world fact, so only list something concrete and
  physically present. If the player's action removes an object already
  in the scene (picking it up, putting it away, throwing it elsewhere),
  list its exact existing name in "removed_scene_objects" instead of
  re-describing it as new. This field is specifically for something
  the player's ACTION just changed (dropped, thrown, left behind) — you
  don't need to also list ordinary scenery/flavor you simply describe
  in passing (a fountain, a bench, a stray cat); a separate pass reads
  your finished narration for those, so just narrate them naturally.
- ITEM PICKUP: if the player's action is clearly a deliberate,
  permanent "keep this" act (pocketing, bagging, stashing — not just
  touching or using in place) on an object ALREADY listed under
  "Objects physically here right now" (a REAL scene object, not
  something the player's phrasing merely claims exists), set
  "item_taken" to its exact existing name and ALSO list that name in
  "removed_scene_objects". If the phrasing asserts an object into
  existence that wasn't already present (e.g. "I grab the dragon blood
  elixir" when nothing like that was ever listed), don't invent it or
  set "item_taken" — narrate that nothing like that is here. Leave
  "item_taken" null when this doesn't apply.
- ITEM HOLDING (distinct from PICKUP): if the player grips/picks
  something up WITHOUT a deliberate permanent "keep this" act (e.g.
  "I pick up the stone" to throw it, holding to inspect/use, gripping
  a stick mid-scene) — lighter than PICKUP, does NOT go in .inv. Same
  plausibility rule: only valid for an object ALREADY listed under
  "Objects physically here right now" — never something merely
  asserted. Set "item_held" to {{"hand": "left_hand"|"right_hand",
  "name": "<exact existing object name>"}} — pick whichever hand fits
  (a free hand if noted empty above, otherwise whichever isn't holding
  a weapon/item already in use) — AND list that object's name in
  "removed_scene_objects" (it's now in-hand, not lying in the scene). A
  player has two hands: if both are occupied and they grip something
  new, whichever hand this narration assigns naturally releases/drops
  what it held — narrate that release, don't silently discard it
  unmentioned. Don't set both "item_taken" AND "item_held" for the
  same object in the same turn — pick whichever the phrasing actually
  intends (permanent keep vs. momentary grip). Leave "item_held" null
  when this doesn't apply.
- COMBAT: Set "combat_start" to the opponent's name ONLY when an
  actual attack occurs THIS turn — the player clearly attacks first
  ("I draw my sword and strike it"), OR a hostile creature/NPC already
  present attacks first (a wolf lunges and bites). Don't set it for: a
  creature merely present, watching, or acting threatening without
  striking; an incidental/non-violent action nearby (a child throwing
  a pebble in play, an animal fleeing); the player merely drawing a
  weapon or approaching without attacking; or any ambiguous case where
  a real attack didn't clearly happen. When in doubt, don't start
  combat — narrate tension and let a following turn confirm it. Leave
  "combat_start" null whenever this doesn't apply, including every
  turn during an already-active fight (the battle engine, not you,
  resolves individual exchanges once combat has started).
- SPECIAL EVENT: Only during an already-active fight, and only for a
  genuinely major interruption from OUTSIDE the fight — a god or vastly
  stronger being descends, a third/bigger monster crashes in and drags
  attention away, a natural disaster splits the scene apart. NOT for
  ordinary combat flow (someone getting hurt, a near-win/loss, dramatic
  phrasing) — reserved for something that would obviously suspend the
  fight for any onlooker. When it genuinely applies, set
  "special_event" true and "special_event_resolution" to "resume" (the
  fight breaks off but its consequences carry into whatever's next) or
  "abandon" (the fight is over for good, nothing carries forward — the
  opponent is destroyed or removed by the interrupting force). Leave
  both null/false every other turn.
- ONLY if this turn contains the player making an explicit promise/vow
  to a present NPC, or a clear betrayal (breaking a prior promise,
  backstabbing an ally, lying to someone who trusted them), set
  "notable_npc_event" to {{"npc_name": "<the NPC involved, matching
  their existing name exactly>", "text": "<one short factual sentence,
  third person, past tense, e.g. 'promised to return the sword' or
  'betrayed the elder's trust after being asked to protect the
  village'>"}}. Otherwise leave it null. Don't set this for ordinary
  dialogue or combat — this becomes a PERMANENT NPC memory, so it must
  be genuinely significant, not routine conversation.

Respond ONLY with JSON, no other text:
{{"narration": "<the 2-4 sentences of prose, dialogue included>",
 "choices": ["<choice 1>", "<choice 2>", "<choice 3>"],
 "new_npcs": [{{"name": "<short name/description>", "hostile": false}}],
 "new_scene_objects": [{{"name": "<short name>", "description": "<brief>"}}],
 "removed_scene_objects": ["<exact existing object name>"],
 "item_taken": null,
 "item_held": null,
 "trial_start": null,
 "trial_weapon": null,
 "combat_start": null,
 "special_event": false,
 "special_event_resolution": null,
 "notable_npc_event": null}}

EXAMPLE — this is the target quality and shape for the narration
field. Match this level of sensory detail, pacing, and voice, not
generic summary prose:

Input situation: player watches a battle unfold at the village gate,
a general leads the defense.

Good narration:
The sky went pale at the demon's approach. "Damn — who let the
kabane in!" a soldier barked, voice cracking. Villagers clutched
their children close, certain this night might be their last. The
general simply raised his spear. "For Valhalla."

Bad narration (too flat/summary, avoid this):
You watch the battle begin. The soldiers are scared but the general
leads them into combat.

Good choices for that scene: ["Draw your weapon and help", "Pull nearby villagers to safety", "Hang back and watch"]
{trial_block}"""

def _format_for_whatsapp(raw: str) -> str:
    """
    Splits narration text into WhatsApp-formatted lines: plain
    sentences become blockquote lines (>), and double-quoted spoken
    dialogue becomes bold (*"..."*) on its own line. Relies on the
    model wrapping spoken lines in "double quotes" (per
    _narration_system()'s instruction) — any text outside quotes is
    treated as narration. If the model emits no quotes at all, the
    whole reply just becomes blockquote narration, which still
    renders fine — this never raises or drops content.
    """
    parts = re.split(r'("[^"]+")', raw)
    lines = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if part.startswith('"') and part.endswith('"'):
            lines.append(f"*{part}*")
        else:
            for sentence in re.split(r"(?<=[.!?])\s+", part):
                sentence = sentence.strip()
                if sentence:
                    lines.append(f"> {sentence}")
    return "\n\n".join(lines)

def narrate_result(action: str, validation: dict, resolution: dict,
                    world_state: dict, call_groq_fn=call_groq) -> dict:
    """
    Final stage: turn the validated action + mechanical result into
    prose, plus exactly 3 fresh next-action choices grounded in that
    prose (see _narration_system() — choices are regenerated every
    turn, never carried over from a prior scene).

    Returns {"reply": str, "choices": list[str], "new_npcs": list,
    "trial_start": str|None, "trial_weapon": str|None,
    "npc_event": {"npc_name": str, "text": str, "pinned": bool}|None}
    — trial_start is only ever non-None when world_state["offers_trial"]
    permitted it for this location AND the model recognized clear
    acceptance intent in the player's action; see _narration_system()'s
    TRIAL AVAILABLE HERE block for the actual recognition rule.
    npc_event is derived mechanically from resolution["target_name"]
    (a combat hit that connected against a real target) — never an
    LLM judgment call, see _derive_npc_event() below.
    """
    if not validation["valid"]:
        # Fail-safe: narrate the failure directly without an LLM
        # call needed, since the fact pattern is simple and fixed.
        # No choices — nothing new was established to choose from.
        return {"reply": validation["reason"], "choices": [], "new_npcs": [],
                "trial_start": None, "trial_weapon": None, "npc_event": None,
                "notable_npc_event": None, "new_scene_objects": [], "removed_scene_objects": [],
                "combat_start": None, "special_event": False,
                "special_event_resolution": None}

    offers_trial = world_state.get("offers_trial")

    context_lines = [
        f"=== CURRENT LOCATION (where the player IS right now) ===",
        f"Location: {world_state.get('location', 'unknown')}",
    ]

    # Full District/Area path for HERE — real data from location_path(),
    # not narrator-inferred. Gives the model something concrete to
    # compare against reachable destinations' own paths below when
    # resolving directional phrasing ("go out", "head further in",
    # "go back") instead of guessing from bare place names alone.
    here_path = world_state.get("location_path") or {}
    if here_path.get("district") and here_path["district"] != "---":
        context_lines.append(
            f"You are in District: {here_path['district']}, "
            f"Area: {here_path.get('area_name', '---')}"
        )
    elif here_path.get("area_name") and here_path["area_name"] != "---":
        context_lines.append(f"You are in Area: {here_path['area_name']}")

    loc_details = world_state.get("location_details") or {}
    if loc_details.get("description"):
        context_lines.append(f"Known facts about this location: {loc_details['description']}")
    if loc_details.get("landmarks"):
        context_lines.append(f"Landmarks here: {', '.join(loc_details['landmarks'])}")

    existing_npcs = world_state.get("npcs", [])
    if existing_npcs:
        names = ", ".join(npc["name"] for npc in existing_npcs)
        context_lines.append(f"NPCs physically here right now (do not re-list in new_npcs): {names}")
        # Durable per-player memory for NPCs present in this scene —
        # separate mechanism from "PAST EVENTS" below. This is
        # pinned+recent only (flat cost regardless of relationship
        # length); full archive is never read here. See database.py's
        # get_npc_events() / npc_events table.
        for npc in existing_npcs:
            events = npc.get("events") or []
            if events:
                context_lines.append(f"What you remember about {npc['name']}:")
                for ev in events:
                    context_lines.append(f"  - {ev}")
    else:
        context_lines.append(
            "NPCs physically here right now: none. This location is "
            "empty of named characters — anyone from a past turn "
            "(including PAST EVENTS below) is NOT here and must not "
            "appear."
        )

    scene_objects = world_state.get("scene_objects", [])
    if scene_objects:
        obj_names = rpg_scene.names_for_context(scene_objects)
        context_lines.append(
            f"Objects physically here right now (do not re-list in new_scene_objects): {obj_names}"
        )
    else:
        context_lines.append("Objects in this scene: none.")

    holding = world_state.get("holding", {})
    held_bits = []
    for hand in ("left_hand", "right_hand"):
        item = holding.get(hand)
        held_bits.append(f"{hand}: {item}" if item else f"{hand}: empty")
    context_lines.append(f"Currently holding — {', '.join(held_bits)}")

    recent_history = world_state.get("history", [])[-2:]
    if recent_history:
        context_lines.append("")
        context_lines.append("=== PAST EVENTS (for continuity/context ONLY) ===")
        context_lines.append(
            "These already happened and likely reference a DIFFERENT location than "
            "CURRENT LOCATION above — the player has moved on since. Use this ONLY "
            "to understand references like pronouns or follow-up questions "
            "(\"war?\", \"remember my promise\"). Any NPC, animal, or object named "
            "here that is NOT also listed in the NPCs/Objects lines above is GONE — "
            "do not bring them back into this scene, do not have them speak or "
            "react, do not describe them as still present. Presence is decided "
            "ONLY by the CURRENT LOCATION section above. Do not re-narrate these "
            "events."
        )
        for turn in recent_history:
            context_lines.append(f"  - player did: {turn.get('action', '')}")
            context_lines.append(f"    result: {turn.get('reply', '')}")
        context_lines.append("")

    context_lines.append(f"Validated action (what the player is doing THIS turn): {action}")

    if resolution["mechanical"]:
        if resolution["damage"] == -1:
            context_lines.append("Mechanical result: the action MISSED / had no effect.")
        else:
            context_lines.append(
                f"Mechanical result: skill '{resolution['skill_name']}' "
                f"dealt {resolution['damage']} damage to the target "
                f"(type multiplier: {resolution['type_mult']})."
            )
    else:
        context_lines.append("Mechanical result: none (non-combat action).")

    user_context = "\n".join(context_lines)

    # ── Mechanical npc_event trigger ────────────────────────────
    # Deliberately NOT an AI judgment call (see design discussion:
    # asking the model to decide "was this memorable" every turn is
    # an extra, unreliable, costly step). Instead: a fixed, narrow
    # rule — a combat hit that actually connected, against a named
    # target, is unambiguously worth remembering. Everything else
    # (narrative flavor, misses, non-combat interactions) derives no
    # event for now; broader categories (quest milestones, explicit
    # promises/betrayals) are a later pass on top of this same rule,
    # not a redesign of it.
    def _derive_npc_event():
        # Uses resolution["target_name"] (the NPC resolve_action
        # actually resolved combat against), NOT the raw extraction
        # target text — that can be null even when a real hit landed
        # (e.g. "I attack with Fireball" against a single hostile
        # NPC, auto-targeted with no name in the player's message).
        target_name = resolution.get("target_name")
        if not target_name:
            return None
        if not resolution.get("mechanical"):
            return None
        if resolution.get("damage") in (None, -1):
            return None  # missed / no effect — nothing landed
        return {
            "npc_name": target_name,
            "text": f"was hit with {resolution.get('skill_name', 'an attack')} "
                    f"by this player ({resolution['damage']} damage)",
            "pinned": False,
        }

    npc_event = _derive_npc_event()

    def _fallback():
        # Deterministic fallback (no LLM available, or it failed) —
        # same plain sentence as before. No choices: there's no
        # generated scene to ground them in, and inventing generic
        # ones (e.g. "look around") would be exactly the kind of
        # unearned narration the pipeline is designed to avoid.
        # trial_start is always None here — recognizing trial-accept
        # intent needs the LLM call, there's no deterministic rule
        # for it, so a failed/unavailable call just can't offer it
        # this turn (player can simply try again next message).
        if resolution["mechanical"] and resolution["damage"] not in (None, -1):
            text = f"You act. {resolution['skill_name']} connects for {resolution['damage']} damage."
        elif resolution["mechanical"] and resolution["damage"] == -1:
            text = "You act, but it doesn't connect."
        else:
            text = f"You {action.lower().lstrip('i ')}."
        return {"reply": _format_for_whatsapp(text), "choices": [], "new_npcs": [],
                "trial_start": None, "trial_weapon": None, "npc_event": npc_event,
                "notable_npc_event": None, "new_scene_objects": [], "removed_scene_objects": [],
                "combat_start": None, "special_event": False,
                "special_event_resolution": None}

    if call_groq_fn is None:
        return _fallback()

    # max_tokens raised from the 300 default — narration has to fit
    # 2-4 sentences of prose PLUS 3 choice strings PLUS any new_npcs
    # PLUS the trial fields into one JSON object; 300 was cutting
    # generation off mid-object on longer scenes, which is what
    # actually produced most of the "raw JSON dumped as the reply"
    # bugs seen in testing — not a JSON-mode problem on its own.
    #
    # model=GROQ_NARRATION_MODEL: narration's ~4.2k-token prompt is
    # the single slowest call in the whole .rpg pipeline (measured
    # 15s on GROQ_MODEL/120b — see call_groq's timeout comment). 20b
    # runs ~2x the decode speed for the same JSON-mode/reasoning_effort
    # call shape — real speed win, real prose-quality tradeoff.
    reply = call_groq_fn(_narration_system(offers_trial), user_context,
                          max_tokens=700, json_mode=True, model=GROQ_NARRATION_MODEL)
    if not reply:
        # Groq call failed (rate limit, timeout, API error, etc.)
        # rather than being unavailable — degrade the same way.
        return _fallback()

    try:
        parsed = extract_json(reply)
        if parsed is None:
            raise ValueError("no JSON object found")
        narration = parsed.get("narration", "").strip()
        choices = parsed.get("choices", [])
        if not isinstance(choices, list):
            choices = []
        choices = [str(c).strip() for c in choices if str(c).strip()][:3]

        new_npcs = parsed.get("new_npcs", [])
        if not isinstance(new_npcs, list):
            new_npcs = []
        clean_npcs = []
        for npc in new_npcs:
            if not isinstance(npc, dict):
                continue
            npc_name = str(npc.get("name", "")).strip()
            if not npc_name:
                continue
            clean_npcs.append({"name": npc_name, "hostile": bool(npc.get("hostile", False))})

        new_scene_objects = parsed.get("new_scene_objects", [])
        if not isinstance(new_scene_objects, list):
            new_scene_objects = []
        clean_new_objects = []
        for obj in new_scene_objects:
            if not isinstance(obj, dict):
                continue
            obj_name = str(obj.get("name", "")).strip()
            if not obj_name:
                continue
            clean_new_objects.append({
                "name": obj_name,
                "description": str(obj.get("description", "")).strip(),
            })

        removed_scene_objects = parsed.get("removed_scene_objects", [])
        if not isinstance(removed_scene_objects, list):
            removed_scene_objects = []
        clean_removed_objects = [str(n).strip() for n in removed_scene_objects if str(n).strip()]

        # trial_start is only ever honored if this location actually
        # offers that trial (offers_trial) — a hallucinated or
        # mismatched value from the model is discarded here rather
        # than trusted outright, same defensive spirit as choices/
        # new_npcs being type/shape-checked above. trial_weapon only
        # makes it through when trial_start == "warrior" too — it's
        # meaningless for the mage trial.
        trial_start = parsed.get("trial_start")
        if trial_start != offers_trial:
            trial_start = None
        trial_weapon = parsed.get("trial_weapon")
        if trial_start != "warrior" or not isinstance(trial_weapon, str):
            trial_weapon = None
        elif trial_weapon.strip().lower() not in (
            "sword", "dagger", "spear", "axe", "mace", "shield", "bow"
        ):
            trial_weapon = None
        else:
            trial_weapon = trial_weapon.strip().lower()

        # combat_start: only trust it if it names an NPC that's
        # actually present this turn (same defensive discipline as
        # trial_start/notable_npc_event above) — a hallucinated
        # opponent name would otherwise start a fight against nothing.
        # Only honored when NOT already mid-fight — the router is the
        # one that actually knows whether a battle is active, so it
        # re-checks this; this is just the narrator-side sanity check.
        combat_start = parsed.get("combat_start")
        if isinstance(combat_start, str):
            combat_start = combat_start.strip()
            present_names_for_combat = {npc["name"] for npc in existing_npcs} | {
                npc["name"] for npc in clean_npcs
            }
            if combat_start not in present_names_for_combat:
                combat_start = None
        else:
            combat_start = None

        # special_event: only meaningful alongside a valid resolution
        # — a bare true with no resolution, or a resolution without
        # special_event being true, is discarded outright rather than
        # guessed at. No tag tracking — an interrupted fight's
        # consequences (HP/wounds) carry forward as ordinary
        # narrative fact (see rpg_battle.extract_interrupted_battle_
        # summary), not as a resumable state keyed by name.
        special_event = bool(parsed.get("special_event"))
        special_event_resolution = parsed.get("special_event_resolution")
        if special_event_resolution not in ("resume", "abandon"):
            special_event = False
            special_event_resolution = None
        if not special_event:
            special_event_resolution = None

        # notable_npc_event: only trust it if it names an NPC that's
        # actually present this turn (same defensive discipline as
        # trial_start above) — a hallucinated name would otherwise
        # create a memory for an NPC that doesn't exist. pinned=True
        # unconditionally: a promise/betrayal is exactly the kind of
        # thing that should never age out of view, unlike the
        # mechanical combat-hit events above.
        notable_npc_event = None
        raw_notable = parsed.get("notable_npc_event")
        if isinstance(raw_notable, dict):
            notable_name = str(raw_notable.get("npc_name", "")).strip()
            notable_text = str(raw_notable.get("text", "")).strip()
            present_names = {npc["name"] for npc in existing_npcs}
            if notable_name and notable_text and notable_name in present_names:
                notable_npc_event = {
                    "npc_name": notable_name, "text": notable_text, "pinned": True,
                }

        # item_taken: only trust it if it names an object that was
        # ALREADY present in the scene at the START of this turn
        # (world_state's pre-turn scene_objects) — same plausibility
        # gate as trial_start/combat_start/travel_target: the
        # player's own phrasing asserting an item into existence is
        # never sufficient on its own (see the design doc — the
        # "dragon blood elixir" problem). A hallucinated or
        # self-asserted item name is discarded here rather than
        # silently added to .inv. Router (rpg.py) is the one that
        # actually mutates soulbound["inventory"]; this is just the
        # narrator-side sanity check, same division of responsibility
        # as combat_start/trial_start above.
        # item_taken: only trust it if it names an object that was
        # ALREADY present — either in the scene, OR already in the
        # player's hand (world_state["holding"]), at the START of
        # this turn. The holding case matters for promotion: "I pick
        # up the stone" (tier 2, now in hand) followed later by "I
        # keep the stone in my inventory" (tier 3) needs the stone to
        # still validate even though it's no longer sitting in
        # scene_objects — it moved into holding, not out of
        # existence. from_hand records which hand it came from (None
        # if it came straight from the scene instead), so router can
        # clear that hand slot on promotion rather than leaving the
        # item duplicated in both .inv and holding at once.
        carry_refusal = None  # set by the item_taken/item_held gates below
        item_taken = parsed.get("item_taken")
        if isinstance(item_taken, str):
            item_taken = item_taken.strip()
            holding_this_turn = world_state.get("holding", {})
            from_hand = None
            for hand, held_name in holding_this_turn.items():
                if held_name == item_taken:
                    from_hand = hand
                    break
            # Match loosely against the scene store ("the cup" == "cup",
            # "cups" == "cup") instead of exact strings, and refuse
            # anything too heavy/fixed to carry. A refusal is reported
            # back via carry_refusal so the story doesn't claim a pickup
            # the game then silently drops.
            scene_hits = rpg_scene.find(world_state.get("scene_objects", []), item_taken)
            if from_hand is None:
                if not scene_hits:
                    item_taken = None
                elif not rpg_scene.can_carry(scene_hits[0]):
                    carry_refusal = rpg_scene.carry_refusal(scene_hits[0])
                    item_taken = None
                else:
                    # Normalize to the store's own name so the router's
                    # removed_scene_objects / inventory use one spelling.
                    item_taken = scene_hits[0]["name"]
        else:
            item_taken = None
            from_hand = None

        # item_held: same plausibility gate as item_taken (must be a
        # REAL pre-existing scene object, never player-asserted), plus
        # a valid hand slot. Unlike item_taken, this doesn't touch
        # .inv at all — router (rpg.py) writes it into
        # soulbound["holding"][hand] instead, a lighter/more easily
        # lost tier than real inventory. Malformed shape (missing
        # hand/name, bad hand value, or a name that wasn't really
        # present) is discarded outright, same defensive spirit as
        # every other narrator-reported field here.
        item_held = parsed.get("item_held")
        if isinstance(item_held, dict):
            held_hand = str(item_held.get("hand", "")).strip()
            held_name = str(item_held.get("name", "")).strip()
            held_hits = rpg_scene.find(world_state.get("scene_objects", []), held_name)
            if held_hand not in ("left_hand", "right_hand") or not held_hits:
                item_held = None
            elif not rpg_scene.can_carry(held_hits[0]):
                carry_refusal = rpg_scene.carry_refusal(held_hits[0])
                item_held = None
            else:
                item_held = {"hand": held_hand, "name": held_hits[0]["name"]}
        else:
            item_held = None

        if not narration:
            return _fallback()
        # The narrator may have already written "you pick up the pillar"
        # before the weight gate refused it. Append the in-fiction reason
        # so the story and the game state agree, instead of silently
        # dropping the pickup and leaving the player confused.
        if carry_refusal:
            narration = f"{narration}\n\n> {carry_refusal}"
        return {"reply": _format_for_whatsapp(narration), "choices": choices,
                "new_npcs": clean_npcs, "trial_start": trial_start,
                "trial_weapon": trial_weapon, "npc_event": npc_event,
                "notable_npc_event": notable_npc_event,
                "new_scene_objects": clean_new_objects,
                "removed_scene_objects": clean_removed_objects,
                "item_taken": item_taken,
                "item_taken_from_hand": from_hand,
                "item_held": item_held,
                "combat_start": combat_start,
                "special_event": special_event,
                "special_event_resolution": special_event_resolution}
    except (AttributeError, ValueError):
        # Model didn't return valid JSON (older prompt behavior, or a
        # malformed reply) — treat the whole thing as plain narration
        # text rather than losing the reply outright. No choices/NPCs,
        # same reasoning as the invalid-premise path above. trial_start
        # also None — can't trust a field we couldn't even parse JSON
        # around.
        print(f"[RPG NARRATE] WARNING: non-JSON reply: {reply[:200]}", flush=True)
        return {"reply": _format_for_whatsapp(reply), "choices": [], "new_npcs": [],
                "trial_start": None, "trial_weapon": None, "npc_event": npc_event,
                "notable_npc_event": None, "new_scene_objects": [], "removed_scene_objects": [],
                "combat_start": None, "special_event": False,
                "special_event_resolution": None}
