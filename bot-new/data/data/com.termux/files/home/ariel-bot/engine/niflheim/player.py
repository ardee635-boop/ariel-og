# Niflheim player: creation, XP, levelling, coins. The player is a plain dict (stored as JSON).
import re
import time

from . import config as cfg
from . import items as I
from . import store


def new_player(name):
    s = cfg.get("start", {})
    hp = int(s.get("hp", 200))
    return {
        "name": name,
        "level": int(s.get("level", 1)),
        "xp": int(s.get("xp", 0)),
        "hp": hp,
        "max_hp": hp,          # base Max HP (before gear): start + level-up gains
        "coins": int(s.get("coins", 0)),
        "location": s.get("location", "ash_town"),
        "discovered": [s.get("location", "ash_town")],   # per-player map: locations reached
        "inventory": {},
        "equipped": {"weapon": None, "armour": None, "accessory": None},
        "duel_wins": 0,
        "duel_losses": 0,
        "created_at": int(time.time()),
    }


def normalize(player):
    """Fill fields added after a player was registered (players from Package 1.2 lack 'discovered')."""
    start = cfg.get("start", {}).get("location", "ash_town")
    d = player.setdefault("discovered", [start])
    if player.get("location") and player["location"] not in d:
        d.append(player["location"])
    player.setdefault("inventory", {})
    return player


def validate_name(name):
    """Returns (ok, cleaned_name_or_error_message)."""
    r = cfg.get("registration", {})
    lo, hi = int(r.get("name_min", 2)), int(r.get("name_max", 20))
    name = re.sub(r"\s+", " ", (name or "").strip())
    if not (lo <= len(name) <= hi):
        return False, f"Name must be {lo}–{hi} characters."
    if not re.fullmatch(r"[\w \-]+", name, flags=re.UNICODE):
        return False, "Use only letters, numbers, spaces, - and _ in your name."
    return True, name


def xp_needed(level):
    """XP needed to go from `level` to `level + 1` (DEFAULT: 100 × level^1.5, rounded; from config)."""
    c = cfg.get("xp_curve", {})
    return int(round(float(c.get("base", 100)) * (level ** float(c.get("exponent", 1.5)))))


def grant_coins(player, amount):
    amount = int(amount)
    player["coins"] = max(0, player["coins"] + amount)
    return player["coins"]


def grant_xp(player, amount):
    """Add XP, then check levels in a loop (excess carries over). Mutates `player`.
    Returns a list of level-up messages, one per level gained, in order. The caller sends
    each as its own WhatsApp message (router._send_to / outbox) and saves the player."""
    lu = cfg.get("level_up", {})
    hp_gain = int(lu.get("max_hp", 100))
    coin_gain = int(lu.get("coins", 500))
    heal = bool(lu.get("heal_by_hp_gained", True))
    messages = []
    player["xp"] += max(0, int(amount))
    while player["xp"] >= xp_needed(player["level"]):
        player["xp"] -= xp_needed(player["level"])
        player["level"] += 1
        player["max_hp"] += hp_gain
        if heal:
            player["hp"] = min(I.final_max_hp(player), player["hp"] + hp_gain)
        grant_coins(player, coin_gain)
        messages.append(
            f"🎉 *LEVEL UP!* {player['name']} reached *Level {player['level']}*\n"
            f"┣ ❤️ +{hp_gain} Max HP (now {I.final_max_hp(player)})\n"
            f"┗ 🪙 +{coin_gain} coins"
        )
    return messages


def location_name(loc_id):
    """Display name for a location id. Reads locations.json once it exists (Package 1.3)."""
    try:
        import json, os
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "locations.json")
        if os.path.exists(p):
            data = json.load(open(p, encoding="utf-8"))
            items = data.get("locations", data) if isinstance(data, dict) else data
            for loc in (items.values() if isinstance(items, dict) else items):
                if isinstance(loc, dict) and loc.get("id") == loc_id:
                    return loc.get("name", loc_id)
    except Exception:
        pass
    s = cfg.get("start", {})
    if loc_id == s.get("location"):
        return s.get("location_name", loc_id)
    return str(loc_id).replace("_", " ").title()


def profile_text(player):
    need = xp_needed(player["level"])
    eq = player.get("equipped", {})
    def slot(k): return eq.get(k) or "—"
    return (
        "❄️ *NIFLHEIM PROFILE* ❄️\n"
        f"┣ 👤 Name: {player['name']}\n"
        f"┣ ⭐ Level: {player['level']}\n"
        f"┣ ✨ XP: {player['xp']}/{need}\n"
        f"┣ ❤️ HP: {player['hp']}/{I.final_max_hp(player)}\n"
        f"┣ 🪙 Coins: {player['coins']}\n"
        f"┣ 📍 Location: {location_name(player['location'])}\n"
        f"┣ ⚔️ Weapon: {slot('weapon')}\n"
        f"┣ 🛡️ Armour: {slot('armour')}\n"
        f"┣ 💍 Accessory: {slot('accessory')}\n"
        f"┗ 🏆 Duels: {player.get('duel_wins', 0)}W / {player.get('duel_losses', 0)}L"
    )
