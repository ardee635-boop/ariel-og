# ============================================================
# NIFLHEIM-ONLINE — SITE ACTION HANDLERS
#
# Actions dispatched from the site (via bridge.py's "type" field,
# as opposed to WhatsApp commands via "text"). These run through
# the same Player/OwnedPokemon model as the bot, so party/PC rules
# never drift between WhatsApp and the site.
#
# Every handler takes (router, sender, payload) and returns a plain
# dict — no game text, just structured data for the site to render.
# Errors are returned as {"error": "..."} rather than raised, since
# bridge.py forwards this straight back to Node/the site as JSON.
#
# MODEL NOTE: player.party and player.box are both flat lists with
# no gaps (see models.Player.add_to_party) — "empty slot" in the UI
# just means index >= len(list), it isn't a stored null. So a swap
# either exchanges two existing mons, or moves one mon into a list
# that has room, never creates a hole.
# ============================================================

from data_items import OAK_TOWN_SHOP

MAX_PARTY = 6
_SHOP_BY_NAME = {item["name"]: item for item in OAK_TOWN_SHOP}

# Same curated pools registration.py's _reg_finish uses for .start on
# WhatsApp — kept in sync here since the site is now the only place a
# fresh trainer is actually created (see index.js /api/auth/signup).
ELEMENTAL_BALLS = [
    "Pyro Ball", "Cryo Ball", "Atmo Ball", "Floro Ball", "Volt Ball",
    "Aether Ball", "Aqua Ball", "Brawn Ball", "Toxic Ball", "Terra Ball",
    "Psy Ball", "Swarm Ball", "Crag Ball", "Phantom Ball", "Wyrm Ball",
    "Umbra Ball", "Alloy Ball", "Fae Ball", "Random Ball",
]
FIRE_STARTERS  = ["charmander", "cyndaquil", "torchic", "chimchar", "fennekin",
                  "tepig", "litten", "scorbunny", "fuecoco", "growlithe"]
WATER_STARTERS = ["squirtle", "totodile", "mudkip", "piplup", "oshawott",
                  "froakie", "popplio", "sobble", "quaxly", "shellder"]
GRASS_STARTERS = ["bulbasaur", "chikorita", "treecko", "turtwig", "snivy",
                  "chespin", "rowlet", "grookey", "sprigatito", "oddish"]

# ── "Special few" — every sender that had a real players row before the
# pre-launch data wipe (captured 2026-07-11, 19 total). Hardcoded because
# the players table itself is about to be cleared, so there's no way to
# derive this list live after that point. A sender counts as a match if
# ANY of jid/lid/phone matches — see _is_special_few below. Each person
# is only granted the legacy egg once (guarded by the "legacy_egg_given"
# flag in handle_grant_starter), so even if more than one identifier
# matches the same person, they can't be double-counted.
from config import LEGACY_EGG_IDS
SPECIAL_FEW = set(LEGACY_EGG_IDS)   # from the LEGACY_EGG_IDS env var


def _is_special_few(router, sender, jid=None, lid=None):
    """
    True if ANY of sender/jid/lid matches the pre-wipe snapshot
    (SPECIAL_FEW) OR has been added since via .addlegacy (stored in
    the legacy_players table — see database.py). SPECIAL_FEW itself
    stays frozen/hardcoded; the DB table is the only mutable part.
    """
    candidates = {c for c in (sender, jid, lid) if c}
    if candidates & SPECIAL_FEW:
        return True
    db = getattr(router, "db", None)
    if db is not None:
        for c in candidates:
            if db.legacy_player_exists(c):
                return True
    return False


def _list_for(player, loc):
    if loc == "party":
        return player.party
    if loc == "pc":
        return player.box
    return None


def _serialize_slots(player):
    return {
        "party": [p.to_dict() for p in player.party],
        "pc":    [p.to_dict() for p in player.box],
    }


def handle_swap(router, sender, payload):
    """
    Move/swap a Pokémon between two slots — party<->party, pc<->pc,
    or party<->pc.

    payload: {
        "from": {"loc": "party"|"pc", "idx": int},
        "to":   {"loc": "party"|"pc", "idx": int},
    }

    Rules:
    - Both slots must reference an EXISTING mon, OR the destination
      may be "one past the end" (an empty visual slot) as long as
      the target list has room (party capped at 6, pc uncapped).
    - If destination holds a mon, source and destination swap places.
    - If destination is the empty slot past the end, the mon simply
      moves there and is removed from the source list.
    """
    player = router._get(sender)
    if not player:
        return {"error": "No player record found."}

    frm = payload.get("from") or {}
    to  = payload.get("to") or {}
    from_loc, from_idx = frm.get("loc"), frm.get("idx")
    to_loc,   to_idx   = to.get("loc"),   to.get("idx")

    from_list = _list_for(player, from_loc)
    to_list   = _list_for(player, to_loc)

    if from_list is None or to_list is None:
        return {"error": "Invalid location. Must be 'party' or 'pc'."}
    if not isinstance(from_idx, int) or not isinstance(to_idx, int):
        return {"error": "Invalid slot index."}
    if from_idx < 0 or to_idx < 0:
        return {"error": "Slot index out of range."}
    if from_idx >= len(from_list):
        return {"error": "No Pokémon in that slot."}

    # Same list, same index — no-op.
    if from_loc == to_loc and from_idx == to_idx:
        return {"ok": True, **_serialize_slots(player)}

    dest_has_mon = to_idx < len(to_list)
    dest_is_next_empty = to_idx == len(to_list)

    if not dest_has_mon and not dest_is_next_empty:
        return {"error": "Destination slot is out of range."}

    if to_loc == "party" and to_idx >= MAX_PARTY:
        return {"error": "Party is capped at 6 Pokémon."}

    moving_mon = from_list[from_idx]

    if from_loc == to_loc:
        # Same list — plain positional swap (dest always has_mon here,
        # since same-list "next empty" would mean idx == len(list),
        # which can't happen unless the list is being appended to itself).
        from_list[from_idx], from_list[to_idx] = from_list[to_idx], from_list[from_idx]
    else:
        # Cross-list move.
        if dest_has_mon:
            # True swap: each mon takes the other's slot.
            other_mon = to_list[to_idx]
            to_list[to_idx] = moving_mon
            from_list[from_idx] = other_mon
        else:
            # Destination is the empty slot past the end — plain move.
            # (Party cap already checked above before any mutation.)
            to_list.append(moving_mon)
            from_list.pop(from_idx)

    router._save(sender, player)
    return {"ok": True, **_serialize_slots(player)}


def handle_buy(router, sender, payload):
    """
    Buy one item from the Oak Town Pokémart (site-side shop tab).

    payload: { "name": str }

    Uses OAK_TOWN_SHOP base prices (the "ps" / mart context — same
    price a player gets standing in the actual mart on WhatsApp).
    Site has no concept of "which zone are you standing in", so it
    always uses base price rather than the town/wild multipliers.
    """
    player = router._get(sender)
    if not player:
        return {"error": "No player record found."}

    name = payload.get("name")
    item = _SHOP_BY_NAME.get(name)
    if not item:
        return {"error": "That item isn't sold here."}

    price = item["price"]
    coins = getattr(player, "coins", 0)
    if coins < price:
        return {"error": f"Not enough coins. You have ₽{coins}, {name} costs ₽{price}."}

    player.coins -= price
    player.inventory[name] = player.inventory.get(name, 0) + 1
    router._save(sender, player)

    return {
        "ok": True,
        "bought": name,
        "price": price,
        "coins": player.coins,
        "inventory": player.inventory,
    }


def handle_grant_starter(router, sender, payload):
    """
    First-time trainer creation, triggered from the site's Starter
    Reveal page (the site is now the only place a fresh Player row
    gets created — WhatsApp's .start just links here, see
    registration.py's _start docstring / index.js signup route).

    Ports the exact same logic .start used to run instantly on
    WhatsApp (registration.py:_reg_finish), minus the WhatsApp
    message text — the site renders its own reveal animation
    instead of chat bubbles.

    payload: {
        "name": str,               — trainer name entered at signup
        "jid": str | None,         — optional, forward-compatible; the
        "lid": str | None,           current site route never sends these
                                      (no players row exists yet at this
                                      point to read them from), so matching
                                      today is effectively sender-only —
                                      correct since SPECIAL_FEW is itself
                                      a snapshot of phone-JID values.
    }

    If this sender (or their known jid/lid) is one of the "special
    few" (SPECIAL_FEW — everyone with a real players row before the
    pre-launch wipe), this ALSO rolls and immediately hatches one of
    the three new legacy eggs (Yuki gets her original Cryo Egg /
    Articuno instead) and grants the "One of us" achievement + the
    Genesis badge. The site's Legacy Egg Reveal page only needs to
    check `legacy` in the response to know whether to run that flow.

    Returns the same shape /api/player/me does for party/pc/
    inventory/badges, so the site can render Home immediately
    after the reveal without a second round-trip.
    """
    import random
    import datetime
    import pokeapi
    from models import Player, OwnedPokemon
    from egg import assign_legacy_egg, EGG_POKEMON_POOL, YUKI_ID

    if router._get(sender):
        return {"error": "Trainer already exists for this account."}

    name = (payload.get("name") or "Traveller").strip()[:16] or "Traveller"
    jid = payload.get("jid")
    lid = payload.get("lid")

    player = Player(name)
    player.story_stage = "has_starter"
    player.joined_at = datetime.datetime.utcnow().isoformat()
    player.zone      = "oak_town"
    player.zone_x    = 12
    player.zone_y    = 6
    player.set_flag("visited_zones", ["oak_town", "route_1", "greenwood_town"])

    elemental_ball = random.choice(ELEMENTAL_BALLS)
    player.give_item("Poké Ball",    3)
    player.give_item(elemental_ball, 1)
    player.give_item("Master Ball",  1)
    player.give_item("Potion",       4)
    player.give_item("Max Potion",   1)
    player.give_item("Full Heal",    1)
    player.coins += 300

    # One random starter per type — same pools/logic as .start.
    chosen = [
        random.choice(FIRE_STARTERS),
        random.choice(WATER_STARTERS),
        random.choice(GRASS_STARTERS),
    ]
    for species in chosen:
        try:
            data = pokeapi.get_full(router.db, species)
            if data:
                poke = OwnedPokemon(data, level=5)
                poke.is_starter = True
                player.add_to_party(poke)
                player.see_pokemon(species)
                player.catch_pokemon(species)
        except Exception:
            pass  # matches WhatsApp behaviour — a PokéAPI hiccup shouldn't block registration

    from router.quests import make_quest
    try:
        gq = make_quest("greenwood_1")
        if not hasattr(player, "quests"):
            player.quests = []
        player.quests.append(gq)
        player.set_flag("greenwood_given", True)
    except Exception:
        pass

    # ── Legacy gift, step 1 of 2 — "special few" only ─────────────
    # Only decide WHICH EGG TYPE here (Dragon/Ghoul/Fairy, or Yuki's
    # Cryo Egg). The actual species roll + hatch + badge grant is
    # deferred to handle_hatch_legacy_egg, fired live when the player
    # taps the egg on the Legacy Reveal page — so the suspense is real
    # instead of a species that was already decided (and already sitting
    # in their party) before the crack animation even plays.
    legacy_result = None
    if _is_special_few(router, sender, jid, lid):
        egg_name = assign_legacy_egg(sender)
        player.give_item(egg_name, 1)
        player.set_flag("legacy_egg_name", egg_name)
        legacy_result = {"egg_name": egg_name}

    router._save(sender, player)

    return {
        "ok": True,
        "elemental_ball": elemental_ball,
        "legacy": legacy_result,  # None for everyone except the special few
        "stats": {
            "name": player.name,
            "level": player.level,
            "coins": player.coins,
            "region": player.zone,
            "pvp_wins": player.pvp_wins,
            "pvp_losses": player.pvp_losses,
            "badges_count": len(player.badges or []),
            "pokedex_caught": len(player.pokedex_caught or []),
            "bio": player.bio,
            "rank": None,
            "guild": None,
        },
        "party": [p.to_dict() for p in player.party],
        "pc": [p.to_dict() for p in player.box],
        "inventory": player.inventory,
        "badges": player.badges or [],
    }


def handle_hatch_legacy_egg(router, sender, payload):
    """
    Legacy gift, step 2 of 2 — fired live when the "special few" player
    taps the egg on the Legacy Reveal page (see handle_grant_starter's
    docstring for why this is split from the type decision). This is
    where the actual species gets rolled, so the crack animation's
    suspense is real rather than decorative — the Pokémon genuinely
    doesn't exist yet until this call resolves.

    Guarded by the "legacy_egg_given" flag so it can only ever run
    once per player, even if the site somehow calls it twice (e.g. a
    retry after a network hiccup).
    """
    import random
    import pokeapi
    from models import OwnedPokemon
    from egg import EGG_POKEMON_POOL, YUKI_ID

    player = router._get(sender)
    if not player:
        return {"error": "No player record found."}

    if player.get_flag("legacy_egg_given"):
        return {"error": "You've already claimed your legacy gift."}

    egg_name = player.get_flag("legacy_egg_name")
    if not egg_name:
        return {"error": "No legacy egg to hatch."}

    legacy_pool = EGG_POKEMON_POOL.get(egg_name, [])
    if not legacy_pool:
        return {"error": "That egg type isn't recognized."}

    legacy_species = legacy_pool[0] if len(legacy_pool) == 1 else random.choice(legacy_pool)
    stars = 6 if (sender == YUKI_ID and egg_name == "Cryo Egg") else random.randint(4, 8)

    data = pokeapi.get_full(router.db, legacy_species)
    if not data:
        return {"error": "Couldn't reach the Pokédex right now — try again in a moment."}

    legacy_poke = OwnedPokemon(data, level=5, stars=stars)
    player.add_to_party(legacy_poke)  # handles party-vs-box overflow itself
    player.see_pokemon(legacy_species)
    player.catch_pokemon(legacy_species)

    if not hasattr(player, "badges") or player.badges is None:
        player.badges = []
    player.badges.insert(0, "Genesis")  # newest badge first, matches site's Badges tab ordering

    # Yuki-exclusive honorific — granted at the same moment as Genesis
    # (this same hatch), inserted after Genesis so it lands at index 0
    # and sits "on top of" the Genesis badge in the site's list, per
    # Kagenou's spec. Not earnable by anyone else; no criteria, just an
    # id check, same pattern as her Cryo Egg/guaranteed Articuno above.
    queen_badge_granted = False
    if sender == YUKI_ID:
        player.badges.insert(0, "Queen of Niflheim")
        queen_badge_granted = True

    # Consume the placeholder egg item granted at registration, mark
    # this as claimed so a retry can never hatch a second Pokémon.
    if player.inventory.get(egg_name, 0) > 0:
        player.inventory[egg_name] -= 1
        if player.inventory[egg_name] <= 0:
            del player.inventory[egg_name]
    player.set_flag("legacy_egg_given", True)

    router._save(sender, player)

    return {
        "ok": True,
        "egg_name": egg_name,
        "pokemon": legacy_poke.to_dict(),
        "achievement": "One of us",
        "badge": "Genesis",
        "queen_badge_granted": queen_badge_granted,
        "party": [p.to_dict() for p in player.party],
        "pc": [p.to_dict() for p in player.box],
        "inventory": player.inventory,
        "badges": player.badges or [],
    }


MAX_BOARD_QUESTS = 3  # per-player active-quest cap, same limit as WhatsApp's .accept


def handle_get_badges(router, sender, payload):
    """
    Site's badge grid — every gym's badge, tagged earned/locked for this
    player, so the UI can show the full set (locked greyed-out) instead
    of only ever rendering badges the player already has. See
    gym.all_badges_status for the actual per-gym logic; this handler
    just authenticates the sender and hands the list back.

    Unauthenticated / not-yet-registered visitors get every badge back
    as locked, same "registered": False pattern as get_quests.
    """
    from gym import all_badges_status

    player = router._get(sender) if sender else None
    if not player:
        # Build the locked-for-everyone view without a real player
        # object — reuse all_badges_status with a throwaway player-like
        # stand-in that just has an empty badges list.
        class _NoPlayer:
            badges = []
        return {"registered": False, "badges": all_badges_status(_NoPlayer())}

    return {"registered": True, "badges": all_badges_status(player)}


def handle_get_gyms(router, sender, payload):
    """
    Site's Gyms list page — GET /api/gyms. Every gym tagged Open/Locked
    for this player based on gym.meets_requirement (e.g. Hydro's
    Lv.10+ party requirement), plus the description/requirement/leader
    fields the detail panel needs. See gym.all_gyms_status for the
    per-gym logic; this handler just authenticates and hands it back.

    Unauthenticated / not-yet-registered visitors get every gym back
    as locked (no party to check against), same pattern as badges/quests.
    """
    from gym import all_gyms_status

    player = router._get(sender) if sender else None
    if not player:
        class _NoPlayer:
            badges = []
            party = []
        return {"registered": False, "gyms": all_gyms_status(_NoPlayer())}

    return {"registered": True, "gyms": all_gyms_status(player)}


def handle_get_pokedex(router, sender, payload):
    """
    Site's Pokédex — GET /api/pokedex. Every species the game has ever
    fetched (pokeapi.list_cached_species — i.e. every species that's
    actually appeared in-world via an encounter, gym/arena team, egg
    hatch, or lab starter), tagged caught/seen/unseen for this player.

    Deliberately NOT hardcoded: unseen species aren't a fixed list
    anywhere — they're just "everything in pokemon_cache minus what
    this player has personally seen/caught", recomputed live each call.
    A brand-new player's "seen" set is exactly their starter(s), because
    grant_starter already calls see_pokemon/catch_pokemon like any other
    catch — nothing dex-specific is set at registration time.

    No fabricated "stars"/rarity here — that's a per-catch random roll
    (roll_stars), not a species trait, so it's omitted rather than faked.

    Unauthenticated visitors get every cached species back as unseen
    (empty seen/caught sets), same pattern as badges/gyms/quests.
    """
    import pokeapi

    player = router._get(sender) if sender else None
    seen   = getattr(player, "pokedex_seen", None) or set() if player else set()
    caught = getattr(player, "pokedex_caught", None) or set() if player else set()

    species_names = pokeapi.list_cached_species(router.db)
    out = []
    for species in species_names:
        data = pokeapi.get_full(router.db, species)
        if not data:
            continue
        name_lower = species.lower()
        if name_lower in caught:
            status = "caught"
        elif name_lower in seen:
            status = "seen"
        else:
            status = "unseen"

        entry = {
            "id":     data.get("id"),
            "name":   data.get("name", species).capitalize(),
            "type":   (data.get("types") or ["normal"])[0],
            "weight": round(data.get("weight", 0) / 10, 1),   # hectograms -> kg
            "height": round(data.get("height", 0) / 10, 1),   # decimetres -> m
            "status": status,
            "sprite": data.get("sprite", ""),
        }
        # Flavor detail is only meaningful (and only shown by the UI)
        # once a player has actually seen or caught the species — an
        # unseen entry renders as "???" regardless, so there's no reason
        # to ship genus/desc/moves for something the player hasn't met.
        if status != "unseen":
            entry["genus"] = data.get("genus", "")
            entry["desc"]  = data.get("flavor_text", "")
            entry["moves"] = " · ".join(
                m.replace("-", " ").title() for m in data.get("default_moves", [])
            )
        out.append(entry)

    return {"registered": bool(player), "pokedex": out}


def handle_get_zones(router, sender, payload):
    """
    Site's world map — GET /api/zones (Phase 7, Section 13). Three-tier
    zone visibility, mirroring handle_get_pokedex's seen/unseen pattern
    but with a key structural difference: Pokédex "seen" is per-player,
    zone "discovered" is GLOBAL (confirmed this session) — one player
    finding a zone flips it to tier 2 for every viewer, not just them.

    Tier 1 (undiscovered) — no player has ever reached this zone via
        .explore. Fully blacked out; only the zone_id is returned so
        the site can render a silhouette, no name/type/anything real.
    Tier 2 (discovered, not personally visited) — zone_discovery has
        a row for it (someone found it), but not this viewer. Basic
        details only: name, type, danger tier.
    Tier 3 (personally visited) — this viewer has actually arrived
        there via .explore (player.discovered_connections has it as
        a destination somewhere). Full details: description, actions,
        poke_center/gyms/etc.

    Deliberately NOT hardcoded against a fixed zone list beyond
    ZONE_INFO — same reasoning as pokedex's cache-driven list, this
    reflects whatever zones actually exist in explore.ZONE_INFO.

    Unauthenticated visitors get every zone at tier 1 or 2 (whatever
    is globally discovered), never tier 3 — same "logged out = no
    personal state" pattern as badges/gyms/pokedex.
    """
    from .explore import ZONE_INFO

    player = router._get(sender) if sender else None

    # Personally-visited set: every destination this player has ever
    # reached, across all zones+directions in discovered_connections.
    personally_visited = set()
    if player:
        for zone_map in (player.discovered_connections or {}).values():
            for dest_list in zone_map.values():
                personally_visited.update(dest_list)
        # The player's own current/starting zone counts as visited too.
        if player.zone:
            personally_visited.add(player.zone)

    out = []
    for zone_id, info in ZONE_INFO.items():
        globally_discovered = router.db.is_zone_discovered(zone_id)
        # Oak Town is the game's starting zone — always visible,
        # never blacked out, regardless of the discovery table.
        if zone_id == "oak_town":
            globally_discovered = True

        if zone_id in personally_visited or zone_id == "oak_town":
            tier = 3
        elif globally_discovered:
            tier = 2
        else:
            tier = 1

        if tier == 1:
            out.append({"zone_id": zone_id, "tier": 1})
            continue

        entry = {
            "zone_id":     zone_id,
            "tier":        tier,
            "name":        info.get("name", zone_id),
            "status":      info.get("status", "Unknown"),
            "danger_tier": info.get("danger_tier", 0),
        }
        if tier == 3:
            entry["description"] = info.get("description", "")
            entry["actions"]     = info.get("actions", [])
            if info.get("status") in ("Town", "City"):
                entry["poke_center"] = bool(info.get("poke_center"))
                entry["gyms"]        = info.get("gyms", "None")
                entry["arenas"]      = info.get("arenas", "None")
                entry["dungeons"]    = info.get("dungeons", "None")
                if info.get("specialty"):
                    entry["specialty"] = info["specialty"]
        out.append(entry)

    return {"registered": bool(player), "zones": out}


def handle_get_quests(router, sender, payload):
    """
    Site's Quests page — GET /api/quests. Ensures the global board is
    fresh (regenerates if >30 min stale, see quests.ensure_global_board),
    then returns both the public board and this sender's own quests
    split into story vs board, matching the site's two-tab layout.

    Unauthenticated site visitors can still call this (sender may not
    have a player row) — they just get "registered": False and an
    empty "mine" section, same shape as /api/player/me.
    """
    from router.quests import ensure_global_board

    ensure_global_board(router.db)
    board_rows = router.db.quest_board_all()
    board = [
        {
            "id": r["id"], "rank": r["rank"], "title": r["title"],
            "type": r["type"], "target": r["target"], "required": r["required"],
            "progress": 0, "reward": r["reward"], "penalty": r["penalty"],
            "claimed": r["claimed_by"] is not None,
            "claimed_by_me": r["claimed_by"] == sender,
        }
        for r in board_rows
    ]

    player = router._get(sender) if sender else None
    if not player:
        return {"board": board, "mine": {"registered": False, "story": [], "board": []}}

    story = [q.to_dict() for q in getattr(player, "quests", [])
             if getattr(q, "source", "board") != "board"]
    mine_board = [q.to_dict() for q in getattr(player, "quests", [])
                  if getattr(q, "source", "board") == "board"]

    return {
        "board": board,
        "mine": {"registered": True, "story": story, "board": mine_board},
    }


def handle_accept_quest(router, sender, payload):
    """
    Site's Accept button. Claims a quest_board row for this sender
    (atomically — see database.py:quest_board_claim, which only
    succeeds if nobody else claimed it first) and adds a matching
    Quest object to the player's own quest list, source="board".

    payload: { "quest_id": str }
    """
    import datetime
    from models import Quest

    player = router._get(sender)
    if not player:
        return {"error": "No player record found."}

    quest_id = payload.get("quest_id")
    if not quest_id:
        return {"error": '"quest_id" is required.'}

    active_board_count = sum(
        1 for q in getattr(player, "quests", [])
        if getattr(q, "source", "board") == "board" and getattr(q, "status", "active") == "active"
    )
    if active_board_count >= MAX_BOARD_QUESTS:
        return {"error": f"You already have {MAX_BOARD_QUESTS} board quests active. Complete or return one first."}

    row = router.db.quest_board_get(quest_id)
    if not row:
        return {"error": "That quest is no longer on the board."}
    if row["claimed_by"] is not None:
        return {"error": "This quest has already been claimed."}

    now_iso = datetime.datetime.utcnow().isoformat()
    won = router.db.quest_board_claim(quest_id, sender, now_iso)
    if not won:
        # Someone else's claim landed first between the read above and here.
        return {"error": "This quest has already been claimed."}

    q = Quest(row["id"], row["title"], "")
    q.type        = row["type"]
    q.target      = row["target"]
    q.required    = row["required"]
    q.reward      = row["reward"]
    q.penalty     = row["penalty"]
    q.rank        = row["rank"]
    q.source      = "board"
    q.accepted    = True
    q.accepted_at = now_iso

    if not hasattr(player, "quests") or player.quests is None:
        player.quests = []
    player.quests.append(q)
    router._save(sender, player)

    return {"ok": True, "quest": q.to_dict()}


def handle_decline_quest(router, sender, payload):
    """
    Site's Decline button (also used to "return" an already-accepted
    quest, per Justice: "you can decline by removing it as well").
    Releases the global claim so the quest reappears on the board for
    others, and removes the matching Quest object from this player's
    own list if present.

    payload: { "quest_id": str }
    """
    player = router._get(sender)
    if not player:
        return {"error": "No player record found."}

    quest_id = payload.get("quest_id")
    if not quest_id:
        return {"error": '"quest_id" is required.'}

    # Story quests can't be rejected or removed — the site's UI already
    # hides the Decline button for them (pane === 'story'), but guard it
    # here too since this endpoint doesn't otherwise know which tab the
    # request came from.
    existing = player.get_quest(quest_id) if hasattr(player, "get_quest") else None
    if existing and getattr(existing, "source", "board") == "story":
        return {"error": "Story quests cannot be declined."}

    router.db.quest_board_release(quest_id, sender)

    if hasattr(player, "quests") and player.quests:
        player.quests = [q for q in player.quests if getattr(q, "id", None) != quest_id]
        router._save(sender, player)

    return {"ok": True}



# ── Niflheim Battle Arena (Session 2) ──
def handle_nif_me(router, sender, payload):
    from niflheim import arena
    return arena.me(router.db, sender)


def handle_nif_ticket(router, sender, payload):
    from niflheim import arena
    t, e = arena.create_ticket(router.db, sender, payload.get("monsterId"))
    return {"error": e} if e else t


def handle_nif_ticket_get(router, sender, payload):
    from niflheim import arena
    return arena.get_ticket(router.db, sender, payload.get("ticket"))


def handle_nif_result(router, sender, payload):
    from niflheim import arena
    return arena.submit_result(router.db, sender, payload.get("ticket"), payload, router=router)
