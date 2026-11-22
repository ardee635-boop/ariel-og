# Session 2 boss tests. Run: python3 tests/niflheim_boss_test.py
import os, sys, sqlite3, random, time, importlib.util
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "engine"))
spec = importlib.util.spec_from_file_location("nif_router", os.path.join(ROOT, "engine", "router", "niflheim.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
from niflheim import player as P, store, journey, combat, arena
journey.arm_timer = lambda *a, **k: None
class FakeDb:
    _mode = "sqlite"
    def __init__(self): self.conn = sqlite3.connect(":memory:")
    def _ex(self, sql, params=()): return self.conn.execute(sql, params)
    def _commit(self): self.conn.commit()
    def _fetchone(self, cur): return cur.fetchone()
class FakeRouter:
    def __init__(self): self.db = FakeDb(); self.out = []
    def _send_to(self, s, msg): self.out.append(msg)
r = FakeRouter(); db = r.db; mgr = m.NiflheimManager(r)
fails = 0
def check(n, c):
    global fails; print(("PASS " if c else "FAIL ") + n); fails += (not c)
class Fixed(random.Random):
    def __init__(self, r=0.99): super().__init__(); self.r = r
    def random(self): return self.r
    def randint(self, a, b): return a
    def choice(self, s): return list(s)[0]
def run(s, t): return mgr.pre_dispatch(s, t, pool_niflheim=True, group_jid="g@g.us")
def put(s, **kw):
    pl = store.load_player(db, s); pl.update(kw); store.save_player(db, s, pl); return pl
mgr.pre_dispatch("a", ".reg Frost", pool_niflheim=True, group_jid="g@g.us")
os.environ["ARENA_URL"] = "https://x.test/arena"
now = time.time()
cat = combat.boss_catalogue()["bosses"]
check("2 bosses, each in a real non-town zone", len(cat) == 2 and all(not __import__("niflheim.world", fromlist=["x"]).is_town(b["zone"]) and __import__("niflheim.world", fromlist=["x"]).get(b["zone"]) for b in cat))
check(".dungeon lists both bosses", all(b["name"] in run("a", ".dungeon") for b in cat))
check(".boss in town: no boss here", "no boss in this zone" in run("a", ".boss"))
put("a", location="frostmere", hp=200, max_hp=200, level=1, xp=0, coins=0, inventory={})
out = run("a", ".boss")
check(".boss in boss zone gives link", "https://x.test/arena?t=" in out and "Hrimthurs" in out)
check(".dungeon marks you are here", "you are here" in run("a", ".dungeon"))
t, e = arena.boss_ticket(db, "a")
check("boss ticket flagged boss, real hp, boss rig", t["boss"] and t["foe"]["hp"] == 400 and t["foe"]["rig"] == "boss" and "xp" not in t["foe"])
check("random tickets are never bosses", all(not arena.create_ticket(db, "a", None, rng=random.Random(i))[0]["boss"] for i in range(30)))
t, _ = arena.boss_ticket(db, "a")
check("too-fast win rejected", arena.submit_result(db, "a", t["ticket"], {"won": True, "foeHp": 0, "playerHp": 100}, now=time.time() + 1).get("outcome") == "rejected")
t, _ = arena.boss_ticket(db, "a")
res = arena.submit_result(db, "a", t["ticket"], {"won": True, "foeHp": 0, "playerHp": 150}, rng=Fixed(0.0), now=time.time() + 60, router=r)
pl = store.load_player(db, "a")
check("boss win pays big, drops the boss item", res["outcome"] == "win" and pl["coins"] >= 700 and pl["inventory"].get("Frost Giant Core") == 1)
check("boss win levels up and messages WhatsApp", pl["level"] > 1 and r.out)
out = run("a", ".boss")
check("cooldown after a win", "recovering" in out and "https://" not in out)
check(".dungeon shows recovering", "recovering" in run("a", ".dungeon"))
put("a", location="wolfsbane_ridge")
check("other boss is separate", "Cinderfang" in run("a", ".boss"))
t, _ = arena.boss_ticket(db, "a")
res = arena.submit_result(db, "a", t["ticket"], {"won": False, "foeHp": 100, "playerHp": 0}, now=time.time() + 60)
check("boss loss: respawn Ash Town, no cooldown", res["outcome"] == "loss" and store.load_player(db, "a")["location"] == "ash_town" and not store.load_player(db, "a").get("boss_cd", {}).get("cinderfang"))
put("a", location="frostmere"); 
os.environ["ARENA_URL"] = "https://x.test/?world=niflheim"
put("a", location="wolfsbane_ridge")
check("ARENA_URL with a query joins the ticket with &", "https://x.test/?world=niflheim&t=" in run("a", ".boss"))
os.environ["ARENA_URL"] = ""
check(".boss without ARENA_URL is a clear message", "not set up" in run("a", ".boss"))
print("\nFAILS:", fails); sys.exit(1 if fails else 0)
