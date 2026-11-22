"""Among Us mini-preview images: direct links, read from assets/amongus/image_links.json.

The owner pastes direct image URLs (https) into that file. Nothing is invented:
a missing, blank or malformed link means the message is sent as plain text,
exactly as before. Lookup order for a player colour: that colour's link, then
the kind's "default" link, then nothing.

Kinds: ``meeting_call`` (shown with the meeting call, keyed by the caller's
colour) and ``ejection`` (shown with the role reveal, keyed by the ejected
player's colour).
"""

import json
import os
import re
from pathlib import Path

KINDS = ("meeting_call", "ejection")
DEFAULT_FILE = Path(__file__).resolve().parents[2] / "assets" / "amongus" / "image_links.json"
_URL_RE = re.compile(r"^https?://\S+$", re.IGNORECASE)

_cache = {"path": None, "mtime": None, "data": {}}


def links_path():
    return Path(os.environ.get("AMONGUS_IMAGE_LINKS") or DEFAULT_FILE)


def _load():
    path = links_path()
    try:
        mtime = path.stat().st_mtime
    except OSError:
        _cache.update(path=str(path), mtime=None, data={})
        return _cache["data"]
    if _cache["path"] == str(path) and _cache["mtime"] == mtime:
        return _cache["data"]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            data = {}
    except (OSError, ValueError):
        data = {}
    _cache.update(path=str(path), mtime=mtime, data=data)
    return data


def _valid(value):
    return value.strip() if isinstance(value, str) and _URL_RE.match(value.strip()) else None


def image_link(kind, color=None):
    """Direct image URL for ``kind`` and a player colour, or None."""
    section = _load().get(kind)
    if not isinstance(section, dict):
        return None
    if color:
        found = _valid(section.get(str(color).lower()))
        if found:
            return found
    return _valid(section.get("default"))


def map_link(map_id):
    """Direct image URL of a whole-map picture (``maps`` section), or None."""
    section = _load().get("maps")
    if not isinstance(section, dict):
        return None
    return _valid(section.get(str(map_id).lower()))


def slot_link(name):
    """Direct image URL of a single-picture slot (``lobby``, ``tasks_list``), or None."""
    return _valid(_load().get(name))


def lobby_link():
    """Lobby artwork sent with ``.lobby open`` (blank = text only)."""
    return slot_link("lobby")


def tasks_list_link():
    """TASKS LIST picture sent with a living player's ``.tasks`` (blank = text only)."""
    return slot_link("tasks_list")


def image_kwargs(kind, color=None):
    """``{"image_url": url}`` when a link exists, else ``{}`` (callers splat it)."""
    url = image_link(kind, color)
    return {"image_url": url} if url else {}
