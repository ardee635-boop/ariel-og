# ============================================================
# NIFLHEIM — router/handle.py
# Main message dispatch — handle()
# ============================================================

import random, re, sys
from interfaces import UI
from combat_session import STATE_ARENA_PENDING, STATE_GYM_PENDING
from dungeon_session import DungeonSession
from ._constants import (
    STATE_IDLE, STATE_EXPLORING, STATE_ENCOUNTER, STATE_BATTLE,
    STATE_DEAD, STATE_PVP, STATE_RAID, STATE_ARENA, STATE_GYM,
    ADMIN_SENDER, DIRECTIONS, DODGE_WORDS,
    TutorialManager,
    victory_level_up, active_quests_ui, quest_card_ui,
    quest_offer_ui, get_mira_quest_offer, is_mira_quest_request,
    LOCATION_NPC_MAP, NPC_DECLINE_LINES, board_ui,
    generate_board, get_premade_quest, should_offer_quest,
    generate_ai_quest, validate_report, register_quest_spawn,
    clear_quest_spawn, can_access_rank, check_rank_up,
    RANK_ORDER, RANK_LEVEL, RANK_TITLES, RANK_BADGE,
    RANK_UP_AT, MAX_QUESTS, _M, MonsterLibrary,
)
# Ariel imports cleared — rebuilding from scratch in ariel.py

_MISSING_GROUP = object()


class HandleMixin:

    BATTLE_SAFE_CMDS = {
        ".status", ".card", ".cardv", ".setage", ".setbio", ".skills", ".skill",
        ".moves", ".move", ".inv", ".inventory", ".party", ".quests", ".quest",
        ".board", ".redeem", ".accept", ".rankup", ".talk", ".arena", ".gym", ".next",
        ".quest", ".hud", ".cds", ".bal", ".pokedex", ".heal", ".me",
        ".buy", ".sell", ".info", ".ffp", ".ffd", ".ffi", ".ff",
    }

    # Commands that always work regardless of battle/encounter state
    GLOBAL_CMDS = {
        ".resetprofile", ".reset",
        ".quicktravel", ".ranks", ".whois", ".rules", ".gyms",
        ".warnings", ".location", ".heal", ".shop",
        ".buy", ".sell", ".font",
    }

    DIRECTIVE_COOLDOWN_SECONDS = 1800  # 30 min, per directive

    # Commands classified into the Normal pool (utility, admin, quest/lord,
    # menus) — see .chat/.normal/.silent design notes. Kept as one set so
    # both the Pokémon-gate exemption and the Normal gate itself agree on
    # exactly what "Normal" covers.
    NORMAL_CMDS = {
        ".ping", ".uptime", ".stats", ".owner", ".groupid",
        ".ranks", ".whois", ".rules", ".gyms", ".warnings", ".font",
        ".home", ".tp", ".player", ".setstage", ".tagall", ".hidetag",
        ".addlegacy", ".legacylist", ".legacy", ".resetplayers", ".delete",
        ".ff", ".ffp",
        ".board", ".redeem", ".rankup", ".quest", ".quests", ".task", ".tasks",
        ".models", ".model", ".llmtest", ".nvtest",   # King-only LLM model switching (rpg_cmds/models.py)
    }

    # Every literal Pokémon/gameplay command actually dispatched below —
    # pulled from every `cmd == '.x'` / `cmd in (...)` site in this file
    # plus the state-scoped command sets (DUNGEON_CMDS, ARENA_ALLOWED).
    # Used ONLY to distinguish "a real command the player needs to
    # register for" from "a typo/unknown word" at the registration gate
    # — NOT a dispatch table itself, so a command missing here just
    # means an unregistered player's typo of it gets silently ignored
    # instead of a not_started() prompt (harmless either way).
    POKEMON_CMDS = {
        ".accept", ".advance", ".ambush", ".arena", ".bal", ".betmenu",
        ".board", ".buy", ".card", ".cardv", ".catch", ".cf", ".challenge",
        ".db", ".decline", ".di", ".dig", ".dive", ".end",
        ".explore", ".ff", ".ffd", ".ffi", ".ffp", ".fight", ".fish",
        ".flee", ".font", ".forfeit", ".giveup", ".goback", ".goto", ".gym",
        ".gyms", ".hatch", ".heal", ".hud", ".hunt", ".info", ".inv",
        ".inventory", ".lb", ".leave", ".location", ".look",
        ".me", ".mine", ".name", ".next", ".no", ".party", ".pheal",
        ".pbattle", ".moves", ".move", ".pokedex", ".quest", ".quests", ".quicktravel", ".rankup",
        ".redeem", ".reject", ".reset", ".roulette", ".sell", ".setage",
        ".setbio", ".setskill", ".shop", ".skill", ".skills", ".skip",
        ".slots", ".start", ".status", ".stop",
        ".swap", ".switch", ".talk", ".trap", ".tutorial",
        ".unsetskill", ".yes", ".zone",
        # DUNGEON_CMDS (defined further down, mirrored here)
        ".dive", ".look", ".hunt", ".mine", ".dig", ".fish",
        ".ambush", ".trap", ".advance", ".goback", ".forfeit",
        ".goto", ".stop",
        # ARENA_ALLOWED (defined further down, mirrored here)
        ".next", ".atk", ".run", ".catch", ".use", ".med",
        ".inv", ".party", ".status", ".card", ".bag",
    }

    # Union used at the registration gate — anything not in here is
    # treated as unrecognized text and silently ignored for
    # unregistered players, rather than prompting them to register
    # for a command that doesn't exist.
    KNOWN_CMDS = NORMAL_CMDS | POKEMON_CMDS | BATTLE_SAFE_CMDS | GLOBAL_CMDS

    def handle(self, sender, text, mentioned_jid=None, quoted_text=None,
               pool_pokemon=False, pool_amongus=False, pool_normal=False, pool_rpg=False,
               pool_chat=False, group_jid=_MISSING_GROUP, is_group=None,
               received_at_ms=None, message_key=None, pool_niflheim=False):
        self.chat.record_names(sender)

        # ── Owner-only bulk commands (.legacy / .resetplayers) ──────────
        # Intercepted FIRST so no pool gate (Normal/Pokemon/RPG), DM-vs-group
        # difference, registration check or stage can silently swallow them.
        # Allowed for the King or the admin number.
        _owner_cmd = (text or "").strip().split(" ")[0].lower()
        if _owner_cmd in (".legacy", ".resetplayers"):
            from permissions import is_king
            if sender == ADMIN_SENDER or is_king(sender):
                try:
                    _args = (text or "").strip().split()[1:]
                    return self._handle_admin(sender, None, _owner_cmd, _args, text, mentioned_jid)
                except Exception as _e:
                    print(f"[ADMIN] {_owner_cmd} failed: {_e!r}", file=sys.stderr, flush=True)
                    return f"⚠️ {_owner_cmd} failed: {_e}"
            print(f"[ADMIN] {_owner_cmd} ignored: {sender} is not King/admin", file=sys.stderr, flush=True)
            return None

        # ── Among Us mode gate — fully isolated, checked before ANYTHING
        # else (Ariel calls, directives, Pokémon registration, stage
        # machine). If not handled here, falls through unchanged. ──
        from .amongus import NOT_HANDLED
        _au_group_jid = (
            getattr(self, "_last_group_jid", None)
            if group_jid is _MISSING_GROUP
            else group_jid
        )
        if is_group is None:
            is_group = bool(
                isinstance(_au_group_jid, str) and _au_group_jid.endswith("@g.us")
            )
        _au_session_group_jid = _au_group_jid if is_group else None
        _au_group_intercept = (
            is_group
            and self.amongus.should_intercept_group(
                sender,
                text,
                _au_session_group_jid,
            )
        )
        if (
            pool_amongus
            or _au_group_intercept
            or (not is_group and self.amongus.has_player(sender))
            or (not is_group and (text or "").strip().lower() == ".amenu")
            or (not is_group and (text or "").strip().lower() in (".dm", ".gc"))
        ):
            _au_result = self.amongus.pre_dispatch(
                sender,
                text,
                _au_session_group_jid,
                received_at_ms,
                quoted_text=quoted_text,
                message_key=message_key,
            )
            if _au_result is not NOT_HANDLED:
                return _au_result
        # If pool_amongus is False, Among Us is completely skipped —
        # its commands fall through to the rest of handle() same as
        # any unrecognized text, same as if Among Us didn't exist for
        # this group. This is Layer 1 (pool toggle) for Among Us.

        # ── Ariel RPG mode gate — same shape as Among Us above: a
        # per-group pool_rpg flag (King-only to toggle, via .rpg
        # on/.rpg off — see index.js's pool-toggle block), persisted
        # the same DB-backed way as the other pools so it survives a
        # restart. Individual senders inside an RPG-on group still
        # play through their own per-sender session/character state;
        # the pool flag only gates whether the group has RPG turned
        # on at all. Checked next, still before Pokémon dispatch, so
        # .status/.skills can be intercepted for RPG-mode senders
        # before the Pokémon versions of those commands ever run. ──
        from .rpg import NOT_HANDLED as RPG_NOT_HANDLED
        _rpg_result = self.rpg.pre_dispatch(sender, text, quoted_text=quoted_text,
                                             group_jid=_au_group_jid, pool_rpg=pool_rpg)
        if _rpg_result is not RPG_NOT_HANDLED:
            return _rpg_result

        # ── Niflheim gate — sits before the Pokémon pool gate (like Among
        # Us and RPG above) so Niflheim commands are never swallowed by it.
        # Inert while pool_niflheim is off. ──
        from .niflheim import NOT_HANDLED as NIF_NOT_HANDLED
        _nif_result = self.niflheim.pre_dispatch(sender, text, pool_niflheim=pool_niflheim,
                                                 is_group=is_group,
                                                 is_admin=(sender == ADMIN_SENDER),
                                                 group_jid=(_au_session_group_jid),
                                                 mentioned_jid=mentioned_jid)
        if _nif_result is not NIF_NOT_HANDLED:
            return _nif_result

        # ── Pokémon pool gate (Layer 1) ───────────────────────────
        # If the Pokémon pool is off for this group, Pokémon commands
        # are silently ignored — mirrors Among Us's approach above.
        # NOTE: this blanket-blocks nearly all Python-routed commands,
        # not just Pokémon ones — a known pre-existing quirk, left as
        # is. The one addition here: when pool_normal is ON, Normal
        # commands are exempted from THIS gate too, so ".normal on"
        # reliably works on its own without also needing ".pokemon on"
        # — otherwise .menu/admin/quest commands would silently die
        # here before ever reaching the Normal gate below.
        if not pool_pokemon:
            _cmd_only = text.strip().split(" ")[0].lower() if text.strip() else ""
            _pokemon_exempt = {".groupid"}
            # Admin commands must always be reachable regardless of
            # this group's pool state — otherwise .home/.tp/.player
            # get silently swallowed here before _handle_admin ever
            # runs, with zero reply and zero error to go on.
            if sender == ADMIN_SENDER:
                _pokemon_exempt = _pokemon_exempt | {".home", ".tp", ".player"}
            if pool_normal:
                _pokemon_exempt = _pokemon_exempt | self.NORMAL_CMDS
            if _cmd_only.startswith(".") and _cmd_only not in _pokemon_exempt:
                return None

        # ── Normal pool gate + .groupid (router/normal.py) ──────────
        from .normal import NOT_HANDLED as NORMAL_NOT_HANDLED
        _normal_result = self.normal.pre_dispatch(sender, text, pool_normal=pool_normal)
        if _normal_result is not NORMAL_NOT_HANDLED:
            return _normal_result

        # ── Ariel trigger (router/chat.py) ──────────────────────────
        from .chat import NOT_HANDLED as CHAT_NOT_HANDLED
        _chat_result = self.chat.pre_dispatch(sender, text, mentioned_jid=mentioned_jid,
                                              pool_chat=pool_chat)
        if _chat_result is not CHAT_NOT_HANDLED:
            return _chat_result

        # ── Everything else is Pokémon-pool logic (router/pokemon.py) ──
        return self._handle_pokemon(sender, text, mentioned_jid=mentioned_jid)
