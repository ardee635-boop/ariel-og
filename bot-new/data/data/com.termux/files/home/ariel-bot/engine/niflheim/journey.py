# Niflheim timed journeys (Pokémon-style design, own storage). One active journey per player.
# resolve() is the single idempotent step used by BOTH the push timer and the catch-up that runs
# on the player's next message, so an arrival can never happen twice.
import random
import sys
import threading
import time

from . import config as cfg
from . import items as I
from . import player as P
from . import store
from . import world

# Package 1.4 sets this to start a real fight: fn(sender, player, journey) -> message string or None.
fight_handler = None

def _get_lock(sender):
    """bridge.py runs as __main__, so its per-sender lock lives there. Importing `bridge` from
    here would load a second copy (second router + DB), so read it off __main__ instead.
    None under tests."""
    fn = getattr(sys.modules.get("__main__"), "_get_sender_lock", None)
    return fn(sender) if fn else None


def _roll_event(total, rng):
    ev = cfg.get("journey_events", {})
    r = rng.random()
    fight = float(ev.get("fight_chance", 0.25))
    if r < fight:
        kind = "fight"
    elif r < fight + (1 - fight) * float(ev.get("flavour_chance", 0.4)):
        kind = "flavour"
    else:
        return {"kind": None, "at": 0, "done": True}
    return {"kind": kind, "at": total * float(ev.get("event_point", 0.5)), "done": False,
            "text": rng.choice(ev.get("flavour_lines", [""])) if kind == "flavour" else ""}


def get_active(db, sender):
    return store.load_journey(db, sender)


def start(db, sender, player, direction, group_jid=None, now=None, rng=random, arm=True, push=None):
    """Begin a journey. Returns (ok, message). Caller has already checked registration."""
    if store.load_fight(db, sender):
        return False, "You can't travel while in a fight!"
    _d = store.load_duel(db, sender)
    if _d and _d["status"] == "active":
        return False, "You can't travel during a duel!"
    if store.load_journey(db, sender):
        return False, "You're already traveling. Use .end to stop."
    loc = world.get(player["location"])
    dest_id = world.exit_dest(loc, direction)
    if not dest_id:
        return False, '"Looks like a dead end..." There is no path that way.'
    dest = world.get(dest_id)
    if not world.requirements_met(player, dest):
        return False, "🔒 That path is locked."
    total = world.travel_time(player["location"], dest_id)
    now = time.time() if now is None else now
    journey = {"origin": player["location"], "direction": direction, "destination": dest_id,
               "total": total, "start": now, "group_jid": group_jid,
               "event": _roll_event(total, rng)}
    store.save_journey(db, sender, journey)
    if arm:
        arm_timer(db, sender, _next_due(journey) - time.time(), push)
    return True, (f"You leave {loc['name']}, heading {direction}...\n\n"
                  f"Travel time: {int(total)}s\nUse .end to stop\nUse .zone to see more details")


def _next_due(j):
    due = j["start"] + j["total"]
    ev = j.get("event") or {}
    if ev.get("kind") and not ev.get("done"):
        due = min(due, j["start"] + ev["at"])
    return due


def resolve(db, sender, now=None):
    """Process everything that is due (event first, then arrival). Returns a list of messages."""
    j = store.load_journey(db, sender)
    if not j:
        return []
    pl = store.load_player(db, sender)
    if not pl:
        store.delete_journey(db, sender)
        return []
    P.normalize(pl)
    now = time.time() if now is None else now
    msgs = []
    ev = j.get("event") or {}
    if ev.get("kind") and not ev.get("done") and now >= j["start"] + ev["at"]:
        ev["done"] = True
        if ev["kind"] == "flavour":
            msgs.append(f"✦ {ev['text']}")
        elif fight_handler:
            m = fight_handler(sender, pl, j)
            if m:
                msgs.append(m)
            pl = store.load_player(db, sender) or pl          # the fight changed HP/XP/coins: don't overwrite them
            P.normalize(pl)
            if store.load_journey(db, sender) is None:        # a lost fight sends you home and ends the walk
                return msgs
        else:
            msgs.append(f"✦ {cfg.get('journey_events', {}).get('fight_placeholder', '')}")
    # A journey-event fight pauses the walk: arrival waits until the fight is over (Package 1.4).
    if now >= j["start"] + j["total"] and not store.load_fight(db, sender):
        origin, dest = world.get(j["origin"]), world.get(j["destination"])
        pl["location"] = dest["id"]
        if dest["id"] not in pl["discovered"]:
            pl["discovered"].append(dest["id"])
        text = (f"You have left {origin['name']}...\n\n...you are now in {dest['name']}.\n\n")
        if world.is_town(dest["id"]) and pl["hp"] < I.final_max_hp(pl):
            pl["hp"] = I.final_max_hp(pl)
            text += "❤️ You feel fully rested.\n\n"
        msgs.append(text + "Use .zone to see more info")
        store.delete_journey(db, sender)
        store.save_player(db, sender, pl)
    else:
        store.save_journey(db, sender, j)
    return msgs


def end(db, sender, now=None):
    """.end: turn back mid-journey (stay in the origin). If it already arrived, that counts as arrival."""
    j = store.load_journey(db, sender)
    if not j:
        return "You're not currently traveling."
    if store.load_fight(db, sender):
        return "You can't turn back in the middle of a fight!"
    msgs = resolve(db, sender, now)
    if store.load_journey(db, sender) is None:        # it had arrived
        return "\n\n".join(msgs)
    store.delete_journey(db, sender)
    origin = world.get(j["origin"])
    return f"You stop and turn back before reaching your destination.\n\nCurrent location: {origin['name']}"


def arm_timer(db, sender, delay, push=None):
    """Push the event/arrival to the chat the journey started in, without waiting for a message."""
    def _fire():
        lock = _get_lock(sender)
        if lock:
            lock.acquire()
        try:
            j = store.load_journey(db, sender)
            if j:
                for m in resolve(db, sender):
                    if push:
                        push(m, group_jid=j.get("group_jid") or sender, allow_dm=True)
        except Exception as e:
            print(f"[NIFLHEIM TIMER] tick failed for {sender}: {e}", file=sys.stderr, flush=True)
        finally:
            if lock:
                lock.release()
        try:
            j = store.load_journey(db, sender)
            if j:
                d = _next_due(j) - time.time()
                if store.load_fight(db, sender):      # arrival is on hold during a fight: poll slowly
                    d = max(d, float(cfg.get("combat", {}).get("fight_poll_seconds", 2)))
                arm_timer(db, sender, d, push)
        except Exception as e:
            print(f"[NIFLHEIM TIMER] re-arm failed for {sender}: {e}", file=sys.stderr, flush=True)

    t = threading.Timer(max(0.3, delay + 0.2), _fire)
    t.daemon = True
    t.start()
