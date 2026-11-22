// web/niflheim.js: Niflheim Battle Arena API (Session 2). Same login as the rest of the site.
// The game logic stays in Python (engine/niflheim/arena.py); this file only relays.
import path from 'path';
import { fileURLToPath } from 'url';
import { app } from './app.js';
import { _siteAuth } from './auth.js';
import { callPythonAction } from '../bridge.js';
import { err } from '../lib/log.js';

const HERE = path.dirname(fileURLToPath(import.meta.url));

function relay(type, payloadOf) {
    return async (req, res) => {
        const auth = await _siteAuth(req);
        if (!auth) return res.status(401).json({ error: 'Not logged in.' });
        try {
            const result = await callPythonAction(auth.sender, type, payloadOf(req));
            if (result?.error) return res.status(503).json({ error: result.error });
            const out = result?.site_result || {};
            if (out.error) return res.status(400).json(out);
            res.status(200).json(out);
        } catch (e) {
            err('⚔️', `${type} error: ${e.message}`);
            res.status(500).json({ error: 'Something went wrong. Try again.' });
        }
    };
}

app.get('/arena', (req, res) => res.sendFile(path.join(HERE, 'niflheim_arena.html')));
app.get('/api/niflheim/me', relay('nif_me', () => ({})));
app.post('/api/niflheim/battle/start', relay('nif_ticket', (req) => ({ monsterId: req.body?.monsterId })));
app.get('/api/niflheim/battle/:ticket', relay('nif_ticket_get', (req) => ({ ticket: req.params.ticket })));
app.post('/api/niflheim/battle/result', relay('nif_result', (req) => ({
    ticket: req.body?.ticket, won: req.body?.won, timeUp: req.body?.timeUp,
    playerHp: req.body?.playerHp, foeHp: req.body?.foeHp,
})));
