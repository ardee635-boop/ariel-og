# Niflheim config loader. Every DEFAULT value lives in data/config.json — never hard-code them.
import json
import os

_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
_cache = None


def load_config(reload=False):
    """Return the config dict (empty if the file is missing or invalid)."""
    global _cache
    if _cache is None or reload:
        try:
            with open(os.path.join(_DATA_DIR, "config.json"), "r", encoding="utf-8") as f:
                _cache = json.load(f)
        except Exception:
            _cache = {}
    return _cache


def get(key, default=None):
    return load_config().get(key, default)
