# ============================================================
# NIFLHEIM — router/_constants.py
# Shared constants and legacy stubs
# ============================================================

import random, threading, time

# ── State constants ───────────────────────────────────────────
STATE_IDLE      = "idle"
STATE_EXPLORING = "exploring"
STATE_ENCOUNTER = "encounter"
STATE_BATTLE    = "battle"
STATE_DEAD      = "dead"
STATE_PVP       = "in_pvp"
STATE_RAID      = "raid"
STATE_LOCKED    = "locked"
STATE_ARENA     = "in_arena"
STATE_GYM       = "in_gym"

from config import ADMIN_SENDER  # from the ADMIN_NUMBER env var

DIRECTIONS = {"1": "North", "2": "South", "3": "East", "4": "West",
              "-1": "North", "-2": "South", "-3": "East", "-4": "West"}

DODGE_WORDS = {
    "jump", "duck", "backstep", "back-step", "block",
    "run", ".dodge", ".evade", "evade", "dodge",
}

# ── Legacy stubs — old combat/quest system ────────────────────
Monster = None
class MonsterLibrary: pass
_M = lambda *a, **k: None
class ZoneLibrary:
    @staticmethod
    def names(): return []
class SkillLibrary: pass
class BattleResolver: pass
class StatusLibrary: pass
calc_telegraph_timer = lambda *a: 0

class CombatSession:
    def __init__(self, sender):
        self.state              = STATE_IDLE
        self.encounter_monster  = None
        self.encounter_direction = None

    def transition(self, s):
        self.state = s

    def set_encounter(self, monster, direction):
        self.encounter_monster   = monster
        self.encounter_direction = direction
        self.state               = STATE_ENCOUNTER

    def clear_encounter(self):
        self.encounter_monster   = None
        self.encounter_direction = None
        self.state               = STATE_EXPLORING

    def cancel_monster_timer(self): pass
    def end_battle(self):           pass

class PvPManager:
    def __init__(self, router):
        pass  # PvP now handled by PvPMixin methods directly on router

class TutorialManager:
    @staticmethod
    def handle(*a, **k): return None

talk_to_kaelen          = lambda *a, **k: ("", None)
talk_to_ariel           = lambda *a, **k: ("", None)
talk_to_npc_unified     = lambda *a, **k: (None, None)
is_mira_quest_request   = lambda *a: False
npc_is_available        = lambda *a: True
LOCATION_NPC_MAP        = {}
NPC_DECLINE_LINES       = []

battle_hud = encounter = fight_opener = monster_telegraph = lambda *a, **k: ""
too_tired = identify = encounter_pending = encounter_walked_away = lambda *a, **k: ""
encounter_noticed = dodge_result = victory_kill = victory_level_up = lambda *a, **k: ""
victory_prof_up = victory_quest_progress = death = revive = lambda *a, **k: ""
flee_success = flee_fail = lambda *a, **k: ""

generate_board      = lambda *a, **k: []
active_quests_ui    = board_ui = quest_card_ui = quest_offer_ui = lambda *a, **k: ""
get_premade_quest   = should_offer_quest = generate_ai_quest = lambda *a, **k: None
validate_report     = get_mira_quest_offer = lambda *a, **k: None
register_quest_spawn = clear_quest_spawn = lambda *a, **k: None
can_access_rank     = lambda *a, **k: False
check_rank_up       = lambda *a, **k: None

RANK_ORDER = []; RANK_LEVEL = {}; RANK_TITLES = {}; RANK_BADGE = {}; MAX_QUESTS = 0
RANK_UP_AT = {}; ZONE_MONSTERS = {}
phase_awakening     = lambda *a, **k: None
get_quest_spawn     = lambda *a, **k: None

def _roll_monster_level(player_level):
    roll = random.random()
    if roll < 0.40:
        lo = max(1, player_level - 5)
        hi = max(1, player_level - 1)
        return random.randint(lo, hi) if lo <= hi else max(1, player_level - 1)
    elif roll < 0.70:
        return player_level
    elif roll < 0.96:
        return player_level + random.randint(1, 10)
    else:
        return player_level + random.randint(10, 20)


class BattleRoyaleManager:
    def __init__(self, router):
        self.router = router
        self.lobby  = {}
        self.open   = False
        self.timer  = None

    def start_lobby(self, sender, player_name):
        if self.open:
            return "⚔️ _A Battle Royale lobby is already open. Type *.join* to enter._"
        self.open  = True
        self.lobby = {sender: player_name}
        self.timer = threading.Timer(30.0, self._lobby_expire)
        self.timer.daemon = True
        self.timer.start()
        return self._lobby_msg()

    def join(self, sender, player_name):
        if not self.open:
            return "⚠️ _No Battle Royale is open right now._"
        if sender in self.lobby:
            return f"_You're already in the arena, {player_name}._"
        if len(self.lobby) >= 5:
            return "⚠️ _Lobby full!_"
        self.lobby[sender] = player_name
        msg = f"⚔️ *{player_name}* joined!\n" + self._lobby_msg()
        if len(self.lobby) >= 5:
            if self.timer: self.timer.cancel()
            threading.Thread(target=self._start_battle, daemon=True).start()
        return msg

    def force_start(self, sender):
        if not self.open:
            return "⚠️ _No Battle Royale is open._"
        if len(self.lobby) < 2:
            return "⚠️ _Need at least 2 players._"
        if self.timer: self.timer.cancel()
        threading.Thread(target=self._start_battle, daemon=True).start()
        return "⚡ _Force starting!_"

    def _lobby_msg(self):
        joined = "\n".join(f"  {i+1}. *{n}*" for i, n in enumerate(self.lobby.values()))
        return (
            "╭━━━━ ❰ ⚔️ BATTLE ROYALE ❱ ━━━━╮\n"
            f"Players: {len(self.lobby)}/5\n{joined}\n"
            "Type *.join* to enter.\n"
            "╰━━━━━━━━━━━━━━━━━━━━━━╯"
        )

    def _lobby_expire(self):
        if not self.open: return
        if len(self.lobby) < 2:
            self.open = False; self.lobby = {}
            send = getattr(self.router, '_direct_send', None)
            if send: send("_Battle Royale cancelled._")
            return
        threading.Thread(target=self._start_battle, daemon=True).start()

    def _start_battle(self):
        self.open = False
        players   = list(self.lobby.values())
        self.lobby = {}
        send = getattr(self.router, '_direct_send', None)
        if not send: return
        for n in ["𝟱...", "𝟰...", "𝟯...", "𝟮...", "𝟭..."]:
            send(n); time.sleep(1.0)
        send("⚔️ *𝗙𝗶𝗴𝗵𝘁!*\n\n" + "\n".join(f"{i+1}. *{n}*" for i, n in enumerate(players)))

