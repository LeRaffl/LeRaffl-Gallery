#!/usr/bin/env python3
"""
Fetch Ireland new registration data from the SIMI / motorstats public
dashboard (stats.simi.ie) and upsert per-variant CSVs.

Usage
-----
    python scripts/fetch_ireland.py [--variant {whole,vans,hdv,buses,all}]
                                    [--months N] [--since YYYY-MM] [--force]

    --variant     Which slice to fetch (default: all).
    --months N    Trailing window of recent months to (re)fetch each run
                  (default 4 — captures the new month plus revisions to the
                  preceding few; SIMI restates recent months).
    --since YYYY-MM   Backfill: fetch every month from this one to the latest
                  available (used once to populate history). Overrides --months.
    --force       Skip the 'previous month already present' early-exit.

Output files (one per SIMI vehicle-category dashboard, same session-filter flow)
-------------------------------------------------------------------------------
    data/Ireland.csv         <- Whole  passenger cars        (root /)
    data/Ireland_Vans.csv    <- Vans   Light Commercial N1   (/lcv)
    data/Ireland_HDV.csv     <- HDV    Heavy Commercial N2/N3 (/hcv)
    data/Ireland_Buses.csv   <- Buses  buses & coaches M2/M3 (/bus)

How the source works (reverse-engineered May 2026)
--------------------------------------------------
stats.simi.ie is a Laravel + Inertia.js SPA ("powered by motorstats"). The
public passenger-car dashboard lives at the site root (`/`, component
`Public/Passenger`). There is NO public query-param or REST API; data is driven
by a server-side session filter:

  1. GET /                      -> sets XSRF-TOKEN + session cookies; the Inertia
                                  asset version is embedded in <div id=app data-page>.
  2. PATCH /filter/passenger    -> stores the filter in the session. Body is JSON;
                                  crucially `month_from`/`month_to` must be OBJECTS
                                  {"name":"April","value":4} (a bare int 500s),
                                  `years` is [{"name":Y,"value":Y}], and
                                  `registration_type` is {"value":"new-total"}.
                                  Needs the X-XSRF-TOKEN header (decoded cookie).
                                  Returns 303 on success.
  3. GET / (Inertia partial)    -> with headers X-Inertia, X-Inertia-Version,
                                  X-Inertia-Partial-Component: Public/Passenger,
                                  X-Inertia-Partial-Data: carsByEngineType
                                  returns the engine-type breakdown for the
                                  filtered period.

Setting one year + month_from==month_to isolates a single calendar month. The
`carsByEngineType` dataset then carries one `units` entry (that year), whose
counts per engine-type sum to the month's total (verified against the dashboard's
totalRegistrationsTable, e.g. 2026-04 = 10,087).

Engine-type label -> canonical column. Ireland reports HEV and ethanol/flexifuel
natively, like Sweden:
    BEV      <- Electric
    HEV      <- Petrol Electric (Hybrid) + Diesel Electric (Hybrid)
    PHEV     <- Petrol/Plug-In Electric Hybrid + Diesel/Plug-In Electric Hybrid
    PETROL   <- Petrol
    DIESEL   <- Diesel
    FLEXFUEL <- Ethanol/Petrol + Ethanol/Diesel
    OTHERS   <- Gas + Petrol / Gas + Diesel / Gas + Hydrogen + Other
    TOTAL    <- sum

This pipeline migrates Ireland from the legacy local R pipeline. The pre-existing
data/Ireland.csv used the older 12-column schema (no FLEXFUEL); we normalise to
the canonical 13 columns on write. Months the dashboard returns as 0 (no data /
future) are skipped, so pre-dashboard historical rows already in the CSV are left
intact.

See docs/architecture/15-source-ireland.md for the full playbook.
"""
import argparse
import csv
import html
import json
import os
import re
import sys
from datetime import date
from pathlib import Path

import requests

BASE = "https://stats.simi.ie"
SOURCE = "stats.simi.ie"

# Variant -> SIMI dashboard route / Inertia component / filter path / CSV.
# Each SIMI vehicle-category dashboard uses the same session-filter flow; only
# the route, the Inertia component name, and the /filter/<type> path differ.
#   Whole  = passenger cars (root /)        Vans = Light Commercial (N1, <=3.5t)
#   HDV    = Heavy Commercial (N2/N3 >3.5t)  Buses = buses & coaches (M2/M3)
VARIANT_CONFIG = {
    "Whole": {"route": "",    "component": "Public/Passenger", "filter": "passenger", "csv": "data/Ireland.csv"},
    "Vans":  {"route": "lcv", "component": "Public/Lcv",       "filter": "lcv",       "csv": "data/Ireland_Vans.csv"},
    "HDV":   {"route": "hcv", "component": "Public/Hcv",       "filter": "hcv",       "csv": "data/Ireland_HDV.csv"},
    "Buses": {"route": "bus", "component": "Public/Bus",       "filter": "bus",       "csv": "data/Ireland_Buses.csv"},
}

MONTH_NAMES = ["January", "February", "March", "April", "May", "June",
               "July", "August", "September", "October", "November", "December"]

# carsByEngineType dataset label -> canonical column. Raise on anything new so
# we notice if SIMI adds an engine type.
LABEL_TO_COL = {
    "Petrol": "PETROL",
    "Diesel": "DIESEL",
    "Electric": "BEV",
    "Petrol Electric (Hybrid)": "HEV",
    "Diesel Electric (Hybrid)": "HEV",
    "Petrol/Plug-In Electric Hybrid": "PHEV",
    "Diesel/Plug-In Electric Hybrid": "PHEV",
    "Ethanol/Petrol": "FLEXFUEL",
    "Ethanol/Diesel": "FLEXFUEL",
    "Gas": "OTHERS",
    "Petrol / Gas": "OTHERS",
    "Diesel / Gas": "OTHERS",
    "Hydrogen": "OTHERS",
    "Other": "OTHERS",
}

CSV_COLUMNS = [
    "period", "time_interval", "variant", "source",
    "BEV", "PHEV", "HEV", "PETROL", "DIESEL", "FLEXFUEL",
    "OTHERS", "TOTAL", "notes",
]

DATA_PAGE_RE = re.compile(r'data-page="([^"]*)"')


class SimiClient:
    def __init__(self):
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"})
        self.version = None

    def bootstrap(self) -> None:
        r = self.s.get(f"{BASE}/", timeout=30)
        r.raise_for_status()
        m = DATA_PAGE_RE.search(r.text)
        if not m:
            raise RuntimeError("Inertia data-page not found on stats.simi.ie root; "
                               "the site shape changed.")
        page = json.loads(html.unescape(m.group(1)))
        self.version = page["version"]
        if "XSRF-TOKEN" not in self.s.cookies:
            raise RuntimeError("XSRF-TOKEN cookie not set by stats.simi.ie root.")

    def _xsrf(self) -> str:
        return requests.utils.unquote(self.s.cookies.get("XSRF-TOKEN"))

    def fetch_month(self, variant: str, year: int, month: int) -> dict[str, float]:
        """Return {canonical_col: count} for a single (variant, year, month)."""
        cfg = VARIANT_CONFIG[variant]
        page_url = f"{BASE}/{cfg['route']}" if cfg["route"] else f"{BASE}/"
        body = {
            "years": [{"name": year, "value": year}],
            "month_from": {"name": MONTH_NAMES[month - 1], "value": month},
            "day_from": None,
            "month_to": {"name": MONTH_NAMES[month - 1], "value": month},
            "day_to": None,
            "registration_type": {"name": "Total New Registrations", "value": "new-total"},
            "sales_types": [], "makes": [], "models": [], "body_types": [],
            "transmissions": [], "engine_types": [], "engine_capacities": [],
            "colours": [], "segments": [], "counties": [],
        }
        p = self.s.patch(
            f"{BASE}/filter/{cfg['filter']}",
            headers={
                "X-XSRF-TOKEN": self._xsrf(),
                "Content-Type": "application/json",
                "Accept": "application/json",
                "X-Requested-With": "XMLHttpRequest",
                "Origin": BASE, "Referer": page_url,
            },
            data=json.dumps(body), allow_redirects=False, timeout=30,
        )
        if p.status_code not in (200, 302, 303):
            raise RuntimeError(f"[{variant} {year}-{month:02d}] filter PATCH failed: "
                               f"HTTP {p.status_code} {p.text[:200]}")
        g = self.s.get(
            page_url,
            headers={
                "X-Inertia": "true",
                "X-Inertia-Version": self.version,
                "X-Inertia-Partial-Component": cfg["component"],
                "X-Inertia-Partial-Data": "carsByEngineType",
            },
            allow_redirects=False, timeout=30,
        )
        g.raise_for_status()
        ce = g.json()["props"].get("carsByEngineType")
        if not ce:
            return {}
        cols: dict[str, float] = {}
        for ds in ce["datasets"]:
            label = ds["label"]
            col = LABEL_TO_COL.get(label)
            if col is None:
                raise RuntimeError(
                    f"[{year}-{month:02d}] unmapped engine-type label {label!r} "
                    f"— add it to LABEL_TO_COL."
                )
            count = ds["units"][0]["count"] if ds.get("units") else 0
            cols[col] = cols.get(col, 0.0) + float(count or 0)
        return cols


def row_from_cols(variant: str, period: str, cols: dict[str, float]) -> dict | None:
    total = sum(cols.values())
    if total == 0.0:
        return None
    return {
        "period": period, "time_interval": "monthly", "variant": variant, "source": SOURCE,
        "BEV": cols.get("BEV", 0.0), "PHEV": cols.get("PHEV", 0.0), "HEV": cols.get("HEV", 0.0),
        "PETROL": cols.get("PETROL", 0.0), "DIESEL": cols.get("DIESEL", 0.0),
        "FLEXFUEL": cols.get("FLEXFUEL", 0.0), "OTHERS": cols.get("OTHERS", 0.0),
        "TOTAL": total, "notes": "",
    }


def upsert_csv(csv_path: str, new_rows: dict) -> tuple[int, int]:
    existing: dict = {}
    if os.path.exists(csv_path):
        with open(csv_path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                # Normalise: older rows may lack FLEXFUEL — fill missing keys.
                for col in CSV_COLUMNS:
                    row.setdefault(col, "")
                existing[(row["period"], row["variant"])] = {k: row[k] for k in CSV_COLUMNS}

    added = updated = 0
    for key, new_row in sorted(new_rows.items()):
        if key not in existing:
            existing[key] = new_row
            added += 1
            print(f"  + {key[1]} {key[0]}")
        else:
            old = existing[key]
            for col in ["BEV", "PHEV", "HEV", "PETROL", "DIESEL", "FLEXFUEL", "OTHERS"]:
                old_val = float(old.get(col) or 0)
                new_val = float(new_row[col] or 0)
                if old_val > 100 and abs(new_val - old_val) / old_val > 0.5:
                    print(f"  WARNING {key[1]} {key[0]} {col}: existing={old_val:.0f}, "
                          f"new={new_val:.0f} — diff >50%, please verify")
            if not new_row.get("notes"):
                new_row["notes"] = old.get("notes", "")
            existing[key] = {**old, **new_row}
            updated += 1

    Path(csv_path).parent.mkdir(parents=True, exist_ok=True)
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, lineterminator="\n")
        writer.writeheader()
        for key in sorted(existing.keys(), key=lambda k: (k[1], k[0])):
            writer.writerow(existing[key])
    return added, updated


def previous_month() -> tuple[int, int]:
    t = date.today()
    return (t.year - 1, 12) if t.month == 1 else (t.year, t.month - 1)


def month_range(start: tuple[int, int], end: tuple[int, int]):
    y, m = start
    while (y, m) <= end:
        yield y, m
        m += 1
        if m == 13:
            y, m = y + 1, 1


def csv_has_period(csv_path: str, period: str, variant: str) -> bool:
    if not os.path.exists(csv_path):
        return False
    with open(csv_path, newline="", encoding="utf-8") as f:
        return any(r["period"] == period and r["variant"] == variant for r in csv.DictReader(f))


def run_variant(client: "SimiClient", variant: str, start, end) -> None:
    cfg = VARIANT_CONFIG[variant]
    print(f"[{variant}] fetching {start[0]}-{start[1]:02d} .. {end[0]}-{end[1]:02d}")
    new_rows: dict = {}
    for y, mo in month_range(start, end):
        cols = client.fetch_month(variant, y, mo)
        row = row_from_cols(variant, f"{y}-{mo:02d}", cols)
        if row is None:
            continue
        new_rows[(f"{y}-{mo:02d}", variant)] = row
    if not new_rows:
        print(f"[{variant}] no non-zero months fetched.")
        return
    added, updated = upsert_csv(cfg["csv"], new_rows)
    print(f"[{variant}] {added} added, {updated} updated -> {cfg['csv']}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--variant", choices=["whole", "vans", "hdv", "buses", "all"],
                    default="all", help="Which slice to fetch (default: all).")
    ap.add_argument("--months", type=int, default=4,
                    help="Trailing window of recent months to (re)fetch (default 4).")
    ap.add_argument("--since", type=str, default=None,
                    help="Backfill start 'YYYY-MM' (fetch through latest). Overrides --months.")
    ap.add_argument("--force", action="store_true",
                    help="Skip the 'previous month already present' early-exit.")
    args = ap.parse_args()

    aliases = {"whole": "Whole", "vans": "Vans", "hdv": "HDV", "buses": "Buses"}
    targets = list(aliases.values()) if args.variant == "all" else [aliases[args.variant]]

    py, pm = previous_month()
    prev_period = f"{py}-{pm:02d}"
    end = (py, pm)

    if args.since:
        m = re.match(r"(\d{4})-(\d{2})$", args.since)
        if not m:
            sys.exit("--since must be YYYY-MM")
        start = (int(m.group(1)), int(m.group(2)))
    else:
        total = py * 12 + (pm - 1) - (args.months - 1)
        start = (total // 12, total % 12 + 1)

    # Per-variant early-exit (skip variants already current), unless --since/--force.
    if not args.since and not args.force:
        pending = [v for v in targets
                   if not csv_has_period(VARIANT_CONFIG[v]["csv"], prev_period, v)]
        for v in [v for v in targets if v not in pending]:
            print(f"[{v}] CSV already has {prev_period}; skipping.")
        targets = pending
        if not targets:
            print("All requested variants are current; nothing to do.")
            return

    client = SimiClient()
    client.bootstrap()
    print(f"Inertia version {client.version}")
    for variant in targets:
        run_variant(client, variant, start, end)


if __name__ == "__main__":
    main()
