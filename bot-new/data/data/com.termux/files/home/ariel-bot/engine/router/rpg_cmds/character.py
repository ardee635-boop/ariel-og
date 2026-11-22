"""
router/rpg_cmds/character.py - Known-command gate, session load, `.status`/`.skills`/`.skill`, `.inv`, `.equip`, `.rpg state`.

Moved verbatim out of RpgManager._dispatch (router/rpg.py, original lines 459-527).
`handle(self, ctx)` runs the block in the same position it had in the old if-chain: it returns the
reply (or None, which ends dispatch), or NOT_HANDLED to fall through to the next block.
"""

from rpg_session import RpgSession
from ._common import NOT_HANDLED


def handle(self, ctx):
    sender, cmd, rest, db, session = ctx.sender, ctx.cmd, ctx.rest, ctx.db, ctx.session

    # ── Everything below requires a recognized RPG command AND an
    # existing character. Recognized-command check comes FIRST —
    # without it, any garbled/mistyped command (e.g. a stray
    # space turning ".setname" into "." + "setname Hiro") falls
    # straight through every specific `if cmd == ...` branch above
    # and hits the registration-gate message below regardless of
    # what was actually typed, misleadingly implying a specific
    # registration problem that was never the real issue. ──
    _KNOWN_RPG_CMDS = {".reg", ".setname", ".rmenu", ".status",
                       ".skills", ".skill", ".inv", ".equip", ".rpg"}
    if cmd not in _KNOWN_RPG_CMDS:
        return None

    session = RpgSession.load(db, sender)
    if not session.exists:
        if session.pending_registration:
            return "You haven't finished registering yet. Use .setname <name>."
        return "You haven't started your journey yet. Send .reg to begin."

    if cmd in (".status", ".skills", ".skill"):
        if cmd == ".status":
            return session.status_text()
        # .skills/.skill — Phase 0: skills list is empty for a
        # fresh character (register() sets skills: []), so this
        # is honest about there being nothing yet rather than
        # inventing content. Real skill-granting (from class
        # choice, leveling, etc.) isn't designed yet.
        skills = session.soulbound.get("skills", [])
        if not skills:
            return "You don't know any skills yet."
        # Trial rewards (e.g. "Weapon Master") are stored as a bare name string,
        # monster-derived skills as {"name": ...} dicts - accept both.
        lines = [f"- {s['name'] if isinstance(s, dict) else s}" for s in skills]
        return "\n".join(lines)

    # ── .inv / .equip — Phase 0: a flat carried-items list plus
    # one "equipped" slot. No armor slot, no stacking/quantities,
    # no weight/encumbrance — just enough to make the weapon a
    # class trial grants (see trials.grant_starting_weapon(),
    # called from the class-confirmation branch below) something
    # a player can actually see and wield. Real inventory systems
    # (multiple slots, non-weapon items, drops, trading) aren't
    # designed yet; this is honest about that rather than
    # inventing structure the design discussion hasn't settled.
    if cmd == ".inv":
        items = session.soulbound.get("inventory", [])
        equipped = session.soulbound.get("equipped")
        if not items:
            return "Your inventory is empty."
        lines = [
            f"- {item}" + (" *(equipped)*" if item == equipped else "")
            for item in items
        ]
        return "\n".join(lines)

    if cmd == ".equip":
        item = rest.strip().lower()
        items = session.soulbound.get("inventory", [])
        if not item:
            return "Use *.equip <item>* — e.g. *.equip sword*."
        if item not in items:
            return f"You don't have a {item} in your *.inv*."
        session.soulbound["equipped"] = item
        session.save(db)
        return f"> You equip your {item}."

    if cmd == ".rpg" and rest.strip().lower() == "state":
        return session.summarize(db)
    ctx.session = session
    return NOT_HANDLED
