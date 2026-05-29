#!/usr/bin/env python3
"""
Fetch Portugal new passenger-car registration data from ACAP's public data
backend (motordata.pt / autoinforma) and upsert data/Portugal.csv.

Usage
-----
    python scripts/fetch_portugal.py [--force]
    python scripts/fetch_portugal.py --sheet [--force]    # backfill/patch from Google Sheet

Output file
-----------
    data/Portugal.csv   <- variant=Whole (Ligeiros de Passageiros, all fuels)

Sources
-------
ACAP (Associação Automóvel de Portugal) publishes registrations on the 1st of
each month from ~17:00 Lisbon time. Its public "Dados" page
(https://www.acap.pt/pt/estatisticas/dados) embeds a motordata.pt chart whose
data comes from a POST endpoint:

    POST https://motordata.pt/autoinforma/chartdata_novo.php
    body: list_catveiculo=0          (0 = LIGEIROS DE PASSAGEIROS / passenger cars)
          list_combustivel=<code>    (single fuel code; see PT_FUEL below)
    -> JSON { thisyear:[Jan..latest], lastyear:[same months prior year], result_table:[...] }

`thisyear` is the monthly series for the CURRENT calendar year (only published
months; e.g. in late May it is [Jan,Feb,Mar,Apr]). There is NO year parameter —
the endpoint always returns the current year. So this fetcher maintains the
current year's months; historical months come from the committed CSV (already
present from the legacy pipeline) or the maintainer's Google Sheet (--sheet).

Fuel code -> canonical column (verified: HEV 17+18 sum = the sheet's HEV, etc.):
    BEV     <- 7  Elétrico (BEV)
    PHEV    <- 14 PHEV/Gasolina + 15 PHEV/Gasóleo
    HEV     <- 17 HEV/Gasolina  + 18 HEV/Gasóleo
    PETROL  <- 1  Gasolina
    DIESEL  <- 2  Gasóleo
    TOTAL   <- all-fuels query (empty list_combustivel) — authoritative
    OTHERS  <- TOTAL − (BEV+PHEV+HEV+PETROL+DIESEL)   [catches GNC/GPL/GNL/H2 and
               any fuel codes NOT shown in the dropdown — the dropdown is
               incomplete, e.g. codes 20/23 exist but aren't listed, so summing
               named "other" codes undercounts; the residual is exact: verified
               2026-04 OTHERS = 21595 − 19977 = 1618 = the sheet's value]
    FLEXFUEL <- (always empty — Portugal does not report ethanol/flexfuel)

Vehicle categories also exposed (out of scope; passenger cars only for now):
    0 Ligeiros passageiros | 1 Ligeiros mercadorias (Vans) |
    2 Pesados passageiros (Buses) | 3 Pesados mercadorias (HDV >3.5t goods).

Year-boundary caveat: December data publishes on Jan 1, when the endpoint's
"thisyear" rolls to the new (empty) year. December may therefore not be fetchable
via motordata until it appears; use `--sheet` to patch it from the maintainer's
Google Sheet (which carries the full history and is kept current).

See docs/architecture/16-source-portugal.md for the full playbook.
"""
import argparse
import csv
import io
import os
import re
import sys
import urllib.request
from datetime import date
from pathlib import Path

import requests

CHART_URL = "https://motordata.pt/autoinforma/chartdata_novo.php"
CHART_REFERER = "https://motordata.pt/autoinforma/charts1t.php"
CAT_PASSENGER = "0"
SOURCE = "ACAP"
CSV_PATH = "data/Portugal.csv"
VARIANT = "Whole"

SHEET_ID = "1tT_Ja3de_S528_JeSBkj74q-lfEIekE5-GRm9_pWgUo"
SHEET_GID = "1007806052"
SHEET_URL = (f"https://docs.google.com/spreadsheets/d/{SHEET_ID}"
             f"/gviz/tq?tqx=out:csv&gid={SHEET_GID}")

# Core fuel code -> canonical column. OTHERS is computed as a residual against
# the all-fuels TOTAL (the dropdown's fuel list is incomplete, so enumerating
# "other" codes would undercount).
PT_CORE_FUEL = {
    "7": "BEV",
    "14": "PHEV", "15": "PHEV",
    "17": "HEV", "18": "HEV",
    "1": "PETROL", "2": "DIESEL",
}

CSV_COLUMNS = [
    "period", "time_interval", "variant", "source",
    "BEV", "PHEV", "HEV", "PETROL", "DIESEL", "FLEXFUEL",
    "OTHERS", "TOTAL", "notes",
]


def fetch_fuel_series(session: requests.Session, fuel_code: str) -> list[float]:
    """Return the current year's monthly series for one fuel (index 0 = January)."""
    r = session.post(
        CHART_URL,
        headers={"Referer": CHART_REFERER, "X-Requested-With": "XMLHttpRequest"},
        data={"list_catveiculo": CAT_PASSENGER, "list_combustivel": fuel_code},
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    return [float(str(v).replace(".", "").replace(",", ".") or 0) for v in data.get("thisyear", [])]


def fetch_motordata() -> dict:
    """Build {period: {col: value, 'TOTAL': t}} for the current calendar year."""
    year = date.today().year
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"})

    # All-fuels total (empty fuel filter) — authoritative monthly TOTAL.
    total_series = fetch_fuel_series(session, "")

    # month index -> {core col: value}
    by_month: dict[int, dict[str, float]] = {}
    for fuel_code, col in PT_CORE_FUEL.items():
        series = fetch_fuel_series(session, fuel_code)
        for i, val in enumerate(series):
            by_month.setdefault(i, {}).setdefault(col, 0.0)
            by_month[i][col] += val

    out: dict[str, dict[str, float]] = {}
    for i, total in enumerate(total_series):
        cols = by_month.get(i, {})
        core = sum(cols.values())
        cols["OTHERS"] = max(0.0, total - core)
        cols["TOTAL"] = total
        out[f"{year}-{i + 1:02d}"] = cols
    return out


def parse_sheet_num(s: str):
    """European format: '14.558' -> 14558.0; '' -> ''."""
    s = (s or "").strip()
    if not s:
        return ""
    return float(s.replace(".", "").replace(",", "."))


def fetch_sheet() -> dict:
    """Read the maintainer's Google Sheet Portugal tab -> {period: {col: value}}."""
    print(f"Fetching Google Sheet: {SHEET_URL}")
    text = urllib.request.urlopen(SHEET_URL).read().decode("utf-8")
    rows = list(csv.reader(io.StringIO(text)))
    header = rows[0]
    col = {name: i for i, name in enumerate(header)}
    out: dict[str, dict] = {}
    period_re = re.compile(r"(\d{4})M(\d{2})")
    for r in rows[1:]:
        if not r or not r[col["YYYYMMM"]]:
            continue
        m = period_re.match(r[col["YYYYMMM"]].strip())
        if not m:
            continue
        period = f"{m.group(1)}-{m.group(2)}"
        out[period] = {c: parse_sheet_num(r[col[c]]) if c in col else ""
                       for c in ["BEV", "PHEV", "HEV", "PETROL", "DIESEL", "OTHERS", "TOTAL"]}
    return out


def to_rows(parsed: dict, from_sheet: bool) -> dict:
    rows: dict = {}
    for period, cols in parsed.items():
        total = cols.get("TOTAL", "")
        total_num = float(total) if total not in ("", None) else 0.0
        if total_num == 0.0:
            continue
        rows[(period, VARIANT)] = {
            "period": period, "time_interval": "monthly", "variant": VARIANT, "source": SOURCE,
            "BEV": cols.get("BEV", 0.0 if not from_sheet else ""),
            "PHEV": cols.get("PHEV", 0.0 if not from_sheet else ""),
            "HEV": cols.get("HEV", 0.0 if not from_sheet else ""),
            "PETROL": cols.get("PETROL", 0.0 if not from_sheet else ""),
            "DIESEL": cols.get("DIESEL", 0.0 if not from_sheet else ""),
            "FLEXFUEL": "",  # Portugal never reports ethanol/flexfuel
            "OTHERS": cols.get("OTHERS", 0.0 if not from_sheet else ""),
            "TOTAL": total,
            "notes": "",
        }
    return rows


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
            old = existing[key]
            for c in ["BEV", "PHEV", "HEV", "PETROL", "DIESEL", "OTHERS"]:
                ov = float(old.get(c) or 0)
                nv = float(new_row[c] or 0)
                if ov > 100 and abs(nv - ov) / ov > 0.5:
                    print(f"  WARNING {key[1]} {key[0]} {c}: existing={ov:.0f}, new={nv:.0f} "
                          f"— diff >50%, please verify")
            existing[key] = {**old, **new_row}
            updated += 1

    Path(csv_path).parent.mkdir(parents=True, exist_ok=True)
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS, lineterminator="\n")
        w.writeheader()
        for key in sorted(existing.keys(), key=lambda k: (k[1], k[0])):
            w.writerow(existing[key])
    return added, updated


def previous_month_period() -> str:
    t = date.today()
    if t.month == 1:
        return f"{t.year - 1}-12"
    return f"{t.year}-{t.month - 1:02d}"


def csv_has_period(csv_path: str, period: str) -> bool:
    if not os.path.exists(csv_path):
        return False
    with open(csv_path, newline="", encoding="utf-8") as f:
        return any(r["period"] == period and r["variant"] == VARIANT for r in csv.DictReader(f))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sheet", action="store_true",
                    help="Backfill/patch from the maintainer's Google Sheet instead of motordata.")
    ap.add_argument("--force", action="store_true", help="Skip the 'previous month present' early-exit.")
    args = ap.parse_args()

    if not args.sheet and not args.force and csv_has_period(CSV_PATH, previous_month_period()):
        print(f"CSV already has {previous_month_period()}; nothing to do (use --force or --sheet).")
        return

    if args.sheet:
        parsed = fetch_sheet()
        rows = to_rows(parsed, from_sheet=True)
    else:
        parsed = fetch_motordata()
        rows = to_rows(parsed, from_sheet=False)

    if not rows:
        print("No non-zero months fetched.")
        return
    periods = sorted(p for p, _ in rows)
    print(f"Parsed {len(rows)} months ({periods[0]} .. {periods[-1]})")
    added, updated = upsert_csv(CSV_PATH, rows)
    print(f"{added} added, {updated} updated -> {CSV_PATH}")


if __name__ == "__main__":
    main()
