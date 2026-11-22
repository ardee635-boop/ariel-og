"""
Where things live. The code is split into folders, but the DATA files
(fonts, assets, items.json, the local SQLite file, caches) stay at the
repo root, so existing deployments and volumes keep working.
"""
import os

ENGINE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # .../engine
ROOT = os.path.dirname(ENGINE_DIR)                                         # repo root
WORLD_DIR = os.path.join(ENGINE_DIR, "pokemon", "world")                   # zone files

# Every folder that holds importable modules. bridge.py adds these to sys.path,
# which is why `from battle import ...` style imports did not have to change.
CODE_DIRS = [
    ENGINE_DIR,
    os.path.join(ENGINE_DIR, "core"),
    os.path.join(ENGINE_DIR, "shared"),
    os.path.join(ENGINE_DIR, "pokemon"),
    WORLD_DIR,
    os.path.join(ENGINE_DIR, "rpg"),
    os.path.join(ENGINE_DIR, "chat"),
]
