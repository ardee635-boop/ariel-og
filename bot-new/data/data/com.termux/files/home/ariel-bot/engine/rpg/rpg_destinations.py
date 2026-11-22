# ============================================================
# rpg_destinations.py — forgiving destination matching
#
# Replaces the exact-name-only lookup in rpg_movement.resolve_
# destination_name. The player's words for a destination are matched
# to a real place in four layers, cheapest first, and the first layer
# that gives ONE clear answer wins:
#
#   1. exact     — the place's own seeded name, or an alias (below)
#   2. cleaned   — same, after dropping "the/a/an/to/at/...", case,
#                  punctuation, and a trailing "s"; also accepts a
#                  partial match ("market" -> "the market") when only
#                  ONE candidate fits
#   3. relative  — "back", "leave", "outside", "exit" -> the place
#                  the player just came from (session.flags)
#   4. typo      — close spelling ("colleseum") — only when ONE
#                  candidate is clearly closest
#
# Candidates are NEARBY places only: what the passages from the
# player's current location lead to (plus the current place's parent
# district and children). The old resolver matched any place in the
# whole world by exact name, which let a player teleport across town
# by typing a name. Nearby-only fixes that and keeps typo matching
# safe, because there are only a handful of things to confuse.
#
# No model call anywhere in here. Pure string work, microseconds.
# Aliases live in code (this file) rather than the database so the
# seed stays the anchor and no schema change is needed.
# ============================================================

import difflib
import re

# Extra names players use for a place, keyed by place id. Add freely.
# Matching is case-insensitive and goes through the same cleanup as
# everything else, so write them plainly.
ALIASES = {
    "townia_square": ["square", "town square", "town center", "town centre",
                      "central square", "plaza", "center", "centre", "central district",
                      "town"],
    "townia_church": ["church", "church of beginnings", "chapel", "elder church"],
    "townia_library": ["library", "libary", "the books", "book house", "mage library"],
    "townia_shrine": ["shrine", "small shrine", "quiet shrine"],
    "townia_market": ["market", "marketplace", "market square", "bazaar",
                      "stalls", "east district", "east", "eastern", "eastern district",
                      "east side"],
    "townia_pet_shop": ["pet shop", "pets", "pet store", "animal shop",
                        "summoner shop", "petshop"],
    "west_district_road": ["west district", "west", "west road", "west side",
                           "western", "western district"],
    "coliseum": ["coliseum", "colosseum", "arena", "the arena", "warrior arena",
                 "fighting arena", "colliseum"],
    "coliseum_lobby": ["lobby", "coliseum lobby", "entrance hall"],
    "adventurers_guild": ["guild", "adventurers guild", "adventurer guild",
                          "guild hall", "guildhall", "adventurers' guild"],
    "south_district_road": ["south district", "south", "south road", "south side",
                           "southern", "southern district"],
    "south_district_lodging": ["lodging", "inn", "tavern", "lodge"],
    "townia_garden_shop": ["garden shop", "garden", "greenhouse shop", "gardener",
                           "odalys shop", "plant shop"],
    "townia_greenhouse": ["greenhouse"],
    "northern_gate": ["gate", "north gate", "northern gate", "town gate",
                      "main gate", "entrance", "north"],
    "outer_forest_road": ["forest", "dark forest", "outer forest", "outer ring",
                          "woods", "the woods"],
    "inner_forest_road": ["inner forest", "inner ring", "deeper forest", "deeper into the forest"],
    "deep_forest_road": ["deep forest", "deep ring", "innermost ring", "forest depths"],
    # ── Townia additions ──────────────────────────────────────────
    "townia_waking_stone": ["waking stone", "stone", "pale stone"],
    "townia_bell_tower": ["bell tower", "bell", "church tower"],
    "townia_twin_altar": ["twin altar", "altar", "split altar"],
    "townia_apothecary": ["apothecary", "apothecry", "potion shop", "potions", "herb shop", "healer"],
    "townia_storehouse": ["storehouse", "storage", "vault", "warehouse", "bank"],
    "townia_training_yard": ["training yard", "yard", "training", "practice yard", "training grounds"],
    "townia_smithy": ["smithy", "forge", "blacksmith", "smith"],
    "townia_quest_board": ["quest board", "board", "notice board", "job board"],
    "townia_bathhouse": ["bathhouse", "bath house", "baths", "the baths", "hot spring"],
    "townia_quiet_garden": ["quiet garden", "walled garden", "garden benches"],
    "townia_tower_ne": ["northeast tower", "north east tower", "ne tower"],
    "townia_tower_se": ["southeast tower", "south east tower", "se tower"],
    "townia_tower_sw": ["southwest tower", "south west tower", "sw tower"],
    "townia_tower_nw": ["northwest tower", "north west tower", "nw tower"],
    "townia_lakeshore": ["lake", "lakeshore", "lake shore", "shore"],
    "townia_old_pier": ["pier", "old pier", "wooden pier"],
    "townia_falls_pool": ["waterfall", "waterfall pool", "falls", "pool"],
    "townia_falls_cliff": ["cliff", "ledge", "cliff above the falls", "top of the falls"],
    "townia_ruin_court": ["ruin", "ruins", "ruined courtyard", "courtyard"],
    "townia_broken_arch": ["broken arch", "arch", "archway"],
    "townia_ruin_hall": ["ruined hall", "hall", "ruined hall"],
    "townia_dungeon_entrance": ["dungeon", "dungeon entrance", "stairway", "stairs down"],
    "townia_dungeon_upper": ["upper halls", "upper floor", "first floor"],
    "townia_dungeon_lower": ["lower halls", "lower floor", "second floor"],
    "townia_dungeon_chamber": ["deep chamber", "chamber", "great doors"],
}

# Words that carry no identity. Removed before comparing.
_STOPWORDS = {
    "the", "a", "an", "to", "at", "in", "into", "on", "of", "towards", "toward",
    "go", "goto", "head", "walk", "run", "travel", "move", "return", "visit",
    "over", "there", "my", "our", "some", "that", "this", "i", "me",
}

# "leave" style words: mean "go to where I just was" (or up a level).
_RELATIVE_WORDS = {
    "back", "outside", "out", "leave", "exit", "away", "previous", "before",
    "where i was", "where i came from", "the way i came", "go back",
}

TYPO_CUTOFF = 0.80      # 0..1 similarity a typo match must reach
TYPO_MARGIN = 0.08      # the best match must beat the runner-up by this much
MIN_TYPO_LEN = 4        # don't fuzzy-match very short words ("inn", "gate")
PARTIAL_MIN_LEN = 3     # shortest fragment accepted as a partial match


def _clean(text) -> str:
    """Lowercase, strip punctuation and filler words, collapse spaces."""
    s = str(text or "").lower().replace("\u2019", "'").replace("\u2011", "-")
    s = re.sub(r"[^a-z0-9' ]+", " ", s)
    s = s.replace("'", "")
    words = [w for w in s.split() if w not in _STOPWORDS]
    return " ".join(words).strip()


def _singular(word: str) -> str:
    return word[:-1] if len(word) > 3 and word.endswith("s") and not word.endswith("ss") else word


def _norm(text) -> str:
    """_clean plus a trailing-s fold so 'stalls' == 'stall', 'pets' == 'pet'."""
    return " ".join(_singular(w) for w in _clean(text).split())


_LEAVE_PREFIXES = ("outside", "out of", "leave", "exit", "away from", "back out of")


def _is_relative(raw) -> bool:
    s = " ".join(str(raw or "").lower().split())
    if s in _RELATIVE_WORDS:
        return True
    if _clean(raw) in _RELATIVE_WORDS:
        return True
    # "outside the market", "leave the market", "exit the library" all
    # mean "get out of here", whatever place is named after the verb
    return any(s == p or s.startswith(p + " ") for p in _LEAVE_PREFIXES)


def _names_for(place: dict) -> list:
    """Every name this place answers to: its display name + aliases."""
    names = []
    if place.get("name"):
        names.append(place["name"])
    names.extend(ALIASES.get(place["id"], []))
    return names


def get_candidates(db, current_place: dict) -> list:
    """Places the player could plausibly mean from here: everything
    connected by a passage, the current place's parent district, its
    child places, and the current place itself (for 'already here')."""
    seen, out = set(), []

    def add(place):
        if place and place["id"] not in seen:
            seen.add(place["id"])
            out.append(place)

    try:
        for psg in db.get_passages_from(current_place["id"]):
            add(db.get_place(psg["to_id"]))
    except Exception:
        pass
    try:
        for child in db.get_children(current_place["id"]):
            add(child)
    except Exception:
        pass
    if current_place.get("parent_id"):
        parent = db.get_place(current_place["parent_id"])
        # a district or area is a label, not somewhere you can walk to
        if parent and parent.get("tier") in ("location", "landmark"):
            add(parent)
    add(current_place)
    return out


def _match_exact(norm_text: str, candidates: list):
    hits = [p for p in candidates
            if any(_norm(n) == norm_text for n in _names_for(p))]
    return hits


def _match_partial(norm_text: str, candidates: list):
    """Player's words are a whole-word fragment of a place's name, or
    a place's alias is a whole-word fragment of what the player said."""
    if len(norm_text) < PARTIAL_MIN_LEN:
        return []
    twords = set(norm_text.split())
    hits = []
    for p in candidates:
        for n in _names_for(p):
            nn = _norm(n)
            nwords = set(nn.split())
            if not nwords:
                continue
            if twords <= nwords or nwords <= twords:
                hits.append(p)
                break
    return hits


_DIRS = {"north": "n", "northern": "n", "south": "s", "southern": "s",
         "east": "e", "eastern": "e", "west": "w", "western": "w"}
_UNSUPPORTED = {"left", "right", "ahead", "behind", "forward", "forwards"}


def _dirs(norm: str) -> set:
    return {_DIRS[w] for w in norm.split() if w in _DIRS}


def _match_typo(norm_text: str, candidates: list):
    """Close spelling. Returns [place] only when one candidate is
    clearly closest; [] when nothing is close or when it's a toss-up."""
    if len(norm_text) < MIN_TYPO_LEN:
        return []
    # left/right/ahead have no meaning in a compass-layout town
    if _UNSUPPORTED & set(norm_text.split()):
        return []
    td = _dirs(norm_text)
    scored = []
    for p in candidates:
        best = 0.0
        for n in _names_for(p):
            nn = _norm(n)
            if len(nn) < MIN_TYPO_LEN:
                continue
            nd = _dirs(nn)
            # "east district" must never typo-match "west district"
            if td and nd and td != nd:
                continue
            best = max(best, difflib.SequenceMatcher(None, norm_text, nn).ratio())
        scored.append((best, p))
    scored.sort(key=lambda x: x[0], reverse=True)
    if not scored or scored[0][0] < TYPO_CUTOFF:
        return []
    if len(scored) > 1 and scored[0][0] - scored[1][0] < TYPO_MARGIN:
        return []
    return [scored[0][1]]


def resolve_destination(db, text, current_place: dict, previous_place_id=None) -> dict:
    """
    Returns {"place": dict|None, "how": str, "already_here": bool,
             "ambiguous": [names]}.
    'how' is one of: exact, cleaned, relative, typo, none — useful for
    logging which layer resolved a move.
    """
    result = {"place": None, "how": "none", "already_here": False, "ambiguous": []}
    if not text or not str(text).strip():
        return result

    # 3 (checked early, because "back" is never a real place name).
    if _is_relative(text):
        target = None
        if previous_place_id and previous_place_id != current_place["id"]:
            target = db.get_place(previous_place_id)
        if target is None and current_place.get("parent_id"):
            parent = db.get_place(current_place["parent_id"])
            # only step "up" to a real place, not to an abstract district
            if parent and parent.get("tier") in ("location", "landmark"):
                target = parent
        if target is None:
            # nothing to go back to: fall back to any single connected
            # place, since "leave" from a dead-end has one obvious exit
            try:
                exits = [db.get_place(p["to_id"]) for p in db.get_passages_from(current_place["id"])]
                exits = [e for e in exits if e]
                if len(exits) == 1:
                    target = exits[0]
            except Exception:
                target = None
        if target:
            result.update(place=target, how="relative")
        return result

    candidates = get_candidates(db, current_place)
    norm_text = _norm(text)
    if not norm_text:
        return result

    for how, fn in (("exact", _match_exact), ("cleaned", _match_partial), ("typo", _match_typo)):
        hits = fn(norm_text, candidates)
        if len(hits) == 1:
            result.update(place=hits[0], how=how)
            break
        if len(hits) > 1:
            # A tie is never guessed. Prefer a hit that is a real
            # connection (not just the current place) if that's unique.
            non_self = [h for h in hits if h["id"] != current_place["id"]]
            if len(non_self) == 1:
                result.update(place=non_self[0], how=how)
                break
            result["ambiguous"] = [h.get("name") or h["id"] for h in hits]
            return result

    if result["place"] and result["place"]["id"] == current_place["id"]:
        result["already_here"] = True
    return result



# ============================================================
# FAR DESTINATIONS (journeys)
#
# resolve_destination() above only sees NEARBY places on purpose (no
# teleporting by typing a name). A far destination is different: the
# player still can't jump there, but they can START A JOURNEY toward
# it. We walk the passage graph outward from where they stand
# (breadth-first, "established" passages only), so a place is
# "far but known" exactly when a chain of real passages leads to it.
# Each hop is one leg (one turn). No model call anywhere in here.
# ============================================================

MAX_ROUTE_NODES = 400   # safety cap on how much of the graph we walk


def bfs_routes(db, start_id: str) -> dict:
    """{place_id: [hop ids from start (exclusive) to that place (inclusive)]}.
    start_id itself maps to []. Only 'established' passages are walked —
    'open' (unbuilt) and 'absent' (rejected) are not roads yet."""
    routes = {start_id: []}
    queue = [start_id]
    while queue and len(routes) < MAX_ROUTE_NODES:
        cur = queue.pop(0)
        try:
            passages = db.get_passages_from(cur)
        except Exception:
            continue
        for psg in passages:
            if psg.get("state") != "established":
                continue
            nxt = psg["to_id"]
            if nxt in routes:
                continue
            routes[nxt] = routes[cur] + [nxt]
            queue.append(nxt)
    return routes


def route_to(db, start_id: str, dest_id: str):
    """Hop list from start to dest (len = legs), or None if no road."""
    return bfs_routes(db, start_id).get(dest_id)


def resolve_far_destination(db, text, current_place: dict) -> dict:
    """
    Same matching cascade as resolve_destination (exact -> partial ->
    typo), but over places 2+ legs away along real passages. Direct
    neighbours are NOT candidates here — resolve_destination owns those.
    Returns {"place": dict|None, "route": [ids]|None, "ambiguous": [names]}.
    """
    result = {"place": None, "route": None, "ambiguous": []}
    if not text or not str(text).strip() or _is_relative(text):
        return result
    norm_text = _norm(text)
    if not norm_text:
        return result

    routes = bfs_routes(db, current_place["id"])
    candidates = []
    for pid, path in routes.items():
        if len(path) < 2:
            continue
        place = db.get_place(pid)
        if place and place.get("name"):
            candidates.append(place)
    if not candidates:
        return result

    for fn in (_match_exact, _match_partial, _match_typo):
        hits = fn(norm_text, candidates)
        if len(hits) == 1:
            result["place"] = hits[0]
            result["route"] = routes[hits[0]["id"]]
            return result
        if len(hits) > 1:
            result["ambiguous"] = [h.get("name") or h["id"] for h in hits]
            return result
    return result
