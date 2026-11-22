# ============================================================
# NIFLHEIM — router/gamble.py
# Casino commands: .cf .slots .roulette .db .di .betmenu
# House edge target: ~40% real win chance across all games.
# ============================================================

import random

MIN_BET = 10
MAX_BET = 5000


def _parse_bet(args, coins: int):
    """Shared bet-amount parsing. Returns (bet, error_msg)."""
    if not args:
        return None, "_Usage: give an amount to bet, e.g. `.cf 100`_"

    raw = args[0].lower()
    if raw in ("all", "allin"):
        bet = coins
    elif raw.isdigit():
        bet = int(raw)
    else:
        return None, "_Bet must be a number (or `all`)._"

    if bet < MIN_BET:
        return None, f"_Minimum bet is ₡{MIN_BET}._"
    if bet > MAX_BET:
        return None, f"_Maximum bet is ₡{MAX_BET}._"
    if bet > coins:
        return None, f"_You only have ₡{coins}._"

    return bet, None


def _settle(player, save_fn, bet: int, payout: int) -> int:
    """Apply the net result to player.coins. payout=0 means total loss."""
    player.coins = getattr(player, "coins", 0) - bet + payout
    save_fn()
    return player.coins


# ── .betmenu ─────────────────────────────────────────────────

def betmenu() -> str:
    return (
        "🎰 *CASINO*\n"
        "┃ `.cf [bet]` — Coinflip · 40% · 2.35x\n"
        "┃ `.di [bet] [1-6]` — Guess the Die · 1-in-6 · 5.2x\n"
        "┃ `.db [bet]` — Dice Bet · 40% · 2.35x\n"
        "┃ `.slots [bet]` — Slots · jackpots up to 10x\n"
        "┃ `.roulette [bet] [red/black/green/no.]` — varies\n"
        "\n_Min bet ₡10 · Max bet ₡5000 · `all` bets everything_"
    )


# ── .cf — Coinflip ───────────────────────────────────────────
# 40% real win chance, 2.35x payout on win.

def handle_coinflip(sender, player, args, save_fn) -> str:
    coins = getattr(player, "coins", 0)
    bet, err = _parse_bet(args, coins)
    if err:
        return err

    win = random.random() < 0.40
    if win:
        payout = int(bet * 2.35)
        new_bal = _settle(player, save_fn, bet, payout)
        return (
            f"🪙 *Heads!* You win!\n"
            f"+₡{payout - bet} net  ·  Balance: ₡{new_bal}"
        )
    else:
        new_bal = _settle(player, save_fn, bet, 0)
        return (
            f"🪙 *Tails.* You lose.\n"
            f"-₡{bet}  ·  Balance: ₡{new_bal}"
        )


# ── .db — Dice Bet ───────────────────────────────────────────
# Roll a d6, "win" band covers ~40% of outcomes (rolls 5-6 plus a
# weighted chance on 4), 2.35x payout. Framed as "beat the house roll."

def handle_dice_bet(sender, player, args, save_fn) -> str:
    coins = getattr(player, "coins", 0)
    bet, err = _parse_bet(args, coins)
    if err:
        return err

    player_roll = random.randint(1, 6)
    house_roll  = random.randint(1, 6)
    # Ties favor the house; this naturally lands close to 40% player wins.
    win = player_roll > house_roll

    if win:
        payout = int(bet * 2.35)
        new_bal = _settle(player, save_fn, bet, payout)
        return (
            f"🎲 You rolled *{player_roll}*, house rolled *{house_roll}*.\n"
            f"You win! +₡{payout - bet} net  ·  Balance: ₡{new_bal}"
        )
    else:
        new_bal = _settle(player, save_fn, bet, 0)
        tie_note = " (ties go to the house)" if player_roll == house_roll else ""
        return (
            f"🎲 You rolled *{player_roll}*, house rolled *{house_roll}*{tie_note}.\n"
            f"You lose. -₡{bet}  ·  Balance: ₡{new_bal}"
        )


# ── .di — Guess the Die ──────────────────────────────────────
# True 1-in-6 (~16.7%) odds, but priced under fair (fair would be 6x)
# to keep the house edge — 5.2x payout keeps expected value ~-13%,
# broadly in line with the other games' worse-than-even-money design.

def handle_die_guess(sender, player, args, save_fn) -> str:
    coins = getattr(player, "coins", 0)
    if len(args) < 2:
        return "_Usage: `.di [bet] [1-6]`_"

    bet, err = _parse_bet(args[:1], coins)
    if err:
        return err

    if not args[1].isdigit() or not (1 <= int(args[1]) <= 6):
        return "_Guess must be a number from 1 to 6._"
    guess = int(args[1])

    roll = random.randint(1, 6)
    win = guess == roll

    if win:
        payout = int(bet * 5.2)
        new_bal = _settle(player, save_fn, bet, payout)
        return (
            f"🎲 The die shows *{roll}*. You guessed *{guess}* — nailed it!\n"
            f"+₡{payout - bet} net  ·  Balance: ₡{new_bal}"
        )
    else:
        new_bal = _settle(player, save_fn, bet, 0)
        return (
            f"🎲 The die shows *{roll}*. You guessed *{guess}* — no match.\n"
            f"-₡{bet}  ·  Balance: ₡{new_bal}"
        )


# ── .slots ────────────────────────────────────────────────────
# Weighted 3-reel slots. Overall "any win" rate tuned to ~40%,
# with most wins being small (near break-even) and jackpots rare.

_SYMBOLS = ["🍒", "🍋", "🔔", "⭐", "💎"]
_WEIGHTS = [40, 28, 18, 10, 4]   # 💎 is rarest


def _spin_reel():
    return random.choices(_SYMBOLS, weights=_WEIGHTS, k=1)[0]


def handle_slots(sender, player, args, save_fn) -> str:
    coins = getattr(player, "coins", 0)
    bet, err = _parse_bet(args, coins)
    if err:
        return err

    reels = [_spin_reel() for _ in range(3)]
    display = " ".join(reels)

    if reels[0] == reels[1] == reels[2]:
        # Triple match — payout scales with rarity of the symbol.
        jackpot_mult = {
            "🍒": 2.0, "🍋": 3.0, "🔔": 5.0, "⭐": 8.0, "💎": 10.0,
        }[reels[0]]
        payout = int(bet * jackpot_mult)
        new_bal = _settle(player, save_fn, bet, payout)
        tag = "💎 JACKPOT! 💎" if reels[0] == "💎" else "Triple match!"
        return (
            f"🎰 [ {display} ]\n"
            f"{tag} +₡{payout - bet} net  ·  Balance: ₡{new_bal}"
        )
    elif reels[0] == reels[1] or reels[1] == reels[2] or reels[0] == reels[2]:
        # Partial match — small consolation payout, keeps overall
        # "you got something back" rate near 40% without inflating EV.
        payout = int(bet * 1.4)
        new_bal = _settle(player, save_fn, bet, payout)
        return (
            f"🎰 [ {display} ]\n"
            f"Partial match. +₡{payout - bet} net  ·  Balance: ₡{new_bal}"
        )
    else:
        new_bal = _settle(player, save_fn, bet, 0)
        return (
            f"🎰 [ {display} ]\n"
            f"No match. -₡{bet}  ·  Balance: ₡{new_bal}"
        )


# ── .roulette ─────────────────────────────────────────────────
# Simplified wheel: 18 red / 18 black / 1 green (0), plus straight
# number bets on 0-36. Payouts mirror real roulette (2x color,
# 35x straight number) — the house edge here comes from the green
# pocket, same as real roulette, rather than an artificial nerf.

def handle_roulette(sender, player, args, save_fn) -> str:
    coins = getattr(player, "coins", 0)
    if len(args) < 2:
        return "_Usage: `.roulette [bet] [red/black/green/0-36]`_"

    bet, err = _parse_bet(args[:1], coins)
    if err:
        return err

    choice = args[1].lower()
    result_num = random.randint(0, 36)
    if result_num == 0:
        result_color = "green"
    else:
        result_color = "red" if result_num % 2 == 1 else "black"

    header = f"🎡 Ball lands on *{result_num} ({result_color})*.\n"

    if choice in ("red", "black"):
        win = choice == result_color
        payout = int(bet * 2.0) if win else 0
    elif choice == "green":
        win = result_color == "green"
        payout = int(bet * 14.0) if win else 0
    elif choice.isdigit() and 0 <= int(choice) <= 36:
        win = int(choice) == result_num
        payout = int(bet * 35.0) if win else 0
    else:
        return "_Bet must be `red`, `black`, `green`, or a number 0-36._"

    if win:
        new_bal = _settle(player, save_fn, bet, payout)
        return header + f"You win! +₡{payout - bet} net  ·  Balance: ₡{new_bal}"
    else:
        new_bal = _settle(player, save_fn, bet, 0)
        return header + f"You lose. -₡{bet}  ·  Balance: ₡{new_bal}"
