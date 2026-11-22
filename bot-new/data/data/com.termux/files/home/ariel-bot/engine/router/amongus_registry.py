# ============================================================
# NIFLHEIM — router/amongus_registry.py
# Owner-managed registry of WhatsApp groups used by Among Us:
# lobby groups (where matches are hosted) and ghost groups (where
# Ghosts chat). Persisted to a JSON file; survives restarts and
# match ends. Only `unset` removes an entry.
# ============================================================

import json
import os
import threading
from pathlib import Path

ROLES = ("lobby", "ghost")


def default_path():
    env = os.environ.get("AMONGUS_REGISTRY_FILE")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[2] / "amongus_group_registry.json"


class GroupRegistry:
    def __init__(self, path=None):
        self.path = Path(path) if path else default_path()
        self._lock = threading.RLock()
        self._data = {role: [] for role in ROLES}
        self._load()

    def _load(self):
        try:
            raw = json.loads(self.path.read_text("utf-8"))
        except (OSError, ValueError):
            return
        for role in ROLES:
            items = raw.get(role) if isinstance(raw, dict) else None
            if isinstance(items, list):
                seen = []
                for jid in items:
                    if isinstance(jid, str) and jid not in seen:
                        seen.append(jid)
                self._data[role] = seen

    def _save(self):
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(self._data), "utf-8")
        os.replace(tmp, self.path)

    def list(self, role):
        """Registered groups of a role, in registration order."""
        with self._lock:
            return list(self._data[role])

    def role_of(self, jid):
        with self._lock:
            for role in ROLES:
                if jid in self._data[role]:
                    return role
        return None

    def add(self, role, jid):
        """Returns None on success, or 'duplicate' / 'other_role' / 'save_failed'."""
        with self._lock:
            held = self.role_of(jid)
            if held == role:
                return "duplicate"
            if held:
                return "other_role"
            self._data[role].append(jid)
            try:
                self._save()
            except OSError:
                self._data[role].remove(jid)
                return "save_failed"
            return None

    def remove(self, role, jid):
        """Returns None on success, or 'missing' / 'save_failed'."""
        with self._lock:
            if jid not in self._data[role]:
                return "missing"
            index = self._data[role].index(jid)
            self._data[role].remove(jid)
            try:
                self._save()
            except OSError:
                self._data[role].insert(index, jid)
                return "save_failed"
            return None
