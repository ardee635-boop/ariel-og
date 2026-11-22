# Niflheim duels (Package 1.6): player vs player on the same Attack / Defend / Potion rules as hunts.
# Simultaneous rounds: both choose, the bot resolves and posts HP. No XP, coins or wager in Session 1.
# State lives in its own table (store.save_duel). All numbers come from config.json ("duel").
import math
import sys
import threading
import time
import uuid

from . import combat
from . import config as cfg
from . import items as I
from . import live
from . import store

_locks = {}
_locks_guard = threading.Lock()


def _lock(duel_id):
    with _locks_guard:
        return _locks.setdefault(duel_id, threading.RLock())


def _dc():
    return cfg.get("duel", {})


def busy_reason(db, sender):
    """Why this player can't join a duel right now, or None."""
    if store.load_fight(db, sender):
        return "in a fight"
    if store.load_journey(db, sender):
        return "travelling"
    if store.load_duel(db, sender):
        return "already in a duel or invite"
    return None


def active_duel(db, sender):
    d = store.load_duel(db, sender)
    return d if d and d["status"] == "active" else None


def _name(db, sender):
    p = store.load_player(db, sender)
    return p["name"] if p else "?"


def _side(duel, sender):
    return "a" if duel["a"] == sender else "b"


def _other(side):
    return "b" if side == "a" else "a"


def _push(push, duel, msgs):
    if push:
        for m in msgs:
            push(m, group_jid=duel["group_jid"], allow_dm=True)


# ── invite / accept / decline ─────────────────────────────────────────────

def invite(db, challenger, target, group_jid, push=None, now=None, arm=True):
    now = time.time() if now is None else now
    if target == challenger:
        return "You can't duel yourself."
    me, foe = store.load_player(db, challenger), store.load_player(db, target)
    if not foe:
        return "That player isn't registered in Niflheim."
    why = busy_reason(db, challenger)
    if why:
        return f"You can't start a duel while you're {why}."
    why = busy_reason(db, target)
    if why:
        return f"{foe['name']} can't be challenged right now ({why})."
    if me["hp"] <= 0 or foe["hp"] <= 0:
        who = me["name"] if me["hp"] <= 0 else foe["name"]
        return f"{who} has no HP left. Heal up first (enter a town or use a potion)."
    secs = int(_dc().get("invite_seconds", 60))
    duel = {"id": uuid.uuid4().hex[:10], "group_jid": group_jid, "a": challenger, "b": target,
            "status": "invited", "created": now, "expires": now + secs, "round": 0,
            "round_start": 0, "actions": {"a": None, "b": None}}
    store.save_duel(db, duel)
    live.register(group_jid, challenger)
    live.register(group_jid, target)
    if arm:
        arm_timer(db, duel["id"], push)
    return (f"⚔️ *{me['name']}* challenges *{foe['name']}* to a duel!\n"
            f"{foe['name']}: .accept or .decline ({secs}s)")


def respond(db, sender, group_jid, accept, push=None, now=None, arm=True):
    d = store.load_duel(db, sender)
    if not d or d["status"] != "invited" or d["b"] != sender:
        return "You have no pending duel invite."
    if d["group_jid"] != group_jid:
        return "That duel invite was sent in a different group."
    with _lock(d["id"]):
        now = time.time() if now is None else now
        d = store.load_duel_by_id(db, d["id"])
        if not d or d["status"] != "invited":
            return "You have no pending duel invite."
        if now >= d["expires"]:
            store.delete_duel(db, d)
            return "That duel invite has expired."
        a_name, b_name = _name(db, d["a"]), _name(db, d["b"])
        if not accept:
            store.delete_duel(db, d)
            return f"🚫 {b_name} declined {a_name}'s duel."
        for s in (d["a"], d["b"]):
            if store.load_fight(db, s) or store.load_journey(db, s):
                store.delete_duel(db, d)
                return "The duel is off: a player is busy (fighting or travelling)."
        pa, pb = store.load_player(db, d["a"]), store.load_player(db, d["b"])
        if pa["hp"] <= 0 or pb["hp"] <= 0:
            store.delete_duel(db, d)
            return "The duel is off: a player has no HP left."
        d["status"], d["round"], d["round_start"] = "active", 1, now
        d["actions"] = {"a": None, "b": None}
        store.save_duel(db, d)
        if arm:
            arm_timer(db, d["id"], push)
        secs = int(_dc().get("round_seconds", 30))
        cap = int(_dc().get("round_cap", 12))
        return (f"⚔️ *DUEL!* {a_name} vs {b_name}\n"
                f"❤️ {a_name} {pa['hp']}/{I.final_max_hp(pa)} | {b_name} {pb['hp']}/{I.final_max_hp(pb)}\n\n"
                f"Both choose: .attack  .defend  .potion\n"
                f"_Round {secs}s · no action = auto-attack · max {cap} rounds._")


# ── rounds ────────────────────────────────────────────────────────────────

def act(db, sender, action, arg=None, now=None):
    """Player picks an action in an active duel. Returns (ok, msgs)."""
    d = active_duel(db, sender)
    if not d:
        return False, ["You're not in a duel."]
    with _lock(d["id"]):
        d = store.load_duel_by_id(db, d["id"])
        if not d or d["status"] != "active":
            return False, ["That duel is over."]
        side = _side(d, sender)
        if d["actions"][side]:
            return False, ["You've already chosen for this round. Waiting for your opponent."]
        if action == "potion":
            p = store.load_player(db, sender)
            if not combat._pick_potion(p, arg):
                return False, ["You don't have that potion. Choose again: .attack  .defend  .potion"
                               if arg else "You have no potions. Choose again: .attack  .defend"]
        d["actions"][side] = {"act": action, "arg": arg}
        if d["actions"]["a"] and d["actions"]["b"]:
            return True, _resolve(db, d, now=time.time() if now is None else now)
        store.save_duel(db, d)
        opp = _name(db, d[_other(side)])
        return True, [f"✅ {_name(db, sender)} is ready. Waiting for {opp}..."]


def _resolve(db, d, now):
    """Resolve the current round (missing actions = attack). Returns messages. Caller holds the lock."""
    dc = _dc()
    mult = float(dc.get("defend_multiplier", 0.5))
    pl = {"a": store.load_player(db, d["a"]), "b": store.load_player(db, d["b"])}
    nm = {s: pl[s]["name"] for s in pl}
    acts = {s: (d["actions"][s] or {"act": "attack", "arg": None}) for s in pl}
    auto = {s: d["actions"][s] is None for s in pl}
    lines = [f"⚔️ *Duel — Round {d['round']}*"]
    dmg = {"a": 0, "b": 0}              # damage each side deals this round
    heal_txt = {}

    for s in pl:                        # potions first (heals apply before damage)
        a = acts[s]
        if a["act"] == "potion":
            name = combat._pick_potion(pl[s], a["arg"])
            if name:
                heal = int(combat._cc().get("potions", {}).get(name, 0))
                pl[s]["inventory"][name] -= 1
                if pl[s]["inventory"][name] <= 0:
                    del pl[s]["inventory"][name]
                before = pl[s]["hp"]
                pl[s]["hp"] = min(I.final_max_hp(pl[s]), pl[s]["hp"] + heal)
                heal_txt[s] = f"🧪 {nm[s]} drinks a {name} (+{pl[s]['hp'] - before} HP)."
            else:
                heal_txt[s] = f"🧪 {nm[s]} fumbles for a potion but has none."
    for s in pl:
        o = _other(s)
        if acts[s]["act"] == "attack":
            x = combat.player_damage(pl[s])
            if acts[o]["act"] == "defend":
                x = int(math.floor(x * mult))
            dmg[s] = x
    for s in pl:
        o = _other(s)
        a = acts[s]["act"]
        if a == "attack":
            lines.append(f"🗡️ {nm[s]} attacks {nm[o]} for {dmg[s]}." + (" (auto)" if auto[s] else "")
                         + (" (blocked half)" if acts[o]["act"] == "defend" else ""))
        elif a == "defend":
            lines.append(f"🛡️ {nm[s]} defends.")
        else:
            lines.append(heal_txt[s])
    for s in pl:
        pl[_other(s)]["hp"] = max(0, pl[_other(s)]["hp"] - dmg[s])

    mx = {s: I.final_max_hp(pl[s]) for s in pl}
    lines.append(f"❤️ {nm['a']} {pl['a']['hp']}/{mx['a']} | {nm['b']} {pl['b']['hp']}/{mx['b']}")

    winner, reason = None, None            # winner: 'a' | 'b' | 'draw' | None
    dead = {s: pl[s]["hp"] <= 0 for s in pl}
    if dead["a"] and dead["b"]:
        winner, reason = "draw", "Both fighters fall at the same time!"
    elif dead["a"] or dead["b"]:
        winner = "b" if dead["a"] else "a"
        reason = f"{nm[_other(winner)]} is out of HP."
    elif d["round"] >= int(dc.get("round_cap", 12)):
        left = {s: pl[s]["hp"] / mx[s] for s in pl}
        # compare with cross-multiplication so equal percentages are an exact tie
        lhs, rhs = pl["a"]["hp"] * mx["b"], pl["b"]["hp"] * mx["a"]
        winner = "draw" if lhs == rhs else ("a" if lhs > rhs else "b")
        reason = f"Round limit reached — {nm['a']} {left['a']*100:.0f}% vs {nm['b']} {left['b']*100:.0f}% HP."

    if winner:
        for s in pl:
            if winner in ("a", "b"):
                key = "duel_wins" if s == winner else "duel_losses"
                pl[s][key] = pl[s].get(key, 0) + 1
            store.save_player(db, d[s], pl[s])
        store.delete_duel(db, d)
        lines += ["", f"🏆 *{nm[winner]} wins the duel!*" if winner != "draw" else "🤝 *The duel is a draw!*", reason]
        return ["\n".join(lines)]

    for s in pl:
        store.save_player(db, d[s], pl[s])
    d["round"] += 1
    d["round_start"] = now
    d["actions"] = {"a": None, "b": None}
    store.save_duel(db, d)
    lines.append("\nChoose: .attack  .defend  .potion")
    return ["\n".join(lines)]


# ── timeouts (shared by push timer and next-message catch-up) ─────────────

def tick_duel(db, duel_id, now=None):
    """Expire a stale invite or auto-attack for overdue rounds. Idempotent. Returns messages."""
    msgs = []
    now = time.time() if now is None else now
    with _lock(duel_id):
        for _ in range(100):
            d = store.load_duel_by_id(db, duel_id)
            if not d:
                break
            if d["status"] == "invited":
                if now >= d["expires"]:
                    store.delete_duel(db, d)
                    msgs.append(f"⌛ {_name(db, d['a'])}'s duel invite to {_name(db, d['b'])} expired.")
                break
            secs = float(_dc().get("round_seconds", 30))
            if now < d["round_start"] + secs:
                break
            out = _resolve(db, d, now=d["round_start"] + secs)
            out[0] = "⏱️ _Time's up — missing actions become auto-attacks._\n" + out[0]
            msgs += out
    return msgs


def tick_for(db, sender, now=None):
    d = store.load_duel(db, sender)
    return tick_duel(db, d["id"], now) if d else []


def cancel_for(db, sender):
    d = store.load_duel(db, sender)
    if d:
        store.delete_duel(db, d)


def _get_lock(sender):
    fn = getattr(sys.modules.get("__main__"), "_get_sender_lock", None)
    return fn(sender) if fn else None


def arm_timer(db, duel_id, push=None):
    d = store.load_duel_by_id(db, duel_id)
    if not d:
        return
    due = d["expires"] if d["status"] == "invited" else d["round_start"] + float(_dc().get("round_seconds", 30))

    def _fire():
        try:
            dd = store.load_duel_by_id(db, duel_id)
            if dd:
                _push(push, dd, tick_duel(db, duel_id))
        except Exception as e:
            print(f"[NIFLHEIM DUEL TIMER] tick failed for {duel_id}: {e}", file=sys.stderr, flush=True)
        try:
            if store.load_duel_by_id(db, duel_id):
                arm_timer(db, duel_id, push)
        except Exception as e:
            print(f"[NIFLHEIM DUEL TIMER] re-arm failed for {duel_id}: {e}", file=sys.stderr, flush=True)

    t = threading.Timer(max(0.3, due - time.time() + 0.2), _fire)
    t.daemon = True
    t.start()
