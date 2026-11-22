# ============================================================
# ARIEL — RPG_BATTLE.PY
# The real combat engine — this is what the live `.rpg` flow calls
# into for actual fights (monsters encountered while exploring,
# dungeon encounters, trial fights, etc). Player's soulbound sheet
# vs. an opponent, converted via soulbound.isekai_to_soulbound()
# where needed, looped with battle.calc_damage() until someone hits
# 0 HP, a turn cap is hit, or the fight is otherwise ended.
#
# This module WAS rpg_sim.py's engine core (copied over as-is —
# see git history / rpg_sim.py's own header for the original
# design notes on hit resolution, narration, and state shape).
# rpg_sim.py now only wraps THIS module for ".rpg sim"'s
# throwaway test-bed sessions (random monster pool, its own
# separate persistence key) — it does not duplicate any of the
# engine logic below. Anything that changes real combat behavior
# belongs here, not in rpg_sim.py.
#
# State lives in db.player_meta under its own key (BATTLE_META_KEY)
# — separate from rpg_session.RpgSession's META_KEY and from
# rpg_sim.py's SIM_META_KEY, so a real fight, a sim session, and
# the overworld RPG state never collide or overwrite each other.
# ============================================================
# NOTE: this module is now a thin front door. The code lives in:
#   rpg_weapon_data.py     weapon skill tables, random monster pool
#   rpg_encounter_gen.py   combatant builders, encounter generation, battle start
#   rpg_action_parse.py    action classification / splitting, LLM prompt templates
#   rpg_turn_order.py      turn order, interrupts, debuff stacks
#   rpg_turn.py            hit resolution, narration, run_turn, render
#   rpg_battle_store.py    load/save/delete battle, interrupted-fight summary
# router/rpg.py and rpg_sim.py keep using `rpg_battle.<name>`, so everything is re-exported here.

import rpg_weapon_data, rpg_encounter_gen, rpg_action_parse, rpg_turn_order, rpg_turn, rpg_battle_store

for _m in (rpg_weapon_data, rpg_encounter_gen, rpg_action_parse, rpg_turn_order, rpg_turn, rpg_battle_store):
    globals().update({_k: _v for _k, _v in vars(_m).items() if not _k.startswith("__")})
del _m
