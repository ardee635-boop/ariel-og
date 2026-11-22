# ============================================================
# NIFLHEIM — EXPLORE_SESSION.PY
# Persisted journey state for .explore — one active journey per
# player, stored via database.py's player_meta (key/value) table
# under META_KEY. No new table required.
# ============================================================

import json
import time

META_KEY = "explore_journey"


class ExploreSession:
    """
    Holds all state for one player's active .explore journey.
    Not held in memory across requests — always loaded from
    player_meta at the top of a request and saved back at the end,
    since WhatsApp has no persistent connection (Section 3 of the
    design notes: "not a live session").
    """

    def __init__(self, sender):
        self.sender             = sender
        self.origin_zone        = None   # zone player left from
        self.direction          = None   # "north"/"south"/"east"/"west"
        self.destination_zone   = None   # resolved target zone (None if dead-end)
        self.total_time_s       = 0.0    # fixed travel time for this journey
        self.start_time         = 0.0    # time.time() when .explore was run
        self.current_zone       = None   # "current effective zone" —
                                          # read by .end (Section 5),
                                          # command-gating (Section 6),
                                          # and the "already traveling"
                                          # rejection message (Section 15)
        self.group_jid          = None   # the chat .explore was run in —
                                          # captured at journey start so the
                                          # proactive push (_arm_arrival_timer)
                                          # sends back to THIS chat, not the
                                          # player's DM. self._last_group_jid
                                          # on the router is a shared,
                                          # per-request value that could
                                          # belong to a different sender's
                                          # chat by the time a background
                                          # timer fires minutes later — this
                                          # avoids that race entirely.
        self.ticks_processed    = 0      # how many 3s ticks already rolled —
                                          # WhatsApp has no persistent connection,
                                          # so ticks are caught up lazily on the
                                          # player's next message, not pushed by
                                          # a live background timer
        self.paused_for_battle  = False  # True while an encounter tick is
                                          # unresolved — stops the proactive
                                          # arrival timer from re-arming and
                                          # spamming more encounters while
                                          # the player hasn't responded yet

    # ── State queries ───────────────────────────────────────────

    def is_active(self):
        return self.origin_zone is not None

    def elapsed(self):
        if not self.is_active():
            return 0.0
        return time.time() - self.start_time

    def remaining(self):
        if not self.is_active():
            return 0.0
        return max(0.0, self.total_time_s - self.elapsed())

    def has_arrived(self):
        return self.is_active() and self.elapsed() >= self.total_time_s

    def pending_ticks(self, tick_seconds=3):
        """
        How many 3s ticks have elapsed but not yet been rolled, capped
        to the journey's remaining travel time (ticks stop counting
        once the player has arrived — arrival is handled separately).
        """
        if not self.is_active():
            return 0
        capped_elapsed = min(self.elapsed(), self.total_time_s)
        total_ticks    = int(capped_elapsed // tick_seconds)
        return max(0, total_ticks - self.ticks_processed)

    # ── Lifecycle ────────────────────────────────────────────────

    def start(self, origin_zone, direction, destination_zone, total_time_s, group_jid=None):
        """Begin a new journey. destination_zone is None for a dead-end."""
        self.origin_zone      = origin_zone
        self.direction        = direction
        self.destination_zone = destination_zone
        self.total_time_s     = total_time_s
        self.start_time       = time.time()
        self.current_zone     = origin_zone
        self.group_jid        = group_jid
        self.ticks_processed  = 0
        self.paused_for_battle = False

    def end(self):
        """
        Voluntary .end or natural arrival — caller reads
        self.current_zone BEFORE calling this to know where the
        player lands, then this clears the journey.
        """
        self.origin_zone      = None
        self.direction        = None
        self.destination_zone = None
        self.total_time_s     = 0.0
        self.start_time       = 0.0
        self.current_zone     = None
        self.group_jid        = None
        self.ticks_processed  = 0
        self.paused_for_battle = False

    # ── Serialise (for DB save via player_meta) ─────────────────

    def to_dict(self):
        return {
            "origin_zone":      self.origin_zone,
            "direction":        self.direction,
            "destination_zone": self.destination_zone,
            "total_time_s":     self.total_time_s,
            "start_time":       self.start_time,
            "current_zone":     self.current_zone,
            "group_jid":        self.group_jid,
            "ticks_processed":  self.ticks_processed,
            "paused_for_battle": self.paused_for_battle,
        }

    @classmethod
    def from_dict(cls, sender, d):
        s = cls(sender)
        s.origin_zone      = d.get("origin_zone")
        s.direction        = d.get("direction")
        s.destination_zone = d.get("destination_zone")
        s.total_time_s     = d.get("total_time_s", 0.0)
        s.start_time       = d.get("start_time", 0.0)
        s.current_zone     = d.get("current_zone")
        s.group_jid        = d.get("group_jid")
        s.ticks_processed  = d.get("ticks_processed", 0)
        s.paused_for_battle = d.get("paused_for_battle", False)
        return s

    # ── DB load/save helpers ─────────────────────────────────────

    @classmethod
    def load(cls, db, sender):
        """Load this player's active journey, or a fresh/empty session."""
        raw = db.get_meta(sender, META_KEY)
        if not raw:
            return cls(sender)
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            return cls(sender)
        return cls.from_dict(sender, data)

    def save(self, db):
        """Persist current state. Deletes the key entirely once inactive."""
        if not self.is_active():
            db.delete_meta(self.sender, META_KEY)
            return
        db.set_meta(self.sender, META_KEY, json.dumps(self.to_dict()))


# ── Pending menu (Section 18) ───────────────────────────────────
# Separate from ExploreSession since a menu is shown BEFORE a journey
# starts — no journey exists yet at that point. Tracks which zone+
# direction the player's next numbered ".explore N" reply refers to,
# so the reply doesn't have to re-guess it.
MENU_META_KEY = "explore_pending_menu"


class PendingMenu:
    def __init__(self, sender):
        self.sender    = sender
        self.zone      = None
        self.direction = None

    def is_active(self):
        return self.zone is not None and self.direction is not None

    def set(self, zone, direction):
        self.zone      = zone
        self.direction = direction

    def clear(self):
        self.zone      = None
        self.direction = None

    @classmethod
    def load(cls, db, sender):
        raw = db.get_meta(sender, MENU_META_KEY)
        m = cls(sender)
        if not raw:
            return m
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            return m
        m.zone      = data.get("zone")
        m.direction = data.get("direction")
        return m

    def save(self, db):
        if not self.is_active():
            db.delete_meta(self.sender, MENU_META_KEY)
            return
        db.set_meta(self.sender, MENU_META_KEY,
                     json.dumps({"zone": self.zone, "direction": self.direction}))
