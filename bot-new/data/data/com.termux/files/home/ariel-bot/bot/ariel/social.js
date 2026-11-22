// Social picture: how well she knows each person, and how people in a chat relate to each other.
// Both grow slowly. Familiarity needs repeated interaction over several different days.
// A relationship label (friend / rival / teasing) needs at least 3 consistent signals.

const KINDS = ['friend', 'rival', 'teasing'];
const MIN_SIGNALS = 3;

export function familiarityOf({ days = 0, n = 0 }) {
    const f = 0.6 * (1 - Math.exp(-days / 6)) + 0.4 * (1 - Math.exp(-n / 50));
    return Math.round((days < 3 ? Math.min(f, 0.25) : f) * 1000) / 1000;      // one busy day is not familiarity
}

export function levelText(f) {
    if (f < 0.12) return 'you barely know them';
    if (f < 0.3) return "you've only talked a little";
    if (f < 0.6) return 'you know them fairly well';
    return 'you know them well';
}

// One new observation about a pair. Contradicting signals weaken the old label before replacing it.
export function applySignal(existing, signal) {
    if (!existing) return { kind: signal.kind, strength: 1, notes: signal.note || null };
    if (existing.kind === signal.kind) {
        return { kind: existing.kind, strength: Math.min(10, Number(existing.strength) + 1), notes: signal.note || existing.notes };
    }
    const left = Number(existing.strength) - 1;
    return left <= 0
        ? { kind: signal.kind, strength: 1, notes: signal.note || null }
        : { kind: existing.kind, strength: left, notes: existing.notes };
}

export function createSocial({ store, tz = 'Africa/Lagos', now = Date.now, log = () => {} }) {
    const counters = { interactions: 0, signals: 0, labelled: 0 };
    const day = () => new Intl.DateTimeFormat('en-CA', { timeZone: tz }).format(new Date(now()));

    // `count` = how many of their messages she answered this turn.
    async function recordInteraction(personId, count = 1) {
        const cur = (await store.getPersonStates([personId])).get(personId);
        const r = cur?.rapport || {};
        const days = Array.isArray(r.days) ? r.days : [];
        const today = day();
        if (days[days.length - 1] !== today) days.push(today);
        const rapport = { ...r, days: days.slice(-60), n: (Number(r.n) || 0) + count };
        await store.savePersonState({
            personId, rapport, lastInteraction: new Date(now()),
            familiarity: familiarityOf({ days: rapport.days.length, n: rapport.n }),
        });
        counters.interactions += count;
    }

    // signals: [{ a: personId, b: personId, kind, note }]
    async function addSignals(chatId, signals) {
        for (const s of signals) {
            if (!KINDS.includes(s.kind) || s.a == null || s.b == null || s.a === s.b) continue;
            const [lo, hi] = s.a < s.b ? [s.a, s.b] : [s.b, s.a];
            const cur = (await store.getRelationships(chatId, [lo, hi])).find((x) => x.person_a === lo && x.person_b === hi);
            const next = applySignal(cur, s);
            await store.upsertRelationship({ chatId, a: lo, b: hi, kind: next.kind, strength: next.strength, notes: next.notes ? String(next.notes).slice(0, 120) : null });
            counters.signals++;
            if (next.strength >= MIN_SIGNALS && (!cur || cur.kind !== next.kind || Number(cur.strength) < MIN_SIGNALS)) counters.labelled++;
        }
    }

    // For the prompt: per-person familiarity wording and the relationships that are established.
    async function describe({ chatId, personIds }) {
        const ids = [...new Set(personIds.filter((x) => x != null))];
        if (!ids.length) return { levels: new Map(), relations: [] };
        const states = await store.getPersonStates(ids);
        const levels = new Map(ids.map((id) => [id, levelText(Number(states.get(id)?.familiarity) || 0)]));
        const rel = (await store.getRelationships(chatId, ids)).filter((r) => Number(r.strength) >= MIN_SIGNALS);
        return { levels, relations: rel.map((r) => ({ a: r.person_a, b: r.person_b, kind: r.kind, notes: r.notes })) };
    }

    return { recordInteraction, addSignals, describe, counters };
}
