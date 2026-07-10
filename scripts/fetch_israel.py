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
THE TRAP (verified by cross-tab probe, 2026-07): the registry codes regular
HEVs as plain **בנזין** — `חשמל/בנזין` / `חשמל/דיזל` are reserved for
PLUG-INs only. A naive fuel-column mapping therefore hides the entire HEV
segment (~25% of the market) inside PETROL. The fix: every petrol/diesel/
hybrid row is joined against the model catalogue (dataset degem-rechev-wltp,
"תוצרים ודגמים של כלי רכב פרטי ומסחרי"), whose `technologiat_hanaa_nm` says
PLUG IN / היברידי רגיל / רכב חשמלי / הנעה רגילה per
(tozeret_cd, degem_cd, shnat_yitzur, ramat_gimur), with a majority vote over
the model's trims when the exact trim is missing. Cross-tab coverage was
100% back to 2017; I-VIA Q3-2025 shares reproduce within ~2pp.

    חשמל                     → BEV   (catalogue: רכב חשמלי, 100%)
    בנזין  + catalogue hybrid → HEV   (the hidden-HEV recovery)
    בנזין  + catalogue plug-in→ PHEV  (rare fuel-column miscoding)
    בנזין  otherwise          → PETROL
    דיזל   (same pattern)     → HEV / PHEV / DIESEL
    חשמל/בנזין, חשמל/דיזל     → PHEV unless catalogue says regular hybrid
    גפ"מ                      → OTHERS (LPG)

Unmapped fuel values are a hard error so CI surfaces schema drift; per-month
join statistics (incl. unmatched rows) are printed on every run.
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

# Registry fuel values that need the catalogue join (HEVs hide in petrol,
# and the chargeable-hybrid buckets need the plug-in/regular verdict).
JOINED_FUELS = {"בנזין": "PETROL", "דיזל": "DIESEL",
                "חשמל/בנזין": "PHEV", "חשמל/דיזל": "PHEV"}
DIRECT_FUELS = {"חשמל": "BEV", "גפ\"מ": "OTHERS"}

REGULAR_HYBRID = "היברידי רגיל"
# technologiat_hanaa_nm values that mean plug-in hybrid. Verified via probe
# ("PLUG IN"); substring match keeps us robust to phrasing variants.
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

def tech_category(tech: str) -> str:
    """Catalogue technologiat_hanaa_nm -> PHEV / HEV / OTHER."""
    t = tech.lower()
    if any(marker in t for marker in PLUGIN_MARKERS):
        return "PHEV"
    if tech == REGULAR_HYBRID:
        return "HEV"
    return "OTHER"   # הנעה רגילה, רכב חשמלי


def load_wltp_lookup() -> tuple[dict, dict]:
    """
    Two lookups from the model catalogue:
      exact:  (tozeret_cd, degem_cd, shnat_yitzur, ramat_gimur) -> category
      votes:  (tozeret_cd, degem_cd, shnat_yitzur) -> {category: n}
    The trim level (ramat_gimur) is part of the exact key because the same
    model code + year can carry trims with different powertrains.
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
        cat = tech_category(tech)
        triple = (r.get("tozeret_cd"), r.get("degem_cd"), r.get("shnat_yitzur"))
        trim = (r.get("ramat_gimur") or "").strip()
        exact[triple + (trim,)] = cat
        votes.setdefault(triple, {})
        votes[triple][cat] = votes[triple].get(cat, 0) + 1
    print(f"  {len(recs):,} catalogue rows -> {len(exact):,} trim keys, "
          f"{len(votes):,} model triples", flush=True)
    return exact, votes


def classify(rec: dict, exact: dict, votes: dict) -> tuple[str | None, str]:
    """-> (category or None if unmatched, join level for stats)."""
    triple = (rec.get("tozeret_cd"), rec.get("degem_cd"), rec.get("shnat_yitzur"))
    trim = (rec.get("ramat_gimur") or "").strip()
    hit = exact.get(triple + (trim,))
    if hit is not None:
        return hit, "trim"
    v = votes.get(triple)
    if v:
        return max(v, key=v.get), "majority"
    return None, "unmatched"


# ---------------------------------------------------------------- probe mode

def probe() -> None:
    """Cross-tab registry fuel value × catalogue propulsion technology.

    Working hypothesis (probe v3): registry sug_delek_nm codes regular HEVs
    as plain בנזין and reserves חשמל/בנזין for plug-ins. The cross-tab
    verifies this and measures catalogue join coverage per era.
    """
    print("=== PROBE v4: fuel × technologiat cross-tab ===", flush=True)
    exact, votes = load_wltp_lookup()
    # Rebuild a tech-name lookup (not just the plug-in bool) for the cross-tab
    recs = ds_all_records(
        WLTP_RESOURCE,
        ["tozeret_cd", "degem_cd", "shnat_yitzur", "ramat_gimur", "technologiat_hanaa_nm"],
    )
    tech_exact = {}
    for r in recs:
        tech = (r.get("technologiat_hanaa_nm") or "").strip()
        if tech:
            key = (r.get("tozeret_cd"), r.get("degem_cd"), r.get("shnat_yitzur"),
                   (r.get("ramat_gimur") or "").strip())
            tech_exact[key] = tech

    for period in ("2026-04", "2025-06", "2022-06", "2019-06", "2017-06"):
        rows = ds_all_records(
            REGISTRY_RESOURCE,
            [FUEL_FIELD, "tozeret_cd", "degem_cd", "shnat_yitzur", "ramat_gimur"],
            filters={DATE_FIELD: unpadded(period), SCOPE_FIELD: SCOPE_VALUE},
        )
        xt: dict = {}
        for rec in rows:
            fuel = (rec.get(FUEL_FIELD) or "").strip()
            key = (rec.get("tozeret_cd"), rec.get("degem_cd"), rec.get("shnat_yitzur"),
                   (rec.get("ramat_gimur") or "").strip())
            tech = tech_exact.get(key, "<no catalogue match>")
            xt.setdefault(fuel, {})
            xt[fuel][tech] = xt[fuel].get(tech, 0) + 1
        print(f"\n  {period} (n={len(rows)}):")
        for fuel in sorted(xt):
            print(f"    {fuel!r}: {json.dumps(xt[fuel], ensure_ascii=False)}")

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
    hev_recovered = 0
    for rec in recs:
        fuel = (rec.get(FUEL_FIELD) or "").strip()
        if fuel in JOINED_FUELS:
            cat, how = classify(rec, exact, votes)
            join_stats[how] += 1
            if cat in ("PHEV", "HEV"):
                counts[cat] += 1
                if cat == "HEV" and fuel in ("בנזין", "דיזל"):
                    hev_recovered += 1
            else:
                # OTHER (regular drive / electric) or unmatched: trust the
                # registry fuel column's default bucket.
                counts[JOINED_FUELS[fuel]] += 1
        elif fuel in DIRECT_FUELS:
            counts[DIRECT_FUELS[fuel]] += 1
        elif fuel == "":
            counts["OTHERS"] += 1
        else:
            unmapped[fuel] = unmapped.get(fuel, 0) + 1

    if unmapped:
        raise SystemExit(f"Unmapped {FUEL_FIELD} values in {period}: {unmapped} — "
                         f"extend the fuel maps deliberately.")

    total = sum(counts.values())
    unmatched_pct = 100 * join_stats["unmatched"] / total if total else 0.0
    print(f"  {period}: total={total} {counts} | HEVs recovered from petrol/diesel: "
          f"{hev_recovered} | join: {join_stats} ({unmatched_pct:.1f}% unmatched)", flush=True)
    if unmatched_pct > 5:
        print(f"  ! {period}: catalogue join unmatched share {unmatched_pct:.1f}% > 5% — "
              f"HEV undercount likely, investigate before trusting this month.", flush=True)
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
    ap.add_argument("--force", action="store_true",
                    help="Skip the 'previous month already present' early-exit.")
    args = ap.parse_args()

    if args.probe:
        probe()
        return

    start, end = default_window()
    start = args.start or start
    end = args.end or end

    if (not args.force and not args.start and not args.end
            and os.path.exists(CSV_PATH)):
        with open(CSV_PATH, newline="", encoding="utf-8") as f:
            if any(r["period"] == end and r["variant"] == VARIANT
                   for r in csv.DictReader(f)):
                print(f"CSV already has {end}; nothing to do (use --force to re-count).")
                return

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
