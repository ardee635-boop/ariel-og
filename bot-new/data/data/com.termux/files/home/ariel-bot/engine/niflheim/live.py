# Registry of groups that currently have Niflheim fights/duels running (in memory, cheap).
# When the world is switched off in a group, pre_dispatch calls cancel_group() so a duel invite,
# duel or fight in progress is cancelled (DEFAULT, guidelines 1.1). Switching off only flips flags
# elsewhere; this is the Niflheim side of it.
_groups = {}


def register(group_jid, sender):
    if group_jid:
        _groups.setdefault(group_jid, set()).add(sender)


def cancel_group(db, group_jid):
    senders = _groups.pop(group_jid, None)
    if not senders:
        return 0
    from . import store
    n = 0
    for s in senders:
        if store.load_fight(db, s):
            store.delete_fight(db, s); n += 1
        d = store.load_duel(db, s)
        if d and d.get("group_jid") == group_jid:
            store.delete_duel(db, d); n += 1
    return n
