# ============================================================
# NIFLHEIM — router/niflheim.py
# Niflheim pool gate. Same shape as the Among Us / RPG gates:
# handle.py calls pre_dispatch() BEFORE the Pokémon pool gate.
# Returns a reply, None (swallowed) or NOT_HANDLED.
# Package 1.1: .nmenu plus the "unavailable" stubs. 1.2 profile, 1.3 world, 1.4 combat/.hunt, 1.5 inventory/shop/gear, 1.6 duels.
# ============================================================

NOT_HANDLED = object()

UNAVAILABLE = "This feature is currently unavailable."
STUB_CMDS = set()   # nothing locked any more (.boss and .dungeon are live in Session 2)
def _arena_link(base, ticket_id):
    """ARENA_URL may already hold a query (…/?world=niflheim); join the ticket with & or ?."""
    return f"{base}{'&' if '?' in base else '?'}t={ticket_id}"


def _site_link():
    """The plain site home (https://host/), never a fight/ticket page. SITE_URL wins, else it is
    derived from ARENA_URL (scheme + host only, so ?world= / /arena paths are dropped)."""
    import os
    from urllib.parse import urlsplit
    raw = os.environ.get("SITE_URL", "").strip() or os.environ.get("ARENA_URL", "").strip()
    if not raw:
        return ""
    u = urlsplit(raw)
    return f"{u.scheme}://{u.netloc}/" if u.scheme and u.netloc else raw


DM_NOTICE = "Niflheim is played in groups where the world is switched on."

NMENU = """╭━━★彡 𝚴𝐈ҒԼ𝚮𝚵𝐈𝚳 彡★━━╮
┃ 𖤓 Prefix: .
┃ 𖤓 Name: Ariel
┃ 𖤓 Creator: Ice King
╰━━━━━━━━━━━━━╯

❄️ NIFLHEIM COMMANDS ❄️
┣ ✦ .reg
┣ ✦ .profile
┣ ✦ .p
┣ ✦ .explore
┣ ✦ .zone
┣ ✦ .end
┣ ✦ .look
┣ ✦ .hunt
┣ ✦ .attack
┣ ✦ .defend
┣ ✦ .potion
┣ ✦ .inv
┣ ✦ .shop
┣ ✦ .buy
┣ ✦ .sell
┣ ✦ .equip
┣ ✦ .unequip
┣ ✦ .use
┣ ✦ .duel @player
┣ ✦ .accept
┣ ✦ .decline
┣ ✦ .boss
┣ ✦ .dungeon
┣ ✦ .arena
┗━━━━━━━━━━━━━"""


class NiflheimManager:
    def __init__(self, router):
        self.router = router
        # Journey-event fights (25% chance per journey) start through this hook (Package 1.4).
        try:
            from niflheim import journey as _j
            _j.fight_handler = self._journey_fight
        except Exception:
            pass

    def _journey_fight(self, sender, pl, j):
        from niflheim import combat
        import threading
        msgs, lvl = combat.auto_fight(self.router.db, sender, pl, group_jid=j.get("group_jid"), source="journey")
        for i, m in enumerate(lvl):                       # each level-up is its own message, after the fight text
            t = threading.Timer(1.5 * (i + 1), self.router._send_to, (sender, m))
            t.daemon = True
            t.start()
        return "\n".join(msgs)

    def pre_dispatch(self, sender, text, pool_niflheim=False, is_group=True, is_admin=False,
                     group_jid=None, mentioned_jid=None):
        """Niflheim gate. Does nothing at all while the pool is off for the group."""
        if not pool_niflheim:
            if group_jid:                    # world switched off: cancel invites/duels/fights there
                from niflheim import live
                live.cancel_group(self.router.db, group_jid)
            return NOT_HANDLED
        raw = (text or "").strip()
        if not raw.startswith("."):
            return NOT_HANDLED
        cmd = raw.split()[0].lower()

        if cmd == ".nmenu":
            return NMENU
        if cmd in STUB_CMDS:
            return UNAVAILABLE

        if cmd not in (".reg", ".profile", ".p", ".ngrant", ".explore", ".zone", ".end", ".look",
                       ".hunt", ".arena", ".boss", ".dungeon", ".website", ".site", ".attack", ".defend", ".potion",
                       ".inv", ".inventory", ".shop", ".buy", ".sell", ".equip", ".unequip", ".use",
                       ".duel", ".accept", ".decline"):
            return NOT_HANDLED

        from niflheim import player as P, store, world, journey, combat, shop, duel
        db = self.router.db
        rest = raw[len(raw.split()[0]):].strip()

        if cmd == ".reg":
            existing = store.load_player(db, sender)
            if existing:
                return f"You are already registered as *{existing['name']}*. Use .profile to see your character."
            if not rest:
                return "Usage: .reg <name>"
            ok, res = P.validate_name(rest)
            if not ok:
                return res
            pl = P.new_player(res)
            store.save_player(db, sender, pl)
            return (f"❄️ Welcome to Niflheim, *{pl['name']}*!\n"
                    f"You start at {P.location_name(pl['location'])} with {pl['hp']} HP.\n"
                    "Use .profile to see your character, .nmenu for commands.")

        if cmd == ".ngrant" and not is_admin:
            return NOT_HANDLED

        pl = store.load_player(db, sender)
        if not pl:
            if cmd in (".profile", ".p"):
                return "You are not registered in Niflheim yet. Use .reg <name>."
            return "You are not registered in Niflheim yet. Use .reg <name>."
        P.normalize(pl)

        # Catch-up: if the pushed arrival/event never happened, resolve it now, ahead of this reply.
        catchup, levelups = [], []
        if cmd != ".end":
            # an overdue fight round auto-attacks first, then a due journey event/arrival resolves
            fm, fl = combat.tick(db, sender)
            catchup += fm
            levelups += fl
            catchup += duel.tick_for(db, sender)          # expired invite / overdue duel round
            catchup += journey.resolve(db, sender)
            if catchup:
                pl = store.load_player(db, sender)
                P.normalize(pl)

        def reply(text, lvl=()):
            for m in list(levelups) + list(lvl):        # each level-up is its own message, in order
                self.router._send_to(sender, m)
            return "\n\n".join(catchup + [text]) if catchup else text

        if cmd in (".profile", ".p"):
            return reply(P.profile_text(pl))

        if cmd in (".inv", ".inventory"):
            return reply(shop.inv_text(pl))

        if cmd == ".shop":
            return reply(shop.shop_text(pl))

        if cmd in (".buy", ".sell", ".equip", ".unequip", ".use"):
            # .buy/.sell are always available. Changing gear or drinking outside .potion mid-fight is not.
            if cmd in (".equip", ".unequip", ".use") and (store.load_fight(db, sender)
                                                          or duel.active_duel(db, sender)):
                return reply("You can't do that in the middle of a fight. Use .attack, .defend or .potion.")
            msg = {".buy": shop.buy, ".sell": shop.sell, ".equip": shop.equip,
                   ".unequip": shop.unequip, ".use": shop.use}[cmd](pl, rest)
            store.save_player(db, sender, pl)
            return reply(msg)

        if cmd == ".hunt":
            if store.load_fight(db, sender):
                return reply("You're already in a fight! Use .attack, .defend or .potion.")
            if duel.active_duel(db, sender):
                return reply("You're in a duel! Use .attack, .defend or .potion.")
            if journey.get_active(db, sender):
                return reply("You can't hunt while travelling. Use .end first.")
            if world.is_town(pl["location"]):
                return reply("There is nothing to hunt in town. Head out with .explore first.")
            msgs, lvl = combat.auto_fight(db, sender, pl, group_jid=group_jid)   # Session 2: automatic
            return reply("\n".join(msgs), lvl)

        if cmd in (".website", ".site"):
            link = _site_link()
            if not link:
                return reply("The website is not set up yet.")
            return reply(f"❄️ *Niflheim Online*\nYour character, the Battle Arena and more:\n{link}")

        if cmd == ".arena":
            import os
            from niflheim import arena
            base = os.environ.get("ARENA_URL", "").strip()
            if not base:
                return reply("The Battle Arena website is not set up yet.")
            if store.load_fight(db, sender) or duel.active_duel(db, sender):
                return reply("Finish your current fight first.")
            t, e = arena.create_ticket(db, sender)
            if e:
                return reply(e)
            return reply(f"⚔️ *Niflheim Battle Arena*\nYour opponent: {t['foe']['name']} (Lv {t['foe']['level']})\n"
                         f"{_arena_link(base, t['ticket'])}\n_Link works for {t['expires_in'] // 60} minutes. Log in with your site account._")

        if cmd == ".dungeon":
            from niflheim import arena
            return reply(arena.boss_board(db, sender))

        if cmd == ".boss":
            import os
            from niflheim import arena
            base = os.environ.get("ARENA_URL", "").strip()
            if not base:
                return reply("The Battle Arena website is not set up yet.")
            if store.load_fight(db, sender) or duel.active_duel(db, sender):
                return reply("Finish your current fight first.")
            t, e = arena.boss_ticket(db, sender)
            if e:
                return reply(e)
            return reply(f"👑 *Boss Battle*\n{t['foe']['name']} (Lv {t['foe']['level']}) awaits.\n"
                         f"{_arena_link(base, t['ticket'])}\n_Link works for {t['expires_in'] // 60} minutes. Log in with your site account._")

        push = getattr(self.router, "_direct_send", None)

        if cmd == ".duel":
            if not group_jid:
                return DM_NOTICE
            if not mentioned_jid:
                return reply("Usage: .duel @player")
            return reply(duel.invite(db, sender, mentioned_jid, group_jid, push=push))

        if cmd in (".accept", ".decline"):
            return reply(duel.respond(db, sender, group_jid, cmd == ".accept", push=push))

        if cmd in (".attack", ".defend", ".potion") and not store.load_fight(db, sender) \
                and duel.active_duel(db, sender):
            ok, msgs = duel.act(db, sender, cmd[1:], rest.split()[0] if rest else None)
            return reply("\n\n".join(msgs))

        if cmd in (".attack", ".defend", ".potion"):
            ok, main, lvl = combat.act(db, sender, cmd[1:], rest.split()[0] if rest else None)
            return reply("\n\n".join(main), lvl if ok else ())

        if cmd == ".end":
            return journey.end(db, sender)

        if cmd == ".explore":
            direction = world.resolve_direction(rest.split()[0] if rest else "")
            if not direction:
                return reply("Usage: .explore <north/south/east/west>")
            ok, msg = journey.start(db, sender, pl, direction, group_jid=group_jid,
                                    push=getattr(self.router, "_direct_send", None))
            return reply(msg)

        if cmd in (".zone", ".look"):
            loc = world.get(pl["location"])
            lines = [f"📍 *{loc['name']}*", f"Type: {world.TYPE_LABEL.get(loc['type'], loc['type'])}"]
            if cmd == ".look":
                lines += ["", loc.get("description", "")]
            j = journey.get_active(db, sender)
            if j:
                import time as _t
                left = max(0, int(round(j["start"] + j["total"] - _t.time())))
                lines += ["", f"🚶 Travelling {j['direction']}... about {left}s left (.end to turn back)"]
            lines += ["", "Exits:"] + world.exits_lines(pl, loc)
            return reply("\n".join(lines))

        # DEV/TEST ONLY (King): .ngrant xp <n> | .ngrant coins <n> — exercises grant_xp/grant_coins.
        if cmd == ".ngrant":
            parts = rest.split()
            if len(parts) != 2 or parts[0] not in ("xp", "coins") or not parts[1].lstrip("-").isdigit():
                return "Usage: .ngrant xp <n> | .ngrant coins <n>"
            n = int(parts[1])
            if parts[0] == "xp":
                msgs = P.grant_xp(pl, n)
                store.save_player(db, sender, pl)
                for m in msgs:                      # one WhatsApp message per level, in order
                    self.router._send_to(sender, m)
                return f"Granted {n} XP. Levels gained: {len(msgs)}."
            P.grant_coins(pl, n)
            store.save_player(db, sender, pl)
            return f"Granted {n} coins. Balance: {pl['coins']}."
        return NOT_HANDLED
