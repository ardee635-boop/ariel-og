import random
import sys
import threading
import types
import unittest
from pathlib import Path


BOT_ROOT = Path(__file__).resolve().parents[1]
ENGINE_DIR = BOT_ROOT / "engine"
ROUTER_DIR = ENGINE_DIR / "router"
sys.path[:0] = [str(ENGINE_DIR), str(ENGINE_DIR / "pokemon"), str(ENGINE_DIR / "core")]

router_package = types.ModuleType("router")
router_package.__path__ = [str(ROUTER_DIR)]
sys.modules.setdefault("router", router_package)

from router.amongus import AmongUsManager  # noqa: E402
from router.amongus_game import Game, PlayerState  # noqa: E402
from router.amongus_map import get_map  # noqa: E402
from router.amongus_movement import MovementEngine  # noqa: E402
from router.amongus_sabotage import CommunicationsSabotage  # noqa: E402
from router import amongus_comms as D  # noqa: E402
from router import amongus_config as C  # noqa: E402


GAME_GROUP = "game@g.us"


class FakeManager:
    def __init__(self):
        self.sent = []
        self.broadcasts = []

    def _push_dm(self, player, message, **kwargs):
        self.sent.append((player, message))

    def _broadcast(self, message, **kwargs):
        self.broadcasts.append(message)


class FakeRouter:
    def _direct_send(self, *args, **kwargs):
        return None


def make_game():
    game = Game.__new__(Game)
    game.manager = FakeManager()
    game.group_jid = GAME_GROUP
    game.map = get_map()
    game.map_id = game.map.id
    game.events = []
    game.players = {}
    game._bodies = {}
    game._corpses = {}
    game._reported_crime_scenes = []
    game._meltdown = None
    game._sabotages = {}
    game._ensure_sabotage_registry()
    game._team_tasks = []
    game._task_sequence = 0
    game._interaction_sequence = 0
    game._closed_task_prompts = {}
    game.over = False
    game.lock = threading.RLock()
    game._stop_event = threading.Event()
    game._timers = set()
    game._meeting = None
    roles = {
        "red": "crewmate",
        "blue": "crewmate",
        "green": "scientist",
        "pink": "impostor",
    }
    colors = {"red": "Red", "blue": "Blue", "green": "Green", "pink": "Pink"}
    for jid, role in roles.items():
        player = PlayerState(jid, role, colors[jid], game.map)
        player.room_entered_at = 0.0
        player.stopped_since = 0.0
        player.room = "CAFETERIA"
        player.tasks = []
        game.players[jid] = player
    game.color_to_jid = {p.color.lower(): p.jid for p in game.players.values()}
    game.movement = MovementEngine(game)
    return game


def close_game(game):
    game.close()


def comms_state(game):
    return game._sabotages["communications"]["state"]


def players_text(game):
    return game.handle("red", ".players", received_at_ms=1_000)


class AmongUsSessionSevenB2aiiTests(unittest.TestCase):
    def test_players_live_when_no_outage(self):
        game = make_game()
        try:
            text = players_text(game)
            self.assertIn("Players still alive (4)", text)
            game.players["blue"].alive = False
            self.assertIn("Players still alive (3)", players_text(game))
            self.assertIn("~Blue~", players_text(game))
        finally:
            close_game(game)

    def test_players_frozen_at_pre_sabotage_state_until_repair(self):
        game = make_game()
        try:
            game.players["green"].alive = False  # dead before the outage
            game._cmd_sabotage(game.players["pink"], "communications", now=100)
            frozen = players_text(game)
            self.assertIn("Players still alive (3)", frozen)
            self.assertIn("~Green~", frozen)

            game.players["blue"].alive = False      # dies during outage
            game.players["pink"].departed = True     # leaves during outage
            self.assertEqual(players_text(game), frozen)
            self.assertNotIn("notice", frozen.lower())

            game._repair_sabotage("communications", game.players["pink"], now=200)
            live = players_text(game)
            self.assertNotEqual(live, frozen)
            self.assertIn("Players still alive (1)", live)
            self.assertIn("~Blue~", live)
            self.assertNotIn("pink", live)
        finally:
            close_game(game)

    def test_new_outage_takes_a_fresh_snapshot(self):
        game = make_game()
        try:
            game._cmd_sabotage(game.players["pink"], "communications", now=100)
            game._repair_sabotage("communications", game.players["red"], now=110)
            game.players["blue"].alive = False
            game._cmd_sabotage(game.players["pink"], "communications", now=400)
            self.assertIn("Players still alive (3)", players_text(game))
            self.assertIn("~Blue~", players_text(game))
        finally:
            close_game(game)

    def test_game_end_clears_snapshot(self):
        game = make_game()
        try:
            game._cmd_sabotage(game.players["pink"], "communications", now=100)
            game._end_game("test over")
            self.assertIsNone(game._sabotages["communications"].frozen_players)
        finally:
            close_game(game)

    def test_lights_does_not_freeze_players(self):
        game = make_game()
        try:
            game._cmd_sabotage(game.players["pink"], "lights", now=100)
            game.players["blue"].alive = False
            self.assertIn("Players still alive (3)", players_text(game))
        finally:
            close_game(game)

    def test_progress_unchanged_without_outage(self):
        game = make_game()
        try:
            game._team_tasks = [{"done": True}, {"done": False}]
            game._comms_rng = random.Random(1)
            self.assertEqual(game._cmd_progress(game.players["red"]), "*Team task progress*\n1/2 tasks complete (50%).")
        finally:
            close_game(game)

    def test_progress_garbled_during_outage_and_normal_after(self):
        game = make_game()
        try:
            game._team_tasks = [{"done": True}, {"done": False}]
            game._cmd_sabotage(game.players["pink"], "communications", now=100)
            game._comms_rng = random.Random(7)
            readings = {game._cmd_progress(game.players["red"]) for _ in range(60)}
            self.assertGreater(len(readings), 10)
            self.assertTrue(any(r != "*Team task progress*\n1/2 tasks complete (50%)." for r in readings))
            game._repair_sabotage("communications", game.players["pink"], now=200)
            self.assertEqual(game._cmd_progress(game.players["red"]), "*Team task progress*\n1/2 tasks complete (50%).")
        finally:
            close_game(game)

    def test_garble_mix_wrong_and_right_numbers_scripts_and_languages(self):
        rng = random.Random(42)
        results = [D.garble_progress(40, rng) for _ in range(2000)]
        accurate = sum(r["accurate"] for r in results)
        self.assertTrue(700 < accurate < 1300)  # ~50% still correct
        styles = {r["style"] for r in results}
        self.assertEqual(styles, set(D.SCRIPT_STYLES + D.LANGUAGE_STYLES + ("plain",)))
        for r in results:
            self.assertTrue(0 <= r["shown"] <= 100)
            self.assertEqual(r["accurate"], r["shown"] == 40)
            if not r["accurate"]:
                self.assertGreaterEqual(abs(r["shown"] - 40), 8)
        plain = sum(r["style"] == "plain" for r in results)
        self.assertTrue(150 < plain < 450)  # ~15%

    def test_garble_edges_stay_in_range(self):
        rng = random.Random(3)
        for true in (0, 1, 99, 100):
            for _ in range(300):
                r = D.garble_progress(true, rng)
                self.assertTrue(0 <= r["shown"] <= 100)
                self.assertEqual(r["accurate"], r["shown"] == true)

    def test_renderings_in_other_writing_systems(self):
        self.assertEqual(D.render_percent(40, "plain"), "40%")
        self.assertEqual(D.render_percent(57, "arabic_indic"), "٥٧٪")
        self.assertEqual(D.render_percent(57, "persian"), "۵۷٪")
        self.assertEqual(D.render_percent(57, "devanagari"), "५७%")
        self.assertEqual(D.render_percent(100, "thai"), "๑๐๐%")
        self.assertEqual(D.render_percent(42, "roman"), "XLII%")
        self.assertEqual(D.render_percent(0, "roman"), "N%")

    def test_number_words(self):
        cases = {
            "spanish": {0: "cero", 21: "veintiuno", 40: "cuarenta", 57: "cincuenta y siete", 100: "cien"},
            "french": {0: "zéro", 21: "vingt et un", 71: "soixante et onze", 77: "soixante-dix-sept",
                       80: "quatre-vingts", 91: "quatre-vingt-onze", 99: "quatre-vingt-dix-neuf", 100: "cent"},
            "german": {0: "null", 1: "eins", 21: "einundzwanzig", 30: "dreißig", 99: "neunundneunzig", 100: "hundert"},
            "italian": {0: "zero", 21: "ventuno", 28: "ventotto", 33: "trentatré", 100: "cento"},
            "chinese": {0: "零", 10: "十", 15: "十五", 30: "三十", 57: "五十七", 100: "一百"},
        }
        fns = {"spanish": D.spanish, "french": D.french, "german": D.german,
               "italian": D.italian, "chinese": D.chinese}
        for lang, table in cases.items():
            for n, word in table.items():
                self.assertEqual(fns[lang](n), word, (lang, n))
        self.assertEqual(D.render_percent(30, "german"), "dreißig Prozent")
        self.assertEqual(D.render_percent(30, "chinese"), "百分之三十")

    def test_every_value_renders_in_every_style(self):
        for style in ("plain",) + D.SCRIPT_STYLES + D.LANGUAGE_STYLES:
            for n in range(101):
                self.assertTrue(D.render_percent(n, style))

    def test_other_commands_unaffected_by_outage(self):
        game = make_game()
        try:
            game._cmd_sabotage(game.players["pink"], "communications", now=100)
            self.assertIn("Cafeteria", game.handle("red", ".where", received_at_ms=1_000).title())
        finally:
            close_game(game)


if __name__ == "__main__":
    unittest.main()
