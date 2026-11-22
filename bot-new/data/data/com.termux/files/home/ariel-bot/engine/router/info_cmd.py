# ============================================================
# NIFLHEIM — router/info_cmd.py
# .info [pokemon|item|zone]  — deep-dive lookup, pulls from PokéAPI
# .skills [no.|pcno.]        — moveset viewer w/ PP, party or box
# ============================================================

import unicodedata
import pokeapi
from data_items import (
    get_item, POKEBALLS, HEALING_ITEMS, PP_ITEMS,
    EXPERIENCE_STONES, EVOLUTION_STONES, HELD_ITEM_EFFECTS,
    OAK_TOWN_SHOP, ITEM_IMAGES, FIELD_ITEMS,
)

# ── Type → emoji, used for both .info mon and .info zone ──────
TYPE_EMOJI = {
    "normal": "⚪", "fire": "🔥", "water": "💧", "electric": "⚡",
    "grass": "🌿", "ice": "❄️", "fighting": "🥊", "poison": "☠️",
    "ground": "🌍", "flying": "🕊️", "psychic": "🔮", "bug": "🐛",
    "rock": "🪨", "ghost": "👻", "dragon": "🐉", "dark": "🌑",
    "steel": "⚙️", "fairy": "✨",
}

# ── Zones with real data files — used for name/alias matching ─
KNOWN_ZONES = {
    "oak_town", "greenwood_town", "hydro_town", "oceana",
    "fauna", "route_1", "route_3", "thunderplains",
}

# ── Elemental (type) balls ──────────────────────────────────────
# One ball per type, evocative names (matches the existing
# Pyro/Cryo/Atmo/Floro/Volt pattern). These ARE the item names —
# not aliases, not "formerly" anything. Catch bonus follows the
# pattern already live in encounters.py (BALL_CATCH_BONUS) for the
# original 5: +0.15 catch rate against a Pokémon whose type matches
# the ball's element.
ELEMENTAL_BALL_NAMES = {
    "normal":   "Aether Ball",
    "fire":     "Pyro Ball",
    "water":    "Aqua Ball",
    "grass":    "Floro Ball",
    "electric": "Volt Ball",
    "ice":      "Cryo Ball",
    "fighting": "Brawn Ball",
    "poison":   "Toxic Ball",
    "ground":   "Terra Ball",
    "flying":   "Atmo Ball",
    "psychic":  "Psy Ball",
    "bug":      "Swarm Ball",
    "rock":     "Crag Ball",
    "ghost":    "Phantom Ball",
    "dragon":   "Wyrm Ball",
    "dark":     "Umbra Ball",
    "steel":    "Alloy Ball",
    "fairy":    "Fae Ball",
}
ELEMENTAL_BALL_BONUS = 0.15  # flat catch-rate bonus vs matching type
_TYPE_BY_BALL_NAME = {v: k for k, v in ELEMENTAL_BALL_NAMES.items()}

# Random Ball — rolls a random type each throw, applies that type's
# bonus. No mechanic existed anywhere in the codebase for this one;
# this is the most direct reading of the name. Flag for confirmation
# if a different behavior is intended.
RANDOM_BALL_NAME = "Random Ball"

# name -> canonical elemental ball name, lowercased
ITEM_ALIASES = {name.lower(): name for name in ELEMENTAL_BALL_NAMES.values()}
ITEM_ALIASES[RANDOM_BALL_NAME.lower()] = RANDOM_BALL_NAME



def _fold_accents(s: str) -> str:
    """Strip accents so 'poke' matches 'poké', etc."""
    return "".join(
        c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)
    )


def _type_line(types: list[str]) -> str:
    return "  ".join(f"{TYPE_EMOJI.get(t, '')}{t.capitalize()}" for t in types)


def _stat_bar(value: int, cap: int = 200, width: int = 10) -> str:
    filled = min(width, max(0, int((value / cap) * width)))
    return f"{'█' * filled}{'░' * (width - filled)}"


class InfoMixin:

    # ── .info dispatcher ───────────────────────────────────────
    def _handle_info(self, sender, player, args: list[str]) -> str:
        if not args:
            return (
                "🔎 *.info* — detailed lookup\n\n"
                "_.info [pokemon]_  — species, stats, types, moves\n"
                "_.info [item]_     — description, effect, price\n"
                "_.info [zone]_     — danger, encounters, gym\n\n"
                "_Example: .info charizard_"
            )

        query = " ".join(args).strip()
        key   = query.lower().replace(" ", "-")

        # 1) Zone — check known zone ids/aliases first (cheap, no API call)
        zone_hit = self._resolve_zone(key, query)
        if zone_hit:
            return self._info_zone(zone_hit)

        # 2) Item — check our local item tables (also cheap)
        item_hit = self._resolve_item(query)
        if item_hit:
            return self._info_item(item_hit)

        # 3) Pokémon — fall through to PokéAPI (network call, cached)
        mon_result = self._info_pokemon(key)
        if mon_result:
            return mon_result

        suggestions = _suggest_species(query)
        if suggestions:
            names = ", ".join(f"*{s.replace('-', ' ').title()}*" for s in suggestions)
            return (
                f"⚠️ _Couldn't find_ *{query}*_. Did you mean:_\n{names}"
            )

        return (
            f"⚠️ _Couldn't find a Pokémon, item, or zone matching_ "
            f"*{query}*_. Check the spelling and try again._"
        )

    # ── Resolvers ───────────────────────────────────────────────
    def _resolve_zone(self, key: str, query: str) -> str | None:
        from map import load_zone
        if key in KNOWN_ZONES:
            return key
        q = query.lower()
        for z in KNOWN_ZONES:
            zd = load_zone(z)
            if zd.get("name", "").lower() == q:
                return z
        return None

    def _resolve_item(self, query: str) -> str | None:
        """Match against every local item table, case-insensitively.
        Also folds accents so 'poke ball' matches 'Poké Ball'."""
        q = _fold_accents(query.lower())

        if q in ITEM_ALIASES:
            return ITEM_ALIASES[q]

        pools = [
            POKEBALLS, HEALING_ITEMS, PP_ITEMS,
            EXPERIENCE_STONES, HELD_ITEM_EFFECTS,
        ]
        for pool in pools:
            for name in pool:
                if _fold_accents(name.lower()) == q:
                    return name
        for name in EVOLUTION_STONES:
            if _fold_accents(name.lower()) == q:
                return name
        for entry in OAK_TOWN_SHOP:
            if _fold_accents(entry["name"].lower()) == q:
                return entry["name"]
        # items.json (if ever populated) as a final fallback
        j = get_item(query)
        if j:
            return j.get("name", query)
        return None

    # ── .info [item] ───────────────────────────────────────────
    def _info_item(self, name: str) -> str:
        from encounter_tables import BALL_TYPE_AFFINITY, BALL_CATCH_BONUS

        lines = [f"📦 *{name}*"]
        affinity_types = BALL_TYPE_AFFINITY.get(name)

        # Category + mechanical effect
        if affinity_types:
            bonus = BALL_CATCH_BONUS.get(name, ELEMENTAL_BALL_BONUS)
            type_s = " / ".join(
                f"{TYPE_EMOJI.get(t,'')}{t.capitalize()}" for t in affinity_types
            )
            cat_label = "/".join(t.capitalize() for t in affinity_types)
            lines.append(f"_Category: {cat_label}-Type Poké Ball_")
            lines.append(f"*Effect:* +{bonus*100:.0f}% catch rate vs {type_s}-type Pokémon.")
            lines.append("_No bonus against other types._")
        elif name == RANDOM_BALL_NAME:
            bonus = BALL_CATCH_BONUS.get(name, ELEMENTAL_BALL_BONUS)
            lines.append("_Category: Poké Ball_")
            lines.append(
                f"*Effect:* Rolls a random type on throw. If it matches the "
                f"wild Pokémon's type, applies a +{bonus*100:.0f}% catch bonus — "
                f"otherwise falls back to standard Poké Ball rate."
            )
            lines.append("_Gamble ball — you won't know the outcome until you throw it._")
        elif name in POKEBALLS:
            mult = POKEBALLS[name]
            mult_s = "Guaranteed catch." if mult >= 255 else f"×{mult} catch rate."
            lines.append("_Category: Poké Ball_")
            lines.append(f"*Effect:* {mult_s}")
        elif name in HEALING_ITEMS:
            e = HEALING_ITEMS[name]
            lines.append("_Category: Healing Item_")
            lines.append(f"*Effect:* {_describe_heal_effect(e)}")
        elif name in PP_ITEMS:
            e = PP_ITEMS[name]
            lines.append("_Category: PP Restore_")
            lines.append(f"*Effect:* {_describe_pp_effect(e)}")
        elif name in EXPERIENCE_STONES:
            e = EXPERIENCE_STONES[name]
            lines.append("_Category: Experience Stone_")
            lines.append(f"*Effect:* {_describe_xp_effect(e)}")
        elif name in EVOLUTION_STONES:
            lines.append("_Category: Evolution Stone_")
            lines.append("*Effect:* Triggers evolution for compatible species.")
        elif name in HELD_ITEM_EFFECTS:
            e = HELD_ITEM_EFFECTS[name]
            lines.append("_Category: Held Item_")
            lines.append(f"*Effect:* {_describe_held_effect(e)}")
        elif name in FIELD_ITEMS:
            lines.append("_Category: Field Item_")
            lines.append("*Effect:* Recalls you to the last town you visited.")
        else:
            lines.append("_No mechanical data on file — flavor item only._")

        # items.json flavor description, if the file is ever populated
        j = get_item(name)
        if j and j.get("description"):
            lines.append(f"_{j['description']}_")

        # Shop price — all 19 balls are stocked, so this always resolves
        shop_entry = next((i for i in OAK_TOWN_SHOP if i["name"] == name), None)
        if shop_entry:
            base = shop_entry["price"]
            lines.append("")
            lines.append(f"*Base Price:* ₡{base}  _(town ×2, wild ×3.5)_")

        img = _item_image(name)
        body = "\n".join(lines)
        return f"__IMG__{img}__CAP__{body}" if img else body

    # ── .info [zone] ────────────────────────────────────────────
    def _info_zone(self, zone_id: str) -> str:
        from map import load_zone, is_safe_zone
        from encounter_tables import ENCOUNTER_TABLES
        from gym import GYMS

        zd     = load_zone(zone_id)
        name   = zd.get("name", zone_id.replace("_", " ").title())
        danger = zd.get("danger", "🟢 Mild")
        safe   = is_safe_zone(zone_id)
        ztype  = zd.get("zone_type", "town" if safe else "field")

        lines = [f"🗺️ *{name}*"]
        lines.append(f"_Type: {ztype.title()}  |  {'🛡️ Safe Zone' if safe else danger}_")
        lines.append("")

        gym = GYMS.get(zone_id)
        if gym:
            lines.append(f"🏅 *Gym:* {gym['town_name']} Gym — Leader {gym['leader']} ({gym['leader_type']})")
            lines.append(f"   _Badge:_ {gym['badge']}")
            lines.append("")

        table = ENCOUNTER_TABLES.get(zone_id)
        if table:
            level_range = table.get("level_range")
            if level_range:
                lines.append(f"*Wild Level Range:* {level_range[0]}–{level_range[1]}")
            lines.append("*Wild Encounters:*")
            for tile_type, entries in table.items():
                if tile_type == "level_range":
                    continue
                species_sorted = sorted(entries, key=lambda e: -e[1])
                top = species_sorted[:8]
                names = ", ".join(s.replace("-", " ").title() for s, _ in top)
                more = len(species_sorted) - len(top)
                suffix = f"  _(+{more} more)_" if more > 0 else ""
                lines.append(f"  _{tile_type.title()}:_ {names}{suffix}")
        elif safe:
            lines.append("_No wild encounters — this is a safe zone._")
        else:
            lines.append("_No encounter data on file for this zone yet._")

        return "\n".join(lines)

    # ── .info [pokemon] ─────────────────────────────────────────
    def _info_pokemon(self, key: str) -> str | None:
        data = pokeapi.get_full(self.db, key)
        if not data:
            return None

        name    = data["name"].capitalize()
        dex_no  = data.get("id", "?")
        types   = data.get("types", [])
        genus   = data.get("genus", "")
        flavor  = data.get("flavor_text", "")
        stats   = data.get("base_stats", {})
        moves   = data.get("default_moves", [])
        abils   = data.get("abilities", [])
        height  = data.get("height", 0) / 10  # dm -> m
        weight  = data.get("weight", 0) / 10  # hg -> kg
        legend  = data.get("is_legendary", False)
        myth    = data.get("is_mythical", False)
        growth  = data.get("growth_rate", "")
        sprite  = data.get("sprite", "")

        tag = " ✨ *Mythical*" if myth else (" ⭐ *Legendary*" if legend else "")

        lines = [f"📖 *#{dex_no} {name}*{tag}"]
        if genus:
            lines.append(f"_{genus}_")
        lines.append(f"Type: {_type_line(types)}")
        lines.append("")

        if flavor:
            lines.append(f"_{flavor}_")
            lines.append("")

        lines.append(f"*Height:* {height:.1f} m   *Weight:* {weight:.1f} kg")
        if growth:
            lines.append(f"*Growth Rate:* {growth.replace('-', ' ').title()}")
        lines.append("")

        lines.append("*Base Stats:*")
        stat_labels = [
            ("hp", "HP"), ("attack", "Atk"), ("defense", "Def"),
            ("special-attack", "SpA"), ("special-defense", "SpD"),
            ("speed", "Spe"),
        ]
        total = 0
        for key_, label in stat_labels:
            v = stats.get(key_, 0)
            total += v
            lines.append(f"  {label:<4} {v:>3}  {_stat_bar(v)}")
        lines.append(f"  {'BST':<4} {total:>3}")
        lines.append("")

        if abils:
            lines.append(f"*Abilities:* {', '.join(a.replace('-', ' ').title() for a in abils)}")

        if moves:
            move_names = ", ".join(m.replace("-", " ").title() for m in moves)
            lines.append(f"*Starting Moves:* {move_names}")

        # Evolution chain, if resolvable
        evo_url = data.get("evolution_chain_url")
        if evo_url:
            chain = pokeapi.get_evolution_chain(self.db, evo_url)
            if chain and len(chain) > 1:
                stage_strs = []
                for stage in chain:
                    s_name = stage["name"].replace("-", " ").title()
                    if stage["trigger"] == "base":
                        stage_strs.append(s_name)
                    elif stage.get("min_level"):
                        stage_strs.append(f"→ {s_name} (Lv.{stage['min_level']})")
                    elif stage.get("item"):
                        stage_strs.append(f"→ {s_name} ({stage['item'].replace('-', ' ').title()})")
                    else:
                        stage_strs.append(f"→ {s_name}")
                lines.append("")
                lines.append(f"*Evolution:* {' '.join(stage_strs)}")

        body = "\n".join(lines)
        return f"__IMG__{sprite}__CAP__{body}" if sprite else body

    # ── .skills — party or box, with PP ─────────────────────────
    def _handle_skills(self, sender, player, args: list[str]) -> str:
        if not args:
            if not player.party:
                return "🎒 _Your party is empty._"
            lines = ["⚔️ *Skills — pick a Pokémon*", ""]
            for i, p in enumerate(player.party, 1):
                lines.append(f"  {i}. {p.nickname}")
            lines.append("")
            lines.append("_.skills [no.]        — party slot_")
            lines.append("_.skills pc[no.]      — box slot_")
            return "\n".join(lines)

        query = " ".join(args).strip()
        qlow  = query.lower()

        # ── PC / box lookup: "pc3", "pc 3", or "pcno.3" style ──
        if qlow.startswith("pc"):
            rest = qlow[2:].strip().lstrip(".").strip()
            if not rest.isdigit():
                return "_Usage: .skills pc[number] — e.g. .skills pc3_"
            idx = int(rest) - 1
            if idx < 0 or idx >= len(player.box):
                return f"⚠️ _No Pokémon in box slot {rest}._"
            mon = player.box[idx]
            return self._skills_card(mon, location="Box")

        # ── Party lookup: number or name/nickname ──
        mon = None
        if qlow.isdigit():
            idx = int(qlow) - 1
            if 0 <= idx < len(player.party):
                mon = player.party[idx]
        else:
            for p in player.party:
                if p.nickname.lower() == qlow or p.name.lower() == qlow:
                    mon = p
                    break

        if not mon:
            return f"⚠️ _You don't have '{query}' in your party. Try .skills pc[no.] for your box._"

        return self._skills_card(mon, location="Party")

    def _skills_card(self, mon, location: str) -> str:
        lines = [f"⚔️ *{mon.nickname}'s Skills*  _({location})_", ""]
        if mon.moves:
            for i, m in enumerate(mon.moves, 1):
                name = m["name"].replace("-", " ").title()
                pp, mpp = m["pp"], m["max_pp"]
                lines.append(f"  {i}. {name:<20} {pp}/{mpp} PP")
        else:
            lines.append("_(no moves learned yet)_")

        pool = getattr(mon, "move_pool", [])
        current = {m["name"] for m in mon.moves}
        available = [m for m in pool if m not in current]
        if available:
            lines.append("")
            lines.append("*Available to Learn:*")
            for i, m in enumerate(available[:5], 1):
                lines.append(f"  {i}. {m.replace('-', ' ').title()}")
            lines.append("")
            lines.append("_.setskill [name] to swap in_")

        sprite = getattr(mon, "sprite", "")
        body = "\n".join(lines)
        return f"__IMG__{sprite}__CAP__{body}" if sprite else body


# ── Item-effect describers ─────────────────────────────────────
def _item_image(name: str) -> str | None:
    if name in ITEM_IMAGES:
        return ITEM_IMAGES[name]
    ptype = _TYPE_BY_BALL_NAME.get(name)
    if ptype:
        return f"https://niflheim-online.vercel.app/assets/items/{ptype}_ball.png"
    if name == RANDOM_BALL_NAME:
        return "https://niflheim-online.vercel.app/assets/items/random_ball.png"
    return None


_SPECIES_POOL_CACHE: set[str] | None = None


def _species_pool() -> set[str]:
    """Every species name that actually appears in-game — arena pool,
    zone encounter tables, and gym pools. Built once and cached."""
    global _SPECIES_POOL_CACHE
    if _SPECIES_POOL_CACHE is not None:
        return _SPECIES_POOL_CACHE

    pool: set[str] = set()
    try:
        from arena import ARENA_POOL
        pool.update(ARENA_POOL)
    except Exception:
        pass
    try:
        from encounter_tables import ENCOUNTER_TABLES
        for table in ENCOUNTER_TABLES.values():
            for tile, entries in table.items():
                if tile == "level_range":
                    continue
                pool.update(name for name, _weight in entries)
    except Exception:
        pass
    try:
        from gym import GYMS
        for g in GYMS.values():
            pool.update(g.get("pool", []))
            pool.update(g.get("leader_pool", []))
    except Exception:
        pass
    try:
        from data_pokemon import STARTERS
        pool.update(STARTERS.keys())
    except Exception:
        pass

    _SPECIES_POOL_CACHE = pool
    return pool


def _edit_distance(a: str, b: str) -> int:
    """Standard Levenshtein distance, iterative DP."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
        prev = cur
    return prev[-1]


def _suggest_species(query: str, max_results: int = 5) -> list[str]:
    """Closest species names by edit distance, within a tight threshold
    so we only ever suggest genuinely close misspellings."""
    q = query.lower().replace(" ", "-")
    pool = _species_pool()
    if not pool:
        return []

    # Distance threshold scales gently with word length so short names
    # (e.g. "eevee") don't match everything within range.
    max_dist = 2 if len(q) <= 6 else 3

    scored = []
    for name in pool:
        d = _edit_distance(q, name)
        if d <= max_dist:
            scored.append((d, name))

    scored.sort(key=lambda x: (x[0], x[1]))
    return [name for _d, name in scored[:max_results]]


def _describe_heal_effect(e: dict) -> str:
    eff, val = e["effect"], e["value"]
    if eff == "hp":         return f"Restores {val} HP."
    if eff == "hp_full":    return "Fully restores HP."
    if eff == "hp_pct":     return f"Restores {int(val * 100)}% of max HP."
    if eff == "full":       return "Fully restores HP and cures all status conditions."
    if eff == "revive":     return f"Revives a fainted Pokémon at {int(val * 100)}% HP."
    if eff == "cure":       return f"Cures {val}."
    if eff == "cure_all":   return "Cures all status conditions."
    return "Unknown effect."


def _describe_pp_effect(e: dict) -> str:
    eff, val = e["effect"], e["value"]
    if eff == "pp":           return f"Restores {val} PP to one move."
    if eff == "pp_full":      return "Fully restores PP to one move."
    if eff == "pp_all":       return f"Restores {val} PP to all moves."
    if eff == "pp_all_full":  return "Fully restores PP to all moves."
    return "Unknown effect."


def _describe_xp_effect(e: dict) -> str:
    eff, val = e["effect"], e["value"]
    if eff == "xp":         return f"Grants {val} XP to a Pokémon."
    if eff == "xp_levels":  return f"Instantly grants {val} level(s) to a Pokémon."
    return "Unknown effect."


def _describe_held_effect(e: dict) -> str:
    eff = e.get("effect", "")
    trig = e.get("trigger", "")
    val = e.get("value")
    parts = []
    if eff == "heal_pct":
        parts.append(f"Heals {val*100:.1f}% max HP")
    elif eff == "drain":
        parts.append(f"Heals {val*100:.0f}% of damage dealt")
    elif eff == "power_boost":
        parts.append(f"Boosts move power ×{val}")
        if e.get("recoil"):
            parts.append(f"(recoils {e['recoil']*100:.0f}% dealt damage)")
    elif eff.endswith("_boost"):
        parts.append(f"Boosts the relevant stat ×{val}")
    elif eff == "contact_dmg":
        parts.append(f"Deals {val*100:.1f}% max HP to attackers on contact")
    elif eff == "survive_1hp":
        parts.append("Survives a KO hit with 1 HP (single use)")
    elif eff == "cure_all":
        parts.append("Cures status ailments automatically")
    elif eff == "type_boost":
        t = e.get("type", "")
        parts.append(f"Boosts {t.capitalize()}-type moves ×{val}")
    elif eff == "crit_up":
        parts.append("Increases critical hit rate")
    elif eff.startswith("accuracy"):
        parts.append(f"Adjusts accuracy ×{val}")
    else:
        parts.append(f"{eff} (×{val})" if val is not None else eff)

    trig_note = {
        "end_turn": "at the end of each turn",
        "on_attack": "when attacking",
        "on_hit": "when hit",
        "on_ko": "when it would be KO'd",
        "hp_below": f"below {int(e.get('threshold', 0.5)*100)}% HP",
        "on_status": "when afflicted with a status condition",
        "on_super": "on super-effective hits",
        "passive": "passively",
    }.get(trig, "")

    result = " — ".join(parts) if len(parts) > 1 else parts[0]
    if trig_note:
        result += f", {trig_note}"
    if e.get("single_use"):
        result += " (single use)"
    return result + "."
