#!/usr/bin/env python3
"""
Fetch South Africa's quarterly new-vehicle drivetrain split from naamsa and
update data/South Africa.csv.

Usage
-----
    python scripts/fetch_south_africa.py [--backfill] [--force] [--dry-run]
                                         [--from-dir DIR] [--dump-dir DIR]
                                         [--github-output PATH] [--summary PATH]

* (default)    Read the newest naamsa "Quarterly Review of Business Conditions"
               PDFs (the newest REPORTS_PER_RUN) and upsert their quarters.
* --backfill   Read every review the naamsa media library lists, oldest
               first, and also write the BOOTSTRAP_ROWS (yearly 2021/2022,
               see below).
* --force      Overwrite rows with a foreign `source` and skip the
               completeness guard.
* --dry-run    Fetch, validate and print; write nothing.
* --from-dir   Read PDFs from DIR instead of the network (offline rebuild).
* --dump-dir   Save every PDF the run downloads (for --from-dir).

Invoked by .github/workflows/fetch-south-africa.yml. Full method, governance
and a debugging runbook: docs/architecture/56-source-south-africa.md.

Data source and scope (read this before using the numbers)
----------------------------------------------------------
naamsa (the Automotive Business Council) publishes every quarter a
"Quarterly Review of Business Conditions" PDF. Section "New energy vehicle
[NEV] sales" carries a table

    Traditional hybrid / Plug-in hybrid / Electric / Total NEVs
    by year (2019/2020 .. last year) and for the quarter + the same quarter
    a year earlier,

and section 7 states the quarter's aggregate new passenger car sales and
aggregate commercial vehicle sales (and the year-ago figures).

The NEV table is **all new vehicles**, not passenger cars: naamsa relates it
to "total new vehicle sales" (Q2-2026 review p.6: "NEV sales comprised 5,6%
of total new vehicle sales"), and the September 2026 media release says
electrification "is also beginning to extend beyond the passenger vehicle
market, with emerging adoption across the light and medium commercial vehicle
segments". naamsa's aggregate market = Passenger cars + Light commercial
vehicles < 3,501 kg (bakkies and minibuses) + Medium CV 3,501-8,500 kg +
Heavy CV 8,501-16,500 kg + Extra-heavy CV > 16,500 kg + Buses > 8,500 kg.
Motorcycles are not part of naamsa's statistics. No passenger-only (M1) or
per-model drivetrain split is published, so the series is the **total new
vehicle market**, not EU M1, and nothing is reclassified by us.

Mapping: Electric -> BEV, Plug-in hybrid -> PHEV, Traditional hybrid -> HEV,
TOTAL = passenger + commercial aggregate sales of the quarter,
ICE = TOTAL - BEV - PHEV - HEV (one bucket: naamsa gives no petrol/diesel
split; the USA convention). Rows sit on the quarter's middle month with
time_interval = quarterly (Canada/Georgia convention).

Restatements: every review repeats the year-ago quarter, often revised. The
newest review wins; a revised row from this same source is overwritten (and
listed in the step summary).

Known source defect: the Q4-2025 review prints the Plug-in and Traditional
hybrid values of its two *quarter* columns in each other's rows (annual
columns are right). A quarter column is therefore reconciled against
"annual minus the other three quarters" when those are known; a PHEV/HEV swap
that reconciles exactly is undone (and reported), anything else aborts.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CSV_PATH = REPO / "data" / "South Africa.csv"
VARIANT = "Whole"
SOURCE = "naamsa.net"
FUELS = ["BEV", "PHEV", "HEV", "ICE"]
CSV_COLUMNS = ["period", "time_interval", "variant", "source", *FUELS, "TOTAL", "notes"]
MEDIA_API = "https://naamsa.net/wp-json/wp/v2/media"
REPORTS_PER_RUN = 2
# naamsa restates individual quarters by a few units; a year "adds up" when
# every fuel is within max(5 units, 0.5 % of the annual value).
TOLERANCE_UNITS = 5
TOLERANCE_SHARE = 0.005
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"}
NOTE_Q = "naamsa total new-vehicle market (cars+LCV+MCV+HCV+XHCV+buses), not M1"

# Rows no machine-readable review carries, written by --backfill only.
# Every number is quoted from a naamsa publication (see the source doc §4):
#  * NEV years 2021/2022: NEV table of every review since Q1-2025
#    (2021: PHEV 51 / HEV 627 / BEV 218; 2022: 122 / 4,070 / 502).
#  * TOTAL 2022 = 529,556: Flash Report Summary December 2023, "Dec 2022 YTD".
#  * TOTAL 2021 = 464,322: sum of the four segment histories in the Flash
#    Report Standard December 2025 (304,338 + 133,078 + 7,520 + 19,386).
BOOTSTRAP_ROWS = {
    "2021-06": ("yearly", {"BEV": 218, "PHEV": 51, "HEV": 627, "TOTAL": 464322},
                "annual figure at mid-year; " + NOTE_Q),
    "2022-06": ("yearly", {"BEV": 502, "PHEV": 122, "HEV": 4070, "TOTAL": 529556},
                "annual figure at mid-year; " + NOTE_Q),
}

QWORDS = {"first": 1, "second": 2, "third": 3, "fourth": 4}
ROW_LABELS = {"Plug-in hybrid": "PHEV", "Traditional hybrid": "HEV",
              "Electric": "BEV", "Total NEVs": "NEV"}


def num(s: str) -> int:
    return int(s.replace(",", "").replace(" ", ""))


def period_of(year: int, q: int) -> str:
    return f"{year}-{3 * q - 1:02d}"


# --------------------------------------------------------------------------
# Parsing one review (text from `pdftotext -layout`)
# --------------------------------------------------------------------------

SALES_RE = re.compile(
    r"(\d{4})\s+(First|Second|Third|Fourth)\s+quarter\s+aggregate\s+industry\s+new\s+"
    r"passenger\s+car\s+sales\s+at\s+([\d,]+)\s+units.*?compared\s+to\s+the\s+([\d,]+)\s+new\s+"
    r"passenger\s+cars.*?Aggregate\s+industry\s+commercial\s+vehicle\s+sales\s+during\s+the\s+"
    r"\S+\s+quarter\s+of\s+\d{4},\s+at\s+([\d,]+)\s+units.*?compared\s+to\s+the\s+([\d,]+)\s+units",
    re.S | re.I)
YEARS_RE = re.compile(r"(?<!\d)(20[12]\d)(?!\d)")


def parse_review(text: str) -> dict:
    """-> {"quarter": (y, q), "totals": {(y,q): int}, "nev": {(y,q): {...}},
           "annual": {year: {...}}}. Raises ValueError on a layout it does not know."""
    m = SALES_RE.search(text)
    if not m:
        raise ValueError("section-7 sales sentence not found")
    year, q = int(m.group(1)), QWORDS[m.group(2).lower()]
    cur, prev = (year, q), (year - 1, q)
    totals = {cur: num(m.group(3)) + num(m.group(5)),
              prev: num(m.group(4)) + num(m.group(6))}

    lines = text.splitlines()
    rows: dict[str, list[int]] = {}
    first_idx = None
    for i, line in enumerate(lines):
        s = line.strip()
        for lab, key in ROW_LABELS.items():
            if s.startswith(lab) and key not in rows:
                vals = re.findall(r"\d[\d,]*", s[len(lab):])
                if len(vals) >= 4:
                    rows[key] = [num(v) for v in vals]
                    if first_idx is None:
                        first_idx = i
    if set(rows) != set(ROW_LABELS.values()):
        raise ValueError(f"NEV table incomplete: {sorted(rows)}")
    n = {len(v) for v in rows.values()}
    if len(n) != 1:
        raise ValueError(f"NEV rows have different lengths: {n}")
    ncols = n.pop()
    # The year header: the nearest line above the table with >= 4 years.
    years: list[int] = []
    for j in range(first_idx - 1, max(first_idx - 12, -1), -1):
        ys = [int(y) for y in YEARS_RE.findall(lines[j])]
        head = ys[:ncols - 2]
        if len(head) == ncols - 2 and all(b == a + 1 for a, b in zip(head, head[1:])):
            years = head
            break
    n_annual = ncols - 2
    if len(years) < n_annual:
        raise ValueError(f"NEV year header not found ({years}, {ncols} columns)")
    years = years[:n_annual]
    for k in range(ncols):
        col = {f: rows[f][k] for f in ("BEV", "PHEV", "HEV")}
        if sum(col.values()) != rows["NEV"][k]:
            raise ValueError(f"NEV column {k}: {col} does not sum to {rows['NEV'][k]}")
    def col(k):  # noqa: E306
        return {f: rows[f][k] for f in ("BEV", "PHEV", "HEV")}
    annual = {y: col(k) for k, y in enumerate(years)}
    nev = {prev: col(ncols - 2), cur: col(ncols - 1)}
    return {"quarter": cur, "totals": totals, "nev": nev, "annual": annual}


# --------------------------------------------------------------------------
# Combining reviews
# --------------------------------------------------------------------------

def reconcile(quarters: dict, annual: dict, log: list[str]) -> None:
    """For every year with all four quarters and an annual column: if the
    quarters do not add up, try undoing a PHEV/HEV row swap in one quarter;
    a swap that makes the year add up (within the restatement tolerance) is applied (and logged). A
    remaining gap is only logged — naamsa restates annual figures by a few
    units. Mutates `quarters`."""
    F = ("BEV", "PHEV", "HEV")

    def ok(y):
        return all(abs(d) <= max(TOLERANCE_UNITS, TOLERANCE_SHARE * annual[y][f])
                   for f, d in gap(y).items())

    def gap(y):
        return {f: annual[y][f] - sum(quarters[(y, k)][f] for k in (1, 2, 3, 4)) for f in F}

    for y in sorted(annual):
        if not all((y, k) in quarters for k in (1, 2, 3, 4)):
            continue
        g = gap(y)
        if ok(y):
            continue
        fixed = False
        for k in (1, 2, 3, 4):
            v = quarters[(y, k)]
            swapped = {"BEV": v["BEV"], "PHEV": v["HEV"], "HEV": v["PHEV"]}
            quarters[(y, k)] = swapped
            if ok(y):
                log.append(f"{y}-Q{k}: PHEV/HEV printed in each other's rows "
                           f"({v['PHEV']}/{v['HEV']}) — swapped back, {y} now adds up "
                           f"to the annual column (residual {gap(y)})")
                fixed = True
                break
            quarters[(y, k)] = v
        if not fixed:
            log.append(f"{y}: quarters differ from the annual column by {g} — kept as published")


def build_rows(reviews: list[dict], log: list[str]) -> dict[str, dict]:
    """reviews oldest -> newest; newest value of a quarter wins."""
    nev: dict = {}
    totals: dict = {}
    annual: dict = {}
    for r in reviews:
        nev.update(r["nev"])
        totals.update(r["totals"])
        annual.update(r["annual"])
    reconcile(nev, annual, log)
    out = {}
    for key in sorted(nev):
        if key not in totals:
            log.append(f"{key[0]}-Q{key[1]}: no total market figure — skipped")
            continue
        v = dict(nev[key])
        v["TOTAL"] = totals[key]
        out[period_of(*key)] = ("quarterly", v, NOTE_Q)
    return out


def counts_of(v: dict) -> dict[str, int]:
    c = {f: v[f] for f in ("BEV", "PHEV", "HEV")}
    c["TOTAL"] = v["TOTAL"]
    c["ICE"] = v["TOTAL"] - c["BEV"] - c["PHEV"] - c["HEV"]
    if c["ICE"] < 0:
        raise ValueError(f"negative ICE: {v}")
    return c


def render_line(period: str, interval: str, v: dict, notes: str) -> str:
    c = counts_of(v)
    buf = io.StringIO()
    csv.writer(buf, lineterminator="").writerow(
        [period, interval, VARIANT, SOURCE] + [str(c[f]) for f in FUELS + ["TOTAL"]] + [notes])
    return buf.getvalue()


# --------------------------------------------------------------------------
# CSV (line-level upserts, invariant 2)
# --------------------------------------------------------------------------

def line_key(line: str) -> tuple[str, str]:
    row = next(csv.reader([line]))
    return row[0], row[2]


def upsert_lines(path: Path, updates: dict[str, str], force: bool) -> dict[str, list[str]]:
    header = ",".join(CSV_COLUMNS)
    lines: list[str] = []
    if path.exists():
        text = path.read_text(encoding="utf-8").split("\n")
        if text[0] != header:
            raise SystemExit(f"{path}: unexpected header {text[0]!r}")
        lines = [l for l in text[1:] if l.strip()]
    stats = {"added": [], "updated": [], "unchanged": [], "skipped": []}
    index = {line_key(l): i for i, l in enumerate(lines)}
    for period, new in sorted(updates.items()):
        key = (period, VARIANT)
        if key not in index:
            lines.append(new)
            stats["added"].append(period)
            continue
        old = lines[index[key]]
        if old == new:
            stats["unchanged"].append(period)
        elif next(csv.reader([old]))[3] != SOURCE and not force:
            stats["skipped"].append(period)
        else:
            lines[index[key]] = new
            stats["updated"].append(period)
    if stats["added"] or stats["updated"]:
        lines.sort(key=line_key)
        path.write_text("\n".join([header] + lines) + "\n", encoding="utf-8")
    return stats


def completeness(rows: dict, newest: str, log: list[str], force: bool) -> None:
    """The newest quarter's total must be within 25 % of the year-ago one."""
    y, m = int(newest[:4]), newest[5:]
    prev = f"{y - 1}-{m}"
    if prev not in rows or force:
        return
    a, b = rows[newest][1]["TOTAL"], rows[prev][1]["TOTAL"]
    ratio = a / b
    if ratio < 0.75:
        raise SystemExit(f"completeness guard: {newest} total {a} is {ratio:.0%} of {prev} ({b})")
    if ratio < 0.9:
        log.append(f"warning: {newest} total is {ratio:.0%} of the year-ago quarter")


# --------------------------------------------------------------------------
# Network / files
# --------------------------------------------------------------------------

def list_reviews() -> list[str]:
    import requests
    urls: set[str] = set()
    for term in ("Review of Business Conditions", "Quarterly Review"):
        for page in range(1, 4):
            r = requests.get(MEDIA_API, params={"search": term, "per_page": 100, "page": page},
                             headers=UA, timeout=60)
            if r.status_code != 200:
                break
            items = r.json()
            for it in items:
                u = it.get("source_url", "")
                if u.lower().endswith(".pdf") and "review" in u.lower():
                    urls.add(u)
            if len(items) < 100:
                break
    # One file per upload date (naamsa re-uploads signed/_E/-1 copies).
    by_date: dict[str, str] = {}
    for u in sorted(urls):
        name = u.rsplit("/", 1)[-1]
        d = name[:8]
        if not d.isdigit():
            continue
        if d not in by_date or len(name) < len(by_date[d].rsplit("/", 1)[-1]):
            by_date[d] = u
    return [by_date[d] for d in sorted(by_date)]


NAME_Q_RE = re.compile(r"(?:Q|Quarter-)([1-4])|([1-4])(?:st|nd|rd|th)-Quarter", re.I)


def quarter_from_name(name: str) -> tuple[int, int] | None:
    """'20260820-naamsa-2nd-Quarter-2026-Review...' -> (2026, 2). The year is
    the last 4-digit year in the name after the upload date (Q4 reviews are
    uploaded in the next year)."""
    stem = name.rsplit("/", 1)[-1][9:]
    m = NAME_Q_RE.search(stem)
    years = re.findall(r"(?<!\d)(20[12]\d)(?!\d)", stem)
    if not m or not years:
        return None
    return int(years[-1]), int(m.group(1) or m.group(2))


def already_have(period: str) -> bool:
    if not CSV_PATH.exists():
        return False
    with CSV_PATH.open(encoding="utf-8", newline="") as fh:
        return any(r["period"] == period and r["source"] == SOURCE for r in csv.DictReader(fh))


def pdf_text(data: bytes) -> str:
    with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
        f.write(data)
        f.flush()
        return subprocess.run(["pdftotext", "-layout", f.name, "-"], check=True,
                              capture_output=True).stdout.decode("utf-8", "replace")


class SelfThrottle(Exception):
    pass


def load_reviews(args, log: list[str]) -> list[dict]:
    if args.from_dir:
        files = sorted(Path(args.from_dir).glob("*.pdf"))
        blobs = [(p.name, p.read_bytes()) for p in files]
    else:
        import requests
        urls = list_reviews()
        if not urls:
            raise SystemExit("naamsa media library lists no quarterly review — layout change?")
        if not args.backfill:
            urls = urls[-REPORTS_PER_RUN:]
            q = quarter_from_name(urls[-1])
            if q and already_have(period_of(*q)) and not args.force:
                print(f"self-throttle: newest review ({urls[-1].rsplit('/', 1)[-1]}) is "
                      f"{q[0]}-Q{q[1]}, already in the CSV — nothing to do")
                raise SelfThrottle()
        blobs = []
        for u in urls:
            r = requests.get(u, headers=UA, timeout=120)
            r.raise_for_status()
            blobs.append((u.rsplit("/", 1)[-1], r.content))
            if args.dump_dir:
                Path(args.dump_dir).mkdir(parents=True, exist_ok=True)
                (Path(args.dump_dir) / blobs[-1][0]).write_bytes(r.content)
    reviews = []
    for name, data in sorted(blobs):
        try:
            try:
                text = pdf_text(data)
            except subprocess.CalledProcessError as e:
                raise ValueError(f"pdftotext failed ({e.returncode})") from e
            rv = parse_review(text)
            rv["file"] = name
            reviews.append(rv)
        except ValueError as e:
            log.append(f"{name}: not parsed ({e}) — scanned or new layout")
    if not reviews:
        raise SystemExit("no review could be parsed")
    return sorted(reviews, key=lambda r: r["quarter"])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--backfill", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--from-dir")
    ap.add_argument("--dump-dir")
    ap.add_argument("--github-output", default=os.environ.get("GITHUB_OUTPUT"))
    ap.add_argument("--summary", default=os.environ.get("GITHUB_STEP_SUMMARY"))
    args = ap.parse_args(argv)

    log: list[str] = []
    try:
        reviews = load_reviews(args, log)
    except SelfThrottle:
        if args.github_output:
            with open(args.github_output, "a") as fh:
                fh.write("changed=false\nchanged_variants=[]\n")
        return 0
    rows = build_rows(reviews, log)
    newest = max(rows)
    completeness(rows, newest, log, args.force)
    if args.backfill:
        for p, r in BOOTSTRAP_ROWS.items():
            rows.setdefault(p, r)
    lines = {p: render_line(p, iv, v, nt) for p, (iv, v, nt) in rows.items()}

    table = ["| period | BEV | PHEV | HEV | ICE | TOTAL | BEV % |", "|---|---|---|---|---|---|---|"]
    for p in sorted(rows):
        c = counts_of(rows[p][1])
        table.append(f"| {p} | {c['BEV']} | {c['PHEV']} | {c['HEV']} | {c['ICE']} | {c['TOTAL']} "
                     f"| {100 * c['BEV'] / c['TOTAL']:.2f} |")
    print("\n".join(table))
    for l in log:
        print("NOTE:", l)

    stats = {"added": [], "updated": [], "unchanged": [], "skipped": []}
    if not args.dry_run:
        stats = upsert_lines(CSV_PATH, lines, args.force)
    print(json.dumps(stats))
    changed = bool(stats["added"] or stats["updated"])
    if args.github_output:
        with open(args.github_output, "a") as fh:
            fh.write(f"changed={'true' if changed else 'false'}\n")
            fh.write(f"changed_variants={json.dumps([VARIANT] if changed else [])}\n")
    if args.summary:
        with open(args.summary, "a") as fh:
            fh.write("## South Africa (naamsa quarterly review)\n\n")
            fh.write("Reviews read: " + ", ".join(r["file"] for r in reviews) + "\n\n")
            fh.write("\n".join(table) + "\n\n")
            for k, v in stats.items():
                if v:
                    fh.write(f"- **{k}**: {', '.join(v)}\n")
            for l in log:
                fh.write(f"- ⚠ {l}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
