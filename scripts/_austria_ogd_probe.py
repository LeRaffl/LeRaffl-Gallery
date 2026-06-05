#!/usr/bin/env python3
"""TEMPORARY discovery probe v3 for Austria open data.

Confirmed: www.statistik.at AND data.statistik.gv.at are both blocked from the
GitHub Actions network (connect timeout). Catalog portals (data.gv.at,
data.europa.eu) are reachable but only hold metadata. This probe checks:
  (a) whether a public fetch relay can pull the OGD CSV from the runner, and
  (b) where data.europa.eu's distribution/download URLs actually point.
Throwaway.
"""
import json
import socket
import sys
import urllib.parse as up

import requests

_orig = socket.getaddrinfo
socket.getaddrinfo = lambda h, p, f=0, t=0, pr=0, fl=0: _orig(h, p, socket.AF_INET, t, pr, fl)

S = requests.Session()
S.headers.update({"User-Agent": "Mozilla/5.0 (LeRaffl-Gallery austria probe)"})

TARGET = "https://data.statistik.gv.at/data/OGD_fkfzul0759_OD_PkwNZL_1.csv"


def get(url, **kw):
    print(f"\n>>> GET {url[:140]}", flush=True)
    try:
        r = S.get(url, timeout=25, **kw)
        body = r.content
        looks_csv = (b";" in body[:2000]) and (b"OGD" in body[:200] or b"C-" in body[:400]
                                               or b"F-" in body[:400])
        print(f"    HTTP {r.status_code}  type={r.headers.get('Content-Type','')}  "
              f"len={len(body)}  looks_like_ogd_csv={looks_csv}", flush=True)
        if looks_csv or (r.ok and len(body) < 1500):
            print("    head:", body[:300], flush=True)
        return r
    except Exception as e:
        print(f"    !! {type(e).__name__}: {str(e)[:160]}", flush=True)
        return None


print("Python:", sys.version, flush=True)

# (a) Public relays — can any pull the blocked OGD CSV from the runner?
print("\n===== PUBLIC RELAYS =====", flush=True)
enc = up.quote(TARGET, safe="")
get("https://api.allorigins.win/raw?url=" + enc)
get("https://corsproxy.io/?url=" + enc)
get("https://r.jina.ai/" + TARGET)
get("https://thingproxy.freeboard.io/fetch/" + TARGET)

# (b) data.europa.eu: find the fuel dataset and inspect its distribution hosts.
print("\n===== data.europa.eu distributions =====", flush=True)
r = get("https://data.europa.eu/api/hub/search/search?q=OGD_fkfzul0759&limit=5")
try:
    res = r.json()["result"]["results"]
    for d in res:
        print("  dataset:", d.get("id"), "|", json.dumps(d.get("title", {}), ensure_ascii=False)[:120], flush=True)
        for dist in d.get("distributions", []):
            url = (dist.get("access_url") or dist.get("download_url") or
                   dist.get("accessURL") or dist.get("downloadURL"))
            fmt = dist.get("format", {})
            print("     dist:", (fmt.get("label") if isinstance(fmt, dict) else fmt), "->", url, flush=True)
except Exception as e:
    print("  parse failed:", repr(e), flush=True)

# Also dump the raw distribution section for the first hit for full visibility.
print("\n===== europa raw first-result distributions (verbatim) =====", flush=True)
try:
    res = S.get("https://data.europa.eu/api/hub/search/search?q=OGD_fkfzul0759&limit=2",
                timeout=25).json()
    print(json.dumps(res["result"]["results"][0].get("distributions", []),
                     ensure_ascii=False)[:2000], flush=True)
except Exception as e:
    print("  failed:", repr(e), flush=True)

print("\n[probe v3] done.", flush=True)
