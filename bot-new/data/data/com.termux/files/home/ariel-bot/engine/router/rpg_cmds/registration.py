"""
router/rpg_cmds/registration.py - `.reg`, `.setname`, `.rmenu` (character creation).

Moved verbatim out of RpgManager._dispatch (router/rpg.py, original lines 286-400).
`handle(self, ctx)` runs the block in the same position it had in the old if-chain: it returns the
reply (or None, which ends dispatch), or NOT_HANDLED to fall through to the next block.
"""

import npc
import re
from rpg_session import RpgSession, STARTING_LOCATION
from ._common import NOT_HANDLED, _with_choices


def handle(self, ctx):
    sender, cmd, rest, db, session = ctx.sender, ctx.cmd, ctx.rest, ctx.db, ctx.session

    # ── .reg — start registration ──────────────────────────
    if cmd == ".reg":
        session = RpgSession.load(db, sender)
        if session.exists:
            return (
                f"You already have a character: "
                f"{session.soulbound.get('name', 'Unknown')}. "
                "Use .rpg reset if you want to start over."
            )
        prompt = session.start_registration()
        session.save(db)
        return prompt

    # ── .setname <name> — no quote-reply required. Ariel's own
    # outgoing messages are the ones that quote the player (so
    # players can tell which reply belongs to them when several
    # are active), not the other way around — the player never
    # needs to quote/reply to Ariel for anything. ──
    if cmd == ".setname":
        session = RpgSession.load(db, sender)

        if not session.pending_registration:
            return "You don't have a pending registration. Send .reg first."

        name = rest.strip()
        if not name:
            return "Usage: .setname <name>"

        # Strip angle-bracket placeholder syntax players sometimes
        # copy-paste in from examples (e.g. "<Prime Sage>"), then
        # cap length and title-case so names display consistently
        # regardless of how the player typed them.
        name = re.sub(r"[<>]", "", name).strip()
        if not name:
            return "Usage: .setname <name>"
        name = name[:32]
        name = name[0].upper() + name[1:] if name else name

        session.register(name)

        # The elder is introduced by name in the opening prose
        # below — must be seeded into the shared rpg_world_npcs
        # table too, or the very first "talk to the elder" /
        # "talk to the nearest person" choice fails premise
        # validation for the same reason any narrator-invented
        # NPC does. Global, not per-session, per the shared-world
        # fix: every player who registers seeds the SAME elder at
        # STARTING_LOCATION (idempotent — add_world_npc no-ops if
        # a previous player already seeded them).
        #
        # Seeded from her real card (NPC.py) — "Danaya", not a
        # freehand description used as a name. Per the bug this
        # fixed: the OLD seed ("a young elder of the church")
        # had no pinned name/pronouns anywhere, which is exactly
        # why "she" here and "his" elsewhere (line ~530) drifted
        # out of sync — nothing forced consistency. See NPC.md.
        elder_card = npc.get_npc_card("townia_church_elder")
        db.add_world_npc(session.location_id, elder_card["name"],
                          hostile=elder_card["hostile"])

        # Opening-scene suggested actions — same mechanism every
        # other turn uses (session.flags["_choices"], resolved by
        # ".rpg <no.>" below), just hand-written here since there's
        # no narrator call yet at registration time.
        opening_choices = [
            'Umm classes?',
            "I think I'll test my strength against a few monsters.",
            "Cursed child?",
        ]
        session.flags["_choices"] = opening_choices
        session.save(db)

        opening_scene = (
            f"You are now *{name}*.\n\n"
            f"> You wake up in {STARTING_LOCATION}, with no "
            "memories of your past.\n\n"
            "> A young woman notices you and smiles warmly. She "
            "looks barely older than you.\n\n"
            '*"Another cursed child, huh... Welcome to Townia."*\n\n'
            "> She introduces herself as Danaya, an elder of the "
            "church.\n\n"
            '*"By any chance have you gotten a class?.... I deeply '
            'recommend you come be a priest at the church of '
            'Beginnings, right here!"*\n\n'
            "> She coughs awkwardly after realizing her insistence.\n\n"
            '*"...Then again, if warrior calls to you more, the '
            "Coliseum in the West District takes trials, and the "
            "library holds the mage's trial too. Would you like to "
            "know more about classes, or do you think you're ready "
            'to brave the bold past the northern gate?"*'
        )

        return _with_choices(opening_scene, opening_choices)

    # ── .rmenu — roleplay command menu. Works with or without a
    # character (unlike .status/.skills/.rpg <action>), same as
    # .reg above, so it's placed before the existing-character
    # gate. Not ".menu" — that name is already used elsewhere. ──
    if cmd == ".rmenu":
        return (
            "🗺️ *Ariel — RPG Commands*\n\n"
            "*.reg* — start registration\n"
            "*.setname <name>* — set your character's name\n"
            "*.status* — character sheet\n"
            "*.skills* — known skills\n"
            "*.inv* — check your inventory\n"
            "*.rpg state* — recap where you are\n"
            "*.rpg <what you do>* — take an action, e.g. .rpg I look around\n"
            "*.rpg sim [weapon] [monster] [lvl]* — test-battle a monster "
            "(weapon: sword/dagger/spear/mace/bow, random if omitted)\n"
            "*.rpg sim end* — forfeit/stop the current sim\n"
            "*.rpg reset* — wipe your character and start over\n"
            "_(.rpg on/off is King-only, toggled per-group)_"
        )
    return NOT_HANDLED
