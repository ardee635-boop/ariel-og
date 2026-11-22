# ============================================================
# NIFLHEIM — egg.py
# Egg incubation system.
#
# Flow:
#   egg enters inventory → start_incubation() called
#   → stores hatch_ready_at timestamp in player flags
#   → fires notification when ready
#   → .hatch resolves the oldest ready egg
#   → if more eggs of same type remain, auto-starts next
#
# One active incubation per egg type at a time.
# Timers re-registered on server restart via restore_timers().
# ============================================================

import random, threading, time
from interfaces import EGG_IMAGES

# ── Legacy one-time gift (the "special few" — everyone registered
#    before the pre-launch data wipe). Yuki keeps her original special
#    case; everyone else rolls one of the three new legacy eggs. This
#    replaces the old LEGACY_IDS/assign_legacy_egg system, which was
#    tied to the now-deleted Oak Lab flow and used stale/incorrectly-
#    shaped identifiers. See router/site_actions.py:SPECIAL_FEW for
#    the current sender list and matching logic.
from config import YUKI_ID  # from the YUKI_NUMBER env var

# ── Egg pools ─────────────────────────────────────────────────
LEGACY_EGG_POOL = ["Dragon Egg", "Ghoul Egg", "Fairy Egg"]

EGG_POKEMON_POOL = {
    "Floro Egg":  ["oddish", "bulbasaur", "bellsprout", "chikorita", "treecko"],
    "Atmo Egg":   ["pidgey", "spearow", "doduo", "taillow", "starly"],
    "Crust Egg":  ["sandshrew", "diglett", "cubone", "geodude", "larvitar"],
    "Cryo Egg":   ["articuno"],
    "Dragon Egg": ["dratini", "bagon", "gible", "axew", "deino"],
    "Ghoul Egg":  ["gastly", "misdreavus", "shuppet", "duskull", "drifloon"],
    "Fairy Egg":  ["clefairy", "snubbull", "togepi", "ralts", "swirlix"],
}

# Named eggs → 4–8 stars. Random egg → 3–7 stars.
NAMED_EGGS  = set(EGG_POKEMON_POOL.keys())
RANDOM_EGGS = {"Random Poké Egg", "Random Floro Egg"}
ALL_EGGS    = NAMED_EGGS | RANDOM_EGGS

# Random Floro Egg — hatches a random Nature(Grass)-type Pokémon from the
# Gen 1 (National Dex #1-151) roster, fetched live from PokéAPI rather
# than a curated pool (see pokeapi.get_gen1_species_by_type). Distinct
# from the plain "Floro Egg" above, which hatches from a small fixed pool.
FLORO_EGG_TYPE = "grass"

# Random egg hatches from a wide pool
RANDOM_EGG_POOL = [
    "bulbasaur", "charmander", "squirtle", "pikachu", "eevee",
    "meowth", "psyduck", "growlithe", "machop", "geodude",
    "slowpoke", "magnemite", "gastly", "onix", "drowzee",
    "krabby", "voltorb", "exeggcute", "cubone", "lickitung",
    "tangela", "kangaskhan", "horsea", "goldeen", "staryu",
    "jigglypuff", "clefairy", "vulpix", "oddish", "paras",
    "venonat", "diglett", "mankey", "abra", "bellsprout",
    "tentacool", "ponyta", "magikarp", "ditto", "porygon",
]

# ── Hatch duration ─────────────────────────────────────────────
HATCH_SECONDS = 300   # 5 minutes

# ── In-memory timer registry { sender: { egg_type: Timer } } ──
_timers: dict[str, dict[str, threading.Timer]] = {}


# ── Helpers ───────────────────────────────────────────────────

def _egg_type(egg_name: str) -> str:
    """Normalize egg name to type key."""
    return egg_name

def _hatch_flag(egg_name: str) -> str:
    return f"hatch_ready_at:{egg_name}"

def _incubating_flag(egg_name: str) -> str:
    return f"incubating:{egg_name}"


# ── Public API ────────────────────────────────────────────────

def start_incubation(sender: str, egg_name: str, router,
                     duration: int = HATCH_SECONDS) -> None:
    """
    Start incubating one egg of egg_name for this sender.
    No-op if already incubating this egg type.
    Stores ready timestamp in player flags.
    """
    player = router._get(sender)
    if not player:
        return

    flag_incubating = _incubating_flag(egg_name)
    if player.get_flag(flag_incubating):
        return  # already incubating this type

    ready_at = time.time() + duration
    player.set_flag(_hatch_flag(egg_name), ready_at)
    player.set_flag(flag_incubating, True)
    router.db.save(sender, player)

    _schedule_timer(sender, egg_name, ready_at, router)


def _schedule_timer(sender: str, egg_name: str, ready_at: float, router) -> None:
    """Schedule a thread timer to fire at ready_at."""
    delay = max(0, ready_at - time.time())

    def _on_ready():
        try:
            player = router._get(sender)
            if not player:
                return
            # Notify
            msg = (
                f"🥚 Your *{egg_name}* is done incubating!\n"
                f"Use *.hatch* to hatch it."
            )
            router._send_to(sender, msg)
            # Mark pending
            player.set_flag(f"hatch_pending:{egg_name}", True)
            router.db.save(sender, player)
        except Exception as e:
            import sys
            print(f"[HATCH] error: {e}", file=sys.stderr, flush=True)

    t = threading.Timer(delay, _on_ready)
    t.daemon = True
    t.start()

    if sender not in _timers:
        _timers[sender] = {}
    _timers[sender][egg_name] = t


def restore_timers(router) -> None:
    """
    Re-register timers on server restart from stored timestamps.
    Call once at startup after loading all players.
    """
    try:
        senders = router.db.all_senders()
    except Exception:
        return

    for sender in senders:
        try:
            player = router._get(sender)
            if not player:
                continue
            for egg_name in ALL_EGGS:
                ready_at = player.get_flag(_hatch_flag(egg_name))
                pending  = player.get_flag(f"hatch_pending:{egg_name}")
                if ready_at and not pending:
                    _schedule_timer(sender, egg_name, ready_at, router)
        except Exception:
            continue


def resolve_hatch(sender: str, router) -> str:
    """
    Called when player uses .hatch.
    Hatches the first ready egg, auto-starts next of same type if any remain.
    """
    player = router._get(sender)
    if not player:
        return "_No player found._"

    # Find a ready egg
    ready_egg = None
    for egg_name in ALL_EGGS:
        if player.get_flag(f"hatch_pending:{egg_name}"):
            if player.inventory.get(egg_name, 0) > 0:
                ready_egg = egg_name
                break

    if not ready_egg:
        # Check if anything is still incubating
        for egg_name in ALL_EGGS:
            if player.get_flag(_incubating_flag(egg_name)):
                ready_at = player.get_flag(_hatch_flag(egg_name)) or 0
                remaining = max(0, int(ready_at - time.time()))
                mins, secs = divmod(remaining, 60)
                return f"⏳ *{egg_name}* is still incubating — {mins}m {secs}s remaining."
        return "_You don't have any eggs ready to hatch._"

    # Pick species + stars
    if ready_egg in NAMED_EGGS:
        pool  = EGG_POKEMON_POOL.get(ready_egg, [])
        stars = 6 if (sender == YUKI_ID and ready_egg == "Cryo Egg") else random.randint(4, 8)
    elif ready_egg == "Random Floro Egg":
        from pokeapi import get_gen1_species_by_type
        pool  = get_gen1_species_by_type(router.db, FLORO_EGG_TYPE)
        stars = random.randint(3, 7)
    else:
        pool  = RANDOM_EGG_POOL
        stars = random.randint(3, 7)

    if not pool:
        return "_This egg has no Pokémon pool. Contact an admin._"

    chosen_species = random.choice(pool)

    from pokeapi import get_full
    from models import OwnedPokemon
    api_data = get_full(router.db, chosen_species)
    if not api_data:
        return "_Something went wrong hatching the egg. Try again._"

    pokemon = OwnedPokemon(api_data, stars=stars)
    player.add_to_party(pokemon)
    player.use_item(ready_egg)

    # Clear flags for this egg
    player.set_flag(_hatch_flag(ready_egg), None)
    player.set_flag(_incubating_flag(ready_egg), None)
    player.set_flag(f"hatch_pending:{ready_egg}", None)

    # Cancel timer if still alive
    if sender in _timers and ready_egg in _timers[sender]:
        try:
            _timers[sender][ready_egg].cancel()
        except Exception:
            pass
        del _timers[sender][ready_egg]

    router.db.save(sender, player)

    # Auto-start next egg of same type if player has more
    if player.inventory.get(ready_egg, 0) > 0:
        start_incubation(sender, ready_egg, router)

    star_display = "⭐" * min(stars, 7)
    return (
        f"🥚 *The {ready_egg} hatches!*\n\n"
        f"*{pokemon.nickname}* (*{pokemon.species.capitalize()}*) emerged!\n"
        f"{star_display}\n\n"
        f"_{pokemon.flavor_text if hasattr(pokemon, 'flavor_text') else ''}_"
    )


def egg_incubation_status(player) -> dict[str, str]:
    """
    Returns { egg_name: status_str } for all eggs in inventory.
    status_str is either "⏳ Xm Ys" or "✅ Ready!"
    """
    status = {}
    for egg_name in ALL_EGGS:
        if player.inventory.get(egg_name, 0) <= 0:
            continue
        if player.get_flag(f"hatch_pending:{egg_name}"):
            status[egg_name] = "✅ Ready!"
        elif player.get_flag(_incubating_flag(egg_name)):
            ready_at  = player.get_flag(_hatch_flag(egg_name)) or 0
            remaining = max(0, int(ready_at - time.time()))
            mins, secs = divmod(remaining, 60)
            status[egg_name] = f"⏳ {mins}m {secs}s"
        # else: egg in inv but not yet incubating (shouldn't happen normally)
    return status


# ── Legacy one-time gift helpers ──────────────────────────────
# Used by router/site_actions.py:handle_grant_starter for the "special
# few" — everyone registered before the pre-launch wipe. Runs once,
# from the site's Starter Reveal flow, not from WhatsApp anymore.

def assign_legacy_egg(sender: str) -> str:
    if sender == YUKI_ID:
        return "Cryo Egg"
    return random.choice(LEGACY_EGG_POOL)

def egg_receive_message(egg_name: str) -> str:
    url     = EGG_IMAGES.get(egg_name, "")
    caption = f"You have received a *{egg_name}* ◓⃙"
    if url:
        return f"__IMG__{url}__CAP__{caption}"
    return caption

