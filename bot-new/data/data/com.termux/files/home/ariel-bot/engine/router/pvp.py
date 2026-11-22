# ============================================================
# NIFLHEIM — router/pvp.py
# Pillar II + IV: Challenge, accept, decline, turn routing, rewards
# ============================================================

import random
import threading
from pvp_session import PvPSession
import battle_log as BL

CHALLENGE_TIMEOUT = 60   # seconds
PVP_XP_MIN        = 20
PVP_XP_MAX        = 50


class PvPMixin:
    """
    Handles all PvP commands:
      .challenge @user [wager]
      .accept / .decline
      skill input while STATE_PVP
      .swap (no.) — forced or voluntary
      .giveup
      .flee during PvP
    """

    def _pvp_init(self):
        if not hasattr(self, "_pvp_challenges"):
            self._pvp_challenges = {}
        if not hasattr(self, "_pvp_sessions"):
            self._pvp_sessions = {}

    # ── .challenge @user [wager] ──────────────────────────────

    def handle_challenge(self, sender, player, mentioned_jid, args=None, group_jid=None):
        self._pvp_init()

        if not mentioned_jid:
            return "⚔️ _Tag someone to challenge. e.g._ `.challenge @PlayerB`"

        if mentioned_jid == sender:
            return "_You can't challenge yourself._"

        target = self._get(mentioned_jid)
        if not target:
            return "_That player hasn't registered yet._"

        if not player.party or all(p.is_fainted() for p in player.party):
            return "_Your Pokémon are all fainted. Heal up before challenging._"

        if not target.party or all(p.is_fainted() for p in target.party):
            return f"_@{target.name}'s Pokémon are all fainted._"

        t_session = self._session(mentioned_jid)
        if t_session.state in ("pvp_pending", "in_pvp"):
            return f"_@{target.name} is already in a battle._"

        s_session = self._session(sender)
        if s_session.state in ("pvp_pending", "in_pvp"):
            return "_You are already in a battle._"

        # ── Wager check ───────────────────────────────────────
        wager = 0
        if args:
            try:
                wager = int(args[0])
                if wager < 0:
                    return "_Wager can't be negative._"
            except ValueError:
                pass

        if wager > 0:
            if player.coins < wager:
                return f"_You don't have enough coins for this wager. (You have {player.coins}₡)_"
            if target.coins < wager:
                return f"_@{target.name} does not have enough coins for this wager._"

        # Set pending
        s_session.state = "pvp_pending"
        t_session.state = "pvp_pending"

        # Capture group_jid now — the timer fires on a background thread later,
        # by which point self._last_group_jid could belong to a different chat.
        _group_jid = group_jid

        def _expire():
            self._pvp_expire(sender, mentioned_jid, _group_jid)

        timer = threading.Timer(CHALLENGE_TIMEOUT, _expire)
        timer.daemon = True
        timer.start()

        self._pvp_challenges[mentioned_jid] = {
            "challenger":        sender,
            "challenger_player": player,
            "timer":             timer,
            "wager":             wager,
            "group_jid":         group_jid,
        }

        challenger_tag = f"@{player.name}"
        target_tag     = f"@{target.name}"
        wager_line     = f"\n💰 *Wager:* {wager}₡ each" if wager else ""

        return (
            f"⚔️ *{target_tag}*, you have been challenged by *{challenger_tag}*!{wager_line}\n\n"
            f"Do you accept this battle?\n"
            f".accept  |  .decline\n\n"
            f"_(expires in {CHALLENGE_TIMEOUT}s)_"
        )

    # ── .accept ───────────────────────────────────────────────

    def handle_pvp_accept(self, sender, player):
        self._pvp_init()

        challenge = self._pvp_challenges.get(sender)
        if not challenge:
            import sys
            print(f"[PVP] .accept from {sender} found no pending challenge. "
                  f"pending keys={list(self._pvp_challenges.keys())}", file=sys.stderr, flush=True)
            return "_You don't have a pending challenge._"

        challenge["timer"].cancel()
        del self._pvp_challenges[sender]

        challenger_jid    = challenge["challenger"]
        challenger_player = challenge["challenger_player"]
        wager             = challenge.get("wager", 0)
        group_jid         = challenge.get("group_jid")

        # Build session
        session_obj = PvPSession(
            challenger_jid, challenger_player,
            sender,         player,
            wager=wager,
            db=self.db,
            group_jid=group_jid,
        )
        self._pvp_sessions[challenger_jid] = session_obj
        self._pvp_sessions[sender]         = session_obj

        self._session(challenger_jid).state = "in_pvp"
        self._session(sender).state         = "in_pvp"

        wager_line = f"\n💰 *Wager:* {wager}₡ each" if wager else ""

        accept_msg = (
            f"✅ *@{player.name}* has accepted the challenge!{wager_line}\n\n"
            f"*Participants*\n"
            f"1. @{player.name}\n"
            f"2. @{challenger_player.name}\n\n"
            f"Prepare for battle..."
        )

        def _send_hud():
            import sys, time
            time.sleep(5)
            try:
                fight_msg = session_obj.battle_hud()
                send = getattr(self, "_direct_send", None)
                if send:
                    send(fight_msg, group_jid=session_obj.group_jid)
                else:
                    print("[PVP] _send_hud: no _direct_send bound", file=sys.stderr, flush=True)
            except Exception as e:
                print(f"[PVP] _send_hud thread error: {e}", file=sys.stderr, flush=True)

        threading.Thread(target=_send_hud, daemon=True).start()

        return accept_msg

    # ── .decline ──────────────────────────────────────────────

    def handle_pvp_decline(self, sender, player):
        self._pvp_init()

        challenge = self._pvp_challenges.get(sender)
        if not challenge:
            return "_You don't have a pending challenge._"

        challenge["timer"].cancel()
        del self._pvp_challenges[sender]

        challenger_jid    = challenge["challenger"]
        challenger_player = challenge["challenger_player"]

        self._session(sender).state         = "exploring"
        self._session(challenger_jid).state = "exploring"

        return f"_@{challenger_player.name}, your challenge was declined by @{player.name}._"

    # ── Expire ────────────────────────────────────────────────

    def _pvp_expire(self, challenger_jid, target_jid, group_jid=None):
        self._pvp_init()
        self._pvp_challenges.pop(target_jid, None)
        self._session(challenger_jid).state = "exploring"
        self._session(target_jid).state     = "exploring"
        send = getattr(self, "_direct_send", None)
        if send: send("_Challenge expired._", group_jid=group_jid)

    # ── Skill input ───────────────────────────────────────────

    def handle_pvp_skill(self, sender, player, move_name: str):
        self._pvp_init()

        session_obj = self._pvp_sessions.get(sender)
        if not session_obj:
            return "_No active PvP battle._"
        if session_obj.ended:
            return None

        # Block if awaiting swap from this player
        if session_obj.awaiting_swap == sender:
            return "_Use .switch (no.) to send out your next Pokémon, or .forfeit._"

        result = session_obj.do_turn(sender, move_name, db=self.db)
        kind   = result[0]

        send = getattr(self, "_direct_send", None)

        if kind == "wait":
            return "_Wait for your turn._"

        if kind == "error":
            return result[1]

        if kind == "action":
            _, action_msg, hud_msg = result
            if send:
                send(action_msg, group_jid=session_obj.group_jid)
                if hud_msg:
                    send(hud_msg, group_jid=session_obj.group_jid)
            return None

        if kind == "faint":
            _, action_msg, swap_msg = result
            if send:
                send(action_msg, group_jid=session_obj.group_jid)
                if swap_msg:
                    send(swap_msg, group_jid=session_obj.group_jid)
            return None

        if kind == "victory":
            _, action_msg, _ = result
            if send: send(action_msg, group_jid=session_obj.group_jid)
            self._pvp_end(session_obj, session_obj.winner_jid)
            return None

        return None

    # ── .switch [name/no] (alias: .swap) ──────────────────────

    def handle_pvp_switch(self, sender, player, arg: str):
        arg = (arg or "").strip()
        if arg.isdigit():
            slot = int(arg)
        else:
            slot = next((i + 1 for i, p in enumerate(player.party)
                         if arg and arg.lower() in p.nickname.lower()), 0)
            if not slot:
                return "_Usage: .switch [name/no]_"
        session_obj = self._pvp_sessions.get(sender) if hasattr(self, "_pvp_sessions") else None
        voluntary = bool(session_obj) and session_obj.awaiting_swap != sender
        return self.handle_pvp_swap(sender, player, slot, voluntary=voluntary)

    # ── .swap ─────────────────────────────────────────────────

    def handle_pvp_swap(self, sender, player, slot: int, voluntary=False):
        self._pvp_init()

        session_obj = self._pvp_sessions.get(sender)
        if not session_obj or session_obj.ended:
            return None

        send = getattr(self, "_direct_send", None)

        if voluntary:
            ok, msg = session_obj.do_voluntary_swap(sender, slot)
        else:
            ok, msg = session_obj.do_swap(sender, slot)

        if send and ok:
            send(msg, group_jid=session_obj.group_jid)
            return None
        return msg

    # ── .giveup / .flee / .forfeit (aliases) ────────────────────

    def handle_pvp_forfeit(self, sender, player):
        self._pvp_init()

        session_obj = self._pvp_sessions.get(sender)
        if not session_obj or session_obj.ended:
            return None

        opponent_jid = session_obj._opponent_jid(sender)
        session_obj.ended      = True
        session_obj.winner_jid = opponent_jid

        send = getattr(self, "_direct_send", None)
        opponent_p = session_obj._player_for(opponent_jid)
        if send:
            send(BL.forfeit_text(player.name, opponent_p.name),
                 group_jid=session_obj.group_jid)

        self._pvp_end(session_obj, opponent_jid, forfeit=True)
        return None

    # Aliases — .giveup, .flee, .forfeit all resolve to the same action
    handle_pvp_giveup = handle_pvp_forfeit
    handle_pvp_flee   = handle_pvp_forfeit

    # ── End battle + rewards ──────────────────────────────────

    def _pvp_end(self, session_obj, winner_jid, forfeit=False):
        send = getattr(self, "_direct_send", None)

        loser_jid  = session_obj._opponent_jid(winner_jid)
        winner_p   = session_obj._player_for(winner_jid)
        loser_p    = session_obj._player_for(loser_jid)
        wager      = session_obj.wager

        # ── Wager transfer ────────────────────────────────────
        wager_line = ""
        if wager > 0:
            winner_p.coins += wager
            loser_p.coins  = max(0, loser_p.coins - wager)
            wager_line = f"\n💰 *+{wager}₡* transferred to @{winner_p.name}"

        # ── Draw detection ────────────────────────────────────
        winner_all_fainted = all(p.is_fainted() for p in winner_p.party)
        if winner_all_fainted:
            # True draw — return wager if any
            if wager > 0:
                winner_p.coins += wager   # undo the transfer
                loser_p.coins  += wager
                wager_line = "\n💰 _Wager returned to both players._"
            if send:
                send(
                    f"🤝 *It's a draw!*\n"
                    f"Both trainers are out of Pokémon.{wager_line}",
                    group_jid=session_obj.group_jid,
                )
        else:
            winner_p.pvp_wins   += 1
            loser_p.pvp_losses  += 1
            rewards = BL.rewards_block(
                f"@{winner_p.name}", coins=wager,
                xp=session_obj.xp_gained.get(winner_jid, 0))
            if send and rewards:
                send(rewards, group_jid=session_obj.group_jid)

        # Save both
        self._save(winner_jid, winner_p)
        self._save(loser_jid,  loser_p)

        # Clean up sessions
        self._pvp_sessions.pop(session_obj.jid_a, None)
        self._pvp_sessions.pop(session_obj.jid_b, None)
        self._session(session_obj.jid_a).state = "exploring"
        self._session(session_obj.jid_b).state = "exploring"

