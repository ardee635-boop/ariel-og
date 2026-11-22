"""Import first in a test: points AMONGUS_IMAGE_LINKS at a copy of the shipped links
with the single-picture slots (lobby, tasks_list) blank, so text-reply tests stay
text-only no matter which artwork is configured. Skipped if the variable is already set."""
import json
import os
import tempfile
from pathlib import Path

if "AMONGUS_IMAGE_LINKS" not in os.environ:
    _src = Path(__file__).resolve().parents[1] / "assets/amongus/image_links.json"
    _data = json.loads(_src.read_text(encoding="utf-8"))
    _data["lobby"] = ""
    _data["tasks_list"] = ""
    _dir = tempfile.mkdtemp(prefix="amongus_links_")
    _path = Path(_dir) / "image_links.json"
    _path.write_text(json.dumps(_data), encoding="utf-8")
    os.environ["AMONGUS_IMAGE_LINKS"] = str(_path)

os.environ.setdefault("AMONGUS_FIXED_MAP", "skeld")  # lobby maps are random; these tests assume Skeld
