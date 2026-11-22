"""Ariel: soulbound rpg (split from soulbound.py)."""
import json
import os
import requests


# In-memory cache of successful Open5e fetches, keyed by the
# lowercased name/key that was requested. Lives for the life of the
# process — cheap and covers the common case (repeat .rpg sim calls
# hitting the same RANDOM_MONSTER_POOL names) without needing any
# persistence story. Cleared on every restart/redeploy, which is
# fine since it's just an optimization, not a source of truth.
_MONSTER_CACHE: dict[str, dict] = {}

# Static fallback for the fixed RANDOM_MONSTER_POOL names — bundled
# with the code so a fresh deploy (empty _MONSTER_CACHE) still works
# instantly for the 10 pool monsters even if Open5e is down/slow,
# instead of depending on a live fetch succeeding at least once
# first. Generated once via fetch_isekai_monster() + json.dump and
# checked in; not meant to be hand-edited. Absent/missing file is
# handled gracefully (just means no offline fallback yet).
_FALLBACK_PATH = os.path.join(__import__("paths").ROOT, "monster_fallback_cache.json")

_FALLBACK_CACHE: dict[str, dict] = {}

try:
    with open(_FALLBACK_PATH, "r", encoding="utf-8") as _f:
        _FALLBACK_CACHE = json.load(_f)
except (FileNotFoundError, json.JSONDecodeError):
    pass

def fetch_isekai_monster(name_or_key: str) -> dict | None:
    """
    Fetches one monster from Open5e's v2 API by exact key (e.g.
    "srd-2024_goblin-boss") or falls back to a name search if the
    key doesn't hit. v2 has no direct /creatures/{key}/ single-item
    lookup by name the way v1 did by slug — this does an exact
    name match via name= first, then returns the first hit.

    NOTE: v1 is deprecated (still runs, in maintenance-only mode).
    This targets v2 (/v2/creatures/), which is the current,
    actively maintained version.

    NOTE 2026-09-04: confirmed via server logs the real failure was
    requests.exceptions.ReadTimeout at 10s, not a bad filter param
    (name__iexact -> name= was a red herring — harmless but not the
    fix). Bumped timeout to 20s and added one retry on timeout,
    since Open5e/the host connection is intermittently slow rather
    than actually erroring. Debug prints kept for now to confirm
    this resolves it; strip once confirmed clean for a while.

    NOTE 2026-09-04 (2): added a cache in front of the network call
    — in-memory first (covers repeat lookups within one running
    process), then a bundled JSON fallback (covers a cold process
    for the known RANDOM_MONSTER_POOL names) — since retries alone
    don't help when Open5e itself is slow/down for a stretch. Only
    successful fetches get cached; a miss/timeout is never cached,
    so a bad lookup doesn't get "stuck" and later successes still
    populate the cache.
    """
    key = name_or_key.strip().lower()
    if key in _MONSTER_CACHE:
        return _MONSTER_CACHE[key]

    for attempt in range(2):
        try:
            resp = requests.get(
                "https://api.open5e.com/v2/creatures/",
                params={"name": name_or_key, "limit": 1},
                timeout=20,
                headers={"User-Agent": "Mozilla/5.0 (compatible; NiflheimBot/1.0)"},
            )
            print(f"[OPEN5E_DEBUG] fetch name={name_or_key!r} status={resp.status_code} "
                  f"body={resp.text[:300]!r}")
            if resp.status_code != 200:
                return _FALLBACK_CACHE.get(key)
            results = resp.json().get("results", [])
            if results:
                _MONSTER_CACHE[key] = results[0]
                return results[0]
            # fall back to partial match
            results = search_isekai_monsters(name_or_key, limit=1)
            if results:
                _MONSTER_CACHE[key] = results[0]
                return results[0]
            return _FALLBACK_CACHE.get(key)
        except requests.exceptions.ReadTimeout as e:
            print(f"[OPEN5E_DEBUG] fetch name={name_or_key!r} TIMEOUT attempt={attempt}: {e!r}")
            if attempt == 0:
                continue  # one retry — often a cold connection, not a dead API
            return _FALLBACK_CACHE.get(key)
        except Exception as e:
            print(f"[OPEN5E_DEBUG] fetch name={name_or_key!r} EXCEPTION: {e!r}")
            return _FALLBACK_CACHE.get(key)

def search_isekai_monsters(query: str, limit: int = 5) -> list[dict]:
    """
    Search Open5e v2 by name substring (name__icontains — v2 has
    no generic ?search= param the way v1 did).
    """
    try:
        resp = requests.get(
            "https://api.open5e.com/v2/creatures/",
            params={"name__icontains": query, "limit": limit},
            timeout=20,
            headers={"User-Agent": "Mozilla/5.0 (compatible; NiflheimBot/1.0)"},
        )
        print(f"[OPEN5E_DEBUG] search query={query!r} status={resp.status_code} "
              f"body={resp.text[:300]!r}")
        if resp.status_code != 200:
            return []
        return resp.json().get("results", [])
    except Exception as e:
        print(f"[OPEN5E_DEBUG] search query={query!r} EXCEPTION: {e!r}")
        return []

def _grade_from_dnd_score(value: float) -> str:
    """
    Grade thresholds for raw D&D 5e ability scores (Open5e's
    strength/dexterity/etc fields, typically 1-30). NOT the same
    scale as Pokémon base stats — separate from _grade_from_stat.
    Breakpoints roughly track 5e's modifier tiers; not confirmed
    against the design doc (doc doesn't specify Isekai thresholds),
    flagged as an assumption.
        18+    -> S
        15-17  -> A
        12-14  -> B
        9-11   -> C
        below 9 -> D
    """
    if value >= 18:
        return "S"
    if value >= 15:
        return "A"
    if value >= 12:
        return "B"
    if value >= 9:
        return "C"
    return "D"

def isekai_to_soulbound(monster_data: dict) -> dict:
    """
    Converts an Open5e v2 /v2/creatures/ result dict into the
    universal Soulbound schema.

    CONFIRMED v2 shape (real sample, goblin family, 2026-08-01) —
    different from v1 in real ways, not just a rename:
        ability_scores: {strength, dexterity, constitution,
                          intelligence, wisdom, charisma}  -- NESTED
                          object now, not flat top-level fields
        modifiers: {...same 6 keys...}  -- already-computed D&D
                    modifiers, available if ever needed later
        speed: {walk, unit}       -- primary speed only
        speed_all: {walk, crawl, hover, fly, burrow, climb, swim}
                    -- full movement picture, richer than v1's
                       speed dict
        challenge_rating: same name/shape as v1
        actions: [{name, desc, action_type,
                   attacks: [{attack_type, to_hit_mod,
                              damage_die_count, damage_die_type,
                              damage_bonus, damage_type, reach,
                              range, ...}]}]
                    -- attacks is now its OWN nested array per
                       action. An action with attacks: [] (e.g.
                       "Nimble Escape") is a pure utility/ability
                       action with no numeric combat data; an
                       action with attacks populated is a real
                       weapon/spell attack. This is a cleaner
                       signal than v1's inconsistent attack_bonus/
                       damage_dice presence.
        traits: [{name, desc}]  -- separate list from actions now
        illustration: field exists in the schema (was null on
                       every entry seen so far — v1 had no image
                       field at all; v2 at least has the slot,
                       just unpopulated for these sources)

    Mapping (direct — ability_scores' 6 values map 1:1 onto 6 of
    the 7 Soulbound stats):
        STR ← ability_scores.strength
        DEX ← ability_scores.dexterity
        DEF ← ability_scores.constitution
        INT ← ability_scores.intelligence
        WIS ← ability_scores.wisdom
        CHA ← ability_scores.charisma
        SPD ← speed_all.walk, falling back to the highest of any
              other movement type (fly/swim/burrow/climb/crawl)
              for creatures with no walk speed (e.g. pure flyers)

    Level: placeholder = round(challenge_rating), minimum 1. Not
    a designed formula — checklist's "level-1 point-budget" logic
    is still a separate, undesigned Phase 1 task.

    Skills: monster_data["actions"] entries are already full objects
    in the source (no extra fetch needed, unlike Pokémon's move-name
    list) — each is converted via
    skills.isekai_action_to_skill(). monster_data["traits"] (separate
    top-level list, name+desc only, no attack data) maps to the
    Soulbound's traits[] as plain {name, description} dicts — not
    run through the skill converter, since traits have no
    damage/accuracy/etc to convert.
    """
    scores = monster_data.get("ability_scores", {}) or {}
    str_ = scores.get("strength", 10)
    dex  = scores.get("dexterity", 10)
    con  = scores.get("constitution", 10)
    int_ = scores.get("intelligence", 10)
    wis  = scores.get("wisdom", 10)
    cha  = scores.get("charisma", 10)

    speed_all = monster_data.get("speed_all", {}) or {}
    spd = speed_all.get("walk", 0) or 0
    if not spd:
        other_speeds = [
            v for k, v in speed_all.items()
            if k != "walk" and isinstance(v, (int, float)) and v
        ]
        spd = max(other_speeds) if other_speeds else 30  # 30ft default walk

    stats = {
        "STR": str_,
        "INT": int_,
        "DEF": con,
        "SPD": spd,
        "DEX": dex,
        "WIS": wis,
        "CHA": cha,
    }
    grades = {stat: _grade_from_dnd_score(val) for stat, val in stats.items()}

    cr = monster_data.get("challenge_rating", 1) or 1
    level = max(1, round(cr))

    from skills_rpg import isekai_action_to_skill
    skills_list = [
        isekai_action_to_skill(action)
        for action in monster_data.get("actions", [])
    ]
    traits_list = [
        {"name": t.get("name", "unknown"), "description": t.get("desc", "")}
        for t in monster_data.get("traits", [])
    ]

    return {
        "name":   monster_data.get("name", "unknown"),
        "series": "isekai",
        "level":  level,
        "stats":  stats,
        "grades": grades,
        "skills": skills_list,
        "traits": traits_list,
    }
