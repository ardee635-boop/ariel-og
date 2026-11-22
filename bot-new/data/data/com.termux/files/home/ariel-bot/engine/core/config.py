"""
Identity config. Real phone numbers live in config/identities.json at the repo
root (private repo), with environment variables of the same name taking
precedence. See config/README.md.
"""
import json
import os

from paths import ROOT

_FILE = os.path.join(ROOT, "config", "identities.json")
try:
    with open(_FILE, encoding="utf-8") as _f:
        _DATA = json.load(_f)
except (OSError, ValueError):
    _DATA = {}


def _get(name):
    v = os.environ.get(name)
    if v is None or str(v).strip() == "":
        v = _DATA.get(name, "")
    return str(v).strip() if not isinstance(v, (list, tuple)) else v


def _jid(name):
    n = _get(name)
    return f"{n}@s.whatsapp.net" if n else None


KING_NUMBER = _get("KING_NUMBER")
KING_JID = _jid("KING_NUMBER")
ADMIN_SENDER = _jid("ADMIN_NUMBER")      # None if unset -> never matches a sender
YUKI_ID = _jid("YUKI_NUMBER")            # None if unset -> never matches a sender
YUKI_NUMBER = _get("YUKI_NUMBER")        # digits only, "" if unset
IVY_NUMBER = _get("IVY_NUMBER")          # digits only, "" if unset (Ariel's sister Ivy / Nessa)

_egg = os.environ.get("LEGACY_EGG_IDS")
if _egg:
    _egg = [x.strip() for x in _egg.split(",")]
else:
    _egg = _DATA.get("LEGACY_EGG_IDS", [])
LEGACY_EGG_IDS = frozenset(x for x in _egg if x)
