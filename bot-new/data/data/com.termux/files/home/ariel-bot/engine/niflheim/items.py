# Niflheim items and gear maths (Package 1.5). Data-driven from data/items.json.
# No imports from player/combat so both can import this module.
import json
import os

from . import config as cfg

_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
SLOTS = ("weapon", "armour", "accessory")
SLOT_ALIASES = {"weapon": "weapon", "armour": "armour", "armor": "armour", "accessory": "accessory"}
_items = None


def catalogue(reload=False):
    global _items
    if _items is None or reload:
        with open(os.path.join(_DATA_DIR, "items.json"), "r", encoding="utf-8") as f:
            _items = {i["name"]: i for i in json.load(f)["items"]}
    return _items


def get(name):
    return catalogue().get(name)


def slot_of(item):
    return item["category"] if item and item.get("category") in SLOTS else None


def find(query, names):
    """Match a typed name against candidate names. Exact (case-insensitive) first, then a unique
    substring. Returns (name, None) or (None, error_text)."""
    q = (query or "").strip().lower()
    if not q:
        return None, "Say which item."
    names = list(names)
    exact = [n for n in names if n.lower() == q]
    if exact:
        return exact[0], None
    part = [n for n in names if q in n.lower()]
    if len(part) == 1:
        return part[0], None
    if len(part) > 1:
        return None, "Which one? " + ", ".join(part)
    return None, f"No item matching \"{query.strip()}\"."


# ── gear maths (integer percent: no float rounding surprises) ─────────────

def _sum(player, key):
    total = 0
    for name in (player.get("equipped") or {}).values():
        it = get(name) if name else None
        if it:
            total += int(it.get(key, 0))
    return total


def atk_pct(player):
    return _sum(player, "atk_pct")


def hp_pct(player):
    return _sum(player, "hp_pct")


def final_max_hp(player):
    """FinalMaxHP = floor(BaseMaxHP × (1 + HP bonus)). BaseMaxHP = player['max_hp'] (200 + 100/level)."""
    return player["max_hp"] * (100 + hp_pct(player)) // 100


def final_damage(player):
    """FinalDamage = floor(BaseDamage × (1 + ATK bonus)). BaseDamage = 15 + Level × 5 (config)."""
    c = cfg.get("combat", {})
    base = int(c.get("attack_base", 15)) + player["level"] * int(c.get("attack_per_level", 5))
    return base * (100 + atk_pct(player)) // 100


def describe(item):
    bits = []
    if item.get("heal"):
        bits.append(f"restores {item['heal']} HP")
    if item.get("atk_pct"):
        bits.append(f"+{item['atk_pct']}% ATK")
    if item.get("hp_pct"):
        bits.append(f"+{item['hp_pct']}% Max HP")
    return ", ".join(bits) if bits else "sell only"


def shop_stock():
    sess = int(cfg.get("shop", {}).get("session", 1))
    return [i for i in catalogue().values() if int(i.get("buy", 0)) > 0 and int(i.get("session", 1)) <= sess]
