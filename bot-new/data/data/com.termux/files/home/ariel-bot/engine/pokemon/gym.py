# ============================================================
# NIFLHEIM — gym.py
# Gym leader gauntlet — defeat the elders, then the leader, earn a badge.
# Structurally mirrors arena.py's round system (same underlying
# session machinery — arm_trainer_battle/commit_trainer_battle/
# arena_next_trainer_mon/clear_arena are generic, not arena-specific),
# but is its own gauntlet: no entry fee/NPC gate, no cooldowns,
# and the final round is always a fixed, named leader rather than
# a random trainer.
#
# PLACEHOLDER DATA: elder names, species pools, and team sizes below
# are reasonable defaults so .gym works end to end. Edit GYMS freely —
# nothing else in the codebase depends on the specific values.
# ============================================================

import random

# ── Config ────────────────────────────────────────────────────
GYMS = {
    "greenwood_town": {
        "town_name":   "Greenwood",
        "leader":      "Levin",
        "leader_type": "Nature",
        "badge":       "Leaf Badge",
        "elder_count": 2,
        "elder_names": ["Elder Mira", "Elder Wyn", "Elder Thera", "Elder Cassin"],
        "pool": [
            "oddish", "gloom", "bellsprout", "weepinbell", "hoppip", "skiploom",
            "sunkern", "sunflora", "tangela", "chikorita", "bayleef",
            "bulbasaur", "ivysaur", "budew", "roselia", "cherubi",
        ],
        "leader_pool": [
            "exeggutor", "tangrowth", "sunflora", "bayleef", "vileplume", "victreebel",
        ],
        "leader_team_size": 3,
    },
    "hydro_town": {
        "town_name":   "Hydro",
        "leader":      "Eren",
        "leader_type": "Water",
        "badge":       "Wave Badge",
        "elder_count": 2,
        "elder_names": ["Elder Dolan", "Elder Kess", "Elder Petra", "Elder Brant"],
        "pool": [
            "squirtle", "wartortle", "totodile", "croconaw", "mudkip", "marshtomp",
            "poliwag", "poliwhirl", "tentacool", "horsea", "seadra", "shellder",
            "krabby", "kingler", "staryu", "psyduck",
        ],
        "leader_pool": [
            "blastoise", "feraligatr", "gyarados", "vaporeon", "kingdra", "starmie",
        ],
        "leader_team_size": 3,
    },
}

# Badge artwork — keyed by badge name (not gym/zone id), since that's
# what player.badges actually stores. Inline SVG data URIs, no external
# hosting needed — thematic emblems matching the site's ice/Nordic
# palette (leaf motif for Nature-type Greenwood, wave motif for
# Water-type Hydro). Add new badges here the same way as gyms are added.
BADGE_IMAGES = {
    "Leaf Badge": "data:image/svg+xml,%3Csvg%20xmlns%3D%22http%3A//www.w3.org/2000/svg%22%20viewBox%3D%220%200%20100%20100%22%3E%0A%3Cdefs%3E%0A%3CradialGradient%20id%3D%22g%22%20cx%3D%2250%25%22%20cy%3D%2235%25%22%20r%3D%2270%25%22%3E%0A%3Cstop%20offset%3D%220%25%22%20stop-color%3D%22%234ADE80%22%20stop-opacity%3D%220.35%22/%3E%0A%3Cstop%20offset%3D%22100%25%22%20stop-color%3D%22%234ADE80%22%20stop-opacity%3D%220%22/%3E%0A%3C/radialGradient%3E%0A%3ClinearGradient%20id%3D%22b%22%20x1%3D%220%22%20y1%3D%220%22%20x2%3D%221%22%20y2%3D%221%22%3E%0A%3Cstop%20offset%3D%220%25%22%20stop-color%3D%22%238FE3FF%22/%3E%0A%3Cstop%20offset%3D%2255%25%22%20stop-color%3D%22%234ADE80%22/%3E%0A%3Cstop%20offset%3D%22100%25%22%20stop-color%3D%22%231F8A4C%22/%3E%0A%3C/linearGradient%3E%0A%3C/defs%3E%0A%3Ccircle%20cx%3D%2250%22%20cy%3D%2250%22%20r%3D%2248%22%20fill%3D%22url%28%23g%29%22/%3E%0A%3Ccircle%20cx%3D%2250%22%20cy%3D%2250%22%20r%3D%2244%22%20fill%3D%22%230A1420%22%20stroke%3D%22%23234258%22%20stroke-width%3D%221.5%22/%3E%0A%3Cpath%20d%3D%22M50%2022%20C%2062%2028%2C%2070%2040%2C%2068%2054%20C%2066%2066%2C%2056%2074%2C%2050%2078%20C%2044%2074%2C%2034%2066%2C%2032%2054%20C%2030%2040%2C%2038%2028%2C%2050%2022%20Z%22%20fill%3D%22url%28%23b%29%22%20stroke%3D%22%23C9F3FF%22%20stroke-width%3D%221%22%20stroke-opacity%3D%220.5%22/%3E%0A%3Cpath%20d%3D%22M50%2030%20L50%2074%22%20stroke%3D%22%230A1420%22%20stroke-width%3D%221.6%22%20stroke-opacity%3D%220.5%22%20stroke-linecap%3D%22round%22/%3E%0A%3Cpath%20d%3D%22M50%2042%20L40%2050%20M50%2042%20L60%2050%20M50%2056%20L42%2062%20M50%2056%20L58%2062%22%20stroke%3D%22%230A1420%22%20stroke-width%3D%221.1%22%20stroke-opacity%3D%220.4%22%20stroke-linecap%3D%22round%22/%3E%0A%3Cpath%20d%3D%22M42%2030%20C%2040%2040%2C%2040%2050%2C%2044%2058%22%20stroke%3D%22%23F0FFF8%22%20stroke-width%3D%221.4%22%20stroke-opacity%3D%220.5%22%20stroke-linecap%3D%22round%22%20fill%3D%22none%22/%3E%0A%3C/svg%3E",
    "Wave Badge": "data:image/svg+xml,%3Csvg%20xmlns%3D%22http%3A//www.w3.org/2000/svg%22%20viewBox%3D%220%200%20100%20100%22%3E%0A%3Cdefs%3E%0A%3CradialGradient%20id%3D%22g%22%20cx%3D%2250%25%22%20cy%3D%2235%25%22%20r%3D%2270%25%22%3E%0A%3Cstop%20offset%3D%220%25%22%20stop-color%3D%22%238FE3FF%22%20stop-opacity%3D%220.4%22/%3E%0A%3Cstop%20offset%3D%22100%25%22%20stop-color%3D%22%238FE3FF%22%20stop-opacity%3D%220%22/%3E%0A%3C/radialGradient%3E%0A%3ClinearGradient%20id%3D%22b%22%20x1%3D%220%22%20y1%3D%220%22%20x2%3D%220%22%20y2%3D%221%22%3E%0A%3Cstop%20offset%3D%220%25%22%20stop-color%3D%22%23C9F3FF%22/%3E%0A%3Cstop%20offset%3D%2250%25%22%20stop-color%3D%22%238FE3FF%22/%3E%0A%3Cstop%20offset%3D%22100%25%22%20stop-color%3D%22%231B5C7A%22/%3E%0A%3C/linearGradient%3E%0A%3C/defs%3E%0A%3Ccircle%20cx%3D%2250%22%20cy%3D%2250%22%20r%3D%2248%22%20fill%3D%22url%28%23g%29%22/%3E%0A%3Ccircle%20cx%3D%2250%22%20cy%3D%2250%22%20r%3D%2244%22%20fill%3D%22%230A1420%22%20stroke%3D%22%23234258%22%20stroke-width%3D%221.5%22/%3E%0A%3Cpath%20d%3D%22M20%2066%20Q%2030%2056%2C%2040%2066%20T%2060%2066%20T%2080%2066%22%20stroke%3D%22url%28%23b%29%22%20stroke-width%3D%224%22%20stroke-linecap%3D%22round%22%20fill%3D%22none%22%20opacity%3D%220.55%22/%3E%0A%3Cpath%20d%3D%22M18%2054%20Q%2030%2042%2C%2042%2054%20T%2066%2054%20T%2082%2054%22%20stroke%3D%22url%28%23b%29%22%20stroke-width%3D%225%22%20stroke-linecap%3D%22round%22%20fill%3D%22none%22%20opacity%3D%220.8%22/%3E%0A%3Cpath%20d%3D%22M20%2040%20Q%2032%2026%2C%2044%2040%20T%2068%2040%20T%2080%2040%22%20stroke%3D%22url%28%23b%29%22%20stroke-width%3D%226%22%20stroke-linecap%3D%22round%22%20fill%3D%22none%22/%3E%0A%3Cpath%20d%3D%22M50%2020%20C%2054%2026%2C%2056%2031%2C%2050%2035%20C%2044%2031%2C%2046%2026%2C%2050%2020%20Z%22%20fill%3D%22%23F0FBFF%22%20opacity%3D%220.85%22/%3E%0A%3C/svg%3E",
    # Genesis — the legacy-egg badge, not tied to any gym. Starfield/
    # origin motif (radiating point of light) rather than an elemental
    # emblem, since it marks "you were here at the beginning" rather
    # than a type-matchup win.
    "Genesis": "data:image/svg+xml,%3Csvg%20xmlns%3D%22http%3A//www.w3.org/2000/svg%22%20viewBox%3D%220%200%20100%20100%22%3E%0A%3Cdefs%3E%0A%3CradialGradient%20id%3D%22g%22%20cx%3D%2250%25%22%20cy%3D%2235%25%22%20r%3D%2270%25%22%3E%0A%3Cstop%20offset%3D%220%25%22%20stop-color%3D%22%23FBD34D%22%20stop-opacity%3D%220.4%22/%3E%0A%3Cstop%20offset%3D%22100%25%22%20stop-color%3D%22%23FBD34D%22%20stop-opacity%3D%220%22/%3E%0A%3C/radialGradient%3E%0A%3CradialGradient%20id%3D%22b%22%20cx%3D%2250%25%22%20cy%3D%2250%25%22%20r%3D%2250%25%22%3E%0A%3Cstop%20offset%3D%220%25%22%20stop-color%3D%22%23FFFDF0%22/%3E%0A%3Cstop%20offset%3D%2260%25%22%20stop-color%3D%22%23FBD34D%22/%3E%0A%3Cstop%20offset%3D%22100%25%22%20stop-color%3D%22%23C98A1F%22/%3E%0A%3C/radialGradient%3E%0A%3C/defs%3E%0A%3Ccircle%20cx%3D%2250%22%20cy%3D%2250%22%20r%3D%2248%22%20fill%3D%22url%28%23g%29%22/%3E%0A%3Ccircle%20cx%3D%2250%22%20cy%3D%2250%22%20r%3D%2244%22%20fill%3D%22%230A1420%22%20stroke%3D%22%23234258%22%20stroke-width%3D%221.5%22/%3E%0A%3Ccircle%20cx%3D%2250%22%20cy%3D%2250%22%20r%3D%228%22%20fill%3D%22url%28%23b%29%22/%3E%0A%3Cpath%20d%3D%22M50%2018%20L53%2044%20L50%2050%20L47%2044%20Z%22%20fill%3D%22%23FBD34D%22/%3E%0A%3Cpath%20d%3D%22M50%2082%20L47%2056%20L50%2050%20L53%2056%20Z%22%20fill%3D%22%23FBD34D%22/%3E%0A%3Cpath%20d%3D%22M18%2050%20L44%2047%20L50%2050%20L44%2053%20Z%22%20fill%3D%22%23FBD34D%22/%3E%0A%3Cpath%20d%3D%22M82%2050%20L56%2053%20L50%2050%20L56%2047%20Z%22%20fill%3D%22%23FBD34D%22/%3E%0A%3Ccircle%20cx%3D%2250%22%20cy%3D%2250%22%20r%3D%2226%22%20fill%3D%22none%22%20stroke%3D%22%23FBD34D%22%20stroke-width%3D%220.8%22%20stroke-opacity%3D%220.35%22%20stroke-dasharray%3D%222%204%22/%3E%0A%3C/svg%3E",
}

# Extra badge detail shown when a player taps into a badge on the site
# (description / condition / effect). Effect is None across the board
# for now — badges are collectibles/proof-of-progress only, no mechanical
# bonus yet. Keyed by badge name, same as BADGE_IMAGES.
BADGE_INFO = {
    "Leaf Badge": {
        "description": "Awarded for besting the Greenwood Gym — proof you can hold "
                        "your own against Nature-type Pokémon in a real gauntlet, "
                        "not just a single battle.",
        "condition":   "Clear the Greenwood Gym: defeat all gym elders, then Gym "
                        "Leader Levin.",
        "effect":      None,
    },
    "Wave Badge": {
        "description": "Awarded for besting the Hydro Gym — proof you can read the "
                        "tide of a Water-type battle and come out ahead.",
        "condition":   "Clear the Hydro Gym: defeat all gym elders, then Gym "
                        "Leader Eren.",
        "effect":      None,
    },
    "Genesis": {
        "description": "Marks the trainers who were here before launch — the "
                        "\"One of us\" achievement, given alongside a legacy egg "
                        "found nowhere else.",
        "condition":   "Legacy-only. Automatically granted to trainers who had a "
                        "real account before the pre-launch wipe — this badge can "
                        "no longer be earned by new trainers.",
        "effect":      None,
    },
}

# Non-gym badges — earned some other way (legacy grant, future events,
# etc.), shown in the grid tagged "Legacy" so new players understand
# why it's permanently locked for them rather than assuming it's a
# gym they haven't found yet. Add entries here as more of these show up.
SPECIAL_BADGES = [
    {"badge_name": "Genesis", "source_label": "Legacy"},
]


def all_badges_status(player) -> list[dict]:
    """
    Every badge in the game — one per gym in GYMS, plus any non-gym
    entries in SPECIAL_BADGES (e.g. Genesis) — each tagged with whether
    this player has earned it. Used by the site's badge grid so it can
    show the full set — locked greyed-out, unlocked in color — instead
    of only ever showing badges the player already has.

    Gyms come first (GYMS dict order — Greenwood, then Hydro, etc.) so
    the grid has a stable, sensible progression order; special badges
    are appended after, tagged with their source_label (e.g. "Legacy")
    so a badge that isn't tied to any gym doesn't read as "a gym I
    haven't found yet."
    """
    earned = set(getattr(player, "badges", None) or [])
    out = []
    for zone_id, gym in GYMS.items():
        badge_name = gym.get("badge", f"{gym.get('leader', '???')} Badge")
        info = BADGE_INFO.get(badge_name, {})
        out.append({
            "zone_id":     zone_id,
            "town_name":   gym.get("town_name", ""),
            "leader":      gym.get("leader", ""),
            "leader_type": gym.get("leader_type", ""),
            "badge_name":  badge_name,
            "earned":      badge_name in earned,
            "image":       BADGE_IMAGES.get(badge_name, ""),
            "description": info.get("description", ""),
            "condition":   info.get("condition", ""),
            "effect":      info.get("effect"),
        })

    for special in SPECIAL_BADGES:
        badge_name = special["badge_name"]
        info = BADGE_INFO.get(badge_name, {})
        out.append({
            "zone_id":     None,
            "town_name":   "",
            "leader":      "",
            "leader_type": "",
            "badge_name":  badge_name,
            "earned":      badge_name in earned,
            "image":       BADGE_IMAGES.get(badge_name, ""),
            "description": info.get("description", ""),
            "condition":   info.get("condition", ""),
            "effect":      info.get("effect"),
            "source_label": special.get("source_label"),
        })

    return out


def all_gyms_status(player) -> list[dict]:
    """
    Every gym in GYMS, tagged open/locked for this player, with the
    fields the site's Gyms list + detail panel read (see loadGyms /
    openGymPanel in web/index.html). Used by site_actions.handle_get_gyms.

    There is no level requirement in the gym code today (gym_enter has
    no gate), so a gym is "open" for anyone who has a party and "locked"
    for visitors with none (logged out / not registered), which is what
    handle_get_gyms passes in for them.
    """
    earned  = set(getattr(player, "badges", None) or [])
    has_party = bool(getattr(player, "party", None))
    out = []
    for zone_id, gym in GYMS.items():
        badge_name = gym.get("badge", f"{gym.get('leader', '???')} Badge")
        info = BADGE_INFO.get(badge_name, {})
        out.append({
            "zone_id":     zone_id,
            "town_name":   gym.get("town_name", ""),
            "leader":      gym.get("leader", ""),
            "leader_type": gym.get("leader_type", ""),
            "badge_name":  badge_name,
            "image":       BADGE_IMAGES.get(badge_name, ""),
            "description": info.get("description", ""),
            "requirement": "Have a Pokémon in your party",
            "status":      "open" if has_party else "locked",
            "cleared":     badge_name in earned,
        })
    return out


# ============================================================
# STATE HELPERS
# ============================================================

def clear_gym_state(db, sender: str):
    for key in ("gym_round", "gym_zone", "gym_used_names"):
        db.delete_meta(sender, key)


# ============================================================
# ENTRY (.gym)
# ============================================================

def gym_enter(db, sender: str, player, session) -> str:
    """Called directly from .gym — no NPC gate, no entry fee."""
    from combat_session import STATE_GYM

    zone_id = getattr(player, "zone", "") or ""
    gym = GYMS.get(zone_id)
    if not gym:
        return "_There's no gym here._"

    clear_gym_state(db, sender)
    db.set_meta(sender, "gym_round", "1")
    db.set_meta(sender, "gym_zone", zone_id)
    session.transition(STATE_GYM)

    town   = gym["town_name"]
    leader = gym["leader"]
    return (
        f"🏛️ _You are entering {town} Gym, prepare yourself!_\n"
        f"_You must defeat the other elders before you can face Gym Leader {leader}!_\n\n"
        f"_Use_ `.next` _to begin._"
    )


# ============================================================
# NEXT ROUND (.next, shared with arena but routed separately)
# ============================================================

def gym_next(db, sender: str, player, session, direct_send=None, group_jid=None) -> str:
    round_str = db.get_meta(sender, "gym_round")
    if not round_str:
        return None
    current_round = int(round_str)

    zone_id = db.get_meta(sender, "gym_zone") or getattr(player, "zone", "")
    gym = GYMS.get(zone_id)
    if not gym:
        return None

    elder_count = gym.get("elder_count", 2)
    ace_level   = max((p.level for p in player.party if not p.is_fainted()), default=1)
    is_final    = current_round > elder_count

    if not is_final:
        used_raw = db.get_meta(sender, "gym_used_names") or ""
        used     = [n for n in used_raw.split(",") if n]
        name_pool = gym.get("elder_names", [])
        pool_names = [n for n in name_pool if n not in used] or name_pool
        trainer = random.choice(pool_names)
        used.append(trainer)
        db.set_meta(sender, "gym_used_names", ",".join(used))

        team_size = random.choice([2, 3])
        team = _build_team(db, ace_level, team_size, gym["pool"])
    else:
        trainer   = gym["leader"]
        team_size = gym.get("leader_team_size", 3)
        team = _build_team(db, ace_level + 2, team_size, gym.get("leader_pool") or gym["pool"])

    # Arm session (STATE_GYM_PENDING) — battle not started yet, blocks .atk etc.
    session.arm_trainer_battle(trainer, team, current_round)
    from combat_session import STATE_GYM_PENDING
    session.transition(STATE_GYM_PENDING)
    session.battle_context = "gym"

    PLAYER_SLOTS = 6
    p_alive  = sum(1 for p in player.party if not p.is_fainted())
    p_dots   = "⚈" * p_alive + "⚆" * (PLAYER_SLOTS - p_alive)
    t_dots   = "⚈" * len(team) + "⚆" * (team_size - len(team))

    first    = team[0]
    mon_name = first["name"].capitalize()
    header   = (f"⚔️ *Gym Leader {trainer}*" if is_final
                else f"⚔️ *Round {current_round} of {elder_count}*")

    msg1 = (
        f"{header}\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"{'Gym Leader' if is_final else 'Elder'} *{trainer}* has challenged you!\n\n"
        f"You: {p_dots}  |  {trainer}: {t_dots}\n\n"
        f"_Battle starts in 5 seconds..._"
    )

    if direct_send:
        import threading, time
        from battle import battle_image_marker
        active = player.party[player.active_slot]
        t_name = trainer
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
                import sys, traceback
                print(f"[GYM] _send_begin thread error: {e}", file=sys.stderr, flush=True)
                traceback.print_exc(file=sys.stderr)

        threading.Thread(target=_send_begin, daemon=True).start()

    return msg1


# ============================================================
# ROUND WON
# ============================================================

def gym_round_won(db, sender: str, player, session) -> str:
    round_str = db.get_meta(sender, "gym_round")
    if not round_str:
        return ""
    current_round = int(round_str)

    zone_id = db.get_meta(sender, "gym_zone") or getattr(player, "zone", "")
    gym = GYMS.get(zone_id, {})
    elder_count = gym.get("elder_count", 2)
    leader      = gym.get("leader", "the Gym Leader")
    badge       = gym.get("badge", f"{leader} Badge")

    if current_round > elder_count:
        # Leader defeated — gym cleared!
        clear_gym_state(db, sender)
        from combat_session import STATE_EXPLORING
        session.transition(STATE_EXPLORING)
        session.clear_arena()

        if not hasattr(player, "badges") or player.badges is None:
            player.badges = []
        already_had = badge in player.badges
        if not already_had:
            player.badges.append(badge)
            reward_line = f"🎖️ You earned the *{badge}*!"
        else:
            reward_line = "_(You already hold this badge — no duplicate awarded.)_"

        quest_line = ""
        if zone_id == "greenwood_town":
            gq = player.get_quest("greenwood_1")
            if gq and gq.status != "complete":
                player.complete_quest("greenwood_1")
                reward_items = gq.reward if isinstance(gq.reward, dict) else {}
                for item, qty in reward_items.items():
                    player.give_item(item, qty)
                reward_list = "\n".join(
                    f"  • {item} × {qty}" for item, qty in reward_items.items()
                )
                quest_line = (
                    f"\n\n✅ *Quest Complete: \"{gq.title}\"*\n"
                    f"You have received:\n{reward_list}"
                )

        return (
            f"🏆 *Gym Cleared!*\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"You defeated Gym Leader *{leader}*!\n\n"
            f"{reward_line}"
            f"{quest_line}"
        )

    # Elder defeated — advance to next round
    next_round = current_round + 1
    db.set_meta(sender, "gym_round", str(next_round))
    trainer = getattr(session, "arena_trainer_name", "the elder") or "the elder"
    if next_round > elder_count:
        hint = f"_Use_ `.next` _to face Gym Leader {leader}!_"
    else:
        hint = "_Use_ `.next` _for your next challenger._"
    return (
        f"⚔️ *{trainer} defeated!*\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"{hint}"
    )


# ============================================================
# LOSS
# ============================================================

def gym_loss(db, sender: str, player, session) -> str:
    clear_gym_state(db, sender)
    return (
        f"💀 *You were defeated.*\n"
        f"_The gym ejects you — heal up and challenge it again whenever you're ready._"
    )


# ============================================================
# INTERNAL HELPERS
# ============================================================

def _build_team(db, player_level: int, team_size: int, pool: list) -> list[dict]:
    from pokeapi import get_full
    from encounters import build_wild_monster

    level_min = max(1, player_level - 2)
    level_max = player_level + 2
    species_pool = random.sample(pool, min(team_size * 2, len(pool))) if len(pool) >= team_size else list(pool)
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
