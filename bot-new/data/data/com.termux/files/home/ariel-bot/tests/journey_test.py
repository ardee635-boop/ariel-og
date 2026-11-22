"""
Journey (far-destination travel) test — real SQLite + real seeded world,
fake narrator (no network). Run from the repo root:
    python3 tests/journey_test.py
"""
import os, sys, tempfile

os.environ.pop("SUPABASE_DB_URL", None)
os.environ["RAILWAY_VOLUME_MOUNT_PATH"] = tempfile.mkdtemp()

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
ENGINE = os.path.join(ROOT, "engine")
for d in [ENGINE] + [os.path.join(ENGINE, x) for x in os.listdir(ENGINE)
                     if os.path.isdir(os.path.join(ENGINE, x))]:
    sys.path.insert(0, d)

from database import Database
import rpg_places_seed, rpg_movement, rpg_destinations
from rpg_session import RpgSession

db = Database()
rpg_places_seed.seed_hardcoded_tree(db)


def fake_action(text, world_state, db=None, call_groq_fn=None):
    return {"extraction": {"action": text, "type": "narrative"},
            "validation": {"valid": True, "reason": None},
            "resolution": {"mechanical": False, "damage": None, "type_mult": None, "skill_name": None},
            "reply": "Flavour text.", "choices": ["Look around", "Rest"],
            "new_npcs": [], "npc_event": None, "notable_npc_event": None,
            "new_scene_objects": [], "removed_scene_objects": [],
            "item_taken": None, "item_taken_from_hand": None, "item_held": None}


def fresh(loc="townia_church"):
    s = RpgSession("test")
    s.exists = True
    s.location_id = loc
    s.location = db.get_place(loc)["name"]
    s.flags = {}
    return s


def ok(cond, label):
    print(("PASS " if cond else "FAIL ") + label)
    if not cond:
        sys.exit(1)


# 1. route length: church -> square -> west road -> coliseum = 3 legs
s = fresh()
route = rpg_destinations.route_to(db, "townia_church", "coliseum")
ok(route == ["townia_square", "west_district_road", "coliseum"], "BFS route church->coliseum")

# 2. start journey: first leg moves, 2 legs left
r = rpg_movement.handle_move_intent(
    s, db, {"destination": "the coliseum", "plausible": None}, fake_action)
ok(r.moved and r.legs_left == 2, "leg 1 moves, 2 legs left")
ok(s.location_id == "townia_square", "player is at the first hop")
ok(s.flags.get("_journey", {}).get("dest_id") == "coliseum", "journey flag set")
txt = rpg_movement.format_journey_reply(r)
ok("still underway" in txt and "2 legs away" in txt, "footer text")
ch = rpg_movement.with_continue_choice(s, ["Look around", "Rest"])
ok(ch[0] == "Continue journey" and len(ch) == 3, "Continue journey injected as choice 1")

# 3. continue twice -> arrive
r = rpg_movement.continue_journey(s, db, fake_action)
ok(r.moved and r.legs_left == 1 and "1 leg away" in rpg_movement.format_journey_reply(r), "leg 2: 1 leg away")
r = rpg_movement.continue_journey(s, db, fake_action)
ok(r.moved and r.legs_left == 0 and s.location_id == "coliseum", "leg 3 arrives")
ok("_journey" not in s.flags, "journey cleared on arrival")
ok("arrived at" in rpg_movement.format_journey_reply(r), "arrival footer")
ok(rpg_movement.with_continue_choice(s, ["Rest"]) == ["Rest"], "no injection after arrival")

# 4. detour: leave the road mid-journey with a normal move -> journey cleared
s = fresh()
rpg_movement.handle_move_intent(s, db, {"destination": "coliseum", "plausible": None}, fake_action)
rpg_movement.handle_move_intent(s, db, {"destination": "library", "plausible": None}, fake_action)
ok(s.location_id == "townia_library" and "_journey" not in s.flags, "explicit move cancels journey")

# 5. wander mid-journey then continue: re-routes from where you actually are
s = fresh()
rpg_movement.handle_move_intent(s, db, {"destination": "coliseum", "plausible": None}, fake_action)
s.location_id, s.location = "townia_market", "the market"   # drifted off the path
r = rpg_movement.continue_journey(s, db, fake_action)
ok(r.moved and s.location_id == "townia_square" and r.legs_left == 2, "re-routes from the market")

# 6. nearby moves are untouched (no journey)
s = fresh()
r = rpg_movement.handle_move_intent(s, db, {"destination": "square", "plausible": None}, fake_action)
ok(r.moved and r.legs_left is None and "_journey" not in s.flags, "adjacent move is an ordinary move")

# 7. nonsense destination is still a plain miss
s = fresh()
r = rpg_movement.handle_move_intent(s, db, {"destination": "zzqxv castle", "plausible": None}, fake_action)
ok(not r.moved and "Nowhere called" in (r.reason or ""), "unknown place still misses")

# 8. continue-phrase matching
for t in ("Continue journey", "continue", "keep going", "Go on!"):
    ok(rpg_movement.is_continue_text(t), f"continue phrase: {t}")
ok(not rpg_movement.is_continue_text("I continue to eat my bread"), "free text is not 'continue'")
print("ALL PASSED")

# 9. outside the wall: the dungeon is 5 legs from the square (gate -> 3 forest rings -> entrance)
route = rpg_destinations.route_to(db, "townia_square", "townia_dungeon_entrance")
ok(route == ["northern_gate", "outer_forest_road", "inner_forest_road",
             "deep_forest_road", "townia_dungeon_entrance"], "square -> dungeon is 5 legs through the forest")
for typed, dest in (("the dungeon", "townia_dungeon_entrance"), ("the lake", "townia_lakeshore"),
                    ("waterfall", "townia_falls_pool"), ("ruins", "townia_ruin_court")):
    s_ = fresh("townia_square")
    r = rpg_movement.handle_move_intent(s_, db, {"destination": typed, "plausible": None}, fake_action)
    ok(r.moved and s_.flags.get("_journey", {}).get("dest_id") == dest, f"'{typed}' starts a journey to {dest}")

# 10. closed world: Townia never invents places, even when the intent says "plausible"
for plaus in (True, False):
    s_ = fresh("townia_square")
    before = len(db._fetchall(db._ex("SELECT id FROM rpg_places")))
    r = rpg_movement.handle_move_intent(
        s_, db, {"destination": "a hidden cellar", "plausible": plaus}, fake_action)
    after = len(db._fetchall(db._ex("SELECT id FROM rpg_places")))
    ok(not r.moved and before == after and s_.location_id == "townia_square",
       f"Townia refuses speculative place (plausible={plaus}), nothing created")

# 11. matcher: directions can't cross, left/right unsupported, adjectives work
def dest(frm, text):
    r = rpg_destinations.resolve_destination(db, text, db.get_place(frm))
    return (r["place"] or {}).get("id"), r["ambiguous"]
ok(dest("coliseum", "east district")[0] is None, "'east district' from the Coliseum no longer walks west")
ok(dest("townia_pet_shop", "left district")[0] is None, "'left district' finds nothing")
ok(dest("townia_square", "eastern")[0] == "townia_market", "'eastern' -> market")
ok(dest("townia_pet_shop", "east") == ("townia_market", []), "'east' at the pet shop is not ambiguous")
ok(dest("townia_square", "libary")[0] == "townia_library", "typo 'libary' still works")
ok(dest("south_district_road", "garden")[0] == "townia_garden_shop", "'garden' still the garden shop")

# 12. seed integrity: tiers, aliases, reachability
places_, _ = rpg_places_seed.build_world_tree()
order = ["dimension", "continent", "region", "nation", "state", "area",
         "district", "location", "landmark", "feature"]
byid = {p.id: p for p in places_}
ok(len(byid) == len(places_), "place ids are unique")
bad = [p.id for p in places_ if p.parent_id and not (
    order.index(p.tier) - order.index(byid[p.parent_id].tier) == 1 or
    (p.tier != "district" and order.index(p.tier) - order.index(byid[p.parent_id].tier) == 2
     and byid[p.parent_id].tier == "area"))]
ok(not bad, f"every parent is one tier up (or skips only the district): {bad}")
ok(all(p.id in rpg_destinations.ALIASES for p in places_ if p.tier == "location"), "every location has aliases")
routes_ = rpg_destinations.bfs_routes(db, "townia_square")
ok(all(p.id in routes_ for p in places_ if p.tier == "location" and p.dimension_id == "townia_dim"),
   "every Townia location is reachable from the square")
print("ALL SPEC CHECKS PASSED")
