# ============================================================
# NIFLHEIM – MODELS.PY
# Player model — Pokémon edition
# ============================================================

import time
import random

RM = '\u200b' * 700   # invisible spacer for WhatsApp message splitting

# HP secondary formula (DEF×0.90 + STR×0.10, secondary_stats.py) produces
# numbers in the same range as a single primary stat (tens) — too low to
# function as a real damage-absorbing HP pool across multiple hits. This
# scale is applied on top when deriving max_hp specifically (nowhere
# else — armor/other secondaries are NOT scaled). Arbitrary, not from
# the design doc (doc doesn't specify an HP pool size) — chosen so a
# freshly-caught Pokémon's HP roughly matches the old system's feel
# rather than one-shotting instantly. Revisit once real playtesting
# data exists.
HP_POOL_SCALE = 1   # real PokéAPI HP now (was a x3 pool under soulbound)


# ── Helpers ───────────────────────────────────────────────────

def wp_bar(current, maximum, width=10):
    filled = int((current / maximum) * width) if maximum > 0 else 0
    return f"`[{'▓' * filled}{'░' * (width - filled)}]` {current}/{maximum}"

def xp_required(level):
    """XP to next level. Smooth curve: 100 at Lv1."""
    return int(100 * (1.123 ** (level - 1)))

def hp_display(current, maximum, emoji="♥"):
    pct = int((current / maximum) * 100) if maximum > 0 else 0
    return f"{emoji} {current}/{maximum} ({pct}%)"


# ── OwnedPokemon ──────────────────────────────────────────────

class OwnedPokemon:
    """
    A Pokémon in the player's party or box.

    REWRITTEN (Phase 3 cutover) to store a real Soulbound object
    (soulbound.py's pokemon_to_soulbound() output — 7 stats,
    grades, skills, traits) as its foundation, instead of the old
    6-stat PokéAPI base_stats + star-multiplier system. `stars` is
    KEPT as a flavor/display multiplier layered on top of the
    Soulbound's own stats (see _apply_star_bonus below) — stars
    were never part of the Soulbound design doc, so this is a
    deliberate choice to preserve existing player-facing star
    rarity/prestige display, not a doc requirement.

    Level scaling now goes through soulbound.stats_at_level()
    (the universal grade-based growth table), not a level-in-a-
    -formula calculation baked into this class.
    """

    def __init__(self, data: dict, nickname: str = "", level: int = 5,
                 stars: int | None = None, db=None):
        from data_pokemon import roll_stars, STAR_LABEL, STAR_PRESTIGE
        from stats import moves_for_level, move_entry

        # Identity
        self.pokemon_id   = data["id"]
        self.name         = data["name"]          # species name
        self.nickname     = nickname or data["name"].capitalize()
        self.types        = data["types"]
        self.sprite       = data.get("sprite", "")

        # Stars — roll once, store forever. Flavor/prestige layer on
        # top of the Soulbound's own stats now, not the sole source
        # of stat variance (see _apply_star_bonus).
        self.stars        = stars if stars is not None else roll_stars()

        # Level / XP
        self.level        = level
        self.xp           = 0
        self.xp_to_next   = xp_required(level)

        # ── Stats straight from PokéAPI base stats ──────────────
        # Stored so stats can be recomputed on level-up / load.
        self.base_stats = dict(data.get("base_stats", {}))
        self.stats = {}
        self._recompute_stats()
        self.max_hp = self.stats["hp"]
        self.hp     = self.max_hp

        # Moves — {name, pp, max_pp}. Level-up learnset + PP from PokéAPI.
        self.moves = [move_entry(m, db) for m in moves_for_level(data, level)]

        # Status condition (burn, paralysis, sleep, freeze, poison, None)
        self.status       = None

        # Catch info
        self.caught_at    = time.time()
        self.catch_rate   = data.get("catch_rate", 45)

        # Evolution info (populated from pokeapi.get_evolution_chain)
        self.evolution_chain_url = data.get("evolution_chain_url", "")

        # Flavor / description text
        self.flavor_text  = data.get("flavor_text", "")
        self.genus         = data.get("genus", "")

        # Is this a starter? (affects story flags)
        self.is_starter   = False

    # ── Stat calculations ──────────────────────────────────────

    def _recompute_stats(self):
        """Rebuild self.stats from PokéAPI base stats at the current level.
        Stars are cosmetic (no stat bonus)."""
        from stats import compute_stats
        self.stats = compute_stats(self.base_stats, self.level)

    def stat(self, stat_name: str) -> float:
        """Level stat by PokéAPI name: attack, defense, special-attack,
        special-defense, speed (and hp)."""
        return self.stats.get(stat_name, 0)

    def secondary_stat(self, name: str) -> float:
        return self.stats.get(name, 0)

    def hydrate_base_stats(self, db) -> bool:
        """Legacy saves (soulbound era) only carry approximated base stats.
        Replace them with the real PokéAPI values; rescales HP proportionally."""
        if not getattr(self, "legacy_stats", False):
            return False
        from pokeapi import get_pokemon
        data = get_pokemon(db, self.name)
        if not data:
            return False
        old_hp, old_max = self.hp, self.max_hp
        self.base_stats = dict(data["base_stats"])
        self._recompute_stats()
        self.max_hp = self.stats["hp"]
        if old_hp <= 0:
            self.hp = 0
        elif old_max:
            self.hp = max(1, min(self.max_hp, round(old_hp / old_max * self.max_hp)))
        else:
            self.hp = self.max_hp
        self.legacy_stats = False
        return True

    def is_fainted(self):
        return self.hp <= 0

    def heal(self, amount: int) -> int:
        """Heal by amount, capped at max_hp. Returns actual HP recovered."""
        before  = self.hp
        self.hp = min(self.max_hp, self.hp + amount)
        return self.hp - before

    def heal_full(self):
        self.hp     = self.max_hp
        self.status = None
        for m in self.moves:
            m["pp"] = m["max_pp"]

    def take_damage(self, amount: int) -> int:
        actual    = min(self.hp, max(0, amount))
        self.hp  -= actual
        return actual

    def gain_xp(self, amount: int) -> list[str]:
        self.xp += amount
        msgs = []
        while self.xp >= self.xp_to_next:
            self.level      += 1
            self.xp         -= self.xp_to_next
            self.xp_to_next  = xp_required(self.level)
            old_max          = self.max_hp
            self._recompute_stats()
            self.max_hp      = self.stats["hp"]
            self.hp          = min(self.hp + (self.max_hp - old_max), self.max_hp)
            msgs.append(f"🌟 *{self.nickname}* grew to Lv.{self.level}!")
        return msgs

    # ── Star helpers ──────────────────────────────────────────

    def star_display(self) -> str:
        from data_pokemon import STAR_LABEL
        return STAR_LABEL.get(self.stars, "?")

    def prestige(self) -> str:
        from data_pokemon import STAR_PRESTIGE
        return STAR_PRESTIGE.get(self.stars, "")

    # ── Display ───────────────────────────────────────────────

    def summary(self) -> str:
        type_str   = "/".join(t.capitalize() for t in self.types)
        prestige   = self.prestige()
        prestige_s = f"  ·  *{prestige}*" if prestige else ""
        status_s   = f"\n⚠️ *Status:* _{self.status}_" if self.status else ""
        hp_pct     = int((self.hp / self.max_hp) * 100) if self.max_hp else 0
        xp_pct     = int((self.xp / self.xp_to_next) * 100) if self.xp_to_next else 0

        # Current skills
        moves_lines = "\n".join(
            f"  {i+1}. {m['name'].replace('-',' ').title()} ({m['pp']}/{m['max_pp']} PP)"
            for i, m in enumerate(self.moves)
        )

        # Available (learnable) skills
        pool = getattr(self, "move_pool", [])
        current_names = {m["name"] for m in self.moves}
        available = [m for m in pool if m not in current_names]
        if available:
            avail_lines = "\n".join(
                f"  {i+1}. {m.replace('-',' ').title()}"
                for i, m in enumerate(available[:5])
            )
            avail_block = f"\n*Available Skills:*\n{avail_lines}\n\n_.swapskill [current no.] [available no.]_"
        else:
            avail_block = "\n*Available Skills:* _none yet_"

        # Flavor text
        flavor = getattr(self, "flavor_text", "") or ""
        flavor_block = f"\n_{flavor}_" if flavor.strip() else ""

        img_line = f"__IMG__{self.sprite}__CAP__" if getattr(self, "sprite", "") else ""

        card = (
            f"*Name:* {self.nickname}  Lv.{self.level}\n"
            f"*Type:* {type_str}{prestige_s}\n"
            f"{self.star_display()}\n"
            f"*HP:* {self.hp}/{self.max_hp} ({hp_pct}%)\n"
            f"*EXP:* {self.xp}/{self.xp_to_next} ({xp_pct}%){status_s}"
            f"{flavor_block}\n"
            f"─────────────\n"
            f"*Skills:*\n{moves_lines}"
            f"{avail_block}"
        )

        if img_line:
            return img_line + card
        return card

    # ── Serialise ─────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "pokemon_id":          self.pokemon_id,
            "name":                self.name,
            "nickname":            self.nickname,
            "types":               self.types,
            "sprite":              self.sprite,
            "stars":               self.stars,
            "level":               self.level,
            "xp":                  self.xp,
            "xp_to_next":          self.xp_to_next,
            "hp":                  self.hp,
            "max_hp":              self.max_hp,
            "base_stats":          self.base_stats,
            "moves":               self.moves,
            "status":              self.status,
            "caught_at":           self.caught_at,
            "catch_rate":          self.catch_rate,
            "evolution_chain_url": self.evolution_chain_url,
            "flavor_text":         self.flavor_text,
            "genus":                getattr(self, "genus", ""),
            "is_starter":          self.is_starter,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "OwnedPokemon":
        p                      = cls.__new__(cls)
        p.pokemon_id           = d["pokemon_id"]
        p.name                 = d["name"]
        p.nickname             = d.get("nickname", d["name"].capitalize())
        p.types                = d.get("types", [])
        p.sprite               = d.get("sprite", "")
        p.stars                = d.get("stars", 1)
        p.level                = d.get("level", 5)
        p.xp                   = d.get("xp", 0)
        p.xp_to_next           = d.get("xp_to_next", xp_required(d.get("level", 5)))
        p.hp                   = d.get("hp", 0)
        p.max_hp               = d.get("max_hp", 0)
        p.base_stats = dict(d.get("base_stats") or {})
        p.legacy_stats = False
        if not p.base_stats:
            # Legacy (soulbound-era) save: approximate base stats from the old
            # level-1 stats until hydrate_base_stats(db) fetches the real ones.
            sb = (d.get("soulbound") or {}).get("stats", {})
            dfn = sb.get("DEF", 45)
            p.base_stats = {
                "hp": max(1, int(dfn * 0.9 + sb.get("STR", 45) * 0.1)),
                "attack": sb.get("STR", 45), "defense": dfn,
                "special-attack": sb.get("INT", 45), "special-defense": dfn,
                "speed": sb.get("SPD", 45),
            }
            p.legacy_stats = True
        p._recompute_stats()
        p.moves                = d.get("moves", [])
        p.status               = d.get("status", None)
        p.caught_at            = d.get("caught_at", 0)
        p.catch_rate           = d.get("catch_rate", 45)
        p.evolution_chain_url  = d.get("evolution_chain_url", "")
        p.flavor_text          = d.get("flavor_text", "")
        p.genus                = d.get("genus", "")
        p.is_starter           = d.get("is_starter", False)
        return p


# ── Player ────────────────────────────────────────────────────

# ── Quest ─────────────────────────────────────────────────────

class Quest:
    def __init__(self, id: str, title: str, description: str, steps: list = None):
        self.id          = id
        self.title       = title
        self.description = description
        self.steps       = steps or []
        self.status      = "active"

        # Quest system fields
        self.type        = None    # defeat_wild / catch_species / reach_location
        self.target      = None    # species name or zone_id (for catch/reach)
        self.required    = 1       # objective count
        self.progress    = 0       # current count
        self.reward      = 0       # coins on completion
        self.penalty     = 0       # coins lost on expiry
        self.rank        = "F"     # quest tier
        self.source      = "board" # board or story
        self.tips        = None    # optional guidance shown on first tap (story quests)
        self.accepted    = False
        self.accepted_at = None
        self.expires_at  = None

    def get(self, key, default=None):
        """Allow dict-style .get() access for compatibility."""
        return getattr(self, key, default)

    def to_dict(self) -> dict:
        return {
            "id":          self.id,
            "title":       self.title,
            "description": self.description,
            "steps":       self.steps,
            "status":      self.status,
            "type":        self.type,
            "target":      self.target,
            "required":    self.required,
            "progress":    self.progress,
            "reward":      self.reward,
            "penalty":     self.penalty,
            "rank":        self.rank,
            "source":      self.source,
            "tips":        self.tips,
            "accepted":    self.accepted,
            "accepted_at": self.accepted_at,
            "expires_at":  self.expires_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Quest":
        q             = cls(d["id"], d["title"], d.get("description", ""), d.get("steps", []))
        q.status      = d.get("status", "active")
        q.type        = d.get("type")
        q.target      = d.get("target")
        q.required    = d.get("required", 1)
        q.progress    = d.get("progress", 0)
        q.reward      = d.get("reward", 0)
        q.penalty     = d.get("penalty", 0)
        q.rank        = d.get("rank", "F")
        q.source      = d.get("source", "board")
        q.tips        = d.get("tips")
        q.accepted    = d.get("accepted", False)
        q.accepted_at = d.get("accepted_at")
        q.expires_at  = d.get("expires_at")
        return q

    def detail_text(self) -> str:
        lines = [f"*{self.title}*", "", self.description]
        if self.steps:
            lines.append("")
            for s in self.steps:
                lines.append(f"  ◻️ {s}")
        return "\n".join(lines)



class Player:

    def __init__(self, name: str):
        self.name           = name

        # Trainer level / XP (separate from Pokémon XP)
        self.level          = 1
        self.xp             = 0
        self.xp_to_next     = 100

        # Party — up to 6 OwnedPokemon
        self.party:  list[OwnedPokemon] = []
        # Box  — overflow storage
        self.box:    list[OwnedPokemon] = []

        # Active battler index in party
        self.active_slot    = 0

        # Pokédex — set of seen pokemon names, set of caught names
        self.pokedex_seen:   set = set()
        self.pokedex_caught: set = set()

        # Badges
        self.badges:        list = []

        # Inventory — {item_name: quantity}
        self.inventory:     dict = {"Poké Ball": 0, "Potion": 0}
        self.coins          = 0

        # World position
        self.zone           = "oak_town"   # current zone id
        self.zone_x         = 12           # tile col within zone
        self.zone_y         = 11           # tile row within zone (player spawn)
        self.static_state   = None         # non-moveable state (e.g. "oak_lab_1"); overrides zone

        # .explore discovery memory (Phase 6, Section 18) — per-player,
        # per zone+direction record of which destinations this player
        # has personally reached. Shape: {"zone_id": {"direction": [dest_id, ...]}}
        self.discovered_connections: dict = {}

        # Quests
        self.quests:           list = []
        self.completed_quests: list = []

        # Story / objectives
        self.story_stage    = "new"        # new → at_lab → choosing → has_starter → route_1
        self.objective      = "Find the Pokélab in Oak Town 🜔˖"
        self.story_flags:   dict = {}      # {flag_name: True/False}
        self.tutorial_done  = False

        # UI preference
        self.hud_style      = 1
        self.menu_preset    = 0

        # PvP record
        self.pvp_wins       = 0
        self.pvp_losses     = 0

        # Profile / .card fields
        self.player_class   = None   # placeholder system, not implemented yet
        self.age            = None
        self.bio            = None
        self.card_theme     = 1      # 1=Normal 2=Glitch 3=Metallic 4=Flame

        # Combat session attached by router (not persisted directly)
        self.session        = None

    # ── Party helpers ─────────────────────────────────────────

    def active_pokemon(self) -> OwnedPokemon | None:
        if not self.party:
            return None
        return self.party[self.active_slot]

    def set_active(self, idx: int):
        """Point active_slot at party[idx]. Does not reorder the party."""
        if idx < 0 or idx >= len(self.party):
            return
        self.active_slot = idx

    def first_conscious(self) -> int | None:
        """Index of first non-fainted Pokémon in party."""
        for i, p in enumerate(self.party):
            if not p.is_fainted():
                return i
        return None

    def all_fainted(self) -> bool:
        return all(p.is_fainted() for p in self.party)

    def add_to_party(self, pokemon: OwnedPokemon) -> bool:
        """Add to party if space, else box. Returns True if added to party."""
        if len(self.party) < 6:
            self.party.append(pokemon)
            return True
        self.box.append(pokemon)
        return False

    # ── Pokédex ───────────────────────────────────────────────

    def see_pokemon(self, name: str):
        self.pokedex_seen.add(name.lower())

    def catch_pokemon(self, name: str):
        self.pokedex_seen.add(name.lower())
        self.pokedex_caught.add(name.lower())

    # ── Inventory ─────────────────────────────────────────────

    # Items that stay in inventory at x0 instead of being removed
    _PERSISTENT_ITEMS = {"Poké Ball", "Potion"}

    def give_item(self, item: str, qty: int = 1):
        self.inventory[item] = self.inventory.get(item, 0) + qty

    def use_item(self, item: str) -> bool:
        """Remove one of item. Returns True if successful."""
        if self.inventory.get(item, 0) <= 0:
            return False
        self.inventory[item] -= 1
        if self.inventory[item] == 0 and item not in self._PERSISTENT_ITEMS:
            del self.inventory[item]
        return True

    def has_item(self, item: str) -> bool:
        return self.inventory.get(item, 0) > 0

    # ── XP / Level ────────────────────────────────────────────

    def gain_xp(self, amount: int) -> list[str]:
        self.xp += amount
        msgs = []
        while self.xp >= self.xp_to_next:
            self.level      += 1
            self.xp         -= self.xp_to_next
            self.xp_to_next  = xp_required(self.level)
            msgs.append(f"🌟 *Trainer level up!* Now Level {self.level}!")
        return msgs

    # ── Story flags ───────────────────────────────────────────


    # ── Quest helpers ─────────────────────────────────────────

    def add_quest(self, quest):
        if not any(q.id == quest.id for q in self.quests + self.completed_quests):
            self.quests.append(quest)

    def complete_quest(self, quest_id: str) -> bool:
        for q in self.quests:
            if q.id == quest_id:
                q.status = "complete"
                self.quests.remove(q)
                self.completed_quests.append(q)
                return True
        return False

    def get_quest(self, quest_id: str):
        for q in self.quests + self.completed_quests:
            if q.id == quest_id:
                return q
        return None

    def quests_text(self) -> str:
        if not self.quests:
            return f"*{self.name}'s Quest Log*\n_(no active quests)_"
        lines = [f"*{self.name}'s Quest Log*"]
        for i, q in enumerate(self.quests, 1):
            lines.append(f"{i}. {q.title}")
        lines.append("\n_Use .quest (no.) for details_")
        return "\n".join(lines)

    def quest_detail_text(self, number: int) -> str:
        if number < 1 or number > len(self.quests):
            return "⚠️ No quest at that number."
        return self.quests[number - 1].detail_text()

    def set_flag(self, flag: str, value=True):
        self.story_flags[flag] = value

    def get_flag(self, flag: str, default=False):
        return self.story_flags.get(flag, default)

    # ── Display ───────────────────────────────────────────────

    def status_text(self) -> str:
        from engine_clock import get_time_display
        time_str = get_time_display()

        party_lines = ""
        for i, p in enumerate(self.party):
            marker     = "▶ " if i == self.active_slot else "  "
            fainted    = " _(fainted)_" if p.is_fainted() else ""
            type_str   = "/".join(t.capitalize() for t in p.types)
            party_lines += f"┃ {marker}{p.nickname} [{type_str}] Lv.{p.level}{fainted}\n"
            party_lines += f"┃   {hp_display(p.hp, p.max_hp)}\n"
        if not party_lines:
            party_lines = "┃ _(no Pokémon yet)_\n"

        inv_lines = "\n".join(
            f"┃  {item} × {qty}" for item, qty in self.inventory.items()
        ) or "┃ _(empty)_"

        badge_str = ", ".join(self.badges) if self.badges else "_(none yet)_"

        return (
            "╭━━❰ ⌖ 𝙽𝙸𝙵𝙻𝙷𝙴𝙸𝙼 ⌖ ❱━━╮\n"
            f"┃ Trainer  › {self.name}\n"
            f"┃ Level    › {self.level}\n"
            f"┃ Badges   › {badge_str}\n"
            f"┃ Coins    › {self.coins}\n"
            "╰━━━━━━━━━━━━━━━━━╯\n"
            "\n" + RM + "\n"
            "╭━━❰ ⌖ 𝙿𝙰𝚁𝚃𝚈 ⌖ ❱━━╮\n"
            + party_lines +
            "╰━━━━━━━━━━━━━━━━━╯\n"
            "\n" + RM + "\n"
            "╭━━❰ ⌖ 𝙱𝙰𝙶 ⌖ ❱━━╮\n"
            + inv_lines + "\n"
            "╰━━━━━━━━━━━━━━━━━╯\n"
            "\n" + RM + "\n"
            "╭━━❰ ⌖ 𝚆𝙾𝚁𝙻𝙳 ⌖ ❱━━╮\n"
            f"┃ {time_str}\n"
            f"┃ Zone › {self.zone}\n"
            f"┃ Pos  › ({self.zone_x}, {self.zone_y})\n"
            "╰━━━━━━━━━━━━━━━━━╯\n"
            "\n" + RM + "\n"
            "╭━━❰ ⌖ 𝙾𝙱𝙹𝙴𝙲𝚃𝙸𝚅𝙴 ⌖ ❱━━╮\n"
            f"┃ {self.objective}\n"
            "╰━━━━━━━━━━━━━━━━━╯"
        )

    def card_text(self) -> str:
        mon = self.active_pokemon()
        mon_str = mon.nickname if mon else "--"
        return (
            "[Card]\n"
            f"Name: {self.name}\n"
            f"Class: {self.player_class or 'None'}\n"
            f"Age: {self.age if self.age is not None else '--'}\n"
            f"Zone: {self.zone}\n"
            f"Pokemon: {mon_str}\n"
            f"Bio: {self.bio if self.bio else '--'}"
        )

    def pokedex_text(self) -> str:
        seen   = len(self.pokedex_seen)
        caught = len(self.pokedex_caught)
        return (
            "╭━━❰ ⌖ 𝙿𝙾𝙺É𝙳𝙴𝚇 ⌖ ❱━━╮\n"
            f"┃ Seen   › {seen}\n"
            f"┃ Caught › {caught}\n"
            "╰━━━━━━━━━━━━━━━━━╯"
        )

    # ── Serialise ─────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "name":            self.name,
            "level":           self.level,
            "xp":              self.xp,
            "xp_to_next":      self.xp_to_next,
            "party":           [p.to_dict() for p in self.party],
            "box":             [p.to_dict() for p in self.box],
            "active_slot":     self.active_slot,
            "pokedex_seen":    list(self.pokedex_seen),
            "pokedex_caught":  list(self.pokedex_caught),
            "badges":          self.badges,
            "inventory":       self.inventory,
            "coins":           self.coins,
            "zone":            self.zone,
            "zone_x":          self.zone_x,
            "zone_y":          self.zone_y,
            "static_state":    self.static_state,
            "discovered_connections": self.discovered_connections,
            "quests":           [q.to_dict() for q in self.quests],
            "completed_quests": [q.to_dict() for q in self.completed_quests],
            "story_stage":     self.story_stage,
            "objective":       self.objective,
            "story_flags":     self.story_flags,
            "tutorial_done":   self.tutorial_done,
            "hud_style":       self.hud_style,
            "menu_preset":     self.menu_preset,
            "pvp_wins":        self.pvp_wins,
            "pvp_losses":      self.pvp_losses,
            "player_class":    self.player_class,
            "age":             self.age,
            "bio":             self.bio,
            "card_theme":      self.card_theme,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Player":
        p                 = cls(d["name"])
        p.level           = d.get("level", 1)
        p.xp              = d.get("xp", 0)
        p.xp_to_next      = d.get("xp_to_next", 100)
        p.party           = [OwnedPokemon.from_dict(x) for x in d.get("party", [])]
        p.box             = [OwnedPokemon.from_dict(x) for x in d.get("box", [])]
        p.active_slot     = d.get("active_slot", 0)
        p.pokedex_seen    = set(d.get("pokedex_seen", []))
        p.pokedex_caught  = set(d.get("pokedex_caught", []))
        p.badges          = d.get("badges", [])
        p.inventory       = d.get("inventory", {"Poké Ball": 0, "Potion": 0})
        p.coins           = d.get("coins", 0)
        p.zone            = d.get("zone", "oak_town")
        p.zone_x          = d.get("zone_x", 12)
        p.zone_y          = d.get("zone_y", 11)
        p.static_state    = d.get("static_state", None)
        p.discovered_connections = d.get("discovered_connections", {})
        p.quests           = [Quest.from_dict(q) for q in d.get("quests", [])]
        p.completed_quests = [Quest.from_dict(q) for q in d.get("completed_quests", [])]
        p.story_stage     = d.get("story_stage", "new")
        p.objective       = d.get("objective", "Find the Pokélab in Oak Town 🜔˖")
        p.story_flags     = d.get("story_flags", {})
        p.tutorial_done   = d.get("tutorial_done", False)
        p.hud_style       = d.get("hud_style", 1)
        p.menu_preset     = d.get("menu_preset", 0)
        p.pvp_wins        = d.get("pvp_wins", 0)
        p.pvp_losses      = d.get("pvp_losses", 0)
        p.player_class    = d.get("player_class", None)
        p.age             = d.get("age", None)
        p.bio             = d.get("bio", None)
        p.card_theme      = d.get("card_theme", 1)
        p.session         = None
        p._migrate(d)
        return p

    # ── Schema migration ──────────────────────────────────────────
    # Bump CURRENT_VERSION and add a new `if v < N:` block any time
    # you add new fields, items, flags, or zones. Runs on every load.

    CURRENT_VERSION = 1

    def _migrate(self, d: dict):
        v = d.get("version", 0)

        if v < 1:
            # Ensure Potion slot exists
            if "Potion" not in self.inventory:
                self.inventory["Potion"] = 0
            # Seed visited_zones from current zone if missing
            if not self.story_flags.get("visited_zones"):
                self.story_flags["visited_zones"] = [self.zone]

        self.story_flags["version"] = self.CURRENT_VERSION
