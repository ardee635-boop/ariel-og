"""
router/rpg_cmds/reset.py - `.rpg reset` / `.rpg delete` and the King-only `.resetworld`.

Moved verbatim out of RpgManager._dispatch (router/rpg.py, original lines 401-458).
`handle(self, ctx)` runs the block in the same position it had in the old if-chain: it returns the
reply (or None, which ends dispatch), or NOT_HANDLED to fall through to the next block.
"""

from permissions import is_king
from rpg_session import RpgSession
from ._common import NOT_HANDLED


def handle(self, ctx):
    sender, cmd, rest, db, session = ctx.sender, ctx.cmd, ctx.rest, ctx.db, ctx.session

    # ── .rpg reset / .rpg delete — exact match on the whole
    # remainder only, so "reset the gate" etc. still narrates
    # normally as an in-world action instead of being swallowed
    # here. Placed before the existing-character gate since a
    # player mid-registration (pending_registration=True, no
    # character yet) needs to be able to reset too. ──
    if cmd == ".rpg" and rest.strip().lower() in ("reset", "delete"):
        session = RpgSession.load(db, sender)
        session.delete(db)
        return "🗑️ Character wiped. Send .reg to start a new journey."

    # ── .resetworld — King-only. Wipes the whole shared world
    # (every Place, Passage, world NPC and world object — invented
    # AND hand-authored), re-seeds the hand-authored tree, then
    # sends every player back to the starting location, since the
    # wipe leaves their stored location_id pointing at rows that
    # no longer exist (see database.reset_world()'s docstring —
    # that method only wipes; rebuilding and fixing sessions is
    # this command's job). Does NOT touch characters, soulbound
    # sheets, inventories or registrations. Placed before the
    # _KNOWN_RPG_CMDS gate below: this command needs no character
    # of its own (the King may not have one), and it used to be
    # missing from that set, so it fell through to `return None`
    # and did nothing at all. ──
    if cmd == ".resetworld":
        if not is_king(sender):
            return "👑 _Only the King can reset the world._"

        import rpg_places_seed
        import rpg_movement
        from rpg_session import META_KEY, STARTING_LOCATION_ID

        db.reset_world()
        rpg_places_seed.seed_hardcoded_tree(db)

        start = db.get_place(STARTING_LOCATION_ID)
        if not start:
            return (
                "⚠️ _World wiped, but the starting location "
                f"({STARTING_LOCATION_ID}) is missing after re-seeding — "
                "players were NOT moved. Check rpg_places_seed._"
            )

        moved = 0
        for player_sender in db.all_senders_with_meta_key(META_KEY):
            s = RpgSession.load(db, player_sender)
            if not s.exists:
                continue  # mid-registration / empty shell: no location to fix
            rpg_movement.move_player_to(s, db, start)
            # a wipe invalidates any open journey and its numbered choices
            s.flags.pop("_journey", None)
            s.flags["_choices"] = []
            s.save(db)
            moved += 1

        return (
            "🌍 *World reset.* Every place, passage and world NPC was "
            "wiped and the hand-authored map re-seeded.\n"
            f"_{moved} player(s) returned to {start['name'] or STARTING_LOCATION_ID}._"
        )
    return NOT_HANDLED
