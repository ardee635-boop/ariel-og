# ============================================================
# LAB.PY  —  Oak Lab 1 flow
# Triggered exclusively via static_state = "oak_lab_1"
# story_stage values: at_lab → choosing → confirming → has_starter
# ============================================================

from data_pokemon import STARTERS

# Number → starter key
_NUM_TO_STARTER = {
    "1": "cyndaquil", "-1": "cyndaquil",
    "2": "chikorita", "-2": "chikorita",
    "3": "squirtle",  "-3": "squirtle",
}

# Valid reply: quotes bot message or tags bot number
def _is_valid_reply(text, quoted_text, mentioned_jid, bot_jid):
    if text.startswith("."):
        return False
    if quoted_text is not None:
        return True
    if mentioned_jid and bot_jid and mentioned_jid == bot_jid:
        return True
    return False


class LabMixin:

    def _handle_lab_flow(self, sender, player, text,
                         quoted_text=None, mentioned_jid=None) -> str | None:
        stage = getattr(player, "story_stage", "at_lab")
        lower = text.strip().lower()

        # ── at_lab — waiting for any valid reply ──────────────
        if stage == "at_lab":
            bot_jid = getattr(self, "_bot_jid", None)
            if not _is_valid_reply(text, quoted_text, mentioned_jid, bot_jid):
                return None
            player.story_stage = "choosing"
            self._save(sender, player)
            return self._oak_starter_menu()

        # ── choosing — pick by number ─────────────────────────
        if stage == "choosing":
            chosen = _NUM_TO_STARTER.get(lower)
            if not chosen:
                return None
            from pokeapi import get_full
            api_data = get_full(self.db, chosen)
            s        = STARTERS[chosen]
            label    = s["label"]
            ptype    = s["type"]
            lore     = s["lore"]
            sprite   = api_data.get("sprite", "") if api_data else ""

            player.set_flag("pending_starter", chosen)
            player.story_stage = "confirming"
            self._save(sender, player)

            caption = (
                f"Name: {label}\n"
                f"Type: {ptype}\n"
                f"Stars: {'✧' * 6}\n"
                f"Description: {lore}\n\n"
                f"Do you wish to take this {label}?\n"
                f"1. Yes\n"
                f"2. No"
            )
            if sprite:
                return f"__IMG__{sprite}__CAP__{caption}"
            return caption

        # ── confirming — yes or no ────────────────────────────
        if stage == "confirming":
            if lower in ("1", "-1", "yes", ".yes", "y", "yep", "yeah", "sure", "ok"):
                chosen = player.get_flag("pending_starter")
                if not chosen:
                    player.story_stage = "choosing"
                    self._save(sender, player)
                    return self._oak_starter_menu()
                # Move to naming stage
                player.story_stage = "naming"
                self._save(sender, player)
                s = STARTERS[chosen]
                return (
                    f"What would you like to call your {s['label']}?\n\n"
                    f"Reply with `.name nickname` or `.skip`"
                )

            if lower in ("2", "-2", "no", ".no", "n", "nope", "nah"):
                player.story_stage = "choosing"
                self._save(sender, player)
                return self._oak_starter_menu()

            return None

        # ── naming — set nickname ─────────────────────────────
        if stage == "naming":
            chosen = player.get_flag("pending_starter")
            if not chosen:
                player.story_stage = "choosing"
                self._save(sender, player)
                return self._oak_starter_menu()

            s = STARTERS[chosen]
            label = s["label"]

            # .skip — use species name
            if lower in (".skip", "skip"):
                return self._give_starter(sender, player, chosen, nickname=label)

            # .name <nickname>
            if lower.startswith(".name "):
                raw = text[6:].strip()
                if not raw:
                    return "_Usage: `.name nickname` or `.skip`_"
                # Store pending nickname and ask confirm
                player.set_flag("pending_nickname", raw)
                self._save(sender, player)
                return (
                    f"Do you wish to name your {label} *{raw}*?\n\n"
                    f"1. Yes\n"
                    f"2. No"
                )

            # Confirm nickname yes/no
            pending_nick = player.get_flag("pending_nickname")
            if pending_nick:
                if lower in ("1", "-1", "yes", ".yes", "y", "yep", "yeah"):
                    return self._give_starter(sender, player, chosen, nickname=pending_nick)
                if lower in ("2", "-2", "no", ".no", "n", "nope", "nah"):
                    player.set_flag("pending_nickname", None)
                    self._save(sender, player)
                    return (
                        f"What would you like to call your {label}?\n\n"
                        f"Reply with `.name nickname` or `.skip`"
                    )

            return "_Reply with `.name nickname` or `.skip`_"

        # ── has_starter — .next handling ─────────────────────
        if stage == "has_starter":
            from egg import LEGACY_IDS, egg_receive_message, start_incubation

            if lower not in (".next", "next"):
                return None

            is_legacy = sender in LEGACY_IDS
            pending_egg = player.get_flag("pending_egg")

            if is_legacy and pending_egg:
                oak_egg_said = player.get_flag("oak_egg_said")
                if not oak_egg_said:
                    # First .next: Oak says egg line
                    from egg import egg_gift_oak_line
                    player.set_flag("oak_egg_said", True)
                    self._save(sender, player)
                    self._queue_message(sender, egg_gift_oak_line(sender, player.name), delay=1)
                    return None
                # Second .next: send egg
                player.set_flag("pending_egg", None)
                player.set_flag("oak_egg_said", None)
                player.set_flag("egg_received", True)
                self._save(sender, player)
                egg_msg = egg_receive_message(pending_egg)
                full_msg = (
                    egg_msg + "\n\n"
                    "_\"Take good care of it...\"_\n\n"
                    "_Use_ `.inv` _to see details_\n"
                    "_Use_ `.next` _to continue_"
                )
                player.add_item(pending_egg, 1) if hasattr(player, 'add_item') else player.inventory.update({pending_egg: player.inventory.get(pending_egg, 0) + 1})
                start_incubation(sender, pending_egg, self)
                self._queue_message(sender, full_msg, delay=1)
                return None

            # Final .next — give route1 items, Greenwood quest, exit
            return self._exit_lab(sender, player)

        return None

    # ── Exit lab ──────────────────────────────────────────────
    def _exit_lab(self, sender, player) -> None:
        from .quests import on_route1_begin
        route_msgs = on_route1_begin(player)
        # Spawn back in oak_town at the western exit tile so the player
        # walks left themselves to cross into route_1.
        player.zone            = "oak_town"
        player.zone_x          = 1
        player.zone_y          = 4
        player.static_state    = None
        player.story_stage     = "has_starter"
        player.objective       = "Head to Route 1 ➜"
        self._save(sender, player)
        for i, msg in enumerate(route_msgs, 1):
            self._queue_message(sender, msg, delay=i)
        return None

    # ── Starter selection menu ────────────────────────────────
    def _oak_starter_menu(self) -> str:
        return (
            "Well, take a look at my babies kiddo, cute right? "
            "But you only get to pick one.\n\n"
            "1. Cyndaquil\n"
            "2. Chikorita\n"
            "3. Squirtle\n\n"
            "_Reply with the list number to choose_\n"
            "_E.g_ `1` _or_ `-1`"
        )

    # ── Give starter ──────────────────────────────────────────
    def _give_starter(self, sender, player, chosen: str, nickname: str = None) -> str:
        from pokeapi import get_full
        from .quests import on_starter_chosen
        from models import OwnedPokemon
        from data_pokemon import starter_given_text as _given_text
        from egg import LEGACY_IDS, assign_legacy_egg

        api_data = get_full(self.db, chosen)
        if not api_data:
            return "_Something went wrong fetching that Pokémon. Try again._"

        s = STARTERS[chosen]
        display = nickname or s["label"]
        pokemon = OwnedPokemon(api_data, nickname=display, level=5, stars=6)

        # Add to player party
        player.add_to_party(pokemon)
        player.set_flag("pending_starter", None)

        is_legacy = sender in LEGACY_IDS
        import sys as _sys; print(f'[LAB] give_starter sender={sender} is_legacy={is_legacy}', file=_sys.stderr, flush=True)

        player.story_stage  = "has_starter"
        player.static_state = "oak_lab_1"

        if is_legacy:
            egg_name = assign_legacy_egg(sender)
            import sys as _sys; print(f'[LAB] egg assigned={egg_name}', file=_sys.stderr, flush=True)
            player.set_flag("pending_egg", egg_name)
            player.inventory[egg_name] = player.inventory.get(egg_name, 0) + 1

        # Quest hooks
        quest_msgs = on_starter_chosen(player, chosen)
        self._save(sender, player)

        for i, msg in enumerate(quest_msgs, 1):
            self._queue_message(sender, msg, delay=i)

        delay = len(quest_msgs) + 1

        oak_name_line = (
            f"*Prof. Oak:* An interesting name indeed... Haha!\n\n"
            f"_Use_ `.next` _to continue._"
        )
        self._queue_message(sender, oak_name_line, delay=delay)

        return None
