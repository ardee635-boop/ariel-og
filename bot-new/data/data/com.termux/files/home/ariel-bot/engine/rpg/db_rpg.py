"""RPG-side tables: places, passages, world NPCs/objects, scene objects, NPC event history."""


class RpgDb:

    # ── RPG world places/passages (Layer 2) ──────────────────────

    def upsert_place(self, place: dict):
        """Insert or fully replace a Place row (dict shape — see
        rpg_places.Place.to_dict()). Used both for seeding the
        hand-authored tree and for persisting a narrator-invented
        place the moment it's created."""
        cols = ("id", "tier", "name", "parent_id",
                "dimension_id", "continent_id", "region_id", "nation_id",
                "state_id", "area_id", "district_id", "location_id",
                "landmark_id", "description", "area_type",
                "settlement_size", "subdivision", "offers_trial",
                "monster_pool", "max_level", "invented")
        values = tuple(place.get(c) for c in cols)
        values = values[:-1] + (int(bool(values[-1])),)  # invented -> 0/1
        placeholders = ", ".join("?" for _ in cols)
        col_list = ", ".join(cols)
        update_list = ", ".join(f"{c} = excluded.{c}" for c in cols if c != "id")
        if self._mode == "pg":
            self._ex(f"""
                INSERT INTO rpg_places ({col_list}) VALUES ({placeholders})
                ON CONFLICT (id) DO UPDATE SET {update_list}
            """, values)
        else:
            self._ex(f"""
                INSERT OR REPLACE INTO rpg_places ({col_list}) VALUES ({placeholders})
            """, values)
        self._commit()

    def get_place(self, place_id: str) -> dict | None:
        rows = self._fetchall(self._ex(
            "SELECT * FROM rpg_places WHERE id = ?", (place_id,)
        ))
        if not rows:
            return None
        cols = ("id", "tier", "name", "parent_id",
                "dimension_id", "continent_id", "region_id", "nation_id",
                "state_id", "area_id", "district_id", "location_id",
                "landmark_id", "description", "area_type",
                "settlement_size", "subdivision", "offers_trial",
                "monster_pool", "max_level", "invented")
        return dict(zip(cols, rows[0]))

    def get_children(self, parent_id: str) -> list[dict]:
        """Every Place whose parent_id is this one — e.g. every
        District under an Area, or every Landmark under a Location."""
        rows = self._fetchall(self._ex(
            "SELECT id FROM rpg_places WHERE parent_id = ?", (parent_id,)
        ))
        return [self.get_place(r[0]) for r in rows]

    def find_place_by_name_and_parent(self, name: str, parent_id: str) -> dict | None:
        """Exact (name, parent_id) match — the dedup check from
        decision #2, before creating a new invented Place. An
        ambiguous near-match (not exact) is NOT resolved here; that's
        left to the LLM per decision #2's "LLM breaks ambiguous ties",
        not a fuzzy query at the DB layer."""
        rows = self._fetchall(self._ex(
            "SELECT id FROM rpg_places WHERE name = ? AND parent_id = ?",
            (name, parent_id)
        ))
        return self.get_place(rows[0][0]) if rows else None

    def add_passage(self, from_id: str, to_id: str, state: str = "established", invented: bool = False):
        if self._mode == "pg":
            self._ex("""
                INSERT INTO rpg_passages (from_id, to_id, state, invented)
                VALUES (?, ?, ?, ?)
                ON CONFLICT (from_id, to_id) DO UPDATE SET state = excluded.state
            """, (from_id, to_id, state, int(invented)))
        else:
            self._ex("""
                INSERT OR REPLACE INTO rpg_passages (from_id, to_id, state, invented)
                VALUES (?, ?, ?, ?)
            """, (from_id, to_id, state, int(invented)))
        self._commit()

    def get_passages_from(self, from_id: str) -> list[dict]:
        rows = self._fetchall(self._ex(
            "SELECT from_id, to_id, state, invented FROM rpg_passages WHERE from_id = ?",
            (from_id,)
        ))
        return [
            {"from_id": r[0], "to_id": r[1], "state": r[2], "invented": bool(r[3])}
            for r in rows
        ]

    def reset_world(self):
        """
        Powers `.resetworld` (router side calls this, then re-seeds
        the hardcoded tree via rpg_places_seed.seed_hardcoded_tree()
        or equivalent — this method only wipes; it does not know how
        to rebuild the hand-authored data, that lives in the seed
        module per decision #4's "new modules alongside the old").

        Wipes, unconditionally: every invented AND hardcoded Place
        row, every passage row, every world NPC, every world object.
        Per the full-reset decision — even hand-authored rows are
        deleted here and must be re-inserted fresh by the caller
        immediately after, so a hand-edited-in-the-DB hardcoded place
        can never survive a reset by accident.

        Does NOT touch players/soulbound/inventory/registrations —
        this resets the WORLD, not player characters. The router-side
        .resetworld command is responsible for also resetting every
        active session's location_id back to STARTING_LOCATION,
        since this wipe can leave old location_id values dangling.
        """
        self._ex("DELETE FROM rpg_places")
        self._ex("DELETE FROM rpg_passages")
        self._ex("DELETE FROM rpg_world_npcs")
        self._ex("DELETE FROM rpg_world_objects")
        self._ex("DELETE FROM rpg_persistent_scene_objects")
        self._commit()

    def add_world_object(self, zone_id: str, name: str, quantity: int | None = None):
        """Seeds a shared, hand-authored object at a location — e.g.
        the northern gate's barrel of crude weapons. Idempotent, same
        pattern as add_world_npc; re-seeding an object that's already
        present is a no-op, so .resetworld's reseed can call this
        freely without double-inserting."""
        if self._mode == "pg":
            self._ex("""
                INSERT INTO rpg_world_objects (zone_id, name, quantity)
                VALUES (?, ?, ?)
                ON CONFLICT (zone_id, name) DO NOTHING
            """, (zone_id, name, quantity))
        else:
            self._ex("""
                INSERT OR IGNORE INTO rpg_world_objects (zone_id, name, quantity)
                VALUES (?, ?, ?)
            """, (zone_id, name, quantity))
        self._commit()

    def get_world_objects(self, zone_id: str) -> list[dict]:
        """All shared objects currently known to exist at this
        location — same "one world" sharing as get_world_npcs."""
        rows = self._fetchall(self._ex(
            "SELECT name, quantity FROM rpg_world_objects WHERE zone_id = ?", (zone_id,)
        ))
        return [{"name": r[0], "quantity": r[1]} for r in rows]

    def take_world_object(self, zone_id: str, name: str) -> bool:
        """
        Attempts to take ONE of a shared object — e.g. a player
        grabbing a weapon from the barrel. Returns True if a unit was
        actually taken, False if the object doesn't exist or is
        already depleted (quantity == 0).

        quantity=NULL means unlimited (a flavor object nobody's meant
        to deplete) — taking from it never decrements and always
        succeeds as long as the row exists.

        This is a real, shared decrement: once the barrel hits 0,
        EVERY player sees it empty, not just whoever took the last
        one — matching the "shared, persistent, important" standard
        this object was built to meet, not scene_objects' per-player
        illusion of scarcity.
        """
        rows = self._fetchall(self._ex(
            "SELECT quantity FROM rpg_world_objects WHERE zone_id = ? AND name = ?",
            (zone_id, name)
        ))
        if not rows:
            return False
        quantity = rows[0][0]
        if quantity is None:
            return True  # unlimited — always succeeds, nothing to decrement
        if quantity <= 0:
            return False
        self._ex(
            "UPDATE rpg_world_objects SET quantity = quantity - 1 "
            "WHERE zone_id = ? AND name = ?",
            (zone_id, name)
        )
        self._commit()
        return True

    # ── Global .rpg world NPCs (shared-world fix) ────────────────
    # Same idea as zone_discovery above, but for WHO is present at
    # an .rpg location rather than whether the location itself has
    # been found. Insert is idempotent on (zone_id, name) — the
    # narrator re-describing an NPC that's already there is a no-op,
    # not a duplicate.

    def npc_active_elsewhere(self, zone_id: str, name: str) -> bool:
        """True if `name` is already seeded at some OTHER zone_id.

        Used to stop the same NPC name existing at two locations at
        once (e.g. "Ken" independently introduced by the narrator at
        two different zones) — names are otherwise only scoped per
        zone, with no global uniqueness. Doesn't decide WHEN an NPC
        should leave a scene (that's the separate, harder removal-
        lifecycle question, still open) — just refuses a second,
        different location for a name that's already active somewhere.
        """
        rows = self._fetchall(self._ex(
            "SELECT 1 FROM rpg_world_npcs WHERE name = ? AND zone_id != ?",
            (name, zone_id)
        ))
        return len(rows) > 0

    def add_world_npc(self, zone_id: str, name: str, hostile: bool = False):
        if self._mode == "pg":
            self._ex("""
                INSERT INTO rpg_world_npcs (zone_id, name, hostile)
                VALUES (?, ?, ?)
                ON CONFLICT (zone_id, name) DO NOTHING
            """, (zone_id, name, int(hostile)))
        else:
            self._ex("""
                INSERT OR IGNORE INTO rpg_world_npcs (zone_id, name, hostile)
                VALUES (?, ?, ?)
            """, (zone_id, name, int(hostile)))
        self._commit()

    def get_world_npcs(self, zone_id: str) -> list[dict]:
        """All NPCs currently known to be present at this .rpg
        location, shared across every player — the same list
        whoever asks, matching the "one world" requirement."""
        rows = self._fetchall(self._ex(
            "SELECT name, hostile FROM rpg_world_npcs WHERE zone_id = ?", (zone_id,)
        ))
        return [{"name": r[0], "hostile": bool(r[1])} for r in rows]

    def remove_world_npc(self, zone_id: str, name: str):
        """For a future 'NPC left the scene' / defeated-in-combat
        case — not called anywhere yet, provided for symmetry so
        NPC removal doesn't require a raw query later."""
        self._ex(
            "DELETE FROM rpg_world_npcs WHERE zone_id = ? AND name = ?",
            (zone_id, name)
        )
        self._commit()

    # ── Persistent shared scene objects (corpses, wreckage — things
    # that EMERGE during play and outlast one player's own scene) ──

    def add_persistent_scene_object(self, zone_id: str, name: str,
                                    description: str = "", kind: str = "item",
                                    weight: str = "light", count: int = 1):
        """Upsert-with-stacking: a second corpse of the same name at
        the same place adds to count rather than duplicating a row or
        silently no-op'ing (unlike add_world_npc's plain INSERT OR
        IGNORE — an NPC is one individual, but a stack of identical
        objects is a real, expected case here, same as rpg_scene.add()
        already handles per-player)."""
        if self._mode == "pg":
            self._ex("""
                INSERT INTO rpg_persistent_scene_objects
                    (zone_id, name, description, kind, weight, count)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT (zone_id, name) DO UPDATE SET
                    count = rpg_persistent_scene_objects.count + EXCLUDED.count,
                    description = CASE
                        WHEN rpg_persistent_scene_objects.description = ''
                        THEN EXCLUDED.description
                        ELSE rpg_persistent_scene_objects.description
                    END
            """, (zone_id, name, description, kind, weight, max(1, int(count))))
        else:
            self._ex("""
                INSERT INTO rpg_persistent_scene_objects
                    (zone_id, name, description, kind, weight, count)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT (zone_id, name) DO UPDATE SET
                    count = count + excluded.count,
                    description = CASE
                        WHEN description = '' THEN excluded.description
                        ELSE description
                    END
            """, (zone_id, name, description, kind, weight, max(1, int(count))))
        self._commit()

    def get_persistent_scene_objects(self, zone_id: str) -> list[dict]:
        """All persistent objects at this location, shared across
        every player who visits — same "one world" contract as
        get_world_npcs. Shape matches rpg_scene.py's entry dict
        (minus the per-session-only id/source/born_turn/ttl fields —
        a caller merging this into a live session's scene_objects
        should run it through rpg_scene.migrate_entry-style handling
        the same as any other loaded entry)."""
        rows = self._fetchall(self._ex(
            "SELECT name, description, kind, weight, count "
            "FROM rpg_persistent_scene_objects WHERE zone_id = ?", (zone_id,)
        ))
        return [{"name": r[0], "description": r[1], "kind": r[2],
                "weight": r[3], "count": r[4]} for r in rows]

    def remove_persistent_scene_object(self, zone_id: str, name: str, count: int = 1):
        """Decrement, deleting the row once it hits zero — mirrors
        rpg_scene.remove()'s stacking-aware removal so a persistent
        entry behaves the same way a per-player one does. count=None
        (or anything >= the current count) removes the whole row."""
        rows = self._fetchall(self._ex(
            "SELECT count FROM rpg_persistent_scene_objects "
            "WHERE zone_id = ? AND name = ?", (zone_id, name)
        ))
        if not rows:
            return
        remaining = rows[0][0] - max(1, int(count or 1))
        if remaining > 0:
            self._ex(
                "UPDATE rpg_persistent_scene_objects SET count = ? "
                "WHERE zone_id = ? AND name = ?", (remaining, zone_id, name)
            )
        else:
            self._ex(
                "DELETE FROM rpg_persistent_scene_objects "
                "WHERE zone_id = ? AND name = ?", (zone_id, name)
            )
        self._commit()

    # ── NPC events (per-player durable NPC memory) ─────────────
    #
    # Design: unbounded storage, bounded retrieval. Every event ever
    # written stays in the table forever (tier="archive" included) —
    # nothing is deleted. What changes per turn is which SLICE gets
    # read back: get_npc_events() below only returns pinned+recent,
    # capped small, so cost per turn never grows no matter how long
    # a player's history with an NPC gets. Full archive is a
    # separate, deliberate call (get_npc_events_archive), never
    # folded into the normal per-turn read.

    RECENT_CAP = 5  # how many "recent" entries stay live before the

                     # oldest ages into archive — small on purpose,
                     # matching the short-history design elsewhere.

    def add_npc_event(self, sender: str, zone_id: str, npc_name: str,
                       text: str, pinned: bool = False):
        """Record one durable fact about a player's history with an
        NPC (e.g. "was slapped by this player once"). pinned=True for
        things that should never be capped out of view (a betrayal,
        a major promise) — everything else enters as "recent" and
        ages into "archive" once RECENT_CAP is exceeded, keeping the
        per-turn read flat regardless of total events."""
        tier = "pinned" if pinned else "recent"
        self._ex("""
            INSERT INTO npc_events (sender, zone_id, npc_name, text, tier)
            VALUES (?, ?, ?, ?, ?)
        """, (sender, zone_id, npc_name, text, tier))
        self._commit()

        if not pinned:
            self._age_out_excess_recent(sender, zone_id, npc_name)

    def _age_out_excess_recent(self, sender: str, zone_id: str, npc_name: str):
        """Keeps only the newest RECENT_CAP "recent" rows live for
        this (sender, npc) pair; anything older gets moved to
        "archive" (never deleted) so retrieval stays capped without
        losing any history."""
        rows = self._fetchall(self._ex("""
            SELECT id FROM npc_events
            WHERE sender = ? AND zone_id = ? AND npc_name = ? AND tier = 'recent'
            ORDER BY created_at DESC, id DESC
        """, (sender, zone_id, npc_name)))
        stale_ids = [r[0] for r in rows[self.RECENT_CAP:]]
        for stale_id in stale_ids:
            self._ex("UPDATE npc_events SET tier = 'archive' WHERE id = ?", (stale_id,))
        if stale_ids:
            self._commit()

    def get_npc_events(self, sender: str, zone_id: str, npc_name: str) -> list[str]:
        """The per-turn read: pinned + recent only, oldest to
        newest, ready to hand straight to the narration prompt. Never
        touches archive — this is what keeps cost flat."""
        rows = self._fetchall(self._ex("""
            SELECT text FROM npc_events
            WHERE sender = ? AND zone_id = ? AND npc_name = ?
              AND tier IN ('pinned', 'recent')
            ORDER BY (tier = 'pinned') DESC, created_at ASC, id ASC
        """, (sender, zone_id, npc_name)))
        return [r[0] for r in rows]

    def get_npc_events_archive(self, sender: str, zone_id: str, npc_name: str) -> list[str]:
        """Full history, unbounded, oldest to newest — deliberate
        call only, never part of the normal per-turn pipeline."""
        rows = self._fetchall(self._ex("""
            SELECT text FROM npc_events
            WHERE sender = ? AND zone_id = ? AND npc_name = ?
            ORDER BY created_at ASC, id ASC
        """, (sender, zone_id, npc_name)))
        return [r[0] for r in rows]

    def _init_rpg_tables(self):
        # Global .rpg NPCs (shared-world fix) — one row per NPC the
        # narrator has introduced at a given .rpg location, keyed by
        # (zone_id, name) so every player who reaches that location
        # sees the SAME NPCs, not their own private hallucinated set
        # (previously these lived only in each player's RpgSession).
        # zone_id here is .rpg's free-text location string, not
        # .explore's zone_id slug — the two systems don't share a
        # location namespace yet, unifying them is a separate task.
        self._ex("""
            CREATE TABLE IF NOT EXISTS rpg_world_npcs (
                zone_id     TEXT NOT NULL,
                name        TEXT NOT NULL,
                hostile     INTEGER NOT NULL DEFAULT 0,
                introduced_at TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (zone_id, name)
            )
        """)
        # Per-player, per-NPC durable memory ("npc_events"). Separate
        # from npc_familiarity (a single numeric score for a
        # different system, Pokemon-side) and from rpg_world_npcs
        # (which only tracks that an NPC EXISTS somewhere, not what
        # happened between a specific player and it).
        #
        # tier is one of "pinned" (always surfaced), "recent" (last
        # few, also always surfaced), or "archive" (kept forever,
        # never auto-read — only pulled if something explicit asks
        # for full history later). Nothing is ever deleted; recent
        # entries age into archive instead (see bump_npc_event_tier
        # below), so cost stays flat per turn regardless of how long
        # a relationship with an NPC has run.
        self._ex("""
            CREATE TABLE IF NOT EXISTS npc_events (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                sender     TEXT NOT NULL,
                zone_id    TEXT NOT NULL,
                npc_name   TEXT NOT NULL,
                text       TEXT NOT NULL,
                tier       TEXT NOT NULL DEFAULT 'recent',
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        # ── rpg_places (Layer 2 of the movement/location rewrite) ──
        # Persists every Place node (see rpg_places.py's Place/
        # build_place) — Dimension through Feature, ONE table for
        # every tier, matching the unified node shape. Replaces
        # rpg_locations.py's seven separate hardcoded dicts once
        # cutover happens (see rpg-movement-rebuild.md decision #4 —
        # this table exists alongside the old system for now, not
        # instead of it).
        #
        # invented=0 rows are the hand-authored seed tree, re-derived
        # from rpg_places.py's seed function on every .resetworld.
        # invented=1 rows are narrator-created mid-session (decision
        # #1: permanent, .resetworld is the ONLY thing that clears
        # them — nothing else ever deletes a Place row).
        self._ex("""
            CREATE TABLE IF NOT EXISTS rpg_places (
                id              TEXT PRIMARY KEY,
                tier            TEXT NOT NULL,
                name            TEXT,
                parent_id       TEXT,
                dimension_id    TEXT,
                continent_id    TEXT,
                region_id       TEXT,
                nation_id       TEXT,
                state_id        TEXT,
                area_id         TEXT,
                district_id     TEXT,
                location_id     TEXT,
                landmark_id     TEXT,
                description     TEXT,
                area_type       TEXT,
                settlement_size TEXT,
                subdivision     TEXT,
                offers_trial    TEXT,
                monster_pool    TEXT,
                max_level       INTEGER,
                invented        INTEGER NOT NULL DEFAULT 0
            )
        """)
        # ── rpg_passages (edges between Places — see movement doc's
        # "places and passages are separate things"). from_id/to_id
        # are rpg_places.id values. state is "established" (the
        # destination Place exists for real), "open" (the passage
        # itself is real/agreed but its destination hasn't been
        # generated yet — lazy, per the movement doc's "real exit,
        # unbuilt destination" case), or "absent" (explicitly
        # rejected — kept as a row, not omitted, so the SAME
        # implausible passage isn't re-judged by the LLM every time
        # it's tried again; see decision #3, LLM-alone plausibility —
        # a rejected result should be sticky, not re-rolled).
        # Undirected connections (the common case) are stored as TWO
        # rows, one each direction — kept explicit/directed always,
        # rather than a special-cased "bidirectional" flag, since a
        # passage that's one-way (a drop, a locked gate from one
        # side) is exactly as real a case in this data model and
        # shouldn't need a different row shape.
        self._ex("""
            CREATE TABLE IF NOT EXISTS rpg_passages (
                from_id    TEXT NOT NULL,
                to_id      TEXT NOT NULL,
                state      TEXT NOT NULL DEFAULT 'established',
                invented   INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (from_id, to_id)
            )
        """)
        # ── rpg_world_objects (Layer 6 follow-up) — shared,
        # persistent, location-bound objects, e.g. the northern
        # gate's barrel of crude weapons. Deliberately separate from
        # scene_objects (rpg_session.py), which is per-player/per-
        # turn and narrator-populated — this table is for a
        # HAND-AUTHORED object that's a fixed, shared fact of a
        # location, the same way rpg_world_npcs is for hand-
        # authored/narrator-introduced NPCs rather than per-player
        # scene state. Same (zone_id, name) keying and idempotent-
        # insert style as rpg_world_npcs, for consistency.
        #
        # quantity is nullable (NULL = effectively unlimited, for a
        # flavor object nobody's meant to deplete) — only decremented
        # by take_world_object() when a real finite count matters
        # (a barrel that can genuinely run out).
        self._ex("""
            CREATE TABLE IF NOT EXISTS rpg_world_objects (
                zone_id       TEXT NOT NULL,
                name          TEXT NOT NULL,
                quantity      INTEGER,
                introduced_at TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (zone_id, name)
            )
        """)
        # Shared, persistent scene objects — the counterpart to
        # rpg_world_objects above, but for things that EMERGE during
        # play rather than being hand-authored (a corpse left after
        # combat, wreckage from an event). Deliberately a separate
        # table: rpg_world_objects's own docstring is explicit that
        # it's for a "HAND-AUTHORED object that's a fixed, shared
        # fact" — conflating the two would blur which objects a
        # world designer put there on purpose vs. which ones just
        # happened. Same (zone_id, name) keying/idempotent-insert
        # style as rpg_world_npcs/rpg_world_objects for consistency;
        # zone_id here is location_id (the stable id), matching how
        # get_world_npcs is actually called despite its own param's
        # legacy name — see rpg_scene.py's DEFAULT_PERSISTENT_KINDS
        # for which kinds (currently: corpse) ever reach this table.
        # kind/weight/count carry rpg_scene.py's own vocabulary
        # (item|scenery|creature|corpse, tiny|light|heavy|fixed) so a
        # row here can be merged back into a session's scene_objects
        # without a shape translation.
        self._ex("""
            CREATE TABLE IF NOT EXISTS rpg_persistent_scene_objects (
                zone_id       TEXT NOT NULL,
                name          TEXT NOT NULL,
                description   TEXT NOT NULL DEFAULT '',
                kind          TEXT NOT NULL DEFAULT 'item',
                weight        TEXT NOT NULL DEFAULT 'light',
                count         INTEGER NOT NULL DEFAULT 1,
                introduced_at TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (zone_id, name)
            )
        """)

