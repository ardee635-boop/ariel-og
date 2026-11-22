// bot/lib/tts.js - text -> WhatsApp voice note (ogg/opus).
// Primary: Gemini TTS (uses GEMINI_API_KEY, same key as .gen) - natural, steerable by a style prompt.
// Then: Groq Orpheus TTS (uses GROQ_API_KEY; the model's terms must be accepted once in the Groq console).
// Fallback: Google Translate TTS (no key, robotic but reliable).
// ffmpeg joins the chunks and encodes to ogg/opus, which WhatsApp needs for a ptt voice note.
import fs from 'fs';
import os from 'os';
import path from 'path';
import { spawn } from 'child_process';
import { err } from './log.js';
import { ROOT } from './env.js';

const MAX_CHARS = 600;       // keep voice notes short
const CHUNK = 190;           // Orpheus/Google both cap input at ~200 chars
const VOICE = process.env.TTS_VOICE || 'autumn'; // autumn, diana, hannah, austin, daniel, troy
// Gemini TTS: voices e.g. Leda (youthful), Kore, Zephyr (bright), Aoede (breezy), Puck, Charon...
const GEMINI_VOICE = process.env.GEMINI_TTS_VOICE || 'Leda';
const GEMINI_MODEL = process.env.GEMINI_TTS_MODEL || 'gemini-2.5-flash-preview-tts';
const GEMINI_STYLE = process.env.GEMINI_TTS_STYLE ||
    'Say this as a cool, composed young woman, calm and a little dry, softly flustered when it is sweet: ';
const GEMINI_CHUNK = 600;

// Strip things that sound bad when read aloud.
export function cleanForSpeech(s) {
    return String(s || '')
        .replace(/__HUD__/g, '')
        .replace(/https?:\/\/\S+/g, '')
        .replace(/@\d{5,}/g, '')
        .replace(/[*_~`>#]/g, '')
        .replace(/\p{Extended_Pictographic}|\uFE0F|\u200D/gu, '')
        // Chat slang the TTS spells out or mangles -> something speakable.
        .replace(/\b(?:l+o+l+|lmao+|lmfao|rofl|kek)\b/gi, 'haha')
        .replace(/\b(?:omg)\b/gi, 'oh my god')
        .replace(/\b(?:idk)\b/gi, "I don't know")
        .replace(/\b(?:tbh)\b/gi, 'to be honest')
        .replace(/\b(?:smh)\b/gi, 'shaking my head')
        .replace(/\b(?:brb)\b/gi, 'be right back')
        .replace(/\b(?:ngl)\b/gi, 'not gonna lie')
        .replace(/\b(?:btw)\b/gi, 'by the way')
        .replace(/\b(?:ty|thx)\b/gi, 'thanks')
        .replace(/\b(?:pls|plz)\b/gi, 'please')
        .replace(/\s+/g, ' ')
        .trim();
}

function splitChunks(text, CHUNK = 190) {
    const sentences = text.match(/[^.!?\n]+[.!?]*/g) || [text];
    const out = [];
    let cur = '';
    for (let s of sentences) {
        s = s.trim();
        if (!s) continue;
        while (s.length > CHUNK) {                 // very long sentence: cut at a space
            let cut = s.lastIndexOf(' ', CHUNK);
            if (cut < CHUNK / 2) cut = CHUNK;
            if (cur) { out.push(cur); cur = ''; }
            out.push(s.slice(0, cut).trim());
            s = s.slice(cut).trim();
        }
        if ((cur + ' ' + s).trim().length > CHUNK) { if (cur) out.push(cur); cur = s; }
        else cur = (cur + ' ' + s).trim();
    }
    if (cur) out.push(cur);
    return out;
}

// Wrap raw 16-bit mono PCM in a WAV header so ffmpeg can concat/encode it like the other providers.
function pcmToWav(pcm, rate = 24000) {
    const h = Buffer.alloc(44);
    h.write('RIFF', 0); h.writeUInt32LE(36 + pcm.length, 4); h.write('WAVE', 8);
    h.write('fmt ', 12); h.writeUInt32LE(16, 16); h.writeUInt16LE(1, 20); h.writeUInt16LE(1, 22);
    h.writeUInt32LE(rate, 24); h.writeUInt32LE(rate * 2, 28); h.writeUInt16LE(2, 32); h.writeUInt16LE(16, 34);
    h.write('data', 36); h.writeUInt32LE(pcm.length, 40);
    return Buffer.concat([h, pcm]);
}

async function geminiChunk(text) {
    const key = (process.env.GEMINI_API_KEY || '').trim();
    if (!key) throw new Error('no GEMINI_API_KEY');
    const res = await fetch(`https://generativelanguage.googleapis.com/v1beta/models/${GEMINI_MODEL}:generateContent`, {
        method: 'POST',
        headers: { 'x-goog-api-key': key, 'Content-Type': 'application/json' },
        body: JSON.stringify({
            contents: [{ parts: [{ text: GEMINI_STYLE + text }] }],
            generationConfig: {
                responseModalities: ['AUDIO'],
                speechConfig: { voiceConfig: { prebuiltVoiceConfig: { voiceName: GEMINI_VOICE } } },
            },
        }),
        signal: AbortSignal.timeout(45000),
    });
    if (!res.ok) throw new Error(`gemini tts HTTP ${res.status} ${(await res.text()).slice(0, 150)}`);
    const data = await res.json();
    const b64 = data?.candidates?.[0]?.content?.parts?.find((p) => p.inlineData)?.inlineData?.data;
    if (!b64) throw new Error('gemini tts: no audio returned');
    return { buf: pcmToWav(Buffer.from(b64, 'base64')), ext: 'wav' };
}

async function groqChunk(text) {
    const key = (process.env.GROQ_API_KEY || '').trim();
    if (!key) throw new Error('no GROQ_API_KEY');
    const res = await fetch('https://api.groq.com/openai/v1/audio/speech', {
        method: 'POST',
        headers: { Authorization: `Bearer ${key}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ model: 'canopylabs/orpheus-v1-english', voice: VOICE, input: text, response_format: 'wav' }),
        signal: AbortSignal.timeout(30000),
    });
    if (!res.ok) throw new Error(`groq tts HTTP ${res.status} ${(await res.text()).slice(0, 150)}`);
    return { buf: Buffer.from(await res.arrayBuffer()), ext: 'wav' };
}

async function googleChunk(text) {
    const url = `https://translate.google.com/translate_tts?ie=UTF-8&client=tw-ob&tl=en&q=${encodeURIComponent(text)}`;
    const res = await fetch(url, { headers: { 'User-Agent': 'Mozilla/5.0' }, signal: AbortSignal.timeout(20000) });
    if (!res.ok) throw new Error(`google tts HTTP ${res.status}`);
    return { buf: Buffer.from(await res.arrayBuffer()), ext: 'mp3' };
}

function ffmpeg(args) {
    return new Promise((resolve, reject) => {
        const p = spawn('ffmpeg', ['-y', '-loglevel', 'error', ...args]);
        let stderr = '';
        p.stderr.on('data', (d) => { stderr += d; });
        p.on('error', reject);
        p.on('close', (code) => code === 0 ? resolve() : reject(new Error(`ffmpeg exit ${code}: ${stderr.slice(0, 200)}`)));
    });
}

// Returns an ogg/opus Buffer, or throws.
export async function synthesizeVoice(rawText) {
    let text = cleanForSpeech(rawText);
    if (!text) throw new Error('nothing to say');
    if (text.length > MAX_CHARS) text = text.slice(0, MAX_CHARS).replace(/\s+\S*$/, '') + '.';

    // One provider for the whole note so the voice stays consistent.
    let parts, lastErr;
    for (const [fn, limit] of [[geminiChunk, GEMINI_CHUNK], [groqChunk, 190], [googleChunk, 190]]) {
        try {
            parts = [];
            for (const c of splitChunks(text, limit)) parts.push(await fn(c));
            break;
        } catch (e) { lastErr = e; parts = null; err('🔊', `${fn.name} failed: ${e.message}`); }
    }
    if (!parts) throw lastErr || new Error('tts failed');

    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'tts_'));
    try {
        const files = parts.map((p, i) => {
            const f = path.join(dir, `c${i}.${p.ext}`);
            fs.writeFileSync(f, p.buf);
            return f;
        });
        const list = path.join(dir, 'list.txt');
        fs.writeFileSync(list, files.map((f) => `file '${f.replace(/'/g, "'\\''")}'`).join('\n'));
        const out = path.join(dir, 'out.ogg');
        await ffmpeg(['-f', 'concat', '-safe', '0', '-i', list, '-vn', '-ac', '1', '-ar', '48000', '-c:a', 'libopus', '-b:a', '32k', out]);
        return fs.readFileSync(out);
    } finally {
        fs.rmSync(dir, { recursive: true, force: true });
    }
}

export async function sendVoiceNote(sock, jid, text, quotedMsg = null) {
    const buf = await synthesizeVoice(text);
    await sock.sendMessage(jid, { audio: buf, mimetype: 'audio/ogg; codecs=opus', ptt: true }, quotedMsg ? { quoted: quotedMsg } : {});
}

// ── Per-chat "Ariel replies in voice" switch (persisted best-effort) ──
const VOICE_FILE = path.join(ROOT, 'voice_chats.json');
const voiceChats = new Set();
try { for (const j of JSON.parse(fs.readFileSync(VOICE_FILE, 'utf8'))) voiceChats.add(j); } catch {}
export const isVoiceChat = (jid) => voiceChats.has(jid);
export function setVoiceChat(jid, on) {
    if (on) voiceChats.add(jid); else voiceChats.delete(jid);
    try { fs.writeFileSync(VOICE_FILE, JSON.stringify([...voiceChats])); } catch {}
}
