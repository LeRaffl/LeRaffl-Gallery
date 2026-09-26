#!/usr/bin/env python3
"""
Fetch Singapore new-car registration data from the Land Transport Authority
(LTA) monthly statistics PDF **M03 "New Registration of Cars by Make"** and
upsert ``data/Singapore.csv``.

Usage
-----
    python scripts/fetch_singapore.py [--dry-run] [--since YYYY-MM] [--url URL]

Source
------
https://www.lta.gov.sg/.../statistics/pdf/M03-Car_Regn_by_make.pdf

This is the official primary source. LTA publishes a single rolling PDF that
covers the current half-year (e.g. Jan–Jun), one row per
``Make × Importer Type × Fuel Type``, with per-month sub-columns
``HB SDN MPV STW SUV Conv Total``. We sum each month's per-row **Total** column
across all makes, grouped by Fuel Type, into the gallery's wide schema.

Why not a cleaner API: data.gov.sg's "cars by make/fuel" datastore is frozen at
2025-05; SingStat M650281 has no fuel split. The LTA PDF is the only current,
official source that breaks new car registrations down by fuel type. (Robbie
Andrew's widely-used CSV is this same data, pre-parsed.) See
docs/architecture/26-source-singapore.md.

Coverage / cadence
------------------
The PDF is a rolling current half-year, so one fetch yields up to ~6 recent
months; the upsert is keyed on ``(period, variant)`` so older months already in
the CSV are left untouched. ``time_interval`` is ``monthly``.

Fuel classification (the PDF's Fuel Type values)
-----------------------------------------------
    Electric                      → BEV
    Petrol-Electric (Plug-In)     → PHEV    (also Diesel-Electric (Plug-In))
    Petrol-Electric               → HEV     (also Diesel-Electric)
    Petrol                        → PETROL
    Diesel                        → DIESEL
    CNG / Petrol-CNG / Others     → OTHERS

Top brands (market/singapore_top.json)
--------------------------------------
Every M03 row already names its make, so the parse also tallies
``(month, fuel column, make)`` — brand × fuel for free. The make is the row
label minus its fuel suffix and its importer type; any label whose importer
part is not one of IMPORTER_TYPES stops the refresh (never a guessed brand).
Months go into the month store market/singapore_months.json (the PDF only
ever holds the current half-year) and market/singapore_top.json is rebuilt
from it via scripts/market_top.py. Brands only — M03 has no models. Runs
behind market_top.guarded, so it never blocks the data.

Invoked by ``.github/workflows/fetch-singapore.yml``. The commit step is
change-gated, so steady-state runs are a no-op.
"""
import argparse
import csv
import os
import re
from pathlib import Path

import sys

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import market_top  # noqa: E402

SOURCE = "lta.gov.sg"   # rendered as "Source: lta.gov.sg"; R. Andrew credited in footnotes.csv
CSV_PATH = "data/Singapore.csv"
VARIANT = "Whole"
M03_URL = ("https://www.lta.gov.sg/content/dam/ltagov/who_we_are/"
           "statistics_and_publications/statistics/pdf/M03-Car_Regn_by_make.pdf")

CSV_COLUMNS = [
    "period", "time_interval", "variant", "source",
    "BEV", "PHEV", "HEV", "PETROL", "DIESEL", "OTHERS", "TOTAL", "notes",
]
VALUE_COLUMNS = ["BEV", "PHEV", "HEV", "PETROL", "DIESEL", "OTHERS"]

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; LeRaffl-Gallery fetch_singapore)"}

# Fuel Type strings as they appear in M03, longest first so a suffix match picks
# the most specific (…(Plug-In) before plain …-Electric, which classify_fuel
# then maps to the right column).
_FUEL_PHRASES = [
    "petrol-electric (plug-in)", "diesel-electric (plug-in)",
    "petrol-electric", "diesel-electric",
    "petrol-cng", "electric", "petrol", "diesel", "cng", "others",
]
_BODY_TOKENS = {"HB", "SDN", "MPV", "STW", "SUV", "Conv", "Total"}

# Ordered (test, column) on the lowercased fuel string. Order matters:
# plug-in (but not "non-plug") before generic electric/hybrid; pure "electric"
# (BEV) before the "-electric" hybrids.
FUEL_RULES = [
    (lambda s: "plug" in s and "non-plug" not in s, "PHEV"),
    (lambda s: "battery electric" in s,             "BEV"),
    (lambda s: s == "electric",                     "BEV"),
    (lambda s: "hybrid" in s,                       "HEV"),
    (lambda s: "electric" in s,                     "HEV"),
    (lambda s: "cng" in s,                          "OTHERS"),
    (lambda s: "diesel" in s,                       "DIESEL"),
    (lambda s: "petrol" in s,                       "PETROL"),
]


def classify_fuel(label: str) -> str:
    s = (label or "").strip().lower()
    for test, col in FUEL_RULES:
        if test(s):
            return col
    return "OTHERS"


# Importer-type part of an M03 row label ("<Make> <Importer Type> <Fuel Type>"),
# lower-cased, longest first. LTA's own codes are AD (authorised dealer) and
# PI (parallel importer).
IMPORTER_TYPES = sorted([
    "authorised dealers", "authorised dealer", "authorized dealers", "authorized dealer",
    "parallel importers", "parallel importer", "parallel imports", "parallel import",
    "ad", "pi",
], key=len, reverse=True)
TOP_SLUG = "singapore"
TOP_UNIT = "registrations (brand = M03 make; no models published)"


def make_of(label_wo_fuel: str) -> str:
    """'bmw ad' -> 'BMW'. Raises on an importer part it does not know, so a
    layout change can never publish 'BMW XYZ' as a brand."""
    t = " ".join(label_wo_fuel.split())
    for imp in IMPORTER_TYPES:
        if t.endswith(" " + imp):
            return market_top.clean(t[: -len(imp)])
    raise ValueError(f"M03 row label {label_wo_fuel!r}: no known importer type "
                     f"(expected one of {IMPORTER_TYPES})")


def refresh_top(makes: dict, periods: dict) -> None:
    """`makes`: {(month, column, label-without-fuel): units} from parse_m03;
    `periods`: its per-month fuel totals (the TOTAL of data/Singapore.csv)."""
    units: dict = {}
    for (m, col, rest), n in makes.items():
        key = (m, col, make_of(rest), "")
        units[key] = units.get(key, 0) + n
    by_month = market_top.per_month(units)
    fresh = {m: (by_month.get(m, {}), int(sum(cols.values())))
             for m, cols in periods.items() if sum(cols.values())}
    for m, (u, t) in fresh.items():         # same numbers as the CSV, or stop
        if sum(u.values()) != t:
            raise RuntimeError(f"{m}: make rows sum to {sum(u.values())}, total {t}")
    market_top.refresh_from_store("Singapore", SOURCE, TOP_UNIT, TOP_SLUG, fresh)


# --------------------------------------------------------------------------- #
# M03 PDF parsing
# --------------------------------------------------------------------------- #
def _cluster_lines(words: list, tol: float = 3.0) -> list:
    """Group extracted words into lines by their vertical position."""
    rows: list = []
    for w in sorted(words, key=lambda x: (round(x["top"]), x["x0"])):
        if rows and abs(w["top"] - rows[-1][0]) <= tol:
            rows[-1][1].append(w)
        else:
            rows.append((w["top"], [w]))
    return [sorted(ws, key=lambda x: x["x0"]) for _, ws in rows]


def _num(text: str):
    t = (text or "").replace(",", "").strip()
    return int(t) if re.fullmatch(r"\d+", t) else None


def parse_m03(pdf_bytes: bytes, debug: bool = False) -> tuple[dict, dict]:
    """Parse the M03 PDF into ({period: {VALUE_COL: total}}, stats).

    Positional strategy (robust to the PDF's zero-suppressed text): per page the
    sub-header line carrying HB/SDN/.../Total gives every body column's x-centre;
    grouped in 7s the 7th ("Total") of each block is that month's total column,
    ordered by the YYYY-MM labels. Each data row's fuel is the suffix of its
    label; every numeric cell is assigned to its nearest column, and only the
    month-Total columns are summed (per fuel).
    """
    import io
    import pdfplumber

    periods: dict[str, dict[str, float]] = {}
    makes: dict[tuple[str, str, str], int] = {}
    rows_ok = rows_bad = 0
    unmapped: set[str] = set()

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            words = page.extract_words(keep_blank_chars=False, use_text_flow=False)
            lines = _cluster_lines(words)

            month_words = sorted(
                (w for w in words if re.fullmatch(r"20\d{2}-\d{2}", w["text"])),
                key=lambda w: w["x0"])
            months = [w["text"] for w in month_words]
            if not months:
                continue

            sub = max(lines, key=lambda ln: sum(1 for w in ln if w["text"] in _BODY_TOKENS))
            cols = [w for w in sub if w["text"] in _BODY_TOKENS]
            if len(cols) < 7 or len(cols) % 7 != 0:
                if debug:
                    print(f"  [m03] page skipped: {len(cols)} body cols, months={months}")
                continue
            n_blocks = len(cols) // 7
            block_months = months[:n_blocks]
            col_centers = [(w["x0"] + w["x1"]) / 2 for w in cols]
            label_left = min(col_centers) - 5
            sub_top = sub[0]["top"]

            for ln in lines:
                if ln[0]["top"] <= sub_top + 3:
                    continue  # header region
                label_words = [w for w in ln if (w["x0"] + w["x1"]) / 2 < label_left]
                label = " ".join(w["text"] for w in label_words).strip().lower()
                # Skip headers, footnotes and notes (anything not a Make … Fuel row).
                if (not label or label[0].isdigit()
                        or label.startswith(("total", "period", "make", "new registration",
                                             "note", "web/", "lta", "source", "figures"))):
                    continue
                fuel = next((p for p in _FUEL_PHRASES if label.endswith(p)), None)
                if fuel is None:
                    fuel = next((p for p in _FUEL_PHRASES if p in label), None)
                if fuel is None:
                    unmapped.add(label)
                    continue
                col = classify_fuel(fuel)
                rest = label[: label.rindex(fuel)].strip()

                row_assigned = 0
                for w in ln:
                    val = _num(w["text"])
                    if val is None:
                        continue
                    cx = (w["x0"] + w["x1"]) / 2
                    ci = min(range(len(col_centers)), key=lambda i: abs(col_centers[i] - cx))
                    if ci % 7 != 6:
                        continue  # a body sub-column, not the month total
                    m = block_months[ci // 7]
                    periods.setdefault(m, {c: 0.0 for c in VALUE_COLUMNS})[col] += val
                    makes[(m, col, rest)] = makes.get((m, col, rest), 0) + val
                    row_assigned += val
                rows_ok += 1 if row_assigned else 0
                rows_bad += 0 if row_assigned else 1

    stats = {"rows_ok": rows_ok, "rows_bad": rows_bad,
             "unmapped": sorted(unmapped), "periods": sorted(periods),
             "makes": makes}
    return periods, stats


def build_rows(periods: dict, since: str | None) -> dict:
    rows: dict = {}
    for period, cols in periods.items():
        if since and period < since:
            continue
        total = sum(cols.values())
        if total == 0:
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
    return rows


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
    ap.add_argument("--url", default=M03_URL, help="Override the M03 PDF URL.")
    ap.add_argument("--since", default=None,
                    help="Only upsert months >= this YYYY-MM (default: all the PDF holds).")
    ap.add_argument("--dry-run", action="store_true",
                    help="Fetch and parse, print the monthly totals, but do not write.")
    ap.add_argument("--debug", action="store_true", help="Verbose parsing diagnostics.")
    ap.add_argument("--force", action="store_true",
                    help="Accepted for parity with other fetchers (commit-gated downstream).")
    args = ap.parse_args()

    session = requests.Session()
    r = session.get(args.url, headers=HEADERS, timeout=120)
    print(f"[m03] GET {args.url} -> HTTP {r.status_code} ({len(r.content)} bytes)")
    r.raise_for_status()

    periods, stats = parse_m03(r.content, debug=args.debug)
    print(f"[m03] rows_ok={stats['rows_ok']} rows_bad={stats['rows_bad']} "
          f"periods={stats['periods']}")
    if stats["unmapped"]:
        print(f"[m03] WARNING unmapped fuel labels (skipped): {stats['unmapped'][:20]}")

    rows = build_rows(periods, args.since)
    if not rows:
        print("no non-zero months parsed")
        return
    for key in sorted(rows):
        c = rows[key]
        print(f"  {key[0]}  " + "  ".join(f"{col}={c[col]}" for col in VALUE_COLUMNS)
              + f"  TOTAL={c['TOTAL']:.0f}")

    if args.dry_run:
        print("(dry-run: CSV not written)")
        return

    added, updated = upsert_csv(CSV_PATH, rows)
    print(f"{added} added, {updated} updated -> {CSV_PATH}")
    market_top.guarded(refresh_top, stats["makes"],
                       {p: c for p, c in periods.items()
                        if not args.since or p >= args.since})


if __name__ == "__main__":
    main()
