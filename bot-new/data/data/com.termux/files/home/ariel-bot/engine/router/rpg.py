# ============================================================
# NIFLHEIM — router/rpg.py
# Ariel RPG mode manager — mirrors AmongUsManager's pre_dispatch
# pattern (router/amongus.py) exactly: per-sender mode toggle,
# checked before anything else in handle(), NOT_HANDLED sentinel
# to fall through when this sender isn't in RPG mode.
#
# This is the actual wiring layer — rpg_engine.py (the 4-stage
# pipeline) and rpg_session.py (persistence + registration) do all
# the real work and were built/proven standalone first. Nothing in
# THIS file reimplements pipeline logic; it only routes commands to
# them and formats replies.
# ============================================================

from rpg_session import RpgSession, STARTING_LOCATION
from rpg_engine import handle_rpg_action
from rpg_llm import call_groq
import npc
import rpg_sim
import rpg_battle
import rpg_scene
import townia_trials as trials
from permissions import is_king
import time
import json
import re

# Real persistence for the RPG on/off flag is the shared group_pools
# mechanism (Postgres bot_auth row, see index.js's saveGroupPools/
# loadGroupPools) — same DB-backed store the pokemon/amongus/chat/
# normal pools already use. This file just reads the resolved
# `pool_rpg` flag handed to it per-message; it doesn't persist
# anything itself.

from .rpg_cmds import HANDLERS
from .rpg_cmds._common import (NOT_HANDLED, DispatchContext, _ZERO_WIDTH_SPACE, _READ_MORE_PAD,
                               _read_more_pad, _with_choices, _maybe_fire_mage_delete)



# .status and .skills already exist as live Pokémon commands
# (router/handle.py ~line 35/1027) — when a sender is in RPG mode,
# THESE specific commands are intercepted here and answered from
# the RPG character sheet instead, same "per-sender override" shape
# AmongUsManager already uses for .pokemon off. Every other command
# not listed here falls through untouched (NOT_HANDLED), so a
# player in RPG mode can still use unrelated global commands.
_INTERCEPTED_WHEN_IN_RPG_MODE = {".status", ".skills", ".skill"}


class RpgManager:
    def __init__(self, router):
        self.router = router
        # NOTE: RPG mode used to be a per-sender, in-memory set() here
        # — self.rpg_on — flipped by anyone via a plain ".rpg on"/
        # ".rpg off" text command with no permission check. That had
        # two real bugs: (1) it lived only in process memory, so a
        # restart silently wiped everyone's RPG mode back to off, and
        # (2) it was open to any sender, not King-only. Fixed by
        # moving the actual on/off TOGGLE out of Python entirely —
        # ".rpg on"/".rpg off" are now handled Node-side (index.js's
        # shared pool-toggle block), gated to King only, and persisted
        # to Postgres the same DB-backed way as the pokemon/amongus/
        # chat/normal pools (see saveGroupPools/loadGroupPools). That
        # toggle short-circuits in Node and never reaches this file at
        # all. What Python receives instead, on every message, is the
        # already-resolved `pool_rpg` flag for this group — this class
        # no longer owns or persists the on/off state itself, it just
        # reads the flag it's handed.

    # ── Scene-noun recording (reply first, record after) ──────────
    #
    # The narrator's prose can establish things (a fountain, a squirrel,
    # a corpse) that nothing recorded, so the next action against them
    # was rejected as "not here". After the reply has gone out, a small
    # second call reads that prose and records what it said is present
    # (rpg_scene.extract_nouns). bridge._do_handle runs this after the
    # reply is written, inside the sender's lock, bounded at 5s.
    #
    # compute() is slow and touches no state. apply() is fast, runs on
    # the calling thread, and RELOADS the session from the DB first — the
    # request's own `session` object is not trusted here, so this can
    # only ever add to what was actually saved, never overwrite it.
    def _queue_scene_extraction(self, sender, db, result):
        if not result.get("validation", {}).get("valid", True):
            return  # a rejected action told no story; nothing to record
        prose = result.get("reply") or ""
        if not prose.strip():
            return
        choices = result.get("choices") or []
        # Snapshot what's recorded now so the model isn't asked to
        # re-report it. (Read-only; no reload needed for a snapshot.)
        try:
            snap_sess = RpgSession.load(db, sender)
            snapshot = list(snap_sess.scene_objects)
            location = snap_sess.location
        except Exception:
            snapshot, location = [], None

        def compute():
            return rpg_scene.extract_nouns(prose, snapshot, call_groq,
                                           choices=choices, location=location)

        def apply(extracted):
            new_things, left, verdicts = extracted
            sess = RpgSession.load(db, sender)
            if not sess.exists:
                return

            def _persist_if_shared(t):
                # A corpse (currently the only kind in DEFAULT_
                # PERSISTENT_KINDS) outlasts one player's own scene —
                # every player who later stands at this location
                # should find it too. Written here, at the ONE place
                # both new_things and choice-named things flow
                # through, so neither path can forget it. Nested
                # inside apply() (not a sibling of it) deliberately —
                # it needs `sess`, which only exists once apply() has
                # actually loaded it; a same-named local one level up
                # would have been a different, unset variable.
                if t.get("kind") in rpg_scene.DEFAULT_PERSISTENT_KINDS and sess.location_id:
                    try:
                        db.add_persistent_scene_object(
                            sess.location_id, t["name"], t.get("description", ""),
                            kind=t["kind"], weight=t["weight"], count=t["count"])
                    except Exception as exc:
                        print(f"[RPG SCENE] shared-object write failed: {exc}",
                              file=__import__("sys").stderr)

            for name in left:
                sess.scene_objects = rpg_scene.remove(
                    sess.scene_objects, name, count=99)
            for t in new_things:
                sess.scene_objects = rpg_scene.add(
                    sess.scene_objects, t["name"], "",
                    kind=t["kind"], weight=t["weight"], count=t["count"],
                    source="narration", turn=sess.turn)
                _persist_if_shared(t)
            # The reply already went out with the UNFILTERED choices —
            # that already happened, can't be undone. What this CAN do:
            #   1. Register whatever an "ok" choice named (the librarian
            #      case) — always, regardless of what's happened to the
            #      choices list since. It's real now; that doesn't
            #      depend on which exact list the player is looking at.
            #   2. Fix session.flags["_choices"] (what a numbered ".rpg
            #      1" tap resolves against) so a contradicted choice can
            #      never be honored — but ONLY if it still equals the
            #      list we judged. If it's moved on (another valid turn
            #      already replaced it), overwriting it would silently
            #      revert whatever that later turn set — so 2 is guarded
            #      and 1 isn't.
            if choices:
                filtered, sess.scene_objects = rpg_scene.apply_choice_verdicts(
                    choices, verdicts, sess.scene_objects, turn=sess.turn)
                for t in verdicts.values():
                    for named in t.get("new_things", []):
                        _persist_if_shared(named)
                if sess.flags.get("_choices") == choices:
                    sess.flags["_choices"] = filtered
            sess.save(db)

        rpg_scene.queue_after_reply(sender, compute, apply)

    # ── Command dispatch — gated by the group's persisted pool_rpg flag,
    # not any Python-side state. Mirrors AmongUsManager.pre_dispatch's
    # shape but reads the flag instead of toggling its own. ──
    def pre_dispatch(self, sender, text, quoted_text=None, group_jid=None, pool_rpg=False):
        raw = (text or "").strip()
        low = raw.lower()

        # Belt-and-suspenders: even if some caller still forwards a
        # literal ".rpg on"/".rpg off" text command down to Python
        # (e.g. a DM, where Node's group-pool toggle doesn't apply),
        # never let it flip anything here — just point at the real
        # mechanism so nobody's left thinking they toggled something
        # that silently no-op'd.
        if low in (".rpg on", ".rpg off"):
            return (
                "🗺️ RPG mode is a per-group setting the King turns on/off "
                "with *.rpg on* / *.rpg off* inside the group itself."
            )

        if not pool_rpg:
            return NOT_HANDLED

        return self._dispatch(sender, raw, quoted_text, group_jid)

    # ── RPG command dispatch (only reached when sender is in RPG mode) ──
    def _dispatch(self, sender, text, quoted_text, group_jid):
        parts = text.split(maxsplit=1)
        if not parts:
            return None
        cmd = parts[0].lower()
        rest = parts[1] if len(parts) > 1 else ""

        db = self.router.db
        ctx = DispatchContext(sender, text, quoted_text, group_jid, parts, cmd, rest, db)

        # The old if-chain, one block per file in router/rpg_cmds/, in the same order.
        # A block returns the reply (None ends dispatch) or NOT_HANDLED to fall through.
        for handle in HANDLERS:
            result = handle(self, ctx)
            if result is not NOT_HANDLED:
                return result

        # Not one of ours — let it fall through to the rest of
        # handle() same as AmongUsManager does for unrecognized text
        # while in Among Us mode.
        return None

