"""RPG: rpg llm (split from rpg_engine.py)."""
import os
import json
import re
import time


                  # without world-grounding context (see _NARRATION_SYSTEM)

GROQ_MODEL = "openai/gpt-oss-120b"  # llama-3.1-8b-instant was deprecated

                                     # by Groq (announced 2026-06-17);
                                     # this is Groq's own recommended
                                     # replacement, same call shape.
                                     # Used for the fast classification-
                                     # style calls (split/classify/decide)
                                     # — these already run sub-second on
                                     # 120b in practice, no reason to
                                     # touch them.

# UPDATED (2026-09): narration specifically gets its own, faster model.
# Its ~4.2k-token prompt measured at 15s wall-clock on 120b's ~500
# tok/s decode — openai/gpt-oss-20b runs ~1000 tok/s (same JSON-mode /
# reasoning_effort support, same 131k context), so this halves decode
# time on the single most expensive call in the pipeline without
# touching the fast calls that don't need it. Genuine speed/quality
# tradeoff — 20b's prose may read flatter than 120b's; if playtesting
# shows narration quality dropping noticeably, revert this one
# constant back to GROQ_MODEL and eat the extra latency instead.
GROQ_NARRATION_MODEL = "openai/gpt-oss-20b"

# ============================================================
# REAL GROQ CALL — matches npc.py's _call_groq() convention
# (same env var, same model, same graceful-None-on-failure shape),
# but generic: no NPC profile/memory lookup, since rpg_engine.py's
# two call sites (extraction, narration) pass their own system
# prompt each time rather than a stored persona.
# ============================================================

def call_groq(system: str, user: str, max_tokens: int = 300, temperature: float = 0.8,
              json_mode: bool = False, model: str | None = None) -> str | None:
    """
    Fires one Groq chat completion. Returns the reply text, or None
    on missing key / any failure — callers (extract_action,
    narrate_result) already handle None by falling back to a safe
    default, same pattern as npc.py's _call_groq callers.

    json_mode=True appends a plain-text instruction to the system
    prompt asking the model to reply with JSON only — it does NOT
    set response_format anymore. Groq's response_format={"type":
    "json_object"} on openai/gpt-oss-120b runs an internal JS
    grammar-compilation step to enforce the shape, and that step
    has been intermittently returning 400 ("Failed to generate JS"
    / "Failed to validate JS") at a high rate — a bug on Groq's
    side in that specific compiler, not something wrong with our
    prompts. Asking in plain text sidesteps that compiler entirely.
    The model still reliably replies with JSON-only text on a clear
    instruction; callers use extract_json() (below) to strip any
    stray text before parsing, so a rare bit of surrounding prose
    doesn't break anything.

    No conversation memory here (unlike npc.py's per-NPC memory) —
    each rpg_engine.py call is a single-turn, tightly-scoped task
    (extract, or narrate), not an ongoing back-and-forth persona
    chat. Multi-turn continuity for Ariel lives in RpgSession.history
    (rpg_session.py) instead, fed in by the caller if/when needed.

    Retries up to 3 total attempts on failure, for ordinary
    transient errors (network blips, rare 5xx).
    """
    key = os.environ.get("GROQ_API_KEY", "").strip()
    if not key:
        return None

    # Retries: 2 total attempts, not 3 — one immediate retry catches
    # ordinary transient blips (network hiccup, rare 5xx).
    #
    # UPDATED (see 2026-09 investigation): a .rpg/.rpg sim turn is
    # actually up to FIVE sequential Groq calls, not two — split_action_text,
    # classify_action_type, classify_skill_key, decide_order, then
    # narrate_result. The first four are small/fast in practice
    # (sub-second, <2k token prompts each). narrate_result is NOT —
    # its ~4.2k token prompt (a ~2.9k-token fixed instruction block
    # plus per-turn world state) measured at 15s wall-clock time to
    # complete on real traffic, entirely legitimate generation time,
    # not a hang. The OLD 4.5s per-attempt timeout was silently wrong
    # for this call: it should have aborted at 4.5s but didn't
    # (observed successes past 10s), meaning the SDK timeout wasn't
    # actually bounding total request time as assumed.
    #
    # Fix: give narration its own longer timeout/attempt budget,
    # separate from the fast classification-style calls, instead of
    # one timeout value pretending to fit both. Small calls keep a
    # tight budget (fail fast, they're cheap to retry); narration
    # gets room to actually finish once, since a real 15-20s narration
    # reply is far better than a phantom timeout that discards it.
    is_narration_call = model == GROQ_NARRATION_MODEL
    PER_ATTEMPT_TIMEOUT = 22.0 if is_narration_call else 4.5
    MAX_ATTEMPTS = 1 if is_narration_call else 2
    RETRY_DELAY_SECONDS = 0.4

    try:
        from groq import Groq
        # Explicit per-request timeout — see note above. Narration
        # gets a single attempt at a real 22s ceiling (one legitimate
        # try, no retry — a second 22s attempt would blow every
        # caller's budget); classification-style calls keep the
        # original fast-fail-and-retry-once behavior, since those
        # really do run sub-second and a hang there IS anomalous.
        client = Groq(api_key=key, timeout=PER_ATTEMPT_TIMEOUT)
    except Exception as exc:
        print(f"[GROQ rpg_engine] {str(exc)[:200]}", flush=True)
        return None

    if json_mode:
        system = system + "\n\nRespond with ONLY a single valid JSON object. " \
                           "No text before or after it, no markdown code fences."

    kwargs = dict(
        model=model or GROQ_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        max_tokens=max_tokens,
        temperature=temperature,
        # openai/gpt-oss-120b is a REASONING model — by default it spends
        # part of max_tokens on an invisible internal reasoning chain
        # BEFORE it ever writes the visible answer into `content`. At low
        # max_tokens (e.g. 40 for a short classification call), the model
        # can burn the entire budget "thinking" and get cut off after
        # only 1-2 characters of the real JSON answer — this is what was
        # producing raw_reply='{"ac' truncation, misread earlier as a
        # rate-limit/token-count issue. "low" keeps reasoning brief so
        # more of the budget goes to the actual answer — these are all
        # simple classification/lookup tasks, not tasks that benefit
        # from deep reasoning anyway.
        reasoning_effort="low",
    )

    last_exc = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = client.chat.completions.create(**kwargs)
            # Logs prompt-caching visibility — Groq's usage object
            # exposes cached-vs-total prompt tokens on models with
            # automatic prompt caching (openai/gpt-oss-120b included,
            # per Groq's May 2026 rollout). This is read-only
            # observability: nothing here changes request behavior,
            # it just lets us confirm from real traffic whether the
            # ~3.6-3.8k token system prompt is actually landing a
            # cache hit turn-to-turn, instead of assuming it is from
            # docs alone. Wrapped defensively since the exact usage
            # field names/availability can vary by SDK version and
            # this must never break a real call if the shape changes.
            try:
                usage = getattr(response, "usage", None)
                if usage:
                    cached = getattr(usage, "prompt_tokens_details", None)
                    cached_tokens = getattr(cached, "cached_tokens", None) if cached else None
                    # queue_time/prompt_time/completion_time/total_time
                    # are Groq-specific (not in the plain OpenAI usage
                    # shape) — this is what actually answers the SPEED
                    # question directly: how much of the wall-clock
                    # time was spent waiting for a free slot vs. actual
                    # prompt processing vs. actual generation, instead
                    # of just token counts.
                    print(
                        f"[GROQ rpg_engine] usage: prompt={getattr(usage, 'prompt_tokens', '?')} "
                        f"completion={getattr(usage, 'completion_tokens', '?')} "
                        f"cached={cached_tokens if cached_tokens is not None else 'n/a'} | "
                        f"queue_time={getattr(usage, 'queue_time', '?')}s "
                        f"prompt_time={getattr(usage, 'prompt_time', '?')}s "
                        f"completion_time={getattr(usage, 'completion_time', '?')}s "
                        f"total_time={getattr(usage, 'total_time', '?')}s",
                        flush=True,
                    )
            except Exception as _usage_exc:
                print(f"[GROQ rpg_engine] usage logging failed (non-fatal): "
                      f"{str(_usage_exc)[:200]}", flush=True)
            return response.choices[0].message.content.strip()
        except Exception as exc:
            last_exc = exc
            status = getattr(exc, "status_code", None)
            print(f"[GROQ rpg_engine] attempt {attempt}/{MAX_ATTEMPTS} failed: "
                  f"{str(exc)[:200]}", flush=True)

            # 429 = rate limited. Retrying immediately almost never
            # clears a rate-limit window (those reset on the order of
            # seconds-to-minutes), so burning the remaining attempt
            # instantly just wastes quota during an outage. Skip
            # straight to giving up instead of hammering the same
            # limited endpoint again seconds later.
            if status == 429:
                print("[GROQ rpg_engine] rate limited (429), not retrying "
                      "immediately — giving up for this call", flush=True)
                break

            if attempt < MAX_ATTEMPTS:
                # Flat short backoff (not exponential) — with only 2
                # attempts total and a 6s per-attempt cap, there's no
                # room in the 20s shared budget for a growing delay;
                # one brief pause before the single retry is enough
                # for a real transient blip to clear.
                time.sleep(RETRY_DELAY_SECONDS)

    print(f"[GROQ rpg_engine] all attempts failed, giving up: "
          f"{str(last_exc)[:200]}", flush=True)
    return None

def extract_json(text: str | None) -> dict | None:
    """
    Pulls a JSON object out of a model reply that's supposed to be
    JSON-only (see call_groq's json_mode). Since response_format is
    no longer used to enforce this at the API level, replies
    occasionally come wrapped in markdown fences or a stray
    sentence — this strips that and parses the first {...} block.
    Returns None if nothing parseable is found; callers already
    treat a None/failed reply as a safe-default case.
    """
    if not text:
        return None
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*|\s*```$", "", stripped.strip(), flags=re.IGNORECASE)
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None
    try:
        return json.loads(stripped[start:end + 1])
    except json.JSONDecodeError:
        return None
