"""Pokemon-side tables: pokemon cache, zone discovery, quest board, legacy players, NPC familiarity."""
import json


class PokemonDb:

    def legacy_player_add(self, sender, added_by=None):
        """Add a sender to the legacy list. Idempotent — re-adding is a no-op."""
        self._ex("""
            INSERT INTO legacy_players (sender, added_by, added_at)
            VALUES (?, ?, ?)
            ON CONFLICT (sender) DO NOTHING
        """ if self._mode == "pg" else """
            INSERT OR IGNORE INTO legacy_players (sender, added_by, added_at)
            VALUES (?, ?, ?)
        """, (sender, added_by, __import__("datetime").datetime.utcnow().isoformat()))
        self._commit()

    def legacy_player_exists(self, sender):
        rows = self._fetchall(self._ex(
            "SELECT 1 FROM legacy_players WHERE sender = ?", (sender,)
        ))
        return bool(rows)

    def legacy_players_all(self):
        rows = self._fetchall(self._ex(
            "SELECT sender, added_by, added_at FROM legacy_players"
        ))
        return [{"sender": r[0], "added_by": r[1], "added_at": r[2]} for r in rows]

    def legacy_add_all_signed_in(self, added_by=None):
        """
        Snapshot EVERY currently signed-in player onto the legacy list,
        under every identity we hold for them, so legacy status still
        matches no matter which id shape shows up later (phone JID or
        @lid). Sources:
          - players.sender, players.jid, players.lid  (registered trainers)
          - users.phone (website sign-ups; the Node auth table)
        Idempotent: ids already on the list are counted, not re-added.
        Returns a dict of counts for the admin reply.
        """
        ids = set()
        try:
            rows = self._fetchall(self._ex("SELECT sender, jid, lid FROM players"))
        except Exception:
            # old DB without the jid/lid columns: fall back to sender only
            self._rollback()
            try:
                rows = [(r[0], None, None) for r in
                        self._fetchall(self._ex("SELECT sender FROM players"))]
            except Exception:
                self._rollback()
                rows = []
        for sender, jid, lid in rows:
            for v in (sender, jid, lid):
                v = (v or "").strip()
                if v:
                    ids.add(v)
        n_players = len(rows)

        n_site = 0
        try:
            if self._table_exists("users"):
                for (phone,) in self._fetchall(self._ex("SELECT phone FROM users")):
                    phone = (phone or "").strip().lstrip("+")
                    if phone.isdigit():
                        ids.add(f"{phone}@s.whatsapp.net")
                        n_site += 1
        except Exception:
            self._rollback()

        existing = {r["sender"] for r in self.legacy_players_all()}
        new = sorted(ids - existing)
        for i in new:
            self.legacy_player_add(i, added_by=added_by)
        return {
            "players":  n_players,
            "site":     n_site,
            "ids":      len(ids),
            "added":    len(new),
            "already":  len(ids) - len(new),
            "added_lid": sum(1 for i in new if i.endswith("@lid")),
            "added_jid": sum(1 for i in new if not i.endswith("@lid")),
        }

    def quest_board_generated_at(self):
        """Timestamp (ISO string) of the current board, or None if empty."""
        rows = self._fetchall(self._ex("SELECT generated_at FROM quest_board LIMIT 1"))
        return rows[0][0] if rows else None

    def quest_board_replace(self, quests: list):
        """
        Wholesale board refresh — wipes the old board and inserts the
        new one in a single pass. Called every 30 min (see
        router/quests.py). Any quest a player had already accepted
        stays valid on their own player row (Quest objects there are
        independent copies) even after the board itself rotates.
        """
        self._ex("DELETE FROM quest_board")
        for q in quests:
            self._ex("""
                INSERT INTO quest_board
                    (id, rank, title, type, target, required, reward, penalty, generated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (q["id"], q["rank"], q["title"], q["type"], q.get("target"),
                  q["required"], q["reward"], q["penalty"], q["generated_at"]))
        self._commit()

    def quest_board_all(self):
        """Every quest currently on the board, across all ranks."""
        rows = self._fetchall(self._ex("""
            SELECT id, rank, title, type, target, required, reward, penalty,
                   generated_at, claimed_by, claimed_at
            FROM quest_board
        """))
        cols = ["id", "rank", "title", "type", "target", "required", "reward",
                "penalty", "generated_at", "claimed_by", "claimed_at"]
        return [dict(zip(cols, r)) for r in rows]

    def quest_board_get(self, quest_id):
        rows = self._fetchall(self._ex("""
            SELECT id, rank, title, type, target, required, reward, penalty,
                   generated_at, claimed_by, claimed_at
            FROM quest_board WHERE id = ?
        """, (quest_id,)))
        if not rows:
            return None
        cols = ["id", "rank", "title", "type", "target", "required", "reward",
                "penalty", "generated_at", "claimed_by", "claimed_at"]
        return dict(zip(cols, rows[0]))

    def quest_board_claim(self, quest_id, sender, claimed_at):
        """
        Atomic claim — only succeeds if claimed_by is currently NULL,
        so two players tapping Accept at the same instant can't both
        win the same quest. Returns True if this call won the claim.
        """
        self._ex("""
            UPDATE quest_board SET claimed_by = ?, claimed_at = ?
            WHERE id = ? AND claimed_by IS NULL
        """, (sender, claimed_at, quest_id))
        self._commit()
        row = self.quest_board_get(quest_id)
        return bool(row and row["claimed_by"] == sender)

    def quest_board_release(self, quest_id, sender):
        """
        Return a claimed quest to the board — only the claimant can
        release their own claim. Used when a player declines/returns
        a quest (see the site's Decline action / .quests removal).
        """
        self._ex("""
            UPDATE quest_board SET claimed_by = NULL, claimed_at = NULL
            WHERE id = ? AND claimed_by = ?
        """, (quest_id, sender))
        self._commit()

    # ── PokéAPI cache ─────────────────────────────────────────

    def cache_get(self, key: str):
        row = self._fetchone(self._ex(
            "SELECT data FROM pokemon_cache WHERE key = ?", (key,)
        ))
        return json.loads(row[0]) if row else None

    def cache_set(self, key: str, value: dict):
        payload = json.dumps(value)
        if self._mode == "pg":
            self._ex("""
                INSERT INTO pokemon_cache (key, data) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET data = EXCLUDED.data
            """, (key, payload))
        else:
            self._ex("""
                INSERT INTO pokemon_cache (key, data) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET data = excluded.data
            """, (key, payload))
        self._commit()

    # ── Global zone discovery (Phase 7, Section 13) ─────────────

    def mark_zone_discovered(self, zone_id: str):
        """
        Idempotent — first .explore arrival at a zone (by anyone)
        flips it from tier 1 (undiscovered) to tier 2 (discovered)
        on the site, globally, forever. No-op if already discovered.
        """
        if self._mode == "pg":
            self._ex("""
                INSERT INTO zone_discovery (zone_id) VALUES (?)
                ON CONFLICT (zone_id) DO NOTHING
            """, (zone_id,))
        else:
            self._ex("""
                INSERT OR IGNORE INTO zone_discovery (zone_id) VALUES (?)
            """, (zone_id,))
        self._commit()

    def is_zone_discovered(self, zone_id: str) -> bool:
        row = self._fetchone(self._ex(
            "SELECT 1 FROM zone_discovery WHERE zone_id = ?", (zone_id,)
        ))
        return row is not None

    def list_discovered_zones(self) -> list[str]:
        rows = self._fetchall(self._ex(
            "SELECT zone_id FROM zone_discovery"
        ))
        return [r[0] for r in rows]

    # ── NPC familiarity ───────────────────────────────────────

    def familiarity_get(self, sender, npc_id):
        row = self._fetchone(self._ex(
            "SELECT score, last_talk, talk_count_today FROM npc_familiarity "
            "WHERE sender = ? AND npc_id = ?",
            (sender, npc_id)
        ))
        if not row:
            return {"score": 0, "last_talk": None, "talk_count_today": 0}
        return {"score": row[0], "last_talk": row[1], "talk_count_today": row[2]}

    def familiarity_add(self, sender, npc_id, points, daily_cap=5):
        import datetime
        today = datetime.date.today().isoformat()
        row = self._fetchone(self._ex(
            "SELECT score, last_talk, talk_count_today FROM npc_familiarity "
            "WHERE sender = ? AND npc_id = ?",
            (sender, npc_id)
        ))
        if not row:
            if self._mode == "pg":
                self._ex("""
                    INSERT INTO npc_familiarity (sender, npc_id, score, last_talk, talk_count_today)
                    VALUES (?, ?, ?, ?, 1)
                    ON CONFLICT(sender, npc_id) DO NOTHING
                """, (sender, npc_id, min(points, daily_cap), today))
            else:
                self._ex("""
                    INSERT OR IGNORE INTO npc_familiarity
                    (sender, npc_id, score, last_talk, talk_count_today)
                    VALUES (?, ?, ?, ?, 1)
                """, (sender, npc_id, min(points, daily_cap), today))
            self._commit()
            return
        score, last_talk, talk_today = row
        if last_talk != today:
            talk_today = 0
        if points == 1:
            if talk_today >= daily_cap:
                return
            talk_today += 1
        new_score = min(100, score + points)
        self._ex("""
            UPDATE npc_familiarity SET score = ?, last_talk = ?, talk_count_today = ?
            WHERE sender = ? AND npc_id = ?
        """, (new_score, today, talk_today, sender, npc_id))
        self._commit()

    def familiarity_tier(self, sender, npc_id):
        f = self.familiarity_get(sender, npc_id)
        s = f["score"]
        if s >= 81:   tier = "Bonded"
        elif s >= 61: tier = "Ally"
        elif s >= 41: tier = "Trusted"
        elif s >= 21: tier = "Acquainted"
        else:         tier = "Stranger"
        return tier, s

    def familiarity_all(self, sender):
        rows = self._fetchall(self._ex(
            "SELECT npc_id, score FROM npc_familiarity WHERE sender = ?", (sender,)
        ))
        return {r[0]: r[1] for r in rows}

    def _init_pokemon_tables(self):
        # PokéAPI response cache
        self._ex("""
            CREATE TABLE IF NOT EXISTS pokemon_cache (
                key  TEXT PRIMARY KEY,
                data TEXT NOT NULL
            )
        """)
        # Global zone discovery (Phase 7, Section 13) — one row per zone
        # the FIRST time any player reaches it via .explore. Global, not
        # per-player: this is what flips a zone from tier 1 (undiscovered)
        # to tier 2 (discovered/grayed-out) on the site for everyone.
        # Per-player tier 3 ("personally visited") stays on
        # player.discovered_connections instead — this table only
        # answers "has anyone ever found this zone at all."
        self._ex("""
            CREATE TABLE IF NOT EXISTS zone_discovery (
                zone_id       TEXT PRIMARY KEY,
                discovered_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        # NPC familiarity per player
        self._ex("""
            CREATE TABLE IF NOT EXISTS npc_familiarity (
                sender           TEXT NOT NULL,
                npc_id           TEXT NOT NULL,
                score            INTEGER NOT NULL DEFAULT 0,
                last_talk        TEXT DEFAULT NULL,
                talk_count_today INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (sender, npc_id)
            )
        """)
        self._ex("""
            CREATE TABLE IF NOT EXISTS zone_spawns (
                id               SERIAL PRIMARY KEY,
                zone             TEXT NOT NULL,
                pokemon_name     TEXT NOT NULL,
                pokemon_data     TEXT NOT NULL,
                spawned_by       TEXT NOT NULL,
                spawned_at       TEXT NOT NULL,
                status           TEXT NOT NULL DEFAULT 'active',
                caught_by        TEXT DEFAULT NULL,
                resolved_at      TEXT DEFAULT NULL
            )
        """)
        # Global quest board — shared across every player, not per-zone
        # or per-player. Regenerated wholesale every 30 minutes (see
        # router/quests.py:BOARD_RESET_SECS / _regenerate_board_if_stale).
        # claimed_by/claimed_at live directly on the row so "claimed"
        # is naturally global — once one player accepts a quest, it's
        # frozen for everyone else until returned (claimed_by cleared).
        self._ex("""
            CREATE TABLE IF NOT EXISTS quest_board (
                id           TEXT PRIMARY KEY,
                rank         TEXT NOT NULL,
                title        TEXT NOT NULL,
                type         TEXT NOT NULL,
                target       TEXT DEFAULT NULL,
                required     INTEGER NOT NULL DEFAULT 1,
                reward       INTEGER NOT NULL DEFAULT 0,
                penalty      INTEGER NOT NULL DEFAULT 0,
                generated_at TEXT NOT NULL,
                claimed_by   TEXT DEFAULT NULL,
                claimed_at   TEXT DEFAULT NULL
            )
        """)
        # Legacy players added after the pre-launch snapshot (SPECIAL_FEW
        # in router/site_actions.py). That set is frozen at 19 hardcoded
        # senders with no add mechanism — this table exists so someone
        # missed from the original 19 can still be granted legacy status
        # via .addlegacy without editing/redeploying code. Checked
        # alongside SPECIAL_FEW, never replaces it.
        self._ex("""
            CREATE TABLE IF NOT EXISTS legacy_players (
                sender     TEXT PRIMARY KEY,
                added_by   TEXT,
                added_at   TEXT
            )
        """)

