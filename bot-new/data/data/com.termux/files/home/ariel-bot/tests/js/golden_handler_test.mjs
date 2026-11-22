// Golden-output test for bot/handler.js handleMessage (and everything it calls in commands.js, groups.js, ...).
//
//   node --no-warnings --import ./tests/js/register.mjs tests/js/golden_handler_test.mjs [--update]
//
// Each scenario = fresh in-memory DB + fresh bot state + fixed clock/random, then one or more fake WhatsApp
// messages through the REAL handleMessage. What is compared is everything observable: every call the bot makes on
// the socket, every Python-bridge call (with pool flags), every media-helper call and every mutating SQL statement.
// See harness.mjs for the fakes (no network, no node_modules, no real database, no real phone numbers).
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import * as H from './harness.mjs';
const { J, NUM, golden, mkMsg, makeSock, makePool, groupMeta } = H;

const HERE = path.dirname(fileURLToPath(import.meta.url));
const GOLDEN = path.join(HERE, '..', 'golden', 'handler_golden.json');
const UPDATE = process.argv.includes('--update');
const DUMP = process.env.GOLDEN_DUMP ? {} : null;

const { botState } = await import('../../bot/lib/state.js');
const { groupMetaCache, groupPrefixCache, presenceCache, lidMap } = await import('../../bot/lib/cache.js');
const { handleMessage } = await import(process.env.HANDLER_FILE ?? '../../bot/handler.js');
const CMD = await import('../../bot/commands.js');
const { setupCommandsTables } = CMD;

const initial = {};
for (const [k, v] of Object.entries(botState))
    initial[k] = Array.isArray(v) ? [] : (v && typeof v === 'object' && !(v instanceof Promise)) ? {} : v;
const ALL_POOLS = { pokemon: true, amongus: true, chat: true, normal: true, rpg: true };
const NO_POOLS = { pokemon: false, amongus: false, chat: false, normal: false, rpg: false };

async function freshWorld(setup = {}) {
    Object.assign(botState, JSON.parse(JSON.stringify(initial)), { _groupOrderChain: Promise.resolve(), _pgPool: null, _pgReady: null });
    for (const c of [groupMetaCache, groupPrefixCache, presenceCache, lidMap]) for (const k of Object.keys(c)) delete c[k];
    const pool = makePool();
    await setupCommandsTables(pool);
    pool.raw.exec(`CREATE TABLE IF NOT EXISTS bot_auth (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                   CREATE TABLE IF NOT EXISTS players (sender TEXT PRIMARY KEY, jid TEXT, lid TEXT);
                   CREATE TABLE IF NOT EXISTS users (phone TEXT PRIMARY KEY, username TEXT NOT NULL, password_hash TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)`);
    botState._pgPool = pool; botState._pgReady = Promise.resolve();
    const linked = setup.linked ?? [J.GROUP];
    botState.allowedGroups = [...linked];
    for (const g of linked) botState.groupPools[g] = { ...(setup.pools ?? ALL_POOLS) };
    for (const [g, p] of Object.entries(setup.groupPools ?? {})) botState.groupPools[g] = { ...p };
    for (const r of setup.ranks ?? [])
        await pool.query('INSERT INTO bot_ranks (jid, phone, lid, rank, group_jid, granted_by) VALUES ($1,$2,$3,$4,$5,$6)',
                         [r.jid, r.jid.split('@')[0], null, r.rank, r.group ?? null, J.KING]);
    const rows = (x) => typeof x === 'function' ? x(H.nowMs()) : (x ?? []);
    for (const r of rows(setup.cmdRanks)) await pool.query('INSERT INTO command_ranks (cmd, min_rank, assigned_by) VALUES ($1,$2,$3)', [r.cmd, r.rank, J.KING]);
    for (const r of rows(setup.customRanks)) await pool.query('INSERT INTO custom_ranks (name, level, created_by) VALUES ($1,$2,$3)', [r.name, r.level, J.KING]);
    if (setup.customRanks) await CMD.loadCustomRanks(pool);
    for (const w of rows(setup.warnings)) await pool.query('INSERT INTO warnings (group_jid, user_jid, count, warned_by) VALUES ($1,$2,$3,$4)', [w.group ?? J.GROUP, w.jid, w.count, J.KING]);
    for (const d of rows(setup.activityDaily)) await pool.query('INSERT INTO activity_daily (group_jid, user_jid, day, msg_count) VALUES ($1,$2,$3,$4)', [d.group ?? J.GROUP, d.jid, d.day, d.count]);
    for (const d of rows(setup.activityCounts)) await pool.query('INSERT INTO activity_counts (group_jid, user_jid, msg_count) VALUES ($1,$2,$3)', [d.group ?? J.GROUP, d.jid, d.count]);
    for (const s of rows(setup.settings)) await pool.query('INSERT INTO group_settings (group_jid, welcome_msg, leave_msg, rules, prefix, antilink, active_threshold) VALUES ($1,$2,$3,$4,$5,$6,$7)',
        [s.group ?? J.GROUP, s.welcome ?? null, s.leave ?? null, s.rules ?? null, s.prefix ?? null, s.antilink ?? null, s.threshold ?? null]);
    for (const p of setup.players ?? []) await pool.query('INSERT INTO players (sender) VALUES ($1)', [p]);
    Object.assign(lidMap, setup.lidMap ?? {});
    for (const m of setup.moderation ?? [])
        await pool.query('INSERT INTO moderation (group_jid, user_jid, muted, ignored) VALUES ($1,$2,$3,$4)', [m.group ?? J.GROUP, m.jid, !!m.muted, !!m.ignored]);
    for (const [k, v] of Object.entries(setup.state ?? {})) botState[k] = v;
    delete globalThis._tttGames; delete globalThis._notes; delete globalThis._tttGames;
    delete process.env.GEMINI_API_KEY; golden.manifest = setup.manifest ? JSON.parse(JSON.stringify(setup.manifest)) : null;
    if (setup.env) for (const [k, v] of Object.entries(setup.env)) process.env[k] = v;
    const groups = { [J.GROUP]: groupMeta(J.GROUP), [J.GROUP2]: groupMeta(J.GROUP2), [J.GROUP3]: groupMeta(J.GROUP3), ...(setup.groups ?? {}) };
    const sock = makeSock(groups, setup.fetchAll ?? groups);
    botState.activeSockRef = sock; botState._currentSock = sock;
    return sock;
}

const results = {};
let clock = H.BASE_TIME;

// Let fire-and-forget work (unawaited sends, real file reads, ...) from the step that just ran finish BEFORE the
// log is read, otherwise it would leak into the next step's log and make results depend on real I/O timing.
const settle = async () => { for (let i = 0; i < 8; i++) await new Promise(r => H.realSetImmediate(r)); await new Promise(r => H.realSetTimeout(r, 1)); };

async function runScenario(name, setup, steps) {
    clock = H.BASE_TIME + (H.hashSeed(name) % 20000) * 3600_000;   // own hour per scenario, from its NAME (adding scenarios never shifts the others)
    H.setClock(clock);
    const sock = await freshWorld(setup);
    await settle();
    for (let i = 0; i < steps.length; i++) {
        const st = steps[i];
        if (st.advance) { H.advanceClock(st.advance); continue; }
        if (st.call) {          // direct call of an exported function (events the message handler never sees)
            golden.log.length = 0; H.seedRandom(H.hashSeed(`${name}#${i}`)); golden.fault = st.fault ?? null;
            const chat = st.chat ?? J.GROUP;
            const ctx = { sock, db: botState._pgPool, chatJid: chat, groupParticipants: st.noParticipants ? [] : groupMeta(chat).participants, ...(st.ctx ?? {}) };
            let exc = null, ret;
            try { ret = await CMD[st.call](...st.args.map(a => a === '$ctx' ? ctx : a === '$db' ? botState._pgPool : a === '$sock' ? sock : a)); } catch (e) { exc = `${e?.constructor?.name}: ${String(e?.message).slice(0, 100)}`; }
            await settle();
            const body = JSON.stringify({ log: golden.log, ret: H.norm(ret), exc });
            results[`${name}|${i}|call:${st.call}`] = { h: H.sha(body), n: golden.log.length, s: body.slice(0, 380) };
            continue;
        }
        golden.log.length = 0;
        H.seedRandom(H.hashSeed(`${name}#${i}`));
        golden.fault = st.fault ?? null; H.forceRandom(st.random ?? null);
        const msg = mkMsg(st);
        let exc = null;
        try {
            await Promise.race([handleMessage(sock, msg), new Promise((_, rej) => H.realSetTimeout(() => rej(new Error('TIMEOUT')), 4000))]);
        } catch (e) { exc = `${e?.constructor?.name}: ${String(e?.message).slice(0, 100)}`; }
        await settle();
        const body = JSON.stringify({ log: golden.log, exc });
        results[`${name}|${i}|${(st.text ?? `<${st.kind}>`).slice(0, 60)}`] = { h: H.sha(body), n: golden.log.length, s: body.slice(0, 380) };
        if (DUMP) DUMP[`${name}|${i}|${(st.text ?? `<${st.kind}>`).slice(0, 60)}`] = body;
    }
}

// =============================================================================================================
// Scenario matrix
// =============================================================================================================
const RANKS = [{ jid: J.QUEEN, rank: 'queen' }, { jid: J.ADMIN, rank: 'prince' }, { jid: J.U3, rank: 'baron' }];
const CONTEXTS = {
    member_all:  { setup: { ranks: RANKS }, from: J.U1 },
    member_none: { setup: { ranks: RANKS, pools: NO_POOLS }, from: J.U1 },
    member_poke: { setup: { ranks: RANKS, pools: { ...NO_POOLS, pokemon: true } }, from: J.U1 },
    member_norm: { setup: { ranks: RANKS, pools: { ...NO_POOLS, normal: true } }, from: J.U1 },
    member_rpg:  { setup: { ranks: RANKS, pools: { ...NO_POOLS, rpg: true } }, from: J.U1 },
    member_amg:  { setup: { ranks: RANKS, pools: { ...NO_POOLS, amongus: true } }, from: J.U1 },
    king_all:    { setup: { ranks: RANKS }, from: J.KING },
    king_none:   { setup: { ranks: RANKS, pools: NO_POOLS }, from: J.KING },
    queen_all:   { setup: { ranks: RANKS }, from: J.QUEEN },
    prince_all:  { setup: { ranks: RANKS }, from: J.ADMIN },
    baron_all:   { setup: { ranks: RANKS }, from: J.U3 },
    unlinked:    { setup: { ranks: RANKS, linked: [J.GROUP] }, from: J.U1, chat: J.GROUP2 },
    king_unlink: { setup: { ranks: RANKS, linked: [J.GROUP] }, from: J.KING, chat: J.GROUP2 },
    dm_on:       { setup: { ranks: RANKS, state: { chatDmOn: true } }, from: J.U1, chat: J.U1 },
    dm_off:      { setup: { ranks: RANKS, state: { chatDmOn: false } }, from: J.U1, chat: J.U1 },
    king_dm:     { setup: { ranks: RANKS, state: { chatDmOn: true } }, from: J.KING, chat: J.KING },
    silent_grp:  { setup: { ranks: RANKS, state: { silentPoolOn: true, silentGroups: [J.GROUP], silentChatGroups: [J.GROUP] } }, from: J.U1 },
    king_silent: { setup: { ranks: RANKS, state: { silentPoolOn: true, silentGroups: [J.GROUP], silentChatGroups: [J.GROUP] } }, from: J.KING },
};
const cmdlib = JSON.parse(fs.readFileSync(path.join(HERE, '..', '..', 'cmdlibrary.json'), 'utf8'));
// The command list is FROZEN in tests/golden/handler_cmds.json so the scenario set never depends on how the source files
// are laid out (it was harvested once from handler.js/commands.js/... plus cmdlibrary.json; regenerate with --regen-cmds
// ONLY when you add a command and are re-recording the golden anyway).
const CMDS_FILE = path.join(HERE, '..', 'golden', 'handler_cmds.json');
const EXTRA = ['.', '.nonexistentcmd', '.MENU', '.Ping', '.rpg on', '.rpg off', '.silent on', '.silent off', '.chatdm on', '.chatdm off', '.pokemon on', '.pokemon off', '.normal on', '.normal off', '.rpg state'];
function harvestCmds(files) {
    const found = new Set();
    for (const f of files) for (const m of fs.readFileSync(f, 'utf8').matchAll(/'(\.[a-z][a-z0-9]{0,14})'/g)) found.add(m[1]);
    return [...new Set([...found, ...Object.keys(cmdlib.commands ?? cmdlib), ...EXTRA])].sort();
}
let CMDS;
if (process.argv.includes('--regen-cmds')) {
    const B = path.join(HERE, '..', '..', 'bot');
    const files = [process.env.HANDLER_SRC ?? 'handler.js', 'commands.js', 'groups.js', 'silent/silent.js', 'silent/mines.js', 'silent/sleep.js', 'work.js', 'chat/stickers.js']
        .map(f => path.isAbsolute(f) ? f : path.join(B, f));
    CMDS = harvestCmds(files);
    fs.writeFileSync(CMDS_FILE, JSON.stringify(CMDS, null, 0));
    H.realConsole.log(`wrote ${CMDS.length} commands to ${CMDS_FILE}`); process.exit(0);
}
CMDS = JSON.parse(fs.readFileSync(CMDS_FILE, 'utf8'));
const VARIANTS = [
    (c) => ({ text: c }),
    (c) => ({ text: `${c} hello world 5` }),
    (c) => ({ text: `${c} @${J.U2.split('@')[0]}`, mentions: [J.U2] }),
    (c) => ({ text: c, quoted: { text: 'quoted words here', from: J.U2 } }),
];
const MATRIX = [];
for (const [cname, c] of Object.entries(CONTEXTS))
    for (const cmd of CMDS)
        VARIANTS.forEach((v, vi) => {
            if (cname.startsWith('member_') && !['member_all', 'member_none'].includes(cname) && vi > 1) return;   // keep size sane
            if (!['member_all', 'king_all', 'queen_all', 'member_none', 'dm_on', 'dm_off', 'king_unlink', 'unlinked'].includes(cname) && vi > 0 && cmd.length % 3 !== 0) return;
            const spec = { from: c.from, chat: c.chat ?? J.GROUP, ...v(cmd) };
            MATRIX.push([`m:${cname}:v${vi}:${cmd}`, c.setup, [spec]]);
        });

// =============================================================================================================
// Hand-written multi-step scenarios (state carries from step to step)
// =============================================================================================================
const SCEN = [];
const g = (text, o = {}) => ({ text, from: J.U1, chat: J.GROUP, ...o });
const k = (text, o = {}) => ({ text, from: J.KING, chat: J.GROUP, ...o });
const SETUP = { ranks: RANKS };
const hdr = (n, setup, steps) => SCEN.push([`s:${n}`, setup, steps]);

hdr('mute_flow', SETUP, [k('.mute @' + J.U2.split('@')[0], { mentions: [J.U2] }), g('hello', { from: J.U2 }), g('.menu', { from: J.U2 }), g('.sticker', { from: J.U2 }),
    g('.meme', { from: J.U2 }), g('.play song', { from: J.U2 }), g('.status', { from: J.U2 }), k('.unmute @' + J.U2.split('@')[0], { mentions: [J.U2] }), g('.menu', { from: J.U2 })]);
hdr('ignore_flow', SETUP, [k('.ignore @' + J.U2.split('@')[0], { mentions: [J.U2] }), g('.menu', { from: J.U2 }), g('.sticker', { from: J.U2 }), g('.meme', { from: J.U2 }),
    g('.status', { from: J.U2 }), k('.unignore @' + J.U2.split('@')[0], { mentions: [J.U2] }), g('.menu', { from: J.U2 })]);
hdr('mute_via_seed', { ranks: RANKS, moderation: [{ jid: J.U2, muted: true }] }, [g('.sticker', { from: J.U2 }), g('.meme', { from: J.U2 }), g('.menu', { from: J.U2 }), g('.status', { from: J.U2 }), g('.take', { from: J.U2 }), g('.pint cats', { from: J.U2 })]);
hdr('ignore_via_seed', { ranks: RANKS, moderation: [{ jid: J.U2, ignored: true }] }, [g('.sticker', { from: J.U2 }), g('.meme', { from: J.U2 }), g('.menu', { from: J.U2 }), g('hi', { from: J.U2 })]);
hdr('antilink_on', SETUP, [k('.antilink on'), g('visit https://evil.example/x now', { from: J.U2 }), g('.sticker https://evil.example', { from: J.U2 }),
    g('.meme https://evil.example', { from: J.U2 }), k('visit https://ok.example'), g('www.evil.example', { from: J.U2 }), k('.antilink off'), g('https://evil.example', { from: J.U2 })]);
hdr('warn_flow', SETUP, [k('.warn @' + J.U2.split('@')[0], { mentions: [J.U2] }), k('.warn @' + J.U2.split('@')[0], { mentions: [J.U2] }), k('.warnings @' + J.U2.split('@')[0], { mentions: [J.U2] }),
    k('.warn @' + J.U2.split('@')[0], { mentions: [J.U2] }), k('.warnings'), k('.clearwarns @' + J.U2.split('@')[0], { mentions: [J.U2] }), k('.warnings @' + J.U2.split('@')[0], { mentions: [J.U2] })]);
hdr('rank_flow', SETUP, [k('.crown @' + J.U2.split('@')[0], { mentions: [J.U2] }), g('.rank', { from: J.U2 }), k('.promote @' + J.U2.split('@')[0], { mentions: [J.U2] }), k('.demote @' + J.U2.split('@')[0], { mentions: [J.U2] }),
    k('.dethrone @' + J.U2.split('@')[0], { mentions: [J.U2] }), k('.ranks'), k('.new rank Bard 55'), k('.delrank Bard'), k('.ascmd .menu lord'), g('.menu', { from: J.U2 }), k('.ascmd .menu king'), g('.menu', { from: J.U2 })]);
hdr('pool_toggles', { ranks: RANKS, pools: NO_POOLS }, [k('.pokemon on'), g('.status'), k('.pokemon off'), g('.status'), k('.rpg on'), g('.rpg state'), k('.rpg off'), k('.normal on'), g('.ping'), k('.normal off'),
    k('.chat on'), k('.chat off'), k('.amongus on'), k('.amongus off'), g('.pokemon on'), k('.pools'), k('.silent on'), k('.silent off')]);
hdr('link_flow', { ranks: RANKS, linked: [] }, [g('.menu'), k('.linkgc', { chat: J.GROUP }), g('.menu'), k('.groups'), k('.linkedgroups'), k('.ignoregc'), g('.menu'), k('.unignoregc'), k('.unlinkgc'), g('.menu')]);
hdr('group_admin', SETUP, [k('.setwelcome Hello {user}!'), k('.setleave Bye'), k('.setrules Be nice'), g('.rules'), k('.welcome'), k('.setprefix !'), g('!menu'), g('.menu'), k('.setprefix .'),
    k('.tagall hi everyone'), k('.hidetag secret'), k('.broadcast news'), k('.whois @' + J.U2.split('@')[0], { mentions: [J.U2] }), k('.invite'), k('.pin'), k('.kick @' + J.U3.split('@')[0], { mentions: [J.U3] })]);
hdr('activity', SETUP, [g('hello'), g('hello again'), g('more', { from: J.U2 }), g('.active'), g('.inactive'), k('.setactive 5'), g('.online'), g('.activity')]);
hdr('py_replies', SETUP, [g('.pynull'), g('.pytimeout'), g('.pyoutbox'), g('.pysticker'), g('.pyimg'), g('.pyhud'), g('.pylist'), g('.rpg pytimeout', {}), g('.rpg look'), g('.rpg pynull')]);
hdr('lid_sender', SETUP, [g('.status', { from: J.LID1, participantAlt: J.U1 }), g('.menu', { from: J.LID1 }), k('.status', { from: '99900000002@lid', participantAlt: J.KING })]);
hdr('media_kinds', SETUP, [g('.sticker', { kind: 'image' }), g('', { kind: 'sticker' }), g('.toimg', { quoted: { text: '', media: true } }), g('.vv', { quoted: { text: '', media: true } }), g('.take', { quoted: { text: '', media: true } }),
    g('.sticker', { quoted: { text: '', media: true } }), g('.pfp', { mentions: [J.U1] }), g('.mypfp'), g('.gcpfp')]);
hdr('fun_cmds', SETUP, [g('.hug @' + J.U2.split('@')[0], { mentions: [J.U2] }), g('.slap @' + J.U2.split('@')[0], { mentions: [J.U2] }), g('.meme'), g('.joke'), g('.truth'), g('.dare'), g('.wyr'), g('.ship @' + J.U2.split('@')[0] + ' @' + J.U3.split('@')[0], { mentions: [J.U2, J.U3] }),
    g('.ttt @' + J.U2.split('@')[0], { mentions: [J.U2] }), g('.spinbottle'), g('.kidnap @' + J.U2.split('@')[0], { mentions: [J.U2] }), g('.note hello'), g('.translate fr hello'), g('.wallpaper cats'), g('.pint cats'), g('.pint none'), g('.play song'), g('.play fail'), g('.play none')]);
hdr('silent_flow', { ranks: RANKS, state: { silentPoolOn: true } }, [k('.silentlink'), k('.silentchat on'), k('.silentchat off'), k('.label Test'), k('.smenu'), k('.royalmenu'), k('.silentunlink'),
    k('.mine 15551110002 hi 5m'), k('.mines'), k('.unmine 15551110002'), k('.sleep 22:00-06:00'), k('.sleeps'), k('.ssteal'), g('hello', { from: J.U2 })]);
hdr('dm_flow', { ranks: RANKS, state: { chatDmOn: true } }, [g('hello ariel', { chat: J.U1 }), g('.menu', { chat: J.U1 }), g('ariel hi', { chat: J.U1 }), g('hi', { chat: J.U1, quoted: { text: 'x', from: J.BOT } }), g('.chatdm off', { chat: J.U1 }),
    k('.chatdm off', { chat: J.KING }), g('hello ariel', { chat: J.U1 })]);
hdr('dev_cmds', SETUP, [k('.d', { quoted: { text: 'x', from: J.U2 } }), k('.d'), g('.d', { quoted: { text: 'x', from: J.U2 } }), k('.d', { quoted: { text: 'x', from: J.BOT } }), k('.arielstatus'), k('.clearauth'), k('.preview'), k('.btest'), k('.listtest'), k('.gen a cat'), k('.resetgroups'), k('.help menu'), k('.help'), k('.menumenu'), k('.d', { quoted: { text: 'x', from: J.U2 } })]);

// ---- silent-group features (all King-only; groups are addressed by their position in `.groups`) ----
const THREE = { ranks: RANKS, linked: [J.GROUP, J.GROUP2, J.GROUP3], state: { silentPoolOn: true } };
const W = H.jid(NUM.WATCH);
hdr('silent_link_idx', THREE, [k('.silentlink'), k('.silentlink x'), k('.silentlink 9'), k('.silentlink 1'), k('.silentlink 1'), k('.silentlink 2'), k('.silentlink 3'),
    k('.silentunlink'), k('.silentunlink 9'), k('.silentunlink 2'), k('.silentunlink 2'), k('.silentunlink 1', { chat: J.GROUP2 }), k('.silentunlink 3'), k('.silentlink 2', { chat: J.GROUP2 }), k('.groups')]);
hdr('silent_chat_idx', { ...THREE, state: { silentPoolOn: true, silentGroups: [J.GROUP, J.GROUP2] } }, [k('.silentchat on'), k('.silentchat zzz 1'), k('.silentchat on 9'), k('.silentchat on 3'), k('.silentchat on 1'), k('.silentchat on 1'),
    k('.silentchat off 1'), k('.silentchat off 1'), k('.silentchat on 2'), g('.silentchat on 1')]);
hdr('label_flow', { ...THREE, state: { silentPoolOn: true, mineWatchNumber: NUM.WATCH } }, [k('.label'), k('.label Bob'), k('.label'), k('.label none'), k('.label none'), g('.label x')]);
hdr('label_nowatch', { ...THREE, state: { silentPoolOn: true, mineWatchNumber: null } }, [k('.label'), k('.label none'), k('.label Bob'), k('.label')]);
hdr('ssteal_flow', { ...THREE, state: { silentPoolOn: true, silentGroups: [J.GROUP, J.GROUP2] } }, [k('.ssteal'), k('.ssteal none'), k('.ssteal 1'), k('.ssteal 9 15551110002'), k('.ssteal 3 15551110002'), k('.ssteal 1 15551110002'),
    k('.ssteal'), k('.silentsteal 2 15551110003'), k('.ssteal none'), k('.ssteal 1 abc'), g('.ssteal 1 15551110002')]);
hdr('mine_flow', { ...THREE, state: { silentPoolOn: true, silentGroups: [J.GROUP, J.GROUP2] } }, [k('.mine'), k('.mine nonsense'), k('.mine 1 .fish 10s'), k('.mine 1 .work 2m 2'), k('.mine 1 .x 500ms'), k('.mine 9 .x 5s'), k('.mine 3 .x 5s'),
    k('.mines'), k('.mine pause 1'), k('.mine pause 9'), k('.mine pause x'), k('.mines'), k('.mine resume 1'), k('.mine resume 2'), k('.mine pause'), k('.unmine'), k('.unmine 9'), k('.unmine 1'), k('.mines'), k('.unmine 1'), k('.mines'), g('.mine 1 .x 5s')]);
const MINES = [{ id: 'a1', groupJid: J.GROUP, groupLabel: 'Group 001', text: '.fish', intervalMs: 5000, label: 1, paused: true, autoPaused: true, startedAt: 1 },
               { id: 'a2', groupJid: J.GROUP, groupLabel: 'Group 001', text: '.work', intervalMs: 9000, label: 2, paused: false, startedAt: 1 }];
hdr('mine_watch', { ...THREE, state: { silentPoolOn: true, silentGroups: [J.GROUP], activeMines: JSON.parse(JSON.stringify(MINES)) } }, [g('hello', { from: W }), g('.rush 3 .fish', { from: W }), g('.rush', { from: W }), g('hello', { from: J.U1 }), k('.mines'), g('stop', { from: W })]);
hdr('mine_watch_steal', { ...THREE, state: { silentPoolOn: true, silentGroups: [J.GROUP], silentStealConfig: { groupJid: J.GROUP, targetNumber: '15551110002', amount: 5 } } },
    [g('hello', { from: J.U2 }), g('.give 5', { from: J.U2 }), g('hello', { from: J.U1 }), g('hello', { from: W })]);
hdr('sleep_flow', THREE, [k('.sleep'), k('.sleep nonsense'), k('.sleep 11:00am-12:00pm'), k('.sleep 22:00-06:00'), k('.sleeps'), k('.unsleep'), k('.unsleep 9'), k('.unsleep x'), k('.unsleep 1'), k('.sleeps'), k('.unsleep 1'), k('.sleeps'), g('.sleep 1:00-2:00')]);
hdr('silent_watch_chat', { ...THREE, state: { silentPoolOn: true, silentPoolOn: true, silentGroups: [J.GROUP], silentChatGroups: [J.GROUP] } }, [g('hello there', { from: W }), g('how are you', { from: J.U1 }), g('ariel what do you think', { from: J.U1 }), g('hi', { from: W }), g('.work', { from: W }), g('.card', { from: W }), g('.work', { from: J.KING }), g('.card', { from: J.KING }), g('.watch 123', { from: J.KING })]);

// ---- games, notes, stickers, media, group admin by index, identity resolution ----
const at = (n) => '@' + J[n].split('@')[0];
const SK = (o = {}) => ({ quoted: { kind: 'sticker', from: J.U2 }, ...o });
hdr('ttt_win', SETUP, [g('.ttt'), g('.ttt', { from: J.U2 }), g('.ttt 1'), g('.ttt 4', { from: J.U2 }), g('.ttt 1', { from: J.U2 }), g('.ttt 2'), g('.ttt 5', { from: J.U2 }), g('.ttt 3'), g('.ttt 6')]);
hdr('ttt_draw', SETUP, [g('.ttt'), g('.ttt', { from: J.U2 }), g('.ttt 1'), g('.ttt 2', { from: J.U2 }), g('.ttt 3'), g('.ttt 5', { from: J.U2 }), g('.ttt 4'), g('.ttt 6', { from: J.U2 }), g('.ttt 8'), g('.ttt 7', { from: J.U2 }), g('.ttt 9')]);
hdr('ttt_misc', SETUP, [g('.ttt 5'), g('.ttt'), g('.ttt 5'), g('.ttt', { from: J.U2 }), g('.ttt 5', { from: J.U3 }), g('.ttt', { from: J.U3 }), g('.ttt 5', { from: J.U2 }), g('.ttt x'), g('.ttt 0'), g('.ttt 10'), g('.ttt reset'), g('.ttt 5'), g('.ttt')]);
hdr('notes', SETUP, [g('.note'), g('.notes'), g('.note first\nsecond line'), g('.note second'), g('.notes'), g('.notes 1'), g('.notes 9'), g('.notes x'), g('.delnote 1'), g('.delnote 9'), g('.delnote'), g('.notes', { from: J.U2 }),
    g('.pnote shared'), g('.pnotes', { from: J.U2 }), g('.pnotes 1', { from: J.U2 }), g('.delpnote 1', { from: J.U2 }), g('.pnotes'), g('.editnote 1'), g('.editpnote 1'),
    ...Array.from({ length: 51 }, (_, i) => g(`.note n${i}`))]);
hdr('take_flow', { ...SETUP, manifest: { ariel: 'ariel/f.webp', happy: 'happy/1.webp' } }, [g('.take'), g('.take happy'), g('.take happy', SK()), g('.take', SK()), g('.take !!!', SK()), g('.take hapy', SK()), g('.take hapy confirm', SK()),
    g('.take sad', SK()), g('.take sad again', SK()), g('.take happy extra words', SK()), g('.arielstickers'), g('.delpack'), g('.delpack happy'), g('.delpack nope'), g('.delpack ariel'), g('.resetstickers'), g('.resetstickers confirm'), g('.arielstickers')]);
hdr('take_empty', SETUP, [g('.take happy', SK()), g('.arielstickers'), g('.resetstickers'), g('.resetstickers confirm'), g('.delpack happy')]);
hdr('toimg_vv', SETUP, [g('.toimg'), g('.toimg', SK()), g('.toimg', { quoted: { kind: 'image' } }), g('.vv'), g('.vv', { quoted: { kind: 'image' } }), g('.vv', { quoted: { kind: 'video' } }), g('.vv', { quoted: { kind: 'audio' } }), g('.vv', { quoted: { kind: 'viewonce' } }),
    g('.vv', { quoted: { kind: 'sticker' } }), k('.vv', { quoted: { kind: 'viewonce' } }), k('.vv'), { ...g('.vv', { from: J.QUEEN }), quoted: { kind: 'image' } }]);
hdr('translate_etc', SETUP, [g('.translate'), g('.translate hello'), g('.translate fr hello'), g('.tt hello world'), g('.tt fail'), g('.wallpaper'), g('.wallpaper cats'), g('.wallpaper none'), g('.pint'), g('.pint cats'), g('.pint none'),
    g('.play'), g('.play song'), g('.play song file'), g('.play none'), g('.play fail'), g('.meme'), g('.triggered'), g('.triggered', { quoted: { kind: 'image' } }), g('.joke'), g('.truth'), g('.dare'), g('.wyr'), g('.hug'), g('.hug ' + at('U2'), { mentions: [J.U2] }), g('.pat none')]);
hdr('gen_flow', { ...SETUP, env: { GEMINI_API_KEY: 'test-key' } }, [g('.gen'), g('.gen a red cat'), g('.gen again quickly'), { advance: 20000 }, g('.gen fail please'), { advance: 20000 }, g('.gen a blue dog')]);
hdr('gen_nokey', SETUP, [g('.gen'), g('.gen a red cat')]);
hdr('gc_by_index', { ranks: RANKS, linked: [J.GROUP], state: {} }, [k('.linkgc 2'), k('.linkgc 2'), k('.linkgc 9'), k('.linkgc x'), k('.linkgc'), k('.unlinkgc 2'), k('.unlinkgc 2'), k('.unlinkgc 9'), k('.ignoregc 3'), k('.linkgc 3'), k('.ignoregc 3'), k('.ignoregc 3'),
    k('.unignoregc 3'), k('.unignoregc 3'), k('.ignoregc 1'), g('.status'), k('.unignoregc 1'), k('.ignore'), k('.unignore'), k('.ignore', { chat: J.U1 }), k('.linkgc 2', { chat: J.KING }), g('.linkgc 2'), { ...g('.linkgc 2', { from: J.QUEEN }) }, g('.ignoregc 2', { from: J.ADMIN })]);
hdr('unlink_here', { ranks: RANKS, linked: [J.GROUP, J.GROUP2] }, [k('.unlinkgc 1'), g('.status'), k('.linkgc 1', { chat: J.GROUP2 }), k('.ignoregc 1', { chat: J.GROUP2 }), g('.status')]);
hdr('groups_empty', { ...SETUP, fetchAll: {}, state: { silentPoolOn: true } }, [k('.groups'), k('.linkedgroups'), k('.silentlink 1'), k('.linkgc 1'), k('.mine 1 .x 5s')]);
hdr('silentunlink_mines', { ...THREE, state: { silentPoolOn: true, silentGroups: [J.GROUP, J.GROUP2], silentChatGroups: [J.GROUP], activeMines: JSON.parse(JSON.stringify(MINES)) } }, [k('.silentunlink 1'), k('.mines'), k('.silentunlink 2'), k('.silentunlink 1', { chat: J.GROUP2 })]);
hdr('hidetag_bc', { ...SETUP, state: { silentPoolOn: true } }, [g('.hidetag hi'), k('.hidetag'), k('.hidetag hello all'), k('.hidetag', { quoted: { text: 'quoted text' } }), k('.hidetag THROWSEND'), g('.broadcast hi'), k('.broadcast'), k('.broadcast news flash'), k('.broadcast', { quoted: { text: 'q' } }), k('.broadcast THROWSEND'),
    { ...g('.hidetag hey', { from: J.QUEEN }) }, { ...g('.broadcast hey', { from: J.QUEEN }) }]);
hdr('pfp_dm', { ...SETUP, state: { chatDmOn: true } }, [g('.mypfp', { chat: J.U1 }), g('.pfp', { chat: J.U1 }), g('.gcpfp', { chat: J.U1 }), g('.pfp ' + at('U2'), { mentions: [J.U2] }), g('.pfp ' + at('U1'), { mentions: [J.U1] }),
    g('.gcpfp'), g('.mypfp'), g('.pfp', { quoted: { text: 'q', from: J.U1 } }), g('.pfp', { quoted: { text: 'q', from: J.U3 } }), g('.mypfp', { from: J.U3 })]);
const LIDMETA = { id: J.GROUP, subject: 'Group 001', participants: [
    { id: '99900000011@lid', lid: '99900000011@lid', phoneNumber: J.U1 }, { id: '99900000012@lid', lid: '99900000012@lid', phoneNumber: J.U2 }, { id: '99900000013@lid', lid: '99900000013@lid' },
    { id: J.KING, admin: 'superadmin' }, { id: J.BOT, admin: 'admin' }] };
hdr('lid_resolution', { ...SETUP, groups: { [J.GROUP]: LIDMETA } }, [g('.status', { from: '99900000011@lid' }), g('.status', { from: '99900000013@lid' }), g('.status', { from: '99900000077@lid' }), g('.status', { from: '99900000011@lid' }),
    g('.hug x', { mentions: ['99900000012@lid'] }), g('.hug x', { mentions: ['99900000099@lid'] }), g('.hug x', { quoted: { text: 'q', from: '99900000012@lid' } }), g('.hug x', { quoted: { text: 'q', from: '99900000099@lid' } }),
    g('.hug x', { mentions: ['bogus'] }), g('', { kind: 'image', from: '99900000011@lid' }), g('.status', { from: '99900000011@lid', participantAlt: J.U1 })]);
hdr('caption_work', { ...SETUP, state: { silentPoolOn: true, silentGroups: [J.GROUP] } }, [g('.work', { kind: 'image' }), g('', { kind: 'image' }), g('.card', { kind: 'image', from: J.KING }), g('.work', { kind: 'image', from: H.jid(NUM.WATCH) }),
    g('.work', { kind: 'image', from: '99900000011@lid' })]);
hdr('reply_to_bot', SETUP, [g('thanks', { quoted: { text: 'hi there', from: J.BOT } }), g('.status', { quoted: { text: 'hi there', from: J.BOT } }), g('ariel hello'), g('Ariel what is up'), g('hey ariel!'), g('arielle', {}), g('thanks', { quoted: { text: 'x', from: J.U2 } })]);
hdr('silent_idle_chat', { ...THREE, state: { silentPoolOn: true, silentGroups: [J.GROUP], silentChatGroups: [J.GROUP] } }, [...Array.from({ length: 24 }, (_, i) => g(`just chatting ${i}`, { from: i % 2 ? J.U1 : J.U2 })), g('hello', { from: H.jid(NUM.WATCH) })]);
hdr('king_silent_work', { ...THREE, state: { silentPoolOn: true } }, [k('.work'), k('.card'), k('.watch 5'), k('.swork'), k('.scard'), g('.work'), k('.work x y')]);
hdr('fault_paths', { ...SETUP, linked: [J.GROUP, J.GROUP4 ?? '120363000000000004@g.us'] }, [k('.groups', { chat: '120363000000000004@g.us' }), g('.status', { chat: '120363000000000004@g.us' }), k('.tagall hi', { chat: '120363000000000004@g.us' }), k('.hidetag x', { chat: '120363000000000004@g.us' }),
    k('.meme THROWSEND'), g('.joke THROWSEND'), k('.mypfp', { chat: '120363000000000004@g.us' })]);

// ---- error paths (fault injection) and a few remaining gated branches ----
hdr('faults', { ...SETUP, state: { silentPoolOn: true } }, [
    g('.meme', { fault: 'fetch' }), g('.triggered', { fault: 'fetch' }), g('.hug ' + at('U2'), { mentions: [J.U2], fault: 'fetch' }), g('.joke', { fault: 'fetch' }), g('.truth', { fault: 'fetch' }), g('.dare', { fault: 'fetch' }), g('.wyr', { fault: 'fetch' }),
    g('.translate fr hi', { fault: 'fetch' }), g('.wallpaper cats', { fault: 'fetch' }), g('.pint cats', { fault: 'pin' }), g('.pint invalid'), g('.pint THROWSEND'), g('.play x', { fault: 'yts' }), g('.play x', { fault: 'download' }),
    k('.preview', { fault: 'thumb' }), k('.preview'), g('.toimg', SK({ fault: 'download' })), g('.toimg', SK()), k('.vv', { quoted: { kind: 'video' } }), k('.vv', { quoted: { kind: 'audio' } }), k('.vv', { quoted: { kind: 'image' }, fault: 'download' }),
    g('.take faulty', SK({ fault: 'download' })), g('.status', { fault: 'python' }), g('hello ariel', { fault: 'python' }), g('.rpg look', { fault: 'python' }), g('.pyoutbox THROWSEND'), k('.broadcast news flash'), k('.broadcast THROWSEND'), k('.hidetag THROWSEND')]);
hdr('gen_faults', { ...SETUP, env: { GEMINI_API_KEY: 'test-key' } }, [g('.gen failgen'), { advance: 20000 }, g('.gen noimage'), { advance: 20000 }, g('.gen ok', { fault: 'fetch' }), { advance: 20000 }, g('.gen ok')]);
hdr('reply_to_bot_lid', { ...SETUP, lidMap: { '99900000099@lid': J.BOT } }, [g('thanks', { quoted: { text: 'x', from: '99900000099@lid' } }), g('thanks', { quoted: { text: 'x', from: '99900000098@lid' } }), g('.status', { quoted: { text: 'x', from: '99900000099@lid' } })]);
hdr('registered_lid', { ...SETUP, groups: { [J.GROUP]: LIDMETA }, players: [J.U1] }, [g('.status', { from: '99900000011@lid' }), g('.status'), g('.menu', { from: '99900000012@lid' })]);
hdr('silent_idle_rand', { ...THREE, state: { silentPoolOn: true, silentGroups: [J.GROUP], silentChatGroups: [J.GROUP] } }, [g('chat one', { from: J.U2, random: 0 }), g('chat two', { from: J.U1, random: 0.001 }), g('chat three', { random: 0.999 }), g('chat four', { from: H.jid(NUM.WATCH), random: 0 }), g('.status', { random: 0 })]);

// ---- commands.js: ranks, moderation, antilink, group settings, activity, invites, spawn, direct event calls ----
const T = (n) => at(n);
const ARANKS = [...RANKS, { jid: J.U2, rank: 'jester', group: J.GROUP }, { jid: J.U2, rank: 'baron' }, { jid: J.U1, rank: 'baron', group: J.GROUP }];
hdr('crown_flow', SETUP, [k('.crown'), k('.crown queen'), k('.crown nonsense ' + T('U2'), { mentions: [J.U2] }), k('.crown queen ' + T('U2'), { mentions: [J.U2] }), k('.crown queen ' + T('U2'), { mentions: [J.U2] }),
    k('.crown prince ' + T('U2'), { mentions: [J.U2] }), k('.crown lord ' + T('U3'), { mentions: [J.U3] }), k('.crown jester ' + T('U1'), { mentions: [J.U1] }), k('.crown duke ' + T('QUEEN'), { mentions: [J.QUEEN] }),
    k('.crown princess ' + T('KING'), { mentions: [J.KING] }), k('.crown duchess ' + T('BOT'), { mentions: [J.BOT] }), k('.ranks'), k('.crown', { quoted: { text: 'x', from: J.U2 } }), k('.crown lord', { quoted: { text: 'x', from: J.U2 } }),
    { ...g('.crown queen ' + T('U3'), { from: J.QUEEN, mentions: [J.U3] }) }, { ...g('.crown prince ' + T('U3'), { from: J.QUEEN, mentions: [J.U3] }) }, g('.crown prince ' + T('U3'), { mentions: [J.U3] }), { ...g('.crown lord ' + T('U2'), { from: J.ADMIN, mentions: [J.U2] }) }]);
hdr('dethrone_flow', { ranks: ARANKS }, [k('.dethrone'), k('.dethrone ' + T('U2'), { mentions: [J.U2] }), k('.dethrone ' + T('U2'), { mentions: [J.U2] }), k('.dethrone ' + T('U3'), { mentions: [J.U3] }), k('.dethrone ' + T('U1'), { mentions: [J.U1] }),
    k('.dethrone ' + T('QUEEN'), { mentions: [J.QUEEN] }), k('.dethrone ' + T('KING'), { mentions: [J.KING] }), k('.dethrone ' + T('U2'), { mentions: [J.U2] }), { ...g('.dethrone ' + T('U3'), { from: J.QUEEN, mentions: [J.U3] }) }, { ...g('.dethrone ' + T('QUEEN'), { from: J.ADMIN, mentions: [J.QUEEN] }) },
    g('.dethrone ' + T('U3'), { mentions: [J.U3] }), k('.dethrone', { quoted: { text: 'x', from: J.U1 } })]);
hdr('promote_demote', { ranks: ARANKS }, [k('.promote'), k('.promote ' + T('U2'), { mentions: [J.U2] }), k('.promote ' + T('U3'), { mentions: [J.U3] }), k('.promote ' + T('KING'), { mentions: [J.KING] }), k('.promote ' + T('U1'), { mentions: [J.U1] }), k('.promote ' + T('BOT'), { mentions: [J.BOT] }),
    k('.demote'), k('.demote ' + T('U3'), { mentions: [J.U3] }), k('.demote ' + T('U1'), { mentions: [J.U1] }), k('.demote ' + T('U2'), { mentions: [J.U2] }), k('.demote ' + T('KING'), { mentions: [J.KING] }), k('.demote ' + T('U2'), { mentions: [J.U2] }),
    g('.promote ' + T('U2'), { mentions: [J.U2] }), g('.demote ' + T('U3'), { mentions: [J.U3] }), { ...g('.promote ' + T('U2'), { from: J.U3, mentions: [J.U2] }) }, { ...g('.demote ' + T('U2'), { from: J.ADMIN, mentions: [J.U2] }) }]);
hdr('rank_seeds', { ranks: ARANKS, customRanks: [{ name: 'bard', level: 55 }, { name: 'sage', level: 65 }], cmdRanks: [{ cmd: '.menu', rank: 'lord' }, { cmd: '.status', rank: 'baron' }, { cmd: '.joke', rank: 'nosuchrank' }] },
    [g('.menu'), g('.menu', { from: J.U3 }), g('.menu', { from: J.QUEEN }), g('.status'), g('.status', { from: J.U3 }), g('.joke'), k('.crown bard ' + T('U3'), { mentions: [J.U3] }), k('.crown sage ' + T('U2'), { mentions: [J.U2] }), g('.rank', { from: J.U2 }), g('.rank', { from: J.U3 }), g('.ranks'), g('.rank ' + T('U1'), { mentions: [J.U1] }), k('.rank', { quoted: { text: 'x', from: J.U2 } })]);
hdr('newrank_delrank', SETUP, [k('.new'), k('.new rank'), k('.new rank bard'), k('.new rank b 50'), k('.new rank bard 100'), k('.new rank bard 0'), k('.new rank bard x'), k('.new rank king 50'), k('.new rank bard 55'), k('.new rank bard 55'), k('.new rank scout 95'),
    k('.crown bard ' + T('U2'), { mentions: [J.U2] }), k('.delrank'), k('.delrank king'), k('.delrank nothere'), k('.delrank bard'), k('.delrank bard'), k('.new rank sage 65'), { ...g('.new rank herald 95', { from: J.QUEEN }) }, { ...g('.new rank herald 60', { from: J.QUEEN }) },
    { ...g('.delrank sage', { from: J.QUEEN }) }, { ...g('.delrank herald', { from: J.QUEEN }) }, g('.new rank x 5'), g('.delrank herald'), { ...g('.new rank sprite 20', { from: J.U3 }) }]);
hdr('warn_limit', SETUP, [k('.warn'), k('.warn ' + T('U2'), { mentions: [J.U2] }), k('.warn ' + T('U2'), { mentions: [J.U2] }), k('.warn ' + T('U2'), { mentions: [J.U2] }), k('.warn ' + T('U2'), { mentions: [J.U2] }), k('.warnings ' + T('U2'), { mentions: [J.U2] }),
    k('.warn ' + T('KING'), { mentions: [J.KING] }), k('.warn ' + T('QUEEN'), { mentions: [J.QUEEN] }), g('.warn ' + T('U2'), { mentions: [J.U2] }), { ...g('.warn ' + T('U1'), { from: J.U3, mentions: [J.U1] }) }, k('.warnings'), k('.clearwarns'), k('.clearwarns ' + T('U2'), { mentions: [J.U2] }), k('.warnings ' + T('U2'), { mentions: [J.U2] })]);
hdr('warn_seeded', { ranks: RANKS, warnings: [{ jid: J.U2, count: 2 }, { jid: J.U1, count: 3 }] }, [k('.warn ' + T('U2'), { mentions: [J.U2] }), k('.warnings ' + T('U1'), { mentions: [J.U1] }), k('.warnings ' + T('U2'), { mentions: [J.U2] }), k('.warn ' + T('U1'), { mentions: [J.U1] })]);
const NOBOT = { id: J.GROUP, subject: 'Group 001', participants: groupMeta(J.GROUP).participants.filter(p => p.id !== J.BOT) };
hdr('lock_flow', SETUP, [k('.close'), k('.open'), k('.close', { chat: J.U1 }), g('.close'), { ...g('.close', { from: J.U3 }) }, k('.lock'), k('.unlock'), k('.mute all'), k('.unmute all')]);
hdr('lock_nobot', { ...SETUP, groups: { [J.GROUP]: NOBOT } }, [k('.close'), k('.open'), k('.kick ' + T('U2'), { mentions: [J.U2] }), k('.antilink on'), g('https://x.example', { from: J.U2 })]);
hdr('kick_flow', SETUP, [k('.kick'), k('.kick ' + T('U2'), { mentions: [J.U2] }), k('.kick ' + T('KING'), { mentions: [J.KING] }), k('.kick ' + T('QUEEN'), { mentions: [J.QUEEN] }), k('.kick ' + T('BOT'), { mentions: [J.BOT] }), g('.kick ' + T('U2'), { mentions: [J.U2] }),
    { ...g('.kick ' + T('U2'), { from: J.U3, mentions: [J.U2] }) }, k('.kick', { quoted: { text: 'x', from: J.U2 } }), k('.kick ' + T('U2'), { mentions: [J.U2], chat: J.U1 }), k('.add 15551110009'), k('.add'), k('.remove ' + T('U3'), { mentions: [J.U3] })]);
const LINK = (u = J.U2, o = {}) => g('see https://evil.example/x', { from: u, ...o });
hdr('antilink_kick', SETUP, [k('.antilink'), k('.antilink bogus'), k('.antilink kick'), k('.antilink'), LINK(), LINK(J.ADMIN), LINK(J.U3), LINK(J.QUEEN), k('see https://ok.example'), g('www.evil.example', { from: J.U2 }), g('no link here', { from: J.U2 }),
    g('', { kind: 'image', from: J.U2 }), g('x', { from: J.U2, quoted: { text: 'https://a.example' } }), k('.antilink off'), LINK(), k('.antilink delete'), LINK(), k('.antilink on'), LINK()]);
hdr('antilink_warn', SETUP, [k('.antilink warn'), LINK(), LINK(), LINK(), LINK(), k('.warnings ' + T('U2'), { mentions: [J.U2] }), LINK(J.U1), k('.antilink status')]);
hdr('antilink_nobot', { ...SETUP, groups: { [J.GROUP]: NOBOT }, settings: [{ antilink: 'kick' }] }, [LINK(), LINK(J.U1)]);
hdr('antilink_seeded', { ...SETUP, settings: [{ antilink: 'warn' }] }, [LINK(), k('.antilink'), { call: 'getAntilinkMode', args: ['$db', J.GROUP] }, { call: 'getAntilinkMode', args: ['$db', J.GROUP2] }]);
hdr('antilink_direct', { ...SETUP, settings: [{ antilink: 'kick' }] }, [
    { call: 'enforceAntilink', args: [{ sock: '$sock', db: '$db', msg: mkMsg({ text: 'https://x.example', from: J.U2 }), chatJid: J.GROUP, senderJid: J.U2, groupParticipants: groupMeta(J.GROUP).participants }] },
    { call: 'enforceAntilink', args: [{ sock: '$sock', db: '$db', msg: mkMsg({ text: 'https://x.example', from: J.U2, chat: J.U2 }), chatJid: J.U2, senderJid: J.U2, groupParticipants: [] }] },
    { call: 'enforceAntilink', args: [{ sock: '$sock', db: '$db', msg: { ...mkMsg({ text: 'https://x.example', from: J.U2 }), key: { remoteJid: J.GROUP, fromMe: true, id: 'F' } }, chatJid: J.GROUP, senderJid: J.U2, groupParticipants: groupMeta(J.GROUP).participants }] },
    { call: 'messageContainsLink', args: [mkMsg({ text: 'visit https://a.example' })] }, { call: 'messageContainsLink', args: [mkMsg({ text: 'visit a.example/path' })] }, { call: 'messageContainsLink', args: [mkMsg({ text: 'nothing' })] }]);
hdr('prefix_flow', SETUP, [k('.setprefix'), k('.setprefix xx'), k('.setprefix !'), k('!menu'), g('!status'), g('.menu'), k('!setprefix .'), k('.setprefix reset'), k('.setprefix #'), g('#ping'), k('#setprefix reset'), g('.ping')]);
hdr('pin_flow', SETUP, [k('.pin'), k('.pin Important notice'), k('.pin', { quoted: { text: 'quoted', from: J.U2 } }), k('.pin THROWSEND'), k('.pin x', { fault: 'fetch' }), g('.pin hi'), { ...g('.pin hi', { from: J.U3 }) }, k('.pin hi', { chat: J.U1 }), k('.unpin'), k('.pin', { quoted: { text: 'q', from: J.U2 }, fault: 'fetch' })]);
hdr('invite_flow', SETUP, [k('.invite'), k('.invite card'), k('.invite test'), k('.invite', { chat: J.U1 }), g('.invite'), { ...g('.invite', { from: J.U3 }) }, k('.invite', { chat: '120363000000000004@g.us' }), k('.invite card', { chat: '120363000000000004@g.us' }),
    k('.invite', { chat: '120363000000000005@g.us' }), k('.invite test', { chat: '120363000000000005@g.us' }), k('.invite card', { fault: 'fetch' }), k('.invite THROWSEND')]);
hdr('invite_groups', { ...SETUP, linked: [J.GROUP, '120363000000000004@g.us', '120363000000000005@g.us'] }, [k('.invite', { chat: '120363000000000004@g.us' }), k('.invite', { chat: '120363000000000005@g.us' }), k('.invite card', { chat: '120363000000000005@g.us' }), k('.invite test', { chat: '120363000000000004@g.us' })]);
const dayStr = (now, back) => new Date(now - back * 86400000).toISOString().slice(0, 10);
hdr('activity_seeded', { ranks: RANKS, activityDaily: (now) => [...[0, 1, 2, 3, 5, 9].flatMap(b => [{ jid: J.U1, day: dayStr(now, b), count: 12 - b }, { jid: J.U2, day: dayStr(now, b), count: 3 }]), { jid: J.U3, day: dayStr(now, 20), count: 4 }],
    activityCounts: [{ jid: J.U1, count: 50 }, { jid: J.U2, count: 9 }, { jid: J.QUEEN, count: 1 }], settings: [{ threshold: 5 }] },
    [g('.active'), g('.inactive'), g('.activity'), g('.activity ' + T('U1'), { mentions: [J.U1] }), g('.top'), g('.topactive'), k('.setactive 3'), g('.active'), k('.setactive x'), k('.setactive'), g('.active 7'), g('.inactive 7'), g('.active 1'), g('.leaderboard'), g('.lb')]);
hdr('online_admin', { ...SETUP, ranks: [...RANKS, { jid: J.U2, rank: 'baron', group: J.GROUP }, { jid: J.U1, rank: 'baron', group: J.GROUP }] }, [g('.online'), g('.admin'), g('.admins'), g('.online', { chat: '120363000000000004@g.us' }), g('.admin', { chat: '120363000000000004@g.us' }), g('.online', { chat: J.U1 }), k('.admin', { chat: J.U1 })]);
hdr('online_presence', { ...SETUP, state: { chatDmOn: false } }, [g('.online'), g('hello', { from: J.U1 }), g('.online'), g('.online', { from: J.U2 })]);
hdr('spawn_flow', SETUP, [g('.spawn'), g('.spawn pikachu'), g('.spawn none'), g('.spawn fail'), g('.spawn pikachu', { fault: 'fetch' }), g('.spawn a b'), g('.spawnp'), g('.spawnp pikachu'), g('.spawnp none'), g('.spawnp pikachu', { fault: 'fetch' }), k('.spawn pikachu 5'), k('.spawnp pikachu 5')]);
hdr('settings_flow', SETUP, [k('.setwelcome'), k('.setwelcome Hi {user} welcome to {group}'), k('.setleave Bye {user}'), k('.setrules 1. be kind'), g('.rules'), g('.welcome'), k('.setwelcome reset'), k('.setleave reset'), k('.setrules reset'), g('.rules'), { ...g('.setrules x', { from: J.U3 }) }, g('.setrules x'),
    k('.setwelcome off'), k('.setleave off'), k('.welcome'), k('.leave')]);
hdr('member_events', { ranks: RANKS, settings: [{ welcome: 'Welcome {user} to {group}!', leave: 'Bye {user}' }] }, [
    { call: 'onMemberJoin', args: ['$ctx', J.U1] }, { call: 'onMemberJoin', args: ['$ctx', { id: J.U2 }] }, { call: 'onMemberJoin', args: ['$ctx', '99900000011@lid'] }, { call: 'onMemberJoin', args: ['$ctx', J.KING] },
    { call: 'onMemberLeave', args: ['$ctx', J.U1] }, { call: 'onMemberLeave', args: ['$ctx', { jid: J.U2 }] }, { call: 'onMemberLeave', args: ['$ctx', '99900000011@lid'] }, { call: 'onMemberJoin', args: ['$ctx', J.U3], noParticipants: true },
    { call: 'onMemberJoin', args: ['$ctx', J.U1], chat: J.GROUP2 }, { call: 'onMemberLeave', args: ['$ctx', J.U1], chat: J.GROUP2 }, { call: 'onMemberJoin', args: ['$ctx', J.U1], fault: 'fetch', chat: '120363000000000004@g.us' }]);
hdr('member_events_default', SETUP, [{ call: 'onMemberJoin', args: ['$ctx', J.U1] }, { call: 'onMemberLeave', args: ['$ctx', J.U1] }, { call: 'onMemberJoin', args: ['$ctx', J.U2], ctx: { sock: { sendMessage: async () => { throw new Error('boom'); } } } }]);
hdr('lid_rank_cmds', { ...SETUP, groups: { [J.GROUP]: LIDMETA }, ranks: [...RANKS, { jid: '99900000012@lid', rank: 'baron' }] }, [k('.crown lord ' + T('U1'), { mentions: ['99900000011@lid'] }), k('.warn x', { mentions: ['99900000012@lid'] }), k('.promote x', { mentions: ['99900000013@lid'] }), k('.dethrone x', { mentions: ['99900000012@lid'] }),
    k('.kick x', { mentions: ['99900000099@lid'] }), k('.rank', { mentions: ['99900000011@lid'] }), k('.whois x', { mentions: ['99900000011@lid'] }), k('.warnings x', { mentions: ['99900000013@lid'] })]);
hdr('direct_misc', { ranks: ARANKS }, [{ call: 'rankBadge', args: ['king'] }, { call: 'rankBadge', args: ['bard'] }, { call: 'rankBadge', args: [undefined] }, { call: 'getRankLevel', args: ['queen'] }, { call: 'getRankLevel', args: ['nope'] },
    { call: 'canActOn', args: ['king', 'queen'] }, { call: 'canActOn', args: ['queen', 'king'] }, { call: 'canActOn', args: ['baron', 'baron'] }, { call: 'canActOn', args: ['lord', 'player'] }, { call: 'canActOn', args: ['player', 'player'] },
    { call: 'getRank', args: ['$db', J.U2, groupMeta(J.GROUP).participants, false, J.GROUP] }, { call: 'getRank', args: ['$db', J.U1, [], true, J.GROUP] }, { call: 'getRank', args: ['$db', J.KING, [], false, null] }, { call: 'getRank', args: ['$db', J.U3, [], false, J.GROUP2] },
    { call: 'isMuted', args: ['$db', J.GROUP, J.U2] }, { call: 'isIgnored', args: ['$db', J.GROUP, J.U2] }, { call: 'trackActivity', args: ['$db', J.GROUP, J.U1] }, { call: 'trackActivity', args: ['$db', J.GROUP, J.U1] }, { call: 'isGroupAdmin', args: [J.ADMIN, groupMeta(J.GROUP).participants] },
    { call: 'isGroupAdmin', args: [J.U1, groupMeta(J.GROUP).participants] }, { call: 'toTag', args: [J.U1, groupMeta(J.GROUP).participants] }, { call: 'toTag', args: ['99900000011@lid', LIDMETA.participants] }, { call: 'toTag', args: ['99900000099@lid', LIDMETA.participants] }, { call: 'toTag', args: ['', []] },
    { call: 'getCommandOverrideRank', args: ['$db', '.menu'] }, { call: 'getCommandOverrideRank', args: ['$db', '.zzz'] }]);

hdr('warn_five', SETUP, [...Array.from({ length: 6 }, () => k('.warn ' + T('U2'), { mentions: [J.U2] })), k('.warnings ' + T('U2'), { mentions: [J.U2] }), ...Array.from({ length: 5 }, () => k('.warn ' + T('U1'), { mentions: [J.U1], fault: 'x' }))]);

// =============================================================================================================
// Run + compare
// =============================================================================================================
const t0 = Date.now ? performance.now() : 0;
const ONLY = (process.argv.find(a => a.startsWith('--only=')) || '').slice(7);
const ALL = [...SCEN, ...MATRIX].filter(([n]) => !ONLY || n.startsWith(ONLY));
if (process.argv.includes('--count')) { H.realConsole.log('scenarios:', ALL.length, 'matrix:', MATRIX.length, 'handwritten:', SCEN.length); process.exit(0); }
for (const [name, setup, steps] of ALL) {
    const a = performance.now();
    await runScenario(name, setup, steps);
    const ms = performance.now() - a;
    if (ms > 1500) H.realConsole.log(`slow scenario ${name}: ${ms.toFixed(0)}ms`);
}
const secs = ((performance.now() - t0) / 1000).toFixed(1);

if (DUMP) { fs.writeFileSync(process.env.GOLDEN_DUMP, JSON.stringify(DUMP)); }
if (UPDATE && ONLY) { H.realConsole.log('refusing: --update together with --only would overwrite the golden with a subset'); process.exit(2); }
if (UPDATE) {
    fs.mkdirSync(path.dirname(GOLDEN), { recursive: true });
    fs.writeFileSync(GOLDEN, JSON.stringify(results, null, 0));
    H.realConsole.log(`golden written: ${Object.keys(results).length} steps from ${ALL.length} scenarios (${secs}s)`);
} else {
    const gold = JSON.parse(fs.readFileSync(GOLDEN, 'utf8'));
    const bad = [...new Set([...Object.keys(gold), ...Object.keys(results)])].sort().filter(k => (!ONLY || k in results) && gold[k]?.h !== results[k]?.h);
    if (bad.length) {
        H.realConsole.log(`FAIL: ${bad.length} of ${Object.keys(results).length} steps differ, first few:`);
        for (const k of bad.slice(0, 6)) H.realConsole.log(' ', k, '\n    golden:', gold[k]?.s, '\n    now:   ', results[k]?.s);
        process.exitCode = 1;
    } else H.realConsole.log(`ok: ${Object.keys(results).length} steps identical to golden (${secs}s)`);
}
