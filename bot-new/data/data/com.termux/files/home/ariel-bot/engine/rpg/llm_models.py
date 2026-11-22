"""
llm_models.py - model registry, presets, per-job routing, provider adapters.

WHY THIS EXISTS (see ariel-bot-rpg-token-notes.md, sections 5, 6a, 6b)
Chat and RPG used to share one Groq tank (gpt-oss-20b), and every combat
call ran on gpt-oss-120b. Groq limits are per MODEL, so spreading jobs over
different models (and a second provider, Gemini) multiplies the free budget.

A JOB is one kind of LLM call:
    chat             Ariel's normal conversation reply (and her sticker pick)
    narration        ordinary RPG narration
    intent           RPG intent extraction
    nouns            scene-noun extraction after a reply
    combat_small     fight helper calls: split / action type / skill / turn order
    combat_narration fight narration

A PRESET assigns an ordered CHAIN of models to every job. The first model is
tried first; if it fails (429, timeout, 5xx, empty reply, dead model) the next
model in the chain is tried. Presets 1-9 are single-model chains for testing and
comparing; preset 10 adds Gemini as overflow behind Groq.

Callers do not pass a model. They either run inside `with llm_job("intent"):`
or pass `job=`; call_groq (rpg_llm.py) and the chat code ask this module.
Test doubles that replace call_groq never see any of this.

NOT VERIFIED LIVE (no API keys or network in the build environment):
  * Gemini model IDs below are guesses from the names on Google's pricing page.
    Override with GEMINI_FLASH_MODEL / GEMINI_LITE_MODEL.
  * qwen/qwen3.8-27b: whether Groq accepts reasoning_effort for it. We omit it,
    and the Groq adapter also retries once without it if Groq answers 400.
"""
import contextlib
import contextvars
import datetime
import json
import os
import re
import threading
import time

# ----------------------------------------------------------------------------
# Jobs and models
# ----------------------------------------------------------------------------
JOBS = ("chat", "narration", "intent", "nouns", "combat_small", "combat_narration")

JOB_HELP = {
    "chat": "Ariel chat reply + sticker pick",
    "narration": "RPG narration",
    "intent": "RPG intent extraction",
    "nouns": "scene-noun extraction",
    "combat_small": "fight helpers (split, action type, skill, order)",
    "combat_narration": "fight narration",
}

# Jobs that get the long single-attempt timeout (they write the big reply). Chat replies
# can run to 900 tokens, so they get the same 22s single attempt, not the 4.5s small-call one.
LONG_JOBS = ("chat", "narration", "combat_narration")

MODELS = {
    "oss120": {"provider": "groq", "id": "openai/gpt-oss-120b", "label": "gpt-oss-120b",
               "reasoning": "low", "daily_cap": 200_000},
    "oss20": {"provider": "groq", "id": "openai/gpt-oss-20b", "label": "gpt-oss-20b",
              "reasoning": "low", "daily_cap": 200_000},
    # reasoning=None: we do not know that Groq accepts reasoning_effort for qwen.
    "qwen": {"provider": "groq", "id": os.environ.get("QWEN_MODEL_ID", "qwen/qwen3.8-27b"),
             "label": "qwen3.8-27b", "reasoning": None, "daily_cap": 200_000},
    "gemini-flash": {"provider": "gemini", "id": os.environ.get("GEMINI_FLASH_MODEL", "gemini-3.8-flash"),
                     "label": "Gemini Flash", "reasoning": None, "daily_cap": None},
    "gemini-lite": {"provider": "gemini", "id": os.environ.get("GEMINI_LITE_MODEL", "gemini-3.5-flash-lite"),
                    "label": "Gemini Flash-Lite", "reasoning": None, "daily_cap": None},
    # NVIDIA NIM (OpenAI-style API at integrate.api.nvidia.com). Free tier is limited by
    # requests (about 40/min, 10,000/day per model), not tokens, so no token cap is tracked.
    "nv-oss20": {"provider": "nvidia", "id": os.environ.get("NVIDIA_OSS20_MODEL", "openai/gpt-oss-20b"),
                 "label": "NVIDIA gpt-oss-20b", "reasoning": None, "daily_cap": None},
    "nv-nemotron": {"provider": "nvidia",
                    "id": os.environ.get("NVIDIA_NEMOTRON_MODEL", "nvidia/nemotron-3-super-120b-a12b"),
                    "label": "NVIDIA nemotron-120b", "reasoning": None, "daily_cap": None},
    # RETIRED on NVIDIA (found in the 2026-10-20 test): openai/gpt-oss-120b answers 410 (end of
    # life 2026-09-03) and nvidia/nemotron-3-super-120b-a12b answers 404 (support ended
    # 2026-10-19). Kept registered so old presets do not crash, but never put them in a chain.
    # Candidates below come from third-party summaries: verify with the /v1/models curl and
    # presets 14-16 before trusting them.
    "nv-ultra": {"provider": "nvidia",
                 "id": os.environ.get("NVIDIA_ULTRA_MODEL", "nvidia/nemotron-3-ultra-550b-a55b"),
                 "label": "NVIDIA nemotron-3-ultra", "reasoning": None, "daily_cap": None},
    "nv-light": {"provider": "nvidia",
                 "id": os.environ.get("NVIDIA_LIGHT_MODEL", "nvidia/nemotron-3.5-lightning-30b-a3b"),
                 "label": "NVIDIA nemotron-3.5-lightning", "reasoning": None, "daily_cap": None},
    "nv-super35": {"provider": "nvidia",
                   "id": os.environ.get("NVIDIA_SUPER35_MODEL", "nvidia/nemotron-3.5-super-vl-120b-a12b"),
                   "label": "NVIDIA nemotron-3.5-super", "reasoning": None, "daily_cap": None},
    # More NVIDIA models for `.rpg model` testing. Each is its own per-model quota on the same
    # key, but NVIDIA's catalog lists models an account may not be provisioned for: check with
    # `.rpg test 7` (a failing model shows "(failed)" in the footer). Any other NVIDIA model:
    # `.rpg model narration nv:<model id>`.
    "nv-oss120": {"provider": "nvidia", "id": os.environ.get("NVIDIA_OSS120_MODEL", "openai/gpt-oss-120b"),
                  "label": "NVIDIA gpt-oss-120b", "reasoning": None, "daily_cap": None},
    "nv-nemo49": {"provider": "nvidia",
                  "id": os.environ.get("NVIDIA_NEMO49_MODEL", "nvidia/llama-3.3-nemotron-super-49b-v1.5"),
                  "label": "NVIDIA nemotron-49b", "reasoning": None, "daily_cap": None},
    "nv-nemo253": {"provider": "nvidia",
                   "id": os.environ.get("NVIDIA_NEMO253_MODEL", "nvidia/llama-3.1-nemotron-ultra-253b-v1"),
                   "label": "NVIDIA nemotron-253b", "reasoning": None, "daily_cap": None},
    "nv-seed36": {"provider": "nvidia",
                  "id": os.environ.get("NVIDIA_SEED36_MODEL", "bytedance/seed-oss-36b-instruct"),
                  "label": "NVIDIA seed-oss-36b", "reasoning": None, "daily_cap": None},
    "nv-nano9": {"provider": "nvidia",
                 "id": os.environ.get("NVIDIA_NANO9_MODEL", "nvidia/nvidia-nemotron-nano-9b-v2"),
                 "label": "NVIDIA nemotron-nano-9b", "reasoning": None, "daily_cap": None},
}

ALIASES = {
    "120": "oss120", "120b": "oss120", "oss120": "oss120", "gpt-oss-120b": "oss120",
    "20": "oss20", "20b": "oss20", "oss20": "oss20", "gpt-oss-20b": "oss20",
    "qwen": "qwen", "q": "qwen", "qwen3.8": "qwen",
    "flash": "gemini-flash", "gemini": "gemini-flash", "gemini-flash": "gemini-flash",
    "lite": "gemini-lite", "flash-lite": "gemini-lite", "gemini-lite": "gemini-lite",
    "nv": "nv-oss20", "nv20": "nv-oss20", "nvidia": "nv-oss20", "nv-oss20": "nv-oss20",
    "nemotron": "nv-nemotron", "nemo120": "nv-nemotron", "nv-nemotron": "nv-nemotron",
    "ultra": "nv-ultra", "nv-ultra": "nv-ultra",
    "light": "nv-light", "lightning": "nv-light", "nv-light": "nv-light",
    "super35": "nv-super35", "nv-super35": "nv-super35",
    "nv120": "nv-oss120", "nv-oss120": "nv-oss120",
    "nemo49": "nv-nemo49", "nv49": "nv-nemo49", "nv-nemo49": "nv-nemo49",
    "nemo253": "nv-nemo253", "nv253": "nv-nemo253", "nv-nemo253": "nv-nemo253",
    "seed": "nv-seed36", "seed36": "nv-seed36", "nv-seed36": "nv-seed36",
    "nano": "nv-nano9", "nano9": "nv-nano9", "nv-nano9": "nv-nano9",
}


def resolve_model(token):
    """'qwen', '20b', 'flash' ... -> registry key, or None.
    'nv:<model id>' registers any NVIDIA model on the fly (for testing)."""
    t = (token or "").strip()
    key = ALIASES.get(t.lower())
    if key:
        return key
    if t.lower().startswith("nv:") and len(t) > 3 and " " not in t:
        mid = t[3:]
        k = "custom:nv:" + mid
        MODELS.setdefault(k, {"provider": "nvidia", "id": mid, "label": "NVIDIA " + mid.split("/")[-1],
                              "reasoning": None, "daily_cap": None})
        return k
    return None


# ----------------------------------------------------------------------------
# Presets
# ----------------------------------------------------------------------------
def _preset(name, chat, narration, intent, nouns, combat_small=None, combat_narration=None):
    """Each argument is a model key or a list of keys (primary first, then overflow).
    Combat jobs follow Intent / Narration unless given explicitly."""
    def lst(x):
        return list(x) if isinstance(x, (list, tuple)) else [x]
    jobs = {
        "chat": lst(chat), "narration": lst(narration), "intent": lst(intent), "nouns": lst(nouns),
        "combat_small": lst(combat_small if combat_small is not None else intent),
        "combat_narration": lst(combat_narration if combat_narration is not None else narration),
    }
    return {"name": name, "jobs": jobs}


PRESETS = {
    1: _preset("Baseline (the old setup)", "oss20", "oss20", "oss120", "oss120",
               combat_small="oss120", combat_narration="oss120"),
    2: _preset("Split Groq (approved plan)", "oss20", "qwen", "oss120", "oss120"),
    3: _preset("Chat/intent swap", "oss120", "qwen", "oss20", "oss20"),
    4: _preset("120b narrator", "oss20", "oss120", "oss20", "oss20"),
    5: _preset("Gemini narrator", "oss20", "gemini-flash", "oss120", "oss120"),
    6: _preset("Gemini RPG, Groq chat", "oss20", "gemini-flash", "gemini-lite", "gemini-lite"),
    7: _preset("Gemini chat, Groq RPG", "gemini-flash", "qwen", "oss120", "oss120"),
    8: _preset("Max spread", "gemini-lite", "qwen", "oss20", "oss120"),
    9: _preset("Cheapest (stress test)", "oss20", "gemini-lite", "gemini-lite", "gemini-lite"),
    # CHAIN OF COMMAND. A model that runs out of tokens is out until 00:00 UTC (see
    # mark_exhausted), so each job walks down its list as the day's budgets run dry.
    # Order: Groq primary -> NVIDIA (separate request-based quota) -> Gemini Flash-Lite last
    # (free prompts may train Google). Chat is Groq 20b only, no fallback, and the 20b is
    # kept out of the RPG chains so chat always has its whole daily bucket.
    10: _preset("Production: chain of command",
                ["oss20"],
                ["qwen", "nv-super35", "nv-ultra", "gemini-lite"],
                ["oss120", "nv-light", "gemini-lite"],
                ["oss120", "nv-light", "gemini-lite"]),
    # Chosen from the live tests of 2026-10-20 (presets 14-16): lightning ran 25+ intent calls
    # with 0 failures but broke the narration JSON on a travel turn, so it is intent-only;
    # 3.5-super and 3-ultra both narrated in character. Chat stays on the 20b alone.
}

# Test presets for the extra NVIDIA models. No fallbacks on purpose, so a model that is not
# provisioned for the account shows up as a failure in the `.rpg test 7` footer.
PRESETS[11] = _preset("NVIDIA test A: gpt-oss-120b", "nv-oss20", "nv-oss120", "nv-oss120", "nv-oss120")
PRESETS[12] = _preset("NVIDIA test B: nemotron-120b narrator", "nv-oss20", "nv-nemotron", "nv-oss20", "nv-oss20")
PRESETS[14] = _preset("NVIDIA test D: nemotron-3.5-lightning", "nv-oss20", "nv-light", "nv-light", "nv-light")
PRESETS[15] = _preset("NVIDIA test E: nemotron-3-ultra narrator", "nv-oss20", "nv-ultra", "nv-light", "nv-light")
PRESETS[16] = _preset("NVIDIA test F: nemotron-3.5-super narrator", "nv-oss20", "nv-super35", "nv-light", "nv-light")
PRESETS[13] = _preset("NVIDIA test C: nemotron-49b narrator", "nv-oss20", "nv-nemo49", "nv-oss20", "nv-oss20")

FALLBACK_PRESET = 2


def _state_path():
    base = os.environ.get("RAILWAY_VOLUME_MOUNT_PATH") or os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, "rpg_model_default.json")


def _load_default_preset():
    try:
        with open(_state_path(), "r", encoding="utf-8") as fh:
            n = int(json.load(fh).get("preset"))
        if n in PRESETS:
            return n
    except Exception:
        pass
    try:
        n = int(os.environ.get("RPG_DEFAULT_PRESET", ""))
        if n in PRESETS:
            return n
    except ValueError:
        pass
    return FALLBACK_PRESET


_lock = threading.RLock()
_state = {"default": None, "preset": None, "overrides": {}}


def _ensure_state():
    with _lock:
        if _state["default"] is None:
            _state["default"] = _load_default_preset()
            _state["preset"] = _state["default"]


def current_preset():
    _ensure_state()
    return _state["preset"]


def default_preset():
    _ensure_state()
    return _state["default"]


def set_preset(n, save=False):
    """Switch to preset n (in memory). save=True also makes it the persisted default."""
    _ensure_state()
    if n not in PRESETS:
        raise ValueError(f"no preset {n}")
    with _lock:
        _state["preset"] = n
        _state["overrides"] = {}
        if save:
            _state["default"] = n
            try:
                with open(_state_path(), "w", encoding="utf-8") as fh:
                    json.dump({"preset": n}, fh)
            except Exception as exc:
                print(f"[LLM] could not persist default preset: {exc}", flush=True)
                return False
    return True


def reset_to_default():
    _ensure_state()
    with _lock:
        _state["preset"] = _state["default"]
        _state["overrides"] = {}


def set_override(job, model_keys):
    _ensure_state()
    if job not in JOBS:
        raise ValueError(f"unknown job {job}")
    with _lock:
        _state["overrides"][job] = list(model_keys)


def get_chain(job):
    """Ordered list of model keys for this job right now."""
    _ensure_state()
    with _lock:
        if job in _state["overrides"]:
            return list(_state["overrides"][job])
        return list(PRESETS[_state["preset"]]["jobs"][job])


# ----------------------------------------------------------------------------
# Job context (so call sites do not need to pass anything through call_groq_fn)
# ----------------------------------------------------------------------------
_job_var = contextvars.ContextVar("llm_job", default=None)


@contextlib.contextmanager
def llm_job(name):
    tok = _job_var.set(name)
    try:
        yield
    finally:
        _job_var.reset(tok)


def current_job():
    return _job_var.get()


def llm_as(job, fn, *args, **kwargs):
    """Call fn(*args, **kwargs) with `job` as the active LLM job. A test double
    standing in for call_groq just sees a normal call."""
    with llm_job(job):
        return fn(*args, **kwargs)


# ----------------------------------------------------------------------------
# Errors
# ----------------------------------------------------------------------------
class LLMError(Exception):
    def __init__(self, msg, status_code=None):
        super().__init__(msg)
        self.status_code = status_code


class RateLimitError(LLMError):
    """Named so rpg_llm.classify_failure recognises it (429 / 'ratelimit' in name)."""
    def __init__(self, msg, status_code=429):
        super().__init__(msg, status_code)


class APITimeoutError(LLMError):
    pass


class EmptyReply(LLMError):
    pass


def is_daily_limit(exc):
    msg = str(exc).lower()
    return any(s in msg for s in ("per day", "perday", "tpd", "rpd", "daily"))


# ----------------------------------------------------------------------------
# Usage, cooldowns, test injection, trace
# ----------------------------------------------------------------------------
DAILY_COOLDOWN_S = float(os.environ.get("LLM_DAILY_COOLDOWN_S", "900"))
MINUTE_COOLDOWN_S = float(os.environ.get("LLM_MINUTE_COOLDOWN_S", "15"))

_usage = {}
_usage_day = [None]
_cooldown_until = {}
_last_error = {}


def _utc_day():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")


def _usage_row(key):
    today = _utc_day()
    if _usage_day[0] != today:
        _usage.clear()
        _usage_day[0] = today
    return _usage.setdefault(key, {"calls": 0, "prompt": 0, "completion": 0, "failures": 0})


def record_usage(key, prompt, completion):
    with _lock:
        row = _usage_row(key)
        row["calls"] += 1
        row["prompt"] += int(prompt or 0)
        row["completion"] += int(completion or 0)


def record_failure(key, exc):
    with _lock:
        _usage_row(key)["failures"] += 1
        _last_error[key] = str(exc)[:120]
        if getattr(exc, "status_code", None) == 429:
            if is_daily_limit(exc):
                # Injected by `.rpg test 2`: do not persist, or the test would lock real models.
                mark_exhausted(key, persist="injected by .rpg test" not in str(exc))
            else:
                _cooldown_until[key] = time.time() + MINUTE_COOLDOWN_S
        elif _is_dead_model(exc):
            mark_exhausted(key)


def cooldown_left(key):
    return max(0.0, _cooldown_until.get(key, 0.0) - time.time())


# --- "Out for the day": a model that hits its DAILY limit (or is dead) is skipped until
# 00:00 UTC instead of being re-tried every 15 minutes. Saved to disk so a restart
# (Render redeploy / sleep) does not make the bot forget and burn calls re-discovering it.
_exhausted = {}          # key -> UTC day string it ran out on
_exhausted_loaded = [False]


def _exh_path():
    return os.path.join(os.path.dirname(_state_path()), "rpg_model_exhausted.json")


def _exh_load():
    if _exhausted_loaded[0]:
        return
    _exhausted_loaded[0] = True
    try:
        with open(_exh_path(), "r", encoding="utf-8") as fh:
            today = _utc_day()
            for k, d in (json.load(fh) or {}).items():
                if d == today:
                    _exhausted.setdefault(k, d)
    except Exception:
        pass


def _exh_save():
    try:
        with open(_exh_path(), "w", encoding="utf-8") as fh:
            json.dump({k: d for k, d in _exhausted.items() if d == _utc_day()}, fh)
    except Exception:
        pass  # read-only disk must never break a reply


def mark_exhausted(key, persist=True):
    with _lock:
        _exh_load()
        _exhausted[key] = _utc_day()
        if persist:
            _exh_save()
    print(f"[LLM] {key} is out for the day (until 00:00 UTC)", flush=True)


def is_exhausted(key):
    with _lock:
        _exh_load()
        return _exhausted.get(key) == _utc_day()


def _is_dead_model(exc):
    """Model removed / not provisioned for this key: no point retrying until tomorrow."""
    code = getattr(exc, "status_code", None)
    msg = str(exc).lower()
    return code in (401, 403, 404, 410) or "decommission" in msg or "does not exist" in msg


def clear_runtime_stats():
    with _lock:
        _usage.clear()
        _cooldown_until.clear()
        _last_error.clear()
        _exhausted.clear()
        _exhausted_loaded[0] = True
        _exh_save()


# Scene-noun extraction mode. "on" = run after every valid reply (the behaviour before the
# token diet). "smart" = skip it when the narration already returned scene objects itself.
# "off" = never. Default stays "on": whether the extra call is truly redundant is
# unverified (the narrator can omit things the extractor catches, and the extractor also
# judges the choices), so flip it live with `.rpg model nouns smart` and watch whether
# players get "that isn't here" rejections before making it the default.
_nouns = {"mode": os.environ.get("RPG_NOUNS_MODE", "on").strip().lower()}
NOUNS_MODES = ("on", "smart", "off")


def nouns_mode():
    return _nouns["mode"] if _nouns["mode"] in NOUNS_MODES else "on"


def set_nouns_mode(mode):
    if mode not in NOUNS_MODES:
        raise ValueError(mode)
    _nouns["mode"] = mode


# Combat shortcuts (token diet): skip the split call for obviously single actions and skip
# the action-type / skill classifiers when the text IS a known skill. Default on; flip with
# `.rpg model shortcuts off` to compare against the old always-call behaviour.
_flags = {"combat_shortcuts": os.environ.get("RPG_COMBAT_SHORTCUTS", "on").strip().lower() != "off"}


def combat_shortcuts_on():
    return _flags["combat_shortcuts"]


def set_combat_shortcuts(on):
    _flags["combat_shortcuts"] = bool(on)


_test = {"fail": None, "until": 0.0, "footer": False}
TEST_TTL_S = 600


def set_test_fail(mode):
    with _lock:
        _test["fail"] = mode
        _test["until"] = time.time() + TEST_TTL_S if mode else 0.0


def set_test_footer(on):
    with _lock:
        _test["footer"] = bool(on)


def test_footer_on():
    return bool(_test["footer"])


def test_fail_mode():
    with _lock:
        if _test["fail"] and time.time() > _test["until"]:
            _test["fail"] = None
        return _test["fail"]


_trace = threading.local()


def begin_trace():
    _trace.calls = []


def _trace_add(job, key, prompt, completion, ok):
    calls = getattr(_trace, "calls", None)
    if calls is not None:
        calls.append((job, key, prompt, completion, ok))


def trace_footer():
    calls = getattr(_trace, "calls", None) or []
    if not calls:
        return ""
    lines = []
    for job, key, p, c, ok in calls:
        label = MODELS.get(key, {}).get("label", key)
        lines.append(f"{job}: {label} {p}+{c} tok" + ("" if ok else " (failed)"))
    total = sum((p or 0) + (c or 0) for _, _, p, c, _ in calls)
    return "\n\n_[test] " + " | ".join(lines) + f" | total {total} tok_"


# ----------------------------------------------------------------------------
# Provider adapters
# ----------------------------------------------------------------------------
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


def _clean(text):
    return _THINK_RE.sub("", text or "").strip()


def _env_key(provider):
    if provider == "groq":
        return os.environ.get("GROQ_API_KEY", "").strip()
    if provider == "gemini":
        return (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or "").strip()
    if provider == "nvidia":
        return os.environ.get("NVIDIA_API_KEY", "").strip()
    return ""


def provider_available(key):
    entry = MODELS.get(key)
    return bool(entry and _env_key(entry["provider"]))


def _groq_complete(entry, messages, max_tokens, temperature, timeout, tag):
    from groq import Groq  # lazy: tests stub sys.modules["groq"]
    client = Groq(api_key=_env_key("groq"), timeout=timeout)
    kwargs = dict(model=entry["id"], messages=messages, max_tokens=max_tokens, temperature=temperature)
    if entry.get("reasoning"):
        kwargs["reasoning_effort"] = entry["reasoning"]
    try:
        resp = client.chat.completions.create(**kwargs)
    except Exception as exc:
        # An unknown reasoning_effort value comes back as a 400; drop it and retry once.
        if "reasoning_effort" in kwargs and getattr(exc, "status_code", None) == 400 \
                and "reasoning" in str(exc).lower():
            kwargs.pop("reasoning_effort")
            resp = client.chat.completions.create(**kwargs)
        else:
            raise
    usage = getattr(resp, "usage", None)
    p = c = 0
    if usage:
        p = getattr(usage, "prompt_tokens", 0) or 0
        c = getattr(usage, "completion_tokens", 0) or 0
        try:
            det = getattr(usage, "prompt_tokens_details", None)
            cached = getattr(det, "cached_tokens", None) if det else None
            print(
                f"[GROQ {tag}] usage: prompt={p} completion={c} "
                f"cached={cached if cached is not None else 'n/a'} | "
                f"queue_time={getattr(usage, 'queue_time', '?')}s "
                f"prompt_time={getattr(usage, 'prompt_time', '?')}s "
                f"completion_time={getattr(usage, 'completion_time', '?')}s "
                f"total_time={getattr(usage, 'total_time', '?')}s model={entry['id']}",
                flush=True)
        except Exception as exc:  # logging must never break a call
            print(f"[GROQ {tag}] usage logging failed (non-fatal): {str(exc)[:200]}", flush=True)
    choice = resp.choices[0]
    text = _clean(choice.message.content)
    return text, p, c, getattr(choice, "finish_reason", None)


def _gemini_complete(entry, messages, max_tokens, temperature, timeout, tag):
    import requests
    system_parts, contents = [], []
    for m in messages:
        if m["role"] == "system":
            system_parts.append(m["content"])
            continue
        role = "model" if m["role"] == "assistant" else "user"
        if contents and contents[-1]["role"] == role:  # Gemini wants alternating turns
            contents[-1]["parts"][0]["text"] += "\n" + m["content"]
        else:
            contents.append({"role": role, "parts": [{"text": m["content"]}]})
    body = {
        "contents": contents or [{"role": "user", "parts": [{"text": "."}]}],
        # Gemini counts hidden "thinking" tokens inside this cap, so leave headroom.
        "generationConfig": {"maxOutputTokens": int(max_tokens) + 256, "temperature": temperature},
    }
    if system_parts:
        body["systemInstruction"] = {"parts": [{"text": "\n\n".join(system_parts)}]}
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{entry['id']}:generateContent"
    try:
        r = requests.post(url, headers={"x-goog-api-key": _env_key("gemini"),
                                        "Content-Type": "application/json"},
                          json=body, timeout=timeout)
    except requests.Timeout:
        raise APITimeoutError("Request timed out.")
    if r.status_code != 200:
        try:
            msg = r.json().get("error", {}).get("message", r.text)
        except Exception:
            msg = r.text
        if r.status_code == 429:
            raise RateLimitError(f"Gemini rate limit: {msg}"[:400])
        raise LLMError(f"Gemini {r.status_code}: {msg}"[:400], status_code=r.status_code)
    data = r.json()
    um = data.get("usageMetadata", {}) or {}
    p = um.get("promptTokenCount", 0) or 0
    c = (um.get("candidatesTokenCount", 0) or 0) + (um.get("thoughtsTokenCount", 0) or 0)
    cands = data.get("candidates") or []
    text, finish = "", None
    if cands:
        finish = cands[0].get("finishReason")
        parts = (cands[0].get("content") or {}).get("parts") or []
        text = _clean("".join(x.get("text", "") for x in parts if not x.get("thought")))
    print(f"[GEMINI {tag}] usage: prompt={p} completion={c} model={entry['id']}", flush=True)
    return text, p, c, finish


# Models that think by default on NVIDIA; `enable_thinking: false` keeps replies fast and short.
# Anything that rejects the field gets one retry without it, so extra entries here are safe.
_NV_THINKING_OFF = ("nemotron-3", "gemma-4", "deepseek-v4", "glm-5", "kimi-k2")

NVIDIA_URL = os.environ.get("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1").rstrip("/")


def _nvidia_complete(entry, messages, max_tokens, temperature, timeout, tag):
    """OpenAI-style chat completion against NVIDIA NIM. Uses `requests` (already a dependency)."""
    import requests
    timeout = max(timeout, 12.0)  # NVIDIA free endpoints queue; 4.5s always timed out
    body = {
        "model": entry["id"],
        "messages": messages,
        # Reasoning models count hidden thinking inside max_tokens, so leave headroom.
        "max_tokens": int(max_tokens) + 400,
        "temperature": temperature,
        "stream": False,
    }
    # The Nemotron 3.x models think by default (slow, and the thinking eats max_tokens).
    # NVIDIA's own examples show chat_template_kwargs.enable_thinking, so switch it off.
    # If an endpoint rejects the field with a 400, retry once without it.
    if any(t in entry["id"] for t in _NV_THINKING_OFF):
        body["chat_template_kwargs"] = {"enable_thinking": False}
    hdrs = {"Authorization": f"Bearer {_env_key('nvidia')}", "Content-Type": "application/json"}
    try:
        r = requests.post(f"{NVIDIA_URL}/chat/completions", headers=hdrs, json=body, timeout=timeout)
        if r.status_code in (400, 422) and "chat_template_kwargs" in body:
            body.pop("chat_template_kwargs")
            r = requests.post(f"{NVIDIA_URL}/chat/completions", headers=hdrs, json=body, timeout=timeout)
    except requests.Timeout:
        raise APITimeoutError("Request timed out.")
    if r.status_code != 200:
        try:
            err = r.json()
            msg = (err.get("error") or {}).get("message") if isinstance(err.get("error"), dict) \
                else (err.get("detail") or err.get("message") or r.text)
        except Exception:
            msg = r.text
        msg = msg or r.text
        if r.status_code == 429:
            raise RateLimitError(f"NVIDIA rate limit: {msg}"[:400])
        raise LLMError(f"NVIDIA {r.status_code}: {msg}"[:400], status_code=r.status_code)
    data = r.json()
    usage = data.get("usage") or {}
    p = usage.get("prompt_tokens", 0) or 0
    c = usage.get("completion_tokens", 0) or 0
    choices = data.get("choices") or []
    text, finish = "", None
    if choices:
        finish = choices[0].get("finish_reason")
        text = _clean((choices[0].get("message") or {}).get("content") or "")
    print(f"[NVIDIA {tag}] usage: prompt={p} completion={c} model={entry['id']}", flush=True)
    return text, p, c, finish


_PROVIDERS = {"groq": _groq_complete, "gemini": _gemini_complete, "nvidia": _nvidia_complete}


# ----------------------------------------------------------------------------
# NVIDIA probe (`.rpg nvtest`): which models does THIS key actually answer, and how fast?
# NVIDIA's /v1/models lists models an account cannot call (the retired nemotron-3-super was
# still listed while answering 404), so the only real check is a tiny chat call per model.
# Calls the adapter directly: no usage counters, no out-for-the-day marks.
# ----------------------------------------------------------------------------
NV_CANDIDATES = (
    "deepseek-ai/deepseek-v4.1-flash",
    "google/gemma-4-31b-it",
    "moonshotai/kimi-k2.6",
    "z-ai/glm-5.3",
    "z-ai/glm-5.3-flash",
    "writer/palmyra-creative-122b",
    "nvidia/nemotron-3.5-lightning-30b-a3b",
    "nvidia/nemotron-3.5-super-vl-120b-a12b",
    "nvidia/nemotron-3-ultra-550b-a55b",
    "nvidia/nemotron-nano-3-30b-a3b",
    "nvidia/llama-3.1-nemotron-ultra-253b-v1",
    "openai/gpt-oss-20b",
    "mistralai/mistral-large-2-instruct",
    "google/gemma-3-12b-it",
    "nvidia/llama-3.1-nemotron-70b-instruct",
)
_PROBE_MESSAGES = [
    {"role": "system", "content": "You are the narrator of a gentle fantasy RPG. Reply in exactly "
                                  "two short sentences, third person, present tense."},
    {"role": "user", "content": "The player looks around a quiet meadow."},
]


def probe_nvidia(model_ids=None, timeout=30.0):
    """Returns (lines, ok_count). One short narration call per model, run in parallel."""
    from concurrent.futures import ThreadPoolExecutor
    ids = list(model_ids) if model_ids else list(NV_CANDIDATES)
    if not provider_available("nv-oss20"):
        return ["No NVIDIA key is set on this server (NVIDIA_API_KEY)."], 0

    def one(mid):
        entry = {"provider": "nvidia", "id": mid, "label": mid, "reasoning": None, "daily_cap": None}
        t0 = time.time()
        try:
            text, p, c, _fin = _PROVIDERS["nvidia"](entry, _PROBE_MESSAGES, 120, 0.8, timeout, "nvtest")
            secs = time.time() - t0
            if not text:
                return (False, secs, mid, "empty reply")
            return (True, secs, mid, " ".join(text.split())[:90])
        except Exception as exc:
            return (False, time.time() - t0, mid, " ".join(str(exc).split())[:70])

    with ThreadPoolExecutor(max_workers=min(8, max(1, len(ids)))) as pool:
        results = list(pool.map(one, ids))
    good = sorted((r for r in results if r[0]), key=lambda r: r[1])
    bad = [r for r in results if not r[0]]
    lines = [f"\u2705 {r[1]:.1f}s {r[2]}\n   {r[3]}" for r in good]
    lines += [f"\u274c {r[1]:.0f}s {r[2]}: {r[3]}" for r in bad]
    return lines, len(good)


# ----------------------------------------------------------------------------
# The one entry point
# ----------------------------------------------------------------------------
def _entry_for(key_or_id):
    if key_or_id in MODELS:
        return key_or_id
    for k, e in MODELS.items():
        if e["id"] == key_or_id:
            return k
    MODELS.setdefault("custom:" + key_or_id, {"provider": "groq", "id": key_or_id, "label": key_or_id,
                                                "reasoning": "low", "daily_cap": None})
    return "custom:" + key_or_id


def _inject(key, idx, job):
    mode = test_fail_mode()
    if not mode:
        return None
    if mode == "daily429":
        raise RateLimitError("Rate limit reached: tokens per day (TPD) limit (injected by .rpg test)")
    if mode == "primary429" and idx == 0:
        raise RateLimitError("Rate limit reached: tokens per minute (injected by .rpg test)")
    if mode == "timeout":
        raise APITimeoutError("Request timed out. (injected by .rpg test)")
    if mode == "empty":
        return ("", 0, 0, "stop")
    if mode == "badjson":
        return ("this is not json at all", 0, 0, "stop")
    return None


def complete(job, messages, *, max_tokens=300, temperature=0.8, model=None, tag="rpg_engine"):
    """Run one completion for `job`, walking the job's model chain.

    Returns (text, model_key). Raises the last exception if every model failed
    (LLMError "no API key set" if no usable provider key exists).
    """
    chain = [_entry_for(model)] if model else get_chain(job)
    usable = [k for k in chain if provider_available(k)]
    if not usable:
        raise LLMError("no API key set")
    long_job = job in LONG_JOBS
    timeout = 22.0 if long_job else 4.5
    attempts = 1 if long_job else 2
    last_exc = None
    for idx, key in enumerate(usable):
        # Route around a model that is cooling down, but never skip the last resort.
        if (is_exhausted(key) or cooldown_left(key) > 0) and idx < len(usable) - 1:
            continue
        entry = MODELS[key]
        for attempt in range(1, attempts + 1):
            try:
                injected = _inject(key, idx, job)
                if injected is not None:
                    text, p, c, finish = injected
                else:
                    text, p, c, finish = _PROVIDERS[entry["provider"]](
                        entry, messages, max_tokens, temperature, timeout, tag)
                if not text:
                    print(f"[LLM] EMPTY reply: finish_reason={finish} max_tokens={max_tokens} "
                          f"model={entry['id']} job={job}", flush=True)
                    record_usage(key, p, c)
                    _trace_add(job, key, p, c, False)
                    raise EmptyReply("empty reply")
                record_usage(key, p, c)
                _trace_add(job, key, p, c, True)
                return text, key
            except Exception as exc:
                last_exc = exc
                if not isinstance(exc, EmptyReply):
                    record_failure(key, exc)
                    _trace_add(job, key, 0, 0, False)
                print(f"[LLM] {job} on {entry['label']} attempt {attempt}/{attempts} failed: "
                      f"{str(exc)[:200]}", flush=True)
                if getattr(exc, "status_code", None) == 429 or isinstance(exc, EmptyReply):
                    break  # retrying the same model will not help
                if attempt < attempts:
                    time.sleep(0.4)
        if idx < len(usable) - 1:
            print(f"[LLM] {job}: falling through to next model in chain", flush=True)
    raise last_exc if last_exc else LLMError("error")


# ----------------------------------------------------------------------------
# Reports (used by .rpg models / .rpg test)
# ----------------------------------------------------------------------------
def _fmt_chain(keys):
    return " -> ".join(MODELS[k]["label"] for k in keys)


def describe_presets():
    _ensure_state()
    lines = ["*Model presets*"]
    for n, p in PRESETS.items():
        mark = "▶ " if n == _state["preset"] else "  "
        dflt = " (default)" if n == _state["default"] else ""
        j = p["jobs"]
        lines.append(f"{mark}*{n}* {p['name']}{dflt}\n    chat {_fmt_chain(j['chat'])} | narr {_fmt_chain(j['narration'])}"
                     f" | intent {_fmt_chain(j['intent'])} | nouns {_fmt_chain(j['nouns'])}")
    lines.append("\nModels: " + ", ".join(f"{k} ({v['label']})" for k, v in MODELS.items() if not k.startswith("custom:")))
    return "\n".join(lines)


def describe_current():
    _ensure_state()
    lines = [f"*Active preset {_state['preset']}* — {PRESETS[_state['preset']]['name']}"
             f" (default {_state['default']})"]
    for job in JOBS:
        chain = get_chain(job)
        parts = []
        for i, k in enumerate(chain):
            tag = MODELS[k]["label"]
            if not provider_available(k):
                tag += " ⚠no key"
            cd = cooldown_left(k)
            if is_exhausted(k):
                tag += " \u26d4out today"
            elif cd > 0:
                tag += f" ⏳{int(cd)}s"
            parts.append(tag)
        star = "*" if job in _state["overrides"] else ""
        lines.append(f"• {job}{star}: " + " -> ".join(parts))
    if _state["overrides"]:
        lines.append("(* = manual override; `.rpg model reset` clears)")
    return "\n".join(lines)


def describe_usage():
    with _lock:
        if not _usage:
            return "No LLM calls recorded since restart (or since UTC midnight)."
        lines = [f"*Usage today (UTC {_utc_day()}, this process only)*"]
        for k, row in sorted(_usage.items()):
            cap = MODELS.get(k, {}).get("daily_cap")
            total = row["prompt"] + row["completion"]
            pct = f" ({total * 100 // cap}% of {cap // 1000}K)" if cap else ""
            err = f" | last error: {_last_error[k]}" if k in _last_error else ""
            lines.append(f"• {MODELS.get(k, {}).get('label', k)}: {row['calls']} calls, "
                         f"{total} tok{pct}, {row['failures']} failed{err}")
        return "\n".join(lines)
