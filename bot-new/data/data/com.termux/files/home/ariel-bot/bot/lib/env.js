// lib/env.js  (split out of index.js)
import path from 'path';
import { fileURLToPath } from 'url';

// bot/ directory (this file lives in bot/lib/); ROOT is the repo root
const __dirname     = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

// Repo layout: bot/ (this file), engine/ (Python), web/, plus data files at the repo root.
export const ROOT          = path.resolve(__dirname, '..');

const GROUPS_FILE   = path.join(ROOT, 'allowed_groups.json');

export const PYTHON_SCRIPT = path.join(ROOT, 'engine', 'bridge.py');

export const PHONE_NUMBER  = process.env.BOT_NUMBER;

   // bot's own number (required)
export const KING_NUMBER  = process.env.KING_NUMBER;

  // owner's number (required)
export const MINE_WATCH_NUMBER = process.env.MINE_WATCH_NUMBER || null;

 // default number Ariel watches for in silent groups (null disables)
export const PAIRING_NUMBER = process.env.PAIRING_NUMBER || PHONE_NUMBER;

// An empty bot/king number would make startsWith('')/includes('') match EVERY jid,
// so refuse to boot instead of misbehaving quietly.
for (const k of ['BOT_NUMBER', 'KING_NUMBER']) {
    if (!process.env[k]) { console.error(`[CONFIG] Missing ${k}. Set it in config/identities.json (or as an env var).`); process.exit(1); }
}

export const BOT_START_TIME = Math.floor(Date.now() / 1000);

export const PORT = process.env.PORT || 3000;

export const JWT_SECRET = process.env.JWT_SECRET;

if (!JWT_SECRET) {
    console.error('❌ JWT_SECRET env var is not set — site auth will not work.');
}

