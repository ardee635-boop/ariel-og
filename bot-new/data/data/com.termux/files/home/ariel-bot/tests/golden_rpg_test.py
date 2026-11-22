"""
Golden-output test for RpgManager (router/rpg.py): drives pre_dispatch() with
~hundreds of scripted multi-step scenarios - registration, inventory, free-text
turns, sim fights, real fights, every Warrior/Mage/Summoner trial phase and the
pending-class prompt - and compares every reply to tests/golden/rpg_golden.json.

Purpose: prove that cutting _dispatch into smaller modules changed nothing.
No network: the LLM boundary (rpg_engine.handle_rpg_action, rpg_llm.call_groq)
is stubbed at its SOURCE module before the router is imported, so the stubs
still apply when the code later moves into other router files.

  python3 tests/golden_rpg_test.py              # compare to golden
  python3 tests/golden_rpg_test.py --update     # rewrite golden (only when behaviour is MEANT to change)
  python3 tests/golden_rpg_test.py --coverage   # also print which router/rpg*.py lines never ran
  python3 tests/golden_rpg_test.py <repo>       # run against another checkout, same golden
"""
import sys, os, tempfile, json, random, io, re, contextlib, dis, types

HERE = os.path.dirname(os.path.abspath(__file__))
args = [a for a in sys.argv[1:] if not a.startswith("--")]
ROOT = os.path.abspath(args[0]) if args else os.path.dirname(HERE)
GOLDEN = os.path.join(HERE, "golden", "rpg_golden.json")
E = ROOT + "/engine"
for d in (E, E+"/core", E+"/shared", E+"/pokemon", E+"/pokemon/world", E+"/rpg", E+"/chat"):
    if d not in sys.path: sys.path.append(d)
sys.path.insert(0, E)
_TMP = tempfile.mkdtemp()
os.environ.pop("SUPABASE_DB_URL", None)          # never touch a real database
os.environ["RAILWAY_VOLUME_MOUNT_PATH"] = _TMP   # throwaway SQLite file
os.chdir(_TMP)

WANT_COV = "--coverage" in sys.argv
_hit = {}                                         # filename -> set(lines)
def _tracer(frame, event, arg):
    fn = frame.f_code.co_filename
    if "/router/rpg" not in fn.replace("\\", "/"):
        return None
    s = _hit.setdefault(fn, set())
    def local(frame, event, arg):
        if event == "line": s.add(frame.f_lineno)
        return local
    s.add(frame.f_lineno)
    return local

Q = lambda: contextlib.redirect_stdout(io.StringIO())
Qe = lambda: contextlib.redirect_stderr(io.StringIO())

with Q(), Qe():
    # ---- stub the LLM boundary at the source, BEFORE the router is imported ----
    import rpg_engine, rpg_llm
    rpg_llm.call_groq = lambda *a, **k: None

    def fake_engine(rest, world, db=None):
        t = rest.lower()
        res = {"reply": f"NARRATE<{rest}>", "choices": ["look around", "wait"],
               "extraction": {"action": {"type": "say", "text": rest}},
               "validation": {"valid": True}}
        m = re.search(r"take (\w+)", t)
        if m: res["item_taken"] = m.group(1)
        m = re.search(r"grab (\w+)", t)
        if m: res["item_taken"] = m.group(1); res["item_taken_from_hand"] = "right"
        m = re.search(r"hold (\w+)", t)
        if m: res["item_held"] = {"hand": "right", "name": m.group(1)}
        m = re.match(r"trial (warrior|mage|summoner)(?: (\w+))?", t)
        if m:
            res["trial_start"] = m.group(1)
            if m.group(2): res["trial_weapon"] = m.group(2)
        if t.startswith("fight"): res["combat_start"] = True
        if "npc" in t: res["new_npcs"] = [{"name": "Bob", "hostile": False}]
        if "invalid" in t: res["validation"] = {"valid": False}
        if "nochoices" in t: res["choices"] = []
        return res
    rpg_engine.handle_rpg_action = fake_engine

    import models, permissions
    permissions.KING_NUMBER = "999"
    permissions.KING_JID = "999@s.whatsapp.net"
    from router import CommandRouter
    from router.rpg import NOT_HANDLED
    from database import Database
    from rpg_session import RpgSession
    import townia_trials as trials
    db = Database()
    r = CommandRouter(db)

    # Real, hand-authored world (places with monster pools, the church, ...)
    import rpg_places_seed, rpg_scene
    rpg_places_seed.seed_hardcoded_tree(db)

    # Open5e is a network API; pre-fill the in-memory cache so sim/real fights
    # are deterministic and offline. Names not listed here stay "not found"
    # on purpose (that error branch is part of the golden).
    import soulbound_rpg
    def fake_creature(name):
        n = sum(map(ord, name))
        return {"name": name, "challenge_rating": 1 + n % 3, "hit_points": 18 + n % 17,
                "armor_class": 11 + n % 4,
                "ability_scores": {"strength": 8 + n % 9, "dexterity": 9 + n % 7, "constitution": 10 + n % 5,
                                   "intelligence": 3 + n % 6, "wisdom": 8, "charisma": 5},
                "speed_all": {"walk": 30}, "traits": [{"name": "Keen Senses", "desc": "Sharp."}],
                "actions": [{"name": "Bite", "desc": "Melee Weapon Attack: +4 to hit, 5 (1d6+2) piercing damage.",
                             "attack_bonus": 4, "damage_dice": "1d6", "damage_bonus": 2}]}
    for _name in ["Goblin", "Wolf", "Skeleton", "Giant Rat", "Zombie", "Kobold", "Giant Spider", "Orc",
                  "Bandit", "Stirge", "Boar", "Dire Wolf", "Giant Boar", "Black Bear", "Hobgoblin", "Bugbear"]:
        soulbound_rpg._MONSTER_CACHE[_name.lower()] = fake_creature(_name)

out = {}
_n = [0]
def new_sender():
    _n[0] += 1
    return f"{5000 + _n[0]}@s.whatsapp.net"

def say(sender, text, pool=True):
    random.seed(7)
    with Q(), Qe():
        try: res = r.rpg.pre_dispatch(sender, text, pool_rpg=pool)
        except Exception as e: res = f"EXC {type(e).__name__}: {str(e)[:80]}"
    with Q(), Qe():
        try: rpg_scene.run_after_reply(sender)       # the bridge runs this right after sending the reply
        except Exception as e: out.setdefault("_scene_exc", []).append(f"{type(e).__name__}: {str(e)[:60]}")
    if res is NOT_HANDLED: res = "NOT_HANDLED"
    return res if res is None or len(str(res)) < 500 else str(res)[:500]

def edit(sender, fn):
    with Q(), Qe():
        s = RpgSession.load(db, sender); fn(s); s.save(db)

def register(sender, name="Hiro"):
    say(sender, ".reg"); say(sender, f".setname {name}")

def scenario(name, steps, reg=True, prep=None, sender=None):
    """steps: strings, or callables(sender)->str for text that depends on state.
    A step may also be ('edit', fn) to mutate the session between turns."""
    s = sender or new_sender()
    if reg: register(s)
    if prep: edit(s, prep)
    for i, step in enumerate(steps):
        if isinstance(step, tuple) and step[0] == "edit":
            edit(s, step[1]); continue
        text = step(s) if callable(step) else step
        if text.startswith(("trial ", "fight ")): text = ".rpg " + text   # trigger phrases for the fake engine
        out[f"{name}|{i}|{text}"] = say(s, text)
    return s

def flags(s, fn):                      # tiny helper for prep lambdas
    def _p(sess): fn(sess.flags)
    return _p

def trial_state(s):
    with Q(), Qe(): return RpgSession.load(db, s).flags.get("trial")

if WANT_COV: sys.settrace(_tracer)

# ---------------------------------------------------------------- 1. gating / unregistered
KNOWN = [".reg", ".setname Bob", ".rmenu", ".status", ".skills", ".skill", ".inv", ".equip sword",
         ".rpg", ".rpg look", ".rpg state", ".rpg sim", ".rpg sim end", ".rpg reset", ".resetworld",
         ".rpg yes", ".rpg attack", ".nonsense", "hello", "", "   "]
for c in KNOWN:
    s = new_sender()
    out[f"noreg|{c}"] = say(s, c)
    out[f"nopool|{c}"] = say(new_sender(), c, pool=False)
for c in (".rpg on", ".rpg off", ".RPG ON"):
    out[f"toggle|{c}|pool"] = say(new_sender(), c, True)
    out[f"toggle|{c}|nopool"] = say(new_sender(), c, False)

# ---------------------------------------------------------------- 2. registration flow
scenario("reg", [".reg", ".reg", ".setname", ".setname <>", ".setname bob", ".setname Bob again", ".reg",
                 ".rpg reset", ".reg"], reg=False)
scenario("reg_long", [".reg", ".setname " + "x" * 50, ".status"], reg=False)
scenario("reg_lower", [".reg", ".setname   zed  ", ".status", ".skills", ".skill"], reg=False)
scenario("setname_noreg", [".setname Bob"], reg=False)
scenario("midreg_cmds", [".reg", ".status", ".inv", ".rpg look", ".rpg state", ".rmenu", ".equip sword"], reg=False)

# ---------------------------------------------------------------- 3. registered, idle
scenario("idle", [".status", ".skills", ".skill", ".rmenu", ".inv", ".equip", ".equip sword",
                  ".rpg", ".rpg state", ".rpg look around", ".rpg 1", ".rpg 2", ".rpg 9", ".rpg 0",
                  ".rpg yes", ".rpg no", ".rpg attack", ".rpg give up", ".rpg sim end", ".nonsense",
                  ".rpg reset", ".status", ".rpg look"])
scenario("inventory", [".inv", ("edit", lambda s: s.soulbound.__setitem__("inventory", ["sword", "torch"])),
                       ".inv", ".equip sword", ".inv", ".equip", ".equip TORCH", ".equip bogus", ".inv",
                       ".rpg state", ".status"])

# ---------------------------------------------------------------- 4. free-text turns (fake engine)
scenario("free", [".rpg I walk north", ".rpg take lantern", ".inv", ".rpg grab rope", ".inv",
                  ".rpg hold torch", ".rpg state", ".rpg npc appears", ".rpg invalid move",
                  ".rpg nochoices please", ".rpg 1", ".rpg 2", ".rpg 5", ".rpg look", ".rpg 1",
                  ".rpg state", ".status"])
scenario("choices", [".rpg 1", ".rpg 2", ".rpg 3", ".rpg 4", ".rpg hello", ".rpg 1", ".rpg 2", ".rpg 3"])
scenario("pickup_hand", [".rpg take sword", ".rpg hold sword", ".rpg grab sword", ".rpg grab sword", ".inv", ".rpg hold axe", ".rpg grab bow", ".rpg grab axe", ".rpg state"])
scenario("rmenu_misc", [".rmenu", ".rpg", ".RPG state", ".Rpg Look"])

# ---------------------------------------------------------------- 5. sim fights
scenario("sim", [".rpg sim", ".rpg sim", ".rpg sim attack", ".rpg sim block", ".rpg sim attack",
                 ".rpg sim attack", ".rpg sim attack", ".rpg sim attack", ".rpg sim end", ".rpg sim end"])
scenario("sim_args", [".rpg sim sword goblin 3", ".rpg sim", ".rpg sim end", ".rpg sim bow wolf 2",
                      ".rpg sim", ".rpg sim end", ".rpg sim dagger", ".rpg sim end", ".rpg sim mace 1",
                      ".rpg sim end", ".rpg sim spear boar", ".rpg sim end", ".rpg sim axe", ".rpg sim end",
                      ".rpg sim nonsense words here", ".rpg sim end"])
scenario("sim_long", [".rpg sim sword"] + [".rpg sim attack"] * 14 + [".rpg sim", ".rpg sim end"])
scenario("sim_during", [".rpg sim", ".status", ".inv", ".rpg look", ".rpg state", ".rpg yes", ".rpg sim end"])

# ---------------------------------------------------------------- 6. real fights
FOREST = lambda s: setattr(s, "location_id", "outer_forest_road")
def STRONG(sess):
    for k in list(sess.soulbound.get("stats", {})): sess.soulbound["stats"][k] = 400

scenario("fight_forest", ["fight the wolf", ".rpg attack", ".rpg attack", ".rpg block", ".rpg attack",
                          ".status", ".inv", ".rpg state", ".rpg look", ".rpg sim", ".rpg sim end",
                          ".rpg attack", ".rpg attack", ".rpg attack", ".rpg attack", ".rpg attack",
                          ".rpg attack", ".rpg attack", ".rpg attack", ".rpg state", ".rpg look"], prep=FOREST)
scenario("fight_forest_flee", ["fight the wolf", ".rpg flee", ".rpg run away", ".rpg attack", ".rpg state",
                               ".rpg dodge", ".rpg use potion", ".rpg heal", ".rpg guard"], prep=FOREST)
scenario("fight_equipped", [("edit", lambda s: s.soulbound.__setitem__("inventory", ["sword"])),
                            ".equip sword", "fight the goblin", ".rpg attack", ".rpg attack", ".rpg attack",
                            ".rpg attack", ".rpg attack"], prep=FOREST)
scenario("fight_town", ["fight the guard", ".rpg look", ".rpg attack"])
scenario("fight_in_trial", ["trial mage", "fight the guard", ".rpg look"], prep=FOREST)
scenario("fight_twice", ["fight a", "fight b", ".rpg attack", ".rpg attack"], prep=FOREST)

scenario("sim_finish_a", [".rpg sim sword goblin 1"] + [".rpg sim attack"] * 34 + [".rpg sim", ".rpg sim end"], prep=lambda s: STRONG(s))
scenario("sim_finish_b", [".rpg sim bow wolf 1"] + [".rpg sim shoot"] * 34 + [".rpg sim"], prep=lambda s: STRONG(s))
scenario("sim_weapon_last", [".rpg sim goblin sword", ".rpg sim end", ".rpg sim giant rat 2 bow", ".rpg sim end",
                             ".rpg sim zombie 3 dagger", ".rpg sim end", ".rpg sim sword", ".rpg sim end"])
scenario("fight_long", ["fight the wolf", ".rpg"] + [".rpg attack"] * 30 + [".rpg", ".rpg look"], prep=lambda s: (FOREST(s), STRONG(s)))
scenario("fight_long_weak", ["fight the wolf", ".rpg"] + [".rpg attack"] * 30 + [".rpg", ".rpg look"], prep=FOREST)
scenario("fight_long_goblin", ["fight the goblin"] + [".rpg strike hard"] * 25 + [".rpg", ".rpg state"], prep=lambda s: (FOREST(s), STRONG(s)))

# ---------------------------------------------------------------- 7. warrior trials
def fight_adapt(s):                    # keep striking while the trial runs, then answer the class prompt
    return ".rpg attack" if trial_state(s) else ".rpg yes"
def fight_adapt_no(s):
    return ".rpg attack" if trial_state(s) else ".rpg no"

for w in ("sword", "dagger", "spear", "axe", "mace"):
    scenario(f"war_fight_{w}", [f"trial warrior {w}", ".rpg look", ".status"] + [".rpg attack"] * 4)
    scenario(f"war_win_{w}", [f"trial warrior {w}"] + [fight_adapt] * 3 + [".status", ".skills", ".inv"], prep=STRONG)
    scenario(f"war_win_{w}_no", [f"trial warrior {w}"] + [fight_adapt_no] * 3 + [".status"], prep=STRONG)
    scenario(f"war_win_{w}_text", [f"trial warrior {w}"] + [".rpg strike"] * 6 + [".rpg something else", ".status"], prep=STRONG)
scenario("war_choose", ["trial warrior", ".rpg look", ".rpg pizza", ".rpg sword", ".rpg attack", ".rpg attack"])
for w in ("sword", "dagger", "spear", "axe", "mace", "shield", "bow", "nonsense"):
    scenario(f"war_pick_{w}", ["trial warrior", f".rpg {w}"] + [".rpg attack"] * 3)
scenario("war_choose_cases", ["trial warrior", ".rpg SWORD", ".rpg attack", ".rpg Attack"])
SHIELD = ["left", "right", "up", "down", "block left", "block right", "high", "low", "duck", "raise shield",
          "i block", "left", "right", "up", "down", "left", "right", "high", "low", "left", "right"]
scenario("war_shield", ["trial warrior shield", ".rpg look"] + [f".rpg {d}" for d in SHIELD] + [".rpg yes", ".status"])
scenario("war_shield_strong", ["trial warrior shield"] + [f".rpg {d}" for d in SHIELD] + [".rpg yes", ".status"], prep=STRONG)
scenario("war_shield_strong2", ["trial warrior shield"] + [f".rpg {d}" for d in SHIELD * 2] + [".rpg no"], prep=STRONG)
scenario("war_shield_vague", ["trial warrior shield"] + [".rpg block"] * 14 + [".rpg yes"])
scenario("war_shield_via_choice", ["trial warrior", ".rpg shield"] + [f".rpg {d}" for d in SHIELD[:18]] + [".rpg no"])
BOW = ["shoot", "aim left", "aim right", "aim high", "aim low", "aim up", "aim down", "left", "right", "up", "down",
       "aim high and left", "compensate for wind", "fire", "release", "aim", "shoot", "aim left", "aim right",
       "aim high", "aim low", "left", "right", "up", "down"]
scenario("war_bow", ["trial warrior bow", ".rpg look"] + [f".rpg {d}" for d in BOW] + [".rpg yes", ".status"])
scenario("war_bow_via_choice", ["trial warrior", ".rpg bow"] + [f".rpg {d}" for d in BOW[:20]] + [".rpg no"])
scenario("war_bow_strong", ["trial warrior bow"] + [f".rpg {d}" for d in BOW * 2] + [".rpg yes", ".status"], prep=STRONG)
scenario("war_bow_vague", ["trial warrior bow"] + [".rpg shoot"] * 16 + [".rpg yes"])
scenario("war_trial_interrupt", ["trial warrior sword", ".status", ".inv", ".rpg state", ".rpg sim",
                                 ".rpg sim end", ".rpg 1", "take rope", ".rpg attack"])

def shield_adapt(s):
    t = trial_state(s)
    return ".rpg block " + t["_pending_direction"] if t and "_pending_direction" in t else ".rpg block"
def shield_wrong(s):
    t = trial_state(s)
    d = t["_pending_direction"] if t and "_pending_direction" in t else "front"
    return ".rpg block " + ("left" if d != "left" else "right")
def bow_adapt(s):
    t = trial_state(s)
    return ".rpg aim " + t["_shot"]["correct_aim"][0] if t and "_shot" in t else ".rpg aim"
scenario("war_shield_adapt", ["trial warrior shield"] + [shield_adapt] * 12 + [".rpg yes", ".status", ".skills"], prep=STRONG)
scenario("war_shield_adapt_no", ["trial warrior shield"] + [shield_adapt] * 12 + [".rpg no"], prep=STRONG)
scenario("war_shield_mixed", ["trial warrior shield"] + [shield_adapt, shield_wrong] * 8 + [".rpg yes"], prep=STRONG)
scenario("war_shield_wrong", ["trial warrior shield"] + [shield_wrong] * 5 + [".rpg look"], prep=STRONG)
scenario("war_bow_adapt", ["trial warrior bow"] + [bow_adapt] * 12 + [".rpg yes", ".status", ".skills"], prep=STRONG)
scenario("war_bow_adapt_no", ["trial warrior bow"] + [bow_adapt] * 12 + [".rpg no"], prep=STRONG)
scenario("war_bow_mixed", ["trial warrior bow"] + [bow_adapt, ".rpg aim nowhere"] * 8 + [".rpg yes"], prep=STRONG)

def ALL_BUT(w):
    def _p(sess):
        sess.soulbound["cleared_weapons"] = [x for x in trials.WARRIOR_WEAPONS if x != w]
        STRONG(sess)
    return _p
for w in ("sword", "dagger", "spear", "axe", "mace"):
    scenario(f"war_last_{w}", [f"trial warrior {w}"] + [fight_adapt] * 3 + [".status", ".skills", ".inv"], prep=ALL_BUT(w))
    scenario(f"war_last_{w}_no", [f"trial warrior {w}"] + [fight_adapt_no] * 3 + [".status", ".skills"], prep=ALL_BUT(w))
scenario("war_last_shield", ["trial warrior shield"] + [shield_adapt] * 12 + [".rpg yes", ".status", ".skills"], prep=ALL_BUT("shield"))
scenario("war_last_bow", ["trial warrior bow"] + [bow_adapt] * 12 + [".rpg yes", ".status", ".skills"], prep=ALL_BUT("bow"))

def CLEARED(n):
    def _p(sess):
        sess.soulbound["cleared_weapons"] = ["sword", "dagger", "spear", "axe", "mace", "shield", "bow"][:n]
        STRONG(sess)
    return _p
for n_done in (2, 5, 6):
    scenario(f"war_clear_{n_done}", ["trial warrior sword"] + [fight_adapt] * 3 + [".status", ".skills"], prep=CLEARED(n_done))
    scenario(f"war_clear_bow_{n_done}", ["trial warrior bow"] + [bow_adapt] * 12 + [".rpg yes", ".status", ".skills"], prep=CLEARED(n_done))
    scenario(f"war_clear_shield_{n_done}", ["trial warrior shield"] + [shield_adapt] * 12 + [".rpg yes", ".status", ".skills"], prep=CLEARED(n_done))

# ---------------------------------------------------------------- 8. mage trial
FAR, PAST = 9e12, 0
def mage_set(delete_at, fired=False):
    def _f(s):
        d = s.flags["trial"]["incantation_data"]
        d["delete_at"] = delete_at; d["shown_at"] = 1.0
        if fired: d["delete_fired"] = True
        s.flags["trial"]["phase"] = "awaiting_recast" if fired else "shown"
    return _f
def inc(s):
    t = trial_state(s)
    return ".rpg " + t["incantation_data"]["incantation"]
def inc_lower(s): return inc(s).lower()
scenario("mage_early_ok", ["trial mage", ("edit", mage_set(FAR)), ".rpg look", inc, ".rpg yes", ".status"])
scenario("mage_early_wrong", ["trial mage", ("edit", mage_set(FAR)), ".rpg wrong words", ".rpg more wrong",
                              inc, ".rpg no"])
scenario("mage_late_ok", ["trial mage", ("edit", mage_set(PAST)), inc, ".rpg yes"])
scenario("mage_late_first_msg_ok", ["trial mage", ("edit", mage_set(PAST)), ".rpg anything", inc, ".rpg yes"])
scenario("mage_late_wrong", ["trial mage", ("edit", mage_set(PAST)), ".rpg nope"] + [".rpg nah"] * 6 + [inc])
scenario("mage_fired_ok", ["trial mage", ("edit", mage_set(PAST, fired=True)), inc, ".rpg yes"])
scenario("mage_fired_wrong", ["trial mage", ("edit", mage_set(PAST, fired=True))] + [".rpg wrong"] * 8 + [inc])
scenario("mage_fired_case", ["trial mage", ("edit", mage_set(PAST, fired=True)), inc_lower, ".rpg yes"])
scenario("mage_giveup", ["trial mage", ("edit", mage_set(FAR)), ".rpg give up", ".status", ".rpg look"])
scenario("mage_giveup_late", ["trial mage", ("edit", mage_set(PAST, fired=True)), ".rpg wrong", ".rpg give up", ".rpg look"])
scenario("mage_giveup_other", [".rpg give up", "trial warrior", ".rpg give up", ".rpg look"])
scenario("mage_giveup_phase", ["trial mage", ("edit", lambda s: s.flags["trial"].__setitem__("phase", "resting")),
                               ".rpg give up", ".rpg look"])
scenario("mage_interrupt", ["trial mage", ("edit", mage_set(FAR)), ".status", ".inv", ".rpg state", ".rpg sim",
                            ".rpg sim end", "take rope"])

# ---------------------------------------------------------------- 9. summoner trial
SPECIES = list(trials.SUMMONER_SPECIES) + ["cats", "dogs", "birds", "dragon", "dragons"]
scenario("summ_start", ["trial summoner", ".rpg look", ".status"])
scenario("summ_species", ["trial summoner"] + [f".rpg {sp}" for sp in SPECIES] + [".rpg nonsense", ".rpg 3"])
scenario("summ_slots", ["trial summoner"] + [f".rpg {sp} {n}" for sp in SPECIES[:5] for n in (1, 3, 10, 11, 0)]
         + [".rpg 5", ".rpg cat cat", ".rpg  "])
scenario("summ_slots_first", ["trial summoner"] + [f".rpg {sp} {n}" for sp in ("cat", "fox", "ferret") for n in (1, 5, 10)])
scenario("summ_slot_noopen", ["trial summoner", ".rpg cat 11", ".rpg cat 0", ".rpg dog 4", ".rpg dog", ".rpg dog 4"])
scenario("summ_bond", ["trial summoner", ".rpg cat 1", ".rpg cat 2", ".rpg yes", ".rpg bond", ".rpg dog 1 bond",
                       ".rpg confirm", ".rpg choose cat 1", ".status", ".rpg look", ".rpg cat", ".rpg fox 3"])
scenario("summ_words", ["trial summoner", ".rpg cat words", ".rpg dog first pen", ".rpg cat x 3"])
scenario("summ_interrupt", ["trial summoner", ".status", ".inv", ".rpg state", ".rpg sim", ".rpg sim end",
                            "take rope", ".rpg give up"])

# ---------------------------------------------------------------- 10. pending class
def pend(*cls, extra=()):
    def _p(sess):
        sess.flags["pending_class"] = cls[0]
        if extra: sess.flags["pending_class_extra"] = list(extra)
    return _p
for cl in sorted(set(trials.CLASS_STARTING_WEAPON) | {"warrior", "mage", "summoner", "priest"}):
    scenario(f"pend_yes_{cl}", [".rpg yes", ".status", ".inv", ".skills", ".rpg yes"], prep=pend(cl))
    scenario(f"pend_no_{cl}", [".rpg no", ".status", ".rpg no"], prep=pend(cl))
    scenario(f"pend_text_{cl}", [".rpg I walk away", ".status", ".rpg yes"], prep=pend(cl))
scenario("pend_extra", [".rpg yes", ".status", ".inv", ".skills"], prep=pend("warrior", extra=tuple(sorted(trials.CLASS_STARTING_WEAPON))[:2]))
scenario("pend_extra_no", [".rpg no", ".status"], prep=pend("warrior", extra=tuple(sorted(trials.CLASS_STARTING_WEAPON))[:1]))
scenario("pend_other_cmds", [".status", ".inv", ".equip", ".rpg state", ".rpg sim", ".rpg sim end", ".rpg yes"], prep=pend("mage"))
scenario("pend_YES", [".rpg YES", ".rpg Yes", ".rpg yes "], prep=pend("mage"))

# ---------------------------------------------------------------- 11. world reset / misc
scenario("resetworld_non_king", [".resetworld"])
ks = "999@s.whatsapp.net"
scenario("resetworld_king", [".resetworld", ".status", ".rpg look"], sender=ks)
scenario("resetworld_king_noreg", [".resetworld"], reg=False)
scenario("reset_then_play", [".rpg reset", ".status", ".reg", ".setname Again", ".rpg look", ".rpg delete", ".status"])
scenario("quoted_group", [".status"])
out["quoted|.status"] = None
with Q(), Qe():
    try:
        random.seed(7); s = new_sender(); register(s)
        out["quoted|.rpg look"] = r.rpg.pre_dispatch(s, ".rpg look", quoted_text="x", group_jid="g@g.us", pool_rpg=True)
    except Exception as e:
        out["quoted|.rpg look"] = f"EXC {type(e).__name__}: {e}"
out["quoted|.rpg look"] = str(out["quoted|.rpg look"])[:500]

if WANT_COV:
    sys.settrace(None)
    for fn, lines in sorted(_hit.items()):
        src = open(fn, encoding="utf-8").read()
        code = compile(src, fn, "exec")
        exe = set()
        def walk(c):
            for _, ln in dis.findlinestarts(c):
                if ln: exe.add(ln)
            for k in c.co_consts:
                if isinstance(k, types.CodeType): walk(k)
        walk(code)
        # drop docstring/blank/comment-only lines (not in findlinestarts) automatically
        miss = sorted(exe - lines)
        pct = 100 * (len(exe) - len(miss)) / max(1, len(exe))
        print(f"COVERAGE {os.path.relpath(fn, ROOT)}: {pct:.1f}% ({len(exe) - len(miss)}/{len(exe)})")
        if miss:
            runs, a = [], miss[0]; p = a
            for m in miss[1:]:
                if m != p + 1: runs.append((a, p)); a = m
                p = m
            runs.append((a, p))
            print("  never ran:", ", ".join(f"{x}" if x == y else f"{x}-{y}" for x, y in runs))

if "--update" in sys.argv:
    os.makedirs(os.path.dirname(GOLDEN), exist_ok=True)
    json.dump(out, open(GOLDEN, "w"), indent=0, sort_keys=True, ensure_ascii=False)
    print(f"golden written: {len(out)} scenarios"); sys.exit(0)

gold = json.load(open(GOLDEN))
cur = json.loads(json.dumps(out, ensure_ascii=False))
bad = [k for k in sorted(set(gold) | set(cur)) if gold.get(k) != cur.get(k)]
if bad:
    print(f"FAIL: {len(bad)} of {len(cur)} scenarios differ, first few:")
    for k in bad[:8]: print(" ", k, "\n    golden:", gold.get(k), "\n    now:   ", cur.get(k))
    sys.exit(1)
print(f"ok: {len(cur)} scenarios identical to golden")
