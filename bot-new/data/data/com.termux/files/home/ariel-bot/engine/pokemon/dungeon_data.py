# ============================================================
# NIFLHEIM — DUNGEON_DATA.PY
# The generic dungeon zone/floor graph SHAPE — node types, pool
# roll logic, and the registry that per-dungeon data (Cinder
# Hollow, etc.) plugs into. No dungeon-specific content lives in
# this file — that belongs in a per-dungeon data module (see
# DUNGEONS registry below) and is looked up by dungeon_id.
#
# Terminology (see dungeon_system_logic.md for full design notes):
#   - node    — base unit. Player stays in a node through an
#               encounter; only .advance/.goback/.goto change it.
#   - spine   — guaranteed route nodes, never rolled, always hit.
#   - path    — everything between spines. A path is a sequence of
#               traversal steps; each step rolls fixed-vs-batch,
#               then rolls a specific node within that pool.
#   - fixed   — hand-authored, deterministic node content.
#   - batch   — generated filler content, competes against fixed.
#   - subzone — a discoverable node (usually fixed), not on the
#               required critical path. Goes on the player's .goto
#               list once found.
# ============================================================

import random

# ── Node kinds ───────────────────────────────────────────────────
NODE_SPINE = "spine"
NODE_FIXED = "fixed"
NODE_BATCH = "batch"

# ── Discovery scope (see dungeon_system_logic.md) ────────────────
SCOPE_WORLD_ONE_SHOT   = "world_one_shot"    # e.g. Ore Vein — first worldwide find gets reward, node stays enterable
SCOPE_WORLD_REPEATABLE = "world_repeatable"  # e.g. Hunting Ground — first find unlocks for everyone, no reward degradation
SCOPE_PER_PLAYER       = "per_player"        # each player gets their own first-find moment
SCOPE_FIRST_CLEAR_BONUS = "first_clear_bonus"  # e.g. Abandoned Cart Cache — real reward once, downgraded loot after


class DungeonFloor:
    """
    One floor's graph: its spine (guaranteed nodes, in order),
    its paths (each connecting two spine nodes), and the fixed +
    batch pools that paths roll against.
    """

    def __init__(self, floor_number, spine, paths, fixed_nodes, batch_pool, branch_assignments=None):
        self.floor_number = floor_number
        self.spine         = spine          # ordered list of node ids — always hit, never rolled
        self.paths         = paths          # {(from_spine_id, to_spine_id): step_count}
        self.fixed_nodes   = fixed_nodes    # {node_id: FixedNode}
        self.batch_pool    = batch_pool     # list of BatchNode — floor-wide, not branch-restricted (see roll_path_node)
        # {(from_spine_id, to_spine_id): [node_id, ...]} — which fixed
        # nodes are assigned to which branch. Unlike batch (floor-wide),
        # fixed nodes are NOT floor-wide — each is tied to a specific
        # branch. A fixed node with no entry here (e.g. a node meant to
        # sit at a spine fork itself, not on any branch) simply never
        # gets rolled via roll_path_node — it'd need its own placement.
        self.branch_assignments = branch_assignments or {}

    def fixed_ids_for_branch(self, branch):
        return self.branch_assignments.get(tuple(branch), [])

    def spine_entrance(self):
        return self.spine[0] if self.spine else None

    def spine_exit(self):
        return self.spine[-1] if self.spine else None

    def spine_index(self, spine_node_id):
        """Position of a spine node within self.spine, or None if not a spine node."""
        try:
            return self.spine.index(spine_node_id)
        except ValueError:
            return None

    def branch_root(self, branch):
        """The spine node a branch (from_spine_id, to_spine_id) hangs off of — its 'from' end."""
        return branch[0]


GOTO_SECONDS_PER_NODE = 5


def _spine_distance(floor, spine_a, spine_b):
    """Steps between two spine nodes, walking along the spine order."""
    idx_a = floor.spine_index(spine_a)
    idx_b = floor.spine_index(spine_b)
    if idx_a is None or idx_b is None:
        return None
    return abs(idx_a - idx_b)


def goto_distance(floor, from_position, from_node_id, to_position, to_node_id):
    """
    Step-count distance between two points on the same floor, for the
    .goto timer (5 seconds/step — see dungeon-system memory).

    from_position / to_position: {"branch": (from_spine_id, to_spine_id),
    "depth": int}, or None if that side is a spine node (use
    from_node_id/to_node_id as the spine id in that case).

    Model: a branch hangs off its root spine node (branch[0]). Distance
    between two points = walk from each point up to a common spine
    node, then along the spine to the other point's spine anchor, then
    back down the other branch — same-branch nodes just subtract
    depths without needing the spine leg.
    """
    # Both on a spine node — pure spine-order distance.
    if from_position is None and to_position is None:
        return _spine_distance(floor, from_node_id, to_node_id)

    # One spine, one branch node — up to the branch's root, then along
    # the spine from that root to the spine node.
    if from_position is None or to_position is None:
        spine_node = from_node_id if from_position is None else to_node_id
        branch_pos = to_position if from_position is None else from_position
        root = floor.branch_root(tuple(branch_pos["branch"]))
        spine_leg = _spine_distance(floor, spine_node, root)
        if spine_leg is None:
            return None
        return spine_leg + branch_pos["depth"]

    # Both on branch nodes.
    branch_a = tuple(from_position["branch"])
    branch_b = tuple(to_position["branch"])
    if branch_a == branch_b:
        return abs(from_position["depth"] - to_position["depth"])

    # Different branches — route through their respective roots, plus
    # the spine distance between those roots (0 if they share a root,
    # e.g. North Branch and South Branch both hanging off `fork`).
    root_a = floor.branch_root(branch_a)
    root_b = floor.branch_root(branch_b)
    spine_leg = _spine_distance(floor, root_a, root_b)
    if spine_leg is None:
        return None
    return from_position["depth"] + spine_leg + to_position["depth"]


def goto_seconds(floor, from_position, from_node_id, to_position, to_node_id):
    dist = goto_distance(floor, from_position, from_node_id, to_position, to_node_id)
    if dist is None:
        return None
    return dist * GOTO_SECONDS_PER_NODE


def trace_goto_route(floor, from_position, from_node_id, to_position, to_node_id):
    """
    Ordered list of waypoints from origin to destination, one entry
    per step (including the origin as step 0), for landing a player
    mid-journey on .stop. Each waypoint is a dict:
      {"label": <spine node id, or None>, "position": <{"branch","depth"} or None>}
    Exactly one of label/position is set per waypoint — same
    convention as elsewhere (spine nodes use label, branch nodes use
    position). Step N of the returned list corresponds to N steps of
    travel from the origin — index with goto_elapsed_steps() to find
    where a player has gotten to if they .stop before arriving.

    Mirrors goto_distance's routing logic exactly, so the two always
    agree on step count (len(route) - 1 == goto_distance(...)).
    """
    # Both on a spine node — walk the spine order directly.
    if from_position is None and to_position is None:
        idx_a = floor.spine_index(from_node_id)
        idx_b = floor.spine_index(to_node_id)
        if idx_a is None or idx_b is None:
            return None
        step = 1 if idx_b >= idx_a else -1
        return [
            {"label": floor.spine[i], "position": None}
            for i in range(idx_a, idx_b + step, step)
        ]

    # One spine, one branch node.
    if from_position is None or to_position is None:
        going_from_spine = from_position is None
        spine_node = from_node_id if going_from_spine else to_node_id
        branch_pos = to_position if going_from_spine else from_position
        branch = tuple(branch_pos["branch"])
        root = floor.branch_root(branch)

        spine_leg = trace_goto_route(floor, None, spine_node, None, root)
        if spine_leg is None:
            return None
        branch_leg = [
            {"label": None, "position": {"branch": list(branch), "depth": d}}
            for d in range(1, branch_pos["depth"] + 1)
        ]

        route = spine_leg + branch_leg  # spine_node -> root -> depth 1..N
        return route if going_from_spine else list(reversed(route))

    # Both on branch nodes.
    branch_a = tuple(from_position["branch"])
    branch_b = tuple(to_position["branch"])

    if branch_a == branch_b:
        depth_a, depth_b = from_position["depth"], to_position["depth"]
        step = 1 if depth_b >= depth_a else -1
        return [
            {"label": None, "position": {"branch": list(branch_a), "depth": d}}
            for d in range(depth_a, depth_b + step, step)
        ]

    # Different branches — walk from_position down to its root, along
    # the spine to to_position's root, then up to_position's branch.
    root_a = floor.branch_root(branch_a)
    root_b = floor.branch_root(branch_b)

    leg_down = [
        {"label": None, "position": {"branch": list(branch_a), "depth": d}}
        for d in range(from_position["depth"], -1, -1)
    ]  # from_position depth .. 0
    leg_spine = trace_goto_route(floor, None, root_a, None, root_b)
    if leg_spine is None:
        return None
    leg_up = [
        {"label": None, "position": {"branch": list(branch_b), "depth": d}}
        for d in range(1, to_position["depth"] + 1)
    ]  # 1 .. to_position depth

    return leg_down + leg_spine[1:] + leg_up  # leg_spine[0] duplicates leg_down's last waypoint (root_a at depth 0 vs spine label root_a — same tile)


class FixedNode:
    """
    A hand-authored, deterministic node. May be a plain path node
    (encounter pocket, hazard, lore beat) or a discoverable subzone
    (has a `scope` and reward attached).
    """

    def __init__(self, node_id, description, is_subzone=False,
                 scope=None, on_find=None, on_enter=None,
                 encounter=None, tags=None):
        self.node_id     = node_id
        self.description = description
        self.is_subzone  = is_subzone
        self.scope       = scope        # one of the SCOPE_* constants, only meaningful if is_subzone
        self.on_find     = on_find      # callable/reward spec — fires on first discovery ("Find" messaging)
        self.on_enter    = on_enter     # callable/reward spec — fires on every later encounter ("Enter" messaging)
        self.encounter    = encounter    # encounter spec (single mon, or team for a Chained Encounter Zone)
        self.tags         = tags or []   # e.g. ["hazard", "trap-heavy"], ["lore", "one-shot"]


class BatchNode:
    """
    Generated filler content. Batch pool size is independently
    tunable per floor (small, up to ~1000). Content generation
    method is an open question (see dungeon_system_logic.md) — this
    is a minimal placeholder shape (theme tag + template slot) until
    that's decided; NOT hand-authored prose per entry.
    """

    def __init__(self, theme_tags=None, template_id=None):
        self.theme_tags  = theme_tags or []
        self.template_id = template_id


# ── Roll logic (generic — dungeon-agnostic) ──────────────────────
# Fixed pool should be sized SMALLER than the critical-path step
# count for the floor (fixed competes against batch, doesn't
# replace it). Batch is picked MORE OFTEN than fixed on the roll.

FIXED_VS_BATCH_WEIGHT = {
    NODE_FIXED: 0.35,
    NODE_BATCH: 0.65,
}


def roll_path_node(floor, remaining_fixed_ids=None):
    """
    One .dive roll within a path segment. Two-step roll per the
    corrected logic: (1) fixed vs. batch, chance-based; (2) which
    specific node within that pool, also chance-based. NOT
    depth-pinned — which branch/path narrows the pool, there's no
    fixed depth coordinate within it.

    remaining_fixed_ids: optionally restrict the fixed roll to a
    subset (e.g. fixed nodes assigned to the player's current branch
    and not yet placed on it — see cinder_hollow_data.py's
    FLOOR_1_BRANCH_ASSIGNMENTS). Pass None (the default) to roll
    against the whole floor's fixed pool with no restriction. Pass an
    explicit empty list to mean "this branch's fixed pool is
    exhausted" — falls to batch, does NOT widen back out to the whole
    floor (an empty list is a real answer, not "no restriction given").
    """
    pool_kind = random.choices(
        list(FIXED_VS_BATCH_WEIGHT.keys()),
        weights=list(FIXED_VS_BATCH_WEIGHT.values()),
        k=1,
    )[0]

    if pool_kind == NODE_FIXED:
        candidates = list(floor.fixed_nodes.keys()) if remaining_fixed_ids is None else remaining_fixed_ids
        if not candidates:
            # Fixed pool exhausted for this branch — fall back to batch.
            pool_kind = NODE_BATCH
        else:
            node_id = random.choice(candidates)
            return NODE_FIXED, floor.fixed_nodes[node_id]

    # Batch fallback / normal batch roll.
    if not floor.batch_pool:
        return NODE_BATCH, None
    return NODE_BATCH, random.choice(floor.batch_pool)


# ── Dungeon registry ──────────────────────────────────────────────
# Per-dungeon data modules register themselves here by dungeon_id.
# Nothing Cinder-Hollow-specific lives in THIS file — a real entry
# looks like:
#
#   from cinder_hollow_data import CINDER_HOLLOW_FLOORS
#   DUNGEONS["cinder_hollow"] = {
#       "name": "Cinder Hollow",
#       "floors": CINDER_HOLLOW_FLOORS,   # {1: DungeonFloor(...), 2: ..., ...}
#       "trap_pool": [...],
#   }
DUNGEONS = {}


def get_dungeon(dungeon_id):
    return DUNGEONS.get(dungeon_id)


def get_floor(dungeon_id, floor_number):
    dungeon = get_dungeon(dungeon_id)
    if not dungeon:
        return None
    return dungeon.get("floors", {}).get(floor_number)
