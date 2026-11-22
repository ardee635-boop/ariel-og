"""
router/rpg_cmds/fight.py - Active real-fight interception (`.rpg <action>` while a battle is running).

Moved verbatim out of RpgManager._dispatch (router/rpg.py, original lines 603-650).
`handle(self, ctx)` runs the block in the same position it had in the old if-chain: it returns the
reply (or None, which ends dispatch), or NOT_HANDLED to fall through to the next block.
"""

import rpg_battle
from rpg_llm import call_groq
from ._common import NOT_HANDLED, _with_choices


def handle(self, ctx):
    sender, cmd, rest, db, session, active_battle = ctx.sender, ctx.cmd, ctx.rest, ctx.db, ctx.session, ctx.active_battle

    low_rest = rest.strip().lower()

    # ── Active real fight — intercepts whatever the player sends
    # next, same discipline as the ".rpg sim" active-session check
    # above, just against rpg_battle.py's live slot (BATTLE_META_KEY)
    # instead of the sim's throwaway one. Checked before trial
    # handling: a player can't be mid-trial-minigame AND mid-real-
    # fight at once (trial_start is only ever honored when no
    # "trial" flag is already set — see below — and combat_start
    # is only ever honored when no "trial" flag is set either),
    # but this check still needs to come first so an ongoing fight
    # always wins over any other interpretation of the message. ──
    active_battle = rpg_battle.load_battle(db, sender)
    if cmd == ".rpg" and active_battle and not active_battle.get("finished"):
        action_text = rest.strip()
        if not action_text:
            return _with_choices(rpg_battle.render_turn(active_battle), [])
        state = rpg_battle.run_turn(active_battle, action_text, call_groq, db=db)

        # ── special_event: an outside-the-fight interruption (see
        # rpg_battle._NARRATE_SYSTEM's SPECIAL EVENT block). The
        # interrupted fight does NOT get reloaded/continued later
        # — the story is moving on to something else entirely
        # (per design: "I punch Alastor, a god descends and tells
        # us the Culling Games have begun" — the NEXT scene is a
        # new thing, not a continuation of that exact duel). What
        # DOES carry forward is what was already true when it
        # broke off (HP, wounds, ongoing conditions) — extracted
        # as one plain-text summary and folded into session
        # history so the very next narration call sees it as
        # recent context, same "PAST EVENTS" mechanism any other
        # turn's reply feeds into. "abandon" skips the extraction
        # entirely — nothing about that fight needs to persist.
        # Either way the LIVE battle slot is always cleared here.
        if state.get("special_event"):
            rpg_battle.delete_battle(db, sender)
            if state["special_event_resolution"] == "resume":
                summary = rpg_battle.extract_interrupted_battle_summary(state)
                session.history.append({"action": "(fight interrupted)", "reply": summary})
            session.save(db)
            return rpg_battle.render_turn(state)

        if state["finished"]:
            rpg_battle.delete_battle(db, sender)
        else:
            rpg_battle.save_battle(db, sender, state)
        return rpg_battle.render_turn(state)
    ctx.low_rest = low_rest
    return NOT_HANDLED
