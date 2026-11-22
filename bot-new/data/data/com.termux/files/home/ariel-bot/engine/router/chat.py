# ============================================================
# NIFLHEIM — router/chat.py
# Chat pool: Ariel conversation trigger + passive group-name cache.
# Same shape as AmongUsManager / RpgManager: handle() calls these at
# fixed points; pre_dispatch returns NOT_HANDLED to fall through.
# Cut out of handle.py (RESTRUCTURE.md §3.5) with no logic changes.
# ============================================================

import re

NOT_HANDLED = object()


class ChatManager:
    def __init__(self, router):
        self.router = router

    def record_names(self, sender):
        """
        Passive group name cache. Record this sender's current WhatsApp
        display name against this group, every message, unconditionally —
        cheap upsert, and it's what lets Ariel later connect a name
        mentioned in conversation ("have you heard from rose") to an
        actual known group member even when that member isn't the one
        currently texting her. DMs (no group_jid) are skipped.
        """
        r = self.router
        _group_jid_for_names = getattr(r, "_last_group_jid", None)
        _push_name_for_names = getattr(r, "_last_push_name", None)
        if _group_jid_for_names and _push_name_for_names:
            try:
                r.db.record_group_name(_group_jid_for_names, sender, _push_name_for_names)
            except Exception as e:
                print(f"[NAMES] record_group_name failed (non-fatal): {e}", flush=True)

    def pre_dispatch(self, sender, text, mentioned_jid=None, pool_chat=False):
        """
        Ariel trigger. Two independent ways in:
         1. The word "ariel" appears anywhere in the text. index.js
            already guarantees this whenever the bot is tagged or a
            message quotes the bot (it prepends "ariel " before
            forwarding here) — so this one check covers mentions,
            tags, quote-replies, AND .silentchat groups, which all
            funnel through the same text field.
         2. The group has .chat on (pool_chat) — every message from
            everyone in that group counts, no "ariel" required.
            .chat on/off itself is handled entirely on the JS side
            (Baron+, per-group pool toggle) — this only ever receives
            the resulting flag.
        Returns Ariel's reply, or NOT_HANDLED to fall through.
        """
        r = self.router
        _raw_lower = text.lower().strip()
        _is_ariel_call = bool(re.search(r'\bariel\b', _raw_lower))
        if _is_ariel_call or pool_chat:
            query = text.strip()
            if text.lower().startswith("ariel "):
                query = text[6:].strip()
            if query:
                from ariel import ariel_chat
                push_name = getattr(r, "_last_push_name", None)
                group_jid = getattr(r, "_last_group_jid", None)
                # Note: the sticker Ariel may have chosen for this reply
                # is read separately by bridge.py, via
                # ariel.pop_ariel_sticker(sender), right after handle()
                # returns — not stashed on the router, since it is a
                # single shared instance across up to 8 concurrent
                # requests and a shared attribute would risk leaking one
                # sender's sticker into a different sender's response.
                return ariel_chat(sender, query, push_name=push_name, db=r.db,
                                  group_jid=group_jid, mentioned_jid=mentioned_jid)
        return NOT_HANDLED
