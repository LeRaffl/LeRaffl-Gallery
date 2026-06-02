#!/usr/bin/env python3
"""
Fetch Netherlands vehicle registration data from duurzamemobiliteit.databank.nl
and upsert per-variant CSVs under data/.

Usage
-----
    python scripts/fetch_netherlands.py [--variant {whole,used,hdv,all}] [--force]

Output files
------------
    data/Netherlands.csv       <- variant=Whole (Personenauto Nieuw)
    data/Netherlands_Used.csv  <- variant=Used  (Personenauto Occasion import)
    data/Netherlands_HDV.csv   <- variant=HDV   (Zware bedrijfsvoertuigen Nieuw)

The script is invoked by .github/workflows/fetch-netherlands.yml on a daily
cron (1st-15th, 06:30 UTC) and via manual workflow_dispatch. When it produces
changes, the workflow commits each touched CSV and triggers render-country.yml
for the corresponding variant.

Full pipeline context — Swing endpoint flow, variant rationale, HEV gap,
FCEV folding, schedule, fragility, maintenance recipes — lives in
docs/architecture/10-source-netherlands.md. Read that before changing the
TEMPLATES constant, the parser, or the column mapping.

Brief recap (so the script reads on its own):

* duurzamemobiliteit.databank.nl is RDW data served by Swing 7.1 (ABF
  Research). No documented public API. We hit pre-saved workspace permalinks
  the maintainer set up in the Swing UI.
* Bootstrap: GET /viewer?workspace_guid=<TEMPLATE> establishes a session and
  embeds a session-bound GUID as `WsGuid: "..."` in the HTML. We then hit
  /viewer/Presentation/GetTableStart with that session GUID, paginating with
  GetTableRows when the pivot is longer than the initial page (~70 rows).
* Dutch label -> canonical column:
      BEV -> BEV;  PHEV -> PHEV;  Benzine -> PETROL;  Diesel -> DIESEL;
      FCEV + Overig -> OTHERS;  HEV column is always blank (RDW doesn't
      split it; full hybrids fold into Benzine/Diesel upstream).
* Dutch locale: "." is thousands separator (6.863 == 6863). "&nbsp;" == 0.
* Two table orientations are possible (Whole/HDV return periods-in-rows;
  Used returns fuels-in-rows with a 2-level period × sub-column header).
  The parser detects which case applies from the headRows labels.
"""
import argparse
import csv
import os
import re
import sys
import time
from datetime import date
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BASE = "https://duurzamemobiliteit.databank.nl"

# Saved Swing workspace templates (configured in the Swing UI via Share Permalink).
# Each is pre-set to monthly granularity, all years 2018-current selected, and
# the relevant Voertuigsoort / Aanvoertype dimension picks.
TEMPLATES = {
    "Whole": "a7d36cf5-9dd3-4eca-96e9-9e1b991af9ba",  # Personenauto Nieuw
    "Used":  "ffaf2d83-0174-4b36-92b9-f7bd96ad4d89",  # Personenauto Occasion import (>90 + <=90)
    "HDV":   "992eb09a-0828-4ef9-97b4-1577ebba3a21",  # Zware bedrijfsvoertuigen Nieuw
}

# Each variant writes to its own CSV. Whole keeps the canonical filename
# (no suffix) — that's the convention for the country's "default" slice and
# what the gallery's world-map + aggregate computations pick up.
CSV_PATHS = {
    "Whole": "data/Netherlands.csv",
    "Used":  "data/Netherlands_Used.csv",
    "HDV":   "data/Netherlands_HDV.csv",
}

# Short, stable source string for the CSV (matches the pattern other countries
# use: pxdata.stat.fi, dpshtrr.al, etc.). The variant-specific template GUID
# goes in the per-row `notes` column for debugging.
SOURCE = "duurzamemobiliteit.databank.nl (RDW)"

HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/18.5 Safari/605.1.15"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "nl-NL,nl;q=0.9,en;q=0.8",
}

CSV_COLUMNS = [
    "period", "time_interval", "variant", "source",
    "BEV", "PHEV", "HEV", "PETROL", "DIESEL", "FLEXFUEL",
    "OTHERS", "TOTAL", "notes",
]

# Fuel label set used to detect axis orientation in the JSON response.
NL_FUELS = {"BEV", "FCEV", "PHEV", "Benzine", "Diesel", "Overig"}

NL_MONTHS = {
    "januari": 1, "februari": 2, "maart": 3, "april": 4, "mei": 5, "juni": 6,
    "juli": 7, "augustus": 8, "september": 9, "oktober": 10, "november": 11,
    "december": 12,
}

WSGUID_RE = re.compile(r'WsGuid:\s*"([a-f0-9-]{36})"')
DATE_RE = re.compile(r"(\d{1,2})\s+(\w+)\s+(\d{4})")


def parse_nl_number(s: str) -> float:
    """'6.863' -> 6863.0; '&nbsp;' / '' -> 0.0. NL uses '.' as thousands sep."""
    if not s or s == "&nbsp;":
        return 0.0
    return float(s.replace(".", "").replace(",", "."))


def parse_nl_period(label: str) -> str:
    """'31 januari 2018' -> '2018-01'."""
    m = DATE_RE.search(label)
    if not m:
        raise ValueError(f"Unrecognised period label: {label!r}")
    _day, month_nl, year = m.groups()
    month = NL_MONTHS.get(month_nl.lower())
    if not month:
        raise ValueError(f"Unrecognised Dutch month: {month_nl!r}")
    return f"{year}-{month:02d}"


def fetch_table(variant: str, session: requests.Session) -> dict:
    """Bootstrap a session-bound workspace and return its full pivot as JSON.

    GetTableStart only returns the first ~70 rows; for longer tables (Whole and
    HDV cover ~100 monthly periods) we follow up with GetTableRows to backfill
    the remainder. Used Imports has only 6 rows (fuels-in-rows layout) so a
    single GetTableStart suffices.
    """
    template_guid = TEMPLATES[variant]
    init_url = f"{BASE}/viewer?workspace_guid={template_guid}"
    print(f"[{variant}] init: {init_url}")
    r = session.get(init_url, headers=HTTP_HEADERS, timeout=30)
    r.raise_for_status()
    m = WSGUID_RE.search(r.text)
    if not m:
        raise RuntimeError(
            f"[{variant}] WsGuid not found in /viewer response; the template GUID "
            f"may have been deleted or Swing changed its HTML shape."
        )
    wsguid = m.group(1)
    referer = {"Referer": f"{BASE}/viewer"}

    start_url = (
        f"{BASE}/viewer/Presentation/GetTableStart"
        f"?workspaceGuid={wsguid}&_={int(time.time() * 1000)}"
    )
    r = session.get(start_url, headers={**HTTP_HEADERS, **referer}, timeout=30)
    r.raise_for_status()
    data = r.json()

    total_rows = data["totalRows"]
    total_cols = data["totalCols"]
    have_rows = len(data["rowData"])
    while have_rows < total_rows:
        more_url = (
            f"{BASE}/viewer/Presentation/GetTableRows"
            f"?workspaceGuid={wsguid}"
            f"&startRow={have_rows}&startCol=0"
            f"&numRows={total_rows - have_rows}&numCols={total_cols}"
            f"&tableId=0&_={int(time.time() * 1000)}"
        )
        r = session.get(more_url, headers={**HTTP_HEADERS, **referer}, timeout=30)
        r.raise_for_status()
        chunk = r.json().get("rowData", [])
        if not chunk:
            raise RuntimeError(
                f"[{variant}] GetTableRows returned no rows at startRow={have_rows}; "
                f"expected {total_rows - have_rows} more"
            )
        data["rowData"].extend(chunk)
        have_rows = len(data["rowData"])
        print(f"[{variant}] paged: {have_rows}/{total_rows} rows")

    return data


def parse_table(data: dict, variant: str) -> dict[str, dict[str, float]]:
    """
    Parse a Swing GetTableStart response into {period: {fuel: value}}.

    Two layouts are possible:
      A. Periods in headRows, fuels in headCols   (Whole, HDV)
      B. Fuels in headRows, periods in headCols   (Used Imports)

    For layout B, Used Imports has a 2-level column header: each period spans
    two sub-columns ("Occasion import > 90 dgn" and "<= 90 dgn") which we sum.
    """
    row_first = data["headRows"][0][0]["d"]
    fuels_in_rows = row_first in NL_FUELS

    if fuels_in_rows:
        return _parse_fuels_in_rows(data, variant)
    return _parse_periods_in_rows(data, variant)


def _parse_periods_in_rows(data: dict, variant: str) -> dict[str, dict[str, float]]:
    """Layout A: periods are rows, fuels are columns (Whole, HDV)."""
    fuel_labels = [hc["d"] for hc in data["headCols"][-1]]  # innermost level
    period_labels = [r[0]["d"] for r in data["headRows"]]
    out: dict[str, dict[str, float]] = {}
    for i, period_label in enumerate(period_labels):
        period = parse_nl_period(period_label)
        row_cells = data["rowData"][i]
        out[period] = {
            fuel_labels[j]: parse_nl_number(row_cells[j]["d"])
            for j in range(len(fuel_labels))
        }
    return out


def _parse_fuels_in_rows(data: dict, variant: str) -> dict[str, dict[str, float]]:
    """Layout B: fuels are rows, periods are columns. Used Imports has 2-level
    column header where each period covers two sub-columns we sum together."""
    fuel_labels = [r[0]["d"] for r in data["headRows"]]
    period_level = data["headCols"][0]  # outer level: period labels (with blanks for spans)

    # Propagate period labels across the sub-columns they span.
    period_per_col: list[str] = []
    current: str | None = None
    for cell in period_level:
        label = cell.get("d", "")
        if label:
            current = label
        if current is None:
            raise RuntimeError(f"[{variant}] period header starts with empty cell")
        period_per_col.append(current)

    out: dict[str, dict[str, float]] = {}
    for fuel_idx, fuel in enumerate(fuel_labels):
        for col_idx, period_label in enumerate(period_per_col):
            period = parse_nl_period(period_label)
            value = parse_nl_number(data["rowData"][fuel_idx][col_idx]["d"])
            out.setdefault(period, {}).setdefault(fuel, 0.0)
            out[period][fuel] += value
    return out


def to_csv_rows(parsed: dict[str, dict[str, float]], variant: str) -> dict[str, dict]:
    """Map parsed {period: {NL_fuel: value}} to canonical CSV row dicts."""
    out: dict[str, dict] = {}
    for period, fuels in parsed.items():
        bev    = fuels.get("BEV", 0.0)
        phev   = fuels.get("PHEV", 0.0)
        petrol = fuels.get("Benzine", 0.0)
        diesel = fuels.get("Diesel", 0.0)
        others = fuels.get("FCEV", 0.0) + fuels.get("Overig", 0.0)
        total  = bev + phev + petrol + diesel + others

        # Skip future months that Swing pre-fills with zeros (every fuel = 0)
        if total == 0.0:
            continue

        out[period] = {
            "period": period,
            "time_interval": "monthly",
            "variant": variant,
            "source": SOURCE,
            "BEV": bev,
            "PHEV": phev,
            "HEV": "",          # Netherlands does not split HEV
            "PETROL": petrol,
            "DIESEL": diesel,
            "FLEXFUEL": "",
            "OTHERS": others,
            "TOTAL": total,
            "notes": f"workspace_guid={TEMPLATES[variant]}",
        }
    return out


def upsert_csv(csv_path: str, new_rows: dict[tuple[str, str], dict]) -> tuple[int, int]:
    """Upsert by (period, variant). Returns (added, updated). Warns on >50% delta."""
    existing: dict[tuple[str, str], dict] = {}
    if os.path.exists(csv_path):
        with open(csv_path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                existing[(row["period"], row["variant"])] = row

    added = updated = 0
    for key, new_row in sorted(new_rows.items()):
        if key not in existing:
            existing[key] = new_row
            added += 1
            print(f"  + {key[1]} {key[0]}")
        else:
            old = existing[key]
            for col in ["BEV", "PHEV", "PETROL", "DIESEL", "OTHERS"]:
                old_val = float(old.get(col) or 0)
                new_val = float(new_row[col] or 0)
                if old_val > 100 and abs(new_val - old_val) / old_val > 0.5:
                    print(
                        f"  WARNING {key[1]} {key[0]} {col}: existing={old_val:.0f}, "
                        f"new={new_val:.0f} — diff >50%, please verify"
                    )
            existing[key] = {**old, **new_row}
            updated += 1

    Path(csv_path).parent.mkdir(parents=True, exist_ok=True)
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, lineterminator="\n")
        writer.writeheader()
        # Sort by variant then period — keeps each variant's history contiguous.
        for key in sorted(existing.keys(), key=lambda k: (k[1], k[0])):
            writer.writerow(existing[key])

    return added, updated


def previous_month_period() -> str:
    """YYYY-MM for the calendar month before today (UTC)."""
    today = date.today()
    if today.month == 1:
        return f"{today.year - 1}-12"
    return f"{today.year}-{today.month - 1:02d}"


def csv_has_period(csv_path: str, period: str) -> bool:
    """Return True if csv_path exists and contains any row for `period`."""
    if not os.path.exists(csv_path):
        return False
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["period"] == period:
                return True
    return False


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--variant",
        choices=["whole", "used", "hdv", "all"],
        default="all",
        help="Which slice to fetch (default: all)",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Skip the 'already current' early-exit check.",
    )
    args = parser.parse_args()

    variant_aliases = {"whole": "Whole", "used": "Used", "hdv": "HDV"}
    targets = (
        list(variant_aliases.values())
        if args.variant == "all"
        else [variant_aliases[args.variant]]
    )

    # Early exit per variant: skip those whose CSV already has last month's
    # row. RDW occasionally restates older months but those don't need
    # same-day pickup; --force is the override for restatement runs.
    if not args.force:
        prev = previous_month_period()
        current = [v for v in targets if csv_has_period(CSV_PATHS[v], prev)]
        targets = [v for v in targets if v not in current]
        for v in current:
            print(f"[{v}] CSV already has {prev}; skipping (use --force to re-fetch).")
        if not targets:
            print("All requested variants are current; nothing to do.")
            return

    session = requests.Session()
    # Retry up to 3 times on connection errors with exponential backoff (2s, 4s, 8s).
    # Handles transient network-unreachable failures seen on GitHub Actions runners.
    _retry = Retry(connect=3, read=2, backoff_factor=2, raise_on_status=False)
    _adapter = HTTPAdapter(max_retries=_retry)
    session.mount("https://", _adapter)
    session.mount("http://", _adapter)

    for variant in targets:
        data = fetch_table(variant, session)
        print(f"[{variant}] caption: {data['caption']}")
        parsed = parse_table(data, variant)
        rows = to_csv_rows(parsed, variant)
        print(f"[{variant}] parsed {len(rows)} non-zero months "
              f"({min(rows, default='—')} .. {max(rows, default='—')})")
        if not rows:
            continue
        keyed = {(p, variant): r for p, r in rows.items()}
        added, updated = upsert_csv(CSV_PATHS[variant], keyed)
        print(f"[{variant}] {added} added, {updated} updated -> {CSV_PATHS[variant]}")


if __name__ == "__main__":
    main()
