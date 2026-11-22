import sys, os, json, threading
from concurrent.futures import ThreadPoolExecutor

_ENGINE_DIR = os.path.dirname(os.path.abspath(__file__))
for _d in (
    _ENGINE_DIR,
    os.path.join(_ENGINE_DIR, "core"),
    os.path.join(_ENGINE_DIR, "shared"),
    os.path.join(_ENGINE_DIR, "pokemon"),
    os.path.join(_ENGINE_DIR, "pokemon", "world"),
    os.path.join(_ENGINE_DIR, "rpg"),
    os.path.join(_ENGINE_DIR, "chat"),
):
    if _d not in sys.path:
        sys.path.append(_d)
sys.path.insert(0, _ENGINE_DIR)   # `router` package + bridge live here

from router import CommandRouter
from database import Database
from interfaces import _player_fonts, _FONT_MAP
from router.site_actions import (
    handle_swap, handle_buy, handle_grant_starter, handle_hatch_legacy_egg,
    handle_get_quests, handle_accept_quest, handle_decline_quest,
    handle_get_badges, handle_get_gyms, handle_get_pokedex,
    handle_nif_me, handle_nif_ticket, handle_nif_ticket_get, handle_nif_result,
)

_SITE_ACTIONS = {
    "swap":  handle_swap,
    "buy":   handle_buy,
    "grant_starter": handle_grant_starter,
    "hatch_legacy_egg": handle_hatch_legacy_egg,
    "get_quests": handle_get_quests,
    "accept_quest": handle_accept_quest,
    "decline_quest": handle_decline_quest,
    "get_badges": handle_get_badges,
    "get_gyms": handle_get_gyms,
    "get_pokedex": handle_get_pokedex,
    "nif_me": handle_nif_me,
    "nif_ticket": handle_nif_ticket,
    "nif_ticket_get": handle_nif_ticket_get,
    "nif_result": handle_nif_result,
}

_db     = Database()
_router = CommandRouter(_db)

# Re-register egg hatch timers from stored timestamps
try:
    from egg import restore_timers as _restore_egg_timers
    _restore_egg_timers(_router)
except Exception as _e:
    import sys
    print(f"[EGG] restore_timers failed: {_e}", file=sys.stderr)

_stdout_lock = threading.Lock()

# Thread pool for parallel handle() calls (one thread per message)
_pool = ThreadPoolExecutor(max_workers=8)

# Per-sender locks — ensures messages from the same sender run sequentially
_sender_locks: dict = {}
_sender_locks_mutex = threading.Lock()

def _get_sender_lock(sender: str) -> threading.Lock:
    with _sender_locks_mutex:
        if sender not in _sender_locks:
            _sender_locks[sender] = threading.Lock()
        return _sender_locks[sender]


def _apply_font(text, sender):
    """Apply player's chosen font to ALL text, skipping border chars and markers."""
    if not text:
        return text
    key = _player_fonts.get(sender)
    if not key or key not in _FONT_MAP:
        return text
    fm = _FONT_MAP[key]

    BORDER_START = set('╭╰╮╯┃┣┗━❰❱⌖彡۞𝕬𝕽𝕴𝕰𝕷𝓦𝓮𝓵𝓬𝓸𝔸𝕽𝕴𝔼𝕷')

    result = []
    i = 0
    while i < len(text):
        found_marker = False
        for marker in ('__IMG__', '__HUD__', '__CAP__', '__THUMB__',
                        '__TITLE__', '__SUB__', '__TYPE__'):
            if text[i:i+len(marker)] == marker:
                result.append(marker)
                i += len(marker)
                found_marker = True
                break
        if found_marker:
            continue

        ch = text[i]
        if ch == '\n':
            result.append('\n')
            i += 1
            continue

        end = text.find('\n', i)
        if end == -1:
            end = len(text)
        line = text[i:end]
        stripped = line.strip()

        if stripped and stripped[0] in BORDER_START:
            result.append(line)
        else:
            result.append(line.translate(fm))

        i = end

    return ''.join(result)


def _direct_send(message, group_jid=None, sender=None, tag_all=False, hide_tags=False, allow_dm=False, group_action=None, group_link_jid=None, append_dm_link=False, image_url=None, image_card=False):
    """Write push message to stdout.
    allow_dm=True lets group_jid be an individual's JID instead of a
    whitelisted group — used by Among Us to notify a specific player
    (e.g. room enter/leave, kill resolution, follow reveal) without a
    new message from them triggering it. Off by default everywhere else.
    group_link_jid=<group jid> (DM only) asks the bot to append that group's
    invite link to the message at send time (best effort).
    append_dm_link=True (group send) asks the bot to append a link to its own DM.
    image_url=<direct https link> (group send) sends the message as that image's caption;
    if the image fails the bot falls back to the plain text.
    image_card=True (with image_url) sends the picture as a big link card instead of a photo caption.
    group_action="restrict"|"unrestrict" tells the bot a Communications chat
    restriction started/ended in a whitelisted group (Among Us). The bot only
    records it (restart safety); messages are deleted via the normal
    delete_message_key path. No WhatsApp group setting is changed; no text sent.
    """
    if sender:
        message = _apply_font(message, sender)
    payload = {
        "response": None,
        "outbox": [{"sender": "__push__", "message": message, "group_jid": group_jid, "tag_all": tag_all, "hide_tags": hide_tags, "allow_dm": allow_dm, "group_action": group_action, "group_link_jid": group_link_jid, "append_dm_link": append_dm_link, "image_url": image_url, "image_card": image_card}],
        "quote_id": None
    }
    with _stdout_lock:
        sys.stdout.write(json.dumps(payload) + "\n")
        sys.stdout.flush()

_router._direct_send = _direct_send

def _precache_zone_pokemon():
    """Pre-fetch and cache all Pokémon in encounter tables so encounters work offline."""
    import threading
    from encounter_tables import ENCOUNTER_TABLES
    from pokeapi import get_full

    def _do():
        all_species = set()
        for zone_data in ENCOUNTER_TABLES.values():
            for tile_pool in zone_data.values():
                if isinstance(tile_pool, list):
                    for entry in tile_pool:
                        if isinstance(entry, tuple):
                            all_species.add(entry[0])
        failed = []
        for species in sorted(all_species):
            try:
                result = get_full(_db, species)
                if not result:
                    failed.append(species)
            except Exception as e:
                failed.append(f"{species} ({e})")
        if failed:
            print(f"[PRECACHE] Done — {len(all_species)} species, {len(failed)} failed: {failed}", file=sys.stderr, flush=True)
        else:
            print(f"[PRECACHE] Done — {len(all_species)} species cached OK.", file=sys.stderr, flush=True)

    t = threading.Thread(target=_do, daemon=True)
    t.start()

_precache_zone_pokemon()

from pokeapi import prewarm_arena_pool
prewarm_arena_pool(_db)


def _do_handle(req_id, sender, text, mentioned_jid, group_jid, is_group=None, quoted_text=None, push_name=None, received_at_ms=None, pool_pokemon=False, pool_amongus=False, pool_normal=False, pool_rpg=False, pool_chat=False, message_key=None, pool_niflheim=False):
    """Run in thread pool — never blocks the stdin loop."""
    import traceback
    print(f"[BRIDGE] [{req_id}] recv: {text}", file=sys.stderr, flush=True)
    _router._last_group_jid = group_jid
    _router._last_push_name = push_name or ""
    with _get_sender_lock(sender):
        try:
            response = _router.handle(sender, text, mentioned_jid=mentioned_jid, quoted_text=quoted_text,
                                       group_jid=group_jid, is_group=is_group,
                                       received_at_ms=received_at_ms,
                                       message_key=message_key,
                                       pool_pokemon=pool_pokemon, pool_amongus=pool_amongus, pool_normal=pool_normal,
                                       pool_rpg=pool_rpg, pool_chat=pool_chat, pool_niflheim=pool_niflheim)
        except Exception as e:
            print(f"[BRIDGE] [{req_id}] CRASH: {e}", file=sys.stderr, flush=True)
            traceback.print_exc(file=sys.stderr)
            response = None

        # Read the sticker choice keyed by `sender`, not off the shared
        # _router instance — up to 8 requests run concurrently on the
        # same _router (see _pool = ThreadPoolExecutor(max_workers=8)
        # above), so a shared attribute here would let one sender's
        # sticker leak into a different sender's response. ariel.py's
        # own per-sender dict (guarded by _get_sender_lock above) is
        # what actually keeps this safe.
        from ariel import pop_ariel_sticker
        sticker = pop_ariel_sticker(sender)

        delete_message_key = None
        link_reply = None
        if isinstance(response, dict) and response.get("__amongus_action__") == "delete_incoming_message":
            delete_message_key = message_key
            response = None
        elif isinstance(response, dict) and response.get("__amongus_action__") == "link_reply":
            # The bot resolves the real link at send time (bot/bridge.js).
            link_reply = {"kind": response.get("kind"), "group_jid": response.get("group_jid")}
            response = response.get("text")

        outbox = []
        for s in list(_router._outbox.keys()):
            msgs = _router.pop_outbox(s)
            for m in msgs:
                outbox.append({
                    "sender":    s,
                    "message":   _apply_font(m, sender),
                    "group_jid": group_jid
                })

        result = {
            "req_id":   req_id,
            "response": response if response else None,
            "outbox":   outbox,
            "quote_id": None,
            "sticker":  sticker,
            "delete_message_key": delete_message_key,
            "link_reply": link_reply,
            "amongus_ghost_groups": _router.amongus.ghost_group_ids(),
        }
        print(f"[BRIDGE] [{req_id}] done", file=sys.stderr, flush=True)
        with _stdout_lock:
            sys.stdout.write(json.dumps(result) + "\n")
            sys.stdout.flush()

        # The reply above is already on its way to the player. Any
        # follow-up bookkeeping a command queued (currently: .rpg's
        # scene-noun extraction, see rpg_scene.py) runs NOW, still inside
        # this sender's lock, so their next message can't start until the
        # scene store is up to date — but they never wait on it to READ
        # this reply. Bounded by rpg_scene.AFTER_REPLY_BUDGET_SECONDS and
        # never raises, so it can't hang or crash the bridge.
        try:
            import rpg_scene
            rpg_scene.run_after_reply(
                sender, log=lambda m: print(m, file=sys.stderr, flush=True))
        except Exception as _e:
            print(f"[BRIDGE] [{req_id}] after-reply hook error: {_e}",
                  file=sys.stderr, flush=True)


def _do_site_action(req_id, action_type, data):
    """Run in thread pool — handles a site-originated action (e.g. swap).
    Uses the same per-sender lock as WhatsApp commands so a site swap
    and an in-progress WhatsApp command for the same player never race.
    """
    sender = data.get("sender", "unknown")
    print(f"[BRIDGE] [{req_id}] site action: {action_type} ({sender})", file=sys.stderr, flush=True)
    with _get_sender_lock(sender):
        try:
            handler = _SITE_ACTIONS[action_type]
            result  = handler(_router, sender, data.get("payload") or {})
        except Exception as e:
            print(f"[BRIDGE] [{req_id}] site action CRASH: {e}", file=sys.stderr, flush=True)
            import traceback
            traceback.print_exc(file=sys.stderr)
            result = {"error": "Internal error processing action."}

        with _stdout_lock:
            sys.stdout.write(json.dumps({"req_id": req_id, "site_result": result}) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    with _stdout_lock:
        sys.stdout.write(json.dumps({"ready": True}) + "\n")
        sys.stdout.flush()

    req_counter = 0
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            data       = json.loads(line)
            req_id     = data.get("req_id", req_counter)
            req_counter += 1

            action_type = data.get("type")
            if action_type in _SITE_ACTIONS:
                # Site-originated action (e.g. party/PC swap) — runs
                # through the same Player model as WhatsApp commands,
                # but bypasses text parsing entirely.
                _pool.submit(_do_site_action, req_id, action_type, data)
                continue

            sender        = data.get("sender", "unknown")
            text          = data.get("text", "")
            mentioned_jid = data.get("mentioned_jid", None)
            group_jid     = data.get("group_jid", None)
            is_group      = data.get("is_group")
            quoted_text   = data.get("quoted_text", None)
            push_name     = data.get("push_name", None)
            received_at_ms = data.get("received_at_ms")
            pool_pokemon  = data.get("pool_pokemon", False)
            pool_amongus  = data.get("pool_amongus", False)
            pool_normal   = data.get("pool_normal", False)
            pool_rpg      = data.get("pool_rpg", False)
            pool_chat     = data.get("pool_chat", False)
            pool_niflheim = data.get("pool_niflheim", False)
            message_key   = data.get("message_key")
            # Fire off in thread pool — stdin loop is immediately free
            _pool.submit(_do_handle, req_id, sender, text, mentioned_jid, group_jid, is_group, quoted_text, push_name, received_at_ms, pool_pokemon, pool_amongus, pool_normal, pool_rpg, pool_chat, message_key, pool_niflheim)
        except Exception as e:
            print(f"[BRIDGE] parse error: {e}", file=sys.stderr, flush=True)
