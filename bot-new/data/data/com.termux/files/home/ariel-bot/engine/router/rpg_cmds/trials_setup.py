"""
router/rpg_cmds/trials_setup.py - Mage trial (recast / give up), Summoner species picker, Warrior weapon choice.

Moved verbatim out of RpgManager._dispatch (router/rpg.py, original lines 651-886).
`handle(self, ctx)` runs the block in the same position it had in the old if-chain: it returns the
reply (or None, which ends dispatch), or NOT_HANDLED to fall through to the next block.
"""

import npc
import townia_trials as trials
from ._common import NOT_HANDLED, _maybe_fire_mage_delete


def handle(self, ctx):
    parts, cmd, rest, db, session, low_rest, active_trial = ctx.parts, ctx.cmd, ctx.rest, ctx.db, ctx.session, ctx.low_rest, ctx.active_trial

    # ── Mage trial — early pass (recast correct before the
    # auto-delete fires) or normal recast after "now you try" ──
    active_trial = session.flags.get("trial")
    if (cmd == ".rpg" and active_trial
            and active_trial.get("class") == "mage"
            and active_trial.get("phase") in ("shown", "awaiting_recast")):
        # Reactive deadline check (see _maybe_fire_mage_delete's
        # docstring for why this replaces a real timer) — if the
        # 9-15s window already passed, this fires the "words
        # fade... now you try" notice BEFORE evaluating whatever
        # the player just sent, since that message might BE their
        # recast attempt, arriving right as the window closes.
        delete_notice = _maybe_fire_mage_delete(session, low_rest)
        active_trial = session.flags["trial"]  # re-fetch: may have
                                                 # just been mutated
                                                 # in place above

        inc_data = active_trial["incantation_data"]
        recast = rest.strip()

        if trials.incantation_matches(inc_data["incantation"], recast):
            early = not inc_data.get("delete_fired")
            del session.flags["trial"]
            session.flags["pending_class"] = "mage"
            session.save(db)
            notice_prefix = f"{delete_notice}\n\n" if delete_notice else ""
            if early:
                return (
                    f"{notice_prefix}"
                    '> The elder blinks, genuinely caught off guard.\n\n'
                    '*"...Well. I wasn\'t expecting that. Impressive — '
                    'you have the makings of a mage."*\n\n'
                    'Would you like to change your class to *"Mage"*?\n'
                    "Reply with *.rpg yes*, *.rpg no*, or *.rpg <text>*"
                )
            return (
                f"{notice_prefix}"
                '> You recall the words perfectly.\n\n'
                '*"Well done. The mana answers you."*\n\n'
                'Would you like to change your class to *"Mage"*?\n'
                "Reply with *.rpg yes*, *.rpg no*, or *.rpg <text>*"
            )

        # Wrong recast — only counts as a real attempt (and
        # advances the retry counter / rest-suggestion check)
        # once the words have actually been shown and deleted;
        # a wrong guess typed WHILE still shown doesn't burn an
        # attempt, since the player could just still be reading.
        if active_trial["phase"] == "awaiting_recast":
            active_trial["attempts"] = active_trial.get("attempts", 0) + 1
            session.flags["trial"] = active_trial
            session.save(db)

            suggest_rest = (
                active_trial["attempts"] % trials.REST_SUGGESTION_EVERY == 0
            )
            base = f"{delete_notice}\n\n" if delete_notice else ""
            base += (
                '> The elder shakes her head.\n\n'
                '*"Not quite. The words matter — try to recall them '
                'exactly."*\n\n'
            )
            if suggest_rest:
                base += (
                    '*"Perhaps you should rest and come back to this '
                    'later... though if you\'d rather keep trying, '
                    'I won\'t stop you."*\n\n'
                )
            base += (
                "Reply with *.rpg trial mage* to hear the words again, "
                "or *.rpg give up* to stop for now."
            )
            return base

        # Still within the shown/reading window — don't burn an
        # attempt, just let it fall through as a normal (wrong)
        # response so they can keep reading/trying once it's
        # actually their turn.
        return (
            '> The elder is still speaking — wait for the words to '
            "fade before you try to recast them."
        )

    if (cmd == ".rpg" and low_rest == "give up"
            and active_trial and active_trial.get("class") == "mage"):
        del session.flags["trial"]
        session.save(db)
        return (
            '> The elder nods, unbothered.\n\n'
            '*"No shame in it. Come back whenever you\'re ready."*'
        )

    # ── Summoner trial — Phase 1 only (species picking). See
    # townia_trials.py's Summoner section for the data/roll
    # functions this calls into. Player can type a bare species
    # name to open/re-open that species' sub-list (rolling fresh
    # trait data the FIRST time it's opened this trial attempt,
    # reusing the already-rolled data on subsequent opens of the
    # same species — matches the "persists per player through
    # Phase 1 browsing" rule), or "<species> <no.>" to commit a
    # pick. Both forms work regardless of which species was most
    # recently opened, since the species name disambiguates it —
    # no separate "must open first" gate. ──
    if (cmd == ".rpg" and active_trial
            and active_trial.get("class") == "summoner"
            and active_trial.get("phase") == "choosing_species"):
        parts = low_rest.split()
        species = parts[0] if parts else ""
        # Accept a simple plural ("cats") as well as the
        # canonical singular key, same forgiving spirit as the
        # Warrior weapon check but tolerant of the trailing "s"
        # a player is likely to type after seeing "🐾 Cats".
        if species.endswith("s") and species[:-1] in trials.SUMMONER_SPECIES:
            species = species[:-1]

        if species not in trials.SUMMONER_SPECIES:
            return (
                "Not a species on offer here. Choose from: "
                f"{', '.join(trials.SUMMONER_SPECIES)}"
            )

        rolls = active_trial.setdefault("rolls", {})

        # Bare species name (no number) — show/re-show that
        # species' sub-list. Roll fresh trait data only if this
        # species hasn't been opened yet this trial attempt.
        if len(parts) == 1:
            if species not in rolls:
                rolls[species] = trials.roll_summoner_sublist(species)
                session.flags["trial"] = active_trial
                session.save(db)
            return trials.render_species_sublist(species)

        # "<species> <no.>" — commit a pick.
        if len(parts) >= 2 and parts[1].isdigit():
            slot = int(parts[1])
            if not (1 <= slot <= 10):
                return f"*{species.capitalize()}* only has slots 1–10."
            if species not in rolls:
                # Player picked a number without ever opening the
                # list first — roll it now so the pick still
                # resolves against real data, same forgiving
                # spirit as the bare-name branch above.
                rolls[species] = trials.roll_summoner_sublist(species)
            pet_traits = rolls[species][slot - 1]
            blurb = trials.SUMMONER_BLURBS[species][slot - 1]

            # Phase 1 -> "pseudo Phase 2" hand-off. Phase 2 itself
            # (affinity-building) is NOT built yet — this stores
            # the committed pick and stops here, matching the
            # locked design's "does not hard-lock" rule (player
            # can still re-run ".rpg <species> <no.>" to switch
            # before Phase 2 exists to make that meaningful).
            active_trial["phase"] = "bonding_stub"
            active_trial["committed_species"] = species
            active_trial["committed_slot"] = slot
            active_trial["committed_traits"] = pet_traits
            session.flags["trial"] = active_trial
            session.save(db)

            keeper_name = npc.get_shopkeeper_card(db, session.sender)["name"]
            return (
                f"> You step toward pen {slot}.\n\n"
                f"> {blurb}\n\n"
                f'*"Good pick,"* {keeper_name} says. *"Go on, '
                "get to know it a little.\"*\n\n"
                "_(Phase 2 — affinity-building — isn't built yet. "
                "Your pick is saved; reply with a different "
                "`.rpg <species> <no.>` any time to switch.)_"
            )

        return (
            f"Reply with *.rpg {species}* to see the list again, "
            f"or *.rpg {species} <no.>* to choose one."
        )

    # ── Warrior trial — weapon choice starts the specific
    # mechanic for that weapon (fight / shield / bow) ─────────
    if (cmd == ".rpg" and active_trial
            and active_trial.get("class") == "warrior"
            and active_trial.get("phase") == "choose_weapon"):
        weapon = low_rest
        if weapon not in trials.WARRIOR_WEAPONS:
            return (
                f"Not a weapon on offer here. Choose from: "
                f"{', '.join(trials.WARRIOR_WEAPONS)}"
            )

        mechanic = trials.WEAPON_MECHANIC[weapon]

        if mechanic == "fight":
            active_trial["phase"] = "fighting"
            active_trial["weapon"] = weapon
            active_trial["opponent_hp"] = trials._opponent_max_hp(weapon)
            session.flags["trial"] = active_trial
            session.save(db)
            opp_name = trials.WARRIOR_OPPONENTS[weapon]["name"]
            return (
                f'> You raise your {weapon}. {opp_name} '
                "settles into a ready stance.\n\n"
                "Reply with *.rpg attack* (or any attack description) "
                "to strike."
            )

        if mechanic == "shield":
            active_trial["phase"] = "shielding"
            active_trial["weapon"] = weapon
            active_trial["blocks"] = 0
            active_trial["hits_taken"] = 0
            session.flags["trial"] = active_trial
            session.save(db)
            direction = trials._weighted_random_direction()
            active_trial["_pending_direction"] = direction
            session.flags["trial"] = active_trial
            session.save(db)
            opp_name = trials.WARRIOR_OPPONENTS["shield"]["name"]
            return (
                f"> You raise your shield. {opp_name} "
                f"swings from your **{direction}**.\n\n"
                "Reply with *.rpg block <direction>* (front/left/right/"
                "behind/above/below), or just *.rpg block* to guess."
            )

        if mechanic == "bow":
            active_trial["phase"] = "shooting"
            active_trial["weapon"] = weapon
            active_trial["hits"] = 0
            shot = trials.roll_bow_shot()
            active_trial["_shot"] = shot
            session.flags["trial"] = active_trial
            session.save(db)
            return (
                f"> You nock an arrow. {shot['description']}\n\n"
                "Reply with *.rpg <how you aim>* to loose the shot."
            )
    ctx.active_trial = active_trial
    return NOT_HANDLED
