"""Ariel chat tables: affection/closeness, group names, directives."""
import sys


class ChatDb:

    # ── Group known-names cache (for Ariel's group name recognition) ──

    def record_group_name(self, group_jid: str, sender: str, push_name: str) -> None:
        """
        Upsert this sender's current WhatsApp display name for this
        group. Called on every group message (see router/handle.py) so
        the cache stays current as people talk or rename themselves.
        No-ops silently if group_jid or push_name is missing — DMs and
        senders with no push_name (rare, but seen in logs) just don't
        get cached, which is fine since there's nothing useful to store.
        """
        if not group_jid or not push_name:
            return
        import datetime
        now = datetime.datetime.utcnow().isoformat()
        if self._mode == "pg":
            self._ex("""
                INSERT INTO group_known_names (group_jid, sender, push_name, last_seen)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(group_jid, sender) DO UPDATE
                    SET push_name = EXCLUDED.push_name, last_seen = EXCLUDED.last_seen
            """, (group_jid, sender, push_name, now))
        else:
            self._ex("""
                INSERT INTO group_known_names (group_jid, sender, push_name, last_seen)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(group_jid, sender) DO UPDATE
                    SET push_name = excluded.push_name, last_seen = excluded.last_seen
            """, (group_jid, sender, push_name, now))
        self._commit()

    def get_group_names(self, group_jid: str) -> list[dict]:
        """
        Returns everyone Ariel has seen talk in this group, as a list
        of {"sender": jid, "push_name": str}. Used to let her connect
        a name mentioned in conversation to an actual known member,
        without needing that member to be the one currently texting.
        """
        if not group_jid:
            return []
        rows = self._fetchall(self._ex(
            "SELECT sender, push_name FROM group_known_names WHERE group_jid = ?",
            (group_jid,)
        ))
        return [{"sender": r[0], "push_name": r[1]} for r in rows]

    # ── Ariel affection ────────────────────────────────────────

    def affection_get(self, sender):
        row = self._fetchone(self._ex(
            "SELECT score, last_talk, talk_count_today FROM ariel_affection WHERE sender = ?",
            (sender,)
        ))
        if not row:
            return {"score": 0, "last_talk": None, "talk_count_today": 0}
        return {"score": row[0], "last_talk": row[1], "talk_count_today": row[2]}

    def affection_add(self, sender, points=1, daily_cap=5):
        import datetime
        today = datetime.date.today().isoformat()
        row = self._fetchone(self._ex(
            "SELECT score, last_talk, talk_count_today FROM ariel_affection WHERE sender = ?",
            (sender,)
        ))
        if not row:
            if self._mode == "pg":
                self._ex("""
                    INSERT INTO ariel_affection (sender, score, last_talk, talk_count_today)
                    VALUES (?, ?, ?, 1)
                    ON CONFLICT(sender) DO NOTHING
                """, (sender, min(points, daily_cap), today))
            else:
                self._ex("""
                    INSERT OR IGNORE INTO ariel_affection (sender, score, last_talk, talk_count_today)
                    VALUES (?, ?, ?, 1)
                """, (sender, min(points, daily_cap), today))
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
            UPDATE ariel_affection SET score = ?, last_talk = ?, talk_count_today = ?
            WHERE sender = ?
        """, (new_score, today, talk_today, sender))
        self._commit()

    # ── Ariel closeness tier (separate from the /100 score above) ──
    # Lifetime message count, never capped, never reset. This is what
    # actually drives how warm/guarded Ariel's system prompt makes her —
    # KING_NUMBER is handled separately in ariel.py (pinned tier, not
    # stored here) since he shouldn't need to "earn" his way to closeness.

    _CLOSENESS_TIERS = [
        (100, "Ship Fam"),
        (61,  "Ride or Die"),
        (31,  "Vibes"),
        (16,  "Kinda Know You"),
        (0,   "Rando"),
    ]

    def closeness_bump(self, sender):
        """Increments the lifetime talk count for this sender by 1.
        Call once per real ariel_chat() turn. Creates the row if it
        doesn't exist yet."""
        row = self._fetchone(self._ex(
            "SELECT talk_count_total FROM ariel_affection WHERE sender = ?", (sender,)
        ))
        if not row:
            if self._mode == "pg":
                self._ex("""
                    INSERT INTO ariel_affection (sender, talk_count_total)
                    VALUES (?, 1)
                    ON CONFLICT(sender) DO UPDATE SET talk_count_total = ariel_affection.talk_count_total + 1
                """, (sender,))
            else:
                self._ex("""
                    INSERT OR IGNORE INTO ariel_affection (sender, talk_count_total) VALUES (?, 1)
                """, (sender,))
                self._ex(
                    "UPDATE ariel_affection SET talk_count_total = talk_count_total + 1 WHERE sender = ? AND talk_count_total = 0",
                    (sender,)
                )
        else:
            self._ex(
                "UPDATE ariel_affection SET talk_count_total = talk_count_total + 1 WHERE sender = ?",
                (sender,)
            )
        self._commit()

    def closeness_tier(self, sender) -> tuple[str, int]:
        """Returns (tier_name, lifetime_talk_count) for this sender.
        Does not account for KING_NUMBER's pinned override — callers
        that need that check it separately."""
        row = self._fetchone(self._ex(
            "SELECT talk_count_total FROM ariel_affection WHERE sender = ?", (sender,)
        ))
        count = row[0] if row else 0
        for threshold, name in self._CLOSENESS_TIERS:
            if count >= threshold:
                return name, count
        return "Rando", count

    def affection_tier(self, sender):
        f = self.affection_get(sender)
        s = f["score"]
        if s >= 80:   tier = "Devoted"
        elif s >= 60: tier = "Close"
        elif s >= 40: tier = "Warm"
        elif s >= 20: tier = "Friendly"
        else:         tier = "Reserved"
        return tier, s

    # ── Realm ranks (read-only view of the .ranks table) ───────

    _RANK_ORDER = ["king", "queen", "prince", "princess", "duke", "duchess",
                   "lord", "jester", "baron"]

    def rank_for(self, sender, group_jid=None):
        """Highest rank this sender holds in bot_ranks (global rows, plus
        baron rows for this group), or None. The table is created and
        written by the Node side (.crown/.ranks); this only reads it."""
        phone = (sender or "").split("@")[0]
        rows = self._fetchall(self._ex(
            "SELECT rank FROM bot_ranks "
            "WHERE (jid = ? OR phone = ? OR lid = ?) "
            "AND (group_jid IS NULL OR group_jid = ?)",
            (sender, phone, sender, group_jid or "")
        ))
        ranks = [str(r[0]).lower() for r in (rows or [])]
        if not ranks:
            return None
        def _pos(r):
            return self._RANK_ORDER.index(r) if r in self._RANK_ORDER else len(self._RANK_ORDER)
        return sorted(ranks, key=_pos)[0]

    # ── Ariel directives ───────────────────────────────────────

    def directive_count_active(self, owner):
        row = self._fetchone(self._ex(
            "SELECT COUNT(*) FROM ariel_directives WHERE owner = ? AND active = 1",
            (owner,)
        ))
        return row[0] if row else 0

    def directive_create(self, owner, condition, action, target_jid=None,
                          target_name=None, group_jid=None, trigger_type="reactive",
                          cap=5):
        """Returns the new directive's id, or None if the owner is at cap."""
        import datetime
        if self.directive_count_active(owner) >= cap:
            return None
        now = datetime.datetime.utcnow().isoformat()
        cur = self._ex("""
            INSERT INTO ariel_directives
                (owner, target_jid, target_name, condition, action, trigger_type, group_jid, active, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)
        """, (owner, target_jid, target_name, condition, action, trigger_type, group_jid, now))
        self._commit()
        if self._mode == "pg":
            row = self._fetchone(self._ex(
                "SELECT id FROM ariel_directives WHERE owner = ? ORDER BY id DESC LIMIT 1",
                (owner,)
            ))
            return row[0] if row else None
        return cur.lastrowid

    def directives_targeting(self, sender_jid, group_jid=None):
        """Active reactive directives where sender_jid is the watched target."""
        rows = self._fetchall(self._ex("""
            SELECT id, owner, target_jid, target_name, condition, action, group_jid, last_fired
            FROM ariel_directives
            WHERE active = 1 AND trigger_type = 'reactive' AND target_jid = ?
        """, (sender_jid,)))
        out = []
        for r in rows:
            if group_jid and r[6] and r[6] != group_jid:
                continue
            out.append({
                "id": r[0], "owner": r[1], "target_jid": r[2], "target_name": r[3],
                "condition": r[4], "action": r[5], "group_jid": r[6], "last_fired": r[7],
            })
        return out

    def directives_list_owner(self, owner):
        rows = self._fetchall(self._ex("""
            SELECT id, target_name, condition, action, trigger_type, active
            FROM ariel_directives WHERE owner = ? ORDER BY id DESC
        """, (owner,)))
        return [{
            "id": r[0], "target_name": r[1], "condition": r[2],
            "action": r[3], "trigger_type": r[4], "active": bool(r[5]),
        } for r in rows]

    def directive_touch_fired(self, directive_id):
        import datetime
        self._ex("UPDATE ariel_directives SET last_fired = ? WHERE id = ?",
                  (datetime.datetime.utcnow().isoformat(), directive_id))
        self._commit()

    def directive_deactivate(self, directive_id, owner=None):
        if owner:
            self._ex("UPDATE ariel_directives SET active = 0 WHERE id = ? AND owner = ?",
                      (directive_id, owner))
        else:
            self._ex("UPDATE ariel_directives SET active = 0 WHERE id = ?", (directive_id,))
        self._commit()

    def _init_chat_tables(self):
        # Ariel affection per player (same flat-cap pattern as npc_familiarity)
        # talk_count_total is separate from score: it's a lifetime message
        # count, never capped and never reset by anything (not even
        # .resetstickers or the unrelated group .active/.inactive activity
        # tracker) — it's what her tier (Rando / Kinda Know You / Vibes /
        # Ride or Die / Ship Fam) is actually based on, since "score" is
        # daily-capped and meant for something else (.me's /100 display).
        self._ex("""
            CREATE TABLE IF NOT EXISTS ariel_affection (
                sender           TEXT PRIMARY KEY,
                score            INTEGER NOT NULL DEFAULT 0,
                last_talk        TEXT DEFAULT NULL,
                talk_count_today INTEGER NOT NULL DEFAULT 0,
                talk_count_total INTEGER NOT NULL DEFAULT 0
            )
        """)
        if self._mode == "pg":
            self._ex("ALTER TABLE ariel_affection ADD COLUMN IF NOT EXISTS talk_count_total INTEGER NOT NULL DEFAULT 0")
        else:
            try:
                self._ex("ALTER TABLE ariel_affection ADD COLUMN talk_count_total INTEGER NOT NULL DEFAULT 0")
            except Exception:
                pass  # column already exists
        # Passive per-group name cache: as people talk in a group, we
        # record their WhatsApp display name (pushName) against their
        # JID. This lets Ariel connect a name mentioned in conversation
        # ("have you heard from rose") to an actual known group member
        # even if that member isn't the one currently talking to her —
        # NOT a contacts-book lookup (WhatsApp doesn't expose a user's
        # personal contact names to the bot), just "who has spoken here
        # and what name did they show up as." Overwritten on every
        # message so it stays current if someone changes their display
        # name.
        self._ex("""
            CREATE TABLE IF NOT EXISTS group_known_names (
                group_jid    TEXT NOT NULL,
                sender       TEXT NOT NULL,
                push_name    TEXT NOT NULL,
                last_seen    TEXT DEFAULT NULL,
                PRIMARY KEY (group_jid, sender)
            )
        """)
        # Ariel standing directives ("if Kingston does X, say Y in the gc")
        self._ex("""
            CREATE TABLE IF NOT EXISTS ariel_directives (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                owner        TEXT NOT NULL,
                target_jid   TEXT DEFAULT NULL,
                target_name  TEXT DEFAULT NULL,
                condition    TEXT NOT NULL,
                action       TEXT NOT NULL,
                trigger_type TEXT NOT NULL DEFAULT 'reactive',
                group_jid    TEXT DEFAULT NULL,
                active       INTEGER NOT NULL DEFAULT 1,
                created_at   TEXT DEFAULT NULL,
                last_fired   TEXT DEFAULT NULL
            )
        """)
        # directives_targeting() runs this table's target_jid lookup on
        # EVERY incoming message (see router/handle.py:handle(), near the
        # top, before any command routing) — without an index this is a
        # full table scan every time, getting slower as directives pile
        # up. Index makes it a fast lookup regardless of table size.
        try:
            self._ex("CREATE INDEX IF NOT EXISTS idx_ariel_directives_target ON ariel_directives (target_jid)")
            self._commit()
        except Exception as e:
            print(f"[DB] CREATE INDEX idx_ariel_directives_target failed (non-fatal): {e}", flush=True, file=sys.stderr)
            self._rollback()

