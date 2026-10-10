#!/usr/bin/env python3
"""
Fetch New Zealand light-vehicle registrations from the NZTA Motor Vehicle
Register (MVR) and update data/New Zealand.csv.

Usage
-----
    python scripts/fetch_new_zealand.py [--period YYYY-MM] [--since YYYY-MM]
                                        [--variant Whole,Vans,HDV,Used]
                                        [--force] [--dry-run]
                                        [--from-json PATH] [--save-json PATH]
                                        [--github-output PATH] [--summary PATH]

* --period     Target month (default: the calendar month that just ended).
* --since      Also count every month from YYYY-MM to the target. Months the
               CSV already holds are compared, never overwritten (unless
               --force); see "History" below for why old months undercount.
* --variant    Only these variants (default: all four).
* --force      Overwrite existing rows (any source) and skip the plausibility
               guard.
* --dry-run    Query, validate and print; write nothing. Re-reading a month
               the CSV already holds this way is the regression check.
* --from-json  Use a saved query result (written by --save-json) instead of
               the network — offline debugging and the tests.

Invoked by .github/workflows/fetch-new-zealand.yml (daily on the 3rd–20th,
plus workflow_dispatch). Full method, governance checks and a debugging
runbook: docs/architecture/19-source-new-zealand.md.

Data source
-----------
NZ Transport Agency Waka Kotahi publishes the Motor Vehicle Register as open
data (CC BY 4.0): one record per currently-registered vehicle, refreshed
monthly "accurate up to the end of the previous month" (the September 2026
snapshot was loaded on 6 October). The fetcher never downloads the records:
the register is an ArcGIS feature service, and its query endpoint returns
grouped counts (`outStatistics`) — a normal run is a handful of small JSON
requests.

The service URL changes when NZTA republishes (it is named after a month,
e.g. ".../MVR_Mar26/FeatureServer"), so it is looked up on every run from
the stable Hub item ITEM_ID; FALLBACK_SERVICE is only used when the Hub
search API is down.

Variants (docs/architecture/19-source-new-zealand.md §2)
--------
Every count is a first registration in New Zealand (IMPORT_STATUS NEW or
USED — not RE-REG, SCRATCH), dated by FIRST_NZ_REGISTRATION_YEAR / _MONTH,
and cut by import status × NZTA vehicle class onto the EU classes:

    Whole   data/New Zealand.csv         NEW,  MA/MB/MC        (M1 new cars)
    Vans    data/New Zealand_Vans.csv    NEW,  NA              (N1)
    HDV     data/New Zealand_HDV.csv     NEW,  NB/NC           (N2/N3)
    Used    data/New Zealand_Used.csv    USED, MA/MB/MC        (M1 used imports)

Used vans (USED × NA) are in no variant. The series the gallery had until
2026-10 — Prof. Ray Willis's compilation of the Ministry of Transport's "light
motor vehicle registrations", new *and* used-import light vehicles — is parked
unchanged in data/New Zealand_legacy.csv (an archive: not fetched, not
rendered). The register reproduces it to about 1 % in every fuel column
through 2026-03 (the shortfall is vehicles deregistered since, and owners with
a confidential listing, whom NZTA leaves out).

Fuel mapping (MOTIVE_POWER -> CSV column)
-----------------------------------------
    ELECTRIC                                   -> BEV
    PLUGIN PETROL / DIESEL HYBRID,
    ELECTRIC [PETROL / DIESEL EXTENDED]        -> PHEV  (EREV folded in: the
                                                  CSV has no EREV column and
                                                  the legacy rows include it)
    PETROL HYBRID, PETROL ELECTRIC HYBRID,
    DIESEL HYBRID, DIESEL ELECTRIC HYBRID      -> HEV   (whatever the certifier
                                                  entered as "hybrid" — some
                                                  48 V mild-hybrid utes too)
    PETROL                                     -> PETROL
    DIESEL                                     -> DIESEL
    LPG, CNG, ELECTRIC FUEL CELL HYDROGEN,
    OTHER, empty                               -> OTHERS

A label outside MOTIVE_MAP is counted in OTHERS and listed in the step
summary; above UNKNOWN_ABORT of a month's total it stops the run — a new
register label needs a human decision about its column.

History
-------
The register is a snapshot of vehicles registered *today*: a month counted
years later misses every vehicle scrapped or exported since (about 4 % for
2024, 30 % for 2015). So the fetcher writes the month that just ended, from
the first snapshot that covers it, and leaves older rows alone (invariant 3,
"don't rewrite the past"). A `--since` backfill adds only months the CSV
lacks and flags them in `notes`.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import market_top  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
DATA_DIR = REPO / "data"
CSV_PATH = DATA_DIR / "New Zealand.csv"
COUNTRY = "New Zealand"
SLUG = "new_zealand"
SOURCE = "NZTA Motor Vehicle Register"
VARIANT = "Whole"
TOP_PATH = market_top.MARKET_DIR / f"{SLUG}_top.json"
TOP_UNIT = ("one first registration of a new passenger car (classes MA/MB/MC, "
            "EU M1) in New Zealand; brand and model as entered on the Motor "
            "Vehicle Register")

ITEM_ID = "7b4df667d5014f1a93e6050b31d18407"
HUB_ITEM = ("https://opendata-nzta.opendata.arcgis.com/api/search/v1/"
            f"collections/all/items/{ITEM_ID}")
FALLBACK_SERVICE = ("https://services.arcgis.com/CXBb7LAjgIIdcsPt/arcgis/rest/"
                    "services/MVR_Mar26/FeatureServer")
PAGE = 2000                      # the service's maxRecordCount

CSV_COLUMNS = ["period", "time_interval", "variant", "source", "BEV", "PHEV",
               "HEV", "PETROL", "DIESEL", "OTHERS", "TOTAL", "notes"]
FUELS = ["BEV", "PHEV", "HEV", "PETROL", "DIESEL", "OTHERS"]

M1 = ("MA", "MB", "MC")          # passenger car, passenger van, off-road passenger
# variant -> (import statuses, vehicle classes), anchored to the EU classes
# like every other country (09-glossary.md).
VARIANTS = {
    "Whole": (("NEW",), M1),
    "Vans": (("NEW",), ("NA",)),
    "HDV": (("NEW",), ("NB", "NC")),
    "Used": (("USED",), M1),
}
STATUSES = tuple(sorted({s for sts, _ in VARIANTS.values() for s in sts}))
CLASSES = tuple(sorted({c for _, cls in VARIANTS.values() for c in cls}))
F_YEAR, F_MONTH = "FIRST_NZ_REGISTRATION_YEAR", "FIRST_NZ_REGISTRATION_MONTH"
REQUIRED_FIELDS = {F_YEAR, F_MONTH, "IMPORT_STATUS", "CLASS", "MOTIVE_POWER",
                   "MAKE", "MODEL"}

MOTIVE_MAP = {
    "ELECTRIC": "BEV",
    "PLUGIN PETROL HYBRID": "PHEV",
    "PLUGIN DIESEL HYBRID": "PHEV",
    "ELECTRIC [PETROL EXTENDED]": "PHEV",
    "ELECTRIC [DIESEL EXTENDED]": "PHEV",
    "PETROL HYBRID": "HEV",
    "PETROL ELECTRIC HYBRID": "HEV",
    "DIESEL HYBRID": "HEV",
    "DIESEL ELECTRIC HYBRID": "HEV",
    "PETROL": "PETROL",
    "DIESEL": "DIESEL",
    "LPG": "OTHERS",
    "CNG": "OTHERS",
    "ELECTRIC FUEL CELL HYDROGEN": "OTHERS",
    "PLUG IN FUEL CELL HYDROGEN HYBRID": "OTHERS",
    "OTHER": "OTHERS",
    "": "OTHERS",
}
ELECTRIFIED = ("BEV", "PHEV", "HEV")
UNKNOWN_ABORT = 0.01             # unknown labels above 1 % of a month stop the run
PLAUSIBLE = (0.5, 2.0)           # TOTAL / same month a year earlier
OVERLAP_WARN = 0.05              # register vs CSV on months the CSV holds
STALE_DAY = 20                   # from this day on, a missing month is an error


# ── HTTP ────────────────────────────────────────────────────────────────────

def http_json(url: str, params: dict | None = None, tries: int = 4) -> dict:
    import requests
    last = None
    for i in range(tries):
        try:
            r = requests.get(url, params=params, timeout=120,
                             headers={"User-Agent": "LeRaffl-Gallery fetcher "
                                      "(+https://github.com/LeRaffl/LeRaffl-Gallery)"})
            if r.status_code == 200:
                d = r.json()
                if isinstance(d, dict) and "error" in d:
                    raise RuntimeError(f"ArcGIS error from {url}: {d['error']}")
                return d
            last = f"HTTP {r.status_code}"
        except (requests.RequestException, ValueError) as e:   # network, bad JSON
            last = f"{type(e).__name__}: {e}"
        time.sleep(2 ** (i + 1))
    raise RuntimeError(f"GET {url} failed after {tries} tries: {last}")


def resolve_service() -> str:
    """The feature service the Hub item currently points at."""
    try:
        d = http_json(HUB_ITEM, tries=2)
        url = (d.get("properties") or d).get("url") or ""
        if "/FeatureServer" in url:
            return url.split("/FeatureServer")[0] + "/FeatureServer"
        print(f"::warning title=NZ register URL::Hub item has no FeatureServer url "
              f"({url!r}); using {FALLBACK_SERVICE}")
    except RuntimeError as e:
        print(f"::warning title=NZ register URL::Hub lookup failed ({e}); "
              f"using {FALLBACK_SERVICE}")
    return FALLBACK_SERVICE


def layer_info(service: str) -> tuple[str, date]:
    """(query URL of the register table, date the data was last loaded)."""
    svc = http_json(service, {"f": "json"})
    tables = (svc.get("tables") or []) + (svc.get("layers") or [])
    if not tables:
        raise RuntimeError(f"{service}: no table in the service")
    layer = f"{service}/{tables[0]['id']}"
    meta = http_json(layer, {"f": "json"})
    fields = {f["name"] for f in meta.get("fields") or []}
    missing = REQUIRED_FIELDS - fields
    if missing:
        raise RuntimeError(f"register schema changed — fields {sorted(missing)} missing")
    ms = ((meta.get("editingInfo") or {}).get("dataLastEditDate")
          or (meta.get("editingInfo") or {}).get("lastEditDate"))
    if not ms:
        raise RuntimeError("register has no dataLastEditDate — cannot tell which "
                           "months are complete")
    loaded = datetime.fromtimestamp(ms / 1000, tz=timezone.utc).date()
    return layer + "/query", loaded


def grouped(query_url: str, where: str, group: list[str]) -> list[dict]:
    """Every row of a grouped count query, paged."""
    out: list[dict] = []
    offset = 0
    while True:
        d = http_json(query_url, {
            "where": where,
            "groupByFieldsForStatistics": ",".join(group),
            "outStatistics": json.dumps([{"statisticType": "count",
                                          "onStatisticField": "OBJECTID",
                                          "outStatisticFieldName": "n"}]),
            "orderByFields": ",".join(group),
            "resultOffset": offset, "resultRecordCount": PAGE, "f": "json"})
        rows = [f["attributes"] for f in d.get("features") or []]
        out += rows
        if len(rows) < PAGE and not d.get("exceededTransferLimit"):
            return out
        offset += len(rows)


def month_num(p: str) -> int:
    return int(p[:4]) * 100 + int(p[5:7])


def scope_where(first: str, last: str, statuses=None, classes=None) -> str:
    q = lambda xs: ",".join(f"'{x}'" for x in xs)
    return (f"({F_YEAR}*100+{F_MONTH}) BETWEEN {month_num(first)} AND {month_num(last)} "
            f"AND IMPORT_STATUS IN ({q(statuses or STATUSES)}) "
            f"AND CLASS IN ({q(classes or CLASSES)})")


def query_register(first: str, last: str, top_from: str | None) -> dict:
    """Everything a run needs, in the --save-json / --from-json shape."""
    service = resolve_service()
    query_url, loaded = layer_info(service)
    print(f"register: {service} (data loaded {loaded})")
    fuel = grouped(query_url, scope_where(first, last),
                   [F_YEAR, F_MONTH, "IMPORT_STATUS", "CLASS", "MOTIVE_POWER"])
    models: list[dict] = []
    if top_from:
        elec = [k for k, v in MOTIVE_MAP.items() if v in ELECTRIFIED and k]
        where = (scope_where(top_from, last, *VARIANTS["Whole"]) + " AND MOTIVE_POWER IN ("
                 + ",".join(f"'{k}'" for k in elec) + ")")
        models = grouped(query_url, where, [F_YEAR, F_MONTH, "MOTIVE_POWER", "MAKE", "MODEL"])
        # month totals for the shares — the fuel query covers only first..last
        if month_num(top_from) < month_num(first):
            fuel_top = grouped(query_url, scope_where(top_from, shift_month(first, -1)),
                               [F_YEAR, F_MONTH, "IMPORT_STATUS", "CLASS", "MOTIVE_POWER"])
            fuel = fuel_top + fuel
    return {"service": service, "loaded": loaded.isoformat(), "fuel": fuel, "models": models}


# ── counting ────────────────────────────────────────────────────────────────

def shift_month(p: str, k: int) -> str:
    y, m = int(p[:4]), int(p[5:7]) + k
    while m < 1:
        y, m = y - 1, m + 12
    while m > 12:
        y, m = y + 1, m - 12
    return f"{y:04d}-{m:02d}"


def period_of(a: dict) -> str:
    return f"{int(a[F_YEAR]):04d}-{int(a[F_MONTH]):02d}"


def column_of(label) -> str | None:
    return MOTIVE_MAP.get(market_top.clean(label))


def variants_of(a: dict) -> list[str]:
    """The variants a grouped row belongs to (at most one)."""
    st, cl = a.get("IMPORT_STATUS") or "", a.get("CLASS") or ""
    return [v for v, (sts, cls) in VARIANTS.items() if st in sts and cl in cls]


def count_months(fuel_rows: list[dict]) -> tuple[dict, dict, dict]:
    """({variant: {period: {column: n, TOTAL}}}, {period: {unknown label: n}},
    {period: {status: n}}) — unknown labels and statuses over every row in scope."""
    counts: dict[str, dict[str, dict[str, int]]] = {v: {} for v in VARIANTS}
    unknown: dict[str, dict[str, int]] = {}
    status: dict[str, dict[str, int]] = {}
    for a in fuel_rows:
        if a.get(F_YEAR) is None or a.get(F_MONTH) is None:
            continue
        vs = variants_of(a)
        if not vs:
            continue
        p, n = period_of(a), int(a["n"])
        col = column_of(a.get("MOTIVE_POWER"))
        if col is None:
            col = "OTHERS"
            lab = market_top.clean(a.get("MOTIVE_POWER"))
            unknown.setdefault(p, {})[lab] = unknown.get(p, {}).get(lab, 0) + n
        for v in vs:
            c = counts[v].setdefault(p, {k: 0 for k in FUELS + ["TOTAL"]})
            c[col] += n
            c["TOTAL"] += n
        s = status.setdefault(p, {})
        s[a.get("IMPORT_STATUS") or ""] = s.get(a.get("IMPORT_STATUS") or "", 0) + n
    return counts, unknown, status


def check_unknown(period: str, unknown: dict, total: int) -> str:
    """'' or a warning; raises above UNKNOWN_ABORT of the month."""
    u = unknown.get(period) or {}
    if not u:
        return ""
    n = sum(u.values())
    msg = f"unmapped MOTIVE_POWER label(s) in {period} (counted in OTHERS): {u}"
    if total and n / total > UNKNOWN_ABORT:
        raise RuntimeError(msg + f" — {n / total:.1%} of the month, above "
                           f"{UNKNOWN_ABORT:.0%}; add them to MOTIVE_MAP")
    return msg


def month_units(model_rows: list[dict]) -> dict[str, dict]:
    """{period: {(class, brand, model): n}} with the CSV's class logic."""
    tally: dict = {}
    for a in model_rows:
        if a.get(F_YEAR) is None or a.get(F_MONTH) is None:
            continue
        cls = column_of(a.get("MOTIVE_POWER"))
        if cls not in ELECTRIFIED:
            continue
        brand = market_top.clean(a.get("MAKE"))
        model = market_top.strip_brand(brand, market_top.clean(a.get("MODEL")))
        key = (period_of(a), cls, brand, model)
        tally[key] = tally.get(key, 0) + int(a["n"])
    return market_top.per_month(tally)


def build_top(data: dict, target: str) -> dict:
    counts = count_months(data["fuel"])[0]["Whole"]
    units = month_units(data["models"])
    window = market_top.month_window(target)
    monthly = {p: (units.get(p, {}), counts[p]["TOTAL"]) for p in window if p in counts}
    return market_top.build_top_monthly(COUNTRY, SOURCE, target, monthly, TOP_UNIT)


def refresh_top(data: dict, target: str) -> None:
    top = build_top(data, target)
    market_top.report(top, TOP_PATH, market_top.write_top(top, TOP_PATH))


# ── CSV line-level upsert (invariant 2) ────────────────────────────────────

def csv_path_for(variant: str, data_dir: Path = DATA_DIR) -> Path:
    return data_dir / (f"{COUNTRY}.csv" if variant == "Whole" else f"{COUNTRY}_{variant}.csv")


def render_line(period: str, counts: dict[str, int], notes: str = "",
                variant: str = VARIANT) -> str:
    buf = io.StringIO()
    csv.writer(buf, lineterminator="").writerow(
        [period, "monthly", variant, SOURCE]
        + [str(counts[k]) for k in FUELS + ["TOTAL"]] + [notes])
    return buf.getvalue()


def read_csv_lines(path: Path) -> tuple[str, list[str]]:
    if not path.exists():
        return ",".join(CSV_COLUMNS), []
    lines = path.read_text(encoding="utf-8").splitlines()
    return (lines[0], lines[1:]) if lines else (",".join(CSV_COLUMNS), [])


def line_key(line: str) -> tuple[str, str]:
    f = next(csv.reader([line]))
    return f[0], f[2]


def existing_rows(path: Path, variant: str = VARIANT) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    with open(path, newline="", encoding="utf-8") as f:
        return {r["period"]: r for r in csv.DictReader(f)
                if (r.get("variant") or "Whole") == variant}


def upsert_lines(path: Path, updates: dict[str, str], force: bool,
                 variant: str = VARIANT) -> dict[str, int]:
    """Insert the given periods' lines; an existing line is replaced only with
    --force. Every other line is written back byte-for-byte."""
    header, lines = read_csv_lines(path)
    if header.split(",") != CSV_COLUMNS:
        raise RuntimeError(f"{path}: unexpected header {header!r}")
    stats = {"added": 0, "updated": 0, "unchanged": 0, "skipped": 0}
    index = {line_key(l): i for i, l in enumerate(lines)}
    for period, new in sorted(updates.items()):
        key = (period, variant)
        if key not in index:
            lines.append(new)
            stats["added"] += 1
        elif lines[index[key]] == new:
            stats["unchanged"] += 1
        elif force:
            lines[index[key]] = new
            stats["updated"] += 1
        else:
            stats["skipped"] += 1
    if stats["added"]:
        lines.sort(key=line_key)
    if stats["added"] or stats["updated"]:
        path.write_text("\n".join([header] + lines) + "\n", encoding="utf-8")
    return stats


def row_counts(row: dict[str, str]) -> dict[str, int]:
    return {k: int(float(row[k])) if row.get(k) not in (None, "") else 0
            for k in FUELS + ["TOTAL"]}


def compare(counts: dict[str, int], row: dict[str, str]) -> tuple[str, float]:
    """(per-column differences register − CSV, TOTAL deviation)."""
    old = row_counts(row)
    diffs = [f"{k} {counts[k] - old[k]:+,}" for k in FUELS + ["TOTAL"] if old[k] != counts[k]]
    dev = (counts["TOTAL"] - old["TOTAL"]) / old["TOTAL"] if old["TOTAL"] else 0.0
    return (", ".join(diffs) or "identical"), dev


def plausibility(period: str, total: int, have: dict[str, dict]) -> float | None:
    """TOTAL / same month a year earlier (NZ registrations are seasonal —
    March and September peak — so this beats a median)."""
    p = shift_month(period, -12)
    if p not in have:
        return None
    old = row_counts(have[p])["TOTAL"]
    return total / old if old else None


# ── main ───────────────────────────────────────────────────────────────────

def default_period(today: date) -> str:
    return shift_month(f"{today.year:04d}-{today.month:02d}", -1)


def month_end(p: str) -> date:
    n = shift_month(p, 1)
    return date(int(n[:4]), int(n[5:7]), 1)


def summary_table(rows: dict[str, dict[str, int]]) -> str:
    out = ["| month | BEV | PHEV | HEV | PETROL | DIESEL | OTHERS | TOTAL | BEV share |",
           "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for p, c in sorted(rows.items()):
        share = f"{c['BEV'] / c['TOTAL']:.1%}" if c["TOTAL"] else "–"
        out.append(f"| {p} | " + " | ".join(f"{c[k]:,}" for k in FUELS + ["TOTAL"])
                   + f" | {share} |")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--period", help="target month YYYY-MM (default: last month)")
    ap.add_argument("--since", help="also count every month from YYYY-MM on")
    ap.add_argument("--variant", help="comma-separated subset of " + ",".join(VARIANTS))
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--from-json", help="saved query result instead of the network")
    ap.add_argument("--save-json", help="write the query result here")
    ap.add_argument("--data-dir", default=str(DATA_DIR))
    ap.add_argument("--no-top", action="store_true", help="skip market/new_zealand_top.json")
    ap.add_argument("--today", help=argparse.SUPPRESS)          # tests
    ap.add_argument("--github-output", default=os.environ.get("GITHUB_OUTPUT"))
    ap.add_argument("--summary", default=os.environ.get("GITHUB_STEP_SUMMARY"))
    args = ap.parse_args(argv)

    today = date.fromisoformat(args.today) if args.today else datetime.now(timezone.utc).date()
    target = args.period or default_period(today)
    first = args.since or target
    if month_num(first) > month_num(target):
        raise RuntimeError(f"--since {first} is after the target {target}")
    variants = [v.strip() for v in args.variant.split(",")] if args.variant else list(VARIANTS)
    bad = [v for v in variants if v not in VARIANTS]
    if bad:
        raise RuntimeError(f"unknown variant(s) {bad}; known: {list(VARIANTS)}")
    data_dir = Path(args.data_dir)
    paths = {v: csv_path_for(v, data_dir) for v in variants}
    have = {v: existing_rows(paths[v], v) for v in variants}

    # Self-throttle: every CSV has the month and the top file is current.
    top_current = args.no_top or market_top.top_is_current(TOP_PATH, target)
    if (all(target in have[v] for v in variants) and top_current and not args.force
            and not args.since and not args.dry_run and not args.from_json):
        print(f"{target} already in every New Zealand CSV and the top file is current "
              "— nothing to do")
        return emit(args, set())

    top_from = None if args.no_top else market_top.month_window(target)[0]
    # The months just before the target are fetched too: they are the overlap
    # check against rows the CSVs already hold.
    q_first = min(first, shift_month(target, -3), key=month_num)
    if args.from_json:
        data = json.loads(Path(args.from_json).read_text(encoding="utf-8"))
    else:
        data = query_register(q_first, target, top_from)
    if args.save_json:
        Path(args.save_json).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    loaded = date.fromisoformat(data["loaded"])
    if loaded < month_end(target):
        msg = (f"the register snapshot (loaded {loaded}) does not cover {target} yet")
        if today.day >= STALE_DAY and today > month_end(target):
            raise RuntimeError(msg + f" — and it is the {today.day}th; NZTA's monthly "
                               "refresh is late or the item moved (see the runbook)")
        print(msg + " — nothing to do until NZTA refreshes it")
        return emit(args, set())

    counts_all, unknown, status = count_months(data["fuel"])
    if not counts_all["Whole"].get(target, {}).get("TOTAL"):
        raise RuntimeError(f"the register has no {target} registrations in scope")

    report: list[str] = [f"### New Zealand — {SOURCE}",
                         f"Service `{data.get('service')}`, data loaded {loaded}."]
    warnings: list[str] = []
    for p in sorted(unknown, key=month_num):
        if month_num(first) <= month_num(p) <= month_num(target):
            w = check_unknown(p, unknown, sum(counts_all[v].get(p, {}).get("TOTAL", 0)
                                                for v in VARIANTS))
            if w:
                warnings.append(w)
    st = status.get(target, {})
    report.append(f"{target}: new {st.get('NEW', 0):,}, used imports {st.get('USED', 0):,}.")

    changed: set[str] = set()
    pending: list[tuple[str, dict[str, str]]] = []
    for v in variants:
        counts = counts_all[v]
        months = [p for p in sorted(counts, key=month_num)
                  if month_num(first) <= month_num(p) <= month_num(target)]
        if target not in counts:
            raise RuntimeError(f"{v}: the register has no {target} registrations in scope")
        ratio = plausibility(target, counts[target]["TOTAL"], have[v])
        if ratio is not None and not (PLAUSIBLE[0] <= ratio <= PLAUSIBLE[1]) and not args.force:
            raise RuntimeError(f"{v} {target}: TOTAL {counts[target]['TOTAL']:,} is ×{ratio:.2f} "
                               f"the same month a year earlier — outside {PLAUSIBLE}; "
                               "check the register, dispatch with force if genuine")
        report += ["", f"#### {v} — `{paths[v].name}`", "",
                   summary_table({p: counts[p] for p in months[-13:]}), "",
                   f"year-ago ratio {('×%.2f' % ratio) if ratio else 'n/a'}"
                   + (f"; {len(months) - 13} earlier month(s) not shown" if len(months) > 13 else "")]

        # Overlap: months the CSV already holds, register vs CSV (information).
        overlap = [p for p in sorted(counts, key=month_num) if p in have[v]
                   and month_num(q_first) <= month_num(p) <= month_num(target)]
        if overlap:
            report += ["", "Register vs CSV on months the CSV already holds "
                       "(register − CSV; the CSV row is kept unless `force`):"]
            for p in overlap[-13:]:
                diff, dev = compare(counts[p], have[v][p])
                flag = " ⚠" if abs(dev) > OVERLAP_WARN else ""
                report.append(f"- {p} ({have[v][p]['source']}): {diff} (TOTAL {dev:+.1%}){flag}")
                if flag:
                    warnings.append(f"{v} {p}: register differs from the CSV by {dev:+.1%}")

        updates = {}
        for p in months:
            notes = ""
            if month_num(p) < month_num(shift_month(target, -2)):
                notes = (f"register snapshot of {loaded}: vehicles deregistered "
                         "since are missing (undercount)")
            updates[p] = render_line(p, counts[p], notes, v)
        pending.append((v, updates))

    if args.dry_run:
        for v, updates in pending:
            for p in sorted(updates):
                print(updates[p])
        report.append("\n_dry run — nothing written_")
    else:
        for v, updates in pending:
            stats = upsert_lines(paths[v], updates, args.force, v)
            report.append(f"\n{paths[v].name}: {stats}")
            print(f"{paths[v].name}: {stats}")
            if stats["added"] or stats["updated"]:
                changed.add(v)
        if not args.no_top and data.get("models"):
            market_top.guarded(refresh_top, data, target)

    for w in warnings:
        print(f"::warning title=New Zealand::{w}")
    if warnings:
        report += ["", "**Review:**"] + [f"- {w}" for w in warnings]
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
        print(f"::error title=New Zealand fetch failed::{e}")
        sys.exit(1)
