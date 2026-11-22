# ============================================================
# NIFLHEIM — shop.py
# Shop system — .shop, .buy, .sell, no static_state blocking
# ============================================================

from data_items import get_shop_with_prices, OAK_TOWN_SHOP, HEALING_ITEMS, get_item

CATEGORY_LABELS = {
    "heal":      "💊 Potions",
    "status":    "✨ Status Heals",
    "ball":      "🔵 Poké Balls",
    "field":     "🎒 Field Items",
    "evolution": "🌀 Evolution",
    "egg":       "🥚 Eggs",
    "special":   "⭐ Special",
}


def _shop_context(player) -> str:
    """Determine price tier based on player's current zone."""
    from map import is_safe_zone
    zone = getattr(player, "zone", "oak_town")
    return "town" if is_safe_zone(zone) else "wild"


def _shop_tier(player) -> str:
    """Determine catalog tier (which items are stocked at all) based on
    the player's current zone_type. City zones stock the full catalog;
    Town zones omit every city_only item. Anything else (route/wild)
    falls back to the town-tier catalog for the rare case .shop is used
    outside a settlement (e.g. an item that lets you shop remotely)."""
    from map import load_zone
    zone_id = getattr(player, "zone", "oak_town")
    zone_type = load_zone(zone_id).get("zone_type")
    return "city" if zone_type == "city" else "town"


def shop_menu(player) -> str:
    """Build the shop display with context-correct prices, grouped by category."""
    context = _shop_context(player)
    tier    = _shop_tier(player)
    items   = get_shop_with_prices(context, tier)

    # Group by category preserving order
    groups: dict[str, list] = {}
    for item in items:
        cat = item.get("category", "special")
        groups.setdefault(cat, []).append(item)

    lines = ["🛒 *POKÉMART*"]
    if context == "wild":
        lines.append("_⚠️ Wilderness surcharge: 3.5×_")
    elif context == "town":
        lines.append("_Town prices_")
    if tier == "town":
        lines.append("_Full catalog available in cities_")

    # Assign global numbers across categories
    idx = 1
    cat_offsets: dict[str, int] = {}  # cat -> start idx
    for cat, cat_items in groups.items():
        label = CATEGORY_LABELS.get(cat, cat.title())
        lines.append(f"\n{label}")
        for item in cat_items:
            lines.append(f"  *{idx}.* {item['name']} — ₡{item['price']}")
            idx += 1

    lines.append("\n_.buy [no.] [qty]  ·  .sell [inv no.] [qty]_")
    lines.append("_View with images: https://ariel-og.vercel.app/?scene=shop_")
    return "\n".join(lines)


def handle_buy(sender, player, args, save_fn) -> str:
    if not args or not args[0].isdigit():
        return "_Usage: .buy [no.] [quantity]_"

    context = _shop_context(player)
    tier    = _shop_tier(player)
    items   = get_shop_with_prices(context, tier)
    idx     = int(args[0]) - 1

    if not (0 <= idx < len(items)):
        return f"_Pick a number between 1 and {len(items)}._"

    qty = int(args[1]) if len(args) > 1 and args[1].isdigit() else 1
    if qty < 1:
        return "_Quantity must be at least 1._"

    item  = items[idx]
    name  = item["name"]
    price = item["price"] * qty
    coins = getattr(player, "coins", 0)

    if coins < price:
        return f"_Not enough coins. You have ₡{coins}, {qty}× {name} costs ₡{price}._"

    player.coins -= price
    player.inventory[name] = player.inventory.get(name, 0) + qty
    save_fn()

    qty_str = f"{qty}× " if qty > 1 else ""
    return (
        f"✅ {qty_str}*{name}* purchased!\n"
        f"₡{price} spent  ·  ₡{player.coins} remaining"
    )


def handle_sell(sender, player, args, save_fn) -> str:
    if not args or not args[0].isdigit():
        return "_Usage: .sell [inv no.] [quantity]_"

    from data_items import indexed_inventory
    rows = indexed_inventory(player)
    n    = int(args[0])

    match = next(((item, qty) for num, item, qty in rows if num == n), None)
    if not match:
        return f"_Pick a number between 1 and {len(rows)}._"
    name, held = match

    base_price = next((i["price"] for i in OAK_TOWN_SHOP if i["name"] == name), None)
    if base_price is None:
        return f"_You can't sell *{name}*._"

    sell_price = max(1, int(base_price * 0.75))

    qty = int(args[1]) if len(args) > 1 and args[1].isdigit() else 1
    qty = min(qty, held)
    if qty < 1:
        return "_Quantity must be at least 1._"

    player.inventory[name] -= qty
    if player.inventory[name] <= 0:
        del player.inventory[name]

    earned = sell_price * qty
    player.coins = getattr(player, "coins", 0) + earned
    save_fn()

    qty_str = f"{qty}× " if qty > 1 else ""
    return (
        f"💰 Sold {qty_str}*{name}* for ₡{earned}\n"
        f"₡{player.coins} in wallet"
    )


def handle_inv_detail(player, args) -> str:
    """Show detail for a specific inventory item by number — number must
    match indexed_inventory (same numbering .inv displays), not raw dict
    order, or .inv [n] would show details for the wrong item."""
    from data_items import indexed_inventory
    rows = indexed_inventory(player)

    if not args or not args[0].isdigit():
        return "_Usage: .inv [number]_"

    n = int(args[0])
    match = next(((item, qty) for num, item, qty in rows if num == n), None)
    if not match:
        return f"_Pick a number between 1 and {len(rows)}._"
    name, qty = match
    item_data = get_item(name)

    # Build detail lines
    lines = [f"*{name}*  ×{qty}"]

    # Sprite if available
    sprite = item_data.get("sprite", "") if item_data else ""
    if sprite:
        lines.insert(0, f"__IMG__{sprite}__CAP__{name}")

    desc = item_data.get("description", "") if item_data else ""
    if desc:
        lines.append(f"_{desc}_")

    # Effect summary
    heal = HEALING_ITEMS.get(name)
    if heal:
        e, v = heal["effect"], heal["value"]
        if e == "hp":
            lines.append(f"Effect: Restores {v} HP")
        elif e == "hp_pct":
            lines.append(f"Effect: Restores {int(v*100)}% max HP")
        elif e == "hp_full":
            lines.append("Effect: Fully restores HP")
        elif e == "full":
            lines.append("Effect: Fully restores HP + cures status")
        elif e == "cure":
            lines.append(f"Effect: Cures {v}")
        elif e == "cure_all":
            lines.append("Effect: Cures all status conditions")
        elif e == "revive":
            lines.append(f"Effect: Revives at {int(v*100)}% HP")

    # Sell value
    base_price = next((i["price"] for i in OAK_TOWN_SHOP if i["name"] == name), None)
    if base_price:
        lines.append(f"Sell: ₡{max(1, int(base_price * 0.75))}")

    return "\n".join(lines)


class ShopMixin:

    def _handle_shop_cmd(self, sender, player) -> str:
        """Open shop menu — no static_state, no movement block."""
        if getattr(player, "story_stage", "new") not in ("has_starter", "route_1"):
            return "_The mart is closed. Come back once you have a Pokémon._"
        return shop_menu(player)

    # Legacy — kept for any oak_mart static_state still in the wild
    def _open_mart(self, sender, player) -> str:
        return self._handle_shop_cmd(sender, player)

    def _handle_shop_flow(self, sender, player, text) -> str | None:
        """No longer used for flow — static_state 'oak_mart' is cleared."""
        player.static_state = None
        self._save(sender, player)
        return None

    # ── Breadcrumbs use ──────────────────────────────────────
    def _use_breadcrumbs(self, sender, player) -> str:
        count = player.inventory.get("Breadcrumbs", 0)
        if count <= 0:
            return "_You don't have any Breadcrumbs._"

        last_town = player.get_flag("last_town")
        if not last_town:
            return "_You haven't visited any other town yet._"

        from map import load_zone
        zone  = load_zone(last_town)
        spawn = zone.get("spawn", (0, 0))

        if count == 1:
            del player.inventory["Breadcrumbs"]
        else:
            player.inventory["Breadcrumbs"] -= 1

        player.zone   = last_town
        player.zone_x = spawn[0]
        player.zone_y = spawn[1]
        self._save(sender, player)

        name = zone.get("name", last_town.replace("_", " ").title())
        return (
            f"🍞 _The breadcrumbs lead you back to {name}..._\n\n"
            + self._render_zone_map(sender, player)
        )
