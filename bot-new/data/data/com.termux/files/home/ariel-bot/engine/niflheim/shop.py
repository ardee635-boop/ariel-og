# Niflheim inventory, shop and equipment commands (Package 1.5).
# Each function mutates the player dict and returns the reply text; the router saves the player.
from . import items as I


def parse_name_qty(rest):
    """'small hp potion 3' -> ('small hp potion', 3); no trailing number -> qty 1. qty < 1 -> None."""
    parts = (rest or "").split()
    qty = 1
    if len(parts) > 1 and parts[-1].isdigit():
        qty = int(parts[-1])
        parts = parts[:-1]
    return " ".join(parts), (qty if qty >= 1 else None)


def add_item(player, name, qty=1):
    inv = player.setdefault("inventory", {})
    inv[name] = inv.get(name, 0) + qty


def take_item(player, name, qty=1):
    inv = player.setdefault("inventory", {})
    inv[name] -= qty
    if inv[name] <= 0:
        del inv[name]


def inv_text(player):
    inv = player.get("inventory", {})
    eq = player.get("equipped", {})
    groups = {"Potions": [], "Equipment": [], "Materials": [], "Other": []}
    for name in sorted(inv):
        cat = (I.get(name) or {}).get("category")
        key = {"consumable": "Potions", "weapon": "Equipment", "armour": "Equipment",
               "accessory": "Equipment", "material": "Materials"}.get(cat, "Other")
        groups[key].append(f"┣ {name} ×{inv[name]}")
    lines = ["🎒 *INVENTORY*", f"🪙 Coins: {player['coins']}", "",
             "*Equipped*",
             f"┣ ⚔️ Weapon: {eq.get('weapon') or '—'}",
             f"┣ 🛡️ Armour: {eq.get('armour') or '—'}",
             f"┗ 💍 Accessory: {eq.get('accessory') or '—'}"]
    any_items = False
    for title, rows in groups.items():
        if rows:
            any_items = True
            lines += ["", f"*{title}*"] + rows
    if not any_items:
        lines += ["", "_Your bag is empty._"]
    return "\n".join(lines)


def shop_text(player):
    lines = ["🛒 *NIFLHEIM SHOP*", f"🪙 You have: {player['coins']}", ""]
    for it in I.shop_stock():
        lines.append(f"┣ {it['name']} — 🪙{it['buy']} (sells for {it['sell']}) · {I.describe(it)}")
    lines += ["", "Use .buy <item> [qty]  ·  .sell <item> [qty]"]
    return "\n".join(lines)


def buy(player, rest):
    name_q, qty = parse_name_qty(rest)
    if not name_q:
        return "Usage: .buy <item> [qty]"
    if qty is None:
        return "Quantity must be 1 or more."
    name, err = I.find(name_q, [i["name"] for i in I.shop_stock()])
    if err:
        return err + " Use .shop to see what's for sale."
    it = I.get(name)
    cost = int(it["buy"]) * qty
    if player["coins"] < cost:
        return f"Not enough coins. {qty}× {name} costs {cost}, you have {player['coins']}."
    player["coins"] -= cost
    add_item(player, name, qty)
    return f"🛒 Bought {qty}× {name} for {cost} coins.\n🪙 Balance: {player['coins']}"


def sell(player, rest):
    name_q, qty = parse_name_qty(rest)
    if not name_q:
        return "Usage: .sell <item> [qty]"
    if qty is None:
        return "Quantity must be 1 or more."
    inv = player.get("inventory", {})
    name, err = I.find(name_q, inv.keys())
    if err:
        return err.replace("No item matching", "You don't have an item matching")
    if inv[name] < qty:
        return f"You only have {inv[name]}× {name}."
    gain = int(I.get(name)["sell"]) * qty
    take_item(player, name, qty)
    player["coins"] += gain
    return f"💰 Sold {qty}× {name} for {gain} coins.\n🪙 Balance: {player['coins']}"


def _cap_hp(player):
    player["hp"] = min(player["hp"], I.final_max_hp(player))


def equip(player, rest):
    if not (rest or "").strip():
        return "Usage: .equip <item>"
    inv = player.get("inventory", {})
    gear = [n for n in inv if I.slot_of(I.get(n))]
    name, err = I.find(rest, gear)
    if err:
        return err.replace("No item matching", "You have no equipment matching")
    slot = I.slot_of(I.get(name))
    eq = player.setdefault("equipped", {"weapon": None, "armour": None, "accessory": None})
    old = eq.get(slot)
    take_item(player, name, 1)
    if old:
        add_item(player, old, 1)
    eq[slot] = name
    _cap_hp(player)
    swap = f" ({old} returned to your bag)" if old else ""
    return (f"✅ Equipped {name} in your {slot} slot.{swap}\n"
            f"⚔️ Damage: {I.final_damage(player)} · ❤️ Max HP: {I.final_max_hp(player)}")


def unequip(player, rest):
    slot = I.SLOT_ALIASES.get((rest or "").strip().lower())
    if not slot:
        return "Usage: .unequip <weapon/armour/accessory>"
    eq = player.setdefault("equipped", {"weapon": None, "armour": None, "accessory": None})
    name = eq.get(slot)
    if not name:
        return f"Nothing is equipped in your {slot} slot."
    eq[slot] = None
    add_item(player, name, 1)
    _cap_hp(player)                      # Max HP may have dropped: current HP is capped
    return (f"✅ Unequipped {name}.\n"
            f"⚔️ Damage: {I.final_damage(player)} · ❤️ HP: {player['hp']}/{I.final_max_hp(player)}")


def use(player, rest):
    if not (rest or "").strip():
        return "Usage: .use <potion>"
    inv = player.get("inventory", {})
    pots = [n for n in inv if (I.get(n) or {}).get("heal")]
    name, err = I.find(rest, pots)
    if err:
        return err.replace("No item matching", "You have no potion matching")
    mx = I.final_max_hp(player)
    if player["hp"] >= mx:
        return f"You're already at full HP ({player['hp']}/{mx})."
    before = player["hp"]
    player["hp"] = min(mx, player["hp"] + int(I.get(name)["heal"]))
    take_item(player, name, 1)
    return f"🧪 You drink a {name}: +{player['hp'] - before} HP.\n❤️ HP: {player['hp']}/{mx}"
