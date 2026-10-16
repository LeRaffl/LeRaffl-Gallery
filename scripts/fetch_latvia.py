#!/usr/bin/env python3
"""
Fetch Latvia's first registrations from CSDD (Ceļu satiksmes drošības
direkcija, the Road Traffic Safety Directorate that keeps the vehicle
register) and upsert data/Latvia*.csv (Whole, Private, Industry, Used, Vans,
HDV, Buses).

Source (free, no login)
-----------------------
CSDD's statistics page "Transportlīdzekļu dati, atjaunoti biežāk nekā reizi
gadā" (https://www.csdd.lv/transportlidzekli/transportlidzeklu-ikmenesa-dati)
offers XLSX workbooks that CSDD replaces every month (about ten working days
after month end), each with the full history. Three are read:

1. **"Pirmoreiz reģistrēto TL skaits"** (~50 KB) — the headline table: first
   registrations per month for cars ("Vieglie"), lorries ("Kravas") and buses
   ("Autobusi"). Read first: it says whether the month is out (so the large
   files are only downloaded when there is something new) and it is the
   cross-check for the other two.
2. **"Pirmoreiz reģistrēto vieglo automobiļu skaits"** (~70 MB) — sheet DATI:
   every passenger car first registered in Latvia since 2000, aggregated to
   one row per year × month × make × model × model year × fuel × status
   (JAUNS: Jauns = new, Lietots = used, "180 dienas") × keeper type
   (TURETAJS: FP natural person / JP legal person) with a count (KOPAA).
3. **"Pirmoreiz reģistrēto autobusu un kravas automobiļu skaits"** (~25 MB) —
   sheet DATI: the same for lorries and buses, with the EU category
   (KATEGORIJA) and the energy source (ENERGIJAS_AVOTS).

Record → CSV
------------
  Whole     cars file, status Jauns                      (new passenger cars)
  Private   Whole, keeper type FP                       (natural person)
  Industry  Whole, keeper type JP                       (legal person)
  Used      cars file, status Lietots or "180 dienas"  (first registered
                                                         abroad before)
  Vans      lorry file, new, EU N1 + N1G
  HDV       lorry file, new, EU N2 + N3 (+ G)
  Buses     lorry file, new, EU M2 + M3 (+ G)

Powertrain (the register's fuel / energy field):
  Elektrība                                   → BEV
  Elektrība un benzīns / … un dīzeļdegviela   → PHEV  (plug-in hybrids: the
                                                       register files full and
                                                       mild hybrids under their
                                                       fuel — a Toyota Prius is
                                                       Benzīns)
  Benzīns                                     → PETROL (incl. HEV / MHEV)
  Dīzeļdegviela                               → DIESEL (incl. MHEV)
  LPG, CNG, Ūdeņradis (hydrogen), Neuzdots    → OTHERS
HEV is not reported: the column stays empty ("not published", never 0) —
the same as ACEA's Latvian figure, which this source reproduces to the car
(§4 of the source doc).

Governance (every real run)
---------------------------
* each file must be found on the page by its label, each sheet with its
  header (schema drift aborts);
* unknown fuel / status / keeper values above 2 % of a variant-month abort;
* cross-check: all first-registered cars of the month (every status) =
  the headline "Vieglie", lorries N1–N3 = "Kravas", buses M2+M3 =
  "Autobusi" — off by more than 0.5 % (and 3 vehicles) aborts;
* completeness: a month below 25 % of the trailing-12 median is not written,
  below 50 % is written with a warning;
* rows from a foreign source other than ACEA are never overwritten without
  --force.

Network: www.csdd.lv does not answer GitHub's hosted runners (connect
timeout, 2026-10-16), so the workflow routes every request through the
project's Cloudflare Worker fetch relay — LATVIA_FETCH_RELAY, the base URL
`https://<worker-host>/fetch?url=` the target is appended to (url-encoded),
gated by LATVIA_RELAY_TOKEN (sent as X-Relay-Token). Unset → direct, which
works from a normal network.

CSDD restates recent months by a car or two when late registrations are
booked, so a normal run rewrites the last 13 months (line-level upsert: only
lines that changed are touched).

Usage
-----
  python scripts/fetch_latvia.py                 # normal run (last month)
  python scripts/fetch_latvia.py --backfill      # every month from 2015-01
  python scripts/fetch_latvia.py --from-dir DIR  # offline: DIR/{headline,cars,lorries}.xlsx

Docs: docs/architecture/58-source-latvia.md (method, validation, runbook).
"""
from __future__ import annotations

import argparse
import collections
import csv
import datetime as dt
import html
import io
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import quote

SCRIPTS = Path(__file__).resolve().parent
REPO = SCRIPTS.parent
sys.path.insert(0, str(SCRIPTS))
import market_top  # noqa: E402

SOURCE = "CSDD"
REPLACEABLE = {"ACEA"}            # the legacy writer this source supersedes
FIRST_PERIOD = "2015-01"          # where data/Latvia.csv (ACEA monthly) starts
RECENT_MONTHS = 13                # a normal run rewrites this many months
PAGE_URL = "https://www.csdd.lv/transportlidzekli/transportlidzeklu-ikmenesa-dati"
BASE_URL = "https://www.csdd.lv"
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"}

# file key → link label on the statistics page (whitespace-normalised)
FILE_LABELS = {
    "headline": "Pirmoreiz reģistrēto TL skaits",
    "cars": "Pirmoreiz reģistrēto vieglo automobiļu skaits",
    "lorries": "Pirmoreiz reģistrēto autobusu un kravas automobiļu skaits",
}

VARIANT_CSV = {
    "Whole": "data/Latvia.csv",
    "Private": "data/Latvia_Private.csv",
    "Industry": "data/Latvia_Industry.csv",
    "Used": "data/Latvia_Used.csv",
    "Vans": "data/Latvia_Vans.csv",
    "HDV": "data/Latvia_HDV.csv",
    "Buses": "data/Latvia_Buses.csv",
}
COLUMNS = ["BEV", "PHEV", "HEV", "PETROL", "DIESEL", "OTHERS"]
COUNTED = ["BEV", "PHEV", "PETROL", "DIESEL", "OTHERS"]   # HEV: not reported

FUEL_CLASS = {
    "elektrība": "BEV",
    "elektrība un benzīns": "PHEV",
    "elektrība un dīzeļdegviela": "PHEV",
    "benzīns": "PETROL",
    "dīzeļdegviela": "DIESEL",
    "sašķidrinātā gāze (lpg)": "OTHERS",
    "saspiestā gāze (cng)": "OTHERS",
    "ūdeņradis": "OTHERS",
    "neuzdots": "OTHERS",
}
STATUS_NEW = "jauns"
STATUS_USED = {"lietots", "180 dienas"}
KEEPER_PRIVATE, KEEPER_LEGAL = "FP", "JP"

CATEGORY_VARIANT = {
    "N1": "Vans", "N1G": "Vans",
    "N2": "HDV", "N2G": "HDV", "N3": "HDV", "N3G": "HDV",
    "M2": "Buses", "M2G": "Buses", "M3": "Buses", "M3G": "Buses",
}
LORRY = {"N1", "N1G", "N2", "N2G", "N3", "N3G"}
BUS = {"M2", "M2G", "M3", "M3G"}

MAX_UNKNOWN_SHARE = 0.02
XCHECK_TOL = 0.005
XCHECK_MIN = 3
MIN_MONTH_FRACTION = 0.25
WARN_MONTH_FRACTION = 0.50
TOP_SLUG = "latvia"
USED_TOP_SLUG = "latvia_used"

NOTES = {
    "Whole": "new passenger cars by the register's fuel field",
    "Private": "new passenger cars, keeper a natural person (FP)",
    "Industry": "new passenger cars, keeper a legal person (JP)",
    "Used": "passenger cars first registered abroad before (Lietots + 180 dienas)",
    "Vans": "new N1 + N1G by energy source",
    "HDV": "new N2 + N3 (incl. G) by energy source",
    "Buses": "new M2 + M3 (incl. G) by energy source",
}


# ── values ─────────────────────────────────────────────────────────────────

def key(x) -> str:
    return " ".join(str(x or "").split()).casefold()


def fuel_class(fuel) -> str | None:
    """Register fuel / energy value → CSV column (None = unknown value)."""
    return FUEL_CLASS.get(key(fuel))


def num(x) -> int:
    if x is None or x == "":
        return 0
    if isinstance(x, (int, float)):
        return int(round(x))
    s = re.sub(r"[\s\xa0]", "", str(x))
    return int(float(s)) if s else 0


def period_of(year, month) -> str | None:
    try:
        y, m = int(year), int(month)
    except (TypeError, ValueError):
        return None
    return f"{y}-{m:02d}" if 1990 < y < 2100 and 1 <= m <= 12 else None


# ── workbooks ──────────────────────────────────────────────────────────────

def open_book(blob: bytes):
    import openpyxl
    return openpyxl.load_workbook(io.BytesIO(blob), read_only=True, data_only=True)


def iter_dati(blob: bytes, need: list[str]):
    """Rows of the DATI sheet as dicts of the `need` columns (by header name)."""
    wb = open_book(blob)
    name = next((n for n in wb.sheetnames if n.strip().upper() == "DATI"), None)
    if name is None:
        raise ValueError(f"no DATI sheet (sheets: {wb.sheetnames})")
    it = wb[name].iter_rows(values_only=True)
    header = [str(c or "").strip().upper() for c in next(it)]
    missing = [c for c in need if c not in header]
    if missing:
        raise ValueError(f"DATI header lacks {missing} (has {header})")
    idx = {c: header.index(c) for c in need}
    for r in it:
        if r and any(v is not None for v in r):
            yield {c: (r[i] if i < len(r) else None) for c, i in idx.items()}


def parse_headline(blob: bytes) -> dict[str, dict[str, int]]:
    """Headline workbook → {period: {"cars", "lorries", "buses"}}. Each sheet
    holds one block per year: a title "… YYYY. GADA MĒNEŠOS", a row of month
    names, then one row per vehicle group with the twelve months."""
    wb = open_book(blob)
    out: dict[str, dict[str, int]] = collections.defaultdict(dict)
    labels = {"vieglie": "cars", "kravas": "lorries", "autobusi": "buses"}
    months = ["janvāris", "februāris", "marts", "aprīlis", "maijs", "jūnijs", "jūlijs",
              "augusts", "septembris", "oktobris", "novembris", "decembris"]
    for ws in wb.worksheets:
        year, cols = None, None
        for r in ws.iter_rows(values_only=True):
            if not r:
                continue
            first = str(r[0] or "")
            t = re.search(r"(\d{4})\.\s*GADA", first.upper())
            if t:
                year, cols = int(t.group(1)), None
                continue
            cells = [key(c) for c in r]
            if "janvāris" in cells:
                # the month columns start where the names do (column B in the
                # history sheet, column C in the current-year sheet)
                cols = {i + 1: cells.index(mn) for i, mn in enumerate(months) if mn in cells}
                continue
            grp = labels.get(key(first))
            if year is None or cols is None or grp is None:
                continue
            for m, c in cols.items():
                v = r[c] if c < len(r) else None
                if v not in (None, "") and num(v) > 0:
                    out[f"{year}-{m:02d}"][grp] = num(v)
    if not out:
        raise ValueError("headline workbook: no 'YYYY. GADA MĒNEŠOS' block found")
    return dict(out)


def zero() -> dict[str, int]:
    return {k: 0 for k in COUNTED}


def display_brand(mark) -> str:
    b = market_top.clean(mark)
    return {"VW": "VOLKSWAGEN", "MERCEDES BENZ": "MERCEDES-BENZ", "BMW I": "BMW"}.get(b, b)


def display_model(brand: str, model) -> str:
    m = market_top.clean(model)
    if m in ("", "-"):
        return "(unnamed)"
    return market_top.strip_brand(brand, m)


def build_months(cars: bytes, lorries: bytes, headline: dict, periods: set[str]) -> dict:
    """The two record workbooks → {period: {"rows": {variant: counts},
    "units": {...}, "used_units": {...}, "checks": [...], "unknown": {...}}}."""
    months = {p: {"rows": {v: zero() for v in VARIANT_CSV},
                  "units": collections.Counter(), "used_units": collections.Counter(),
                  "unknown": collections.defaultdict(lambda: [0, set()]),
                  "first_cars": 0, "first_lorries": 0, "first_buses": 0}
              for p in periods}
    for rec in iter_dati(cars, ["GADS", "MENESIS", "MARKA", "MODELIS", "DEGVIELA",
                                "JAUNS", "TURETAJS", "KOPAA"]):
        p = period_of(rec["GADS"], rec["MENESIS"])
        if p not in months:
            continue
        m, n = months[p], num(rec["KOPAA"])
        m["first_cars"] += n
        cls = fuel_class(rec["DEGVIELA"])
        status = key(rec["JAUNS"])
        v = "Whole" if status == STATUS_NEW else "Used" if status in STATUS_USED else None
        if v is None:
            m["unknown"]["Whole"][0] += n
            m["unknown"]["Whole"][1].add(f"status {rec['JAUNS']}")
            continue
        if cls is None:
            m["unknown"][v][0] += n
            m["unknown"][v][1].add(f"fuel {rec['DEGVIELA']}")
            cls = "OTHERS"
        m["rows"][v][cls] += n
        brand = display_brand(rec["MARKA"])
        unit = (cls, brand, display_model(brand, rec["MODELIS"]))
        if v == "Whole":
            m["units"][unit] += n
            keeper = str(rec["TURETAJS"] or "").strip().upper()
            if keeper not in (KEEPER_PRIVATE, KEEPER_LEGAL):
                m["unknown"]["Private"][0] += n
                m["unknown"]["Private"][1].add(f"keeper {rec['TURETAJS']}")
            m["rows"]["Private" if keeper == KEEPER_PRIVATE else "Industry"][cls] += n
        else:
            m["used_units"][unit] += n
    for rec in iter_dati(lorries, ["GADS", "MENESIS", "KATEGORIJA", "ENERGIJAS_AVOTS",
                                   "JAUNS", "KOPAA"]):
        p = period_of(rec["GADS"], rec["MENESIS"])
        if p not in months:
            continue
        m, n = months[p], num(rec["KOPAA"])
        cat = str(rec["KATEGORIJA"] or "").strip().upper()
        if cat in LORRY:
            m["first_lorries"] += n
        elif cat in BUS:
            m["first_buses"] += n
        v = CATEGORY_VARIANT.get(cat)
        if v is None or key(rec["JAUNS"]) != STATUS_NEW:
            continue
        cls = fuel_class(rec["ENERGIJAS_AVOTS"])
        if cls is None:
            m["unknown"][v][0] += n
            m["unknown"][v][1].add(f"fuel {rec['ENERGIJAS_AVOTS']}")
            cls = "OTHERS"
        m["rows"][v][cls] += n

    out = {}
    for p, m in months.items():
        for r in m["rows"].values():
            r["TOTAL"] = sum(r[k] for k in COUNTED)
        h = headline.get(p, {})
        checks = [
            ("first-registered passenger cars (DATI vs headline Vieglie)", m["first_cars"], h.get("cars")),
            ("first-registered lorries N1-N3 (DATI vs headline Kravas)", m["first_lorries"], h.get("lorries")),
            ("first-registered buses M2-M3 (DATI vs headline Autobusi)", m["first_buses"], h.get("buses")),
        ]
        out[p] = {"rows": m["rows"], "units": dict(m["units"]),
                  "used_units": dict(m["used_units"]), "checks": checks,
                  "unknown": {v: (n, sorted(l)) for v, (n, l) in m["unknown"].items()}}
    return out


def check_failures(checks, hard_only: bool = True) -> list[str]:
    """Cross-checks off by more than max(3, 0.5 %). Only the passenger-car
    check is hard: CSDD's headline "Kravas" also counts lorry types outside
    N1–N3 and books some vehicles in another month (−1 … −15 %), and
    "Autobusi" differs by a few buses — those two are reported, not enforced."""
    bad = []
    for label, got, ref in (checks[:1] if hard_only else checks):
        if ref is None:
            continue
        if abs(got - ref) > max(XCHECK_MIN, XCHECK_TOL * ref):
            bad.append(f"{label}: {got} vs {ref}")
    return bad


# ── CSV line-level upsert (invariant 2) ────────────────────────────────────

def csv_columns() -> list[str]:
    return ["period", "time_interval", "variant", "source"] + COLUMNS + ["TOTAL", "notes"]


def fmt(v: int) -> str:
    return f"{float(v):.1f}"


def render_line(period: str, variant: str, counts: dict[str, int], notes: str) -> str:
    buf = io.StringIO()
    vals = ["" if k == "HEV" else fmt(counts[k]) for k in COLUMNS]
    csv.writer(buf, lineterminator="").writerow(
        [period, "monthly", variant, SOURCE] + vals + [fmt(counts["TOTAL"]), notes])
    return buf.getvalue()


def parse_line(line: str) -> list[str]:
    return next(csv.reader([line]))


def upsert_lines(path: Path, updates: dict[tuple[str, str], str], force: bool) -> dict[str, int]:
    """Replace/insert only the given (period, variant) lines; every other line
    is written back byte for byte. New lines go in period order."""
    columns = csv_columns()
    if path.exists():
        raw = path.read_bytes().decode("utf-8")
        eol = "\r\n" if "\r\n" in raw else "\n"
        lines = raw.splitlines()
        header, lines = (lines[0], lines[1:]) if lines else (",".join(columns), [])
    else:
        header, lines, eol = ",".join(columns), [], "\n"
    if header.split(",") != columns:
        sys.exit(f"{path}: unexpected header {header!r} (expected {columns})")
    stats = {"added": 0, "updated": 0, "unchanged": 0, "skipped": 0}
    index = {(f[0], f[2]): i for i, f in enumerate(parse_line(l) for l in lines)}
    for k, new in sorted(updates.items()):
        if k in index:
            old = lines[index[k]]
            src = parse_line(old)[3].strip()
            if old == new:
                stats["unchanged"] += 1
            elif src != SOURCE and src not in REPLACEABLE and not force:
                stats["skipped"] += 1
                print(f"  {path.name} {k[0]}: kept (foreign source {src!r}; --force overrides)")
            else:
                lines[index[k]] = new
                stats["updated"] += 1
        else:
            pos = len(lines)
            for i, l in enumerate(lines):
                f = parse_line(l)
                if (f[0], f[2]) > k:
                    pos = i
                    break
            lines.insert(pos, new)
            index = {(f[0], f[2]): i for i, f in enumerate(parse_line(l) for l in lines)}
            stats["added"] += 1
    if stats["added"] or stats["updated"]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((eol.join([header] + lines) + eol).encode("utf-8"))
    return stats


def existing_rows(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    with open(path, newline="", encoding="utf-8") as f:
        return {r["period"]: r for r in csv.DictReader(f)}


def acea_note(old: dict | None, counts: dict[str, int]) -> str:
    """When an ACEA row is replaced, keep ACEA's figure in the note when it
    differs (the correction trail: ACEA stays the cross-check)."""
    if not old or (old.get("source") or "").strip().upper() != "ACEA":
        return ""
    if old.get("time_interval") != "monthly" or not old.get("TOTAL"):
        return f"; replaces ACEA {old.get('time_interval')} row"
    diffs = []
    for k in COUNTED + ["TOTAL"]:
        a = int(round(float(old[k]))) if old.get(k) else 0
        if a != counts[k]:
            diffs.append(f"{k} {a}")
    if not diffs:
        return "; = ACEA"
    a = int(round(float(old["TOTAL"])))
    return f"; replaces ACEA (TOTAL {a}, {counts['TOTAL'] - a:+d}; ACEA had " + " / ".join(diffs) + ")"


# ── network ────────────────────────────────────────────────────────────────

def relayed(url: str, relay: str) -> str:
    """The URL to request: through the fetch relay when one is set (the target
    url-encoded onto its base, as the Worker's /fetch?url= expects)."""
    return relay + quote(url, safe="") if relay else url


def find_files(page: str) -> dict[str, str]:
    """Statistics page → {file key: url} for the three workbooks, matched by
    the visible link text (the URLs are opaque ...&xi=N indexes)."""
    out = {}
    page = re.sub(r"<(style|script)\b.*?</\1>", " ", page, flags=re.S | re.I)
    for m in re.finditer(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', page, re.S):
        text = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", m.group(2))).split())
        text = re.sub(r"\s*[<>]?\s*\d+(?:[.,]\d+)?\s*[MmKk]b\s*$", "", text).strip()
        for k, label in FILE_LABELS.items():
            if text.casefold() == label.casefold() and k not in out:
                href = html.unescape(m.group(1))
                out[k] = href if href.startswith("http") else BASE_URL + href
    return out


# ── checks & report ────────────────────────────────────────────────────────

def median_fraction(period: str, total: int, have: dict[str, dict]) -> float | None:
    prior = sorted(p for p in have if p < period and have[p].get("time_interval") == "monthly"
                   and have[p].get("TOTAL"))[-12:]
    if len(prior) < 6:
        return None
    vals = sorted(float(have[p]["TOTAL"]) for p in prior)
    median = vals[len(vals) // 2]
    return total / median if median else None


def previous_month(today: dt.date) -> str:
    y, m = (today.year - 1, 12) if today.month == 1 else (today.year, today.month - 1)
    return f"{y}-{m:02d}"


def month_range(first: str, last: str) -> list[str]:
    y, m = map(int, first.split("-"))
    out = []
    while f"{y}-{m:02d}" <= last:
        out.append(f"{y}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--variant", default="all", help="all | " + " | ".join(VARIANT_CSV))
    ap.add_argument("--period", default="", help="Target month YYYY-MM (default: last month)")
    ap.add_argument("--backfill", action="store_true",
                    help=f"Write every month from {FIRST_PERIOD} on.")
    ap.add_argument("--force", action="store_true",
                    help="Ignore the self-throttle, the guards and foreign source strings.")
    ap.add_argument("--from-dir", default="",
                    help="Offline: DIR/headline.xlsx, DIR/cars.xlsx, DIR/lorries.xlsx.")
    ap.add_argument("--dump-dir", default="", help="Save every downloaded workbook here.")
    ap.add_argument("--dry-run", action="store_true", help="Report, write nothing.")
    ap.add_argument("--github-output", default=os.environ.get("GITHUB_OUTPUT"))
    ap.add_argument("--step-summary", default=os.environ.get("GITHUB_STEP_SUMMARY"))
    args = ap.parse_args()

    variants = list(VARIANT_CSV) if args.variant == "all" else [args.variant]
    for v in variants:
        if v not in VARIANT_CSV:
            sys.exit(f"Unknown variant {v!r}. Valid: {list(VARIANT_CSV)} or all.")
    paths = {v: REPO / VARIANT_CSV[v] for v in VARIANT_CSV}
    have = {v: existing_rows(paths[v]) for v in VARIANT_CSV}
    target = args.period or previous_month(dt.date.today())

    if (not args.backfill and not args.force
            and all(have[v].get(target, {}).get("source") == SOURCE for v in variants)):
        print(f"{target} already written from {SOURCE} in every CSV — nothing to do (no HTTP).")
        return emit(args, set())

    if args.from_dir:
        d = Path(args.from_dir)
        load = lambda k: (d / f"{k}.xlsx").read_bytes()  # noqa: E731
    else:
        import requests
        session = requests.Session()
        session.headers.update(UA)
        relay = os.environ.get("LATVIA_FETCH_RELAY", "").strip()
        token = os.environ.get("LATVIA_RELAY_TOKEN", "").strip()
        if relay:
            # The Worker sends its own User-Agent upstream unless told otherwise.
            session.headers["X-Fwd-User-Agent"] = UA["User-Agent"]
            if token:
                session.headers["X-Relay-Token"] = token
        print("[net] " + (f"via the fetch relay (token {'set' if token else 'not set'})"
                          if relay else "direct (LATVIA_FETCH_RELAY not set)"))
        r = session.get(relayed(PAGE_URL, relay), timeout=120)
        r.raise_for_status()
        files = find_files(r.text)
        lacking = [k for k in FILE_LABELS if k not in files]
        if lacking:
            sys.exit(f"Statistics page: no link labelled {[FILE_LABELS[k] for k in lacking]} "
                     "— layout changed? Not writing. See the runbook in 58-source-latvia.md.")

        def load(k):
            resp = session.get(relayed(files[k], relay), timeout=600)
            resp.raise_for_status()
            if resp.content[:2] != b"PK":
                raise SystemExit(f"{k}: not an XLSX ({resp.headers.get('content-type')})")
            if args.dump_dir:
                Path(args.dump_dir).mkdir(parents=True, exist_ok=True)
                (Path(args.dump_dir) / f"{k}.xlsx").write_bytes(resp.content)
            return resp.content

    headline = parse_headline(load("headline"))
    if target not in headline or "cars" not in headline[target]:
        print(f"CSDD's headline table has no {target} yet (latest {max(headline)}) — retry next run.")
        return emit(args, set())
    first = FIRST_PERIOD if args.backfill else max(
        FIRST_PERIOD, month_range("2000-01", target)[-RECENT_MONTHS])
    periods = set(month_range(first, target))
    print(f"Months {first} … {target}; downloading the record workbooks")
    months = build_months(load("cars"), load("lorries"), headline, periods)

    problems: list[str] = []
    recent = max(FIRST_PERIOD, month_range("2000-01", target)[-RECENT_MONTHS])
    for p in sorted(months):
        m = months[p]
        bad = check_failures(m["checks"])
        if bad and p < recent:
            # the record files show the register as it is today; months more
            # than a year back drift from the headline table written at the
            # time (records removed since, late bookings) — new cars still
            # equal ACEA's figure to the car (58-source-latvia.md §4)
            print(f"  {p}: headline differs (historic month, not enforced): " + "; ".join(bad))
            bad = []
        if bad and not args.force:
            problems.append(f"{p}: cross-check failed — " + "; ".join(bad))
        elif bad:
            print(f"::warning title=Latvia {p} cross-check (forced)::" + "; ".join(bad))
        for v, (n, labels) in m["unknown"].items():
            tot = m["rows"]["Whole" if v in ("Private", "Industry") else v]["TOTAL"] or 1
            if n / tot > MAX_UNKNOWN_SHARE and not args.force:
                problems.append(f"{p} {v}: {n} vehicles ({n / tot:.1%}) with unknown values {labels}")
            elif labels:
                print(f"::warning title=New value {p} {v}::{labels} → OTHERS / skipped")
    if problems:
        sys.exit("Governance check failed — not writing:\n  " + "\n  ".join(problems[:20]))

    changed: set[str] = set()
    report_rows = []
    periods_sorted = sorted(months)
    for v in variants:
        updates = {}
        for p in periods_sorted:
            row = months[p]["rows"][v]
            tot = row["TOTAL"]
            if tot == 0 and v not in ("Buses", "HDV"):
                continue
            frac = median_fraction(p, tot, have[v])
            if p == target and frac is not None and not args.force and v in ("Whole", "Used"):
                if frac < MIN_MONTH_FRACTION:
                    print(f"{v} {p}: TOTAL {tot:,} is {frac:.0%} of the trailing median — "
                          "looks partial; not writing (--force if genuine).")
                    continue
                if frac < WARN_MONTH_FRACTION:
                    print(f"::warning title=Latvia {v} {p} unusually low::TOTAL {tot:,} = "
                          f"{frac:.0%} of the trailing-12 median — written; check it.")
            old = have[v].get(p)
            if old and old.get("source") == SOURCE and old.get("notes"):
                notes = old["notes"]           # keep the first write's ACEA trail
                if "; replaces ACEA" not in notes and "; = ACEA" not in notes:
                    notes = f"CSDD {p}: {NOTES[v]}"
            else:
                notes = f"CSDD {p}: {NOTES[v]}" + acea_note(old, row)
            updates[(p, v)] = render_line(p, v, row, notes)
            report_rows.append((v, p, row, old))
        if args.dry_run:
            print(f"{VARIANT_CSV[v]}: dry run, {len(updates)} row(s) computed")
            continue
        stats = upsert_lines(paths[v], updates, args.force)
        print(f"{VARIANT_CSV[v]}: {stats}")
        if stats["added"] or stats["updated"]:
            changed.add(v)

    if not args.dry_run and "Whole" in variants:
        fresh = {p: (months[p]["units"], months[p]["rows"]["Whole"]["TOTAL"]) for p in periods_sorted}
        market_top.guarded(market_top.refresh_from_store, "Latvia",
                           "CSDD (vehicle register, first registrations)",
                           "new passenger cars first registered in Latvia",
                           TOP_SLUG, fresh)
    if not args.dry_run and "Used" in variants:
        fresh = {p: (months[p]["used_units"], months[p]["rows"]["Used"]["TOTAL"])
                 for p in periods_sorted}
        market_top.guarded(market_top.refresh_from_store, "Latvia",
                           "CSDD (vehicle register, first registrations)",
                           "used passenger cars imported into Latvia (first Latvian registration)",
                           USED_TOP_SLUG, fresh, "Used")

    rep = report(report_rows, target, months)
    print("\n" + rep)
    if args.step_summary:
        with open(args.step_summary, "a", encoding="utf-8") as fh:
            fh.write(rep)
    return emit(args, changed)


def report(rows, target: str, months: dict) -> str:
    out = [f"## Latvia (CSDD) — up to {target}", ""]
    for p in sorted(months)[-3:]:
        out.append(f"- Cross-check {p}: " + "; ".join(
            f"{l} {g} = {r}" if g == r else f"{l} {g} vs {r}" for l, g, r in months[p]["checks"]))
    out += ["", "| variant | month | TOTAL | BEV | PHEV | PETROL | DIESEL | OTHERS | Δ TOTAL vs old row |",
            "|---|---|---:|---:|---:|---:|---:|---:|---|"]
    for v, p, r, old in rows[-40:]:
        d = ""
        if old and old.get("TOTAL"):
            d = f"{r['TOTAL'] - int(round(float(old['TOTAL']))):+d} ({old.get('source')})"
        out.append(f"| {v} | {p} | {r['TOTAL']:,} | {r['BEV']:,} | {r['PHEV']:,} | "
                   f"{r['PETROL']:,} | {r['DIESEL']:,} | {r['OTHERS']:,} | {d} |")
    return "\n".join(out) + "\n"


def emit(args, changed: set[str]) -> int:
    if args.github_output:
        with open(args.github_output, "a", encoding="utf-8") as f:
            f.write(f"changed={'true' if changed else 'false'}\n")
            f.write(f"changed_variants={json.dumps(sorted(changed))}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
