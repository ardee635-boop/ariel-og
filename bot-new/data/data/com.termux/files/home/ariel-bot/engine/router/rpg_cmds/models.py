"""
router/rpg_cmds/models.py - King-only developer commands for switching LLM models.

These are NORMAL-pool commands (dispatched from router/normal.py, gated by the
group's Normal pool), not .rpg sub-commands:

    .models                 list the 10 presets and what each job uses
    .model                  show the active assignment per job
    .model <1-10>           switch to preset n (in memory; restart restores the default)
    .model <n> save         switch AND make it the default after restarts
    .model save             make the current preset the default
    .model <job> <m> [m2]   override one job; extra models are overflow in order
                            jobs: chat narration intent nouns combat_small combat_narration
                            models: 120b 20b qwen flash lite
    .model nouns on|smart|off   scene-noun extraction (smart = skip when the narrator
                            already listed scene objects)
    .model shortcuts on|off     combat shortcuts (skip split / classifiers when obvious)
    .model reset            back to the default preset, overrides cleared
    .llmtest                list test modes
    .llmtest <1-10>         run a test mode (see TESTS below)
    .nvtest                 call every candidate NVIDIA model once, report which answer + speed
    .nvtest <model id> ...  probe specific NVIDIA model ids

(.test is already taken by the ping/test dev command in bot/handler/dev_cmds.js,
so the failure-injection tests live under .llmtest.)

Non-King senders get no reply (silently ignored, like the other admin commands).
"""
import llm_models as lm
from permissions import is_king
from ._common import NOT_HANDLED

_JOB_ALIASES = {
    "chat": "chat", "narration": "narration", "narr": "narration", "narrator": "narration",
    "intent": "intent", "nouns": "nouns", "noun": "nouns",
    "combat_small": "combat_small", "small": "combat_small",
    "combat_narration": "combat_narration", "combat_narr": "combat_narration", "fight": "combat_narration",
}

TESTS = {
    1: "Off: clear any injected failure and the footer",
    2: "Inject: daily-limit 429 on EVERY model (checks the low-budget reply)",
    3: "Inject: 429 on the FIRST model of each chain only (checks overflow to the next model)",
    4: "Inject: timeouts on every model",
    5: "Inject: empty replies",
    6: "Inject: replies that are not JSON (checks the parse fallback)",
    7: "Toggle: footer on every RPG reply showing model + tokens per call",
    8: "Dry run: which model each job would use right now (no LLM calls)",
    9: "Usage: calls, tokens and failures per model since restart",
    10: "Reset: clear cooldowns and usage counters",
}
_INJECT = {2: "daily429", 3: "primary429", 4: "timeout", 5: "empty", 6: "badjson"}

_USAGE = (
    "*Model commands* (King only)\n"
    "• `.models` list presets\n"
    "• `.model` show active assignment\n"
    "• `.model <1-10>` switch preset (add `save` to keep it after restart)\n"
    "• `.model <job> <model> [overflow]` e.g. `.model narration qwen flash`\n"
    "  jobs: chat narration intent nouns combat_small combat_narration\n"
    "  models: 120b 20b qwen flash lite\n"
    "• `.model nouns on|smart|off` scene-noun extraction\n"
    "• `.model shortcuts on|off` combat shortcuts\n"
    "• `.model reset` back to default\n"
    "• `.llmtest` list test modes, `.llmtest <n>` run one\n"
    "• `.nvtest` probe NVIDIA models (which answer, how fast)"
)


def _models_cmd(args):
    if not args:
        return lm.describe_current()
    first = args[0].lower()
    if first == "reset" and len(args) == 1:
        lm.reset_to_default()
        return "↩️ Back to the default preset.\n" + lm.describe_current()
    if first == "save" and len(args) == 1:
        ok = lm.set_preset(lm.current_preset(), save=True)
        return (f"💾 Preset {lm.current_preset()} is now the default." if ok
                else "⚠️ Switched, but could not write the default to disk.")
    if first.isdigit():
        n = int(first)
        if n not in lm.PRESETS or len(args) > 2 or (len(args) == 2 and args[1].lower() != "save"):
            return f"Preset must be 1-{max(lm.PRESETS)} (optionally followed by `save`)."
        ok = lm.set_preset(n, save=len(args) == 2)
        head = f"✅ Preset {n} active" + (" and saved as default" if len(args) == 2 and ok else
                                         " (until restart; add `save` to keep it)")
        return head + "\n" + lm.describe_current()
    if first == "shortcuts" and len(args) == 2 and args[1].lower() in ("on", "off"):
        lm.set_combat_shortcuts(args[1].lower() == "on")
        return f"✅ Combat shortcuts: *{args[1].lower()}* (skip split for obvious single actions; skip classifiers on exact skill text)"
    if first in ("nouns", "noun") and len(args) == 2 and args[1].lower() in lm.NOUNS_MODES:
        lm.set_nouns_mode(args[1].lower())
        return (f"✅ Scene-noun extraction: *{args[1].lower()}*\n"
                "on = after every reply, smart = skip when the narrator already listed objects, off = never.")
    job = _JOB_ALIASES.get(first)
    if job:
        keys = [lm.resolve_model(a) for a in args[1:]]
        if not keys or any(k is None for k in keys):
            return ("Say which model(s): 120b 20b qwen flash lite nv nemotron nv120 nemo49 nemo253 seed nano, "
                    "or nv:<NVIDIA model id>. Example: `.model narration qwen nemotron lite`")
        lm.set_override(job, keys)
        return f"✅ {job} now uses {' -> '.join(lm.MODELS[k]['label'] for k in keys)}\n" + lm.describe_current()
    return NOT_HANDLED


def _test_cmd(args):
    if not args:
        return "*Test modes*\n" + "\n".join(f"{n}. {t}" for n, t in TESTS.items()) + \
               f"\nInjected failures expire after {lm.TEST_TTL_S // 60} minutes."
    if len(args) != 1 or not args[0].isdigit() or int(args[0]) not in TESTS:
        return NOT_HANDLED
    n = int(args[0])
    if n == 1:
        lm.set_test_fail(None)
        lm.set_test_footer(False)
        return "🧪 Test modes cleared."
    if n in _INJECT:
        lm.set_test_fail(_INJECT[n])
        return (f"🧪 {TESTS[n]}\nActive for {lm.TEST_TTL_S // 60} min or until `.llmtest 1`. "
                "Now send an RPG action.")
    if n == 7:
        lm.set_test_footer(not lm.test_footer_on())
        return f"🧪 Footer {'ON' if lm.test_footer_on() else 'OFF'}."
    if n == 8:
        return lm.describe_current()
    if n == 9:
        return lm.describe_usage()
    if n == 10:
        lm.clear_runtime_stats()
        return "🧪 Cooldowns and usage counters cleared."
    return NOT_HANDLED


MODEL_CMDS = {".models", ".model", ".llmtest", ".nvtest"}


def handle_command(sender, text):
    """Run one Normal-pool model command. Returns the reply string, None (ignored),
    or NOT_HANDLED when `text` isn't one of ours."""
    parts = (text or "").split()
    if not parts:
        return NOT_HANDLED
    cmd = parts[0].lower()
    if cmd not in MODEL_CMDS:
        return NOT_HANDLED
    if not is_king(sender):
        return None  # King-only; stay silent for everyone else
    args = parts[1:]
    if cmd == ".nvtest":
        ids = [a for a in args if "/" in a] or None
        if args and ids is None:
            return "Usage: `.nvtest` or `.nvtest <NVIDIA model id> ...` (ids look like `org/model-name`)"
        lines, n_ok = lm.probe_nvidia(ids)
        total = len(ids) if ids else len(lm.NV_CANDIDATES)
        return f"*NVIDIA probe: {n_ok}/{total} answered*\n" + "\n".join(lines)
    if cmd == ".models":
        return lm.describe_presets()
    if cmd == ".model":
        if args and args[0].lower() in ("help", "?"):
            return _USAGE
        out = _models_cmd(args)
        return _USAGE if out is NOT_HANDLED else out
    out = _test_cmd(args)
    if out is NOT_HANDLED:
        return _test_cmd([])
    return out


def handle(self, ctx):
    """Legacy RpgManager-handler signature (kept for tests); not registered in HANDLERS
    any more - model commands are Normal-pool now."""
    return handle_command(ctx.sender, ctx.text)
