# Niflheim combat engine (Package 1.4). Deterministic, three actions only: attack, defend, potion.
# Shared by .hunt and journey-event fights; duels and bosses (1.6 / later) reuse round logic.
# All numbers come from config.json ("combat") and data/monsters.json.
#
# Return convention: functions that advance a fight return (main_msgs, levelup_msgs).
#   main_msgs   - round / result text, in order
#   levelup_msgs- one string per level gained; the caller sends each as its OWN WhatsApp message.
import json
import math
import os
import random
import sys
import threading
import time

from . import config as cfg
from . import items as I
from . import live
from . import player as P
from . import store

_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
_mon = None
_boss = None


def _cc():
    return cfg.get("combat", {})


def catalogue(reload=False):
    global _mon
    if _mon is None or reload:
        with open(os.path.join(_DATA_DIR, "monsters.json"), "r", encoding="utf-8") as f:
            _mon = json.load(f)
    return _mon


def boss_catalogue(reload=False):
    global _boss
    if _boss is None or reload:
        with open(os.path.join(_DATA_DIR, "bosses.json"), "r", encoding="utf-8") as f:
            _boss = json.load(f)
    return _boss


# ── numbers ───────────────────────────────────────────────────────────────

def player_damage(player):
    """FinalDamage = floor((15 + Level × 5) × (1 + ATK bonus)) — gear from items.json (Package 1.5)."""
    return I.final_damage(player)


def player_max_hp(player):
    """FinalMaxHP = floor(BaseMaxHP × (1 + HP bonus))."""
    return I.final_max_hp(player)


def _bar(hp, mx):
    return f"{max(0, hp)}/{mx}"


# ── fight lifecycle ───────────────────────────────────────────────────────

def active(db, sender):
    return store.load_fight(db, sender)


def start_fight(db, sender, player, group_jid=None, rng=random, push=None, arm=True, monster_id=None,
                source="hunt"):
    """Create a fight vs one catalogue monster. Returns the opening message."""
    cat = catalogue()["monsters"]
    m = next((x for x in cat if x["id"] == monster_id), None) if monster_id else rng.choice(cat)
    fight = {
        "kind": "monster", "source": source, "round": 1, "group_jid": group_jid,
        "round_start": time.time(),
        "monster": {"id": m["id"], "name": m["name"], "level": m["level"], "hp": m["hp"],
                    "max_hp": m["hp"], "damage": m["damage"], "xp": m["xp"],
                    "coins": m["coins"], "unique_item": m.get("unique_item")},
    }
    store.save_fight(db, sender, fight)
    live.register(group_jid, sender)
    if arm:
        arm_round_timer(db, sender, push)
    secs = int(_cc().get("round_seconds", 30))
    return (f"⚔️ *A wild {m['name']} appears!* (Lv {m['level']})\n"
            f"❤️ You {_bar(player['hp'], player_max_hp(player))} | 👹 {m['name']} {_bar(m['hp'], m['hp'])}\n\n"
            f"Choose: .attack  .defend  .potion\n_No action in {secs}s = auto-attack._")


def _pick_potion(player, arg):
    pots = _cc().get("potions", {})
    inv = player.get("inventory", {})
    arg = (arg or "").strip().lower()
    if arg:
        for name in pots:
            n = name.lower()
            if arg == n or arg == n.replace(" hp potion", "").replace(" potion", "") \
                    or (arg == "small" and n.startswith("small")) or (arg == "hp" and n == "hp potion"):
                return name if inv.get(name, 0) > 0 else None
        return None
    for name in _cc().get("default_potion_order", list(pots)):
        if inv.get(name, 0) > 0:
            return name
    return None


def _roll_rewards(player, mon, rng):
    """XP always; coins chance-based; one item roll per kill (20% unique / 5% general / 75% none)."""
    c = _cc()
    lines = []
    xp = rng.randint(mon["xp"][0], mon["xp"][1])
    levelups = P.grant_xp(player, xp)
    lines.append(f"✨ +{xp} XP")
    if rng.random() < float(mon.get("coin_chance", c.get("coin_chance", 0.7))):
        coins = rng.randint(mon["coins"][0], mon["coins"][1])
        P.grant_coins(player, coins)
        lines.append(f"🪙 +{coins} coins")
    r = rng.random()
    item = None
    du = float(mon.get("drop_unique", c.get("drop_unique", 0.20)))
    dg = float(mon.get("drop_general", c.get("drop_general", 0.05)))
    if r < du:
        item = mon.get("unique_item")
    elif r < du + dg:
        pool = catalogue().get("general_pool", [])
        item = rng.choice(pool) if pool else None
    if item:
        inv = player.setdefault("inventory", {})
        inv[item] = inv.get(item, 0) + 1
        lines.append(f"🎁 Dropped: {item}")
    return lines, levelups


def _round(db, sender, fight, pl, action, arg, rng, now=None):
    """Resolve one round. Player acts first; if the monster survives it attacks (always).
    Returns (main_msgs, levelup_msgs, ended)."""
    c = _cc()
    mon = fight["monster"]
    rd = fight["round"]
    lines = [f"⚔️ *Round {rd}* — You vs {mon['name']}"]
    defending = False

    if action == "defend":
        defending = True
        lines.append("🛡️ You brace yourself.")
    elif action == "potion":
        name = _pick_potion(pl, arg)
        heal = int(c.get("potions", {}).get(name, 0)) if name else 0
        pl["inventory"][name] -= 1
        if pl["inventory"][name] <= 0:
            del pl["inventory"][name]
        before = pl["hp"]
        pl["hp"] = min(player_max_hp(pl), pl["hp"] + heal)
        lines.append(f"🧪 You drink a {name}: +{pl['hp'] - before} HP.")
    else:
        dmg = player_damage(pl)
        mon["hp"] = max(0, mon["hp"] - dmg)
        lines.append(f"🗡️ You hit {mon['name']} for {dmg}.")

    if mon["hp"] <= 0:
        lines.append(f"💀 {mon['name']} is defeated!")
        rl, lvl = _roll_rewards(pl, mon, rng)
        lines.append(f"❤️ You {_bar(pl['hp'], player_max_hp(pl))}")
        lines += ["", "🏆 *Victory!*"] + rl
        store.save_player(db, sender, pl)
        store.delete_fight(db, sender)
        return ["\n".join(lines)], lvl, True

    hit = rng.randint(mon["damage"][0], mon["damage"][1])
    if defending:
        hit = int(math.floor(hit * float(c.get("defend_multiplier", 0.5))))
    pl["hp"] = max(0, pl["hp"] - hit)
    lines.append(f"🩸 {mon['name']} hits you for {hit}." + (" (blocked half)" if defending else ""))

    if pl["hp"] <= 0:
        start = cfg.get("start", {})
        pl["location"] = start.get("location", "ash_town")
        pl["hp"] = player_max_hp(pl)
        lines.append("")
        lines.append(f"☠️ *You were defeated by the {mon['name']}.*")
        lines.append(f"You wake up in {P.location_name(pl['location'])} with full HP.")
        store.save_player(db, sender, pl)
        store.delete_fight(db, sender)
        store.delete_journey(db, sender)         # a journey the fight interrupted is cancelled
        return ["\n".join(lines)], [], True

    lines.append(f"❤️ You {_bar(pl['hp'], player_max_hp(pl))} | 👹 {mon['name']} {_bar(mon['hp'], mon['max_hp'])}")
    fight["round"] = rd + 1
    fight["round_start"] = time.time() if now is None else now
    store.save_player(db, sender, pl)
    store.save_fight(db, sender, fight)
    lines.append("\nChoose: .attack  .defend  .potion")
    return ["\n".join(lines)], [], False


def act(db, sender, action, arg=None, rng=random):
    """Player's chosen action. Returns (ok, main_msgs, levelup_msgs)."""
    fight = store.load_fight(db, sender)
    if not fight:
        return False, ["You're not in a fight. Use .hunt outside town to find one."], []
    pl = store.load_player(db, sender)
    P.normalize(pl)
    if action == "potion" and not _pick_potion(pl, arg):
        if arg:
            return False, [f"You don't have that potion. Choose again: .attack  .defend  .potion"], []
        return False, ["You have no potions. Choose again: .attack  .defend"], []
    main, lvl, _ = _round(db, sender, fight, pl, action, arg, rng)
    return True, main, lvl


def tick(db, sender, now=None, rng=random):
    """Auto-attack for every round whose timer ran out. Idempotent: safe from both the push timer
    and the catch-up on the player's next message. A player idle for several rounds gets each
    missed round resolved in order. Returns (main_msgs, levelup_msgs)."""
    main, lvls = [], []
    now = time.time() if now is None else now
    secs = float(_cc().get("round_seconds", 30))
    for _ in range(200):                                   # hard stop, a fight can't loop forever
        fight = store.load_fight(db, sender)
        if not fight or now < fight["round_start"] + secs:
            break
        pl = store.load_player(db, sender)
        if not pl:
            store.delete_fight(db, sender)
            break
        P.normalize(pl)
        m, l, ended = _round(db, sender, fight, pl, "attack", None, rng,
                             now=fight["round_start"] + secs)
        m[0] = "⏱️ _No action — auto-attack._\n" + m[0]
        main += m
        lvls += l
        if ended:
            break
    return main, lvls


def auto_fight(db, sender, player, group_jid=None, rng=random, monster_id=None, source="hunt"):
    """Session 2: ordinary encounters resolve by themselves (no manual turns on WhatsApp).
    Uses the same round maths as _round: attack every round, drink a potion when HP is low.
    Returns (main_msgs, levelup_msgs). The player dict is mutated and saved by _round."""
    cat = catalogue()["monsters"]
    m = next((x for x in cat if x["id"] == monster_id), None) if monster_id else rng.choice(cat)
    ac = cfg.get("auto_combat", {})
    fight = {"kind": "monster", "source": source, "round": 1, "group_jid": group_jid,
             "round_start": time.time(),
             "monster": {"id": m["id"], "name": m["name"], "level": m["level"], "hp": m["hp"],
                         "max_hp": m["hp"], "damage": m["damage"], "xp": m["xp"],
                         "coins": m["coins"], "unique_item": m.get("unique_item")}}
    store.save_fight(db, sender, fight)
    low = int(ac.get("potion_below_hp_pct", 30))
    last, levelups, rounds = [], [], 0
    for rounds in range(1, int(ac.get("max_rounds", 60)) + 1):
        potion = player["hp"] * 100 <= player_max_hp(player) * low and _pick_potion(player, None)
        last, lvl, ended = _round(db, sender, fight, player, "potion" if potion else "attack", None, rng)
        levelups += lvl
        if ended:
            break
    else:
        store.delete_fight(db, sender)
        return [f"⚔️ You encountered a *{m['name']}* (Lv {m['level']}).\nThe fight drags on and you both back away."], levelups
    # Short result card: no round-by-round text.
    text = last[0]
    won = fight["monster"]["hp"] <= 0
    out = [f"⚔️ You encountered a *{m['name']}* (Lv {m['level']}).", ""]
    if won:
        out.append(f"🏆 You killed the {m['name']}!")
        out.append(f"❤️ HP: {_bar(player['hp'], player_max_hp(player))}")
        rewards = text.split("🏆 *Victory!*", 1)[1].strip().splitlines() if "🏆 *Victory!*" in text else []
        if rewards:
            out += [""] + [l for l in rewards if l.strip()]
    else:
        out.append(f"☠️ The {m['name']} defeated you!")
        out.append(f"❤️ HP: {_bar(player['hp'], player_max_hp(player))} (you woke up in {P.location_name(player['location'])})")
    return ["\n".join(out)], levelups


# ── push timer ────────────────────────────────────────────────────────────

def _get_lock(sender):
    fn = getattr(sys.modules.get("__main__"), "_get_sender_lock", None)
    return fn(sender) if fn else None


def arm_round_timer(db, sender, push=None):
    """Fire the auto-attack at the end of the round timer and push to the chat the fight began in."""
    fight = store.load_fight(db, sender)
    if not fight:
        return
    delay = fight["round_start"] + float(_cc().get("round_seconds", 30)) - time.time()

    def _fire():
        lock = _get_lock(sender)
        if lock:
            lock.acquire()
        try:
            f = store.load_fight(db, sender)
            if f:
                main, lvls = tick(db, sender)
                if push:
                    for m in main + lvls:                  # each level-up is its own message
                        push(m, group_jid=f.get("group_jid") or sender, allow_dm=True)
        except Exception as e:
            print(f"[NIFLHEIM FIGHT TIMER] tick failed for {sender}: {e}", file=sys.stderr, flush=True)
        finally:
            if lock:
                lock.release()
        try:
            if store.load_fight(db, sender):
                arm_round_timer(db, sender, push)
        except Exception as e:
            print(f"[NIFLHEIM FIGHT TIMER] re-arm failed for {sender}: {e}", file=sys.stderr, flush=True)

    t = threading.Timer(max(0.3, delay + 0.2), _fire)
    t.daemon = True
    t.start()
