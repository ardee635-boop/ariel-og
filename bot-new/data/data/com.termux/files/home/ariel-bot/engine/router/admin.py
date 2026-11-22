# ============================================================
# NIFLHEIM — router/admin.py
# Admin commands and test utilities
# ============================================================

from models import Player
from ._constants import STATE_IDLE


class AdminMixin:

    def _handle_admin(self, sender, player, cmd, args, text, mentioned_jid):
        if cmd == ".resetworld":
            return self._admin_reset_world()

        if cmd == ".player":
            return self._admin_test_player(sender, args)

        if cmd == ".home":
            # Admin escape hatch — warp back to Oak Town no matter what
            # movement state the player is in (mid-journey, dead-ended
            # in a dungeon with no return path, paused for battle, etc).
            # Explicitly tears down any active explore session first so
            # a later tick/.zone check can't clobber this back to the
            # in-progress destination.
            from .explore import ExploreSession
            session = ExploreSession.load(self.db, sender)
            if session.is_active():
                session.end()
                session.save(self.db)
            player.zone          = "oak_town"
            player.zone_x        = 2
            player.zone_y        = 4
            player.static_state  = None
            self._save(sender, player)
            return (
                "🏠 *Warped home to Oak Town.*\n\n"
                + self._render_zone_map(sender, player)
            )

        if cmd == ".tp":
            player.zone         = "oak_town"
            player.zone_x       = 2
            player.zone_y       = 4
            player.static_state = None
            self._save(sender, player)
            return (
                "🌀 *Teleported to Oak Town entrance.*\n\n"
                + self._render_zone_map(sender, player)
            )

        if cmd == ".setstage":
            if not args:
                return "⚠️ Usage: *.setstage [stage]*"
            player.story_stage = args[0]
            self._save(sender, player)
            return f"✅ story_stage set to `{args[0]}`"

        if cmd == ".addlegacy":
            if not args:
                return "⚠️ Usage: *.addlegacy [phone number]*  (digits only, no +)"
            phone = args[0].strip().lstrip("+")
            if not phone.isdigit():
                return "⚠️ Phone number must be digits only, e.g. *.addlegacy 2348000000000*"
            target_sender = f"{phone}@s.whatsapp.net"
            if self.db.legacy_player_exists(target_sender):
                return f"ℹ️ `{target_sender}` is already on the legacy list."
            self.db.legacy_player_add(target_sender, added_by=sender)
            return f"✅ `{target_sender}` added to the legacy list — will get a legacy egg on next starter grant."

        if cmd == ".legacylist":
            rows = self.db.legacy_players_all()
            if not rows:
                return "📋 No players added via *.addlegacy* yet."
            lines = [f"• {r['sender']} (added {r['added_at']})" for r in rows]
            return "📋 *Legacy list (post-launch additions):*\n" + "\n".join(lines)

        if cmd == ".legacy":
            # Snapshot everyone currently signed in (phone JID + LID, plus
            # site accounts) onto the legacy list, in one go.
            r = self.db.legacy_add_all_signed_in(added_by=sender)
            return (
                "👑 *Legacy snapshot done.*\n"
                f"• Players scanned: {r['players']}\n"
                f"• Site accounts scanned: {r['site']}\n"
                f"• Unique ids found (jid + lid): {r['ids']}\n"
                f"• Newly added: {r['added']} "
                f"({r['added_jid']} jid, {r['added_lid']} lid)\n"
                f"• Already on the list: {r['already']}\n\n"
                "_Run *.legacylist* to see the list. Legacy survives "
                "*.resetplayers*._"
            )

        if cmd == ".resetplayers":
            # Destructive and irreversible, so it needs an explicit confirm.
            if not args or args[0].lower() != "confirm":
                n = len(self.db.all_senders())
                return (
                    f"⚠️ *This wipes ALL {n} registered player(s)* and everything "
                    "about them, in every world: profiles, parties/boxes, "
                    "registrations, meta/RPG sessions, Niflheim data, NPC "
                    "memory, affection, directives, site accounts and warnings.\n\n"
                    "Kept: the legacy list, royalty ranks, and the world itself.\n\n"
                    "Run *.legacy* first if you haven't. "
                    "To proceed, send: *.resetplayers confirm*"
                )
            counts = self.db.reset_all_players()
            self.cache.clear()
            self.sessions.clear()
            lines = [f"• {t}: {n}" for t, n in counts.items()]
            return (
                "🗑️ *All players wiped.*\n" + "\n".join(lines) +
                "\n\n_Legacy list, ranks and world data were left untouched._"
            )

        if cmd == ".delete":
            if not args: return "⚠️ Usage: *.delete [name]*"
            tn = " ".join(args)
            ts, tp = self._find_player_by_name(tn)
            if not tp: return f"❓ '{tn}' not found."
            self.db.delete(ts); self.db.delete_reg(ts)
            self.cache.pop(ts, None); self.sessions.pop(ts, None)
            return f"🗑️ *{tn}* deleted."

        return None

    def _find_player_by_name(self, name):
        import json
        try:
            rows = self.db.conn.execute("SELECT sender, data FROM players").fetchall()
            for sender, data in rows:
                try:
                    d = json.loads(data)
                    if d.get("name", "").lower() == name.lower():
                        p = self._get(sender)
                        if p: return sender, p
                except: pass
        except: pass
        return None, None

    def _admin_test_player(self, sender, args):
        test = Player("TestPlayer")
        test.story_stage = "new"
        test.zone        = "oak_town"
        test.zone_x      = 12
        test.zone_y      = 6
        self.cache[sender] = test
        self.db.save(sender, test)
        return "🧪 Test player created."

    def _admin_reset_world(self):
        """
        .resetworld — full world reset, per the movement-rebuild
        session's locked spec:
          1. Wipe every invented AND hardcoded Place/Passage row,
             every world NPC, every world object (database.reset_world()).
          2. Re-seed the hardcoded tree fresh from source
             (rpg_places_seed.seed_hardcoded_tree()) — even hand-
             authored data is rewritten, not preserved from whatever
             was in the DB before, so a hand-edited row can never
             survive a reset by accident.
          3. Reset every active RPG session's location back to
             STARTING_LOCATION_ID — a wipe can leave old location_id
             values (invented places, or even a re-seeded hardcoded
             place with a fresh row) dangling for anyone standing
             there.
        Does NOT touch soulbound/inventory/class/trial progress —
        this resets the WORLD, not player characters, per that same
        session's explicit scope.
        """
        from rpg_places_seed import seed_hardcoded_tree
        from rpg_session import RpgSession, META_KEY, STARTING_LOCATION_ID

        self.db.reset_world()
        seed_hardcoded_tree(self.db)

        senders = self.db.all_senders_with_meta_key(META_KEY)
        moved = 0
        for s in senders:
            session = RpgSession.load(self.db, s)
            if not session.exists:
                continue
            session.location_id = STARTING_LOCATION_ID
            session.location = "the town square"
            session.scene_objects = []
            # a wipe invalidates any open journey and its numbered choices
            session.flags.pop("_journey", None)
            session.flags["_choices"] = []
            session.save(self.db)
            moved += 1

        return (
            f"🌍 World reset. Hardcoded places/NPCs/objects re-seeded "
            f"fresh; every invented place, passage, and world object "
            f"wiped. {moved} active player(s) returned to the town square."
        )
