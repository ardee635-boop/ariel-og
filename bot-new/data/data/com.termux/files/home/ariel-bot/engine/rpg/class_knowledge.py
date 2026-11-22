"""
RPG: class_knowledge — what every NPC in Townia knows about classes and trials.

Class and trial knowledge is PUBLIC (any guard, shopkeeper or passerby can
explain it), so it is generated from the same data the mechanics use —
townia_trials.py (weapons, classes, win conditions) and the places that
offer each trial (offers_trial in the seed) — instead of being written by
hand. Change a trial or move a trial site and this text follows.

Hidden classes are deliberately absent: anything not defined in
townia_trials is simply not in this block, and the block tells the narrator
that no other class is known to anyone, so NPCs neither invent nor confirm
one. When a class goes from hidden to public, it appears here once it is
added to the trial data.

build() returns "" outside Townia (trials only exist there), so prompts
elsewhere don't pay for it.
"""

import townia_trials as T

_SITE_ORDER = ("warrior", "mage", "summoner")


def _and(items):
    items = list(items)
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _where(site):
    if not site:
        return "somewhere in Townia"
    name = site["name"] or "somewhere in Townia"
    return f"{name} ({site['district']} District)" if site.get("district") else name


def build(db, place) -> str:
    if not place or place.get("dimension_id") != "townia_dim":
        return ""
    sites = {s["trial"]: s for s in db.get_trial_sites()}

    lines = [
        "CLASS & TRIAL KNOWLEDGE (common knowledge: every NPC in Townia knows this, "
        "from guards to passersby. Answer questions about it accurately and in "
        "character; don't recite it unprompted):",
        "- A cursed child earns a class by passing a trial, then confirming the "
        "change. Trials can be retaken any number of times; failing costs nothing.",
    ]

    if "warrior" in sites:
        fight = [w for w in T.WARRIOR_WEAPONS if T.WEAPON_MECHANIC[w] == "fight"]
        grants = "; ".join(f"{w} -> {' and '.join(T.WEAPON_CLASS[w])}" for w in T.WARRIOR_WEAPONS)
        lines.append(
            f"- Warrior trial, at {_where(sites['warrior'])}: pick a weapon "
            f"({', '.join(T.WARRIOR_WEAPONS)}) and face that weapon's opponent. "
            f"{_and(fight).capitalize()} are straight duels, won by wearing the opponent down; "
            f"the shield trial is blocking strikes from the right direction "
            f"({T.SHIELD_HITS_TO_WIN} clean blocks wins); the bow trial is landing "
            f"{T.BOW_HITS_TO_WIN} shots. Passing grants the matching class: {grants}.")
    if "mage" in sites:
        lines.append(
            f"- Mage trial, at {_where(sites['mage'])}: study a spoken incantation "
            f"shown briefly; it fades after about {T.MIN_DELETE_SECONDS}-{T.MAX_DELETE_SECONDS} "
            "seconds, then you must recite it back correctly.")
    if "summoner" in sites:
        lines.append(
            f"- Summoner trial, at {_where(sites['summoner'])}: bond with a companion. "
            "Only the first stage (choosing a companion) is open so far; the rest is "
            "still being prepared, so say so if asked what comes next.")

    lines.append(
        "These are the only classes anyone here knows of. If asked about any other "
        "class (hidden, secret, or one not listed), no one here knows of one: never "
        "invent or confirm one.")
    return "\n".join(lines)
