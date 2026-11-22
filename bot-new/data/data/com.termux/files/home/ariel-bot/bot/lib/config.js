// Loads config/identities.json into process.env (env vars already set win).
// Import this FIRST in any file that reads KING_NUMBER / BOT_NUMBER / etc.
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dir = path.dirname(fileURLToPath(import.meta.url));
const FILE  = path.resolve(__dir, '..', '..', 'config', 'identities.json');

try {
    const cfg = JSON.parse(fs.readFileSync(FILE, 'utf8'));
    for (const [k, v] of Object.entries(cfg)) {
        if (k.startsWith('_')) continue;
        if (process.env[k] === undefined || process.env[k] === '') {
            process.env[k] = Array.isArray(v) ? v.join(',') : String(v);
        }
    }
} catch (e) {
    if (e.code !== 'ENOENT') console.error('[CONFIG] could not read', FILE, e.message);
}
