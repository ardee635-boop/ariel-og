const http = require('http');
const url  = require('url');

const PORT = process.env.PORT || 3000;

http.createServer((req, res) => {
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
