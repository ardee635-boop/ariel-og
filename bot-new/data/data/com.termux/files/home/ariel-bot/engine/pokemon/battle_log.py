# ============================================================
# NIFLHEIM — battle_log.py
# Output frame for battle messages, per the Commands & Formats doc.
# Pure formatting only: no state, no DB. Callers pass in the action
# lines (from resolve_turn) and the HP rows.
# ============================================================

TITLE = "━━ ⚔️ BATTLE LOG ⚔️ ━━"
RULE = "━━━━━━━━━━━━━━━━━━"

PVP_COMMANDS = (
    ".moves — View your Pokémon's moves\n"
    ".switch [name/no] — Switch Pokémon\n"
    ".forfeit — Forfeit the battle\n\n"
    "Say the move name to attack."
)
PVE_COMMANDS = (
    ".moves — View your Pokémon's moves\n"
    ".switch [number] — Switch Pokémon\n"
    ".flee — Run from battle\n\n"
    "Say the move name to attack."
)


def _hp_block(rows, blank_between=False):
    """rows: list of 'label: cur/max HP' strings."""
    sep = "\n\n" if blank_between else "\n"
    return sep.join(rows)


def log_frame(action_lines, hp_rows, commands=None, footer_lines=None,
              blank_between_hp=False):
    """
    action_lines : list[str]  — move/effect lines, already formatted
    hp_rows      : list[str]  — e.g. ["@Joel's Lucario: 72/120 HP", ...]
    commands     : str|None   — PVP_COMMANDS / PVE_COMMANDS, None when battle ended
    footer_lines : list[str]  — faint / result / 'Battle ended.' lines
    PvP rows are tight; PvE rows are spaced (blank_between_hp=True).
    """
    parts = [TITLE, "\n".join(action_lines).strip("\n"), RULE,
             _hp_block(hp_rows, blank_between_hp), RULE]
    if footer_lines:
        parts.append("\n\n".join(footer_lines))
    if commands:
        parts.append(commands)
    return "\n\n".join(p for p in parts if p)


def rewards_block(header, coins=0, xp=0, items=None, others=None):
    """
    Order: Coins -> EXP -> Items -> Others. Only what was earned.
    items/others: list of (qty, name). Returns '' if nothing earned.
    """
    lines = []
    if coins:
        lines.append(f"> {coins} PokéCoins")
    if xp:
        lines.append(f"> {xp} XP")
    for qty, name in (items or []):
        lines.append(f"> {qty}× {name}")
    for qty, name in (others or []):
        lines.append(f"> {qty}× {name}")
    if not lines:
        return ""
    return f"{header} received:\n" + "\n".join(lines)


# ── Action lines (one actor's move block) ─────────────────────

def action_block(actor, move, dmg=None, eff=1.0, crit=False, missed=False, notes=()):
    """Move, damage, crit, effectiveness (only if != 1.0), then status notes.
    notes: already-worded strings, rendered as '> ...' lines."""
    lines = [f"{actor} used {move}!"]
    if missed:
        return lines + ["> But it missed!"]
    if dmg is not None and eff == 0:
        lines.append("> It had no effect!")
    elif dmg is not None:
        lines.append(f"> It dealt {dmg} damage!")
        if crit:
            lines.append("> Critical hit!")
        if eff > 1:
            lines.append("> It's super effective!")
        elif eff < 1:
            lines.append("> It's not very effective...")
    return lines + [f"> {n}" for n in notes]


def join_blocks(blocks):
    """Blank line between actors."""
    return "\n\n".join("\n".join(b) for b in blocks if b).split("\n")


def switch_block(trainer, old, new):
    return [f"{trainer} withdrew {old}!", f"> {trainer} sent out {new}!"]


# ── Faint / result text ───────────────────────────────────────

def replacement_prompt(fainted, options):
    """options: [(slot, name, cur, max)]. Uses .switch (no .gb switch)."""
    rows = "\n".join(f"[ {n} ] {nm} ({c}/{m} HP)" for n, nm, c, m in options)
    return (f"{RULE}\n*Oh no! Your {fainted} fainted!*\n*Choose a replacement:*\n"
            f"> Use `.switch <number>`\n\n{rows}")


def pvp_end_lines(fainted, loser, winner):
    return [f"*Oh no! Your {fainted} fainted!*",
            f"*{loser} has no remaining Pokémon!*",
            f"*{winner} wins the battle!*",
            "Battle ended."]


def forfeit_text(quitter, winner):
    """.flee and .forfeit are interchangeable (PvP)."""
    return f"{quitter} forfeited the battle!\n\n*{winner} wins!*\n\nBattle ended."


def pve_win_lines(wild):
    return [f"The wild {wild} ran away!", "Battle ended."]


def pve_lose_lines(mon):
    return [f"Your {mon} can no longer battle!", "Battle ended."]


# ── PvE ───────────────────────────────────────────────────────

def encounter_marker(sprite, name, description):
    """Big preview (image + name + description as separate fields) FIRST,
    announcement text after. Name/description are NOT repeated in the text.
    The empty __TYPE__ token is required by send.js's __THUMB__ parser."""
    body = ("A wild Pokémon appeared! 🎊\n\n"
            "What will you do?\n\n"
            ".fight   .flee")
    return f"__THUMB__{sprite}__TITLE__{name}__SUB__{description}__TYPE____CAP__{body}"


def pve_hp_rows(mon_name, mon_hp, mon_max, wild_name, wild_hp, wild_max):
    return [f"Your {mon_name}: {max(0, mon_hp)}/{mon_max} HP",
            f"Wild {wild_name}: {max(0, wild_hp)}/{wild_max} HP"]


def pve_start_caption(rows):
    return log_frame(["A wild Pokémon battle has started!"], rows, PVE_COMMANDS,
                     blank_between_hp=True)


# ── .move(s) ──────────────────────────────────────────────────

def _mv_name(name):
    return name.replace("-", " ").title()


def _mv_stats(r):
    power = r["power"] if r.get("power") else "—"
    return (f"Type: {r['type'].title()} ({r['category'].title()})",
            f"Power: {power}", f"Accuracy: {r['accuracy']}")


def moves_list(mon_name, rows):
    """rows: dicts {name, pp, max_pp, type, category, power, accuracy}."""
    out = [f"*{mon_name}'s Moves*", ""]
    for i, r in enumerate(rows, 1):
        t, p, a = _mv_stats(r)
        out += [f"{i}. *{_mv_name(r['name'])}*", f"   PP: {r['pp']}/{r['max_pp']}",
                f"   {t}", f"   {p}", f"   {a}", ""]
    out.append("Use .move(s) <number> to see move details.")
    return "\n".join(out)


def move_detail(r):
    t, p, a = _mv_stats(r)
    bold = lambda s: "*" + s.split(":", 1)[0] + ":*" + s.split(":", 1)[1]
    return "\n".join([
        f"*{_mv_name(r['name'])}*", "",
        f"*PP:* {r['pp']} / {r['max_pp']}", bold(t), bold(p), bold(a), "",
        f"*Description:* {r.get('description') or r.get('effect') or '—'}"])
