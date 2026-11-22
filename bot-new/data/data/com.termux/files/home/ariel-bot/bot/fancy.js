// ============================================================
// fancy.js — Unicode fonts + hidetag sender for announcements
// Used by .ignoregc / .unignoregc and .crown / .dethrone.
// ============================================================

// Map A–Z / a–z onto a Unicode "math alphabet" block (other characters
// pass through unchanged, so numbers, punctuation and emoji stay intact).
function mapAlphabet(str, upperStart, lowerStart) {
    let out = '';
    for (const ch of String(str)) {
        const c = ch.codePointAt(0);
        if (c >= 65 && c <= 90)       out += String.fromCodePoint(upperStart + (c - 65));
        else if (c >= 97 && c <= 122) out += String.fromCodePoint(lowerStart + (c - 97));
        else                          out += ch;
    }
    return out;
}

// 𝕭𝖔𝖑𝖉 𝕱𝖗𝖆𝖐𝖙𝖚𝖗 — dark, gothic (exile, dethroning)
export const toFraktur = (s) => mapAlphabet(s, 0x1D56C, 0x1D586);

// 𝓑𝓸𝓵𝓭 𝓢𝓬𝓻𝓲𝓹𝓽 — graceful, royal (forgiveness, crowning)
export const toScript  = (s) => mapAlphabet(s, 0x1D4D0, 0x1D4EA);

// Send `text` to a group and silently notify EVERYONE (a "hidetag": all
// members are mentioned, but no @names clutter the message). Any "@number"
// written inside `text` still shows as a normal visible tag, because the
// number's JID is added to the mention list too.
// Throws if the send fails, so callers can fall back to a plain message.
export async function sendHidetag(sock, jid, text, participants = null) {
    let parts = participants;
    if (!parts?.length) parts = (await sock.groupMetadata(jid)).participants;
    const visible = [];
    const re = /@(\d{7,15})/g;
    let m;
    while ((m = re.exec(text)) !== null) visible.push(`${m[1]}@s.whatsapp.net`);
    const mentions = [...new Set([...parts.map(p => p.id), ...visible])];
    return sock.sendMessage(jid, { text, mentions });
}
