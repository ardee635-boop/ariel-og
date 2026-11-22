
# ============================================================
# POKEAPI.PY  –  PokéAPI wrapper with local DB caching
# Endpoints used:
#   /pokemon/{id}          — stats, moves, sprites, abilities
#   /pokemon-species/{id}  — flavor text, evolution chain URL
#   /evolution-chain/{id}  — full evolution tree
#   /type/{id}             — type matchup data
# ============================================================

import json
import requests

BASE = "https://pokeapi.co/api/v2"
TIMEOUT = 10  # seconds

# ── In-memory cache (runtime) ─────────────────────────────────
# Prevents duplicate DB lookups in the same session
_mem: dict = {}


# ─────────────────────────────────────────────────────────────
# DB helpers — plugs into your existing Database class
# Call init_cache_table(db) once on startup
# ─────────────────────────────────────────────────────────────

def init_cache_table(db):
    """Add pokemon_cache table if it doesn't exist."""
    db._ex("""
        CREATE TABLE IF NOT EXISTS pokemon_cache (
            key   TEXT PRIMARY KEY,
            data  TEXT NOT NULL
        )
    """)
    db._commit()


def _db_get(db, key: str):
    if key in _mem:
        return _mem[key]
    row = db._fetchone(db._ex(
        "SELECT data FROM pokemon_cache WHERE key = ?", (key,)
    ))
    if row:
        val = json.loads(row[0])
        _mem[key] = val
        return val
    return None


def _db_set(db, key: str, value: dict):
    payload = json.dumps(value)
    if db._mode == "pg":
        db._ex("""
            INSERT INTO pokemon_cache (key, data) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET data = EXCLUDED.data
        """, (key, payload))
    else:
        db._ex("""
            INSERT INTO pokemon_cache (key, data) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET data = excluded.data
        """, (key, payload))
    db._commit()
    _mem[key] = value


# ─────────────────────────────────────────────────────────────
# Raw fetcher
# ─────────────────────────────────────────────────────────────

def _fetch(url: str) -> dict | None:
    try:
        r = requests.get(url, timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"[PokeAPI] fetch failed {url}: {e}")
        return None


def list_cached_species(db) -> list[str]:
    """
    Every species name the game has ever fetched full data for — i.e.
    every "pokemon:*" key in pokemon_cache. This is the live source of
    truth for what "exists in-world" (encounters, gym/arena teams, egg
    hatches, lab starters all route through get_full/get_pokemon), so
    it's the right basis for the Pokédex's Unseen list — not the full
    ~1000+ species PokéAPI knows about, just what this game actually uses.
    """
    rows = db._fetchall(db._ex(
        "SELECT key FROM pokemon_cache WHERE key LIKE 'pokemon:%'"
    ))
    return [row[0].split("pokemon:", 1)[1] for row in rows]


# ─────────────────────────────────────────────────────────────
# Core — get_pokemon(db, name_or_id)
# Returns a clean dict with everything the game needs
# ─────────────────────────────────────────────────────────────

def get_pokemon(db, name_or_id) -> dict | None:
    """
    Full Pokémon data — stats, moves, types, sprite, abilities.
    Cached in DB after first fetch.
    """
    key = f"pokemon:{str(name_or_id).lower()}"
    cached = _db_get(db, key)
    if cached:
        return cached

    raw = _fetch(f"{BASE}/pokemon/{name_or_id}")
    if not raw:
        return None

    # Pull base stats into a clean dict
    stats = {s["stat"]["name"]: s["base_stat"] for s in raw["stats"]}

    # First 4 moves (level-up moves, ordered by level)
    level_moves = sorted(
        [m for m in raw["moves"]
         if any(v["move_learn_method"]["name"] == "level-up"
                for v in m["version_group_details"])],
        key=lambda m: min(
            v["level_learned_at"]
            for v in m["version_group_details"]
            if v["move_learn_method"]["name"] == "level-up"
        )
    )
    default_moves = [m["move"]["name"] for m in level_moves[:4]]
    learnset = [
        [m["move"]["name"],
         min(v["level_learned_at"] for v in m["version_group_details"]
             if v["move_learn_method"]["name"] == "level-up")]
        for m in level_moves
    ]

    # Sprite — prefer official artwork, fall back to front_default
    sprites = raw.get("sprites", {})
    sprite  = (
        sprites.get("other", {}).get("official-artwork", {}).get("front_default") or
        sprites.get("front_default") or
        ""
    )

    data = {
        "id":         raw["id"],
        "name":       raw["name"],
        "types":      [t["type"]["name"] for t in raw["types"]],
        "base_stats": {
            "hp":              stats.get("hp", 45),
            "attack":          stats.get("attack", 45),
            "defense":         stats.get("defense", 45),
            "special-attack":  stats.get("special-attack", 45),
            "special-defense": stats.get("special-defense", 45),
            "speed":           stats.get("speed", 45),
        },
        "abilities":    [a["ability"]["name"] for a in raw["abilities"]],
        "default_moves": default_moves,
        "learnset":     learnset,      # [[move, level], ...] level-up moves, ascending
        "sprite":       sprite,
        "base_exp":     raw.get("base_experience", 50),
        "height":       raw.get("height", 0),   # decimetres
        "weight":       raw.get("weight", 0),   # hectograms
        "species_url":  raw["species"]["url"],
    }

    _db_set(db, key, data)
    return data


# ─────────────────────────────────────────────────────────────
# Species — flavor text + evolution chain URL
# ─────────────────────────────────────────────────────────────

def get_species(db, name_or_id) -> dict | None:
    """
    Species data — flavor text, catch rate, egg groups,
    evolution chain URL.
    """
    key = f"species:{str(name_or_id).lower()}"
    cached = _db_get(db, key)
    if cached:
        return cached

    raw = _fetch(f"{BASE}/pokemon-species/{name_or_id}")
    if not raw:
        return None

    # English flavor text — grab most recent entry
    flavor = ""
    for entry in reversed(raw.get("flavor_text_entries", [])):
        if entry["language"]["name"] == "en":
            flavor = entry["flavor_text"].replace("\n", " ").replace("\f", " ")
            break

    # English genus (species category, e.g. "Fire Mouse Pokémon")
    genus = ""
    for entry in raw.get("genera", []):
        if entry["language"]["name"] == "en":
            genus = entry["genus"]
            break

    data = {
        "id":               raw["id"],
        "name":             raw["name"],
        "flavor_text":      flavor,
        "genus":            genus,
        "catch_rate":       raw.get("capture_rate", 45),
        "base_happiness":   raw.get("base_happiness", 70),
        "growth_rate":      raw["growth_rate"]["name"],
        "egg_groups":       [e["name"] for e in raw.get("egg_groups", [])],
        "evolution_chain_url": raw["evolution_chain"]["url"],
        "is_legendary":     raw.get("is_legendary", False),
        "is_mythical":      raw.get("is_mythical", False),
        "generation":       raw["generation"]["name"],
    }

    _db_set(db, key, data)
    return data


# ─────────────────────────────────────────────────────────────
# Evolution chain
# ─────────────────────────────────────────────────────────────

def get_evolution_chain(db, chain_url: str) -> list | None:
    """
    Returns a flat list of evolution stages.
    Each stage: {"name": str, "min_level": int|None, "trigger": str}

    Example for Charmander:
    [
      {"name": "charmander", "min_level": None,  "trigger": "base"},
      {"name": "charmeleon", "min_level": 16,    "trigger": "level-up"},
      {"name": "charizard",  "min_level": 36,    "trigger": "level-up"},
    ]
    """
    key = f"evo:{chain_url}"
    cached = _db_get(db, key)
    if cached:
        return cached

    raw = _fetch(chain_url)
    if not raw:
        return None

    chain = []

    def _walk(node, is_base=False):
        name    = node["species"]["name"]
        details = node.get("evolution_details", [{}])
        d       = details[0] if details else {}
        chain.append({
            "name":      name,
            "min_level": d.get("min_level"),
            "trigger":   "base" if is_base else d.get("trigger", {}).get("name", "level-up"),
            "item":      d.get("item", {}).get("name") if d.get("item") else None,
        })
        for child in node.get("evolves_to", []):
            _walk(child)

    _walk(raw["chain"], is_base=True)
    _db_set(db, key, chain)
    return chain


# ─────────────────────────────────────────────────────────────
# Type matchups
# ─────────────────────────────────────────────────────────────

def get_type(db, type_name: str) -> dict | None:
    """
    Returns damage relations for a type.
    {
      "double_damage_to":   [...],
      "half_damage_to":     [...],
      "no_damage_to":       [...],
      "double_damage_from": [...],
      "half_damage_from":   [...],
      "no_damage_from":     [...],
    }
    """
    key = f"type:{type_name.lower()}"
    cached = _db_get(db, key)
    if cached:
        return cached

    raw = _fetch(f"{BASE}/type/{type_name}")
    if not raw:
        return None

    dr = raw["damage_relations"]
    data = {k: [t["name"] for t in v] for k, v in dr.items()}

    _db_set(db, key, data)
    return data


def get_gen1_species_by_type(db, type_name: str) -> list[str]:
    """
    Returns every Gen 1 (National Dex #1-151) species name of the given
    type, e.g. get_gen1_species_by_type(db, "grass") -> ["bulbasaur",
    "ivysaur", "venusaur", "oddish", ...].

    Used by egg.py for the Random Floro Egg reward, which is meant to
    hatch a random Nature(Grass)-type Pokémon from the Gen 1 Pokédex —
    not restricted to a curated pool like the other named eggs.

    PokéAPI's /type/{name} endpoint returns every species of that type
    across all generations with a pokemon-species URL each of which
    ends in /{national_dex_number}/. We filter on that number rather
    than fetching each species individually, to keep this a single
    cached call.
    """
    key = f"type-gen1:{type_name.lower()}"
    cached = _db_get(db, key)
    if cached:
        return cached.get("species", [])

    raw = _fetch(f"{BASE}/type/{type_name}")
    if not raw:
        return []

    species = []
    for entry in raw.get("pokemon", []):
        poke = entry.get("pokemon", {})
        name = poke.get("name", "")
        url  = poke.get("url", "")
        # url looks like .../pokemon/25/ — dex number is the last path segment
        try:
            dex_num = int(url.rstrip("/").rsplit("/", 1)[-1])
        except (ValueError, IndexError):
            continue
        # Skip alternate forms (megas, regional forms, etc.) which use
        # dex numbers > 151 or hyphenated names outside Gen 1's range.
        if 1 <= dex_num <= 151:
            species.append(name)

    _db_set(db, key, {"species": species})
    return species


def type_multiplier(db, move_type: str, defender_types: list[str]) -> float:
    """
    Calculate damage multiplier for move_type vs a defender
    with one or two types.
    Returns 0.0, 0.25, 0.5, 1.0, 2.0, or 4.0
    """
    type_data = get_type(db, move_type)
    if not type_data:
        return 1.0

    mult = 1.0
    for def_type in defender_types:
        if def_type in type_data.get("double_damage_to", []):
            mult *= 2.0
        elif def_type in type_data.get("half_damage_to", []):
            mult *= 0.5
        elif def_type in type_data.get("no_damage_to", []):
            mult *= 0.0
    return mult


# ─────────────────────────────────────────────────────────────
# Move data
# ─────────────────────────────────────────────────────────────

def get_move(db, move_name: str) -> dict | None:
    """
    Returns clean move data.
    {
      "name", "type", "category" (physical/special/status),
      "power", "accuracy", "pp", "priority",
      "effect_chance", "effect"
    }
    """
    key = f"move:{move_name.lower()}"
    cached = _db_get(db, key)
    if cached:
        return cached

    raw = _fetch(f"{BASE}/move/{move_name}")
    if not raw:
        return None

    # English effect text
    effect = ""
    for entry in raw.get("effect_entries", []):
        if entry["language"]["name"] == "en":
            effect = entry["short_effect"]
            break

    # English flavor text (what the .move detail screen shows)
    description = ""
    for entry in reversed(raw.get("flavor_text_entries", [])):
        if entry["language"]["name"] == "en":
            description = " ".join(entry["flavor_text"].split())
            break

    data = {
        "name":          raw["name"],
        "description":   description,
        "type":          raw["type"]["name"],
        "category":      raw["damage_class"]["name"],   # physical/special/status
        "power":         raw.get("power") or 0,
        "accuracy":      raw.get("accuracy") or 100,
        "pp":            raw.get("pp", 10),
        "priority":      raw.get("priority", 0),
        "effect_chance": raw.get("effect_chance"),
        "effect":        effect,
        "stat_changes":  [
            {"stat": sc["stat"]["name"], "change": sc["change"]}
            for sc in raw.get("stat_changes", [])
        ],
    }

    _db_set(db, key, data)
    return data


# ─────────────────────────────────────────────────────────────
# Convenience — full pokemon bundle (pokemon + species)
# ─────────────────────────────────────────────────────────────

def get_full(db, name_or_id) -> dict | None:
    """
    Merges get_pokemon + get_species into one dict.
    This is what you pass around in game for a wild/owned Pokémon.
    """
    poke    = get_pokemon(db, name_or_id)
    if not poke:
        return None
    species = get_species(db, name_or_id)
    if species:
        poke.update({
            "flavor_text":    species["flavor_text"],
            "genus":          species.get("genus", ""),
            "catch_rate":     species["catch_rate"],
            "growth_rate":    species["growth_rate"],
            "evolution_chain_url": species["evolution_chain_url"],
            "is_legendary":   species["is_legendary"],
            "is_mythical":    species["is_mythical"],
            "generation":     species["generation"],
        })
    return poke


def prewarm_arena_pool(db) -> None:
    """
    Pre-cache all arena pool species on startup.
    Runs in a background daemon thread — never blocks the bot.
    Calls get_full() for each species; DB caching means subsequent
    calls during gameplay are instant reads.
    """
    import threading
    import sys
    from arena import ARENA_POOL

    def _warm():
        print("[POKEAPI] Arena pool pre-warm started...", file=sys.stderr, flush=True)
        ok = 0
        for species in ARENA_POOL:
            try:
                result = get_full(db, species)
                if result:
                    ok += 1
            except Exception as e:
                print(f"[POKEAPI] prewarm failed for {species}: {e}", file=sys.stderr, flush=True)
        print(f"[POKEAPI] Arena pool pre-warm done — {ok}/{len(ARENA_POOL)} cached.", file=sys.stderr, flush=True)

    t = threading.Thread(target=_warm, daemon=True, name="arena-prewarm")
    t.start()


# Soulbound conversion (pokemon_to_soulbound) moved to soulbound.py —
# see that file for all 3 series converters (Pokémon/Isekai/Digimon).

