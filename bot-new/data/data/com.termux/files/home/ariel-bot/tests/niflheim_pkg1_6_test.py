# Package 1.6 tests — run: python3 tests/niflheim_pkg1_6_test.py
import os, sys, sqlite3, random, time, importlib.util
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "engine"))
spec = importlib.util.spec_from_file_location("nif_router", os.path.join(ROOT, "engine", "router", "niflheim.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
from niflheim import store, journey, combat, duel, live
journey.arm_timer = lambda *a, **k: None
combat.arm_round_timer = lambda *a, **k: None
duel.arm_timer = lambda *a, **k: None
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
def run(s, t, gj="g1@g.us", men=None, pool=True): return mgr.pre_dispatch(s, t, pool_niflheim=pool, group_jid=gj, mentioned_jid=men)
def pl(s): return store.load_player(db, s)
def put(s, **kw):
    p = pl(s); p.update(kw); store.save_player(db, s, p)
for s, n in (("a", "Frost"), ("b", "Ember"), ("c", "Gale"), ("d", "Rime"), ("e", "Ash")):
    run(s, f".reg {n}"); put(s, location="misty_glade")

# ── invites
check(".duel without a tag -> usage", "Usage" in run("a", ".duel"))
check("can't duel self", "yourself" in run("a", ".duel @x", men="a"))
check("target must be registered", "isn't registered" in run("a", ".duel @x", men="zzz"))
check("DM refused", "played in groups" in run("a", ".duel @b", gj=None, men="b"))
out = run("a", ".duel @Ember", men="b")
check("invite posted, 60s", "Frost" in out and "Ember" in out and "60s" in out and store.load_duel(db, "b")["status"] == "invited")
check("only one invite per player (challenger)", "can't start a duel" in run("a", ".duel @c", men="c"))
check("target already invited -> can't be challenged", "can't be challenged" in run("c", ".duel @b", men="b"))
check("wrong player can't accept", "no pending duel invite" in run("c", ".accept"))
check("challenger can't accept own invite", "no pending duel invite" in run("a", ".accept"))
check("accept from another group refused", "different group" in run("b", ".accept", gj="g2@g.us"))
out = run("b", ".decline")
check("decline cancels", "declined" in out and store.load_duel(db, "a") is None)
check(".decline with nothing pending", "no pending" in run("b", ".decline"))

# ── busy participants
combat.start_fight(db, "b", pl("b"), "g1@g.us", monster_id="slime", arm=False)
check("target mid-fight can't be challenged", "can't be challenged" in run("a", ".duel @b", men="b"))
store.delete_fight(db, "b")
combat.start_fight(db, "a", pl("a"), "g1@g.us", monster_id="slime", arm=False)
check("challenger mid-fight refused", "can't start a duel" in run("a", ".duel @b", men="b"))
store.delete_fight(db, "a")
j = {"origin": "misty_glade", "direction": "south", "destination": "whispering_woods", "total": 14, "start": time.time(), "group_jid": "g", "event": {"kind": None, "at": 0, "done": True}}
store.save_journey(db, "b", j)
check("target travelling can't be challenged", "can't be challenged" in run("a", ".duel @b", men="b"))
store.delete_journey(db, "b")
put("b", hp=0)
check("zero-HP player refused", "no HP left" in run("a", ".duel @b", men="b"))
put("b", hp=200)

# ── timeout of invite
run("a", ".duel @b", men="b"); d = store.load_duel(db, "a")
check("invite not expired at 59s", duel.tick_duel(db, d["id"], now=d["created"] + 59) == [])
msgs = duel.tick_duel(db, d["id"], now=d["created"] + 60)
check("invite expires at 60s (pushed message)", len(msgs) == 1 and "expired" in msgs[0] and store.load_duel(db, "a") is None)
run("a", ".duel @b", men="b"); d = store.load_duel(db, "a"); d["expires"] = time.time() - 1; store.save_duel(db, d)
check("late .accept: catch-up says expired", "expired" in run("b", ".accept") and store.load_duel(db, "b") is None)

# ── accept + a full duel, deterministic: no potions, all attacks
put("a", hp=200, max_hp=200, level=1, duel_wins=0, duel_losses=0); put("b", hp=200, max_hp=200, level=1, duel_wins=0, duel_losses=0)
run("a", ".duel @b", men="b")
out = run("b", ".accept")
check("accept starts duel with both HP shown", "DUEL!" in out and "200/200" in out and store.load_duel(db, "a")["status"] == "active")
check(".hunt/.explore refused in a duel", "in a duel" in run("a", ".hunt") and "during a duel" in run("a", ".explore south"))
check(".equip/.use refused in a duel", "middle of a fight" in run("a", ".equip x") and "middle of a fight" in run("b", ".use hp"))
out = run("a", ".attack")
check("first action is only 'ready' (nothing resolved)", "ready" in out and store.load_duel(db, "a")["round"] == 1 and pl("b")["hp"] == 200)
check("can't choose twice", "already chosen" in run("a", ".defend"))
out = run("b", ".attack")
check("second action resolves round: both -20", "Round 1" in out and pl("a")["hp"] == 180 and pl("b")["hp"] == 180 and store.load_duel(db, "a")["round"] == 2)
# round 2: A defends, B attacks -> 10 dmg to A; round 3: both defend -> nothing
run("a", ".defend"); out = run("b", ".attack")
check("defend halves incoming (20 -> 10)", pl("a")["hp"] == 170 and "blocked half" in out)
run("a", ".defend"); run("b", ".defend")
check("both defend: no damage", pl("a")["hp"] == 170 and pl("b")["hp"] == 180)

# ── potions in duel
put("a", inventory={"Small HP Potion": 1}); 
check("potion with none refused", "no potions" in run("b", ".potion") and store.load_duel(db, "a")["actions"]["b"] is None)
run("a", ".potion"); out = run("b", ".attack")
check("potion heals before damage: 170+30-20 = 180, potion consumed", pl("a")["hp"] == 180 and pl("a")["inventory"] == {} and "drinks" in out)

# ── one acts, the other times out -> auto attack
d = store.load_duel(db, "a"); rd = d["round"]
run("a", ".defend")
d = store.load_duel(db, "a"); d["round_start"] = 5000.0; store.save_duel(db, d)
check("not due before 30s", duel.tick_duel(db, d["id"], now=5029) == [])
msgs = duel.tick_duel(db, d["id"], now=5030)
check("timeout: B auto-attacks, A's defend counted (20 -> 10)", len(msgs) == 1 and "auto" in msgs[0] and pl("a")["hp"] == 170)
check("tick idempotent", duel.tick_duel(db, d["id"], now=5030) == [])
# nobody acts: both auto-attack until the round cap or a death
d = store.load_duel(db, "a")
start_round = d["round"]
d["round_start"] = 9000.0; store.save_duel(db, d)
msgs = duel.tick_duel(db, d["id"], now=9000 + 30 * 40)
check("idle duel resolves by itself to the round cap and ends", store.load_duel(db, "a") is None and "Round limit reached" in msgs[-1] and "Ember wins the duel" in msgs[-1])
a_, b_ = pl("a"), pl("b")
check("cap result recorded; HP persists (no heal, no respawn)", (a_["duel_wins"], a_["duel_losses"], b_["duel_wins"], b_["duel_losses"]) == (0, 1, 1, 0) and (a_["hp"], b_["hp"]) == (30, 40))
check("no coins/XP awarded", a_["xp"] == 0 and b_["xp"] == 0 and a_["coins"] == 0)

# ── winner by KO with exact numbers: A hits 20/round, B has 40 HP
put("a", hp=200, max_hp=200, duel_wins=0, duel_losses=0); put("b", hp=40, max_hp=200, duel_wins=0, duel_losses=0)
run("a", ".duel @b", men="b"); run("b", ".accept")
run("a", ".attack"); run("b", ".defend")           # 20 -> 10
run("a", ".attack"); run("b", ".defend")           # 10 -> 20 left? (40-10-10)
d = store.load_duel(db, "a")
check("KO path set up (B at 20 HP)", pl("b")["hp"] == 20 and d is not None)
run("a", ".attack"); out = run("b", ".attack")
check("B reaches 0 HP: A wins, announced", "Frost wins the duel" in out and pl("b")["hp"] == 0 and pl("a")["duel_wins"] == 1 and pl("b")["duel_losses"] == 1)
check("B stays at 0 HP (no respawn)", pl("b")["location"] == "misty_glade" and pl("b")["hp"] == 0)
check("duel cleared for both", store.load_duel(db, "a") is None and store.load_duel(db, "b") is None)

# ── mutual KO = draw
put("a", hp=20, max_hp=200, duel_wins=0, duel_losses=0); put("b", hp=20, max_hp=200, duel_wins=0, duel_losses=0)
run("a", ".duel @b", men="b"); run("b", ".accept"); run("a", ".attack"); out = run("b", ".attack")
check("both reach 0 same round -> draw, nothing recorded", "draw" in out and pl("a")["duel_wins"] == 0 and pl("a")["duel_losses"] == 0 and pl("b")["duel_losses"] == 0)

# ── round cap: higher HP% wins; tie = draw
put("a", hp=200, max_hp=200); put("b", hp=200, max_hp=200)
run("a", ".duel @b", men="b"); run("b", ".accept")
for i in range(11): run("a", ".defend"); run("b", ".defend")
d = store.load_duel(db, "a")
check("11 quiet rounds: still going, round 12 next", d["round"] == 12)
run("a", ".attack"); out = run("b", ".defend")                      # A deals 10 to B in round 12
check("round cap 12: higher HP% wins (Frost 100% vs Ember 95%)", "Round limit reached" in out and "Frost wins the duel" in out and store.load_duel(db, "a") is None)
put("a", hp=200, max_hp=200); put("b", hp=200, max_hp=200)
run("a", ".duel @b", men="b"); run("b", ".accept")
for i in range(12): run("a", ".defend"); out = run("b", ".defend")
check("round cap tie (equal %) = draw", "draw" in out and store.load_duel(db, "a") is None)
put("a", hp=100, max_hp=200); put("b", hp=300, max_hp=600)         # 50% vs 50% with different Max HP
run("a", ".duel @b", men="b"); run("b", ".accept")
for i in range(12): run("a", ".defend"); out = run("b", ".defend")
check("percentage tie across different Max HP = draw", "draw" in out)

# ── level gap + gear damage used
put("a", hp=200, max_hp=200, level=1, equipped={"weapon": None, "armour": None, "accessory": None}); put("b", hp=500, max_hp=500, level=10)
run("a", ".duel @b", men="b"); run("b", ".accept"); run("a", ".attack"); out = run("b", ".attack")
check("level gap allowed; damage uses level (B Lv10 = 65, A Lv1 = 20)", pl("a")["hp"] == 135 and pl("b")["hp"] == 480)
store.delete_duel(db, store.load_duel(db, "a"))
put("a", hp=200, max_hp=200, level=1, equipped={"weapon": None, "armour": None, "accessory": None}); put("b", hp=200, max_hp=200, level=1)
put("b", inventory={"Iron Sword": 1}); put("b", equipped={"weapon": "Iron Sword", "armour": None, "accessory": None})
run("a", ".duel @b", men="b"); run("b", ".accept"); run("a", ".attack"); run("b", ".attack")
check("gear bonus applies in duels (Iron Sword: 22)", pl("a")["hp"] == 178)
store.delete_duel(db, store.load_duel(db, "a"))

# ── two duels in different groups at once; no cross-talk
put("a", hp=200, max_hp=200); put("b", hp=200, max_hp=200); put("c", hp=200, max_hp=200); put("d", hp=200, max_hp=200)
run("a", ".duel @b", gj="g1@g.us", men="b"); run("b", ".accept", gj="g1@g.us")
run("c", ".duel @d", gj="g2@g.us", men="d"); run("d", ".accept", gj="g2@g.us")
run("a", ".attack", gj="g1@g.us"); run("c", ".defend", gj="g2@g.us")
d1, d2 = store.load_duel(db, "a"), store.load_duel(db, "c")
check("two simultaneous duels are independent", d1["id"] != d2["id"] and d1["actions"]["a"] and not d1["actions"]["b"] and d2["actions"]["a"] and d2["group_jid"] == "g2@g.us" and pl("b")["hp"] == 200)
run("b", ".attack", gj="g1@g.us")
check("finishing one leaves the other waiting", store.load_duel(db, "c")["round"] == 1 and store.load_duel(db, "a")["round"] == 2)

# ── world switched off cancels duel/fight/invite in that group (g1) but not g2
combat.start_fight(db, "e", pl("e"), "g1@g.us", monster_id="slime", arm=False)
run("a", ".reg x", gj="g1@g.us", pool=False)       # any message with the pool OFF in g1
check("pool off in g1: duel + fight cancelled", store.load_duel(db, "a") is None and store.load_fight(db, "e") is None)
check("pool off in g1: g2 duel untouched", store.load_duel(db, "c") is not None)
check("pool off: commands ignored", run("a", ".duel @b", men="b", pool=False) is m.NOT_HANDLED)

# ── .attack with nothing going on, pending-invite player can still do other things
check(".attack when not fighting/dueling", "not in a fight" in run("e", ".attack"))
# ── profile shows record
check(".profile shows duel record", "Duels:" in run("a", ".profile") and "W /" in run("a", ".profile"))
check(".boss is live (needs the arena site set up)", "not set up" in run("a", ".boss") or "boss" in run("a", ".boss").lower())
sys.exit(1 if fails else 0)
