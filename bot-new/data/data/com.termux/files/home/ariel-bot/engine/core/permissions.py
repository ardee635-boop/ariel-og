"""Who is the King. Single source: config/identities.json (see config.py).
Everything below the King (ranks, lords) is the JS rank system in bot/admin."""
from config import KING_JID, KING_NUMBER


def is_king(sender: str) -> bool:
    if not sender or not KING_NUMBER:
        return False
    return sender == KING_JID or sender.split("@")[0] == KING_NUMBER
