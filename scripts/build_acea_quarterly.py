#!/usr/bin/env python3
"""ACEA's quarterly fuel-type release, per country, as one long table.

reference/acea_country_quarterly.csv — country, quarter (YYYY-Qn), BEV,
PHEV, HEV, PETROL, DIESEL, release, column. ACEA published the country
split by fuel only quarterly until 2022 (monthly per-country tables start
with the 2024-11 release); these XLSX files, one per quarter, are what the
HEV back-estimates for countries whose own source has no hybrid split are
built from (Czechia 2018-2021; a cross-check for the Netherlands and
Finland — docs 10, 12, 51).

ACEA's HEV includes full and mild hybrids; PETROL and DIESEL exclude them.
Each release carries its quarter and the same quarter a year earlier; the
release's own quarter is used, the prior-year column only where no release
of that quarter exists (2014, and 2018 Q1 from the 2019 Q1 file). The
2015-2017 alternative-fuel releases have HEV but no petrol/diesel split, and
merge BEV and PHEV for some countries, so only their HEV is kept.

    python scripts/build_acea_quarterly.py [--cache DIR] [--out PATH]
"""
from __future__ import annotations

import argparse
import csv
import io
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reference" / "acea_country_quarterly.csv"
BASE = "https://www.acea.auto/files/"
# One release per quarter (found through the site's media library; the
# 2018-2019 posts themselves only embed charts).
RELEASES = [
    # Alternative-fuel releases: HEV per country, no petrol/diesel split.
    "AFV_registrations_Q1_2015_FINAL.xlsx",
    "AFV_registrations_Q2_2015_FINAL_v2.xlsx",
    "AFV_registrations_Q3_2015_FINAL.xlsx",
    "AFV_registrations_Q4_2015_FINAL.xlsx",
    "20160513_AFV_Q1_2016_FINAL.xlsx",
    "20160907_AFV_Q2_2016_FINAL.xlsx",
    "20161028_AFV_Q3_2016_FINAL.xlsx",
    "20170201_AFV_Q4_2016_FINAL.xlsx",
    "20170504_AFV_Q1_2017_FINAL.xlsx",
    "20170907_AFV_Q2_2017_FINAL.xlsx",
    "20180130_AFV_Q3_2017_FINAL.xlsx",
    "20180201_AFV_Q4_2017_FINAL.xlsx",
    # Fuel-type releases: BEV, PHEV, HEV, petrol, diesel per country.
    "20180905_Fuel_types_Q2_2018_FINAL.xlsx",
    "20181108_PRPC_fuel_Q3_2018_FINAL.xlsx",
    "20190207_PRPC_fuel_Q4_2018_FINAL.xlsx",
    "20190508_PRPC_fuel_Q1_2019_FINAL.xlsx",
    "20190904_PRPC_fuel_Q2_2019_FINAL.xlsx",
    "20191107_PRPC_fuel_Q3_2019_FINAL.xlsx",
    "20200206_PRPC_fuel_Q4_2019_FINAL.xlsx",
    "20200512_PRPC_fuel_Q1_2020_FINAL.xlsx",
    "20200903_PRPC_fuel_Q2_2020-FINAL.xlsx",
    "20201105_PRPC_fuel_Q3_2020_FINAL.xlsx",
    "20210204_PRPC_fuel_Q4_2020_FINAL.xlsx",
    "20210423_PRPC_fuel_Q1_2021_FINAL.xlsx",
    "20210723_PRPC-fuel_Q2-2021_FINAL.xlsx",
    "20211022_PRPC-fuel_Q3-2021_FINAL.xlsx",
    "20220202_PRPC-fuel_Q4-2021_FINAL.xlsx",
    "20220505_PRPC-fuel_Q1-2022_FINAL.xlsx",
    "20220720_PRPC-fuel_Q2-2022_FINAL.xlsx",
    "20221103_PRPC-fuel_Q3-2022_FINAL.xlsx",
    "20230201_PRPC-fuel_Q4-2022_FINAL.xlsx",
]
SHEETS = {"BEV": "BEV", "PHEV": "PHEV", "HEV": "HEV", "HEVs": "HEV",
          "Petrol": "PETROL", "Diesel": "DIESEL"}
FIELDS = ["country", "quarter", "BEV", "PHEV", "HEV", "PETROL", "DIESEL", "release", "column"]
ALIASES = {"CZECH REPUBLIC": "Czechia", "CZECHIA": "Czechia"}
NOT_COUNTRIES = ("EUROPEAN UNION", "EU", "EFTA", "EU + EFTA", "EU + EFTA + UK", "CHANGE", "UNITS",
                 "TOTAL", "EU14", "EU13", "EU12", "EU11", "EU28", "EU27")


def release_quarter(name: str) -> tuple[int, int]:
    m = re.search(r"Q([1-4])[_-]?(\d{4})", name)
    if not m:
        raise ValueError(f"no quarter in {name}")
    return int(m.group(2)), int(m.group(1))


def country_name(cell: str) -> str | None:
    t = " ".join(str(cell).split()).rstrip("0123456789*").strip()
    up = t.upper()
    if not t or up in NOT_COUNTRIES or up.startswith(("EU", "EFTA", "TOTAL", "SOURCE", "1", "2")):
        return None
    if not re.fullmatch(r"[A-Za-z .'-]+", t):
        return None
    return ALIASES.get(up, t.title())


def parse_sheet(rows) -> dict[str, tuple[float, float]]:
    """{country: (this quarter, same quarter a year earlier)}: the first two
    numbers to the right of a country name."""
    out = {}
    for row in rows:
        for i, cell in enumerate(row):
            if not isinstance(cell, str):
                continue
            name = country_name(cell)
            if not name:
                continue
            nums = [c for c in row[i + 1:] if isinstance(c, (int, float))]
            if len(nums) >= 2:
                out.setdefault(name, (float(nums[0]), float(nums[1])))
            break
    return out


def parse_release(data: bytes, name: str) -> list[dict]:
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    y, q = release_quarter(name)
    sheets = {}
    for sheet, col in SHEETS.items():
        if sheet in wb.sheetnames and col not in sheets:
            sheets[col] = parse_sheet(wb[sheet].iter_rows(values_only=True))
    rows = []
    countries = set().union(*sheets.values()) if sheets else set()
    for which, (yy, label) in enumerate(((y, "quarter"), (y - 1, "prior-year"))):
        for c in sorted(countries):
            rec = {"country": c, "quarter": f"{yy}-Q{q}", "release": BASE + name, "column": label}
            for col, table in sheets.items():
                v = table.get(c)
                rec[col] = "" if v is None else int(v[which])
            if "AFV" in name:       # BEV/PHEV merged for some countries there
                for col in ("BEV", "PHEV", "PETROL", "DIESEL"):
                    rec[col] = ""
            rows.append(rec)
    return rows


def build(cache: Path | None) -> list[dict]:
    import requests
    by_key: dict[tuple[str, str], dict] = {}
    for name in RELEASES:
        path = cache / name if cache else None
        if path and path.exists():
            data = path.read_bytes()
        else:
            r = requests.get(BASE + name, timeout=120)
            r.raise_for_status()
            data = r.content
            if path:
                path.write_bytes(data)
        for rec in parse_release(data, name):
            key = (rec["country"], rec["quarter"])
            # A quarter's own release wins over a later prior-year column.
            if key not in by_key or (by_key[key]["column"] == "prior-year"
                                     and rec["column"] == "quarter"):
                by_key[key] = rec
    return [by_key[k] for k in sorted(by_key)]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cache", type=Path, help="directory with the XLSX files (downloaded if missing)")
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()
    rows = build(args.cache)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    print(f"{args.out}: {len(rows)} country-quarters", file=sys.stderr)


if __name__ == "__main__":
    main()
