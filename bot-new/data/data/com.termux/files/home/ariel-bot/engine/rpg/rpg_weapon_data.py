"""RPG: rpg weapon data (split from rpg_battle.py)."""


BATTLE_META_KEY = "rpg_battle_state"

# ── Sword moveset (Phase 0 — sword only, per current scope) ────
#
# Four skills, deliberately shaped to stress-test differentiation:
# SLASH / THRUST / RIPOSTE sit in a near-identical damage/accuracy
# band on purpose (the actual test is "can the bot tell these three
# apart from flavor text alone, not just detect *a* sword hit").
# SUNDERING_BLOW is the clear outlier — the "ultimate" — so there's
# also a control case that should never be confused with the other
# three. No status effects (bleed, etc.) in this pass — pure damage
# only, per direction.
SWORD_SKILLS = [
    {
        "key": "slash",
        "name": "Sword Slash",
        "description": "A plain, direct cut with the edge of the blade.",
        "example": "I slash at the goblin",
        "damage": 20,
        "scaling": "STR",
        "accuracy": 95,
        "element": "normal",
    },
    {
        "key": "thrust",
        "name": "Precise Thrust",
        "description": "A controlled stab aimed through a gap in the target's guard.",
        "example": "I aim for a gap in its guard and thrust",
        "damage": 25,
        "scaling": "STR",
        "accuracy": 90,
        "element": "normal",
    },
    {
        "key": "riposte",
        "name": "Riposte",
        "description": "A reactive counter-strike, timed off the opponent's own swing.",
        "example": "I wait for its swing and counter",
        "damage": 25,
        "scaling": "STR",
        "accuracy": 88,
        "element": "normal",
    },
    {
        "key": "sunder",
        "name": "Sundering Blow",
        "description": "A two-handed overhead swing with everything behind it — slow, "
                        "telegraphed, and brutal if it lands.",
        "example": "I raise my sword with both hands and bring it down with everything I have",
        "damage": 40,
        "scaling": "STR",
        "accuracy": 65,
        "element": "normal",
    },
]

SWORD_SKILLS_BY_KEY = {s["key"]: s for s in SWORD_SKILLS}

# ── Additional weapon skill tables ──────────────────────────────
#
# Each weapon is its own skill table, same schema as SWORD_SKILLS
# (key/name/description/example/damage/scaling/accuracy/element),
# picked via WEAPON_TABLES below instead of hardcoding SWORD_SKILLS
# onto every player combatant. Every weapon gets a DISTINCT mechanic,
# not just different numbers on the same shape — reasoning per
# weapon is in its own comment.

# Dagger: lower base damage/higher accuracy than sword (precision
# over power), and a real mechanical edge specific to daggers —
# higher BLEED APPLICATION CHANCE via "bleed_multiplier" (read by
# build_player_combatant to set soulbound-level bleed multiplier —
# see APPLICATION LAYER note below). Thematically correct: a
# dagger's whole design is precision cuts to vital/vascular spots,
# not raw power, so it should be meaningfully likelier to open a
# bleeding wound than the same damage number from a blunter weapon.
DAGGER_SKILLS = [
    {
        "key": "quick_cut",
        "name": "Quick Cut",
        "description": "A fast, shallow slash meant to open a wound rather than overpower.",
        "example": "I flick the dagger across its arm",
        "damage": 14,
        "scaling": "DEX",
        "accuracy": 97,
        "element": "normal",
    },
    {
        "key": "gut_stab",
        "name": "Gut Stab",
        "description": "A close, driving stab aimed at soft tissue.",
        "example": "I drive the dagger into its side",
        "damage": 18,
        "scaling": "DEX",
        "accuracy": 92,
        "element": "normal",
    },
    {
        "key": "backstep_slice",
        "name": "Backstep Slice",
        "description": "A retreating slash thrown as the wielder creates distance.",
        "example": "I step back and slice as I go",
        "damage": 16,
        "scaling": "DEX",
        "accuracy": 94,
        "element": "normal",
    },
    {
        "key": "flurry",
        "name": "Flurry",
        "description": "A rapid, committed multi-cut with everything behind precision, "
                        "not power — high risk if it's read and countered.",
        "example": "I go in with a fast flurry of cuts",
        "damage": 26,
        "scaling": "DEX",
        "accuracy": 75,
        "element": "normal",
    },
]

DAGGER_SKILLS_BY_KEY = {s["key"]: s for s in DAGGER_SKILLS}

DAGGER_BLEED_MULTIPLIER = 1.6  # applied via per-weapon status multiplier, see soulbound.py

# Spear: REACH property — a spear keeps the wielder at a distance
# advantage. Mechanically: gets priority in _decide_order against an
# opponent that hasn't yet closed distance (see _decide_order call
# sites — reach is passed through and read there), representing a
# longer weapon getting the first strike as a target enters range.
# This is the first weapon whose distinct mechanic touches TURN
# ORDER rather than damage/accuracy/status.
SPEAR_SKILLS = [
    {
        "key": "jab",
        "name": "Spear Jab",
        "description": "A quick, controlled thrust at range.",
        "example": "I jab at it with the spear",
        "damage": 18,
        "scaling": "STR",
        "accuracy": 93,
        "element": "normal",
        "reach": True,
    },
    {
        "key": "sweep",
        "name": "Haft Sweep",
        "description": "A low sweep with the shaft aimed at the legs to knock the target's footing.",
        "example": "I sweep low at its legs with the shaft",
        "damage": 15,
        "scaling": "STR",
        "accuracy": 88,
        "element": "normal",
        "reach": True,
    },
    {
        "key": "lunge",
        "name": "Lunging Thrust",
        "description": "A committed forward lunge, extending full reach into the strike.",
        "example": "I lunge forward with the spear extended",
        "damage": 27,
        "scaling": "STR",
        "accuracy": 85,
        "element": "normal",
        "reach": True,
    },
    {
        "key": "brace",
        "name": "Braced Point",
        "description": "The spear planted and braced, point forward, punishing anything "
                        "that closes the distance carelessly.",
        "example": "I brace the spear and hold my ground",
        "damage": 22,
        "scaling": "STR",
        "accuracy": 90,
        "element": "normal",
        "reach": True,
    },
]

SPEAR_SKILLS_BY_KEY = {s["key"]: s for s in SPEAR_SKILLS}

# Mace: blunt trauma — explicitly NOT bleed-eligible (see
# eligible_statuses_for_hit's damage_class check: "blunt" is its own
# damage_class, distinct from "Physical", so it's excluded from the
# Physical->bleed fallback on purpose). Instead carries a genuinely
# different mechanic: STAGGER — a one-hit accuracy debuff on the
# TARGET's next action (concussive trauma throwing off their own
# aim/balance), same shape/mechanism as blinded_stack (a ModifierStack
# DEX percent reduction), not a damage-tick status like bleed/poison,
# since "got staggered" isn't a wound that keeps hurting, it's a
# one-time disruption. See stagger_stack() / state["player_staggered"]
# /state["monster_staggered"].
MACE_SKILLS = [
    {
        "key": "bash",
        "name": "Mace Bash",
        "description": "A direct swing meant to crush and jar, not cut.",
        "example": "I bash it with the mace",
        "damage": 22,
        "scaling": "STR",
        "accuracy": 88,
        "element": "normal",
        "damage_class": "blunt",
        "stagger_chance": 0.35,
    },
    {
        "key": "crush",
        "name": "Crushing Blow",
        "description": "A heavy overhead swing bringing the full weight of the head down.",
        "example": "I swing the mace down with full force",
        "damage": 32,
        "scaling": "STR",
        "accuracy": 78,
        "element": "normal",
        "damage_class": "blunt",
        "stagger_chance": 0.55,
    },
    {
        "key": "guard_break",
        "name": "Guard Breaker",
        "description": "A heavy strike aimed squarely at whatever the target is using to block.",
        "example": "I hammer at its guard to break it open",
        "damage": 19,
        "scaling": "STR",
        "accuracy": 85,
        "element": "normal",
        "damage_class": "blunt",
        "stagger_chance": 0.45,
    },
    {
        "key": "haft_check",
        "name": "Haft Check",
        "description": "A short, controlled jab with the haft to create an opening.",
        "example": "I check it with a short jab of the haft",
        "damage": 12,
        "scaling": "STR",
        "accuracy": 95,
        "element": "normal",
        "damage_class": "blunt",
        "stagger_chance": 0.2,
    },
]

MACE_SKILLS_BY_KEY = {s["key"]: s for s in MACE_SKILLS}

# Bow: RANGED property — the mirror opposite of spear's reach. A bow
# user is at a disadvantage once an opponent closes to melee (no
# equivalent of riposte/thrust up close), represented the same way
# reach is: read at the _decide_order call site. Also naturally
# excluded from "reactive counter" style skills (no bow equivalent
# of Riposte) since you can't nock-and-loose reactively the way a
# blade parry-riposte works.
BOW_SKILLS = [
    {
        "key": "loose",
        "name": "Loose Arrow",
        "description": "A standard aimed shot.",
        "example": "I loose an arrow at it",
        "damage": 20,
        "scaling": "DEX",
        "accuracy": 90,
        "element": "normal",
        "ranged": True,
    },
    {
        "key": "called_shot",
        "name": "Called Shot",
        "description": "A slower, carefully aimed shot at a specific vulnerable point.",
        "example": "I take my time and aim for a called shot",
        "damage": 30,
        "scaling": "DEX",
        "accuracy": 70,
        "element": "normal",
        "ranged": True,
    },
    {
        "key": "retreat_shot",
        "name": "Retreating Shot",
        "description": "A shot loosed while backing away to keep range open.",
        "example": "I back away and fire as I go",
        "damage": 16,
        "scaling": "DEX",
        "accuracy": 88,
        "element": "normal",
        "ranged": True,
    },
    {
        "key": "volley",
        "name": "Rapid Volley",
        "description": "Several arrows loosed in quick succession, less precise per shot.",
        "example": "I fire off a quick volley",
        "damage": 24,
        "scaling": "DEX",
        "accuracy": 72,
        "element": "normal",
        "ranged": True,
    },
]

BOW_SKILLS_BY_KEY = {s["key"]: s for s in BOW_SKILLS}

# Shield: blunt/STR like mace, but built around the shield's edge/face/
# rim and body weight rather than a swung head — bashes, shoves, and
# guard-breaks are legitimate ATTACKS with a shield (not just a block),
# same principle as every other weapon here: the moveset is what you can
# hit someone WITH, not a defense-only item.
SHIELD_SKILLS = [
    {
        "key": "bash",
        "name": "Shield Bash",
        "description": "A direct slam with the shield's face, meant to stun and knock back.",
        "example": "I bash it with my shield",
        "damage": 18,
        "scaling": "STR",
        "accuracy": 90,
        "element": "normal",
        "damage_class": "blunt",
        "stagger_chance": 0.4,
    },
    {
        "key": "rim_strike",
        "name": "Rim Strike",
        "description": "A sharp jab with the shield's edge at an exposed vital point.",
        "example": "I jab the rim of my shield into it",
        "damage": 24,
        "scaling": "STR",
        "accuracy": 80,
        "element": "normal",
        "damage_class": "blunt",
        "stagger_chance": 0.3,
    },
    {
        "key": "shoulder_charge",
        "name": "Shoulder Charge",
        "description": "A full-body charge behind the raised shield, trading precision for weight.",
        "example": "I charge in behind my shield",
        "damage": 28,
        "scaling": "STR",
        "accuracy": 75,
        "element": "normal",
        "damage_class": "blunt",
        "stagger_chance": 0.5,
    },
    {
        "key": "guard_break",
        "name": "Guard Breaker",
        "description": "A heavy shove aimed at knocking a raised guard aside.",
        "example": "I slam my shield into its guard to break it open",
        "damage": 14,
        "scaling": "STR",
        "accuracy": 92,
        "element": "normal",
        "damage_class": "blunt",
        "stagger_chance": 0.35,
    },
]

SHIELD_SKILLS_BY_KEY = {s["key"]: s for s in SHIELD_SKILLS}

# Registry — single source of truth for "what weapons exist", used
# by build_player_combatant (weapon selection, including random pick
# for bare `.rpg sim`) and by the router/help text later. Adding a
# new weapon means adding one table above + one entry here, nothing
# else hardcodes the weapon list.
WEAPON_TABLES = {
    "sword": SWORD_SKILLS,
    "dagger": DAGGER_SKILLS,
    "spear": SPEAR_SKILLS,
    "mace": MACE_SKILLS,
    "bow": BOW_SKILLS,
    "shield": SHIELD_SKILLS,
}

# Every skill in every player weapon table above IS a weapon-item
# attack by construction — but their flavor names ("Riposte", "Quick
# Cut", "Flurry") don't reliably contain a literal weapon-type
# keyword the way item names like "chest armor" or "shortbow" do, so
# soulbound.py's keyword-based _skill_role() would misclassify most
# of them as 'unknown' (verified: only 4/20 matched by keyword before
# this fix). Tagging structurally here — by TABLE membership, which
# is always correct — instead of guessing from the name, is the
# actual fix; every entry gets a real, reliable "is_weapon_item" flag
# that build_loadout can trust regardless of skill naming.
for _table in WEAPON_TABLES.values():
    for _skill in _table:
        _skill["is_weapon_item"] = True

del _table, _skill

# Generic entry for freeform techniques that AREN'T one of the 4 named
# skills — a leg sweep, a knee strike, a feint into a follow-up swing,
# a grapple, anything improvised. These are real, legitimate combat
# actions that shouldn't be forced to pretend to be "Sword Slash" just
# because that's the closest named skill. Damage/accuracy sit at a
# plain, unmodified baseline (same ballpark as Slash) — the actual
# "did this land clean, glance, get blocked, or rebound" judgment is
# left to the narrator's prose, not simulated here as a separate
# mechanic, since that's genuinely a narrative call, not a numeric one.
_FREEFORM_TECHNIQUE = {
    "key": "freeform",
    "name": "Improvised Technique",
    "description": "A physical technique outside the 4 named skills — "
                    "a sweep, strike, grapple, feint, or other move.",
    "damage": 20,
    "scaling": "STR",
    "accuracy": 90,
    "element": "normal",
}

# Small curated pool for `.rpg sim` with no monster named — avoids
# depending on Open5e having a "random" endpoint (it doesn't) and
# avoids paging through results just to throw most of them away.
# Early/low-CR names, appropriate for a player just testing sword
# skills, not a real encounter table.
#
# NOTE: these 10 names go through the normal fetch_isekai_monster ->
# isekai_to_soulbound -> stats_at_level pipeline below, same as any
# other named monster — real Open5e ability scores, real HP, real
# skill damage (via isekai_action_to_skill's average-roll fix). An
# earlier hand-set stat table for just these 10 names was tried and
# then reverted per direction ("let's now use the actual stats
# instead of hard coding") — kept here as a note in case the real
# stats turn out too swingy again and a curated table is wanted back.
RANDOM_MONSTER_POOL = [
    "Goblin", "Wolf", "Skeleton", "Giant Rat", "Zombie",
    "Kobold", "Giant Spider", "Orc", "Bandit", "Stirge",
]

MAX_TURNS = 30  # stalemate guard — see run_turn()'s cap check
