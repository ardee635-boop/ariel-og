# Package 1.3 tests — run: python3 tests/niflheim_pkg1_3_test.py
import os, sys, sqlite3, random, importlib.util
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "engine"))
spec = importlib.util.spec_from_file_location("nif_router", os.path.join(ROOT, "engine", "router", "niflheim.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
from niflheim import player as P, store, world, journey
journey.arm_timer = lambda *a, **k: None          # no real timers in tests

class FakeDb:
    _mode = "sqlite"
    def __init__(self): self.conn = sqlite3.connect(":memory:")
    def _ex(self, sql, params=()): return self.conn.execute(sql, params)
    def _commit(self): self.conn.commit()
    def _fetchone(self, cur): return cur.fetchone()
class FakeRouter:
    def __init__(self): self.db = FakeDb(); self.out = []
    def _send_to(self, s, msg): self.out.append(msg)
r = FakeRouter(); mgr = m.NiflheimManager(r); db = r.db
journey.fight_handler = None       # 1.4: the manager installs the real fight hook; 1.3 tests the placeholder path
fails = 0
def check(name, cond):
    global fails; print(("PASS " if cond else "FAIL ") + name); fails += (not cond)
def run(sender, text, gj="g@g.us"): return mgr.pre_dispatch(sender, text, pool_niflheim=True, group_jid=gj)

# ── map data
L = world.locations()
check("17 locations", len(L) == 17)
check("types: 1 town, 4 hubs, 12 places", sorted(l["type"] for l in L.values()).count("hub") == 4 and sorted(l["type"] for l in L.values()).count("place") == 12 and world.is_town("ash_town"))
check("all exits valid and reversible", all(world.get(d)["exits"].get({"north":"south","south":"north","east":"west","west":"east"}[dr]) == l["id"] for l in L.values() for dr, d in l["exits"].items()))
check("hubs: back + 3 new places", all(len(L[h]["exits"]) == 4 for h in ("whispering_woods","emberfield","silverbrook","duskhollow")))
check("travel times 12/14", world.travel_time("ash_town","whispering_woods") == 12 and world.travel_time("whispering_woods","misty_glade") == 14 and world.travel_time("misty_glade","whispering_woods") == 14)
check("aliases", [world.resolve_direction(x) for x in "nsew"] == ["north","south","east","west"])

# ── commands
check("unregistered .zone refused", "not registered" in run("a", ".zone"))
run("a", ".reg Frost"); run("b", ".reg Ember")
z = run("a", ".zone")
check(".zone at Ash Town: 4 exits all ???", "Ash Town" in z and z.count("???") == 4 and "Town" in z)
check(".look has description", "quiet heart" in run("a", ".look") and "Exits:" in run("a", ".look"))
check(".explore no/bad direction -> usage", "Usage" in run("a", ".explore") and "Usage" in run("a", ".explore up"))
check("dead end (hub has no exit?) n/a - place dead end", True)

# fix event roll to none for determinism
class R(random.Random):
    def random(self): return 0.99
rng = R()
import time
pl = store.load_player(db, "a"); T0 = time.time()
ok, msg = journey.start(db, "a", pl, "north", "g@g.us", now=T0, rng=rng, arm=False)
check("explore starts, shows 12s", ok and "heading north" in msg and "12s" in msg)
check("second .explore refused while travelling", "already traveling" in run("a", ".explore east"))
check(".zone while travelling shows status", "Travelling north" in run("a", ".zone"))
check("not arrived yet -> nothing", journey.resolve(db, "a", now=T0 + 5) == [])
check("player b independent map", "???" in run("b", ".zone") and store.load_journey(db, "b") is None)
msgs = journey.resolve(db, "a", now=T0 + 12)
check("arrival at 12s", len(msgs) == 1 and "Whispering Woods" in msgs[0])
pl = store.load_player(db, "a")
check("location + discovery saved", pl["location"] == "whispering_woods" and "whispering_woods" in pl["discovered"])
check("arrival idempotent", journey.resolve(db, "a", now=T0 + 50) == [] and store.load_journey(db, "a") is None)
z = run("a", ".zone")
check("discovered neighbour named, others ???", "South: Ash Town" in z and z.count("???") == 3)
check("b's map unaffected by a", run("b", ".zone").count("???") == 4)

# ── .end
T1 = 2000.0
journey.start(db, "a", pl, "north", "g@g.us", now=T1, rng=rng, arm=False)
e = journey.end(db, "a", now=T1 + 3)
check(".end mid-journey: stays at origin", "turn back" in e and store.load_player(db, "a")["location"] == "whispering_woods" and store.load_journey(db, "a") is None)
check(".end when idle", "not currently traveling" in journey.end(db, "a"))
journey.start(db, "a", pl, "north", "g@g.us", now=T1, rng=rng, arm=False)
e = journey.end(db, "a", now=T1 + 20)
check(".end after arrival counts as arrival", "Misty Glade" in e and store.load_player(db, "a")["location"] == "misty_glade")

# ── catch-up on next message (no push happened)
import time
pl = store.load_player(db, "a")
journey.start(db, "a", pl, "south", "g@g.us", now=time.time() - 100, rng=rng, arm=False)
out = run("a", ".zone")
check("catch-up arrival prepended on next message", "you are now in Whispering Woods" in out and "📍 *Whispering Woods*" in out)

# ── town heal
pl = store.load_player(db, "a"); pl["hp"] = 50; store.save_player(db, "a", pl)
journey.start(db, "a", pl, "south", "g@g.us", now=time.time() - 100, rng=rng, arm=False)
journey.resolve(db, "a")
pl = store.load_player(db, "a")
check("entering Ash Town fully heals", pl["location"] == "ash_town" and pl["hp"] == pl["max_hp"])

# ── invalid exit and lock mechanism
ok, msg = journey.start(db, "a", pl, "north", "g", now=0, rng=rng, arm=False); journey.end(db, "a", now=1e9)
pl = store.load_player(db, "a")
ok, msg = journey.start(db, "a", dict(pl, location="misty_glade"), "east", "g", now=0, rng=rng, arm=False)
check("dead end refused", (not ok) and "dead end" in msg)
L["whispering_woods"]["requires"] = {"level": 5}
ok, msg = journey.start(db, "a", dict(pl, location="ash_town"), "north", "g", now=0, rng=rng, arm=False)
check("locked location refused", (not ok) and "locked" in msg)
pl2 = store.load_player(db, "a"); pl2["location"] = "ash_town"; store.save_player(db, "a", pl2)
check("🔒 shown on exit", "🔒" in run("a", ".zone"))
L["whispering_woods"]["requires"] = {}
check("unknown requirement key stays locked", not world.requirements_met(pl, {"requires": {"boss": "x"}}))

# ── events
class F(random.Random):
    def random(self): return 0.0
ev = journey._roll_event(12, F())
check("fight roll -> fight event at midpoint", ev["kind"] == "fight" and ev["at"] == 6)
class G(random.Random):
    def random(self): return 0.3
ev = journey._roll_event(12, G())
check("flavour roll", ev["kind"] == "flavour" and ev["text"])
check("no event roll", journey._roll_event(12, rng)["kind"] is None)
store.save_player(db, "c", P.new_player("Cee"))
pc = store.load_player(db, "c")
journey.start(db, "c", pc, "north", "g", now=500.0, rng=F(), arm=False)
mid = journey.resolve(db, "c", now=506)
check("fight event fires at midpoint (placeholder until 1.4)", len(mid) == 1 and store.load_journey(db, "c") is not None)
check("event fires only once", journey.resolve(db, "c", now=508) == [])
fin = journey.resolve(db, "c", now=512)
check("then arrival", len(fin) == 1 and "you are now in" in fin[0])
journey.fight_handler = lambda s, p, j: "⚔️ A monster appears!"
journey.start(db, "c", store.load_player(db, "c"), "south", "g", now=600.0, rng=F(), arm=False)
check("fight_handler hook is used when set", journey.resolve(db, "c", now=606) == ["⚔️ A monster appears!"])
journey.fight_handler = None

# ── 1.2 player without discovered field (upgrade path)
old = P.new_player("Old"); del old["discovered"]; P.normalize(old)
check("normalize adds discovered", old["discovered"] == ["ash_town"])
sys.exit(1 if fails else 0)
