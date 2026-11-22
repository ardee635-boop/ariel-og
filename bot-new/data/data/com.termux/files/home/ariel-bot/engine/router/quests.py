# ============================================================
# NIFLHEIM — router/quests.py
# Quest system: .board, .quests, .redeem, .rankup
# ============================================================

import random
import time
import datetime

from map import is_safe_zone
from models import Quest

# ── Story quest definitions ───────────────────────────────────

QUEST_DEFINITIONS = {
    "first_pokemon_1": Quest(
        id          = "first_pokemon_1",
        title       = "My First Pokémon I",
        description = "Dr Oak has invited you to his Pokélab in Oak Town. Go visit him.",
    ),
    "first_pokemon_2": Quest(
        id          = "first_pokemon_2",
        title       = "My First Pokémon II",
        description = (
            "Dr Oak has promised you a gift. "
            "Ask him about it at the Pokélab."
        ),
    ),
    "greenwood_1": Quest(
        id          = "greenwood_1",
        title       = "Greenwood Gym",
        description = (
            "You have registered yourself as a globally recognized trainer. "
            "Prove your worth and defeat Levin, the Gym Leader of Greenwood Town."
        ),
    ),
}

# These three are story quests, not board quests — Quest.__init__ doesn't
# take source/reward/tips as constructor params, so they're set here.
# Previously all three silently defaulted to source="board" (the Quest
# model's default), which is why greenwood_1 was showing up under Side
# Quests on the site instead of Story Quests.
QUEST_DEFINITIONS["first_pokemon_1"].source = "story"
QUEST_DEFINITIONS["first_pokemon_2"].source = "story"

QUEST_DEFINITIONS["greenwood_1"].source = "story"
QUEST_DEFINITIONS["greenwood_1"].rank   = "F"
QUEST_DEFINITIONS["greenwood_1"].reward = {
    "Floro Ball":             2,
    "Essence":                1,
    "Small Experience Stone": 3,
    "Random Floro Egg":       1,
}
QUEST_DEFINITIONS["greenwood_1"].tips = (
    "💡 *Tips*\n"
    "On WhatsApp, use *.quicktravel* to quickly move between zones.\n"
    "On WhatsApp, go *left* to reach Greenwood Town on foot."
)


def make_quest(quest_id: str) -> Quest:
    """Return a fresh Quest instance by id, copying all definition fields
    (not just id/title/description/steps — source, reward, penalty, tips
    and rank must survive too, or every quest silently reverts to the
    Quest model's defaults, e.g. source='board')."""
    q = QUEST_DEFINITIONS.get(quest_id)
    if not q:
        raise ValueError(f"Unknown quest id: {quest_id}")
    fresh          = Quest(q.id, q.title, q.description, list(q.steps))
    fresh.type     = q.type
    fresh.target   = q.target
    fresh.required = q.required
    fresh.reward   = q.reward
    fresh.penalty  = q.penalty
    fresh.rank     = q.rank
    fresh.source   = q.source
    fresh.tips     = q.tips
    return fresh


# ── Story quest event handlers ────────────────────────────────

def on_registration_complete(player) -> list:
    """Called right after .name completes. Gives quest 1."""
    q = make_quest("first_pokemon_1")
    player.add_quest(q)
    player.set_flag("oak_chat_enabled", False)
    return [
        f"📋 You have received the quest "
        f"*\"{q.title}\"*\n"
        f"_{q.description}_\n\n"
        f"Look for the *𓏺🜔* symbol on the map."
    ]


def on_lab_entered(player) -> list:
    """Called when player steps onto the lab tile. Completes Q1, gives Q2."""
    msgs = []

    if not player.get_flag("quest1_completed"):
        for q in list(getattr(player, "quests", [])):
            if getattr(q, "id", None) == "first_pokemon_1":
                q.status = "complete"
                player.quests.remove(q)
                player.completed_quests.append(q)
                break
        player.set_flag("quest1_completed", True)
        msgs.append("✅ Quest *\"My First Pokémon I\"* completed!")

    if not player.get_flag("quest2_given"):
        q2 = make_quest("first_pokemon_2")
        if not hasattr(player, "quests"):
            player.quests = []
        if not any(getattr(q, "id", None) == q2.id for q in player.quests):
            player.quests.append(q2)
        player.set_flag("quest2_given", True)
        msgs.append(
            f"📋 You have received the quest "
            f"*\"{q2.title}\"*\n"
            f"_{q2.description}_"
        )

    return msgs


def on_starter_chosen(player, pokemon_name: str) -> list:
    """Called after player confirms their starter. Completes Q2."""
    msgs = []

    if not player.get_flag("quest2_completed"):
        for q in list(getattr(player, "quests", [])):
            if getattr(q, "id", None) == "first_pokemon_2":
                q.status = "complete"
                player.quests.remove(q)
                player.completed_quests.append(q)
                break
        player.set_flag("quest2_completed", True)
        player.set_flag("oak_chat_enabled", False)
        msgs.append("✅ Quest *\"My First Pokémon II\"* completed!")

    return msgs


def on_route1_begin(player) -> list:
    """Called when player transitions to route_1. Clears Q1+Q2, gives items + Greenwood quest."""
    # Silently clear Q1 if still open
    if not player.get_flag("quest1_completed"):
        for q in list(getattr(player, "quests", [])):
            if getattr(q, "id", None) == "first_pokemon_1":
                q.status = "complete"
                player.quests.remove(q)
                player.completed_quests.append(q)
                break
        player.set_flag("quest1_completed", True)

    # Silently clear Q2 if still open
    if not player.get_flag("quest2_completed"):
        for q in list(getattr(player, "quests", [])):
            if getattr(q, "id", None) == "first_pokemon_2":
                q.status = "complete"
                player.quests.remove(q)
                player.completed_quests.append(q)
                break
        player.set_flag("quest2_completed", True)

    # Give items
    player.give_item("Poké Ball", 3)
    player.give_item("Potion", 1)

    msgs = []
    if not player.get_flag("greenwood_given"):
        gq = make_quest("greenwood_1")
        if not hasattr(player, "quests"):
            player.quests = []
        if not any(getattr(q, "id", None) == gq.id for q in player.quests):
            player.quests.append(gq)
        player.set_flag("greenwood_given", True)
        msgs.append(
            f"📦 *You received:* 3× Poké Ball, 1× Potion!\n\n"
            f"📋 You have received the quest "
            f"*\"{gq.title}\"*\n"
            f"_{gq.description}_\n\n"
            f"_You can now move using:_\n"
            f"*1* up  •  *2* down  •  *3* left  •  *4* right"
        )

    return msgs

# ── Rank config ───────────────────────────────────────────────

RANK_ORDER = ["F", "E", "D", "C", "B", "A", "S"]

RANK_REQUIREMENTS = {
    # current_rank: {kills, badges, trainer_fight}
    "F": {"kills": 50,  "badges": 0, "trainer": False},
    "E": {"kills": 70,  "badges": 1, "trainer": False},
    "D": {"kills": 80,  "badges": 1, "trainer": True},
}

# ── Board state (per zone, resets every 30 min) ───────────────

_board_cache: dict = {}   # zone_id -> {quests: [...], generated_at: float}
BOARD_RESET_SECS = 30 * 60
BOARD_SIZE       = 20

# ── Quest templates ───────────────────────────────────────────

# Rank -> (objective_types, count_range, reward_coins_range, penalty_range)
_TEMPLATES = {
    "F": {
        "types":   ["defeat_wild", "catch_species"],
        "counts":  (3, 10),
        "rewards": (30, 80),
        "penalty": (10, 30),
    },
    "E": {
        "types":   ["defeat_wild", "catch_species"],
        "counts":  (8, 20),
        "rewards": (80, 200),
        "penalty": (30, 80),
    },
    "D": {
        "types":   ["defeat_wild", "catch_species", "reach_location"],
        "counts":  (15, 35),
        "rewards": (150, 400),
        "penalty": (80, 150),
    },
    "C": {
        "types":   ["defeat_wild", "catch_species", "reach_location"],
        "counts":  (25, 50),
        "rewards": (300, 700),
        "penalty": (120, 250),
    },
}

# Common species for catch quests
_COMMON_SPECIES = [
    "rattata", "pidgey", "weedle", "caterpie", "metapod",
    "kakuna", "spearow", "ekans", "sandshrew", "nidoran-f",
    "nidoran-m", "clefairy", "vulpix", "jigglypuff", "zubat",
    "oddish", "paras", "venonat", "diglett", "meowth",
    "psyduck", "mankey", "growlithe", "poliwag", "abra",
    "machop", "bellsprout", "tentacool", "geodude", "ponyta",
    "slowpoke", "magnemite", "farfetchd", "doduo", "seel",
    "grimer", "shellder", "gastly", "drowzee", "krabby",
    "voltorb", "exeggcute", "cubone", "koffing", "rhyhorn",
    "horsea", "goldeen", "staryu", "magikarp", "eevee",
]

_REACH_LOCATIONS = ["route_1", "greenwood_town", "oak_town"]


def _gen_quest(rank: str, idx: int) -> dict:
    tmpl    = _TEMPLATES.get(rank, _TEMPLATES["F"])
    qtype   = random.choice(tmpl["types"])
    count   = random.randint(*tmpl["counts"])
    reward  = random.randint(*tmpl["rewards"])
    penalty = random.randint(*tmpl["penalty"])

    if qtype == "defeat_wild":
        title  = f"Defeat {count} wild Pokémon"
        target = None
    elif qtype == "catch_species":
        species = random.choice(_COMMON_SPECIES)
        title   = f"Catch {count} {species.replace('-', ' ').capitalize()}"
        target  = species
        count   = max(1, min(count, 5))
    else:  # reach_location
        loc    = random.choice(_REACH_LOCATIONS)
        title  = f"Travel to {loc.replace('_', ' ').title()}"
        target = loc
        count  = 1

    return {
        "id":       f"board_{rank}_{idx}_{random.randint(1000,9999)}",
        "title":    title,
        "type":     qtype,
        "target":   target,
        "required": count,
        "progress": 0,
        "reward":   reward,
        "penalty":  penalty,
        "rank":     rank,
        "source":   "board",
    }


def _get_board(zone_id: str, player_rank: str) -> list:
    """Return (or generate) the 50-quest board for this zone."""
    now   = time.time()
    entry = _board_cache.get(zone_id)
    if entry and (now - entry["generated_at"]) < BOARD_RESET_SECS:
        return entry["quests"]

    quests = [_gen_quest(player_rank, i) for i in range(BOARD_SIZE)]
    _board_cache[zone_id] = {"quests": quests, "generated_at": now}
    return quests


# ── Global quest board (site-facing) ──────────────────────────
# Unlike _get_board above (per-zone, per-player-rank, in-memory — the
# original WhatsApp .board command, left untouched), this is ONE
# shared board across the whole game: 20 quests per rank for F/E/D/C
# (80 total), persisted in quest_board so every player — site or
# WhatsApp — sees and claims from the exact same list. Regenerates
# wholesale every 30 minutes. See router/site_actions.py for the
# site's accept/decline actions that claim/release rows here.
GLOBAL_BOARD_RANKS = ["F", "E", "D", "C"]

def ensure_global_board(db):
    """
    Regenerate the global board if it's missing or older than 30 min.
    Safe to call on every /api/quests request — it's a no-op read
    (one cheap timestamp check) unless the board is actually stale.
    """
    import datetime as _dt

    generated_at = db.quest_board_generated_at()
    if generated_at:
        try:
            age = (_dt.datetime.utcnow() - _dt.datetime.fromisoformat(generated_at)).total_seconds()
            if age < BOARD_RESET_SECS:
                return  # still fresh
        except Exception:
            pass  # unparseable timestamp — fall through and regenerate

    now_iso = _dt.datetime.utcnow().isoformat()
    quests = []
    for rank in GLOBAL_BOARD_RANKS:
        for i in range(BOARD_SIZE):
            q = _gen_quest(rank, i)
            q["generated_at"] = now_iso
            quests.append(q)
    db.quest_board_replace(quests)


def _get_active_board_quests(player) -> list:
    """Get board quests stored as dicts in player flags."""
    return player.get_flag("board_quests", [])

def _save_active_board_quests(player, quests: list):
    player.set_flag("board_quests", quests)

def _available_board_quests(zone_id: str, player) -> list:
    """Board quests not yet accepted by this player."""
    accepted_ids = {q["id"] for q in _get_active_board_quests(player)}
    board        = _get_board(zone_id, getattr(player, "guild_rank", "F"))
    return [q for q in board if q["id"] not in accepted_ids]


def _completed_quests(player) -> list:
    return [q for q in _get_active_board_quests(player)
            if q.get("progress", 0) >= q.get("required", 1)]


def _expired_quests(player) -> list:
    now = datetime.datetime.utcnow().isoformat()
    return [q for q in _get_active_board_quests(player)
            if q.get("expires_at") and q["expires_at"] < now
            and q.get("progress", 0) < q.get("required", 1)]


def _progress_bar(progress: int, required: int, width: int = 8) -> str:
    filled = int((progress / max(required, 1)) * width)
    return "█" * filled + "░" * (width - filled)


# ── Quest hooks (called from battle.py) ──────────────────────

def on_defeat(player, wild: dict):
    quests  = _get_active_board_quests(player)
    changed = False
    for q in quests:
        if q.get("type") == "defeat_wild" and q.get("progress", 0) < q.get("required", 1):
            q["progress"] = q.get("progress", 0) + 1
            changed = True
    if changed:
        _save_active_board_quests(player, quests)
    return changed


def on_catch(player, species: str):
    quests  = _get_active_board_quests(player)
    changed = False
    for q in quests:
        if (q.get("type") == "catch_species"
                and q.get("target", "").lower() == species.lower()
                and q.get("progress", 0) < q.get("required", 1)):
            q["progress"] = q.get("progress", 0) + 1
            changed = True
    if changed:
        _save_active_board_quests(player, quests)
    return changed


def on_move(player, zone_id: str):
    quests  = _get_active_board_quests(player)
    changed = False
    for q in quests:
        if (q.get("type") == "reach_location"
                and q.get("target") == zone_id
                and q.get("progress", 0) < q.get("required", 1)):
            q["progress"] = 1
            changed = True
    if changed:
        _save_active_board_quests(player, quests)
    return changed


# ── Rank-up trainer (placeholder) ────────────────────────────

def _rank_trainer_for(player) -> dict:
    """Build a scaled trainer for D→C rank-up fight."""
    lvl = max(5, getattr(player, "level", 1))
    return {
        "name":   "Rank Examiner",
        "party": [
            {"name": "eevee",   "level": lvl},
            {"name": "growlithe", "level": lvl + 2},
        ],
    }


# ── QuestMixin ────────────────────────────────────────────────

class QuestMixin:

    def _handle_quests(self, sender, player, cmd, args, text):

        if cmd in (".quests", ".quest"):
            return self._cmd_quests(player)

        if cmd == ".board":
            return self._cmd_board(sender, player)

        if cmd in (".accept",):
            return self._cmd_accept(sender, player, args)

        if cmd == ".redeem":
            return self._cmd_redeem(sender, player, args)

        if cmd == ".rankup":
            return self._cmd_rankup(sender, player)

        return None

    # ── .quests ───────────────────────────────────────────────

    def _cmd_quests(self, player):
        lines = ["📋 *Active Quests*\n"]
        has_any = False

        # ── Story quests (Quest objects on player.quests) ─────
        story_quests = [
            q for q in getattr(player, "quests", [])
            if getattr(q, "status", "active") == "active"
        ]
        if story_quests:
            has_any = True
            lines.append("*📖 Story*")
            for q in story_quests:
                lines.append(f"🔸 *{q.title}*\n   _{q.description}_")

        # ── Board quests (dicts in player flags) ──────────────
        board_quests = _get_active_board_quests(player)
        now = datetime.datetime.utcnow().isoformat()
        penalized = []
        for q in board_quests[:]:
            if q.get("expires_at") and q["expires_at"] < now and q.get("progress", 0) < q.get("required", 1):
                player.coins = max(0, getattr(player, "coins", 0) - q["penalty"])
                penalized.append(q)
                board_quests.remove(q)
        _save_active_board_quests(player, board_quests)

        if board_quests:
            has_any = True
            lines.append("\n*📋 Board*")
            for i, q in enumerate(board_quests, 1):
                prog = q.get("progress", 0)
                req  = q.get("required", 1)
                bar  = _progress_bar(prog, req)
                done = "✅" if prog >= req else "🔸"
                exp  = q.get("expires_at", "")[:10] if q.get("expires_at") else "—"
                lines.append(
                    f"{done} *{i}. {q['title']}*\n"
                    f"   {bar} {prog}/{req}\n"
                    f"   💰 {q['reward']}₡  ⚠️ -{q['penalty']}₡  📅 {exp}"
                )

        if penalized:
            lines.append("\n⚠️ _Expired board quests removed. Coins deducted._")

        if not has_any:
            base = "📋 _No active quests._\n_Visit .board in town to grab some._"
            if penalized:
                names = ", ".join(q["title"] for q in penalized)
                base += f"\n\n⚠️ _Expired: {names}. Coins deducted._"
            return base

        return "\n\n".join(lines)

    # ── .board ────────────────────────────────────────────────

    def _cmd_board(self, sender, player):
        zone = getattr(player, "zone", "")
        if not is_safe_zone(zone):
            return "📋 _Quest boards are only available in towns._"

        available    = _available_board_quests(zone, player)
        board_active = _get_active_board_quests(player)

        if not available:
            return "📋 _No quests available right now. Board resets every 30 minutes._"

        # Show first 10 available
        shown = available[:10]
        lines = [f"📋 *Quest Board — {zone.replace('_', ' ').title()}*",
                 f"_Slots: {len(board_active)}/3 · Showing {len(shown)} of {len(available)}_\n"]

        for i, q in enumerate(shown, 1):
            lines.append(
                f"*{i}. {q['title']}*\n"
                f"   💰 {q['reward']}₡  ⚠️ -{q['penalty']}₡\n"
                f"   _.accept {i} to take this quest_"
            )

        return "\n\n".join(lines)

    # ── .accept ───────────────────────────────────────────────

    def _cmd_accept(self, sender, player, args):
        zone = getattr(player, "zone", "")
        if not is_safe_zone(zone):
            return "📋 _You can only accept quests in towns._"

        active = _get_active_board_quests(player)
        if len(active) >= 3:
            return "⚠️ _You already have 3 board quests active. Complete or wait for one to expire._"

        if not args or not args[0].isdigit():
            return "⚠️ Usage: *.accept [number]*"

        idx       = int(args[0]) - 1
        available = _available_board_quests(zone, player)
        if idx < 0 or idx >= len(available[:10]):
            return "⚠️ _Invalid quest number._"

        quest = dict(available[idx])
        quest["accepted"]    = True
        quest["accepted_at"] = datetime.datetime.utcnow().isoformat()
        quest["expires_at"]  = (
            datetime.datetime.utcnow() + datetime.timedelta(days=2)
        ).isoformat()

        _save_active_board_quests(player, active + [quest])
        self._save(sender, player)
        return f"✅ Quest accepted: *{quest['title']}*\n_Expires in 2 days. Reward: {quest['reward']}₡_"

    # ── .redeem ───────────────────────────────────────────────

    def _cmd_redeem(self, sender, player, args):
        zone = getattr(player, "zone", "")
        if not is_safe_zone(zone):
            return "🏆 _You can only redeem quests in towns._"

        completed = _completed_quests(player)
        if not completed:
            return "🏆 _No completed quests to redeem._"

        if len(completed) > 1 and not args:
            lines = ["🏆 *Completed Quests — choose one to redeem:*\n"]
            for i, q in enumerate(completed, 1):
                lines.append(f"*{i}. {q['title']}*  💰 {q['reward']}₡")
            lines.append("\n_Use *.redeem [number]* to claim._")
            return "\n".join(lines)

        if args and args[0].isdigit():
            idx = int(args[0]) - 1
            if idx < 0 or idx >= len(completed):
                return "⚠️ _Invalid number._"
            quest = completed[idx]
        else:
            quest = completed[0]

        active = _get_active_board_quests(player)
        player.coins       = getattr(player, "coins", 0) + quest["reward"]
        player.quests_done = getattr(player, "quests_done", 0) + 1
        _save_active_board_quests(player, [q for q in active if q["id"] != quest["id"]])
        self._save(sender, player)

        return (
            f"🏆 *Quest Complete!*\n"
            f"_{quest['title']}_\n\n"
            f"💰 +{quest['reward']}₡  |  Total: {player.coins}₡\n"
            f"📋 Quests Done: {player.quests_done}"
        )

    # ── .rankup ───────────────────────────────────────────────

    def _cmd_rankup(self, sender, player):
        zone = getattr(player, "zone", "")
        if not is_safe_zone(zone):
            return "🏅 _Rank up is only available in towns._"

        rank     = getattr(player, "guild_rank", "F")
        reqs     = RANK_REQUIREMENTS.get(rank)
        if not reqs:
            return f"🏅 _Rank {rank} has no further advancement defined yet._"

        kills    = getattr(player, "rank_kills", 0)
        badges   = len(getattr(player, "badges", []))
        next_rank = RANK_ORDER[RANK_ORDER.index(rank) + 1]

        # Check kills
        if kills < reqs["kills"]:
            return (
                f"🏅 *Rank Up: {rank} → {next_rank}*\n\n"
                f"⚔️ Wild Defeats: {kills}/{reqs['kills']}\n"
                f"🏆 Badges: {badges}/{reqs['badges']}\n\n"
                f"_Keep training!_"
            )

        # Check badges
        if badges < reqs["badges"]:
            return (
                f"🏅 *Rank Up: {rank} → {next_rank}*\n\n"
                f"⚔️ Wild Defeats: ✅ {kills}/{reqs['kills']}\n"
                f"🏆 Badges: {badges}/{reqs['badges']} ❌\n\n"
                f"_Earn a gym badge first!_"
            )

        # Trainer fight required (D → C)
        if reqs["trainer"]:
            return (
                f"🏅 *Rank Examination: {rank} → {next_rank}*\n\n"
                f"⚔️ Wild Defeats: ✅\n"
                f"🏆 Badges: ✅\n\n"
                f"_You must defeat the Rank Examiner!_\n"
                f"_(Trainer battle system coming soon)_"
            )

        # All clear — rank up
        player.guild_rank = next_rank
        player.rank_kills = 0   # reset kill counter
        self._save(sender, player)

        return (
            f"🎉 *Rank Up!*\n\n"
            f"You are now *Rank {next_rank}*!\n\n"
            f"_New quests and opportunities await._"
        )

