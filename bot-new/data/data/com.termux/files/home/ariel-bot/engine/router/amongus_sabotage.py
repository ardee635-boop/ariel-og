"""Shared per-game sabotage lifecycle for the Niflheim Among Us engine."""


SABOTAGE_NAMES = ("lights", "communications", "oxygen", "reactor")


class Sabotage(dict):
    """Mutable state for one sabotage type in one game.

    A dict-backed object keeps the state easy to inspect in deterministic tests
    while exposing the lifecycle operations used by game logic.
    """

    def __init__(self, name, cooldown_seconds):
        super().__init__(
            name=name,
            state="idle",
            activated_at=None,
            deadline=None,
            cooldown_until=0.0,
            paused_remaining=None,
            warnings_sent=set(),
            repair_interactions={},
            timer=None,
        )
        self.cooldown_seconds = float(cooldown_seconds)

    def activate(self, now, deadline=None):
        if self["state"] == "active":
            return False
        self["state"] = "active"
        self["activated_at"] = float(now)
        self["deadline"] = None if deadline is None else float(deadline)
        self["cooldown_until"] = float(now) + self.cooldown_seconds
        self["paused_remaining"] = None
        self["warnings_sent"] = set()
        self["repair_interactions"] = {}
        return True

    def repair(self, now):
        if self["state"] != "active":
            return False
        self["state"] = "repaired"
        self["repaired_at"] = float(now)
        self["deadline"] = None
        self["paused_remaining"] = None
        self["repair_interactions"].clear()
        return True

    def fail(self, now):
        if self["state"] != "active":
            return False
        self["state"] = "failed"
        self["failed_at"] = float(now)
        self["deadline"] = None
        self["paused_remaining"] = None
        self["repair_interactions"].clear()
        return True

    def activation_note(self):
        """Extra text for the group activation broadcast (7C overrides)."""
        return ""

    # Display hooks; only Communications overrides these (7B-2a-ii).
    def freeze_players(self, entries):
        return False

    @property
    def frozen_players(self):
        return None

    @property
    def suppressing(self):
        return False

    def cancel(self):
        """Cancel a still-active sabotage when the match ends."""
        if self["state"] != "active":
            return False
        self["state"] = "idle"
        self["deadline"] = None
        self["paused_remaining"] = None
        self["repair_interactions"].clear()
        self["timer"] = None
        return True


class LightsSabotage(Sabotage):
    """Lights: no deadline, stays active until repaired (Session 7B-1)."""

    def activate(self, now, deadline=None):
        # Lights never times out, whatever the caller passes.
        return super().activate(now, deadline=None)

    @property
    def masking(self):
        """True while passive observations should hide who (used by 7B-1a-ii)."""
        return self["state"] == "active"


class CommunicationsSabotage(Sabotage):
    """Communications: no deadline, stays active until repaired (Session 7B-2)."""

    def __init__(self, name, cooldown_seconds):
        super().__init__(name, cooldown_seconds)
        self["players_snapshot"] = None

    def activate(self, now, deadline=None):
        # Communications never times out, whatever the caller passes.
        self["players_snapshot"] = None
        return super().activate(now, deadline=None)

    def freeze_players(self, entries):
        """Store the `.players` list as it was at activation (7B-2a-ii).

        entries: [(jid, alive), ...]. Never updated until repair.
        """
        if self["state"] != "active":
            return False
        self["players_snapshot"] = [(jid, bool(alive)) for jid, alive in entries]
        return True

    @property
    def frozen_players(self):
        """The frozen list while active, else None (live list applies)."""
        if self["state"] != "active":
            return None
        return self["players_snapshot"]

    def _clear_snapshot(self, result):
        if result:
            self["players_snapshot"] = None
        return result

    def repair(self, now):
        return self._clear_snapshot(super().repair(now))

    def fail(self, now):
        return self._clear_snapshot(super().fail(now))

    def cancel(self):
        return self._clear_snapshot(super().cancel())

    @property
    def suppressing(self):
        """True while passive notices are suppressed (used by 7B-2a-iii)."""
        return self["state"] == "active"


_SABOTAGE_CLASSES = {
    "lights": LightsSabotage,
    "communications": CommunicationsSabotage,
}


def make_sabotage(name, cooldown_seconds, game=None):
    """Build the right sabotage object for a type."""
    if name in ("oxygen", "reactor"):
        from .amongus_paired import PairedSabotage  # avoids an import cycle
        return PairedSabotage(name, cooldown_seconds, game=game)
    return _SABOTAGE_CLASSES.get(name, Sabotage)(name, cooldown_seconds)
