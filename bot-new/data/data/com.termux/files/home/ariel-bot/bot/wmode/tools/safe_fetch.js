// bot/wmode/tools/safe_fetch.js — fetch a public web page on behalf of a model.
// The model chooses the URL, so this must never reach the bot's own network: only http/https on ports 80/443,
// no credentials in the URL, every resolved address must be public (checked AT CONNECT TIME, which also defeats
// DNS rebinding), every redirect is re-checked, and size / time are capped.
import http from 'node:http';
import https from 'node:https';
import dns from 'node:dns';
import net from 'node:net';
import zlib from 'node:zlib';
import { ToolError } from './sandbox.js';

const BLOCK = new net.BlockList();
for (const [a, p] of [['0.0.0.0', 8], ['10.0.0.0', 8], ['100.64.0.0', 10], ['127.0.0.0', 8], ['169.254.0.0', 16], ['172.16.0.0', 12], ['192.0.0.0', 24],
    ['192.0.2.0', 24], ['192.168.0.0', 16], ['198.18.0.0', 15], ['198.51.100.0', 24], ['203.0.113.0', 24], ['224.0.0.0', 4], ['240.0.0.0', 4]]) BLOCK.addSubnet(a, p, 'ipv4');
for (const [a, p] of [['::', 128], ['::1', 128], ['fc00::', 7], ['fe80::', 10], ['ff00::', 8], ['2001:db8::', 32], ['64:ff9b::', 96], ['100::', 64]]) BLOCK.addSubnet(a, p, 'ipv6');

export function isPublicIp(ip) {
    let s = String(ip || '').replace(/^\[|\]$/g, '').split('%')[0];
    let v = net.isIP(s);
    if (!v) return false;
    const m = /^::ffff:(\d+\.\d+\.\d+\.\d+)$/i.exec(s);   // IPv4-mapped written with dots: judge the IPv4 part
    if (m) { s = m[1]; v = 4; }
    return !BLOCK.check(s, v === 4 ? 'ipv4' : 'ipv6');
}

// Resolves a name and refuses it if ANY address is non-public. Used as the socket's lookup, so the address
// that is checked is the address that is connected to.
export function makeSafeLookup(dnsLookup = dns.lookup) {
    return (hostname, opts, cb) => {
        if (typeof opts === 'function') { cb = opts; opts = {}; }
        dnsLookup(hostname, { all: true, family: opts?.family || 0 }, (err, addrs) => {
            if (err) return cb(err);
            if (!addrs?.length || addrs.some((a) => !isPublicIp(a.address))) return cb(Object.assign(new Error(`blocked: ${hostname} resolves to a non-public address`), { code: 'EBLOCKED' }));
            return opts?.all ? cb(null, addrs) : cb(null, addrs[0].address, addrs[0].family);
        });
    };
}

const BAD_HOST = /(^|\.)(localhost|local|internal|localdomain|lan|home|corp|intranet)$/i;
export function checkUrl(raw, { allowPrivate = false } = {}) {
    let u;
    try { u = new URL(String(raw)); } catch { throw new ToolError('not a valid URL', 'blocked_url'); }
    if (u.protocol !== 'http:' && u.protocol !== 'https:') throw new ToolError('only http and https URLs are allowed', 'blocked_url');
    if (u.username || u.password) throw new ToolError('URLs with credentials are not allowed', 'blocked_url');
    if (allowPrivate) return u;   // test hook only: protocol and credentials are still enforced
    const port = u.port || (u.protocol === 'https:' ? '443' : '80');
    if (port !== '80' && port !== '443') throw new ToolError('only ports 80 and 443 are allowed', 'blocked_url');
    const host = u.hostname.replace(/^\[|\]$/g, '');
    if (!host || BAD_HOST.test(host)) throw new ToolError('that host is not allowed', 'blocked_url');
    if (net.isIP(host) && !isPublicIp(host)) throw new ToolError('that address is not public', 'blocked_url');
    return u;
}

const OK_TYPE = /^(text\/|application\/(json|xml|xhtml\+xml|rss\+xml|atom\+xml|ld\+json))/i;

function doRequest(u, { timeoutMs, lookup, userAgent }) {
    return new Promise((resolve, reject) => {
        const mod = u.protocol === 'https:' ? https : http;
        const req = mod.request(u, { method: 'GET', lookup, timeout: timeoutMs, headers: {
            'user-agent': userAgent, accept: 'text/html,application/xhtml+xml,text/plain,application/json;q=0.9,*/*;q=0.1',
            'accept-encoding': 'gzip, deflate, br', 'accept-language': 'en' } }, resolve);
        req.on('timeout', () => req.destroy(Object.assign(new Error('timed out'), { code: 'ETIMEDOUT' })));
        req.on('error', reject);
        req.end();
    });
}

async function readBody(res, maxBytes) {
    let stream = res;
    const enc = String(res.headers['content-encoding'] || '').toLowerCase();
    if (enc === 'gzip' || enc === 'x-gzip') stream = res.pipe(zlib.createGunzip());
    else if (enc === 'deflate') stream = res.pipe(zlib.createInflate());
    else if (enc === 'br') stream = res.pipe(zlib.createBrotliDecompress());
    const chunks = []; let size = 0; let truncated = false;
    try {
        for await (const c of stream) {
            if (size + c.length > maxBytes) { chunks.push(c.subarray(0, maxBytes - size)); size = maxBytes; truncated = true; break; }
            chunks.push(c); size += c.length;
        }
    } finally { res.destroy(); }
    return { buf: Buffer.concat(chunks), truncated };
}

function decode(buf, contentType) {
    const label = /charset=["']?([\w-]+)/i.exec(contentType || '')?.[1] || 'utf-8';
    try { return new TextDecoder(label).decode(buf); } catch { return new TextDecoder('utf-8').decode(buf); }
}

export async function fetchPage(url, { timeoutMs = 15_000, maxBytes = 1_000_000, maxRedirects = 3, allowPrivate = false,
    userAgent = 'Mozilla/5.0 (compatible; ArielWorkMode/1.0)', lookup = makeSafeLookup(), _request = doRequest } = {}) {
    const deadline = Date.now() + timeoutMs;
    let current = String(url);
    for (let hop = 0; hop <= maxRedirects; hop++) {
        const u = checkUrl(current, { allowPrivate });   // every hop is checked again
        const left = deadline - Date.now();
        if (left <= 0) throw new ToolError('page took too long', 'timeout');
        let res;
        try { res = await _request(u, { timeoutMs: left, lookup: allowPrivate ? undefined : lookup, userAgent }); }
        catch (e) {
            if (e.code === 'EBLOCKED') throw new ToolError(e.message, 'blocked_url');
            if (e.code === 'ETIMEDOUT') throw new ToolError('page took too long', 'timeout');
            throw new ToolError(`could not fetch the page (${e.code || e.message})`, 'fetch_failed');
        }
        const status = res.statusCode || 0;
        if (status >= 300 && status < 400 && res.headers.location) {
            res.resume(); res.destroy();
            try { current = new URL(res.headers.location, u).toString(); } catch { throw new ToolError('bad redirect', 'fetch_failed'); }
            continue;
        }
        if (status >= 400) { res.resume(); res.destroy(); throw new ToolError(`the site answered HTTP ${status}`, 'http_error'); }
        const contentType = String(res.headers['content-type'] || 'text/html');
        if (!OK_TYPE.test(contentType)) { res.resume(); res.destroy(); throw new ToolError(`unsupported content type (${contentType.split(';')[0]}); only text pages are read`, 'unsupported_type'); }
        let body;
        try { body = await Promise.race([readBody(res, maxBytes), new Promise((_, rej) => setTimeout(() => rej(Object.assign(new Error('t'), { code: 'ETIMEDOUT' })), Math.max(1, deadline - Date.now())))]); }
        catch (e) { res.destroy(); throw new ToolError(e.code === 'ETIMEDOUT' ? 'page took too long' : `could not read the page (${e.code || e.message})`, e.code === 'ETIMEDOUT' ? 'timeout' : 'fetch_failed'); }
        return { finalUrl: u.toString(), status, contentType, text: decode(body.buf, contentType), truncated: body.truncated, bytes: body.buf.length, redirects: hop };
    }
    throw new ToolError(`too many redirects (more than ${maxRedirects})`, 'fetch_failed');
}
