// bot/wmode/index.js — the WhatsApp side of Work Mode (King only).
//
//   .wchat on | off | status     switch Work Mode for this chat / see state
//   .whelp                       the command list
//   .wtasks  .wtask [id]  .wlog [id]   recent tasks / one task / what it did
//   .cchat <message>             creative brainstorming (.cchat clear starts fresh)
//   .wproject                    saved to-dos, decisions and notes for this chat
//   .wpause [id]  .wresume [id]  .wcancel [id]
//   .wapprove [id]  .wdeny [id]  answer a task's request to run code / delete a file
//
// While Work Mode is on in a chat, the King's plain messages there are work requests. Anything that
// starts with "." still goes through the normal command path, so .chat / .ariel / games keep working.
// Everyone else in the chat, and every chat where Work Mode is off, is handled exactly as before.
import { lidMap } from '../lib/cache.js';
import { KING_NUMBER, BOT_START_TIME } from '../lib/env.js';
import { sendText } from '../lib/send.js';
import { normJid } from '../ariel/ids.js';
import { isChatEnabled } from '../ariel/wire.js';
import { buildAdapters } from '../ariel/providers/adapters.js';
import { resolveSettings } from './settings.js';
import { createWorkStore } from './store.js';
import { createProviderManager } from './providers.js';
import { createWorkManager } from './manager.js';
import { createWorkInterface, WORK_COMMANDS } from './wa.js';
import path from 'node:path';
import { createSandbox } from './tools/sandbox.js';
import { createToolRegistry } from './tools/index.js';
import { registerFsTools } from './tools/fs_tools.js';
import { registerCmdTools } from './tools/cmd_tools.js';
import { registerWebTools } from './tools/web_tools.js';
import { registerSearchTool } from './tools/search.js';
import { registerProjectTools } from './tools/project_tools.js';
import { createProjectStore } from './project.js';
import { createCreativeChat } from './creative.js';

const digits = (v) => String(v || '').replace(/\D/g, '');

// ── who is the King (same idea as handler/entry.js, usable before sender resolution) ──
function jidDigits(j) {
    const n = normJid(j);
    if (!n) return null;
    const mapped = lidMap[n] ? normJid(lidMap[n]) : null;
    return digits((mapped || n).split('@')[0]);
}
export function isKingMessage(msg) {
    const k = msg?.key || {};
    const king = digits(KING_NUMBER);
    if (!king) return false;
    return [k.participant, k.participantAlt, k.participantPn, k.senderPn, k.remoteJid, k.remoteJidAlt]
        .some((j) => j && jidDigits(j) === king);
}

// ── lazy singleton ──────────────────────────────────────────────
let built = null;
function build() {
    if (built) return built;
    built = (async () => {
        if (!process.env.SUPABASE_DB_URL && !process.env.ARIEL_DB_URL) return { off: true };
        const db = await import('../ariel/db.js');
        const store = createWorkStore(db);
        const settings = resolveSettings(await db.getConfig('work_settings', null).catch(() => null));
        const providers = createProviderManager({
            adapters: buildAdapters(process.env), settings,
            getOverride: () => db.getConfig('work_routing', null),
            usage: { record: (row) => db.logUsage(row), todayTokens: (role) => db.todayTokens(role) },
            persistHealth: (dump) => store.setConfig('work_health', dump),
        });
        providers.health.load(await store.getConfig('work_health', {}).catch(() => ({})));
        let tools = null;
        const project = createProjectStore(db, { maxItems: settings.projectMaxItems });
        try {   // file + command tools, confined to the workspace folder; the bot still runs without them
            const sandbox = createSandbox({ root: path.resolve(process.cwd(), settings.workspaceDir) });
            tools = registerCmdTools(registerFsTools(createToolRegistry({ settings, log: (m) => console.log(`[WORK] ${m}`) }), { sandbox, settings }), { sandbox, settings });
            registerWebTools(tools, { settings });                       // fetch_page (public pages only)
            registerSearchTool(tools, { settings, env: process.env });   // web_search (Tavily -> Brave -> Wikipedia)
            registerProjectTools(tools, { project, getTask: (id) => store.getTask(id), settings });   // notes, decisions, to-dos (sql/005)
        } catch (e) { console.error('[WORK] tools unavailable:', e?.message || e); }
        const manager = createWorkManager({
            store, providers, settings, tools, project,
            isChatEnabled: (jid, isDM) => isChatEnabled(jid, isDM),
            log: (m) => console.log(`[WORK] ${m}`),
        });
        const creative = createCreativeChat({ providers, settings });
        return { off: false, store, settings, providers, manager, creative };
    })().catch((e) => { console.error('[WORK] setup failed:', e?.message || e); built = null; return { off: true }; });
    return built;
}

// ── one interface per live socket (a reconnect creates a new socket, so it gets a new interface) ──
const ifaces = new WeakMap();
function ifaceFor(sock, b) {
    let i = ifaces.get(sock);
    if (!i) {
        i = createWorkInterface({
            manager: b.manager, creative: b.creative, settings: b.settings,
            send: (jid, text, quoted) => sendText(sock, jid, text, quoted),
            typing: async (jid, on) => { await sock.sendPresenceUpdate(on ? 'composing' : 'paused', jid); },
            log: (m) => console.log(`[WORK] ${m}`),
        });
        ifaces.set(sock, i);
    }
    return i;
}

// ── main entry (called from handler/entry.js before Ariel's own ingest) ──
// Returns true when Work Mode consumed the message. Never throws.
export async function workModeIntercept(sock, msg) {
    try {
        const text = (msg.message?.conversation || msg.message?.extendedTextMessage?.text || '').trim();
        if (!text) return false;
        const chatJid = msg.key.remoteJid;
        const lower = text.toLowerCase().replace(/\s+/g, ' ');
        const cmd = lower.split(' ')[0];
        const isCmd = WORK_COMMANDS.has(cmd);

        // Cheap exits first: most messages are neither a Work command nor in a Work chat.
        if (!isCmd && !text.length) return false;
        if (!isKingMessage(msg)) return false;
        const ts = Number(msg.messageTimestamp);
        if (ts && ts < BOT_START_TIME - 10) return false;   // history replay after reconnect

        const b = await build();
        if (b.off) {
            if (isCmd) { await sendText(sock, chatJid, '🧰 Work Mode is unavailable: the database is not configured (SUPABASE_DB_URL).', msg); return true; }
            return false;
        }
        const isDM = !chatJid.endsWith('@g.us');
        return await ifaceFor(sock, b).handle({ text, chatJid, userId: digits(KING_NUMBER), isDM, msgId: msg.key.id, quoted: msg });
    } catch (e) {
        console.error('[WORK] intercept failed:', e?.stack || e?.message || e);
        try { await sendText(sock, msg.key.remoteJid, `🧰 ⚠️ Work Mode hit an error: ${String(e.message || e).slice(0, 160)}`, msg); } catch { /* nothing more to do */ }
        return true;
    }
}

// Called once when the WhatsApp connection opens: finish tasks that were running when the bot stopped,
// then keep sweeping for abandoned ones. Duplicate-safe (see store.claimTask).
let sweeper = null;
export async function workModeOnConnected(sock) {
    try {
        const b = await build();
        if (b.off) return;
        const sweep = async () => {
            const outcomes = await b.manager.recover({ notifyFor: (t) => (x) => sendText(sock, t.chatJid, x) });
            for (const o of outcomes) await ifaceFor(sock, b).deliver(o.chatJid, o);
            await b.manager.housekeeping().catch(() => {});
        };
        await sweep();
        if (sweeper) clearInterval(sweeper);
        sweeper = setInterval(() => sweep().catch((e) => console.error('[WORK] sweep failed:', e?.message)), b.settings.sweepMs);
        sweeper.unref?.();
        console.log('[WORK] Work Mode ready');
    } catch (e) { console.error('[WORK] startup recovery failed:', e?.message || e); }
}
