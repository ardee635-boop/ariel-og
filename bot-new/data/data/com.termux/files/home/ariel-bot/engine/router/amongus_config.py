"""Shared tuning values for the Niflheim Among Us engine."""

WORLD_TICK_SECONDS = 1.0
MOVEMENT_EXIT_DELAY_SECONDS = WORLD_TICK_SECONDS
ROOM_EVENT_AWARENESS_SECONDS = 2.0
# Arrivals in the same room this close together count as simultaneous (user, Session 8):
# neither gets a 'beside you' notice for the other; both rely on the paired room update.
SIMULTANEOUS_ARRIVAL_SECONDS = 1.0
CORRIDOR_ENCOUNTER_RADIUS_SECONDS = 2.0 * WORLD_TICK_SECONDS

MIN_PLAYERS = 4
MAX_PLAYERS = 20
LOBBY_INACTIVITY_TIMEOUT_SECONDS = 10 * 60

IMPOSTOR_THRESHOLDS = (7, 14)
SCIENTIST_MIN_PLAYERS = 7

PLAYER_COLORS = (
    "Red",
    "Blue",
    "Green",
    "Pink",
    "Orange",
    "Yellow",
    "Black",
    "White",
    "Purple",
    "Brown",
    "Cyan",
    "Lime",
    "Maroon",
    "Rose",
    "Banana",
    "Gray",
    "Tan",
    "Coral",
    "Turquoise",
    "Lavender",
)

KILL_RESOLUTION_SECONDS = 5   # Session 05/09: wait 5 s, then 30 s cooldown
KILL_COOLDOWN_SECONDS = 30
VENT_COOLDOWN_SECONDS = 30
SCIENTIST_VITALS_COOLDOWN_SECONDS = 20
SCIENTIST_WITNESS_COOLDOWN_SECONDS = 75
FOLLOW_REVEAL_SECONDS = 25
# Meeting timeline (Session 07/09): discussion is open for the whole meeting,
# voting opens at MEETING_VOTING_OPENS_SECONDS, the "10 seconds left" warning
# goes out MEETING_WARNING_BEFORE_END_SECONDS before the end (i.e. at 80 s).
MEETING_DURATION_SECONDS = 90
MEETING_VOTING_OPENS_SECONDS = 60
MEETING_WARNING_BEFORE_END_SECONDS = 10
MEETING_WARNING_SECONDS = MEETING_DURATION_SECONDS - MEETING_WARNING_BEFORE_END_SECONDS
# Backwards-compatible name: total meeting length (was the 60 s vote window).
MEETING_VOTE_SECONDS = MEETING_DURATION_SECONDS
# Seconds left to vote when voting opens (announced as "30 seconds left").
MEETING_VOTING_WINDOW_SECONDS = MEETING_DURATION_SECONDS - MEETING_VOTING_OPENS_SECONDS
# Meeting result (design note v5.3, 22.6): four group messages, this far apart.
# Also spaces the match-over message after a reveal. 0 = send everything at once.
EJECTION_REVEAL_STEP_SECONDS = 4.0

TASK_COOLDOWN_SECONDS = 30
TASK_INTERACTION_TIMEOUT_SECONDS = 60
GHOST_TASK_COOLDOWN_SECONDS = 50
CAMPING_TRIGGER_SECONDS = 60
FOLLOW_PROXIMITY_RADIUS_SECONDS = CORRIDOR_ENCOUNTER_RADIUS_SECONDS
VENT_MAX_SECONDS = 15
GHOST_TRAVEL_TIME_MULTIPLIER = 0.5

SABOTAGE_COOLDOWNS_SECONDS = {
    "lights": 3 * 60,
    "reactor": 5 * 60,
    "communications": 3 * 60,
    "oxygen": 4 * 60,
}
SABOTAGE_DEADLINE_RANGE_SECONDS = (30, 40)
SABOTAGE_WARNING_SECONDS = (20, 10)

# Repair rooms now live in amongus_map.SABOTAGE_STATIONS_BY_MAP (per map).

# Communications outage display (7B-2a-ii). `.players` is frozen at the
# pre-sabotage list; `.progress` is shown corrupted.
COMMS_PROGRESS_WRONG_CHANCE = 0.5      # chance the shown number is wrong
COMMS_PROGRESS_OFFSET_RANGE = (8, 30)  # size of the error when it is wrong
COMMS_PROGRESS_PLAIN_CHANCE = 0.15     # chance it is still shown normally

# Communications group restriction and post-repair report (7B-2b-i, 06E).
# While Communications is down, ordinary messages in the game group are
# DELETED (no WhatsApp announcement-only lock). Only Among Us commands, and
# the repairer's phrase answer, are kept. Needs the bot to be group admin.
COMMS_RESTRICTION_ENABLED = True
# Meetings are discussed in the game group, so the restriction is lifted while
# a meeting runs and re-applied afterwards if Communications is still down.
COMMS_RESTRICTION_LIFTED_DURING_MEETINGS = True
# First word of every message that counts as an Among Us command (kept while
# the restriction is on; everything else is deleted).
COMMS_GROUP_ALLOWED_COMMANDS = frozenset({
    ".amongus", ".pokemon", ".lobby", ".join", ".leave", ".amenu",
    ".endgame", ".gc", ".dm", ".vote", ".task", ".tasks", ".m", ".stop", ".goback",
    ".where", ".map", ".status", ".kill", ".players", ".progress", ".vent", ".vitals",
    ".witness", ".cds", ".cooldown", ".follow", ".unfollow", ".cscene",
    ".crimescene", ".cs", ".report", ".meeting", ".say", ".sabotage", ".scan",
    ".ready", ".repair",
})
COMMS_INACTIVITY_REPORT_SECONDS = 60

# Compatibility values used only by the older trial mechanics while
# later sessions replace them with the Niflheim task/sabotage rules.
LEGACY_LINGER_THRESHOLD_SECONDS = 15
LEGACY_MELTDOWN_DOOM_SECONDS = 30
LEGACY_COOLDOWN_ACTION_SECONDS = 6


def impostor_count(player_count):
    if player_count < IMPOSTOR_THRESHOLDS[0]:
        return 1
    if player_count < IMPOSTOR_THRESHOLDS[1]:
        return 2
    return 3

# ── Paired-scan sabotages: O₂ and Reactor (Session 7C) ─────
PAIRED_SCAN_WINDOW_SECONDS = 2.0
# A lone scan is dropped this long after its window closes, so a partner
# scan stamped inside the window is never lost to tick timing.
PAIRED_SCAN_EXPIRY_MARGIN_SECONDS = WORLD_TICK_SECONDS
# Confirmed (06C): only living Crewmates repair any sabotage.
PAIRED_SABOTAGE_IMPOSTORS_CAN_REPAIR = False
# O2 only: optional `.ready` sends "3", "2", "1", "SCAN NOW!". The design does
# not specify the gap between the four messages; 1 s is an implementation
# default (UNDECIDED - change here if the user picks another spacing).
READY_COUNTDOWN_STEP_SECONDS = 1.0


# ── Solo test mode (.lobby test) ────────────────────────────
# Dummy players are silent stand-ins: they get no DMs, never move, never vote.
DUMMY_PREFIX = "test-dummy-"


def is_dummy(jid):
    return str(jid).startswith(DUMMY_PREFIX)
