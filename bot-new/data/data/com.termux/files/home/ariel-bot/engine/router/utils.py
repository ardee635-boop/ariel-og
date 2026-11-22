# ============================================================
# NIFLHEIM — router/utils.py
# Shared helper methods
# ============================================================

import threading, time


class UtilsMixin:

    def _normalize(self, text):
        if not text:
            return ""
        text = " ".join(text.strip().split())
        if text.startswith(". "):
            text = "." + text[2:].lstrip()
        return text


    def _bestiary_page(self, names, title, page, per_page):
        from interfaces import UI
        from ._constants import _M
        start   = (page - 1) * per_page; end = start + per_page
        chunk   = names[start:end]
        total   = max(1, (len(names) + per_page - 1) // per_page)
        entries = []
        for n in chunk:
            m = _M.get(n, {}) if callable(getattr(_M, "get", None)) else {}
            entries.append({
                "name": n, "tier_num": m.get("tier_num", 1),
                "rank": m.get("rank", "F"), "type_str": m.get("type", ""),
            })
        return UI.bestiary_list(entries, title, page, total)

    def _maybe_offer_quest(self, sender, player, npc_id, npc_name):
        from ._constants import (should_offer_quest, generate_ai_quest,
                                  get_premade_quest, quest_offer_ui, MAX_QUESTS)
        guild_qs = self.db.quest_active(sender)
        npc_qs   = self.db.npc_quest_active(sender)
        if len(guild_qs) + len(npc_qs) >= MAX_QUESTS:
            return None
        if self.db.npc_quest_pending_offer(sender, npc_id):
            return None
        tier, score = self.db.familiarity_tier(sender, npc_id)
        if not should_offer_quest(score):
            return None
        quest = generate_ai_quest(npc_id, player, score) if score >= 41 else None
        if not quest:
            quest = get_premade_quest(npc_id, player.level, getattr(player, "guild_rank", "F"))
        if not quest:
            return None
        quest["source_npc"] = npc_id
        offer_id = self.db.npc_quest_set_offered(sender, quest)
        if not offer_id:
            return None
        return (offer_id, quest_offer_ui(quest, offer_id, npc_name))

    def _render_zone_map(self, sender, player):
        from map import render_minimap
        return render_minimap(player)

    def _send_to(self, sender, message):
        if sender not in self._outbox: self._outbox[sender] = []
        self._outbox[sender].append(message)

    def pop_outbox(self, sender):
        return self._outbox.pop(sender, [])

    def _queue_delayed(self, sender, message, delay_secs):
        grp = getattr(self, "_last_group_jid", None)
        def _send():
            time.sleep(delay_secs)
            if hasattr(self, "_direct_send"): self._direct_send(message, grp)
        threading.Thread(target=_send, daemon=True).start()

    def _queue_message(self, sender, message, delay: int = 1):
        self._queue_delayed(sender, message, delay)

    def _split_battle_result(self, sender, result, delay: float = 1.0):
        """
        3-tuple (action_log, monster_log, hud):
          action_log  — sent immediately
          monster_log — queued at 1s (skipped if empty)
          hud         — queued at 2s (or 1s if no monster_log)

        4-tuple (action_log, monster_log, faint_msg, None):
          action_log  — sent immediately
          monster_log — queued at 1s (skipped if empty)
          faint_msg   — queued at 2s (or 1s if no monster_log), no HUD

        2-tuple (log, hud):
          log — sent immediately, hud queued at 1s

        Plain string — returned as-is.
        """
        if isinstance(result, tuple) and len(result) == 4:
            log_text, monster_text, faint_text, _ = result
            if monster_text:
                self._queue_delayed(sender, monster_text, delay)
                self._queue_delayed(sender, faint_text, delay * 2)
            else:
                self._queue_delayed(sender, faint_text, delay)
            return log_text
        if isinstance(result, tuple) and len(result) == 3:
            log_text, monster_text, hud_text = result
            if monster_text:
                self._queue_delayed(sender, monster_text, delay)
                self._queue_delayed(sender, hud_text, delay * 2)
            else:
                self._queue_delayed(sender, hud_text, delay)
            return log_text
        if isinstance(result, tuple) and len(result) == 2:
            log_text, hud_text = result
            self._queue_delayed(sender, hud_text, delay)
            return log_text
        return result
