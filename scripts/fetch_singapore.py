#!/usr/bin/env python3
"""
Fetch Singapore new-car registration data from **data.gov.sg** (the official
open-data portal that republishes Land Transport Authority / LTA figures) and
upsert ``data/Singapore.csv``.

Usage
-----
    python scripts/fetch_singapore.py [--resource-id ID] [--since YYYY-MM]
                                      [--dry-run] [--list-categories]

Source
------
data.gov.sg CKAN datastore. The dataset is "New Registration of Cars by Fuel
Type" (monthly), resource id ``d_d3f4d708e1d0a37b4365414e2fad3a07`` — the same
id already cited in the legacy hand-maintained ``data/Singapore.csv``. The
SingStat Table Builder series M650281 and newautomotive's tracker both rest on
this same LTA data; data.gov.sg exposes it through a clean JSON REST API, so we
read it directly.

    GET https://data.gov.sg/api/action/datastore_search
        ?resource_id=<id>&limit=<n>&offset=<m>

The datastore is LONG format — one record per (month, fuel_type) with a numeric
count. We page through every record, classify each fuel_type into a gallery
column, and sum per month into the wide schema.

Fuel classification (ordered substring rules)
--------------------------------------------
The LTA taxonomy has shifted over the years and uses labels such as
``Petrol``, ``Diesel``, ``Petrol-Electric`` (a non-plug-in hybrid),
``Electric`` (BEV) and ``Petrol-Electric (Plug-In)`` (PHEV). The rules below
also tolerate the alternative ``Battery electric`` / ``Plugin hybrid`` /
``Non-plugin hybrid`` wording. Order matters: plug-in is tested before the
generic ``electric``/``hybrid`` checks, and pure ``Electric`` before the
``-Electric`` hybrids.

    contains "plug"               → PHEV
    contains "battery electric"   → BEV
    equals   "electric"           → BEV
    contains "hybrid"             → HEV   (non-plug-in hybrid)
    contains "electric"           → HEV   (Petrol-Electric, Diesel-Electric)
    contains "cng"                → OTHERS
    contains "diesel"             → DIESEL
    contains "petrol"             → PETROL
    <everything else>             → OTHERS  (printed as a WARNING so a new
                                             category can't vanish silently)

Note on history: the LTA fuel split only resolves BEV/PHEV/HEV from ~2022-07.
Earlier months report electrified cars inside a coarse "Others"/"Petrol-Electric"
bucket, so a clean fetch yields empty BEV/PHEV/HEV for those months (unlike the
legacy file, which spread an annual EV estimate across the year). See
docs/architecture/26-source-singapore.md.

Invoked by ``.github/workflows/fetch-singapore.yml``. The commit step is
change-gated, so steady-state runs are a no-op.
"""
import argparse
import csv
import os
import re
from pathlib import Path

import requests

SOURCE = "data.gov.sg"
CSV_PATH = "data/Singapore.csv"
VARIANT = "Whole"
# "New Registration of Cars by Fuel Type, Monthly" — id cited in the legacy CSV.
DEFAULT_RESOURCE_ID = "d_d3f4d708e1d0a37b4365414e2fad3a07"
DATASTORE_URL = "https://data.gov.sg/api/action/datastore_search"
DATASETS_V2_URL = "https://api-production.data.gov.sg/v2/public/api/datasets"
PAGE_SIZE = 5000

CSV_COLUMNS = [
    "period", "time_interval", "variant", "source",
    "BEV", "PHEV", "HEV", "PETROL", "DIESEL", "OTHERS", "TOTAL", "notes",
]
VALUE_COLUMNS = ["BEV", "PHEV", "HEV", "PETROL", "DIESEL", "OTHERS"]

HEADERS = {
    "User-Agent": "LeRaffl-Gallery fetch_singapore (+https://github.com/leraffl/leraffl-gallery)",
}

# Ordered (test, column). The test gets the lowercased, stripped fuel label.
FUEL_RULES = [
    # "plug" but not "non-plug(in)" — "Non-plugin hybrid" is an HEV, not a PHEV.
    (lambda s: "plug" in s and "non-plug" not in s and "non plug" not in s, "PHEV"),
    (lambda s: "battery electric" in s, "BEV"),
    (lambda s: s == "electric",         "BEV"),
    (lambda s: "hybrid" in s,           "HEV"),
    (lambda s: "electric" in s,         "HEV"),
    (lambda s: "cng" in s,              "OTHERS"),
    (lambda s: "diesel" in s,           "DIESEL"),
    (lambda s: "petrol" in s,           "PETROL"),
]


def classify_fuel(label: str) -> str:
    s = (label or "").strip().lower()
    for test, col in FUEL_RULES:
        if test(s):
            return col
    return "OTHERS"


# --------------------------------------------------------------------------- #
# data.gov.sg CKAN datastore
# --------------------------------------------------------------------------- #
def fetch_records(session: requests.Session, resource_id: str) -> list[dict]:
    """Page through the whole datastore resource and return all records."""
    records: list[dict] = []
    offset = 0
    total = None
    while True:
        params = {"resource_id": resource_id, "limit": PAGE_SIZE, "offset": offset}
        r = session.get(DATASTORE_URL, params=params, headers=HEADERS, timeout=120)
        r.raise_for_status()
        payload = r.json()
        if not payload.get("success"):
            raise RuntimeError(f"datastore_search returned success=false: {payload}")
        result = payload["result"]
        if total is None:
            total = result.get("total")
            field_ids = [f.get("id") for f in result.get("fields", [])]
            print(f"[meta] resource={resource_id} total={total} fields={field_ids}")
        batch = result.get("records", [])
        records.extend(batch)
        offset += len(batch)
        if not batch or (total is not None and offset >= int(total)):
            break
    print(f"[data] fetched {len(records)} records")
    return records


def _probe_latest(session: requests.Session, rid: str) -> tuple[str | None, list | None]:
    """Return (latest_month, fields) for a datastore resource, or (None, None)."""
    for params in ({"resource_id": rid, "limit": 1, "sort": "month desc"},
                   {"resource_id": rid, "limit": 1}):
        try:
            pr = session.get(DATASTORE_URL, params=params, headers=HEADERS, timeout=60)
            body = pr.json()
            if pr.ok and body.get("success"):
                res = body["result"]
                fields = [f["id"] for f in res.get("fields", []) if f["id"] != "_id"]
                recs = res.get("records", [])
                if recs:
                    rec = recs[0]
                    latest = rec.get("month") or rec.get("year_month") or rec.get("period")
                    return latest, fields
                return None, fields
        except Exception:  # noqa: BLE001
            continue
    return None, None


def discover(session: requests.Session, query: str) -> None:
    """Page data.gov.sg's v2 dataset catalogue, keep datasets whose name matches
    `query` (any whitespace-separated term, case-insensitive), and print each
    candidate's latest month + datastore fields. Locates the live monthly "cars
    by fuel type" resource when an id goes stale.
    """
    terms = [t.lower() for t in query.split()]
    page = 1
    pages = None
    candidates: list[tuple[str, str]] = []
    while True:
        r = session.get(DATASETS_V2_URL, params={"page": page}, headers=HEADERS, timeout=120)
        r.raise_for_status()
        data = r.json().get("data", {})
        if pages is None:
            pages = data.get("pages")
            print(f"[discover] scanning {pages} catalogue pages for terms {terms}")
        for ds in data.get("datasets", []):
            name = ds.get("name") or ""
            nl = name.lower()
            if all(t in nl for t in terms):
                candidates.append((ds.get("datasetId"), name))
        page += 1
        if not pages or page > pages:
            break

    print(f"[discover] {len(candidates)} name matches")
    for rid, name in candidates:
        latest, fields = _probe_latest(session, rid)
        has_fuel = bool(fields) and any("fuel" in f for f in fields)
        print(f"  {name[:60]:60s} rid={rid} latest={latest} fuel={has_fuel} fields={fields}")


SINGSTAT_URL = "https://tablebuilder.singstat.gov.sg/api/table/tabledata/{rid}"


def probe_singstat(session: requests.Session, rid: str) -> None:
    """Print a SingStat Table Builder series' row labels + latest periods, to
    check it as an alternative source when data.gov.sg goes stale.
    """
    url = SINGSTAT_URL.format(rid=rid)
    r = session.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=120)
    print(f"[singstat] GET {url} -> HTTP {r.status_code}")
    r.raise_for_status()
    body = r.json()
    data = body.get("Data", body.get("data", {}))
    rows = data.get("row", []) if isinstance(data, dict) else []
    print(f"[singstat] title={data.get('title') if isinstance(data, dict) else None!r} rows={len(rows)}")
    for row in rows:
        cols = row.get("columns", [])
        keys = [c.get("key") for c in cols]
        latest = keys[-3:] if keys else []
        print(f"  row={row.get('rowText')!r} uom={row.get('uoM')!r} "
              f"ncols={len(cols)} latest_keys={latest}")


def _detect_fields(records: list[dict]) -> tuple[str, str, str]:
    """Find the (month, fuel_type, number) field names. Prefer the canonical
    names but fall back to structural detection so a renamed column is tolerated.
    """
    sample = records[0]
    keys = [k for k in sample.keys() if k != "_id"]

    def pick(preferred, predicate):
        for name in preferred:
            if name in sample:
                return name
        for k in keys:
            if predicate(k, sample[k]):
                return k
        return None

    month_field = pick(
        ["month", "year_month", "period", "date"],
        lambda k, v: bool(re.match(r"^\d{4}-\d{2}", str(v))),
    )
    number_field = pick(
        ["number", "count", "value", "qty", "quantity"],
        lambda k, v: str(v).replace(".", "", 1).replace("-", "", 1).isdigit(),
    )
    fuel_field = pick(
        ["fuel_type", "fuel", "type", "category"],
        lambda k, v: k not in (month_field, number_field) and not str(v).replace(".", "", 1).isdigit(),
    )
    if not (month_field and fuel_field and number_field):
        raise RuntimeError(
            f"could not detect fields from keys {keys!r} "
            f"(month={month_field}, fuel={fuel_field}, number={number_field})"
        )
    print(f"[fields] month={month_field!r} fuel={fuel_field!r} number={number_field!r}")
    return month_field, fuel_field, number_field


def _norm_period(raw: str) -> str | None:
    """'2024-01' / '2024-01-01' / '2024' → 'YYYY-MM' (None if no month)."""
    m = re.match(r"^(\d{4})-(\d{2})", str(raw))
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    return None


def aggregate(records: list[dict], since: str | None) -> tuple[dict, dict]:
    """Return ({(period, variant): row}, {raw_label: gallery_col}) for monthly sums."""
    month_field, fuel_field, number_field = _detect_fields(records)

    periods: dict[str, dict[str, float]] = {}
    seen_labels: dict[str, str] = {}
    unmapped: set[str] = set()

    for rec in records:
        period = _norm_period(rec.get(month_field, ""))
        if period is None:
            continue
        if since and period < since:
            continue
        label = str(rec.get(fuel_field, "")).strip()
        col = classify_fuel(label)
        seen_labels[label] = col
        if col == "OTHERS" and not any(
            t(label.lower()) for t, _ in FUEL_RULES
        ) and label and "other" not in label.lower():
            unmapped.add(label)

        raw_val = rec.get(number_field, 0)
        try:
            val = float(raw_val)
        except (TypeError, ValueError):
            val = 0.0
        slot = periods.setdefault(period, {c: 0.0 for c in VALUE_COLUMNS})
        slot[col] += val

    if unmapped:
        print(f"  WARNING unmapped fuel labels dumped into OTHERS: {sorted(unmapped)} "
              f"— add a rule to FUEL_RULES if any belong elsewhere.")

    rows: dict = {}
    for period, cols in periods.items():
        total = sum(cols.values())
        if total == 0.0:
            continue
        rows[(period, VARIANT)] = {
            "period":        period,
            "time_interval": "monthly",
            "variant":       VARIANT,
            "source":        SOURCE,
            **{c: (float(cols[c]) if cols[c] else "") for c in VALUE_COLUMNS},
            "TOTAL":         float(total),
            "notes":         "",
        }
    return rows, seen_labels


# --------------------------------------------------------------------------- #
# CSV upsert (mirrors fetch_malaysia.py)
# --------------------------------------------------------------------------- #
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
            print(f"  + {key[1]} {key[0]}")
        else:
            if not new_row.get("notes"):
                new_row["notes"] = existing[key].get("notes", "")
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
    ap.add_argument("--resource-id", default=DEFAULT_RESOURCE_ID,
                    help=f"data.gov.sg datastore resource id (default {DEFAULT_RESOURCE_ID}).")
    ap.add_argument("--since", default=None,
                    help="Only upsert months >= this YYYY-MM (default: all months "
                         "the dataset returns).")
    ap.add_argument("--dry-run", action="store_true",
                    help="Fetch and print, but do not write the CSV.")
    ap.add_argument("--list-categories", action="store_true",
                    help="Print every distinct fuel label and its mapped column, then exit. "
                         "Use this on the first run to confirm the live taxonomy.")
    ap.add_argument("--discover", metavar="QUERY", default=None,
                    help="Search data.gov.sg for datasets matching QUERY and print each "
                         "datastore resource's latest month + fields, then exit. Use to "
                         "locate the live resource if the default id goes stale.")
    ap.add_argument("--probe-singstat", metavar="ID", default=None,
                    help="Probe a SingStat Table Builder series (e.g. M650281) and print "
                         "its row labels + latest periods, then exit.")
    ap.add_argument("--force", action="store_true",
                    help="Accepted for parity with other fetchers (this fetcher is "
                         "commit-gated downstream and always re-fetches).")
    args = ap.parse_args()

    session = requests.Session()

    if args.discover:
        discover(session, args.discover)
        return

    if args.probe_singstat:
        probe_singstat(session, args.probe_singstat)
        return

    records = fetch_records(session, args.resource_id)
    if not records:
        print("no records returned")
        return

    rows, seen_labels = aggregate(records, args.since)

    if args.list_categories:
        print("\nDistinct fuel labels → gallery column:")
        for label in sorted(seen_labels):
            print(f"  {label!r:40s} → {seen_labels[label]}")
        return

    if not rows:
        print("no non-zero months parsed")
        return
    periods = sorted(p for p, _ in rows)
    print(f"parsed {len(rows)} months ({periods[0]} .. {periods[-1]})")

    if args.dry_run:
        for key in sorted(rows):
            r = rows[key]
            print(f"  {key[0]}  " + "  ".join(
                f"{c}={r[c]}" for c in VALUE_COLUMNS) + f"  TOTAL={r['TOTAL']:.0f}")
        print("(dry-run: CSV not written)")
        return

    added, updated = upsert_csv(CSV_PATH, rows)
    print(f"{added} added, {updated} updated -> {CSV_PATH}")


if __name__ == "__main__":
    main()
