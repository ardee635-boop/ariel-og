# Niflheim storage — own tables, prefixed niflheim_. Does not touch the Pokémon player record
# or the shared ExploreSession table. Uses the shared Database connection helpers (_ex/_commit)
# so it works on both Supabase/PostgreSQL and the SQLite fallback.
import json

_tables_ready = False


def ensure_tables(db):
    """One-time, idempotent table creation (CREATE TABLE IF NOT EXISTS). Safe to call repeatedly."""
    global _tables_ready
    if _tables_ready:
        return
    db._ex("""
        CREATE TABLE IF NOT EXISTS niflheim_players (
            sender TEXT PRIMARY KEY,
            data   TEXT NOT NULL
        )
    """)
    db._ex("""
        CREATE TABLE IF NOT EXISTS niflheim_journeys (
            sender TEXT PRIMARY KEY,
            data   TEXT NOT NULL
        )
    """)
    db._commit()
    _tables_ready = True


def load_player(db, sender):
    ensure_tables(db)
    row = db._fetchone(db._ex("SELECT data FROM niflheim_players WHERE sender = ?", (sender,)))
    return json.loads(row[0]) if row else None


def save_player(db, sender, player):
    ensure_tables(db)
    payload = json.dumps(player)
    if getattr(db, "_mode", "sqlite") == "pg":
        db._ex("""
            INSERT INTO niflheim_players (sender, data) VALUES (?, ?)
            ON CONFLICT (sender) DO UPDATE SET data = EXCLUDED.data
        """, (sender, payload))
    else:
        db._ex("""
            INSERT INTO niflheim_players (sender, data) VALUES (?, ?)
            ON CONFLICT(sender) DO UPDATE SET data = excluded.data
        """, (sender, payload))
    db._commit()


# ── Journeys (one active journey per player; own table, not the shared ExploreSession) ──

def load_journey(db, sender):
    ensure_tables(db)
    row = db._fetchone(db._ex("SELECT data FROM niflheim_journeys WHERE sender = ?", (sender,)))
    return json.loads(row[0]) if row else None


def save_journey(db, sender, journey):
    ensure_tables(db)
    payload = json.dumps(journey)
    if getattr(db, "_mode", "sqlite") == "pg":
        db._ex("""
            INSERT INTO niflheim_journeys (sender, data) VALUES (?, ?)
            ON CONFLICT (sender) DO UPDATE SET data = EXCLUDED.data
        """, (sender, payload))
    else:
        db._ex("""
            INSERT INTO niflheim_journeys (sender, data) VALUES (?, ?)
            ON CONFLICT(sender) DO UPDATE SET data = excluded.data
        """, (sender, payload))
    db._commit()


def delete_journey(db, sender):
    ensure_tables(db)
    db._ex("DELETE FROM niflheim_journeys WHERE sender = ?", (sender,))
    db._commit()


# ── Fights (Package 1.4; one active fight per player; own table) ──

def _ensure_fights(db):
    if getattr(db, "_nif_fights_ready", False):
        return
    ensure_tables(db)
    db._ex("""
        CREATE TABLE IF NOT EXISTS niflheim_fights (
            sender TEXT PRIMARY KEY,
            data   TEXT NOT NULL
        )
    """)
    db._commit()
    try:
        db._nif_fights_ready = True
    except Exception:
        pass


def load_fight(db, sender):
    _ensure_fights(db)
    row = db._fetchone(db._ex("SELECT data FROM niflheim_fights WHERE sender = ?", (sender,)))
    return json.loads(row[0]) if row else None


def save_fight(db, sender, fight):
    _ensure_fights(db)
    payload = json.dumps(fight)
    if getattr(db, "_mode", "sqlite") == "pg":
        db._ex("""
            INSERT INTO niflheim_fights (sender, data) VALUES (?, ?)
            ON CONFLICT (sender) DO UPDATE SET data = EXCLUDED.data
        """, (sender, payload))
    else:
        db._ex("""
            INSERT INTO niflheim_fights (sender, data) VALUES (?, ?)
            ON CONFLICT(sender) DO UPDATE SET data = excluded.data
        """, (sender, payload))
    db._commit()


def delete_fight(db, sender):
    _ensure_fights(db)
    db._ex("DELETE FROM niflheim_fights WHERE sender = ?", (sender,))
    db._commit()


# ── Duels (Package 1.6; own table). Row "d:<id>" = the duel; row "p:<sender>" = that player's duel id. ──

def _ensure_duels(db):
    if getattr(db, "_nif_duels_ready", False):
        return
    ensure_tables(db)
    db._ex("""
        CREATE TABLE IF NOT EXISTS niflheim_duels (
            key  TEXT PRIMARY KEY,
            data TEXT NOT NULL
        )
    """)
    db._commit()
    try:
        db._nif_duels_ready = True
    except Exception:
        pass


def _duel_put(db, key, payload):
    if getattr(db, "_mode", "sqlite") == "pg":
        db._ex("""
            INSERT INTO niflheim_duels (key, data) VALUES (?, ?)
            ON CONFLICT (key) DO UPDATE SET data = EXCLUDED.data
        """, (key, payload))
    else:
        db._ex("""
            INSERT INTO niflheim_duels (key, data) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET data = excluded.data
        """, (key, payload))


def save_duel(db, duel):
    """Save the duel and (re)point both players at it."""
    _ensure_duels(db)
    _duel_put(db, "d:" + duel["id"], json.dumps(duel))
    for s in (duel["a"], duel["b"]):
        _duel_put(db, "p:" + s, json.dumps(duel["id"]))
    db._commit()


def load_duel_by_id(db, duel_id):
    _ensure_duels(db)
    row = db._fetchone(db._ex("SELECT data FROM niflheim_duels WHERE key = ?", ("d:" + duel_id,)))
    return json.loads(row[0]) if row else None


def load_duel(db, sender):
    """The duel (invite or active) this player is in, or None."""
    _ensure_duels(db)
    row = db._fetchone(db._ex("SELECT data FROM niflheim_duels WHERE key = ?", ("p:" + sender,)))
    if not row:
        return None
    d = load_duel_by_id(db, json.loads(row[0]))
    if d is None:                                   # stale index
        db._ex("DELETE FROM niflheim_duels WHERE key = ?", ("p:" + sender,))
        db._commit()
    return d


def delete_duel(db, duel):
    _ensure_duels(db)
    db._ex("DELETE FROM niflheim_duels WHERE key = ?", ("d:" + duel["id"],))
    for s in (duel["a"], duel["b"]):
        db._ex("DELETE FROM niflheim_duels WHERE key = ?", ("p:" + s,))
    db._commit()


# ── Arena tickets (Session 2): one open website battle per player ──
def _ensure_tickets(db):
    if getattr(db, "_nif_tickets_ready", False):
        return
    ensure_tables(db)
    db._ex("CREATE TABLE IF NOT EXISTS niflheim_tickets (id TEXT PRIMARY KEY, sender TEXT NOT NULL, data TEXT NOT NULL)")
    db._commit()
    try:
        db._nif_tickets_ready = True
    except Exception:
        pass


def save_ticket(db, ticket):
    """Store a ticket; any older ticket of the same player is replaced."""
    _ensure_tickets(db)
    db._ex("DELETE FROM niflheim_tickets WHERE sender = ?", (ticket["sender"],))
    db._ex("INSERT INTO niflheim_tickets (id, sender, data) VALUES (?, ?, ?)",
           (ticket["id"], ticket["sender"], json.dumps(ticket)))
    db._commit()


def load_ticket(db, ticket_id):
    _ensure_tickets(db)
    row = db._fetchone(db._ex("SELECT data FROM niflheim_tickets WHERE id = ?", (str(ticket_id),)))
    return json.loads(row[0]) if row else None


def delete_ticket(db, ticket_id):
    _ensure_tickets(db)
    db._ex("DELETE FROM niflheim_tickets WHERE id = ?", (str(ticket_id),))
    db._commit()
