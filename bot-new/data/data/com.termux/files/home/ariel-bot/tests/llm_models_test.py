"""
Tests for the model-preset layer (engine/rpg/llm_models.py), its wiring into call_groq,
the King-only `.model / models / test` commands, the combat shortcuts, the narration
token diet and the chat changes. No network: Groq and Gemini are faked.

Run from the repo root:  python3 tests/llm_models_test.py
"""
import os, sys, tempfile, types, json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
E = os.path.join(ROOT, "engine")
for d in (E, *(os.path.join(E, x) for x in ("core", "shared", "pokemon", "pokemon/world", "rpg", "chat"))):
    if d not in sys.path:
        sys.path.append(d)
sys.path.insert(0, E)
_TMP = tempfile.mkdtemp()
os.environ.pop("SUPABASE_DB_URL", None)
os.environ["RAILWAY_VOLUME_MOUNT_PATH"] = _TMP
os.environ.pop("RPG_DEFAULT_PRESET", None)
os.chdir(_TMP)

fails = []
def ok(cond, name):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        fails.append(name)

import llm_models as lm
import rpg_llm

# ── 1. preset integrity ──────────────────────────────────────────────────
ok(sorted(lm.PRESETS) == list(range(1, 17)), "there are 16 presets (1-10 plus NVIDIA test presets 11-16)")
# Test-only preset 99 = the old overflow layout (Groq -> 20b -> NVIDIA -> Flash-Lite). Preset 10
# no longer has NVIDIA in it (the NVIDIA models it used were retired), but the overflow and
# exhaustion logic still needs a chain with NVIDIA in it to be tested.
lm.PRESETS[99] = lm._preset("test overflow", ["oss20", "nv-oss20", "gemini-lite"],
                            ["qwen", "oss20", "nv-nemotron", "gemini-lite"],
                            ["oss120", "oss20", "nv-oss20", "gemini-lite"],
                            ["oss120", "oss20", "nv-oss20", "gemini-lite"])
ok(all(set(p["jobs"]) == set(lm.JOBS) for p in lm.PRESETS.values()), "every preset assigns every job")
ok(all(k in lm.MODELS for p in lm.PRESETS.values() for ch in p["jobs"].values() for k in ch),
   "every model key in every chain exists in the registry")
ok(all(ch for p in lm.PRESETS.values() for ch in p["jobs"].values()), "no empty chains")
p2 = lm.PRESETS[2]["jobs"]
ok(p2["chat"] == ["oss20"] and p2["narration"] == ["qwen"] and p2["intent"] == ["oss120"] and p2["nouns"] == ["oss120"],
   "preset 2 = approved plan (chat 20b, narration qwen, intent/nouns 120b)")
ok(p2["combat_small"] == p2["intent"] and p2["combat_narration"] == p2["narration"],
   "combat jobs follow intent / narration by default")
ok(lm.PRESETS[1]["jobs"]["combat_narration"] == ["oss120"] and lm.PRESETS[1]["jobs"]["combat_small"] == ["oss120"],
   "preset 1 keeps combat on 120b like the old code")
ok(lm.PRESETS[10]["jobs"]["narration"] == ["qwen", "nv-super35", "nv-ultra", "gemini-lite"],
   "preset 10 narration: qwen -> NVIDIA 3.5-super -> NVIDIA ultra -> Flash-Lite")
ok(lm.PRESETS[10]["jobs"]["intent"] == ["oss120", "nv-light", "gemini-lite"]
   and lm.PRESETS[10]["jobs"]["nouns"] == ["oss120", "nv-light", "gemini-lite"]
   and lm.PRESETS[10]["jobs"]["chat"] == ["oss20"],
   "preset 10: intent/nouns 120b -> NVIDIA lightning -> Flash-Lite, chat is the 20b alone")
ok("nv-light" not in lm.PRESETS[10]["jobs"]["narration"],
   "preset 10 keeps lightning out of narration (it broke the narration JSON in live tests)")
ok(all("oss20" not in lm.PRESETS[10]["jobs"][j] for j in lm.JOBS if j != "chat"),
   "preset 10 keeps the 20b out of the RPG chains (it is chat's bucket)")
ok(not any(k in ("nv-oss120", "nv-nemotron") for ch in lm.PRESETS[10]["jobs"].values() for k in ch),
   "preset 10 has none of the NVIDIA models that were retired (410 / 404)")
ok(lm.MODELS["nv-light"]["id"] == "nvidia/nemotron-3.5-lightning-30b-a3b"
   and lm.MODELS["nv-super35"]["id"] == "nvidia/nemotron-3.5-super-vl-120b-a12b"
   and lm.MODELS["nv-ultra"]["id"] == "nvidia/nemotron-3-ultra-550b-a55b"
   and lm.PRESETS[14]["jobs"]["narration"] == ["nv-light"]
   and lm.PRESETS[15]["jobs"]["narration"] == ["nv-ultra"]
   and lm.PRESETS[16]["jobs"]["narration"] == ["nv-super35"],
   "NVIDIA test presets 14-16 point at the three current Nemotron models")
ok(not any("gemini-flash" in ch for p in (lm.PRESETS[10],) for ch in p["jobs"].values()),
   "preset 10 leaves out Gemini Flash (it timed out every call in testing)")
ok(lm.resolve_model("nvidia") == "nv-oss20" and lm.resolve_model("nemotron") == "nv-nemotron",
   "NVIDIA aliases resolve")
ok(lm.resolve_model("nv120") == "nv-oss120" and lm.resolve_model("nemo49") == "nv-nemo49"
   and lm.resolve_model("seed") == "nv-seed36" and lm.resolve_model("nano") == "nv-nano9"
   and lm.resolve_model("nemo253") == "nv-nemo253" and lm.resolve_model("nemo120") == "nv-nemotron",
   "extra NVIDIA model aliases resolve")
ck = lm.resolve_model("nv:qwen/some-model")
ok(ck == "custom:nv:qwen/some-model" and lm.MODELS[ck]["provider"] == "nvidia" and lm.MODELS[ck]["id"] == "qwen/some-model",
   "nv:<id> registers any NVIDIA model on the fly")
ok(lm.resolve_model("nv:") is None and lm.resolve_model("nv:a b") is None, "empty or spaced nv: ids are rejected")
ok(all(lm.MODELS[k]["provider"] == "nvidia" for p in (11, 12, 13) for ch in lm.PRESETS[p]["jobs"].values() for k in ch),
   "NVIDIA test presets use only NVIDIA models (no fallbacks, so failures show)")
ok("NVIDIA gpt-oss-120b" in lm.describe_presets() and "custom:" not in lm.describe_presets(),
   ".models lists the extra NVIDIA models and hides on-the-fly ones")
ok(lm.resolve_model("20b") == "oss20" and lm.resolve_model("Flash") == "gemini-flash"
   and lm.resolve_model("nope") is None, "model aliases resolve")

# ── 2. state: default, switch, save, reset, overrides ───────────────────
ok(lm.default_preset() == 2 and lm.current_preset() == 2, "default preset is 2")
lm.set_preset(5)
ok(lm.current_preset() == 5 and lm.default_preset() == 2, "set_preset is in memory only")
lm.reset_to_default()
ok(lm.current_preset() == 2, "reset returns to default")
lm.set_preset(7, save=True)
saved = json.load(open(lm._state_path()))
ok(saved == {"preset": 7} and lm.default_preset() == 7, "save=True persists the default")
lm._state.update({"default": None, "preset": None, "overrides": {}})  # simulate restart
ok(lm.current_preset() == 7, "persisted default survives a restart")
lm.set_preset(2, save=True)
lm.set_override("narration", ["gemini-flash", "oss20"])
ok(lm.get_chain("narration") == ["gemini-flash", "oss20"] and lm.get_chain("chat") == ["oss20"], "per-job override")
lm.set_preset(2)
ok(lm.get_chain("narration") == ["qwen"], "switching preset clears overrides")

# ── 3. complete(): chain, overflow, cooldown, errors ─────────────────────
calls = []
def make_provider(behaviour):
    def prov(entry, messages, max_tokens, temperature, timeout, tag):
        calls.append((entry["id"], timeout))
        r = behaviour(entry["id"])
        if isinstance(r, Exception):
            raise r
        return r, 100, 20, "stop"
    return prov

os.environ["GROQ_API_KEY"] = "g"; os.environ["GEMINI_API_KEY"] = "m"; os.environ["NVIDIA_API_KEY"] = "n"
real_providers = dict(lm._PROVIDERS)
msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]

lm._PROVIDERS["groq"] = make_provider(lambda mid: "groq-ok")
lm._PROVIDERS["gemini"] = make_provider(lambda mid: "gem-ok")
lm._PROVIDERS["nvidia"] = make_provider(lambda mid: "nv-ok")
lm.set_preset(2); lm.clear_runtime_stats(); calls.clear()
text, key = lm.complete("narration", msgs, max_tokens=50)
ok(text == "groq-ok" and key == "qwen" and calls[0][0] == "qwen/qwen3.8-27b", "narration under preset 2 runs on qwen")
ok(calls[0][1] == 22.0, "narration gets the long 22s timeout")
calls.clear(); lm.complete("intent", msgs)
ok(calls[0] == ("openai/gpt-oss-120b", 4.5), "intent runs on 120b with the short timeout")
calls.clear(); lm.complete("chat", msgs)
ok(calls[0] == ("openai/gpt-oss-20b", 22.0), "chat runs on 20b with the long timeout")
ok(lm._usage["qwen"]["calls"] == 1 and lm._usage["qwen"]["prompt"] == 100, "usage is recorded per model")

# overflow on 429 (test preset 99: Groq -> 20b -> NVIDIA -> Flash-Lite)
lm.set_preset(99); lm.clear_runtime_stats(); calls.clear()
lm._PROVIDERS["groq"] = make_provider(lambda mid: lm.RateLimitError("Rate limit: tokens per day (TPD)"))
text, key = lm.complete("narration", msgs)
ok(text == "nv-ok" and key == "nv-nemotron", "overflow: Groq daily-limited (qwen and 20b) falls to NVIDIA")
ok(lm.is_exhausted("qwen") and lm.is_exhausted("oss20"), "a daily-limit 429 marks each Groq model out for the day")
ok(lm.cooldown_left("qwen") == 0, "a daily-limit 429 is not a short cooldown")
calls.clear(); lm.complete("narration", msgs)
ok([c[0] for c in calls] == [lm.MODELS["nv-nemotron"]["id"]], "exhausted models are skipped while an alternative exists")
# NVIDIA also out -> Flash-Lite is the last resort
lm.clear_runtime_stats(); calls.clear()
lm._PROVIDERS["nvidia"] = make_provider(lambda mid: lm.RateLimitError("requests per day"))
text, key = lm.complete("narration", msgs)
ok(text == "gem-ok" and key == "gemini-lite", "NVIDIA limited too -> Gemini Flash-Lite answers last")
lm._PROVIDERS["nvidia"] = make_provider(lambda mid: "nv-ok")
# last resort is never skipped
lm.set_preset(2)
calls.clear()
lm._PROVIDERS["groq"] = make_provider(lambda mid: "back")
text, key = lm.complete("narration", msgs)
ok(text == "back" and calls, "the only/last model is tried even while cooling down")

# all fail
lm.set_preset(99); lm.clear_runtime_stats()
lm._PROVIDERS["groq"] = make_provider(lambda mid: lm.RateLimitError("tokens per minute"))
lm._PROVIDERS["gemini"] = make_provider(lambda mid: lm.APITimeoutError("Request timed out."))
lm._PROVIDERS["nvidia"] = make_provider(lambda mid: lm.RateLimitError("tokens per minute"))
try:
    lm.complete("intent", msgs); raised = None
except Exception as e:
    raised = e
ok(isinstance(raised, lm.APITimeoutError), "when every model fails the last error is raised")

# empty reply falls through
lm.clear_runtime_stats()
lm._PROVIDERS["groq"] = make_provider(lambda mid: "")
lm._PROVIDERS["gemini"] = make_provider(lambda mid: "gem-ok")
lm._PROVIDERS["nvidia"] = make_provider(lambda mid: "nv-ok")
ok(lm.complete("intent", msgs)[1] == "nv-oss20", "an empty reply from both Groq models falls through to NVIDIA")
lm.clear_runtime_stats()
lm._PROVIDERS["nvidia"] = make_provider(lambda mid: "")
ok(lm.complete("intent", msgs)[1] == "gemini-lite", "empty from NVIDIA too falls through to Flash-Lite")
lm._PROVIDERS["nvidia"] = make_provider(lambda mid: "nv-ok")

# no key
lm.set_preset(99)
del os.environ["GROQ_API_KEY"]; del os.environ["GEMINI_API_KEY"]; del os.environ["NVIDIA_API_KEY"]
try:
    lm.complete("intent", msgs); err = None
except Exception as e:
    err = str(e)
ok(err == "no API key set", "no provider key -> 'no API key set'")
os.environ["GROQ_API_KEY"] = "g"
lm.set_preset(99)
lm._PROVIDERS["groq"] = make_provider(lambda mid: "g-only")
ok(lm.complete("narration", msgs)[0] == "g-only", "models whose provider has no key are skipped")
os.environ["GEMINI_API_KEY"] = "m"; os.environ["NVIDIA_API_KEY"] = "n"

# ── 3b. out-for-the-day (exhausted) behaviour ───────────────────────────
import datetime as _dt
lm.set_preset(99); lm.clear_runtime_stats(); calls.clear()
lm._PROVIDERS["groq"] = make_provider(lambda mid: lm.RateLimitError("Rate limit: tokens per minute (TPM)"))
lm.complete("narration", msgs)
ok(not lm.is_exhausted("qwen") and lm.cooldown_left("qwen") > 0, "a per-minute 429 is a short cooldown, not out-for-the-day")
lm.clear_runtime_stats(); calls.clear()
lm._PROVIDERS["nvidia"] = make_provider(lambda mid: lm.LLMError("NVIDIA 410: model has reached its end of life", status_code=410))
lm._PROVIDERS["groq"] = make_provider(lambda mid: lm.RateLimitError("tokens per minute"))
lm.complete("chat", msgs)
ok(lm.is_exhausted("nv-oss20"), "a 410 (retired model) marks it out for the day")
lm._PROVIDERS["nvidia"] = make_provider(lambda mid: lm.LLMError("NVIDIA 404: Not found for account", status_code=404))
lm.clear_runtime_stats()
lm.complete("chat", msgs)
ok(lm.is_exhausted("nv-oss20"), "a 404 (not provisioned) marks it out for the day")
# persisted across a restart, and gone the next UTC day
lm.mark_exhausted("qwen")
lm._exhausted.clear(); lm._exhausted_loaded[0] = False
ok(lm.is_exhausted("qwen"), "out-for-the-day marks survive a restart (saved to disk)")
_real_day = lm._utc_day
lm._utc_day = lambda: "2099-01-01"
ok(not lm.is_exhausted("qwen"), "out-for-the-day ends at the next UTC day")
lm._utc_day = _real_day
lm.clear_runtime_stats()
ok(not lm.is_exhausted("qwen"), "clear_runtime_stats clears the out-for-the-day marks")
# the last model in a chain is still tried even if marked out
lm.set_preset(10); lm.clear_runtime_stats(); lm.mark_exhausted("oss20")
lm._PROVIDERS["groq"] = make_provider(lambda mid: "still-answers")
ok(lm.complete("chat", msgs)[0] == "still-answers", "chat's only model is still tried while marked out")
lm.clear_runtime_stats()
lm._PROVIDERS["nvidia"] = make_provider(lambda mid: "nv-ok")
lm._PROVIDERS["groq"] = make_provider(lambda mid: "groq-ok")

# ── 3c. NVIDIA probe (.nvtest) ───────────────────────────────────────
def _fake_nv(entry, messages, max_tokens, temperature, timeout, tag):
    if "dead" in entry["id"]:
        raise lm.LLMError("NVIDIA 404: Not found for account", status_code=404)
    if "empty" in entry["id"]:
        return "", 0, 0, "stop"
    return "The meadow sways. A breeze moves.", 10, 8, "stop"
_real_nv = lm._PROVIDERS["nvidia"]
lm._PROVIDERS["nvidia"] = _fake_nv
lm.clear_runtime_stats()
_lines, _n = lm.probe_nvidia(["a/good", "b/dead", "c/empty"])
ok(_n == 1 and _lines[0].startswith("\u2705") and any("404" in l for l in _lines) and any("empty reply" in l for l in _lines),
   "nvtest: reports good, 404 and empty models separately")
ok(not lm.is_exhausted("nv-oss20") and not lm._usage, "nvtest does not touch usage counters or out-for-the-day marks")
ok(len(lm.probe_nvidia()[0]) == len(lm.NV_CANDIDATES), "nvtest with no ids probes every candidate")
lm._PROVIDERS["nvidia"] = _real_nv
_k = os.environ.pop("NVIDIA_API_KEY")
ok(lm.probe_nvidia(["a/b"])[1] == 0, "nvtest without a key reports it instead of crashing")
os.environ["NVIDIA_API_KEY"] = _k
lm._PROVIDERS["nvidia"] = make_provider(lambda mid: "nv-ok")

# ── 4. test injection ────────────────────────────────────────────────────
lm.set_preset(99); lm.clear_runtime_stats()
lm._PROVIDERS["groq"] = make_provider(lambda mid: "groq-ok")
lm._PROVIDERS["gemini"] = make_provider(lambda mid: "gem-ok")
lm.set_test_fail("primary429")
ok(lm.complete("intent", msgs)[1] == "oss20", "test 3: first model 429 -> next model in the chain answers")
lm.clear_runtime_stats()
lm.set_test_fail("daily429")
try:
    lm.complete("intent", msgs); e = None
except Exception as ex:
    e = ex
ok(e is not None and rpg_llm.classify_failure(e) == "daily limit reached", "test 2: every model daily-limited")
lm.set_test_fail("badjson")
ok(lm.complete("intent", msgs)[0] == "this is not json at all", "test 6: non-JSON reply")
lm.set_test_fail("timeout")
try:
    lm.complete("intent", msgs); e = None
except Exception as ex:
    e = ex
ok(e is not None and rpg_llm.classify_failure(e) == "timed out", "test 4: timeouts label as 'timed out'")
lm.set_test_fail("empty")
try:
    lm.complete("intent", msgs); e = None
except Exception as ex:
    e = ex
ok(isinstance(e, lm.EmptyReply), "test 5: empty replies")
lm.set_test_fail("daily429"); lm._test["until"] = 0
ok(lm.test_fail_mode() is None, "injected failures expire")
lm.set_test_fail(None)

# ── 5. call_groq wiring (fake groq SDK) ──────────────────────────────────
for p in ("groq", "gemini", "nvidia"):
    lm._PROVIDERS[p] = real_providers[p]
seen = []
def fake_groq_module(behaviour):
    class _Msg:
        def __init__(self, c): self.content = c
    class _Choice:
        def __init__(self, c): self.message = _Msg(c); self.finish_reason = "stop"
    class _Resp:
        def __init__(self, c):
            self.choices = [_Choice(c)]
            self.usage = types.SimpleNamespace(prompt_tokens=10, completion_tokens=5, prompt_tokens_details=None)
    class _Completions:
        def create(self, **kw):
            seen.append(kw)
            r = behaviour(kw)
            if isinstance(r, Exception): raise r
            return _Resp(r)
    class Groq:
        def __init__(self, **kw): self.chat = types.SimpleNamespace(completions=_Completions())
    return types.SimpleNamespace(Groq=Groq)

sys.modules["groq"] = fake_groq_module(lambda kw: "fine")
lm.set_preset(2); lm.clear_runtime_stats()
with lm.llm_job("narration"):
    r = rpg_llm.call_groq("sys", "usr", json_mode=True)
ok(r == "fine" and seen[-1]["model"] == "qwen/qwen3.8-27b", "call_groq under a narration job uses qwen")
ok("reasoning_effort" not in seen[-1], "qwen is called without reasoning_effort")
ok("JSON" in seen[-1]["messages"][0]["content"], "json_mode still appends the JSON instruction")
rpg_llm.call_groq("sys", "usr")
ok(seen[-1]["model"] == "openai/gpt-oss-120b" and seen[-1].get("reasoning_effort") == "low",
   "no job -> intent default (120b) with reasoning_effort=low")
with lm.llm_job("chat"):
    rpg_llm.call_groq("sys", "usr")
ok(seen[-1]["model"] == "openai/gpt-oss-20b", "chat job uses 20b")
rpg_llm.call_groq("sys", "usr", model="openai/gpt-oss-20b")
ok(seen[-1]["model"] == "openai/gpt-oss-20b", "explicit model= still works as an override")
n_before = len(seen)
def _reasoning_400(kw):
    if "reasoning_effort" in kw:
        e = Exception("invalid reasoning_effort"); e.status_code = 400; return e
    return "ok-no-reasoning"
sys.modules["groq"] = fake_groq_module(_reasoning_400)
lm.set_override("intent", ["oss120"])
ok(rpg_llm.call_groq("s", "u") == "ok-no-reasoning" and len(seen) - n_before == 2,
   "a 400 about reasoning_effort retries once without it")
lm.set_preset(2)
sys.modules["groq"] = fake_groq_module(lambda kw: "<think>hmm</think>answer")
ok(rpg_llm.call_groq("s", "u") == "answer", "<think> blocks are stripped from replies")

class RateLimitError(Exception):
    def __init__(self, m, status=None): super().__init__(m); self.status_code = status
sys.modules["groq"] = fake_groq_module(lambda kw: RateLimitError("tokens per day (TPD)", 429))
lm.clear_runtime_stats()
ok(rpg_llm.call_groq("s", "u") is None and rpg_llm.failure_label() == "daily limit reached", "daily limit is labelled")
ok(rpg_llm.degraded_notice("daily limit reached") and "allowance" in rpg_llm.degraded_notice("daily limit reached"),
   "daily limit gets a friendly player notice")
ok(rpg_llm.degraded_notice("rate limited") and rpg_llm.degraded_notice("timed out") is None,
   "per-minute limit gets a notice, other reasons keep the old wording")

# ── 6. Gemini adapter (fake requests) ────────────────────────────────────
import requests
posted = {}
class _R:
    def __init__(self, status, data): self.status_code = status; self._d = data; self.text = json.dumps(data)
    def json(self): return self._d
def fake_post(url, headers=None, json=None, timeout=None):
    posted.update(url=url, headers=headers, body=json, timeout=timeout)
    return posted["resp"]
real_post = requests.post
requests.post = fake_post
posted["resp"] = _R(200, {"candidates": [{"finishReason": "STOP", "content": {"parts": [
    {"text": "hidden", "thought": True}, {"text": "Hello "}, {"text": "there"}]}}],
    "usageMetadata": {"promptTokenCount": 30, "candidatesTokenCount": 7, "thoughtsTokenCount": 3}})
text, p, c, fin = lm._gemini_complete(lm.MODELS["gemini-flash"], [
    {"role": "system", "content": "SYS"}, {"role": "user", "content": "a"},
    {"role": "assistant", "content": "b"}, {"role": "user", "content": "c"}], 100, 0.5, 5.0, "t")
ok(text == "Hello there" and (p, c) == (30, 10), "Gemini reply text and usage parsed (thought parts skipped)")
b = posted["body"]
ok(b["systemInstruction"]["parts"][0]["text"] == "SYS" and [x["role"] for x in b["contents"]] == ["user", "model", "user"],
   "Gemini payload: system instruction + alternating roles")
ok(b["generationConfig"]["maxOutputTokens"] == 356 and posted["headers"]["x-goog-api-key"] == "m",
   "Gemini payload: output headroom for thinking tokens; key sent as a header, not in the URL")
ok("key=" not in posted["url"], "API key is not in the URL")
posted["resp"] = _R(429, {"error": {"message": "Quota exceeded for metric ... PerDay"}})
try:
    lm._gemini_complete(lm.MODELS["gemini-flash"], msgs, 10, 0.5, 5.0, "t"); e = None
except Exception as ex:
    e = ex
ok(isinstance(e, lm.RateLimitError) and lm.is_daily_limit(e), "Gemini 429 -> RateLimitError, PerDay detected as daily")
requests.post = real_post

# ── 6b. NVIDIA adapter (fake requests) ───────────────────────────────────
requests.post = fake_post
posted["resp"] = _R(200, {"choices": [{"finish_reason": "stop", "message": {"content": "Hi from NV", "reasoning_content": "hidden"}}],
                          "usage": {"prompt_tokens": 40, "completion_tokens": 12}})
text, p, c, fin = lm._nvidia_complete(lm.MODELS["nv-oss20"], [{"role": "system", "content": "SYS"}, {"role": "user", "content": "u"}],
                                       100, 0.7, 5.0, "t")
ok(text == "Hi from NV" and (p, c) == (40, 12), "NVIDIA reply text and usage parsed (reasoning_content ignored)")
ok(posted["url"] == "https://integrate.api.nvidia.com/v1/chat/completions" and posted["body"]["model"] == "openai/gpt-oss-20b",
   "NVIDIA request goes to the OpenAI-style endpoint with the right model id")
ok(posted["headers"]["Authorization"] == "Bearer n" and "?" not in posted["url"], "NVIDIA key is sent as a bearer header, not in the URL")
ok(posted["body"]["max_tokens"] == 500 and posted["body"]["stream"] is False, "NVIDIA payload: output headroom for thinking tokens, no streaming")
posted["resp"] = _R(429, {"error": {"message": "Too Many Requests"}})
try:
    lm._nvidia_complete(lm.MODELS["nv-oss20"], msgs, 10, 0.5, 5.0, "t"); e = None
except Exception as ex:
    e = ex
ok(isinstance(e, lm.RateLimitError) and not lm.is_daily_limit(e), "NVIDIA 429 -> RateLimitError (per-minute cooldown)")
posted["resp"] = _R(500, {"detail": "boom"})
try:
    lm._nvidia_complete(lm.MODELS["nv-oss20"], msgs, 10, 0.5, 5.0, "t"); e = None
except Exception as ex:
    e = ex
ok(isinstance(e, lm.LLMError) and e.status_code == 500, "NVIDIA 5xx -> LLMError")
posted["resp"] = _R(200, {"choices": [{"finish_reason": "length", "message": {"content": None}}], "usage": {}})
ok(lm._nvidia_complete(lm.MODELS["nv-oss20"], msgs, 10, 0.5, 5.0, "t")[0] == "", "NVIDIA null content -> empty text (falls through the chain)")
requests.post = real_post
ok("nvidia" in lm._PROVIDERS and lm.provider_available("nv-oss20"), "NVIDIA provider registered and key detected")

# ── 7. commands ──────────────────────────────────────────────────────────
import router.rpg_cmds.models as mc
from router.rpg_cmds._common import NOT_HANDLED, DispatchContext
king = {"v": True}
mc.is_king = lambda s: king["v"]
def run(text, sender="k"):
    return mc.handle_command(sender, text)
lm.set_preset(2)
ok("Model presets" in run(".models") and "10" in run(".models"), ".models lists the presets")
ok("Active preset 2" in run(".model"), ".model shows the active assignment")
ok("Preset 5 active" in run(".model 5") and lm.current_preset() == 5, ".model 5 switches")
ok(lm.default_preset() == 2, ".model 5 does not change the saved default")
ok("saved as default" in run(".model 2 save") and lm.default_preset() == 2, ".model <n> save persists")
out = run(".model narration qwen flash")
ok(lm.get_chain("narration") == ["qwen", "gemini-flash"], ".model <job> <m> <overflow> sets a chain")
ok(run(".model narration banana").startswith("Say which"), "unknown model name is explained")
run(".model narration nv:Qwen/Some-Model")
ok(lm.get_chain("narration") == ["custom:nv:Qwen/Some-Model"] and lm.MODELS["custom:nv:Qwen/Some-Model"]["id"] == "Qwen/Some-Model",
   ".model narration nv:<id> keeps the id's case")
ok("Preset 11 active" in run(".model 11") and lm.current_preset() == 11, ".model 11 switches to an NVIDIA test preset")
lm.set_preset(2)
ok(isinstance(run(".model reset"), str) and lm.get_chain("narration") == ["qwen"], ".model reset clears overrides")
run(".model nouns smart"); ok(lm.nouns_mode() == "smart", ".model nouns smart")
run(".model nouns on"); ok(lm.nouns_mode() == "on", ".model nouns on")
run(".model shortcuts off"); ok(not lm.combat_shortcuts_on(), ".model shortcuts off")
run(".model shortcuts on"); ok(lm.combat_shortcuts_on(), ".model shortcuts on")
ok("Test modes" in run(".llmtest") and "10." in run(".llmtest"), ".llmtest lists modes")
run(".llmtest 3"); ok(lm.test_fail_mode() == "primary429", ".llmtest 3 injects a primary-model 429")
run(".llmtest 1"); ok(lm.test_fail_mode() is None and not lm.test_footer_on(), ".llmtest 1 clears")
run(".llmtest 7"); ok(lm.test_footer_on(), ".llmtest 7 turns the footer on"); run(".llmtest 7")
ok("Usage" in run(".llmtest 9") or "No LLM calls" in run(".llmtest 9"), ".llmtest 9 reports usage")
ok(run(".llmtest 10").startswith("🧪"), ".llmtest 10 clears counters")
ok(run(".llmtest the door") is NOT_HANDLED, "'.llmtest the door' is left to the narrator")
ok(run(".model citizens walk past") is NOT_HANDLED, "'.model citizens walk past' is left to the narrator")
ok(run(".rpg look around") is NOT_HANDLED and run(".look") is NOT_HANDLED, "other commands pass through")
king["v"] = False
ok(run(".models") is None and run(".model 5") is None and run(".llmtest 3") is None,
   "non-King senders cannot use model/test commands")
ok(lm.current_preset() == 2, "a non-King attempt changed nothing")
king["v"] = True

# trace footer
lm.set_preset(2); lm.clear_runtime_stats()
lm._PROVIDERS["groq"] = make_provider(lambda mid: "x")
lm.begin_trace(); lm.complete("narration", msgs)
ok("narration: qwen3.8-27b 100+20 tok" in lm.trace_footer() and "total 120" in lm.trace_footer(), "trace footer lists model + tokens")
for p in ("groq", "gemini", "nvidia"):
    lm._PROVIDERS[p] = real_providers[p]

# ── 8. combat shortcuts ──────────────────────────────────────────────────
import rpg_action_parse as ap
lm.set_combat_shortcuts(True)
for t in ("I slash at the goblin", "attack!", "I step back", "raise my shield"):
    ok(ap._obviously_single(t), f"single action: {t!r}")
for t in ("I dodge then slash", "I slash, then step back", "parry and counter", "step back. then strike",
          "I swing while backing away", "I feint and thrust"):
    ok(not ap._obviously_single(t), f"possible multi-action goes to the model: {t!r}")
ok(not ap._obviously_single("one two three four five six seven eight nine ten eleven twelve thirteen"), "long text goes to the model")
llm_calls = []
def spy(system, user, **kw):
    llm_calls.append(system[:20]); return json.dumps({"actions": ["x"]})
ok(ap.split_action_text("I slash at the goblin", spy) == ["I slash at the goblin"] and not llm_calls,
   "split skips the LLM for an obvious single action")
ap.split_action_text("I dodge then slash", spy)
ok(len(llm_calls) == 1, "split still calls the LLM when the message could hold two actions")
lm.set_combat_shortcuts(False); llm_calls.clear()
ap.split_action_text("I slash at the goblin", spy)
ok(len(llm_calls) == 1, "with shortcuts off the split call always runs")
lm.set_combat_shortcuts(True)
from rpg_weapon_data import WEAPON_TABLES
sk = WEAPON_TABLES["sword"][0]
ok(ap._exact_skill_key(sk["example"], "sword") == sk["key"], "exact skill example text maps to its key")
ok(ap._exact_skill_key("I use " + sk["name"], "sword") == sk["key"], "'I use <skill name>' maps to its key")
ok(ap._exact_skill_key("I do something fancy", "sword") is None, "fuzzy text is not shortcut")
llm_calls.clear()
ok(ap._classify_action_type(sk["example"], spy, "sword") == ap.ACTION_COMBAT and not llm_calls,
   "action-type classifier skipped on an exact skill")
ok(ap._classify_skill_key(sk["example"], spy, "sword") == sk["key"] and not llm_calls,
   "skill classifier skipped on an exact skill")
ap._classify_action_type("I wave hello", spy, "sword")
ok(len(llm_calls) == 1, "action-type classifier still runs for other text")

# ── 9. narration token diet ──────────────────────────────────────────────
import rpg_narrate as rn
ok(rn._needs_class_knowledge("I ask about classes", [], False), "class word in the action -> include knowledge")
ok(rn._needs_class_knowledge("I look around", [], True), "standing at a trial site -> include knowledge")
ok(rn._needs_class_knowledge("where is that?", [{"action": "I ask about the trial", "reply": "..."}], False),
   "follow-up to a class question -> include knowledge")
ok(not rn._needs_class_knowledge("I look around", [{"action": "I wave", "reply": "She smiles."}], False),
   "unrelated turn -> no class knowledge")
long_reply = "word " * 100
ok(len(rn._clip(long_reply)) <= rn.PAST_REPLY_CHARS + 1 and rn._clip(long_reply).endswith("…"), "past replies are capped")
ok(rn._clip("short") == "short", "short past replies are untouched")
import rpg_intent as ri
ok(len(ri._clip_past(long_reply)) <= 251, "intent context is capped too")
seen_prompts = []
def narr_spy(system, user, **kw):
    seen_prompts.append(user)
    return json.dumps({"narration": "ok", "choices": ["a", "b", "c"], "new_npcs": []})
ws = {"location": "Square", "class_knowledge": "CLASS & TRIAL KNOWLEDGE (x)", "history": [], "npcs": [],
      "scene_objects": [], "holding": {}, "location_details": {}}
res = {"mechanical": False, "damage": None, "type_mult": None, "skill_name": None}
rn.narrate_result("I look around", {"valid": True, "reason": None}, res, dict(ws), narr_spy)
ok("CLASS & TRIAL" not in seen_prompts[-1], "unrelated narration prompt omits class knowledge")
rn.narrate_result("I ask about classes", {"valid": True, "reason": None}, res, dict(ws), narr_spy)
ok("CLASS & TRIAL" in seen_prompts[-1], "class question narration prompt includes it")
ws2 = dict(ws, history=[{"action": "a" * 400, "reply": "b" * 400}])
rn.narrate_result("I look around", {"valid": True, "reason": None}, res, ws2, narr_spy)
ok("b" * 300 not in seen_prompts[-1], "narration prompt clips long past replies")
ok("2-3 short sentences" in rn._narration_system(False), "narration asks for 2-3 short sentences")

# ── 10. chat ─────────────────────────────────────────────────────────────
import ariel
ok(ariel._ARIEL_MAX_TURNS == 4, "chat keeps 4 turns of history")
man = {"happy-dance": "", "sleepy": "", "ariel": "", "angry_cat": ""}
ok(ariel._pick_sticker("I am so happy today", "hi", man) == "happy-dance", "sticker: tag word found in the reply")
ok(ariel._pick_sticker("hmm", "hi", man, hints="sleepy tired") == "sleepy", "sticker: mood hint matches a tag")
ok(ariel._pick_sticker("xyz", "qrs", man) == "ariel", "sticker: no match -> the 'ariel' catch-all")
ok(ariel._pick_sticker("x", "y", {}) is None, "sticker: empty manifest -> None")
import inspect
src = inspect.getsource(ariel)
ok("gpt-oss-120b" not in src.split("legacy constants")[-1].replace('GROQ_STICKER_MODEL = "openai/gpt-oss-120b"', ""),
   "chat code no longer calls 120b")
ok("client.chat.completions" not in src, "chat no longer talks to Groq directly (goes through llm_models)")

print()
if fails:
    print(f"{len(fails)} FAILED:"); [print("  -", f) for f in fails]
    sys.exit(1)
print("LLM MODELS TESTS PASSED")
