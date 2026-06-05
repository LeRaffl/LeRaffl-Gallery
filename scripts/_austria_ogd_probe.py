#!/usr/bin/env python3
"""TEMPORARY discovery probe for the Statistik Austria OGD portal.

Run on a GitHub Actions runner (the target network) to verify reachability of
data.statistik.gv.at and dump the structure of the new-registration datasets so
we can build a real OGD-based fetcher. This file is throwaway — delete once the
OGD migration in fetch_austria.py is done.
"""
import io
import socket
import sys

import requests

# GH runners have no IPv6 route; force IPv4 (same as fetch_austria.py).
_orig = socket.getaddrinfo
socket.getaddrinfo = lambda h, p, f=0, t=0, pr=0, fl=0: _orig(h, p, socket.AF_INET, t, pr, fl)

S = requests.Session()
S.headers.update({"User-Agent": "LeRaffl-Gallery/austria-ogd-probe"})

DATA = "https://data.statistik.gv.at/data/"
KNOWN_PKW = "OGD_fkfzul0759_OD_PkwNZL_1"


def get(url, **kw):
    print(f"\n>>> GET {url}", flush=True)
    r = S.get(url, timeout=30, **kw)
    print(f"    HTTP {r.status_code}, {len(r.content)} bytes", flush=True)
    return r


def dump_csv(name, text, max_rows=12):
    print(f"--- {name} (first {max_rows} lines) ---", flush=True)
    for i, line in enumerate(text.splitlines()):
        if i >= max_rows:
            print(f"    ... ({len(text.splitlines())} lines total)", flush=True)
            break
        print("   ", line, flush=True)


def probe_dataset(ds):
    print(f"\n========== DATASET {ds} ==========", flush=True)
    try:
        fact = get(DATA + ds + ".csv")
        fact.raise_for_status()
    except Exception as e:
        print(f"    !! fact download failed: {e!r}", flush=True)
        return
    dump_csv(ds + ".csv", fact.text, max_rows=8)

    try:
        hdr = get(DATA + ds + "_HEADER.csv")
        hdr.raise_for_status()
        dump_csv(ds + "_HEADER.csv", hdr.text, max_rows=40)
        # Find classification field codes (start with "C-") and dump each.
        codes = []
        for line in hdr.text.splitlines()[1:]:
            cell = line.split(";")[0].strip().strip('"')
            if cell.startswith("C-"):
                codes.append(cell)
        print(f"\n    classification codes: {codes}", flush=True)
        for code in codes:
            try:
                c = get(DATA + ds + "_" + code + ".csv")
                c.raise_for_status()
                dump_csv(ds + "_" + code + ".csv", c.text, max_rows=60)
            except Exception as e:
                print(f"    !! classification {code} failed: {e!r}", flush=True)
    except Exception as e:
        print(f"    !! header download failed: {e!r}", flush=True)


def discover_via_ckan():
    """Enumerate Statistik Austria new-registration datasets via data.gv.at CKAN."""
    url = ("https://www.data.gv.at/katalog/api/3/action/package_search"
           "?fq=organization:statistik-austria&q=neuzulassung&rows=50")
    try:
        r = get(url)
        r.raise_for_status()
        data = r.json()
        results = data.get("result", {}).get("results", [])
        print(f"\n    CKAN found {len(results)} datasets:", flush=True)
        for d in results:
            title = d.get("title", "")
            name = d.get("name", "")
            print(f"      * {name}  |  {title}", flush=True)
            for res in d.get("resources", []):
                fmt = res.get("format", "")
                ru = res.get("url", "")
                if "data.statistik.gv.at/data/" in ru and not ru.endswith("_HEADER.csv"):
                    print(f"          [{fmt}] {ru}", flush=True)
    except Exception as e:
        print(f"    !! CKAN discovery failed: {e!r}", flush=True)


if __name__ == "__main__":
    print("Python:", sys.version, flush=True)
    discover_via_ckan()
    targets = sys.argv[1:] or [KNOWN_PKW]
    for ds in targets:
        probe_dataset(ds)
    print("\n[probe] done.", flush=True)
