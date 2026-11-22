# ============================================================
# NIFLHEIM — router/amongus_map.py
# Room graphs keyed by map ID. The user-selected default is the supplied
# Skeld image; repeated labels are canonicalized to the standard 14 rooms.
# Travel durations remain gameplay values because the image has no scale.
# ============================================================

from dataclasses import dataclass

from . import amongus_config as C

MAP_ID = "skeld"
MAP_NAME = "The Skeld"
DEFAULT_MAP_ID = MAP_ID
MAP_IS_FINAL = True
MAP_SOURCE = "user-supplied Skeld map image"
START_ROOM = "CAFETERIA"

# room -> {neighbor: seconds}. Symmetric (built both directions below).
_EDGES_RAW = [
    ("CAFETERIA", "MEDBAY", 4),
    ("CAFETERIA", "WEAPONS", 4),
    ("CAFETERIA", "STORAGE", 5),
    ("CAFETERIA", "ADMIN", 6),       # confirmed direct — not only via Storage
    ("UPPER_ENGINE", "REACTOR", 4),
    ("REACTOR", "LOWER_ENGINE", 4),
    ("REACTOR", "SECURITY", 4),      # the 4-way junction (Upper/Lower Engine, Security all meet at Reactor)
    ("SECURITY", "MEDBAY", 4),
    ("SECURITY", "ELECTRICAL", 4),
    ("ELECTRICAL", "STORAGE", 4),
    ("STORAGE", "ADMIN", 4),
    ("STORAGE", "COMMUNICATIONS", 5),
    ("ADMIN", "SHIELDS", 5),
    ("WEAPONS", "O2", 4),
    ("O2", "NAVIGATION", 5),
    ("NAVIGATION", "SHIELDS", 4),
    ("SHIELDS", "COMMUNICATIONS", 4),
]

EDGES = {}
for _a, _b, _t in _EDGES_RAW:
    EDGES.setdefault(_a, {})[_b] = _t
    EDGES.setdefault(_b, {})[_a] = _t

ROOMS = sorted(EDGES.keys())

# Impostor-only vent network based on the supplied image and the legacy
# trial's route graph.
VENTS = {
    "REACTOR":      ["UPPER_ENGINE", "LOWER_ENGINE"],
    "UPPER_ENGINE":  ["REACTOR", "LOWER_ENGINE"],
    "LOWER_ENGINE":  ["REACTOR", "UPPER_ENGINE"],
    "ELECTRICAL":   ["MEDBAY", "SECURITY"],
    "MEDBAY":       ["ELECTRICAL", "SECURITY"],
    "SECURITY":     ["ELECTRICAL", "MEDBAY"],
    "WEAPONS":      ["NAVIGATION"],
    "NAVIGATION":   ["WEAPONS", "SHIELDS"],
    "SHIELDS":      ["NAVIGATION"],
}

# One task per room for the legacy trial mechanics; later sessions replace
# this with the randomized task subset from the full design.
TASKS = {
    "CAFETERIA":      ("Empty Garbage", 6),
    "MEDBAY":         ("Submit Scan", 10),
    "UPPER_ENGINE":   ("Fuel Engine", 7),
    "SECURITY":       ("Fix Wiring", 6),
    "REACTOR":        ("Start Reactor", 9),
    "LOWER_ENGINE":   ("Fuel Engine", 7),
    "ELECTRICAL":     ("Fix Wiring", 8),
    "STORAGE":        ("Fuel Engines", 6),
    "ADMIN":          ("Swipe Card", 5),
    "WEAPONS":        ("Clear Asteroids", 6),
    "O2":             ("Empty Garbage", 6),
    "NAVIGATION":     ("Chart Course", 7),
    "SHIELDS":        ("Prime Shields", 6),
    "COMMUNICATIONS": ("Upload Data", 6),
}

# Meltdown's two fix-rooms — mapped to the real game's actual O2
# sabotage pairing (two separate rooms), per the design notes' rule
# that Meltdown always needs two different rooms to confirm from.
MELTDOWN_ROOMS = ("O2", "ADMIN")

MELTDOWN_DOOM_SECONDS = C.LEGACY_MELTDOWN_DOOM_SECONDS
COOLDOWN_ACTION_SECONDS = C.LEGACY_COOLDOWN_ACTION_SECONDS


@dataclass(frozen=True)
class MapDefinition:
    id: str
    name: str
    start_room: str
    rooms: tuple
    edges: dict
    vents: dict
    tasks: dict
    meltdown_rooms: tuple
    meltdown_doom_seconds: int
    cooldown_action_seconds: int
    travel_times_approximate: bool = True


MAPS = {
    MAP_ID: MapDefinition(
        id=MAP_ID,
        name=MAP_NAME,
        start_room=START_ROOM,
        rooms=tuple(ROOMS),
        edges=EDGES,
        vents=VENTS,
        tasks=TASKS,
        meltdown_rooms=MELTDOWN_ROOMS,
        meltdown_doom_seconds=MELTDOWN_DOOM_SECONDS,
        cooldown_action_seconds=COOLDOWN_ACTION_SECONDS,
    )
}


# ── Additional maps (Cyberia Facility, Orbital Research Station) ──
# Built from the supplied images. Room links and travel seconds are gameplay
# values read off the pictures (the images have no scale); adjust freely.

def _build_edges(raw):
    edges = {}
    for a, b, t in raw:
        edges.setdefault(a, {})[b] = t
        edges.setdefault(b, {})[a] = t
    return edges


def _mapdef(map_id, name, raw_edges, vents, tasks, meltdown, start="CAFETERIA"):
    edges = _build_edges(raw_edges)
    return MapDefinition(
        id=map_id,
        name=name,
        start_room=start,
        rooms=tuple(sorted(edges)),
        edges=edges,
        vents=vents,
        tasks=tasks,
        meltdown_rooms=meltdown,
        meltdown_doom_seconds=MELTDOWN_DOOM_SECONDS,
        cooldown_action_seconds=COOLDOWN_ACTION_SECONDS,
    )


_CYBERIA_EDGES = [
    ("REACTOR", "ENGINES", 4),
    ("REACTOR", "SECURITY", 4),
    ("REACTOR", "MEDBAY", 4),
    ("ENGINES", "ADMIN", 5),
    ("ENGINES", "SECURITY", 4),
    ("SECURITY", "STORAGE", 4),
    ("ADMIN", "ELECTRICAL", 5),
    ("ADMIN", "STORAGE", 4),
    ("ELECTRICAL", "O2", 5),
    ("ELECTRICAL", "STORAGE", 4),
    ("O2", "WEAPONS", 4),
    ("O2", "NAVIGATION", 4),
    ("NAVIGATION", "STORAGE", 4),
    ("NAVIGATION", "WEAPONS", 4),
    ("WEAPONS", "COMMS", 4),
    ("COMMS", "LOWER_ENGINE", 5),
    ("COMMS", "NAVIGATION", 5),
    ("LOWER_ENGINE", "CAFETERIA", 4),
    ("LOWER_ENGINE", "STORAGE", 4),
    ("CAFETERIA", "MEDBAY", 4),
    ("CAFETERIA", "SECURITY", 4),
    ("CAFETERIA", "STORAGE", 5),
]

_CYBERIA_VENTS = {
    "REACTOR":   ["ENGINES", "SECURITY"],
    "ENGINES":   ["REACTOR", "SECURITY"],
    "SECURITY":  ["REACTOR", "ENGINES"],
    "ADMIN":     ["ELECTRICAL"],
    "ELECTRICAL": ["ADMIN", "O2"],
    "O2":        ["ELECTRICAL"],
    "WEAPONS":   ["NAVIGATION", "COMMS"],
    "NAVIGATION": ["WEAPONS"],
    "COMMS":     ["WEAPONS"],
}

_CYBERIA_TASKS = {
    "CAFETERIA":    ("Emergency Check", 5),
    "MEDBAY":       ("Body Scanner", 10),
    "REACTOR":      ("Unlock Manifolds", 8),
    "ENGINES":      ("Fuel Engines", 7),
    "LOWER_ENGINE": ("Align Engine", 7),
    "SECURITY":     ("Divert Power", 6),
    "ADMIN":        ("Swipe Card", 5),
    "ELECTRICAL":   ("Fix Wiring", 8),
    "O2":           ("Clean Filter", 6),
    "WEAPONS":      ("Clear Asteroids", 6),
    "NAVIGATION":   ("Star Chart", 7),
    "STORAGE":      ("Calibrate Distributor", 7),
    "COMMS":        ("Download Data", 6),
}

_ORBITAL_EDGES = [
    ("COCKPIT", "REACTOR", 3),
    ("REACTOR", "UPPER_ENGINE", 4),
    ("REACTOR", "LOWER_ENGINE", 4),
    ("REACTOR", "ADMIN", 4),
    ("UPPER_ENGINE", "GARDEN_DOME", 5),
    ("GARDEN_DOME", "CAFETERIA", 5),
    ("GARDEN_DOME", "CRYO_LAB", 4),
    ("CRYO_LAB", "MEDBAY", 3),
    ("CRYO_LAB", "ADMIN", 4),
    ("CAFETERIA", "MEDBAY", 5),
    ("CAFETERIA", "STORAGE", 5),
    ("STORAGE", "NAVIGATION", 5),
    ("STORAGE", "WEAPONS", 4),
    ("WEAPONS", "ELECTRICAL", 4),
    ("WEAPONS", "DATA_CENTER", 4),
    ("ELECTRICAL", "O2", 4),
    ("ELECTRICAL", "AI_CORE", 3),
    ("ELECTRICAL", "LOWER_ENGINE", 5),
    ("AI_CORE", "DATA_CENTER", 3),
    ("DATA_CENTER", "MINING_BAY", 4),
    ("NAVIGATION", "MINING_BAY", 5),
    ("O2", "ADMIN", 4),
]

_ORBITAL_VENTS = {
    "REACTOR":      ["UPPER_ENGINE", "LOWER_ENGINE"],
    "UPPER_ENGINE": ["REACTOR", "LOWER_ENGINE"],
    "LOWER_ENGINE": ["REACTOR", "UPPER_ENGINE"],
    "ELECTRICAL":   ["AI_CORE", "O2"],
    "AI_CORE":      ["ELECTRICAL", "O2"],
    "O2":           ["ELECTRICAL", "AI_CORE"],
    "WEAPONS":      ["STORAGE"],
    "STORAGE":      ["WEAPONS"],
}

_ORBITAL_TASKS = {
    "COCKPIT":      ("Chart Course", 7),
    "REACTOR":      ("Start Reactor", 9),
    "UPPER_ENGINE": ("Fuel Engine", 7),
    "LOWER_ENGINE": ("Fuel Engine", 7),
    "ADMIN":        ("Swipe Card", 5),
    "O2":           ("Clean Filter", 6),
    "ELECTRICAL":   ("Fix Wiring", 8),
    "AI_CORE":      ("Reboot AI", 8),
    "DATA_CENTER":  ("Upload Data", 6),
    "WEAPONS":      ("Clear Asteroids", 6),
    "STORAGE":      ("Fuel Engines", 6),
    "NAVIGATION":   ("Chart Course", 7),
    "MINING_BAY":   ("Mine Ore", 7),
    "CAFETERIA":    ("Empty Garbage", 6),
    "GARDEN_DOME":  ("Water Plants", 6),
    "CRYO_LAB":     ("Check Cryo Pods", 7),
    "MEDBAY":       ("Submit Scan", 10),
}

MAPS["cyberia"] = _mapdef(
    "cyberia", "Cyberia Facility", _CYBERIA_EDGES, _CYBERIA_VENTS,
    _CYBERIA_TASKS, ("O2", "ADMIN"),
)
MAPS["orbital"] = _mapdef(
    "orbital", "Orbital Research Station", _ORBITAL_EDGES, _ORBITAL_VENTS,
    _ORBITAL_TASKS, ("O2", "ADMIN"),
)

# Lobby-selectable maps, in menu order (1-based numbers for `.lobby map 2`).
MAP_ORDER = ("skeld", "cyberia", "orbital")
MAP_ALIASES = {
    "skeld": "skeld", "theskeld": "skeld",
    "cyberia": "cyberia", "cyberiafacility": "cyberia", "facility": "cyberia",
    "orbital": "orbital", "orbitalresearchstation": "orbital",
    "orbitalresearch": "orbital", "station": "orbital",
}


def resolve_map(arg):
    """Map id from a number (1-based) or a name; None if nothing matches."""
    key = "".join(ch for ch in str(arg).lower() if ch.isalnum())
    if not key:
        return None
    if key.isdigit():
        n = int(key)
        return MAP_ORDER[n - 1] if 1 <= n <= len(MAP_ORDER) else None
    return MAP_ALIASES.get(key)


def map_menu_text():
    return "\n".join(f"{i}. {MAPS[m].name}" for i, m in enumerate(MAP_ORDER, 1))


def random_map_id():
    """Random lobby map. AMONGUS_FIXED_MAP=<id> pins it (tests / debugging)."""
    import os
    import random
    fixed = os.environ.get("AMONGUS_FIXED_MAP", "").strip().lower()
    if fixed in MAPS:
        return fixed
    return random.choice(MAP_ORDER)


def get_map(map_id=DEFAULT_MAP_ID):
    try:
        return MAPS[map_id]
    except KeyError as exc:
        raise ValueError(
            f"Unknown Niflheim map {map_id!r}. Available maps: "
            f"{', '.join(sorted(MAPS))}"
        ) from exc


def shortest_path(start, end, map_id=DEFAULT_MAP_ID):
    """Dijkstra over EDGES, minimizing total travel TIME (not hop count),
    since dwell time varies per edge. Returns list of rooms including
    start and end, or None if unreachable (shouldn't happen — graph's
    fully connected) or start==end (returns [start])."""
    if start == end:
        return [start]
    import heapq
    dist = {start: 0}
    prev = {}
    pq = [(0, start)]
    visited = set()
    while pq:
        d, node = heapq.heappop(pq)
        if node in visited:
            continue
        visited.add(node)
        if node == end:
            break
        for nbr, w in get_map(map_id).edges.get(node, {}).items():
            nd = d + w
            if nbr not in dist or nd < dist[nbr]:
                dist[nbr] = nd
                prev[nbr] = node
                heapq.heappush(pq, (nd, nbr))
    if end not in dist:
        return None
    path = [end]
    while path[-1] != start:
        path.append(prev[path[-1]])
    path.reverse()
    return path


def path_hops(path, map_id=DEFAULT_MAP_ID):
    """[(room_a, room_b, seconds), ...] for each leg of a path."""
    edges = get_map(map_id).edges
    return [(path[i], path[i+1], edges[path[i]][path[i+1]]) for i in range(len(path) - 1)]
    edges = get_map(map_id).edges
    return [(path[i], path[i+1], edges[path[i]][path[i+1]]) for i in range(len(path) - 1)]


# ── Sabotage repair stations (per map) ─────────────────────
# map_id -> sabotage -> ordered station entries (key, label, room).
# Session 06A/09: stations are map data; the count is defined per sabotage
# (Lights 1, Communications 1, O2 2, Reactor 2). Only The Skeld exists now;
# add another map by adding another top-level entry. Sabotage code reads these
# through get_stations()/get_station_rooms() and never hard-codes room names.
# Skeld pairs: Reactor = Upper + Lower Engine (06C), O2 = O2 + Admin (06D).
SABOTAGE_STATIONS_BY_MAP = {
    MAP_ID: {
        "lights": (("lights_repair", "Lights repair", "ELECTRICAL"),),
        "communications": (
            ("comms_repair", "Communications repair", "COMMUNICATIONS"),
        ),
        "oxygen": (
            ("oxygen_a", "Oxygen station", "O2"),
            ("oxygen_b", "Oxygen station", "ADMIN"),
        ),
        "reactor": (
            ("reactor_a", "Reactor station", "UPPER_ENGINE"),
            ("reactor_b", "Reactor station", "LOWER_ENGINE"),
        ),
    },
    "cyberia": {
        "lights": (("lights_repair", "Lights repair", "ELECTRICAL"),),
        "communications": (("comms_repair", "Communications repair", "COMMS"),),
        "oxygen": (
            ("oxygen_a", "Oxygen station", "O2"),
            ("oxygen_b", "Oxygen station", "ADMIN"),
        ),
        "reactor": (
            ("reactor_a", "Reactor station", "ENGINES"),
            ("reactor_b", "Reactor station", "LOWER_ENGINE"),
        ),
    },
    "orbital": {
        "lights": (("lights_repair", "Lights repair", "ELECTRICAL"),),
        "communications": (("comms_repair", "Communications repair", "DATA_CENTER"),),
        "oxygen": (
            ("oxygen_a", "Oxygen station", "O2"),
            ("oxygen_b", "Oxygen station", "ADMIN"),
        ),
        "reactor": (
            ("reactor_a", "Reactor station", "UPPER_ENGINE"),
            ("reactor_b", "Reactor station", "LOWER_ENGINE"),
        ),
    },
}


def validate_station_registry():
    """Raise ValueError unless every map has valid stations for every sabotage."""
    required = ("lights", "communications", "oxygen", "reactor")
    for map_id, table in SABOTAGE_STATIONS_BY_MAP.items():
        rooms = get_map(map_id).rooms
        for name in required:
            if name not in table or not table[name]:
                raise ValueError(f"Map {map_id!r} has no stations for {name!r}")
            for _key, _label, room in table[name]:
                if room not in rooms:
                    raise ValueError(
                        f"Station room {room!r} is not on map {map_id!r}"
                    )


def get_stations(name, map_id=DEFAULT_MAP_ID):
    """Ordered ((key, label, room), ...) repair stations for a sabotage."""
    try:
        table = SABOTAGE_STATIONS_BY_MAP[map_id]
    except KeyError as exc:
        raise ValueError(f"No sabotage stations defined for map {map_id!r}") from exc
    stations = table[name]
    rooms = get_map(map_id).rooms
    for _key, _label, room in stations:
        if room not in rooms:
            raise ValueError(f"Station room {room!r} is not on map {map_id!r}")
    return stations


def get_station_rooms(name, map_id=DEFAULT_MAP_ID):
    """The repair-station rooms (in order) for a sabotage on a map."""
    return tuple(room for _key, _label, room in get_stations(name, map_id))


validate_station_registry()
