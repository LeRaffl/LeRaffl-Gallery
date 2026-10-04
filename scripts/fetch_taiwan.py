#!/usr/bin/env python3
"""
Fetch Taiwan's new-vehicle registrations by fuel (the Highway Bureau's
motor-vehicle register, as published in the Ministry of Transportation and
Communications' statistics database) and upsert data/Taiwan*.csv
(Whole + Vans + HDV + Buses).

Source
------
Every vehicle that gets a Taiwanese number plate is registered with the
Highway Bureau (交通部公路局, THB — the Directorate General of Highways until
2023). THB's own statistics site (stat.thb.gov.tw) sits behind an Imperva
wall that answers every GitHub-runner request — browser or not — with
"Error 16, access denied" (probed 2026-10-04). The Ministry (MOTC) republishes
THB's monthly tables, free and without login, in its statistics database
"交通部統計查詢網" (statis.motc.gov.tw), which runners reach. Two of its tables:

  Seq 104  機動車輛新領牌車輛數－按使用燃料分   new registrations by vehicle
           kind × fuel, monthly from 2012-01  (the data)
  Seq 118  各型汽車新領牌車輛數－按廠牌分       new registrations by vehicle
           kind × brand, monthly from 2012-09 (cross-check + brand table)

Both are read through the JSON endpoint the database's own page script calls:

  GET https://statis.motc.gov.tw/motc/Statistics/Display?Seq=104
      HTML: the newest month (first option of the period picker) and the ids
      of every statistical item (vehicle kind) and fuel, found by their label
  GET .../Statistics/Display.json?Seq=104&Start=110-01-00&End=115-08-00
      &ShowMonth=true&ShowYear=false&ShowQuarter=false&ShowHalfYear=false
      &Mode=0&ColumnValues=<kind id>&CodeListValues=<fuel ids, "_"-joined>
      JSON: data = [{"date": "115-08-00", "Column_844_78.1173": "1,093 ", …}]
  GET .../Statistics/DisplayPublishDate.json?seq=104   publication date

Periods are ROC years (民國): 115-08-00 = 2026-08 (year + 1911). Values are
strings with thousands separators and a trailing space; "-" means none. The
ids are never hard-coded: the page's labels map to ids, and the JSON's own
`nameMapping` must give the same labels back (schema drift aborts).

Timing: MOTC published August 2026 on 2026-09-15 (DisplayPublishDate.json);
months appear around the 15th of the following month.

Record → CSV
------------
THB's vehicle kinds (定義: 交通統計名詞定義) map to the EU classes:

  Whole  data/Taiwan.csv        小客車  passenger cars, up to 9 seats      (EU M1)
                                        incl. taxis and rental cars
  Vans   data/Taiwan_Vans.csv   小貨車  goods vehicles up to 3.5 t          (≈ N1)
                                        (since 2020-09-04 also 3.5–5 t up to 6 m long)
  HDV    data/Taiwan_HDV.csv    大貨車  goods vehicles over 3.5 t           (≈ N2+N3)
                                        (since 2020-09-04 without the 3.5–5 t ≤ 6 m)
  Buses  data/Taiwan_Buses.csv  大客車  buses and coaches, 10+ seats or > 3.5 t (M2+M3)

Not in any variant: 特種車 (special vehicles), 機車 (motorcycles and mopeds —
see docs/architecture/49-source-taiwan.md §9).

Fuel → columns (THB's 使用燃料 categories, defined in the table's notes):

  電能 (electric only)                                → BEV
  汽油/電能, 柴油/電能 (petrol|diesel + electricity,
    mainly combustion), 電能/汽油, 電能/柴油
    (electricity + petrol|diesel, mainly electric)   → PHEV
  電能(增程) (range extender)                         → EREV
  汽油(油電), 柴油(油電) (fuel only, can drive
    electrically — hybrids), 汽油(電能) (fuel only,
    driven only by the motor — Nissan e-POWER)       → HEV
  汽油 → PETROL · 柴油 → DIESEL
  液化石油氣, 汽油/液化石油氣                          → LPG
  anything new                                        → OTHERS (listed; > 1 % aborts)

The register has no separate mild-hybrid code: 48 V mild hybrids are in
whichever of 汽油 / 汽油(油電) their type approval names, so HEV may hold some.

History starts 2021-01. Before that the combined code 汽油/電能 still held
conventional full hybrids (Prius-era coding: 600–900 a month in 2016, when
plug-ins were almost unknown); the dedicated hybrid code 汽油(油電) appears
from 2017-06 and 汽油/電能 fell from ~550 a month to 36 in 2020-12/2021-01.
From 2021-01 every plug-in code holds plug-ins only, so the PHEV column is
consistent. BEV and TOTAL are unaffected by that recoding, but one series has
one start (invariant 3: never splice across a definition break).

Governance (every real run)
---------------------------
* the table pages must still list every vehicle kind and fuel this script
  maps, and the JSON's name mapping must agree (schema drift aborts);
* every month must have every fuel cell; the fuels must sum to the table's
  own 總計 (TOTAL) exactly;
* a fuel category the script does not know is counted as OTHERS and listed;
  above 1 % of a month's TOTAL the run aborts (--force overrides);
* cross-check: for every month written, each vehicle kind's total in the
  brand table (Seq 118, compiled separately) must equal its total in the fuel
  table (exact for 167 months 2012-09 → 2026-08); a difference beyond
  max(3, 0.1 %) aborts (--force overrides);
* a new month whose Whole TOTAL is below 40 % of the trailing-12 median is
  not written (--force overrides; Lunar New Year Februaries run at 54–74 %).

Writes are line-level upserts keyed on (period, variant) (invariant 2); a row
whose `source` is not ours is never overwritten without --force. A normal
run re-reads the newest 24 months, so a revision by THB is picked up and
listed in the step summary. Also writes market/taiwan_top.json (top brands of
new passenger cars, every powertrain — the source has no brand × fuel table)
via scripts/market_top.py.

Usage
-----
    python scripts/fetch_taiwan.py                     # newest published month
    python scripts/fetch_taiwan.py --period 2026-07
    python scripts/fetch_taiwan.py --backfill          # 2021-01 → now
    python scripts/fetch_taiwan.py --dump-dir DIR      # also save the raw responses
    python scripts/fetch_taiwan.py --from-dir DIR      # offline, from a dump
"""

from __future__ import annotations

import argparse
import collections
import csv
import html as htmllib
import io
import json
import os
import re
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import market_top  # noqa: E402

SOURCE = "THB register via MOTC statistics database"
FIRST_PERIOD = "2021-01"          # first month with a consistent plug-in coding
LOOKBACK_MONTHS = 24              # a normal run re-reads this many months

BASE = "https://statis.motc.gov.tw/motc/Statistics"
FUEL_SEQ = 104
BRAND_SEQ = 118

# variant -> (THB vehicle kind as labelled in both tables, CSV path)
VARIANTS = {
    "Whole": ("小客車", "data/Taiwan.csv"),
    "Vans": ("小貨車", "data/Taiwan_Vans.csv"),
    "HDV": ("大貨車", "data/Taiwan_HDV.csv"),
    "Buses": ("大客車", "data/Taiwan_Buses.csv"),
}
RENDERED_VARIANTS = tuple(VARIANTS)

FUEL_TOTAL = "總計"
FUEL_COLUMN = {
    "電能": "BEV",
    "汽油/電能": "PHEV", "柴油/電能": "PHEV",
    "電能/汽油": "PHEV", "電能/柴油": "PHEV",
    "電能(增程)": "EREV",
    "汽油(油電)": "HEV", "柴油(油電)": "HEV", "汽油(電能)": "HEV",
    "汽油": "PETROL",
    "柴油": "DIESEL",
    "液化石油氣": "LPG", "汽油/液化石油氣": "LPG",
}
BRAND_TOTAL = "廠牌別總計"
BRAND_OTHER = "其他"

FUELS = ["BEV", "PHEV", "EREV", "HEV", "PETROL", "DIESEL", "LPG", "OTHERS"]
CSV_COLUMNS = (["period", "time_interval", "variant", "source"]
               + FUELS + ["TOTAL", "notes"])

MIN_MONTH_FRACTION = 0.40
MAX_UNKNOWN_FUEL_SHARE = 0.01
XCHECK_ABS_TOL = 3
XCHECK_REL_TOL = 0.001

HTTP_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/128.0 Safari/537.36 LeRaffl-Gallery fetch_taiwan.py"),
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
}
# Connections from GitHub runners to statis.motc.gov.tw occasionally time out
# at connect, sometimes for a few minutes (seen 2026-10-04); retries back off
# 15, 30, 60, 120 s.
HTTP_TRIES = 5
HTTP_TIMEOUT = (25, 150)

REPO = Path(__file__).resolve().parent.parent
TOP_PATH = market_top.MARKET_DIR / "taiwan_top.json"
TOP_UNIT = ("new registrations of passenger cars (小客車) by the brand THB records — "
            "the registering maker or importer; every powertrain, as the source "
            "publishes brands without a fuel split")

# THB's brand table is by registrant: locally built cars are recorded under
# the local maker, imports under the marque, and a few names are in Chinese.
# The table shows marques — a local maker that builds one marque only is
# merged with that marque's imports; China Motor (中華: Mitsubishi and its own
# models) stays itself. Names not listed are title-cased (acronyms kept).
BRAND_NAMES = {
    "國瑞": "Toyota", "TOYOTA": "Toyota", "豐田": "Toyota",        # Kuozui Motors
    "本田": "Honda", "HONDA": "Honda",                               # Honda Taiwan
    "三陽": "Hyundai", "HYUNDAI": "Hyundai", "現代": "Hyundai",       # San Yang (SYM)
    "福特六和": "Ford", "FORD": "Ford",                              # Ford Lio Ho
    "日產": "Nissan", "NISSAN": "Nissan",                            # Yulon Nissan
    "中華": "China Motor (CMC)",
    "三菱": "Mitsubishi",
    "裕隆": "Yulon",
    "納智捷": "Luxgen",
    "賓士": "Mercedes-Benz", "MERCEDES-BENZ": "Mercedes-Benz",
    "福斯": "Volkswagen",
    "馬自達": "Mazda",
    "鈴木": "Suzuki",
    "起亞": "Kia",
    "速霸陸": "Subaru",
    "標緻": "Peugeot", "羽田標緻": "Peugeot",
    "雪鐵龍": "Citroën", "CITROEN": "Citroën",
    "富豪": "Volvo",
    "雷諾": "Renault",
    "大發": "Daihatsu",
    "五十鈴": "Isuzu",
    "SKODA": "Škoda",
    "LANDROVER": "Land Rover",
    "ALFAROMEO": "Alfa Romeo",
    "ASTONMARTIN": "Aston Martin",
    "ROLLS-ROYCE": "Rolls-Royce",
}
ACRONYMS = {"BMW", "MG", "MINI", "DS", "GMC", "GM", "MAN", "DAF", "BYD", "AMC", "IPW", "TD", "MCI"}


# ── small helpers ───────────────────────────────────────────────────────────

def norm_label(s: str) -> str:
    """Page and JSON labels → one spelling: HTML entities decoded, full-width
    parentheses / slash folded to ASCII, all whitespace removed."""
    s = htmllib.unescape(str(s or ""))
    s = s.replace("（", "(").replace("）", ")").replace("／", "/")
    return re.sub(r"\s+", "", s)


def roc_to_period(date: str) -> str | None:
    """'115-08-00' → '2026-08'; yearly/half-year rows ('115-00-00') → None."""
    m = re.fullmatch(r"(\d{2,3})-(\d{2})-\d{2}", str(date or "").strip())
    if not m:
        raise ValueError(f"unexpected period {date!r}")
    month = int(m.group(2))
    if not 1 <= month <= 12:
        return None
    return f"{int(m.group(1)) + 1911}-{month:02d}"


def period_to_roc(period: str) -> str:
    y, m = int(period[:4]), int(period[5:7])
    return f"{y - 1911}-{m:02d}-00"


def parse_count(v) -> int:
    """'31,361 ' → 31361; '-' / '' → 0 (THB prints '-' for none)."""
    s = str(v if v is not None else "").strip()
    if s in ("", "-", "－"):
        return 0
    s = s.replace(",", "")
    if not re.fullmatch(r"\d+", s):
        raise ValueError(f"unexpected cell value {v!r}")
    return int(s)


def months_between(a: str, b: str) -> list[str]:
    out = []
    y, m = int(a[:4]), int(a[5:7])
    while f"{y}-{m:02d}" <= b:
        out.append(f"{y}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def shift_month(p: str, k: int) -> str:
    y, m = int(p[:4]), int(p[5:7]) - 1 + k
    return f"{y + m // 12}-{m % 12 + 1:02d}"


def display_brand(name: str) -> str:
    if name in BRAND_NAMES:
        return BRAND_NAMES[name]
    if name.isascii() and name.upper() == name and name not in ACRONYMS:
        return "-".join(w.capitalize() for w in name.split("-"))
    return name


# ── the database page (discovery) ──────────────────────────────────────────

def parse_display_page(page: str) -> dict:
    """{'newest': 'YYYY-MM', 'columns': {label: id}, 'codes': {label: id}}
    from a Display?Seq=N page. Labels come from the <label for=…> of each
    checkbox of the "設定統計項" (items) and "設定複分類" (fuel / brand) lists."""
    labels = {}
    for for_id, text in re.findall(r'<label[^>]*\bfor="([^"]+)"[^>]*>(.*?)</label>', page, re.S):
        labels[for_id] = norm_label(re.sub(r"<[^>]+>", "", text))

    def boxes(cls: str) -> dict[str, str]:
        out = {}
        for tag in re.findall(r"<input\b[^>]*>", page):
            if not re.search(r'class="[^"]*\b' + cls + r'\b', tag):
                continue
            value = re.search(r'\bvalue="([^"]*)"', tag)
            ident = re.search(r'\bid="([^"]*)"', tag)
            if value and ident and ident.group(1) in labels:
                out.setdefault(labels[ident.group(1)], value.group(1))
        return out

    picker = re.search(r'id="select-period-start".*?</select>', page, re.S)
    newest = None
    if picker:
        for value in re.findall(r'<option value="(\d{2,3}-\d{2}-\d{2})"', picker.group(0)):
            newest = roc_to_period(value)
            if newest:
                break
    return {"newest": newest, "columns": boxes("checkbox-set-column"),
            "codes": boxes("checkbox-set-code-list-value")}


def parse_display_json(doc: dict, column_id: str,
                       code_names: dict[str, str]) -> dict[str, dict[str, int]]:
    """Display.json → {period: {code label: count}} for one queried item.
    `code_names` maps code id → expected label; the JSON's own nameMapping
    must agree (a relabelled id is schema drift)."""
    mapping = (doc.get("nameMapping") or {}).get("codeListMappings") or {}
    got_names = {}
    for lst in mapping.values():
        for cid, name in (lst.get("nameMappings") or {}).items():
            got_names[str(cid)] = norm_label(name)
    for cid, want in code_names.items():
        if cid in got_names and got_names[cid] != norm_label(want):
            raise SystemExit(f"Schema drift: code {cid} is {got_names[cid]!r} in the JSON, "
                             f"{want!r} on the page — not writing.")
    col_names = {str(k): norm_label(v) for k, v in
                 ((doc.get("nameMapping") or {}).get("columnNameMappings") or {}).items()}
    out: dict[str, dict[str, int]] = {}
    for row in doc.get("data") or []:
        period = roc_to_period(row.get("date"))
        if period is None:
            continue
        cells = {}
        for key, value in row.items():
            m = re.fullmatch(r"Column_(\d+)_\d+\.(\d+)", key)
            if not m:
                continue
            if m.group(1) != str(column_id):
                raise SystemExit(f"Display.json returned item {m.group(1)} "
                                 f"({col_names.get(m.group(1))}) — asked for {column_id}.")
            cid = m.group(2)
            name = code_names.get(cid) or got_names.get(cid) or f"code {cid}"
            cells[norm_label(name)] = parse_count(value)
        out[period] = cells
    return out


# ── network ────────────────────────────────────────────────────────────────

class Source:
    """Live access to statis.motc.gov.tw, or a saved dump (--from-dir).
    Every response read live is also written to --dump-dir when given."""

    def __init__(self, from_dir: str = "", dump_dir: str = ""):
        self.from_dir = Path(from_dir) if from_dir else None
        self.dump_dir = Path(dump_dir) if dump_dir else None
        self.session = requests.Session()
        self.session.headers.update(HTTP_HEADERS)
        if self.dump_dir:
            self.dump_dir.mkdir(parents=True, exist_ok=True)

    def _get(self, url: str, params: dict | None = None) -> requests.Response:
        last = None
        for attempt in range(HTTP_TRIES):
            try:
                r = self.session.get(url, params=params, timeout=HTTP_TIMEOUT)
                r.raise_for_status()
                return r
            except requests.RequestException as e:
                last = e
                wait = 15 * 2 ** attempt
                print(f"  {url.rsplit('/', 1)[-1][:40]}: {type(e).__name__} — retry in {wait}s",
                      flush=True)
                if attempt + 1 < HTTP_TRIES:
                    time.sleep(wait)
        raise SystemExit(f"statis.motc.gov.tw unreachable after {HTTP_TRIES} tries: {last}")

    def _saved(self, name: str) -> str:
        path = self.from_dir / name
        if not path.exists():
            raise SystemExit(f"{path} missing in --from-dir")
        return path.read_text(encoding="utf-8")

    def _dump(self, name: str, text: str) -> None:
        if self.dump_dir:
            (self.dump_dir / name).write_text(text, encoding="utf-8")

    def page(self, seq: int) -> str:
        name = f"display_{seq}.html"
        if self.from_dir:
            return self._saved(name)
        text = self._get(f"{BASE}/Display", {"Seq": seq}).text
        self._dump(name, text)
        return text

    def publish_date(self, seq: int) -> str:
        name = f"publish_{seq}.json"
        if self.from_dir:
            path = self.from_dir / name
            text = path.read_text(encoding="utf-8") if path.exists() else "{}"
        else:
            try:
                text = self._get(f"{BASE}/DisplayPublishDate.json", {"seq": seq}).text
            except SystemExit:
                return ""
            self._dump(name, text)
        try:
            return (json.loads(text).get("publishDateIso") or "")[:10]
        except ValueError:
            return ""

    def table(self, seq: int, column_id: str, code_ids: list[str],
              first: str, last: str, name: str) -> dict:
        fname = f"{name}.json"
        if self.from_dir:
            return json.loads(self._saved(fname))
        params = {"Seq": seq, "Start": period_to_roc(first), "End": period_to_roc(last),
                  "ShowYear": "false", "ShowMonth": "true", "ShowQuarter": "false",
                  "ShowHalfYear": "false", "Mode": "0", "ColumnValues": column_id,
                  "CodeListValues": "_".join(code_ids)}
        r = self._get(f"{BASE}/Display.json", params)
        self._dump(fname, r.text)
        return r.json()


# ── aggregation ────────────────────────────────────────────────────────────

def empty_counts() -> dict[str, int]:
    return {k: 0 for k in FUELS + ["TOTAL"]}


def to_counts(cells: dict[str, int]) -> tuple[dict[str, int], dict[str, int]]:
    """One month's {fuel label: n} → (CSV counts, {unknown label: n})."""
    c = empty_counts()
    unknown = {}
    for label, n in cells.items():
        if label == FUEL_TOTAL:
            c["TOTAL"] = n
        elif label in FUEL_COLUMN:
            c[FUEL_COLUMN[label]] += n
        else:
            c["OTHERS"] += n
            if n:
                unknown[label] = n
    return c, unknown


def check_month(period: str, variant: str, cells: dict[str, int]) -> list[str]:
    problems = []
    if FUEL_TOTAL not in cells:
        problems.append(f"{period} {variant}: no 總計 cell")
    missing = [f for f in FUEL_COLUMN if f not in cells]
    if missing:
        problems.append(f"{period} {variant}: fuel cells missing {missing}")
    parts = sum(n for k, n in cells.items() if k != FUEL_TOTAL)
    if FUEL_TOTAL in cells and parts != cells[FUEL_TOTAL]:
        problems.append(f"{period} {variant}: fuels sum to {parts:,}, 總計 is "
                        f"{cells[FUEL_TOTAL]:,}")
    return problems


def within_tolerance(a: int, b: int) -> bool:
    return abs(a - b) <= max(XCHECK_ABS_TOL, XCHECK_REL_TOL * max(a, b))


def cross_check(fuel_totals: dict[str, dict[str, int]],
                brand_totals: dict[str, dict[str, int]],
                periods: list[str]) -> tuple[int, list[str], list[str]]:
    """Compare each variant's TOTAL with the brand table's 廠牌別總計 →
    (months compared, small differences, real mismatches)."""
    compared, small, bad = 0, [], []
    for v, per in fuel_totals.items():
        for p in periods:
            if p not in per:
                continue
            b = brand_totals.get(v, {}).get(p)
            if b is None:
                bad.append(f"{p} {v}: no brand-table total")
                continue
            compared += 1
            a = per[p]
            if a != b:
                msg = f"{p} {v}: fuel table {a:,} vs brand table {b:,}"
                (small if within_tolerance(a, b) else bad).append(msg)
    return compared, small, bad


# ── CSV line-level upsert (invariant 2) ────────────────────────────────────

def fmt(v: int) -> str:
    return f"{float(v):.1f}"


def render_line(period: str, variant: str, counts: dict[str, int], notes: str = "") -> str:
    buf = io.StringIO()
    csv.writer(buf, lineterminator="").writerow(
        [period, "monthly", variant, SOURCE]
        + [fmt(counts[k]) for k in FUELS + ["TOTAL"]] + [notes])
    return buf.getvalue()


def read_csv_lines(path: Path) -> tuple[str, list[str]]:
    if not path.exists():
        return ",".join(CSV_COLUMNS), []
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines:
        return ",".join(CSV_COLUMNS), []
    return lines[0], lines[1:]


def line_key(line: str) -> tuple[str, str]:
    f = next(csv.reader([line]))
    return f[0], f[2]


def line_source(line: str) -> str:
    return next(csv.reader([line]))[3]


def upsert_lines(path: Path, updates: dict[tuple[str, str], str],
                 force: bool) -> dict[str, int]:
    """Replace/insert only the given (period, variant) lines; every other
    line is written back byte-for-byte. Keeps rows sorted by period."""
    header, lines = read_csv_lines(path)
    if header.split(",") != CSV_COLUMNS:
        sys.exit(f"{path}: unexpected header {header!r}")
    stats = {"added": 0, "updated": 0, "unchanged": 0, "skipped": 0}
    index = {line_key(l): i for i, l in enumerate(lines)}
    for key, new in sorted(updates.items()):
        if key in index:
            old = lines[index[key]]
            if old == new:
                stats["unchanged"] += 1
            elif line_source(old) != SOURCE and not force:
                stats["skipped"] += 1
            else:
                lines[index[key]] = new
                stats["updated"] += 1
        else:
            lines.append(new)
            stats["added"] += 1
    if stats["added"]:
        lines.sort(key=line_key)
    if stats["added"] or stats["updated"]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join([header] + lines) + "\n", encoding="utf-8")
    return stats


def existing_periods(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    with open(path, newline="", encoding="utf-8") as f:
        return {r["period"]: r for r in csv.DictReader(f)}


def revisions(path: Path, updates: dict[tuple[str, str], str]) -> list[str]:
    """Human-readable list of existing rows that `updates` would change."""
    _, lines = read_csv_lines(path)
    old = {line_key(l): l for l in lines}
    out = []
    for key, new in sorted(updates.items()):
        if key not in old or old[key] == new:
            continue
        a = dict(zip(CSV_COLUMNS, next(csv.reader([old[key]]))))
        b = dict(zip(CSV_COLUMNS, next(csv.reader([new]))))
        diffs = [f"{c} {float(a[c] or 0):g}→{float(b[c]):g}" for c in FUELS + ["TOTAL"]
                 if a.get(c) != b.get(c)]
        if a.get("source") != b.get("source"):
            diffs.append(f"source `{a.get('source')}`→`{b.get('source')}`")
        out.append(f"{key[0]} {key[1]}: " + ", ".join(diffs))
    return out


def median_fraction(period: str, total: int, have: dict[str, dict]) -> float | None:
    prior = sorted(p for p in have if p < period)[-12:]
    if len(prior) < 6:
        return None
    vals = sorted(float(have[p]["TOTAL"]) for p in prior)
    median = vals[len(vals) // 2]
    return total / median if median else None


# ── brand table → market/taiwan_top.json ───────────────────────────────────

def unlisted(cells: dict[str, int]) -> int:
    """Registrations in the brand table's total that no listed brand carries.
    Since 2026-06 THB itemises a brand the ministry's code list does not have
    (about 600-850 cars a month that used to be in 其他)."""
    total = cells.get(BRAND_TOTAL, 0)
    return max(0, total - sum(n for k, n in cells.items() if k != BRAND_TOTAL))


def build_top(brands: dict[str, dict[str, int]], totals: dict[str, int], target: str) -> dict:
    """Trailing-12-month brand ranking of new passenger cars, every powertrain
    (class ALL — market_top.py). `brands` = {period: {brand label: n}}; the
    brand table's own 其他 (others) and any registrations no listed brand
    carries count towards the total, never into the ranking."""
    monthly = {}
    for p in market_top.month_window(target):
        if p not in brands or not totals.get(p):
            continue
        units = collections.Counter()
        for name, n in brands[p].items():
            if name == BRAND_TOTAL or not n:
                continue
            brand = market_top.REST if name == BRAND_OTHER else display_brand(name)
            units[(market_top.ALL, brand, "")] += n
        if unlisted(brands[p]):
            units[(market_top.ALL, market_top.REST, "")] += unlisted(brands[p])
        monthly[p] = (dict(units), totals[p])
    return market_top.build_top_monthly("Taiwan", SOURCE, target, monthly, TOP_UNIT)


# ── report ─────────────────────────────────────────────────────────────────

def report(target: str, counts: dict[str, dict[str, dict[str, int]]], periods: list[str],
           published: str, xcheck: str, unknown: dict, brands_target: dict[str, int]) -> str:
    out = [f"## Taiwan (THB register via MOTC statistics) — {target}\n",
           f"MOTC publication date of the newest month: {published or 'unknown'}\n",
           "| variant | " + " | ".join(FUELS) + " | TOTAL | BEV share | PHEV+EREV share |",
           "|---|" + "---:|" * (len(FUELS) + 3)]
    for v in counts:
        c = counts[v].get(target)
        if not c:
            continue
        tot = c["TOTAL"] or 1
        out.append(f"| {v} | " + " | ".join(f"{c[k]:,}" for k in FUELS)
                   + f" | {c['TOTAL']:,} | {c['BEV'] / tot:.2%} | "
                     f"{(c['PHEV'] + c['EREV']) / tot:.2%} |")
    out.append(f"\nMonths processed: {periods[0]} → {periods[-1]} ({len(periods)})")
    out.append(f"\n### Cross-check: fuel table vs brand table (Seq 118)\n\n{xcheck}")
    out.append("\n### Fuel categories this script does not know (counted as OTHERS)\n")
    out.append("\n".join(f"- {p} {v}: `{lab}` × {n:,}" for (p, v, lab), n in sorted(unknown.items()))
               or "None.")
    if brands_target:
        marques = collections.Counter()
        for b, n in brands_target.items():
            if b not in (BRAND_TOTAL, BRAND_OTHER) and n:
                marques[display_brand(b)] += n
        out.append(f"\n### Top passenger-car brands in {target} (every powertrain)\n")
        out.append(", ".join(f"{b} {n:,}" for b, n in market_top.ranked(marques, 12)))
        gap = unlisted(brands_target)
        out.append(f"\nOutside the ranking: THB's 其他 (others) "
                   f"{brands_target.get(BRAND_OTHER, 0):,}; in the total but in no listed "
                   f"brand {gap:,}" + (" (a brand the database's code list lacks — see doc 49 §7)"
                                       if gap else "") + ".")
    return "\n".join(out) + "\n"


# ── main ───────────────────────────────────────────────────────────────────

def resolve(discovered: dict, labels: list[str], what: str, seq: int) -> dict[str, str]:
    """{label: id} for the labels this script needs; a missing one aborts."""
    have = discovered[what]
    missing = [l for l in labels if norm_label(l) not in have]
    if missing:
        raise SystemExit(f"Schema drift: Seq {seq} page no longer lists {missing} "
                         f"(it lists {sorted(have)[:40]}) — not writing.")
    return {l: have[norm_label(l)] for l in labels}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--variant", default="all",
                    help=f"all | {' | '.join(VARIANTS)} (default: all)")
    ap.add_argument("--period", default="",
                    help="Newest month to write, YYYY-MM (default: newest published month).")
    ap.add_argument("--backfill", action="store_true",
                    help=f"Re-derive every month from {FIRST_PERIOD} (default: the newest "
                         f"{LOOKBACK_MONTHS} months).")
    ap.add_argument("--force", action="store_true",
                    help="Ignore the self-throttle, the completeness and cross-check "
                         "guards, the unknown-fuel threshold and foreign source strings.")
    ap.add_argument("--from-dir", default="", help="Offline: responses saved by --dump-dir.")
    ap.add_argument("--dump-dir", default="", help="Save every response read to this folder.")
    ap.add_argument("--github-output", default=os.environ.get("GITHUB_OUTPUT"))
    ap.add_argument("--step-summary", default=os.environ.get("GITHUB_STEP_SUMMARY"))
    args = ap.parse_args()

    variants = list(VARIANTS) if args.variant == "all" else [args.variant]
    for v in variants:
        if v not in VARIANTS:
            sys.exit(f"Unknown variant {v!r}. Valid: {list(VARIANTS)} or all.")
    paths = {v: REPO / VARIANTS[v][1] for v in variants}
    have = {v: existing_periods(paths[v]) for v in variants}
    backfill = args.backfill or any(not paths[v].exists() for v in variants)

    src = Source(args.from_dir, args.dump_dir)

    # Step 1 — discovery: the newest month and the ids of every label used.
    fuel_page = parse_display_page(src.page(FUEL_SEQ))
    newest = fuel_page["newest"]
    if not newest:
        sys.exit("No month found in the Seq 104 period picker — page layout changed? "
                 "Not writing.")
    published = src.publish_date(FUEL_SEQ)
    print(f"Newest month in MOTC table {FUEL_SEQ}: {newest} (published {published or '?'})")
    last = min(args.period, newest) if args.period else newest
    if last < FIRST_PERIOD:
        sys.exit(f"--period {last} is before the first month written ({FIRST_PERIOD}).")

    # Step 2 — self-throttle: every CSV already holds the newest month.
    in_csv = all(have[v].get(newest, {}).get("source") == SOURCE for v in variants)
    if in_csv and not backfill and not args.force and not args.period:
        print(f"{newest} already in every Taiwan CSV; nothing to do.")
        return emit(args, set())

    kinds = resolve(fuel_page, [VARIANTS[v][0] for v in variants], "columns", FUEL_SEQ)
    fuel_ids = resolve(fuel_page, [FUEL_TOTAL] + list(FUEL_COLUMN), "codes", FUEL_SEQ)
    # Any further fuel the page lists is queried too: it must show up in the
    # month check (counted as OTHERS), never silently drop out of the sum.
    extra = {l: i for l, i in fuel_page["codes"].items()
             if l not in {norm_label(k) for k in fuel_ids}}
    if extra:
        print(f"::warning title=New THB fuel categories::{sorted(extra)} — counted as OTHERS.")
    code_names = {i: l for l, i in {**fuel_ids, **extra}.items()}

    brand_page = parse_display_page(src.page(BRAND_SEQ))
    brand_kinds = resolve(brand_page, [VARIANTS[v][0] for v in variants], "columns", BRAND_SEQ)
    brand_total_id = resolve(brand_page, [BRAND_TOTAL], "codes", BRAND_SEQ)[BRAND_TOTAL]
    brand_names = {i: l for l, i in brand_page["codes"].items()}

    first = FIRST_PERIOD if backfill else max(FIRST_PERIOD, shift_month(last, 1 - LOOKBACK_MONTHS))
    todo = months_between(first, last)
    print(f"Reading {first} → {last} ({len(todo)} months) for {variants}")

    # Step 3 — the fuel table, one query per vehicle kind.
    counts: dict[str, dict[str, dict[str, int]]] = {}
    unknown: dict[tuple[str, str, str], int] = {}
    problems: list[str] = []
    for v in variants:
        kind = VARIANTS[v][0]
        doc = src.table(FUEL_SEQ, kinds[kind], sorted(code_names, key=int), first, last,
                        f"fuel_{v}")
        months = parse_display_json(doc, kinds[kind], code_names)
        counts[v] = {}
        for p in todo:
            if p not in months:
                problems.append(f"{p} {v}: month missing from Display.json")
                continue
            problems += check_month(p, v, months[p])
            c, unk = to_counts(months[p])
            counts[v][p] = c
            for lab, n in unk.items():
                unknown[(p, v, lab)] = n
        print(f"  {v} ({kind}): {len(counts[v])} months")
    if problems:
        sys.exit("Consistency check failed — not writing:\n  " + "\n  ".join(problems[:30]))
    for p in todo:
        whole_unknown = sum(n for (pp, v, _), n in unknown.items() if pp == p and v == "Whole")
        tot = counts.get("Whole", {}).get(p, {}).get("TOTAL") or 0
        if tot and whole_unknown / tot > MAX_UNKNOWN_FUEL_SHARE and not args.force:
            sys.exit(f"{p}: {whole_unknown:,} passenger cars in fuel categories this script "
                     f"does not map ({whole_unknown / tot:.1%}) — map them in FUEL_COLUMN, "
                     "not writing.")

    # Step 4 — the brand table: totals for the cross-check, brands for Whole.
    brand_totals: dict[str, dict[str, int]] = {}
    whole_brands: dict[str, dict[str, int]] = {}
    for v in variants:
        kind = VARIANTS[v][0]
        ids = sorted(brand_names, key=int) if v == "Whole" else [brand_total_id]
        doc = src.table(BRAND_SEQ, brand_kinds[kind], ids, first, last, f"brand_{v}")
        months = parse_display_json(doc, brand_kinds[kind], brand_names)
        brand_totals[v] = {p: cells.get(norm_label(BRAND_TOTAL), 0) for p, cells in months.items()}
        if v == "Whole":
            whole_brands = months
    compared, small, mism = cross_check({v: {p: c["TOTAL"] for p, c in counts[v].items()}
                                         for v in variants}, brand_totals, todo)
    if mism and not args.force:
        sys.exit("Cross-check against the brand table failed — not writing (--force "
                 "overrides):\n  " + "\n  ".join(mism[:30]))
    xcheck = (f"{compared} variant-month(s) compared ({todo[0]} → {todo[-1]}): "
              + ("every total identical." if not (small or mism) else "")
              + (f" {len(small)} difference(s) within tolerance: " + "; ".join(small[:10])
                 if small else "")
              + (f" {len(mism)} MISMATCHES (forced): " + "; ".join(mism[:10]) if mism else ""))
    print("Cross-check: " + xcheck)

    # Step 5 — completeness guard on a month not yet in the CSVs.
    writable = list(todo)
    if "Whole" in variants and newest not in have["Whole"] and newest in writable:
        frac = median_fraction(newest, counts["Whole"][newest]["TOTAL"], have["Whole"])
        if frac is not None and frac < MIN_MONTH_FRACTION and not backfill and not args.force:
            print(f"::warning title=Taiwan {newest} looks incomplete::Whole TOTAL "
                  f"{counts['Whole'][newest]['TOTAL']:,} is {frac:.0%} of the trailing "
                  "median — not written. Re-run with force if genuine.")
            writable.remove(newest)
    if not writable:
        print("No month to write.")
        return emit(args, set())
    target = max(writable)

    changed: set[str] = set()
    revised: list[str] = []
    for v in variants:
        updates = {(p, v): render_line(p, v, counts[v][p]) for p in writable
                   if counts[v][p]["TOTAL"] > 0}
        revised += revisions(paths[v], updates)
        stats = upsert_lines(paths[v], updates, args.force)
        print(f"{VARIANTS[v][1]}: {stats}")
        if stats["added"] or stats["updated"]:
            changed.add(v)
    if revised:
        print(f"::notice title=Earlier months revised by THB::{len(revised)} row(s) changed — "
              "see the step summary.")

    def refresh_top() -> None:
        top = build_top(whole_brands, {p: c["TOTAL"] for p, c in counts["Whole"].items()}, target)
        print(f"{TOP_PATH.relative_to(REPO)}: "
              f"{'updated' if market_top.write_top(top, TOP_PATH) else 'unchanged'}")
    if "Whole" in variants:
        market_top.guarded(refresh_top)

    rep = report(target, counts, todo, published, xcheck, unknown,
                 whole_brands.get(target, {}))
    rep += "\n### Earlier months revised in this run\n\n"
    rep += ("\n".join(f"- {r}" for r in revised) if revised else "None.") + "\n"
    print("\n" + rep)
    if args.step_summary:
        with open(args.step_summary, "a", encoding="utf-8") as fh:
            fh.write(rep)
    return emit(args, changed)


def render_list(changed: set[str]) -> list[str]:
    return sorted(v for v in changed if v in RENDERED_VARIANTS)


def emit(args, changed: set[str]) -> int:
    if args.github_output:
        with open(args.github_output, "a", encoding="utf-8") as f:
            f.write(f"changed={'true' if changed else 'false'}\n")
            f.write(f"changed_variants={json.dumps(render_list(changed))}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
