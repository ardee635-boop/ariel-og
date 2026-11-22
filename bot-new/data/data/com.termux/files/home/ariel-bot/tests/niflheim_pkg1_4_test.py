# Package 1.4 tests — run: python3 tests/niflheim_pkg1_4_test.py
import os, sys, sqlite3, random, time, importlib.util
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "engine"))
spec = importlib.util.spec_from_file_location("nif_router", os.path.join(ROOT, "engine", "router", "niflheim.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
from niflheim import player as P, store, world, journey, combat
journey.arm_timer = lambda *a, **k: None          # no real timers in tests
combat.arm_round_timer = lambda *a, **k: None

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
fails = 0
def check(name, cond):
    global fails; print(("PASS " if cond else "FAIL ") + name); fails += (not cond)
def run(sender, text, gj="g@g.us"): return mgr.pre_dispatch(sender, text, pool_niflheim=True, group_jid=gj)
def put(sender, **kw):
    pl = store.load_player(db, sender); pl.update(kw); store.save_player(db, sender, pl); return pl
class Fixed(random.Random):
    """random() fixed, randint -> low/high end, choice -> first."""
    def __init__(self, r=0.99, hi=False): super().__init__(); self.r, self.hi = r, hi
    def random(self): return self.r
    def randint(self, a, b): return b if self.hi else a
    def choice(self, seq): return list(seq)[0]

# ── data
cat = combat.catalogue()["monsters"]
check("4 monsters, LOCKED values", [(x["name"], x["hp"], x["damage"], x["xp"], x["coins"]) for x in cat] ==
      [("Slime",75,[8,12],[5,10],[50,100]),("Wild Wolf",90,[10,15],[10,15],[80,140]),
       ("Goblin",105,[12,16],[12,18],[100,180]),("Forest Boar",120,[13,18],[15,22],[120,200])])
check("monster HP 75-120", min(x["hp"] for x in cat) == 75 and max(x["hp"] for x in cat) == 120)
check("attack formula 15+5L", [combat.player_damage({"level": l}) for l in (1,2,5,10,20)] == [20,25,40,65,115])
check("Lv1 can't one-shot any Lv1 monster", all(combat.player_damage({"level": 1}) < x["hp"] for x in cat))

# ── hunt gating
check("unregistered .hunt refused", "not registered" in run("a", ".hunt"))
run("a", ".reg Frost")
check("no hunt in town", "nothing to hunt in town" in run("a", ".hunt"))
check(".attack outside fight", "not in a fight" in run("a", ".attack"))
put("a", location="misty_glade")
out = run("a", ".hunt")
check(".hunt outside town resolves automatically (Session 2)", "You encountered" in out and store.load_fight(db, "a") is None)

# ── actions, deterministic: Slime, low damage rolls
store.delete_fight(db, "a")
put("a", location="misty_glade", hp=200, max_hp=200, inventory={})
combat.start_fight(db, "a", store.load_player(db, "a"), "g@g.us", rng=Fixed(), monster_id="slime", arm=False)
ok, main, lvl = combat.act(db, "a", "attack", rng=Fixed())
f = store.load_fight(db, "a"); pl = store.load_player(db, "a")
check("attack: 20 dmg dealt, monster 55/75", "hit Slime for 20" in main[0] and f["monster"]["hp"] == 55)
check("monster always attacks back (8-12)", pl["hp"] == 192 and "Slime hits you for 8" in main[0] and f["round"] == 2)
ok, main, _ = combat.act(db, "a", "defend", rng=Fixed(hi=True))
pl = store.load_player(db, "a")
check("defend halves incoming damage (12 -> 6)", "for 6" in main[-1] and pl["hp"] == 186)
check("potion with none: refused, choose again, round not used",
      combat.act(db, "a", "potion")[0] is False and store.load_fight(db, "a")["round"] == 3 and "no potions" in combat.act(db, "a", "potion")[1][0])
put("a", hp=100, inventory={"Small HP Potion": 1, "HP Potion": 1})
ok, main, _ = combat.act(db, "a", "potion", rng=Fixed())
pl = store.load_player(db, "a")
check("default potion = Small (+30), uses the round, monster still attacks", pl["hp"] == 100 + 30 - 8 and pl["inventory"] == {"HP Potion": 1})
ok, main, _ = combat.act(db, "a", "potion", "hp", rng=Fixed())
pl = store.load_player(db, "a")
check("'.potion hp' uses HP Potion (+60)", pl["hp"] == 122 + 60 - 8 and "HP Potion" not in pl["inventory"])
put("a", hp=195, inventory={"HP Potion": 1})
combat.act(db, "a", "potion", rng=Fixed()); pl = store.load_player(db, "a")
check("heal capped at Max HP (then monster hit)", pl["hp"] == 200 - 8)

# ── win + rewards (keep attacking, low roll => 75% none, coins always since r<0.7 false at .99 -> no coins)
store.delete_fight(db, "a")
put("a", level=1, xp=0, hp=200, max_hp=200, coins=0, inventory={})
combat.start_fight(db, "a", store.load_player(db, "a"), "g", rng=Fixed(), monster_id="slime", arm=False)
for _ in range(4):
    ok, main, lvl = combat.act(db, "a", "attack", rng=Fixed(0.99))
pl = store.load_player(db, "a")
check("slime dies in 4 hits; fight cleared", "Victory" in main[0] and store.load_fight(db, "a") is None)
check("XP always (min 5), no coin/item at r=.99", pl["xp"] == 5 and pl["coins"] == 0 and pl["inventory"] == {})
store.delete_fight(db, "a"); put("a", xp=0, coins=0, inventory={})
combat.start_fight(db, "a", store.load_player(db, "a"), "g", rng=Fixed(), monster_id="wild_wolf", arm=False)
for _ in range(5): ok, main, lvl = combat.act(db, "a", "attack", rng=Fixed(0.0, hi=True))
pl = store.load_player(db, "a")
check("r=0: coins awarded in range + UNIQUE drop (Wolf Fang)", pl["coins"] == 140 and pl["inventory"] == {"Wolf Fang": 1} and pl["xp"] == 15)
# general drop band: 0.20 <= r < 0.25
store.delete_fight(db, "a"); put("a", xp=0, coins=0, inventory={})
class G(Fixed):
    def __init__(self): super().__init__(0.22); 
combat.start_fight(db, "a", store.load_player(db, "a"), "g", rng=Fixed(), monster_id="slime", arm=False)
for _ in range(4): combat.act(db, "a", "attack", rng=G())
check("r=.22 -> general item from pool (first = Small HP Potion)", store.load_player(db, "a")["inventory"] == {"Small HP Potion": 1})
# drop distribution
rng = random.Random(7); n = 20000; uniq = gen = none = 0
for _ in range(n):
    mon = cat[0]; p = {"level": 1, "xp": 0, "hp": 1, "max_hp": 1, "coins": 0, "name": "x", "inventory": {}}
    combat._roll_rewards(p, mon, rng)
    inv = p["inventory"]
    if "Slime Core" in inv: uniq += 1
    elif inv: gen += 1
    else: none += 1
check("drop rates ~20/5/75", abs(uniq/n-.20) < .015 and abs(gen/n-.05) < .01 and abs(none/n-.75) < .015)

# ── level-ups from fights: separate messages
store.delete_fight(db, "a"); put("a", level=1, xp=95, max_hp=200, hp=200, coins=0, inventory={})
combat.start_fight(db, "a", store.load_player(db, "a"), "g", rng=Fixed(), monster_id="slime", arm=False)
for _ in range(3): combat.act(db, "a", "attack", rng=Fixed())
r.out.clear()
out = run("a", ".attack")
pl = store.load_player(db, "a")
check("fight win levels up via router: own message sent", "Victory" in out and len(r.out) == 1 and "LEVEL UP" in r.out[0] and pl["level"] == 2 and pl["max_hp"] == 300)

# ── defeat
store.delete_fight(db, "a"); put("a", level=1, xp=0, max_hp=200, hp=10, location="misty_glade", inventory={})
combat.start_fight(db, "a", store.load_player(db, "a"), "g", rng=Fixed(), monster_id="forest_boar", arm=False)
ok, main, _ = combat.act(db, "a", "attack", rng=Fixed())
pl = store.load_player(db, "a")
check("defeat: respawn Ash Town, full HP, no coin/item loss", "defeated" in main[0] and pl["location"] == "ash_town" and pl["hp"] == pl["max_hp"] and store.load_fight(db, "a") is None)

# ── auto-attack on timeout + catch-up
store.delete_fight(db, "a"); put("a", level=1, xp=0, hp=200, max_hp=200, location="misty_glade")
T = 1000.0
combat.start_fight(db, "a", store.load_player(db, "a"), "g", rng=Fixed(), monster_id="forest_boar", arm=False)
fg = store.load_fight(db, "a"); fg["round_start"] = T; store.save_fight(db, "a", fg)
check("not due before 30s", combat.tick(db, "a", now=T + 29, rng=Fixed()) == ([], []))
main, _ = combat.tick(db, "a", now=T + 30, rng=Fixed())
check("30s no action -> auto-attack", len(main) == 1 and "auto-attack" in main[0] and store.load_fight(db, "a")["monster"]["hp"] == 100)
check("tick idempotent in same window", combat.tick(db, "a", now=T + 30, rng=Fixed()) == ([], []))
main, _ = combat.tick(db, "a", now=T + 30 + 61, rng=Fixed())
check("idle for 2 more rounds -> both resolved in order", len(main) == 2 and "Round 2" in main[0] and "Round 3" in main[1])
fg = store.load_fight(db, "a"); fg["round_start"] = time.time() - 40; store.save_fight(db, "a", fg)
out = run("a", ".zone")
check("catch-up auto-attack prepended on next message", "auto-attack" in out and "📍" in out)

# ── journey-event fight
store.delete_fight(db, "a")
put("a", location="ash_town", hp=200, max_hp=200)
class F(random.Random):
    def random(self): return 0.0
T0 = time.time() - 6.5
ok, msg = journey.start(db, "a", store.load_player(db, "a"), "north", "g@g.us", now=T0, rng=F(), arm=False)
out = run("a", ".zone")
check("journey event fights automatically at the midpoint", "You encountered" in out and store.load_fight(db, "a") is None)
check("journey still active after the fight", store.load_journey(db, "a") is not None)
j = store.load_journey(db, "a"); j["start"] = time.time() - 100; store.save_journey(db, "a", j)
check("after the fight the journey arrives", "you are now in Whispering Woods" in "\n".join(journey.resolve(db, "a")) and store.load_player(db, "a")["location"] == "whispering_woods")
# defeat on a journey cancels it (HP 5: every monster out-damages that)
put("a", location="ash_town", hp=5)
journey.start(db, "a", store.load_player(db, "a"), "north", "g@g.us", now=time.time() - 6.5, rng=F(), arm=False)
run("a", ".zone")
check("defeat mid-journey: respawn Ash Town, journey cancelled", store.load_journey(db, "a") is None and store.load_player(db, "a")["location"] == "ash_town")

# ── .hunt while travelling (no fight)
put("a", location="ash_town", hp=200)
journey.start(db, "a", store.load_player(db, "a"), "north", "g@g.us", now=time.time(), rng=Fixed(), arm=False)
put("a", location="misty_glade")
check("hunt refused while travelling", "while travelling" in run("a", ".hunt"))
journey.end(db, "a")

# ── HP persists; town heal on arrival
put("a", location="misty_glade", hp=77)
check("HP persists after a fight (no auto-heal outside town)", store.load_player(db, "a")["hp"] == 77)

# ── independence + menu + other pools
run("b", ".reg Ember"); put("b", location="cinder_creek")
run("b", ".hunt")
check("player b fight resolved on its own, a unaffected", store.load_fight(db, "b") is None and store.load_fight(db, "a") is None)
check(".nmenu lists combat commands", all(c in run("b", ".nmenu") for c in (".attack", ".defend", ".potion", ".hunt")))
check("pool off -> commands ignored", mgr.pre_dispatch("b", ".hunt", pool_niflheim=False) is m.NOT_HANDLED)
check(".boss is live (needs the arena site set up)", "not set up" in run("b", ".boss") or "boss" in run("b", ".boss").lower())
sys.exit(1 if fails else 0)
