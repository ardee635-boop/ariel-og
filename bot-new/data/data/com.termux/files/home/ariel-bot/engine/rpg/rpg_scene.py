# ============================================================
# ARIEL — RPG_SCENE.PY (scene object store)
# ============================================================
#
# One owner for "what physically exists in the player's current
# scene". Everything else (apply_engine_result, validate_premise,
# the narrator's context block, the take/hold gates) asks this
# module instead of poking at a raw list.
#
# WHY THIS EXISTS
#   scene_objects used to be a plain list of {"name", "description"}
#   compared by exact string. That broke down as soon as the
#   narrator was allowed to establish things by DESCRIBING them
#   (a squirrel, a fountain, a corpse) instead of only by dropping
#   them:
#     - two cups became one row, or two rows that couldn't be told
#       apart when one was removed
#     - a pillar became "pickable" because pickup only checked that
#       the name was listed
#     - nothing ever expired, so a squirrel that scurried off stayed
#     - dedup/removal used exact strings while the validator used
#       word overlap, so "the cup" and "cup" disagreed
#
# ENTRY SHAPE (backward compatible: "name" and "description" keep
# their old meaning, everything else is additive)
#   {
#     "id":          "o12",           # stable within a session
#     "name":        "cup",           # display name, singular
#     "description": "...",
#     "count":       2,               # stacked identical things
#     "kind":        "item|scenery|creature|corpse",
#     "weight":      "tiny|light|heavy|fixed",
#     "source":      "narration|drop|legacy",
#     "born_turn":   17,              # session turn it appeared
#     "ttl":         None | int,      # turns until it lapses; None = stays
#     "persistent":  False,           # True -> also belongs in shared store
#   }
#
# TURN CLOCK
#   Expiry counts VALID turns only (see RpgSession.turn), never
#   failed/rejected ones, matching how history already skips them.
#
# THIS MODULE HAS NO I/O. It works on plain dicts and lists so it
# can be tested without a database, a session, or an LLM.
# ============================================================

import re

WEIGHTS = ("tiny", "light", "heavy", "fixed")
KINDS = ("item", "scenery", "creature", "corpse")

# Only these can be picked up or held. "heavy" can be dragged/moved
# in the fiction but never goes in .inv or a hand slot; "fixed" is
# part of the place itself.
PORTABLE_WEIGHTS = ("tiny", "light")

# Default lifetimes in valid turns, by kind. None = no expiry.
# Creatures wander off; scenery/corpses/items stay until something
# removes them or the player travels.
DEFAULT_TTL = {
    "creature": 4,
    "item": None,
    "scenery": None,
    "corpse": None,
}

# Kinds that outlast the scene for EVERYONE (shared store candidates).
DEFAULT_PERSISTENT_KINDS = ("corpse",)

# Hard cap so a chatty model can't flood the scene.
MAX_ENTRIES = 24
MAX_NEW_PER_TURN = 6

_STOPWORDS = {"the", "a", "an", "some", "one", "two", "three", "of", "beside",
              "me", "my", "near", "by", "here", "that", "this", "old", "small",
              "large", "little", "big"}

_NUMBER_WORDS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4,
                 "five": 5, "six": 6, "pair": 2}


def _clean(s) -> str:
    """Lowercase, normalize the odd hyphens/whitespace the model
    emits (U+2011 shows up in real output), collapse spaces."""
    s = str(s or "").replace("\u2011", "-").replace("\u2010", "-")
    s = re.sub(r"[^\w\s'-]", " ", s.lower())
    return re.sub(r"\s+", " ", s).strip()


def _singular(word: str) -> str:
    """Very small plural folding — enough for cups/squirrels/stones.
    Deliberately conservative: leaves 'glass', 'moss', 'bus' alone."""
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 4 and word.endswith("ves"):
        return word[:-3] + "f"
    if len(word) > 3 and word.endswith("es") and word[-3] in "sxz":
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def normalize_name(name) -> str:
    """Canonical form for identity: lowercase, no leading article or
    quantity word, plural folded on the head noun. 'The two Cups'
    and 'cup' normalize the same."""
    words = _clean(name).split()
    while words and (words[0] in _STOPWORDS or words[0] in _NUMBER_WORDS):
        words.pop(0)
    if not words:
        return ""
    words[-1] = _singular(words[-1])
    return " ".join(words)


def content_words(name) -> set:
    """Word set used for loose matching (validator-style overlap),
    with plural folding so 'cups' matches 'cup'."""
    return {_singular(w) for w in _clean(name).split() if w not in _STOPWORDS
            and w not in _NUMBER_WORDS}


def parse_quantity(name) -> int:
    """'two cups' -> 2, 'a cup' -> 1, 'cups' -> 1. Model output only
    gives us a count when it says one; we never guess higher."""
    words = _clean(name).split()
    if words and words[0] in _NUMBER_WORDS and words[0] not in ("a", "an", "one"):
        return _NUMBER_WORDS[words[0]]
    if words and words[0].isdigit():
        return max(1, min(int(words[0]), 20))
    return 1


# ------------------------------------------------------------
# Construction / migration
# ------------------------------------------------------------

def _next_id(entries: list) -> str:
    used = {e.get("id") for e in entries}
    n = 1
    while f"o{n}" in used:
        n += 1
    return f"o{n}"


def make_entry(name, description="", *, kind="item", weight="light",
               source="narration", turn=0, count=None, ttl="default",
               persistent=None, entries=None) -> dict:
    """Build one normalized entry. Unknown kind/weight fall back to
    safe defaults rather than raising, since these come from an LLM."""
    kind = kind if kind in KINDS else "item"
    weight = weight if weight in WEIGHTS else "light"
    if kind in ("scenery",) and weight in PORTABLE_WEIGHTS:
        # A model calling a fountain "light" must never make it
        # pickable. Scenery is never portable.
        weight = "fixed"
    if kind == "corpse" and weight in PORTABLE_WEIGHTS:
        weight = "heavy"
    display = normalize_name(name) or _clean(name) or "thing"
    qty = count if count is not None else parse_quantity(name)
    if ttl == "default":
        ttl = DEFAULT_TTL.get(kind)
    if persistent is None:
        persistent = kind in DEFAULT_PERSISTENT_KINDS
    return {
        "id": _next_id(entries or []),
        "name": display,
        "description": str(description or "").strip(),
        "count": max(1, int(qty)),
        "kind": kind,
        "weight": weight,
        "source": source,
        "born_turn": int(turn),
        "ttl": ttl,
        "persistent": bool(persistent),
    }


def migrate_entry(raw, *, turn=0, entries=None) -> dict | None:
    """Upgrade one saved entry. Old sessions stored
    {"name","description"} only — those become count 1, light,
    source 'legacy', born now. Already-new entries pass through
    with any missing keys filled in."""
    if not isinstance(raw, dict):
        return None
    name = str(raw.get("name", "")).strip()
    if not name:
        return None
    if "id" in raw and "weight" in raw and "kind" in raw:
        out = dict(raw)
        out.setdefault("count", 1)
        out.setdefault("description", "")
        out.setdefault("source", "narration")
        out.setdefault("born_turn", turn)
        out.setdefault("ttl", None)
        out.setdefault("persistent", False)
        return out
    return make_entry(name, raw.get("description", ""), kind="item",
                      weight="light", source="legacy", turn=turn,
                      ttl=None, entries=entries)


def migrate_list(raw_list, *, turn=0) -> list:
    """Whole-list migration used by RpgSession.from_dict."""
    out = []
    for raw in raw_list or []:
        e = migrate_entry(raw, turn=turn, entries=out)
        if e:
            out.append(e)
    return out


# ------------------------------------------------------------
# Matching
# ------------------------------------------------------------

def find(entries: list, name) -> list:
    """All entries a player's/narrator's phrase could mean, best
    matches first. Order: exact normalized name, then word-overlap.
    Never raises; empty list means 'not here'."""
    norm = normalize_name(name)
    if not norm:
        return []
    exact = [e for e in entries if normalize_name(e["name"]) == norm]
    if exact:
        return exact
    want = content_words(name)
    if not want:
        return []
    return [e for e in entries if want & content_words(e["name"])]


def has(entries: list, name) -> bool:
    return bool(find(entries, name))


def describe_one(e: dict) -> str:
    """'2 cups' / 'a cup' — used in the narrator's context block."""
    n = e.get("count", 1)
    nm = e["name"]
    if n > 1:
        plural = nm if nm.endswith("s") else nm + "s"
        return f"{n} {plural}"
    return f"a {nm}"


# ------------------------------------------------------------
# Mutation. Each returns the (possibly new) list; none touch I/O.
# ------------------------------------------------------------

def add(entries: list, name, description="", *, kind="item", weight="light",
        source="narration", turn=0, count=None, ttl="default",
        persistent=None) -> list:
    """Add a thing, STACKING onto an existing identical entry (same
    normalized name and kind) instead of duplicating it. Two cups
    become one row with count 2."""
    if len(entries) >= MAX_ENTRIES:
        return entries
    norm = normalize_name(name)
    if not norm:
        return entries
    qty = count if count is not None else parse_quantity(name)
    for e in entries:
        if normalize_name(e["name"]) == norm and e.get("kind") == (kind if kind in KINDS else "item"):
            e["count"] = min(e.get("count", 1) + max(1, qty), 99)
            if description and not e.get("description"):
                e["description"] = str(description).strip()
            return entries
    entries.append(make_entry(name, description, kind=kind, weight=weight,
                              source=source, turn=turn, count=qty, ttl=ttl,
                              persistent=persistent, entries=entries))
    return entries


def remove(entries: list, name, count=1) -> list:
    """Take `count` of a thing away. A stack of 2 cups drops to 1;
    the last one removes the row. Matches loosely (word overlap) so
    'the cup' and 'cup' both work. Removes from the best match only."""
    hits = find(entries, name)
    if not hits:
        return entries
    target = hits[0]
    remaining = target.get("count", 1) - max(1, count)
    if remaining > 0:
        target["count"] = remaining
        return entries
    return [e for e in entries if e is not target]


def remove_by_id(entries: list, entry_id: str, count=1) -> list:
    for e in entries:
        if e.get("id") == entry_id:
            remaining = e.get("count", 1) - max(1, count)
            if remaining > 0:
                e["count"] = remaining
                return entries
            return [x for x in entries if x is not e]
    return entries


def expire(entries: list, current_turn: int) -> tuple[list, list]:
    """Drop anything whose ttl has run out. Returns (kept, dropped)
    so callers can tell the narrator what just left."""
    kept, dropped = [], []
    for e in entries:
        ttl = e.get("ttl")
        if ttl is not None and current_turn - e.get("born_turn", 0) >= ttl:
            dropped.append(e)
        else:
            kept.append(e)
    return kept, dropped


# ------------------------------------------------------------
# Weight gates (used by the take/hold plausibility checks)
# ------------------------------------------------------------

def can_carry(entry: dict) -> bool:
    return entry.get("weight") in PORTABLE_WEIGHTS


def carry_refusal(entry: dict) -> str:
    """In-fiction reason a non-portable thing can't be taken."""
    nm = entry.get("name", "it")
    if entry.get("weight") == "fixed":
        return f"The {nm} is part of the place — it isn't going anywhere."
    return f"The {nm} is far too heavy to carry off, though you could shove or drag it."


# ------------------------------------------------------------
# Rendering (narrator context / .rpg state)
# ------------------------------------------------------------

def names_for_context(entries: list) -> str:
    return ", ".join(describe_one(e) for e in entries)


def plain_names(entries: list) -> list:
    """Bare display names — what validate_premise and the choice
    filter compare against."""
    return [e["name"] for e in entries]


# ============================================================
# NOUN EXTRACTION (the pass that makes narrated things REAL)
# ============================================================
#
# After the narrator writes its prose, a SECOND, small call reads only
# that prose and lists the physical things it established. This is
# what closes the "the narrator described a squirrel but the game
# says there's no squirrel" gap: anything the story says is here gets
# recorded, so the validator, the choice filter and the take/hold
# gates all see the same world the player just read about.
#
# Design rules (each one exists because a 20b model will break it):
#   - It reads ONLY the finished prose plus what is already recorded.
#     It never sees the player's message, so a player asserting
#     "I grab the elixir" cannot smuggle an object into existence.
#   - It only reports things the prose actually says are PRESENT.
#     Not things mentioned as absent, remembered, or imagined.
#   - Every field is validated in code. Anything malformed, or any
#     call failure/timeout, yields "record nothing" — never a guess.
#   - Capped per turn (MAX_NEW_PER_TURN) so it can't flood the scene.
#   - Named characters are NOT its job (NPCs already have new_npcs and
#     a shared table). Unnamed animals/people-as-scenery are creatures.

EXTRACT_SYSTEM = """You read one passage from a roleplay game, plus the 3 next-action choices offered after it, and report on both. Reply with JSON only.

Format:
{"things": [{"name": "<short singular noun>", "kind": "item|scenery|creature|corpse", "weight": "tiny|light|heavy|fixed", "count": <int>}],
 "left": ["<name of a recorded thing the passage says is now gone, destroyed, or has left>"],
 "choice_verdicts": [{"index": <0, 1, or 2>, "verdict": "ok|contradicts", "names": ["<any new physical thing this choice refers to>"]}]}

PART 1 — the passage. Only list things it says ARE here right now. Ignore things that are absent, remembered, hoped for, or only being asked about.
- name: 1-3 words, singular, no article. "a stone fountain" -> "stone fountain".
- kind: item = loose object someone could pick up. scenery = part of the place (fountain, pillar, wall, tree, door). creature = a living animal or unnamed person. corpse = a dead body.
- weight: tiny = fits in a fist (coin, pen). light = one hand (cup, stone, book). heavy = movable only with effort (barrel, corpse, boulder). fixed = part of the place, cannot be moved.
- count: how many, default 1. Two cups -> one entry with count 2.
- Do NOT list: the player, named characters, weather, sounds, smells, light, feelings, or vague crowds ("townsfolk chatter").
- Do NOT list anything already in RECORDED unless the passage adds more of it.
- "left": only for a RECORDED thing the passage clearly says left, died, broke, or was taken away.
- At most 6 things. If nothing qualifies for "things", return an empty list.

PART 2 — the 3 choices, judged against LOCATION and RECORDED, not against the passage.
For each choice (index 0, 1, 2), decide:
- "ok" — the choice fits what this kind of place would ordinarily contain, OR points at something in RECORDED. A choice naming a plausible fixture of the location is "ok" even if nothing recorded it yet (a library plausibly has a librarian; a market plausibly has a merchant). Everyday actions with no specific target ("Leave", "Wait", "Look around") are always "ok".
- "contradicts" — the choice names something LOCATION or RECORDED explicitly rules out (an instructor at a place whose own notes say no one is there; a door at a place with no doors; anything RECORDED as having left or been destroyed).
If a choice is "ok" and it names a new physical thing not already in RECORDED (the librarian, a training drum), list that name in "names" using the same name/kind rules as PART 1 things — but do NOT duplicate it into the top-level "things" list; report it ONLY here.
When genuinely unsure, prefer "ok" — this check exists to catch clear contradictions, not to second-guess reasonable atmosphere.

At most 6 things total across both parts. If nothing qualifies, return empty lists."""

# Words that mean a candidate is not a physical thing at all. Matched as
# whole words AND as suffixes/prefixes of a token, because a model says
# "sunlight", "moonlight", "torchlight", "birdsong", "footsteps" — a plain
# word list misses every compound.
_NOT_THINGS = {"sound", "noise", "murmur", "chatter", "smell", "scent", "air",
               "wind", "light", "shadow", "silence", "sky", "sun", "warmth",
               "crowd", "townsfolk", "echo", "feeling", "mood", "breeze",
               "song", "music", "voice", "whisper", "glow", "gleam", "haze",
               "mist", "fog", "heat", "cold", "dust", "atmosphere", "aroma",
               "stench", "hum", "clatter", "rumble", "footstep", "darkness"}
_NOT_THING_TAILS = ("light", "song", "shadow", "noise", "sound", "glow",
                    "smell", "scent", "steps", "wind", "shine")


def _is_not_a_thing(name) -> bool:
    """True if the phrase names an ambient quality rather than a
    physical object (sounds, light, smells, crowds, moods)."""
    words = content_words(name)
    if words & _NOT_THINGS:
        return True
    for w in words:
        # compounds: sunlight, moonlight, birdsong, footsteps, tailwind
        if len(w) > 5 and w.endswith(_NOT_THING_TAILS):
            return True
    return False


def _extract_json_obj(text):
    """Local, dependency-free version of rpg_engine.extract_json so this
    module stays importable on its own. Returns a dict or None."""
    import json
    if not text:
        return None
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", t).strip()
    start, end = t.find("{"), t.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None
    try:
        obj = json.loads(t[start:end + 1])
    except (ValueError, TypeError):
        return None
    return obj if isinstance(obj, dict) else None


def _clean_thing(t, entries, seen) -> dict | None:
    """Validate one {"name","kind","weight","count"} candidate, shared by
    PART 1 (things) and PART 2 (a choice's "names"). Returns a dict ready
    for add(), or None if dubious. Mutates `seen` to prevent duplicates
    within one extraction reply."""
    if not isinstance(t, dict):
        return None
    name = str(t.get("name", "")).strip()
    norm = normalize_name(name)
    if not norm or len(norm) > 40 or len(norm.split()) > 4:
        return None
    if _is_not_a_thing(name):
        return None
    kind = t.get("kind") if t.get("kind") in KINDS else None
    if kind is None:
        return None  # a thing we can't even categorise: skip, don't guess
    weight = t.get("weight") if t.get("weight") in WEIGHTS else None
    if weight is None:
        weight = {"scenery": "fixed", "corpse": "heavy",
                  "creature": "light", "item": "light"}[kind]
    try:
        count = int(t.get("count", 1))
    except (TypeError, ValueError):
        count = 1
    count = max(1, min(count, 20))
    key = (norm, kind)
    if key in seen:
        return None
    seen.add(key)
    # Already recorded? Only add the DIFFERENCE if it reports more than
    # what we hold; a plain re-mention adds nothing.
    existing = [e for e in entries if normalize_name(e["name"]) == norm
                and e.get("kind") == kind]
    if existing:
        extra = count - existing[0].get("count", 1)
        if extra <= 0:
            return None
        count = extra
    return {"name": norm, "kind": kind, "weight": weight,
            "count": count, "source": "narration"}


def clean_extraction(parsed, entries) -> tuple[list, list, dict]:
    """Validate a parsed extraction reply. Returns (new_things, left,
    choice_verdicts). new_things are dicts ready for add(); left are
    names to remove; choice_verdicts maps a 0/1/2 choice index to
    {"verdict": "ok"|"contradicts", "new_things": [...]}. Anything
    dubious is dropped rather than repaired — an unparsed choice
    defaults to "ok" (see extract_nouns: silence must never censor)."""
    if not isinstance(parsed, dict):
        return [], [], {}

    out = []
    seen = set()
    raw_things = parsed.get("things")
    if isinstance(raw_things, list):
        for t in raw_things:
            if len(out) >= MAX_NEW_PER_TURN:
                break
            cleaned = _clean_thing(t, entries, seen)
            if cleaned:
                out.append(cleaned)

    left = []
    raw_left = parsed.get("left")
    if isinstance(raw_left, list):
        for n in raw_left[:MAX_NEW_PER_TURN]:
            n = str(n or "").strip()
            # Only honour a departure for something we actually hold.
            if n and find(entries, n):
                left.append(n)

    # PART 2: per-choice verdicts. Missing/malformed entries are simply
    # absent from the result — extract_nouns fills those in as "ok",
    # never as "contradicts". A parsing gap must never censor a choice;
    # it can only fail to catch a bad one, same failure direction as
    # every other best-effort part of this pass.
    verdicts = {}
    raw_verdicts = parsed.get("choice_verdicts")
    if isinstance(raw_verdicts, list):
        for v in raw_verdicts:
            if not isinstance(v, dict):
                continue
            idx = v.get("index")
            if idx not in (0, 1, 2):
                continue
            verdict = v.get("verdict") if v.get("verdict") in ("ok", "contradicts") else "ok"
            names_out = []
            raw_names = v.get("names")
            if isinstance(raw_names, list):
                for n in raw_names[:3]:
                    cleaned = _clean_thing(n, entries, seen) if isinstance(n, dict) else None
                    if cleaned:
                        names_out.append(cleaned)
            verdicts[idx] = {"verdict": verdict, "new_things": names_out}

    return out, left, verdicts


def extract_nouns(prose, entries, call_fn, choices=None,
                  location=None) -> tuple[list, list, dict]:
    """Run the extraction pass. `call_fn` is the same call_groq-shaped
    callable the engine already uses: (system, user, **kw) -> str|None.
    `choices` is the narrator's list of up to 3 next-action strings —
    pass it to also get PART 2's judgement back.

    Returns (new_things, left, choice_verdicts). choice_verdicts maps
    index -> {"verdict","new_things"} for whichever choices were judged.
    ANY failure (no call_fn, empty prose, bad reply, exception) returns
    ([], [], {}) — an empty choice_verdicts means "no verdict for any
    choice", and callers MUST treat a missing index as ok/keep, never
    as a silent rejection. This pass is best-effort and must never
    break, delay, or CENSOR a turn on its own failure."""
    if call_fn is None or not prose or not str(prose).strip():
        return [], [], {}
    recorded = names_for_context(entries) if entries else "nothing"
    parts = [f"RECORDED: {recorded}"]
    if location:
        parts.append(f"LOCATION: {location}")
    parts.append(f"PASSAGE:\n{str(prose).strip()[:1500]}")
    if choices:
        numbered = "\n".join(f"{i}. {c}" for i, c in enumerate(choices[:3]))
        parts.append(f"CHOICES:\n{numbered}")
    user = "\n\n".join(parts)
    try:
        reply = call_fn(EXTRACT_SYSTEM, user, max_tokens=380,
                        temperature=0.1, json_mode=True)
    except Exception:
        return [], [], {}
    return clean_extraction(_extract_json_obj(reply), entries)


# ============================================================
# DEFERRED WORK SLOT (reply first, record after)
# ============================================================
#
# The reply can't leave the Python process until router.handle()
# returns. To let the player read their scene while the extraction
# call runs, the router stashes a job here keyed by sender, and
# bridge._do_handle pops and runs it AFTER writing the reply. It runs
# inside that sender's lock, so the player's next message cannot start
# validating until the job is done or has hit its time limit.
#
# A job has two halves, and the split is the important part:
#
#   compute()  -> the slow LLM call. Touches NO game state. Runs in a
#                 thread we are allowed to abandon after the budget.
#   apply(res) -> the fast write. Runs on the CALLING thread, inside
#                 the sender lock, and ONLY if compute() finished in
#                 time.
#
# Why: the session is persisted as one JSON blob, last write wins
# (database.set_meta). If a slow compute() thread wrote the session
# itself after we gave up on it, it could land after the player's next
# turn and silently overwrite it (lost inventory, lost location). By
# never letting an abandoned thread write anything, a timeout can only
# ever mean "nothing recorded this turn" — never corrupted state.
# Same idea as ariel.py's pop_ariel_sticker(sender) slot.

import threading
import time as _time

AFTER_REPLY_BUDGET_SECONDS = 5.0

_pending = {}
_pending_lock = threading.Lock()


def queue_after_reply(sender, compute, apply):
    """Stash a (compute, apply) pair to run after this sender's reply.
    A newer unrun job replaces an older one — only the latest scene
    matters."""
    with _pending_lock:
        _pending[sender] = (compute, apply)


def pop_after_reply(sender):
    with _pending_lock:
        return _pending.pop(sender, None)


def run_after_reply(sender, budget=AFTER_REPLY_BUDGET_SECONDS, log=None):
    """Run this sender's stashed job. Never raises, never blocks longer
    than `budget` seconds on the slow half. Returns one of
    'none' | 'ok' | 'timeout' | 'compute_error' | 'apply_error'."""
    job = pop_after_reply(sender)
    if job is None:
        return "none"
    compute, apply = job
    box = {}

    def _target():
        try:
            box["result"] = compute()
            box["done"] = True
        except Exception as exc:
            box["error"] = exc

    t0 = _time.monotonic()
    th = threading.Thread(target=_target, daemon=True)
    th.start()
    th.join(budget)

    if th.is_alive():
        # Abandoned. Its result (if it ever arrives) is never applied.
        if log:
            log(f"[RPG SCENE] noun extraction exceeded {budget}s; nothing "
                f"recorded this turn")
        return "timeout"
    if "error" in box or not box.get("done"):
        if log:
            log(f"[RPG SCENE] noun extraction failed: {box.get('error')}")
        return "compute_error"
    try:
        apply(box["result"])
    except Exception as exc:
        if log:
            log(f"[RPG SCENE] applying extracted nouns failed: {exc}")
        return "apply_error"
    if log:
        log(f"[RPG SCENE] noun extraction ok in {_time.monotonic() - t0:.1f}s")
    return "ok"


# ------------------------------------------------------------
# Applying choice verdicts
# ------------------------------------------------------------

# Neutral, always-safe fallbacks for a choice the extraction pass caught
# contradicting the scene. Deliberately generic — better than a specific
# guess, since we don't know what SHOULD have been offered.
_SAFE_FALLBACKS = ["Look around", "Wait and see what happens", "Move on"]


def apply_choice_verdicts(choices: list, verdicts: dict, entries: list,
                          turn: int = 0) -> tuple[list, list]:
    """Turn extraction's per-choice verdicts into the choices the player
    actually sees, and register whatever new things "ok" choices named
    (the librarian case: real once offered, not only once narrated).

    A missing index (extraction failed, or didn't cover that choice) is
    kept as-is — see extract_nouns's docstring: absence must never mean
    rejection. Returns (final_choices, updated_entries)."""
    final = []
    used_fallbacks = set()
    for i, choice in enumerate(choices[:3]):
        v = verdicts.get(i)
        if v is None or v.get("verdict") != "contradicts":
            final.append(choice)
            if v:
                for t in v.get("new_things", []):
                    entries = add(entries, t["name"], "", kind=t["kind"],
                                 weight=t["weight"], count=t["count"],
                                 source="choice", turn=turn)
            continue
        # Contradicted: swap in a fallback that isn't already used/offered.
        for fb in _SAFE_FALLBACKS:
            if fb not in used_fallbacks and fb not in choices:
                used_fallbacks.add(fb)
                final.append(fb)
                break
        else:
            final.append("Look around")
    return final, entries
