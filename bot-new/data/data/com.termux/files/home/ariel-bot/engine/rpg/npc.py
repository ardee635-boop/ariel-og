# npc_key -> {name, title, pronouns, hostile, personality, voice_note}
#
# Hand-authored cards for NAMED, RECURRING, structurally important
# NPCs only — see NPC.md (design doc) for the full rationale. This is
# NOT meant to hold every NPC the narrator ever invents; incidental,
# one-off characters (a nameless bandit, a passerby) stay fully
# narrator-improvised, same as today. A card gets added here only
# when a developer consciously decides this NPC needs to stay
# consistent across turns/players — promotion is never automatic or
# retroactive just because a narrator-invented NPC happened to recur.
#
# Required: name, title, pronouns, hostile.
# Optional: personality, voice_note.
NPC_CARDS = {
    "townia_church_elder": {
        "name": "Danaya",
        "title": "Elder of the Church",
        "pronouns": "she/her",
        "hostile": False,
        "personality": "warm, patient, quietly perceptive",
        "voice_note": "speaks slowly, favors old proverbs",
    },
    # Pet shop shopkeeper — special case, NOT a fixed card. Per the
    # Summoner trial design, her NAME is code-generated and saved per
    # playthrough (different players get different shopkeepers), but
    # everything else about her (title/pronouns/personality/voice)
    # stays fixed here so she reads consistently regardless of which
    # name gets rolled. See generate_shopkeeper_name() /
    # get_shopkeeper_card() below for the per-player name handling —
    # this entry is the shared template, not a usable card on its own
    # (no "name" key — get_npc_card() would return an incomplete card
    # if called directly on this key, so callers should use
    # get_shopkeeper_card(db, sender) instead for this one NPC).
    "townia_pet_shop_keeper": {
        "title": "the pet shop's keeper",
        "pronouns": "she/her",
        "hostile": False,
        "personality": "warm, a little irreverent, genuinely fond of cursed kids rather than wary of them",
        "voice_note": "treats \"cursed child\" like just another kid who wandered in, not a tragedy",
    },
    # Odalys — the gardener tending the greenhouse (see
    # rpg_places_seed.py's townia_garden_shop, moved to South
    # District this session). Already named in the location's own
    # description text; this card just gives her the same standing
    # every other recurring NPC gets, per "no such thing as an
    # unimportant NPC" — nothing about her role changes, only that
    # she's now a real, structured card instead of a name mentioned
    # only in prose.
    "townia_garden_shop_odalys": {
        "name": "Odalys",
        "title": "the gardener",
        "pronouns": "she/her",
        "hostile": False,
        "personality": "quiet, unhurried, glad for company she rarely gets",
        "voice_note": "talks about her plants like old friends, half to herself",
    },
    # The two northern gate guards — previously unnamed ("two guards
    # who watch cursed children with open distrust"), given real
    # cards this session per the same "no unimportant NPC" standard.
    # Two distinct people, not a shared/interchangeable pair — each
    # gets their own key so dialogue/relationship state (npc_events,
    # npc_familiarity) can track them separately if that ever matters.
    "northern_gate_guard_1": {
        "name": "Bram",
        "title": "gate guard",
        "pronouns": "he/him",
        "hostile": False,
        "personality": "gruff, watchful, distrustful of cursed children but not cruel about it",
        "voice_note": "short sentences, states rules rather than explains them",
    },
    "northern_gate_guard_2": {
        "name": "Yselle",
        "title": "gate guard",
        "pronouns": "she/her",
        "hostile": False,
        "personality": "quieter than Bram, watches more than she speaks, softer toward the kids he's harsh with",
        "voice_note": "says little, but what she says tends to be the fairer read of the two",
    },
}

# Name pool the shopkeeper's per-playthrough name is rolled from.
# Plain, warm, easy-to-say names — nothing that reads as a joke or a
# reference, matching the doc's "genuinely fond, a little irreverent"
# character rather than a punchline.
SHOPKEEPER_NAME_POOL = [
    "Maribel", "Odessa", "Junie", "Cordelia", "Rosalind",
    "Wilhelmina", "Petra", "Marisol", "Beatrix", "Dot",
]

_SHOPKEEPER_META_KEY = "pet_shop_keeper_name"


def get_npc_card(npc_key: str) -> dict | None:
    """Returns the full card dict for a known npc_key, or None if it
    isn't a hand-authored card (i.e. it's narrator-improvised).

    NOTE: for "townia_pet_shop_keeper" this returns the template card
    WITHOUT a "name" — that NPC's name is per-player, not fixed. Use
    get_shopkeeper_card(db, sender) to get a complete card for her."""
    return NPC_CARDS.get(npc_key)


def get_shopkeeper_card(db, sender: str) -> dict:
    """Returns a complete pet shop shopkeeper card for this specific
    player, generating and persisting her name on first visit.

    The name is stored in player_meta (per-sender, lighter than a
    full table — matches the doc's "code-generated and saved per
    playthrough" requirement without needing a new global table like
    rpg_world_npcs, which is shared across ALL players and would give
    every player the same shopkeeper). Once rolled for a sender, the
    same name is returned on every subsequent call for that sender.
    """
    template = NPC_CARDS["townia_pet_shop_keeper"]
    name = db.get_meta(sender, _SHOPKEEPER_META_KEY)
    if not name:
        import random
        name = random.choice(SHOPKEEPER_NAME_POOL)
        db.set_meta(sender, _SHOPKEEPER_META_KEY, name)
    return {**template, "name": name}
