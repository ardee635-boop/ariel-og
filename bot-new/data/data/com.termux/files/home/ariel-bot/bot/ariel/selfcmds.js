// Owner commands for stage 8 (`.ariel style | feedback | self | reflect`). Kept apart from wire.js so
// they can be tested with the in-memory store. Each returns the reply text.
export function createSelfCommands({ self, feedback, persona, reflection, mood }) {
    const kindsText = (kinds) => Object.entries(kinds).map(([k, v]) => `${k} ${v.n} (${v.people} ${v.people === 1 ? 'person' : 'people'})`).join(', ');

    return {
        style: async (arg) => {
            const a = String(arg || '').trim().split(/\s+/).filter(Boolean);
            if (a[0] === 'reset') { await feedback.reset(); persona.refresh(); return '🎨 Style is back to the defaults.'; }
            if (a.length === 2) {
                try { const st = await feedback.setByHand(a[0], a[1]); persona.refresh(); return `🎨 ${a[0]} is now ${st[a[0]]}.`; }
                catch (e) { return `🎨 ⚠️ ${e.message}`; }
            }
            const x = await feedback.summary();
            return ['🎨 *Style*',
                `expressiveness ${x.style.expressiveness}/3 · reply length ${x.style.length}/3 (2 = normal) · emoji ${x.style.emoji}/3 (2 = normal)`,
                `_${x.words}_`, `remarks this week: ${kindsText(x.kinds) || 'none'}`,
                '_.ariel style reset | .ariel style <expressiveness|length|emoji> <number>_'].join('\n');
        },

        feedback: async () => {
            const x = await feedback.summary();
            const c = feedback.counters;
            const kinds = Object.entries(x.kinds).map(([k, v]) => `• ${k}: ${v.n} from ${v.people} ${v.people === 1 ? 'person' : 'people'}`);
            return ['🎨 *Feedback, last 7 days*', ...(kinds.length ? kinds : ['nothing yet']),
                `since boot: ${c.seen} noticed, ${c.stored} stored, ${c.changes} style change(s)`,
                '_A setting moves only after 3 remarks from 2+ people in 7 days, one step at a time._'].join('\n');
        },

        self: async (arg) => {
            const a = String(arg || '').trim().split(/\s+/).filter(Boolean);
            const items = await self.listIdentity();
            if (a[0] === 'drop') {
                const it = items[Number(a[1]) - 1];
                if (!it) return '🪞 _Usage: .ariel self drop <number from the list>_';
                await reflection.drop(it.key); persona.refresh();
                return `🪞 Dropped: ${it.value.text}`;
            }
            const live = (await self.getConfig('reflect.live', false)) === true;
            const out = [`🪞 *Her developing self* (reflection is ${live ? 'LIVE' : 'in dry-run'})`];
            if (!items.length) out.push('nothing yet (it grows from repeated conversations, weekly)');
            items.forEach((i, n) => out.push(`${n + 1}. ${i.value.kind}: ${i.value.text} (${i.evidence_count} episodes, v${i.version})`));
            const mw = await mood.words();
            out.push(mw ? `mood: ${mw.split('. ')[0]}.` : 'mood: normal');
            const log = (await self.getLog()).slice(-5).reverse();
            if (log.length) { out.push('recent changes:'); for (const e of log) out.push(`- ${String(e.at).slice(0, 10)} ${e.status} ${e.type}: ${String(e.text).slice(0, 90)}`); }
            out.push('_.ariel self drop <n> removes one_');
            return out.join('\n');
        },

        reflect: async (arg) => {
            const a = String(arg || '').trim();
            if (a === 'live') { await self.setConfig('reflect.live', true); return '🪞 Reflection is now LIVE: weekly changes (at most 2) are applied and logged.'; }
            if (a === 'dry') { await self.setConfig('reflect.live', false); return '🪞 Reflection is back to dry-run (proposals are only logged).'; }
            const r = await reflection.run();
            persona.refresh();
            if (r.skipped && !r.applied.length && !r.proposed.length) return `🪞 Nothing to do: ${r.skipped}.`;
            const lines = [`🪞 Reflection (${r.live ? 'LIVE' : 'dry-run'}): ${r.applied.length} applied, ${r.proposed.length} proposed, ${r.rejected.length} rejected`];
            for (const e of [...r.applied, ...r.proposed]) lines.push(`${e.status === 'applied' ? '✓' : '·'} ${e.op} ${e.kind}: ${e.text}  (${e.evidence.length} episodes)`);
            for (const x of r.rejected.slice(0, 4)) lines.push(`✗ ${x.text} — ${x.why}`);
            return lines.join('\n');
        },
    };
}
