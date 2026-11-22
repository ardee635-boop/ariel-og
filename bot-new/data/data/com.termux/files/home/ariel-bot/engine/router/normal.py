# ============================================================
# NIFLHEIM — router/normal.py
# Normal pool: the pool gate and the always-reachable .groupid.
# Cut out of handle.py (RESTRUCTURE.md §3.5) with no logic changes.
# The Normal command set itself (NORMAL_CMDS) still lives on
# HandleMixin because the Pokémon gate and KNOWN_CMDS share it.
# ============================================================

NOT_HANDLED = object()


class NormalManager:
    def __init__(self, router):
        self.router = router

    def pre_dispatch(self, sender, text, pool_normal=False):
        """
        Normal pool gate (Layer 1): if the Normal pool is off for this
        group, Normal-classified commands (admin, quest, utility) are
        silently ignored (returns None). Then .groupid, which is always
        reachable. Returns a reply, None (swallowed), or NOT_HANDLED.
        """
        r = self.router
        if not pool_normal:
            _cmd_only2 = text.strip().split(" ")[0].lower() if text.strip() else ""
            if _cmd_only2 in r.NORMAL_CMDS:
                return None

        # ── King-only LLM model commands (.models/.model/.llmtest/.nvtest) ──
        _cmd_word = text.strip().split(" ")[0].lower() if text.strip() else ""
        if _cmd_word in r.NORMAL_CMDS and _cmd_word in (".models", ".model", ".llmtest", ".nvtest"):
            from .rpg_cmds import models as _model_cmds
            return _model_cmds.handle_command(sender, text)

        # ── .groupid — returns JID/LID of the current chat ──
        if text.strip().lower() == ".groupid":
            _gj = getattr(r, "_last_group_jid", None)
            _lid = getattr(r, "_last_lid", None)
            if _gj:
                parts = [f"*Group JID:* `{_gj}`"]
                if _lid:
                    parts.append(f"*LID:* `{_lid}`")
                return "\n".join(parts)
            return f"*Your JID:* `{sender}`"
        return NOT_HANDLED
