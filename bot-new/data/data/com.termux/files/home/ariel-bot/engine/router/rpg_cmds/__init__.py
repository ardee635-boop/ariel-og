"""RpgManager._dispatch handler blocks, in dispatch order (see router/rpg.py)."""
from . import registration, reset, character, sim, fight, trials_setup, trials_weapons, actions

HANDLERS = (
    registration.handle,
    reset.handle,
    character.handle,
    sim.handle,
    fight.handle,
    trials_setup.handle,
    trials_weapons.handle,
    actions.handle,
)
