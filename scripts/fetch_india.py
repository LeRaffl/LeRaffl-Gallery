#!/usr/bin/env python3
"""
India (Vahan) fetcher — currently PROBE ONLY.

Usage
-----
    python scripts/fetch_india.py --probe
        Reachability + shape probe, meant to run from GitHub Actions (the
        maintainer's own access to Vahan historically required a VPN, so
        whether GH runners can reach it at all decides the fetcher design).

Routes under evaluation (see docs/architecture/29-expansion-candidates.md):
1. analytics dashboard  vahan.parivahan.gov.in/analytics/  (JSF/PrimeFaces)
2. vahan4dashboard reportview (JSF)
3. data.gov.in OGD API (month/category/fuel-wise registrations dataset) —
   needs a (free) API key; probed here with the public sample key that
   data.gov.in ships in its own API docs, good enough for a shape check.

A historical reference extract exists (maintainer's Vahan pulls up to
2026M04, category LMV + 2W/3W wheeler groups) but its raw sheets carry
column-alignment issues between header vintages, so the gallery series will
be built from a fresh pull once a working route is confirmed — the extract
then serves as cross-check only.
"""
import argparse
import json

import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
      "Accept-Language": "en-US,en;q=0.9"}

# data.gov.in's public documentation sample key (rate-limited, fine for probing)
OGD_SAMPLE_KEY = "579b464db66ec23bdd0000018c1e5ba53de4104f4f8b4d7cbd7ecc06"
OGD_DATASET = "76192d23-59ba-4be8-9ccb-a469e83dc552"

TARGETS = [
    ("vahan4 dashboard", "https://vahan.parivahan.gov.in/vahan4dashboard/"),
    ("vahan4 reportview", "https://vahan.parivahan.gov.in/vahan4dashboard/vahan/view/reportview.xhtml"),
    ("analytics", "https://analytics.parivahan.gov.in/analytics/publicdashboard"),
    ("parivahan root", "https://parivahan.gov.in/"),
    ("data.gov.in root", "https://www.data.gov.in/"),
    ("OGD API sample", f"https://api.data.gov.in/resource/{OGD_DATASET}?api-key={OGD_SAMPLE_KEY}&format=json&limit=3"),
]


def probe() -> None:
    print("=== PROBE: India source reachability from this runner ===", flush=True)
    s = requests.Session()
    s.headers.update(UA)
    for name, url in TARGETS:
        try:
            r = s.get(url, timeout=45, allow_redirects=True)
            body = r.text[:400].replace("\n", " ")
            print(f"\n[{name}] {url}\n  HTTP {r.status_code}  final={r.url}\n  head: {body}", flush=True)
            if "api.data.gov.in" in url and r.ok:
                try:
                    j = r.json()
                    print(f"  OGD: total={j.get('total')} updated={j.get('updated_date')} "
                          f"fields={[f.get('id') for f in j.get('field', [])]}")
                    for rec in j.get("records", [])[:3]:
                        print(f"  rec: {json.dumps(rec, ensure_ascii=False)[:300]}")
                except ValueError:
                    pass
        except requests.RequestException as e:
            print(f"\n[{name}] {url}\n  FAILED: {e}", flush=True)
    print("\n=== PROBE DONE ===")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--probe", action="store_true")
    args = ap.parse_args()
    if args.probe:
        probe()
        return
    raise SystemExit("Only --probe is implemented until a working route is confirmed.")


if __name__ == "__main__":
    main()
