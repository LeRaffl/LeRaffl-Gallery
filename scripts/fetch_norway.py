#!/usr/bin/env python3
"""
Fetch Norway's new-car registrations from OFV and update data/Norway.csv.

Usage
-----
    python scripts/fetch_norway.py [--period YYYY-MM] [--force] [--dry-run]
                                   [--from-html PATH] [--export PATH]
                                   [--github-output PATH] [--summary PATH]

* --period     Target month (default: the calendar month that just ended).
* --force      Overwrite an existing row for the month (also one written by
               another source, e.g. ACEA) and skip the plausibility guards.
* --dry-run    Parse, validate and print; write nothing. Re-reading a month
               the CSV already holds this way is the regression test for a
               parser change: it must reproduce the committed row.
* --from-html  Parse a saved OFV article instead of the network (offline
               debugging; the month is read from the table caption).
* --export     Use a saved copy of ofv.no/api/statistikk/export.json for the
               cross-checks instead of downloading it.

Invoked by .github/workflows/fetch-norway.yml (twice a day on the 1st-12th,
plus workflow_dispatch). Full method, governance checks and a debugging
runbook: docs/architecture/54-source-norway.md.

Data source
-----------
OFV (Opplysningsrådet for veitrafikken) compiles Norway's first registrations
from the national vehicle register of Statens vegvesen and has been the
source of the gallery's Norway series from the start — by hand
("ofv.no & ACEA") and, since 2026-04, through ACEA, which republishes OFV's
figures three to four weeks later (and skipped July 2026 altogether).

On the first working day of the next month OFV posts a news article
(ofv.no/aktuelt/<slug>, no stable URL) whose tables are real HTML since the
September 2026 release (earlier releases carried them as images):

    Fordeling per drivstoff i september 2026 og hittil i år
                          september 2026      Hittil i 2026
    Drivstoff             Antall   Andel      Antall   Andel
    Elektrisitet          18 511   98,81 %    112 825  97,94 %
    Bensin hybrid             99    0,53 %        708   0,61 %
    ...
    Total                 18 733  100,00 %    115 196 100,00 %

plus "De 30 mest solgte bilmerkene / bilmodellene i <month> <year>" (every
powertrain). A second article the next day has the same three tables for
vans (varebiler); the fetcher recognises and skips it.

The article is found through the site's RSS feed (ofv.no/aktuelt/rss.xml, the
newest 30 posts) and, as a fallback, the sitemap: every post published from
the 1st of the next month on is read until one carries a fuel table for the
target month whose brand table is about passenger cars.

Independent cross-check: OFV's open JSON export
(ofv.no/api/statistikk/export.json, CC BY 4.0, explicitly allowed in robots.txt)
carries the monthly totals of the year and the fuel mix January to the last
complete month. The month's TOTAL must equal the export's month exactly, and
the article's year-to-date column must equal the export's fuel mix fuel by
fuel. If no article can be found by the 10th, the export alone gives the
month as year-to-date minus the months the CSV already has; such a row is
written with notes "derived: ..." and replaced by the article's figures as
soon as one turns up.

Fuel mapping (OFV drivstoff -> CSV column)
------------------------------------------
    Elektrisitet                                -> BEV
    Bensin plugin hybrid, Diesel plugin hybrid  -> PHEV
    Bensin hybrid, Diesel hybrid                -> HEV
    Bensin                                      -> PETROL
    Diesel                                      -> DIESEL
    Hydrogen, Gass, Biogass, Parafin, Annet ... -> OTHERS (as ACEA files them)

Labels outside FUEL_LABELS abort the run: a new OFV row needs a human
decision about its column (54-source-norway.md §4).

History
-------
Rows up to 2026-08 are the hand-transcribed OFV figures and ACEA's republished
ones; OFV's own year-to-date for January-September 2026 reproduces them to
one car per fuel (54-source-norway.md §5). OFV refreshes earlier months a
little as late registrations arrive; the CSV keeps every month as first
published (invariant 3).
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import sys
import time
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import market_top  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
CSV_PATH = REPO / "data" / "Norway.csv"
COUNTRY = "Norway"
SOURCE = "OFV"
VARIANT = "Whole"

SITE = "https://ofv.no"
RSS_URL = SITE + "/aktuelt/rss.xml"
SITEMAP_URL = SITE + "/sitemap.xml"
EXPORT_URL = SITE + "/api/statistikk/export.json"

CSV_COLUMNS = ["period", "time_interval", "variant", "source", "BEV", "PHEV",
               "HEV", "PETROL", "DIESEL", "OTHERS", "TOTAL", "notes"]
FUELS = ["BEV", "PHEV", "HEV", "PETROL", "DIESEL", "OTHERS"]

# OFV's drivstoff label (lower case, whitespace collapsed) -> CSV column.
FUEL_LABELS = {
    "elektrisitet": "BEV",
    "bensin plugin hybrid": "PHEV", "diesel plugin hybrid": "PHEV",
    "bensin hybrid": "HEV", "diesel hybrid": "HEV",
    "bensin": "PETROL",
    "diesel": "DIESEL",
    # Rare fuels: ACEA files them as "others", and so does the CSV.
    "hydrogen": "OTHERS", "gass": "OTHERS", "biogass": "OTHERS",
    "parafin": "OTHERS", "annet drivstoff": "OTHERS", "annet": "OTHERS",
}
TOTAL_LABELS = {"total", "totalt", "sum"}
REQUIRED = {"BEV"}       # a table without an electric row is not a fuel table

MONTHS = ["januar", "februar", "mars", "april", "mai", "juni", "juli",
          "august", "september", "oktober", "november", "desember"]

# Governance thresholds (docs/architecture/54-source-norway.md §6).
SHARE_TOL = 0.06        # printed "Andel" vs recomputed, in percentage points
YTD_WARN = 0.01         # article YTD minus the CSV's earlier months vs month
YTD_ABORT = 0.05
PLAUSIBLE = (0.15, 4.0) # TOTAL / same month a year earlier. Norway's tax changes
                        # are violent: 2023-01 and 2026-01 were ×0.24, 2024-01
                        # ×2.72 and 2025-12 ×2.57 — real, and must pass.
LATE_DAY = 10           # after this day of M+1, "no article found" -> fallback

DERIVED = "derived: "
EXPORT_NOTE = ("derived: OFV year-to-date fuel mix (ofv.no/api/statistikk/export.json) "
               "minus the CSV's earlier months of the year — no OFV article with the "
               "month's fuel table was found; replaced by the article's figures once found")

HTTP_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/128.0 Safari/537.36 "
                   "LeRaffl-Gallery (+https://leraffl.github.io/LeRaffl-Gallery/)"),
    "Accept": "text/html,application/xml,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "nb-NO,nb;q=0.9,en;q=0.8",
}
HTTP_TRIES = 4

TOP_PATH = market_top.MARKET_DIR / "norway_top.json"
STORE_PATH = market_top.MARKET_DIR / "norway_months.json"
TOP_UNIT = ("new passenger cars by brand as OFV publishes them — every powertrain "
            "(OFV's brand table has no fuel split; Norway's market is ~98 % "
            "battery-electric); brands and models are OFV's monthly top 30, the "
            "rest of the market is unranked")


# ── HTML tables ────────────────────────────────────────────────────────────

class _Tables(HTMLParser):
    """Every <table> of a page as {"caption", "rows"} (rows of cell texts)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[dict] = []
        self._depth = 0
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self._caption: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self._depth += 1
            if self._depth == 1:
                self.tables.append({"caption": "", "rows": []})
        elif self._depth == 1 and tag == "caption":
            self._caption = []
        elif self._depth == 1 and tag == "tr":
            self._row = []
        elif self._depth == 1 and tag in ("td", "th") and self._row is not None:
            self._cell = []
        elif tag == "br" and self._cell is not None:
            self._cell.append(" ")

    def handle_endtag(self, tag):
        if tag == "table":
            self._depth = max(0, self._depth - 1)
        elif self._depth == 1 and tag == "caption" and self._caption is not None:
            self.tables[-1]["caption"] = " ".join("".join(self._caption).split())
            self._caption = None
        elif self._depth == 1 and tag in ("td", "th") and self._cell is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif self._depth == 1 and tag == "tr" and self._row is not None:
            if any(self._row):
                self.tables[-1]["rows"].append(self._row)
            self._row = None

    def handle_data(self, data):
        if self._caption is not None:
            self._caption.append(data)
        elif self._cell is not None:
            self._cell.append(data)


def tables_of(page: str) -> list[dict]:
    p = _Tables()
    p.feed(page)
    return [t for t in p.tables if t["rows"]]


def to_int(cell: str) -> int | None:
    """'18 511' / '18 511' / '112825' -> int; anything else None."""
    s = re.sub(r"[\s  .]", "", cell or "")
    return int(s) if re.fullmatch(r"-?\d+", s) else None


def to_pct(cell: str) -> float | None:
    s = re.sub(r"[\s  %]", "", cell or "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def month_year(text: str) -> tuple[int, int] | None:
    """'... i september 2026 og hittil i år' -> (2026, 9)."""
    m = re.search(r"\b(" + "|".join(MONTHS) + r")\s+(\d{4})\b", text.lower())
    return (int(m.group(2)), MONTHS.index(m.group(1)) + 1) if m else None


# ── fuel table ─────────────────────────────────────────────────────────────

def is_fuel_table(t: dict) -> bool:
    return "drivstoff" in t["caption"].lower() or any(
        r and r[0].strip().lower() == "drivstoff" for r in t["rows"][:3])


def parse_fuel_table(t: dict) -> dict | None:
    """OFV's "Fordeling per drivstoff" table -> {year, month, cur, ytd, share}.
    None if `t` is not a fuel table; raises on one that does not have the
    expected shape (schema drift)."""
    if not is_fuel_table(t):
        return None
    head = t["caption"] + " " + " ".join(" ".join(r) for r in t["rows"][:2])
    ym = month_year(head)
    if not ym:
        raise RuntimeError(f"fuel table without a month in its caption: {t['caption']!r}")
    cur: dict[str, int] = {}
    ytd: dict[str, int] = {}
    share: dict[str, float | None] = {}
    rows: list[tuple[str, int, int | None]] = []
    unknown = []
    for r in t["rows"]:
        label = " ".join(r[0].lower().split()) if r else ""
        if len(r) < 2 or to_int(r[1]) is None:
            continue                       # header rows
        a = to_int(r[1])
        b = to_int(r[3]) if len(r) > 3 else None
        if label in TOTAL_LABELS:
            cur["TOTAL"] = a
            if b is not None:
                ytd["TOTAL"] = b
            continue
        col = FUEL_LABELS.get(label)
        if col is None:
            unknown.append(r[0])
            continue
        rows.append((r[0], a, to_pct(r[2]) if len(r) > 2 else None))
        cur[col] = cur.get(col, 0) + a
        if b is not None:
            ytd[col] = ytd.get(col, 0) + b
    if unknown:
        raise RuntimeError(f"unknown OFV fuel row(s) {unknown} — map them in FUEL_LABELS "
                           "(docs/architecture/54-source-norway.md §4)")
    missing = REQUIRED - set(cur)
    if missing or "TOTAL" not in cur:
        raise RuntimeError(f"fuel table lacks {sorted(missing | ({'TOTAL'} - set(cur)))}")
    return {"year": ym[0], "month": ym[1], "cur": cur, "ytd": ytd, "rows": rows}


def to_counts(values: dict[str, int]) -> dict[str, int]:
    out = {k: int(values.get(k, 0)) for k in FUELS}
    out["TOTAL"] = int(values["TOTAL"])
    return out


def validate(f: dict) -> list[str]:
    """Internal consistency of one fuel table. Returns problems (abort)."""
    problems = []
    for side in ("cur", "ytd"):
        v = f[side]
        if not v:
            continue
        s = sum(v.get(k, 0) for k in FUELS)
        if s != v.get("TOTAL"):
            problems.append(f"{side}: fuels sum to {s:,} ≠ Total {v.get('TOTAL', 0):,}")
    total = f["cur"]["TOTAL"]
    for label, n, printed in f["rows"]:
        if printed is None or not total:
            continue
        got = 100 * n / total
        if abs(got - printed) > SHARE_TOL:
            problems.append(f"{label}: printed share {printed}% but {n:,} / {total:,} = "
                            f"{got:.2f}% — columns shifted?")
    if f["ytd"] and f["ytd"].get("TOTAL", 0) < total:
        problems.append(f"year-to-date Total {f['ytd'].get('TOTAL'):,} < month {total:,}")
    return problems


def period_of(f: dict) -> str:
    return f"{f['year']}-{f['month']:02d}"


# ── brand + model tables ───────────────────────────────────────────────────

def group_of(tables: list[dict], title: str = "") -> str:
    """'varebiler' if the article is about vans, else 'personbiler'."""
    text = (title + " " + " ".join(t["caption"] for t in tables)).lower()
    return "varebiler" if "varebil" in text else "personbiler"


def parse_ranking(t: dict) -> dict | None:
    """'De 30 mest solgte bilmerkene/bilmodellene i <month> <year>' ->
    {kind: brands|models, period, items: [(label, n)]}."""
    cap = t["caption"].lower()
    if "mest solgte" not in cap:
        return None
    kind = "brands" if "merke" in cap else "models" if "modell" in cap else None
    if not kind:
        return None
    ym = month_year(cap)
    items = [(" ".join(r[0].split()), to_int(r[1])) for r in t["rows"]
             if len(r) >= 2 and to_int(r[1]) is not None]
    return {"kind": kind, "period": f"{ym[0]}-{ym[1]:02d}" if ym else None, "items": items}


def split_model(label: str, brands: list[str]) -> tuple[str, str]:
    """'Polestar Polestar 2' -> ('POLESTAR', 'POLESTAR 2') against the brand
    names (longest first, so 'Mercedes-Benz GLC' never splits at 'Mercedes')."""
    s = market_top.clean(label)
    for b in sorted(brands, key=len, reverse=True):
        if s.startswith(b + " "):
            return b, s[len(b) + 1:]
    head, _, rest = s.partition(" ")
    return head, rest or s


def month_units(tables: list[dict], period: str, total: int) -> dict:
    """{(ALL, brand, model): n} of one month — brand rows (model "") and model
    rows in one dict, as fetch_uk.py stores them. Raises if the rankings are
    for another month or list more cars than the month has."""
    found = {}
    for t in tables:
        r = parse_ranking(t)
        if r:
            found.setdefault(r["kind"], r)
    if "brands" not in found:
        raise RuntimeError("article has no brand table")
    for r in found.values():
        if r["period"] and r["period"] != period:
            raise RuntimeError(f"{r['kind']} table is for {r['period']}, fuel table for {period}")
    brands = {}
    for name, n in found["brands"]["items"]:
        b = market_top.clean(name)
        brands[b] = brands.get(b, 0) + n
    if sum(brands.values()) > total:
        raise RuntimeError(f"brand table lists {sum(brands.values()):,} > TOTAL {total:,}")
    units = {(market_top.ALL, b, ""): n for b, n in brands.items() if n}
    for label, n in found.get("models", {}).get("items", []):
        b, m = split_model(label, list(brands))
        key = (market_top.ALL, b, m)
        units[key] = units.get(key, 0) + n
    if sum(n for k, n in units.items() if k[2]) > total:
        raise RuntimeError("model table lists more cars than the month's TOTAL")
    return units


def build_norway_top(store: dict) -> dict:
    """market/norway_top.json from the month store: brands and models are two
    separate top-30 tables, so each is ranked on its own and spliced (UK)."""
    target = max(store)
    months_b, months_m = {}, {}
    for p, (u, tot) in store.items():
        b = {k: n for k, n in u.items() if not k[2]}
        b[(market_top.ALL, market_top.REST, "")] = tot - sum(b.values())
        m = {k: n for k, n in u.items() if k[2]}
        m[(market_top.ALL, market_top.REST, "")] = tot - sum(m.values())
        months_b[p], months_m[p] = (b, tot), (m, tot)
    top = market_top.build_top_monthly(COUNTRY, SOURCE, target, months_b, TOP_UNIT)
    return market_top.splice_models(top, market_top.build_top_monthly(
        COUNTRY, SOURCE, target, months_m, TOP_UNIT))


def refresh_top(period: str, units: dict, total: int) -> None:
    store = market_top.load_store(STORE_PATH)
    store[period] = (units, total)
    market_top.save_store(STORE_PATH, store, COUNTRY, SOURCE)
    top = build_norway_top(store)
    market_top.report(top, TOP_PATH, market_top.write_top(top, TOP_PATH))


# ── network ────────────────────────────────────────────────────────────────

def http_get(url: str) -> str:
    import requests
    last = None
    for attempt in range(HTTP_TRIES):
        try:
            r = requests.get(url, headers=HTTP_HEADERS, timeout=(20, 180))
            if r.status_code == 200:
                r.encoding = r.encoding or "utf-8"
                return r.text
            last = f"HTTP {r.status_code}"
            if r.status_code in (400, 401, 403, 404, 410):
                break
        except requests.RequestException as e:
            last = f"{type(e).__name__}: {e}"
        time.sleep(2 ** (attempt + 1))
    raise RuntimeError(f"GET {url} failed: {last}")


def shift_month(p: str, k: int) -> str:
    y, m = map(int, p.split("-"))
    m += k
    y += (m - 1) // 12
    m = (m - 1) % 12 + 1
    return f"{y:04d}-{m:02d}"


def rss_candidates(xml: str, after: date) -> list[tuple[str, str]]:
    """(link, title) of the RSS items published on or after `after`."""
    out = []
    for item in re.findall(r"<item>(.*?)</item>", xml, re.S):
        link = re.search(r"<link>(.*?)</link>", item, re.S)
        pub = re.search(r"<pubDate>(.*?)</pubDate>", item, re.S)
        title = re.search(r"<title>(.*?)</title>", item, re.S)
        if not link or not pub:
            continue
        try:
            when = parsedate_to_datetime(pub.group(1).strip()).date()
        except (TypeError, ValueError):
            continue
        if when >= after:
            out.append((link.group(1).strip(), (title.group(1) if title else "").strip()))
    return out


def sitemap_candidates(xml: str, after: date) -> list[tuple[str, str]]:
    """/aktuelt/ URLs of the sitemap changed on or after `after`."""
    out = []
    for e in re.findall(r"<url>(.*?)</url>", xml, re.S):
        loc = re.search(r"<loc>(.*?)</loc>", e)
        mod = re.search(r"<lastmod>(\d{4}-\d{2}-\d{2})", e)
        if loc and "/aktuelt/" in loc.group(1) and mod and date.fromisoformat(mod.group(1)) >= after:
            out.append((loc.group(1).strip(), ""))
    return out


def article_for(period: str, url: str, page: str, title: str = "") -> dict | None:
    """The passenger-car release for `period` in one article, or None."""
    tables = tables_of(page)
    fuel = next((parse_fuel_table(t) for t in tables if is_fuel_table(t)), None)
    if not fuel or period_of(fuel) != period:
        return None
    if group_of(tables, title) != "personbiler":
        print(f"  {url}: the {period} van (varebil) release — skipped")
        return None
    return {"url": url, "fuel": fuel, "tables": tables}


def find_article(period: str) -> dict | None:
    """OFV's passenger-car release for `period`: RSS first, sitemap second."""
    after = date(*map(int, shift_month(period, 1).split("-")), 1)
    seen: set[str] = set()
    for name, url, parse in (("RSS", RSS_URL, rss_candidates),
                             ("sitemap", SITEMAP_URL, sitemap_candidates)):
        try:
            cands = parse(http_get(url), after)
        except RuntimeError as e:
            print(f"::warning title=Norway {name} unreadable::{e}")
            continue
        for link, title in cands:
            if link in seen:
                continue
            seen.add(link)
            try:
                page = http_get(link)
            except RuntimeError as e:
                print(f"  {link}: {e}")
                continue
            try:
                hit = article_for(period, link, page, title)
            except RuntimeError as e:
                # A fuel-shaped table that does not parse is schema drift,
                # not "someone else's article" — surface it.
                raise RuntimeError(f"{link}: {e}") from e
            if hit:
                print(f"  found via {name}: {link}")
                return hit
    return None


# ── export.json (independent cross-check / fallback) ───────────────────────

def export_month_total(export: dict, period: str) -> int | None:
    g = (export.get("data") or {}).get("personbiler") or {}
    y, m = map(int, period.split("-"))
    if str(g.get("thisYearLabel")) == str(y):
        key = "current"
    elif str(g.get("prevYearLabel")) == str(y):
        key = "previous"
    else:
        return None
    monthly = g.get("monthly") or []
    if len(monthly) >= m and monthly[m - 1].get(key) is not None:
        return int(monthly[m - 1][key])
    return None


def export_fuel_ytd(export: dict) -> tuple[str, dict[str, int]] | None:
    """(last month covered 'YYYY-MM', {column: n} January..that month)."""
    g = (export.get("data") or {}).get("personbiler") or {}
    label = g.get("fuelRangeLabel") or ""
    dates = re.findall(r"\d{1,2}\.\s*(" + "|".join(MONTHS) + r")\s+(\d{4})", label.lower())
    mix = g.get("fuelMix")
    if not dates or not mix:
        return None
    end = f"{int(dates[-1][1]):04d}-{MONTHS.index(dates[-1][0]) + 1:02d}"
    out: dict[str, int] = {}
    for item in mix:
        name = " ".join(str(item.get("name", "")).lower().split())
        col = FUEL_LABELS.get(name)
        if col is None:
            raise RuntimeError(f"export.json: unknown fuel {item.get('name')!r} — map it in "
                               "FUEL_LABELS")
        out[col] = out.get(col, 0) + int(item.get("value") or 0)
    out["TOTAL"] = sum(out.values())
    return end, out


# ── CSV line-level upsert (invariant 2) ────────────────────────────────────

def render_line(period: str, counts: dict[str, int], notes: str = "") -> str:
    buf = io.StringIO()
    csv.writer(buf, lineterminator="").writerow(
        [period, "monthly", VARIANT, SOURCE]
        + [str(counts[k]) for k in FUELS + ["TOTAL"]] + [notes])
    return buf.getvalue()


def read_csv_lines(path: Path) -> tuple[str, list[str], str]:
    """(header, lines with their own line endings, dominant line ending).
    Norway.csv is CRLF with one historical LF line; every untouched line keeps
    its own ending byte for byte, new lines take the dominant one."""
    if not path.exists():
        return ",".join(CSV_COLUMNS) + "\r\n", [], "\r\n"
    raw = path.read_bytes().decode("utf-8")
    eol = "\r\n" if raw.count("\r\n") * 2 >= raw.count("\n") else "\n"
    lines = raw.splitlines(keepends=True)
    if not lines:
        return ",".join(CSV_COLUMNS) + eol, [], eol
    if not lines[-1].endswith("\n"):
        lines[-1] += eol
    return lines[0], lines[1:], eol


def line_key(line: str) -> tuple[str, str]:
    f = next(csv.reader([line.rstrip("\r\n")]))
    return f[0], f[2]


def existing_rows(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    with open(path, newline="", encoding="utf-8") as f:
        return {r["period"]: r for r in csv.DictReader(f)
                if (r.get("variant") or "Whole") == VARIANT}


def upsert_lines(path: Path, updates: dict[str, str], force: bool,
                 replace: frozenset[str] = frozenset()) -> dict[str, int]:
    """Insert the given periods' lines; an existing line is replaced only with
    --force or when its period is in `replace` (an ACEA row, a derived row).
    Every other line is written back byte-for-byte."""
    header, lines, eol = read_csv_lines(path)
    if header.rstrip("\r\n").split(",") != CSV_COLUMNS:
        raise SystemExit(f"{path}: unexpected header {header!r}")
    stats = {"added": 0, "updated": 0, "unchanged": 0, "skipped": 0}
    index = {line_key(l): i for i, l in enumerate(lines)}
    for period, new in sorted(updates.items()):
        key = (period, VARIANT)
        if key not in index:
            # Insert before the first later period; nothing else moves.
            at = next((i for i, l in enumerate(lines) if line_key(l) > key), len(lines))
            lines.insert(at, new + eol)
            index = {line_key(l): i for i, l in enumerate(lines)}
            stats["added"] += 1
        elif lines[index[key]].rstrip("\r\n") == new:
            stats["unchanged"] += 1
        elif force or period in replace:
            old = lines[index[key]]
            lines[index[key]] = new + old[len(old.rstrip("\r\n")):]
            stats["updated"] += 1
        else:
            stats["skipped"] += 1
    if stats["added"] or stats["updated"]:
        path.write_bytes("".join([header] + lines).encode("utf-8"))
    return stats


def row_counts(row: dict[str, str]) -> dict[str, int]:
    return {k: int(float(row[k])) if row.get(k) not in (None, "") else 0
            for k in FUELS + ["TOTAL"]}


def compare(counts: dict[str, int], row: dict[str, str] | None) -> str:
    if row is None:
        return "not in the CSV"
    old = row_counts(row)
    return ", ".join(f"{k} {old[k]:,}→{counts[k]:,}" for k in FUELS + ["TOTAL"]
                     if old[k] != counts[k])


def replaceable(row: dict[str, str] | None) -> bool:
    """A row this fetcher may overwrite without --force: ACEA's (OFV's own
    figures, republished weeks later) or a derived row of its own."""
    if row is None:
        return True
    src = (row.get("source") or "").strip()
    return src.upper() == "ACEA" or (src == SOURCE and (row.get("notes") or "").startswith(DERIVED))


# ── checks against the committed history ───────────────────────────────────

def ytd_check(f: dict, have: dict[str, dict]) -> tuple[str, float | None]:
    """The article's year-to-date column minus the CSV's January..M-1 must give
    the month again (up to OFV's small refreshes of earlier months)."""
    y = f.get("ytd")
    if not y or "TOTAL" not in y:
        return "no year-to-date column", None
    if f["month"] == 1:
        return "January: year-to-date = month" + (
            "" if y["TOTAL"] == f["cur"]["TOTAL"] else " — but it differs!"), (
            0.0 if y["TOTAL"] == f["cur"]["TOTAL"] else 1.0)
    earlier = [f"{f['year']}-{m:02d}" for m in range(1, f["month"])]
    if any(p not in have for p in earlier):
        return "CSV lacks earlier months of the year — skipped", None
    implied = y["TOTAL"] - sum(row_counts(have[p])["TOTAL"] for p in earlier)
    got = f["cur"]["TOTAL"]
    dev = (implied - got) / got if got else None
    per_fuel = []
    for k in FUELS:
        imp = y.get(k, 0) - sum(row_counts(have[p])[k] for p in earlier)
        if imp != f["cur"].get(k, 0):
            per_fuel.append(f"{k} {imp:,} vs {f['cur'].get(k, 0):,}")
    msg = (f"YTD {y['TOTAL']:,} − CSV Jan..{earlier[-1][-2:]} = {implied:,} vs month "
           f"{got:,} ({dev:+.2%})")
    if per_fuel:
        msg += "; " + ", ".join(per_fuel)
    return msg, dev


def export_check(f: dict, export: dict | None) -> list[str]:
    """Two independent OFV publications must agree exactly: the article's
    month TOTAL vs the export's monthly series, the article's year-to-date
    column vs the export's fuel mix. Returns problems (abort)."""
    if not export:
        return []
    problems = []
    period = period_of(f)
    t = export_month_total(export, period)
    if t is not None and t != f["cur"]["TOTAL"]:
        problems.append(f"export.json has {t:,} new cars for {period}, the article "
                        f"{f['cur']['TOTAL']:,}")
    mix = export_fuel_ytd(export)
    if mix and mix[0] == period and f.get("ytd"):
        diffs = [f"{k} {f['ytd'].get(k, 0):,} vs {mix[1].get(k, 0):,}"
                 for k in FUELS + ["TOTAL"] if f["ytd"].get(k, 0) != mix[1].get(k, 0)]
        if diffs:
            problems.append("article year-to-date ≠ export.json fuel mix: " + ", ".join(diffs))
    return problems


def plausibility(period: str, total: int, have: dict[str, dict]) -> float | None:
    p = shift_month(period, -12)
    if p not in have:
        return None
    old = row_counts(have[p])["TOTAL"]
    return total / old if old else None


def derive_from_export(period: str, export: dict, have: dict[str, dict]) -> dict[str, int] | None:
    """Month = export year-to-date − the CSV's January..M-1 (fallback only)."""
    mix = export_fuel_ytd(export)
    if not mix or mix[0] != period:
        return None
    y, m = map(int, period.split("-"))
    earlier = [f"{y}-{k:02d}" for k in range(1, m)]
    if any(p not in have for p in earlier):
        return None
    out = {k: mix[1].get(k, 0) - sum(row_counts(have[p])[k] for p in earlier)
           for k in FUELS + ["TOTAL"]}
    if any(v < 0 for v in out.values()):
        return None
    t = export_month_total(export, period)
    if t is not None and abs(t - out["TOTAL"]) > max(30, 0.01 * t):
        raise RuntimeError(f"derived {period} TOTAL {out['TOTAL']:,} vs export month "
                           f"{t:,} — the CSV's earlier months do not fit OFV's year-to-date")
    return out


# ── main ───────────────────────────────────────────────────────────────────

def default_period(today: date) -> str:
    return shift_month(f"{today.year:04d}-{today.month:02d}", -1)


def summary_table(period: str, counts: dict[str, int], url: str) -> str:
    total = counts["TOTAL"]
    lines = [f"### Norway {period} — OFV", "", f"Release: {url}", "",
             "| column | units | share |", "|---|---:|---:|"]
    for k in FUELS + ["TOTAL"]:
        lines.append(f"| {k} | {counts[k]:,} | {100 * counts[k] / total:.2f}% |")
    return "\n".join(lines)


def process(art: dict, have: dict, export: dict | None, force: bool,
            report: list[str]) -> tuple[str, dict]:
    """Validate one article's fuel table. Returns (CSV line, counts) or raises."""
    f, url = art["fuel"], art["url"]
    period = period_of(f)
    problems = validate(f)
    if problems:
        raise RuntimeError(f"{period}: " + "; ".join(problems))
    disagree = export_check(f, export)
    if disagree and not force:
        raise RuntimeError(f"{period}: " + "; ".join(disagree) + " — re-run later; if it "
                           "persists, compare by hand, then --force")
    counts = to_counts(f["cur"])
    report.append(summary_table(period, counts, url))
    if disagree:
        print(f"::warning title=Norway export.json disagrees (forced)::{'; '.join(disagree)}")
        report.append("- export.json disagrees (written with --force): " + "; ".join(disagree))
    elif export:
        report.append("- export.json: month TOTAL and year-to-date fuel mix agree with the "
                      "article")
    msg, dev = ytd_check(f, have)
    report.append(f"- year-to-date check: {msg}")
    if dev is not None and abs(dev) > YTD_ABORT and not force:
        raise RuntimeError(f"{period}: year-to-date check off by {dev:+.1%} (> "
                           f"{YTD_ABORT:.0%}) — wrong month, or OFV revised earlier months "
                           "heavily; check by hand, then --force")
    if dev is not None and abs(dev) > YTD_WARN:
        print(f"::warning title=Norway year-to-date check::{msg}")
    ratio = plausibility(period, counts["TOTAL"], have)
    if ratio is not None:
        report.append(f"- TOTAL vs same month a year earlier: ×{ratio:.2f}")
        if not PLAUSIBLE[0] <= ratio <= PLAUSIBLE[1] and not force:
            raise RuntimeError(f"{period}: TOTAL {counts['TOTAL']:,} is ×{ratio:.2f} the same "
                               "month a year earlier — implausible; check, then --force")
    return render_line(period, counts, url if url.startswith("http") else ""), counts


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--period")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--from-html")
    ap.add_argument("--export", help="saved export.json (default: download it)")
    ap.add_argument("--csv", default=str(CSV_PATH))
    ap.add_argument("--no-top", action="store_true", help="skip market/norway_top.json")
    ap.add_argument("--github-output", default=os.environ.get("GITHUB_OUTPUT"))
    ap.add_argument("--summary", default=os.environ.get("GITHUB_STEP_SUMMARY"))
    args = ap.parse_args(argv)

    csv_path = Path(args.csv)
    have = existing_rows(csv_path)
    today = datetime.now(timezone.utc).date()
    report: list[str] = []

    def load_export() -> dict | None:
        try:
            text = (Path(args.export).read_text(encoding="utf-8") if args.export
                    else http_get(EXPORT_URL))
            return json.loads(text)
        except (RuntimeError, OSError, ValueError) as e:
            print(f"::warning title=Norway export.json unreadable::{e} — the article is "
                  "taken without the cross-check")
            return None

    if args.from_html:
        page = Path(args.from_html).read_text(encoding="utf-8")
        tables = tables_of(page)
        fuel = next((parse_fuel_table(t) for t in tables if is_fuel_table(t)), None)
        if not fuel:
            raise SystemExit(f"{args.from_html}: no fuel table")
        art = {"url": args.from_html, "fuel": fuel, "tables": tables}
        line, counts = process(art, have, load_export() if args.export else None, True, report)
        report.append(f"- group: {group_of(tables)}")
        report.append(f"- vs CSV: {compare(counts, have.get(period_of(fuel))) or 'identical'}")
        print("\n".join(report))
        print(line)
        return 0

    period = args.period or default_period(today)
    cur = have.get(period)
    top_current = market_top.top_as_of(TOP_PATH) == period
    if (not args.force and cur and cur.get("source") == SOURCE
            and not (cur.get("notes") or "").startswith(DERIVED)
            and (top_current or args.no_top)):
        print(f"{period} already in {csv_path.name} from {SOURCE} and "
              "market/norway_top.json is current — nothing to do.")
        return emit(args, set())

    export = load_export()
    art = find_article(period)
    updates: dict[str, str] = {}
    replace: set[str] = set()
    units = None
    if art is None:
        due = date(*map(int, shift_month(period, 1).split("-")), LATE_DAY)
        msg = f"{period}: no OFV article with the month's fuel table found yet"
        if today <= due:
            print(msg)
            report.append(f"- {msg}")
        else:
            derived = derive_from_export(period, export, have) if export else None
            if derived is None:
                print(f"::error title=Norway release not found::{msg}, and export.json "
                      "cannot stand in — see 54-source-norway.md §7")
                return 1
            if cur and not replaceable(cur) and not args.force:
                report.append(f"- {msg}; {period} is already in the CSV "
                              f"({cur.get('source')}) — kept")
            else:
                print(f"::warning title=Norway month derived from export.json::{msg} — "
                      "writing year-to-date minus earlier months (flagged in notes)")
                report.append(summary_table(period, derived, EXPORT_URL))
                report.append(f"- {EXPORT_NOTE}")
                updates[period] = render_line(period, derived, EXPORT_NOTE)
                if cur:
                    replace.add(period)
    else:
        line, counts = process(art, have, export, args.force, report)
        diff = compare(counts, cur)
        if cur is None:
            updates[period] = line
        elif not diff and cur.get("source") == SOURCE and not replaceable(cur):
            report.append(f"- {period}: identical to the CSV")
        elif replaceable(cur):
            updates[period] = line
            replace.add(period)
            report.append(f"- {period}: replaces the {cur.get('source')} row"
                          + (f" ({diff})" if diff else " (numbers identical)"))
        else:
            report.append(f"- {period} differs from the CSV ({cur.get('source')}): {diff} "
                          "— kept unless --force")
            if args.force:
                updates[period] = line
        try:
            units = month_units(art["tables"], period, counts["TOTAL"])
        except RuntimeError as e:
            print(f"::warning title=Norway brand/model tables unreadable::{e}")

    changed: set[str] = set()
    if updates and not args.dry_run:
        stats = upsert_lines(csv_path, updates, args.force, frozenset(replace))
        print(f"{csv_path.name}: {stats}")
        if stats["added"] or stats["updated"]:
            changed.add(VARIANT)
    elif updates:
        print("dry run — would write:\n" + "\n".join(updates.values()))

    if units and not args.no_top and not args.dry_run:
        market_top.guarded(refresh_top, period, units, art["fuel"]["cur"]["TOTAL"])

    text = "\n".join(report)
    print(text)
    if args.summary:
        with open(args.summary, "a", encoding="utf-8") as fh:
            fh.write(text + "\n")
    return emit(args, changed)


def emit(args, changed: set[str]) -> int:
    if args.github_output:
        with open(args.github_output, "a", encoding="utf-8") as f:
            f.write(f"changed={'true' if changed else 'false'}\n")
            f.write(f"changed_variants={json.dumps(sorted(changed))}\n")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except RuntimeError as e:
        print(f"::error title=Norway fetch failed::{e}")
        sys.exit(1)
