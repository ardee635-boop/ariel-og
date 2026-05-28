const http = require('http');
const url  = require('url');

const PORT = process.env.PORT || 3000;

http.createServer((req, res) => {
    const timestamp = new Date().toISOString();
    const ua        = req.headers['user-agent'] || 'none';
    const referer   = req.headers['referer'] || 'none';
    const host      = req.headers['host'] || 'none';
    const ip        = req.socket.remoteAddress || 'none';

    console.log(`[REQUEST] ════════════════════════════`);
    console.log(`[REQUEST] time    : ${timestamp}`);
    console.log(`[REQUEST] method  : ${req.method}`);
    console.log(`[REQUEST] url     : ${req.url}`);
    console.log(`[REQUEST] ip      : ${ip}`);
    console.log(`[REQUEST] ua      : ${ua}`);
    console.log(`[REQUEST] referer : ${referer}`);
    console.log(`[REQUEST] host    : ${host}`);
    console.log(`[REQUEST] ════════════════════════════`);

    const { query } = url.parse(req.url, true);

    const title = query.title || 'Ariel';
    const sub   = query.sub   || '';
    const img   = query.img   || '';

    const html = `<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta property="og:title"       content="${escHtml(title)}">
    <meta property="og:description" content="${escHtml(sub)}">
    <meta property="og:image"       content="${escHtml(img)}">
    <meta property="og:url"         content="https://${req.headers.host}${req.url}">
    <meta property="og:type"        content="website">
    <title>${escHtml(title)}</title>
</head>
<body></body>
</html>`;

    console.log(`[RESPONSE] title="${title}" sub="${sub}" img="${img.slice(0, 60)}"`);
    res.writeHead(200, { 'Content-Type': 'text/html' });
    res.end(html);
}).listen(PORT, () => console.log(`OG server running on port ${PORT}`));

function escHtml(str) {
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/"/g, '&quot;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
}
