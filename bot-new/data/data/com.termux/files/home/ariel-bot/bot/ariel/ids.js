// WhatsApp id helpers (pure, no imports).
//
// One person can show up as a phone JID (2348...@s.whatsapp.net), a LID
// (123...@lid), or a bare phone number. We keep all of them in
// ariel.person_identities with three kinds:
//   jid   -> '2348...@s.whatsapp.net'   (device suffix removed)
//   lid   -> '123...@lid'               (device suffix removed)
//   phone -> '2348...'                  (digits only, 7-15 long)

const PHONE_RE = /^\d{7,15}$/;

// '2348...:12@s.whatsapp.net' -> '2348...@s.whatsapp.net'. Returns null for junk.
export function normJid(raw) {
    if (typeof raw !== 'string') return null;
    const s = raw.trim();
    const at = s.lastIndexOf('@');
    if (at <= 0) return null;
    const user = s.slice(0, at).split(':')[0];
    const server = s.slice(at + 1).toLowerCase();
    if (!user || !server) return null;
    return `${user}@${server}`;
}

export function isGroupJid(jid) { return typeof jid === 'string' && jid.endsWith('@g.us'); }
export function isLid(jid) { return typeof jid === 'string' && jid.endsWith('@lid'); }
export function isPhoneJid(jid) { return typeof jid === 'string' && jid.endsWith('@s.whatsapp.net'); }

export function phoneOf(jid) {
    const n = normJid(jid);
    if (!n || !isPhoneJid(n)) return null;
    const digits = n.split('@')[0];
    return PHONE_RE.test(digits) ? digits : null;
}

// One raw id -> the identity rows it implies ([] for groups, broadcast lists, junk).
export function identitiesOf(raw) {
    const n = normJid(raw);
    if (!n) return [];
    if (isLid(n)) return [{ kind: 'lid', value: n }];
    if (isPhoneJid(n)) {
        const out = [{ kind: 'jid', value: n }];
        const p = phoneOf(n);
        if (p) out.push({ kind: 'phone', value: p });
        return out;
    }
    return [];
}

// Many raw ids (all from ONE sender in ONE event) -> a deduped identity set.
// Guard against bad data gluing two people together: one event may carry at most
// one phone number and one lid. The first of each (primary ids come first) wins;
// anything that disagrees is dropped and reported in `dropped`.
export function buildIdentitySet(rawIds) {
    const seen = new Set();
    const out = [];
    const dropped = [];
    let phone = null;
    let lid = null;
    for (const raw of rawIds || []) {
        const ids = identitiesOf(raw);
        if (!ids.length) continue;
        const p = ids.find((i) => i.kind === 'phone')?.value ?? null;
        const l = ids.find((i) => i.kind === 'lid')?.value ?? null;
        if (p) {
            if (phone && phone !== p) { dropped.push(normJid(raw)); continue; }
            phone = p;
        }
        if (l) {
            if (lid && lid !== l) { dropped.push(normJid(raw)); continue; }
            lid = l;
        }
        for (const i of ids) {
            if (seen.has(i.value)) continue;
            seen.add(i.value);
            out.push(i);
        }
    }
    return { identities: out, dropped };
}

// A chat's own key. Groups use their JID. A DM belongs to a PERSON, not to
// whichever id the message arrived on, so a person who shows up as both a phone
// JID and a @lid still has exactly one DM chat.
export const dmChatKey = (personId) => `dm:${personId}`;
