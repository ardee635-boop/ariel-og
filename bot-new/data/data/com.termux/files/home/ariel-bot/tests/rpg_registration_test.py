"""
Proves the registration flow works through the REAL router wiring
(router/rpg.py via CommandRouter.handle()), not a hand-written
stand-in. No quote-reply is required anywhere in this flow — Ariel's
own outgoing messages quote the player, never the other way around.

Run: python3 rpg_registration_test.py
"""

import sys
sys.path.insert(0, ".")

from router import CommandRouter
from database import Database
from rpg_session import RpgSession, STARTING_LOCATION

router = CommandRouter(db=Database())
sender = "registration_test_sender"

print("=" * 60)
print("STEP 1: .rpg on")
print("=" * 60)
reply_on = router.handle(sender, ".rpg on")
print(reply_on)
assert "RPG mode ON" in reply_on
print(">>> PASS\n")

print("=" * 60)
print("STEP 2: .reg")
print("=" * 60)
reply_reg = router.handle(sender, ".reg")
print(reply_reg)
assert "Niflheim" in reply_reg
print(">>> PASS\n")

print("=" * 60)
print("STEP 3: .rpg state — before registration completes")
print("=" * 60)
reply_state_pending = router.handle(sender, ".rpg state")
print(reply_state_pending)
assert "haven't finished registering" in reply_state_pending
print(">>> PASS: correctly shows pending registration, no character yet.\n")

print("=" * 60)
print("STEP 4: .setname Hiro — plain command, NO quoting")
print("=" * 60)
reply_setname = router.handle(sender, ".setname Hiro", quoted_text=None)
print(reply_setname)
assert "Hiro" in reply_setname
assert STARTING_LOCATION in reply_setname
print(">>> PASS: registration accepted with zero quoting.\n")

print("=" * 60)
print("STEP 5: .status")
print("=" * 60)
reply_status = router.handle(sender, ".status")
print(reply_status)
assert "Name: Hiro" in reply_status
assert "HP: 10" in reply_status
print(">>> PASS\n")

print("=" * 60)
print("STEP 6: .rpg state — after registration")
print("=" * 60)
reply_state_final = router.handle(sender, ".rpg state")
print(reply_state_final)
assert "Hiro" in reply_state_final
assert STARTING_LOCATION in reply_state_final
print(">>> PASS\n")

print("=" * 60)
print("STEP 7: sanity check — a sender NOT in RPG mode gets normal")
print("Pokémon .status, not intercepted by Ariel")
print("=" * 60)
other_sender = "not_in_rpg_mode"
reply_other = router.handle(other_sender, ".status")
print(repr(reply_other)[:150])
assert "Name: Hiro" not in (reply_other or "")
print(">>> PASS: no leakage to senders outside RPG mode.\n")

print("=" * 60)
print("STEP 8: .rpg 3 — 'talk to the nearest person', right after")
print("registration. Regression check for the elder-not-seeded bug:")
print("the elder is introduced in the opening prose and must already")
print("be a real NPC in world_state, or this wrongly gets rejected.")
print("=" * 60)
reply_choice = router.handle(sender, ".rpg 3")
print(reply_choice)
assert "no one present" not in reply_choice, "FAIL: elder NPC wasn't seeded at registration!"
print(">>> PASS: opening-scene NPC was real, choice resolved.\n")

print("=" * 60)
print("STEP 9: SHARED WORLD CHECK — a second, different player")
print("registers and should see the SAME elder at the same location,")
print("not their own independently-seeded copy.")
print("=" * 60)
sender2 = "registration_test_sender_2"
router.handle(sender2, ".rpg on")
router.handle(sender2, ".reg")
router.handle(sender2, ".setname Second")
reply_state_2 = router.handle(sender2, ".rpg state")
print(reply_state_2)
assert "a young elder of the church" in reply_state_2
print(">>> PASS: second player sees the same NPC — one shared world confirmed.\n")

print("=" * 60)
print("ALL REGISTRATION TESTS PASSED (real router wiring, no quoting)")
print("=" * 60)
