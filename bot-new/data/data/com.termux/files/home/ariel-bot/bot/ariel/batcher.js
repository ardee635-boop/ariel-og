// "Wait for the chat to go quiet": one timer per chat that each new message pushes back,
// but never past a hard cap measured from the first message of the batch.
export function createBatcher({ now = Date.now, setT = setTimeout, clearT = clearTimeout } = {}) {
    const slots = new Map();   // key -> { first, timer }

    function touch(key, waitMs, capMs, fire) {
        const t = now();
        let s = slots.get(key);
        if (!s) { s = { first: t, timer: null }; slots.set(key, s); }
        clearT(s.timer);
        const due = Math.min(t + waitMs, s.first + capMs);
        s.timer = setT(() => { slots.delete(key); fire(); }, Math.max(0, due - t));
    }
    const has = (key) => slots.has(key);
    function cancel(key) {
        const s = slots.get(key);
        if (s) { clearT(s.timer); slots.delete(key); }
    }
    return { touch, has, cancel };
}
