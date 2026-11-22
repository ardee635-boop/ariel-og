"""
NIFLHEIM — migrate_townia_trail.py
One-time migration: brings an EXISTING database up to the current Townia
seed (the townia.md spec: wall + towers, new shops, lake / waterfall /
ruin / dungeon areas). rpg_places_seed only runs on a fresh seed or
.resetworld, so without this the new places don't exist for live players.

What it does:
  1. Upserts every seeded place that is MISSING from the DB, or whose
     tier/parent differs from the seed (e.g. Lodging: landmark -> location).
     Places that already match are left alone — no description overwrites.
  2. Adds every seeded passage pair that is missing (both directions).
  3. Removes the stale rows from the earlier south-trail draft
     (townia_ruins, townia_undercroft, undercroft_entrance and the
     south_district_road <-> townia_lakeshore passage), if present.

Idempotent: safe to run twice.

USAGE (from the repo root):
    python3 scripts/migrate_townia_trail.py            # dry run — reports only
    python3 scripts/migrate_townia_trail.py --apply    # actually writes
"""

import os
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
ENGINE = os.path.join(ROOT, "engine")
for d in [ENGINE] + [os.path.join(ENGINE, x) for x in os.listdir(ENGINE)
                     if os.path.isdir(os.path.join(ENGINE, x))]:
    sys.path.insert(0, d)

from database import Database
import rpg_places_seed

STALE_PLACE_IDS = ("townia_ruins", "townia_undercroft", "undercroft_entrance")
STALE_PAIRS = (("south_district_road", "townia_lakeshore"),)


def _has_passage(db, a, b):
    return any(p["to_id"] == b for p in db.get_passages_from(a))


def main():
    apply = "--apply" in sys.argv
    db = Database()
    places, _ = rpg_places_seed.build_world_tree()

    n_new = n_changed = 0
    for p in places:
        row = db.get_place(p.id)
        if row is None:
            print(f"place   NEW      {p.id}")
            n_new += 1
        elif (row["tier"], row["parent_id"]) != (p.tier, p.parent_id):
            print(f"place   CHANGED  {p.id}  ({row['tier']}/{row['parent_id']} -> {p.tier}/{p.parent_id})")
            n_changed += 1
        else:
            continue
        if apply:
            db.upsert_place(p.to_dict())

    n_pass = 0
    for a, b in rpg_places_seed._passage_pairs():
        for x, y in ((a, b), (b, a)):
            if not _has_passage(db, x, y):
                print(f"passage ADD      {x} -> {y}")
                n_pass += 1
                if apply:
                    db.add_passage(x, y, state="established", invented=False)

    n_stale = 0
    for pid in STALE_PLACE_IDS:
        if db.get_place(pid):
            print(f"stale   REMOVE   place {pid} (+ its passages)")
            n_stale += 1
            if apply:
                db._ex("DELETE FROM rpg_passages WHERE from_id = ? OR to_id = ?", (pid, pid))
                db._ex("DELETE FROM rpg_places WHERE id = ?", (pid,))
                db._commit()
    for a, b in STALE_PAIRS:
        for x, y in ((a, b), (b, a)):
            if _has_passage(db, x, y):
                print(f"stale   REMOVE   passage {x} -> {y}")
                n_stale += 1
                if apply:
                    db._ex("DELETE FROM rpg_passages WHERE from_id = ? AND to_id = ?", (x, y))
                    db._commit()

    print(f"\n{n_new} new, {n_changed} changed places; {n_pass} passage rows to add; {n_stale} stale rows to remove.")
    print("Applied." if apply else "Dry run — nothing written. Re-run with --apply.")


if __name__ == "__main__":
    main()
