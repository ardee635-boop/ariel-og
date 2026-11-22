export default function makeWASocket() { throw new Error('makeWASocket stub: not used by the golden tests'); }
export const fetchLatestBaileysVersion = async () => ({ version: [2, 0, 0] });
export const makeCacheableSignalKeyStore = (k) => k;
export const Browsers = { macOS: () => ['stub', 'stub', '1'] };
export const DisconnectReason = { loggedOut: 401, restartRequired: 515 };
export const BufferJSON = { replacer: (k, v) => v, reviver: (k, v) => v };
export const jidNormalizedUser = (jid) => (jid || '').replace(/:\d+@/, '@').replace('@c.us', '@s.whatsapp.net');
export const generateWAMessageFromContent = (jid, content) => ({ key: { remoteJid: jid, id: 'GEN' }, message: content });
export async function* downloadContentFromMessage() { if (globalThis.__golden?.fault === 'download') throw new Error('download failed'); yield Buffer.from('MEDIA-BYTES'); }
export const proto = { Message: { InteractiveMessage: { create: (x) => x, NativeFlowMessage: { create: (x) => x }, Body: { create: (x) => x }, Footer: { create: (x) => x }, Header: { create: (x) => x } }, create: (x) => x }, WebMessageInfo: { fromObject: (x) => x } };
