#!/usr/bin/env python3
"""
Fetch Netherlands vehicle registration data from duurzamemobiliteit.databank.nl
and update data/Netherlands.csv.

Usage
-----
    python scripts/fetch_netherlands.py [--variant {whole,used,hdv,all}] [--csv PATH]

* --variant  Which slice(s) to fetch (default: all).
* --csv      Target CSV (default: data/Netherlands.csv).

This script is invoked by .github/workflows/fetch-netherlands.yml on a monthly
cron and via manual workflow_dispatch. When it produces changes, the workflow
commits data/Netherlands.csv and triggers render-country.yml for each touched
variant.

Data source
-----------
duurzamemobiliteit.databank.nl is RDW data (Rijksdienst voor het Wegverkeer)
re-presented through the Swing 7.1 BI platform (vendor: ABF Research). There is
no documented public API, but each saved "workspace" (a pivot configuration) is
addressable via a shareable URL of the form:

    /viewer?workspace_guid=<TEMPLATE_GUID>

Hitting that URL with a cookie jar establishes a session-bound workspace whose
GUID is embedded in the response HTML as `WsGuid: "<SESSION_GUID>"`. From there,

    /viewer/Presentation/GetTableStart?workspaceGuid=<SESSION_GUID>

returns the pivot data as JSON. Three workspaces are configured (by the
maintainer, in the Swing UI, via the share-icon → permalink mechanism) — one
per variant we render:

  * Whole         — Instroom Personenauto Nieuw   (2018-01 .. current)
  * Used Imports  — Instroom Personenauto Occasion import (>90 dgn + <=90 dgn)
  * HDV           — Instroom Zware bedrijfsvoertuigen Nieuw

All three list BEV, FCEV, PHEV, Benzine, Diesel, Overig as the only fuel
categories. Notable: **the Netherlands does not split HEV separately** — full
hybrids are folded into Benzine/Diesel upstream. We therefore emit no HEV
column for Netherlands.

Column mapping (Dutch -> CSV column)
------------------------------------
    BEV               -> BEV
    PHEV              -> PHEV
    Benzine           -> PETROL
    Diesel            -> DIESEL
    FCEV  + Overig    -> OTHERS   (FCEV folded — <1 unit/month for Whole,
                                   ~30/month for Used Imports; effect on the
                                   ICE/BEV trajectory is negligible)
    (none)            -> HEV       (always blank for Netherlands)
    sum of above      -> TOTAL

Table orientation
-----------------
The Whole and HDV workspaces return tables with periods as rows and fuels as
columns; Used Imports returns fuels as rows and (period × sub-column) as
columns, because that workspace splits Aanvoertype into "> 90 dgn" and
"<= 90 dgn" sub-categories which we sum together. The parser detects
orientation from the headRows / headCols labels.

Number format: Dutch locale uses "." as thousands separator (e.g. "6.863" is
six-thousand-eight-hundred-sixty-three, not 6.863). Empty cells render as
"&nbsp;" and are treated as zero.
"""
import argparse
import csv
import os
import re
import sys
import time
from pathlib import Path

import requests

BASE = "https://duurzamemobiliteit.databank.nl"

# Saved Swing workspace templates (configured in the Swing UI via Share Permalink).
# Each is pre-set to monthly granularity, all years 2018-current selected, and
# the relevant Voertuigsoort / Aanvoertype dimension picks.
TEMPLATES = {
    "Whole":        "a7d36cf5-9dd3-4eca-96e9-9e1b991af9ba",  # Personenauto Nieuw
    "Used Imports": "ffaf2d83-0174-4b36-92b9-f7bd96ad4d89",  # Personenauto Occasion import (>90 + <=90)
    "HDV":          "992eb09a-0828-4ef9-97b4-1577ebba3a21",  # Zware bedrijfsvoertuigen Nieuw
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--variant",
        choices=["whole", "used", "hdv", "all"],
        default="all",
        help="Which slice to fetch (default: all)",
    )
    parser.add_argument(
        "--csv", default="data/Netherlands.csv",
        help="Target CSV (default: data/Netherlands.csv)",
    )
    args = parser.parse_args()

    variant_aliases = {"whole": "Whole", "used": "Used Imports", "hdv": "HDV"}
    targets = (
        list(variant_aliases.values())
        if args.variant == "all"
        else [variant_aliases[args.variant]]
    )

    session = requests.Session()
    all_new_rows: dict[tuple[str, str], dict] = {}
    for variant in targets:
        data = fetch_table(variant, session)
        print(f"[{variant}] caption: {data['caption']}")
        parsed = parse_table(data, variant)
        rows = to_csv_rows(parsed, variant)
        print(f"[{variant}] parsed {len(rows)} non-zero months "
              f"({min(rows, default='—')} .. {max(rows, default='—')})")
        for period, row in rows.items():
            all_new_rows[(period, variant)] = row

    if not all_new_rows:
        print("No data parsed. Nothing to update.")
        sys.exit(1)

    added, updated = upsert_csv(args.csv, all_new_rows)
    print(f"\nDone: {added} rows added, {updated} rows updated -> {args.csv}")


if __name__ == "__main__":
    main()
