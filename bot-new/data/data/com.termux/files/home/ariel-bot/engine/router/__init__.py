# ============================================================
# NIFLHEIM — router/__init__.py
# CommandRouter — assembles all mixins
# ============================================================

import sys
from database import Database
from models import Player
from interfaces import UI

from ._constants import (
    STATE_IDLE, STATE_EXPLORING, STATE_ENCOUNTER, STATE_BATTLE,
    STATE_DEAD, STATE_PVP, STATE_RAID, STATE_LOCKED,
    PvPManager, BattleRoyaleManager,
)
# CombatSession must come from combat_session.py (the real implementation —
# set_trainer_battle, arena_next_trainer_mon, clear_arena, locks, etc.).
# ._constants.CombatSession is a gutted legacy stub left over from an old
# refactor; importing it here was silently breaking every arena battle.
from combat_session import CombatSession
from .handle       import HandleMixin
from .pokemon      import PokemonMixin
from .registration import RegistrationMixin
from .movement     import MovementMixin
from .admin        import AdminMixin
from .utils        import UtilsMixin
from .lord         import LordMixin
from .shop         import ShopMixin
from .pvp          import PvPMixin
from .quests       import QuestMixin, on_defeat, on_catch, on_move
from .amongus      import AmongUsCoordinator
from .rpg          import RpgManager
from .chat         import ChatManager
from .normal       import NormalManager
from .niflheim     import NiflheimManager
from .info_cmd     import InfoMixin

import battle as _battle_mod
try:
    _battle_mod.register_quest_hooks(on_defeat, on_catch)
except Exception:
    pass


class CommandRouter(
    HandleMixin,
    PokemonMixin,
    RegistrationMixin,
    MovementMixin,
    AdminMixin,
    UtilsMixin,
    LordMixin,
    ShopMixin,
    PvPMixin,
    QuestMixin,
    InfoMixin,
):
    def __init__(self, db=None):
        self.db           = db or Database()
        self.cache        = {}
        self.sessions     = {}
        self.reg          = {}
        self._board_cache = {}
        self.pvp          = PvPManager(self)
        self.br           = BattleRoyaleManager(self)
        self.amongus      = AmongUsCoordinator(self)
        self.rpg          = RpgManager(self)
        self.chat         = ChatManager(self)
        self.normal       = NormalManager(self)
        self.niflheim     = NiflheimManager(self)
        self._outbox      = {}
        self._restore_reg()

    def _session(self, sender):
        if sender not in self.sessions:
            self.sessions[sender] = CombatSession(sender)
        return self.sessions[sender]

    def _restore_reg(self):
        import json
        try:
            rows = self.db.conn.execute(
                "SELECT sender, data FROM registrations"
            ).fetchall()
            for sender, data in rows:
                try: self.reg[sender] = json.loads(data)
                except: pass
        except: pass

    def _get(self, sender):
        if sender in self.cache: return self.cache[sender]
        p = self.db.load(sender)
        if p: self.cache[sender] = p
        return p

    def _save(self, sender, player):
        self.cache[sender] = player
        self.db.save(sender, player)

    # _normalize() now comes from UtilsMixin (whitespace cleanup only).
    # The old _WORD_ALIASES system that rewrote bare "y"/"n"/"1"-"4"/etc.
    # into ".yes"/".no"/".1"-".4" globally was dead weight left over from
    # the old multi-step registration flow — registration is now instant
    # (see registration.py:_reg_finish) and doesn't ask yes/no questions.
    # It was also actively harmful: it made any unregistered sender who
    # typed a bare "y"/"n" get treated as if they'd typed a dash-command,
    # and made registered players who typed a bare "1"-"4" while chatting
    # silently move their character. Removed.

    # Legacy stubs for old combat — remove when rewritten
    def _handle_dodge(self, sender, player, session, dodge_word): return None
    def _commit_fight(self, sender, player, session, monster):   return None
    def _attack(self, sender, player, session, skill_input):     return None
    def _handle_victory(self, sender, player, session, monster, combat_log): return None
    def _handle_death(self, sender, player, combat_log=""):      return None
    def _start_delayed_attack(self, *a):                         return None
    def _start_monster_idle_timer(self, *a):                     return None

