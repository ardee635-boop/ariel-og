// bot/wmode/settings.js — every Work Mode limit lives here, none are hardcoded elsewhere.
// Precedence: built-in default < ariel.config key "work_settings" < environment variable.
export const DEFAULT_SETTINGS = {
    taskTokenBudget: 60000,   // input+output tokens one task may use before it pauses
    maxRetries: 2,            // extra attempts when every model failed for a transient reason
    retryBackoffMs: 1500,
    leaseMs: 60_000,          // a running task is "owned" this long without a heartbeat
    sweepMs: 60_000,          // how often expired leases are looked for
    recentTurns: 8,           // temporary conversation context kept per chat
    recentChars: 4000,
    eventKeepDays: 14,
    eventClipChars: 800,
    maxMessageChars: 3500,    // one WhatsApp message; longer answers are split
    maxRequestChars: 6000,    // longer requests are cut before they reach a model
    planMode: 'auto',         // 'auto' (decide per request) | 'always' | 'never'
    planMinChars: 280,        // requests at least this long are planned in auto mode
    maxSteps: 6,
    contextChars: 6000,       // how much earlier-step output a step prompt may carry (older steps shrink)
    stepOutputChars: 1500,    // step output kept in the database
    workspaceDir: 'work-workspace', // the ONLY folder file tools can touch (relative to the bot's working directory)
    toolOutputChars: 6000,    // one tool result shown to a model is cut to this
    maxReadBytes: 60000,
    maxWriteBytes: 200000,
    maxListEntries: 200,
    maxSearchResults: 40,
    toolMode: 'auto',         // 'auto' (file/code requests get tools) | 'always' | 'never'
    agentMaxSteps: 12,        // tool calls before a task pauses (.wresume grants another batch)
    agentResultChars: 1500,   // tool result kept per turn in the database and in recent prompts
    webTimeoutMs: 15000,      // one page download, redirects included
    webMaxBytes: 1000000,     // download cap per page
    webMaxRedirects: 3,
    pageChars: 5000,          // characters of a page shown per fetch_page call
    searchBackends: ['tavily', 'brave', 'wikipedia'],  // tried in this order; Tavily/Brave need TAVILY_API_KEY / BRAVE_API_KEY
    searchResults: 6,
    searchTimeoutMs: 10000,
    searchParkMs: 1800000,    // a backend that is out of quota / unauthorised is skipped this long
    commandTimeoutMs: 30000,  // a command is killed (whole process group) after this long
    commandOutputChars: 4000, // command output shown to a model
    autoApproveTests: false,  // true = run_tests without asking; run_command on code always asks
    verify: true,             // stage 7: ask for a check before accepting a code change, flag unbacked "it works" claims
    verifyNudges: 1,          // how many times Ariel sends the model back to run a check
    review: true,             // stage 7: an independent model reviews code changes before the final answer
    reviewMinTokens: 1500,    // skip the review (never pause for it) when less than this budget is left
    reviewChars: 6000,        // how much code the reviewer is shown
    progressMinMs: 8000,      // stage 8: progress lines are merged into at most one WhatsApp message per this long
    progressMaxLines: 6,      // lines shown in one progress message
    progressMaxMessages: 10,  // progress messages one task may send (the final answer is always sent)
    typing: true,             // show "typing…" while a task runs
    typingRefreshMs: 10000,
    logLines: 12,             // .wlog shows this many events
    projectMaxItems: 500,     // notes + decisions + to-dos one chat may keep
    projectItemChars: 2000,   // one note/decision body (longer is refused, never silently cut)
    projectContextItems: 5,   // project items shown to the model at the start of a tool task
    projectContextChars: 1500,
    projectListMax: 20,
    creativeTurns: 10,        // `.cchat`: messages (yours + hers) remembered per chat, in memory only
    creativeChars: 3000,      // `.cchat`: one remembered message is cut to this
    creativeIdleMs: 7_200_000, // `.cchat`: a chat idle this long starts fresh
    verifiedModels: [],       // extra "provider/model" ids allowed from a config override
};

const ENV_MAP = {
    WORK_TASK_TOKEN_BUDGET: ['taskTokenBudget', Number],
    WORK_MAX_RETRIES: ['maxRetries', Number],
    WORK_LEASE_MS: ['leaseMs', Number],
    WORK_PLAN_MODE: ['planMode', String],
    WORK_MAX_STEPS: ['maxSteps', Number],
    WORK_RECENT_TURNS: ['recentTurns', Number],
    WORK_EVENT_KEEP_DAYS: ['eventKeepDays', Number],
    WORK_TOOL_MODE: ['toolMode', String],
    WORK_AGENT_MAX_STEPS: ['agentMaxSteps', Number],
    WORK_WORKSPACE_DIR: ['workspaceDir', String],
    WORK_COMMAND_TIMEOUT_MS: ['commandTimeoutMs', Number],
    WORK_VERIFY: ['verify', (v) => !/^(0|false|off|no)$/i.test(v)],
    WORK_REVIEW: ['review', (v) => !/^(0|false|off|no)$/i.test(v)],
};

export function resolveSettings(override = null, env = process.env) {
    const out = { ...DEFAULT_SETTINGS };
    if (override && typeof override === 'object') {
        for (const k of Object.keys(DEFAULT_SETTINGS)) if (override[k] !== undefined && override[k] !== null) out[k] = override[k];
    }
    for (const [name, [key, cast]] of Object.entries(ENV_MAP)) {
        if (env[name] === undefined || env[name] === '') continue;
        const v = cast(env[name]);
        if (Number.isFinite(v)) out[key] = v;
    }
    return out;
}
