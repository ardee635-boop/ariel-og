// web/pokemon.js  (split out of index.js)
import { app } from './app.js';
import { _siteAuth } from './auth.js';
import { _getDB } from '../lib/db.js';
import { err } from '../lib/log.js';
import { callPythonAction } from '../bridge.js';
import { _isRateLimited, _rateLimitHits } from '../lib/ratelimit.js';

app.get('/api/player/me', async (req, res) => {
    const auth = await _siteAuth(req);
    if (!auth) return res.status(401).json({ error: 'Not logged in.' });

    try {
        const db = await _getDB();
        const result = await db.query('SELECT data FROM players WHERE sender = $1', [auth.sender]);
        if (result.rows.length === 0) {
            // Account exists (site login worked) but no in-game Player row yet —
            // they haven't registered via WhatsApp. Not an error, just empty state.
            return res.status(200).json({ registered: false });
        }

        const data = result.rows[0].data; // TEXT column — always a raw JSON string
        const player = JSON.parse(data);

        // "You have gained the quest..." toast — fires once for whichever
        // story quest is newest and hasn't been acknowledged yet. Covers
        // both fresh registrations (greenwood_1 granted at signup) and
        // already-registered players who simply haven't seen the prompt
        // on the site before. seen_quest_notices lives in story_flags so
        // WhatsApp and the site share the same "have they seen this" state.
        const flags = player.story_flags || {};
        const seenNotices = flags.seen_quest_notices || [];
        const storyQuests = (player.quests || []).filter(q => (q.source || 'board') !== 'board');
        const unseenStory = storyQuests.find(q => !seenNotices.includes(q.id));
        const questNotice = unseenStory ? { id: unseenStory.id, title: unseenStory.title } : null;

        res.status(200).json({
            registered: true,
            quest_notice: questNotice,
            stats: {
                name: player.name,
                level: player.level,
                coins: player.coins,
                region: player.zone,
                pvp_wins: player.pvp_wins,
                pvp_losses: player.pvp_losses,
                badges_count: (player.badges || []).length,
                pokedex_caught: (player.pokedex_caught || []).length,
                bio: player.bio,
                rank: null,   // placeholder — no ranking system yet
                guild: null,  // placeholder — no guild system yet
            },
            party: player.party || [],
            pc: player.box || [],
            inventory: player.inventory || {},
            badges: player.badges || [],
        });
    } catch (e) {
        err('🌐', `player/me error: ${e.message}`);
        res.status(500).json({ error: 'Something went wrong loading player data.' });
    }
});

app.post('/api/player/ack-quest-notice', async (req, res) => {
    const auth = await _siteAuth(req);
    if (!auth) return res.status(401).json({ error: 'Not logged in.' });

    const { quest_id } = req.body || {};
    if (!quest_id) return res.status(400).json({ error: '"quest_id" is required.' });

    try {
        const db = await _getDB();
        const result = await db.query('SELECT data FROM players WHERE sender = $1', [auth.sender]);
        if (result.rows.length === 0) return res.status(404).json({ error: 'No player record found.' });

        const player = JSON.parse(result.rows[0].data);
        player.story_flags = player.story_flags || {};
        const seen = player.story_flags.seen_quest_notices || [];
        if (!seen.includes(quest_id)) seen.push(quest_id);
        player.story_flags.seen_quest_notices = seen;

        await db.query('UPDATE players SET data = $1 WHERE sender = $2', [JSON.stringify(player), auth.sender]);
        res.status(200).json({ ok: true });
    } catch (e) {
        err('🌐', `player/ack-quest-notice error: ${e.message}`);
        res.status(500).json({ error: 'Something went wrong.' });
    }
});

// Tracks whether a player has ever tapped into a given story quest's
// tips before, so the site can pop the standalone tips panel exactly
// once per quest and fall back to the inline tips line on every later
// visit. Mirrors ack-quest-notice's story_flags pattern above.
app.post('/api/quests/tips-seen', async (req, res) => {
    const auth = await _siteAuth(req);
    if (!auth) return res.status(401).json({ error: 'Not logged in.' });

    const { quest_id } = req.body || {};
    if (!quest_id) return res.status(400).json({ error: '"quest_id" is required.' });

    try {
        const db = await _getDB();
        const result = await db.query('SELECT data FROM players WHERE sender = $1', [auth.sender]);
        if (result.rows.length === 0) return res.status(404).json({ error: 'No player record found.' });

        const player = JSON.parse(result.rows[0].data);
        player.story_flags = player.story_flags || {};
        const seenTips = player.story_flags.seen_quest_tips || [];
        const firstView = !seenTips.includes(quest_id);
        if (firstView) {
            seenTips.push(quest_id);
            player.story_flags.seen_quest_tips = seenTips;
            await db.query('UPDATE players SET data = $1 WHERE sender = $2', [JSON.stringify(player), auth.sender]);
        }

        res.status(200).json({ ok: true, first_view: firstView });
    } catch (e) {
        err('🌐', `quests/tips-seen error: ${e.message}`);
        res.status(500).json({ error: 'Something went wrong.' });
    }
});

app.post('/api/player/swap', async (req, res) => {
    const auth = await _siteAuth(req);
    if (!auth) return res.status(401).json({ error: 'Not logged in.' });

    const { from, to } = req.body || {};
    if (!from || !to) {
        return res.status(400).json({ error: '"from" and "to" slots are required.' });
    }

    try {
        const result = await callPythonAction(auth.sender, 'swap', { from, to });
        if (result?.site_result?.error) {
            return res.status(400).json({ error: result.site_result.error });
        }
        if (result?.error) {
            return res.status(503).json({ error: result.error });
        }
        res.status(200).json(result.site_result);
    } catch (e) {
        err('🌐', `player/swap error: ${e.message}`);
        res.status(500).json({ error: 'Something went wrong performing the swap.' });
    }
});

// Static Oak Town mart catalog — base ("ps") prices, same as standing in the
// actual mart on WhatsApp. Site has no zone context, so no multipliers here.
const OAK_TOWN_SHOP = [
    { name: 'Potion',              price: 50,   category: 'heal' },
    { name: 'Super Potion',        price: 75,   category: 'heal' },
    { name: 'Breadcrumbs',         price: 50,   category: 'field' },
    { name: 'Ice Heal',            price: 100,  category: 'status' },
    { name: 'Paralyze Heal',       price: 100,  category: 'status' },
    { name: 'Antidote',            price: 150,  category: 'status' },
    { name: 'Poké Ball',           price: 200,  category: 'ball' },
    { name: 'Awakening',           price: 200,  category: 'status' },
    { name: 'Hyper Potion',        price: 200,  category: 'heal' },
    { name: 'Random Ball',         price: 200,  category: 'ball' },
    { name: 'Pyro Ball',           price: 250,  category: 'ball' },
    { name: 'Cryo Ball',           price: 250,  category: 'ball' },
    { name: 'Atmo Ball',           price: 250,  category: 'ball' },
    { name: 'Floro Ball',          price: 250,  category: 'ball' },
    { name: 'Volt Ball',           price: 250,  category: 'ball' },
    { name: 'Aether Ball',         price: 250,  category: 'ball' },
    { name: 'Aqua Ball',           price: 250,  category: 'ball' },
    { name: 'Brawn Ball',          price: 250,  category: 'ball' },
    { name: 'Toxic Ball',          price: 250,  category: 'ball' },
    { name: 'Terra Ball',          price: 250,  category: 'ball' },
    { name: 'Psy Ball',            price: 250,  category: 'ball' },
    { name: 'Swarm Ball',          price: 250,  category: 'ball' },
    { name: 'Crag Ball',           price: 250,  category: 'ball' },
    { name: 'Phantom Ball',        price: 250,  category: 'ball' },
    { name: 'Wyrm Ball',           price: 250,  category: 'ball' },
    { name: 'Umbra Ball',          price: 250,  category: 'ball' },
    { name: 'Alloy Ball',          price: 250,  category: 'ball' },
    { name: 'Fae Ball',            price: 250,  category: 'ball' },
    { name: 'Max Potion',          price: 400,  category: 'heal' },
    { name: 'Full Heal',           price: 400,  category: 'status' },
    { name: 'Essence',             price: 500,  category: 'evolution' },
    { name: 'Great Ball',          price: 500,  category: 'ball' },
    { name: 'Fishing Rod',         price: 600,  category: 'field' },
    { name: 'Ultra Ball',          price: 700,  category: 'ball' },
    { name: 'Master Ball',         price: 1000, category: 'ball' },
    { name: 'Random Poké Egg',     price: 1000, category: 'egg' },
];

app.post('/api/player/grant-starter', async (req, res) => {
    const auth = await _siteAuth(req);
    if (!auth) return res.status(401).json({ error: 'Not logged in.' });

    try {
        // Note: jid/lid can't be looked up here — this call is what
        // creates the players row in the first place, so there's
        // nothing to read yet. SPECIAL_FEW is matched on `sender`
        // (the phone-JID from login) alone, which is correct for the
        // current snapshot list since every entry in it is phone-JID
        // shaped. If a future legacy check ever needs jid/lid matching
        // too, that'll only be possible for players who message the
        // bot on WhatsApp again after registering (see the identity
        // tracking added near the isRegistered check further up).
        const result = await callPythonAction(auth.sender, 'grant_starter', { name: auth.username });
        if (result?.site_result?.error) {
            return res.status(400).json({ error: result.site_result.error });
        }
        if (result?.error) {
            return res.status(503).json({ error: result.error });
        }
        res.status(200).json(result.site_result);
    } catch (e) {
        err('🌐', `player/grant-starter error: ${e.message}`);
        res.status(500).json({ error: 'Something went wrong creating your trainer.' });
    }
});

app.post('/api/player/hatch-legacy-egg', async (req, res) => {
    const auth = await _siteAuth(req);
    if (!auth) return res.status(401).json({ error: 'Not logged in.' });

    try {
        const result = await callPythonAction(auth.sender, 'hatch_legacy_egg', {});
        if (result?.site_result?.error) {
            return res.status(400).json({ error: result.site_result.error });
        }
        if (result?.error) {
            return res.status(503).json({ error: result.error });
        }
        res.status(200).json(result.site_result);
    } catch (e) {
        err('🌐', `player/hatch-legacy-egg error: ${e.message}`);
        res.status(500).json({ error: 'Something went wrong hatching your egg.' });
    }
});

app.get('/api/quests', async (req, res) => {
    // Public — no auth needed to browse the board. Auth only changes
    // whether "mine" comes back populated (see handle_get_quests).
    const auth = await _siteAuth(req); // may be null — that's fine here
    try {
        const result = await callPythonAction(auth?.sender || null, 'get_quests', {});
        if (result?.site_result?.error) {
            return res.status(400).json({ error: result.site_result.error });
        }
        if (result?.error) {
            return res.status(503).json({ error: result.error });
        }
        res.status(200).json(result.site_result);
    } catch (e) {
        err('🌐', `quests error: ${e.message}`);
        res.status(500).json({ error: 'Something went wrong loading quests.' });
    }
});

app.get('/api/badges', async (req, res) => {
    // Public, same reasoning as /api/quests — locked badges are fine to
    // show a logged-out visitor, only "registered" changes.
    const auth = await _siteAuth(req);
    try {
        const result = await callPythonAction(auth?.sender || null, 'get_badges', {});
        if (result?.site_result?.error) {
            return res.status(400).json({ error: result.site_result.error });
        }
        if (result?.error) {
            return res.status(503).json({ error: result.error });
        }
        res.status(200).json(result.site_result);
    } catch (e) {
        err('🌐', `badges error: ${e.message}`);
        res.status(500).json({ error: 'Something went wrong loading badges.' });
    }
});

app.get('/api/gyms', async (req, res) => {
    // Public, same reasoning as /api/badges — locked gyms are fine to
    // show a logged-out visitor (no party to check requirements against),
    // only "registered" changes.
    const auth = await _siteAuth(req);
    try {
        const result = await callPythonAction(auth?.sender || null, 'get_gyms', {});
        if (result?.site_result?.error) {
            return res.status(400).json({ error: result.site_result.error });
        }
        if (result?.error) {
            return res.status(503).json({ error: result.error });
        }
        res.status(200).json(result.site_result);
    } catch (e) {
        err('🌐', `gyms error: ${e.message}`);
        res.status(500).json({ error: 'Something went wrong loading gyms.' });
    }
});

app.get('/api/pokedex', async (req, res) => {
    // Public, same reasoning as /api/badges/gyms — a logged-out visitor
    // just sees every cached species as unseen, only "registered" changes.
    const auth = await _siteAuth(req);
    try {
        const result = await callPythonAction(auth?.sender || null, 'get_pokedex', {});
        if (result?.site_result?.error) {
            return res.status(400).json({ error: result.site_result.error });
        }
        if (result?.error) {
            return res.status(503).json({ error: result.error });
        }
        res.status(200).json(result.site_result);
    } catch (e) {
        err('🌐', `pokedex error: ${e.message}`);
        res.status(500).json({ error: 'Something went wrong loading the Pokédex.' });
    }
});

app.get('/api/zones', async (req, res) => {
    // Public, same reasoning as /api/pokedex — a logged-out visitor
    // sees every zone at whatever tier is globally discovered (tier 1
    // or 2), just never tier 3 (personally visited), same pattern as
    // "registered" elsewhere. Zone discovery itself (Phase 7) is
    // global, not per-viewer, so this is NOT the same as pokedex's
    // per-player seen/caught — only tier 3 depends on who's asking.
    const auth = await _siteAuth(req);
    try {
        const result = await callPythonAction(auth?.sender || null, 'get_zones', {});
        if (result?.site_result?.error) {
            return res.status(400).json({ error: result.site_result.error });
        }
        if (result?.error) {
            return res.status(503).json({ error: result.error });
        }
        res.status(200).json(result.site_result);
    } catch (e) {
        err('🌐', `zones error: ${e.message}`);
        res.status(500).json({ error: 'Something went wrong loading the world map.' });
    }
});

// Housekeeping so the map doesn't grow forever with stale players.
setInterval(() => {
    const now = Date.now();
    for (const [key, hits] of _rateLimitHits.entries()) {
        const fresh = hits.filter(t => now - t < 60_000);
        if (fresh.length === 0) _rateLimitHits.delete(key);
        else _rateLimitHits.set(key, fresh);
    }
}, 5 * 60_000).unref();

app.post('/api/quests/accept', async (req, res) => {
    const auth = await _siteAuth(req);
    if (!auth) return res.status(401).json({ error: 'Not logged in.' });

    // 5 accept attempts per 10 seconds per player — enough for normal misclicks,
    // tight enough to stop spam-claiming across a fast-changing quest board.
    if (_isRateLimited(`quest-accept:${auth.sender}`, 5, 10_000)) {
        return res.status(429).json({ error: 'Slow down — try again in a few seconds.' });
    }

    const { quest_id } = req.body || {};
    if (!quest_id) return res.status(400).json({ error: '"quest_id" is required.' });

    try {
        const result = await callPythonAction(auth.sender, 'accept_quest', { quest_id });
        if (result?.site_result?.error) {
            return res.status(400).json({ error: result.site_result.error });
        }
        if (result?.error) {
            return res.status(503).json({ error: result.error });
        }
        res.status(200).json(result.site_result);
    } catch (e) {
        err('🌐', `quests/accept error: ${e.message}`);
        res.status(500).json({ error: 'Something went wrong accepting that quest.' });
    }
});

app.post('/api/quests/decline', async (req, res) => {
    const auth = await _siteAuth(req);
    if (!auth) return res.status(401).json({ error: 'Not logged in.' });

    const { quest_id } = req.body || {};
    if (!quest_id) return res.status(400).json({ error: '"quest_id" is required.' });

    try {
        const result = await callPythonAction(auth.sender, 'decline_quest', { quest_id });
        if (result?.site_result?.error) {
            return res.status(400).json({ error: result.site_result.error });
        }
        if (result?.error) {
            return res.status(503).json({ error: result.error });
        }
        res.status(200).json(result.site_result);
    } catch (e) {
        err('🌐', `quests/decline error: ${e.message}`);
        res.status(500).json({ error: 'Something went wrong returning that quest.' });
    }
});

app.get('/api/leaderboard', async (req, res) => {
    // Public — no auth needed to view rankings.
    try {
        const db = await _getDB();
        const result = await db.query('SELECT data FROM players');

        const rows = result.rows
            .map(r => {
                try { return JSON.parse(r.data); } catch { return null; }
            })
            .filter(Boolean);

        const topBy = (scoreFn) =>
            rows
                .map(p => ({ name: p.name || 'Unnamed', value: scoreFn(p) }))
                .sort((a, b) => b.value - a.value);

        res.status(200).json({
            level:  topBy(p => p.level || 0),
            pvp:    topBy(p => p.pvp_wins || 0),
            caught: topBy(p => (p.pokedex_caught || []).length),
            badges: topBy(p => (p.badges || []).length),
        });
    } catch (e) {
        err('🌐', `leaderboard error: ${e.message}`);
        res.status(500).json({ error: 'Something went wrong loading the leaderboard.' });
    }
});

app.get('/api/shop', (req, res) => {
    // Public catalog — no auth needed to browse, only to buy.
    res.status(200).json({ items: OAK_TOWN_SHOP });
});

app.post('/api/player/buy', async (req, res) => {
    const auth = await _siteAuth(req);
    if (!auth) return res.status(401).json({ error: 'Not logged in.' });

    const { name } = req.body || {};
    if (!name) {
        return res.status(400).json({ error: '"name" is required.' });
    }

    try {
        const result = await callPythonAction(auth.sender, 'buy', { name });
        if (result?.site_result?.error) {
            return res.status(400).json({ error: result.site_result.error });
        }
        if (result?.error) {
            return res.status(503).json({ error: result.error });
        }
        res.status(200).json(result.site_result);
    } catch (e) {
        err('🌐', `player/buy error: ${e.message}`);
        res.status(500).json({ error: 'Something went wrong performing the purchase.' });
    }
});

