# hud.py is being rewritten for Pokémon — stub out old combat imports
battle_hud = encounter = fight_opener = monster_telegraph = None
dodge_result = victory_kill = victory_level_up = victory_prof_up = None
victory_quest_progress = death = revive = flee_success = flee_fail = None
too_tired = identify = encounter_pending = encounter_walked_away = None
encounter_noticed = None
# ============================================================
# RAPHAEL – INTERFACES.PY
# UI text, registration flow, HUD styles, font system
# Images: reg_start only | .guild | .identify | .skill (single)
# No pictures for: zone, battle, inv, skills list, status, shop,
#                  forge, town, kaelen, potions
# ============================================================

import random
ARIEL_HEADER = "┌───萌 𝐀𝐑𝐈𝐄𝐋 萌───┐"
ARIEL_FOOT   = "└────────────『 萌 』"

def ariel_block(*lines):
    body = "\n".join("┝ " + l if l else "┝" for l in lines)
    return ARIEL_HEADER + "\n┝\n" + body + "\n┝\n" + ARIEL_FOOT

RM = '\u200b' * 700

# ── Font system ───────────────────────────────────────────────
_player_fonts = {}

_FONT_MAP = {
    "gothic": str.maketrans(
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789",
        "𝕬𝕭𝕮𝕯𝕰𝕱𝕲𝕳𝕴𝕵𝕶𝕷𝕸𝕹𝕺𝕻𝕼𝕽𝕾𝕿𝖀𝖁𝖂𝖃𝖄𝖅𝖆𝖇𝖈𝖉𝖊𝖋𝖌𝖍𝖎𝖏𝖐𝖑𝖒𝖓𝖔𝖕𝖖𝖗𝖘𝖙𝖚𝖛𝖜𝖝𝖞𝖟𝟎𝟏𝟐𝟑𝟒𝟓𝟔𝟕𝟖𝟗"
    ),
    "bold_sans": str.maketrans(
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789",
        "𝗔𝗕𝗖𝗗𝗘𝗙𝗚𝗛𝗜𝗝𝗞𝗟𝗠𝗡𝗢𝗣𝗤𝗥𝗦𝗧𝗨𝗩𝗪𝗫𝗬𝗭𝗮𝗯𝗰𝗱𝗲𝗳𝗴𝗵𝗶𝗷𝗸𝗹𝗺𝗻𝗼𝗽𝗾𝗿𝘀𝘁𝘂𝘃𝘄𝘅𝘆𝘇𝟬𝟭𝟮𝟯𝟰𝟱𝟲𝟳𝟴𝟵"
    ),
    "mono": str.maketrans(
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789",
        "𝙰𝙱𝙲𝙳𝙴𝙵𝙶𝙷𝙸𝙹𝙺𝙻𝙼𝙽𝙾𝙿𝚀𝚁𝚂𝚃𝚄𝚅𝚆𝚇𝚈𝚉𝚊𝚋𝚌𝚍𝚎𝚏𝚐𝚑𝚒𝚓𝚔𝚕𝚖𝚗𝚘𝚙𝚚𝚛𝚜𝚝𝚞𝚟𝚠𝚡𝚢𝚣𝟶𝟷𝟸𝟹𝟺𝟻𝟼𝟽𝟾𝟿"
    ),
    "script": str.maketrans(
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789",
        "𝓐𝓑𝓒𝓓𝓔𝓕𝓖𝓗𝓘𝓙𝓚𝓛𝓜𝓝𝓞𝓟𝓠𝓡𝓢𝓣𝓤𝓥𝓦𝓧𝓨𝓩𝓪𝓫𝓬𝓭𝓮𝓯𝓰𝓱𝓲𝓳𝓴𝓵𝓶𝓷𝓸𝓹𝓺𝓻𝓼𝓽𝓾𝓿𝔀𝔁𝔂𝔃𝟎𝟏𝟐𝟑𝟒𝟓𝟔𝟕𝟖𝟗"
    ),
}

_FONT_NAMES = {
    "1": ("gothic",    "𝕬𝕭𝕮 Gothic"),
    "2": ("bold_sans", "𝗔𝗕𝗖 Bold"),
    "3": ("mono",      "𝙰𝙱𝙲 Mono"),
    "4": ("script",    "𝓐𝓑𝓒 Script"),
}

# ── Menu preset styles ────────────────────────────────────────
# Each preset is a dict of style tokens used by pmenu() and menu()
_MENU_PRESETS = {
    0: {
        "header":    "╭━━★彡 𝚴𝐈ҒԼ𝚮𝚵𝐈𝚳 彡★━━╮\n┃  𖤓 Prefix: .\n┃  𖤓 Name: Ariel\n┃  𖤓 Creator: Ice King\n╰━━━━━━━━━━━━━╯",
        "sec_open":  lambda t, e: f"*{e} {t} {e}*",
        "row":       "┣ ✦ ",
        "sec_close": "┗━━━━━━━━━━━",
    },
    1: {
        "header":    "╭━━★彡 ҒԼ 彡★━━╮\n┃ ⋆⁺₊❅ Prefix: .\n┃ ⋆⁺₊❅ Name: Ariel\n┃ ⋆⁺₊❅ Creator: Ice King\n╰━━━━━━━━━━━━━╯",
        "sec_open":  lambda t, e: f"* {t} *",
        "row":       "┃ ⋆⁺₊❅ ",
        "sec_close": "╰━━━━━━━━━━━━━",
    },
    2: {
        "header":    "╭━━★彡 ҒԼ 彡★━━╮\n┃ ✦ ✧ Prefix: .\n┃ ✦ ✧ Name: Ariel\n┃ ✦ ✧ Creator: Ice King\n╰━━━━━━━━━━━━━╯",
        "sec_open":  lambda t, e: f" {t} ",
        "row":       "┃ ✦ ✧ ",
        "sec_close": "╰━━━━━━━━━━━━━",
    },
    3: {
        "header":    "╭━━★彡 ҒԼ 彡★━━╮\n┃ ┧ Prefix: .\n┃ ┧ Name: Ariel\n┃ ┧ Creator: Ice King\n╰━━━━━━━━━━━━━╯",
        "sec_open":  lambda t, e: f"* {t} *",
        "row":       "┃ 🔥 ",
        "sec_close": "╰━━━━━━━━━━━━━",
    },
    4: {
        "header":    "╔══〔 𝕹𝖎𝖋𝖑𝖍𝖊𝖎𝖒 〕══╗\n║  ❄ Prefix: .\n║  ❄ Name: Ariel\n║  ❄ Creator: Ice King\n╚═══════════════════╝",
        "sec_open":  lambda t, e: f"❄━━━ {t} ━━━❄",
        "row":       "║ ❅ ",
        "sec_close": "╚══════════════════",
    },
}

def _get_preset(player) -> dict:
    idx = getattr(player, "menu_preset", 0)
    return _MENU_PRESETS.get(idx, _MENU_PRESETS[0])

def _sec(style, title, emoji, rows) -> str:
    """Build one menu section using the active preset style."""
    header = style["sec_open"](title, emoji)
    body   = "".join(style["row"] + r + "\n" for r in rows)
    return f"{header}\n{body}{style['sec_close']}\n\n"


class RPGFont:
    @staticmethod
    def set_font(key, sender):
        if key not in _FONT_NAMES:
            return "Invalid font. Use *.font* to see options."
        name, label = _FONT_NAMES[key]
        _player_fonts[sender] = name
        return f"Font set to *{label}*."

    @staticmethod
    def set_preset(player, key: str) -> str:
        """Set menu layout preset on player. key = '0'-'4'."""
        valid = {"0", "1", "2", "3", "4"}
        if key not in valid:
            return "❌ Invalid preset. Use *.font 0* to *.font 4*."
        player.menu_preset = int(key)
        labels = {
            "0": "Default ★彡",
            "1": "Ice Crystal ⋆⁺₊❅",
            "2": "Double Star ✦✧",
            "3": "Fire 🔥",
            "4": "Niflheim ❄",
        }
        return f"✅ Menu style set to *{labels[key]}*."

    @staticmethod
    def show_fonts():
        return (
            "🎨 *Menu Presets*\n\n"
            "*.font 0*  — Default ★彡\n"
            "*.font 1*  — Ice Crystal ⋆⁺₊❅\n"
            "*.font 2*  — Double Star ✦✧\n"
            "*.font 3*  — Fire 🔥\n"
            "*.font 4*  — Niflheim ❄\n\n"
            "_Type .font [0-4] to switch_"
        )


# ── Registration image (step 1 only) ─────────────────────────
REG_IMG = "https://i.ibb.co/HLyLq0sx/1775695517151-2.png"

# ── Egg image map ─────────────────────────────────────────────
EGG_IMAGES = {
    "Cryo Egg":  "https://i.ibb.co/BVKBXjdh/Cryo-Egg.jpg",
    "Floro Egg": "https://i.ibb.co/jPStdZjZ/Floro-Egg.jpg",
    "Atmo Egg":  "https://i.ibb.co/cckKbyY8/Atmo-Egg.jpg",
    "Crust Egg": "https://i.ibb.co/53dQrvZ/Crust-Egg.jpg",
    # TODO: upload Dragon_Egg.jpg / Ghoul_Egg.jpg / Fairy_Egg.jpg to a
    # host (ibb.co or similar) and paste the real URLs here — these are
    # only used by egg_receive_message()'s WhatsApp image caption, not
    # by the site (the site references its own copies directly).
    "Dragon Egg": "",
    "Ghoul Egg":  "",
    "Fairy Egg":  "",
    "Random Floro Egg": "",
}

GAEA_CLASS_REACTIONS = {
    "Mage":    "❝ A Mage? *(Gaea chuckles...)* Seeking to bend the laws of reality to your will? A dangerous ambition, little spark. ❞",
    "Warrior": "❝ A Warrior? *(Gaea chuckles...)* You choose the path of steel and blood. May your shield hold longer than those who came before you. ❞",
    "Scout":   "❝ A Scout? *(Gaea chuckles...)* An interesting choice indeed. The shadows are a lonely place for those who cannot back up their pride. ❞",
    "Archer":  "❝ An Archer? *(Gaea chuckles...)* You wish to strike from afar, never letting the enemy see the face of their end. A wise, if cold, choice. ❞",
}

GAEA_BLESSINGS = {
    "Mage": "Aether", "Warrior": "Iron", "Scout": "Shadows", "Archer": "Wind"
}

GENDER_CHILD = {"Male": "son", "Female": "daughter", "Other": "child"}


def _hp_line(current, maximum, emoji="♥"):
    pct = int((current / maximum) * 100) if maximum > 0 else 0
    return f"{emoji} {current}/{maximum} ({pct}%)"


class UI:
    # ── Registration ─────────────────────────────────────────

    @staticmethod
    def reg_start():
        body = (
            f"❝ Wake up, Wanderer. Your story isn't finished yet. ❞\n\n"
            f"──────────────────\n{RM}\n──────────────────\n\n"
            f"The world is a blur of starlight. You have no home, no title...\n"
            f"Only the clothes on your back and the path beneath your feet.\n\n"
            f"──────────────────\n{RM}\n──────────────────\n\n"
            f"❝ State your name, child. ❞\n\n"
            f"Type *.name [your name]* to proceed.\n"
            f"_Example: .name Equinox_"
        )
        return (
            f"__IMG__{REG_IMG}"
            )

    @staticmethod
    def reg_step2(name):
        return (
            f"❝ *{name}*... a name that balances light and dark. ❞\n\n"
            f"{RM}\n"
            f"_The void ripples as your name is etched into the stars._\n"
            f"_The Goddess Gaea leans in, her form shimmering like a nebula._\n\n"
            f"{RM}\n"
            f"❝ But tell me, child — how do you walk through this world? ❞\n\n"
            f"{RM}\n"
            + ariel_block(
                f"👤 ENTITY: {name}",
                "📍 LOCATION: THE VOID",
                "🧬 GENDER: PENDING...",
                "",
                "1️⃣ Male",
                "2️⃣ Female",
                "3️⃣ Other",
                "",
                "✦ .gender [number]",
            )
        )

    @staticmethod
    def reg_step4(name, race="Human"):
        return (
            f"❝ Now, *{name}* — which path calls to your soul? ❞\n\n"
            f"{RM}\n"
            f"_The Goddess Gaea observes the shifting currents of your destiny._\n\n"
            f"{RM}\n"
            + ariel_block(
                f"👤 ENTITY: {name}",
                "🎓 CLASS: PENDING...",
                "",
                "1️⃣ 🔮 Mage",
                "2️⃣ ⚔️ Warrior",
                "3️⃣ 🗡️ Scout",
                "4️⃣ 🏹 Archer",
                "",
                "✦ .class [number]",
            )
        )

    @staticmethod
    def reg_confirm(name, gender, race, class_type):
        return (
            f"*Name:* {name}\n"
            f"*Gender:* {gender}\n"
            f"*Class:* {class_type}\n\n"
            f"Type *yes* to confirm or *no* to restart."
        )

    @staticmethod
    def reg_complete(player):
        reaction = GAEA_CLASS_REACTIONS.get(player.class_type, "❝ An interesting choice. ❞")
        blessing = GAEA_BLESSINGS.get(player.class_type, "Fate")
        return (
            f"{reaction}\n\n"
            f"{RM}\n"
            f"❝ Go forth, *{player.name}*. "
            f"Carve a legend so grand that even the Heavens will be forced to whisper your name. ❞\n\n"
            f"❝ May the *{blessing}* keep you. ❞\n\n"
            f"{RM}\n"
            f"_The void shatters. The warmth of the Goddess fades._\n\n"
            f"📜 *PROFILE INITIALIZED*\n\n"
            + ariel_block(
                "✦ .quicktravel [zone]  to travel",
                "✦ .menu     all commands",
                "✦ .tutorial optional tutorial",
            )
        )

    @staticmethod
    def already_registered(player):
        return (
            f"{player.icon()} *You have already awakened, {player.name} the {player.class_type}.*\n"
            f"_Your legend is already written._\n\n"
            f"Type *.menu* to see your options."
        )

    @staticmethod
    def reg_bad_name():
        return None

    @staticmethod
    def reg_bad_gender():
        return None

    @staticmethod
    def reg_bad_race():
        return None

    @staticmethod
    def reg_bad_class():
        return None

    # ── Trainer Card ──────────────────────────────────────────
    @staticmethod
    def card(player):
        import datetime
        s    = _get_preset(player)
        name = player.name.upper()

        # Build header with player name instead of "NIFLHEIM"
        _CARD_HEADERS = {
            0: lambda n: f"╭━━★彡 {n} 彡★━━╮\n┃  ❝ {player.bio or 'No bio set'} ❞\n┃  ◈ Rank · {player.guild_rank}\n╰━━━━━━━━━━━╯",
            1: lambda n: f"╭━━★彡 {n} 彡★━━╮\n┃ ⋆⁺₊❅ ❝ {player.bio or 'No bio set'} ❞\n┃ ⋆⁺₊❅ ◈ Rank · {player.guild_rank}\n╰━━━━━━━━━━━━━╯",
            2: lambda n: f"╭━━★彡 {n} 彡★━━╮\n┃ ✦ ✧ ❝ {player.bio or 'No bio set'} ❞\n┃ ✦ ✧ ◈ Rank · {player.guild_rank}\n╰━━━━━━━━━━━━━╯",
            3: lambda n: f"╭━━★彡 {n} 彡★━━╮\n┃ ┧ ❝ {player.bio or 'No bio set'} ❞\n┃ ┧ ◈ Rank · {player.guild_rank}\n╰━━━━━━━━━━━━━╯",
            4: lambda n: f"╔══〔 {n} 〕══╗\n║  ❄ ❝ {player.bio or 'No bio set'} ❞\n║  ❄ ◈ Rank · {player.guild_rank}\n╚═══════════════════╝",
        }
        preset_idx = getattr(player, "menu_preset", 0)
        header_fn  = _CARD_HEADERS.get(preset_idx, _CARD_HEADERS[0])
        header     = header_fn(name)

        # Days since joined
        joined = getattr(player, "joined_at", None)
        if joined:
            try:
                delta = (datetime.datetime.utcnow() - datetime.datetime.fromisoformat(joined)).days
                day_str = f"Day {delta + 1}"
            except Exception:
                day_str = "—"
        else:
            day_str = "Day 1"

        seen   = len(getattr(player, "pokedex_seen", set()))
        caught = len(getattr(player, "pokedex_caught", set()))
        badges = len(getattr(player, "badges", []))
        poke_count = len(player.party) + len(player.box)

        body = (
            header + "\n\n"
            + _sec(s, "PvE", "⚔️", [
                f"↑ Wins · {player.pve_wins}",
                f"↓ Losses · {player.pve_losses}",
            ])
            + _sec(s, "PvP", "🥊", [
                f"↑ Wins · {player.pvp_wins}",
                f"↓ Losses · {player.pvp_losses}",
            ])
            + _sec(s, "PROFILE", "📦", [
                f"Pokémon · {poke_count}",
                f"Pokédex · {seen} seen / {caught} caught",
                f"Badges · {badges}",
                f"Guild Rank · {player.guild_rank}",
                f"Quests Done · {player.quests_done}",
                f"Since · {day_str}",
            ]).rstrip()
        )
        return body

    # ── Exploration ───────────────────────────────────────────
    @staticmethod
    def zone_enter(player, zone_name, gate_name="North Gate", zone_img=""):
        nav  = "1 · 2 · 3 · 4"
        return f"🌿 *{zone_name}*\n_{gate_name}_\n\n_The air shifts. Something stirs in the distance._\n\n{nav}"

    @staticmethod
    def zone_move(zone_name, danger, atmos, time_str, zone_img=""):
        nav = "1 · 2 · 3 · 4"
        return f"*{zone_name}*  {danger}\n_{atmos}_\n\n{time_str}\n\n{nav}"

    @staticmethod
    def move_no_encounter(player, direction, zone_name="", gate_name="", zone_img=""):
        flairs = [
            "✦ _Something watches from the trees._",
            "✦ _The air grows thick with silence._",
            "✦ _Footsteps in the distance — not yours._",
            "✦ _A rustle. Then nothing._",
            "✦ _The path ahead is quiet... for now._",
        ]
        flair = random.choice(flairs)
        nav   = "1 · 2 · 3 · 4"
        return f"_🌿 {player.name} ventures {direction}..._\n{flair}\n\n{nav}"

    @staticmethod
    def already_in_zone(player):
        return (
            f"You're already in a zone.\n\n"
            f"1 · 2 · 3 · 4\n\n"
            f"Or *.flee* to leave."
        )

    # ── Zone detail (.zone) ────────────────────────────────────
    @staticmethod


    # ── Zone detail (.zone) ────────────────────────────────────
    @staticmethod
    def zone_detail(zone_data, zone_img=""):
        body = (
            f"*{zone_data['name']}*\n"
            f"{zone_data.get('danger','')}\n\n"
            f"_{zone_data.get('description','A mysterious place.')}_\n\n"
            f"Min Level: {zone_data.get('min_level',1)}"
        )
        if zone_img:
            return f"__IMG__{zone_img}__CAP__{body}"
        return body

    # ── Look (.look) ──────────────────────────────────────────
    @staticmethod
    def look(zone_name, zone_img="", atmos=""):
        body = (
            f"👁️ *You scan your surroundings...*\n\n"
            f"_{atmos or 'The area feels unsettled.'}_"
        )
        if zone_img:
            return f"__IMG__{zone_img}__CAP__{body}"
        return body


    # ── Skills list (no picture) ──────────────────────────────
    @staticmethod
    def skills_list(player):
        lines    = [f"⚔️ *{player.name}'s Skills — {player.class_type}*\n"]
        actives  = [s for s in player.skills if s.get("type") != "passive"]
        passives = [s for s in player.skills if s.get("type") == "passive"]
        for i, sk in enumerate(actives, 1):
            legacy_tag = "👑 " if sk.get("legacy") else ""
            unbreak    = " ★" if sk.get("unbreakable") else ""
            rarity     = sk.get("rarity","Common")
            cast_time  = sk.get("cast_time","instant")
            cd         = sk.get("cd", 0)
            cd_str     = f"{cd}s" if cd else "—"
            lines.append(
                f"{i}. {legacy_tag}*{sk['name']}*{unbreak}  _{rarity}_  [Active]\n"
                f"   _{sk.get('flavor','')}_\n"
                f"   Cast: {cast_time}  CD: {cd_str}"
            )
        if passives:
            lines.append("")
            for i, sk in enumerate(passives, 1):
                rarity = sk.get("rarity","Common")
                lines.append(
                    f"P{i}. *{sk['name']}*  _{rarity}_  [Passive]\n"
                    f"   _{sk.get('flavor','')}_"
                )
        lines.append("\n_Type skill name to use · *.skill [name]* for details_")
        return "\n".join(lines)

    # ── Single skill detail (.skill name) ─────────────────────
    @staticmethod
    def skill_detail(skill, img=""):
        """Shows one skill with optional image (when pics are added later)."""
        legacy_tag = "👑 Legacy  " if skill.get("legacy") else ""
        unbreak    = "  ★ Cannot be broken" if skill.get("unbreakable") else ""
        cast_time  = skill.get("cast_time","instant")
        cd         = skill.get("cd",0)
        cd_str     = f"{cd}s" if cd else "None"
        mp         = skill.get("mp_cost","—")
        if "mp_cost_pct" in skill:
            mp = f"{int(skill['mp_cost_pct']*100)}% MP"
        body = (
            f"{legacy_tag}*{skill['name']}*{unbreak}\n"
            f"_{skill.get('rarity','')} · {skill.get('type','').title()}_\n\n"
            f"_{skill.get('flavor','')}_\n\n"
            f"Cast: {cast_time}  CD: {cd_str}  Cost: {mp}"
        )
        if img:
            return f"__IMG__{img}__CAP__{body}"
        return body

    # ── Cooldowns ─────────────────────────────────────────────
    @staticmethod
    def cooldowns(player):
        lines = [f"⏳ *Cooldowns — {player.name}*\n"]
        any_cd = False
        for sk in player.skills:
            remaining = 0
            if sk.get("cd_type") != "turn" and sk.get("cd_last_used",0) > 0:
                import time
                elapsed   = time.time() - sk.get("cd_last_used",0)
                remaining = max(0, sk.get("cd",0) - elapsed)
            if remaining > 0:
                mins = int(remaining // 60)
                secs = int(remaining % 60)
                cd_str = f"{mins}m {secs}s" if mins else f"{secs}s"
                lines.append(f"┣ *{sk['name']}*  — {cd_str} left")
                any_cd = True
        if not any_cd:
            lines.append("_All skills ready!_")
        return "\n".join(lines)

    # ── Inventory ─────────────────────────────────────────────
    @staticmethod
    def inventory(player):
        from data_items import indexed_inventory, POKEBALLS, HEALING_ITEMS, PP_ITEMS, HELD_ITEM_EFFECTS, EVOLUTION_STONES, EXPERIENCE_STONES
        from egg import ALL_EGGS, egg_incubation_status

        CATEGORY_ORDER = [
            ("🔴 Poké Balls",   POKEBALLS),
            ("💊 Medicine",     {**HEALING_ITEMS, **PP_ITEMS}),
            ("⚔️ Battle Items", HELD_ITEM_EFFECTS),
            ("💎 Stones",       {**{s: None for s in EVOLUTION_STONES}, **EXPERIENCE_STONES}),
        ]

        rows = indexed_inventory(player)  # [(number, item, qty), ...] — single source of truth,
                                           # shared with .sell / .inv [n] / .use so numbers never drift
        egg_status = egg_incubation_status(player)

        lines = [f"🎒 *{player.name}'s Bag*\n"]

        for cat_label, cat_items in CATEGORY_ORDER:
            cat_lines = [f"{n}. {item} × {qty}" for n, item, qty in rows if item in cat_items]
            if cat_lines:
                lines.append(f"*{cat_label}*")
                lines.extend(cat_lines)
                lines.append("")

        known = set()
        for _, cat_items in CATEGORY_ORDER:
            known.update(cat_items.keys())

        egg_lines, key_lines = [], []
        for n, item, qty in rows:
            if item in known:
                continue
            if item in ALL_EGGS:
                status = egg_status.get(item, "")
                suffix = f"  {status}" if status else ""
                egg_lines.append(f"{n}. {item} × {qty}{suffix}")
            else:
                key_lines.append(f"{n}. {item} × {qty}")

        if egg_lines:
            lines.append("*🥚 Eggs*")
            lines.extend(egg_lines)
            lines.append("")
        if key_lines:
            lines.append("*🗝️ Key Items*")
            lines.extend(key_lines)
            lines.append("")

        if not rows:
            lines.append("_Your bag is empty._")

        lines.append("_.catch [no.] · .med [no.] · .use [no.]_")
        return "\n".join(lines)

    @staticmethod
    def inventory_item(item_name, qty):
        from data_items import POKEBALLS, HEALING_ITEMS, PP_ITEMS, HELD_ITEM_EFFECTS, item_description
        desc = item_description(item_name)

        if item_name in POKEBALLS:
            mult = POKEBALLS[item_name]
            extra = f"\n_Catch rate: ×{mult}_"
        elif item_name in HEALING_ITEMS:
            eff = HEALING_ITEMS[item_name]
            extra = f"\n_Effect: {eff['effect']} +{eff['value']}_"
        elif item_name in PP_ITEMS:
            eff = PP_ITEMS[item_name]
            extra = f"\n_Effect: {eff['effect']} +{eff['value']}_"
        elif item_name in HELD_ITEM_EFFECTS:
            eff = HELD_ITEM_EFFECTS[item_name]
            extra = f"\n_Trigger: {eff['trigger']}_"
        else:
            extra = ""

        return f"{desc}\n*Qty:* {qty}{extra}"

    # ── Town square (no image) ────────────────────────────────
    @staticmethod
    def town_square(player):
        return (
            "⛪︎ *Town Square* ⛪︎\n"
            "NPC: Ariel\n\n"
            "_\"Welcome to Avalon.\"_\n\n"
            "*.guild*\n"
            "*.shop*\n"
            "*.forge*\n"
            "*.quicktravel [zone] to move on*"
        )

    @staticmethod
    def city_gate_fine(player, fine=15):
        return (
            f"💂 *CITY GATE:* _{player.name}, since you lack a Guild Pass,_\n"
            f"_a {fine}G entry tax has been deducted from your pouch._\n\n"
            f"💰 Remaining: *{player.coins}G*\n\n"
            f"_Type *.guildreg* to waive all future fees._"
        )

    # ── Shop (no image) ───────────────────────────────────────
    @staticmethod
    def shop_menu(player, items):
        weapons     = [i for i in items if i["item_type"]=="weapon"]
        consumables = [i for i in items if i["item_type"]=="consumable"]
        artifacts   = [i for i in items if i["item_type"]=="artifact"]
        materials   = [i for i in items if i["item_type"]=="material"]
        armor       = [i for i in items if i["item_type"]=="armor"]

        def _row(it):
            lock = " 🔒" if it.get("locked") else ""
            return f"┃ [{it['id']}] {it['name']}{lock}  ·  {it['price']}G"

        return (
            "*Merchant's Trove*\n"
            "*NPC:* _Doran_\n"
            "_General Shop_\n\n"
            f"_\"Welcome welcome, always a pleasure to do business with you, {player.name}.\"_\n\n"
            "*.general*\n"
            "*.weapons*\n"
            "*.materials*\n"
            "*.armor*\n"
            "*.leave*"
        )

    # ── Forge (no image) ──────────────────────────────────────
    @staticmethod
    def forge_menu(player, inv_items):
        body = (
            "*The Iron Hearth*\n"
            "*NPC:* _Torvin_\n"
            "_Smithy · Forge_\n\n"
            "_*(Torvin grunts without looking up.) Just don't break anything...*_\n\n"
        )
        weapons = [i for i in inv_items if i["item_type"]=="weapon"]
        if weapons:
            body += "*⚔️ Your Weapons*\n"
            for w in weapons:
                lvl  = w.get("level", 0)
                plus = f" +{lvl}" if lvl > 0 else ""
                body += f"┃ [{w['item_id']}] {w['item_name']}{plus}\n"
            body += "\n"
        body += (
            "*.upgrade [inventory ID]*\n"
            "*.repair*\n"
            "*.enchant*\n"
            "*.craft*\n"
            "*.leave*"
        )
        return body

    # ── News ──────────────────────────────────────────────────
    @staticmethod
    def news_feed(entries):
        if not entries:
            return "📰 *Avalon News*\n\n_No reports yet. The world is quiet... for now._"
        lines = [f"📰 *Avalon News Board*\n"]
        event_icons = {"world":"🌍","boss":"💀","guild":"🏛️","pvp":"⚔️","system":"⚙️"}
        for e in entries:
            icon = event_icons.get(e.get("type","world"),"📌")
            lines.append(f"{icon} *{e['headline']}*\n_{e.get('body','')}_ \n")
        return "\n".join(lines)

    @staticmethod
    def leaderboard(entries):
        lines = ["🏆 *Legends of Avalon*\n"]
        medals = ["🥇","🥈","🥉"]
        for i, row in enumerate(entries[:10], 1):
            name, cls, rank, kills, missions = row
            m = medals[i-1] if i <= 3 else f"{i}."
            lines.append(f"{m} *{name}* — {cls} · Kills: {kills} · Missions: {missions}")
        return "\n".join(lines) if len(lines) > 1 else "_No records yet._"

    @staticmethod
    def guild_sell_empty():
        return "❝ You have nothing to sell, adventurer. Go out and fight something. ❞"

    @staticmethod
    def guild_sold(items, coins):
        return (
            f"💰 *Items sold!*\n\n"
            f"_{', '.join(items)}_\n\n"
            f"Received *{coins} coins*."
        )

    @staticmethod
    def guild_hidden_quest(player):
        return (
            f"❝ If you wish to meet him… step up your game. ❞\n\n"
            f"⭐ *Hidden Quest Unlocked!*\n\n"
            f"*Eccentric Guildmaster*\n"
            f"_Gain 3 levels within 10 minutes_\n\n"
            f"Reward: _Meet Guildmaster Gerald_"
        )

    # ── PvP ───────────────────────────────────────────────────
    @staticmethod
    def pvp_challenge(challenger, target):
        return (
            f"⚔️ *{challenger}* challenges *{target}* to a duel!\n\n"
            f"Type *.accept* or *.decline*."
        )


    @staticmethod
    def sp_menu(player):
        sp      = getattr(player, "sp", 0)
        RM      = "\u200b" * 700
        stats   = player.stats
        stat_str = "  ".join(f"{k}: {v}" for k, v in stats.items())
        return (
            f"✨ *Stat Points — {sp} SP available*\n"
            f"\n{RM}\n"
            f"{stat_str}\n\n"
            f"_.sp [stat] → +1_\n"
            f"_.sp [stat] [amount] → +X_"
        )

    @staticmethod
    def sp_result(player, stat, amount, sp_left):
        return (
            f"✨ *+{amount} {stat}* → now {player.stats.get(stat, '?')}\n"
            f"SP remaining: {sp_left}"
        )

    @staticmethod
    def balance(player):
        return f"💰 Coins: {player.coins:,}"


    @staticmethod
    def gate_blocked(gate_name, min_level, player_level, guard_quote):
        return (
            f"🚧 *{gate_name.title()} Gate — Restricted*\n\n"
            f"_{guard_quote}_\n\n"
            f"Required: Lv.{min_level}  |  You: Lv.{player_level}"
        )

    GATE_GUARD_QUOTES = {
        "north": "The Northern Gate is open to all. The forest however, is not.",
        "east":  "Eastern Gate requires Lv.15 minimum. Train harder.",
        "west":  "The Scorched Woods are no place for someone your level.",
        "south": "Lv.30 minimum for the Southern Gate. I am not negotiating.",
    }

    @staticmethod
    def explore_move(player, zone, atm, image_url=""):
        from engine_clock import get_time_display
        from map import load_zone, IMPASSABLE

        try:
            time_str = get_time_display()
        except:
            time_str = "Day"

        # Danger → star rating
        DANGER_STARS = {
            "🟢 Safe":      1,
            "🟢 Mild":      2,
            "🟡 Moderate":  3,
            "🟠 Dangerous": 4,
            "🔴 Deadly":    5,
            "⚡ Barrier":   1,
        }
        star_count = DANGER_STARS.get(zone.get("danger", ""), 2)
        stars = "✧" * star_count

        cx, cy = player.zone_x, player.zone_y

        # Direction buttons — ✘ if next tile is impassable
        def is_blocked(dc, dr):
            try:
                z = load_zone(player.zone)
                g = z.get("grid", [])
                nc, nr = cx + dc, cy + dr
                if not (0 <= nr < len(g) and 0 <= nc < len(g[0])): return True
                return g[nr][nc] in IMPASSABLE
            except:
                return False

        n = "✘" if is_blocked( 0, -1) else "Forward"
        s = "✘" if is_blocked( 0,  1) else "Backward"
        w = "✘" if is_blocked(-1,  0) else "Left"
        e = "✘" if is_blocked( 1,  0) else "Right"

        col_w = 18
        row1 = f"1 [{n}]".ljust(col_w) + f"2 [{s}]"
        row2 = f"3 [{w}]".ljust(col_w) + f"4 [{e}]"

        return (
            f"*{zone['name']}* {stars}\n"
            f"_{atm}_\n\n"
            f"{time_str}       ({cx}, {cy})\n\n"
            f"{row1}\n"
            f"{row2}"
        )


    @staticmethod
    def bestiary_menu():
        return (
            "📖 *Bestiary — Avalon Grimoire*\n\n"
            "Filter by:\n"
            "1️⃣ Name (A-Z)\n"
            "2️⃣ Rank (F-S)\n"
            "3️⃣ Zone\n"
            "4️⃣ Tier\n\n"
            "_.bestiary name a_\n"
            "_.bestiary rank c_\n"
            "_.bestiary zone jotun_\n"
            "_.bestiary tier 2_"
        )

    @staticmethod
    def pvp_leaderboard(entries):
        lines = ["🏆 *PvP Leaderboard*\n"]
        medals = ["🥇","🥈","🥉"]
        for i, (name, wins, losses) in enumerate(entries[:10], 1):
            m = medals[i-1] if i <= 3 else f"{i}."
            lines.append(f"{m} *{name}*  W:{wins}  L:{losses}")
        return "\n".join(lines) if len(lines) > 1 else "No duel records yet."

    @staticmethod
    def pvp_record(player):
        return (
            f"⚔️ *{player.name}'s Duel Record*\n\n"
            f"🏆 Wins:   {getattr(player,'pvp_wins',0)}\n"
            f"💀 Losses: {getattr(player,'pvp_losses',0)}"
        )



    # ── Bestiary ──────────────────────────────────────────────
    @staticmethod
    def bestiary_list(query, matches):
        """
        Shows search results — greys out partial matches.
        matches = list of (monster_name, is_exact_match)
        """
        if not matches:
            return f"📖 *Bestiary*\n\n_No entries matching '{query}'._"
        lines = [f"📖 *Bestiary — '{query}'*\n"]
        for i, (name, exact) in enumerate(matches, 1):
            # Highlight the query in the name
            display = name.replace(query.title(), f"*{query.title()}*") if not exact else f"*{name}*"
            lines.append(f"{i}. {display}")
        lines.append("\n_.bestiary [exact name] for full entry_")
        return "\n".join(lines)

    @staticmethod
    def bestiary_entry(monster_name, m_data, img=""):
        """Full grimoire entry for one monster."""
        skills = ", ".join(s["name"] for s in m_data.get("skills", []))
        body   = (
            f"📖 *{monster_name}*\n"
            f"_{m_data.get('type','?')} · Difficulty: {m_data.get('difficulty','?')}_\n\n"
            f"♥ Base HP: {m_data.get('base_hp','?')}\n"
            f"⚔️ Base ATK: {m_data.get('base_atk','?')}\n"
            f"💨 Speed: {m_data.get('base_spd','?')}\n\n"
            f"_Skills: {skills}_"
        )
        if img:
            return f"__IMG__{img}__CAP__{body}"
        return body

    # ── Misc ──────────────────────────────────────────────────
    @staticmethod
    def not_dead():
        return "_You're not dead. No need to revive._"

    @staticmethod
    def not_started():
        return "_You haven't awakened yet. Type *.start* to begin._"

    @staticmethod
    def unknown_cmd(cmd):
        return f"_Unknown command: *{cmd}*_\n\nType *.menu* to see all commands."


    @staticmethod
    def zone_caution(zone_name, zone_min, player_level):
        return f"⚠️ *{zone_name}* requires Lv.{zone_min}. You are Lv.{player_level}. Proceed with caution."
	
