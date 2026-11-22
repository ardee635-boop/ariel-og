"""
router/rpg_cmds/_common.py - pieces shared by RpgManager and the handler modules.

Moved verbatim out of router/rpg.py (NOT_HANDLED, the "Read more" padding,
_with_choices, _maybe_fire_mage_delete) plus DispatchContext, the small bag of
locals the old 1,000-line _dispatch kept in function scope.
router/rpg.py re-exports all of these, so existing imports keep working.
"""
import time


class DispatchContext:
    """Locals that used to live in RpgManager._dispatch's scope, shared by the handler blocks."""
    def __init__(self, sender, text, quoted_text, group_jid, parts, cmd, rest, db):
        self.sender, self.text = sender, text
        self.quoted_text, self.group_jid = quoted_text, group_jid
        self.parts, self.cmd, self.rest, self.db = parts, cmd, rest, db
        # assigned by earlier blocks, read by later ones (same order as the old if-chain)
        self.session = None
        self.stripped_rest = self.low_stripped_rest = self.low_rest = None
        self.active_battle = self.active_trial = None
        self.pending_class = self.pending_extra = None


NOT_HANDLED = object()

# Forces WhatsApp's chat-bubble preview to truncate and show "Read
# more" before whatever comes after this. Matches the SAME pattern
# used elsewhere in the project (interfaces.py, pvp_session.py,
# encounters.py, models.py: RM = '\u200b' * 700) — one long run of
# zero-width spaces on a SINGLE line, not one per line. A zero-width
# character is zero WIDTH, not zero height: stacking them with \n
# between each one (the old bug here) still produces that many real
# blank lines, since each line still has its own line-height even
# with invisible content on it. A single unbroken run has no
# newlines in it at all, so it takes zero vertical space while still
# being long enough that WhatsApp can't render/wrap it and truncates
# instead — that's what actually triggers "Read more".
_ZERO_WIDTH_SPACE = "\u200b"
_READ_MORE_PAD = _ZERO_WIDTH_SPACE * 700


def _read_more_pad() -> str:
    return _READ_MORE_PAD


def _with_choices(body: str, choices: list[str]) -> str:
    """
    Appends the SAME 'Recommended choices' block (zero-width
    read-more pad included) after any narration body — used for
    both the opening scene AND every ordinary .rpg narration turn,
    so choices are visible every time, not just at character
    creation. Falls back to plain body (no read-more pad, no
    choices header) when there's nothing to show — an empty/no
    choices list means there's nothing worth padding for, and
    padding a message that has no follow-up content would just be
    a wall of invisible characters for no reason.
    """
    if not choices:
        return body
    choices_block = "\n".join(f"{i}. {text}" for i, text in enumerate(choices, start=1))
    return (
        f"{body}\n"
        f"{_read_more_pad()}\n"
        "*Recommended choices*\n\n"
        f"{choices_block}\n\n"
        "Reply with *.rpg <no.>* to pick one, or type your own "
        "action with *.rpg <what you do>*."
    )


def _maybe_fire_mage_delete(session, low_rest: str) -> str | None:
    """
    Reactive replacement for a real timer. Render doesn't keep a
    process alive/awake to fire a threading.Timer reliably after a
    9-15s delay — there's no guarantee the same process (or any
    process) is still running when that moment arrives. So instead
    of scheduling anything, the delay is just a deadline
    (incantation_data["delete_at"], set once up front by
    start_mage_incantation()) that gets checked reactively: the
    NEXT time this player sends ANY .rpg message while the deadline
    has already passed, this fires the delete+"now you try" message
    first, then lets normal dispatch continue afterward.

    This means the "auto-delete" isn't truly proactive/unprompted —
    it only actually happens once the player sends their next
    message post-deadline — but that's the correct tradeoff for a
    stateless host rather than a fragile timer that silently never
    fires if the process restarts mid-wait.

    Returns the delete+prompt message to send BEFORE processing
    whatever the player just typed, or None if no delete is due.
    The caller is responsible for still processing the player's
    actual message afterward (their message may itself be the
    correct recast, sent in the same breath as the deadline passing
    — that's handled by letting normal dispatch continue right after
    this fires, not by treating this as a terminal reply).
    """
    trial = session.flags.get("trial")
    if not trial or trial.get("class") != "mage":
        return None
    inc_data = trial.get("incantation_data")
    if not inc_data or inc_data.get("delete_fired"):
        return None
    if time.time() < inc_data["delete_at"]:
        return None  # not due yet

    inc_data["delete_fired"] = True
    trial["phase"] = "awaiting_recast"
    session.flags["trial"] = trial
    # Deliberately NOT saved here — caller saves once, after finishing
    # whatever else it does with this same session object, to avoid
    # a redundant extra DB write on every single message.
    return (
        "*The elder's words fade from the air.*\n\n"
        '*"Now you try."*'
    )
