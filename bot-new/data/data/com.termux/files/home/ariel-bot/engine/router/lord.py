# ============================================================
# NIFLHEIM — router/lord.py
# King-only dev commands: .ff, .ffp
# ============================================================

import random
from permissions import is_king
from encounters import build_wild_monster, encounter_screen
from combat_session import STATE_ENCOUNTER, STATE_EXPLORING


class LordMixin:

    # ── Entry point ───────────────────────────────────────────

    def _handle_lord(self, sender, player, cmd, args, text, mentioned_jid):
        """King-only dev tools: .ff / .ffp (warm the PokeAPI move cache).
        .throne/.dethrone/.lords/.spawn/.spawnp used to live here; the rank system
        (.crown/.dethrone/.ranks) and .spawn/.spawnp are handled by bot/admin (JS),
        which always answered first, so the Python copies were unreachable."""
        if not is_king(sender):
            return None   # let the handler fall through
        if cmd == ".ff":
            return self._cmd_ff(sender, args)
        if cmd == ".ffp":
            return self._cmd_ffp(sender, args)
        return None

    def _cmd_ff(self, sender, args):
        """
        .ff            → 1 random move
        .ff 10         → 10 random moves
        .ff light      → 1 random move containing 'light'
        .ff light 10   → 10 random moves containing 'light'
        .ff tackle     → cache specific move 'tackle'
        .ff cyndaquil  → all moves of cyndaquil (detected by non-numeric, non-filter)
        """
        import requests
        from pokeapi import get_move, get_full

        # Parse args
        filter_str = None
        count      = 1
        is_poke    = False

        if len(args) == 0:
            pass
        elif len(args) == 1:
            if args[0].isdigit():
                count = min(int(args[0]), 50)
            else:
                filter_str = args[0].lower()
        elif len(args) >= 2:
            if args[1].isdigit():
                filter_str = args[0].lower()
                count      = min(int(args[1]), 50)
            else:
                filter_str = args[0].lower()

        self._send_to(sender, f"_Fetching move list from PokéAPI…_")

        # Check if filter_str is a Pokémon name
        if filter_str:
            poke_data = get_full(self.db, filter_str)
            if poke_data and poke_data.get("moves"):
                # It's a Pokémon — fetch all its moves
                move_names = [m["move"]["name"] if isinstance(m, dict) and "move" in m
                              else m for m in poke_data["moves"]]
                self._send_to(sender, f"_Found {len(move_names)} moves for *{filter_str.capitalize()}*. Caching…_")
                cached, failed = 0, 0
                for mn in move_names:
                    try:
                        result = get_move(self.db, mn)
                        if result:
                            cached += 1
                        else:
                            failed += 1
                    except Exception:
                        failed += 1
                return (
                    f"✅ *{filter_str.capitalize()}* moves cached.\n"
                    f"  Cached: *{cached}* · Failed: *{failed}*"
                )

        # Fetch full move list from PokeAPI
        try:
            resp  = requests.get("https://pokeapi.co/api/v2/move?limit=10000", timeout=10)
            moves = resp.json().get("results", [])
        except Exception as e:
            return f"❌ Failed to fetch move list: {e}"

        all_names = [m["name"] for m in moves]

        # Apply filter
        if filter_str:
            pool = [n for n in all_names if filter_str in n]
            if not pool:
                return f"❌ No moves found matching `{filter_str}`."
        else:
            pool = all_names

        selected = random.sample(pool, min(count, len(pool)))

        self._send_to(sender, f"_Caching *{len(selected)}* move(s)…_")
        cached, failed = 0, 0
        for mn in selected:
            try:
                result = get_move(self.db, mn)
                if result:
                    cached += 1
                else:
                    failed += 1
            except Exception:
                failed += 1

        names_preview = ", ".join(n.replace("-", " ").title() for n in selected[:5])
        if len(selected) > 5:
            names_preview += f" … (+{len(selected) - 5} more)"
        return (
            f"✅ Move fetch complete.\n"
            f"  Cached: *{cached}* · Failed: *{failed}*\n"
            f"  _{names_preview}_"
        )

    # ── .ffp (fetch/cache Pokémon + their moves) ─────────────

    def _cmd_ffp(self, sender, args):
        """
        .ffp      → 1 random Pokémon + all its moves
        .ffp 10   → 10 random Pokémon + all their moves
        """
        import requests
        from pokeapi import get_full, get_move

        count = 1
        if args and args[0].isdigit():
            count = min(int(args[0]), 20)

        self._send_to(sender, f"_Fetching Pokémon list from PokéAPI…_")

        try:
            resp  = requests.get("https://pokeapi.co/api/v2/pokemon?limit=10000", timeout=10)
            pokes = resp.json().get("results", [])
        except Exception as e:
            return f"❌ Failed to fetch Pokémon list: {e}"

        all_names = [p["name"] for p in pokes]
        selected  = random.sample(all_names, min(count, len(all_names)))

        self._send_to(sender, f"_Caching *{len(selected)}* Pokémon + their moves…_")

        total_poke, total_moves, failed = 0, 0, 0
        for pname in selected:
            try:
                pdata = get_full(self.db, pname)
                if not pdata:
                    failed += 1
                    continue
                total_poke += 1
                move_names = [m["move"]["name"] if isinstance(m, dict) and "move" in m
                              else m for m in pdata.get("moves", [])]
                for mn in move_names:
                    try:
                        if get_move(self.db, mn):
                            total_moves += 1
                    except Exception:
                        pass
            except Exception:
                failed += 1

        poke_preview = ", ".join(n.capitalize() for n in selected[:5])
        if len(selected) > 5:
            poke_preview += f" … (+{len(selected) - 5} more)"
        return (
            f"✅ Pokémon fetch complete.\n"
            f"  Pokémon: *{total_poke}* · Moves: *{total_moves}* · Failed: *{failed}*\n"
            f"  _{poke_preview}_"
        )
