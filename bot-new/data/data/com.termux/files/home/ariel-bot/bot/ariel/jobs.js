// Background work. Everything goes through the jobs table, so a restart loses nothing.
// A failed job retries with growing delays up to maxAttempts, then becomes "dead" (shown by `.ariel jobs`).
// Jobs are written to be safe to run twice.

const lagosParts = (d, tz) => {
    const p = new Intl.DateTimeFormat('en-CA', { timeZone: tz, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', hourCycle: 'h23' })
        .formatToParts(d).reduce((a, x) => ((a[x.type] = x.value), a), {});
    const weekday = new Intl.DateTimeFormat('en-US', { timeZone: tz, weekday: 'short' }).format(d);
    return { day: `${p.year}-${p.month}-${p.day}`, hour: Number(p.hour), weekday };
};

export function createJobs({ maint, handlers, cfg, log = () => {}, now = Date.now, tz = 'Africa/Lagos' }) {
    const M = cfg.maint;
    const counters = { done: 0, retried: 0, dead: 0 };
    const status = { lastError: null, running: false };
    let stopped = true;
    let timers = [];

    const enqueue = (kind, payload, opts = {}) => maint.enqueue({ kind, payload, runAt: opts.runAt || null, key: opts.key || null });

    async function runOne() {
        const job = await maint.claimJob();
        if (!job) return false;
        const h = handlers[job.kind];
        if (!h) {
            counters.dead++;
            await maint.failJob(job.id, { error: `no handler for "${job.kind}"`, dead: true });
            return true;
        }
        try {
            await Promise.race([
                h({ payload: job.payload || {}, enqueue, job }),
                new Promise((_, rej) => setTimeout(() => rej(new Error('job timed out')), M.jobTimeoutMs).unref?.()),
            ]);
            await maint.finishJob(job.id);
            counters.done++;
        } catch (e) {
            const msg = String(e?.message || e).slice(0, 400);
            status.lastError = `${job.kind}: ${msg}`;
            if (job.attempts >= M.maxAttempts) {
                counters.dead++;
                await maint.failJob(job.id, { error: msg, dead: true });
                log(`[ARIEL] job ${job.id} (${job.kind}) is dead after ${job.attempts} attempts: ${msg}`);
            } else {
                counters.retried++;
                const delay = Math.min(3600, 30 * 2 ** (job.attempts - 1)) * 1000;
                await maint.failJob(job.id, { error: msg, dead: false, retryAt: new Date(now() + delay) });
                log(`[ARIEL] job ${job.id} (${job.kind}) failed, retry in ${Math.round(delay / 1000)}s: ${msg}`);
            }
        }
        return true;
    }

    async function loop() {
        status.running = true;
        let lastRecover = 0;
        while (!stopped) {
            try {
                if (now() - lastRecover > 60_000) {
                    lastRecover = now();
                    const n = await maint.recoverStuck();
                    if (n) log(`[ARIEL] ${n} stuck job(s) put back in the queue`);
                }
                const worked = await runOne();
                if (!worked) await new Promise((r) => setTimeout(r, M.pollMs));
            } catch (e) {
                status.lastError = `queue: ${String(e?.message || e).slice(0, 200)}`;
                await new Promise((r) => setTimeout(r, 10_000));      // database hiccup: wait, don't spin
            }
        }
        status.running = false;
    }

    // Every 5 minutes: look for closed segments. Nightly (after 03:00 Lagos, once per day): consolidate, then cleanup.
    let tickN = 0;
    async function tick() {
        try {
            await enqueue('segment_close', {}, { key: 'tick' });
            if (++tickN % 3 === 0) await enqueue('initiative_tick', {}, { key: 'tick' });      // every 15 minutes
            const { day, hour, weekday } = lagosParts(new Date(now()), tz);
            if (hour >= 3 && !(await maint.hasKey('consolidate', `night:${day}`))) {
                await enqueue('consolidate', { day }, { key: `night:${day}` });
            }
            // Stage 8 (only when the handlers are wired): daily feedback review, weekly reflection on Sunday.
            if (handlers.style_review && hour >= 4 && !(await maint.hasKey('style_review', `day:${day}`))) {
                await enqueue('style_review', { day }, { key: `day:${day}` });
            }
            if (handlers.reflect && weekday === 'Sun' && hour >= 4 && !(await maint.hasKey('reflect', `week:${day}`))) {
                await enqueue('reflect', { day }, { key: `week:${day}` });
            }
        } catch (e) { log(`[ARIEL] scheduler: ${String(e?.message || e).slice(0, 160)}`); }
    }

    function start() {
        if (!stopped) return;
        stopped = false;
        loop();
        const t1 = setInterval(tick, 5 * 60_000);
        t1.unref?.();
        const t0 = setTimeout(tick, 20_000);
        t0.unref?.();
        timers = [t0, t1];
    }
    function stop() { stopped = true; timers.forEach((t) => { clearInterval(t); clearTimeout(t); }); timers = []; }

    return { start, stop, enqueue, runOne, tick, counters, status };
}
