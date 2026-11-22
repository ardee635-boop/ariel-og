# ============================================================
# RAPHAEL – COMBAT_SESSION.PY
# Unified combat state — one object per active player fight
# ============================================================

import time
import threading
import random

# ── Session states ────────────────────────────────────────────
STATE_IDLE       = "idle"
STATE_EXPLORING  = "exploring"
STATE_ENCOUNTER  = "encounter"   # saw monster, not yet fighting
STATE_BATTLE     = "battle"
STATE_DEAD       = "dead"
STATE_PVP        = "in_pvp"
STATE_RAID       = "in_raid"
STATE_ARENA      = "in_arena"
STATE_ARENA_PENDING = "in_arena_pending"  # between .next and the 5s HUD delay
STATE_GYM        = "in_gym"
STATE_GYM_PENDING = "in_gym_pending"      # between .next and the 5s HUD delay (gym version)
STATE_LOCKED     = "locked"      # throttle lock

# ── Monster post-dodge decisions ──────────────────────────────
# 30% attack again, 40% wait 10s, 30% wait for player
DODGE_FOLLOWUP = [
    ("attack",      0.30),
    ("wait_timed",  0.40),
    ("wait_player", 0.30),
]


class CombatSession:
    """
    Holds all state for one player's active combat.
    Attach to player object as player.session
    """

    def __init__(self, sender):
        self.pending_skill    = None   # skill dict being cast
        self.pending_cast_end = 0.0    # time.time() when cast completes
        self.cast_timer       = None   # threading.Timer
        self.sender          = sender
        self.state           = STATE_IDLE

        # Monster refs
        self.monster         = None
        self.multi_monsters  = []

        # Encounter pending
        self.encounter_monster     = None
        self.encounter_direction   = None   # direction player came from (block this)
        self.encounter_timer       = None   # threading.Timer
        # Arena trainer battle state
        self.arena_trainer_name  = None
        self.arena_trainer_team  = []
        self.arena_trainer_index = 0
        self.arena_round         = 0

        # Battle context — what kind of fight is this?
        # "wild"    — standard wild encounter
        # "trainer" — arena PvE trainer gauntlet
        # "gym"     — gym leader gauntlet (elders + leader)
        # "pvp"     — player vs player
        # None      — not in a fight
        self.battle_context = None

        # Battle
        self.monster_timer         = None   # idle attack timer
        self.last_attack_tag       = None

        # Message IDs for quoting
        self.last_player_msg_id    = None
        self.last_monster_msg_id   = None
        self.last_system_msg_id    = None

        # Set True when the player explicitly cancels an idle timer (by acting).
        # Threads check this to know they were pre-empted, not just superseded.
        self._timer_cancelled      = False

        # Dodge / fumble tracking (separate)
        self.dodge_chain           = 0
        self.fumble_chain          = 0

        # Spam throttle
        self.skill_timestamps      = []     # list of time.time() per skill use
        self.throttle_until        = 0      # time.time() when throttle lifts

        # Queue offset for staggered delayed messages
        self.queue_offset          = 0.0

        # Session lock
        self._lock                 = threading.Lock()

    # ── State transitions ─────────────────────────────────────

    def transition(self, new_state):
        """Thread-safe state transition. Returns True if successful."""
        with self._lock:
            self.state = new_state
            return True

    def try_transition(self, from_state, new_state):
        """Only transition if currently in from_state."""
        with self._lock:
            if self.state != from_state:
                return False
            self.state = new_state
            return True

    # ── Encounter ─────────────────────────────────────────────

    def set_encounter(self, monster, came_from_direction=None):
        """Set up a pending encounter."""
        self.encounter_monster   = monster
        self.encounter_direction = came_from_direction
        self.transition(STATE_ENCOUNTER)

    def clear_encounter(self):
        self.cancel_encounter_timer()
        self.encounter_monster   = None
        self.encounter_direction = None

    def start_encounter_timer(self, callback, seconds=30):
        """30s timer — fires callback if player doesn't act."""
        self.cancel_encounter_timer()
        t = threading.Timer(seconds, callback)
        t.daemon = True
        t.start()
        self.encounter_timer = t

    def cancel_encounter_timer(self):
        if self.encounter_timer:
            try:
                self.encounter_timer.cancel()
            except Exception:
                pass
            self.encounter_timer = None

    # ── Battle ────────────────────────────────────────────────

    def start_battle(self, monster, multi=None):
        """Commit to battle from encounter."""
        self.monster         = monster
        self.multi_monsters  = multi or []
        self.dodge_chain     = 0
        self.fumble_chain    = 0
        self.clear_encounter()
        self.battle_context  = "wild"
        self.transition(STATE_BATTLE)

    def arm_trainer_battle(self, trainer_name: str, team: list, round_num: int):
        """Stage an arena trainer battle without starting it yet.
        State stays STATE_ARENA_PENDING until commit_trainer_battle() is called
        from the delayed thread, blocking .atk/.run etc. during the 5s window."""
        self.arena_trainer_name  = trainer_name
        self.arena_trainer_team  = list(team)
        self.arena_trainer_index = 0
        self.arena_round         = round_num
        self.transition(STATE_ARENA_PENDING)

    def commit_trainer_battle(self):
        """Called from the delayed thread after the 5s wait — actually starts the battle."""
        from battle import _init_modifier_stack
        first_mon = self.arena_trainer_team[0]
        self.multi_monsters    = []
        self.dodge_chain       = 0
        self.fumble_chain      = 0
        self.clear_encounter()
        self.monster           = first_mon
        self.encounter_monster = first_mon
        # Preserve whichever trainer-battle context was already armed
        # (gym.py / arena.py both call arm_trainer_battle() first and
        # set battle_context before this runs) — don't clobber "gym"
        # back to "trainer", or gym rounds after the first silently
        # get treated as arena rounds.
        if getattr(self, "battle_context", None) not in ("gym", "trainer"):
            self.battle_context = "trainer"
        self.battle_state = {
            "wild":          first_mon,
            "participants":  {},
            "turn":          1,
            "player_stack":  _init_modifier_stack(),
            "wild_stack":    _init_modifier_stack(),
        }
        self.state = "battle_menu"

    def set_trainer_battle(self, trainer_name: str, team: list, round_num: int):
        """Set up an arena trainer battle. Starts battle with first Pokémon."""
        self.arena_trainer_name  = trainer_name
        self.arena_trainer_team  = list(team)      # full team
        self.arena_trainer_index = 0               # which mon is active
        self.arena_round         = round_num
        first_mon = team[0]
        self.start_battle(first_mon)

    def arena_next_trainer_mon(self):
        """
        Advance to next trainer Pokémon after current faints.
        Returns next mon dict or None if all fainted.
        """
        if not hasattr(self, "arena_trainer_team") or not self.arena_trainer_team:
            return None
        self.arena_trainer_index = getattr(self, "arena_trainer_index", 0) + 1
        if self.arena_trainer_index < len(self.arena_trainer_team):
            next_mon = self.arena_trainer_team[self.arena_trainer_index]
            self.monster           = next_mon
            self.encounter_monster = next_mon
            if hasattr(self, "battle_state") and self.battle_state:
                self.battle_state["wild"] = next_mon
            return next_mon
        return None

    def clear_arena(self):
        """Clear arena trainer state."""
        self.arena_trainer_name  = None
        self.arena_trainer_team  = []
        self.arena_trainer_index = 0
        self.arena_round         = 0
        self.battle_context      = None

    def end_battle(self):
        self.cancel_monster_timer()
        self.monster        = None
        self.multi_monsters = []
        self.dodge_chain    = 0
        self.fumble_chain   = 0
        self.queue_offset   = 0.0
        self.battle_context = None

    def start_monster_timer(self, callback, seconds=0):
        """Start monster attack cycle. seconds=0 fires immediately in a thread."""
        self.cancel_monster_timer()
        self._timer_cancelled = False
        if seconds == 0:
            t = threading.Thread(target=callback, daemon=True)
            t.start()
            self.monster_timer = t
        else:
            t = threading.Timer(seconds, callback)
            t.daemon = True
            t.start()
            self.monster_timer = t
        return t

    def cancel_monster_timer(self):
        if self.monster_timer:
            try:
                self.monster_timer.cancel()
            except Exception:
                pass
            self.monster_timer    = None
            self._timer_cancelled = True  # signal: player acted, thread should abort

    def monster_timer_active(self):
        """Returns True if a monster attack cycle is currently running."""
        t = self.monster_timer
        if t is None: return False
        if isinstance(t, threading.Timer): return t.is_alive()
        if isinstance(t, threading.Thread): return t.is_alive()
        return False

    # ── Action queue ──────────────────────────────────────────

    def queue_action(self, callback, delay=0):
        """Schedule a callback after delay seconds (0 = immediate thread)."""
        return self.start_monster_timer(callback, seconds=delay)

    # ── Spam throttle ─────────────────────────────────────────

    def check_throttle(self):
        """Returns (is_throttled, seconds_remaining)."""
        now = time.time()
        if now < self.throttle_until:
            return True, round(self.throttle_until - now, 1)
        return False, 0

    def record_skill_use(self):
        """
        Record a skill use. If 5 uses in 4s, apply 3s throttle.
        Returns True if throttle just triggered.
        """
        now = time.time()
        self.skill_timestamps = [t for t in self.skill_timestamps if now - t < 4.0]
        self.skill_timestamps.append(now)
        if len(self.skill_timestamps) >= 5:
            self.throttle_until    = now + 3.0
            self.skill_timestamps  = []
            return True
        return False

    # ── Queue offset ──────────────────────────────────────────

    def next_queue_delay(self, step=1.5):
        """Returns next staggered delay and advances offset."""
        self.queue_offset += step
        return self.queue_offset

    def reset_queue(self):
        self.queue_offset = 0.0

    # ── Dodge / fumble ────────────────────────────────────────

    def roll_fumble(self, player_spd, player_hp, player_max_hp, has_debuff=False):
        """
        Roll fumble chance. Returns True if fumbled.
        Factors: low SPD, high dodge_chain, low HP %, debuffs.
        """
        base = 0.08  # 8% base fumble

        # SPD factor — lower SPD = higher fumble
        spd_pen = max(0, (20 - player_spd) * 0.005)

        # Dodge chain — each consecutive dodge adds 3%
        chain_pen = self.dodge_chain * 0.03

        # Low HP panic — below 30% HP adds up to 5%
        hp_pct = player_hp / player_max_hp if player_max_hp > 0 else 1
        hp_pen = max(0, (0.30 - hp_pct) * 0.15) if hp_pct < 0.30 else 0

        # Debuff (stun, blind etc)
        debuff_pen = 0.08 if has_debuff else 0

        chance = min(0.45, base + spd_pen + chain_pen + hp_pen + debuff_pen)
        return random.random() < chance

    def fumble_damage_mult(self):
        """Returns damage multiplier on fumble. Range 0.4 to 1.3."""
        base = 0.40 + (self.fumble_chain * 0.10)
        return min(1.30, base)

    def fumble_byproduct(self):
        """Random byproduct on fumble. Returns effect name or None."""
        roll = random.random()
        if roll < 0.15:
            return "self_stun"      # skip next action
        if roll < 0.28:
            return "def_down"       # DEF -20% for 1 turn
        if roll < 0.38:
            return "face_plant"     # -10% HP immediately
        return None

    # ── Monster post-dodge decision ───────────────────────────

    @staticmethod
    def roll_monster_followup():
        """30/40/30 split after player dodges."""
        roll = random.random()
        if roll < 0.30:
            return "attack"
        if roll < 0.70:
            return "wait_timed"
        return "wait_player"

    # ── Serialise (for DB save) ───────────────────────────────

    def to_dict(self):
        """Minimal serialisation — timers not included."""
        return {
            "state":         self.state,
            "dodge_chain":   self.dodge_chain,
            "fumble_chain":  self.fumble_chain,
            "throttle_until":self.throttle_until,
        }

    @classmethod
    def from_dict(cls, sender, d):
        s = cls(sender)
        s.state          = d.get("state", STATE_IDLE)
        s.dodge_chain    = d.get("dodge_chain", 0)
        s.fumble_chain   = d.get("fumble_chain", 0)
        s.throttle_until = d.get("throttle_until", 0)
        # If was in battle/encounter on reload, reset to exploring (timer lost)
        if s.state in (STATE_BATTLE, STATE_ENCOUNTER, "battle_menu"):
            s.state = STATE_EXPLORING
        # If was mid-5s arena window on reload, roll back to STATE_ARENA so player can .next again
        if s.state == STATE_ARENA_PENDING:
            s.state = STATE_ARENA
        # Same rollback for the gym's equivalent pending window
        if s.state == STATE_GYM_PENDING:
            s.state = STATE_GYM
        return s

    # ── Cast ──────────────────────────────────────────────────

    def start_cast(self, skill, cast_time):
        """Begin casting — router fires actual resolve after delay."""
        self.pending_skill    = skill
        self.pending_cast_end = time.time() + cast_time
        self.cast_timer       = None  # router handles the thread

    def cancel_cast(self):
        """Player broke cast — cancel and return the pending skill."""
        if self.cast_timer:
            try: self.cast_timer.cancel()
            except: pass
            self.cast_timer = None
        sk = self.pending_skill
        self.pending_skill    = None
        self.pending_cast_end = 0.0
        return sk

    def is_casting(self):
        return self.pending_skill is not None and time.time() < self.pending_cast_end

