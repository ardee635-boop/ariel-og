# Package 1.2 tests — run: python3 tests/niflheim_pkg1_2_test.py
import os, sys, sqlite3, importlib.util
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "engine"))
spec = importlib.util.spec_from_file_location("nif_router", os.path.join(ROOT, "engine", "router", "niflheim.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
from niflheim import player as P, store

class FakeDb:
    _mode = "sqlite"
    def __init__(self): self.conn = sqlite3.connect(":memory:")
    def _ex(self, sql, params=()): return self.conn.execute(sql, params)
    def _commit(self): self.conn.commit()
    def _fetchone(self, cur): return cur.fetchone()
class FakeRouter:
    def __init__(self): self.db = FakeDb(); self.out = []
    def _send_to(self, s, msg): self.out.append(msg)

r = FakeRouter(); mgr = m.NiflheimManager(r)
fails = 0
def check(name, cond):
    global fails; print(("PASS " if cond else "FAIL ") + name); fails += (not cond)
def run(sender, text, admin=False): return mgr.pre_dispatch(sender, text, pool_niflheim=True, is_admin=admin)

check("unregistered .profile prompts reg", "not registered" in run("a", ".profile"))
check(".reg without name -> usage", "Usage" in run("a", ".reg"))
check(".reg bad name rejected", "characters" in run("a", ".reg x"))
check(".reg ok", "Welcome to Niflheim, *Frost*" in run("a", ".reg Frost"))
check(".reg twice handled politely", "already registered as *Frost*" in run("a", ".reg Other"))
pr = run("a", ".profile")
check(".profile == .p", pr == run("a", ".p"))
check("profile defaults", all(x in pr for x in ("Level: 1", "XP: 0/100", "HP: 200/200", "Coins: 0", "Ash Town", "0W / 0L")))
check("xp curve", [P.xp_needed(l) for l in (1, 2, 3, 4)] == [100, 283, 520, 800])
check(".ngrant refused for non-admin", run("a", ".ngrant xp 5") is m.NOT_HANDLED)
res = run("a", ".ngrant xp 1500", admin=True)   # 100+283+520 = 903 -> level 4, 597 left
check("3 level-ups = 3 separate queued messages", len(r.out) == 3 and "Levels gained: 3" in res)
check("messages in order and unique", [("Level 2" in r.out[0]), ("Level 3" in r.out[1]), ("Level 4" in r.out[2])] == [True]*3 and len(set(r.out)) == 3)
pl = store.load_player(r.db, "a")
check("level/xp carry-over", pl["level"] == 4 and pl["xp"] == 597)
check("Max HP +100/level", pl["max_hp"] == 500)
check("coins +500/level", pl["coins"] == 1500)
check("HP gains with max", pl["hp"] == 500)
check("progress shown", "XP: 597/800" in run("a", ".p"))
run("a", ".ngrant coins 250", admin=True)
check("grant_coins", store.load_player(r.db, "a")["coins"] == 1750)
run("b", ".reg Ember")
check("second player independent", store.load_player(r.db, "b")["level"] == 1)
check("pool off ignored", mgr.pre_dispatch("a", ".p", pool_niflheim=False) is m.NOT_HANDLED)
check("level-up exactly at threshold", len(P.grant_xp(P.new_player("T"), 100)) == 1)
check("no level-up below threshold", P.grant_xp(P.new_player("T"), 99) == [])
sys.exit(1 if fails else 0)
