"""Session 8 match simulator: lobby to victory on a fake clock.

Drives the real AmongUsManager and Game with scripted bots. Time is a plain
number: each simulated second the world is ticked, then bots send commands
stamped with that second. No sleeping, no wall-clock timers firing.
"""

import random
import re
import sys
import types
from pathlib import Path

BOT_ROOT = Path(__file__).resolve().parents[1]
ENGINE_DIR = BOT_ROOT / "engine"
ROUTER_DIR = ENGINE_DIR / "router"
sys.path[:0] = [str(ENGINE_DIR), str(ENGINE_DIR / "pokemon"), str(ENGINE_DIR / "core")]
router_package = types.ModuleType("router")
router_package.__path__ = [str(ROUTER_DIR)]
sys.modules.setdefault("router", router_package)

import os  # noqa: E402
os.environ.setdefault("AMONGUS_STAGE_OFFLINE", "1")  # tests never touch the network
os.environ.setdefault("AMONGUS_FIXED_MAP", "skeld")   # lobby maps are random; tests assume Skeld
# Shipped links, minus the single-picture slots, so text-reply tests stay text-only.
import json as _json  # noqa: E402
import tempfile as _tempfile  # noqa: E402
from router import amongus_images as _IMG  # noqa: E402
_links = _json.loads(_IMG.DEFAULT_FILE.read_text(encoding="utf-8"))
_links["lobby"] = ""
_links["tasks_list"] = ""
_tmpdir = _tempfile.mkdtemp(prefix="amongus_links_")
_IMG.DEFAULT_FILE = Path(_tmpdir) / "image_links.json"
_IMG.DEFAULT_FILE.write_text(_json.dumps(_links), encoding="utf-8")
from router import amongus_config as C  # noqa: E402
from router.amongus import AmongUsManager  # noqa: E402

# The simulator runs on a fake clock, so the timed ejection reveal (real-time
# gaps between its messages) is collapsed: every message is sent at once.
C.EJECTION_REVEAL_STEP_SECONDS = 0.0

GROUP = "120363000000000001@g.us"
GHOST_GROUP = "120363000000000002@g.us"
T0 = 1_800_000_000.0
JID_RE = re.compile(r"\d{8,}@(s\.whatsapp\.net|lid|g\.us)")


class SimRouter:
    def __init__(self):
        self.group = []   # (t, text)
        self.dms = []     # (t, jid, text)
        self.actions = []
        self.clock = T0

    def _direct_send(self, message, group_jid=None, allow_dm=False, **kw):
        if kw.get("group_action"):
            self.actions.append((self.clock, kw["group_action"]))
        elif allow_dm:
            self.dms.append((self.clock, group_jid, message))
        else:
            self.group.append((self.clock, message))


def jid_for(i):
    return f"23480{i:07d}@s.whatsapp.net"


class Match:
    def __init__(self, n=8, seed=0, force_roles=None):
        random.seed(seed)
        self.rng = random.Random(seed ^ 0x5EED)
        self.router = SimRouter()
        self.mgr = AmongUsManager(self.router, GROUP)
        self.mgr.game_kwargs = {"start_clock": False}
        self.jids = [jid_for(i) for i in range(1, n + 1)]
        self.t = T0
        self.replies = []   # (t, jid, text)
        self.errors = []
        for j in self.jids:
            self.send(j, ".amongus on")
        self.send(self.jids[0], ".lobby open", group=True)
        for j in self.jids[1:]:
            self.send(j, ".join", group=True)
        self.send(self.jids[0], ".lobby start", group=True)
        self.game = self.mgr.game
        assert self.game is not None, "game did not start"
        if force_roles:
            force_roles(self.game)

    # ── I/O ──
    def send(self, jid, text, group=False, quoted=None):
        self.router.clock = self.t
        # Communications repair answers are only accepted in the game group
        # (Package 6a), so a well-behaved bot sends them there.
        game = getattr(self, "game", None)
        if game is not None and not group and text.lower().startswith(".task answer "):
            if game.is_comms_phrase_answer(jid, text, quoted):
                group = True
        try:
            out = self.mgr._pre_dispatch(
                jid, text, group_jid=GROUP if group else None,
                received_at_ms=round(self.t * 1000), quoted_text=quoted,
            )
        except Exception as exc:  # recorded, never swallowed silently
            self.errors.append((self.t, jid, text, repr(exc)))
            raise
        if isinstance(out, str):
            self.replies.append((self.t, jid, out))
        return out

    def tick(self):
        self.t += 1.0
        self.router.clock = self.t
        g = self.game
        with g.lock:
            g._tick(self.t)

    # ── introspection helpers (bots may cheat; real players cannot) ──
    def by_color(self, color):
        return next(p for p in self.game.players.values() if p.color == color)

    def living(self):
        return [p for p in self.game.players.values() if p.alive and not p.departed]

    def player(self, jid):
        return self.game.players[jid]

    def outputs_after(self, t):
        return (
            [x for x in self.router.group if x[0] > t],
            [x for x in self.router.dms if x[0] > t],
        )

    def cleanup(self):
        self.game.close()
        self.mgr._cancel_timer()


# ───────────────────────── bots ─────────────────────────
ROOMS = None


def _rooms(match):
    return list(match.game.map.rooms)


FUZZ_COMMANDS = (
    ".m {room}", ".m {room}", ".m {room}", ".m {n}", ".stop", ".goback", ".where",
    ".status", ".task", ".task", ".task 1", ".task 2", ".task next", ".tasks",
    ".players", ".progress", ".vent", ".vent {room}", ".vitals", ".witness",
    ".cds", ".cooldown", ".follow {color}", ".unfollow", ".cscene", ".report",
    ".meeting", ".vote {color}", ".vote skip", ".kill {color}", ".kill",
    ".sabotage lights", ".sabotage comms", ".sabotage o2", ".sabotage reactor",
    ".sabotage oxygen", ".sabotage", "scan", ".scan", ".task answer 1",
    ".task answer x", ".say hello", ".m", ".m 999", ".m nowhere", ".kill nobody",
    ".follow", ".vote", ".vote zzz", ".repair", ".debugrepair", "hello there",
    ".leave", ".join", ".lobby open", ".lobby start", ".amenu", "",
)


def fuzz_step(match, intensity=0.25, allow_leave=False):
    rng = match.rng
    rooms = _rooms(match)
    colors = [p.color for p in match.game.players.values()]
    for jid in match.jids:
        if rng.random() > intensity:
            continue
        cmd = rng.choice(FUZZ_COMMANDS)
        if cmd == ".leave" and not allow_leave:
            continue
        text = cmd.format(
            room=rng.choice(rooms).replace("_", " "),
            n=rng.randint(1, len(rooms)),
            color=rng.choice(colors),
        )
        if not text:
            continue
        # sometimes answer the live task prompt correctly
        p = match.game.players[jid]
        if p.task_in_progress and rng.random() < 0.5:
            text = f".task answer {p.task_in_progress.get('expected')}"
        in_group = rng.random() < 0.08
        match.send(jid, text, group=in_group)


def _own_tasks(game, p):
    return [t for t in p.tasks if not t.get("done")]


def smart_crew_step(match, p):
    """One decision for a crew bot. Returns nothing; sends at most one command."""
    g = match.game
    jid = p.jid
    if g._meeting:
        if jid not in g._meeting["votes"] and match.t >= g._meeting["opens_at"]:
            imps = [x for x in match.living() if x.role == "impostor"]
            if imps and match.rng.random() < match.vote_accuracy:
                target = match.rng.choice(imps).color
            else:
                target = "skip"
            match.send(jid, f".vote {target}")
        return
    if p.task_in_progress:
        match.send(jid, f".task answer {p.task_in_progress.get('expected')}")
        return
    if not p.settled or p.path:
        return
    if g._bodies.get(p.room):
        match.send(jid, ".report")
        return
    todo = _own_tasks(g, p) if p.alive else [
        t for t in g._team_tasks if not t.get("done")
    ]
    if not todo:
        return
    here = [t for t in todo if t["room"] == p.room] if p.alive else todo[:1]
    if here:
        cands = g._task_candidates(p, room_only=p.alive)
        for i, c in enumerate(cands, start=1):
            if c["id"] == here[0]["id"]:
                match.send(jid, f".task {i}")
                return
        match.send(jid, ".task")
        return
    match.send(jid, f".m {todo[0]['room']}")


def smart_impostor_step(match, p, kill=True, sabotage=None):
    g = match.game
    jid = p.jid
    if g._meeting:
        if jid not in g._meeting["votes"] and match.t >= g._meeting["opens_at"]:
            crew = [x for x in match.living() if x.role != "impostor"]
            match.send(jid, f".vote {match.rng.choice(crew).color}" if crew else ".vote skip")
        return
    if sabotage and match.rng.random() < 0.15:
        match.send(jid, f".sabotage {match.rng.choice(sabotage)}")
    if p.task_in_progress or not p.settled or p.path:
        return
    if kill:
        victims = [
            x for x in match.living()
            if x.role != "impostor" and x.room == p.room and x.settled
        ]
        if victims:
            match.send(jid, f".kill {match.rng.choice(victims).color}")
            return
    if match.rng.random() < 0.3:
        match.send(jid, f".m {match.rng.choice(_rooms(match))}")


def smart_step(match, kill=True, sabotage=None, crew_acts=True):
    for jid in match.jids:
        p = match.game.players[jid]
        if p.departed:
            continue
        if p.role == "impostor" and p.alive:
            smart_impostor_step(match, p, kill, sabotage)
        elif crew_acts:
            smart_crew_step(match, p)
        # call a meeting when a body is known and nobody is voting
    g = match.game
    if not g._meeting and g._bodies and match.rng.random() < 0.05:
        for room, bodies in g._bodies.items():
            if bodies:
                for p in match.living():
                    if p.role != "impostor" and p.room == room and p.settled:
                        match.send(p.jid, ".report")
                        return


# ───────────────────────── invariants ─────────────────────────
class InvariantError(AssertionError):
    pass


def check_invariants(match, seen):
    """Cheap per-step checks. ``seen`` carries counters between calls."""
    g = match.game
    r = match.router
    # 1. identity: no raw JID in anything a player or the group can read
    def leak(kind, t, text):
        shape = JID_RE.sub("<JID>", text)
        seen.setdefault("leaks", {}).setdefault(kind, set()).add(shape[:90])

    for t, text in r.group[seen["group"]:]:
        if JID_RE.search(text):
            leak("group", t, text)
    for t, jid, text in r.dms[seen["dms"]:]:
        if JID_RE.search(text):
            leak("dm", t, text)
    for t, jid, text in match.replies[seen["replies"]:]:
        if JID_RE.search(text):
            leak("reply", t, text)
    seen["group"], seen["dms"], seen["replies"] = (
        len(r.group), len(r.dms), len(match.replies),
    )
    # 2. state sanity
    for p in g.players.values():
        if p.in_vent_until is not None and p.role != "impostor":
            raise InvariantError(f"{p.color} is a non-impostor in a vent")
        if not p.alive and p.pending_kill:
            raise InvariantError(f"{p.color} is dead with a pending kill")
        if p.departed and p.task_in_progress:
            raise InvariantError(f"{p.color} departed with a live task interaction")
    if g._meeting:
        for p in g.players.values():
            if p.pending_kill:
                raise InvariantError("pending kill during a meeting")
    # 3. after the end: silence and no live machinery
    if g.over:
        if g._timers:
            raise InvariantError("timers pending after game end")
        if g._meeting:
            raise InvariantError("meeting still open after game end")
        for name, s in g._sabotages.items():
            if s["state"] == "active":
                raise InvariantError(f"{name} still active after game end")
        for p in g.players.values():
            if p.task_in_progress:
                raise InvariantError(f"{p.color} still has a task interaction after end")
            if p.pending_kill:
                raise InvariantError(f"{p.color} has a pending kill after end")


def new_seen():
    return {"group": 0, "dms": 0, "replies": 0}


def run(match, steps, step_fn, check=True):
    """Tick + bots for up to ``steps`` simulated seconds; stops at game end.

    Returns the number of steps used.
    """
    seen = new_seen()
    for i in range(steps):
        match.tick()
        if match.game.over:
            break
        step_fn(match)
        if check:
            check_invariants(match, seen)
        if match.game.over:
            break
    if check:
        check_invariants(match, seen)
    return i + 1
