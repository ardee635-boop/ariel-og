# ============================================================
# NIFLHEIM — router/movement.py
# Zone-grid movement (oak_town, route_1, etc.)
# ============================================================

import random
from ._constants import STATE_EXPLORING, STATE_IDLE


def old_man_block() -> str:
    """
    Blocks Oak Town → Route 1 until the player has a starter.
    Moved here from the old npc.py (deleted) — this is a movement
    gate, not NPC dialogue, so it stays even with Oak's chat gone.
    """
    return (
        "*Old Man Bram steps into your path.*\n"
        "Hold on there. Route 1 is no place to go empty-handed.\n"
        "Get yourself a Pokémon from the Professor first.\n"
        "_The road west is blocked._"
    )


class MovementMixin:

    def _handle_movement(self, sender, player, direction: str) -> str | None:
        """
        Zone-aware movement for any zone file (oak_town, route_1, etc).
        Returns reply string, or None to fall through to world_registry movement.
        """
        # ── Static state — movement silently blocked ───────────
        if getattr(player, "static_state", None):
            return None

        # ── Arena state — movement locked ─────────────────────
        from combat_session import (
            STATE_ARENA, STATE_ARENA_PENDING, STATE_GYM, STATE_GYM_PENDING,
            STATE_BATTLE, STATE_ENCOUNTER, STATE_PVP, STATE_RAID,
        )
        _sess = self._session(sender)
        if _sess.state == STATE_ARENA:
            return "_You're in the arena. Use_ `.next` _to fight or finish your battles._"
        if _sess.state == STATE_ARENA_PENDING:
            return "_Battle is about to start..._"
        if _sess.state == STATE_GYM:
            return "_You're in the gym. Use_ `.next` _to fight or finish your battles._"
        if _sess.state == STATE_GYM_PENDING:
            return "_Battle is about to start..._"
        if _sess.state == STATE_BATTLE and getattr(_sess, "arena_trainer_name", None):
            return "_You're in an arena battle! Finish the fight first._"
        if _sess.state == "battle_menu" and getattr(_sess, "arena_trainer_name", None):
            return "_You're in an arena battle! Finish the fight first._"
        if _sess.state in (STATE_BATTLE, "battle_menu"):
            return "_You can't move during a battle! Finish the fight first._"
        if _sess.state == STATE_ENCOUNTER:
            return "_A wild Pokémon is right there! Fight or flee before moving on._"
        if _sess.state == STATE_PVP:
            return "_You're in a PvP battle! Finish the fight first._"
        if _sess.state == STATE_RAID:
            return "_You're in a raid battle! Finish the fight first._"

        # ── PC healing — block movement until timestamp expires ─
        pc_heal_val = self.db.get_meta(sender, "pc_healing")
        if pc_heal_val:
            import time as _time
            try:
                if _time.time() < float(pc_heal_val):
                    return "_Please wait while your Pokémon are being healed..._"
                else:
                    self.db.delete_meta(sender, "pc_healing")
            except ValueError:
                self.db.delete_meta(sender, "pc_healing")

        # ── NPC conversation — movement breaks it ─────────────
        active_npc = self.db.get_meta(sender, "active_npc")
        if active_npc:
            self.db.delete_meta(sender, "active_npc")
            self.db.delete_meta(sender, "active_npc_name")
            # Don't block movement — just end convo silently and continue

        zone_id = getattr(player, "zone", "oak_town")

        from map import load_zone, IMPASSABLE, get_npc, get_sign

        ZONE = load_zone(zone_id)
        if not ZONE:
            return None

        col, row = player.zone_x, player.zone_y

        MOVE_DELTA = {"1": (0, -1), "2": (0, 1), "3": (-1, 0), "4": (1, 0),
                      "-1": (0, -1), "-2": (0, 1), "-3": (-1, 0), "-4": (1, 0)}
        dc, dr  = MOVE_DELTA.get(direction, (0, 0))
        new_col = col + dc
        new_row = row + dr

        grid   = ZONE["grid"]
        width  = ZONE["width"]
        height = ZONE["height"]

        # ── Out of bounds — hard wall ─────────────────────────
        is_oob = not (0 <= new_col < width and 0 <= new_row < height)
        if is_oob:
            return "_There is nothing that way._"

        tile = grid[new_row][new_col]

        # ── EX tile — zone exit ───────────────────────────────
        if tile == "EX":
            exits = ZONE.get("exits", {})
            exit_def = exits.get(f"{new_row},{new_col}")
            if not exit_def:
                return "_The way is blocked._"

            to_zone   = exit_def["to_zone"]
            to_exit   = exit_def.get("to_exit")
            dest_zone = load_zone(to_zone)
            if not dest_zone:
                return "_The way is blocked._"

            # ── ID-based exit linking ─────────────────────────
            if to_exit:
                exit_positions = dest_zone.get("exit_positions", {})
                dest_pos = exit_positions.get(to_exit)
                if not dest_pos:
                    return "_The way is blocked._"
                sc, sr = dest_pos
            else:
                # fallback: legacy hardcoded spawn
                sc, sr = exit_def["spawn"]

            # Oak Town → Route 1 gate check
            if zone_id == "oak_town" and to_zone == "route_1":
                if getattr(player, "story_stage", "new") not in ("has_starter", "route_1"):
                    return old_man_block()
                player.story_stage = "route_1"
                player.objective   = "Explore Route 1 — find and catch wild Pokémon"

            player.zone   = to_zone
            player.zone_x = sc
            player.zone_y = sr
            # Track visited zones for .quicktravel
            visited = player.get_flag("visited_zones", [])
            if to_zone not in visited:
                visited.append(to_zone)
                player.set_flag("visited_zones", visited)
            # Quest hook — reach_location
            try:
                from .quests import on_move as _on_move
                _on_move(player, to_zone)
            except Exception:
                pass
            self._session(sender).transition(STATE_EXPLORING)
            self._save(sender, player)
            dest_name = dest_zone.get("name", to_zone.replace("_", " ").title())
            arrival   = f"📍 *Entering {dest_name}*"
            return arrival + "\n" + self._render_zone_map(sender, player)

        # ── Impassable tiles ──────────────────────────────────
        if tile in IMPASSABLE:
            if tile == "~~":
                return "_The sea blocks your path._"
            if tile == "WW":
                return "_The water is too deep to cross._"
            if tile == "BB":
                return "_A berry tree blocks your way._"
            return "_The way is blocked._"

        # ── Lab tile (oak_town only) ───────────────────────────
        # NOTE: starter granting now happens entirely on the site's Starter
        # Reveal page (see router/site_actions.py:handle_grant_starter). The
        # old in-WhatsApp "reply 1/2/3 to Prof. Oak" flow (router/lab.py,
        # LabMixin) is no longer wired into the router, so setting
        # story_stage to "at_lab"/"choosing"/"confirming" here used to leave
        # players stuck with no handler ever reading their reply. Quest 1
        # completion / Quest 2 grant (on_lab_entered) still happens as
        # before — only the dead reply-flow state is removed.
        if tile == "LL":
            player.zone_x = new_col
            player.zone_y = new_row

            if getattr(player, "story_stage", "new") in ("has_starter", "route_1"):
                player.static_state = None
                self._save(sender, player)
                return "_The doctor is busy right now..._"

            player.static_state = None

            from .quests import on_lab_entered
            quest_msgs = on_lab_entered(player)
            for i, msg in enumerate(quest_msgs, 1):
                self._queue_message(sender, msg, delay=i)

            self._save(sender, player)

            delay = len(quest_msgs) + 1
            oak_msg = (
                "*Prof. Oak looks up from his notes.*\n"
                "Ah — {name}. Your starter is waiting for you —\n"
                "head to the site to claim it:\n"
                "https://ariel-og.vercel.app/"
            ).format(name=player.name)
            self._queue_message(sender, oak_msg, delay=delay)
            return None

        # ── House tile ────────────────────────────────────────
        if tile == "HH":
            return "_You peek inside. Nothing for you here yet._"

        # ── Pokémart tile ─────────────────────────────────────
        if tile == "PS":
            return self._open_mart(sender, player)



        # ── Pokémon Center tile ───────────────────────────────
        if tile == "PC":
            player.zone_x = new_col
            player.zone_y = new_row

            # Heal all party
            healed = 0
            for mon in getattr(player, "party", []):
                if hasattr(mon, "heal_full"):
                    mon.heal_full()
                    healed += 1

            from combat_session import STATE_EXPLORING, STATE_DEAD
            import time as _time
            session = self._session(sender)
            if session.state == STATE_DEAD:
                session.transition(STATE_EXPLORING)

            # Set heal lock with expiry timestamp (3 seconds)
            self.db.set_meta(sender, "pc_healing", str(_time.time() + 3))
            self._save(sender, player)

            self._queue_message(sender,
                "🏥 *Pokémon Center*\n"
                "━━━━━━━━━━━━━━━━\n"
                "_Welcome to the Pokémon Care Center.\n"
                "Please wait while we heal your Pokémon..._",
                delay=0
            )

            heal_msg = (
                f"✅ _All {healed} of your Pokémon have been healed to full health!_\n"
                "_You're free to go._"
            ) if healed else "✨ _Your Pokémon are already at full health!_\n_You're free to go._"

            self._queue_message(sender, f"🏥 *Pokémon Care Center*\n━━━━━━━━━━━━━━━━\n{heal_msg}", delay=3)
            return None

        # ── Sign tile ─────────────────────────────────────────
        if tile == "SG":
            sign = get_sign(zone_id, new_row, new_col)
            if sign:
                return f"📋 {sign}"

        # ── Cave tile — blocked for now ───────────────────────
        if tile == "CC":
            return "_The cave entrance is sealed. Come back later._"

        # ── Normal movement ───────────────────────────────────
        player.zone_x = new_col
        player.zone_y = new_row
        self._save(sender, player)

        # ── Encounter check for grass/water tiles ─────────────
        try:
            if tile in ("GG", "WW") and zone_id not in ("oak_town",):
                from encounters import roll_encounter
                respite = player.get_flag("respite_steps", 0)
                if respite > 0:
                    player.set_flag("respite_steps", respite - 1)
                    self._save(sender, player)
                else:
                    grass_steps = player.get_flag("grass_steps", 0)
                    if roll_encounter(grass_steps):
                        player.set_flag("grass_steps", 0)
                        player.set_flag("respite_steps", 1)
                        self._save(sender, player)
                        from ._constants import STATE_EXPLORING
                        session = self._session(sender)
                        session.transition(STATE_EXPLORING)
                        return self._spawn_encounter(sender, player, session, direction,
                                                     "water" if tile == "WW" else "GG")
                    else:
                        player.set_flag("grass_steps", grass_steps + 1)
                        self._save(sender, player)
            elif tile not in ("GG", "WW"):
                player.set_flag("grass_steps", 0)
                self._save(sender, player)
        except Exception as e:
            import sys
            print(f"[MOVEMENT] encounter check error: {e}", file=sys.stderr, flush=True)

        return self._render_zone_map(sender, player)

    # ────────────────────────────────────────────────────────────
    # FROZEN — .dash (multi-step grid dash)
    #
    # Moved here from router/handle.py's command dispatch as part
    # of the .explore rework (see explore_checklist.md Phase 1).
    # No longer reachable via any command — router entry for
    # ".dash" was deleted in handle.py. Logic below is otherwise
    # completely unchanged, kept intact for a future Discord build
    # where real grid movement may return.
    # ────────────────────────────────────────────────────────────
    def _handle_dash_FROZEN(self, sender, player, session, args, stage):
        from map import load_zone, IMPASSABLE, ENCOUNTER_TILES, is_safe_zone
        from ._constants import STATE_BATTLE, STATE_ENCOUNTER

        if stage in (STATE_BATTLE, STATE_ENCOUNTER):
            return "_You can't dash during a battle._"
        if not args or len(args) < 2:
            return "_Usage: .dash [1/2/3/4] [steps]  e.g. .dash 2 10_"
        direction = args[0]
        if direction not in ("1", "2", "3", "4"):
            return "_Direction must be 1 (north) 2 (south) 3 (west) 4 (east)._"
        if not args[1].isdigit():
            return "_Steps must be a number._"
        steps = min(int(args[1]), 20)  # cap at 20
        if steps < 1:
            return "_Steps must be at least 1._"

        DELTA = {"1": (0, -1), "2": (0, 1), "3": (-1, 0), "4": (1, 0)}
        dc, dr = DELTA[direction]

        zone_id  = getattr(player, "zone", "oak_town")
        zone     = load_zone(zone_id)
        grid     = zone.get("grid", [])
        height   = zone.get("height", len(grid))
        width    = zone.get("width", len(grid[0]) if grid else 0)
        exits    = zone.get("exits", {})
        npcs     = zone.get("npcs", {})

        # NPC tile positions
        npc_tiles = set()
        for r, row in enumerate(grid):
            for c, t in enumerate(row):
                if t == "NP":
                    npc_tiles.add((r, c))

        moved   = 0
        stopped = None
        encounter_triggered = False

        cx, cy = player.zone_x, player.zone_y

        for _ in range(steps):
            nx = cx + dc
            ny = cy + dr

            # Check EX — stop before it
            exit_key = f"{ny},{nx}"
            if exit_key in exits:
                stopped = "zone exit ahead"
                break

            # Out of bounds
            if not (0 <= nx < width and 0 <= ny < height):
                stopped = "edge of zone"
                break

            tile = grid[ny][nx] if grid else "TT"

            # Impassable — stop before
            if tile in IMPASSABLE:
                stopped = "blocked"
                break

            # NPC adjacent — stop one tile before
            if (ny, nx) in npc_tiles:
                stopped = "NPC ahead"
                break

            # Move accepted
            cx, cy = nx, ny
            moved += 1

            # Encounter roll on encounter tiles
            if tile in ENCOUNTER_TILES and not is_safe_zone(zone_id):
                import random
                from encounters import roll_wild_pokemon, build_wild_monster, encounter_screen
                from pokeapi import get_full
                grass_walked = player.get_flag("dash_grass_steps", 0) + 1
                player.set_flag("dash_grass_steps", grass_walked)
                # Guaranteed encounter after 5 grass tiles; otherwise 30% per tile
                roll = random.random()
                if roll < 0.30 or grass_walked >= 5:
                    player.set_flag("dash_grass_steps", 0)
                    result = roll_wild_pokemon(zone_id, "grass")
                    if result:
                        species, level = result
                        api_data = get_full(self.db, species)
                        if api_data:
                            monster = build_wild_monster(api_data, level)
                            player.zone_x = cx
                            player.zone_y = cy
                            player.see_pokemon(species)
                            session.set_encounter(monster, None)
                            self._save(sender, player)
                            dir_names = {"1":"north","2":"south","3":"west","4":"east"}
                            return (
                                f"_Dashed {moved} step(s) {dir_names[direction]}..._\n\n"
                                + encounter_screen(monster)
                            )

        player.zone_x = cx
        player.zone_y = cy
        self._save(sender, player)

        dir_names = {"1":"north","2":"south","3":"west","4":"east"}
        msg = f"_Dashed {moved} step(s) {dir_names[direction]}._"
        if stopped:
            msg += f"\n_{stopped.capitalize()}._"
        if moved == 0:
            msg = f"_Can't move that way._"
        return msg + "\n\n" + self._render_zone_map(sender, player)

