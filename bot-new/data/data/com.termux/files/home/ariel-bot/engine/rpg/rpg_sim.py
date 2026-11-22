# ============================================================
# ARIEL — RPG_SIM.PY
# Thin wrapper around rpg_battle.py for `.rpg sim` — a standalone
# sandbox for testing combat/weapon-table changes without touching
# a real fight. All actual combat math, hit resolution, narration,
# and state shape live in rpg_battle.py; this file does NOT
# duplicate any of that logic.
#
# What's genuinely sim-specific and lives here:
#   - Its own persistence key (SIM_META_KEY), separate from
#     rpg_battle.py's BATTLE_META_KEY and rpg_session.RpgSession's
#     META_KEY, so an active sim never collides with a real fight
#     or the overworld RPG state.
#   - Nothing else — WEAPON_TABLES, RANDOM_MONSTER_POOL, and every
#     build_*/run_turn/render_* function are used directly from
#     rpg_battle.py (re-exported below for router/rpg.py's existing
#     `rpg_sim.WEAPON_TABLES` / `rpg_sim.run_turn(...)` call sites).
#
# Deliberately NOT routed through rpg_engine.handle_rpg_action() —
# no premise validation, no world_state, no persisted history. This
# is a pure numeric duel: player's soulbound sheet vs. one Open5e
# creature, same engine a real fight uses, just saved under its own
# throwaway key.
# ============================================================

import json

import rpg_battle
from rpg_battle import (
    WEAPON_TABLES,
    RANDOM_MONSTER_POOL,
    MAX_TURNS,
    build_player_combatant,
    build_monster_combatant,
    run_turn,
    render_turn,
    render_start,
    _with_choices,
)

SIM_META_KEY = "rpg_sim_state"


def start_sim(session_soulbound: dict, player_level: int, monster_name: str | None,
              monster_level: int | None, weapon_key: str | None = None) -> dict | str:
    """
    Builds a fresh sim state dict via rpg_battle.start_battle() — see
    that function for the real build logic. Kept as its own name
    here since router/rpg.py calls `rpg_sim.start_sim(...)`.
    """
    return rpg_battle.start_battle(session_soulbound, player_level, monster_name,
                                    monster_level, weapon_key)


def load_sim(db, sender) -> dict | None:
    raw = db.get_meta(sender, SIM_META_KEY)
    if not raw:
        return None
    return json.loads(raw)


def save_sim(db, sender, state: dict):
    db.set_meta(sender, SIM_META_KEY, json.dumps(state))


def delete_sim(db, sender):
    db.delete_meta(sender, SIM_META_KEY)
