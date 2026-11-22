#!/usr/bin/env python3
"""Denmark's ACEA fuel split 2023-01 .. latest, month by month, from ACEA's
public press-release PDFs -> reference/acea_denmark_hev.csv.

Why: Statistics Denmark has no code for non-plug hybrids (they sit in its
petrol and diesel). ACEA's Danish HEV is Mobility Denmark's "Hybrid" +
"Mild Hybrid" (DBI IT's classification of the same register), and
scripts/denmark_hev.py splits Statbank's petrol + diesel by ACEA's
HEV:petrol:diesel shares. This file is the history behind that split;
scripts/backfill_denmark_hev.py applies it. 2022 comes from ACEA's
quarterly fuel releases already in reference/acea_country_quarterly.csv.

Every release carries a MONTHLY and a YEAR-TO-DATE table, each with this
year's and last year's column. Releases before November 2023 render those
tables as images, and ACEA's edge refuses some releases from some IPs, so
a month is taken, in this order, from:

  1. a release's own MONTHLY table (this-year column),
  2. the next year's release's MONTHLY table (prior-year column),
  3. YTD(month) - YTD(month - 1), from either YTD column,
  4. a YTD span minus the months inside it that are known; when more than
     one month of the span is unknown, the span stays one row (basis
     "span") and backfill_denmark_hev.py gives each of its months the
     span's shares, flagged as an estimate.

The derivation of every row is written next to it. Run (network):

    python scripts/extract_acea_denmark.py --cache /tmp/acea --to 2026-09
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_acea as fa  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reference" / "acea_denmark_hev.csv"
COUNTRY = "Denmark"
FUELS = fa.PDF_FUEL_ORDER            # BEV PHEV HEV OTHERS PETROL DIESEL TOTAL
FIRST = "2023-01"
COLUMNS = ["from", "to", "basis", *FUELS, "derivation"]


def _per(y: int, m: int) -> str:
    return f"{y}-{m:02d}"


def _months(lo: str, hi: str) -> list[str]:
    y, m = int(lo[:4]), int(lo[5:])
    out = []
    while _per(y, m) <= hi:
        out.append(_per(y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


# ------------------------------------------------------------ PDF access
def pdf_for(period: str, cache: Path, tries: int = 3) -> Path | None:
    y, m = int(period[:4]), int(period[5:])
    path = cache / f"{period}.pdf"
    if path.is_file():
        return path
    url = fa.ACEA_URL_TEMPLATE.format(month_name=fa.ENGLISH_MONTHS[m - 1], year=y)
    for attempt in range(tries):
        try:
            path.write_bytes(fa.load_pdf_bytes(url))
            return path
        except FileNotFoundError:
            return None
        except Exception as e:              # ACEA's edge (520/403) is moody
            if attempt == tries - 1:
                print(f"  {period}: not available ({e})")
                return None
            time.sleep(3 * (attempt + 1))
    return None


# ------------------------------------------------------------ YTD table
# The YTD grid shares the MONTHLY grid's header; fetch_acea.py only reads
# MONTHLY. Three layouts occur (clean text, cell rules with newline-joined
# values, runs fragmented by stray spaces), tried in that order.
def _ytd_page(pdf):
    for page in pdf.pages:
        text = page.extract_text() or ""
        if "BY MARKET AND POWER SOURCE" in text and re.search(r"YEAR[- ]TO[- ]DATE", text):
            return page, text
    return None, None


def _ytd_via_text(text: str) -> dict | None:
    m = re.search(r"YEAR[- ]TO[- ]DATE", text)
    seg = text[m.end():]
    m2 = re.search(r"\bMONTHLY\b", seg)
    if m2:
        seg = seg[:m2.start()]
    for line in seg.split("\n"):
        line = line.strip()
        if line.startswith(COUNTRY + " "):
            pairs = fa._parse_country_pairs(line[len(COUNTRY):])
            if pairs is not None:
                return dict(zip(FUELS, pairs))
    return None


def _ytd_via_tables(page) -> dict | None:
    for cand in (page.extract_tables() or []):
        if not cand or len(cand) < 3:
            continue
        header = [fa._normalise_header(c) for c in cand[0]]
        if "BATTERYELECTRIC" not in header or "TOTAL" not in header:
            continue
        col: dict[str, int] = {}
        for ci, cell in enumerate(cand[0]):
            key = fa.HEADER_TO_FUEL.get(fa._normalise_header(cell))
            if key and key not in col:
                col[key] = ci
        if set(fa.HEADER_TO_FUEL.values()) - set(col):
            continue
        for row in cand[1:]:
            names = [n.strip() for n in (row[0] or "").split("\n") if n.strip()]
            if COUNTRY not in names:
                continue
            i = names.index(COUNTRY)
            out = {}
            for fuel, ci in col.items():
                lines = (row[ci] or "").split("\n")
                cell = fa._parse_cell(lines[i]) if i < len(lines) else None
                if cell is None:
                    break
                out[fuel] = cell
            else:
                return out
    return None


def _ytd_via_position(page) -> dict | None:
    def num(cell):
        s = re.sub(r"[^0-9,]", "", (cell or "").replace(" ", ""))
        return int(s.replace(",", "")) if s else None

    for strategy in (("text", "text"), ("lines", "text"), ("text", "lines")):
        try:
            tables = page.extract_tables({"vertical_strategy": strategy[0],
                                          "horizontal_strategy": strategy[1]})
        except Exception:
            continue
        for cand in tables:
            if not cand or len(cand[0]) < 2 + 3 * len(FUELS):
                continue
            for row in cand:
                if not row or re.sub(r"\s+", "", row[0] or "").casefold() != COUNTRY.casefold():
                    continue
                out = {}
                for i, fuel in enumerate(FUELS):
                    cur, pri = num(row[2 + 3 * i]), num(row[3 + 3 * i])
                    if cur is None or pri is None:
                        break
                    out[fuel] = (cur, pri)
                else:
                    return out
    return None


def parse_ytd(pdf_path: Path) -> dict | None:
    """{fuel: (this-year YTD, prior-year YTD)} for Denmark, or None."""
    import pdfplumber
    with pdfplumber.open(str(pdf_path)) as pdf:
        page, text = _ytd_page(pdf)
        if page is None:
            return None
        return _ytd_via_text(text) or _ytd_via_tables(page) or _ytd_via_position(page)


def parse_month(pdf_path: Path) -> dict | None:
    """{fuel: (this month, same month last year)} for Denmark, or None."""
    try:
        parsed, _ = fa.parse_monthly_table(str(pdf_path), [COUNTRY])
    except Exception:
        return None
    return parsed.get(COUNTRY)


# ------------------------------------------------------------ assembly
def collect(releases: dict[str, Path]) -> tuple[dict, dict]:
    """(month values, YTD values), each {period: (fuels, provenance)}."""
    mon: dict[str, tuple[dict, str]] = {}
    ytd: dict[str, tuple[dict, str]] = {}
    for period in sorted(releases):
        y, m = int(period[:4]), int(period[5:])
        got = parse_month(releases[period])
        if got:
            mon.setdefault(period, ({f: got[f][0] for f in FUELS}, f"{period} release, monthly table"))
            mon.setdefault(_per(y - 1, m), ({f: got[f][1] for f in FUELS},
                                            f"{period} release, monthly table, prior-year column"))
        got = parse_ytd(releases[period])
        if got:
            ytd.setdefault(period, ({f: got[f][0] for f in FUELS}, f"{period} release YTD"))
            ytd.setdefault(_per(y - 1, m), ({f: got[f][1] for f in FUELS},
                                            f"{period} release YTD, prior-year column"))
    return mon, ytd


def assemble(mon: dict, ytd: dict, lo: str, hi: str) -> list[dict]:
    """Rows of reference/acea_denmark_hev.csv (see the module docstring)."""
    zero = ({f: 0 for f in FUELS}, "start of year")

    def y_at(y: int, m: int):
        return zero if m == 0 else ytd.get(_per(y, m))

    def sub(a: dict, b: dict) -> dict:
        return {f: a[f] - b[f] for f in FUELS}

    known = {p: v for p, v in mon.items() if lo <= p <= hi}
    for p in _months(lo, hi):                                      # step 3
        if p in known:
            continue
        y, m = int(p[:4]), int(p[5:])
        a, b = y_at(y, m), y_at(y, m - 1)
        if a and b:
            known[p] = (sub(a[0], b[0]), f"{a[1]} minus {b[1]}")
    spans = []
    done = set(known)
    for p in _months(lo, hi):                                      # step 4
        if p in done:
            continue
        y, m = int(p[:4]), int(p[5:])
        hit = None
        for start in range(m, 0, -1):
            low = y_at(y, start - 1)
            if not low:
                continue
            for end in range(m, 13):
                high = y_at(y, end)
                if high:
                    hit = (start, end, high, low)
                    break
            if hit:
                break
        if hit is None:
            print(f"  {p}: no ACEA figure — left out")
            done.add(p)
            continue
        start, end, high, low = hit
        vals, how = sub(high[0], low[0]), f"{high[1]} minus {low[1]}"
        inside = [_per(y, i) for i in range(start, end + 1)]
        for q in inside:
            if q in known:
                vals, how = sub(vals, known[q][0]), f"{how} minus {q} ({known[q][1]})"
        rest = [q for q in inside if q not in known]
        if len(rest) == 1:
            known[rest[0]] = (vals, how)
        else:
            spans.append({"from": rest[0], "to": rest[-1], "basis": "span", **vals,
                          "derivation": how})
        done.update(rest)
    rows = [{"from": p, "to": p, "basis": "month", **v, "derivation": how}
            for p, (v, how) in known.items()]
    rows += spans
    for r in rows:
        if any(r[f] < 0 for f in FUELS):
            raise SystemExit(f"{r['from']}..{r['to']}: negative count ({r['derivation']})")
    return sorted(rows, key=lambda r: r["from"])


def write(rows: list[dict], path: Path = OUT) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cache", type=Path, required=True, help="PDF cache dir")
    ap.add_argument("--to", required=True, help="last month, YYYY-MM")
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()
    args.cache.mkdir(parents=True, exist_ok=True)
    # A month's prior-year columns sit in next year's release, so read
    # releases up to a year past --to where they exist.
    y, m = int(args.to[:4]), int(args.to[5:])
    today = date.today()
    last = min(_per(y + 1, m), _per(today.year, today.month))
    releases = {}
    for p in _months(FIRST, last):
        got = pdf_for(p, args.cache)
        if got:
            releases[p] = got
    mon, ytd = collect(releases)
    rows = assemble(mon, ytd, FIRST, args.to)
    write(rows, args.out)
    print(f"{len(rows)} rows -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
