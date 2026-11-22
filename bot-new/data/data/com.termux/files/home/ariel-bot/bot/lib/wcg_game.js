// bot/lib/wcg_game.js - the `.wcg` Word Chain Game engine.
// No WhatsApp / DB code in here: everything outside goes through the injected `io`
// ({ send }) so the whole thing can be tested with fake timers (tests/js/wcg_game_test.mjs).
//
// Flow:  .wcg start (host, lobby 20s)  ->  .wcg join  ->  auto start  ->  7s player-order reveal
//        ->  turns.  Each word must start with the last letter of the previous word, be a real
//        word, not used before, and at least `minLen` letters.  Run out the clock = eliminated.
//        Last player standing wins.  Only the host can .wcg end.
import fs from 'node:fs';

export const LOBBY_MS = 20_000;        // lobby stays open after .wcg start
export const REVEAL_MS = 7_000;        // player order is shown this long before the first turn
export const MIN_PLAYERS = 2;
export const ROUNDS_PER_TIER = 3;      // every 3 rounds: +1 letter, less time
// Round 1-3: 3 letters / 60s   4-6: 4 / 45s   7-9: 5 / 30s   10-12: 6 / 15s   13+: 7 / 10s (final tier)
export const TIERS = [
    { minLen: 3, ms: 60_000 },
    { minLen: 4, ms: 45_000 },
    { minLen: 5, ms: 30_000 },
    { minLen: 6, ms: 15_000 },
    { minLen: 7, ms: 10_000 },
];
export const tierFor = (round) => TIERS[Math.min(Math.floor((round - 1) / ROUNDS_PER_TIER), TIERS.length - 1)];

// Bot remarks after an elimination (shown after "@player is out."). Add more freely.
export const REMARKS = [
    'Time ran out.',
    'Blinked and missed it.',
    'The clock does not wait.',
    'Got stuck and never recovered.',
    'Fell asleep on the keyboard.',
    'Too slow.',
    'Thought too hard, typed too little.',
    'The chain broke here.',
    'Silence was not a strategy.',
    'The dictionary waited. The clock did not.',
];

const STARTERS = [
    'apple', 'river', 'train', 'mouse', 'ocean', 'tiger', 'light', 'storm', 'plant', 'bread',
    'chair', 'music', 'night', 'dream', 'cloud', 'green', 'house', 'sugar', 'water', 'happy',
    'knife', 'pizza', 'beach', 'lemon', 'snake', 'candy', 'robot', 'smile', 'world', 'flame',
];

export const HELP_TEXT =
    '*Word Chain*\n' +
    '┣ ✦ .wcg start  - open a lobby (you become host)\n' +
    '┣ ✦ .wcg join  - join the lobby\n' +
    '┗ ✦ .wcg end  - end the game (host only)\n\n' +
    'Say a word that starts with the last letter of the previous word. No repeats. ' +
    'Every 3 rounds the minimum length goes up by 1 and the time goes down. ' +
    'Run out of time and you are out. Last player standing wins.';

export const tag = (jid) => '@' + String(jid).split('@')[0];

/** Numbered list, host marked:  1. @mica - Host */
export const roster = (jids, host) => jids.map((j, i) => `${i + 1}. ${tag(j)}${j === host ? ' - Host' : ''}`).join('\n');

/** Load the bundled word list (one lowercase word per line). */
export function loadWords(file = new URL('./wcg_words.txt', import.meta.url)) {
    return fs.readFileSync(file, 'utf8').split('\n').map(w => w.trim().toLowerCase()).filter(w => /^[a-z]{2,}$/.test(w));
}

export const BIG_LIST_URL = 'https://raw.githubusercontent.com/dwyl/english-words/master/words_alpha.txt';
const BIG_CACHE = new URL('./wcg_words_big.txt', import.meta.url);

/** Parse + sanity-check a downloaded list. Returns null if it does not look like a word list. */
export function parseBigList(txt) {
    const list = String(txt).split(/\r?\n/).map(w => w.trim().toLowerCase()).filter(w => /^[a-z]{2,}$/.test(w));
    return list.length >= 100_000 ? list : null;
}

/** Cached big list if present, else download it once (and cache). Returns the list or null (keep the bundled one). */
export async function loadBigWords({ fetchFn = globalThis.fetch, cache = BIG_CACHE, url = BIG_LIST_URL, log = console.log } = {}) {
    try {
        if (fs.existsSync(cache)) {
            const cached = parseBigList(fs.readFileSync(cache, 'utf8'));
            if (cached) return cached;
        }
        const res = await fetchFn(url);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const txt = await res.text();
        const list = parseBigList(txt);
        if (!list) throw new Error('downloaded file does not look like a word list');
        try { fs.writeFileSync(cache, txt); } catch { /* read-only disk: fine, just re-download next boot */ }
        log(`[wcg] big dictionary loaded: ${list.length} words`);
        return list;
    } catch (e) {
        log(`[wcg] big dictionary unavailable (${e.message}); using the built-in list`);
        return null;
    }
}

let _shared = null, _sharedCommon = null;
const sharedWords = () => (_shared ??= loadWords());
// Everyday words used for starting/hint suggestions (the full list also accepts obscure ones).
const sharedCommon = () => (_sharedCommon ??= loadWords(new URL('./wcg_common.txt', import.meta.url)));

export class WcgManager {
    /** io.send(chat, text, { mentions, quoted }) -> Promise */
    constructor(io, { rand = Math.random, setT = setTimeout, clearT = clearTimeout, words, common } = {}) {
        this.io = io; this.rand = rand; this.setT = setT; this.clearT = clearT;
        const list = words ?? sharedWords();
        this.dict = new Set(list);
        this.byLetter = {};
        for (const w of list) (this.byLetter[w[0]] ??= []).push(w);
        this.commonByLetter = {};
        for (const w of (common ?? (words ? [] : sharedCommon()))) (this.commonByLetter[w[0]] ??= []).push(w);
        this.games = new Map();   // chat -> game
    }

    // ─────────────── small helpers ───────────────
    _say(chat, text, jids = [], quoted) {
        const mentions = [...new Set(jids)];
        return this.io.send(chat, text, { mentions, quoted });
    }
    _tm(g, fn, ms) { this._clr(g); g.timer = this.setT(fn, ms); }
    _clr(g) { if (g.timer != null) { this.clearT(g.timer); g.timer = null; } }
    _end(chat, g) { this._clr(g); g.phase = 'over'; this.games.delete(chat); }

    /** A word the player could have used: right letter, long enough, unused. */
    suggest(letter, minLen, used) {
        const ok = (w) => w.length >= minLen && !used.has(w);
        // everyday words first; fall back to the full dictionary only if none fit
        let pool = (this.commonByLetter[letter] ?? []).filter(ok);
        if (!pool.length) pool = (this.byLetter[letter] ?? []).filter(ok);
        if (!pool.length) return null;
        const near = pool.filter(w => w.length <= minLen + 2);   // shortish = playable, not showy
        const from = near.length ? near : pool;
        return from[Math.floor(this.rand() * from.length)];
    }

    /** Swap in a bigger dictionary for validation (hints keep using the everyday list). */
    setWords(list) {
        this.dict = new Set(list);
        this.byLetter = {};
        for (const w of list) (this.byLetter[w[0]] ??= []).push(w);
    }

    /** True if `sender` is the player whose turn it is (cheap check for the handler). */
    isTurn(chat, sender) {
        const g = this.games.get(chat);
        return !!g && g.phase === 'play' && g.current === sender;
    }
    active(chat) { return this.games.has(chat); }

    // ─────────────── commands ───────────────
    async command(chat, sender, args, quoted) {
        const sub = (args[0] || '').toLowerCase();
        if (!sub || sub === 'help') return this._say(chat, HELP_TEXT, [], quoted);
        if (sub === 'start') return this._open(chat, sender, quoted);
        if (sub === 'join') return this._join(chat, sender, quoted);
        if (sub === 'end' || sub === 'stop') return this._stop(chat, sender, quoted);
        return this._say(chat, HELP_TEXT, [], quoted);
    }

    async _open(chat, sender, quoted) {
        if (this.games.has(chat)) return this._say(chat, '_A Word Chain is already running here._', [], quoted);
        const g = { phase: 'lobby', host: sender, players: [sender], timer: null, used: new Set() };
        this.games.set(chat, g);
        this._tm(g, () => this._closeLobby(chat, g), LOBBY_MS);
        await this._say(chat,
            `*Word Chain*\nLobby open for ${LOBBY_MS / 1000}s.\n\n${roster(g.players, g.host)}\n\nSend *.wcg join* to play (${MIN_PLAYERS}+ players).`,
            g.players, quoted);
    }

    async _join(chat, sender, quoted) {
        const g = this.games.get(chat);
        if (!g) return this._say(chat, '_No lobby open. Use .wcg start to open one._', [], quoted);
        if (g.phase !== 'lobby') return this._say(chat, '_The game has already started._', [], quoted);
        if (g.players.includes(sender)) return this._say(chat, `_${tag(sender)} is already in._`, [sender], quoted);
        g.players.push(sender);
        await this._say(chat, `*Word Chain*\n${tag(sender)} joined.\n\n${roster(g.players, g.host)}`, g.players, quoted);
    }

    async _stop(chat, sender, quoted) {
        const g = this.games.get(chat);
        if (!g) return this._say(chat, '_No Word Chain is running._', [], quoted);
        if (sender !== g.host) return this._say(chat, `_Only the host (${tag(g.host)}) can end the game._`, [g.host], quoted);
        const left = g.phase === 'play' ? g.order : g.players;
        this._end(chat, g);
        await this._say(chat, `*Word Chain ended* by the host.`, left, quoted);
    }

    // ─────────────── lobby -> reveal -> play ───────────────
    async _closeLobby(chat, g) {
        if (this.games.get(chat) !== g || g.phase !== 'lobby') return;
        if (g.players.length < MIN_PLAYERS) {
            this._end(chat, g);
            return this._say(chat, `_Lobby closed: not enough players (${g.players.length}/${MIN_PLAYERS})._`);
        }
        g.phase = 'reveal';
        g.order = this._shuffle(g.players);
        const list = roster(g.order, g.host);
        this._tm(g, () => this._begin(chat, g), REVEAL_MS);
        await this._say(chat,
            `*Word Chain*\nPlayers, in turn order:\n\n${list}\n\nStarting in ${REVEAL_MS / 1000}s...`, g.order);
    }

    _shuffle(arr) {
        const a = arr.slice();
        for (let i = a.length - 1; i > 0; i--) {
            const j = Math.floor(this.rand() * (i + 1));
            [a[i], a[j]] = [a[j], a[i]];
        }
        return a;
    }

    async _begin(chat, g) {
        if (this.games.get(chat) !== g || g.phase !== 'reveal') return;
        g.phase = 'play';
        g.round = 1;
        g.queue = g.order.slice();          // who has not played yet this round
        const start = STARTERS[Math.floor(this.rand() * STARTERS.length)];
        g.used.add(start);
        g.last = start;
        const t = tierFor(1);
        await this._say(chat,
            `*Word Chain started*\nFirst word: *${start}*\n` +
            `Next word starts with the last letter. No repeats. ${t.minLen}+ letters, ${t.ms / 1000}s per turn.`);
        await this._nextTurn(chat, g, '');
    }

    /** Hand the baton to the next player in the queue (starts a new round when the queue is empty). */
    async _nextTurn(chat, g, prefix, extra = []) {
        const parts = prefix ? [prefix] : [];
        if (!g.queue.length) {
            const before = tierFor(g.round);
            g.round += 1;
            g.queue = g.order.slice();
            const after = tierFor(g.round);
            if (after !== before) {
                parts.push(`*Round ${g.round}*: ${after.minLen}+ letters, ${after.ms / 1000}s per turn.`);
            }
        }
        g.current = g.queue.shift();
        const t = tierFor(g.round);
        const letter = g.last[g.last.length - 1];
        g.turnId = (g.turnId || 0) + 1;
        const id = g.turnId;
        this._tm(g, () => this._timeout(chat, g, id), t.ms);
        parts.push(`${tag(g.current)}, your turn: *${letter.toUpperCase()}*  (${t.minLen}+ letters, ${t.ms / 1000}s)`);
        await this._say(chat, parts.join('\n\n'), [g.current, ...extra]);
    }

    // ─────────────── a player's word ───────────────
    /** Returns true if the message was ours (a word attempt by the current player). */
    async answer(chat, sender, text, quoted) {
        const g = this.games.get(chat);
        if (!g || g.phase !== 'play' || g.current !== sender) return false;
        const w = String(text || '').trim().toLowerCase();
        if (!/^[a-z]+$/.test(w)) return false;     // chatter / multiple words / emoji: not an attempt
        const t = tierFor(g.round);
        const need = g.last[g.last.length - 1];
        let why = null;
        if (w[0] !== need) why = `does not start with *${need.toUpperCase()}*`;
        else if (w.length < t.minLen) why = `is too short (min ${t.minLen} letters)`;
        else if (g.used.has(w)) why = 'was already used';
        else if (!this.dict.has(w)) why = 'is not in the dictionary';
        if (why) {
            await this._say(chat, `❌ *${w}* ${why}.`, [], quoted);
            return true;
        }
        this._clr(g);
        g.turnId += 1;                       // invalidate the running timeout
        g.used.add(w);
        g.last = w;
        await this._nextTurn(chat, g, `✅ *${w}*`);
        return true;
    }

    // ─────────────── elimination ───────────────
    async _timeout(chat, g, id) {
        if (this.games.get(chat) !== g || g.phase !== 'play' || g.turnId !== id) return;
        const out = g.current;
        const t = tierFor(g.round);
        const need = g.last[g.last.length - 1];
        g.order = g.order.filter(j => j !== out);
        g.queue = g.queue.filter(j => j !== out);
        const remark = REMARKS[Math.floor(this.rand() * REMARKS.length)];
        const hint = this.suggest(need, t.minLen, g.used);
        const msg = `❌ ${tag(out)} is out. ${remark}` +
            (hint ? `\nYou could have said: *${hint}*` : '');
        if (g.order.length <= 1) {
            const winner = g.order[0];
            this._end(chat, g);
            return this._say(chat, `${msg}\n\n🏆 *${tag(winner)} wins the Word Chain!*`, [out, winner]);
        }
        await this._nextTurn(chat, g, msg + `\n\n*Remaining*\n${roster(g.order, g.host)}`, [out, ...g.order]);
    }
}
