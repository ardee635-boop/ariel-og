# ============================================================
# NIFLHEIM — DUNGEON_SESSION.PY
# Persisted state for one player's active dungeon run — one active
# run per player, stored via database.py's player_meta (key/value)
# table under META_KEY. No new table required.
#
# Mirrors explore_session.py's ExploreSession pattern: WhatsApp has
# no persistent connection, so nothing is held in memory across
# requests — always loaded from player_meta at the top of a request
# and saved back at the end.
#
# This file is dungeon-AGNOSTIC. Which dungeon, which floor's graph,
# which encounter tables, etc. all live in dungeon_data.py (or a
# per-dungeon data module) and are looked up by dungeon_id — nothing
# Cinder-Hollow-specific belongs here.
# ============================================================

import json
import time

META_KEY = "dungeon_run"

# ── World-level (not per-player) dungeon state ────────────────────
# Elite Encounter cooldown is GLOBAL — shared across all players, not
# per-player like the rest of this file. There's no dedicated
# world-state table, so this piggybacks on the same get_meta/set_meta
# mechanism used for player_meta, keyed under a fixed sentinel
# "sender" value instead of a real player id. If a real global/world
# state table gets added later, migrate this to use it instead.
WORLD_STATE_SENDER = "__world__"
ELITE_COOLDOWN_KEY_PREFIX = "dungeon_elite_cooldown"  # + ":" + dungeon_id + ":" + floor
ELITE_COOLDOWN_SECONDS = 5 * 60


def _elite_cooldown_key(dungeon_id, floor):
    return f"{ELITE_COOLDOWN_KEY_PREFIX}:{dungeon_id}:{floor}"


def mark_elite_defeated(db, dungeon_id, floor):
    """Call this the moment an Elite Encounter is defeated — starts the global 5-minute cooldown."""
    db.set_meta(WORLD_STATE_SENDER, _elite_cooldown_key(dungeon_id, floor), str(time.time()))


def elite_cooldown_remaining(db, dungeon_id, floor):
    """
    Seconds left on the Elite's global cooldown, or 0 if it's up
    (or has never been defeated — nothing to cool down from).
    """
    raw = db.get_meta(WORLD_STATE_SENDER, _elite_cooldown_key(dungeon_id, floor))
    if not raw:
        return 0
    try:
        defeated_at = float(raw)
    except (TypeError, ValueError):
        return 0
    elapsed = time.time() - defeated_at
    remaining = ELITE_COOLDOWN_SECONDS - elapsed
    return max(0, remaining)


def elite_on_cooldown(db, dungeon_id, floor):
    return elite_cooldown_remaining(db, dungeon_id, floor) > 0


class DungeonSession:
    """
    Holds all state for one player's active dungeon run: which
    dungeon, which floor, which node they're standing in, what
    they've discovered so far this run, and checkpoint progress.
    """

    def __init__(self, sender):
        self.sender            = sender
        self.dungeon_id        = None   # e.g. "cinder_hollow" — key into dungeon data registry
        self.floor              = None   # current floor number (1-indexed)
        self.current_node       = None   # node id player is standing in right now
        self.checkpoint_node    = None   # last checkpoint reached THIS floor — where death/forfeit returns to
        self.locked_in          = False  # True once player confirms .yes at entry; False = still at threshold
        self.discovered_nodes   = {}     # {floor_number: [node_id, ...]} — per-player discovered subzones (.goto list source)
        self.node_positions     = {}     # {floor_number: {node_id: {"branch": str, "depth": int}}} — per-run position, assigned when a node is placed (NOT the spine — spines don't need this, see below)
        self.current_position   = None   # {"branch": str, "depth": int} for current_node — None while standing on a spine node
        self.cleared_spine      = {}     # {floor_number: [node_id, ...]} — spine nodes already passed through this run
        self.dive_uses          = {}     # {floor_number: count} — diminishing-returns counter for .dive on this floor
        self.paused_for_battle  = False  # True while an encounter/chained fight is unresolved — mirrors ExploreSession
        self.start_time         = 0.0    # time.time() when the run began (whole dungeon, not per-floor)
        self.goto_journey       = None   # active .goto travel state — see start_goto_journey() / goto elapsed-steps helpers below

    # ── State queries ───────────────────────────────────────────

    def is_active(self):
        return self.dungeon_id is not None

    def is_locked_in(self):
        return self.is_active() and self.locked_in

    def at_threshold(self):
        """True if arrived via .dive but hasn't confirmed .yes yet."""
        return self.is_active() and not self.locked_in

    def discovered_for_floor(self, floor):
        return set(self.discovered_nodes.get(str(floor), []))

    def dive_count_for_floor(self, floor):
        return self.dive_uses.get(str(floor), 0)

    # ── Lifecycle ────────────────────────────────────────────────

    def arrive(self, dungeon_id, entrance_node):
        """
        Player has reached the dungeon via overworld .dive but has
        NOT yet confirmed entry — locked_in stays False. Mirrors the
        "You have arrived at <Dungeon> ... Do you wish to enter?"
        threshold flow (see dungeon_system_logic.md — entry flow).
        """
        self.dungeon_id       = dungeon_id
        self.floor             = 1
        self.current_node      = entrance_node
        self.checkpoint_node   = entrance_node
        self.locked_in         = False
        self.discovered_nodes  = {}
        self.node_positions    = {}
        self.current_position  = None
        self.cleared_spine     = {}
        self.dive_uses         = {}
        self.paused_for_battle = False
        self.start_time        = time.time()

    def confirm_entry(self):
        """Player answered .yes at the threshold — now locked in."""
        self.locked_in = True

    def decline_entry(self):
        """Player answered .no at the threshold — clears the session, leaves safely."""
        self.end()

    def advance_to_node(self, node_id, position=None):
        """
        position: {"branch": str, "depth": int}, or None if node_id is
        a spine node (spines don't carry a per-run branch position).
        """
        self.current_node = node_id
        self.current_position = position

    def choose_branch(self, branch):
        """
        Player commits to a direction at a spine fork (via .advance).
        branch: (from_spine_id, to_spine_id) tuple identifying the
        path. Sets current_position to depth 0 on that branch — the
        player hasn't placed/found any node on it yet, just entered it.
        """
        self.current_position = {"branch": list(branch), "depth": 0}

    def advance_depth(self):
        """Move one step deeper along the currently-committed branch (called after a .dive places a new node)."""
        if self.current_position is not None:
            self.current_position["depth"] += 1

    def current_branch(self):
        """The (from_spine_id, to_spine_id) tuple of the branch the player is currently on, or None if standing on a spine node."""
        if self.current_position is None:
            return None
        return tuple(self.current_position["branch"])

    def current_depth(self):
        return self.current_position["depth"] if self.current_position is not None else 0

    # ── .goto journey (in-transit travel, mirrors ExploreSession) ────
    # Not an instant teleport — the player is "in transit" for the
    # full travel time, and .stop lands them wherever their elapsed
    # time actually put them along the route, not at the destination.

    def start_goto_journey(self, from_node_id, from_position, to_node_id, to_position, total_steps, seconds_per_step):
        self.goto_journey = {
            "from_node_id": from_node_id,
            "from_position": from_position,
            "to_node_id":    to_node_id,
            "to_position":   to_position,
            "total_steps":   total_steps,
            "seconds_per_step": seconds_per_step,
            "start_time":    time.time(),
        }

    def goto_in_progress(self):
        return self.goto_journey is not None

    def goto_elapsed_steps(self):
        """How many of the journey's steps have elapsed, capped to total_steps."""
        if self.goto_journey is None:
            return 0
        elapsed = time.time() - self.goto_journey["start_time"]
        steps = int(elapsed // self.goto_journey["seconds_per_step"])
        return max(0, min(steps, self.goto_journey["total_steps"]))

    def goto_has_arrived(self):
        if self.goto_journey is None:
            return False
        return self.goto_elapsed_steps() >= self.goto_journey["total_steps"]

    def end_goto_journey(self):
        self.goto_journey = None

    def record_discovery(self, floor, node_id, position=None):
        """
        position: {"branch": str, "depth": int} — the node's per-run
        placement, assigned once when it's first placed via .dive.
        None for spine nodes (spines aren't recorded here at all —
        see record_spine_cleared).
        """
        floor = str(floor)
        found = self.discovered_nodes.setdefault(floor, [])
        if node_id not in found:
            found.append(node_id)
        if position is not None:
            self.node_positions.setdefault(floor, {})[node_id] = position

    def position_of(self, floor, node_id):
        """The recorded (branch, depth) position of a discovered node, or None."""
        return self.node_positions.get(str(floor), {}).get(node_id)

    def record_spine_cleared(self, floor, node_id):
        floor = str(floor)
        cleared = self.cleared_spine.setdefault(floor, [])
        if node_id not in cleared:
            cleared.append(node_id)

    def increment_dive(self, floor):
        floor = str(floor)
        self.dive_uses[floor] = self.dive_uses.get(floor, 0) + 1

    def set_checkpoint(self, node_id):
        self.checkpoint_node = node_id

    def advance_floor(self, next_floor, entrance_node):
        """
        Move to the next floor via the explicit floor-progression
        command (NOT folded into .dive — see dungeon_system_logic.md).
        Only callable once that floor's entrance has been found.
        Per-floor discovery/dive-count state resets; dungeon-wide
        state (dungeon_id, start_time) persists.
        """
        self.floor           = next_floor
        self.current_node    = entrance_node
        self.checkpoint_node = entrance_node
        self.current_position = None  # entrance is a spine node
        self.paused_for_battle = False

    def return_to_checkpoint(self):
        """Death or forfeit — bounce back to the last checkpoint on the current floor."""
        self.current_node      = self.checkpoint_node
        self.current_position  = None  # checkpoints are always spine nodes
        self.paused_for_battle = False

    def end(self):
        """Run over — cleared, died with no continue, or left. Clears the session."""
        self.sender             = self.sender
        self.dungeon_id         = None
        self.floor               = None
        self.current_node        = None
        self.checkpoint_node     = None
        self.locked_in           = False
        self.discovered_nodes    = {}
        self.cleared_spine       = {}
        self.dive_uses           = {}
        self.paused_for_battle   = False
        self.start_time          = 0.0

    # ── Serialise (for DB save via player_meta) ─────────────────

    def to_dict(self):
        return {
            "dungeon_id":       self.dungeon_id,
            "floor":            self.floor,
            "current_node":     self.current_node,
            "checkpoint_node":  self.checkpoint_node,
            "locked_in":        self.locked_in,
            "discovered_nodes": self.discovered_nodes,
            "node_positions":   self.node_positions,
            "current_position": self.current_position,
            "cleared_spine":    self.cleared_spine,
            "dive_uses":        self.dive_uses,
            "paused_for_battle": self.paused_for_battle,
            "start_time":       self.start_time,
            "goto_journey":     self.goto_journey,
        }

    @classmethod
    def from_dict(cls, sender, d):
        s = cls(sender)
        s.dungeon_id       = d.get("dungeon_id")
        s.floor             = d.get("floor")
        s.current_node      = d.get("current_node")
        s.checkpoint_node   = d.get("checkpoint_node")
        s.locked_in         = d.get("locked_in", False)
        s.discovered_nodes  = d.get("discovered_nodes", {})
        s.node_positions    = d.get("node_positions", {})
        s.current_position  = d.get("current_position")
        s.cleared_spine     = d.get("cleared_spine", {})
        s.dive_uses         = d.get("dive_uses", {})
        s.paused_for_battle = d.get("paused_for_battle", False)
        s.start_time        = d.get("start_time", 0.0)
        s.goto_journey       = d.get("goto_journey")
        return s

    # ── DB load/save helpers ─────────────────────────────────────

    @classmethod
    def load(cls, db, sender):
        """Load this player's active dungeon run, or a fresh/empty session."""
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
