// ESM resolve hook: no node_modules and no network are needed to run the golden tests.
// Third-party packages -> tiny deterministic stubs; the Python bridge and the network-bound media
// helpers -> stubs too. Everything else (all of the bot's own logic) is the real code.
const STUBS = new URL('./stubs/', import.meta.url);
const PACKAGES = {
    '@whiskeysockets/baileys': 'baileys.mjs', 'sharp': 'sharp.mjs', 'jsonwebtoken': 'jsonwebtoken.mjs',
    'yt-search': 'yt-search.mjs', 'pg': 'pg.mjs', 'express': 'express.mjs', 'cookie-parser': 'cookie-parser.mjs',
    'argon2': 'argon2.mjs', 'wa-sticker-formatter': 'wa-sticker-formatter.mjs', 'qrcode-terminal': 'qrcode-terminal.mjs',
    'pino': 'pino.mjs',
};
// repo files replaced by stubs (matched on the resolved URL's tail)
const OVERRIDES = [['/bot/bridge.js', 'bridge.mjs'], ['/bot/media.js', 'media.mjs']];

export async function resolve(specifier, context, nextResolve) {
    if (PACKAGES[specifier]) return { url: new URL(PACKAGES[specifier], STUBS).href, shortCircuit: true };
    const r = await nextResolve(specifier, context);
    for (const [tail, stub] of OVERRIDES)
        if (r.url.endsWith(tail)) return { url: new URL(stub, STUBS).href, shortCircuit: true };
    return r;
}
