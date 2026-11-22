// lib/msgid.js — message-ID tooling for the card auto-claim.
// Baileys stamps its own messages with a recognisable ID (3EB0... / BAE5...).
// This module (1) logs the IDs your real phone produces so we can compare,
// and (2) can generate phone-shaped IDs for Ariel's sends (.scard id phone).
import { randomBytes } from 'crypto';

const st = { mode: 'default', log: false, sampleLen: 32, samples: [], ours: new Set() };
const LIB_STYLE = /^(3EB0|BAE5)/i;

export const isLibStyle = (id) => LIB_STYLE.test(id || '');

export function setIdMode(m) { st.mode = m === 'phone' ? 'phone' : 'default'; }
export function setIdLog(on) { st.log = !!on; }
export function idInfo() {
    return { mode: st.mode, log: st.log, sampleLen: st.sampleLen, samples: st.samples.slice(-3) };
}

// Remember an ID we sent ourselves, so it is never mistaken for a phone ID.
export function noteOurs(id) {
    if (!id) return;
    st.ours.add(id);
    if (st.ours.size > 300) st.ours.delete(st.ours.values().next().value);
    if (st.log) console.log(`[MSGID] ARIEL sent id=${id} len=${id.length} libStyle=${isLibStyle(id)}`);
}

// Call for every upsert message (any type). Logs your own phone's IDs.
export function observe(msg, type) {
    try {
        const id = msg?.key?.id;
        if (!id || !msg.key.fromMe) return;
        // WhatsApp echoes our own sends back; the echo carries the ID that was really on the wire.
        if (st.ours.has(id)) {
            if (st.log) console.log(`[MSGID] CONFIRMED on wire id=${id} len=${id.length} libStyle=${isLibStyle(id)}`);
            return;
        }
        if (isLibStyle(id)) {                             // not a phone message
            if (st.log) console.log(`[MSGID] WARNING own message went out with library-style id=${id} (not one we generated)`);
            return;
        }
        st.sampleLen = id.length;
        st.samples.push(id); if (st.samples.length > 10) st.samples.shift();
        if (st.log) console.log(`[MSGID] PHONE sent id=${id} len=${id.length} upsert=${type}`);
    } catch {}
}

// A phone-shaped ID (uppercase hex, same length as the last real one seen),
// or undefined when mode is 'default' (Baileys picks its own).
export function nextId() {
    if (st.mode !== 'phone') return undefined;
    return phoneId();
}

// Always returns a phone-shaped ID, whatever the mode is. Used for claims.
export function phoneId() {
    const len = st.sampleLen || 32;
    let id;
    do { id = randomBytes(Math.ceil(len / 2)).toString('hex').toUpperCase().slice(0, len); }
    while (isLibStyle(id));
    return id;
}
