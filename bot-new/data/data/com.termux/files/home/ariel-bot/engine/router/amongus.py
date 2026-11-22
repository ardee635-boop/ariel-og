# ============================================================
# NIFLHEIM — router/amongus.py
# Among Us mode — fully isolated from the Pokémon/Player system.
# No registration, no shared state, no Supabase persistence.
#
# Architecture note: handle.py calls AmongUsManager.pre_dispatch()
# as the VERY FIRST thing in handle(), before the Pokémon
# registration gate or stage machine ever run. If pre_dispatch
# returns NOT_HANDLED, handle() falls through to normal Pokémon
# logic untouched. Anything else IS the final response (even None,
# which means "handled silently, no reply").
# ============================================================

import threading

from . import amongus_config as C
from . import amongus_images as IMG
from . import amongus_map as M
from . import amongus_stage as STAGE
from .amongus_registry import GroupRegistry

# Sentinel — distinguishes "not our command, let Pokémon handle it"
# from a real (possibly None/silent) Among Us response.
NOT_HANDLED = object()
DELETE_INCOMING_MESSAGE = {"__amongus_action__": "delete_incoming_message"}
COMMS_ANSWER_IN_GROUP_TEXT = (
    "📡 _Communications answers must be given in the game group: reply to the "
    "scrambled transmission message there, or send `.task answer <phrase>` "
    "there. Private answers are not accepted._"
)


def LINK_REPLY(kind, group_jid, text):
    """Ask the bot to answer with a real WhatsApp link (resolved at send time).

    kind: "dm" (chat with Ariel) or "game_group" (invite link of group_jid).
    """
    return {
        "__amongus_action__": "link_reply",
        "kind": kind,
        "group_jid": group_jid,
        "text": text,
    }

MIN_PLAYERS = C.MIN_PLAYERS
MAX_PLAYERS = C.MAX_PLAYERS
INACTIVITY_TIMEOUT_SECONDS = C.LOBBY_INACTIVITY_TIMEOUT_SECONDS


def _impostor_count(player_count):
    return C.impostor_count(player_count)


class Lobby:
    """A single Among Us lobby, owned by one WhatsApp group."""

    _id_counter = 0
    _id_lock = threading.Lock()

    def __init__(self, group_jid, host, map_id=M.DEFAULT_MAP_ID):
        with Lobby._id_lock:
            Lobby._id_counter += 1
            self.id = Lobby._id_counter
        self.group_jid = group_jid
        self.host = host
        self.map_id = map_id
        self.players = [host]
        self.started = False
        self.test_role = None   # set by .lobby test: the host's forced role

    def roster_text(self):
        return "\n".join(f"{i + 1}. Player {i + 1}" for i in range(len(self.players)))

    def player_number(self, jid):
        try:
            return self.players.index(jid) + 1
        except ValueError:
            return None


class AmongUsManager:
    """Game/lobby state for exactly one WhatsApp group."""

    def __init__(self, router, group_jid):
        self.router = router
        self.group_jid = group_jid
        self._lock = threading.RLock()
        self.amongus_on = set()       # senders currently in Among Us mode
        self.pokemon_off = set()      # senders who've disabled Pokémon commands
        self.lobby = None
        self.game = None
        self._timer = None            # inactivity threading.Timer
        self._ghosts_group_jid = None # picked from the owner registry at match start
        self.ghost_picker = None      # set by the coordinator: manager -> ghost group jid or None

    # ── Mode toggle — always reachable, regardless of current mode ──
    def pre_dispatch(
        self,
        sender,
        text,
        group_jid=None,
        received_at_ms=None,
        quoted_text=None,
        message_key=None,
    ):
        with self._lock:
            return self._pre_dispatch(
                sender,
                text,
                group_jid,
                received_at_ms,
                quoted_text,
                message_key,
            )

    def _pre_dispatch(
        self,
        sender,
        text,
        group_jid=None,
        received_at_ms=None,
        quoted_text=None,
        message_key=None,
    ):
        raw = (text or "").strip()
        low = raw.lower()

        if (
            group_jid == self.group_jid
            and self.game
            and not self.game.over
            and sender in self.game.players
        ):
            player = self.game.players[sender]
            if not player.alive and not player.departed:
                return DELETE_INCOMING_MESSAGE

        # Communications is down: only Among Us commands (and the repairer's
        # phrase answer) stay in the game group; everything else is deleted.
        if (
            group_jid
            and group_jid == self.group_jid
            and self.game
            and not self.game.over
            and not self.game.group_message_allowed(sender, raw, quoted_text)
        ):
            return DELETE_INCOMING_MESSAGE

        if low == ".amongus on":
            self.amongus_on.add(sender)
            return (
                "🔪 *Among Us mode ON.*\n\n"
                "Use *.lobby open* to host a game, or *.join* to enter an open lobby.\n\n"
                "Use *.amongus off* to turn it off for this group."
            )
        if low == ".amongus off":
            self.amongus_on.discard(sender)
            self._remove_player(sender)
            return "👋 *Among Us mode OFF.*"

        if low == ".pokemon off":
            self.pokemon_off.add(sender)
            return "⏸️ *Pokémon commands disabled.* _.pokemon on to re-enable._"
        if low == ".pokemon on":
            self.pokemon_off.discard(sender)
            return "▶️ *Pokémon commands re-enabled.*"

        if low == ".amenu":
            return self._amenu()

        # In a group, the JS pool toggle swallows ".amongus on" (it flips the
        # group pool and never reaches Python), so players could never enter
        # amongus_on. Joining a lobby is opt-in enough: auto-enable the sender.
        if group_jid and (low.split() or [""])[0] in (".lobby", ".join"):
            self.amongus_on.add(sender)

        if sender in self.amongus_on or self.contains_player(sender):
            return self._dispatch(
                sender,
                raw,
                group_jid,
                received_at_ms,
                quoted_text,
                message_key,
            )

        if sender in self.pokemon_off:
            return None  # swallow — Pokémon commands ignored for this sender

        return NOT_HANDLED

    # ── Among Us command dispatch ──
    def _dispatch(
        self,
        sender,
        text,
        group_jid,
        received_at_ms=None,
        quoted_text=None,
        message_key=None,
    ):
        parts = text.split()
        if not parts:
            return None
        cmd = parts[0].lower()
        arg = parts[1].lower() if len(parts) > 1 else ""

        # Lobby commands (always reachable even mid-game)
        if cmd == ".lobby" and arg == "open":
            return self._lobby_open(sender, group_jid)
        if cmd == ".lobby" and arg == "start":
            return self._lobby_start(sender, received_at_ms)
        if cmd == ".lobby" and arg == "test":
            return self._lobby_test(
                sender,
                parts[2].lower() if len(parts) > 2 else "",
                received_at_ms,
            )
        if cmd == ".lobby" and arg == "list":
            return self._lobby_list()
        if cmd == ".lobby" and arg == "map":
            return self._lobby_set_map(sender, " ".join(parts[2:]))
        if cmd == ".join":
            return self._lobby_join(sender, group_jid)
        if cmd == ".leave":
            return self._lobby_leave(sender)
        if cmd == ".amenu":
            return self._amenu()
        if cmd == ".endgame":
            return self._end_game_by_host(sender)
        if cmd == ".map" and not (self.game and not self.game.over):
            return self._lobby_map(sender)

        # In-game commands — route to the active Game
        if self.game and not self.game.over:
            if group_jid:
                # Public voting is intentional; all other game commands can
                # reveal private role, location, or task information.
                if cmd == ".vote":
                    return self.game.handle_gc_vote(
                        sender,
                        text,
                        received_at_ms=received_at_ms,
                    )
                if self.game.is_comms_phrase_answer(sender, text, quoted_text):
                    # Communications repair: the answer is given in the group.
                    reply = self.game.handle(
                        sender,
                        text,
                        received_at_ms=received_at_ms,
                        quoted_text=quoted_text,
                    )
                    player = self.game.players.get(sender)
                    if reply and player and player.color:
                        reply = f"*{player.color}:* {reply}"
                    return reply
                if cmd in C.COMMS_GROUP_ALLOWED_COMMANDS:
                    return (
                        "📩 _Game commands are private. Message Ariel directly; "
                        "use .vote in the group during meetings._"
                    )
                return NOT_HANDLED  # not an Among Us command: no reply from here
            if self.game.is_comms_phrase_answer(sender, text, quoted_text):
                return COMMS_ANSWER_IN_GROUP_TEXT
            return self.game.handle(
                sender,
                text,
                received_at_ms=received_at_ms,
                quoted_text=quoted_text,
            )

        # Anything else is not an Among Us command: no error, the rest of the
        # bot handles it exactly as if the Among Us pool were off.
        return NOT_HANDLED

    # ── Lobby actions ──
    def _lobby_open(self, sender, group_jid):
        if not group_jid:
            return "⚠️ _.lobby open needs to be sent in the group chat, not a DM._"
        if self.game and not self.game.over:
            return "⚠️ _A game is already running in this group._"
        if self.lobby and not self.lobby.started:
            return "⚠️ _A lobby's already open. .join it instead._"
        self.lobby = Lobby(group_jid, sender, map_id=M.random_map_id())
        STAGE.warm(C.PLAYER_COLORS)   # background download; never blocks
        self._reset_timer()
        map_name = M.get_map(self.lobby.map_id).name
        text = (
            f"🛰️ *Lobby #{self.lobby.id} opened.*\n"
            f"Map: *{map_name}* _(random)_\n"
            f"Players: {len(self.lobby.players)}/{MAX_PLAYERS}\n\n"
            "Use *.join* to enter. The host can use *.lobby start* "
            f"when at least {MIN_PLAYERS} players have joined.\n"
            "Host: *.lobby map <number or name>* to pick the map."
        )
        url = IMG.lobby_link()
        if url:
            self._broadcast(text, group_jid=group_jid, image_url=url, image_card=True)
            return None
        return text

    def _lobby_set_map(self, sender, choice):
        """`.lobby map` lists the maps; `.lobby map <no./name>` sets it (host, before start)."""
        lobby = self.lobby
        if not lobby or lobby.started:
            return "⚠️ _No open lobby. Send .lobby open first._"
        current = M.get_map(lobby.map_id).name
        menu = M.map_menu_text()
        if not choice.strip():
            return (
                f"🗺️ *Maps* — current: *{current}*\n{menu}\n\n"
                "_Host: .lobby map <number or name>_"
            )
        if sender != lobby.host:
            return "⚠️ _Only the host can change the map._"
        map_id = M.resolve_map(choice)
        if not map_id:
            return f"⚠️ _Unknown map._\n{menu}"
        lobby.map_id = map_id
        text = f"🗺️ *Map set to {M.get_map(map_id).name}.*"
        url = IMG.map_link(map_id)
        if url:
            self._broadcast(text, group_jid=lobby.group_jid, image_url=url)
            return None
        return text

    def _lobby_join(self, sender, group_jid):
        if not group_jid or group_jid != self.group_jid:
            return "⚠️ _.join must be sent in the game group chat._"
        lobby = self.lobby
        if not lobby or lobby.started:
            return "⚠️ _No open lobby right now. Ask someone to .lobby open._"
        if sender in lobby.players:
            return "_You're already in this lobby._"
        if len(lobby.players) >= MAX_PLAYERS:
            return f"⚠️ _Lobby's full ({MAX_PLAYERS} max)._"
        lobby.players.append(sender)
        self._reset_timer()
        return (
            f"✅ *Player {lobby.player_number(sender)} joined the lobby.*\n"
            f"Players: {len(lobby.players)}/{MAX_PLAYERS}\n\n"
            f"*Lobby players*\n{lobby.roster_text()}"
        )

    def _lobby_leave(self, sender):
        self._remove_player(sender)
        return "👋 You left the lobby."

    def _lobby_list(self):
        lobby = self.lobby
        if not lobby:
            return "🛰️ _There is no open lobby right now._\nUse *.lobby open* to create one."
        n_imp = _impostor_count(len(lobby.players))
        host_number = lobby.player_number(lobby.host)
        map_name = M.get_map(lobby.map_id).name
        return (
            f"🛰️ *Lobby #{lobby.id}* — {len(lobby.players)}/{MAX_PLAYERS} players "
            f"({n_imp} impostor(s) at this size)\n"
            f"Map: *{map_name}*\n"
            f"Host: Player {host_number}\n\n"
            f"{lobby.roster_text()}"
        )

    def _remove_player(self, sender):
        if self.game and not self.game.over and sender in self.game.players:
            self.game.mark_departed(sender)
        lobby = self.lobby
        if not lobby or sender not in lobby.players:
            return
        if lobby.started:
            # The match owns its roster now; leaving is handled by
            # Game.mark_departed, and the lobby's host handover is moot.
            return
        lobby.players.remove(sender)
        if sender == lobby.host:
            if lobby.players:
                lobby.host = lobby.players[0]
                self._broadcast(
                    f"👋 Host left — *Player {lobby.player_number(lobby.host)}* is now host.\n\n"
                    f"{lobby.roster_text()}"
                )
            else:
                self._cancel_timer()
                self.lobby = None
                self._broadcast("👋 _Last player left — lobby closed._")
        else:
            self._reset_timer()

    def _lobby_start(self, sender, received_at_ms=None):
        lobby = self.lobby
        if not lobby:
            return "⚠️ _No open lobby._"
        if lobby.started:
            return "⚠️ _Already started._"
        if sender != lobby.host:
            return "⚠️ _Only the host can start the game._"
        if len(lobby.players) < MIN_PLAYERS:
            return f"⚠️ _Need at least {MIN_PLAYERS} players ({len(lobby.players)}/{MIN_PLAYERS})._"
        lobby.started = True
        self._cancel_timer()
        from .amongus_game import Game
        self.game = Game(
            self,
            lobby,
            started_at_ms=received_at_ms,
            **getattr(self, "game_kwargs", {}),
        )
        if callable(self.ghost_picker):
            self._ghosts_group_jid = self.ghost_picker(self)
        return None  # Game.__init__ broadcasts the start message itself

    def _lobby_test(self, sender, role_arg, received_at_ms=None):
        """Host-only solo test: pad the lobby with silent dummies and start."""
        lobby = self.lobby
        if not lobby:
            return "⚠️ _No open lobby. Send .lobby open first._"
        if lobby.started:
            return "⚠️ _Already started._"
        if sender != lobby.host:
            return "⚠️ _Only the host can start a test game._"
        roles = {
            "": "crewmate", "crew": "crewmate", "crewmate": "crewmate",
            "imp": "impostor", "impostor": "impostor",
            "sci": "scientist", "scientist": "scientist",
        }
        if role_arg not in roles:
            return "_Usage: .lobby test [crew|imp|sci]_"
        lobby.test_role = roles[role_arg]
        added = 0
        while len(lobby.players) < MIN_PLAYERS:
            added += 1
            lobby.players.append(f"{C.DUMMY_PREFIX}{added}")
        self._broadcast(
            "🧪 *Test mode started.*\n"
            f"Role: *{lobby.test_role.upper()}*\n"
            f"Dummy players: {added}\n"
            "_Dummy players do not move, complete tasks, or vote._"
        )
        return self._lobby_start(sender, received_at_ms)

    def _lobby_map(self, sender):
        """`.map` before the match starts: the picture of the chosen map (no position yet)."""
        lobby = self.lobby
        if not lobby or lobby.started or sender not in lobby.players:
            return NOT_HANDLED
        game_map = M.get_map(lobby.map_id)
        caption = (
            f"🗺️ *{game_map.name}*\n"
            "The match has not started yet. Your starting room is "
            f"*{game_map.start_room.replace('_', ' ').title()}*."
        )
        url = IMG.map_link(game_map.id)
        if url:
            self._push_dm(sender, caption, image_url=url)
            return None
        return caption

    def _end_game_by_host(self, sender):
        """Host-only: stop the running match. Everything pending is cancelled."""
        game = self.game
        lobby = self.lobby
        if not game or game.over:
            return "⚠️ _There is no running game to end._"
        if not lobby or sender != lobby.host:
            return "⚠️ _Only the host can end the game._"
        with game.lock:
            game._end_game("🛑 *Match ended by the host.*\nNo winner was declared.")
        return None

    def _handle_ghost_group_message(self, sender):
        game = self.game
        if not game or game.over:
            return NOT_HANDLED
        player = game.players.get(sender)
        if player and player.alive and not player.departed:
            return DELETE_INCOMING_MESSAGE
        if player and not player.departed:
            return None
        return DELETE_INCOMING_MESSAGE

    def _reset_ghost_group(self, game):
        if self.game is game:
            self._ghosts_group_jid = None

    @staticmethod
    def _amenu():
        return (
            "*Among Us — Commands*\n"
            "\n*Setup (group chat):*\n"
            ".amongus on / off  _(Baron+, for the whole group)_\n"
            ".lobby open\n"
            ".join / .leave\n"
            ".lobby list\n"
            ".lobby map [number or name]  _(host sets the map)_\n"
            f".lobby start  _(host only, {MIN_PLAYERS}+ players)_\n"
            ".lobby test [crew|imp|sci]  _(host, solo test with dummies)_\n"
            ".endgame  _(host only, stops the match)_\n"
            ".pokemon on / off  — pause your Pokémon commands _(DM)_\n"
            "\n*In-game (DM Ariel):*\n"
            ".m  — list rooms\n"
            ".m <room or number>  — move\n"
            ".stop  — stop at your exact position\n"
            ".goback  — return to the reference room\n"
            ".where  — your current location\n"
            ".map    — the map and your exits\n"
            ".status  — people and bodies here\n"
            ".task  — list eligible tasks here\n"
            ".task <n>  — start a task interaction\n"
            ".task answer <answer>  — answer it in DM\n"
            "Reply to the task prompt or use .task next to switch tasks\n"
            ".tasks  — your tasks / available ghost tasks\n"
            ".progress  — task progress bar\n"
            ".players  — who's still alive\n"
            ".kill <colour>  — kill _(impostor)_\n"
            ".vent / .vent in / .vent <room> / .vent out  _(impostor)_\n"
            ".vitals / .witness  — Scientist only\n"
            ".sabotage lights|communications|oxygen|reactor  _(impostor)_\n"
            "scan  — reply scan to a bot message during O₂ / Reactor sabotage\n"
            ".ready  — optional O₂ repair countdown (3-2-1)\n"
            ".cooldown / .CDs  — your cooldowns\n"
            ".follow <colour> / .unfollow\n"
            ".cscene (.crimescene / .cs)  — reported crime-scene history\n"
            ".report  — report a body\n"
            ".meeting  — emergency meeting\n"
            ".vote <colour> / .vote skip  _(DM or GC)_\n"
            ".say <message>  — speak in a meeting as your colour (DM); "
            "ghosts: ghost chat\n"
            ".GC  — link to your game group\n"
            ".dm  — link to your DM with Ariel\n"
            "\n*Utility (anywhere):*\n"
            ".groupid  — get JID / LID of this chat"
        )

    # ── Ghost chat ──
    def _push_ghost_chat(self, game, sender_jid, message):
        dead = [p for p in game.players.values() if not p.alive and p.jid != sender_jid]
        sender = game.players.get(sender_jid)
        sender_label = sender.color if sender else "Ghost"
        formatted = f"👻 *{sender_label}:* {message}"
        if self._ghosts_group_jid:
            self._broadcast(formatted, group_jid=self._ghosts_group_jid)
        else:
            # Fallback: DM each ghost individually
            for p in dead:
                self._push_dm(p.jid, formatted)

    # ── Inactivity timeout ──
    def _reset_timer(self):
        self._cancel_timer()
        self._timer = threading.Timer(INACTIVITY_TIMEOUT_SECONDS, self._timeout)
        self._timer.daemon = True
        self._timer.start()

    def _cancel_timer(self):
        if self._timer:
            self._timer.cancel()
            self._timer = None

    def _timeout(self):
        with self._lock:
            lobby = self.lobby
            if not lobby or lobby.started:
                return
            lobby_id = lobby.id
            self.lobby = None
            self._broadcast(f"_Lobby {lobby_id} has ended._", group_jid=lobby.group_jid)

    # ── Send helpers ──
    def _sanitize_group_message(self, message):
        sanitized = str(message)
        replacements = {}
        if self.lobby:
            replacements.update(
                {
                    player_jid: f"Player {index}"
                    for index, player_jid in enumerate(self.lobby.players, 1)
                }
            )
        if self.game:
            replacements.update(
                {
                    player.jid: player.color
                    for player in self.game.players.values()
                }
            )
        for player_jid, label in sorted(
            replacements.items(),
            key=lambda item: len(item[0]),
            reverse=True,
        ):
            sanitized = sanitized.replace(player_jid, label)
        return sanitized

    def _broadcast(
        self, message, group_jid=None, tag_all=False, hide_tags=False,
        append_dm_link=False, image_url=None, image_card=False,
    ):
        """Send sanitized output to the lobby's group chat (or a specified GC).

        append_dm_link=True asks the bot to append the real link to its DM at
        send time (meeting call and voting announcements). image_url=<direct
        link> sends the message as that image's caption (mini-previews).
        """
        send = getattr(self.router, "_direct_send", None)
        if not send:
            return
        target = group_jid or self.group_jid or (self.lobby.group_jid if self.lobby else None)
        extra = {"append_dm_link": True} if append_dm_link else {}
        if image_url:
            extra["image_url"] = image_url
            if image_card:
                extra["image_card"] = True      # big link card instead of a photo caption
        if target:
            send(
                self._sanitize_group_message(message),
                group_jid=target,
                tag_all=tag_all,
                hide_tags=hide_tags,
                **extra,
            )
        else:
            send(
                self._sanitize_group_message(message),
                tag_all=tag_all,
                hide_tags=hide_tags,
                **extra,
            )

    def _set_comms_restriction(self, restricted, group_jid=None):
        """Tell the bot a Communications chat restriction started or ended.

        No WhatsApp group setting is changed (deletion alone, 06E). The bot
        keeps a restart-surviving record of restricted groups and warns once
        if it cannot delete messages (not a group admin). Returns True if the
        request was handed to the transport.
        """
        send = getattr(self.router, "_direct_send", None)
        target = group_jid or self.group_jid or (
            self.lobby.group_jid if self.lobby else None
        )
        if not send or not target:
            return False
        send(
            "",
            group_jid=target,
            group_action="restrict" if restricted else "unrestrict",
        )
        return True

    def _push_dm(self, player_jid, message, image_url=None, image_card=False):
        """Push directly to one player's DM via the JS allow_dm extension.

        ``image_url`` (a direct https link) sends the message as that image's
        caption; the bot falls back to plain text if the image cannot be sent.
        """
        if C.is_dummy(player_jid):
            return  # solo-test dummies have no real chat to message
        send = getattr(self.router, "_direct_send", None)
        if not send:
            return
        if image_url and image_card:
            send(message, group_jid=player_jid, allow_dm=True, image_url=image_url, image_card=True)
        elif image_url:
            send(message, group_jid=player_jid, allow_dm=True, image_url=image_url)
        else:
            send(message, group_jid=player_jid, allow_dm=True)

    def _push_dm_with_link(self, player_jid, message):
        """Like _push_dm, but asks the bot to append the real game-group link."""
        if C.is_dummy(player_jid):
            return
        send = getattr(self.router, "_direct_send", None)
        if not send:
            return
        group = self.group_jid or (self.lobby.group_jid if self.lobby else None)
        send(message, group_jid=player_jid, allow_dm=True, group_link_jid=group)

    def contains_player(self, sender):
        with self._lock:
            # Only an OPEN lobby or a LIVE match claims a player. A finished
            # match (or the lobby it came from) must not keep its players tied
            # to this group, or a later match elsewhere would block their DMs.
            lobby_open = (
                self.lobby is not None
                and not self.lobby.started
                and sender in self.lobby.players
            )
            game_live = (
                self.game is not None
                and not self.game.over
                and sender in self.game.players
            )
            return lobby_open or game_live


class AmongUsCoordinator:
    """Routes each group to its own manager and resolves private game commands."""

    def __init__(self, router, registry=None, owner_check=None):
        self.router = router
        self._lock = threading.RLock()
        self._groups = {}
        self.registry = registry or GroupRegistry()
        self.owner_check = owner_check   # callable(sender) -> bool; default: core.permissions.is_king

    def _manager_for(self, group_jid):
        if not group_jid:
            return None
        with self._lock:
            manager = self._groups.get(group_jid)
            if manager is None:
                manager = AmongUsManager(self.router, group_jid)
                manager.ghost_picker = self._pick_ghost_group
                self._groups[group_jid] = manager
            return manager

    def _managers_for_player(self, sender):
        with self._lock:
            managers = tuple(self._groups.values())
        return [manager for manager in managers if manager.contains_player(sender)]

    def has_player(self, sender):
        return bool(self._managers_for_player(sender))

    def _active_managers(self):
        with self._lock:
            return tuple(self._groups.values())

    def ghost_group_ids(self):
        return sorted(
            {
                manager._ghosts_group_jid
                for manager in self._active_managers()
                if manager._ghosts_group_jid
                and manager.game
                and not manager.game.over
            }
        )

    def should_intercept_group(self, sender, text, group_jid):
        if not group_jid:
            return False
        raw = (text or "").strip().lower()
        for manager in self._active_managers():
            if manager.game and not manager.game.over:
                if manager._ghosts_group_jid == group_jid:
                    return True
                if (
                    manager.group_jid == group_jid
                    and manager.game.comms_restriction_active()
                ):
                    return True
                player = manager.game.players.get(sender)
                if (
                    manager.group_jid == group_jid
                    and player
                    and not player.alive
                    and not player.departed
                ):
                    return True
        return False

    # ── Owner registry: .set/.unset alobbygc|aghostgc, .alobbygcs, .ghostgcs ──
    REGISTRY_ROLES = {"alobbygc": "lobby", "aghostgc": "ghost"}
    REGISTRY_LISTS = {".alobbygcs": "lobby", ".ghostgcs": "ghost"}

    def _is_owner(self, sender):
        check = self.owner_check
        if check is None:
            try:
                from core.permissions import is_king as check
            except Exception:
                return False
        try:
            return bool(check(sender))
        except Exception:
            return False   # fail closed

    @staticmethod
    def _short(jid):
        return "…" + str(jid).split("@")[0][-6:]

    def _group_status(self, role, jid):
        managers = self._active_managers()
        if role == "lobby":
            manager = next((m for m in managers if m.group_jid == jid), None)
            if manager and manager.game and not manager.game.over:
                return "in a game"
            if manager and manager.lobby and not manager.lobby.started:
                return "lobby open"
            return "idle"
        busy = any(
            m._ghosts_group_jid == jid and m.game and not m.game.over
            for m in managers
        )
        return "in use" if busy else "free"

    def _registry_list(self, role):
        title = "Lobby groups" if role == "lobby" else "Ghost groups"
        groups = self.registry.list(role)
        if not groups:
            return f"_No {title.lower()} are registered._"
        lines = [
            f"{i}. Group {self._short(jid)} — {self._group_status(role, jid)}"
            for i, jid in enumerate(groups, 1)
        ]
        return f"*{title}*\n" + "\n".join(lines)

    def _registry_command(self, sender, text, group_jid):
        """Owner-only registry commands. NOT_HANDLED when the text is not one."""
        words = (text or "").strip().lower().split()
        if not words:
            return NOT_HANDLED
        is_list = len(words) == 1 and words[0] in self.REGISTRY_LISTS
        is_edit = (
            len(words) == 2
            and words[0] in (".set", ".unset")
            and words[1] in self.REGISTRY_ROLES
        )
        if not (is_list or is_edit):
            return NOT_HANDLED
        if not self._is_owner(sender):
            return "⚠️ _Only the bot owner can use that command._"
        if is_list:
            return self._registry_list(self.REGISTRY_LISTS[words[0]])
        if not group_jid or not str(group_jid).endswith("@g.us"):
            return "⚠️ _Run this in the group you want to register._"
        role = self.REGISTRY_ROLES[words[1]]
        label = "lobby" if role == "lobby" else "ghost"
        if words[0] == ".set":
            result = self.registry.add(role, group_jid)
            if result == "duplicate":
                return f"_This group is already a registered {label} group._"
            if result == "other_role":
                other = "ghost" if role == "lobby" else "lobby"
                return f"⚠️ _This group is already a {other} group. A group can't be both._"
            if result:
                return "⚠️ _I couldn't save the registry. Nothing was changed._"
            return f"✅ _This group is now a registered {label} group._"
        if self._group_status(role, group_jid) == ("in a game" if role == "lobby" else "in use"):
            return "⚠️ _This group is in a live game. Unregister it after the match._"
        result = self.registry.remove(role, group_jid)
        if result == "missing":
            return f"_This group is not a registered {label} group._"
        if result:
            return "⚠️ _I couldn't save the registry. Nothing was changed._"
        return f"✅ _This group is no longer a registered {label} group._"

    def _pick_ghost_group(self, manager):
        """Ghost chat for a match: lobby group N uses ghost group N (registration
        order). An unregistered lobby group uses the ghost group only if exactly
        one is registered. A ghost group already in a live match is never reused."""
        lobbies = self.registry.list("lobby")
        ghosts = self.registry.list("ghost")
        candidate = None
        if manager.group_jid in lobbies:
            index = lobbies.index(manager.group_jid)
            if index < len(ghosts):
                candidate = ghosts[index]
        elif len(ghosts) == 1:
            candidate = ghosts[0]
        if candidate is None:
            return None
        for other in self._active_managers():
            if (
                other is not manager
                and other._ghosts_group_jid == candidate
                and other.game
                and not other.game.over
            ):
                return None
        return candidate

    def _link_command(self, sender, text, group_jid):
        """`.dm` / `.GC` (anywhere): reply with a direct link, resolved by the bot.

        `.dm` links the chat with Ariel; `.GC` links the sender's game group.
        Returns None when the text is not one of the two commands.
        """
        words = (text or "").strip().lower().split()
        if len(words) != 1 or words[0] not in {".dm", ".gc"}:
            return None
        if words[0] == ".dm":
            return LINK_REPLY(
                "dm", None, "💬 *Your DM with Ariel:*"
            )
        managers = self._managers_for_player(sender)
        if group_jid:
            here = [m for m in managers if m.group_jid == group_jid]
            if here:
                managers = here
        if not managers:
            return "⚠️ _You're not in an Among Us game._"
        if len(managers) > 1:
            return (
                "⚠️ _You're in more than one Among Us game. "
                "Send .GC in the game group you mean._"
            )
        return LINK_REPLY(
            "game_group", managers[0].group_jid, "🎮 *Your game group:*"
        )

    def pre_dispatch(
        self,
        sender,
        text,
        group_jid=None,
        received_at_ms=None,
        quoted_text=None,
        message_key=None,
    ):
        link_reply = self._link_command(sender, text, group_jid)
        if link_reply is not None:
            return link_reply
        registry_reply = self._registry_command(sender, text, group_jid)
        if registry_reply is not NOT_HANDLED:
            return registry_reply
        if group_jid:
            for manager in self._active_managers():
                if manager._ghosts_group_jid == group_jid:
                    return manager._handle_ghost_group_message(sender)
            manager = self._manager_for(group_jid)
            return manager.pre_dispatch(
                sender,
                text,
                group_jid,
                received_at_ms,
                quoted_text,
                message_key,
            )

        if (text or "").strip().lower() == ".amenu":
            return AmongUsManager._amenu()

        managers = self._managers_for_player(sender)
        if len(managers) == 1:
            return managers[0].pre_dispatch(
                sender,
                text,
                None,
                received_at_ms,
                quoted_text,
                message_key,
            )
        if len(managers) > 1:
            return (
                "⚠️ _You're in more than one Among Us game. Send this command "
                "in the correct game group so it reaches the right match._"
            )
        return NOT_HANDLED


