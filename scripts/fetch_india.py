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
# The mandi-prices resource every data.gov.in docs example uses — tells the
# sample key's global health apart from per-resource restrictions.
OGD_DEMO = "9ef84268-d588-465a-a308-a864a43d0070"

TARGETS = [
    # Probe v1 results (2026-07-10): vahan.parivahan.gov.in resets foreign
    # connections; api.data.gov.in reachable but sample key 403 on the Vahan
    # dataset. Probe v2 hunts key-less routes.
    ("OGD sample key vs demo resource", f"https://api.data.gov.in/resource/{OGD_DEMO}?api-key={OGD_SAMPLE_KEY}&format=json&limit=2"),
    ("OGD vahan dataset keyless", f"https://api.data.gov.in/resource/{OGD_DATASET}?format=json&limit=2"),
    ("OGD vahan dataset page (download links)", f"https://www.data.gov.in/apis/{OGD_DATASET}"),
    ("data.gov.in backend resource meta", f"https://www.data.gov.in/backend/dmspublic/v1/resources?filters%5Bid%5D={OGD_DATASET}"),
    ("IndiaDataPortal CKAN search", "https://ckan.indiadataportal.com/api/3/action/package_search?q=vahan+fuel&rows=8"),
    ("ICED NITI transport", "https://iced.niti.gov.in/transport/electric-mobility/ev-sales"),
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
            if r.ok and ("api.data.gov.in" in url or "ckan" in url or "/backend/" in url):
                try:
                    j = r.json()
                    if "ckan" in url:
                        res = j.get("result", {})
                        print(f"  CKAN: count={res.get('count')}")
                        for pkg in res.get("results", [])[:8]:
                            print(f"    dataset: {pkg.get('name')}  title={pkg.get('title')!r}")
                            for rr in pkg.get("resources", [])[:6]:
                                print(f"      resource: {rr.get('id')} fmt={rr.get('format')} "
                                      f"datastore={rr.get('datastore_active')} name={rr.get('name')!r}")
                    else:
                        print(f"  JSON keys: {list(j)[:12]}")
                        print(f"  total={j.get('total')} updated={j.get('updated_date')} "
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
