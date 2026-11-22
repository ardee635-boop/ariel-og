# ============================================================
# rpg_map.py — location lookups backed by the hand-authored seed
#
# Replaces rpg_locations.py's helper functions (location_name,
# location_details, offered_trial, location_path, encounter_pool).
# The old file kept its own hardcoded copy of the map, which drifted
# from rpg_places_seed.py. This module has NO map data of its own:
# everything is read from rpg_places_seed.build_world_tree(), so
# the seed is the single anchor. .resetworld rebuilds the database
# from that same seed, so the two can never disagree.
#
# Lookup order for a place id:
#   1. the seed (in code, never affected by database state)
#   2. the database, if a db handle is passed — this is the only way
#      to see places the narrator invented mid-session, which exist
#      nowhere but the database
#   3. nothing found -> the same "rough but never crashes" fallbacks
#      the old helpers used
# ============================================================

import rpg_places_seed

_SEED = None   # {id: Place}, built once — the seed is pure code, it never changes at runtime


def _seed() -> dict:
    global _SEED
    if _SEED is None:
        places, _handles = rpg_places_seed.build_world_tree()
        _SEED = {p.id: p for p in places}
    return _SEED


def get_place(location_id, db=None) -> dict | None:
    """Place as a plain dict. Seed first, then the database (invented
    places), else None."""
    if not location_id:
        return None
    p = _seed().get(location_id)
    if p is not None:
        return p.to_dict()
    if db is not None:
        try:
            return db.get_place(location_id)
        except Exception:
            return None
    return None


def location_name(location_id, db=None) -> str:
    """Display label. Falls back to the raw id, title-cased, so an
    unrecognised id never crashes a caller."""
    place = get_place(location_id, db)
    if place and place.get("name"):
        return place["name"]
    return str(location_id or "").replace("_", " ").title()


def is_warded_settlement(location_id, db=None) -> bool:
    """True when this place sits inside a settlement (area_type ==
    'settlement') — Townia's own lore: a settlement's ward keeps
    anyone within it from being killed. This does NOT mean combat is
    disabled, only that it can never be lethal there; see
    rpg_engine.resolve_action's use of this flag. A place with no
    resolvable area (freeform-invented, or an id not in the tree)
    is NOT warded — err toward real stakes rather than a blanket
    safety net for places we don't actually recognise."""
    place = get_place(location_id, db)
    if not place:
        return False
    area = get_place(place.get("area_id"), db) if place.get("area_id") else place
    return bool(area) and area.get("area_type") == "settlement"


def location_details(location_id, db=None) -> dict:
    """Grounding facts for the narrator. {} when the place is unknown
    or has nothing written. The seed has no separate landmark list
    (landmarks are their own child places now), so this is just the
    description, kept under the same keys the narrator already reads."""
    place = get_place(location_id, db)
    if not place:
        return {}
    return {
        "description": place.get("description"),
        "landmarks": [],
    }


def offered_trial(location_id, db=None) -> str | None:
    """Which class trial (warrior / mage / summoner) this place offers,
    or None. This is the gate the narrator checks before it may start
    a trial."""
    place = get_place(location_id, db)
    return place.get("offers_trial") if place else None


def encounter_pool(location_id, db=None) -> dict | None:
    """Monster list and level cap for a place, or None when it can't
    spawn encounters (towns, shops). Same return shape the old helper
    had, so rpg_battle.generate_encounter is unchanged apart from the
    lookup. Only places with a monster_pool and max_level spawn."""
    place = get_place(location_id, db)
    if not place or not place.get("monster_pool"):
        return None
    pool = place["monster_pool"]
    if isinstance(pool, str):
        pool = [m.strip() for m in pool.split(",") if m.strip()]
    if not pool:
        return None
    return {"max_level": place.get("max_level") or 1, "monster_pool": list(pool)}


def location_path(location_id, db=None) -> dict:
    """Dimension -> ... -> District -> Location path for the narrator,
    using the same keys and "---" placeholder convention the old
    helper used. Built from the place's own ancestor chain."""
    tree = _seed()
    place = get_place(location_id, db)
    if not place:
        return {
            "dimension": "---", "continent": "---", "region": "---",
            "nation": "---", "state": "---", "area": "---",
            "settlement_size_label": None, "area_name": "---",
            "district": "Unknown", "location": location_name(location_id, db),
        }

    def _name(pid):
        p = tree.get(pid) if pid else None
        if p is None and pid and db is not None:
            try:
                row = db.get_place(pid)
            except Exception:
                row = None
            return (row or {}).get("name")
        return p.name if p else None

    area_id = place.get("area_id") or (place["id"] if place.get("tier") == "area" else None)
    area = tree.get(area_id)
    area_type = (area.area_type if area else None) or ""
    settlement = None
    if area_type == "settlement":
        settlement = ((area.settlement_size if area else None) or "settlement").title()

    subdivides = bool(area and area.subdivision)
    district = _name(place.get("district_id")) if subdivides else None

    return {
        "dimension": _name(place.get("dimension_id")) or "---",
        "continent": _name(place.get("continent_id")) or "---",
        "region": _name(place.get("region_id")) or "---",
        "nation": _name(place.get("nation_id")) or "---",
        "state": _name(place.get("state_id")) or "---",
        "area": area_type.title() if area_type else "---",
        "settlement_size_label": settlement,
        "area_name": (area.name if area else None) or "---",
        "district": district or "---",
        "location": place.get("name") or location_name(location_id, db),
    }


def find_place_id_by_name(label) -> str | None:
    """Seed place id whose display name matches this label exactly
    (case-insensitive), else None. Only used to upgrade very old saved
    sessions that stored a display label but no location id."""
    if not label:
        return None
    want = str(label).strip().lower()
    for pid, p in _seed().items():
        if p.tier in ("location", "landmark") and (p.name or "").strip().lower() == want:
            return pid
    return None
