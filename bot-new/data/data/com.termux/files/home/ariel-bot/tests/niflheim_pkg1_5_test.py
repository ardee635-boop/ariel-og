# Package 1.5 tests — run: python3 tests/niflheim_pkg1_5_test.py
import os, sys, sqlite3, random, importlib.util
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "engine"))
spec = importlib.util.spec_from_file_location("nif_router", os.path.join(ROOT, "engine", "router", "niflheim.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
from niflheim import player as P, store, journey, combat, items as I
journey.arm_timer = lambda *a, **k: None
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
def run(s, t): return mgr.pre_dispatch(s, t, pool_niflheim=True, group_jid="g@g.us")
def pl(s="a"): return store.load_player(db, s)
def put(s, **kw):
    p = pl(s); p.update(kw); store.save_player(db, s, p)

run("a", ".reg Frost")
# ── catalogue
c = I.catalogue()
check("10 items (8 from Session 1 + 2 boss drops), prices LOCKED-proposal", len(c) == 10 and (c["Iron Sword"]["buy"], c["Iron Sword"]["sell"]) == (1500, 600)
      and (c["Small HP Potion"]["buy"], c["Small HP Potion"]["sell"]) == (150, 60)
      and (c["Leather Armor"]["buy"], c["Leather Armor"]["sell"]) == (1200, 480) and c["Goblin Charm"]["sell"] == 500)
check("shop stock = 4 sellable items, drop-only absent", [i["name"] for i in I.shop_stock()] == ["Small HP Potion", "HP Potion", "Iron Sword", "Leather Armor"])
s = run("a", ".shop")
check(".shop works from any location, lists 4", all(n in s for n in ("Small HP Potion", "HP Potion", "Iron Sword", "Leather Armor")) and "Slime Core" not in s)
check(".inv and .inventory same output, empty bag", run("a", ".inv") == run("a", ".inventory") and "empty" in run("a", ".inv"))

# ── buy
check("buy with too few coins refused, nothing changes", "Not enough coins" in run("a", ".buy Iron Sword") and pl()["coins"] == 0 and pl()["inventory"] == {})
put("a", coins=2000)
check("buy potion x2", "Bought 2× Small HP Potion for 300" in run("a", ".buy small hp potion 2") and pl()["coins"] == 1700 and pl()["inventory"] == {"Small HP Potion": 2})
check("exact name beats substring ('hp potion')", "Bought 1× HP Potion" in run("a", ".buy hp potion") and pl()["inventory"]["HP Potion"] == 1)
check("ambiguous name asks which", "Which one?" in run("a", ".buy potion"))
check("drop-only item can't be bought", "No item matching" in run("a", ".buy slime core"))
check("bad qty / usage", "Usage" in run("a", ".buy") and "1 or more" in run("a", ".buy small 0"))
check("buy sword with 1400 coins refused (costs 1500)", "Not enough coins" in run("a", ".buy sword"))
put("a", coins=5000)
run("a", ".buy leather"); run("a", ".buy sword")
check("coins deducted correctly", pl()["coins"] == 5000 - 1200 - 1500)

# ── equip + gear maths
p = pl()
check("base damage 20, no bonus", combat.player_damage(p) == 20 and combat.player_max_hp(p) == 200)
out = run("a", ".equip iron sword")
p = pl()
check("equip sword: +10% ATK -> Lv1 damage 22 (floor 22.0)", "Equipped Iron Sword" in out and p["equipped"]["weapon"] == "Iron Sword" and combat.player_damage(p) == 22)
check("equipped item leaves inventory", p["inventory"].get("Iron Sword", 0) == 0)
out = run("a", ".equip leather armor")
p = pl()
check("equip armour: Max HP 200 -> 220", combat.player_max_hp(p) == 220 and "220" in out)
check(".profile shows final Max HP and gear", "HP: 200/220" in run("a", ".profile") and "Iron Sword" in run("a", ".p") and "Leather Armor" in run("a", ".p"))
put("a", inventory={"Goblin Charm": 1, "Iron Sword": 1, "Slime Core": 3})
run("a", ".equip goblin")
p = pl()
check("bonuses stack additively: 10% + 5% of base 200 = 230", combat.player_max_hp(p) == 230)
put("a", level=3, max_hp=400)
p = pl()
check("BaseHP = base Max HP (200+100/level): 400 * 1.15 = 460", combat.player_max_hp(p) == 460)
put("a", level=5, max_hp=600)
check("ATK floor: Lv5 base 40 * 1.10 = 44", combat.player_damage(pl()) == 44)
put("a", level=1, max_hp=200)
run("a", ".equip iron sword")
check("swapping into an occupied slot returns the old item", pl()["inventory"].get("Iron Sword", 0) == 1 and pl()["equipped"]["weapon"] == "Iron Sword")
check("can't equip a material / unowned", "no equipment matching" in run("a", ".equip slime core") and "no equipment matching" in run("a", ".equip leather"))
# unequip caps HP
put("a", hp=230)
out = run("a", ".unequip accessory")
check("unequip accessory: Max HP 230->220, current HP capped", pl()["hp"] == 220 and "Unequipped Goblin Charm" in out and pl()["inventory"].get("Goblin Charm") == 1)
out = run("a", ".unequip armor")
check("unequip armour (alias 'armor'): Max HP 200, HP capped", pl()["hp"] == 200 and combat.player_max_hp(pl()) == 200)
check("unequip empty slot / bad slot", "Nothing is equipped" in run("a", ".unequip armour") and "Usage" in run("a", ".unequip hat"))
put("a", hp=100, max_hp=200)
check("equipping armour doesn't heal", (run("a", ".equip leather"), pl()["hp"])[1] == 100 if "Leather Armor" in pl()["inventory"] else True)

# ── .inv content
put("a", inventory={"Small HP Potion": 2, "Iron Sword": 1, "Wolf Fang": 4}, equipped={"weapon": "Iron Sword", "armour": None, "accessory": None})
inv = run("a", ".inv")
check(".inv shows potions, equipment, materials, quantities, equipped", "Small HP Potion ×2" in inv and "Wolf Fang ×4" in inv and "Weapon: Iron Sword" in inv and "*Potions*" in inv and "*Materials*" in inv)

# ── sell
put("a", coins=0, inventory={"Wolf Fang": 4, "Goblin Charm": 1, "Iron Sword": 1})
out = run("a", ".sell wolf fang 3")
check("sell 3 Wolf Fang = 450, reported", "Sold 3× Wolf Fang for 450" in out and pl()["coins"] == 450 and pl()["inventory"]["Wolf Fang"] == 1)
check("can't sell more than owned / unowned", "only have 1" in run("a", ".sell wolf fang 5") and "don't have" in run("a", ".sell boar tusk"))
run("a", ".sell goblin charm"); run("a", ".sell sword")
check("sell charm 500 + sword 600", pl()["coins"] == 450 + 500 + 600)
check("equipped items are not sellable (not in bag)", "don't have" in run("a", ".sell iron sword"))
check("sell usage", "Usage" in run("a", ".sell"))

# ── .use out of combat
put("a", hp=100, max_hp=200, equipped={"weapon": None, "armour": None, "accessory": None}, inventory={"Small HP Potion": 1, "HP Potion": 1})
check(".use small: +30", "+30 HP" in run("a", ".use small") and pl()["hp"] == 130 and "Small HP Potion" not in pl()["inventory"])
check(".use hp: +60", "+60 HP" in run("a", ".use hp potion") and pl()["hp"] == 190)
put("a", hp=200, inventory={"HP Potion": 1})
check(".use at full HP refused, potion kept", "full HP" in run("a", ".use hp potion") and pl()["inventory"]["HP Potion"] == 1)
check(".use non-potion / none", "no potion matching" in run("a", ".use sword") and "Usage" in run("a", ".use"))
put("a", hp=190)
run("a", ".use hp potion")
check("heal capped at Max HP", pl()["hp"] == 200)

# ── in a fight: equip/use refused, shop still open, combat uses gear
put("a", location="misty_glade", hp=200, max_hp=200, coins=2000, inventory={"Iron Sword": 1}, equipped={"weapon": None, "armour": None, "accessory": None})
run("a", ".equip sword")
combat.start_fight(db, "a", pl(), "g", rng=random.Random(1), monster_id="slime", arm=False)
check(".equip/.unequip/.use refused mid-fight", all("middle of a fight" in run("a", c) for c in (".equip x", ".unequip weapon", ".use hp")))
check(".buy still works mid-fight (shop always accessible)", "Bought" in run("a", ".buy small hp potion"))
class Fx(random.Random):
    def randint(self, a, b): return a
ok, main, _ = combat.act(db, "a", "attack", rng=Fx())
check("equipped sword: fight damage is 22", "hit Slime for 22" in main[0] and store.load_fight(db, "a")["monster"]["hp"] == 53)
# Max HP from gear used for potion cap in fight and respawn heal
put("a", equipped={"weapon": None, "armour": "Leather Armor", "accessory": None}, hp=219, max_hp=200)
combat.act(db, "a", "potion", rng=Fx())
check("in-fight potion capped at FINAL Max HP (220) before monster hit", pl()["hp"] == 220 - 8)
# town heal uses final Max HP
put("a", location="whispering_woods", hp=10); store.delete_fight(db, "a")
import time
journey.start(db, "a", pl(), "south", "g", now=time.time() - 100, rng=Fx(0.99) if False else random.Random(), arm=False)
store.delete_journey(db, "a")
j = {"origin": "whispering_woods", "direction": "south", "destination": "ash_town", "total": 12, "start": time.time() - 100, "group_jid": "g", "event": {"kind": None, "at": 0, "done": True}}
store.save_journey(db, "a", j); journey.resolve(db, "a")
check("entering Ash Town heals to FINAL Max HP (220)", pl()["hp"] == 220)
# level-up heal respects final max
put("a", level=1, xp=0, hp=220, max_hp=200)
p = pl(); msgs = P.grant_xp(p, 100)
check("level-up message shows final Max HP (300*1.1=330)", "now 330" in msgs[0] and p["max_hp"] == 300)
# two players independent
run("b", ".reg Ember"); put("b", coins=300)
run("b", ".buy hp potion")
check("inventories are per player", pl("b")["inventory"] == {"HP Potion": 1})
check("pool off ignores shop commands", mgr.pre_dispatch("b", ".shop", pool_niflheim=False) is m.NOT_HANDLED)
sys.exit(1 if fails else 0)
