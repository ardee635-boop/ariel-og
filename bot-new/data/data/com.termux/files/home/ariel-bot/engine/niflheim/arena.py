# Niflheim Battle Arena (Session 2): server side of website battles.
# The website never decides rewards. It asks for a TICKET (which monster, the player's real stats),
# fights in the browser, then reports only the outcome. This module validates it and applies the
# rewards to the SAME player record WhatsApp uses (one character, one inventory).
# NOTE: the fight itself runs in the browser, so a determined cheater can still fake a win. The checks
# below (single-use ticket, expiry, minimum fight time, rewards decided here) limit the damage.
import math
import random
import secrets
import time

from . import combat
from . import config as cfg
from . import items as I
from . import player as P
from . import store


def _ac():
    return cfg.get("arena", {})


def player_summary(pl):
    return {"name": pl["name"], "level": pl["level"], "xp": pl["xp"], "xp_needed": P.xp_needed(pl["level"]),
            "hp": pl["hp"], "max_hp": I.final_max_hp(pl), "coins": pl["coins"],
            "location": P.location_name(pl["location"]), "damage": I.final_damage(pl),
            "equipped": pl.get("equipped", {}), "inventory": pl.get("inventory", {})}


def _load(db, sender):
    pl = store.load_player(db, sender)
    if pl:
        P.normalize(pl)
    return pl


def me(db, sender):
    pl = _load(db, sender)
    return {"player": player_summary(pl)} if pl else {"error": "You are not registered in Niflheim yet. Use .reg <name> on WhatsApp."}


def _public(t, pl):
    m = t["monster"]
    lo, hi = m["damage"]
    return {"ticket": t["id"], "boss": bool(m.get("boss")), "expires_in": max(0, int(t["expires"] - time.time())),
            "player": {"name": pl["name"], "level": pl["level"], "hp": max(1, pl["hp"]),
                       "max_hp": I.final_max_hp(pl), "damage": I.final_damage(pl)},
            "foe": {"id": m["id"], "name": m["name"], "level": m["level"], "hp": m["hp"],
                    "damage": (lo + hi) // 2, "rig": _ac().get("rig", {}).get(m["id"], "wolf")}}


def create_ticket(db, sender, monster_id=None, rng=random, now=None):
    """Returns (public_ticket_dict, None) or (None, error_text)."""
    pl = _load(db, sender)
    if not pl:
        return None, "You are not registered in Niflheim yet. Use .reg <name> on WhatsApp."
    cat = combat.catalogue()["monsters"] + combat.boss_catalogue()["bosses"]
    if monster_id:
        m = next((x for x in cat if x["id"] == monster_id), None)
    else:
        m = rng.choice(combat.catalogue()["monsters"])          # random fights are never bosses
    if not m:
        return None, "Unknown monster."
    now = time.time() if now is None else now
    t = {"id": secrets.token_urlsafe(12), "sender": sender, "monster": m, "created": now,
         "expires": now + float(_ac().get("ticket_ttl_seconds", 900))}
    store.save_ticket(db, t)
    return _public(t, pl), None


def boss_by_zone(zone):
    return [b for b in combat.boss_catalogue()["bosses"] if b["zone"] == zone]


def _cooldown_left(pl, boss_id, now=None):
    now = time.time() if now is None else now
    return max(0, int(float(pl.get("boss_cd", {}).get(boss_id, 0)) - now))


def _mins(sec):
    return f"{max(1, (sec + 59) // 60)} min"


def boss_ticket(db, sender, now=None):
    """Ticket for the boss of the zone the player is standing in. Returns (public_ticket, None) or (None, error)."""
    from . import journey, world
    pl = _load(db, sender)
    if not pl:
        return None, "You are not registered in Niflheim yet. Use .reg <n> on WhatsApp."
    if journey.get_active(db, sender):
        return None, "You can't face a boss while travelling. Use .end first."
    here = boss_by_zone(pl["location"])
    if not here:
        return None, "There is no boss in this zone. Use .dungeon to see where they live."
    b = here[0]
    left = _cooldown_left(pl, b["id"], now)
    if left:
        return None, f"{b['name']} is still recovering. Come back in {_mins(left)}."
    return create_ticket(db, sender, b["id"], now=now)


def boss_board(db, sender, now=None):
    """Text for .dungeon: every boss, where it lives, and whether you can fight it now."""
    pl = _load(db, sender)
    if not pl:
        return "You are not registered in Niflheim yet. Use .reg <n> to start."
    lines = ["🏰 *Boss Board*"]
    for b in combat.boss_catalogue()["bosses"]:
        left = _cooldown_left(pl, b["id"], now)
        status = f"recovering ({_mins(left)})" if left else ("ready, you are here! Use .boss" if pl["location"] == b["zone"] else "ready")
        lines.append(f"• *{b['name']}* (Lv {b['level']}) in {P.location_name(b['zone'])}: {status}")
    lines.append("Go to a boss's zone with .explore, then use .boss for a battle link.")
    return "\n".join(lines)


def get_ticket(db, sender, ticket_id, now=None):
    t = store.load_ticket(db, ticket_id)
    if not t or t["sender"] != sender:
        return {"error": "Battle ticket not found."}
    if (time.time() if now is None else now) > t["expires"]:
        store.delete_ticket(db, ticket_id)
        return {"error": "This battle ticket has expired. Ask Ariel for a new link."}
    pl = _load(db, sender)
    return _public(t, pl) if pl else {"error": "You are not registered in Niflheim yet."}


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def submit_result(db, sender, ticket_id, res, router=None, rng=random, now=None):
    """Apply a reported outcome. Returns a dict for the website: outcome, summary, rewards, player."""
    now = time.time() if now is None else now
    t = store.load_ticket(db, ticket_id)
    if not t or t["sender"] != sender:
        return {"error": "Battle ticket not found or already used."}
    store.delete_ticket(db, ticket_id)                      # single use, whatever happens next
    if now > t["expires"]:
        return {"error": "This battle ticket has expired."}
    pl = _load(db, sender)
    if not pl:
        return {"error": "You are not registered in Niflheim yet."}
    res = res or {}
    mon, maxhp = t["monster"], I.final_max_hp(pl)
    try:
        ph = int(_clamp(float(res.get("playerHp", 0)), 0, maxhp))
        fh = float(res.get("foeHp", mon["hp"]))
    except (TypeError, ValueError):
        return {"error": "Bad result."}
    won, time_up = bool(res.get("won")), bool(res.get("timeUp"))
    ac = _ac()

    if won:
        hits = math.ceil(mon["hp"] / max(1, I.final_damage(pl)))
        need = max(float(ac.get("min_win_seconds", 3)), hits * float(ac.get("seconds_per_hit", .45)) * float(ac.get("speed_margin", .8)))
        if fh > 0 or ph <= 0 or (now - t["created"]) < need:
            return {"error": "Result rejected.", "outcome": "rejected"}
        pl["hp"] = max(1, ph)
        lines, levelups = combat._roll_rewards(pl, mon, rng)
        if mon.get("boss"):
            pl.setdefault("boss_cd", {})[mon["id"]] = now + float(ac.get("boss_cooldown_seconds", 3600))
        store.save_player(db, sender, pl)
        if router:
            for m in levelups:                              # each level-up is its own WhatsApp message
                router._send_to(sender, m)
        return {"outcome": "win", "rewards": lines, "levelups": len(levelups), "player": player_summary(pl),
                "summary": f"{mon['name']} defeated! " + " · ".join(l.replace("*", "") for l in lines)
                           + (f" · Level up x{len(levelups)}!" if levelups else "")}
    if time_up:
        pl["hp"] = max(1, ph)
        store.save_player(db, sender, pl)
        return {"outcome": "timeup", "rewards": [], "player": player_summary(pl), "summary": "Time ran out. No rewards."}
    # defeat: same penalty as a lost WhatsApp fight
    pl["location"] = cfg.get("start", {}).get("location", "ash_town")
    pl["hp"] = I.final_max_hp(pl)
    store.save_player(db, sender, pl)
    store.delete_journey(db, sender)
    return {"outcome": "loss", "rewards": [], "player": player_summary(pl),
            "summary": f"Defeated by {mon['name']}. You wake up in {P.location_name(pl['location'])} with full HP."}
