// bridge.js  (split out of index.js)
import fs from 'fs';
import path from 'path';
import { spawn } from 'child_process';
import { err, log, warn } from './lib/log.js';
import { botState } from './lib/state.js';
import { PYTHON_SCRIPT, ROOT, PHONE_NUMBER } from './lib/env.js';
import { sendAny, sendImage, sleep, isStageFile } from './lib/send.js';
import { stats } from './lib/cache.js';
import { sendCard } from './lib/card.js';
import { isPoolOn } from './groups.js';

export const pendingCallbacks = {};
const amongUsGhostGroups = new Set();

export function startPython() {
    log('🐍', 'Starting Python engine...');
    botState.pythonProc  = spawn('python3', ['-u', PYTHON_SCRIPT], { cwd: ROOT });
    botState.pythonReady = false;
    let buffer  = '';

    botState.pythonProc.stdout.on('data', (data) => {
        buffer += data.toString();
        let idx;
        while ((idx = buffer.indexOf('\n')) !== -1) {
            const line = buffer.slice(0, idx).trim();
            buffer = buffer.slice(idx + 1);
            if (!line) continue;
            let parsed;
            try { parsed = JSON.parse(line); }
            catch {
                err('🐍', `Unparseable Python output: ${line.slice(0, 80)}`);
                continue;
            }
            if (parsed.ready) {
                botState.pythonReady = true;
                log('✅', 'Python engine ready');
                // A fresh engine has no matches, so any recorded Communications
                // restriction is stale: clear it before any game can start.
                clearStaleRestrictions();
                continue;
            }
            // Push message (clock tick, etc.) — no req_id
            if (parsed.outbox?.length > 0 && parsed.outbox[0]?.sender === '__push__') {
                if (botState.activeSockRef) {
                    (async () => {
                        for (const item of parsed.outbox) {
                            const targetJid = item.group_jid;
                            // Existing path: pushes to a whitelisted group chat.
                            const isAllowedGroup = targetJid && botState.allowedGroups.includes(targetJid);
                            // Among Us Communications: a chat restriction started/ended.
                            // No WhatsApp setting is changed (messages are deleted by the
                            // normal delete path); we only keep a restart-surviving record.
                            if (item.group_action === 'restrict' || item.group_action === 'unrestrict') {
                                if (isAllowedGroup && String(targetJid).endsWith('@g.us')) {
                                    await applyCommsRestriction(botState.activeSockRef, targetJid, item.group_action === 'restrict');
                                }
                                continue;
                            }
                            // New, narrow path: an individual DM, but ONLY when the
                            // Python side explicitly opts in via allow_dm=true (e.g.
                            // Among Us notifications to a specific player). Never
                            // opened up generally — this is not a blanket DM-push.
                            const isAllowedDM = targetJid && item.allow_dm === true
                                && typeof targetJid === 'string'
                                && targetJid.endsWith('@s.whatsapp.net');
                            if (isAllowedGroup || isAllowedDM) {
                                // DM that should carry the game-group link (Among Us sabotage/meeting
                                // notices). Best effort: send the message without it if the link
                                // can't be fetched (e.g. the bot is not a group admin).
                                if (isAllowedDM && item.group_link_jid
                                    && botState.allowedGroups.includes(item.group_link_jid)) {
                                    const link = await getGroupLink(botState.activeSockRef, item.group_link_jid);
                                    if (link) item.message = `${item.message}\n\n🔗 Open the game group: ${link}`;
                                }
                                log('📤', `PUSH → ${String(targetJid).slice(0,12)}… "${String(item.message).slice(0,35)}"`);
                                // Group message that should carry the link to the bot's DM
                                // (Among Us meeting call / voting announcements).
                                if (item.append_dm_link && isAllowedGroup) {
                                    const dmLink = botDmLink();
                                    if (dmLink) item.message = `${item.message}\n\n💬 Open DM with Ariel: ${dmLink}`;
                                }
                                const qmsg = item.quotedMsg || null;
                                if (item.tag_all) {
                                    try {
                                        const meta    = await botState.activeSockRef.groupMetadata(targetJid);
                                        const members = meta.participants.map(p => p.id);
                                        const tags    = item.hide_tags ? '' : members.map(id => '@' + id.split('@')[0]).join(' ');
                                        const fullMsg = tags ? item.message + '\n' + tags : item.message;
                                        await botState.activeSockRef.sendMessage(targetJid, { text: fullMsg, mentions: item.hide_tags ? [] : members });
                                    } catch(e) { await sendAny(botState.activeSockRef, targetJid, item.message, qmsg); }
                                } else if ((isAllowedGroup || isAllowedDM) && typeof item.image_url === 'string'
                                    && (/^https?:\/\/\S+$/i.test(item.image_url) || isStageFile(item.image_url))) {
                                    // Among Us mini-preview: the message is the caption. sendImage
                                    // falls back to plain text if the image cannot be sent.
                                    // image_card (lobby artwork, .tasks picture, role card): the same picture as a big link
                                    // card; if the card cannot be sent it goes out as the photo it always was.
                                    let sentAsCard = false;
                                    if (item.image_card === true) {
                                        try {
                                            const ref = isStageFile(item.image_url) ? fs.readFileSync(path.resolve(item.image_url)) : item.image_url;
                                            const lines = String(item.message).split('\n').map(l => l.replace(/[*_]/g, '').trim()).filter(Boolean);
                                            await sendCard(botState.activeSockRef, targetJid, {
                                                title: 'Among Us', body: lines[0] || '', image: ref, text: item.message,
                                                big: true, shape: 'auto', strict: true, quoted: qmsg,
                                            });
                                            sentAsCard = true;
                                        } catch (e) { warn('🖼️', `Among Us card failed (${e?.message || e}) - sending the photo instead`); }
                                    }
                                    if (!sentAsCard) await sendImage(botState.activeSockRef, targetJid, item.image_url, item.message, qmsg);
                                } else {
                                    await sendAny(botState.activeSockRef, targetJid, item.message, qmsg);
                                }
                                await sleep(350);
                            }
                        }
                    })();
                }
                continue;
            }
            // Normal response — resolve by req_id
            if (Array.isArray(parsed.amongus_ghost_groups)) {
                amongUsGhostGroups.clear();
                for (const jid of parsed.amongus_ghost_groups) {
                    if (typeof jid === 'string' && jid.endsWith('@g.us')) {
                        amongUsGhostGroups.add(jid);
                    }
                }
            }
            const settle = () => {
                const cb = pendingCallbacks[parsed.req_id];
                if (cb) {
                    delete pendingCallbacks[parsed.req_id];
                    cb.resolve(parsed);
                }
            };
            if (parsed.link_reply && botState.activeSockRef) {
                // `.GC` / `.dm`: answer with the real link, resolved now.
                (async () => {
                    try {
                        const lr = parsed.link_reply;
                        const link = lr.kind === 'dm'
                            ? botDmLink()
                            : (lr.group_jid ? await getGroupLink(botState.activeSockRef, lr.group_jid) : null);
                        parsed.response = link
                            ? `${parsed.response}\n${link}`
                            : `${parsed.response}\n⚠️ _I can't produce that link right now${lr.kind === 'game_group' ? ' (I may need to be a group admin)' : ''}._`;
                    } catch (e) {
                        warn('🔗', `link_reply failed: ${e?.message || e}`);
                    }
                    settle();
                })();
                continue;
            }
            settle();
        }
    });

    botState.pythonProc.stderr.on('data', (d) => {
        const msg = d.toString().trim();
        if (msg) err('🐍', msg);
    });

    botState.pythonProc.on('exit', (code) => {
        botState.pythonReady = false;
        stats.pythonErrors++;
        // Any request still waiting on this dead process will never get its
        // req_id echoed back — resolve them now so callers don't hang, and
        // so their { resolve } closures (which can pin req/res objects,
        // message text, etc.) actually get released instead of leaking.
        const stranded = Object.keys(pendingCallbacks).length;
        if (stranded > 0) {
            warn('🐍', `Clearing ${stranded} stranded callback(s) from dead Python process`);
            for (const key of Object.keys(pendingCallbacks)) {
                pendingCallbacks[key].resolve({ response: null, outbox: [], error: 'Game engine restarted.' });
                delete pendingCallbacks[key];
            }
        }
        warn('🐍', `Python exited (${code}). Restarting in 2s...`);
        setTimeout(startPython, 2000);
    });

    botState.pythonProc.on('error', (e) => {
        err('🐍', `Failed to start Python: ${e.message}`);
        err('🐍', `Script path: ${PYTHON_SCRIPT}`);
        err('🐍', `Does file exist? ${fs.existsSync(PYTHON_SCRIPT)}`);
    });
}

// UPDATED (2026-09): 20s was sized before it was clear a .rpg/.rpg sim
// turn's narration call alone can legitimately take up to ~22s on Groq
// (large ~4.2k-token prompt; see rpg_engine.py's call_groq narration
// timeout note). Raised to 30s so a genuinely-completing narration call
// isn't cut off mid-flight from the Node side — that produced the
// "state saved but no reply shown" desync the .rpg ✔️/✖️ reactions
// exist to signal. Non-.rpg commands finish far under this in practice,
// so raising the ceiling doesn't change their behavior; this only
// matters for whichever call is actually slow enough to approach it.
const _PYTHON_CALL_TIMEOUT_MS = 30_000;

// Groups where we already warned that the bot cannot delete messages (not admin).
const lockWarned = new Set();

// ── Among Us Communications restriction record ─────────────────────────
// While Communications is down, Python deletes ordinary messages in the game
// group. No WhatsApp setting changes, so nothing can stay locked, but the
// groups are recorded in a file that survives a restart: it is written BEFORE
// the restriction starts, removed when it ends, and cleared (with one notice
// to each group) the next time the engine starts, because a restart loses the
// match.
const RESTRICTION_FILE = path.join(ROOT, 'amongus_comms_restrictions.json');
const restrictedGroups = loadRestrictionRecord();
const pendingRestartNotices = new Set();

function loadRestrictionRecord() {
    try {
        const arr = JSON.parse(fs.readFileSync(RESTRICTION_FILE, 'utf8'));
        return new Set(Array.isArray(arr) ? arr.filter((j) => typeof j === 'string') : []);
    } catch {
        return new Set();
    }
}

function saveRestrictionRecord() {
    try {
        const tmp = `${RESTRICTION_FILE}.tmp`;
        fs.writeFileSync(tmp, JSON.stringify([...restrictedGroups]));
        fs.renameSync(tmp, RESTRICTION_FILE);
        return true;
    } catch (e) {
        warn('🔒', `Could not save the Communications restriction record: ${e?.message || e}`);
        return false;
    }
}

async function botCanDelete(sock, groupJid) {
    // true / false when known, null when it cannot be determined (no warning then).
    try {
        const meta = await sock.groupMetadata(groupJid);
        const mine = new Set([sock.user?.id, sock.user?.lid].filter(Boolean).map((j) => String(j).split(':')[0].split('@')[0]));
        const me = (meta.participants || []).find((p) => mine.has(String(p.id).split(':')[0].split('@')[0]));
        return me ? Boolean(me.admin) : null;
    } catch {
        return null;
    }
}

async function applyCommsRestriction(sock, groupJid, restricted) {
    if (restricted) {
        restrictedGroups.add(groupJid);   // record first, then the restriction is live
        saveRestrictionRecord();
        log('🔒', `Communications restriction ON: ${String(groupJid).slice(0, 12)}…`);
        if (!lockWarned.has(groupJid) && (await botCanDelete(sock, groupJid)) === false) {
            lockWarned.add(groupJid);
            try {
                await sock.sendMessage(groupJid, {
                    text: '⚠️ I am not a group admin, so I cannot delete messages. Make me an admin so Communications sabotage can silence chat. Play on the honour system until then.',
                });
            } catch {}
        }
    } else if (restrictedGroups.delete(groupJid)) {
        saveRestrictionRecord();
        log('🔓', `Communications restriction OFF: ${String(groupJid).slice(0, 12)}…`);
    }
}

// Engine (re)started: every recorded restriction belongs to a lost match.
function clearStaleRestrictions() {
    const stale = [...restrictedGroups];
    if (!stale.length) return;
    restrictedGroups.clear();
    saveRestrictionRecord();
    for (const jid of stale) pendingRestartNotices.add(jid);
    warn('🔓', `Cleared ${stale.length} stale Communications restriction(s) after a restart`);
    flushRestartNotices();
}

function flushRestartNotices() {
    const sock = botState.activeSockRef;
    if (!sock) {                       // not connected yet: try again shortly
        if (pendingRestartNotices.size) setTimeout(flushRestartNotices, 5000);
        return;
    }
    for (const jid of [...pendingRestartNotices]) {
        pendingRestartNotices.delete(jid);
        sock.sendMessage(jid, {
            text: '⚠️ I restarted, so the Among Us match here was lost. Group chat is back to normal.',
        }).catch((e) => warn('🔓', `Restart notice failed for ${String(jid).slice(0, 12)}…: ${e?.message || e}`));
    }
}

// Direct link to this bot's own chat (digits only of the configured number).
function botDmLink() {
    const digits = String(PHONE_NUMBER || '').replace(/\D/g, '');
    return digits ? `https://wa.me/${digits}` : null;
}

const groupLinkCache = new Map();   // groupJid -> { link, at }
const GROUP_LINK_TTL_MS = 10 * 60 * 1000;

async function getGroupLink(sock, groupJid) {
    const hit = groupLinkCache.get(groupJid);
    if (hit && Date.now() - hit.at < GROUP_LINK_TTL_MS) return hit.link;
    try {
        const code = await sock.groupInviteCode(groupJid);
        if (!code) return null;
        const link = `https://chat.whatsapp.com/${code}`;
        groupLinkCache.set(groupJid, { link, at: Date.now() });
        return link;
    } catch (e) {
        warn('🔗', `Could not get invite link for ${String(groupJid).slice(0, 12)}…: ${e.message}`);
        return null;
    }
}

export function callPython(sender, text, mentionedJid = null, groupJid = null, quotedText = null, pushName = null, messageKey = null) {
    return new Promise((resolve) => {
        if (!botState.pythonReady || !botState.pythonProc) {
            warn('⚠️', `Python not ready — ignoring "${text.slice(0, 30)}"`);
            return resolve({ response: null, outbox: [] });
        }
        stats.pythonCalls++;
        const req_id = botState._reqCounter++;
        const timeoutHandle = setTimeout(() => {
            if (pendingCallbacks[req_id]) {
                delete pendingCallbacks[req_id];
                warn('🐍', `Timed out waiting on req_id ${req_id} ("${text.slice(0, 30)}")`);
                resolve({ response: null, outbox: [], error: 'Game engine timed out.' });
            }
        }, _PYTHON_CALL_TIMEOUT_MS);
        pendingCallbacks[req_id] = {
            resolve: (val) => { clearTimeout(timeoutHandle); resolve(val); }
        };
        const pool_pokemon = groupJid ? isPoolOn(groupJid, 'pokemon') : false;
        const pool_amongus = groupJid
            ? isPoolOn(groupJid, 'amongus')
                || amongUsGhostGroups.has(groupJid)
                || restrictedGroups.has(groupJid)
                || /^\.(?:(?:set|unset)\s+(?:alobbygc|aghostgc)|alobbygcs|ghostgcs)$/i.test(String(text || '').trim())
            : false;
        const pool_normal  = groupJid ? isPoolOn(groupJid, 'normal')  : false;
        const pool_rpg     = groupJid ? isPoolOn(groupJid, 'rpg')     : false;
        const pool_chat    = groupJid ? isPoolOn(groupJid, 'chat')    : false;
        const pool_niflheim = groupJid ? isPoolOn(groupJid, 'niflheim') : false;
        const is_group     = typeof groupJid === 'string' && groupJid.endsWith('@g.us');
        if (/^\.(amenu|lobby|join|amongus)\b/i.test(String(text || ''))) {
            log('🧩', `[POOLDBG] ${String(text).slice(0, 20)} group=${groupJid} pools=${JSON.stringify(botState.groupPools?.[groupJid] ?? null)} pool_amongus=${pool_amongus}`);
        }
        botState.pythonProc.stdin.write(
            JSON.stringify({ req_id, sender, text, mentioned_jid: mentionedJid, group_jid: groupJid, is_group, received_at_ms: Date.now(), quoted_text: quotedText, push_name: pushName, message_key: messageKey, pool_pokemon, pool_amongus, pool_normal, pool_rpg, pool_chat, pool_niflheim }) + '\n'
        );
    });
}

// Site-originated action (e.g. party/PC swap) — bypasses text parsing,
// runs through bridge.py's _SITE_ACTIONS dispatch instead of the
// WhatsApp command router. Resolves with { error } or the handler's
// own result shape (see router/site_actions.py).
export function callPythonAction(sender, type, payload) {
    return new Promise((resolve) => {
        if (!botState.pythonReady || !botState.pythonProc) {
            warn('⚠️', `Python not ready — ignoring site action "${type}"`);
            return resolve({ error: 'Game engine is not ready. Try again shortly.' });
        }
        stats.pythonCalls++;
        const req_id = botState._reqCounter++;
        const timeoutHandle = setTimeout(() => {
            if (pendingCallbacks[req_id]) {
                delete pendingCallbacks[req_id];
                warn('🐍', `Timed out waiting on req_id ${req_id} (site action "${type}")`);
                resolve({ error: 'Game engine timed out.' });
            }
        }, _PYTHON_CALL_TIMEOUT_MS);
        pendingCallbacks[req_id] = {
            resolve: (val) => { clearTimeout(timeoutHandle); resolve(val); }
        };
        botState.pythonProc.stdin.write(
            JSON.stringify({ req_id, sender, type, payload }) + '\n'
        );
    });
}

