"""
router/rpg_cmds/actions.py - Pending-class confirmation and the main `.rpg <free text>` turn (movement, item pickup/hold, trial start, combat start).

Moved verbatim out of RpgManager._dispatch (router/rpg.py, original lines 1059-1327).
`handle(self, ctx)` runs the block in the same position it had in the old if-chain: it returns the
reply (or None, which ends dispatch), or NOT_HANDLED to fall through to the next block.
"""

import json
import rpg_battle
import rpg_movement
import townia_trials as trials
from rpg_engine import handle_rpg_action
from ._common import NOT_HANDLED, _with_choices


def handle(self, ctx):
    sender, cmd, rest, db, session, low_rest, pending_class, pending_extra = ctx.sender, ctx.cmd, ctx.rest, ctx.db, ctx.session, ctx.low_rest, ctx.pending_class, ctx.pending_extra

    # ── Class confirmation — .rpg yes / .rpg no / .rpg <text> ─
    # A weapon trial can grant more than one class at once (bow
    # -> Archer + Scout) — pending_class is the primary one
    # (becomes soulbound["class"], the single displayed/active
    # class, unchanged shape for .status etc), pending_class_extra
    # holds any additional ones, all folded into the running
    # soulbound["classes"] list either way so nothing granted is
    # ever silently dropped.
    pending_class = session.flags.get("pending_class")
    pending_extra = session.flags.get("pending_class_extra", [])
    if cmd == ".rpg" and pending_class:
        if low_rest == "yes":
            session.soulbound["class"] = pending_class
            session.soulbound.setdefault("classes", [])
            for cls in [pending_class] + pending_extra:
                if cls not in session.soulbound["classes"]:
                    session.soulbound["classes"].append(cls)
            # Weapon(s) come from CLASS_STARTING_WEAPON, keyed by
            # class name — not by which trial was actually played.
            # E.g. clearing the bow trial grants Archer + Scout,
            # which resolves to bow AND dagger, since a Scout is
            # always a dagger user regardless of which trial
            # unlocked the class. Mage isn't in the table at all,
            # so it grants nothing here — expected, not a bug.
            granted = trials.grant_starting_weapon(
                session.soulbound, [pending_class] + pending_extra
            )
            weapon_note = ""
            if granted:
                weapon_note = "\n\n" + "\n".join(
                    f'> You have obtained a *{weapon}*.' for weapon in granted
                ) + "\nUse *.inv* to see owned items."
            del session.flags["pending_class"]
            session.flags.pop("pending_class_extra", None)
            session.save(db)
            all_gained = ", ".join([pending_class] + pending_extra)
            return (
                f'> Your class is now *{all_gained}*.{weapon_note}'
                '\n\nUse *.status* anytime to check your class.'
            )
        if low_rest == "no":
            del session.flags["pending_class"]
            session.flags.pop("pending_class_extra", None)
            session.save(db)
            return "> No class change. You can try another trial anytime."
        # .rpg <anything else> here — free text response instead
        # of a plain yes/no. Doesn't force a decision; just lets
        # it fall through to normal narration below, same as any
        # other .rpg action, since a player might reasonably want
        # to ask a question before committing.
        del session.flags["pending_class"]
        session.flags.pop("pending_class_extra", None)

    if cmd == ".rpg":
        if not rest.strip():
            return "Usage: .rpg <what you do> — e.g. .rpg I look around"

        # ── .rpg <no.> shorthand — resolves against whatever
        # choices the PREVIOUS turn generated (session.flags
        # ["_choices"], refreshed after every .rpg action below —
        # not just the opening scene). Falls through to normal
        # free-text handling on a number outside that list, or if
        # no choices exist, since a bare number is also valid
        # in-world text (e.g. counting something) and shouldn't
        # be treated as a broken command. ──
        stripped = rest.strip()
        choices = session.flags.get("_choices")
        if choices and stripped.isdigit():
            idx = int(stripped) - 1
            if 0 <= idx < len(choices):
                rest = choices[idx]

        # ── Movement is classified and resolved entirely inside
        # handle_rpg_action now (rpg_intent.extract_intent's
        # "move" type -> rpg_movement.handle_move_intent) — see
        # rpg_engine.py's handle_rpg_action docstring for the full
        # cutover note. No separate travel_target post-processing
        # here anymore; by the time `result` comes back below, a
        # move turn has already been fully applied (session
        # mutated, choices set) if it succeeded. ──

        # ── Journey: "Continue journey" (choice 1 while en route) or
        # "keep going" etc. advances one leg, deterministically — no
        # intent-classifier call, the code already knows what it means.
        if session.flags.get("_journey") and rpg_movement.is_continue_text(rest):
            leg = rpg_movement.continue_journey(session, db, handle_rpg_action)
            if leg.moved:
                reply = rpg_movement.format_journey_reply(leg)
            else:
                reply = f"*TRAVEL LOG* not moved: {leg.reason or 'unknown reason'}"
            leg_choices = rpg_movement.with_continue_choice(
                session, session.flags.get("_choices", []))
            session.flags["_choices"] = leg_choices
            session.save(db)
            if leg.moved:
                self._queue_scene_extraction(
                    sender, db, {"reply": leg.arrival_reply, "choices": leg_choices})
            return _with_choices(reply, leg_choices)

        result = handle_rpg_action(rest, session.to_world_state_dict(db), db=db)
        session.apply_engine_result(result, db)
        # Always overwrite with THIS turn's choices (even an empty
        # list on an invalid/fallback reply) — stale choices from
        # a previous scene must never linger and get misapplied
        # to a later bare number. While a journey is active,
        # "Continue journey" is injected as choice 1.
        result["choices"] = rpg_movement.with_continue_choice(
            session, result.get("choices", []))
        session.flags["_choices"] = result["choices"]

        # ── Item pickup, recognized via narrator intent (see
        # rpg_engine._narration_system's ITEM PICKUP block) — same
        # pattern as before: already validated inside
        # narrate_result against this turn's REAL scene_objects
        # (not the player's bare claim), so item_taken here is
        # trustworthy. Doesn't early-return — picking something up
        # doesn't preempt the rest of the turn's narration, it's
        # folded into the same reply.
        # 25-slot cap per design discussion (Townia hidden-events
        # doc) — not enforced yet elsewhere either; flagged there,
        # not re-solved here.
        item_taken_name = result.get("item_taken")
        if item_taken_name and session.soulbound is not None:
            session.soulbound.setdefault("inventory", [])
            if item_taken_name not in session.soulbound["inventory"]:
                session.soulbound["inventory"].append(item_taken_name)
            # If this item was promoted straight out of a hand
            # (tier 2 -> tier 3 — e.g. "I keep the stone I'm
            # holding"), clear that hand slot so it isn't left
            # duplicated in both .inv and holding at once.
            from_hand = result.get("item_taken_from_hand")
            if from_hand and session.soulbound.get("holding", {}).get(from_hand) == item_taken_name:
                session.soulbound["holding"][from_hand] = None

        # ── Item holding (tier 2 — lighter than .inv, see
        # object-persistence design doc). 2 hand slots, matching
        # soulbound.py's existing left_hand/right_hand combat
        # loadout naming. Already validated inside narrate_result
        # against real scene_objects + a real hand key, so
        # item_held here is trustworthy. Overwrites whichever hand
        # is named — per design, picking up something new in an
        # already-occupied hand naturally releases whatever was
        # there before (the narrator is instructed to narrate that
        # release, not silently drop it unmentioned).
        item_held = result.get("item_held")
        if item_held and session.soulbound is not None:
            session.soulbound.setdefault("holding", {})
            session.soulbound["holding"][item_held["hand"]] = item_held["name"]

        # ── Trial start, recognized via narrator intent (see
        # rpg_engine._narration_system's TRIAL AVAILABLE HERE
        # block) rather than a slash command — never overwrite an
        # already-in-progress trial (the player is mid-fight
        # somewhere else entirely if "trial" is already set; a
        # stale/re-triggered intent match should not clobber it).
        trial_start = result.get("trial_start")
        if trial_start and "trial" not in session.flags:
            if trial_start == "warrior":
                trial_weapon = result.get("trial_weapon")
                if trial_weapon in trials.WARRIOR_WEAPONS:
                    # Weapon named in the same breath as accepting
                    # the trial — skip straight into that weapon's
                    # mechanic, same phases the router's dedicated
                    # blocks below already handle.
                    mechanic = trials.WEAPON_MECHANIC[trial_weapon]
                    if mechanic == "fight":
                        session.flags["trial"] = {
                            "class": "warrior", "phase": "fighting",
                            "weapon": trial_weapon,
                            "opponent_hp": trials._opponent_max_hp(trial_weapon),
                        }
                    elif mechanic == "shield":
                        session.flags["trial"] = {
                            "class": "warrior", "phase": "shielding",
                            "weapon": trial_weapon,
                            "blocks": 0, "hits_taken": 0,
                            "_pending_direction": trials._weighted_random_direction(),
                        }
                    elif mechanic == "bow":
                        session.flags["trial"] = {
                            "class": "warrior", "phase": "shooting",
                            "weapon": trial_weapon, "hits": 0,
                            "_shot": trials.roll_bow_shot(),
                        }
                else:
                    session.flags["trial"] = {"class": "warrior", "phase": "choose_weapon"}
            elif trial_start == "mage":
                inc_data = trials.start_mage_incantation()
                session.flags["trial"] = {
                    "class": "mage",
                    "phase": "shown",
                    "incantation_data": inc_data,
                    "attempts": 0,
                }
            elif trial_start == "summoner":
                # Phase 1 only — see townia_trials.py's Summoner
                # section. Player hasn't opened any species list
                # yet; "rolls" holds per-player trait data for
                # slots the player HAS opened so far this trial
                # attempt, keyed by species (populated lazily by
                # the ".rpg <species> <no.>"/species-name-only
                # handling below, not all up front).
                session.flags["trial"] = {
                    "class": "summoner",
                    "phase": "choosing_species",
                    "rolls": {},
                }
                # Species picker as a real WhatsApp list message
                # (tap-to-select bottom sheet), per the design
                # doc's LOCKED presentation flow — NOT plain text.
                # __LIST__<json>__/LIST__ is a marker in the same
                # spirit as __IMG__/__HUD__ elsewhere: index.js's
                # sendAny() detects it and builds the real
                # listMessage via the proven manual-binary-node
                # approach (see index.js's old .listtest command,
                # which this reuses rather than duplicates), with
                # a graceful plain-text fallback if the relay
                # fails. A player who taps a row gets that row's
                # title back as an ordinary text reply — the
                # existing bare-species-name handling in the block
                # above already accepts that with no changes.
                list_payload = trials.render_species_list_payload()
                result["reply"] = (
                    result["reply"] + "\n\n"
                    "__LIST__" + json.dumps(list_payload) + "__/LIST__"
                )
                # Suppress the normal narrator "Recommended choices"
                # block for THIS turn specifically — the list
                # message above IS the choice-picker for this beat,
                # and showing both would be two competing pickers
                # for the same decision (species). Every later
                # summoner-trial turn goes through the dedicated
                # ".rpg <species>..." handling further up this
                # file, not this narrator path, so this only
                # affects the single opening turn.
                result["choices"] = []

        # ── Real combat start, recognized via narrator intent
        # (see rpg_engine._narration_system's COMBAT block) — an
        # actual attack happened this turn, either the player's
        # or a present hostile's. Never starts a fight on top of
        # an already-active trial (mutually exclusive minigames)
        # or an already-active battle (the "Active real fight"
        # intercept earlier in this function would have caught
        # this turn already if one were running, but re-checking
        # here costs nothing and guards against any future
        # reordering of these blocks). The opponent's actual
        # stats are NEVER the narrator's to invent — see
        # rpg_battle.start_story_battle/generate_encounter: only
        # this location's hand-authored monster_pool, leveled and
        # rarity-rolled server-side. If this location has no pool
        # (a safe town spot, say, where combat_start should never
        # have fired in the first place), start_story_battle
        # returns a plain error string instead of a state dict —
        # relayed to the player as-is rather than silently
        # swallowed, since it signals a narrator/location mismatch
        # worth noticing.
        combat_start = result.get("combat_start")
        if (combat_start and "trial" not in session.flags
                and not rpg_battle.load_battle(db, sender)):
            player_level = session.soulbound.get("level", 1) if session.soulbound else 1
            # Real combat uses whatever's actually equipped (see
            # .equip) — not a random pick like .rpg sim. No
            # equipped weapon (fresh character, no class yet)
            # falls back to None, which start_story_battle/
            # build_player_combatant still resolve as a random
            # WEAPON_TABLES pick; that's a placeholder until bare-
            # handed/unarmed combat is designed, not a deliberate
            # choice to randomize for classed characters.
            equipped_weapon = (
                session.soulbound.get("equipped") if session.soulbound else None
            )
            battle_state = rpg_battle.start_story_battle(
                session.soulbound, player_level, session.location_id,
                weapon_key=equipped_weapon,
            )
            if isinstance(battle_state, str):
                session.save(db)
                return _with_choices(f"{result['reply']}\n\n{battle_state}", [])
            rpg_battle.save_battle(db, sender, battle_state)
            session.flags["_choices"] = []
            session.save(db)
            return _with_choices(
                f"{result['reply']}\n\n{rpg_battle.render_start(battle_state)}", []
            )

        session.save(db)
        self._queue_scene_extraction(sender, db, result)
        return _with_choices(result["reply"], result.get("choices", []))
    return NOT_HANDLED
