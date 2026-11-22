"""
Regression checks for the session-3 bug fixes. No network needed.

Run from the repo root:  python3 tests/bugfix_regression_test.py
"""
import os, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
E = os.path.join(ROOT, "engine")
for d in (E, *(os.path.join(E, x) for x in
               ("core", "shared", "pokemon", "pokemon/world", "rpg", "chat"))):
    if d not in sys.path:
        sys.path.append(d)
sys.path.insert(0, E)
_TMP = tempfile.mkdtemp()
os.environ.pop("SUPABASE_DB_URL", None)          # never touch a real database
os.environ["RAILWAY_VOLUME_MOUNT_PATH"] = _TMP   # throwaway SQLite file (db_core puts it here, not in cwd)
os.chdir(_TMP)

failures = []
def check(name, fn):
    try:
        fn(); print("ok  ", name)
    except Exception as e:
        failures.append(name); print("FAIL", name, "->", type(e).__name__, e)

def t_dungeon_registers():
    import router.dungeon, dungeon_data
    assert "cinder_hollow" in dungeon_data.DUNGEONS

def t_goto_single_def():
    import ast
    src = open(os.path.join(E, "router", "dungeon.py")).read()
    n = sum(1 for x in ast.parse(src).body
            if isinstance(x, ast.FunctionDef) and x.name == "check_goto_arrival")
    assert n == 1, f"check_goto_arrival defined {n} times"

def t_trainer_commit():
    from combat_session import CombatSession
    cs = CombatSession.__new__(CombatSession)
    cs.arena_trainer_team = [{"name": "Oddish"}]
    cs.clear_encounter = lambda: None
    cs.battle_context = None
    cs.commit_trainer_battle()
    assert {"player_stack", "wild_stack"} <= set(cs.battle_state)

def t_gyms():
    import gym
    P = type("P", (), {})
    anon = P(); anon.badges = []; anon.party = []
    reg = P(); reg.badges = ["Leaf Badge"]; reg.party = [object()]
    assert all(g["status"] == "locked" for g in gym.all_gyms_status(anon))
    g = gym.all_gyms_status(reg)
    assert g[0]["status"] == "open" and g[0]["cleared"] and not g[1]["cleared"]
    for k in ("town_name", "leader", "leader_type", "description", "requirement", "image"):
        assert k in g[0], k

def t_location_and_battle_screen_imports():
    from encounters import battle_screen   # handle.py imports it from here
    import map
    assert callable(map.get_zone_name) and callable(map.render_minimap)

def t_explore_move_text():
    import interfaces, inspect
    assert "{gx}" not in inspect.getsource(interfaces)

def t_bow_shot_json_safe():
    import json, random, townia_trials as t
    for seed in range(20):
        random.seed(seed)
        shot = t.roll_bow_shot()
        json.dumps(shot)                                  # used to raise: set is not JSON serializable
        assert t.resolve_bow_shot(shot["correct_aim"][0], shot)["hit"]

def t_skills_accepts_string_entries():
    # trial rewards ("Weapon Master") are stored as bare strings; .skills used to crash on them
    import router.rpg_cmds.character as ch, inspect
    assert "isinstance(s, dict)" in inspect.getsource(ch)

def t_rpg_dispatch_is_split():
    from router.rpg import RpgManager, NOT_HANDLED
    from router.rpg_cmds import HANDLERS
    from router.rpg_cmds._common import NOT_HANDLED as N2
    assert NOT_HANDLED is N2 and len(HANDLERS) == 8

for n, f in list(globals().items()):
    if n.startswith("t_"):
        check(n[2:], f)
sys.exit(1 if failures else 0)
