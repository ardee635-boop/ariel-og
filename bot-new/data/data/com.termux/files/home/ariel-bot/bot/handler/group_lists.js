// bot/handler/group_lists.js - `.groups` and `.linkedgroups`.
// Moved verbatim out of handleMessage (handler.js, original lines 430-476).
// run(ctx) returns CONTINUE to fall through to the next step, or ends handling of the message (return / return value).
import { botState } from '../lib/state.js';
import { getOrderedGroups } from '../groups.js';
import { _replyMaybeSilent } from '../silent/mines.js';
import { isSilentGroup } from '../silent/silent.js';
import { CONTINUE } from './_common.js';

export async function run(ctx) {
    let { sock, msg, chatJid, lower, isKingSender } = ctx;

    // Status marks: 🔗 linked · 🤫 silent-linked · 🙈 ignored · ▫️ none of those (normal).
    // Linked + silent together (🔗🤫) is a hybrid.
    const _gcTag = (id) =>
        (botState.allowedGroups.includes(id) ? '🔗' : '') +
        (isSilentGroup(id) ? '🤫' : '') +
        (botState.ignoredGroups.includes(id) ? '🙈' : '') || '▫️';
    const _gcLegend = '🔗 linked · 🤫 silent · 🙈 ignored · ▫️ normal\n_🔗🤫 = hybrid (linked + silent)_';

    if (lower === '.groups') {
        if (!isKingSender) return;
        try {
            const list = await getOrderedGroups(sock);
            if (!list.length) {
                await _replyMaybeSilent(sock, chatJid, '_Ariel isn\'t in any groups right now._', msg);
                return;
            }
            const lines = list.map((g, i) => `${i + 1}. ${_gcTag(g.id)} ${g.subject}`);
            const nLinked = list.filter(g => botState.allowedGroups.includes(g.id)).length;
            const nSilent = list.filter(g => isSilentGroup(g.id)).length;
            const nIgnored = list.filter(g => botState.ignoredGroups.includes(g.id)).length;
            const nNormal = list.filter(g => _gcTag(g.id) === '▫️').length;
            await _replyMaybeSilent(sock, chatJid,
                `📋 *All groups* (${list.length})\n\n${lines.join('\n')}\n\n` +
                `${_gcLegend}\n_${nLinked} linked · ${nSilent} silent · ${nIgnored} ignored · ${nNormal} normal_`, msg);
        } catch (e) {
            await _replyMaybeSilent(sock, chatJid, `⚠️ Couldn't fetch groups: ${e.message}`, msg);
        }
        return;
    }

    // .linkedgroups / .linkedgroup / .linkedgc — only the linked ones, with
    // the SAME numbers .groups shows (so the numbered commands line up).
    if (lower === '.linkedgroups' || lower === '.linkedgroup' || lower === '.linkedgc' || lower === '.linked') {
        if (!isKingSender) return;
        try {
            const list = await getOrderedGroups(sock);
            const rows = list
                .map((g, i) => ({ g, n: i + 1 }))
                .filter(x => botState.allowedGroups.includes(x.g.id))
                .map(x => `${x.n}. ${_gcTag(x.g.id)} ${x.g.subject}`);
            await _replyMaybeSilent(sock, chatJid,
                rows.length
                    ? `🔗 *Linked groups* (${rows.length})\n\n${rows.join('\n')}\n\n_Numbers match .groups_`
                    : '_No linked groups._', msg);
        } catch (e) {
            await _replyMaybeSilent(sock, chatJid, `⚠️ Couldn't fetch groups: ${e.message}`, msg);
        }
        return;
    }
    return CONTINUE;
}
