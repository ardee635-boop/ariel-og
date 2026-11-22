// Tunable limits for the conversation engine. Everything here is a starting value from the design doc.
export const DEFAULTS = {
    batch: { dmMs: 3500, groupMs: 6000, capMs: 20000 },   // wait for quiet; hard cap from the first message
    tokenBudget: 2500,          // recent-chat budget for the context pack (was 6000: each reply ate most of a Groq minute)
    recentLimit: 40,            // rows read from the database per call
    maxOutputTokens: 500,
    temperature: 0.9,
    maxBubbles: 4,
    maxBubbleChars: 700,
    involvement: 25,            // about one unprompted group contribution per 25 messages (per-chat setting can change it)
    followUpMs: 90_000,         // after she answers someone in a group, their next plain message within this time counts as for her
    maxFollowUps: 3,            // ...for at most this many in a row (a tag, quote or her name resets it)
    maxEmoji: 2,                // per reply, enforced in code
    sticker: { only: 0.20, alongside: 0.10, onlyMaxChars: 80 },   // per text reply: sticker instead of text (short replies only) / sticker added after the text
    quoteChance: { group: 1, dm: 1 },   // chance her reply quotes the message it answers (1 = always). Extra bubbles and an added sticker never quote
    ratePerMin: 6,              // addressed messages per person per minute
    staleMs: 90_000,            // older than this when we see it (restart backlog): store, don't answer
    repeatWindow: 20,           // her own last messages checked by the repetition guard
    tz: 'Africa/Lagos',
    maint: {
        segmentIdleMin: 30, segmentMaxMsgs: 40,          // a segment closes after 30 min idle or 40 messages
        retentionDays: 14, minRetentionDays: 3, keepLatest: 200, cleanupBatch: 500,
        limits: { person: 300, group: 500, global: 200 },
        mergeSim: 0.88, maxMergesPerNight: 25,
        minConfidence: 0.6, maxMemoriesPerSegment: 12,
        maxAttempts: 5, pollMs: 3000, jobTimeoutMs: 5 * 60_000,
    },
    self: {                                              // stage 8: identity evolution and feedback
        feedback: { minSignals: 3, minPeople: 2, windowDays: 7, dedupeHours: 12, keepDays: 60 },
        reflect: { windowDays: 28, minEpisodes: 3, minChats: 2, maxChangesPerWeek: 2, maxSummaries: 60, staleDays: 120,
                   maxItems: { interest: 8, opinion: 6, preference: 6 } },
        cacheMs: 120_000,                                // how long the prompt reuses what it read about herself
    },
    typing: { msPerChar: 100, minMs: 0, maxMs: 5000, readMinMs: 200, readMaxMs: 600, gapMinMs: 350, gapMaxMs: 900 },   // 10 characters = 1 second of typing, +-25%, from instant up to 5 s
};

export function withDefaults(over = {}) {
    return {
        ...DEFAULTS, ...over,
        quoteChance: { ...DEFAULTS.quoteChance, ...(over.quoteChance || {}) },
        sticker: { ...DEFAULTS.sticker, ...(over.sticker || {}) },
        batch: { ...DEFAULTS.batch, ...(over.batch || {}) },
        typing: { ...DEFAULTS.typing, ...(over.typing || {}) },
        self: {
            ...DEFAULTS.self, ...(over.self || {}),
            feedback: { ...DEFAULTS.self.feedback, ...((over.self || {}).feedback || {}) },
            reflect: { ...DEFAULTS.self.reflect, ...((over.self || {}).reflect || {}), maxItems: { ...DEFAULTS.self.reflect.maxItems, ...(((over.self || {}).reflect || {}).maxItems || {}) } },
        },
        maint: { ...DEFAULTS.maint, ...(over.maint || {}), limits: { ...DEFAULTS.maint.limits, ...((over.maint || {}).limits || {}) } },
    };
}
