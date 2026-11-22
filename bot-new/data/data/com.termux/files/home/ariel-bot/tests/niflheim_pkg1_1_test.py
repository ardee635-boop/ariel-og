# Package 1.1 tests — run: python3 tests/niflheim_pkg1_1_test.py
import os, sys, json
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "engine"))
import importlib.util
spec = importlib.util.spec_from_file_location("nif_router", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "engine", "router", "niflheim.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
mgr = m.NiflheimManager(None)
fails = 0
def check(name, cond):
    global fails
    print(("PASS " if cond else "FAIL ") + name); fails += (not cond)

check("pool off: .nmenu not handled", mgr.pre_dispatch("s", ".nmenu", pool_niflheim=False) is m.NOT_HANDLED)
check("pool off: .boss not handled", mgr.pre_dispatch("s", ".boss", pool_niflheim=False) is m.NOT_HANDLED)
check("pool on: .nmenu shows menu", "NIFLHEIM COMMANDS" in mgr.pre_dispatch("s", ".nmenu", pool_niflheim=True))
check("pool off: .boss/.dungeon/.arena not handled", all(mgr.pre_dispatch("s", c, pool_niflheim=False) is m.NOT_HANDLED for c in (".boss", ".dungeon", ".arena")))
check("no commands locked any more", not m.STUB_CMDS and "🔒" not in m.NMENU)
check("pool on: plain text ignored", mgr.pre_dispatch("s", "hello", pool_niflheim=True) is m.NOT_HANDLED)
check(".battle absent from menu", ".battle" not in m.NMENU)
cfg = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "engine", "niflheim", "data", "config.json")))
check("config.json valid", isinstance(cfg, dict))
sys.exit(1 if fails else 0)
