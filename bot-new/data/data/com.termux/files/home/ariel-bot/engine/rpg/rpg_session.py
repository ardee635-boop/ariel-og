# ============================================================
# ARIEL — RPG_SESSION.PY
# Persisted world_state for one player's .rpg session, stored via
# database.py's player_meta (key/value) table — same mechanism
# ExploreSession already uses for .explore journeys, no new table.
#
# Mirrors explore_session.py's load-at-start/save-at-end pattern:
# WhatsApp has no persistent connection, so state is never held in
# memory between messages — always reloaded fresh, mutated, saved
# back.
# ============================================================

import json
import re

from rpg_map import location_name, offered_trial, location_details, location_path, find_place_id_by_name, is_warded_settlement
import rpg_scene

META_KEY = "rpg_world_state"

STARTING_LOCATION_ID = "townia_square"
STARTING_LOCATION    = location_name(STARTING_LOCATION_ID)


def slugify_location(label: str) -> str:
    """
    Fallback ONLY for a location label that isn't in
    the seed map (e.g. a spot the narrator
    invents on the fly, outside the fixed capital map) — turns free
    text into a stable short key the same way the registry's ids are
    shaped, so freeform locations and hand-authored ones can share
    the same rpg_world_npcs keying scheme. Deliberately crude (no
    synonym/dedup handling): two labels that mean the same place
    must already be written the same way to slug the same, this only
    guards against whitespace/punctuation/case drift, not phrasing
    drift.
    """
    slug = re.sub(r"[^a-z0-9]+", "_", label.strip().lower()).strip("_")
    return slug or "unknown"

# Single source of truth for both the primary-stat ORDER (used
# everywhere a stat block is built or displayed) and the flat
# STARTING value every new character begins with — was previously
# duplicated as a literal dict in register() and a separately typed
# tuple in status_text(), which is exactly the kind of thing that
# drifts out of sync if the starting baseline ever changes.
#
# VIT added as an 8th primary (was STR/DEX/SPD/DEF/INT/WIS/CHA only)
# — feeds the new flat-conversion HP formula in secondary_stats.py
# (see compute_hp there): VIT/1, DEF/3, STR/3 each grant +100 HP per
# full unit, floor division, no partial credit for a remainder.
#
# STARTING_PRIMARY_STAT_VALUE dropped from 10 to 5 for ALL 8
# primaries (deliberate — not just VIT). NOTE: mana/stamina/
# physical_attack/etc.'s weighted-blend formulas in
# SECONDARY_FORMULAS were tuned assuming a baseline of 10 (weights
# sum to 1.0, so old-baseline-10 gave secondary=10 flat). At 5, those
# formulas now output 5 flat instead of 10 — still internally
# consistent (still land on whatever the baseline is), just half
# the old starting values. Worth knowing if that undershoots feel
# for mana/stamina/etc., since only HP got a NEW formula — everything
# else still uses the pre-existing weighted blend at the new baseline.
PRIMARY_STAT_NAMES = ("STR", "DEX", "SPD", "DEF", "INT", "WIS", "CHA", "VIT")
STARTING_PRIMARY_STAT_VALUE = 5


class RpgSession:
    """
    Holds one player's persistent world_state for Ariel. Unlike
    ExploreSession (which clears itself when inactive), an RPG
    session is meant to live indefinitely once created — "never-
    ending world" per the design discussion — so there's no
    is_active()/end() pair the way ExploreSession has. Deletion is
    only ever explicit, via .rpg reset/delete.

    Registration flow:
      1. Player sends `.reg` — Ariel replies with a welcome prompt,
         and this session is marked pending_registration=True (but
         exists stays False — no character yet, just "waiting for a
         name"). No quote-reply is required anywhere in this flow —
         Ariel's own outgoing messages quote the player (so players
         can tell which reply is theirs when several are active at
         once), never the other way around.
      2. Player sends `.setname <name>` as a plain command, no reply/
         quote needed.
      3. register() runs: creates a bare soulbound sheet with just
         the name and flat starting stats, seeds world_state at
         Townia's altar, sets exists=True.
    """

    def __init__(self, sender):
        self.sender    = sender
        self.exists    = False   # False until registration completes
        self.pending_registration = False  # True between .reg and a valid .setname reply
        self.location  = None    # display label, e.g. "Townia — the town square, beside the fountain"
        self.location_id = None  # stable key into the seed map (rpg_places_seed) /
                                  # rpg_world_npcs — see slugify_location() for the
                                  # fallback when a location isn't in the fixed registry
        # NPCs are NOT stored per-session anymore — see to_world_state_dict()/
        # apply_engine_result() below. They live in the GLOBAL
        # rpg_world_npcs DB table, keyed by location_id, so every player
        # at the same .rpg location sees the same NPCs ("one world").
        self.flags     = {}      # arbitrary world facts, e.g. {"torch_lit": True}
        self.soulbound = None    # the player's character sheet (soulbound.py schema)
        self.history   = []      # recent (action, reply) pairs — Phase 0: simple
                                  # list, no compression yet. See TODO in class
                                  # docstring below re: context window limits.
        self.turn = 0            # VALID turns taken; the clock scene objects age by
                                  # (rejected/failed turns never advance it, same
                                  # rule as history). See rpg_scene.expire().
        self.scene_objects = []  # per-player, per-location objects that exist
                                  # only in the CURRENT scene (e.g. a thrown can) —
                                  # not a permanent memory, not shared with other
                                  # players. Cleared on travel (see travel_to()).
                                  # Each entry: {"name": str, "description": str}.
                                  # Promoted to something durable only via an
                                  # explicit player action (e.g. picking it up
                                  # into inventory) — not built here; this is
                                  # just the scene-presence layer itself.

    # ── Registration ─────────────────────────────────────────────

    def start_registration(self):
        """
        Called when the player sends .reg. Does NOT create a
        character yet — just arms the session to accept the next
        .setname as this player's registration. No quote-reply is
        required from the player — Ariel's OWN outgoing messages are
        the ones that quote the player (so players can tell which
        reply is theirs when several are active at once), not the
        other way around. The player never needs to quote/reply to
        Ariel for anything.
        """
        self.pending_registration = True
        return (
            "Welcome to Niflheim.\n\n"
            "Use .setname <name> to begin.\n\n"
            "Example: .setname Hiro"
        )

    def register(self, name: str):
        """
        Completes registration: bare Soulbound sheet with just a
        name, flat starting stats (see PRIMARY_STAT_NAMES/
        STARTING_PRIMARY_STAT_VALUE), world seeded at Townia's altar
        with no NPCs present.

        Caller (router side) is responsible for having already
        confirmed self.pending_registration is True before calling
        this — this method itself does not re-check, to keep it a
        plain state mutation.

        Primary stats start flat at STARTING_PRIMARY_STAT_VALUE across
        all eight (STR/DEX/SPD/DEF/INT/WIS/CHA/VIT), per
        PRIMARY_STAT_NAMES above — a clean, unmodified baseline
        before any class/gear/trait modifiers apply. Class is
        hardcoded to "none" for now, matching the .status format
        given in the design discussion.
        """
        name = name.strip()
        self.soulbound = {
            "name": name,
            "series": "player",
            "class": "none",  # hardcoded per design discussion — real class system not built yet
            "level": 1,
            "stats": {stat: STARTING_PRIMARY_STAT_VALUE for stat in PRIMARY_STAT_NAMES},
            "grades": {},
            "skills": [],
            "traits": [],
        }
        self.location = STARTING_LOCATION
        self.location_id = STARTING_LOCATION_ID
        self.flags = {}
        self.history = []
        self.scene_objects = []
        self.turn = 0
        self.exists = True
        self.pending_registration = False

    def travel_to(self, location_id: str):
        """
        Moves the player to location_id and updates the display label
        to match (via rpg_locations.location_name). Caller is
        responsible for having already validated this is a legal
        move — this method itself just performs it. NOTE: this only
        resolves display names against the OLD rpg_locations dicts;
        the live router path no longer calls this method for
        narrator-driven movement — see rpg_movement.move_player_to,
        which does the same job but resolves against the new
        rpg_places/DB-backed tree instead (so it also works for a
        narrator-invented place, which this method's location_name
        lookup cannot resolve). This method is kept for the direct
        callers that still use it — see rpg_engine_test.py's
        scene_objects-expiry test — not for movement in the live bot.

        Clears scene_objects: this is the actual expiry trigger scene
        objects were designed around but didn't have until travel
        existed (see rpg_session.__init__'s scene_objects comment).
        Per-player and per-location by design (see design discussion:
        the can isn't shared with other players), so nothing else
        needs to know this happened — no DB write, no other
        player's session is affected.

        Does NOT touch history or flags — those aren't scene-scoped
        the way scene_objects are; a player's short-term continuity
        and world flags persist across a move, same as before travel
        existed.
        """
        self.location_id = location_id
        self.location = location_name(location_id)
        self.scene_objects = []

    def status_text(self) -> str:
        """
        Powers `.status` — matches the exact format given in the
        design discussion: Name / Class / HP / MP / SP / primary
        stats, plus a pointer to `.skills`.

        HP/MP/SP are read live from secondary_stats.py's real
        formulas (hp: DEF/STR blend, mana: INT/WIS blend, stamina:
        DEF/STR blend) via soulbound.get_secondary_stats() — NOT
        invented here. At a flat starting 10 on every primary, all
        three land exactly on 10.0 (each formula's weights sum to
        1.0), which is why a fresh character shows 10/10/10.

        Flagged: models.py applies HP_POOL_SCALE (×3) on top of the
        raw hp secondary for OwnedPokemon specifically — that scale
        is NOT applied here, since player characters don't go
        through OwnedPokemon at all and nothing in the design
        discussion said to inherit it. Worth a deliberate decision
        later, not assumed silently.
        """
        if not self.exists or not self.soulbound:
            return "You haven't started your journey yet. Send .reg to begin."

        from soulbound_core import get_secondary_stats

        secondaries = get_secondary_stats(self.soulbound, stack=None)
        hp  = secondaries.get("hp", 0)
        mp  = secondaries.get("mana", 0)
        sp  = secondaries.get("stamina", 0)
        stats = self.soulbound.get("stats", {})

        lines = [
            f"Name: {self.soulbound.get('name', 'Unknown')}",
            f"Class: {self.soulbound.get('class', 'none')}",
            f"HP: {hp:g}",
            f"MP: {mp:g}",
            f"SP: {sp:g}",
            "",
        ]
        for stat_name in PRIMARY_STAT_NAMES:
            lines.append(f"{stat_name}: {stats.get(stat_name, 0):g}")
        lines.append("")
        inventory = self.soulbound.get("inventory", [])
        lines.append(f"Inventory: {', '.join(inventory) if inventory else '(empty)'}")
        lines.append("Use .skills to see skills, .inv for full inventory")

        return "\n".join(lines)

    # ── State ────────────────────────────────────────────────────

    def _scene_objects_with_persistent(self, db) -> list:
        """Read-time merge of this player's own scene_objects with
        whatever's SHARED/persistent at the current location (see the
        table's own rpg_persistent_scene_objects docstring — corpses,
        wreckage; not the hand-authored rpg_world_objects). A name
        already present per-player is left alone rather than doubled;
        that entry already came from somewhere (this player caused it,
        or an earlier merge already added it) and re-merging it every
        single turn would just be wasted work, never a real conflict —
        the shared table is the source of truth for its own count."""
        if not self.location_id:
            return self.scene_objects
        try:
            shared = db.get_persistent_scene_objects(self.location_id)
        except Exception:
            return self.scene_objects
        if not shared:
            return self.scene_objects
        own_names = {rpg_scene.normalize_name(o["name"]) for o in self.scene_objects}
        merged = list(self.scene_objects)
        for row in shared:
            if rpg_scene.normalize_name(row["name"]) in own_names:
                continue
            merged.append({
                "id": f"shared:{row['name']}", "name": row["name"],
                "description": row["description"], "count": row["count"],
                "kind": row["kind"], "weight": row["weight"],
                "source": "persistent", "born_turn": self.turn,
                "ttl": None, "persistent": True,
            })
        return merged

    def to_world_state_dict(self, db):
        """
        Shape expected by rpg_engine.py's handle_rpg_action().

        npcs comes from db.get_world_npcs(self.location_id) — the
        GLOBAL, shared-per-location NPC list (rpg_world_npcs table),
        keyed by the STABLE location_id (not the display label) so
        NPCs stay correctly grouped even as location display text
        varies. This is the actual "one shared world" fix: two
        players standing at the same .rpg location now see the SAME
        NPCs, not their own independently-hallucinated set. db is
        required now (not optional) since there's no meaningful
        world_state without it. "location" in the returned dict is
        still the display label — the narrator only ever sees/uses
        that, never the id.

        "offers_trial" tells the narrator whether THIS location can
        offer a class trial right now (see rpg_locations.offered_trial)
        — None everywhere except the Coliseum (warrior) and library
        (mage). This is what lets the narrator recognize trial-accept
        intent in free text ("I step into the ring") without a
        player being able to "intend" a trial from the wrong place.
        Already-classed players still see this (retaking a trial is
        allowed per design) — router-side state, not this dict,
        decides whether a NEW trial actually starts if one's already
        in progress.
        """
        npcs = db.get_world_npcs(self.location_id) if self.location_id else []
        if npcs and self.location_id:
            for npc in npcs:
                # Flat, cheap read regardless of how long this
                # player's history with the NPC is — see
                # database.py's get_npc_events() (pinned+recent only,
                # archive never touched here).
                npc["events"] = db.get_npc_events(self.sender, self.location_id, npc["name"])

        # Pet shop shopkeeper — special-cased instead of going through
        # db.get_world_npcs() like every other NPC here, because her
        # name is PER-PLAYER (see npc.get_shopkeeper_card()), not
        # global-per-zone like rpg_world_npcs assumes. Injected in the
        # same {"name", "hostile", "events"} shape the narrator prompt
        # already expects from existing_npcs, so no prompt-building
        # changes are needed downstream.
        if self.location_id == "townia_pet_shop":
            import npc as _npc
            keeper = _npc.get_shopkeeper_card(db, self.sender)
            npcs = list(npcs) + [{
                "name": keeper["name"],
                "hostile": keeper["hostile"],
                "events": db.get_npc_events(self.sender, self.location_id, keeper["name"]),
            }]

        return {
            "location": self.location,
            "location_details": location_details(self.location_id, db) if self.location_id else {},
            # Full Dimension->...->District->Location path for HERE,
            # per World.md's locked hierarchy (see location_path()'s
            # own docstring) — lets the narrator directly compare the
            # player's own District/Area against each reachable
            # destination's (see "reachable_locations_paths" below)
            # instead of guessing "in vs out" from bare names alone.
            # Real bug this fixes: at a District boundary like the
            # northern gate (District: North, Area: Townia) with
            # connections to BOTH the town square (District: Center,
            # same Area) and the outer forest (District: Outer Ring,
            # Area: the Dark Forest — a different Area entirely), a
            # flat name list gave the narrator nothing to resolve "go
            # OUT" against; the real path data already existed via
            # location_path(), it just wasn't wired in here yet.
            "location_path": location_path(self.location_id, db) if self.location_id else {},
            "npcs":     npcs,
            "player":   {"soulbound": self.soulbound},
            "flags":    self.flags,
            "offers_trial": offered_trial(self.location_id, db) if self.location_id else None,
            "warded": is_warded_settlement(self.location_id, db) if self.location_id else False,
            # Last couple turns only (extract_action/narrate_result
            # cap this further to [-2:] themselves) — short-term
            # continuity for fragment/pronoun messages like "war?",
            # NOT the same mechanism as npc_events' durable per-NPC
            # memory below. See rpg_engine.py's extract_action().
            "history":  self.history[-2:],
            # Per-player, per-scene objects (e.g. a thrown can) —
            # cleared on travel (see travel_to()), never a permanent
            # memory. See __init__'s scene_objects comment. Merged
            # here with anything SHARED/persistent at this location
            # (rpg_persistent_scene_objects — a corpse left after
            # combat, wreckage from an event; see rpg_scene.py's
            # DEFAULT_PERSISTENT_KINDS for which kinds ever reach that
            # table). This is a READ-time merge only, done fresh every
            # turn — nothing here is written back into self.scene_
            # objects, so the merge never needs de-duplication logic
            # of its own beyond what rpg_scene.add() already provides
            # to whichever caller actually persists a change.
            "scene_objects": self._scene_objects_with_persistent(db),
            # Live session object — added for the movement cutover:
            # rpg_engine.handle_rpg_action's "move" branch calls into
            # rpg_movement.handle_move_intent, which needs the real
            # session (not just this snapshot dict) to actually apply
            # a location change. Nothing else in this dict is mutable
            # like this — every other key is a read-only snapshot for
            # the narrator; this one is a deliberate, narrow exception
            # for movement specifically.
            "_session": self,
            # Tier 2 object persistence — see design doc. Two hand
            # slots, matching soulbound.py's existing left_hand/
            # right_hand combat loadout naming (that system already
            # notes the player's off-hand sits empty outside combat,
            # confirming 2 real slots were always the intended model,
            # not 1). Lazily present via .get so older saved
            # characters without this key don't break.
            "holding": self.soulbound.get("holding", {}) if self.soulbound else {},
        }

    def apply_engine_result(self, result: dict, db):
        """
        After rpg_engine.handle_rpg_action() runs, fold anything
        that should persist back into session state.

        NPCs the narrator introduced (result["new_npcs"]) are written
        to db.add_world_npc(), keyed by self.location_id — GLOBAL
        storage, not a per-session list, so every player who reaches
        this location afterward sees them too. add_world_npc() is
        already idempotent on (zone_id, name), so no dedup needed
        here the way the old self.npcs merge required.

        This is the fix for the real gap noted here previously: the
        engine used to be fully read-only against world_state (no
        damage-to-NPC-HP, no flag mutation) — NPC presence is now
        read-write AND shared; HP/flags are still open, unrelated
        gaps, and remain per-player for now.
        """
        action = result["extraction"]["action"]
        reply  = result["reply"]
        # Only record VALID turns. A rejected action never actually
        # happened in the story — it's just an error message telling
        # the player their premise was wrong — so treating it as a
        # real prior turn corrupts the next turn's continuity: the
        # rejection message ("there is no one present...") would get
        # fed back into extract_action/narrate_result as if it were
        # real narration, which is what caused Flag 2 (garbage/null
        # replies on the turn immediately after a rejection).
        if result.get("validation", {}).get("valid", True):
            self.history.append({"action": action, "reply": reply})
        # Phase 0: unbounded growth — no trimming/summarization yet.
        # Flagged in ariel-rpg-bot memory notes as a known gap
        # ("context window vs infinite history").

        new_npcs = result.get("new_npcs", [])
        if new_npcs and self.location_id:
            for npc in new_npcs:
                # Refuse to seed a name that's already active at a
                # DIFFERENT location — names were only ever scoped
                # per zone, so nothing previously stopped the same
                # NPC existing in two places (see database.py's
                # npc_active_elsewhere). Skipping here just prevents
                # a new collision; it doesn't resolve one that
                # already exists in the data.
                if db.npc_active_elsewhere(self.location_id, npc["name"]):
                    continue
                db.add_world_npc(self.location_id, npc["name"], npc.get("hostile", False))

        for npc_event in (result.get("npc_event"), result.get("notable_npc_event")):
            if npc_event and self.location_id:
                db.add_npc_event(
                    self.sender, self.location_id,
                    npc_event["npc_name"], npc_event["text"],
                    pinned=npc_event.get("pinned", False),
                )

        # Scene objects: per-player, in-memory only (see design
        # discussion — not shared like NPCs), so this is a plain list
        # mutation, no DB write. Removed first so a turn that both
        # removes and re-adds the same name in one go (unlikely, but
        # not impossible) ends up correct either way.
        #
        # All of this now goes through rpg_scene (ids, stacking counts,
        # weight, loose name matching, expiry) instead of exact-string
        # list edits. The result's new_scene_objects/removed_scene_objects
        # keys keep their old shape, so the router and narrator contract
        # don't change — only what happens to them here.
        turn_was_valid = result.get("validation", {}).get("valid", True)
        if turn_was_valid:
            # Only VALID turns age the scene. A rejected move or a
            # premise error never happened in the story, so it must
            # not make a squirrel wander off.
            self.turn += 1

        for name in result.get("removed_scene_objects", []):
            self.scene_objects = rpg_scene.remove(self.scene_objects, name)

        for obj in result.get("new_scene_objects", []):
            # Legacy shape (drop/throw): {"name","description"} only.
            # Extraction-pass shape adds kind/weight/count. Missing
            # fields fall back to a carryable item, matching how a
            # dropped can has always behaved.
            self.scene_objects = rpg_scene.add(
                self.scene_objects, obj["name"], obj.get("description", ""),
                kind=obj.get("kind", "item"), weight=obj.get("weight", "light"),
                source=obj.get("source", "drop"), turn=self.turn,
                count=obj.get("count"), ttl=obj.get("ttl", "default"),
                persistent=obj.get("persistent"),
            )

        if turn_was_valid:
            self.scene_objects, _gone = rpg_scene.expire(self.scene_objects, self.turn)

    def summarize(self, db) -> str:
        """
        Powers `.rpg state` — a rough summary of the player's last
        action, where they are, what they're doing, and whether they
        have anything to do (per the design discussion). Deliberately
        plain/templated, not an LLM call — this is meant to be a
        quick, reliable status check, not more narration.

        db is now required: NPCs present are read live from the
        shared rpg_world_npcs table (same source to_world_state_dict()
        uses), not a per-session list.
        """
        if not self.exists:
            if self.pending_registration:
                return "You haven't finished registering yet. Use .setname <name>."
            return "You haven't started your journey yet. Send .reg to begin."

        name = self.soulbound.get("name", "your character") if self.soulbound else "your character"
        lines = [f"*{name}*", f"Location: {self.location or 'unknown'}"]

        if self.history:
            last = self.history[-1]
            lines.append(f"Last action: {last['action']}")
            lines.append(f"What happened: {last['reply']}")
        else:
            lines.append("You haven't done anything yet — send `.rpg <action>` to begin.")

        npcs = db.get_world_npcs(self.location_id) if self.location_id else []
        if npcs:
            names = ", ".join(npc["name"] for npc in npcs)
            lines.append(f"Present with you: {names}")
        else:
            lines.append("No one else is here right now.")

        # Objectives/quests are still a stub (per design discussion —
        # deferred on purpose), so this is honest about not having
        # anything real to report yet rather than inventing content.
        lines.append("Objectives: none tracked yet.")

        return "\n".join(lines)

    # ── Serialise ────────────────────────────────────────────────

    def to_dict(self):
        return {
            "exists":               self.exists,
            "pending_registration": self.pending_registration,
            "location":             self.location,
            "location_id":          self.location_id,
            "flags":                self.flags,
            "soulbound":            self.soulbound,
            "history":              self.history,
            "scene_objects":        self.scene_objects,
            "turn":                 self.turn,
        }

    @classmethod
    def from_dict(cls, sender, d):
        s = cls(sender)
        s.exists               = d.get("exists", False)
        s.pending_registration = d.get("pending_registration", False)
        s.location             = d.get("location")
        # Backward-compat: a session saved before location_id existed
        # has no such key. First try to match the saved label against
        # a known registry entry (so an old player lands on the SAME
        # id everyone else uses, not a one-off slug of their own) —
        # only fall back to raw slugify_location() if the label isn't
        # in the fixed registry at all (e.g. player was somewhere the
        # narrator invented freeform). Best-effort, not perfect, but
        # keeps existing players sharing the real NPC pool instead of
        # silently landing in an empty bucket of their own.
        saved_location_id = d.get("location_id")
        if not saved_location_id and s.location:
            saved_location_id = find_place_id_by_name(s.location) \
                or slugify_location(s.location)
        s.location_id          = saved_location_id
        # npcs intentionally dropped — global rpg_world_npcs table now,
        # not per-session state. An old saved session with a leftover
        # "npcs" key from before this change is simply ignored here,
        # not migrated — those were per-player-hallucinated NPCs
        # anyway, not canonical, nothing worth carrying forward.
        s.flags                = d.get("flags", {})
        s.soulbound             = d.get("soulbound")
        s.history               = d.get("history", [])
        # Backward-compat: sessions saved before scene_objects existed
        # just get an empty scene, same spirit as history's default.
        s.turn                  = int(d.get("turn", 0) or 0)
        # Old sessions stored {"name","description"} only. Upgrade them
        # in place (count 1, light, source "legacy") so nobody's saved
        # scene breaks. New-shape entries pass through untouched.
        s.scene_objects         = rpg_scene.migrate_list(
            d.get("scene_objects", []), turn=s.turn)
        return s

    # ── DB load/save ─────────────────────────────────────────────

    @classmethod
    def load(cls, db, sender):
        """Load this player's RPG world_state, or a fresh/empty session."""
        raw = db.get_meta(sender, META_KEY)
        if not raw:
            return cls(sender)
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            return cls(sender)
        return cls.from_dict(sender, data)

    def save(self, db):
        """
        Persist current state. Unlike ExploreSession, never auto-
        deletes — an RPG session persisting is the whole point.
        """
        db.set_meta(self.sender, META_KEY, json.dumps(self.to_dict()))

    def delete(self, db):
        """Explicit wipe — for a future .rpg reset/delete command."""
        db.delete_meta(self.sender, META_KEY)
        self.__init__(self.sender)
