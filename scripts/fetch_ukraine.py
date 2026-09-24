#!/usr/bin/env python3
"""
Fetch Ukraine registration data from the Ministry of Internal Affairs' open
vehicle-registration register and upsert data/Ukraine*.csv
(Whole + Private + Industry + Used + Vans).

Source
------
The MIA's Main Service Centre (ГСЦ МВС) publishes every registration
operation of the national vehicle register as one CSV record on the national
open-data portal (CKAN) — free, no login, no key:

    https://data.gov.ua/dataset/0ffd8b75-0628-48cc-952a-9302f9799ec0
    «Відомості про транспортні засоби та їх власників»

One zip per year (`reestrTZYYYY`, one CSV inside); the current year's zip is
re-uploaded monthly and its member is named after the cut-off date
(`reestrtz31.08.2026.csv` = everything up to 31 Aug 2026). Resources are
discovered through `package_show`, never by hard-coded URL — resource ids
change on re-upload.

Every record carries the operation code (`OPER_CODE`), the date (`D_REG`),
brand, model, vehicle kind (`KIND`: ЛЕГКОВИЙ = passenger car, ВАНТАЖНИЙ =
goods vehicle, …), gross weight (`TOTAL_WEIGHT`), owner type (`PERSON`:
P = natural person, J = legal person) and — unlike Argentina's DNRPA — a
**fuel field** (`FUEL`). Nothing is classified from model names.

Record → CSV
------------
Only *first registrations* count, split by the MIA's own operation codes:

  NEW_OPS   105 new vehicle bought from a dealer, imported
             99 new vehicle bought from a dealer, made in Ukraine
             72 new vehicle imported by the owner (customs declaration)
            180 184 185  new vehicle first registered by a business
             74  75 102  new vehicle — humanitarian import / experimental
  USED_OPS  100 used vehicle bought from a dealer, imported
             70  71 used vehicle imported by the owner (customs docs)
             76  77 used vehicle — humanitarian import
            172 first registration of imported passenger cars (2018 wave)

Code 105 only exists from 2018-08; before that, dealer sales of new *and*
used cars shared code 100 (82 % were ≤1 year old, 12 % were 4+ years old),
so the new/used split cannot be made from the source's own codes. The
series therefore starts 2018-09, the first full month of the current code
set (docs/architecture/40-source-ukraine.md §2).

  Whole     data/Ukraine.csv            KIND = ЛЕГКОВИЙ ∧ NEW_OPS   (EU M1)
  Private   data/Ukraine_Private.csv    Whole ∧ PERSON = P
  Industry  data/Ukraine_Industry.csv   Whole ∧ PERSON = J  (P + J = Whole)
  Used      data/Ukraine_Used.csv       KIND = ЛЕГКОВИЙ ∧ USED_OPS (imports)
  Vans      data/Ukraine_Vans.csv       KIND = ВАНТАЖНИЙ ∧ TOTAL_WEIGHT ≤ 3500
                                        ∧ NEW_OPS              (EU N1)

Fuel → columns
--------------
  ЕЛЕКТРО                                 → BEV
  ЕЛЕКТРО АБО БЕНЗИН / … АБО ДИЗЕЛЬНЕ
  ПАЛИВО / БЕНЗИН, ГАЗ АБО ЕЛЕКТРО /
  ГАЗ ТА ЕЛЕКТРО                          → HEV  — ONE combined hybrid bucket:
                                            the register does not separate
                                            plug-in, full and mild hybrids
                                            (Türkiye/Georgia convention: HEV
                                            column, no PHEV column; charted as
                                            "Hybrid", counted inside ICE)
  БЕНЗИН                                  → PETROL
  ДИЗЕЛЬНЕ ПАЛИВО                         → DIESEL
  БЕНЗИН АБО ГАЗ, ГАЗ, … АБО ГАЗ, blank,
  НЕ ВИЗНАЧЕНО, ВОДЕНЬ, …                 → OTHERS

Governance (every real run)
---------------------------
* required columns must resolve (the header changed shape in 2026 — the op
  code and name now share one column); a missing one aborts the run;
* every yearly file in range must yield records; a zero-record year aborts;
* a month is only written once the file's cut-off date covers all of it;
* a new month below 40 % of the trailing-12 median is treated as an
  incomplete upload and not written (--force overrides);
* unknown fuel strings above 2 % of the month's Whole abort the run (schema
  drift); below that they go to OTHERS and are listed in the step summary;
* first-registration-like operation codes outside NEW_OPS/USED_OPS are
  listed in the step summary (the net for new codes the MIA introduces);
* Private + Industry must equal Whole (records with a blank PERSON are
  reported, never silently dropped from Whole).

Writes are line-level upserts keyed on (period, variant) (invariant 2); a
row whose `source` is not ours is never overwritten without --force.
Also writes market/ukraine_top.json (top BEV / Hybrid brands and models,
trailing 12 months, Whole) via scripts/market_top.py.

Usage
-----
    python scripts/fetch_ukraine.py                    # previous month
    python scripts/fetch_ukraine.py --period 2026-08
    python scripts/fetch_ukraine.py --backfill         # 2018-09 → now
    python scripts/fetch_ukraine.py --from-agg agg.csv.gz   # offline

`--from-agg` reads a pre-aggregated CSV (month, op, kind, wt, fuel, person,
brand, model, n — extra columns ignored) instead of downloading; used by the
tests and for offline rebuilds.
"""

from __future__ import annotations

import argparse
import collections
import csv
import gzip
import io
import itertools
import json
import os
import re
import sys
import zipfile
from datetime import date
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import market_top  # noqa: E402

SOURCE = "MIA HSC (data.gov.ua)"
PACKAGE_URL = ("https://data.gov.ua/api/3/action/package_show"
               "?id=0ffd8b75-0628-48cc-952a-9302f9799ec0")
BACKFILL_FROM_DEFAULT = "2018-09"   # first full month of op code 105

VARIANT_CSV = {
    "Whole":    "data/Ukraine.csv",
    "Private":  "data/Ukraine_Private.csv",
    "Industry": "data/Ukraine_Industry.csv",
    "Used":     "data/Ukraine_Used.csv",
    "Vans":     "data/Ukraine_Vans.csv",
}
RENDERED_VARIANTS = tuple(VARIANT_CSV)

FUELS = ["BEV", "HEV", "PETROL", "DIESEL", "OTHERS"]
CSV_COLUMNS = (["period", "time_interval", "variant", "source"]
               + FUELS + ["TOTAL", "notes"])

NEW_OPS = frozenset({105, 99, 72, 180, 184, 185, 74, 75, 102})
USED_OPS = frozenset({100, 70, 71, 76, 77, 172})

KIND_M1 = "ЛЕГКОВИЙ"
KIND_GOODS = "ВАНТАЖНИЙ"
N1_MAX_KG = 3500

FUEL_MAP = {
    "ЕЛЕКТРО": "BEV",
    "ЕЛЕКТРО АБО БЕНЗИН": "HEV",
    "ЕЛЕКТРО АБО ДИЗЕЛЬНЕ ПАЛИВО": "HEV",
    "БЕНЗИН, ГАЗ АБО ЕЛЕКТРО": "HEV",
    "ГАЗ ТА ЕЛЕКТРО": "HEV",
    "БЕНЗИН": "PETROL",
    "ДИЗЕЛЬНЕ ПАЛИВО": "DIESEL",
    "БЕНЗИН АБО ГАЗ": "OTHERS",
    "ГАЗ": "OTHERS",
    "ДИЗЕЛЬНЕ ПАЛИВО АБО ГАЗ": "OTHERS",
    "ВОДЕНЬ": "OTHERS",          # hydrogen — a handful of records
    "НЕ ВИЗНАЧЕНО": "OTHERS",    # "not determined"
    "ВІДСУТНЄ": "OTHERS",        # "absent"
    "": "OTHERS", "NULL": "OTHERS", ".": "OTHERS",
}

# Operation names that smell like a first registration. Codes outside
# NEW_OPS/USED_OPS matching this are reported (not counted) every run.
FIRST_REG_HINT = re.compile(r"ПЕРВИНН|З-ЗА КОРДОНУ|НОВ(ОГО|ИХ) ТЗ")

HTTP_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (compatible; LeRaffl-Gallery/1.0; "
                   "+https://leraffl.github.io/LeRaffl-Gallery/)"),
}
MIN_MONTH_FRACTION = 0.4
MAX_UNKNOWN_FUEL_SHARE = 0.02

REPO = Path(__file__).resolve().parent.parent
TOP_PATH = market_top.MARKET_DIR / "ukraine_top.json"
TOP_UNIT = ("registrations (brand = BRAND, model = MODEL as recorded by the "
            "MIA register; Hybrid = the register's combined hybrid fuel value)")


# ── scope ──────────────────────────────────────────────────────────────────

def norm(s) -> str:
    return " ".join(str(s or "").replace(" ", " ").split()).upper()


def fuel_class(fuel: str) -> str | None:
    """Gallery column for a FUEL string; None if the string is unknown."""
    return FUEL_MAP.get(norm(fuel))


def weight_bucket(total_weight: str) -> str:
    try:
        w = float(str(total_weight).replace(",", "."))
    except ValueError:
        return "?"
    if w <= 0:
        return "?"
    return "le3500" if w <= N1_MAX_KG else "gt3500"


def variants_for(op: int, kind: str, wt: str, person: str) -> list[str]:
    kind = norm(kind)
    if kind == KIND_M1:
        if op in NEW_OPS:
            p = norm(person)[:1]
            return ["Whole"] + (["Private"] if p == "P"
                                else ["Industry"] if p == "J" else [])
        if op in USED_OPS:
            return ["Used"]
        return []
    if kind == KIND_GOODS and op in NEW_OPS and wt == "le3500":
        return ["Vans"]
    return []


def parse_op(raw: str) -> tuple[int | None, str]:
    """'105' or '105 - ПЕРВИННА …' → (105, 'ПЕРВИННА …')."""
    m = re.match(r"\s*(\d+)\s*(?:-\s*(.*))?$", raw or "")
    if not m:
        return None, ""
    return int(m.group(1)), (m.group(2) or "").strip()


def parse_period(d: str) -> str | None:
    d = (d or "").strip()
    m = re.match(r"(\d{4})-(\d\d)-\d\d", d)
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    m = re.match(r"(\d\d)\.(\d\d)\.(\d{2}|\d{4})\b", d)
    if m:
        y = m.group(3)
        return f"{'20' + y if len(y) == 2 else y}-{m.group(2)}"
    return None


def parse_day(d: str) -> date | None:
    d = (d or "").strip()
    m = re.match(r"(\d{4})-(\d\d)-(\d\d)", d)
    if m:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.match(r"(\d\d)\.(\d\d)\.(\d{2}|\d{4})\b", d)
    if m:
        y = m.group(3)
        return date(int("20" + y if len(y) == 2 else y), int(m.group(2)), int(m.group(1)))
    return None


def empty_counts() -> dict[str, int]:
    return {k: 0 for k in FUELS + ["TOTAL"]}


class Aggregator:
    def __init__(self, backfill_from: str = BACKFILL_FROM_DEFAULT) -> None:
        self.backfill_from = backfill_from
        self.counts: dict[str, dict[str, dict[str, int]]] = \
            collections.defaultdict(lambda: collections.defaultdict(empty_counts))
        # (period, class, brand, model) -> units, Whole only (market top)
        self.units: collections.Counter = collections.Counter()
        self.unknown_fuel: collections.Counter = collections.Counter()   # (period, fuel)
        self.unmapped_ops: collections.Counter = collections.Counter()   # (period, code, name, kind)
        self.blank_person: collections.Counter = collections.Counter()   # period
        self.op_names: dict[int, str] = {}
        self.max_day: dict[str, date] = {}    # period -> newest record date seen

    def add(self, period: str | None, op: int | None, op_name: str, kind: str,
            wt: str, fuel: str, person: str, brand: str, model: str,
            n: int = 1) -> None:
        if not period or op is None or period < self.backfill_from:
            return
        if op_name and op not in self.op_names:
            self.op_names[op] = op_name
        vs = variants_for(op, kind, wt, person)
        if not vs:
            name = op_name or self.op_names.get(op, "")
            if (op not in NEW_OPS and op not in USED_OPS
                    and norm(kind) in (KIND_M1, KIND_GOODS)
                    and FIRST_REG_HINT.search(norm(name))):
                self.unmapped_ops[(period, op, name[:80], norm(kind))] += n
            return
        cls = fuel_class(fuel)
        if cls is None:
            self.unknown_fuel[(period, norm(fuel))] += n
            cls = "OTHERS"
        for v in vs:
            c = self.counts[period][v]
            c[cls] += n
            c["TOTAL"] += n
        if vs[0] == "Whole":
            if len(vs) == 1:
                self.blank_person[period] += n
            b = market_top.clean(brand)
            self.units[(period, cls, b, market_top.strip_brand(b, market_top.clean(model)))] += n


# ── download / parse ───────────────────────────────────────────────────────

REQUIRED = ("D_REG", "KIND", "FUEL", "PERSON", "BRAND", "MODEL", "TOTAL_WEIGHT")


def resolve_columns(header: list[str]) -> dict[str, int]:
    """Map logical fields to column indexes. The 2026 file merged the op code
    and name into one column (`CD.OPER_CODE||'-'||CD.OPERAS`); earlier files
    have OPER_CODE + OPER_NAME. A missing required field is fatal."""
    hdr = [h.strip().strip('"').upper() for h in header]
    ix = {h: i for i, h in enumerate(hdr)}
    out = {}
    op = next((i for i, h in enumerate(hdr) if "OPER_CODE" in h), None)
    if op is None:
        raise SystemExit(f"schema drift: no OPER_CODE column in {hdr}")
    out["OP"] = op
    if "OPER_NAME" in ix:
        out["OP_NAME"] = ix["OPER_NAME"]
    missing = [k for k in REQUIRED if k not in ix]
    if missing:
        raise SystemExit(f"schema drift: missing columns {missing} in {hdr}")
    out.update({k: ix[k] for k in REQUIRED})
    return out


def add_rows(rows, agg: Aggregator) -> tuple[int, date | None, int]:
    """Feed csv rows (header first) into the aggregator. Returns (records,
    newest D_REG day, records whose date or op code did not parse)."""
    it = iter(rows)
    col = resolve_columns(next(it))
    n = bad = 0
    newest: date | None = None
    for row in it:
        n += 1
        get = lambda k: row[col[k]] if col.get(k) is not None and col[k] < len(row) else ""
        op, name = parse_op(get("OP"))
        if "OP_NAME" in col:
            name = get("OP_NAME").strip()
        day = parse_day(get("D_REG"))
        if op is None or day is None:
            bad += 1
            continue
        if newest is None or day > newest:
            newest = day
        period = f"{day.year:04d}-{day.month:02d}"
        if day > agg.max_day.get(period, date.min):
            agg.max_day[period] = day
        agg.add(period, op, name, get("KIND"),
                weight_bucket(get("TOTAL_WEIGHT")), get("FUEL"), get("PERSON"),
                get("BRAND"), get("MODEL"))
    return n, newest, bad


def sniff_encoding(z: zipfile.ZipFile, name: str) -> str:
    """utf-8 or cp1251, decided on the first 4 MB (a multi-byte character cut
    at the boundary is tolerated). Decided up front, never mid-stream: a
    fallback after rows were already counted would count them twice."""
    with z.open(name) as raw:
        head = raw.read(4 << 20)
    try:
        head.decode("utf-8")
        return "utf-8-sig"
    except UnicodeDecodeError as e:
        if e.start >= len(head) - 3:
            return "utf-8-sig"
        return "cp1251"


def iter_member(z: zipfile.ZipFile, name: str):
    """csv rows of one zip member (header row first)."""
    enc = sniff_encoding(z, name)
    with z.open(name) as raw:
        text = io.TextIOWrapper(raw, encoding=enc, newline="")
        head = text.readline()
        delim = ";" if head.count(";") > head.count(",") else ","
        try:
            yield from csv.reader(itertools.chain([head], text), delimiter=delim)
        except UnicodeDecodeError as e:
            raise SystemExit(f"{name}: undecodable bytes as {enc} past the sniffed "
                             f"prefix ({e}) — not writing.")


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HTTP_HEADERS)
    return s


def year_of_resource(res: dict) -> int | None:
    for field in (res.get("name") or "", res.get("url") or ""):
        m = re.search(r"reestr_?tz_?(20\d\d)", field, re.I) or \
            re.search(r"z0101(20\d\d)", field)
        if m:
            return int(m.group(1))
    return None


def list_year_urls(session: requests.Session) -> dict[int, str]:
    r = session.get(PACKAGE_URL, timeout=120)
    r.raise_for_status()
    best: dict[int, tuple[str, str]] = {}
    for res in r.json()["result"]["resources"]:
        y = year_of_resource(res)
        if y is None:
            continue
        stamp = res.get("last_modified") or res.get("created") or ""
        if y not in best or stamp > best[y][0]:
            best[y] = (stamp, res["url"])
    return {y: u for y, (_, u) in best.items()}


def ingest_year(session, url: str, agg: Aggregator) -> tuple[int, date | None, date | None]:
    r = session.get(url, timeout=1800)
    r.raise_for_status()
    z = zipfile.ZipFile(io.BytesIO(r.content))
    members = [i.filename for i in z.infolist() if not i.is_dir()]
    print(f"  {url.rsplit('/', 1)[-1]}: members {members}")
    total, newest, cutoff = 0, None, None
    for name in members:
        k, last, bad = add_rows(iter_member(z, name), agg)
        cutoff = cutoff_from_name(name) or cutoff
        print(f"  {name}: {k:,} records, newest {last}, cut-off in name "
              f"{cutoff_from_name(name)}, unparsed {bad:,}")
        if k and bad / k > 0.001:
            raise SystemExit(f"{name}: {bad:,} of {k:,} records have no parsable "
                             "date or op code — schema drift, not writing.")
        total += k
        if last and (newest is None or last > newest):
            newest = last
    if cutoff and newest and newest > cutoff:
        raise SystemExit(f"{url}: records dated {newest} after the cut-off "
                         f"{cutoff} in the file name — not writing.")
    return total, newest, cutoff


def ingest_agg_file(path: str, agg: Aggregator) -> None:
    opener = gzip.open if path.endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            op, name = parse_op(row["op"])
            agg.add(row["month"], op, name, row["kind"], row["wt"], row["fuel"],
                    row["person"], row["brand"], row["model"], int(row["n"]))


# ── CSV line-level upsert (invariant 2) ────────────────────────────────────

def fmt(v: int) -> str:
    return f"{float(v):.1f}"


def render_line(period: str, variant: str, counts: dict[str, int],
                notes: str = "") -> str:
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


# ── checks ─────────────────────────────────────────────────────────────────

def previous_month(today: date) -> str:
    if today.month == 1:
        return f"{today.year - 1}-12"
    return f"{today.year}-{today.month - 1:02d}"


def cutoff_from_name(name: str) -> date | None:
    """`reestrtz31.08.2026.csv` → 2026-08-31: the MIA names the current-year
    member after the day the extract was cut."""
    m = re.search(r"(\d\d)\.(\d\d)\.(\d{4})", name)
    if not m:
        return None
    try:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    except ValueError:
        return None


# The name date is the day the extract was cut and is NOT included (the 2025
# file "reestrtz31.12.2025" ends on 30 Dec; the 2026 file "31.08.2026" on 30
# Aug). A month whose last day(s) are missing is still written — its row
# carries a note — as long as no more than this many days are missing; the
# next upload re-derives it and the note disappears.
MONTH_END_SLACK_DAYS = 3


def month_end(period: str) -> date:
    y, m = int(period[:4]), int(period[5:7])
    nxt = date(y + (m == 12), m % 12 + 1, 1)
    return date.fromordinal(nxt.toordinal() - 1)


def last_included_day(newest: date | None, cutoff: date | None) -> date | None:
    if cutoff:
        day_before = date.fromordinal(cutoff.toordinal() - 1)
        # records dated ON the cut day would mean the date is inclusive
        return max(day_before, newest) if newest else day_before
    return newest


def complete_through(newest: date | None, cutoff: date | None = None) -> str | None:
    """Newest month the file covers up to at most MONTH_END_SLACK_DAYS before
    its last day."""
    d = last_included_day(newest, cutoff)
    if d is None:
        return None
    period = f"{d.year:04d}-{d.month:02d}"
    if (month_end(period) - d).days <= MONTH_END_SLACK_DAYS:
        return period
    y, m = d.year, d.month - 1
    if m == 0:
        y, m = y - 1, 12
    return f"{y:04d}-{m:02d}"


def gap_note(period: str, agg: "Aggregator") -> str:
    """Factual note for a month whose newest record is before its last day."""
    last = agg.max_day.get(period)
    if last is None or last >= month_end(period):
        return ""
    return (f"MIA extract has no records after {last.isoformat()} "
            f"(month ends {month_end(period).isoformat()}); re-derived on the next upload")


def looks_incomplete(period: str, total: int, have: dict[str, dict]) -> bool:
    prior = sorted(p for p in have if p < period)[-12:]
    if len(prior) < 6:
        return False
    vals = sorted(float(have[p]["TOTAL"]) for p in prior)
    median = vals[len(vals) // 2]
    return total < MIN_MONTH_FRACTION * median


def check_consistency(agg: Aggregator, periods: list[str]) -> list[str]:
    """Private + Industry + blank-PERSON must equal Whole, fuels must sum to
    TOTAL. Returns problems (empty = fine)."""
    problems = []
    for p in periods:
        c = agg.counts[p]
        w = c["Whole"]["TOTAL"]
        pi = c["Private"]["TOTAL"] + c["Industry"]["TOTAL"] + agg.blank_person[p]
        if w != pi:
            problems.append(f"{p}: Private+Industry+blank {pi} != Whole {w}")
        for v, cc in c.items():
            if sum(cc[k] for k in FUELS) != cc["TOTAL"]:
                problems.append(f"{p} {v}: fuels do not sum to TOTAL")
    return problems


def build_top(agg: Aggregator, target: str) -> dict:
    window = set(market_top.month_window(target))
    units = collections.Counter()
    for (p, cls, b, m), n in agg.units.items():
        if p in window:
            units[(cls, b, m)] += n
    total = sum(agg.counts[p]["Whole"]["TOTAL"] for p in window if p in agg.counts)
    return market_top.build_top("Ukraine", SOURCE, target, units, total, TOP_UNIT)


def report(agg: Aggregator, target: str, variants: list[str]) -> str:
    t = agg.counts[target]
    out = [f"## Ukraine (MIA register, data.gov.ua) — {target}\n",
           "| variant | BEV | Hybrid | PETROL | DIESEL | OTHERS | TOTAL | BEV share |",
           "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for v in variants:
        c = t[v]
        tot = c["TOTAL"] or 1
        out.append(f"| {v} | " + " | ".join(f"{c[k]:,}" for k in FUELS)
                   + f" | {c['TOTAL']:,} | {c['BEV'] / tot:.2%} |")
    brands = collections.Counter()
    for (p, cls, b, m), n in agg.units.items():
        if p == target:
            brands[b] += n
    out.append("\n### Top 10 brands, new passenger cars (cross-check against "
               "Ukrautoprom's monthly release)\n")
    out.append(", ".join(f"{b} {n:,}" for b, n in brands.most_common(10)) or "—")
    unk = {k: n for k, n in agg.unknown_fuel.items() if k[0] == target}
    out.append("\n### Unknown FUEL strings this month (counted as OTHERS)\n")
    out.append("\n".join(f"- `{f or '(blank)'}`: {n:,}" for (_, f), n in unk.items()) or "None.")
    ops = {k: n for k, n in agg.unmapped_ops.items() if k[0] == target}
    out.append("\n### First-registration-like operations NOT counted (review!)\n")
    out.append("\n".join(f"- {code} {name} [{kind}]: {n:,}"
                         for (_, code, name, kind), n in
                         sorted(ops.items(), key=lambda kv: -kv[1])) or "None.")
    out.append(f"\nRecords with blank PERSON in Whole: {agg.blank_person[target]:,}")
    gaps = [(p, gap_note(p, agg)) for p in sorted(agg.max_day) if gap_note(p, agg)
            and p >= agg.backfill_from]
    out.append("\n### Months whose newest record is before the month end (row carries a note)\n")
    out.append("\n".join(f"- {p}: {n}" for p, n in gaps) or "None.")
    return "\n".join(out) + "\n"


# ── main ───────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--variant", default="all",
                    help=f"all | {' | '.join(VARIANT_CSV)} (default: all)")
    ap.add_argument("--period", default="",
                    help="Target month YYYY-MM (default: previous month).")
    ap.add_argument("--backfill", action="store_true",
                    help="Re-derive every month from --backfill-from (downloads "
                         "every yearly file). Implied when a CSV does not exist yet.")
    ap.add_argument("--backfill-from", default=BACKFILL_FROM_DEFAULT)
    ap.add_argument("--force", action="store_true",
                    help="Ignore the self-throttle, the completeness check and "
                         "foreign source strings.")
    ap.add_argument("--from-agg", default="",
                    help="Offline: read a pre-aggregated CSV instead of downloading "
                         "(implies --backfill).")
    ap.add_argument("--github-output", default=os.environ.get("GITHUB_OUTPUT"))
    ap.add_argument("--step-summary", default=os.environ.get("GITHUB_STEP_SUMMARY"))
    args = ap.parse_args()

    if args.backfill_from < BACKFILL_FROM_DEFAULT:
        sys.exit(f"--backfill-from before {BACKFILL_FROM_DEFAULT} is not supported: "
                 "op code 105 does not exist yet, new and used cars share code 100.")
    variants = list(VARIANT_CSV) if args.variant == "all" else [args.variant]
    for v in variants:
        if v not in VARIANT_CSV:
            sys.exit(f"Unknown variant {v!r}. Valid: {list(VARIANT_CSV)} or all.")
    paths = {v: REPO / VARIANT_CSV[v] for v in variants}
    have = {v: existing_periods(paths[v]) for v in variants}

    target = args.period or previous_month(date.today())
    backfill = (args.backfill or bool(args.from_agg)
                or any(not paths[v].exists() for v in variants))

    if not backfill and not args.force and all(
            have[v].get(target, {}).get("source") == SOURCE for v in variants):
        print(f"{target} already fetched from {SOURCE} for {variants}; nothing to do.")
        return emit(args, set())

    agg = Aggregator(args.backfill_from)
    covered: str | None = None
    urls: list[str] = []
    if args.from_agg:
        ingest_agg_file(args.from_agg, agg)
        covered = max(agg.counts) if agg.counts else None
        urls.append(args.from_agg)
    else:
        session = make_session()
        years = list_year_urls(session)
        print("Yearly files on the portal:", {y: u.rsplit('/', 1)[-1] for y, u in sorted(years.items())})
        first = int(args.backfill_from[:4]) if backfill else int(target[:4]) - 1
        newest_all: date | None = None
        cutoff_all: date | None = None
        for year in range(first, int(target[:4]) + 1):
            if year not in years:
                if year < int(target[:4]):
                    sys.exit(f"No yearly file for {year} on the portal — the history "
                             "would have a hole; not writing.")
                print(f"Year {year}: not on the portal yet.")
                continue
            print(f"Year {year}:")
            k, newest, cutoff = ingest_year(session, years[year], agg)
            if k == 0:
                sys.exit(f"Year {year}: zero records — broken upload, not writing.")
            urls.append(years[year])
            if newest and (newest_all is None or newest > newest_all):
                newest_all, cutoff_all = newest, cutoff
        covered = complete_through(newest_all, cutoff_all)
        print(f"Newest record {newest_all}, cut-off {cutoff_all} → complete through {covered}")

    if covered is None or target > covered or target not in agg.counts:
        print(f"{target} is not fully published yet (file complete through "
              f"{covered}) — will retry on the next scheduled run.")
        return emit(args, set())

    periods = sorted(p for p in agg.counts if args.backfill_from <= p <= target)

    unk = sum(n for (p, _), n in agg.unknown_fuel.items() if p == target)
    whole_total = agg.counts[target]["Whole"]["TOTAL"]
    if whole_total and unk / whole_total > MAX_UNKNOWN_FUEL_SHARE:
        sys.exit(f"{target}: {unk:,} records with unknown FUEL strings "
                 f"({unk / whole_total:.1%} of Whole) — schema drift, not writing. "
                 f"Strings: {sorted({f for (p, f) in agg.unknown_fuel if p == target})}")

    problems = check_consistency(agg, periods)
    if problems:
        sys.exit("Consistency check failed:\n  " + "\n  ".join(problems[:20]))

    if (not backfill and not args.force and "Whole" in variants
            and looks_incomplete(target, whole_total, have["Whole"])):
        print(f"{target}: Whole TOTAL {whole_total:,} is below "
              f"{MIN_MONTH_FRACTION:.0%} of the trailing median — looks like an "
              "incomplete upload; not writing. Re-run with --force if genuine.")
        return emit(args, set())

    changed: set[str] = set()
    for v in variants:
        updates = {(p, v): render_line(p, v, agg.counts[p][v], gap_note(p, agg))
                   for p in periods if agg.counts[p][v]["TOTAL"] > 0}
        stats = upsert_lines(paths[v], updates, args.force)
        print(f"{VARIANT_CSV[v]}: {stats}")
        if stats["added"] or stats["updated"]:
            changed.add(v)

    def refresh_top() -> None:
        top = build_top(agg, target)
        print(f"{TOP_PATH.relative_to(REPO)}: "
              f"{'updated' if market_top.write_top(top, TOP_PATH) else 'unchanged'}")
    if "Whole" in variants:
        market_top.guarded(refresh_top)

    rep = report(agg, target, variants)
    print("\n" + rep)
    if args.step_summary:
        with open(args.step_summary, "a", encoding="utf-8") as fh:
            fh.write(rep)
    print("Sources: " + ", ".join(urls))
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
