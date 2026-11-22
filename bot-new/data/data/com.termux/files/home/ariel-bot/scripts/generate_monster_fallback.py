"""
One-off script: populate monster_fallback_cache.json with all 10
RANDOM_MONSTER_POOL monsters, fetched live from Open5e.

Run this once locally (or via a Render shell) whenever the pool
changes or the fallback needs refreshing:

    python3 generate_monster_fallback.py

Commit the resulting monster_fallback_cache.json alongside
soulbound.py so it deploys with the bot.
"""
import json
import time

from rpg_sim import RANDOM_MONSTER_POOL
from soulbound import fetch_isekai_monster, _FALLBACK_PATH

OUT_PATH = "monster_fallback_cache.json"


def main():
    cache = {}
    for name in RANDOM_MONSTER_POOL:
        key = name.strip().lower()
        print(f"Fetching {name!r}...")
        raw = fetch_isekai_monster(name)
        if raw:
            cache[key] = raw
            print(f"  ok ({raw.get('name', '?')})")
        else:
            print(f"  FAILED — {name!r} not saved, retry later")
        time.sleep(1)  # be polite to Open5e

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2)

    print(f"\nWrote {len(cache)}/{len(RANDOM_MONSTER_POOL)} monsters to {OUT_PATH}")
    if len(cache) < len(RANDOM_MONSTER_POOL):
        print("Some monsters failed — re-run later to fill in the gaps "
              "(existing entries won't be re-fetched, this overwrites the "
              "whole file each run, so keep re-running until all 10 are in).")


if __name__ == "__main__":
    main()
