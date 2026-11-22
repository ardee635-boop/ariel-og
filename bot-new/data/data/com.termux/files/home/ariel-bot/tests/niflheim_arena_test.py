# Session 2 tests: arena tickets/results + automatic WhatsApp fights. Run: python3 tests/niflheim_arena_test.py
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
t, e = arena.create_ticket(db, "nobody"); check("ticket needs a registered player", t is None and "not registered" in e)
t, e = arena.create_ticket(db, "a", "wild_wolf")
check("ticket carries real stats", t["player"]["max_hp"] == 200 and t["player"]["damage"] == 20 and t["foe"]["hp"] == 90 and t["foe"]["rig"] == "wolf")
check("ticket hides rewards", "xp" not in t["foe"] and "coins" not in t["foe"])
check("other player cannot read the ticket", "error" in arena.get_ticket(db, "b", t["ticket"]))
t2, _ = arena.create_ticket(db, "a", "goblin")
check("new ticket replaces the old one", "error" in arena.get_ticket(db, "a", t["ticket"]) and "error" not in arena.get_ticket(db, "a", t2["ticket"]))
check("other player cannot submit it", "error" in arena.submit_result(db, "b", t2["ticket"], {"won": True, "foeHp": 0, "playerHp": 100}))
now = time.time()
r1 = arena.submit_result(db, "a", t2["ticket"], {"won": True, "foeHp": 0, "playerHp": 150}, router=r, rng=Fixed(), now=now + 1)
check("instant win rejected, no rewards", r1.get("outcome") == "rejected" and store.load_player(db, "a")["xp"] == 0)
check("rejected ticket is burned", "error" in arena.submit_result(db, "a", t2["ticket"], {"won": True, "foeHp": 0, "playerHp": 150}, now=now + 20))
t3, _ = arena.create_ticket(db, "a", "slime")
r2 = arena.submit_result(db, "a", t3["ticket"], {"won": True, "foeHp": 0, "playerHp": 150}, router=r, rng=Fixed(), now=time.time() + 10)
pl = store.load_player(db, "a")
check("valid win gives XP from the server table", r2["outcome"] == "win" and pl["xp"] == 5 and pl["hp"] == 150)
check("win cannot be replayed", "error" in arena.submit_result(db, "a", t3["ticket"], {"won": True, "foeHp": 0, "playerHp": 150}))
t4, _ = arena.create_ticket(db, "a", "slime")
check("win with foe still alive rejected", arena.submit_result(db, "a", t4["ticket"], {"won": True, "foeHp": 30, "playerHp": 150}, now=time.time() + 10).get("outcome") == "rejected")
put("a", location="misty_glade")
t5, _ = arena.create_ticket(db, "a", "slime")
r3 = arena.submit_result(db, "a", t5["ticket"], {"won": False, "foeHp": 40, "playerHp": 0})
pl = store.load_player(db, "a")
check("loss sends you home with full HP", r3["outcome"] == "loss" and pl["location"] == "ash_town" and pl["hp"] == 200)
t6, _ = arena.create_ticket(db, "a", "slime")
check("expired ticket refused", "expired" in arena.submit_result(db, "a", t6["ticket"], {"won": True, "foeHp": 0, "playerHp": 100}, now=time.time() + 99999)["error"])
for _ in range(2):  # HP clamp: a client claiming huge HP cannot exceed max HP
    t7, _ = arena.create_ticket(db, "a", "slime")
arena.submit_result(db, "a", t7["ticket"], {"won": True, "foeHp": 0, "playerHp": 99999}, rng=Fixed(), now=time.time() + 10)
check("claimed HP is clamped to max", store.load_player(db, "a")["hp"] <= 200)

# Automatic WhatsApp fights
put("a", location="misty_glade", hp=200, max_hp=200, level=1, xp=0, inventory={})
msgs, lvl = combat.auto_fight(db, "a", store.load_player(db, "a"), monster_id="slime", rng=Fixed())
check("auto fight ends by itself", store.load_fight(db, "a") is None and "You encountered" in msgs[0])
check("auto fight pays XP", store.load_player(db, "a")["xp"] >= 5 or store.load_player(db, "a")["level"] > 1)
put("a", location="misty_glade", hp=200, max_hp=200)
out = run("a", ".hunt")
check(".hunt resolves with no manual turns", "You encountered" in out and ".attack" not in out.split("Fought")[0] and store.load_fight(db, "a") is None)
put("a", location="misty_glade", hp=40, max_hp=200, inventory={"HP Potion": 3})
combat.auto_fight(db, "a", store.load_player(db, "a"), monster_id="forest_boar", rng=Fixed())
check("potion used when HP is low", store.load_player(db, "a")["inventory"].get("HP Potion", 3) < 3)
put("a", location="ash_town")
os.environ["ARENA_URL"] = "https://x.test/arena"
out = run("a", ".arena")
check(".arena gives a ticket link", "https://x.test/arena?t=" in out)
_w = run("a", ".website")
check(".website sends the plain site link, not a fight ticket", "https://x.test/" in _w and "?t=" not in _w and "/arena" not in _w)
check(".site matches .website", run("a", ".site") == _w)
check(".nmenu lists .arena", ".arena" in run("a", ".nmenu"))
print("\nFAILS:", fails); sys.exit(1 if fails else 0)
