// bot/lib/afk.js - pure helpers for `.afk` / `.afknote` (no WhatsApp / DB code, so they can be unit-tested).

/** Said right after `.afk`. No LLM: this pool is the goodbye. */
export const GOODBYES = [
    'See you later!',
    'Go on, we will hold the fort.',
    'Bye for now, come back soon.',
    'Enjoy your break.',
    'Catch you later.',
    'Alright, we will miss you. A little.',
    'Do not be gone too long.',
    'Off you go then.',
    'Take care, see you soon.',
    'Noted. Do not disappear on us.',
    'Go recharge, the group will survive.',
    'Say hi to the real world for us.',
];
export const FALLBACK_GOODBYES = GOODBYES;      // old name, kept so nothing importing it breaks

/** Said when an afk person talks again. {tag} = @them, {time} = how long they were gone. */
export const WELCOME_BACKS = [
    'Welcome back {tag}! You are no longer afk. (gone {time})',
    '{tag} is back! Afk mode off. (gone {time})',
    'Look who showed up. Welcome back {tag}, you are no longer afk. ({time})',
    'Ah, {tag} returns! No longer afk. (gone {time})',
    'Welcome back {tag}! We kept your seat warm. ({time})',
    '{tag} has re-entered the chat. You are no longer afk. ({time})',
    'You are back {tag}! Afk cleared. (gone {time})',
    'The wanderer returns. Welcome back {tag}, no longer afk. ({time})',
    'Welcome back {tag}! Hope the break was good. (gone {time})',
    '{tag} is no longer afk. Missed you! ({time})',
    'And we are whole again. Welcome back {tag}! (gone {time})',
    'Afk over for {tag}. Welcome back! ({time})',
];

export const numOf = (jid) => String(jid || '').split('@')[0].split(':')[0];
export const tag = (jid) => '@' + numOf(jid);

/** Max length of an afk reason / a note, so one message cannot flood the group. */
export const MAX_REASON = 120;
export const MAX_NOTE = 300;
export const MAX_NOTES = 10;                    // per afk person
export const cleanReason = (raw) => String(raw || '').replace(/\s+/g, ' ').trim().slice(0, MAX_REASON);
export const cleanNote = (raw) => String(raw || '').replace(/[ \t]+/g, ' ').trim().slice(0, MAX_NOTE);

export function announce(jid, reason) {
    return reason ? `${tag(jid)} is now afk: ${reason}` : `${tag(jid)} is now afk.`;
}

export function agoText(ms) {
    const s = Math.max(0, Math.floor(ms / 1000));
    if (s < 60) return 'just now';
    const m = Math.floor(s / 60);
    if (m < 60) return `${m}m`;
    const h = Math.floor(m / 60);
    if (h < 24) return `${h}h ${m % 60}m`;
    return `${Math.floor(h / 24)}d ${h % 24}h`;
}

/** What people see when they tag / reply to / hidetag an afk person:
 *    @user is afk
 *    Reason: xxx                                                          */
export const afkLine = (jid, a) => `${tag(jid)} is afk\nReason: ${a.reason || 'none'}`;
export const mentionNotice = afkLine;           // old name

export const pickFrom = (pool, rand = Math.random) => pool[Math.floor(rand() * pool.length)];
export const pickFallback = (rand = Math.random) => pickFrom(GOODBYES, rand);

export function backNotice(jid, a, now = Date.now(), rand = Math.random) {
    return pickFrom(WELCOME_BACKS, rand).replaceAll('{tag}', tag(jid)).replaceAll('{time}', agoText(now - a.since));
}

/** The notes left for someone, shown when they come back. */
export function notesText(jid, notes, now = Date.now()) {
    if (!notes?.length) return '';
    return `📨 Messages for ${tag(jid)}:\n` + notes.map(n => `• ${tag(n.from)}: ${n.text} (${agoText(now - n.at)} ago)`).join('\n');
}

/** Every number a person can be known by in a group (phone, LID, device-suffixed forms), from the jids we have for them. */
export function aliasesFor(jids, participants = []) {
    const out = new Set(jids.map(numOf).filter(Boolean));
    for (const p of participants || []) {
        const ids = [p.id, p.lid, p.phoneNumber].map(numOf).filter(Boolean);
        if (ids.some(n => out.has(n))) ids.forEach(n => out.add(n));
    }
    return [...out];
}

/** Everyone a message is aimed at: @mentions (also hidden ones), reply targets, and typed "@number"s.
 *  Looks inside whichever message type carries the contextInfo (text, image caption, video, sticker, ...). */
export function targetsOf(message, text = '') {
    const jids = [];
    for (const v of Object.values(message || {})) {
        const c = v && typeof v === 'object' ? v.contextInfo : null;
        if (!c) continue;
        for (const m of c.mentionedJid || []) jids.push(m);
        if (c.stanzaId && c.participant) jids.push(c.participant);
    }
    for (const m of String(text).matchAll(/@(\d{6,})/g)) jids.push(m[1]);
    return jids;
}

/** `.afknote @user the note` -> the note text with the @number removed (WhatsApp italics `_..._` around it are dropped too). */
export function parseNote(text) {
    const body = String(text || '').replace(/^\s*\.afknote\b/i, '').replace(/@\d{5,}/g, ' ');
    return cleanNote(body.replace(/^\s*_+([\s\S]*?)_+\s*$/, '$1'));
}

/** Commands whose whole point is to tag people. `.hidetag` / `.tagall` tag everyone, so they wake every afk member. */
export const TAG_EVERYONE_CMDS = new Set(['.tagall', '.hidetag']);
