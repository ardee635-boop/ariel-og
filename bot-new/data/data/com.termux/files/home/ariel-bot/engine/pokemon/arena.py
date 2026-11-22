# ============================================================
# NIFLHEIM — arena.py
# Niflheim Soulbound Arena — 3-round gauntlet
# Universal — callable via .arena from anywhere, no physical location
# Normal / Bug / Grass Pokémon pool, scaled to player level
# ============================================================

import random
import time

# ── Config ────────────────────────────────────────────────────
ENTRY_COST       = 100
TOTAL_ROUNDS     = 3
COOLDOWN_WIN     = 300   # 5 min after winning all 3
COOLDOWN_LOSS    = 10    # 10 sec after losing

# ── Pokémon pool ──────────────────────────────────────────────
ARENA_POOL = [
    # Normal
    "rattata","raticate","pidgey","pidgeotto","spearow","meowth",
    "jigglypuff","eevee","sentret","furret","hoothoot","noctowl",
    "aipom","dunsparce","teddiursa",
    # Bug
    "caterpie","metapod","butterfree","weedle","kakuna","beedrill",
    "paras","parasect","venonat","venomoth","scyther","pinsir",
    "ledyba","ledian","spinarak","ariados","yanma","pineco",
    # Grass
    "bulbasaur","ivysaur","oddish","gloom","bellsprout","weepinbell",
    "exeggcute","tangela","chikorita","bayleef","hoppip","skiploom",
    "sunkern","sunflora","bellossom",
]

# ── Trainer names ─────────────────────────────────────────────
TRAINER_NAMES = [
    "Elven","Tora","Dex","Mira","Cassin","Vael","Rook",
    "Lyss","Borin","Petra","Cale","Synn","Wyn","Thera",
    "Dolan","Kess","Brant","Orin","Zara","Finn",
]

# ── Trainer pre-battle taunts ─────────────────────────────────
TRAINER_QUOTES = [
    "Take me down if you can, chum!",
    "I've been waiting for a real challenge.",
    "Don't hold back — I won't.",
    "Let's see what you're made of!",
    "I hope you're ready for this.",
    "My Pokémon are itching for a fight!",
    "You'll have to earn your way through me.",
    "Good luck. You're going to need it.",
    "I've beaten everyone who's stood here. You're next.",
    "Show me something worth watching!",
    "This arena has broken stronger trainers than you.",
    "Win or lose, make it interesting.",
]

# ── Rewards (no eggs, no pokéballs, no rare items) ────────────
ARENA_REWARDS = [
    ("Potion", 1),
    ("Super Potion", 1),
    ("Antidote", 1),
    ("Paralyze Heal", 1),
    ("Awakening", 1),
    ("Burn Heal", 1),
    ("Escape Rope", 1),
    ("Repel", 1),
]

# ============================================================
# STATE HELPERS
# ============================================================

def get_cooldown_remaining(db, sender: str) -> int:
    val = db.get_meta(sender, "arena_cooldown")
    if not val:
        return 0
    try:
        remaining = float(val) - time.time()
        return max(0, int(remaining))
    except ValueError:
        return 0


def set_cooldown(db, sender: str, secs: int):
    db.set_meta(sender, "arena_cooldown", str(time.time() + secs))


def clear_arena_state(db, sender: str):
    for key in ("arena_round", "arena_trainer", "arena_used_names"):
        db.delete_meta(sender, key)


# ============================================================
# CHALLENGE PROMPT (.arena)
# ============================================================

def arena_prompt(db, sender: str, player) -> str:
    """
    Called when player uses .arena, from anywhere.
    Sets arena_pending=1. Returns the challenge confirmation message.
    """
    remaining = get_cooldown_remaining(db, sender)
    if remaining > 0:
        mins = remaining // 60
        secs = remaining % 60
        if mins > 0:
            return f"_The arena is closed. Come back in {mins}m {secs}s._"
        return f"_The arena is closed. Come back in {secs}s._"

    db.set_meta(sender, "arena_pending", "1")

    return (
        f"You are challenging the *Niflheim Soulbound Arena*.\n"
        f"Do you wish to continue?\n"
        f"Our fee is *{ENTRY_COST} coins*.\n\n"
        f"`.Accept`      `.Reject`"
    )


# ============================================================
# ENTRY (after .accept)
# ============================================================

def arena_enter(db, sender: str, player, session) -> str:
    """
    Called when player uses .accept with arena_pending set.
    Deducts coins, sets STATE_ARENA.
    """
    from combat_session import STATE_ARENA

    db.delete_meta(sender, "arena_pending")

    remaining = get_cooldown_remaining(db, sender)
    if remaining > 0:
        mins = remaining // 60
        secs = remaining % 60
        if mins > 0:
            return f"_Not yet. {mins}m {secs}s remaining._"
        return f"_Not yet. {secs}s remaining._"

    coins = getattr(player, "coins", 0)
    if coins < ENTRY_COST:
        return f"_You need {ENTRY_COST} coins. You only have {coins}._"

    player.coins -= ENTRY_COST

    clear_arena_state(db, sender)
    db.set_meta(sender, "arena_round", "1")
    db.set_meta(sender, "arena_used_names", "")

    session.transition(STATE_ARENA)

    return (
        f"🏟️ *Niflheim Soulbound Arena*\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"You have entered the Arena.\n"
        f"There are *{TOTAL_ROUNDS} rounds* in this arena.\n\n"
        f"_Use_ `.next` _to begin your first battle._"
    )


# ============================================================
# DECLINE (after .reject)
# ============================================================

def arena_reject(db, sender: str) -> str:
    """Called when player uses .reject with arena_pending set. Just cancels."""
    db.delete_meta(sender, "arena_pending")
    return "_You back out of the challenge. The arena will be waiting whenever you're ready._"


# ============================================================
# NEXT ROUND
# ============================================================

def arena_next(db, sender: str, player, session, direct_send=None, group_jid=None) -> str:
    round_str = db.get_meta(sender, "arena_round")
    if not round_str:
        return None

    current_round = int(round_str)

    # Build trainer
    used_raw = db.get_meta(sender, "arena_used_names") or ""
    used     = [n for n in used_raw.split(",") if n]
    pool     = [n for n in TRAINER_NAMES if n not in used]
    trainer  = random.choice(pool or TRAINER_NAMES)
    used.append(trainer)
    db.set_meta(sender, "arena_used_names", ",".join(used))
    db.set_meta(sender, "arena_trainer", trainer)

    # Team size: R1=2, R2=3or4, R3=4or5or6
    ace_level = max((p.level for p in player.party if not p.is_fainted()), default=1)
    if current_round == 1:
        team_size = 2
    elif current_round == 2:
        team_size = random.choice([3, 4])
    else:
        team_size = random.choice([4, 5, 6])
    team = _build_trainer_team(db, ace_level, team_size)

    # Arm session (STATE_ARENA_PENDING) — battle not started yet, blocks .atk etc.
    session.arm_trainer_battle(trainer, team, current_round)

    # Dots — player side always out of 6
    PLAYER_SLOTS = 6
    p_alive  = sum(1 for p in player.party if not p.is_fainted())
    p_dots   = "⚈" * p_alive + "⚆" * (PLAYER_SLOTS - p_alive)
    t_dots   = "⚈" * len(team) + "⚆" * (team_size - len(team))

    quote    = random.choice(TRAINER_QUOTES)
    first    = team[0]
    mon_name = first["name"].capitalize()

    msg1 = (
        f"⚔️ *Round {current_round} of {TOTAL_ROUNDS}*\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"Trainer *{trainer}* has challenged you!\n"
        f"_\"{quote}\"_\n\n"
        f"You: {p_dots}  |  {trainer}: {t_dots}\n\n"
        f"_Battle starts in 5 seconds..._"
    )

    # Fire Begin! screen after 5s, then commit to STATE_BATTLE
    if direct_send:
        import threading
        from battle import battle_image_marker
        active = player.party[player.active_slot]
        t_name = trainer
        # Capture group_jid at call time so the thread sends to the right chat
        _group_jid = group_jid

        def _send_begin():
            time.sleep(5)
            try:
                session.commit_trainer_battle()
                hud = battle_image_marker(player.name, active, first, label=t_name)
                begin_msg = (
                    f"*You* sent out *{active.nickname}*!\n"
                    f"*{t_name}* sent out *{mon_name}*!\n\n"
                    f"{hud}"
                )
                direct_send(begin_msg, group_jid=_group_jid)
            except Exception as e:
                import sys
                print(f"[ARENA] _send_begin thread error: {e}", file=sys.stderr, flush=True)
                import traceback
                traceback.print_exc(file=sys.stderr)

        threading.Thread(target=_send_begin, daemon=True).start()

    return msg1


# ============================================================
# ROUND WON
# ============================================================

def arena_round_won(db, sender: str, player, session) -> str:
    round_str = db.get_meta(sender, "arena_round")
    if not round_str:
        return ""

    current_round = int(round_str)

    if current_round >= TOTAL_ROUNDS:
        # All done — reward + cooldown + warp out
        reward_item, qty = random.choice(ARENA_REWARDS)
        player.give_item(reward_item, qty)
        set_cooldown(db, sender, COOLDOWN_WIN)
        clear_arena_state(db, sender)   # wipes arena_round from DB — signals gauntlet over
        from combat_session import STATE_EXPLORING
        session.transition(STATE_EXPLORING)
        session.clear_arena()           # safe to clear fully now
        return (
            f"🏆 *Arena Complete!*\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"You cleared all {TOTAL_ROUNDS} rounds!\n\n"
            f"🎁 Reward: *{reward_item} ×{qty}*\n\n"
            f"_The arena is closed for you for 5 minutes._"
        )
    else:
        next_round = current_round + 1
        db.set_meta(sender, "arena_round", str(next_round))
        trainer = getattr(session, "arena_trainer_name", "the trainer") or "the trainer"
        return (
            f"⚔️ *Trainer {trainer} defeated!*\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"Round {current_round} cleared!\n\n"
            f"_Use_ `.next` _to begin Round {next_round}._"
        )


# ============================================================
# LOSS / EXIT
# ============================================================

def arena_loss(db, sender: str, player, session) -> str:
    clear_arena_state(db, sender)
    set_cooldown(db, sender, COOLDOWN_LOSS)
    from combat_session import STATE_EXPLORING
    session.transition(STATE_EXPLORING)
    session.clear_arena()
    return (
        f"💀 *You were defeated.*\n"
        f"_You've been dropped from the arena.\n"
        f"The arena is locked for 10 seconds._"
    )


# ============================================================
# DOTS HUD
# ============================================================

def arena_dots(player_party: list, trainer_team: list, trainer_name: str) -> str:
    PLAYER_SLOTS = 6
    p_alive = sum(1 for p in player_party if not p.is_fainted())
    t_alive = sum(1 for m in trainer_team if m.get("hp", 0) > 0)
    t_total = len(trainer_team)
    p_dots  = "⚈" * p_alive + "⚆" * (PLAYER_SLOTS - p_alive)
    t_dots  = "⚈" * t_alive + "⚆" * (t_total - t_alive)
    return f"You: {p_dots}  |  {trainer_name}: {t_dots}"


# ============================================================
# INTERNAL HELPERS
# ============================================================


# ============================================================
# INTERNAL HELPERS
# ============================================================

def _build_trainer_team(db, player_level: int, team_size: int) -> list[dict]:
    from pokeapi import get_full
    from encounters import build_wild_monster

    level_min = max(1, player_level - 2)
    level_max = player_level + 2
    species_pool = random.sample(ARENA_POOL, min(team_size * 3, len(ARENA_POOL)))
    team = []
    for species in species_pool:
        if len(team) >= team_size:
            break
        level    = random.randint(level_min, level_max)
        api_data = get_full(db, species)
        if not api_data:
            continue
        mon = build_wild_monster(api_data, level)
        mon["trainer_owned"] = True
        team.append(mon)

    # Fallback
    while len(team) < team_size:
        team.append({
            "name": "rattata", "level": player_level,
            "types": ["normal"], "hp": 20, "max_hp": 20,
            "base_stats": {"hp":30,"atk":56,"def":35,"sp_atk":25,"sp_def":35,"spd":72},
            "moves": [{"name": "tackle", "pp": 35, "max_pp": 35}],
            "status": None, "catch_rate": 255, "base_experience": 51,
            "sprite": "", "stars": 1, "catch_fail_penalty": 0,
            "trainer_owned": True,
        })
    return team
