# ============================================================
# NIFLHEIM – DATA_ITEMS.PY
# Item definitions, catch mechanics, held item effects
# Full Pokémon item list loaded from items.json
# ============================================================

import json
import os
import random

# ── Load full item list from items.json ───────────────────────
_ITEMS_FILE = os.path.join(__import__("paths").ROOT, "items.json")
_ITEM_LOOKUP: dict = {}

def _load_items():
    global _ITEM_LOOKUP
    if _ITEM_LOOKUP:
        return
    try:
        with open(_ITEMS_FILE, "r", encoding="utf-8") as f:
            items = json.load(f)
        _ITEM_LOOKUP = {i["name"].lower(): i for i in items}
    except Exception as e:
        print(f"[ITEMS] Failed to load items.json: {e}")

_load_items()

def get_item(name: str) -> dict | None:
    """Look up an item by name (case-insensitive)."""
    return _ITEM_LOOKUP.get(name.lower())

def item_description(name: str) -> str:
    item = get_item(name)
    if not item:
        return f"_{name} — no data found._"
    desc = item.get("description", "")
    return f"*{item['name']}*\n_{desc}_" if desc else f"*{item['name']}*"


# ── Item categories ───────────────────────────────────────────

# Poké Balls — catch rate multipliers
POKEBALLS = {
    "Poké Ball":    1.0,
    "Great Ball":   1.5,
    "Ultra Ball":   2.0,
    "Master Ball":  255.0,   # guaranteed catch
    "Net Ball":     3.0,     # vs Water/Bug
    "Dusk Ball":    3.5,     # at night or in caves
    "Quick Ball":   5.0,     # first turn only
    "Timer Ball":   1.0,     # scales with turns (handled in catch logic)
    "Nest Ball":    1.0,     # scales with Pokémon level (handled in catch logic)
    "Heal Ball":    1.0,     # standard catch rate, heals on catch
    "Repeat Ball":  3.0,     # vs already caught species
    "Dive Ball":    3.5,     # on water tiles
    "Love Ball":    8.0,     # opposite gender
    "Level Ball":   1.0,     # scales with level difference
    "Fast Ball":    4.0,     # vs fast Pokémon (speed ≥ 100)
    "Friend Ball":  1.0,     # standard, sets high friendship
    "Moon Ball":    4.0,     # vs Moon Stone evolutions
    "Dream Ball":   4.0,     # vs sleeping Pokémon
    "Beast Ball":   0.1,     # bad vs non-Ultra Beasts
    "Safari Ball":  1.5,
    "Sport Ball":   1.5,
    "Premier Ball": 1.0,
    "Cherish Ball": 1.0,
    "Park Ball":    255.0,
}

# Healing items — {item_name: {effect, value}}
HEALING_ITEMS = {
    "Potion":          {"effect": "hp",     "value": 20},
    "Super Potion":    {"effect": "hp",     "value": 60},
    "Hyper Potion":    {"effect": "hp",     "value": 120},
    "Max Potion":      {"effect": "hp_full","value": 0},
    "Full Restore":    {"effect": "full",   "value": 0},
    "Revive":          {"effect": "revive", "value": 0.5},    # revive at 50% HP
    "Max Revive":      {"effect": "revive", "value": 1.0},    # revive at full HP
    "Fresh Water":     {"effect": "hp",     "value": 30},
    "Soda Pop":        {"effect": "hp",     "value": 50},
    "Lemonade":        {"effect": "hp",     "value": 80},
    "Moomoo Milk":     {"effect": "hp",     "value": 100},
    "Energy Root":     {"effect": "hp",     "value": 200},
    "Berry Juice":     {"effect": "hp",     "value": 20},
    "Oran Berry":      {"effect": "hp",     "value": 10},
    "Sitrus Berry":    {"effect": "hp_pct", "value": 0.25},   # 25% max HP
    "Lum Berry":       {"effect": "cure_all","value": 0},
    "Antidote":        {"effect": "cure",   "value": "poison"},
    "Burn Heal":       {"effect": "cure",   "value": "burn"},
    "Ice Heal":        {"effect": "cure",   "value": "freeze"},
    "Awakening":       {"effect": "cure",   "value": "sleep"},
    "Paralyze Heal":   {"effect": "cure",   "value": "paralysis"},
    "Full Heal":       {"effect": "cure_all","value": 0},
    "Pecha Berry":     {"effect": "cure",   "value": "poison"},
    "Cheri Berry":     {"effect": "cure",   "value": "paralysis"},
    "Chesto Berry":    {"effect": "cure",   "value": "sleep"},
    "Rawst Berry":     {"effect": "cure",   "value": "burn"},
    "Aspear Berry":    {"effect": "cure",   "value": "freeze"},
}

# PP restore items
PP_ITEMS = {
    "Ether":     {"effect": "pp",      "value": 10},
    "Max Ether": {"effect": "pp_full", "value": 0},
    "Elixir":    {"effect": "pp_all",  "value": 10},
    "Max Elixir":{"effect": "pp_all_full","value": 0},
    "Leppa Berry":{"effect": "pp",     "value": 10},
}

# Experience stones — Niflheim-original consumables that grant trainer XP
# directly to a Pokémon. Not yet consumable in-game (no .use command exists
# yet — see egg.py header note); this is the data layer so rewards/shop can
# reference these items now and the .use command can read from here later.
EXPERIENCE_STONES = {
    "Small Experience Stone": {"effect": "xp",         "value": 50},
    "Mid Experience Stone":   {"effect": "xp",         "value": 100},
    "Big Experience Stone":   {"effect": "xp_levels",  "value": 1},
    "Large Experience Stone": {"effect": "xp_levels",  "value": 5},
    "Great Experience Stone": {"effect": "xp_levels",  "value": 10},
}

# Evolution stones
EVOLUTION_STONES = {
    "Fire Stone", "Water Stone", "Thunder Stone", "Leaf Stone",
    "Moon Stone", "Sun Stone", "Shiny Stone", "Dusk Stone",
    "Dawn Stone", "Ice Stone", "Oval Stone",
}

# Battle held items — simplified effect tags for combat resolver
HELD_ITEM_EFFECTS = {
    "Leftovers":       {"trigger": "end_turn",  "effect": "heal_pct",    "value": 0.0625},
    "Black Sludge":    {"trigger": "end_turn",  "effect": "heal_pct",    "value": 0.0625,  "type_req": "poison"},
    "Shell Bell":      {"trigger": "on_attack", "effect": "drain",       "value": 0.125},
    "Life Orb":        {"trigger": "on_attack", "effect": "power_boost", "value": 1.3,     "recoil": 0.1},
    "Choice Band":     {"trigger": "passive",   "effect": "atk_boost",   "value": 1.5,     "lock_move": True},
    "Choice Specs":    {"trigger": "passive",   "effect": "spatk_boost", "value": 1.5,     "lock_move": True},
    "Choice Scarf":    {"trigger": "passive",   "effect": "spd_boost",   "value": 1.5,     "lock_move": True},
    "Eviolite":        {"trigger": "passive",   "effect": "def_boost",   "value": 1.5,     "req": "can_evolve"},
    "Rocky Helmet":    {"trigger": "on_hit",    "effect": "contact_dmg", "value": 0.1667},
    "Focus Sash":      {"trigger": "on_ko",     "effect": "survive_1hp", "value": 1,       "single_use": True},
    "Assault Vest":    {"trigger": "passive",   "effect": "spdef_boost", "value": 1.5,     "no_status_moves": True},
    "Sitrus Berry":    {"trigger": "hp_below",  "effect": "heal_pct",    "value": 0.25,    "threshold": 0.5, "single_use": True},
    "Oran Berry":      {"trigger": "hp_below",  "effect": "heal_flat",   "value": 10,      "threshold": 0.5, "single_use": True},
    "Lum Berry":       {"trigger": "on_status", "effect": "cure_all",    "value": 0,       "single_use": True},
    "Lax Incense":     {"trigger": "passive",   "effect": "accuracy_down","value": 0.9},
    "Bright Powder":   {"trigger": "passive",   "effect": "accuracy_down","value": 0.9},
    "Wide Lens":       {"trigger": "passive",   "effect": "accuracy_up", "value": 1.1},
    "Scope Lens":      {"trigger": "passive",   "effect": "crit_up",     "value": 1},
    "Razor Claw":      {"trigger": "passive",   "effect": "crit_up",     "value": 1},
    "Muscle Band":     {"trigger": "passive",   "effect": "phys_boost",  "value": 1.1},
    "Wise Glasses":    {"trigger": "passive",   "effect": "spec_boost",  "value": 1.1},
    "Expert Belt":     {"trigger": "on_super",  "effect": "power_boost", "value": 1.2},
    "Charcoal":        {"trigger": "passive",   "effect": "type_boost",  "value": 1.2,     "type": "fire"},
    "Mystic Water":    {"trigger": "passive",   "effect": "type_boost",  "value": 1.2,     "type": "water"},
    "Magnet":          {"trigger": "passive",   "effect": "type_boost",  "value": 1.2,     "type": "electric"},
    "Miracle Seed":    {"trigger": "passive",   "effect": "type_boost",  "value": 1.2,     "type": "grass"},
    "Never-Melt Ice":  {"trigger": "passive",   "effect": "type_boost",  "value": 1.2,     "type": "ice"},
    "Black Belt":      {"trigger": "passive",   "effect": "type_boost",  "value": 1.2,     "type": "fighting"},
    "Poison Barb":     {"trigger": "passive",   "effect": "type_boost",  "value": 1.2,     "type": "poison"},
    "Soft Sand":       {"trigger": "passive",   "effect": "type_boost",  "value": 1.2,     "type": "ground"},
    "Sharp Beak":      {"trigger": "passive",   "effect": "type_boost",  "value": 1.2,     "type": "flying"},
    "Twisted Spoon":   {"trigger": "passive",   "effect": "type_boost",  "value": 1.2,     "type": "psychic"},
    "Silver Powder":   {"trigger": "passive",   "effect": "type_boost",  "value": 1.2,     "type": "bug"},
    "Hard Stone":      {"trigger": "passive",   "effect": "type_boost",  "value": 1.2,     "type": "rock"},
    "Spell Tag":       {"trigger": "passive",   "effect": "type_boost",  "value": 1.2,     "type": "ghost"},
    "Metal Coat":      {"trigger": "passive",   "effect": "type_boost",  "value": 1.2,     "type": "steel"},
    "Dragon Fang":     {"trigger": "passive",   "effect": "type_boost",  "value": 1.2,     "type": "dragon"},
    "Black Glasses":   {"trigger": "passive",   "effect": "type_boost",  "value": 1.2,     "type": "dark"},
    "Fairy Feather":   {"trigger": "passive",   "effect": "type_boost",  "value": 1.2,     "type": "fairy"},
}


# ── Catch mechanics ───────────────────────────────────────────

def catch_rate(
    pokemon_catch_rate: int,
    pokemon_hp: int,
    pokemon_max_hp: int,
    ball_name: str,
    status: str | None = None,
    turn: int = 1,
    zone_id: str = "",
    already_caught: bool = False,
) -> tuple[bool, int]:
    """
    Calculate catch success.
    Returns (caught: bool, shake_count: int 0-3).
    Based on Gen 3+ formula.
    """
    ball_mult = POKEBALLS.get(ball_name, 1.0)

    # Special ball conditions
    if ball_name == "Timer Ball":
        ball_mult = min(4.0, 1.0 + (turn * 0.3))
    elif ball_name == "Nest Ball":
        # Better for lower level Pokémon (approximate)
        ball_mult = max(1.0, 4.0 - (pokemon_max_hp / 20))
    elif ball_name == "Quick Ball" and turn > 1:
        ball_mult = 1.0
    elif ball_name == "Repeat Ball" and already_caught:
        ball_mult = 3.0
    elif ball_name == "Dusk Ball" and "cave" in zone_id:
        ball_mult = 3.5
    elif ball_name == "Dream Ball" and status == "sleep":
        ball_mult = 4.0

    # Status multiplier
    status_mult = 1.0
    if status in ("sleep", "freeze"):
        status_mult = 2.5
    elif status in ("paralysis", "poison", "burn"):
        status_mult = 1.5

    # HP ratio — lower HP = higher catch chance
    hp_ratio = pokemon_hp / pokemon_max_hp if pokemon_max_hp > 0 else 1.0
    hp_factor = (3 - 2 * hp_ratio) / 3

    # Modified catch rate (Gen 3+ formula approximation)
    modified = int((pokemon_catch_rate * ball_mult * hp_factor * status_mult))
    modified = max(1, min(255, modified))

    # Master Ball — instant catch
    if ball_name == "Master Ball" or ball_name == "Park Ball":
        return True, 3

    # Shake probability (0-255 scale)
    shake_prob = int(65536 / ((255 / modified) ** 0.1875))

    shakes = 0
    caught = True
    for _ in range(4):
        if random.randint(0, 65535) < shake_prob:
            shakes += 1
        else:
            caught = False
            break

    return caught, min(shakes, 3)


def catch_message(caught: bool, shakes: int, pokemon_name: str, ball_name: str) -> str:
    """Generate catch result message."""
    shake_text = {
        0: "The Pokémon broke free immediately!",
        1: "Almost had it!",
        2: "Aargh! So close!",
        3: "Oh no! It broke free at the last moment!",
    }
    if caught:
        return f"*{pokemon_name}* was caught! 🎉\n_Gotcha! {pokemon_name} was added to your party!_"
    return f"*{shake_text.get(shakes, 'It got away!')}*"


# ── Item use in battle ────────────────────────────────────────

def use_healing_item(item_name: str, pokemon) -> str:
    """
    Apply a healing item to an OwnedPokemon.
    Returns result message.
    """
    effect = HEALING_ITEMS.get(item_name)
    if not effect:
        return f"_{item_name} can't be used here._"

    e = effect["effect"]

    if e == "hp":
        healed = pokemon.heal(effect["value"])
        return f"🧪 *{item_name}!*\n{pokemon.nickname} recovered {healed} HP!"

    if e == "hp_pct":
        healed = pokemon.heal(int(pokemon.max_hp * effect["value"]))
        return f"🧪 *{item_name}!*\n{pokemon.nickname} recovered {healed} HP!"

    if e == "hp_full":
        healed = pokemon.heal(pokemon.max_hp)
        return f"🧪 *{item_name}!*\n{pokemon.nickname} was fully restored!"

    if e == "full":
        healed = pokemon.heal(pokemon.max_hp)
        pokemon.status = None
        return f"🧪 *{item_name}!*\n{pokemon.nickname} was fully restored!"

    if e == "revive":
        if not pokemon.is_fainted():
            return f"_{pokemon.nickname} doesn't need a Revive._"
        pokemon.hp = int(pokemon.max_hp * effect["value"])
        pokemon.status = None
        return f"🧪 *{item_name}!*\n{pokemon.nickname} was revived!"

    if e == "cure":
        if pokemon.status == effect["value"]:
            pokemon.status = None
            return f"🧪 *{item_name}!*\n{pokemon.nickname}'s {effect['value']} was cured!"
        return f"_{pokemon.nickname} isn't {effect['value']}._"

    if e == "cure_all":
        pokemon.status = None
        return f"🧪 *{item_name}!*\n{pokemon.nickname} was cured of all status conditions!"

    return f"_{item_name} had no effect._"


# ── Starter pack ──────────────────────────────────────────────

STARTER_INVENTORY = {
    "Poké Ball":   5,
    "Potion":      3,
    "Antidote":    1,
}

# ── Shop stock (Oak Town Pokémart — unlocked after getting starter) ──
# city_only items are absent from a Town's shop entirely (not just priced
# higher) — per the Town/City split: Town sells only the plain Poké Ball,
# no other balls, no Essence, no Fishing Rod. City sells the full catalog.
OAK_TOWN_SHOP = [
    {"name": "Potion",        "price": 50,   "category": "heal"},
    {"name": "Super Potion",  "price": 75,   "category": "heal"},
    {"name": "Breadcrumbs",   "price": 50,   "category": "field"},
    {"name": "Fishing Rod",   "price": 600,  "category": "field", "city_only": True},
    {"name": "Ice Heal",      "price": 100,  "category": "status"},
    {"name": "Paralyze Heal", "price": 100,  "category": "status"},
    {"name": "Antidote",      "price": 150,  "category": "status"},
    {"name": "Poké Ball",     "price": 200,  "category": "ball"},
    {"name": "Awakening",     "price": 200,  "category": "status"},
    {"name": "Hyper Potion",  "price": 200,  "category": "heal"},
    {"name": "Pyro Ball",     "price": 250,  "category": "ball", "city_only": True},
    {"name": "Cryo Ball",     "price": 250,  "category": "ball", "city_only": True},
    {"name": "Atmo Ball",     "price": 250,  "category": "ball", "city_only": True},
    {"name": "Floro Ball",    "price": 250,  "category": "ball", "city_only": True},
    {"name": "Volt Ball",     "price": 250,  "category": "ball", "city_only": True},
    {"name": "Aether Ball",   "price": 250,  "category": "ball", "city_only": True},
    {"name": "Aqua Ball",     "price": 250,  "category": "ball", "city_only": True},
    {"name": "Brawn Ball",    "price": 250,  "category": "ball", "city_only": True},
    {"name": "Toxic Ball",    "price": 250,  "category": "ball", "city_only": True},
    {"name": "Terra Ball",    "price": 250,  "category": "ball", "city_only": True},
    {"name": "Psy Ball",      "price": 250,  "category": "ball", "city_only": True},
    {"name": "Swarm Ball",    "price": 250,  "category": "ball", "city_only": True},
    {"name": "Crag Ball",     "price": 250,  "category": "ball", "city_only": True},
    {"name": "Phantom Ball",  "price": 250,  "category": "ball", "city_only": True},
    {"name": "Wyrm Ball",     "price": 250,  "category": "ball", "city_only": True},
    {"name": "Umbra Ball",    "price": 250,  "category": "ball", "city_only": True},
    {"name": "Alloy Ball",    "price": 250,  "category": "ball", "city_only": True},
    {"name": "Fae Ball",      "price": 250,  "category": "ball", "city_only": True},
    {"name": "Random Ball",   "price": 200,  "category": "ball", "city_only": True},
    {"name": "Max Potion",    "price": 400,  "category": "heal"},
    {"name": "Full Heal",     "price": 400,  "category": "status"},
    {"name": "Essence",       "price": 500,  "category": "evolution", "city_only": True},
    {"name": "Great Ball",    "price": 500,  "category": "ball", "city_only": True},
    {"name": "Ultra Ball",    "price": 700,  "category": "ball", "city_only": True},
    {"name": "Master Ball",   "price": 1000, "category": "ball", "city_only": True},
    {"name": "Random Poké Egg", "price": 1000, "category": "egg"},
]

# Price multipliers by context
# "ps"   = Pokémart / Pokéshop in a town — base price
# "town" = .shop used while in a town (no mart tile) — ~2x
# "wild" = .shop used in a wild/route zone — ~3-4x
SHOP_MULTIPLIERS = {
    "ps":   1.0,
    "town": 2.0,
    "wild": 3.5,
}


def get_shop_with_prices(context: str = "ps", tier: str = "city") -> list:
    """Return shop list with prices adjusted for context.

    tier is the zone-kind catalog filter ("town" or "city") — a Town's
    shop omits every city_only item, a City's shop carries the full
    OAK_TOWN_SHOP list. This is independent of context, which only
    controls the price multiplier (ps/town/wild).
    """
    mult = SHOP_MULTIPLIERS.get(context, 1.0)
    result = []
    for item in OAK_TOWN_SHOP:
        if tier == "town" and item.get("city_only"):
            continue
        result.append({**item, "price": int(item["price"] * mult)})
    return result



# Field item effects
FIELD_ITEMS = {
    "Breadcrumbs": {"effect": "recall_town"},
}


def shop_display(shop: list, title: str = "𝙿𝙾𝙺É𝙼𝙰𝚁𝚃") -> str:
    """Format a shop's stock for display."""
    lines = [f"╭━━❰ ⌖ {title} ⌖ ❱━━╮"]
    for i, item in enumerate(shop, 1):
        lines.append(f"┃ {i}. *{item['name']}* — ₽{item['price']}")
    lines.append("╰━━━━━━━━━━━━━━━━━╯")
    lines.append("_Type the number to buy_")
    return "\n".join(lines)


# ── Item images ──────────────────────────────────────────────
# One URL per item, used identically by the bot (sendImage on WhatsApp)
# and the website (<img src>). Standard Pokémon items point at PokéAPI's
# public sprite mirror; Niflheim-original items point at our own hosted
# assets (served from the ariel-og Vercel deployment).
#
# NOTE: replace _SITE_ITEM_BASE below with the real deployed asset base
# once the /assets/items/ folder is pushed to ariel-og. Until then these
# 8 original-item URLs won't resolve — swap in your actual Vercel domain.

_POKEAPI_ITEM_BASE = "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/items"
_SITE_ITEM_BASE = "/assets/items"  # relative path — works on whatever domain the site is actually deployed at

ITEM_IMAGES = {
    # ── Standard Pokémon items → PokéAPI sprite mirror ──
    "Potion":          f"{_POKEAPI_ITEM_BASE}/potion.png",
    "Super Potion":    f"{_POKEAPI_ITEM_BASE}/super-potion.png",
    "Hyper Potion":    f"{_POKEAPI_ITEM_BASE}/hyper-potion.png",
    "Max Potion":      f"{_POKEAPI_ITEM_BASE}/max-potion.png",
    "Full Restore":    f"{_POKEAPI_ITEM_BASE}/full-restore.png",
    "Revive":          f"{_POKEAPI_ITEM_BASE}/revive.png",
    "Max Revive":      f"{_POKEAPI_ITEM_BASE}/max-revive.png",
    "Fresh Water":     f"{_POKEAPI_ITEM_BASE}/fresh-water.png",
    "Soda Pop":        f"{_POKEAPI_ITEM_BASE}/soda-pop.png",
    "Ice Heal":        f"{_POKEAPI_ITEM_BASE}/ice-heal.png",
    "Paralyze Heal":   f"{_POKEAPI_ITEM_BASE}/paralyze-heal.png",
    "Antidote":        f"{_POKEAPI_ITEM_BASE}/antidote.png",
    "Awakening":       f"{_POKEAPI_ITEM_BASE}/awakening.png",
    "Full Heal":       f"{_POKEAPI_ITEM_BASE}/full-heal.png",
    "Poké Ball":       f"{_POKEAPI_ITEM_BASE}/poke-ball.png",
    "Great Ball":      f"{_POKEAPI_ITEM_BASE}/great-ball.png",
    "Ultra Ball":      f"{_POKEAPI_ITEM_BASE}/ultra-ball.png",
    "Master Ball":     f"{_POKEAPI_ITEM_BASE}/master-ball.png",

    # ── Niflheim-original items → our own hosted art ──
    "Pyro Ball":         f"{_SITE_ITEM_BASE}/fire_ball.png",
    "Cryo Ball":         f"{_SITE_ITEM_BASE}/ice_ball.png",
    "Atmo Ball":         f"{_SITE_ITEM_BASE}/flying_ball.png",
    "Floro Ball":        f"{_SITE_ITEM_BASE}/grass_ball.png",
    "Volt Ball":         f"{_SITE_ITEM_BASE}/electric_ball.png",
    "Aether Ball":       f"{_SITE_ITEM_BASE}/normal_ball.png",
    "Aqua Ball":         f"{_SITE_ITEM_BASE}/water_ball.png",
    "Brawn Ball":        f"{_SITE_ITEM_BASE}/fighting_ball.png",
    "Toxic Ball":        f"{_SITE_ITEM_BASE}/poison_ball.png",
    "Terra Ball":        f"{_SITE_ITEM_BASE}/ground_ball.png",
    "Psy Ball":          f"{_SITE_ITEM_BASE}/psychic_ball.png",
    "Swarm Ball":        f"{_SITE_ITEM_BASE}/bug_ball.png",
    "Crag Ball":         f"{_SITE_ITEM_BASE}/rock_ball.png",
    "Phantom Ball":      f"{_SITE_ITEM_BASE}/ghost_ball.png",
    "Wyrm Ball":         f"{_SITE_ITEM_BASE}/dragon_ball.png",
    "Umbra Ball":        f"{_SITE_ITEM_BASE}/dark_ball.png",
    "Alloy Ball":        f"{_SITE_ITEM_BASE}/steel_ball.png",
    "Fae Ball":          f"{_SITE_ITEM_BASE}/fairy_ball.png",
    "Random Ball":       f"{_SITE_ITEM_BASE}/random_ball.png",
    "Breadcrumbs":       f"{_SITE_ITEM_BASE}/breadcrumbs.png",
    "Essence":           f"{_SITE_ITEM_BASE}/essence.png",
    "Random Poké Egg":   f"{_SITE_ITEM_BASE}/random_poke_egg.png",
    "Small Experience Stone": f"{_SITE_ITEM_BASE}/exp_stone_small.png",
    "Mid Experience Stone":   f"{_SITE_ITEM_BASE}/exp_stone_mid.png",
    "Big Experience Stone":   f"{_SITE_ITEM_BASE}/exp_stone_big.png",
    "Large Experience Stone": f"{_SITE_ITEM_BASE}/exp_stone_large.png",
    "Great Experience Stone": f"{_SITE_ITEM_BASE}/exp_stone_great.png",
    "Random Floro Egg":       f"{_SITE_ITEM_BASE}/random_floro_egg.png",
}


def get_item_image(name: str) -> str | None:
    """Return the image URL for an item, or None if not mapped yet."""
    return ITEM_IMAGES.get(name)


def indexed_inventory(player) -> list[tuple[int, str, int]]:
    """
    Single source of truth for bag numbering. Returns
    [(number, item_name, qty), ...] in the exact same category order
    UI.inventory() displays (Poké Balls, Medicine, Battle Items, Stones,
    Eggs, then Key Items) — anything that numbers a bag slot (.inv [n],
    .sell [n], .use [n]) should read from this instead of iterating
    player.inventory directly, or its numbers will drift from what the
    player actually sees on screen.
    """
    from egg import ALL_EGGS

    categories = [
        POKEBALLS,
        {**HEALING_ITEMS, **PP_ITEMS},
        HELD_ITEM_EFFECTS,
        {**{s: None for s in EVOLUTION_STONES}, **EXPERIENCE_STONES},
    ]

    result  = []
    counter = 1
    seen    = set()

    for cat_items in categories:
        for item, qty in player.inventory.items():
            if item in cat_items and item not in seen and qty > 0:
                result.append((counter, item, qty))
                seen.add(item)
                counter += 1

    # Eggs, then everything else (Key Items) — matches UI.inventory's
    # "Key Items — anything not in any category" fallback order.
    eggs, keys = [], []
    for item, qty in player.inventory.items():
        if item not in seen and qty > 0:
            (eggs if item in ALL_EGGS else keys).append((item, qty))
            seen.add(item)

    for item, qty in eggs + keys:
        result.append((counter, item, qty))
        counter += 1

    return result


def find_indexed_item(player, n: int) -> str | None:
    """Look up the item name at bag slot n (1-indexed), or None if out
    of range. Convenience wrapper around indexed_inventory for commands
    that just need the one name, e.g. .use [n]."""
    for num, item, _qty in indexed_inventory(player):
        if num == n:
            return item
    return None
