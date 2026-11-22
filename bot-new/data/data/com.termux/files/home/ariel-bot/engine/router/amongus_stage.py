"""Among Us stage previews: a colour character composited onto a stage background.

* ``square``    stage -> the MINI preview (meeting call, ejection reveal, `.status`)
* ``landscape`` stage -> the FULL preview (role card at match start)

The character is placed on the LEFT of the stage (design note: "the small
cube/character is positioned on the left"). All pictures are direct links kept in
``assets/amongus/image_links.json``:

    "stage":      {"square": {"default": url, "crewmate": "", "impostor": ""},
                   "landscape": {...same...}}
    "characters": {"red": url, "blue": url, ...}

NETWORK RULE: nothing here may block the game. ``warm()`` downloads in a background
thread; ``compose()`` only uses what is already on disk and returns a local file
path (or None, in which case the caller falls back to the plain colour image or to
text). A character that is not a transparent cut-out is never composited.
"""

import hashlib
import os
import threading
import urllib.request
from pathlib import Path

from . import amongus_images as IMG

SIZES = ("square", "landscape")
MAX_DOWNLOAD_BYTES = 8 * 1024 * 1024
DOWNLOAD_TIMEOUT_SECONDS = 10
MAX_SIDE_PIXELS = 900          # output is scaled so its longest side is at most this
JPEG_QUALITY = 88

# (character height as a share of the stage height, left margin share of the width,
#  bottom margin share of the height) - one place to tune the look.
LAYOUT = {
    "square":    (0.68, 0.07, 0.08),
    "landscape": (0.74, 0.08, 0.07),
}

_lock = threading.Lock()
_warming = set()


def cache_dir():
    path = Path(os.environ.get("AMONGUS_STAGE_CACHE") or (IMG.DEFAULT_FILE.parent / ".cache"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def _key(*parts):
    return hashlib.sha1("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:20]


def _download(url, dest):
    """Fetch ``url`` to ``dest`` (atomic). Raises on any problem."""
    req = urllib.request.Request(url, headers={"User-Agent": "ariel-bot/1"})
    with urllib.request.urlopen(req, timeout=DOWNLOAD_TIMEOUT_SECONDS) as resp:
        data = resp.read(MAX_DOWNLOAD_BYTES + 1)
    if not data or len(data) > MAX_DOWNLOAD_BYTES:
        raise ValueError("empty or too large")
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(dest)


def _local(url):
    return cache_dir() / f"src_{_key(url)}"


def _fetch(url):
    """Local path of ``url``, downloading it if needed. Used ONLY off the game thread."""
    dest = _local(url)
    if not dest.exists():
        _download(url, dest)
    return dest


SCENES = ("emergency", "report", "ejection")   # optional per-event backgrounds


def stage_url(size, role=None, scene=None):
    section = (IMG._load().get("stage") or {})
    section = section.get(size) if isinstance(section, dict) else None
    if not isinstance(section, dict):
        return None
    if scene:
        found = IMG._valid(section.get(str(scene).lower()))
        if found:
            return found
    return IMG._valid(section.get(str(role or "").lower())) or IMG._valid(section.get("default"))


def character_url(color):
    section = IMG._load().get("characters")
    if not isinstance(section, dict) or not color:
        return None
    return IMG._valid(section.get(str(color).lower()))


def warm(colors, roles=("crewmate", "impostor")):
    """Download every stage and the given colours' characters in the background."""
    urls = []
    for size in SIZES:
        for role in roles:
            u = stage_url(size, role)
            if u and u not in urls:
                urls.append(u)
        for scene in SCENES:
            u = stage_url(size, None, scene)
            if u and u not in urls:
                urls.append(u)
    for color in colors:
        u = character_url(color)
        if u and u not in urls:
            urls.append(u)
    todo = [u for u in urls if not _local(u).exists()]
    if not todo or os.environ.get("AMONGUS_STAGE_OFFLINE"):
        return None

    def run():
        for u in todo:
            with _lock:
                if u in _warming:
                    continue
                _warming.add(u)
            try:
                _fetch(u)
            except Exception:       # offline / bad link: composites simply stay unavailable
                pass
            finally:
                with _lock:
                    _warming.discard(u)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread


def layout_box(size, stage_w, stage_h, char_w, char_h):
    """(x, y, w, h) of the character on the stage: left side, near the bottom."""
    height_share, left_share, bottom_share = LAYOUT[size]
    h = max(1, round(stage_h * height_share))
    w = max(1, round(char_w * h / char_h))
    max_w = round(stage_w * 0.6)        # never swallow more than 60% of the width
    if w > max_w:
        w = max_w
        h = max(1, round(char_h * w / char_w))
    x = round(stage_w * left_share)
    y = stage_h - h - round(stage_h * bottom_share)
    return x, max(0, y), w, h


def compose(size, color, role=None, scene=None):
    """Local file path of the finished picture, or None (never blocks, never raises)."""
    try:
        if size not in SIZES:
            return None
        bg_url, ch_url = stage_url(size, role, scene), character_url(color)
        if not bg_url or not ch_url:
            return None
        bg_path, ch_path = _local(bg_url), _local(ch_url)
        if not bg_path.exists() or not ch_path.exists():
            warm([color])           # not downloaded yet: fetch in the background for next time
            return None
        out = cache_dir() / f"stage_{_key(size, bg_url, ch_url, bg_path.stat().st_size, ch_path.stat().st_size)}.jpg"
        if out.exists():
            return str(out)
        from PIL import Image
        with Image.open(ch_path) as raw:
            character = raw.convert("RGBA")
        alpha = character.getchannel("A").getextrema()
        if alpha[0] >= 250:         # no transparency: not a cut-out, do not paste a box onto the stage
            return None
        bbox = character.getchannel("A").point(lambda v: 255 if v > 8 else 0).getbbox()
        if bbox:
            character = character.crop(bbox)
        with Image.open(bg_path) as raw:
            stage = raw.convert("RGBA")
        scale = min(1.0, MAX_SIDE_PIXELS / max(stage.size))
        if scale < 1.0:
            stage = stage.resize((round(stage.width * scale), round(stage.height * scale)), Image.LANCZOS)
        x, y, w, h = layout_box(size, stage.width, stage.height, character.width, character.height)
        character = character.resize((w, h), Image.LANCZOS)
        stage.alpha_composite(character, (x, y))
        tmp = out.with_suffix(".tmp.jpg")
        stage.convert("RGB").save(tmp, "JPEG", quality=JPEG_QUALITY)
        tmp.replace(out)
        return str(out)
    except Exception:
        return None


def preview_kwargs(size, color, role=None, kind=None, scene=None):
    """``{"image_url": <local file or direct link>}`` or ``{}``.

    Prefers the stage composite; falls back to the plain per-colour link for
    ``kind`` (``meeting_call`` / ``ejection``) when the composite is not ready.
    """
    path = compose(size, color, role, scene)
    if path:
        return {"image_url": path}
    if kind:
        return IMG.image_kwargs(kind, color)
    return {}
