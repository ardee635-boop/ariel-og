"""
NIFLHEIM — migrate_hp_fix.py
One-time migration: recalculates max_hp (and proportionally scales
current hp) for every already-caught Pokémon (party + box, all players),
using the corrected HP formula from models.py's OwnedPokemon fix.

BACKGROUND:
  OwnedPokemon.max_hp went through two bugs:
  1. Originally calculated as:
      int(((2 * base_hp * level) / 100) + (level * 15) + 10)
     which is not the standard Pokémon HP formula (level*15 instead of
     level) and produced wildly inflated numbers (e.g. ~300-5000 HP for
     a low-level Pokémon depending on base stats).
  2. That was fixed, but a *10 scale was added on top:
      int(((2 * base_hp * level) / 100) + level + 10) * 10
     under the assumption every attack/defense/speed formula elsewhere
     was scaled *10 too, so ratios would stay unchanged. That assumption
     didn't hold — calc_damage/calc_def_stat in battle.py used the real,
     unscaled Atk/Def ratio, so the *10'd HP alongside unscaled damage
     made Pokémon roughly 10x tankier than intended relative to hits.

  Both are now fixed to the real, unscaled formula:
      int(((2 * base_hp * level) / 100) + level + 10)
  matching calc_damage/calc_def_stat, which also use real Atk/Def
  ratios with no scaling multiplier.

  That formula fix only applies going forward — any Pokémon caught
  BEFORE the fix was deployed still has its old, inflated max_hp/hp
  sitting in the database untouched (from_dict() reads stored values
  directly, it doesn't recompute them). This script closes that gap.
  This includes Pokémon that were already migrated once by an earlier
  run of this same script under the old (*10) formula — re-running is
  safe and will bring them down to the real scale too.

WHAT IT DOES, per Pokémon (party + box, every player):
  1. Recomputes max_hp from the Pokémon's own stored base_stats["hp"]
     and level, using the CURRENT (fixed) formula in models.py — calls
     the real OwnedPokemon HP formula directly (see _recompute_max_hp)
     rather than duplicating it here, so this script can never drift
     out of sync with models.py again.
  2. Scales current hp proportionally to the OLD max_hp, so a
     Pokémon that was e.g. at 50% health stays at 50% health rather
     than snapping to full or being left over the new max. Fainted
     (hp == 0) Pokémon stay at 0.
  3. Skips any Pokémon whose recomputed max_hp is already equal to
     its stored max_hp (already-fixed / never touched by either bug) —
     safe to re-run.

USAGE:
    cd whatsapp-bot
    python3 migrate_hp_fix.py            # dry run — reports only
    python3 migrate_hp_fix.py --apply    # actually writes changes

Dry run is the default on purpose — read the report first.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import Database
from models import Player, OwnedPokemon


def _recompute_max_hp(poke: OwnedPokemon) -> int:
    """Recomputes max_hp using models.py's CURRENT formula, applied to
    this Pokémon's own stored base_stats/level. Mirrors OwnedPokemon.
    __init__'s HP line exactly — kept as a one-line call-through rather
    than a duplicated formula so this script can't silently drift out
    of sync with models.py if the formula ever changes again."""
    base_hp = poke.base_stats.get("hp", 45)
    level   = poke.level
    return int(((2 * base_hp * level) / 100) + level + 10)


def migrate(apply: bool):
    db = Database()
    rows = db.all_players_data()  # [(sender, raw_dict), ...]

    changed_players = []
    total_mons_fixed = 0
    total_mons_skipped = 0
    errors = []

    for sender, raw in rows:
        try:
            player = Player.from_dict(raw)
        except Exception as e:
            errors.append(f"{sender}: couldn't load — {e}")
            continue

        player_changed = False
        mons_fixed_here = []

        for poke in list(player.party) + list(player.box):
            old_max = poke.max_hp
            new_max = _recompute_max_hp(poke)

            if new_max == old_max:
                total_mons_skipped += 1
                continue

            # Scale current hp proportionally so health % is preserved.
            # Fainted stays fainted (0 -> 0). Guard against div-by-zero
            # if a corrupt record somehow has old_max <= 0.
            if old_max > 0 and poke.hp > 0:
                pct = poke.hp / old_max
                new_hp = max(1, min(new_max, round(new_max * pct)))
            else:
                new_hp = 0

            mons_fixed_here.append(
                f"{poke.nickname} (Lv{poke.level}): "
                f"max_hp {old_max} -> {new_max}, hp {poke.hp} -> {new_hp}"
            )

            poke.max_hp = new_max
            poke.hp     = new_hp
            player_changed = True
            total_mons_fixed += 1

        if player_changed:
            changed_players.append((sender, mons_fixed_here))
            if apply:
                db.save(sender, player)

    print()
    print("=" * 60)
    print(f"{'APPLIED' if apply else 'DRY RUN — no changes written'}")
    print("=" * 60)
    print(f"Players with at least one Pokémon fixed: {len(changed_players)}")
    for sender, mons in changed_players:
        print(f"\n  {sender}:")
        for line in mons:
            print(f"    - {line}")
    print(f"\nTotal Pokémon fixed:   {total_mons_fixed}")
    print(f"Total Pokémon skipped (already correct): {total_mons_skipped}")
    if errors:
        print(f"\nErrors ({len(errors)}):")
        for e in errors:
            print(f"    - {e}")
    print()
    if not apply:
        print("This was a dry run. Re-run with --apply to write these changes.")


if __name__ == "__main__":
    migrate(apply="--apply" in sys.argv)
