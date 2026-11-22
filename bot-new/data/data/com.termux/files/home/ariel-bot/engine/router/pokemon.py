# ============================================================
# NIFLHEIM — router/pokemon.py
# Pokémon pool: registration gate, state machine, every Pokémon/
# gameplay command. Cut out of handle() (RESTRUCTURE.md §3.5) with no
# logic changes: same code, same `self`, now reached via
# handle() -> self._handle_pokemon(...).
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



class PokemonMixin:

    def _handle_pokemon(self, sender, text, mentioned_jid=None):
        text = self._normalize(text)
        if not text: return None
        print(f"[HANDLE] sender={sender} text={text}", file=sys.stderr, flush=True)

        parts = text.split()
        cmd   = parts[0].lower()
        args  = parts[1:]

        if cmd == ".start":
            push_name = getattr(self, "_last_push_name", None)
            return self._start(sender, push_name=push_name)

        try:
            if sender not in self.reg:
                db_reg = self.db.load_reg(sender)
                if db_reg: self.reg[sender] = db_reg
        except Exception as e:
            print(f"[ROUTER] load_reg failed: {e}", file=sys.stderr, flush=True)

        if cmd == ".resetprofile":
            self.db.delete(sender)
            self.cache.pop(sender, None)
            self.sessions.pop(sender, None)
            self.reg.pop(sender, None)
            return (
                "🗑️ *Profile fully wiped.*\n"
                "_Character, registration, NPC/Ariel affinity, quest claims, "
                "and site login all cleared. Legacy status and rank preserved._\n\n"
                "_Type *.start* to begin anew._"
            )

        # Stale mid-registration entries can no longer exist going forward
        # (.start now only ever links to the site — see registration.py),
        # but a leftover row from before this change shouldn't crash the
        # router. Clear it out and continue as normal.
        if sender in self.reg:
            self.reg.pop(sender, None)
            self.db.delete_reg(sender)

        player = self._get(sender)
        if not player:
            # Only prompt registration for a command that actually exists —
            # a typo or unrecognized word (e.g. ".tact") is silently
            # ignored instead of telling the player to log in for a
            # command that was never real. See KNOWN_CMDS above.
            if text.startswith(".") and cmd in self.KNOWN_CMDS:
                return UI.not_started()
            return None

        # ── .explore journey tick catch-up — WhatsApp has no live
        # connection, so pending ticks (encounter/item rolls, arrival)
        # are caught up passively on the player's next message rather
        # than pushed by a background timer. Runs before the state
        # machine below so an in-progress journey can still surface an
        # arrival/encounter even if the player's actual command is
        # unrelated. .explore/.end/.zone themselves are dispatched
        # further down and handle their own tick logic explicitly.
        # Dungeon commands are excluded the same way — a dungeon run
        # is its own locked-in session (see dungeon_session.py) and
        # shouldn't be interrupted by an unrelated overworld journey
        # tick, nor should entering a dungeon interrupt an overworld
        # journey that was already in progress.
        DUNGEON_CMDS = {
            ".dive", ".look", ".hunt", ".mine", ".dig", ".fish",
            ".ambush", ".trap", ".advance", ".goback", ".forfeit",
            ".goto", ".stop",
        }
        if cmd not in (".explore", ".end", ".zone") and cmd not in DUNGEON_CMDS:
            from .explore import handle_journey_tick
            _tick_msg = handle_journey_tick(sender, player, self.db, lambda: self._save(sender, player), router=self)
            if _tick_msg:
                return _tick_msg

        session = self._session(sender)
        stage   = session.state
        if cmd in (".moves", ".move"):
            return self._handle_moves(player, args)
        if cmd == ".forfeit":
            cmd = ".flee"   # one command; handled below for every state
        import sys as _sys
        if cmd in (".fight", ".catch", ".flee"):
            print(f"[BATTLE DISPATCH DEBUG] sender={sender} cmd={cmd} stage={stage} "
                  f"encounter_monster={getattr(session, 'encounter_monster', None)}",
                  file=_sys.stderr, flush=True)

        # ── Arena state — only battle cmds + .next allowed ──
        ARENA_ALLOWED = {
            ".next",".atk",".run",".catch",".use",".med",
            ".inv",".party",".status",".card",".bag",
            ".ff",".ffp",
            ".reset",".resetprofile",
        }
        if stage in (STATE_ARENA, STATE_ARENA_PENDING) and cmd and cmd.startswith(".") and cmd not in ARENA_ALLOWED:
            return None
        if stage in (STATE_GYM, STATE_GYM_PENDING) and cmd and cmd.startswith(".") and cmd not in ARENA_ALLOWED:
            return None

        # ── Static state — train switch, highest priority ─
        static = getattr(player, "static_state", None)
        if static:
            _lab_passthrough = {".yes", ".no", ".skip", ".next", ".name",
                                  ".buy", ".sell", ".shop", ".inv", ".inventory",
                                  ".bal", ".status", ".card", ".party"}
            is_dash_cmd = (
                text.startswith(".") and
                not text.strip().lstrip("-")[:1].isdigit() and
                text.split()[0].lower() not in _lab_passthrough
            )
            if not is_dash_cmd:
                if static == "oak_mart":
                    player.static_state = None
                    self._save(sender, player)
                return None  # unknown static state — silent ignore

        if stage == STATE_DEAD:
            if cmd in (".status", ".card"): return player.card_text()
            return "_All your Pokémon have fainted. Visit a Pokémon Center to heal up._"

        if stage == "pve_swap":
            monster = getattr(session, "encounter_monster", None)
            if cmd == ".swap":
                if not args or not args[0].isdigit():
                    return "_Usage: .swap (party no.)_"
                idx  = int(args[0]) - 1
                if idx < 0 or idx >= len(player.party):
                    return "⚠️ _Invalid slot._"
                poke = player.party[idx]
                if poke.is_fainted():
                    return f"_{poke.nickname} cannot be summoned right now_"
                player.set_active(idx)
                session.state = "battle_menu" if monster else STATE_EXPLORING
                self._save(sender, player)
                from encounters import battle_screen
                msg = f"Go, *{poke.nickname}*!"
                if monster:
                    return msg + "\n\n" + battle_screen(poke, monster)
                return msg
            if cmd in (".flee", "flee", ".forfeit"):
                session.clear_encounter()
                session.transition(STATE_EXPLORING)
                self._save(sender, player)
                from .explore import handle_journey_resume
                _resume = handle_journey_resume(sender, player, self.db)
                if _resume:
                    return "_You fled the battle!_\n\n" + _resume
                return "_You fled the battle!_"
            if cmd not in self.BATTLE_SAFE_CMDS:
                return "_Choose a Pokémon to send out with .swap (no.), or .flee._"

        if stage == "pvp_blackout": return None

        if sender == ADMIN_SENDER:
            res = self._handle_admin(sender, player, cmd, args, text, mentioned_jid)
            if res is not None: return res

        # ── Lord commands ─────────────────────────────────────
        if cmd in (".ff", ".ffp"):
            res = self._handle_lord(sender, player, cmd, args, text, mentioned_jid)
            if res is not None: return res

        if cmd == ".reset":
            if hasattr(session, "end_battle"):   session.end_battle()
            if hasattr(session, "clear_encounter"): session.clear_encounter()
            if hasattr(session, "clear_arena"): session.clear_arena()
            self.db.set_meta(sender, "arena_round", "")
            self.db.set_meta(sender, "arena_pending", "")
            self.db.set_meta(sender, "gym_round", "")
            self.db.set_meta(sender, "gym_zone", "")
            self.db.set_meta(sender, "gym_used_names", "")
            self.db.set_meta(sender, "active_npc", "")
            session.transition(STATE_IDLE)
            player.current_monster = None
            if hasattr(player, "reset_battle"): player.reset_battle()
            self._save(sender, player)
            return "🔄 _State reset._"

        # .flee and .forfeit are one command: each replaces the other
        # everywhere it is used (PvP, wild/trainer fights, dungeon runs).
        if cmd in (".forfeit", "flee"):
            cmd = ".flee"

        if cmd == ".flee":
            if stage == STATE_RAID: return "⚠️ _You cannot flee a raid._"
            if stage == STATE_PVP:
                return self.handle_pvp_flee(sender, player)
            if stage == STATE_ENCOUNTER:
                # Pre-fight encounter screen — no battle_state exists yet
                # (that's only created once .fight runs on_encounter), so
                # this can't go through BattleEngine.on_command's speed
                # check. This used to call a nonexistent self._flee(),
                # which raised on every encounter-stage .flee. Just back
                # out of the encounter directly and resume the journey,
                # same as a successful BattleEngine flee does.
                monster = getattr(session, "encounter_monster", None)
                name = monster.get("name", "it").title() if monster else "it"
                session.clear_encounter()
                session.transition(STATE_EXPLORING)
                self._save(sender, player)
                from .explore import resume_journey_if_paused
                resume_suffix = resume_journey_if_paused(sender, player, self.db)
                return "You got away safely!\n\nBattle ended." + resume_suffix
            if stage not in ("battle_menu", STATE_BATTLE) \
                    and DungeonSession.load(self.db, sender).is_locked_in():
                # not in a fight, inside a dungeon: leaving = giving up the run
                from .dungeon import handle_forfeit
                return handle_forfeit(sender, player, self.db)
            if stage == STATE_EXPLORING:
                return None  # nothing to flee from
            if stage != "battle_menu" and stage != STATE_BATTLE:
                return None
            # stage == "battle_menu" (or STATE_BATTLE) → fall through to the
            # BattleEngine dispatch below, which runs the real speed-based
            # flee-chance check.

        if stage == "tutorial":
            return TutorialManager.handle(sender, player, text.strip(), self)

        # ── Global commands — always pass through any state ──────
        if cmd in self.GLOBAL_CMDS:
            pass  # fall through to command handlers below
        elif stage in (STATE_ENCOUNTER, "battle_menu"):
            monster = getattr(session, "encounter_monster", None) or getattr(session, "monster", None)
            if not monster:
                session.transition(STATE_EXPLORING); return None

            from battle import BattleEngine
            engine = BattleEngine(self.db, sender)

            # Encounter screen — waiting for .fight or .flee
            if stage == STATE_ENCOUNTER:
                if cmd == ".fight":
                    result = engine.on_encounter(session, player)
                    self._save(sender, player)
                    return self._split_battle_result(sender, result)
                if cmd in self.BATTLE_SAFE_CMDS:
                    pass  # allow status/inv checks during encounter
                else:
                    return "_A wild Pokémon is blocking your path!_\n-fight to engage · .flee to escape"

            # In-battle commands (battle_menu state)
            elif stage == "battle_menu":
                result = engine.on_command(session, player, cmd, args)
                if result is not None:
                    self._save(sender, player)
                    return self._split_battle_result(sender, result)

                if cmd in self.BATTLE_SAFE_CMDS: pass
                else: return None

        if stage == STATE_RAID:
            return "⚠️ _Raids are not yet available._"

        if stage == STATE_PVP:
            if cmd == ".skills":
                poke = player.active_pokemon()
                if not poke: return "_No active Pokémon._"
                from encounters import skills_screen
                return skills_screen(poke)
            if cmd in (".switch", ".swap"):
                if not args:
                    return "_Usage: .switch [name/no]_"
                return self.handle_pvp_switch(sender, player, " ".join(args))
            if cmd == ".giveup":
                return self.handle_pvp_giveup(sender, player)
            if cmd not in self.BATTLE_SAFE_CMDS:
                move_name = cmd.lstrip("-") + (" " + " ".join(args) if args else "")
                return self.handle_pvp_skill(sender, player, move_name.strip())

        if stage == "pvp_pending":
            if cmd == ".accept":
                return self.handle_pvp_accept(sender, player)
            if cmd in (".decline", ".reject"):
                return self.handle_pvp_decline(sender, player)
            if cmd not in self.BATTLE_SAFE_CMDS:
                return None

        if stage == STATE_ARENA and cmd not in (".next", ".arena"):
            from battle import BattleEngine
            engine = BattleEngine(self.db, sender)
            if cmd in self.BATTLE_SAFE_CMDS:
                if session.monster:
                    result = engine.on_command(session, player, cmd, args)
                    if result is not None:
                        self._save(sender, player)
                        return self._split_battle_result(sender, result)
                    return None
                else:
                    pass  # safe cmd, no monster — fall through
            elif session.monster:
                result = engine.on_command(session, player, cmd, args)
                if result is not None:
                    self._save(sender, player)
                    return self._split_battle_result(sender, result)
            return None

        if stage == STATE_GYM and cmd not in (".next", ".gym"):
            from battle import BattleEngine
            engine = BattleEngine(self.db, sender)
            if cmd in self.BATTLE_SAFE_CMDS:
                if session.monster:
                    result = engine.on_command(session, player, cmd, args)
                    if result is not None:
                        self._save(sender, player)
                        return self._split_battle_result(sender, result)
                    return None
                else:
                    pass  # safe cmd, no monster — fall through
            elif session.monster:
                result = engine.on_command(session, player, cmd, args)
                if result is not None:
                    self._save(sender, player)
                    return self._split_battle_result(sender, result)
            return None

        if stage == STATE_EXPLORING:
            if not text.startswith("."): return None

        # ── Movement ──────────────────────────────────────────
        # 1/2/3/4-style grid movement is frozen (not deleted) as of
        # the .explore rework. Dispatch removed here on purpose —
        # _handle_movement() in router/movement.py is left fully
        # intact for a future Discord build. See explore_checklist.md
        # Phase 1.

        # ── NPC routing ───────────────────────────────────────
        if cmd == ".accept":
            if self.db.get_meta(sender, "arena_pending"):
                from arena import arena_enter
                msg = arena_enter(self.db, sender, player, session)
                self._save(sender, player)
                return msg

        if cmd in (".reject", ".decline"):
            if self.db.get_meta(sender, "arena_pending"):
                from arena import arena_reject
                msg = arena_reject(self.db, sender)
                self._save(sender, player)
                return msg

        if stage == STATE_IDLE:
            lower_text = text.lower()
            zone_id    = getattr(player, "zone", "oak_town") or "oak_town"

            if not text.startswith("."):
                return None

        # ══ COMMANDS ══════════════════════════════════════════

        # ── .me — how Ariel sees you ─────────────────────────
        if cmd == ".me":
            tier, score = self.db.affection_tier(sender)
            directives = self.db.directives_list_owner(sender)
            active_directives = [d for d in directives if d["active"]]
            lines = [f"*Ariel's read on you:* {tier} ({score}/100)"]
            if active_directives:
                lines.append("\n_Things I'm watching for you:_")
                for d in active_directives[:5]:
                    who = d.get("target_name") or "someone"
                    lines.append(f"  • {who}: {d['condition']}")
            return "\n".join(lines)

        # ── .arena ────────────────────────────────────────────
        if cmd == ".arena":
            from arena import arena_prompt
            msg = arena_prompt(self.db, sender, player)
            self._save(sender, player)
            return msg

        # ── .gym ──────────────────────────────────────────────
        if cmd == ".gym":
            from gym import gym_enter
            msg = gym_enter(self.db, sender, player, session)
            self._save(sender, player)
            return msg

        # ── .gyms (site link — list of all gyms, open/locked) ──
        if cmd == ".gyms":
            return (
                "🏛️ _View all gyms, requirements, and leaders here:_\n"
                "https://ariel-og.vercel.app/?scene=gyms"
            )

        # ── .next (arena rounds) ──────────────────────────────
        if cmd == ".next":
            send = getattr(self, "_direct_send", None)
            grp  = getattr(self, "_last_group_jid", None)
            if session.state == STATE_ARENA:
                from arena import arena_next
                round_str = self.db.get_meta(sender, "arena_round")
                if not round_str:
                    return None
                msg = arena_next(self.db, sender, player, session, direct_send=send, group_jid=grp)
                self._save(sender, player)
                return msg
            if session.state == STATE_GYM:
                from gym import gym_next
                round_str = self.db.get_meta(sender, "gym_round")
                if not round_str:
                    return None
                msg = gym_next(self.db, sender, player, session, direct_send=send, group_jid=grp)
                self._save(sender, player)
                return msg
            return None

        # FROZEN as of the .explore rework — .minimap dispatch
        # removed. _render_zone_map() itself is untouched and still
        # used elsewhere (e.g. the frozen .dash logic in
        # router/movement.py). See explore_checklist.md Phase 1.

        if cmd == ".heal":
            if stage in (STATE_BATTLE, STATE_ENCOUNTER, "battle_menu"):
                return None  # handled by BattleEngine
            from data_items import HEALING_ITEMS
            # Identify target pokemon
            if args:
                target_q = " ".join(args)
                target = None
                for i, p in enumerate(player.party):
                    if target_q.isdigit() and int(target_q) - 1 == i:
                        target = p; break
                    if p.nickname.lower() == target_q.lower() or p.name.lower() == target_q.lower():
                        target = p; break
                if not target:
                    return f"⚠️ _No Pokémon found for '{target_q}'._"
            else:
                # Default to active/first non-fainted
                target = player.active_pokemon()
                if not target:
                    return "_Your party has no conscious Pokémon._"
            if target.is_fainted():
                return f"_*{target.nickname}* has fainted and can't be healed with items._"
            if target.hp >= target.max_hp:
                return f"_*{target.nickname}* is already at full HP._"
            # Try healing items in priority order
            for item_name in ("Max Potion", "Hyper Potion", "Super Potion", "Potion"):
                if player.has_item(item_name):
                    player.use_item(item_name)
                    info = HEALING_ITEMS.get(item_name, {})
                    if info.get("effect") == "hp_full":
                        healed = target.max_hp - target.hp
                        target.hp = target.max_hp
                    else:
                        healed = target.heal(info.get("value", 20))
                    self._save(sender, player)
                    return f"_Used *{item_name}*! *{target.nickname}* recovered *{healed} HP*. ({target.hp}/{target.max_hp})_"
            return "_You have no healing items._"

        if cmd == ".location":
            from map import get_zone_name, render_minimap
            return (f"📍 *{get_zone_name(player.zone)}* ({player.zone_x}, {player.zone_y})\n\n"
                    f"{render_minimap(player)}")

        if cmd == ".pbattle":
            return self._handle_pbattle(sender, player, session, stage)

        if cmd == ".explore" and not self.EXPLORE_OPEN:
            return "🚧 _Explore is under development. Use .pbattle for wild encounters._"

        if cmd == ".explore":
            from .explore import handle_explore
            group_jid = getattr(self, "_last_group_jid", None)
            return handle_explore(sender, player, args, self.db, lambda: self._save(sender, player), group_jid, self)

        if cmd == ".end":
            from .explore import handle_end
            return handle_end(sender, player, self.db, lambda: self._save(sender, player), self)

        if cmd == ".zone":
            from .explore import handle_zone
            return handle_zone(sender, player, self.db, self)

        # ── Dungeon commands ──────────────────────────────────────
        # See router/dungeon.py and dungeon_session.py. .yes/.no are
        # shared with other flows (lab, quests, etc.), so the dungeon
        # confirm/decline handlers check DungeonSession.at_threshold()
        # themselves and are only reached here if nothing else already
        # claimed the reply — this block sits after those other .yes/
        # .no consumers so it doesn't steal their input.
        #
        # check_goto_arrival is a FALLBACK safety net, not the primary
        # mechanism — .goto's live-push timer (see router/dungeon.py's
        # _arm_goto_step_timer) is what normally delivers each step's
        # result without the player sending anything. This only
        # matters if that timer didn't fire (e.g. a process restart),
        # centralized here once instead of duplicated per-handler.
        _DUNGEON_ARRIVAL_CHECK_CMDS = DUNGEON_CMDS | {".yes", ".no"}
        if cmd in _DUNGEON_ARRIVAL_CHECK_CMDS:
            _dungeon_session_check = DungeonSession.load(self.db, sender)
            if _dungeon_session_check.is_locked_in() and _dungeon_session_check.goto_in_progress():
                from .dungeon import check_goto_arrival
                _arrival_msg = check_goto_arrival(_dungeon_session_check, self.db)
                if _arrival_msg and cmd != ".stop":
                    # .stop has its own explicit handler further down —
                    # let it run normally rather than short-circuiting
                    # here, so the "interrupted" wording is used instead
                    # of the passive-arrival wording.
                    return _arrival_msg

        if cmd == ".dive":
            from .dungeon import handle_dive
            _dungeon_session = DungeonSession.load(self.db, sender)
            if _dungeon_session.is_locked_in():
                return handle_dive(sender, player, self.db, lambda: self._save(sender, player), combat_session=session)
            # not in a dungeon — fall through to overworld .explore handling above,
            # which already returned if it matched; nothing left to do here.

        if cmd == ".yes" and DungeonSession.load(self.db, sender).at_threshold():
            from .dungeon import handle_dungeon_confirm
            return handle_dungeon_confirm(sender, player, self.db)

        if cmd == ".no" and DungeonSession.load(self.db, sender).at_threshold():
            from .dungeon import handle_dungeon_decline
            return handle_dungeon_decline(sender, player, self.db)

        if cmd == ".look":
            _dungeon_session = DungeonSession.load(self.db, sender)
            if _dungeon_session.is_locked_in():
                from .dungeon import handle_look
                return handle_look(sender, player, self.db)

        if cmd == ".hunt":
            _dungeon_session = DungeonSession.load(self.db, sender)
            if _dungeon_session.is_locked_in():
                from .dungeon import handle_hunt
                return handle_hunt(sender, player, self.db)

        if cmd == ".mine":
            _dungeon_session = DungeonSession.load(self.db, sender)
            if _dungeon_session.is_locked_in():
                from .dungeon import handle_mine
                return handle_mine(sender, player, self.db)

        if cmd == ".dig":
            _dungeon_session = DungeonSession.load(self.db, sender)
            if _dungeon_session.is_locked_in():
                from .dungeon import handle_dig
                return handle_dig(sender, player, self.db)

        if cmd == ".fish":
            _dungeon_session = DungeonSession.load(self.db, sender)
            if _dungeon_session.is_locked_in():
                from .dungeon import handle_fish
                return handle_fish(sender, player, self.db)

        if cmd == ".ambush":
            from .dungeon import handle_ambush
            return handle_ambush(sender, player, self.db)

        if cmd == ".trap":
            from .dungeon import handle_trap
            return handle_trap(sender, player, self.db)

        if cmd == ".advance":
            _dungeon_session = DungeonSession.load(self.db, sender)
            if _dungeon_session.is_locked_in():
                from .dungeon import handle_advance
                return handle_advance(sender, player, self.db, args=args)

        if cmd == ".goback":
            from .dungeon import handle_goback
            return handle_goback(sender, player, self.db)

        if cmd == ".goto":
            from .dungeon import handle_goto
            return handle_goto(sender, player, args, self.db, combat_session=session)

        if cmd == ".stop":
            _dungeon_session = DungeonSession.load(self.db, sender)
            if _dungeon_session.is_locked_in() and _dungeon_session.goto_in_progress():
                from .dungeon import handle_stop
                return handle_stop(sender, player, self.db)
            # not mid-journey — fall through; .stop isn't claimed by
            # anything else currently, so this just no-ops elsewhere.

        # .forfeit is handled earlier alongside PvP .forfeit — see the
        # dungeon-aware check near STATE_PVP handling above.

        if cmd == ".shop":
            return self._handle_shop_cmd(sender, player)

        if cmd == ".buy":
            from .shop import handle_buy
            from egg import ALL_EGGS, start_incubation
            result = handle_buy(sender, player, args, lambda: self._save(sender, player))
            # Auto-start incubation if an egg was purchased
            if result and result.startswith("✅"):
                from data_items import get_shop_with_prices
                from .shop import _shop_context
                try:
                    context = _shop_context(player)
                    items   = get_shop_with_prices(context)
                    if args and args[0].isdigit():
                        idx = int(args[0]) - 1
                        if 0 <= idx < len(items):
                            item_name = items[idx]["name"]
                            if item_name in ALL_EGGS:
                                start_incubation(sender, item_name, self)
                except Exception:
                    pass
            return result

        if cmd == ".sell":
            from .shop import handle_sell
            return handle_sell(sender, player, args, lambda: self._save(sender, player))

        if cmd in (".inv", ".inventory"):
            if args:
                from .shop import handle_inv_detail
                return handle_inv_detail(player, args)
            return UI.inventory(player)

        if cmd == ".hatch":
            from egg import resolve_hatch
            return resolve_hatch(sender, self)

        if cmd in (".status", ".card"): return player.card_text()
        if cmd == ".pokedex": return player.pokedex_text()

        if cmd == ".bal":     return UI.balance(player)


        if cmd == ".betmenu":
            from .gamble import betmenu
            return betmenu()

        if cmd == ".cf":
            from .gamble import handle_coinflip
            return handle_coinflip(sender, player, args, lambda: self._save(sender, player))

        if cmd == ".db":
            from .gamble import handle_dice_bet
            return handle_dice_bet(sender, player, args, lambda: self._save(sender, player))

        if cmd == ".di":
            from .gamble import handle_die_guess
            return handle_die_guess(sender, player, args, lambda: self._save(sender, player))

        if cmd == ".slots":
            from .gamble import handle_slots
            return handle_slots(sender, player, args, lambda: self._save(sender, player))

        if cmd == ".roulette":
            from .gamble import handle_roulette
            return handle_roulette(sender, player, args, lambda: self._save(sender, player))


        if cmd == ".setage":
            if not args:
                return "_Usage: .setage [value]_"
            player.age = " ".join(args)
            self._save(sender, player)
            return f"✅ _Age set to_ *{player.age}*"

        if cmd == ".setbio":
            if not args:
                return "_Usage: .setbio [text]_"
            player.bio = " ".join(args)
            self._save(sender, player)
            return f"✅ _Bio updated._"

        if cmd in (".skills", ".skill"):
            return self._handle_skills(sender, player, args)

        if cmd == ".cardv":
            themes = {1: "Normal", 2: "Glitch", 3: "Metallic", 4: "Flame"}
            if not args:
                lines = ["🎴 *Card Designs*", ""]
                for n, label in themes.items():
                    marker = " ✅" if n == player.card_theme else ""
                    lines.append(f"{n}. {label}{marker}")
                lines.append("")
                lines.append("_.cardv [no.] to switch_")
                return "\n".join(lines)
            if not args[0].isdigit() or int(args[0]) not in themes:
                return "⚠️ _Invalid design number. Use .cardv to see options._"
            player.card_theme = int(args[0])
            self._save(sender, player)
            return f"✅ _Card design set to_ *{themes[player.card_theme]}*"

        if cmd == ".info":
            return self._handle_info(sender, player, args)

        if cmd in (".quests", ".quest", ".board", ".redeem", ".accept", ".rankup"):
            return self._handle_quests(sender, player, cmd, args, text)

        if cmd == ".party":
            if not player.party:
                return "🎒 _Your party is empty. Get a starter from Prof. Oak._"
            # .party [no.] → full detail (unchanged, text)
            if args and args[0].isdigit():
                idx = int(args[0]) - 1
                if idx < 0 or idx >= len(player.party):
                    return "⚠️ _Invalid slot._"
                return player.party[idx].summary()
            # .party → rendered image card + full text roster as caption
            lines = ["🎒 *Your Party*", ""]
            for i, p in enumerate(player.party):
                hp_bar = "💀" if p.is_fainted() else f"{p.hp}/{p.max_hp} HP"
                lines.append(f"  *{i+1}.* {p.nickname}  Lv.{p.level}  —  {hp_bar}")
            lines.append("")
            lines.append("_.party [no.] for full info_")
            caption = "\n".join(lines)
            try:
                import os
                from party_render import render as render_party_card
                mons = [{
                    "name":    p.nickname,
                    "level":   p.level,
                    "types":   p.types,
                    "hp":      p.hp,
                    "max_hp":  p.max_hp,
                    "status":  getattr(p, "status", None),
                    "sprite":  getattr(p, "sprite", ""),
                } for p in player.party]
                safe_sender = "".join(c for c in sender if c.isalnum())
                out_path = os.path.join("/tmp", f"party_{safe_sender}.png")
                render_party_card(mons, getattr(player, "name", "") or "Trainer", out_path)
                return f"__IMG__{out_path}__CAP__{caption}"
            except Exception as e:
                print(f"[PARTY_RENDER] failed: {e}", file=sys.stderr, flush=True)
                # Fallback to text-only list if rendering fails for any reason
                return caption
                return "\n".join(lines)

        if cmd == ".lb":
            return self._leaderboard_text(args)

        if cmd == ".pheal":
            from world_registry import get_zone
            zone = get_zone(getattr(player, "zone", ""))
            if zone.get("zone_type") != "town":
                return "_You need to be in a town to do that._"
            if not player.party:
                return "🎒 _Your party is empty._"

            healed = 0
            for mon in player.party:
                if hasattr(mon, "heal_full"):
                    mon.heal_full()
                    healed += 1

            import time as _time
            session = self._session(sender)
            if session.state == STATE_DEAD:
                session.transition(STATE_EXPLORING)

            self.db.set_meta(sender, "pc_healing", str(_time.time() + 3))
            self._save(sender, player)

            self._queue_message(sender,
                "🏥 *Pokémon Center*\n"
                "━━━━━━━━━━━━━━━━\n"
                "_Welcome to the Pokémon Care Center.\n"
                "Please wait while we heal your Pokémon..._",
                delay=0
            )

            heal_msg = (
                f"✅ _All {healed} of your Pokémon have been healed to full health!_\n"
                "_You're free to go._"
            ) if healed else "✨ _Your Pokémon are already at full health!_\n_You're free to go._"

            self._queue_message(sender, f"🏥 *Pokémon Care Center*\n━━━━━━━━━━━━━━━━\n{heal_msg}", delay=3)
            return None

        if cmd == ".switch":
            if stage in (STATE_BATTLE, STATE_ARENA, STATE_ARENA_PENDING, STATE_GYM, STATE_GYM_PENDING, STATE_PVP, STATE_RAID, "battle_menu", STATE_ENCOUNTER):
                return "_You can't access the PC mid-battle._"

            if len(args) < 2:
                return (
                    "_Usage:_\n"
                    "_.switch p[slot] p[slot] — swap two party slots_\n"
                    "_.switch p[slot] pc — move a party mon to the PC_\n"
                    "_.switch p[slot] pc[slot] — swap a party mon with a PC mon_"
                )

            def _parse_slot(tok: str):
                """Returns ('p'|'pc', index) or None if unparseable.
                'pc' with no number means 'first open PC slot' (append).
                A bare digit (old syntax, e.g. '.switch 1 3') is treated
                as a party slot for backward compatibility."""
                tok = tok.lower()
                if tok == "pc":
                    return ("pc", None)
                if tok.startswith("pc") and tok[2:].isdigit():
                    return ("pc", int(tok[2:]) - 1)
                if tok.startswith("p") and tok[1:].isdigit():
                    return ("p", int(tok[1:]) - 1)
                if tok.isdigit():
                    return ("p", int(tok) - 1)
                return None

            a_loc, a_idx = _parse_slot(args[0]) or (None, None)
            b_loc, b_idx = _parse_slot(args[1]) or (None, None)

            if a_loc is None or b_loc is None:
                return "_Usage: .switch p[slot] p[slot] | .switch p[slot] pc | .switch p[slot] pc[slot]_"

            # Both p<->p: original party-slot swap, unchanged.
            if a_loc == "p" and b_loc == "p":
                if not (0 <= a_idx < len(player.party)) or not (0 <= b_idx < len(player.party)):
                    return "⚠️ _Invalid slot number._"
                if a_idx == b_idx:
                    return "⚠️ _That's the same slot._"
                player.party[a_idx], player.party[b_idx] = player.party[b_idx], player.party[a_idx]
                self._save(sender, player)
                na, nb = player.party[a_idx].nickname, player.party[b_idx].nickname
                return f"✅ Swapped *{na}* (slot {a_idx+1}) and *{nb}* (slot {b_idx+1})."

            # Normalize so the party slot is always "a" — .switch pc1 p2 works too.
            if a_loc == "pc" and b_loc == "p":
                a_loc, a_idx, b_loc, b_idx = b_loc, b_idx, a_loc, a_idx

            if a_loc != "p" or b_loc != "pc":
                return "_Usage: .switch p[slot] p[slot] | .switch p[slot] pc | .switch p[slot] pc[slot]_"

            if not (0 <= a_idx < len(player.party)):
                return "⚠️ _Invalid party slot number._"
            if len(player.party) <= 1 and b_idx is None:
                return "⚠️ _You can't PC your last Pokémon — you need at least one in your party._"

            mover = player.party[a_idx]

            if b_idx is None:
                # .switch p[slot] pc — move to PC, no swap-back.
                if len(player.party) <= 1:
                    return "⚠️ _You can't PC your last Pokémon._"
                player.party.pop(a_idx)
                player.box.append(mover)
                self._save(sender, player)
                return f"✅ *{mover.nickname}* moved to the PC. (Party {len(player.party)}/6, PC {len(player.box)})"

            # .switch p[slot] pc[slot] — swap with a specific PC mon.
            if not (0 <= b_idx < len(player.box)):
                return f"⚠️ _No Pokémon in PC slot {b_idx+1}._"
            incoming = player.box[b_idx]
            player.party[a_idx], player.box[b_idx] = incoming, mover
            self._save(sender, player)
            return f"✅ Swapped *{mover.nickname}* (party {a_idx+1}) with *{incoming.nickname}* (PC {b_idx+1})."

        if cmd == ".leave":
            if getattr(player, "zone", "") == "lab":
                player.zone   = "oak_town"
                player.zone_x = 20
                player.zone_y = 12
                self._save(sender, player)
                return "📍 _Back in Oak Town._"
            player.location = "square"
            self._save(sender, player)
            return UI.town_square(player) if hasattr(UI, "town_square") else "📍 _Oak Town._"

        if cmd == ".hud":
            if not args or args[0] not in ("1", "2", "3"):
                return "🎨 *HUD Styles*\n\n*.hud 1* — Full\n*.hud 2* — Header\n*.hud 3* — Plain"
            player.hud_style = int(args[0])
            self._save(sender, player)
            return f"✅ HUD style *{args[0]}*."

        if cmd == ".font":
            from interfaces import RPGFont
            if not args or args[0] not in ("0", "1", "2", "3", "4"):
                return RPGFont.show_fonts()
            msg = RPGFont.set_preset(player, args[0])
            self._save(sender, player)
            return msg

        if cmd == ".tutorial":
            player.stage = "tutorial"; player.tutorial_phase = 0; player.tutorial_done = False
            self._save(sender, player)
            from tutorial import phase_awakening
            return phase_awakening(player)

        # ── Setskill flow ─────────────────────────────────────
        if getattr(player, "story_stage", None) == "setskill":
            return self._handle_setskill_flow(sender, player, text.strip())

        # ── Caught Pokémon naming ─────────────────────────────
        if getattr(player, "story_stage", None) == "caught_naming":
            return self._handle_caught_naming(sender, player, cmd, text, args)

        if cmd == ".name":
            # Standalone: .name p1 [nickname]  or  .name pc1 [nickname]
            if getattr(player, "story_stage", None) != "caught_naming":
                if not args:
                    return "_Usage: .name p[slot] [nickname]  or  .name pc[slot] [nickname]_"
                slot_arg = args[0].lower()
                nick = " ".join(args[1:]).strip() if len(args) > 1 else ""
                if nick.startswith("[") and nick.endswith("]"):
                    nick = nick[1:-1].strip()
                in_box = slot_arg.startswith("pc")
                num_str = slot_arg[2:] if in_box else slot_arg[1:]
                if not num_str.isdigit():
                    return "_Usage: .name p[slot] [nickname]  or  .name pc[slot] [nickname]_"
                idx = int(num_str) - 1
                pool = player.box if in_box else player.party
                loc  = "PC" if in_box else "party"
                if idx < 0 or idx >= len(pool):
                    return f"⚠️ _No Pokémon in {loc} slot {int(num_str)}._"
                target = pool[idx]
                if not nick:
                    return f"_Current name: *{target.nickname}*. Usage: .name {slot_arg} [nickname]_"
                if len(nick) > 16:
                    return "_Nickname must be 16 characters or less._"
                old_nick = target.nickname
                target.nickname = nick.capitalize()
                self._save(sender, player)
                return f"✅ *{old_nick}* renamed to *{target.nickname}*."

        if cmd == ".setskill":
            if stage in (STATE_BATTLE, STATE_ENCOUNTER):
                return "_You cannot set skill nicknames during battle._"
            raw_arg = " ".join(args).strip().lower()
            # .setskill → show menu
            if not raw_arg:
                return (
                    "⚙️ *Skill Nicknames*\n\n"
                    "_.setskill [pokemon]_ — assign a nickname to a skill\n"
                    "_.setskill list_ — view all your skill nicknames\n"
                    "_.unsetskill [pokemon]_ — remove a nickname"
                )
            # .setskill list
            if raw_arg == "list":
                return self._setskill_list(player)
            # .setskill [pokemon] — start flow
            return self._setskill_start(sender, player, raw_arg, removing=False)

        if cmd == ".unsetskill":
            if stage in (STATE_BATTLE, STATE_ENCOUNTER):
                return "_You cannot do this during battle._"
            raw_arg = " ".join(args).strip().lower()
            if not raw_arg:
                return "_Usage: .unsetskill [pokemon]_"
            return self._setskill_start(sender, player, raw_arg, removing=True)

        # ── setskill flow state ────────────────────────────────
        if getattr(player, "story_stage", None) == "setskill":
            return self._handle_setskill_flow(sender, player, text.strip())

        if cmd == ".challenge":
            grp_pvp = getattr(self, "_last_group_jid", None)
            return self.handle_challenge(sender, player, mentioned_jid, args=args, group_jid=grp_pvp)

        # ── .dash ─────────────────────────────────────────────
        # FROZEN as of the .explore rework — see explore_checklist.md
        # Phase 1. Logic preserved intact as _handle_dash_FROZEN()
        # in router/movement.py; no longer reachable via command.

        # ── .hunt ─────────────────────────────────────────────
        if cmd == ".hunt":
            import time
            from map import is_safe_zone
            zone_id = getattr(player, "zone", "oak_town")
            if is_safe_zone(zone_id):
                return "_You can't hunt in a town._\n_Use .quicktravel to change location._"
            if stage in (STATE_BATTLE, STATE_ENCOUNTER):
                return "_You're already in a battle._"
            # Cooldown check — 15 seconds
            last_hunt = player.get_flag("last_hunt", 0)
            now = time.time()
            remaining = 15 - (now - last_hunt)
            if remaining > 0:
                return f"_Hunt is on cooldown. ({int(remaining)}s remaining)_"
            # Lower encounter chance than walking — flat 8%
            import random
            from encounters import roll_wild_pokemon, build_wild_monster, encounter_screen
            from pokeapi import get_full
            if random.random() > 0.60:
                player.set_flag("last_hunt", now)
                self._save(sender, player)
                return "_You search the area but find nothing..._"
            result = roll_wild_pokemon(zone_id, "grass")
            if not result:
                player.set_flag("last_hunt", now)
                self._save(sender, player)
                return "_Nothing seems to be around._"
            species, level = result
            api_data = get_full(self.db, species)
            if not api_data:
                player.set_flag("last_hunt", now)
                self._save(sender, player)
                return "_Something stirred but slipped away._"
            monster = build_wild_monster(api_data, level)
            player.see_pokemon(species)
            player.set_flag("last_hunt", now)
            session.set_encounter(monster, None)
            self._save(sender, player)
            return encounter_screen(monster)

        # ── .fish ─────────────────────────────────────────────
        if cmd == ".fish":
            import time
            from map import is_safe_zone, load_zone
            if player.inventory.get("Fishing Rod", 0) < 1:
                return "_You don't have a Fishing Rod._\n_Grab one from the shop first._"
            zone_id = getattr(player, "zone", "oak_town")
            if is_safe_zone(zone_id):
                return "_You can't fish in a town._\n_Use .quicktravel to change location._"
            if stage in (STATE_BATTLE, STATE_ENCOUNTER):
                return "_You're already in a battle._"
            # Must be standing next to water (WW tile) to fish
            zone = load_zone(zone_id)
            grid = zone.get("grid", [])
            px, py = getattr(player, "zone_x", 0), getattr(player, "zone_y", 0)
            adjacent = [(px, py - 1), (px, py + 1), (px - 1, py), (px + 1, py)]
            near_water = False
            for ax, ay in adjacent:
                if 0 <= ay < len(grid) and 0 <= ax < len(grid[ay]):
                    if grid[ay][ax] == "WW":
                        near_water = True
                        break
            if not near_water:
                return "_There's no water nearby to fish in._"
            # Cooldown check — 15 seconds, shares hunt's rhythm
            last_fish = player.get_flag("last_fish", 0)
            now = time.time()
            remaining = 15 - (now - last_fish)
            if remaining > 0:
                return f"_Fishing is on cooldown. ({int(remaining)}s remaining)_"
            import random
            from encounters import roll_wild_pokemon, build_wild_monster, encounter_screen
            from pokeapi import get_full
            if random.random() > 0.60:
                player.set_flag("last_fish", now)
                self._save(sender, player)
                return "_You cast your line but nothing bites..._"
            result = roll_wild_pokemon(zone_id, "water")
            if not result:
                player.set_flag("last_fish", now)
                self._save(sender, player)
                return "_The water is still. Nothing seems to be around._"
            species, level = result
            api_data = get_full(self.db, species)
            if not api_data:
                player.set_flag("last_fish", now)
                self._save(sender, player)
                return "_Something tugged the line and got away._"
            monster = build_wild_monster(api_data, level)
            player.see_pokemon(species)
            player.set_flag("last_fish", now)
            session.set_encounter(monster, None)
            self._save(sender, player)
            return encounter_screen(monster)

        # ── .quicktravel ──────────────────────────────────────
        if cmd == ".quicktravel":
            import time
            from map import load_zone, is_safe_zone
            if stage in (STATE_BATTLE, STATE_ENCOUNTER):
                return "_You can't travel during a battle._"
            # Cooldown check — 60 seconds
            last_qt = player.get_flag("last_quicktravel", 0)
            now = time.time()
            remaining = 60 - (now - last_qt)
            if remaining > 0:
                return f"_Quick Travel is on cooldown. ({int(remaining)}s remaining)_"
            visited = player.get_flag("visited_zones", [])
            current = getattr(player, "zone", "oak_town")
            # Remove current zone from options
            options = [z for z in visited if z != current]
            if not args:
                if not options:
                    return "_You haven't visited any other zones yet._\n_You need to reach an area manually to travel there._"
                lines = ["🗺️ *Quick Travel*", "_Where would you like to go?_", ""]
                for i, z in enumerate(options, 1):
                    zone_data = load_zone(z)
                    name = zone_data.get("name", z.replace("_", " ").title())
                    lines.append(f"  *{i}.* {name}")
                lines.append("")
                lines.append("_.quicktravel [number]_")
                return "\n".join(lines)
            # Handle selection
            sel = " ".join(args)  # rejoin so multi-word names work
            if sel.isdigit():
                idx = int(sel) - 1
                if idx < 0 or idx >= len(options):
                    return "⚠️ _Invalid selection._"
                dest = options[idx]
            else:
                sel_key = sel.lower().replace(" ", "_")
                # Match against zone id or display name, case-insensitive
                dest = None
                for z in options:
                    if z == sel_key:
                        dest = z; break
                if not dest:
                    for z in options:
                        zd = load_zone(z)
                        zname = zd.get("name", z.replace("_", " ")).lower()
                        if zname == sel.lower():
                            dest = z; break
                if not dest:
                    return f"⚠️ _You haven't visited '{sel}'._"
            zone_data = load_zone(dest)
            if not zone_data:
                return "⚠️ _Unknown zone._"
            # Get arrival position from ZONE_SPAWNS first, fallback to exit_positions
            from encounter_tables import ZONE_SPAWNS
            if dest in ZONE_SPAWNS:
                spawn = ZONE_SPAWNS[dest]
            else:
                exit_positions = zone_data.get("exit_positions", {})
                spawn = list(exit_positions.values())[0] if exit_positions else zone_data.get("spawn", (0, 0))
            player.zone   = dest
            player.zone_x = spawn[0]
            player.zone_y = spawn[1]
            player.set_flag("last_quicktravel", now)
            self._save(sender, player)
            zone_name = zone_data.get("name", dest.replace("_", " ").title())
            safe = is_safe_zone(dest)
            arrival = f"⚡ _Travelled to_ *{zone_name}*{'.' if safe else ' — stay alert.'}"
            minimap = self._render_zone_map(sender, player)
            return arrival + "\n\n" + minimap

        return None
    # ══════════════════════════════════════════════════════════
    # SETSKILL SYSTEM
    # Storage: story_flags["skill_nicknames"]
    #   { "species_nickname_key": { "skill_name": ["phrase1", "phrase2"] } }
    # Flow state: story_flags["setskill_flow"]
    #   { "step": 1|2|3, "poke_key": str, "skill_name": str|None, "removing": bool }
    # ══════════════════════════════════════════════════════════

    # ── .move(s) [number] ─────────────────────────────────────
    def _handle_moves(self, player, args):
        import battle_log
        from pokeapi import get_move
        mon = player.active_pokemon()
        if not mon:
            return "_No active Pokémon._"
        rows = []
        for m in mon.moves:
            d = get_move(self.db, m["name"]) or {}
            rows.append({
                "name": m["name"], "pp": m["pp"], "max_pp": m.get("max_pp", m["pp"]),
                "type": d.get("type", "normal"), "category": d.get("category", "physical"),
                "power": d.get("power", 0), "accuracy": d.get("accuracy", 100),
                "description": d.get("description", ""), "effect": d.get("effect", ""),
            })
        if not rows:
            return "_No moves._"
        if args:
            if not args[0].isdigit() or not (1 <= int(args[0]) <= len(rows)):
                return f"_Pick a move number from 1 to {len(rows)}._"
            return battle_log.move_detail(rows[int(args[0]) - 1])
        return battle_log.moves_list(mon.nickname, rows)

    EXPLORE_OPEN = False   # flip to True to reopen .explore

    # ── .pbattle — chance-based wild encounter ────────────────
    PBATTLE_CHANCE = 0.60   # placeholder: exact encounter chances undecided

    def _handle_pbattle(self, sender, player, session, stage):
        import random
        from combat_session import STATE_EXPLORING, STATE_IDLE
        import battle_log
        if stage not in (STATE_EXPLORING, STATE_IDLE):
            return None
        active = player.active_pokemon()
        if not active or active.is_fainted():
            return "_Your active Pokémon can't battle right now._"
        if random.random() > self.PBATTLE_CHANCE:
            return "_Nothing appeared._"    # placeholder: no-encounter text undecided
        from encounters import roll_wild_pokemon, build_wild_monster
        from pokeapi import get_full
        result = roll_wild_pokemon(player.zone, "grass", player.level)
        if not result:
            return "_Nothing appeared._"
        species, level = result
        api_data = get_full(self.db, species)
        if not api_data:
            return "_Nothing appeared._"
        monster = build_wild_monster(api_data, level, db=self.db)
        monster["description"] = api_data.get("flavor_text", "") or ""
        player.see_pokemon(species)
        session.set_encounter(monster)
        self._save(sender, player)
        return battle_log.encounter_marker(
            monster.get("sprite", ""), monster["name"].capitalize(), monster["description"])

    def _poke_key(self, poke) -> str:
        return f"{poke.name}_{poke.nickname.lower()}"

    def _all_poke_ordered(self, player):
        """Party first, then box."""
        return [(p, False) for p in player.party] + [(p, True) for p in player.box]

    def _find_poke(self, player, query: str):
        """Find a Pokémon by number or name (party first, then box)."""
        all_poke = self._all_poke_ordered(player)
        if query.isdigit():
            idx = int(query) - 1
            if 0 <= idx < len(all_poke):
                return all_poke[idx]
            return None, None
        for poke, in_box in all_poke:
            if poke.nickname.lower() == query or poke.name.lower() == query:
                return poke, in_box
        return None, None

    def _setskill_list(self, player) -> str:
        """Show all skill nicknames grouped by Pokémon."""
        db = player.get_flag("skill_nicknames", {})
        if not db:
            return "_You haven't set any skill nicknames yet._"
        lines = ["📋 *Skill Nicknames*", ""]
        for poke, in_box in self._all_poke_ordered(player):
            key = self._poke_key(poke)
            if key not in db:
                continue
            loc = "📦 PC" if in_box else ""
            lines.append(f"*{poke.nickname}* {loc}")
            for skill, phrases in db[key].items():
                skill_display = skill.replace("-", " ").title()
                for phrase in phrases:
                    lines.append(f'  _{skill_display}_ → "{phrase}"')
            lines.append("")
        if len(lines) == 2:
            return "_You haven't set any skill nicknames yet._"
        return "\n".join(lines).strip()

    def _setskill_start(self, sender, player, query: str, removing: bool) -> str:
        """Start the setskill/unsetskill flow for a given Pokémon query."""
        poke, in_box = self._find_poke(player, query)
        if poke is None:
            return f"_No Pokémon found for \"{query}\"._"
        key = self._poke_key(poke)
        # Build skill list — equipped then unequipped
        equipped = poke.moves  # list of {name, pp, max_pp}
        pool = getattr(poke, "move_pool", [])
        current_names = {m["name"] for m in equipped}
        unequipped = [m for m in pool if m not in current_names]

        lines = [f"⚙️ *{poke.nickname}'s Skills*", ""]
        lines.append("*Equipped:*")
        for i, m in enumerate(equipped):
            lines.append(f"  {i+1}. {m['name'].replace('-',' ').title()} ({m['pp']}/{m['max_pp']} PP)")
        if unequipped:
            lines.append("\n*Unequipped:*")
            for j, m in enumerate(unequipped):
                lines.append(f"  {len(equipped)+j+1}. {m.replace('-',' ').title()}")
        lines.append("")
        action = "remove a nickname from" if removing else "nickname"
        lines.append(f"_Reply with the number of the skill you want to {action}._")
        lines.append("_Any other message cancels._")

        # Store flow state
        player.set_flag("setskill_flow", {
            "step": 1,
            "poke_key": key,
            "skill_index_map": {
                str(i+1): m["name"] for i, m in enumerate(equipped)
            } | {
                str(len(equipped)+j+1): m for j, m in enumerate(unequipped)
            },
            "skill_name": None,
            "removing": removing,
        })
        player.story_stage = "setskill"
        self._save(sender, player)
        return "\n".join(lines)

    def _handle_setskill_flow(self, sender, player, text: str) -> str:
        flow = player.get_flag("setskill_flow", {})
        step = flow.get("step", 1)
        removing = flow.get("removing", False)

        def _cancel():
            player.story_stage = None
            player.set_flag("setskill_flow", {})
            self._save(sender, player)
            return "_Cancelled._"

        if step == 1:
            # Expecting a skill number
            if not text.strip().isdigit():
                return _cancel()
            idx_map = flow.get("skill_index_map", {})
            skill_name = idx_map.get(text.strip())
            if not skill_name:
                return _cancel()

            flow["step"] = 2
            flow["skill_name"] = skill_name
            player.set_flag("setskill_flow", flow)
            self._save(sender, player)

            skill_display = skill_name.replace("-", " ").title()
            db = player.get_flag("skill_nicknames", {})
            poke_key = flow["poke_key"]
            existing = db.get(poke_key, {}).get(skill_name, [])

            if removing:
                if not existing:
                    player.story_stage = None
                    player.set_flag("setskill_flow", {})
                    self._save(sender, player)
                    return f"_No nicknames set for {skill_display}._"
                lines = [f"⚙️ *Nicknames for {skill_display}:*", ""]
                for i, phrase in enumerate(existing):
                    lines.append(f"  {i+1}. \"{phrase}\"")
                lines.append("")
                lines.append("_Reply with the number to remove. Any other message cancels._")
                flow["step"] = 3
                flow["existing"] = existing
                player.set_flag("setskill_flow", flow)
                self._save(sender, player)
                return "\n".join(lines)
            else:
                hint = ""
                if existing:
                    hint = f"_Existing: {', '.join(chr(34)+p+chr(34) for p in existing)}_\n"
                return (
                    f"⚙️ *{skill_display}*\n\n"
                    f"{hint}"
                    f"_Reply with the phrase you want to use for this skill._\n"
                    f"_Must contain at least one letter. Any command cancels._"
                )

        if step == 2:
            # Expecting a phrase (setskill only)
            import re
            if not re.search(r"[a-zA-Z]", text):
                return _cancel()
            phrase = text.strip().lower()
            skill_name = flow["skill_name"]
            poke_key = flow["poke_key"]
            db = player.get_flag("skill_nicknames", {})
            if poke_key not in db:
                db[poke_key] = {}
            if skill_name not in db[poke_key]:
                db[poke_key][skill_name] = []
            if phrase not in db[poke_key][skill_name]:
                db[poke_key][skill_name].append(phrase)
            player.set_flag("skill_nicknames", db)
            player.story_stage = None
            player.set_flag("setskill_flow", {})
            self._save(sender, player)
            skill_display = skill_name.replace("-", " ").title()
            return f"✅ *\"{text.strip()}\"* → *{skill_display}*"

        if step == 3:
            # Expecting a number to remove (unsetskill only)
            if not text.strip().isdigit():
                return _cancel()
            existing = flow.get("existing", [])
            idx = int(text.strip()) - 1
            if idx < 0 or idx >= len(existing):
                return _cancel()
            removed = existing[idx]
            skill_name = flow["skill_name"]
            poke_key = flow["poke_key"]
            db = player.get_flag("skill_nicknames", {})
            if poke_key in db and skill_name in db[poke_key]:
                db[poke_key][skill_name] = [p for p in db[poke_key][skill_name] if p != removed]
                if not db[poke_key][skill_name]:
                    del db[poke_key][skill_name]
                if not db[poke_key]:
                    del db[poke_key]
            player.set_flag("skill_nicknames", db)
            player.story_stage = None
            player.set_flag("setskill_flow", {})
            self._save(sender, player)
            skill_display = skill_name.replace("-", " ").title()
            return f"✅ Removed *\"{removed}\"* from *{skill_display}*."

        return _cancel()

    def _handle_caught_naming(self, sender, player, cmd, text, args):
        """Handle .name / .skip after catching a Pokémon."""
        in_box = player.get_flag("caught_naming_box", False)
        slot   = player.get_flag("caught_naming_slot", 0)
        target = player.box[slot] if in_box else (player.party[slot] if slot < len(player.party) else None)

        if not target:
            player.story_stage = "route_1"
            self._save(sender, player)
            return None

        if cmd == ".skip":
            player.story_stage = "route_1"
            player.set_flag("caught_naming_slot", None)
            player.set_flag("caught_naming_box", False)
            self._save(sender, player)
            return f"_Kept the name *{target.nickname}*._"

        if cmd == ".name" or cmd.startswith(".name"):
            raw = text.strip()[5:].strip() if len(text.strip()) > 5 else ""
            if not raw and args:
                raw = " ".join(args)
            if raw.startswith("[") and raw.endswith("]"):
                raw = raw[1:-1].strip()
            if not raw:
                return "_Usage: .name [nickname] or .skip_"
            if len(raw) > 16:
                return "_Nickname must be 16 characters or less._"
            target.nickname = raw.capitalize()
            player.story_stage = "route_1"
            player.set_flag("caught_naming_slot", None)
            player.set_flag("caught_naming_box", False)
            self._save(sender, player)
            return f"✅ Your Pokémon has been named *{target.nickname}*!"

        return "_Would you like to name this Pokémon?\n*.name [nickname]*\n*.skip*_"

    # ── Leaderboard ───────────────────────────────────────────
    # Same 4 categories as the website's leaderboard tabs (index.html:
    # Level / PvP Wins / Caught / Badges), so .lb and the site always
    # agree on what "top 10" means.
    LB_CATEGORIES = {
        "level":  ("Level",    lambda d: d.get("level", 0)),
        "pvp":    ("PvP Wins", lambda d: d.get("pvp_wins", 0)),
        "caught": ("Caught",   lambda d: len(d.get("pokedex_caught", []) or [])),
        "badges": ("Badges",   lambda d: len(d.get("badges", []) or [])),
    }
    LB_ALIASES = {
        "lvl": "level", "level": "level",
        "pvp": "pvp", "wins": "pvp",
        "caught": "caught", "dex": "caught", "pokedex": "caught",
        "badges": "badges", "badge": "badges", "gym": "badges",
    }

    def _leaderboard_text(self, args) -> str:
        key = self.LB_ALIASES.get(args[0].lower(), "level") if args else "level"
        label, scorer = self.LB_CATEGORIES[key]

        rows = self.db.all_players_data()
        scored = []
        for _sender, d in rows:
            name = d.get("name") or "Unnamed"
            scored.append((name, scorer(d)))

        scored.sort(key=lambda r: r[1], reverse=True)
        top = scored[:10]

        if not top:
            return "_No trainers registered yet._"

        medals = ["🥇", "🥈", "🥉"]
        unit = {"level": "LV", "pvp": "W", "caught": "", "badges": ""}[key]
        lines = [f"🏆 *Leaderboard — {label}*", ""]
        for i, (name, value) in enumerate(top, 1):
            marker = medals[i - 1] if i <= 3 else f"{i}."
            lines.append(f"{marker} *{name}* — {value}{unit}")
        lines.append("")
        lines.append("_.lb [level|pvp|caught|badges]_")
        return "\n".join(lines)
