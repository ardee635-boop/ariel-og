// chat/stickers.js  (split out of index.js)
import { err, log } from '../lib/log.js';
import { stats } from '../lib/cache.js';

// Ariel's expression stickers — dynamic, built entirely via the
// .take command (reply to any sticker with ".take <tag> [description]").
// Each tag holds one or more numbered .webp variants — stored as
// objects ariel/<tag>/1.webp, 2.webp, etc in the public Supabase
// Storage bucket "ariel-stickers" — so a tag like "blush" can hold
// several different images; when she uses that tag, one variant is
// picked at random. ariel/manifest.json (also in the bucket) maps
// tag -> description, since ariel.py needs to know what each tag
// means (an arbitrary tag name alone doesn't tell the model when to
// use it). No pre-made stickers or hardcoded tag list — whatever's
// been .take'n so far IS her vocabulary, empty until you start saving.
//
// Storage lives in Supabase, NOT on local disk — Render's filesystem
// is rebuilt from the git image on every redeploy, so anything
// written to disk at runtime (this used to be plain files under
// stickers/ariel/) was wiped on every deploy. The bucket is public,
// so reads go straight to the public URL (no auth needed); writes
// (upload/delete) go through the Storage REST API with the service
// role key, since public-read buckets still require auth to mutate.
const SUPABASE_URL = process.env.SUPABASE_URL;

const SUPABASE_SERVICE_ROLE_KEY = process.env.SUPABASE_SERVICE_ROLE_KEY;

const ARIEL_STICKERS_BUCKET = 'ariel-stickers';

export const ARIEL_STICKERS_PREFIX = 'ariel';

 // objects live under ariel/<tag>/<n>.webp
const ARIEL_MANIFEST_OBJECT = `${ARIEL_STICKERS_PREFIX}/manifest.json`;

// Every sticker .take'n is stamped with this as its WhatsApp pack
// name, so if someone saves one from a chat, WhatsApp visually groups
// it under this pack — a bonus side effect of using wa-sticker-formatter
// for metadata, not something the bot can read back later.
export const ARIEL_STICKER_PACK_NAME = 'Ariel';

// Reserved fallback tag — always exists at position 1 in .arielstickers
// even with zero images saved under it, survives .resetstickers, and
// can't be deleted via .delpack. Used when the picker (ariel.py) can't
// confidently match any real tag to the reply. Still .take-able like
// any other tag (reply to a sticker with ".take ariel") to actually
// populate it with images — it's exempt from the normal "must have at
// least one image to exist" rule, not from being tagged onto at all.
export const ARIEL_FALLBACK_TAG = 'ariel';

if (!SUPABASE_URL || !SUPABASE_SERVICE_ROLE_KEY) {
    err('🎨', '[sticker] SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY not set — sticker storage will fail.');
}

function _stickerPublicUrl(objectPath) {
    return `${SUPABASE_URL}/storage/v1/object/public/${ARIEL_STICKERS_BUCKET}/${objectPath}`;
}

// Upload (create-or-overwrite) an object in the bucket. Used for both
// manifest.json and .webp variants — same endpoint, different content type.
export async function _stickerUpload(objectPath, buffer, contentType) {
    const res = await fetch(
        `${SUPABASE_URL}/storage/v1/object/${ARIEL_STICKERS_BUCKET}/${objectPath}`,
        {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${SUPABASE_SERVICE_ROLE_KEY}`,
                'apikey': SUPABASE_SERVICE_ROLE_KEY,
                'Content-Type': contentType,
                'x-upsert': 'true',
            },
            body: buffer,
        }
    );
    if (!res.ok) {
        const body = await res.text().catch(() => '');
        throw new Error(`upload ${objectPath} failed: ${res.status} ${body}`);
    }
}

export async function _stickerDelete(objectPaths) {
    // Storage's bulk-delete endpoint takes an array of object paths (prefixes
    // don't work here — every path, e.g. every variant file, must be listed).
    const res = await fetch(
        `${SUPABASE_URL}/storage/v1/object/${ARIEL_STICKERS_BUCKET}`,
        {
            method: 'DELETE',
            headers: {
                'Authorization': `Bearer ${SUPABASE_SERVICE_ROLE_KEY}`,
                'apikey': SUPABASE_SERVICE_ROLE_KEY,
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ prefixes: objectPaths }),
        }
    );
    if (!res.ok) {
        const body = await res.text().catch(() => '');
        throw new Error(`delete failed: ${res.status} ${body}`);
    }
}

// Lists object names directly under a "folder" prefix in the bucket
// (Storage has no real directories — this uses the list endpoint with
// prefix + delimiter semantics). Returns [] on any failure or empty folder.
async function _stickerListFolder(prefix) {
    const res = await fetch(
        `${SUPABASE_URL}/storage/v1/object/list/${ARIEL_STICKERS_BUCKET}`,
        {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${SUPABASE_SERVICE_ROLE_KEY}`,
                'apikey': SUPABASE_SERVICE_ROLE_KEY,
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ prefix, limit: 1000 }),
        }
    );
    if (!res.ok) return [];
    const items = await res.json().catch(() => []);
    // The list endpoint returns folder placeholder entries too in some
    // setups; filter to real objects (they have an "id"/"metadata" field).
    return Array.isArray(items) ? items.filter(i => i && i.name).map(i => i.name) : [];
}

export async function _loadArielManifest() {
    try {
        const res = await fetch(_stickerPublicUrl(ARIEL_MANIFEST_OBJECT));
        if (res.status === 404 || res.status === 400) {
            log('🎨', `[sticker] manifest not found in bucket — treating as empty`);
            return {};
        }
        if (!res.ok) {
            err('🎨', `[sticker] manifest fetch failed: ${res.status}`);
            return {};
        }
        const data = await res.json();
        log('🎨', `[sticker] manifest loaded: ${Object.keys(data).length} tag(s) -> ${Object.keys(data).join(', ') || '(none)'}`);
        return data;
    } catch (e) {
        err('🎨', `[sticker] manifest read/parse failed: ${e.message}`);
        return {};
    }
}

export async function _saveArielManifest(manifest) {
    try {
        const buf = Buffer.from(JSON.stringify(manifest, null, 2), 'utf8');
        await _stickerUpload(ARIEL_MANIFEST_OBJECT, buf, 'application/json');
        log('🎨', `[sticker] manifest saved: ${Object.keys(manifest).length} tag(s)`);
    } catch (e) {
        err('🎨', `[sticker] manifest save FAILED: ${e.message}`);
        throw e; // don't let the caller believe the save succeeded
    }
}

// Lists the numbered variant files already saved under a tag
// (ariel/<tag>/1.webp, 2.webp, ...), sorted numerically. [] if the
// tag has no objects yet.
export async function _listStickerVariants(tag) {
    const names = await _stickerListFolder(`${ARIEL_STICKERS_PREFIX}/${tag}`);
    return names
        .filter(f => /^\d+\.webp$/.test(f))
        .sort((a, b) => parseInt(a) - parseInt(b));
}

// Returns every object path under ariel/<tag>/ (full paths, ready to
// pass to _stickerDelete). Storage's list endpoint isn't recursive, but
// each tag is a flat folder of just numbered .webp files, so one
// non-recursive list per tag is enough — no nested folders to walk.
export async function _listStickerObjectPaths(tag) {
    const variants = await _listStickerVariants(tag);
    return variants.map(v => `${ARIEL_STICKERS_PREFIX}/${tag}/${v}`);
}

// Shared sticker-send logic — the single place that turns a tag name
// (as returned by ariel.py's _pick_sticker(), via callPython's
// "sticker" field) into an actual sticker sent to WhatsApp. Every
// callPython call site that wants Ariel to send a sticker should call
// this with its result, instead of re-implementing the fetch/send
// itself — that duplication is exactly how the silentchat group path
// used to drop stickers silently while the DM path worked fine.
// quotedMsg is optional: pass the original msg to quote-reply, or
// omit/pass null for a bare send (e.g. the silent/disguised paths that
// don't quote anything).
export async function _sendArielSticker(sock, chatJid, sticker, quotedMsg = null) {
    log('🎨', `[sticker] attempting send: sticker=${JSON.stringify(sticker)}`);
    if (!sticker) return;
    const safeTag = String(sticker).toLowerCase().replace(/[^a-z0-9_]/g, '');
    const variants = safeTag ? await _listStickerVariants(safeTag) : [];
    log('🎨', `[sticker] tag="${safeTag}" has ${variants.length} variant(s)`);
    if (!variants.length) {
        // The reserved fallback tag is allowed to have zero images
        // (e.g. nothing uploaded yet) — that's an expected state, not
        // an error, so skip quietly instead of logging via err().
        if (safeTag === ARIEL_FALLBACK_TAG) {
            log('🎨', `[sticker] fallback tag "${ARIEL_FALLBACK_TAG}" has no images yet — skipping send`);
        } else {
            err('🎨', `[sticker] tag "${safeTag}" chosen but no variant objects exist in bucket`);
        }
        return;
    }
    const pick = variants[Math.floor(Math.random() * variants.length)];
    const objectPath = `${ARIEL_STICKERS_PREFIX}/${safeTag}/${pick}`;
    try {
        const res = await fetch(_stickerPublicUrl(objectPath));
        if (!res.ok) throw new Error(`fetch ${objectPath} -> ${res.status}`);
        const stickerBuf = Buffer.from(await res.arrayBuffer());
        const sendOpts = quotedMsg ? { quoted: quotedMsg } : {};
        const sentMsg = await sock.sendMessage(chatJid, { sticker: stickerBuf }, sendOpts);
        stats.msgsSent++;
        log('🎨', `[sticker] sent ${objectPath}`);
        return sentMsg || true;
    } catch (e) {
        err('🎨', `[sticker] send failed (tag=${safeTag}, path=${objectPath}): ${e.message}`);
    }
}

