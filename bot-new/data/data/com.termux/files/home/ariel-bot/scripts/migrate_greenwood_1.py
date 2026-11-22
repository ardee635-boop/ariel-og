"""
NIFLHEIM — migrate_greenwood_1.py
One-time migration: fixes greenwood_1 for every existing player whose
save data predates the story-quest fix (source/reward/tips were never
set, so it was silently miscategorized as a board quest with no reward).

Run this ONCE, after deploying the code fix (router/quests.py, gym.py,
etc.), and before or after players keep playing — it's safe either way
since it only touches players who already have a stale greenwood_1.

WHAT IT DOES, per player:
  1. If greenwood_1 is in player.quests (still active/unclaimed):
     patch it in place — source, reward, tips, rank — to match the
     current QUEST_DEFINITIONS. Progress/status untouched.
  2. If greenwood_1 is in player.completed_quests (they already beat
     the gym before the reward existed):
     move it back to player.quests as a fresh, active copy — so
     re-clearing Greenwood gym triggers gym.py's reward path and they
     actually receive the items this time. player.badges is NOT
     touched — the Leaf Badge (if they have one) stays theirs; they
     just need to re-clear the gym encounter to collect the quest
     reward that didn't exist yet when they first cleared it.
  3. If they don't have greenwood_1 at all (never reached Route 1 /
     never registered on the site): skipped entirely, nothing to do.

USAGE:
    cd whatsapp-bot
    python3 migrate_greenwood_1.py            # dry run — reports only
    python3 migrate_greenwood_1.py --apply    # actually writes changes

Dry run is the default on purpose — read the report first.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import Database
from router.quests import make_quest


def migrate(apply: bool):
    db = Database()
    rows = db.all_players_data()  # [(sender, raw_dict), ...]

    fixed_active    = []
    reset_completed = []
    skipped         = 0

    for sender, raw in rows:
        from models import Player
        try:
            player = Player.from_dict(raw)
        except Exception as e:
            print(f"[SKIP] {sender}: couldn't load — {e}")
            continue

        # Case 1: still active/unclaimed
        active_gq = next((q for q in player.quests if q.id == "greenwood_1"), None)
        if active_gq:
            fresh = make_quest("greenwood_1")
            active_gq.source = fresh.source
            active_gq.reward = fresh.reward
            active_gq.tips   = fresh.tips
            active_gq.rank   = fresh.rank
            # description/title left as-is if the player already saw the
            # old wording — cosmetic, not worth overwriting silently.
            active_gq.title       = fresh.title
            active_gq.description = fresh.description
            fixed_active.append(sender)
            if apply:
                db.save(sender, player)
            continue

        # Case 2: already completed — reset to active so re-clearing the
        # gym grants the (now real) reward. Badge is left untouched.
        completed_gq = next((q for q in player.completed_quests if q.id == "greenwood_1"), None)
        if completed_gq:
            player.completed_quests.remove(completed_gq)
            fresh = make_quest("greenwood_1")
            player.quests.append(fresh)
            reset_completed.append(sender)
            if apply:
                db.save(sender, player)
            continue

        # Case 3: no greenwood_1 at all — nothing to migrate
        skipped += 1

    print()
    print("=" * 60)
    print(f"{'APPLIED' if apply else 'DRY RUN — no changes written'}")
    print("=" * 60)
    print(f"Active quest patched (source/reward/tips fixed): {len(fixed_active)}")
    for s in fixed_active:
        print(f"    - {s}")
    print(f"Completed quest reset to active (re-clear to collect): {len(reset_completed)}")
    for s in reset_completed:
        print(f"    - {s}")
    print(f"Skipped (no greenwood_1 on record): {skipped}")
    print()
    if not apply:
        print("This was a dry run. Re-run with --apply to write these changes.")


if __name__ == "__main__":
    migrate(apply="--apply" in sys.argv)
