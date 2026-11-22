# ============================================================
# NIFLHEIM — pvp_session.py
# PvP Turn Engine
#
# Uses resolve_turn() from battle.py — identical formula to PvE.
# Only PvP-specific logic here:
#   - Two OwnedPokemon on both sides
#   - Simultaneous turn resolution: each side submits a move, nothing
#     resolves until BOTH have submitted, then both moves resolve
#     together in speed order (faster mon's move first; if it faints
#     the target, the slower mon's already-queued move never happens
#     — standard Pokémon simultaneous-turn rule). No per-half-turn
#     ack/wait message is sent; the first mover's submission is
#     silent until the second mover closes out the round.
#   - Forced swap prompt after faint
#   - Battle card image (battle_render) + combined caption showing
#     both actors' stanzas in resolution order
# ============================================================

import random
from models import OwnedPokemon
from battle import (
    resolve_turn,
    apply_status_tick, _status_prevents_action,
    _init_modifier_stack, STATUS_ICONS,
    battle_image_marker,
)

import battle_log as BL

RM = "\u200b" * 700  # readmore spacer


def _hp_bar(hp, max_hp, width=10):
    if max_hp <= 0:
        return "░" * width
    filled = int(round((hp / max_hp) * width))
    filled = max(0, min(width, filled))
    pct = int((hp / max_hp) * 100)
    bar = "█" * filled + "░" * (width - filled)
    color = "🟩" if pct > 50 else "🟨" if pct > 20 else "🟥"
    return f"{color} {bar} {hp}/{max_hp}"


class PvPSession:
    """
    Holds state for a single 1v1 PvP battle between two players.

    pending_move    : {jid: move_or_swap_dict_or_None} — simultaneous
                       turn queue; a round resolves once both are set
    awaiting_swap   : jid of player who must swap after faint, or None
    ended           : True once battle is fully over
    winner_jid      : JID of winner, None if draw
    wager           : int coins wagered (0 = no wager)
    """

    def __init__(self, jid_a, player_a, jid_b, player_b, wager=0, db=None, group_jid=None):
        self.jid_a    = jid_a
        self.jid_b    = jid_b
        self.player_a = player_a
        self.player_b = player_b
        self.wager    = wager
        self.db       = db
        self.group_jid = group_jid

        self.name_a = f"@{player_a.name}"
        self.name_b = f"@{player_b.name}"

        self.pokemon_a = player_a.party[player_a.active_slot]
        self.pokemon_b = player_b.party[player_b.active_slot]

        self.stack_a = _init_modifier_stack()
        self.stack_b = _init_modifier_stack()

        self._flinched = None   # jid of flinched player this turn (set during resolution)

        # Simultaneous-turn queue: each side submits a move; nothing
        # resolves until both slots are filled. Cleared after each
        # round resolves (or on faint/swap).
        self.pending_move = {jid_a: None, jid_b: None}
        self.xp_gained    = {jid_a: 0, jid_b: 0}   # shown in the rewards block

        self.ended         = False
        self.winner_jid    = None
        self.awaiting_swap = None

    # ── Helpers ───────────────────────────────────────────────

    def _attacker_for(self, jid):
        if jid == self.jid_a:
            return self.pokemon_a, self.name_a, self.stack_a
        return self.pokemon_b, self.name_b, self.stack_b

    def _player_for(self, jid):
        return self.player_a if jid == self.jid_a else self.player_b

    def _pokemon_for(self, jid):
        return self.pokemon_a if jid == self.jid_a else self.pokemon_b

    def _stack_for(self, jid):
        return self.stack_a if jid == self.jid_a else self.stack_b

    def _set_pokemon(self, jid, poke):
        if jid == self.jid_a:
            self.pokemon_a = poke
            self.stack_a   = _init_modifier_stack()
        else:
            self.pokemon_b = poke
            self.stack_b   = _init_modifier_stack()

    def _name_for(self, jid):
        return self.name_a if jid == self.jid_a else self.name_b

    def _opponent_jid(self, jid):
        return self.jid_b if jid == self.jid_a else self.jid_a

    def _award_xp(self, jid, poke):
        gain = random.randint(20, 50)
        poke.gain_xp(gain)
        self.xp_gained[jid] += gain

    def _hp_rows(self):
        a, b = self.pokemon_a, self.pokemon_b
        return [f"{self.name_a}'s {a.nickname}: {max(0, a.hp)}/{a.max_hp} HP",
                f"{self.name_b}'s {b.nickname}: {max(0, b.hp)}/{b.max_hp} HP"]

    def _frame(self, lines, commands=True, footer_lines=None):
        # Plain "X fainted!" lines are dropped: the PvP note shows faints
        # after the HP block (replacement prompt / end-of-battle lines).
        body = [l for l in lines if not (l.endswith(" fainted!") and not l.startswith("*"))]
        return BL.log_frame(body, self._hp_rows(),
                            BL.PVP_COMMANDS if commands else None, footer_lines)

    def start_caption(self):
        return BL.log_frame(["Battle started!"], self._hp_rows(), BL.PVP_COMMANDS,
                            blank_between_hp=True)

    def _resolve_move(self, poke: OwnedPokemon, raw_input: str):
        """Substring match — same logic as BattleEngine._resolve_skill."""
        import re
        def _norm(t):
            return " ".join(re.sub(r"[^a-zA-Z0-9 ]", " ", t).lower().split())
        norm_input = _norm(raw_input)
        for m in poke.moves:
            nm = _norm(m["name"])
            if nm and nm in norm_input:
                return m
        return None

    # ── Turn resolution ───────────────────────────────────────

    def do_turn(self, sender_jid: str, raw_input: str, db=None):
        """
        Submits sender_jid's move for this round. Nothing resolves until
        BOTH sides have submitted — the first submission is silent
        (returns "queued", no message to send). Once the second side
        submits, both moves resolve together in speed order and a
        single combined result is returned.

        Returns one of:
          ("queued",  None,       None)              — first mover this round, nothing to send
          ("action",  action_msg, hud_msg)            — round resolved, hud_msg is the __IMG__ marker
          ("faint",   action_msg, swap_msg)
          ("victory", action_msg, None)
          ("error",   msg,        None)
          ("wait",    None,       None)
        """
        db = db or self.db

        if self.ended:
            return ("wait", None, None)

        if self.awaiting_swap:
            if sender_jid != self.awaiting_swap:
                return ("wait", None, None)
            return ("error", "_Use .switch (no.) to send out your next Pokémon._", None)

        if sender_jid not in (self.jid_a, self.jid_b):
            return ("wait", None, None)

        if self.pending_move.get(sender_jid) is not None:
            return ("error", "_You've already locked in a move this round — waiting on your opponent._", None)

        atk_poke, atk_name, atk_stages = self._attacker_for(sender_jid)

        move_obj = self._resolve_move(atk_poke, raw_input)
        if not move_obj:
            return ("error", f"_{atk_poke.nickname} doesn't know that move!_", None)
        if move_obj["pp"] <= 0:
            return ("error", f"_{move_obj['name']} has no PP left!_", None)

        self.pending_move[sender_jid] = move_obj

        other_jid = self._opponent_jid(sender_jid)
        if self.pending_move.get(other_jid) is None:
            # First mover this round — silent, nothing sent.
            return ("queued", None, None)

        # Both sides have submitted — resolve the round together.
        return self._resolve_round(db)

    def _resolve_round(self, db):
        """Both pending moves/swaps are set. Swaps resolve first (a swap
        is instant — the new Pokémon is already in before any attack
        lands, same as mainline Pokémon), THEN any remaining attack(s)
        resolve in speed order. If two attacks and the faster one faints
        the target, the slower mon's already-queued move never happens
        (standard Pokémon simultaneous-turn rule)."""
        move_a = self.pending_move[self.jid_a]
        move_b = self.pending_move[self.jid_b]
        self.pending_move[self.jid_a] = None
        self.pending_move[self.jid_b] = None
        self._flinched = None

        combined = []

        # ── Swaps resolve first, instantly, no speed comparison ──
        for jid, mv in ((self.jid_a, move_a), (self.jid_b, move_b)):
            if isinstance(mv, dict) and mv.get("_swap"):
                poke = self._pokemon_for(jid)
                combined.extend(BL.switch_block(self._player_for(jid).name, mv["old_name"], poke.nickname))

        remaining = []  # (jid, move_obj) for sides that actually attacked
        for jid, mv in ((self.jid_a, move_a), (self.jid_b, move_b)):
            if isinstance(mv, dict) and not mv.get("_swap"):
                remaining.append((jid, mv))

        if len(remaining) == 0:
            # Both sides just swapped — no attack this round.
            return ("action", self._frame(combined), None)

        if len(remaining) == 1:
            # One side swapped, the other attacked — attacker hits
            # whatever's now in front of them (already updated above).
            atk_jid, atk_move = remaining[0]
            def_jid = self._opponent_jid(atk_jid)
            atk_poke, atk_name, atk_stack = self._attacker_for(atk_jid)
            def_poke, def_name, def_stack = self._attacker_for(def_jid)

            log = []
            result = resolve_turn(
                atk_poke, def_poke, atk_move,
                attacker_stack=atk_stack, defender_stack=def_stack,
                db=db, log=log,
                moved_first=True,
                flinch_flag=None,
            )
            combined.extend(log)

            if result == "fainted":
                self._award_xp(atk_jid, atk_poke)
                def_player = self._player_for(def_jid)
                return self._handle_def_faint(combined, def_poke, def_jid, def_player, atk_jid, atk_poke)

            apply_status_tick(atk_poke, combined)
            apply_status_tick(def_poke, combined)
            r = self._check_post_tick(combined, atk_poke, def_poke, atk_jid, def_jid, self._player_for(def_jid))
            if r:
                if r[0] in ("action", "faint", "victory") and combined is not r[1]:
                    pass  # r already carries the right joined log
                return r

            return ("action", self._frame(combined), None)

        # ── Both sides attacked — resolve in speed order ──
        from battle import _apply_stack_to_primary
        PARALYSIS_SPEED_MULT = 0.5  # matches battle.py's approach
        stats_a = self.pokemon_a.stats
        stats_b = self.pokemon_b.stats
        spd_a = _apply_stack_to_primary("speed", stats_a.get("speed", 0), self.stack_a)
        if self.pokemon_a.status == "paralysis":
            spd_a *= PARALYSIS_SPEED_MULT
        spd_b = _apply_stack_to_primary("speed", stats_b.get("speed", 0), self.stack_b)
        if self.pokemon_b.status == "paralysis":
            spd_b *= PARALYSIS_SPEED_MULT
        a_first = spd_a >= spd_b  # tie goes to challenger (a)

        if a_first:
            first_jid,  first_move  = self.jid_a, move_a
            second_jid, second_move = self.jid_b, move_b
        else:
            first_jid,  first_move  = self.jid_b, move_b
            second_jid, second_move = self.jid_a, move_a

        first_poke, first_name, first_stack   = self._attacker_for(first_jid)
        second_poke, second_name, second_stack = self._attacker_for(second_jid)

        first_log  = []
        second_log = []

        def _flinch_flag_second(_):
            self._flinched = second_jid

        first_result = resolve_turn(
            first_poke, second_poke, first_move,
            attacker_stack=first_stack, defender_stack=second_stack,
            db=db, log=first_log,
            moved_first=True,
            flinch_flag=_flinch_flag_second,
        )
        combined.extend(first_log)

        if first_result == "fainted":
            self._award_xp(first_jid, first_poke)
            # Second mon fainted before it could act — its move never happens.
            second_player = self._player_for(second_jid)
            return self._handle_def_faint(combined, second_poke, second_jid, second_player, first_jid, first_poke)

        # Second mon still standing (or was only flinched/status-blocked) — it acts.
        second_result = resolve_turn(
            second_poke, first_poke, second_move,
            attacker_stack=second_stack, defender_stack=first_stack,
            db=db, log=second_log,
            moved_first=False,
            flinch_flag=None,
        )
        if second_log:
            combined.append("")  # blank line between actor stanzas
            combined.extend(second_log)

        if second_result == "fainted":
            self._award_xp(second_jid, second_poke)
            first_player = self._player_for(first_jid)
            return self._handle_def_faint(combined, first_poke, first_jid, first_player, second_jid, second_poke)

        # End-of-turn status ticks for both sides.
        apply_status_tick(first_poke, combined)
        apply_status_tick(second_poke, combined)
        r = self._check_post_tick(combined, first_poke, second_poke, first_jid, second_jid,
                                   self._player_for(second_jid))
        if r: return r

        return ("action", self._frame(combined), None)

    # ── Post-tick faint checks ────────────────────────────────

    def _check_post_tick(self, log, atk_poke, def_poke, atk_jid, def_jid, def_player):
        """Check if either side fainted from status ticks. Returns result tuple or None."""
        atk_player = self._player_for(atk_jid)

        if def_poke.is_fainted():
            self._award_xp(atk_jid, atk_poke)
            log.append(f"{def_poke.nickname} fainted from status! 💀")
            return self._handle_def_faint(log, def_poke, def_jid, def_player, atk_jid, atk_poke)

        if atk_poke.is_fainted():
            log.append(f"{atk_poke.nickname} fainted from status! 💀")
            return self._after_faint(log, atk_poke, atk_jid, atk_player)

        return None

    def _handle_def_faint(self, log, def_poke, def_jid, def_player, atk_jid, atk_poke):
        return self._after_faint(log, def_poke, def_jid, def_player)

    def _after_faint(self, log, fainted_poke, loser_jid, loser_player):
        """Replacement prompt if the loser has usable Pokémon, else battle over."""
        remaining = [(i + 1, p) for i, p in enumerate(loser_player.party) if not p.is_fainted()]
        if not remaining:
            winner_jid = self._opponent_jid(loser_jid)
            self.ended      = True
            self.winner_jid = winner_jid
            end = BL.pvp_end_lines(fainted_poke.nickname, loser_player.name,
                                   self._player_for(winner_jid).name)
            return ("victory", self._frame(log, False, end), None)
        self.awaiting_swap = loser_jid
        prompt = BL.replacement_prompt(
            fainted_poke.nickname, [(n, p.nickname, p.hp, p.max_hp) for n, p in remaining])
        # log frame already closes with the divider the prompt starts with
        prompt_body = prompt.split("\n", 1)[1]
        return ("faint", self._frame(log, False) + "\n" + prompt_body, None)

    # ── Swap after faint ──────────────────────────────────────

    def do_swap(self, sender_jid: str, slot: int):
        """Forced swap after faint — swapping player gets the next turn."""
        if self.awaiting_swap != sender_jid:
            return False, "_It's not your time to swap._"

        player = self._player_for(sender_jid)
        idx    = slot - 1

        if idx < 0 or idx >= len(player.party):
            return False, "⚠️ _Invalid slot._"

        poke = player.party[idx]
        if poke.is_fainted():
            return False, f"_{poke.nickname} cannot be summoned right now_"

        self._set_pokemon(sender_jid, poke)
        player.active_slot = idx
        self.awaiting_swap = None
        self._flinched     = None

        # Swapping player gets the turn
        self.turn = "a" if sender_jid == self.jid_a else "b"
        name = self._name_for(sender_jid)

        msg = f"{self._player_for(sender_jid).name} sent out {poke.nickname}!\n\n" + BL.PVP_COMMANDS
        return True, msg

    def do_voluntary_swap(self, sender_jid: str, slot: int):
        """Voluntary mid-battle swap — counts as this side's move for the
        round, same as an attack. Queues silently if the opponent hasn't
        submitted yet; if they have, the round resolves immediately with
        the new Pokémon already in for any incoming attack."""
        if self.ended or self.awaiting_swap:
            return False, "_Can't swap right now._"
        if self.pending_move.get(sender_jid) is not None:
            return False, "_You've already locked in a move this round — waiting on your opponent._"

        player = self._player_for(sender_jid)
        idx    = slot - 1

        if idx < 0 or idx >= len(player.party):
            return False, "⚠️ _Invalid slot._"

        poke = player.party[idx]
        if poke.is_fainted():
            return False, f"_{poke.nickname} cannot be summoned right now_"

        current = self._pokemon_for(sender_jid)
        if poke is current:
            return False, f"_{poke.nickname} is already in battle!_"

        old_name = current.nickname
        self._set_pokemon(sender_jid, poke)
        player.active_slot = idx

        self.pending_move[sender_jid] = {"_swap": True, "old_name": old_name}

        other_jid = self._opponent_jid(sender_jid)
        if self.pending_move.get(other_jid) is None:
            # Swap is silent too, like an attack submission — no message
            # until the opponent also acts.
            return True, None

        result = self._resolve_round(self.db)
        # Normalize to the (ok, msg) shape do_voluntary_swap's callers expect.
        kind, action_msg, hud_or_swap = result
        if kind in ("action", "faint", "victory"):
            msg = action_msg if not hud_or_swap else f"{action_msg}\n\n{hud_or_swap}"
            return True, msg
        return True, action_msg

    # ── HUD ───────────────────────────────────────────────────

    def battle_hud(self, caption=None) -> str:
        """Builds the __IMG__...__CAP__... battle card marker shown once
        both sides have acted this round. No 'whose turn' line — in the
        simultaneous model both players act every round, there's no
        turn order to announce, just 'submit your move' implicitly."""
        player_mon = {
            "name":   self.pokemon_a.nickname,
            "level":  self.pokemon_a.level,
            "hp":     max(0, self.pokemon_a.hp),
            "max_hp": self.pokemon_a.max_hp,
            "status": self.pokemon_a.status,
            "sprite": self.pokemon_a.sprite,
        }
        enemy_mon = {
            "name":   self.pokemon_b.nickname,
            "level":  self.pokemon_b.level,
            "hp":     max(0, self.pokemon_b.hp),
            "max_hp": self.pokemon_b.max_hp,
            "status": self.pokemon_b.status,
            "sprite": self.pokemon_b.sprite,
        }

        import battle_render, os, time
        out_dir = os.path.join(__import__("paths").ROOT, ".battle_cards")
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, f"pvp_{int(time.time()*1000)}.png")
        battle_render.render(player_mon, enemy_mon, out_path, label="PVP")

        caption = caption or self.start_caption()
        return f"__IMG__{out_path}__CAP__{caption}"
