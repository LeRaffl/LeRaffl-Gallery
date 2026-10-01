#!/usr/bin/env python3
"""
Backfill data/Italy_Vans.csv from every UNRAE LCV "Struttura del mercato" PDF.

fetch_italy.py only reads the latest LCV PDF, and only the post-2025 layout
(which has a monthly column).  This script walks the whole UNRAE index,
downloads every immatricolazioni-veicoli-commerciali-* PDF and rebuilds the
monthly series:

  1. month column of the month's own table                (≥ 2025-02, and every January)
  2. comparison column of the next year's table            (fills unpublished months)
  3. YTD difference  Jan..M − Jan..M−1                     (≤ 2025-01: tables are YTD-only)
  4. YTD gap-fill    Jan..M+1 − month M+1 − Jan..M−1       (M's own PDF is missing)

For 3, all pairings of own-year and comparison-year YTD tables are tried and
the one whose TOTAL is closest to UNRAE's published monthly total wins; a
derived month more than 2 % off that total, or with any negative count, is
left out.  Differencing two bulletins folds late registrations into the month
(typically < 0,3 % of TOTAL); every derived row says so in `notes`.

Gaps that remain: months before 2017-05, June/July 2017–2021 and 2023
July/August (UNRAE publishes those as one Jan..August table), 2020-09..12
and 2021-10 (no table, or every derivation > 2 % off), and 2025-11/12 (pages without PDF; fetch_italy.py fills these from the
2026-11/12 comparison columns).  Fuel splits before 2018-05 come only from
2018 comparison columns; PDFs before then list totals only.

Usage
-----
    python scripts/backfill_italy_vans.py --dry-run
    python scripts/backfill_italy_vans.py               # add missing months
    python scripts/backfill_italy_vans.py --overwrite   # also replace existing rows
    python scripts/backfill_italy_vans.py --cache-dir /tmp/lcv   # keep PDFs
"""
import argparse
import re
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import fetch_italy as fi  # noqa: E402

CSV = fi.VARIANT_CONFIG["Vans"]["csv"]
_MAX_PAGE = re.compile(r'href="[^"]*immatricolazioni[^"]*[?&](?:page|p)=(\d+)[^"]*"', re.I)
_TOTALS_HEAD = re.compile(r"^\s*mese\s+(\d{4})\s+(\d{4})")
_TOTALS_ROW  = re.compile(r"^\s*([a-z]+)\s+([\d.]+)\s+([\d.]+)")

NOTE_YTD = ("derived: UNRAE Jan-M minus Jan-(M-1) totals (YTD-only table); "
            "late registrations of earlier months land here")
NOTE_GAP = "derived: Jan-(M+1) minus month M+1 minus Jan-(M-1); no UNRAE table for M"
NOTE_NO_PHEV = "PHEV not split out in the source; HEV covers all hybrids"
MAX_TOTAL_DEV = 0.02


def discover(throttle: float) -> list[str]:
    """Every LCV struttura page on the paginated UNRAE index, oldest first."""
    html = fi.http_get(fi.STRUTTURA_INDEX)
    pages = set(fi.find_lcv_pages(html))
    last = max((int(n) for n in _MAX_PAGE.findall(html)), default=1)
    for n in range(2, last + 1):
        print(f"  index page {n}/{last}", end="\r", flush=True)
        pages.update(fi.find_lcv_pages(fi.http_get(f"{fi.STRUTTURA_INDEX}?page={n}")))
        time.sleep(throttle)
    print()
    return sorted(pages, key=lambda u: int(u.split("/")[-2]))


def parse_monthly_totals(text: str) -> dict[tuple[int, int], int]:
    """UNRAE's own 'mese | YYYY | YYYY' monthly total tables (page 1)."""
    out: dict[tuple[int, int], int] = {}
    lines = text.splitlines()
    for i, ln in enumerate(lines):
        head = _TOTALS_HEAD.match(ln)
        if not head:
            continue
        y1, y2 = int(head.group(1)), int(head.group(2))
        for row in lines[i + 1:i + 16]:
            if row.strip().startswith("Totale"):
                break
            m = _TOTALS_ROW.match(row)
            if m and m.group(1) in fi.IT_MONTHS:
                mo = fi.IT_MONTHS[m.group(1)]
                out[(y1, mo)] = int(m.group(2).replace(".", ""))
                out[(y2, mo)] = int(m.group(3).replace(".", ""))
    return out


def _sub(a: dict, b: dict) -> dict:
    return {k: None if a[k] is None or b[k] is None else a[k] - b[k] for k in fi.LCV_FUELS}


def assemble(texts: list[str]) -> dict[str, tuple[dict, str]]:
    """{period: (fuels, notes)} from PDF texts given oldest first."""
    own, cmp_, ytd, cytd = {}, {}, {}, {}
    official: dict[tuple[int, int], int] = {}
    for text in texts:
        official.update(parse_monthly_totals(text))      # later PDFs win (consolidated)
        for t in fi.parse_lcv_struttura(text):
            y, m, cy = t["year"], t["month"], t["cmp_year"]
            ytd[(y, m)] = t["ytd_cur"]
            cytd[(cy, m)] = t["ytd_cmp"]
            if t["month_cur"] is not None:
                own[(y, m)] = t["month_cur"]
                cmp_[(cy, m)] = t["month_cmp"]

    zero = {k: 0 for k in fi.LCV_FUELS}

    def valid(f: dict, key: tuple[int, int]) -> float | None:
        """Relative TOTAL deviation from UNRAE's monthly total, or None if unusable."""
        if any(v is not None and v < 0 for v in f.values()) or key not in official:
            return None
        dev = abs(f["TOTAL"] - official[key]) / official[key]
        return dev if dev <= MAX_TOTAL_DEV else None

    def ytd_at(y: int, m: int) -> list[dict]:
        if m == 0:
            return [zero]
        return [d[(y, m)] for d in (cytd, ytd) if (y, m) in d]

    def published(y: int, m: int) -> dict | None:
        return own.get((y, m)) or cmp_.get((y, m))

    series: dict[str, tuple[dict, str]] = {}
    years = sorted({y for y, _ in list(ytd) + list(cytd)})
    for y in years:
        for m in range(1, 13):
            if (y, m) in own:
                f, note = own[(y, m)], ""
            elif (y, m) in cmp_:
                f, note = cmp_[(y, m)], fi.PRIOR_YEAR_NOTE
            else:
                cands = [(_sub(a, b), NOTE_YTD)
                         for a in ytd_at(y, m) for b in ytd_at(y, m - 1)]
                nxt = published(y, m + 1) if m < 12 else None
                if nxt:
                    cands += [(_sub(_sub(a, nxt), b), NOTE_GAP)
                              for a in ytd_at(y, m + 1) for b in ytd_at(y, m - 1)]
                scored = [(valid(c, (y, m)), c, n) for c, n in cands]
                scored = [s for s in scored if s[0] is not None]
                if not scored:
                    continue
                _, f, note = min(scored, key=lambda s: s[0])
            if f["PHEV"] is None:
                note = "; ".join(x for x in (note, NOTE_NO_PHEV) if x)
            series[f"{y}-{m:02d}"] = (f, note)
    return series


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="Print rows, write nothing.")
    ap.add_argument("--overwrite", action="store_true", help="Replace rows already in the CSV.")
    ap.add_argument("--cache-dir", help="Keep downloaded PDFs here (re-used on the next run).")
    ap.add_argument("--throttle", type=float, default=0.5, help="Seconds between requests.")
    args = ap.parse_args()

    print("Discovering LCV struttura pages …")
    pages = discover(args.throttle)
    print(f"{len(pages)} pages.")

    tmp = None
    if args.cache_dir:
        cache = Path(args.cache_dir)
        cache.mkdir(parents=True, exist_ok=True)
    else:
        tmp = tempfile.TemporaryDirectory()
        cache = Path(tmp.name)

    texts = []
    for url in pages:
        pdf = cache / (url.rstrip("/").split("/")[-1] + ".pdf")
        if not pdf.exists():
            pdf_url = fi.find_lcv_pdf_url(fi.http_get(url))
            time.sleep(args.throttle)
            if pdf_url is None:
                print(f"  no PDF: {url}")
                continue
            fi.download_pdf(pdf_url, pdf)
            time.sleep(args.throttle)
        texts.append(fi.pdf_to_text(pdf))

    series = assemble(texts)
    print(f"{len(series)} months: {min(series)} .. {max(series)}")
    for period, (fuels, note) in sorted(series.items()):
        cols = fi.lcv_to_cols(fuels)
        fi.sanity_check(cols, period, strict=True)
        line = " ".join(f"{k}={v}" for k, v in cols.items())
        if args.dry_run:
            print(f"  {period} {line}  [{note}]")
            continue
        if fi.csv_has_period(CSV, period, "Vans") and not args.overwrite:
            continue
        status, _ = fi.upsert(CSV, period, cols, "Vans", notes=note)
        print(f"  {period} {status}: {line}")
    if tmp:
        tmp.cleanup()


if __name__ == "__main__":
    main()
