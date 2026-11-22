// bot/handler/late_cmds.js - `.btest`, `.listtest`, `.gen`.
// Moved verbatim out of handleMessage (handler.js, original lines 2589-2776).
// run(ctx) returns CONTINUE to fall through to the next step, or ends handling of the message (return / return value).
import { generateWAMessageFromContent, proto } from '@whiskeysockets/baileys';
import { sendText } from '../lib/send.js';
import { _isRateLimited } from '../lib/ratelimit.js';
import { CONTINUE } from './_common.js';

export async function run(ctx) {
    let { sock, msg, chatJid, text, senderJid, lower } = ctx;

    // ── .btest — throwaway test for native WhatsApp button rendering ──
    // NOTE: mainline @whiskeysockets/baileys dropped native support for
    // interactive buttons/list messages. WhatsApp only renders these if
    // the outgoing stanza carries specific binary nodes (<biz>/<interactive>/
    // <native_flow>) that real WhatsApp clients send but Baileys no longer
    // builds for you. This manually constructs a buttonsMessage and injects
    // those nodes via additionalNodes on relayMessage. This is a hack, not
    // an officially supported path — expect it to be flaky across
    // WhatsApp Web/Desktop/iOS, and to break on WhatsApp client updates.
    // Dummy content only; "Potions"/"Elixirs"/"Herbs" are not real items.
    // Placed here (ahead of handleBotCommand) because this needs raw
    // sock.relayMessage access — commands.js's handleBotCommand only
    // returns a reply payload, it doesn't send directly.
    if (lower === '.btest') {
        try {
            const buttonMsg = {
                buttonsMessage: {
                    contentText: 'Welcome to Niflheim eShop — use the buttons below to browse our wares.',
                    footerText: 'Niflheim eShop',
                    buttons: [
                        { buttonId: 'btest_potions', buttonText: { displayText: 'Potions' }, type: 1 },
                        { buttonId: 'btest_elixirs', buttonText: { displayText: 'Elixirs' }, type: 1 },
                        { buttonId: 'btest_herbs',   buttonText: { displayText: 'Herbs' },   type: 1 },
                        { buttonId: 'btest_next',    buttonText: { displayText: 'Next' },    type: 1 },
                    ],
                    headerType: 1,
                },
            };

            const preppedMsg = generateWAMessageFromContent(
                chatJid,
                proto.Message.fromObject(buttonMsg),
                { userJid: sock.user.id, quoted: msg }
            );

            await sock.relayMessage(chatJid, preppedMsg.message, {
                messageId: preppedMsg.key.id,
                additionalNodes: [{
                    tag: 'biz',
                    attrs: {},
                    content: [{
                        tag: 'interactive',
                        attrs: { type: 'native_flow', v: '1' },
                        content: [{ tag: 'native_flow', attrs: { name: 'mixed' } }],
                    }],
                }],
            });
        } catch (e) {
            console.error('[.btest] button send failed:', e);
            await sendText(
                sock, chatJid,
                '⚠️ _Button send failed (expected on some clients — mainline Baileys doesn\'t officially support buttons). Falling back to text:_\n\n' +
                '🛒 *Niflheim eShop*\n1. Potions\n2. Elixirs\n3. Herbs\n4. Next',
                msg
            );
        }
        return;
    }

    // ── .listtest — throwaway test for native WhatsApp LIST message rendering ──
    // NOTE: separate WhatsApp component from buttonsMessage (the .btest one) —
    // this is the bottom-sheet radio-style picker (like UBA ChatBanking's "Select"
    // menu). Same underlying problem: mainline @whiskeysockets/baileys doesn't
    // build the binary nodes WhatsApp needs to render it, so we inject them
    // manually via additionalNodes on relayMessage, same as .btest.
    // Getting buttonsMessage working does NOT guarantee this renders — it's a
    // different message type and historically flakier on Baileys forks.
    // WhatsApp's own list format caps at 10 rows total across ALL sections
    // combined. This is now a real constraint, not just future-relevant:
    // the live Summoner trial species picker (9 species) uses this same
    // trick for real via sendListMessage() above, which is the version to
    // extend/reuse — this .listtest command itself is now redundant with
    // that and kept only as a standalone render smoke-test.
    // Dummy content only — options below don't do anything yet.
    if (lower === '.listtest') {
        console.log('[LISTTEST] block entered');
        try {
            const listMsg = {
                listMessage: {
                    title: 'Niflheim eShop',
                    description: 'How can we help you today?',
                    buttonText: 'Select',
                    listType: 1, // SINGLE_SELECT
                    sections: [
                        {
                            title: 'Shop Menu',
                            rows: [
                                { rowId: 'listtest_potions', title: 'Potions', description: 'Restore HP' },
                                { rowId: 'listtest_elixirs', title: 'Elixirs', description: 'Restore PP' },
                                { rowId: 'listtest_herbs',   title: 'Herbs',   description: 'Cure status effects' },
                                { rowId: 'listtest_misc',    title: 'Misc',    description: 'Everything else' },
                            ],
                        },
                    ],
                },
            };

            const preppedMsg = generateWAMessageFromContent(
                chatJid,
                proto.Message.fromObject(listMsg),
                { userJid: sock.user.id, quoted: msg }
            );
            console.log('[LISTTEST] generateWAMessageFromContent OK, relaying...');

            await sock.relayMessage(chatJid, preppedMsg.message, {
                messageId: preppedMsg.key.id,
                // FIX (was wrong): listMessage needs a <list> node, NOT the
                // <interactive><native_flow> node buttonsMessage uses.
                // Confirmed via evolution-api's fix for this exact bug —
                // they found the buttons node structure doesn't apply to
                // lists, and that the modern interactiveMessage+single_select
                // approach doesn't render on Web/Desktop at all; the legacy
                // listMessage + this specific <biz><list type=product_list
                // v=2/></biz> node is what actually renders.
                additionalNodes: [{
                    tag: 'biz',
                    attrs: {},
                    content: [{
                        tag: 'list',
                        attrs: { type: 'product_list', v: '2' },
                    }],
                }],
            });
            console.log('[LISTTEST] relayMessage completed without throwing');
        } catch (e) {
            console.error('[.listtest] list send failed:', e);
            await sendText(
                sock, chatJid,
                '⚠️ _List send failed (expected on some clients — this is an unofficial format Baileys doesn\'t natively support). Falling back to text:_\n\n' +
                '🛒 *Niflheim eShop*\n1. Potions\n2. Elixirs\n3. Herbs\n4. Misc',
                msg
            );
        }
        return;
    }

    // ── .gen <description> — AI image generation via Gemini 3.1 Flash Lite
    // Image ("Nano Banana 2 Lite" — Google's own docs describe it as "the
    // efficiency specialist... ultra-low latency and cost-effective"). Swapped
    // from gemini-2.5-flash-image after that model returned a hard 429 quota
    // error on this account's free tier — lite/cost-tier models are a real,
    // reasoned guess at better free-tier treatment, not confirmed in Google's
    // published docs (their per-model free RPD numbers live only in the
    // account-specific AI Studio dashboard, not in public docs). If this
    // 429s too, that's a real answer: this account's free tier likely
    // doesn't cover ANY image model, not just the flagship one.
    // Requires GEMINI_API_KEY set in the environment (Google AI Studio free
    // tier — see https://aistudio.google.com/apikey). Returns base64 image
    // bytes directly in the response body (no hosted URL), so the image is
    // sent to WhatsApp as a raw Buffer via sock.sendMessage, same pattern
    // already used by .toimg elsewhere in this file.
    if (lower.startsWith('.gen ') || lower === '.gen') {
        const prompt = text.trim().slice(4).trim(); // strip ".gen", keep the rest
        if (!prompt) {
            await sendText(sock, chatJid, '🎨 _Usage: .gen <description> — e.g. .gen a golden dragon curled around a mountain peak_', msg);
            return;
        }
        if (!process.env.GEMINI_API_KEY) {
            await sendText(sock, chatJid, '⚠️ _.gen isn\'t configured yet — missing GEMINI_API_KEY._', msg);
            return;
        }
        if (_isRateLimited(`gen:${senderJid}`, 1, 15_000)) {
            await sendText(sock, chatJid, '⏳ _Slow down — one image every 15 seconds. Try again shortly._', msg);
            return;
        }
        try {
            const resp = await fetch(
                'https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-flash-lite-image:generateContent',
                {
                    method: 'POST',
                    headers: {
                        'x-goog-api-key': process.env.GEMINI_API_KEY,
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        contents: [{ parts: [{ text: prompt }] }],
                    }),
                }
            );
            if (!resp.ok) {
                const errBody = await resp.text().catch(() => '');
                throw new Error(`Gemini API ${resp.status}: ${errBody.slice(0, 200)}`);
            }
            const data = await resp.json();
            const parts = data?.candidates?.[0]?.content?.parts || [];
            const imagePart = parts.find(p => p.inlineData?.data);
            if (!imagePart) {
                // Gemini can respond with text-only (e.g. it refused the
                // prompt, or described instead of generating) — surface
                // whatever text it did return rather than failing silently.
                const textPart = parts.find(p => p.text)?.text;
                throw new Error(textPart ? `No image returned — Gemini said: ${textPart.slice(0, 150)}` : 'No image returned');
            }
            const buffer = Buffer.from(imagePart.inlineData.data, 'base64');
            await sock.sendMessage(chatJid, { image: buffer, caption: `🎨 *${prompt}*` }, { quoted: msg });
        } catch (e) {
            console.error('[.gen] Gemini image generation failed:', e);
            await sendText(sock, chatJid, `⚠️ _Image generation failed: ${e.message.slice(0, 150)}_`, msg);
        }
        return;
    }
    return CONTINUE;
}
