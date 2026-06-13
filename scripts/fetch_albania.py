#!/usr/bin/env python3
"""
Fetch Albania monthly vehicle-registration data from Robbie Andrew's pre-parsed
CSV and upsert ``data/Albania.csv``.

Usage
-----
    python scripts/fetch_albania.py [--dry-run] [--since YYYY-MM] [--url URL]

Primary source
--------------
Albania's General Directorate of Road Transport Services (DPSHTRR) publishes
a Looker Studio dashboard at

    https://www.dpshtrr.al/open-data-dpshtrr-english

which is updated monthly and covers every month of the current year (and the
full prior year). The dashboard requires a Google account to export — it is not
directly automatable. Robbie Andrew (@robbieandrew.bsky.social) mirrors the
same data as a plain CSV at

    https://robbieandrew.github.io/carsales/albania_carsales_monthly.csv

This is the URL we fetch. Attribution in the CSV's ``source`` column stays
``dpshtrr.al`` (the official primary); R. Andrew is credited in
``footnotes.csv``. See docs/architecture/27-source-albania.md.

Column mapping (Robbie CSV → gallery schema)
--------------------------------------------
    Battery electric      → BEV
    Plugin hybrid         → PHEV
    Non-plugin hybrid     → HEV
    Petrol                → PETROL
    Diesel                → DIESEL
    LPG / LPG blend       → OTHERS  (summed with Others)
    Others                → OTHERS  (summed with LPG)
    TOTAL = BEV + PHEV + HEV + PETROL + DIESEL + OTHERS

Note: All registrations — both new cars and first registrations of imported
used vehicles — are included. Albania has a significant used-car import market
so the headline figures are higher than new-car-only figures elsewhere.

Coverage / cadence
------------------
Robbie's CSV covers monthly data from ~2019 onward and is updated shortly
after DPSHTRR publishes each month's dashboard (typically a few weeks after
month-end). The upsert is keyed on ``(period, variant)`` so older months
already in the CSV are left untouched. ``time_interval`` is ``monthly``.

Invoked by ``.github/workflows/fetch-albania.yml``. The commit step is
change-gated, so steady-state runs are a no-op.
"""
import argparse
import csv
import io
import os
import re
from pathlib import Path

import requests

SOURCE = "dpshtrr.al"  # official attribution; R. Andrew credited in footnotes.csv
CSV_PATH = "data/Albania.csv"
VARIANT = "Whole"
ROBBIEANDREW_URL = (
    "https://robbieandrew.github.io/carsales/albania_carsales_monthly.csv"
)

CSV_COLUMNS = [
    "period", "time_interval", "variant", "source",
    "BEV", "PHEV", "HEV", "PETROL", "DIESEL", "OTHERS", "TOTAL", "notes",
]
VALUE_COLUMNS = ["BEV", "PHEV", "HEV", "PETROL", "DIESEL", "OTHERS"]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; LeRaffl-Gallery fetch_albania; "
        "+https://leraffl.github.io/LeRaffl-Gallery/)"
    ),
    "Accept": "text/csv,text/plain,*/*",
    "Referer": "https://robbieandrew.github.io/carsales/",
}


def _num(val: str) -> float | None:
    try:
        return float(val.replace(",", "").strip())
    except (ValueError, AttributeError):
        return None


def parse_robbie_csv(content: bytes) -> dict:
    """Parse Robbie Andrew's albania_carsales_monthly.csv.

    Expected header:
        "YYYYMM","Diesel","Petrol","LPG / LPG blend",
        "Non-plugin hybrid","Plugin hybrid","Battery electric","Others"
    """
    text = content.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))

    # Normalize header names (strip quotes / spaces / BOM).
    rows_out: dict = {}
    skipped = 0
    for row in reader:
        # Strip whitespace from keys and values.
        row = {k.strip().strip('"'): v.strip() for k, v in row.items()}
        ym = row.get("YYYYMM", "").strip()
        if not re.fullmatch(r"\d{6}", ym):
            skipped += 1
            continue
        period = f"{ym[:4]}-{ym[4:]}"

        bev  = _num(row.get("Battery electric", "")) or 0.0
        phev = _num(row.get("Plugin hybrid", "")) or 0.0
        hev  = _num(row.get("Non-plugin hybrid", "")) or 0.0
        pet  = _num(row.get("Petrol", "")) or 0.0
        die  = _num(row.get("Diesel", "")) or 0.0
        lpg  = _num(row.get("LPG / LPG blend", "")) or 0.0
        oth  = _num(row.get("Others", "")) or 0.0
        others = lpg + oth
        total = bev + phev + hev + pet + die + others
        if total == 0:
            continue

        rows_out[(period, VARIANT)] = {
            "period":        period,
            "time_interval": "monthly",
            "variant":       VARIANT,
            "source":        SOURCE,
            "BEV":    bev  if bev  else "",
            "PHEV":   phev if phev else "",
            "HEV":    hev  if hev  else "",
            "PETROL": pet,
            "DIESEL": die,
            "OTHERS": others if others else "",
            "TOTAL":  total,
            "notes":  "",
        }

    if skipped:
        print(f"[albania] skipped {skipped} non-data rows")
    return rows_out


def upsert_csv(csv_path: str, new_rows: dict, since: str | None) -> tuple[int, int]:
    existing: dict = {}
    if os.path.exists(csv_path):
        with open(csv_path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                for c in CSV_COLUMNS:
                    row.setdefault(c, "")
                existing[(row["period"], row["variant"])] = {
                    k: row[k] for k in CSV_COLUMNS
                }

    added = updated = 0
    for key, new_row in sorted(new_rows.items()):
        if since and key[0] < since:
            continue
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
    ap.add_argument("--url", default=ROBBIEANDREW_URL,
                    help="Override the source CSV URL.")
    ap.add_argument("--since", default=None,
                    help="Only upsert months >= YYYY-MM (default: all).")
    ap.add_argument("--dry-run", action="store_true",
                    help="Fetch and parse, print monthly totals, do not write.")
    ap.add_argument("--force", action="store_true",
                    help="Accepted for parity (commit-gated downstream).")
    args = ap.parse_args()

    session = requests.Session()
    r = session.get(args.url, headers=HEADERS, timeout=60)
    print(f"[albania] GET {args.url} -> HTTP {r.status_code} ({len(r.content)} bytes)")
    r.raise_for_status()

    rows = parse_robbie_csv(r.content)
    if not rows:
        print("no non-zero months parsed")
        return

    for key in sorted(rows):
        c = rows[key]
        print(f"  {key[0]}  " + "  ".join(
            f"{col}={c[col]}" for col in VALUE_COLUMNS
        ) + f"  TOTAL={c['TOTAL']:.0f}")

    if args.dry_run:
        print("(dry-run: CSV not written)")
        return

    added, updated = upsert_csv(CSV_PATH, rows, args.since)
    print(f"{added} added, {updated} updated -> {CSV_PATH}")


if __name__ == "__main__":
    main()
