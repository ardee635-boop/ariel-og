// ============================================================
// NIFLHEIM-ONLINE — api/preview.js
//
// Vercel Serverless Function. Deployed automatically because it
// lives under /api — no separate service, no Next.js needed,
// coexists fine with the rest of the site being a plain Vite SPA.
//
// Purpose: give WhatsApp's link-preview crawler a URL with real,
// per-request Open Graph meta tags (og:title / og:description /
// og:image), so a message like ".shop" or ".quest" renders as an
// instant thumbnail card instead of a slow raw image attachment.
// This replaces the old standalone ariel-og.onrender.com service,
// which is no longer reachable — same param shape (title/sub/img)
// so the bot's sendThumbnail() only needs a URL change, not a
// rewrite.
//
// IMPORTANT: this must stay a plain HTML string response, not a
// React/client-rendered page — WhatsApp's crawler does not execute
// JavaScript, it only reads the raw HTML on the initial response.
// ============================================================

function escapeHtml(str) {
  return String(str || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

module.exports = (req, res) => {
  const { title = 'Ariel', sub = '', img = '' } = req.query || {};

  const safeTitle = escapeHtml(title);
  const safeSub   = escapeHtml(sub);
  const safeImg   = escapeHtml(img);

  // Description falls back to a generic line if no subtitle was passed,
  // since an empty og:description sometimes makes clients skip the card.
  const description = safeSub || 'Niflheim Online';

  const html = `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>${safeTitle}</title>
<meta property="og:title" content="${safeTitle}">
<meta property="og:description" content="${description}">
${safeImg ? `<meta property="og:image" content="${safeImg}">` : ''}
<meta property="og:type" content="website">
<meta name="twitter:card" content="summary_large_image">
<meta http-equiv="refresh" content="0; url=https://ariel-og.vercel.app/">
</head>
<body>
<p>Redirecting to <a href="https://ariel-og.vercel.app/">Niflheim Online</a>…</p>
</body>
</html>`;

  res.setHeader('Content-Type', 'text/html; charset=utf-8');
  // Short cache — previews are per-quest/per-item and change often,
  // but a little caching avoids hammering the function on repeat taps.
  res.setHeader('Cache-Control', 'public, max-age=60, s-maxage=300');
  res.status(200).send(html);
};
