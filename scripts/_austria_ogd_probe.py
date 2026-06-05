#!/usr/bin/env python3
"""TEMPORARY discovery probe v2 for Austria open data.

Finding so far: GitHub Actions can reach www.data.gv.at but NOT
data.statistik.gv.at / www.statistik.at (both connect-timeout / blocked).
This probe checks which hosts are reachable and where the new-registration
dataset's actual CSV bytes can be downloaded from. Throwaway.
"""
import json
import socket
import sys

import requests

_orig = socket.getaddrinfo
socket.getaddrinfo = lambda h, p, f=0, t=0, pr=0, fl=0: _orig(h, p, socket.AF_INET, t, pr, fl)

S = requests.Session()
S.headers.update({"User-Agent": "LeRaffl-Gallery/austria-ogd-probe"})

DATASET = "OGD_fkfzul0759_OD_PkwNZL_1"


def reach(url, method="GET"):
    print(f"\n>>> {method} {url}", flush=True)
    try:
        r = S.request(method, url, timeout=12, allow_redirects=False)
        loc = r.headers.get("Location", "")
        ct = r.headers.get("Content-Type", "")
        print(f"    HTTP {r.status_code}  type={ct}  len={len(r.content)}"
              + (f"  ->Location: {loc}" if loc else ""), flush=True)
        return r
    except Exception as e:
        print(f"    !! {type(e).__name__}: {str(e)[:160]}", flush=True)
        return None


def show_json(r, max_chars=1500):
    if r is None:
        return None
    try:
        data = r.json()
        print("    JSON:", json.dumps(data, ensure_ascii=False)[:max_chars], flush=True)
        return data
    except Exception as e:
        print(f"    (not json: {e}); body[:300]={r.text[:300]!r}", flush=True)
        return None


print("Python:", sys.version, flush=True)

# 1) Host reachability matrix.
print("\n===== HOST REACHABILITY =====", flush=True)
reach("https://www.data.gv.at/", "HEAD")
reach("https://data.europa.eu/en", "HEAD")
reach("https://data.statistik.gv.at/data/" + DATASET + ".csv", "HEAD")

# 2) data.gv.at catalog API candidates (find dataset + resource URLs).
print("\n===== data.gv.at CKAN search =====", flush=True)
for base in [
    "https://www.data.gv.at/katalog/api/3/action/package_search?q=Kfz-Neuzulassungen+Kraftstoff&rows=20",
    "https://www.data.gv.at/api/3/action/package_search?q=Kfz-Neuzulassungen+Kraftstoff&rows=20",
    "https://www.data.gv.at/api/hub/search/datasets?query=Neuzulassungen&limit=20",
]:
    d = show_json(reach(base))
    if d and d.get("success") and d.get("result", {}).get("results"):
        for ds in d["result"]["results"]:
            print(f"      DS {ds.get('name')} | {ds.get('title')}", flush=True)
            for res in ds.get("resources", []):
                print(f"          [{res.get('format')}] {res.get('url')}", flush=True)
        break

# 3) data.europa.eu search (mirrors member-state OGD; may host distributions).
print("\n===== data.europa.eu search =====", flush=True)
show_json(reach(
    "https://data.europa.eu/api/hub/search/search?q=" + DATASET + "&limit=5"))
show_json(reach(
    "https://data.europa.eu/api/hub/search/search?q=Kfz-Neuzulassungen%20Kraftstoff&limit=5"))

# 4) Does data.gv.at proxy/serve the raw file, or only redirect to statistik?
print("\n===== data.gv.at dataset page (look for resource links) =====", flush=True)
reach("https://www.data.gv.at/katalog/api/3/action/package_show?id=" + DATASET.lower())
reach("https://www.data.gv.at/katalog/api/3/action/package_show?id=" + DATASET)

print("\n[probe v2] done.", flush=True)
