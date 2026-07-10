#!/usr/bin/env python3
"""
Fetch Israel new passenger-car registration data from the Ministry of
Transport's open vehicle registry on data.gov.il and upsert data/Israel.csv.

Usage
-----
    python scripts/fetch_israel.py --probe
        Explore the datastore: list the dataset's resources, dump field
        schemas + a sample record, distinct values of fuel/scope-ish fields,
        and per-month record counts. Used to develop/verify the mapping from
        CI (the source is not reachable from every dev sandbox).

    python scripts/fetch_israel.py [--start YYYY-MM] [--end YYYY-MM] [--force]
        Aggregate monthly new registrations by fuel type and upsert
        data/Israel.csv. Default window: last 3 months (recent months are
        re-counted because late registrations/corrections trickle in).

Source
------
https://data.gov.il/dataset/private-and-commercial-vehicles
("מספרי רישוי של כלי רכב פרטיים ומסחריים", Ministry of Transport licensing DB)
CKAN datastore API. The dataset is a *stock snapshot* of currently-registered
vehicles; monthly new registrations are derived by grouping on the
road-entry date (moed_aliya_lakvish). Deregistered vehicles drop out of the
snapshot over time, so deep history undercounts slightly — recent months are
effectively exact.

Fuel mapping (sug_delek_nm) — VERIFY VIA --probe BEFORE TRUSTING
----------------------------------------------------------------
    חשמל          → BEV
    חשמל/בנזין    → HEV   (combined HEV+PHEV unless a plug-in split exists)
    חשמל/דיזל     → HEV
    בנזין         → PETROL
    דיזל          → DIESEL
    גפ"מ / other  → OTHERS
Unmapped values are a hard error so CI surfaces schema drift immediately.
"""
import argparse
import csv
import json
import os
import re
import sys
import time
from datetime import date
from pathlib import Path

import requests

API = "https://data.gov.il/api/3/action"
DATASET_ID = "private-and-commercial-vehicles"
# Known datastore resource of the registry snapshot; probe/package_show is the
# authority — this is only the fallback if package_show is unavailable.
FALLBACK_RESOURCE_IDS = ["053cea08-09bc-40ec-8f7a-156f0677aff3"]

SOURCE = "data.gov.il (Ministry of Transport registry)"
CSV_PATH = "data/Israel.csv"
VARIANT = "Whole"
DATE_FIELD = "moed_aliya_lakvish"
FUEL_FIELD = "sug_delek_nm"

CSV_COLUMNS = [
    "period", "time_interval", "variant", "source",
    "BEV", "PHEV", "HEV", "PETROL", "DIESEL", "OTHERS", "TOTAL", "notes",
]

FUEL_MAP = {
    "חשמל": "BEV",
    "חשמל/בנזין": "HEV",
    "חשמל/דיזל": "HEV",
    "בנזין": "PETROL",
    "דיזל": "DIESEL",
}
# Values that are known and deliberately bucketed into OTHERS.
FUEL_OTHERS = {"גפ\"מ", "גז", "גז טבעי דחוס", "מימן"}

session = requests.Session()
# data.gov.il rejects default python user agents.
session.headers.update({"User-Agent": "Mozilla/5.0 (compatible; LeRaffl-Gallery/1.0; +https://leraffl.github.io/LeRaffl-Gallery/)"})


def api_get(action: str, **params) -> dict:
    """GET a CKAN action; params values are passed as query params."""
    url = f"{API}/{action}"
    for attempt in range(4):
        try:
            r = session.get(url, params=params, timeout=90)
            r.raise_for_status()
            payload = r.json()
            if not payload.get("success"):
                raise RuntimeError(f"CKAN error on {action}: {payload.get('error')}")
            return payload["result"]
        except (requests.RequestException, ValueError) as e:
            if attempt == 3:
                raise
            wait = 2 ** (attempt + 1)
            print(f"  ! {action} failed ({e}); retrying in {wait}s", flush=True)
            time.sleep(wait)


def datastore_resources() -> list[dict]:
    """All datastore-active resources of the registry dataset."""
    try:
        pkg = api_get("package_show", id=DATASET_ID)
    except Exception as e:
        print(f"  ! package_show failed ({e}); using fallback resource ids")
        return [{"id": rid, "name": "(fallback)"} for rid in FALLBACK_RESOURCE_IDS]
    res = [r for r in pkg.get("resources", []) if r.get("datastore_active")]
    return res or [{"id": rid, "name": "(fallback)"} for rid in FALLBACK_RESOURCE_IDS]


def ds_search(resource_id: str, **params) -> dict:
    return api_get("datastore_search", resource_id=resource_id, **params)


def month_records(resource_id: str, period: str, fields: list[str]) -> list[dict]:
    """All records of one YYYY-MM month from one resource (paged)."""
    out, offset = [], 0
    filters = json.dumps({DATE_FIELD: period}, ensure_ascii=False)
    while True:
        res = ds_search(resource_id, filters=filters, fields=",".join(fields),
                        limit=32000, offset=offset)
        recs = res.get("records", [])
        out.extend(recs)
        total = res.get("total", len(out))
        offset += len(recs)
        if not recs or offset >= total:
            return out


# ---------------------------------------------------------------- probe mode

def probe() -> None:
    print("=== PROBE: data.gov.il vehicle registry ===", flush=True)

    print("\n--- package_show:", DATASET_ID)
    resources = datastore_resources()
    for r in resources:
        print(f"  resource: id={r['id']} name={r.get('name')!r} "
              f"last_modified={r.get('last_modified')}")

    interesting = re.compile(r"delek|hanaa|technolog|moed|aliya|degem|merkav|sug|mishkal|kvutza", re.I)

    for r in resources:
        rid = r["id"]
        print(f"\n--- resource {rid} ({r.get('name')!r})")
        res = ds_search(rid, limit=1)
        total = res.get("total")
        fields = [f["id"] for f in res.get("fields", [])]
        print(f"  total records: {total}")
        print(f"  fields: {fields}")
        for rec in res.get("records", []):
            print("  sample record:")
            print("   ", json.dumps(rec, ensure_ascii=False, default=str))

        # Distinct values of candidate categorical fields
        for f in fields:
            if f == "_id" or not interesting.search(f):
                continue
            if any(k in f.lower() for k in ("delek", "hanaa", "technolog", "merkav", "sug_degem", "kvutza")):
                try:
                    dv = ds_search(rid, distinct="true", fields=f, limit=60)
                    vals = [rec.get(f) for rec in dv.get("records", [])]
                    print(f"  distinct {f} ({len(vals)}): {json.dumps(vals, ensure_ascii=False, default=str)}")
                except Exception as e:
                    print(f"  distinct {f}: FAILED ({e})")

        # Date-field mechanics: filter on the sample's own value, then on
        # recent YYYY-MM strings.
        recs = res.get("records", [])
        if recs and DATE_FIELD in recs[0]:
            sample_val = recs[0][DATE_FIELD]
            print(f"  {DATE_FIELD} sample value: {sample_val!r}")
            for probe_val in {str(sample_val), "2026-05", "2026-04", "2025-12"}:
                try:
                    c = ds_search(rid, filters=json.dumps({DATE_FIELD: probe_val}),
                                  fields="_id", limit=1)
                    print(f"  count where {DATE_FIELD}={probe_val!r}: {c.get('total')}")
                except Exception as e:
                    print(f"  count where {DATE_FIELD}={probe_val!r}: FAILED ({e})")

        # Fuel × recent-month cross-tab (only if both fields exist)
        if recs and FUEL_FIELD in recs[0] and DATE_FIELD in recs[0]:
            try:
                dv = ds_search(rid, distinct="true", fields=FUEL_FIELD, limit=60)
                fuel_vals = [x.get(FUEL_FIELD) for x in dv.get("records", [])]
                for period in ("2026-05", "2025-06"):
                    line = {}
                    for fv in fuel_vals:
                        c = ds_search(rid, filters=json.dumps({DATE_FIELD: period, FUEL_FIELD: fv}, ensure_ascii=False),
                                      fields="_id", limit=1)
                        line[str(fv)] = c.get("total")
                    print(f"  {period} × {FUEL_FIELD}: {json.dumps(line, ensure_ascii=False)}")
            except Exception as e:
                print(f"  cross-tab failed: {e}")

    # Hunt for the vehicle-models dataset (possible PHEV/HEV disambiguator)
    print("\n--- package_search: model/degem datasets")
    try:
        found = api_get("package_search", q="דגמי רכב", rows=15)
        for pkg in found.get("results", []):
            print(f"  dataset: {pkg['name']}  title={pkg.get('title')!r}")
            for rr in pkg.get("resources", []):
                if rr.get("datastore_active"):
                    print(f"    resource: {rr['id']} name={rr.get('name')!r}")
        # Sample any resource whose dataset name hints at model specs
        for pkg in found.get("results", []):
            if any(k in (pkg.get("title") or "") + pkg["name"] for k in ("דגמ", "degem", "models")):
                for rr in pkg.get("resources", []):
                    if not rr.get("datastore_active"):
                        continue
                    try:
                        s = ds_search(rr["id"], limit=1)
                        flds = [f["id"] for f in s.get("fields", [])]
                        tech = [f for f in flds if re.search(r"hanaa|technolog|delek", f, re.I)]
                        if tech:
                            print(f"    >> {pkg['name']} / {rr['id']} fields={flds}")
                            for rec in s.get("records", []):
                                print("       sample:", json.dumps(rec, ensure_ascii=False, default=str))
                    except Exception:
                        pass
    except Exception as e:
        print(f"  package_search failed: {e}")

    print("\n=== PROBE DONE ===")


# ---------------------------------------------------------------- fetch mode

def month_range(start: str, end: str) -> list[str]:
    y0, m0 = map(int, start.split("-"))
    y1, m1 = map(int, end.split("-"))
    out = []
    y, m = y0, m0
    while (y, m) <= (y1, m1):
        out.append(f"{y}-{m:02d}")
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def default_window() -> tuple[str, str]:
    t = date.today()
    end_y, end_m = (t.year, t.month - 1) if t.month > 1 else (t.year - 1, 12)
    start_m, start_y = end_m - 2, end_y
    if start_m < 1:
        start_m += 12
        start_y -= 1
    return f"{start_y}-{start_m:02d}", f"{end_y}-{end_m:02d}"


def aggregate_month(resources: list[dict], period: str) -> dict | None:
    counts = {c: 0 for c in ("BEV", "PHEV", "HEV", "PETROL", "DIESEL", "OTHERS")}
    unmapped: dict = {}
    n = 0
    for r in resources:
        recs = month_records(r["id"], period, [FUEL_FIELD])
        n += len(recs)
        for rec in recs:
            fuel = (rec.get(FUEL_FIELD) or "").strip()
            col = FUEL_MAP.get(fuel)
            if col is None:
                if fuel in FUEL_OTHERS or fuel == "":
                    col = "OTHERS"
                else:
                    unmapped[fuel] = unmapped.get(fuel, 0) + 1
                    col = "OTHERS"
            counts[col] += 1
    if unmapped:
        raise SystemExit(f"Unmapped {FUEL_FIELD} values in {period}: {unmapped} — "
                         f"extend FUEL_MAP/FUEL_OTHERS deliberately.")
    if n == 0:
        return None
    total = sum(counts.values())
    print(f"  {period}: {total} registrations {counts}")
    return {
        "period": period, "time_interval": "monthly", "variant": VARIANT,
        "source": SOURCE,
        **{c: (float(v) if v else "") for c, v in counts.items()},
        "TOTAL": float(total), "notes": "",
    }


def upsert_csv(csv_path: str, new_rows: dict) -> tuple[int, int]:
    existing: dict = {}
    if os.path.exists(csv_path):
        with open(csv_path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                for c in CSV_COLUMNS:
                    row.setdefault(c, "")
                existing[(row["period"], row["variant"])] = {k: row[k] for k in CSV_COLUMNS}
    added = updated = 0
    for key, new_row in sorted(new_rows.items()):
        if key not in existing:
            existing[key] = new_row
            added += 1
        else:
            existing[key] = {**existing[key], **new_row}
            updated += 1
    Path(csv_path).parent.mkdir(parents=True, exist_ok=True)
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS, lineterminator="\n")
        w.writeheader()
        for key in sorted(existing.keys(), key=lambda k: (k[1], k[0])):
            w.writerow(existing[key])
    return added, updated


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--probe", action="store_true", help="Explore the datastore schema and exit.")
    ap.add_argument("--start", help="First month to (re-)count, YYYY-MM.")
    ap.add_argument("--end", help="Last month to (re-)count, YYYY-MM.")
    ap.add_argument("--force", action="store_true", help="(reserved) skip freshness early-exit")
    args = ap.parse_args()

    if args.probe:
        probe()
        return

    start, end = default_window()
    start = args.start or start
    end = args.end or end
    print(f"Fetching Israel registrations {start} .. {end}")

    resources = datastore_resources()
    print(f"Registry resources: {[r['id'] for r in resources]}")

    new_rows = {}
    for period in month_range(start, end):
        row = aggregate_month(resources, period)
        if row:
            new_rows[(period, VARIANT)] = row

    if not new_rows:
        print("No rows extracted.")
        sys.exit(1)
    added, updated = upsert_csv(CSV_PATH, new_rows)
    print(f"{added} added, {updated} updated -> {CSV_PATH}")


if __name__ == "__main__":
    main()
