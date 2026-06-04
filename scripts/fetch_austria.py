#!/usr/bin/env python3
"""
Fetch Austria first-registration data from Statistik Austria's .ods
publications and upsert per-variant CSVs under data/.

Usage
-----
    python scripts/fetch_austria.py [--variant {whole,hdv,vans,all}]
                                    [--year YYYY] [--force]

Output files
------------
    data/Austria.csv          <- variant=Whole (Pkw Klasse M1)
    data/Austria_HDV.csv      <- variant=HDV   (Lkw N2 + N3 + Sattelzugfahrzeuge)
    data/Austria_Vans.csv     <- variant=Vans  (Lkw N1, ≤ 3.5 t)

Sources
-------
Listing page:
  https://www.statistik.at/statistiken/tourismus-und-verkehr/fahrzeuge/kfz-neuzulassungen

Two .ods file families are used (paths under /fileadmin/pages/77/):
  DE2 — "Fahrzeug-Neuzulassungen", one sheet per month. Used for Whole only.
        Tabelle 2 = "Pkw-Neuzulassungen nach Kraftstoffart" with explicit
        "darunter Plug-In" rows that let us split PHEV vs HEV.
        Filenames:  DE2_NeuzulassungenFahrzeugeJaennerBis<Month><YYYY>.ods
                    NeuzulassungenFahrzeugeJaennerBisDezember<YYYY>.ods
  DE3 — "Kfz-Neuzulassungen nach Bundesland und Kraftstoffart", vehicle class
        × fuel column matrix. Two layouts:
          DE3 monthly: per-month sheets (available 2025-01 onward).
                       Filenames: (DE3_)?NeuzulassungenKraftfahrzeugeBundesland
                                  KraftstoffartEnergiequelleJaennerBis<M><Y>.ods
          DE3 annual : single year sheet, used as fallback for years before
                       monthly cumulative files appeared (only 2024 currently).
                       Filename: NeuzulassungenKraftfahrzeugeBundeslandKraftstoff
                                 artEnergiequelle<YYYY>.ods

Canonical-column mapping
------------------------
Whole (DE2 Pkw Tabelle 2):
    BEV     <- Elektro
    PHEV    <- "darunter Plug-In" (Benzin/Elektro) + (Diesel/Elektro)
    HEV     <- (Benzin/Elektro hybrid − Plug-In) + (Diesel/Elektro hybrid − Plug-In)
    PETROL  <- Benzin
    DIESEL  <- Diesel
    OTHERS  <- Pkw insgesamt − Σ above  (sweeps Erdgas / LPG / Wasserstoff)

HDV / Vans (DE3 vehicle-class rows):
    BEV     <- Elektro
    PHEV    <- ""  (DE3 has no Plug-In subsplit for Lkw rows)
    HEV     <- Benzin/Elektro (hybrid) + Diesel/Elektro (hybrid)
               (lumped: source publishes PHEV + HEV + MHEV together for Lkw;
                we put the lump under HEV, leave PHEV blank — same shape as
                Finland's HEV-blank convention, mirrored.)
    PETROL  <- Benzin
    DIESEL  <- Diesel
    OTHERS  <- Erdgas + Flüssiggas + bivalent + Wasserstoff
    TOTAL   <- sum of the canonical columns above

Backfill scope
--------------
Whole: existing data/Austria.csv (manually extracted 2012-01 onward) is
authoritative; this script just keeps it current.
HDV / Vans: no prior CSV. Statistik Austria's per-month Kraftstoff×Klasse
publication only exists from 2025-01 onward, so the backfill envelope is:
  2024            -> single annual row (time_interval=annual, period=2024)
  2025 / 2026 ... -> monthly rows
Pre-2024 monthly LKW × fuel is not published.

Schedule
--------
.github/workflows/fetch-austria.yml runs daily on the 8th-22nd at 09:25 UTC.
Statistik Austria publishes the previous month's cumulative file around the
10th-14th of the month at 07-09 UTC; 09:25 UTC sits just after that window.
Per-variant early-exit makes runs no-ops once the previous month is in the CSV.
"""
import argparse
import csv
import io
import os
import re
import xml.etree.ElementTree as ET
import zipfile
from datetime import date
from pathlib import Path

import requests

LISTING_URL = (
    "https://www.statistik.at/statistiken/tourismus-und-verkehr/"
    "fahrzeuge/kfz-neuzulassungen"
)
FILE_BASE = "https://www.statistik.at"
SOURCE = "Statistik Austria"

CSV_COLUMNS = [
    "period", "time_interval", "variant", "source",
    "BEV", "PHEV", "HEV", "PETROL", "DIESEL", "OTHERS", "TOTAL", "notes",
]

# Sheet name (proper German) -> month number. Cumulative-month sheets
# (e.g. "Jänner-April") and aggregate sheets do not match and are skipped.
MONTH_NAMES = {
    "Jänner": 1, "Februar": 2, "März": 3, "April": 4, "Mai": 5, "Juni": 6,
    "Juli": 7, "August": 8, "September": 9, "Oktober": 10, "November": 11, "Dezember": 12,
}

# URL month-name (ASCII) -> month number. Used to rank cumulative files when
# multiple coexist for a year (we always pick the file covering the most months).
URL_MONTH_NAMES = {
    "Jaenner": 1, "Februar": 2, "Maerz": 3, "April": 4, "Mai": 5, "Juni": 6,
    "Juli": 7, "August": 8, "September": 9, "Oktober": 10, "November": 11, "Dezember": 12,
}

# DE2 Tabelle-2 row labels (exact, including en-dash U+2013 in "Plug-In" rows).
L_BENZIN = "Benzin"
L_DIESEL = "Diesel"
L_ELEKTRO = "Elektro"
L_HYB_B  = "Benzin/Elektro (hybrid)"
L_PLG_B  = "darunter Benzin/Elektro (hybrid) – Plug-In"
L_HYB_D  = "Diesel/Elektro (hybrid)"
L_PLG_D  = "darunter Diesel/Elektro (hybrid) – Plug-In"
L_TOTAL  = "Pkw insgesamt"

# DE3 fuel-column header -> canonical column. Statistik Austria varies
# whitespace and small wording across files ("Benzin" vs "Benzin inkl.Flex-Fuel",
# "Wasserstoff (Brennstoffzelle)" with or without the space). We normalise by
# stripping all whitespace and lowercasing before lookup, so the keys here are
# the normalised forms.
def _norm_fuel(s: str) -> str:
    return re.sub(r"\s+", "", s).lower()

_DE3_FUEL_RAW = {
    "Benzin":                          "PETROL",
    "Benzin inkl.Flex-Fuel":           "PETROL",
    "Benzin inkl. Flex-Fuel":          "PETROL",
    "Diesel":                          "DIESEL",
    "Elektro":                         "BEV",
    "Benzin/Elektro (hybrid)":         "HEV",
    "Diesel/Elektro (hybrid)":         "HEV",
    "Erdgas":                          "OTHERS",
    "Flüssiggas":                      "OTHERS",
    "Benzin/Erdgas (bivalent)":        "OTHERS",
    "Benzin/Flüssiggas (bivalent)":    "OTHERS",
    "Wasserstoff (Brennstoffzelle)":   "OTHERS",
}
DE3_FUEL_TO_COL = {_norm_fuel(k): v for k, v in _DE3_FUEL_RAW.items()}

# Variant configuration. file_kinds lists the source families to fetch,
# in order of preference for any given year. classes is the set of DE3
# vehicle-class row labels to sum (None for Whole, which uses DE2 Pkw rows).
VARIANT_CONFIG = {
    "Whole": {
        "csv": "data/Austria.csv",
        "file_kinds": ["de2"],
        "classes": None,
    },
    "HDV": {
        "csv": "data/Austria_HDV.csv",
        "file_kinds": ["de3_monthly", "de3_annual"],
        "classes": frozenset({
            "Lastkraftwagen Klasse N2",
            "Lastkraftwagen Klasse N3",
            "Sattelzugfahrzeuge",
        }),
    },
    "Vans": {
        "csv": "data/Austria_Vans.csv",
        "file_kinds": ["de3_monthly", "de3_annual"],
        "classes": frozenset({"Lastkraftwagen Klasse N1"}),
    },
}

# Filename regexes (all anchored under /fileadmin/pages/77/).
FILE_RE_DE2 = re.compile(
    r"/fileadmin/pages/77/(?:DE\d+_)?"
    r"NeuzulassungenFahrzeugeJaennerBis([A-Za-z]+)(\d{4})\.ods"
)
FILE_RE_DE3_MONTHLY = re.compile(
    r"/fileadmin/pages/77/(?:DE\d+_)?"
    r"NeuzulassungenKraftfahrzeugeBundeslandKraftstoffartEnergiequelle"
    r"JaennerBis([A-Za-z]+)(\d{4})\.ods"
)
FILE_RE_DE3_ANNUAL = re.compile(
    r"/fileadmin/pages/77/"
    r"NeuzulassungenKraftfahrzeugeBundeslandKraftstoffartEnergiequelle(\d{4})\.ods"
)

TNS = "{urn:oasis:names:tc:opendocument:xmlns:table:1.0}"
ONS = "{urn:oasis:names:tc:opendocument:xmlns:office:1.0}"
PNS = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}"


# ---------------------------------------------------------------------------
# URL discovery
# ---------------------------------------------------------------------------

def discover_file_urls(session: requests.Session) -> dict[tuple[str, int], str]:
    """Return {(kind, year): absolute_url}.

    kind ∈ {"de2", "de3_monthly", "de3_annual"}. For DE2 and DE3-monthly we
    keep, per year, the file covering the most months (highest URL month);
    DE3-annual yields one entry per year.
    """
    r = session.get(LISTING_URL, timeout=60)
    r.raise_for_status()
    text = r.text

    best: dict[tuple[str, int], tuple[int, str]] = {}

    def consider(kind: str, year: int, month_idx: int, path: str) -> None:
        key = (kind, year)
        prev = best.get(key)
        if prev is None or month_idx > prev[0]:
            best[key] = (month_idx, FILE_BASE + path)

    for m in FILE_RE_DE2.finditer(text):
        idx = URL_MONTH_NAMES.get(m.group(1))
        if idx is None:
            print(f"[discover] WARNING: unknown DE2 URL month {m.group(1)!r}")
            continue
        consider("de2", int(m.group(2)), idx, m.group(0))

    for m in FILE_RE_DE3_MONTHLY.finditer(text):
        idx = URL_MONTH_NAMES.get(m.group(1))
        if idx is None:
            print(f"[discover] WARNING: unknown DE3 URL month {m.group(1)!r}")
            continue
        consider("de3_monthly", int(m.group(2)), idx, m.group(0))

    for m in FILE_RE_DE3_ANNUAL.finditer(text):
        # Skip if this URL also matched the DE3-monthly pattern (it ends with
        # ...JaennerBis<Month><Year>.ods); the annual regex is the loose superset.
        if FILE_RE_DE3_MONTHLY.fullmatch(m.group(0)):
            continue
        consider("de3_annual", int(m.group(1)), 0, m.group(0))

    return {k: url for k, (_, url) in best.items()}


def fetch_ods(url: str, session: requests.Session, cache: dict) -> bytes:
    if url in cache:
        return cache[url]
    print(f"[fetch] {url}")
    r = session.get(url, timeout=120)
    r.raise_for_status()
    cache[url] = r.content
    return r.content


# ---------------------------------------------------------------------------
# ODS / XML helpers
# ---------------------------------------------------------------------------

def _row_cells(row: ET.Element) -> list[str]:
    """Return raw cell values for a row, expanding number-columns-repeated up to 3."""
    out: list[str] = []
    for c in row.findall(f"{TNS}table-cell"):
        rep = int(c.get(f"{TNS}number-columns-repeated", "1") or "1")
        v = c.get(f"{ONS}value")
        if v is None:
            v = "".join(t.text or "" for t in c.iter(f"{PNS}p"))
        for _ in range(min(rep, 3)):
            out.append(v)
    return out


def _to_float(v: str) -> float:
    """Convert cell text to float; '' / '-' / non-numeric → 0.0."""
    if v is None:
        return 0.0
    s = str(v).strip()
    if not s or s == "-":
        return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def _open_xml(content: bytes) -> ET.Element:
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        return ET.fromstring(z.read("content.xml"))


# ---------------------------------------------------------------------------
# DE2 parser (Whole)
# ---------------------------------------------------------------------------

def _parse_de2_sheet_tab2(sheet: ET.Element) -> dict[str, float]:
    """Read DE2 Pkw 'Tabelle 2: ... nach Kraftstoffart' rows.

    Returns {row_label: column-B value} for rows between the Tabelle-2 header
    and the source-footnote (`Q:`) / next-table marker.
    """
    found: dict[str, float] = {}
    in_tab2 = False
    for r in sheet.findall(f"{TNS}table-row"):
        cells = _row_cells(r)
        if not cells:
            continue
        label = str(cells[0]).strip()
        if not in_tab2:
            if label.startswith("Tabelle 2") and "Kraftstoffart" in label:
                in_tab2 = True
            continue
        if label.startswith("Q:") or label.startswith("Tabelle 3"):
            break
        if len(cells) < 2:
            continue
        try:
            found[label] = float(cells[1])
        except (ValueError, TypeError):
            continue
    return found


def parse_de2(content: bytes, year: int) -> dict[str, dict[str, float]]:
    """Parse a DE2 cumulative-month .ods. Returns {period: canonical-cols}."""
    root = _open_xml(content)
    out: dict[str, dict[str, float]] = {}
    for sheet in root.iter(f"{TNS}table"):
        sheet_name = sheet.get(f"{TNS}name", "")
        month = MONTH_NAMES.get(sheet_name)
        if month is None:
            continue  # cumulative / helper sheet
        rows = _parse_de2_sheet_tab2(sheet)
        if not rows:
            print(f"[Whole {year}-{month:02d}] WARNING: Tabelle 2 not found in {sheet_name!r}")
            continue
        required = [L_BENZIN, L_DIESEL, L_ELEKTRO, L_HYB_B, L_PLG_B, L_HYB_D, L_PLG_D, L_TOTAL]
        missing = [k for k in required if k not in rows]
        if missing:
            print(f"[Whole {year}-{month:02d}] WARNING: missing {missing} — skipping")
            continue

        petrol = rows[L_BENZIN]
        diesel = rows[L_DIESEL]
        bev    = rows[L_ELEKTRO]
        hyb_b, plg_b = rows[L_HYB_B], rows[L_PLG_B]
        hyb_d, plg_d = rows[L_HYB_D], rows[L_PLG_D]
        total  = rows[L_TOTAL]

        phev = plg_b + plg_d
        hev  = (hyb_b - plg_b) + (hyb_d - plg_d)
        others = total - bev - phev - hev - petrol - diesel
        if -0.5 < others < 0:
            others = 0.0
        if others < 0:
            print(f"[Whole {year}-{month:02d}] WARNING: OTHERS={others:.1f} < 0")

        out[f"{year}-{month:02d}"] = {
            "BEV": bev, "PHEV": phev, "HEV": hev,
            "PETROL": petrol, "DIESEL": diesel,
            "OTHERS": max(0.0, others), "TOTAL": total,
        }
    return out


# ---------------------------------------------------------------------------
# DE3 parser (HDV / Vans)
# ---------------------------------------------------------------------------

def _de3_header_map(rows: list[ET.Element]) -> dict[int, str] | None:
    """Locate the header row and return {col_idx: canonical}."""
    for r in rows:
        cells = _row_cells(r)
        if not cells:
            continue
        labels = [str(c).strip() for c in cells]
        norms = [_norm_fuel(lbl) for lbl in labels]
        # Header is the row containing both "Diesel" and a Benzin-family cell.
        if "diesel" in norms and any(n.startswith("benzin") for n in norms):
            mapping: dict[int, str] = {}
            for i, (lbl, n) in enumerate(zip(labels, norms)):
                if i == 0 or not lbl:
                    continue
                canon = DE3_FUEL_TO_COL.get(n)
                if canon is None:
                    print(f"[discover] WARNING: unknown DE3 fuel column {lbl!r} "
                          f"— bucketing into OTHERS")
                    canon = "OTHERS"
                mapping[i] = canon
            return mapping
    return None


def _sum_de3_classes(
    sheet: ET.Element,
    classes: frozenset[str],
    period_label: str,
) -> dict[str, float] | None:
    rows = sheet.findall(f"{TNS}table-row")
    header = _de3_header_map(rows)
    if header is None:
        return None

    # DE3 sheets list each vehicle class once for the Österreich aggregate, then
    # again per Bundesland (9 federal states). We want only the Österreich-level
    # numbers, so we sum the *first* occurrence of each target class label.
    sums = {"BEV": 0.0, "HEV": 0.0, "PETROL": 0.0, "DIESEL": 0.0, "OTHERS": 0.0}
    matched: set[str] = set()
    for r in rows:
        cells = _row_cells(r)
        if not cells:
            continue
        label = str(cells[0]).strip()
        if label not in classes or label in matched:
            continue
        matched.add(label)
        for col_idx, canon in header.items():
            if col_idx >= len(cells):
                continue
            sums[canon] += _to_float(cells[col_idx])

    missing = classes - matched
    if missing:
        print(f"[{period_label}] WARNING: vehicle classes not found: {sorted(missing)}")
        if not matched:
            return None

    sums["TOTAL"] = sum(sums.values())
    return sums


def parse_de3_monthly(content: bytes, year: int, variant: str,
                      classes: frozenset[str]) -> dict[str, dict[str, float]]:
    """Parse a DE3 cumulative-month .ods. Returns {period: cols}."""
    root = _open_xml(content)
    out: dict[str, dict[str, float]] = {}
    for sheet in root.iter(f"{TNS}table"):
        sheet_name = sheet.get(f"{TNS}name", "")
        month = MONTH_NAMES.get(sheet_name)
        if month is None:
            continue
        period = f"{year}-{month:02d}"
        cols = _sum_de3_classes(sheet, classes, f"{variant} {period}")
        if cols is not None:
            out[period] = cols
    return out


def parse_de3_annual(content: bytes, year: int, variant: str,
                     classes: frozenset[str]) -> dict[str, dict[str, float]]:
    """Parse a DE3 single-sheet annual .ods. Returns {period: cols} (one entry)."""
    root = _open_xml(content)
    # Annual files have a single data sheet whose name is the year (e.g. "2024").
    sheets = list(root.iter(f"{TNS}table"))
    if not sheets:
        return {}
    cols = _sum_de3_classes(sheets[0], classes, f"{variant} {year}")
    if cols is None:
        return {}
    return {str(year): cols}


# ---------------------------------------------------------------------------
# Row assembly & upsert
# ---------------------------------------------------------------------------

def to_csv_rows(parsed: dict[str, dict[str, float]], variant: str,
                time_interval: str) -> dict:
    rows: dict = {}
    for period, cols in parsed.items():
        if cols.get("TOTAL", 0.0) == 0.0:
            continue
        rows[period] = {
            "period": period,
            "time_interval": time_interval,
            "variant": variant,
            "source": SOURCE,
            "BEV":    cols.get("BEV", 0.0),
            "PHEV":   cols.get("PHEV", ""),
            "HEV":    cols.get("HEV", ""),
            "PETROL": cols.get("PETROL", 0.0),
            "DIESEL": cols.get("DIESEL", 0.0),
            "OTHERS": cols.get("OTHERS", 0.0),
            "TOTAL":  cols["TOTAL"],
            "notes":  "",
        }
    return rows


def upsert_csv(csv_path: str, new_rows: dict) -> tuple[int, int]:
    """Upsert by (period, variant). Returns (added, updated). Warns on >50% delta."""
    existing: dict = {}
    if os.path.exists(csv_path):
        with open(csv_path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                existing[(row["period"], row["variant"])] = row

    added = updated = 0
    for period, new_row in sorted(new_rows.items()):
        key = (period, new_row["variant"])
        if key not in existing:
            existing[key] = new_row
            added += 1
            print(f"  + {new_row['variant']} {period}")
        else:
            old = existing[key]
            for col in ["BEV", "PHEV", "HEV", "PETROL", "DIESEL", "OTHERS", "TOTAL"]:
                try:
                    old_val = float(old.get(col) or 0)
                    new_val = float(new_row.get(col) or 0)
                except (TypeError, ValueError):
                    continue
                if old_val > 100 and abs(new_val - old_val) / old_val > 0.5:
                    print(
                        f"  WARNING {new_row['variant']} {period} {col}: "
                        f"existing={old_val:.0f}, new={new_val:.0f} — diff >50%"
                    )
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


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def previous_month_period() -> str:
    today = date.today()
    if today.month == 1:
        return f"{today.year - 1}-12"
    return f"{today.year}-{today.month - 1:02d}"


def csv_has_period_for_variant(csv_path: str, period: str, variant: str) -> bool:
    if not os.path.exists(csv_path):
        return False
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["period"] == period and row["variant"] == variant:
                return True
    return False


def run_variant(variant: str, urls: dict, session: requests.Session,
                cache: dict, year_filter: int | None) -> tuple[int, int]:
    cfg = VARIANT_CONFIG[variant]
    classes = cfg["classes"]
    csv_path = cfg["csv"]
    total_added = total_updated = 0

    # Collect (kind, year, url) the variant cares about, deduping by year so
    # that — when both DE3 monthly and annual exist for the same year — the
    # monthly file wins (it's listed first in file_kinds).
    by_year: dict[int, tuple[str, str]] = {}
    for kind in cfg["file_kinds"]:
        for (k, y), url in urls.items():
            if k != kind:
                continue
            if year_filter is not None and y != year_filter:
                continue
            by_year.setdefault(y, (kind, url))

    if not by_year:
        print(f"[{variant}] no source files available "
              f"{'for year ' + str(year_filter) if year_filter else ''}")
        return (0, 0)

    for year in sorted(by_year):
        kind, url = by_year[year]
        content = fetch_ods(url, session, cache)
        if kind == "de2":
            parsed = parse_de2(content, year)
            interval = "monthly"
        elif kind == "de3_monthly":
            parsed = parse_de3_monthly(content, year, variant, classes)
            interval = "monthly"
        elif kind == "de3_annual":
            parsed = parse_de3_annual(content, year, variant, classes)
            interval = "annual"
        else:
            raise RuntimeError(f"unknown file kind {kind!r}")

        rows = to_csv_rows(parsed, variant, interval)
        if not rows:
            print(f"[{variant} {year}] no rows from {url}")
            continue
        print(f"[{variant} {year}] parsed {len(rows)} row(s) "
              f"({min(rows)} .. {max(rows)}) from {kind}")
        added, updated = upsert_csv(csv_path, rows)
        total_added += added
        total_updated += updated

    print(f"[{variant}] {total_added} added, {total_updated} updated -> {csv_path}")
    return total_added, total_updated


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--variant", choices=["whole", "hdv", "vans", "all"], default="all",
        help="Variant to fetch (default: all).",
    )
    parser.add_argument(
        "--year", type=int, default=None,
        help="Refetch only this year (default: current year + any historic "
             "files the variant needs that aren't already in its CSV).",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Skip the 'already current' early-exit check.",
    )
    args = parser.parse_args()

    aliases = {"whole": "Whole", "hdv": "HDV", "vans": "Vans"}
    targets = list(aliases.values()) if args.variant == "all" else [aliases[args.variant]]

    if not args.force and args.year is None:
        prev = previous_month_period()
        skip = [v for v in targets
                if csv_has_period_for_variant(VARIANT_CONFIG[v]["csv"], prev, v)]
        for v in skip:
            print(f"[{v}] CSV already has {prev}; skipping (use --force to re-fetch).")
        targets = [v for v in targets if v not in skip]
        if not targets:
            print("All requested variants are current; nothing to do.")
            return

    session = requests.Session()
    session.headers.update({"User-Agent": "LeRaffl-Gallery/austria-fetch"})
    urls = discover_file_urls(session)
    if not urls:
        raise RuntimeError("No source files found on listing page.")

    # year_filter behaviour:
    #   --year given        -> only that year, for every variant
    #   default (no --year) -> current year for Whole (already-backfilled CSV);
    #                          all available years for HDV/Vans the first time
    #                          (subsequent runs early-exit). After first
    #                          backfill, year_filter=current keeps reruns fast.
    cache: dict = {}
    current_year = date.today().year
    for variant in targets:
        if args.year is not None:
            yf = args.year
        elif variant == "Whole":
            yf = current_year
        else:
            # HDV/Vans: backfill all years on first run, current year thereafter.
            csv_path = VARIANT_CONFIG[variant]["csv"]
            yf = None if not os.path.exists(csv_path) else current_year
        run_variant(variant, urls, session, cache, yf)


if __name__ == "__main__":
    main()
