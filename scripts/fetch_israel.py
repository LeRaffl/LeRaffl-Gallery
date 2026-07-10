#!/usr/bin/env python3
"""
Fetch Israel new passenger-car registration data from the Ministry of
Transport's open vehicle registry on data.gov.il and upsert data/Israel.csv.

Usage
-----
    python scripts/fetch_israel.py --probe
        Explore the datastore: distinct propulsion-technology values in the
        WLTP model catalogue, P/M scope counts per month vs I-VIA reference
        figures. Used to develop/verify the mapping from CI (the source is
        not reachable from every dev sandbox).

    python scripts/fetch_israel.py [--start YYYY-MM] [--end YYYY-MM] [--dry-run]
        Aggregate monthly new registrations by fuel type and upsert
        data/Israel.csv. Default window: last 3 months (the registry is a
        living snapshot; recent months are re-counted on every run).

Source
------
https://data.gov.il/dataset/private-and-commercial-vehicles
("מספרי רישוי של כלי רכב פרטיים ומסחריים", Ministry of Transport licensing DB)
CKAN datastore API, resource מאגר מספרי רישוי של כלי רכב (~4.15M records =
all currently-registered private & light-commercial vehicles). The second
resource of the dataset ("… - המשך") holds EXTRA COLUMNS for the same
vehicles (tyre codes etc.), NOT extra rows — never aggregate over it.

Monthly new registrations are derived by grouping on the road-entry month
(`moed_aliya_lakvish`). Quirks verified by probe (2026-07):

- `moed_aliya_lakvish` is UNPADDED: "2016-3", "2025-12" — query values must
  drop the leading zero of the month; CSV periods stay zero-padded.
- The dataset is a *stock snapshot* of currently-registered vehicles;
  deregistered vehicles (scrapped/exported) drop out over time, so deep
  history undercounts slightly. Recent months are effectively exact.
- Scope: `sug_degem` = "P" (private passenger cars) is the gallery `Whole`;
  "M" (light commercial ≤3.5t) is excluded (potential future Vans variant).
- No motorcycles / heavy trucks / buses in this dataset.

Fuel mapping (sug_delek_nm; 6 values verified by probe)
-------------------------------------------------------
    חשמל          → BEV
    בנזין         → PETROL
    דיזל          → DIESEL
    גפ"מ          → OTHERS  (LPG)
    חשמל/בנזין    → HEV or PHEV via WLTP model-catalogue join
    חשמל/דיזל     → HEV or PHEV via WLTP model-catalogue join

The registry itself does not separate PHEV from HEV. The model catalogue
(dataset degem-rechev-wltp, "תוצרים ודגמים של כלי רכב פרטי ומסחרי") carries
`technologiat_hanaa_nm` (propulsion technology: PLUG IN / היברידי רגיל /
רכב חשמלי / הנעה רגילה). Hybrid registry rows are classified by joining on
(tozeret_cd, degem_cd, shnat_yitzur, ramat_gimur) — the trim level is part
of the key because one model code + year can carry both HEV and PHEV trims —
with a majority vote over the model's trims as fallback when the exact trim
is missing. Hybrids with no catalogue match at all default to HEV (PHEVs
were negligible in the pre-WLTP-catalogue years); per-month join statistics
are printed on every run.

Unmapped fuel values are a hard error so CI surfaces schema drift.
"""
import argparse
import csv
import json
import os
import sys
import time
from datetime import date
from pathlib import Path

import requests

API = "https://data.gov.il/api/3/action"
DATASET_ID = "private-and-commercial-vehicles"
REGISTRY_RESOURCE = "053cea08-09bc-40ec-8f7a-156f0677aff3"   # מאגר מספרי רישוי של כלי רכב
WLTP_RESOURCE = "142afde2-6228-49f9-8a29-9b6c3a0cbe40"       # תוצרים ודגמים של כלי רכב WLTP

SOURCE = "data.gov.il (Ministry of Transport registry)"
CSV_PATH = "data/Israel.csv"
VARIANT = "Whole"
DATE_FIELD = "moed_aliya_lakvish"
FUEL_FIELD = "sug_delek_nm"
SCOPE_FIELD = "sug_degem"          # P = private passenger car (= Whole)
SCOPE_VALUE = "P"

CSV_COLUMNS = [
    "period", "time_interval", "variant", "source",
    "BEV", "PHEV", "HEV", "PETROL", "DIESEL", "OTHERS", "TOTAL", "notes",
]

FUEL_MAP = {
    "חשמל": "BEV",
    "בנזין": "PETROL",
    "דיזל": "DIESEL",
    "גפ\"מ": "OTHERS",
}
HYBRID_VALUES = {"חשמל/בנזין", "חשמל/דיזל"}

# technologiat_hanaa_nm values that mean plug-in hybrid. Verified via probe;
# substring match on "פלאג" (plug) keeps us robust to phrasing variants.
PLUGIN_MARKERS = ("פלאג", "plug")

session = requests.Session()
# data.gov.il rejects default python user agents.
session.headers.update({"User-Agent": "Mozilla/5.0 (compatible; LeRaffl-Gallery/1.0; +https://leraffl.github.io/LeRaffl-Gallery/)"})


def api_get(action: str, **params) -> dict:
    url = f"{API}/{action}"
    for attempt in range(4):
        try:
            r = session.get(url, params=params, timeout=120)
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


def ds_search(resource_id: str, **params) -> dict:
    return api_get("datastore_search", resource_id=resource_id, **params)


def ds_all_records(resource_id: str, fields: list[str], filters: dict | None = None) -> list[dict]:
    """Page through a datastore query and return all records."""
    out, offset = [], 0
    kw = {"fields": ",".join(fields), "limit": 32000}
    if filters:
        kw["filters"] = json.dumps(filters, ensure_ascii=False)
    while True:
        res = ds_search(resource_id, offset=offset, **kw)
        recs = res.get("records", [])
        out.extend(recs)
        total = res.get("total", len(out))
        offset += len(recs)
        if not recs or offset >= total:
            return out


def unpadded(period: str) -> str:
    """'2026-05' -> '2026-5' (the registry stores months unpadded)."""
    y, m = period.split("-")
    return f"{y}-{int(m)}"


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
    months = []
    y, m = t.year, t.month
    for _ in range(3):
        m -= 1
        if m == 0:
            y, m = y - 1, 12
        months.append(f"{y}-{m:02d}")
    return months[-1], months[0]


# ------------------------------------------------------- WLTP model lookup

def load_wltp_lookup() -> tuple[dict, dict]:
    """
    Two lookups from the model catalogue:
      exact:  (tozeret_cd, degem_cd, shnat_yitzur, ramat_gimur) -> is_plugin
      votes:  (tozeret_cd, degem_cd, shnat_yitzur) -> {False: n, True: m}
    The trim level (ramat_gimur) matters: the same model code + year can
    carry both an HEV and a PHEV trim, so a triple-only join with a
    "prefer plug-in" tie-break misclassifies entire model families
    (verified 2026-07: it turned every April-2026 hybrid into a PHEV).
    """
    print("Loading WLTP model catalogue …", flush=True)
    recs = ds_all_records(
        WLTP_RESOURCE,
        ["tozeret_cd", "degem_cd", "shnat_yitzur", "ramat_gimur", "technologiat_hanaa_nm"],
    )
    exact: dict = {}
    votes: dict = {}
    for r in recs:
        tech = (r.get("technologiat_hanaa_nm") or "").strip()
        if not tech:
            continue
        plugin = is_plugin(tech)
        triple = (r.get("tozeret_cd"), r.get("degem_cd"), r.get("shnat_yitzur"))
        trim = (r.get("ramat_gimur") or "").strip()
        exact[triple + (trim,)] = plugin
        votes.setdefault(triple, {False: 0, True: 0})[plugin] += 1
    mixed = sum(1 for v in votes.values() if v[False] and v[True])
    print(f"  {len(recs):,} catalogue rows -> {len(exact):,} trim keys, "
          f"{len(votes):,} model triples ({mixed:,} with mixed HEV/PHEV trims)", flush=True)
    return exact, votes


def is_plugin(tech: str) -> bool:
    t = tech.lower()
    return any(marker in t for marker in PLUGIN_MARKERS)


def classify_hybrid(rec: dict, exact: dict, votes: dict) -> tuple[str, str]:
    """-> (column, how) where column is PHEV/HEV and how tags the join level."""
    triple = (rec.get("tozeret_cd"), rec.get("degem_cd"), rec.get("shnat_yitzur"))
    trim = (rec.get("ramat_gimur") or "").strip()
    hit = exact.get(triple + (trim,))
    if hit is not None:
        return ("PHEV" if hit else "HEV"), "trim"
    v = votes.get(triple)
    if v:
        # Majority vote across the model's trims; ties break to HEV (the
        # larger bucket in Israel, so the smaller expected error).
        return ("PHEV" if v[True] > v[False] else "HEV"), "majority"
    return "HEV", "unmatched"


# ---------------------------------------------------------------- probe mode

def probe() -> None:
    print("=== PROBE v3 ===", flush=True)

    print("\n--- WLTP catalogue: rows per technologiat_hanaa_nm")
    dv = ds_search(WLTP_RESOURCE, distinct="true", fields="technologiat_hanaa_nm", limit=60)
    for r in dv.get("records", []):
        tech = r.get("technologiat_hanaa_nm")
        n = ds_search(WLTP_RESOURCE, filters=json.dumps({"technologiat_hanaa_nm": tech}, ensure_ascii=False),
                      fields="_id", limit=1).get("total")
        print(f"  {tech!r}: {n}")

    exact, votes = load_wltp_lookup()

    print("\n--- Trial aggregation (trim-level hybrid split): 2025-06, 2026-01 .. 2026-05")
    print("    I-VIA Q4-2025 reference shares: petrol 36.4%, hybrid 26.2%, PHEV 11.5%")
    for period in ("2025-06", "2026-01", "2026-02", "2026-03", "2026-04", "2026-05"):
        row = aggregate_month(period, (exact, votes))
        if row:
            t = row["TOTAL"]
            shares = {c: f"{100 * float(row[c] or 0) / t:.1f}%" for c in
                      ("BEV", "PHEV", "HEV", "PETROL", "DIESEL")}
            print(f"  -> {period} shares: {shares}")

    print("\n=== PROBE DONE ===")


# ---------------------------------------------------------------- fetch mode

def aggregate_month(period: str, wltp_lookup: tuple[dict, dict]) -> dict | None:
    """One CSV row for period (YYYY-MM, padded) or None if no data yet."""
    exact, votes = wltp_lookup
    recs = ds_all_records(
        REGISTRY_RESOURCE,
        [FUEL_FIELD, "tozeret_cd", "degem_cd", "shnat_yitzur", "ramat_gimur"],
        filters={DATE_FIELD: unpadded(period), SCOPE_FIELD: SCOPE_VALUE},
    )
    if not recs:
        return None

    counts = {c: 0 for c in ("BEV", "PHEV", "HEV", "PETROL", "DIESEL", "OTHERS")}
    unmapped: dict = {}
    join_stats = {"trim": 0, "majority": 0, "unmatched": 0}
    for rec in recs:
        fuel = (rec.get(FUEL_FIELD) or "").strip()
        if fuel in HYBRID_VALUES:
            col, how = classify_hybrid(rec, exact, votes)
            counts[col] += 1
            join_stats[how] += 1
        elif fuel in FUEL_MAP:
            counts[FUEL_MAP[fuel]] += 1
        elif fuel == "":
            counts["OTHERS"] += 1
        else:
            unmapped[fuel] = unmapped.get(fuel, 0) + 1

    if unmapped:
        raise SystemExit(f"Unmapped {FUEL_FIELD} values in {period}: {unmapped} — "
                         f"extend FUEL_MAP deliberately.")

    total = sum(counts.values())
    print(f"  {period}: total={total} {counts} | hybrid join: {join_stats}", flush=True)
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
    ap.add_argument("--dry-run", action="store_true", help="Aggregate and print but do not write the CSV.")
    args = ap.parse_args()

    if args.probe:
        probe()
        return

    start, end = default_window()
    start = args.start or start
    end = args.end or end
    print(f"Fetching Israel registrations {start} .. {end}")

    wltp_lookup = load_wltp_lookup()

    new_rows = {}
    for period in month_range(start, end):
        row = aggregate_month(period, wltp_lookup)
        if row:
            new_rows[(period, VARIANT)] = row

    if not new_rows:
        print("No rows extracted.")
        sys.exit(1)
    if args.dry_run:
        print(f"[dry-run] {len(new_rows)} months aggregated; CSV untouched.")
        return
    added, updated = upsert_csv(CSV_PATH, new_rows)
    print(f"{added} added, {updated} updated -> {CSV_PATH}")


if __name__ == "__main__":
    main()
