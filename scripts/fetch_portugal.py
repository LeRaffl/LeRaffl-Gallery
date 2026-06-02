#!/usr/bin/env python3
"""
Fetch Portugal new registration data from ACAP's public data backend
(motordata.pt / autoinforma) and upsert per-variant CSVs.

Usage
-----
    python scripts/fetch_portugal.py [--variant {whole,vans,hdv,buses,all}] [--force]
    python scripts/fetch_portugal.py --sheet [--force]    # backfill/patch Whole from Google Sheet

Output files (one per motordata vehicle-category; same POST flow, different cat)
-------------------------------------------------------------------------------
    data/Portugal.csv         <- Whole  Ligeiros de Passageiros (M1)        cat 0
    data/Portugal_Vans.csv    <- Vans   Ligeiros de Mercadorias (N1 <=3.5t) cat 1
    data/Portugal_HDV.csv     <- HDV    Pesados de Mercadorias (N2/N3 >3.5t) cat 3
    data/Portugal_Buses.csv   <- Buses  Pesados de Passageiros (M2/M3)      cat 2

Note: motordata exposes only the CURRENT calendar year (no year param), and the
Google Sheet only has passenger history — so the commercial variants start thin
(2025/2026) and accumulate over time. They are fetched/committed but not
auto-rendered on schedule (see .github/workflows/fetch-portugal.yml).

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
SOURCE = "ACAP"

# Variant -> motordata vehicle-category code (list_catveiculo) + CSV.
#   0 Ligeiros Passageiros (M1) | 1 Ligeiros Mercadorias (N1, Vans) |
#   2 Pesados Passageiros (M2/M3, Buses) | 3 Pesados Mercadorias (N2/N3 >3.5t, HDV)
VARIANT_CONFIG = {
    "Whole": {"cat": "0", "csv": "data/Portugal.csv"},
    "Vans":  {"cat": "1", "csv": "data/Portugal_Vans.csv"},
    "HDV":   {"cat": "3", "csv": "data/Portugal_HDV.csv"},
    "Buses": {"cat": "2", "csv": "data/Portugal_Buses.csv"},
}

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


def fetch_fuel_series(session: requests.Session, cat: str, fuel_code: str) -> list[float]:
    """Current year's monthly series for one (vehicle category, fuel). Index 0 = January."""
    r = session.post(
        CHART_URL,
        headers={"Referer": CHART_REFERER, "X-Requested-With": "XMLHttpRequest"},
        data={"list_catveiculo": cat, "list_combustivel": fuel_code},
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    return [float(str(v).replace(".", "").replace(",", ".") or 0) for v in data.get("thisyear", [])]


def fetch_motordata(cat: str) -> dict:
    """Build {period: {col: value, 'TOTAL': t}} for the current calendar year."""
    year = date.today().year
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"})

    # All-fuels total (empty fuel filter) — authoritative monthly TOTAL.
    total_series = fetch_fuel_series(session, cat, "")

    # month index -> {core col: value}
    by_month: dict[int, dict[str, float]] = {}
    for fuel_code, col in PT_CORE_FUEL.items():
        series = fetch_fuel_series(session, cat, fuel_code)
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


def to_rows(parsed: dict, variant: str, from_sheet: bool) -> dict:
    rows: dict = {}
    for period, cols in parsed.items():
        total = cols.get("TOTAL", "")
        total_num = float(total) if total not in ("", None) else 0.0
        if total_num == 0.0:
            continue
        rows[(period, variant)] = {
            "period": period, "time_interval": "monthly", "variant": variant, "source": SOURCE,
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
            if not new_row.get("notes"):
                new_row["notes"] = old.get("notes", "")
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


def csv_has_period(csv_path: str, period: str, variant: str) -> bool:
    if not os.path.exists(csv_path):
        return False
    with open(csv_path, newline="", encoding="utf-8") as f:
        return any(r["period"] == period and r["variant"] == variant for r in csv.DictReader(f))


def run_variant(variant: str, from_sheet: bool) -> None:
    cfg = VARIANT_CONFIG[variant]
    if from_sheet:
        parsed = fetch_sheet()  # sheet only carries passenger (Whole)
    else:
        parsed = fetch_motordata(cfg["cat"])
    rows = to_rows(parsed, variant, from_sheet)
    if not rows:
        print(f"[{variant}] no non-zero months fetched.")
        return
    periods = sorted(p for p, _ in rows)
    print(f"[{variant}] parsed {len(rows)} months ({periods[0]} .. {periods[-1]})")
    added, updated = upsert_csv(cfg["csv"], rows)
    print(f"[{variant}] {added} added, {updated} updated -> {cfg['csv']}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--variant", choices=["whole", "vans", "hdv", "buses", "all"],
                    default="all", help="Which slice to fetch (default: all).")
    ap.add_argument("--sheet", action="store_true",
                    help="Backfill/patch the Whole variant from the maintainer's Google Sheet "
                         "(the sheet only carries passenger cars).")
    ap.add_argument("--force", action="store_true", help="Skip the 'previous month present' early-exit.")
    args = ap.parse_args()

    if args.sheet:
        # The Google Sheet only has passenger data → Whole only.
        run_variant("Whole", from_sheet=True)
        return

    aliases = {"whole": "Whole", "vans": "Vans", "hdv": "HDV", "buses": "Buses"}
    targets = list(aliases.values()) if args.variant == "all" else [aliases[args.variant]]

    if not args.force:
        prev = previous_month_period()
        pending = [v for v in targets
                   if not csv_has_period(VARIANT_CONFIG[v]["csv"], prev, v)]
        for v in [v for v in targets if v not in pending]:
            print(f"[{v}] CSV already has {prev}; skipping.")
        targets = pending
        if not targets:
            print("All requested variants are current; nothing to do.")
            return

    for variant in targets:
        run_variant(variant, from_sheet=False)


if __name__ == "__main__":
    main()
