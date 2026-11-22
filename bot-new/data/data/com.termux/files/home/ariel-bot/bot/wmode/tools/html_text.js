// bot/wmode/tools/html_text.js — readable text out of an HTML page, no dependencies. Good enough to read, not a browser.
const ENT = { amp: '&', lt: '<', gt: '>', quot: '"', apos: "'", nbsp: ' ', mdash: '—', ndash: '–', hellip: '…', copy: '©', rsquo: '’', lsquo: '‘', rdquo: '”', ldquo: '“', laquo: '«', raquo: '»', middot: '·', bull: '•' };
const decodeEntities = (s) => s.replace(/&(#x[0-9a-f]+|#\d+|[a-z]+);/gi, (m, e) => {
    if (e[0] === '#') { const n = e[1].toLowerCase() === 'x' ? parseInt(e.slice(2), 16) : parseInt(e.slice(1), 10); return n > 0 && n < 0x110000 ? String.fromCodePoint(n) : ''; }
    return ENT[e.toLowerCase()] ?? m;
});

export function htmlToText(html, { baseUrl = null, wantLinks = false, maxLinks = 12 } = {}) {
    let h = String(html || '');
    const title = decodeEntities((/<title[^>]*>([\s\S]*?)<\/title>/i.exec(h)?.[1] || '').replace(/\s+/g, ' ').trim());
    h = h.replace(/<!--[\s\S]*?-->/g, '').replace(/<(script|style|noscript|svg|template|iframe|head)\b[\s\S]*?<\/\1>/gi, '');
    const main = /<(main|article)\b[^>]*>([\s\S]*?)<\/\1>/i.exec(h);
    if (main && main[2].length > 400) h = main[2];
    else h = h.replace(/<(nav|footer|aside|form)\b[\s\S]*?<\/\1>/gi, '');
    const links = [];
    if (wantLinks) {
        for (const m of h.matchAll(/<a\b[^>]*\bhref=["']([^"'#][^"']*)["'][^>]*>([\s\S]*?)<\/a>/gi)) {
            if (links.length >= maxLinks) break;
            let href; try { href = new URL(decodeEntities(m[1]), baseUrl || undefined).toString(); } catch { continue; }
            const text = decodeEntities(m[2].replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim());
            if (/^https?:/.test(href) && text) links.push({ text: text.slice(0, 80), href });
        }
    }
    h = h.replace(/<li\b[^>]*>/gi, '\n- ').replace(/<\/(p|div|section|h[1-6]|tr|ul|ol|table|blockquote|pre|header|figure)>|<br\s*\/?>/gi, '\n').replace(/<\/t[dh]>/gi, ' | ').replace(/<[^>]+>/g, '');
    const text = decodeEntities(h).split('\n').map((l) => l.replace(/[ \t\u00a0]+/g, ' ').trim()).join('\n').replace(/\n{3,}/g, '\n\n').trim();
    return { title, text, links };
}
