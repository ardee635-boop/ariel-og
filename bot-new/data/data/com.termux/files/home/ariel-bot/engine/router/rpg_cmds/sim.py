"""
router/rpg_cmds/sim.py - `.rpg sim ...` test battles.

Moved verbatim out of RpgManager._dispatch (router/rpg.py, original lines 528-602).
`handle(self, ctx)` runs the block in the same position it had in the old if-chain: it returns the
reply (or None, which ends dispatch), or NOT_HANDLED to fall through to the next block.
"""

import rpg_sim
from rpg_llm import call_groq
from ._common import NOT_HANDLED, _with_choices


def handle(self, ctx):
    sender, cmd, rest, db, session, stripped_rest, low_stripped_rest = ctx.sender, ctx.cmd, ctx.rest, ctx.db, ctx.session, ctx.stripped_rest, ctx.low_stripped_rest

    # ── .rpg sim — standalone test-bed combat, weapon-selectable
    # (sword/dagger/spear/mace/bow — see rpg_sim.py's WEAPON_TABLES;
    # random if not specified). Fully separate from the real RPG
    # world_state/session flow: no premise validation, no
    # narrator history, its own db.player_meta key. Checked
    # early — before trial/free-text handling below — so an
    # active sim always intercepts what the player sends next,
    # the same way an active trial does. ──
    stripped_rest = rest.strip()
    low_stripped_rest = stripped_rest.lower()
    if cmd == ".rpg" and (low_stripped_rest == "sim" or low_stripped_rest.startswith("sim ")):
        sim_arg = stripped_rest[3:].strip()  # text after "sim"
        existing_sim = rpg_sim.load_sim(db, sender)

        if sim_arg.lower() == "end":
            if not existing_sim or existing_sim.get("finished"):
                rpg_sim.delete_sim(db, sender)
                return "No sim battle is currently running."
            rpg_sim.delete_sim(db, sender)
            return (f"🏳️ *You forfeit against {existing_sim['monster']['name']}. "
                    "Loss recorded.*")

        if existing_sim and not existing_sim.get("finished"):
            # Sim already running — sim_arg (if any) is the
            # player's attack narration for this turn, NOT a
            # request to start a new one. Starting a fresh sim
            # mid-fight isn't supported yet (per current scope:
            # one sim at a time) — player must .rpg sim end first.
            if not sim_arg:
                return _with_choices(rpg_sim.render_turn(existing_sim), [])
            state = rpg_sim.run_turn(existing_sim, sim_arg, call_groq, db=db)
            if state["finished"]:
                rpg_sim.delete_sim(db, sender)
            else:
                rpg_sim.save_sim(db, sender, state)
            return rpg_sim.render_turn(state)

        # No sim running yet — sim_arg is "[weapon] <monster> <lvl>" or
        # empty. Weapon is matched first, by exact keyword against
        # rpg_sim.WEAPON_TABLES, checked as either the FIRST or LAST
        # word (".rpg sim dagger goblin 5" and ".rpg sim goblin 5
        # dagger" both work) and stripped out before the existing
        # monster/level parsing runs on whatever's left — this keeps
        # multi-word monster names ("giant rat") intact, since the
        # weapon check only ever consumes one exact-match word, never
        # guesses from the middle of the remaining text.
        # No weapon word present -> weapon_key stays None -> start_sim
        # picks a random weapon, per ".rpg sim gives a random weapon".
        monster_name = None
        monster_level = None
        weapon_key = None
        if sim_arg:
            words = sim_arg.split()
            if words and words[0].lower() in rpg_sim.WEAPON_TABLES:
                weapon_key = words[0].lower()
                words = words[1:]
            elif words and words[-1].lower() in rpg_sim.WEAPON_TABLES:
                weapon_key = words[-1].lower()
                words = words[:-1]
            remaining = " ".join(words).strip()
            if remaining:
                sim_parts = remaining.rsplit(maxsplit=1)
                if len(sim_parts) == 2 and sim_parts[1].isdigit():
                    monster_name, monster_level = sim_parts[0], int(sim_parts[1])
                else:
                    monster_name = remaining

        player_level = session.soulbound.get("level", 1) if session.soulbound else 1
        new_state = rpg_sim.start_sim(session.soulbound, player_level,
                                       monster_name, monster_level, weapon_key)
        if isinstance(new_state, str):
            return new_state  # monster lookup failed, or unknown weapon name — error message
        rpg_sim.save_sim(db, sender, new_state)
        return rpg_sim.render_start(new_state)
    return NOT_HANDLED
