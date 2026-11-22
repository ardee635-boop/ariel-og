"""
Golden-output test for CommandRouter.handle(): drives the real router with
~500 scripted inputs (every pool-flag combination, group/DM, every known
command, registered/unregistered senders, special session states) and
compares the replies to tests/golden/handle_golden.json.

Purpose: prove a refactor of handle()/pokemon/chat/normal changed nothing.
No network needed; Ariel's LLM call is stubbed.

  python3 tests/golden_handle_test.py            # compare to golden
  python3 tests/golden_handle_test.py --update   # rewrite golden (only when behaviour is MEANT to change)
  python3 tests/golden_handle_test.py <repo>     # run against another checkout, same golden
"""
import sys, os, tempfile, json, random, io, itertools, contextlib

HERE = os.path.dirname(os.path.abspath(__file__))
args = [a for a in sys.argv[1:] if not a.startswith("--")]
ROOT = os.path.abspath(args[0]) if args else os.path.dirname(HERE)
GOLDEN = os.path.join(HERE, "golden", "handle_golden.json")
E = ROOT + "/engine"
for d in (E, E+"/core", E+"/shared", E+"/pokemon", E+"/pokemon/world", E+"/rpg", E+"/chat"):
    if d not in sys.path: sys.path.append(d)
sys.path.insert(0, E)
_TMP = tempfile.mkdtemp()
os.environ.pop("SUPABASE_DB_URL", None)          # never touch a real database
os.environ["RAILWAY_VOLUME_MOUNT_PATH"] = _TMP   # throwaway SQLite file (db_core puts it here, not in cwd)
os.chdir(_TMP)

Q = lambda: contextlib.redirect_stdout(io.StringIO())
Qe = lambda: contextlib.redirect_stderr(io.StringIO())
with Q(), Qe():
    import models, ariel
    from router import CommandRouter
    from database import Database
    calls, names = [], []
    ariel.ariel_chat = lambda sender, query, **kw: (calls.append(
        (sender, query, kw.get("push_name"), kw.get("group_jid"), kw.get("mentioned_jid")))
        or f"ARIEL<{query}>")
    db = Database()
    db.record_group_name = lambda g, s, n: names.append((g, s, n))
    r = CommandRouter(db)

R, U, G = "222@s.whatsapp.net", "333@s.whatsapp.net", "g1@g.us"
out = {}

def mk(sender, **kw):
    p = models.Player("T"); p.story_stage = "route_1"
    for k, v in kw.items(): setattr(p, k, v)
    r._save(sender, p); r.sessions.pop(sender, None)

def run(label, sender, text, setup=None, group=None, lid=None, push=None, mj=None, **flags):
    random.seed(7)
    r._last_group_jid, r._last_lid, r._last_push_name = group, lid, push
    calls.clear(); names.clear()
    with Q(), Qe():
        if setup: setup()
        try: res = r.handle(sender, text, mentioned_jid=mj, **flags)
        except Exception as e: res = f"EXC {type(e).__name__}: {str(e)[:80]}"
    res = res if res is None or len(str(res)) < 400 else str(res)[:400]
    out[label] = [res, list(calls), list(names)]

# 1. pool-flag matrix x group/DM
for pk, no, ch in itertools.product([0, 1], repeat=3):
    fl = dict(pool_pokemon=bool(pk), pool_normal=bool(no), pool_chat=bool(ch))
    for cmd in (".groupid", ".ping", ".ranks", ".location", ".status", "hello there", "ariel hey you", "Ariel", ".menu"):
        run(f"flags{pk}{no}{ch}|{cmd}|grp", R, cmd, setup=lambda: mk(R), group=G, lid="lid9", push="Rose", mj="x@s", **fl)
        run(f"flags{pk}{no}{ch}|{cmd}|dm", R, cmd, setup=lambda: mk(R), **fl)

# 2. every known command, registered vs not (Pokémon + Normal pools on)
ON = dict(pool_pokemon=True, pool_normal=True, pool_chat=False)
cmds = sorted(r.KNOWN_CMDS) + [".nonsense", ".name Foo", ".swap 1", ".goto x", ".setskill a", ".lb",
                              ".buy potion 1", ".sell potion", "north", "w", "1"]
for c in cmds:
    run(f"unreg|{c}", U, c, **ON)
    run(f"fresh|{c}", R, c, setup=lambda: mk(R), **ON)

# 3. special session / static states
def st(state):
    def f(): mk(R); r._session(R).state = state
    return f
for state in ("dead", "pve_swap", "pvp_blackout", "tutorial", "battle_menu", "encounter", "arena",
              "gym", "raid", "pvp", "pvp_pending", "exploring"):
    for c in (".status", ".flee", ".heal", ".party", ".fight", ".next", ".swap 1", ".foo", ".reset"):
        run(f"state:{state}|{c}", R, c, setup=st(state), **ON)
for c in (".yes", ".status", ".buy x", ".foo", "hi", ".1"):
    run(f"static|{c}", R, c, setup=lambda: mk(R, static_state="oak_lab_1"), **ON)

blob = json.dumps(out, sort_keys=True, indent=0, default=str)
if "--update" in sys.argv:
    os.makedirs(os.path.dirname(GOLDEN), exist_ok=True)
    open(GOLDEN, "w").write(blob); print(f"golden written: {len(out)} scenarios"); sys.exit(0)
gold = json.load(open(GOLDEN)); cur = json.loads(blob)
bad = [k for k in sorted(set(gold) | set(cur)) if gold.get(k) != cur.get(k)]
if bad:
    print(f"FAIL: {len(bad)} of {len(cur)} scenarios differ, first few:")
    for k in bad[:8]: print(" ", k, "\n    golden:", gold.get(k), "\n    now:   ", cur.get(k))
    sys.exit(1)
print(f"ok: {len(cur)} scenarios identical to golden")
