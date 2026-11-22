// bot/lib/lang_game.js - the `.lang` game engine (solo sessions + tournaments).
// No WhatsApp / DB code in here: everything outside goes through the injected `io`
// ({ send, participants }) so the whole thing can be tested with fake timers.
import { LANGUAGES, LANG_ALIASES } from './lang_words.js';

export const WORD_TIMEOUT_MS = 60_000;     // no solve for 1 minute = fail, next word
export const LOBBY_MS = 25_000;            // tournament lobby stays open
export const RULES_MS = 10_000;            // rules are shown this long before round 1
export const TIMED_MS = 3 * 60_000;        // .lang timed
export const SYL_POINT = 1;
export const WORD_BONUS = 5;
export const IDLE_FAIL_CAP = 10;           // tournaments: this many words in a row with no attempt ends it
export const MODES = ['fixed', 'timed', 'infinite'];

// Alternative romaji spellings accepted for a syllable (kunrei etc. -> Hepburn).
const ALT = {
    si: 'shi', ti: 'chi', tu: 'tsu', hu: 'fu', zi: 'ji',
    sya: 'sha', syu: 'shu', syo: 'sho', tya: 'cha', tyu: 'chu', tyo: 'cho',
    zya: 'ja', zyu: 'ju', zyo: 'jo', jya: 'ja', jyu: 'ju', jyo: 'jo',
    "n'": 'n', nn: 'n', wo: 'o',
};
const canon = (t) => ALT[t] ?? t;

/** Score one answer against a word. Answers are syllables separated by spaces; an
 *  unspaced answer is just one (probably wrong) syllable. Position matters. */
export function checkAnswer(word, text) {
    const toks = String(text).toLowerCase().trim().split(/\s+/).filter(Boolean);
    const marks = toks.map((t, i) => i < word.syl.length && canon(t) === word.syl[i]);
    const full = toks.length === word.syl.length && marks.every(Boolean);
    return { toks, marks, full };
}

const tag = (jid) => '@' + String(jid).split('@')[0];

function shuffle(arr, rand) {
    const a = arr.slice();
    for (let i = a.length - 1; i > 0; i--) {
        const j = Math.floor(rand() * (i + 1));
        [a[i], a[j]] = [a[j], a[i]];
    }
    return a;
}

/** Endless shuffled word source with one word of look-ahead. */
class Deck {
    constructor(words, rand) { this.words = words; this.rand = rand; this.q = []; this.cur = this._pull(); this.nxt = this._pull(); }
    _pull() {
        if (!this.q.length) {
            this.q = shuffle(this.words, this.rand);
            if (this.cur && this.q[this.q.length - 1] === this.cur) this.q.reverse();
        }
        return this.q.pop();
    }
    advance() { this.cur = this.nxt; this.nxt = this._pull(); }
}

export function rankPlayers(players) {
    const list = [...players.entries()].map(([jid, p]) => ({ jid, score: p.score }));
    list.sort((a, b) => b.score - a.score);
    let rank = 0, last = null;
    list.forEach((e, i) => { if (e.score !== last) { rank = i + 1; last = e.score; } e.rank = rank; });
    return list;
}

export function boardText(players) {
    const lines = rankPlayers(players).map((e, i) => `${i + 1}. ${tag(e.jid)} - ${e.score} point${e.score === 1 ? '' : 's'}`);
    return `*Players*\n${lines.join('\n')}`;
}

const ordinal = (n) => (n === 1 ? '1st' : n === 2 ? '2nd' : n === 3 ? '3rd' : `${n}th`);
export function finalText(players, title = '🏁 *Tournament over!*') {
    const rows = rankPlayers(players).map(e => {
        const pts = `${e.score} point${e.score === 1 ? '' : 's'}`;
        if (e.rank === 1) return `*1st* ${tag(e.jid)} - ${pts} 🥇 🥇 🥇`;
        if (e.rank === 2) return `*2nd* ${tag(e.jid)} - ${pts} 🏅 🏅`;
        if (e.rank === 3) return `*3rd* ${tag(e.jid)} - ${pts} ✨`;
        return `${ordinal(e.rank)}. ${tag(e.jid)} - ${pts}`;
    });
    return `${title}\n\n${rows.join('\n')}`;
}

export const HELP_TEXT =
    '🎌 *.lang* — type the sounds of the word\n' +
    '┣ ✦ .lang start (language)  — solo game (Japanese)\n' +
    '┣ ✦ .lang end  — stop your solo game\n' +
    '┣ ✦ .lang tournament  — open a lobby, then .lang join\n' +
    '┣ ✦ .lang fixed / timed / infinite  — pick the mode while the lobby is open\n' +
    '┗ ✦ .bail  — reveal the answer and move on\n\n' +
    'Reply to any of my messages with the sounds spaced by syllable, e.g. *ko n ba n wa*.';

const RULES = (extra = '') =>
    '*Rules:*\n' +
    '1. Reply to any of my messages with the sound (romaji) of the Current word, spaced by syllable: *ko n ba n wa*\n' +
    '2. 1 point for each syllable in the right place, +5 for the first to get the whole word\n' +
    '3. .bail reveals the answer and moves on (counts as ❌). 1 minute with no solve is also ❌ (in solo, 1 minute with no reply ends your game)' +
    (extra ? '\n' + extra : '');

export class LangManager {
    /**
     * io.send(chat, text, { mentions, quoted })  -> Promise
     * io.participants(chat)                     -> Promise<string[]> (jids)
     */
    constructor(io, { rand = Math.random, setT = setTimeout, clearT = clearTimeout } = {}) {
        this.io = io; this.rand = rand; this.setT = setT; this.clearT = clearT;
        this.solo = new Map();   // `${chat}|${sender}` -> session
        this.tours = new Map();  // chat -> tournament
    }

    // ─────────────── shared pieces ───────────────
    _panel(round, extraTop = '', progress = '') {
        const prev = round.prev ? `${round.prev.word.kana} ${round.prev.ok ? '✅' : '❌'} (${round.prev.word.display} — ${round.prev.word.en})` : '—';
        return (extraTop ? extraTop + '\n\n' : '') +
            `Prev: ${prev}\n` +
            `Current: ${round.deck.cur.kana} — ${round.deck.cur.en}\n` +
            ` (.bail to reveal)\n` +
            `Next: ${round.deck.nxt.kana} — ${round.deck.nxt.en}` +
            (progress ? `\n${progress}` : '');
    }
    _newRound(langKey) {
        return { deck: new Deck(LANGUAGES[langKey].words, this.rand), prev: null, timer: null, attempted: false, idle: 0, got: new Map() };
    }
    _finishWord(round, ok) {
        round.prev = { word: round.deck.cur, ok };
        round.deck.advance();
        round.got = new Map();
        round.idle = ok || round.attempted ? 0 : round.idle + 1;
        round.attempted = false;
    }
    _feedback(word, res, earned, already) {
        const body = res.toks.map((t, i) => `${t}${res.marks[i] ? '✅' : '❌'}`).join(' ');
        const pts = earned > 0 ? `  +${earned}` : (res.marks.some(Boolean) && already ? '  (Alr got)' : '');
        return body + pts;
    }
    /** Apply one answer for one player. Returns { earned, fb, solved, total }. */
    _grade(round, player, text) {
        const word = round.deck.cur;
        const res = checkAnswer(word, text);
        round.attempted = true;
        let got = round.got.get(player.jid);
        if (!got) { got = new Set(); round.got.set(player.jid, got); }
        let earned = 0, already = false;
        res.marks.forEach((ok, i) => {
            if (!ok) return;
            if (got.has(i)) already = true; else { got.add(i); earned += SYL_POINT; }
        });
        player.score += earned;
        return { earned, res, word, fb: this._feedback(word, res, earned, already), solved: res.full };
    }

    // ─────────────── solo ───────────────
    _soloKey(chat, sender) { return `${chat}|${sender}`; }
    hasSolo(chat, sender) { return this.solo.has(this._soloKey(chat, sender)); }

    async soloStart(chat, sender, langArg, quoted) {
        if (this.tours.get(chat)?.players.has(sender)) return this.io.send(chat, '_You are in a tournament — finish that first._', { quoted });
        const key = this._soloKey(chat, sender);
        if (this.solo.has(key)) return this.io.send(chat, '_You already have a game running. Reply to my last word, or .lang end._', { quoted });
        const lk = LANG_ALIASES[(langArg || 'japanese').toLowerCase()];
        if (!lk) return this.io.send(chat, `_Only Japanese is available for now — try *.lang start japanese*._`, { quoted });
        const round = this._newRound(lk);
        const s = { chat, sender, lang: lk, round, player: { jid: sender, score: 0 }, words: 0 };
        this.solo.set(key, s);
        await this.io.send(chat, this._panel(round, `🎌 *${LANGUAGES[lk].name}* — ${tag(sender)}'s game\n_Spaced syllables, e.g. ko n ba n wa_`), { mentions: [sender] });
        this._armSolo(s);
    }
    _armSolo(s) {
        this.clearT(s.round.timer);
        s.round.timer = this.setT(() => this._soloTimeout(s), WORD_TIMEOUT_MS);
    }
    _soloLive(s) { return this.solo.get(this._soloKey(s.chat, s.sender)) === s; }
    async _soloTimeout(s) {
        if (!this._soloLive(s)) return;
        const word = s.round.deck.cur;
        // Solo: a minute with no reply is a fail AND ends the run.
        await this._soloStop(s, `⏰ ${tag(s.sender)} — no reply for 1 minute ❌ (${word.display} — ${word.en})`);
    }
    async _soloStop(s, msg) {
        this.clearT(s.round.timer);
        this.solo.delete(this._soloKey(s.chat, s.sender));
        await this.io.send(s.chat, `${msg}\n🏁 ${tag(s.sender)} — final score: *${s.player.score}*`, { mentions: [s.sender] });
    }
    async soloEnd(chat, sender, quoted) {
        const s = this.solo.get(this._soloKey(chat, sender));
        if (!s) return false;
        await this._soloStop(s, '🛑 _Game ended._');
        return true;
    }
    async _soloAnswer(s, text, quoted) {
        const g = this._grade(s.round, s.player, text);
        if (!g.solved) { await this.io.send(s.chat, g.fb, { quoted }); this._armSolo(s); return; }
        s.player.score += WORD_BONUS;
        const gain = g.earned + WORD_BONUS;
        this._finishWord(s.round, true);
        await this.io.send(s.chat, this._panel(s.round, `${g.fb}\n🎉 ${tag(s.sender)} got it! +${WORD_BONUS} word bonus (${gain} this word)`, `Score: ${s.player.score}`), { mentions: [s.sender], quoted });
        this._armSolo(s);
    }
    async _soloBail(s, quoted) {
        const word = s.round.deck.cur;
        this._finishWord(s.round, false);
        await this.io.send(s.chat, this._panel(s.round, `❌ (${word.display} — ${word.en})`, `Score: ${s.player.score}`), { quoted });
        this._armSolo(s);
    }

    // ─────────────── tournament ───────────────
    async tourOpen(chat, sender, quoted) {
        if (this.tours.has(chat)) return this.io.send(chat, '_A tournament is already running in this group._', { quoted });
        if (this.hasSolo(chat, sender)) await this.soloEnd(chat, sender);
        const t = { chat, host: sender, phase: 'lobby', mode: 'fixed', players: new Map(), round: null, timers: [], wordsDone: 0, total: 0 };
        t.players.set(sender, { jid: sender, score: 0 });
        this.tours.set(chat, t);
        await this.io.send(chat,
            `🏆 *Language Tournament*\nLobby is open for ${LOBBY_MS / 1000}s — type *.lang join* to enter.\n` +
            `Mode: *fixed* (25 words + 10 per player). Change it with *.lang fixed / timed / infinite*\n` +
            `_timed = 3 minutes · infinite = until a player sends .lang end_\n\n${boardText(t.players)}`,
            { mentions: [...t.players.keys()] });
        t.timers.push(this.setT(() => this._tourRules(t), LOBBY_MS));
    }
    async tourJoin(chat, sender, quoted) {
        const t = this.tours.get(chat);
        if (!t || t.phase !== 'lobby') return this.io.send(chat, '_No tournament lobby is open. Start one with *.lang tournament*._', { quoted });
        if (t.players.has(sender)) return this.io.send(chat, "_You're already in._", { quoted });
        if (this.hasSolo(chat, sender)) await this.soloEnd(chat, sender);
        t.players.set(sender, { jid: sender, score: 0 });
        await this.io.send(chat, `✅ ${tag(sender)} joined!\n\n${boardText(t.players)}`, { mentions: [...t.players.keys()] });
    }
    async tourMode(chat, sender, mode, quoted) {
        const t = this.tours.get(chat);
        if (!t || t.phase !== 'lobby') return this.io.send(chat, '_Modes can only be changed while a tournament lobby is open._', { quoted });
        if (!t.players.has(sender)) return this.io.send(chat, '_Join the lobby first (*.lang join*)._', { quoted });
        t.mode = mode;
        const n = 25 + 10 * t.players.size;
        const desc = mode === 'fixed' ? `${n} words (25 + 10 per player — grows as players join)` : mode === 'timed' ? '3 minutes' : 'until a player sends .lang end';
        await this.io.send(chat, `⚙️ Mode: *${mode}* — ${desc}`, { quoted });
    }
    async _tourRules(t) {
        if (this.tours.get(t.chat) !== t) return;
        if (t.players.size < 2) {
            this.tours.delete(t.chat);
            return this.io.send(t.chat, '_Tournament cancelled — it needs at least 2 players._');
        }
        t.phase = 'rules';
        let everyone = [];
        try { everyone = await this.io.participants(t.chat); } catch { /* fall back to players only */ }
        const mentions = [...new Set([...everyone, ...t.players.keys()])];
        const players = [...t.players.keys()].map(tag).join(' ');
        await this.io.send(t.chat,
            `🏆 *Language Tournament* — starting in ${RULES_MS / 1000}s!\nMode: *${t.mode}*\nPlayers: ${players}\n\n${RULES()}`,
            { mentions, hide: true });
        t.timers.push(this.setT(() => this._tourBegin(t), RULES_MS));
    }
    async _tourBegin(t) {
        if (this.tours.get(t.chat) !== t) return;
        t.phase = 'running';
        t.round = this._newRound('japanese');
        t.total = t.mode === 'fixed' ? 25 + 10 * t.players.size : Infinity;
        if (t.mode === 'timed') t.timers.push(this.setT(() => this._tourFinish(t, '⏱️ _Time!_'), TIMED_MS));
        await this.io.send(t.chat, this._panel(t.round, '🏆 *Go!*', this._progress(t) + '\n\n' + boardText(t.players)), { mentions: [...t.players.keys()] });
        this._armTour(t);
    }
    _progress(t) { return t.mode === 'fixed' ? `Word ${t.wordsDone + 1}/${t.total}` : t.mode === 'timed' ? 'Timed: 3 minutes' : 'Infinite — .lang end to stop'; }
    _armTour(t) {
        this.clearT(t.round.timer);
        t.round.timer = this.setT(() => this._tourTimeout(t), WORD_TIMEOUT_MS);
    }
    async _tourTimeout(t) {
        if (this.tours.get(t.chat) !== t || t.phase !== 'running') return;
        await this._tourAdvance(t, false, `⏰ Time's up ❌ (${t.round.deck.cur.display} — ${t.round.deck.cur.en})`);
    }
    async _tourAdvance(t, ok, top, opts = {}) {
        t.round.timer && this.clearT(t.round.timer);
        this._finishWord(t.round, ok);
        t.wordsDone++;
        if (t.wordsDone >= t.total) return this._tourFinish(t, top + '\n\n_That was the last word!_');
        if (t.round.idle >= IDLE_FAIL_CAP) return this._tourFinish(t, '💤 _No replies for a while — tournament ended._');
        await this.io.send(t.chat, this._panel(t.round, top, this._progress(t) + '\n\n' + boardText(t.players)), { mentions: [...t.players.keys()], ...opts });
        this._armTour(t);
    }
    async _tourFinish(t, note) {
        if (this.tours.get(t.chat) !== t) return;
        this.tours.delete(t.chat);
        t.timers.forEach(x => this.clearT(x));
        this.clearT(t.round?.timer);
        t.phase = 'done';
        await this.io.send(t.chat, `${note ? note + '\n\n' : ''}${finalText(t.players)}`, { mentions: [...t.players.keys()] });
    }
    async tourEnd(chat, sender, quoted) {
        const t = this.tours.get(chat);
        if (!t || !t.players.has(sender)) return false;
        if (t.phase === 'lobby' || t.phase === 'rules') {
            if (sender !== t.host) { await this.io.send(chat, '_Only the host can cancel before it starts._', { quoted }); return true; }
            t.timers.forEach(x => this.clearT(x));
            this.tours.delete(chat);
            await this.io.send(chat, '_Tournament cancelled._', { quoted });
            return true;
        }
        await this._tourFinish(t, '🛑 _Ended by a player._');
        return true;
    }
    async _tourAnswer(t, sender, text, quoted) {
        const player = t.players.get(sender);
        const g = this._grade(t.round, player, text);
        if (!g.solved) { await this.io.send(t.chat, g.fb, { quoted }); this._armTour(t); return; }
        player.score += WORD_BONUS;
        await this._tourAdvance(t, true, `${g.fb}\n🎉 ${tag(sender)} got it first! +${WORD_BONUS}`, { quoted });
    }
    async _tourBail(t, quoted) {
        await this._tourAdvance(t, false, `❌ (${t.round.deck.cur.display} — ${t.round.deck.cur.en})`, { quoted });
    }

    // ─────────────── entry points used by the handler ───────────────
    /** `.lang ...` commands. args = words after ".lang". */
    async command(chat, sender, args, quoted) {
        const sub = (args[0] || '').toLowerCase();
        if (!sub) return this.io.send(chat, HELP_TEXT, { quoted });
        if (sub === 'start') return this.soloStart(chat, sender, args[1], quoted);
        if (sub === 'end') {
            if (await this.tourEnd(chat, sender, quoted)) return;
            if (await this.soloEnd(chat, sender, quoted)) return;
            return this.io.send(chat, "_You don't have a game running._", { quoted });
        }
        if (sub === 'tournament') return this.tourOpen(chat, sender, quoted);
        if (sub === 'join') return this.tourJoin(chat, sender, quoted);
        if (MODES.includes(sub)) return this.tourMode(chat, sender, sub, quoted);
        return this.io.send(chat, HELP_TEXT, { quoted });
    }

    /** `.bail` — true if it was consumed. */
    async bail(chat, sender, quoted) {
        const t = this.tours.get(chat);
        if (t?.phase === 'running' && t.players.has(sender)) { await this._tourBail(t, quoted); return true; }
        const s = this.solo.get(this._soloKey(chat, sender));
        if (s) { await this._soloBail(s, quoted); return true; }
        return false;
    }

    /** A plain reply to one of the bot's messages. true if it was an answer. */
    async answer(chat, sender, text, quoted) {
        const t = this.tours.get(chat);
        if (t?.players.has(sender)) {
            if (t.phase !== 'running') return false;
            await this._tourAnswer(t, sender, text, quoted);
            return true;
        }
        const s = this.solo.get(this._soloKey(chat, sender));
        if (s) { await this._soloAnswer(s, text, quoted); return true; }
        return false;
    }
}
