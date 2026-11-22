"""
router/rpg_cmds/trials_weapons.py - Warrior trial mechanics: fight weapons, shield blocking, bow shooting.

Moved verbatim out of RpgManager._dispatch (router/rpg.py, original lines 887-1058).
`handle(self, ctx)` runs the block in the same position it had in the old if-chain: it returns the
reply (or None, which ends dispatch), or NOT_HANDLED to fall through to the next block.
"""

import townia_trials as trials
from ._common import NOT_HANDLED


def handle(self, ctx):
    cmd, rest, db, session, active_trial = ctx.cmd, ctx.rest, ctx.db, ctx.session, ctx.active_trial

    # ── Fight-mechanic weapons (sword/dagger/spear/axe/mace) ──
    if (cmd == ".rpg" and active_trial
            and active_trial.get("class") == "warrior"
            and active_trial.get("phase") == "fighting"):
        weapon = active_trial["weapon"]
        stats = session.soulbound.get("stats", {})
        result = trials.resolve_fight_exchange(stats)
        active_trial["opponent_hp"] -= result["damage"]
        max_hp = trials._opponent_max_hp(weapon)
        floor = trials.WIN_HP_FRACTION * max_hp
        opp_name = trials.WARRIOR_OPPONENTS[weapon]["name"]

        if active_trial["opponent_hp"] <= floor:
            del session.flags["trial"]
            gained_raw = trials.record_weapon_cleared(session.soulbound, weapon)
            gained_skills = [g[len("__skill__"):] for g in gained_raw if g.startswith("__skill__")]
            gained = [g for g in gained_raw if not g.startswith("__skill__")]
            if gained_skills:
                session.soulbound.setdefault("skills", [])
                for skill in gained_skills:
                    if skill not in session.soulbound["skills"]:
                        session.soulbound["skills"].append(skill)
            session.flags["pending_class"] = gained[0]
            session.flags["pending_class_extra"] = gained[1:]
            session.save(db)
            gained_text = " and ".join(gained)
            skill_note = (
                f"\n\n> You've mastered every weapon in the ring — "
                f"you also gain the skill *{gained_skills[0]}*!"
                if gained_skills else ""
            )
            return (
                f'> Your {weapon} lands true — {opp_name} '
                "drops to a knee, beaten.\n\n"
                '*"Well fought!"* the elder calls out.'
                f"{skill_note}\n\n"
                f'Would you like to take the class *"{gained_text}"*?\n'
                "Reply with *.rpg yes*, *.rpg no*, or *.rpg <text>*"
            )

        session.flags["trial"] = active_trial
        session.save(db)
        return (
            f"> You strike with your {weapon}. {opp_name} "
            f"staggers ({active_trial['opponent_hp']:.0f}/{max_hp:.0f} HP).\n\n"
            "Reply with *.rpg attack* to strike again."
        )

    # ── Shield mechanic ────────────────────────────────────────
    if (cmd == ".rpg" and active_trial
            and active_trial.get("class") == "warrior"
            and active_trial.get("phase") == "shielding"):
        stats = session.soulbound.get("stats", {})
        incoming = active_trial["_pending_direction"]
        block = trials.resolve_shield_block(rest, incoming, stats)

        if block["blocked"]:
            active_trial["blocks"] += 1
        else:
            active_trial["hits_taken"] += 1

        if active_trial["blocks"] >= trials.SHIELD_HITS_TO_WIN:
            weapon = active_trial["weapon"]
            del session.flags["trial"]
            gained_raw = trials.record_weapon_cleared(session.soulbound, weapon)
            gained_skills = [g[len("__skill__"):] for g in gained_raw if g.startswith("__skill__")]
            gained = [g for g in gained_raw if not g.startswith("__skill__")]
            if gained_skills:
                session.soulbound.setdefault("skills", [])
                for skill in gained_skills:
                    if skill not in session.soulbound["skills"]:
                        session.soulbound["skills"].append(skill)
            session.flags["pending_class"] = gained[0]
            session.flags["pending_class_extra"] = gained[1:]
            session.save(db)
            skill_note = (
                f"\n\n> You've mastered every weapon in the ring — "
                f"you also gain the skill *{gained_skills[0]}*!"
                if gained_skills else ""
            )
            return (
                "> You catch the tenth blow clean on your shield. "
                f"{trials.WARRIOR_OPPONENTS['shield']['name']} steps "
                "back, impressed.\n\n"
                '*"Well fought!"* the elder calls out.'
                f"{skill_note}\n\n"
                f'Would you like to take the class *"{gained[0]}"*?\n'
                "Reply with *.rpg yes*, *.rpg no*, or *.rpg <text>*"
            )

        if active_trial["hits_taken"] >= trials.SHIELD_HITS_TO_LOSE:
            del session.flags["trial"]
            session.save(db)
            return (
                "> The third blow gets through your guard.\n\n"
                '*"Close! Come back and try again whenever you\'re '
                'ready."*'
            )

        next_direction = trials._weighted_random_direction()
        active_trial["_pending_direction"] = next_direction
        session.flags["trial"] = active_trial
        session.save(db)
        if not block["matched"]:
            wrong_side = trials.parse_block_direction(rest)
            outcome = f"you guard {wrong_side} — wrong side, it gets through"
            return (
                f"> Attack from your **{block['direction']}** — {outcome}.\n"
                f"Blocks: {active_trial['blocks']}/{trials.SHIELD_HITS_TO_WIN} · "
                f"Hits taken: {active_trial['hits_taken']}/{trials.SHIELD_HITS_TO_LOSE}\n\n"
                f"Next swing comes from your **{next_direction}**.\n"
                "Reply with *.rpg block <direction>* or *.rpg block* to guess."
            )
        outcome = "You block it!" if block["blocked"] else "It gets through."
        return (
            f"> Attack from your **{block['direction']}** — {outcome}\n"
            f"Blocks: {active_trial['blocks']}/{trials.SHIELD_HITS_TO_WIN} · "
            f"Hits taken: {active_trial['hits_taken']}/{trials.SHIELD_HITS_TO_LOSE}\n\n"
            f"Next swing comes from your **{next_direction}**.\n"
            "Reply with *.rpg block <direction>* or *.rpg block* to guess."
        )

    # ── Bow mechanic ────────────────────────────────────────────
    if (cmd == ".rpg" and active_trial
            and active_trial.get("class") == "warrior"
            and active_trial.get("phase") == "shooting"):
        shot = active_trial["_shot"]
        result = trials.resolve_bow_shot(rest, shot)

        if result["hit"]:
            active_trial["hits"] += 1

        if active_trial["hits"] >= trials.BOW_HITS_TO_WIN:
            weapon = "bow"
            del session.flags["trial"]
            gained_raw = trials.record_weapon_cleared(session.soulbound, weapon)
            gained_skills = [g[len("__skill__"):] for g in gained_raw if g.startswith("__skill__")]
            gained = [g for g in gained_raw if not g.startswith("__skill__")]
            if gained_skills:
                session.soulbound.setdefault("skills", [])
                for skill in gained_skills:
                    if skill not in session.soulbound["skills"]:
                        session.soulbound["skills"].append(skill)
            session.flags["pending_class"] = gained[0]
            session.flags["pending_class_extra"] = gained[1:]
            session.save(db)
            gained_text = " and ".join(gained)
            skill_note = (
                f"\n\n> You've mastered every weapon in the ring — "
                f"you also gain the skill *{gained_skills[0]}*!"
                if gained_skills else ""
            )
            return (
                "> Your tenth arrow finds its mark dead center.\n\n"
                '*"Well fought!"* the elder calls out.'
                f"{skill_note}\n\n"
                f'Would you like to take the class *"{gained_text}"*?\n'
                "Reply with *.rpg yes*, *.rpg no*, or *.rpg <text>*"
            )

        next_shot = trials.roll_bow_shot()
        active_trial["_shot"] = next_shot
        session.flags["trial"] = active_trial
        session.save(db)
        outcome = "The arrow strikes true!" if result["hit"] else "The arrow goes wide."
        return (
            f"> {outcome}\n"
            f"Hits: {active_trial['hits']}/{trials.BOW_HITS_TO_WIN}\n\n"
            f"Next shot: {next_shot['description']}\n"
            "Reply with *.rpg <how you aim>* to loose the shot."
        )
    return NOT_HANDLED
