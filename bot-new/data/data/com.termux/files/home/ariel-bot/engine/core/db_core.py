"""Database core: connection, query helpers, player store, key/value meta, table creation."""
import json, os, sys
from models import Player


def _get_conn():
    url = os.environ.get("SUPABASE_DB_URL", "")
    if url:
        try:
            import psycopg2
            conn = psycopg2.connect(url + "?sslmode=require")
            conn.autocommit = False
            print("[DB] Connected to Supabase PostgreSQL.", flush=True, file=sys.stderr)
            return conn, "pg"
        except Exception as e:
            print(f"[DB] Supabase failed: {e} — falling back to SQLite.", flush=True, file=sys.stderr)

    import sqlite3
    path = os.path.join(
        os.environ.get("RAILWAY_VOLUME_MOUNT_PATH", __import__("paths").ROOT),
        "niflheim.db"
    )
    print(f"[DB] Using local SQLite at {path}", flush=True, file=sys.stderr)
    return sqlite3.connect(path, check_same_thread=False), "sqlite"




class DbCore:

    def __init__(self):
        self.conn, self._mode = _get_conn()
        self._init_tables()

    # ── Query helpers ─────────────────────────────────────────

    def _ex(self, sql, params=()):
        """Execute — normalises ? placeholders for PostgreSQL."""
        if self._mode == "pg":
            sql = sql.replace("?", "%s")
            sql = sql.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY")
            sql = sql.replace("(datetime('now'))", "(NOW())")
            cur = self.conn.cursor()
            try:
                cur.execute(sql, params)
            except Exception:
                # On Postgres, a failed statement poisons the whole
                # transaction — every later _ex() call would silently
                # fail too (InFailedSqlTransaction) until the connection
                # is rolled back. Roll back immediately so one bad
                # statement can't cascade-fail unrelated ones, then
                # re-raise so the caller still sees (and can log/handle)
                # the original error.
                self._rollback()
                raise
            return cur
        return self.conn.execute(sql, params)

    def _commit(self):
        self.conn.commit()

    def _rollback(self):
        try:
            self.conn.rollback()
        except Exception:
            pass

    def _fetchone(self, cur):
        return cur.fetchone()

    def _fetchall(self, cur):
        return cur.fetchall()

    def all_senders_with_meta_key(self, key: str) -> list[str]:
        """Every sender that has a row under this meta key — used by
        .resetworld to find every active RPG session (key=
        rpg_session.META_KEY = "rpg_world_state") so their location
        can be reset after a world wipe, without needing a separate
        sessions-list table."""
        rows = self._fetchall(self._ex(
            "SELECT sender FROM player_meta WHERE key = ?", (key,)
        ))
        return [r[0] for r in rows]

    # ── Players ───────────────────────────────────────────────

    def save(self, sender, player):
        payload = json.dumps(player.to_dict())
        if self._mode == "pg":
            self._ex("""
                INSERT INTO players (sender, data) VALUES (?, ?)
                ON CONFLICT(sender) DO UPDATE SET data = EXCLUDED.data
            """, (sender, payload))
        else:
            self._ex("""
                INSERT INTO players (sender, data) VALUES (?, ?)
                ON CONFLICT(sender) DO UPDATE SET data = excluded.data
            """, (sender, payload))
        self._commit()

    def load(self, sender):
        row = self._fetchone(self._ex(
            "SELECT data FROM players WHERE sender = ?", (sender,)
        ))
        if not row:
            return None
        player = Player.from_dict(json.loads(row[0]))
        for mon in list(player.party) + list(player.box):
            if getattr(mon, "legacy_stats", False):
                try:
                    mon.hydrate_base_stats(self)
                except Exception:
                    pass   # offline / not cached: approximated stats stay until next load
        return player

    def exists(self, sender):
        row = self._fetchone(self._ex(
            "SELECT 1 FROM players WHERE sender = ?", (sender,)
        ))
        return row is not None

    def delete(self, sender):
        """Full profile wipe. Purges every sender-keyed table across both
        the Python game DB and the Node/JS auth+moderation tables (`users`,
        `warnings`) — all of which live in the same Postgres database, just
        under SUPABASE_DB_URL, created by different services.

        Deliberately spares:
        - `legacy_players` — legacy status is meant to survive a reset.
        - `bot_ranks` — royalty/king/lord/baron rank is meant to survive
          a reset too (it's a standing title, not game progress).
        """
        self._ex("DELETE FROM players WHERE sender = ?", (sender,))
        self._ex("DELETE FROM registrations WHERE sender = ?", (sender,))
        self._ex("DELETE FROM player_meta WHERE sender = ?", (sender,))
        self._ex("DELETE FROM npc_familiarity WHERE sender = ?", (sender,))
        self._ex("DELETE FROM ariel_affection WHERE sender = ?", (sender,))
        self._ex(
            "DELETE FROM ariel_directives WHERE owner = ? OR target_jid = ?",
            (sender, sender),
        )
        self._ex("DELETE FROM zone_spawns WHERE spawned_by = ?", (sender,))
        # Clear any quest this sender had claimed so it isn't stuck
        # "claimed" forever and blocked for everyone else.
        self._ex(
            "UPDATE quest_board SET claimed_by = NULL, claimed_at = NULL "
            "WHERE claimed_by = ?",
            (sender,),
        )

        # ── Cross-service tables ──────────────────────────────
        # `users`, `warnings`, `bot_ranks` are created by the Node/index.js
        # and commands.js side, but they live in the SAME Postgres database
        # (same SUPABASE_DB_URL), so this connection can reach them too.
        # Guard each with a table-exists check so SQLite/local dev (where
        # these tables never get created) doesn't blow up.
        phone = sender.split("@")[0] if "@" in sender else sender
        for table, sql, params in (
            ("users",    "DELETE FROM users WHERE phone = ?", (phone,)),
            ("warnings", "DELETE FROM warnings WHERE user_jid = ?", (sender,)),
        ):
            try:
                if self._table_exists(table):
                    self._ex(sql, params)
            except Exception as e:
                print(f"[DB] cross-service purge of {table} failed: {e}", file=sys.stderr, flush=True)

        self._commit()

    # Every table that holds per-player data, wiped whole by
    # reset_all_players(). Spared on purpose: legacy_players, bot_ranks,
    # and all world data (rpg_places/passages/world_npcs/world_objects,
    # quest_board rows, pokemon_cache, zone_discovery).
    _PLAYER_TABLES = (
        "players", "registrations", "player_meta",
        "npc_familiarity", "npc_events",
        "ariel_affection", "ariel_directives",
        "zone_spawns",
        "niflheim_players", "niflheim_journeys", "niflheim_fights",
        "niflheim_duels", "niflheim_tickets",
        "users", "warnings",           # Node-side site accounts + moderation
    )

    def reset_all_players(self):
        """Wipe every player, in every world (Pokemon, RPG, Niflheim, site
        accounts). Returns {table: rows_deleted}. Each table is wiped in
        its own try/rollback so one missing/odd table can't abort the rest.
        Also releases any claimed quests on the board."""
        counts = {}
        for table in self._PLAYER_TABLES:
            try:
                if not self._table_exists(table):
                    continue
                n = self._fetchone(self._ex(f"SELECT COUNT(*) FROM {table}"))[0]
                self._ex(f"DELETE FROM {table}")
                self._commit()
                counts[table] = n
            except Exception as e:
                self._rollback()
                print(f"[DB] reset_all_players: {table} failed: {e}", file=sys.stderr, flush=True)
                counts[table] = "error"
        try:
            self._ex("UPDATE quest_board SET claimed_by = NULL, claimed_at = NULL")
            self._commit()
        except Exception:
            self._rollback()
        return counts

    def _table_exists(self, name):
        if self._mode == "pg":
            row = self._fetchone(self._ex(
                "SELECT 1 FROM information_schema.tables WHERE table_name = ?",
                (name,),
            ))
        else:
            row = self._fetchone(self._ex(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?",
                (name,),
            ))
        return row is not None

    def all_senders(self):
        rows = self._fetchall(self._ex("SELECT sender FROM players"))
        return [r[0] for r in rows]

    # ── Registrations ─────────────────────────────────────────

    def save_reg(self, sender, reg_data):
        payload = json.dumps(reg_data)
        if self._mode == "pg":
            self._ex("""
                INSERT INTO registrations (sender, data) VALUES (?, ?)
                ON CONFLICT(sender) DO UPDATE SET data = EXCLUDED.data
            """, (sender, payload))
        else:
            self._ex("""
                INSERT INTO registrations (sender, data) VALUES (?, ?)
                ON CONFLICT(sender) DO UPDATE SET data = excluded.data
            """, (sender, payload))
        self._commit()

    def load_reg(self, sender):
        row = self._fetchone(self._ex(
            "SELECT data FROM registrations WHERE sender = ?", (sender,)
        ))
        return json.loads(row[0]) if row else None

    def delete_reg(self, sender):
        self._ex("DELETE FROM registrations WHERE sender = ?", (sender,))
        self._commit()

    # ── Player meta ───────────────────────────────────────────

    def set_meta(self, sender, key, value):
        if self._mode == "pg":
            self._ex("""
                INSERT INTO player_meta (sender, key, value) VALUES (?, ?, ?)
                ON CONFLICT(sender, key) DO UPDATE SET value = EXCLUDED.value
            """, (sender, key, str(value)))
        else:
            self._ex("""
                INSERT INTO player_meta (sender, key, value) VALUES (?, ?, ?)
                ON CONFLICT(sender, key) DO UPDATE SET value = excluded.value
            """, (sender, key, str(value)))
        self._commit()

    def get_meta(self, sender, key):
        row = self._fetchone(self._ex(
            "SELECT value FROM player_meta WHERE sender = ? AND key = ?",
            (sender, key)
        ))
        return row[0] if row else None

    def delete_meta(self, sender, key):
        self._ex(
            "DELETE FROM player_meta WHERE sender = ? AND key = ?",
            (sender, key)
        )
        self._commit()

    # ── Leaderboards ─────────────────────────────────────────────

    def all_players_data(self):
        """
        Bulk-load every player's raw dict in one query — for leaderboards
        and other full-roster scans. Avoids N+1 queries from calling
        load() per sender. Skips rows with corrupt/unparseable JSON.
        """
        rows = self._fetchall(self._ex("SELECT sender, data FROM players"))
        out = []
        for sender, data in rows:
            try:
                out.append((sender, json.loads(data)))
            except Exception:
                continue
        return out

    # ── Raw execute (router escape hatch) ─────────────────────

    def execute(self, sql, params=()):
        return self._ex(sql, params)

    def _init_core_tables(self):
        self._ex("""
            CREATE TABLE IF NOT EXISTS players (
                sender TEXT PRIMARY KEY,
                data   TEXT NOT NULL,
                jid    TEXT,
                lid    TEXT
            )
        """)
        # Migration: players table already existed before jid/lid were
        # added above (CREATE TABLE IF NOT EXISTS is a no-op on tables
        # that already exist), so add the columns explicitly if missing.
        for col in ("jid", "lid"):
            try:
                self._ex(f"ALTER TABLE players ADD COLUMN IF NOT EXISTS {col} TEXT")
                self._commit()
            except Exception as e:
                # older sqlite/testing paths may not support IF NOT EXISTS
                # here — but on Postgres a failed statement poisons the
                # whole transaction, so every CREATE TABLE after this one
                # would silently fail too unless we roll back right away.
                print(f"[DB] ALTER TABLE players ADD COLUMN {col} failed (non-fatal): {e}", flush=True, file=sys.stderr)
                self._rollback()
        # Pending registrations (name step before player is created)
        self._ex("""
            CREATE TABLE IF NOT EXISTS registrations (
                sender TEXT PRIMARY KEY,
                data   TEXT NOT NULL
            )
        """)
        # Per-player key-value meta (objective, flags, temp state)
        self._ex("""
            CREATE TABLE IF NOT EXISTS player_meta (
                sender TEXT NOT NULL,
                key    TEXT NOT NULL,
                value  TEXT NOT NULL,
                PRIMARY KEY (sender, key)
            )
        """)


    def _init_tables(self):
        """Create every table. Each group lives next to the code that uses it."""
        self._init_core_tables()
        self._init_pokemon_tables()
        self._init_rpg_tables()
        self._init_chat_tables()
        self._commit()

