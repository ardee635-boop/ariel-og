// Stand-in for bot/media.js: the real one calls Pinterest/YouTube over the network.
const G = () => globalThis.__golden;
export async function pinterestSearch(query, limit = 6) { if (G().fault === 'pin') throw new Error('pinterest down'); G().log.push(['pinterest', query, limit]); return query.includes('none') ? [] : query.includes('invalid') ? ['bad://x'] : ['https://img.example/1.jpg', 'https://img.example/2.jpg']; }
export async function searchYouTube(query) { if (G().fault === 'yts') throw new Error('yt down'); G().log.push(['yts', query]); return query.includes('none') ? null : { title: 'Song ' + query, url: 'https://yt.example/v', duration: '3:00', thumbnail: 'https://img.example/t.jpg' }; }
export async function downloadYouTubeAudio(sock, videoUrl, outputPathNoExt, query) {
    G().log.push(['ytdl', videoUrl, query]);
    if (query.includes('fail')) throw new Error('download failed');
    // a real, existing file so the handler's readFileSync works without any disk writes
    if (query.includes('file')) return { type: 'file', path: new URL('../../../README.md', import.meta.url).pathname };
    return { type: 'url', url: 'https://audio.example/a.mp3' };
}
export async function filterValidImageUrls(urls) { return urls.filter(u => !u.startsWith('bad:')); }
export async function sendThumbnail(sock, jid, imageUrl, title, subtitle, body = '', quotedMsg = null) { if (G().fault === 'thumb') throw new Error('thumb failed'); G().log.push(['thumb', jid, imageUrl, title, subtitle, body]); }
