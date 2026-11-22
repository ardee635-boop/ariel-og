// Turns a raw Baileys message into the small, plain shape Ariel stores.
// Pure: no imports besides ids.js, no database, no socket.
import { normJid } from './ids.js';

const MAX_BODY = 4000;
const MAX_QUOTE = 200;

const WRAPPERS = ['ephemeralMessage', 'viewOnceMessage', 'viewOnceMessageV2',
    'viewOnceMessageV2Extension', 'documentWithCaptionMessage', 'editedMessage'];

// Message types that carry a contextInfo (reply / mentions).
const CONTEXT_HOLDERS = ['extendedTextMessage', 'imageMessage', 'videoMessage', 'audioMessage',
    'documentMessage', 'stickerMessage', 'locationMessage', 'contactMessage', 'pollCreationMessage',
    'pollCreationMessageV2', 'pollCreationMessageV3', 'ptvMessage'];

// Message types that are not conversation (receipts, key shares, reactions, ...).
const IGNORED = new Set(['reactionMessage', 'senderKeyDistributionMessage', 'messageContextInfo',
    'pollUpdateMessage', 'keepInChatMessage', 'encReactionMessage', 'groupInviteMessage',
    'call', 'bcallMessage', 'requestPhoneNumberMessage']);

export function clean(s, max = MAX_BODY) {
    let t = String(s ?? '');
    t = t.replace(/\u0000/g, '');                        // Postgres text cannot hold NUL
    if (typeof t.toWellFormed === 'function') t = t.toWellFormed();   // lone surrogates break inserts
    t = t.replace(/\r\n?/g, '\n').trim();
    return t.length > max ? t.slice(0, max) : t;
}

export function unwrap(message) {
    let m = message;
    for (let i = 0; i < 6 && m; i++) {
        let next = null;
        for (const k of WRAPPERS) {
            if (m[k]?.message) { next = m[k].message; break; }
        }
        if (!next) break;
        m = next;
    }
    return m || null;
}

// Real messages often carry extra objects next to the content (key shares, device info, ...) and their key order
// varies between WhatsApp/Baileys versions, so look for the content types first, in a fixed order.
const CONTENT_TYPES = ['extendedTextMessage', 'imageMessage', 'videoMessage', 'ptvMessage', 'audioMessage', 'stickerMessage',
    'documentMessage', 'locationMessage', 'liveLocationMessage', 'contactMessage', 'contactsArrayMessage',
    'pollCreationMessage', 'pollCreationMessageV2', 'pollCreationMessageV3'];

function typeOf(m) {
    if (!m) return null;
    if (typeof m.conversation === 'string') return 'conversation';
    for (const k of CONTENT_TYPES) if (m[k] && typeof m[k] === 'object') return k;
    for (const k of Object.keys(m)) {
        if (k === 'messageContextInfo' || k === 'conversation') continue;
        if (m[k] && typeof m[k] === 'object') return k;
    }
    return null;
}

// What this message "says" (caption or text) plus a kind label.
function describe(m) {
    const t = typeOf(m);
    if (t === 'conversation') return { kind: 'text', text: clean(m.conversation), caption: '' };
    if (!t) return null;
    const c = m[t];
    switch (t) {
        case 'extendedTextMessage': return { kind: 'text', text: clean(c.text), caption: '' };
        case 'imageMessage': return { kind: 'image', text: '', caption: clean(c.caption) };
        case 'videoMessage': return { kind: c.gifPlayback ? 'gif' : 'video', text: '', caption: clean(c.caption) };
        case 'ptvMessage': return { kind: 'video', text: '', caption: '' };
        case 'audioMessage': return { kind: c.ptt ? 'voice' : 'audio', text: '', caption: '' };
        case 'stickerMessage': return { kind: 'sticker', text: '', caption: '' };
        case 'documentMessage': return { kind: 'document', text: '', caption: clean(c.caption || c.fileName, 200) };
        case 'locationMessage': return { kind: 'location', text: '', caption: clean(c.name || c.address, 200) };
        case 'liveLocationMessage': return { kind: 'location', text: '', caption: clean(c.caption, 200) };
        case 'contactMessage': return { kind: 'contact', text: '', caption: clean(c.displayName, 100) };
        case 'contactsArrayMessage': return { kind: 'contact', text: '', caption: clean(c.displayName, 100) };
        case 'pollCreationMessage':
        case 'pollCreationMessageV2':
        case 'pollCreationMessageV3': return { kind: 'poll', text: '', caption: clean(c.name, 300) };
        default: return IGNORED.has(t) ? null : { kind: 'other', text: '', caption: '' };
    }
}

export function bodyFor(d) {
    if (!d) return '';
    if (d.kind === 'text') return d.text;
    if (d.kind === 'other') return '';
    return d.caption ? `[${d.kind}] ${d.caption}` : `[${d.kind}]`;
}

function contextOf(m) {
    const t = typeOf(m);
    if (!t || !CONTEXT_HOLDERS.includes(t)) return null;
    return m[t]?.contextInfo || null;
}

function quotedSnippet(quoted) {
    const q = unwrap(quoted);
    const d = describe(q);
    const b = bodyFor(d);
    return b ? clean(b, MAX_QUOTE) : '';
}

const PROTO_REVOKE = new Set([0, 'REVOKE']);
const PROTO_EDIT = new Set([14, 'MESSAGE_EDIT']);

/**
 * extractMessage(msg, { isBot })
 *   isBot(jid) -> boolean   tells whether a jid is Ariel herself.
 *
 * Returns one of:
 *   { skip: true, reason }
 *   { kind: 'message', waId, ts, body, replyTo, commandText, meta, mentionJids }
 *   { kind: 'edit',    waId, ts, targetId, body }
 *   { kind: 'revoke',  waId, ts, targetId }
 */
export function extractMessage(msg, { isBot = () => false } = {}) {
    if (!msg?.message) return { skip: true, reason: 'empty' };
    const waId = msg.key?.id || null;
    const rawTs = Number(msg.messageTimestamp?.low ?? msg.messageTimestamp);
    const ts = Number.isFinite(rawTs) && rawTs > 0 ? new Date(rawTs * 1000) : new Date();

    const m = unwrap(msg.message);
    if (!m) return { skip: true, reason: 'empty' };

    // Edits and "delete for everyone" arrive as protocol messages.
    if (m.protocolMessage) {
        const p = m.protocolMessage;
        const targetId = p.key?.id || null;
        if (PROTO_REVOKE.has(p.type) && targetId) return { kind: 'revoke', waId, ts, targetId };
        if (PROTO_EDIT.has(p.type) && targetId) {
            const body = bodyFor(describe(unwrap(p.editedMessage)));
            if (body) return { kind: 'edit', waId, ts, targetId, body };
        }
        return { skip: true, reason: 'protocol' };
    }

    const d = describe(m);
    if (!d) return { skip: true, reason: 'ignored-type' };
    const body = bodyFor(d);
    if (!body) return { skip: true, reason: 'no-body' };

    const ci = contextOf(m);
    const mentionJids = (ci?.mentionedJid || []).map(normJid).filter(Boolean);
    const quotedParticipant = ci?.participant ? normJid(ci.participant) : null;

    const meta = { type: d.kind };
    if (mentionJids.some((j) => isBot(j))) meta.mentioned_ariel = true;
    if (quotedParticipant && isBot(quotedParticipant)) meta.quoted_ariel = true;
    if (ci?.quotedMessage) {
        const snip = quotedSnippet(ci.quotedMessage);
        if (snip) meta.quoted_text = snip;
    }
    if (ci?.isForwarded) meta.forwarded = true;

    return {
        kind: 'message',
        waId,
        ts,
        body,
        replyTo: ci?.stanzaId || null,
        // The text a command would be typed in (not the "[image]" label).
        commandText: d.kind === 'text' ? d.text : d.caption,
        meta,
        mentionJids,
        quotedParticipant,
    };
}
