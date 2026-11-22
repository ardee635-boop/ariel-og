#!/usr/bin/env python3
import json
import sys
import urllib.request
import urllib.parse

query = sys.argv[1] if len(sys.argv) > 1 else "gold"

options = {
    "isPrefetch": False,
    "query": query,
    "scope": "pins",
    "no_fetch_context_on_resource": False,
}
source_url = f"/search/pins/?q={urllib.parse.quote(query)}"
data_param = json.dumps({"options": options, "context": {}})

url = (
    "https://www.pinterest.com/resource/BaseSearchResource/get/"
    f"?source_url={urllib.parse.quote(source_url)}"
    f"&data={urllib.parse.quote(data_param)}"
)

headers = {
    "x-pinterest-pws-handler": "www/search/[scope].js",
    "x-requested-with": "XMLHttpRequest",
    "accept": "application/json, text/javascript, */*, q=0.01",
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    ),
    "referer": f"https://www.pinterest.com{source_url}",
}

print("=== 1. Pinterest search request ===")
print("URL:", url)
print()

req = urllib.request.Request(url, headers=headers)
try:
    with urllib.request.urlopen(req, timeout=15) as resp:
        status = resp.status
        body = resp.read()
        resp_headers = dict(resp.getheaders())
except urllib.error.HTTPError as e:
    status = e.code
    body = e.read()
    resp_headers = dict(e.headers) if e.headers else {}
except Exception as e:
    print(f"REQUEST FAILED OUTRIGHT: {type(e).__name__}: {e}")
    sys.exit(1)

print(f"HTTP status: {status}")
print("content-type:", resp_headers.get("Content-Type"))
print()

print("=== 2. Response body (first 2000 chars) ===")
print(body[:2000].decode("utf-8", errors="replace"))
print()

print("=== 3. Extracted image URLs (first 6) ===")
urls = []
try:
    parsed = json.loads(body)
    results = (parsed.get("resource_response", {}) or {}).get("data", {})
    if isinstance(results, dict):
        results = results.get("results", [])
    if not isinstance(results, list):
        results = []
    for i, pin in enumerate(results[:6]):
        imgs = (pin or {}).get("images", {}) or {}
        u = (
            (imgs.get("orig") or {}).get("url")
            or (imgs.get("736x") or {}).get("url")
            or (imgs.get("474x") or {}).get("url")
        )
        print(f"{i}: {u}")
        if u:
            urls.append(u)
except json.JSONDecodeError as e:
    print(f"JSON PARSE FAILED: {e}  <-- Pinterest likely returned an HTML block/challenge page instead of JSON")
except Exception as e:
    print(f"UNEXPECTED PARSE ERROR: {type(e).__name__}: {e}")

print()
print("=== 4. For each extracted URL, what does it actually serve? ===")
for u in urls:
    print(f"--- {u} ---")
    try:
        r = urllib.request.Request(u, headers={"Range": "bytes=0-4095"})
        with urllib.request.urlopen(r, timeout=15) as resp:
            print("  HTTP:", resp.status)
            print("  content-type:", resp.headers.get("Content-Type"))
            print("  content-length:", resp.headers.get("Content-Length"))
    except urllib.error.HTTPError as e:
        print("  HTTP:", e.code)
        print("  content-type:", e.headers.get("Content-Type") if e.headers else None)
    except Exception as e:
        print(f"  FETCH FAILED: {type(e).__name__}: {e}")
    print()
