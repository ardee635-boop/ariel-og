# ============================================================
# ARIEL.PY — RESET STUB (2026-10-31)
#
# The old chat companion was wiped for a full redesign (see the
# Ariel AI master redesign plan). This file only keeps the two
# names the rest of the bot imports, so nothing crashes:
#
#   router/chat.py : from ariel import ariel_chat
#   bridge.py      : from ariel import pop_ariel_sticker
#
# Both are inert: ariel_chat() returns None (handled, no reply =
# silence) and pop_ariel_sticker() returns None (no sticker).
# Replace this file when the new engine is built.
# ============================================================


def ariel_chat(sender, message, push_name=None, db=None,
               group_jid=None, mentioned_jid=None):
    return None


def pop_ariel_sticker(sender):
    return None
