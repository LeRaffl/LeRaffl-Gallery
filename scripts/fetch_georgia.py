#!/usr/bin/env python3
"""
Fetch Georgia's quarterly initial vehicle registrations by fuel from Geostat
and update data/Georgia.csv.

Usage
-----
    python scripts/fetch_georgia.py [--quarter YYYY-Qn] [--backfill] [--force]
                                    [--dry-run] [--from-dir DIR] [--dump-dir DIR]
                                    [--github-output PATH] [--summary PATH]

* --quarter    Target quarter (default: the newest quarter Geostat lists).
* --backfill   Read every quarter from FIRST_YEAR (2017-Q1) on and add the
               quarters data/Georgia.csv does not have yet. Quarters it already
               has are compared, never overwritten without --force.
* --force      Overwrite existing rows that differ (and rows with a foreign
               `source`), and skip the completeness guard.
* --dry-run    Fetch, validate and print; write nothing. Re-reading quarters
               the CSV already holds this way is the regression test for a
               mapping change: it must reproduce the committed rows.
* --from-dir   Read the JSON answers saved by --dump-dir instead of the
               network (offline debugging; see the runbook).
* --dump-dir   Save every JSON answer the run reads (for --from-dir).

Invoked by .github/workflows/fetch-georgia.yml (daily, plus
workflow_dispatch). Full method, governance checks and a debugging runbook:
docs/architecture/52-source-georgia.md.

Data source
-----------
Geostat (National Statistics Office of Georgia) publishes its road-transport
statistics as the "Automobile" portal, automobile.geostat.ge — a JavaScript
front end over a public JSON API at autoapi.geostat.ge (no key; the API only
answers requests that carry the portal's Origin/Referer headers). The page
"Automobiles → Rating" with the period switch on "during the period" shows
the vehicles *initially registered in Georgia* in a quarter, from the Ministry
of Internal Affairs' Service Agency register: every vehicle category (cars,
trucks, buses, special vehicles) and every vehicle registered in Georgia for
the first time — new or an imported used car. The fetcher reads:

  mobile-text/ratings?year=Y        the period picker: which quarters of Y
                                    Geostat has published ("I", "II", ...)
  mobile/fuels?year=Y&quarter=Q&table=true
                                    the quarter's fuel split (7 categories)
  mobile/fuels?...&quarter=99       the calendar year (to date) — cross-check
  mobile/treemap?year=Y&quarter=Q&table=true
                                    the quarter's brand → model counts (top
                                    25 brands, top models per brand, the rest
                                    as "დანარჩენი" = "others") → market/georgia_top.json

Mapping (Geostat category → column):
  Electric → BEV; Hybrid → HEV (one combined bucket: plug-in and full hybrids
  are not separated — the Türkiye convention, PHEV has no column);
  Gasoline + Gasoline-gas (petrol cars converted to LPG/CNG) → PETROL;
  Diesel → DIESEL; Gas + Others → OTHERS; TOTAL = sum of all seven.
  An unknown category stops the run (see the runbook).

Rows sit on the quarter's middle month with time_interval = quarterly
(Q1 → YYYY-02, Q2 → -05, Q3 → -08, Q4 → -11), as the hand-entered history
did (and as Canada does).
"""
from __future__ import annotations

import argparse
import collections
import csv
import io
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import market_top  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
CSV_PATH = REPO / "data" / "Georgia.csv"
COUNTRY = "Georgia"
SOURCE = "National Statistics Office of Georgia"
VARIANT = "Whole"
FIRST_YEAR = 2017               # the API's first year (2016 and older answer [])

API = "https://autoapi.geostat.ge/"
PORTAL = "https://automobile.geostat.ge/en/automobiles/rating"
HTTP_HEADERS = {
    "Origin": "https://automobile.geostat.ge",
    "Referer": "https://automobile.geostat.ge/",
    "Accept": "application/json",
    "User-Agent": ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"),
}
HTTP_TRIES = 4

CSV_COLUMNS = ["period", "time_interval", "variant", "source", "BEV", "HEV",
               "PETROL", "DIESEL", "OTHERS", "TOTAL", "notes"]
FUELS = ["BEV", "HEV", "PETROL", "DIESEL", "OTHERS"]
CATEGORY_MAP = {
    "Electric": "BEV",
    "Hybrid": "HEV",
    "Gasoline": "PETROL",
    "Gasoline-gas": "PETROL",
    "Diesel": "DIESEL",
    "Gas": "OTHERS",
    "Others": "OTHERS",
}
REQUIRED = {"Electric", "Hybrid", "Gasoline", "Diesel"}

QUARTERS = ["I", "II", "III", "IV"]
MID_MONTH = {"I": 2, "II": 5, "III": 8, "IV": 11}

GUARD_ABORT = 0.5   # TOTAL below half the same quarter a year earlier → stop
GUARD_WARN = 0.75   # … below three quarters → warning in the summary

TOP_PATH = market_top.MARKET_DIR / "georgia_top.json"
OTHERS_KA = "დანარჩენი"   # Geostat's "others" line, in Georgian even with lang=en
TOP_UNIT = ("vehicles initially registered in Georgia by brand and model as "
            "Geostat's treemap lists them — every powertrain and every vehicle "
            "category (new and imported used together); Geostat lists the top 25 "
            "brands and the top models of each, the rest counts towards the total "
            "but is not ranked")


# --------------------------------------------------------------------------
# Periods
# --------------------------------------------------------------------------

def period_of(year: int, q: str) -> str:
    return f"{year:04d}-{MID_MONTH[q]:02d}"


def quarter_of(period: str) -> tuple[int, str]:
    y, m = map(int, period.split("-"))
    for q, mm in MID_MONTH.items():
        if mm == m:
            return y, q
    raise ValueError(f"{period} is not a quarter's middle month")


def parse_quarter_arg(s: str) -> tuple[int, str]:
    m = re.fullmatch(r"(\d{4})-?Q([1-4])", s.strip(), re.I)
    if not m:
        raise SystemExit(f"--quarter {s!r}: expected YYYY-Qn, e.g. 2026-Q2")
    return int(m.group(1)), QUARTERS[int(m.group(2)) - 1]


def label(year: int, q: str) -> str:
    return f"{year}-Q{QUARTERS.index(q) + 1}"


def qkey(t: tuple[int, str]) -> tuple[int, int]:
    """Sort/compare key for (year, roman quarter)."""
    return t[0], QUARTERS.index(t[1])


def prev_quarter(year: int, q: str) -> tuple[int, str]:
    i = QUARTERS.index(q)
    return (year, QUARTERS[i - 1]) if i else (year - 1, "IV")


# --------------------------------------------------------------------------
# Source access (network or a --dump-dir copy)
# --------------------------------------------------------------------------

class Source:
    """One place for every API call, so a run can be replayed offline."""

    def __init__(self, from_dir: str | None = None, dump_dir: str | None = None):
        self.from_dir = Path(from_dir) if from_dir else None
        self.dump_dir = Path(dump_dir) if dump_dir else None
        self.requests = 0

    @staticmethod
    def _name(path: str, params: dict) -> str:
        keys = "_".join(str(params[k]) for k in ("year", "quarter") if k in params)
        return f"{path.replace('/', '_')}_{keys}.json"

    def get(self, path: str, params: dict):
        name = self._name(path, params)
        if self.from_dir:
            f = self.from_dir / name
            if not f.exists():
                raise RuntimeError(f"--from-dir: {f} missing")
            return json.loads(f.read_text(encoding="utf-8"))
        text = http_get(API + path, {"lang": "en", **params})
        self.requests += 1
        if self.dump_dir:
            self.dump_dir.mkdir(parents=True, exist_ok=True)
            (self.dump_dir / name).write_text(text, encoding="utf-8")
        try:
            return json.loads(text)
        except ValueError as e:
            raise RuntimeError(f"{path} {params}: not JSON ({e}): {text[:200]!r}")

    def quarters(self, year: int) -> list[str]:
        """The quarters of `year` in the portal's period picker."""
        data = self.get("mobile-text/ratings", {"year": year, "table": "true"})
        for sel in data if isinstance(data, list) else []:
            if isinstance(sel, dict) and str(sel.get("placeholder", "")).lower() == "quarter":
                codes = [str(v.get("code")) for v in sel.get("selectValues") or []]
                return [q for q in QUARTERS if q in codes]
        raise RuntimeError(f"mobile-text/ratings year={year}: no 'Quarter' selector "
                           "— the portal's picker changed (see the runbook)")

    def fuels(self, year: int, quarter: str) -> dict[str, int]:
        data = self.get("mobile/fuels", {"year": year, "quarter": quarter, "table": "true"})
        return parse_fuels(data, f"{year} quarter={quarter}")

    def treemap(self, year: int, quarter: str) -> dict:
        return self.get("mobile/treemap", {"year": year, "quarter": quarter, "table": "true"})


def http_get(url: str, params: dict | None = None) -> str:
    import requests
    last = None
    for attempt in range(HTTP_TRIES):
        try:
            r = requests.get(url, params=params, headers=HTTP_HEADERS, timeout=(20, 90))
            if r.status_code == 200:
                return r.text
            last = f"HTTP {r.status_code}"
            if r.status_code in (400, 401, 404):
                break
        except requests.RequestException as e:
            last = f"{type(e).__name__}: {e}"
        time.sleep(2 ** (attempt + 1))
    raise RuntimeError(f"GET {url} {params or ''} failed: {last}")


# --------------------------------------------------------------------------
# Parsing and mapping
# --------------------------------------------------------------------------

def parse_fuels(data, where: str) -> dict[str, int]:
    """[{"name": "Gasoline", "value": 22349}, ...] → {"Gasoline": 22349, ...}.
    An empty list means "not published"; anything else malformed stops."""
    if data == []:
        return {}
    if not isinstance(data, list):
        raise ValueError(f"fuels {where}: expected a list, got {type(data).__name__}")
    out: dict[str, int] = {}
    for item in data:
        try:
            name = str(item["name"]).strip()
            value = float(item["value"])
        except (KeyError, TypeError, ValueError):
            raise ValueError(f"fuels {where}: malformed item {item!r}")
        if value < 0 or value != int(value):
            raise ValueError(f"fuels {where}: {name} = {item['value']!r} is not a count")
        if name in out:
            raise ValueError(f"fuels {where}: category {name!r} listed twice")
        out[name] = int(value)
    return out


def to_counts(cats: dict[str, int], where: str) -> dict[str, int]:
    """Geostat categories → gallery columns. Unknown or missing categories stop."""
    unknown = sorted(set(cats) - set(CATEGORY_MAP))
    if unknown:
        raise ValueError(f"fuels {where}: unknown categor{'y' if len(unknown) == 1 else 'ies'} "
                         f"{unknown} — decide the column in CATEGORY_MAP (runbook §8)")
    missing = sorted(REQUIRED - set(cats))
    if missing:
        raise ValueError(f"fuels {where}: categories {missing} missing — schema drift")
    counts = {f: 0 for f in FUELS}
    for name, n in cats.items():
        counts[CATEGORY_MAP[name]] += n
    counts["TOTAL"] = sum(cats.values())
    return counts


def render_line(period: str, counts: dict[str, int], notes: str = "") -> str:
    buf = io.StringIO()
    csv.writer(buf, lineterminator="").writerow(
        [period, "quarterly", VARIANT, SOURCE]
        + [str(counts[f]) for f in FUELS + ["TOTAL"]] + [notes])
    return buf.getvalue()


# --------------------------------------------------------------------------
# CSV (line-level upserts, invariant 2)
# --------------------------------------------------------------------------

def read_csv_lines(path: Path) -> tuple[str, list[str]]:
    text = path.read_text(encoding="utf-8")
    lines = [l for l in text.split("\n") if l.strip()]
    return lines[0], lines[1:]


def line_key(line: str) -> tuple[str, str]:
    row = next(csv.reader([line]))
    return row[0], row[2]


def existing_rows(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8", newline="") as fh:
        return {r["period"]: r for r in csv.DictReader(fh) if r.get("variant") == VARIANT}


def row_counts(row: dict[str, str]) -> dict[str, int]:
    return {c: int(round(float(row[c]))) if (row.get(c) or "").strip() else 0
            for c in FUELS + ["TOTAL"]}


def compare(counts: dict[str, int], row: dict[str, str] | None) -> str:
    """'' when the CSV row carries the same numbers, else a short diff."""
    if row is None:
        return "not in the CSV"
    old = row_counts(row)
    diffs = [f"{c} {old[c]}→{counts[c]}" for c in FUELS + ["TOTAL"] if old[c] != counts[c]]
    return ", ".join(diffs)


def upsert_lines(path: Path, updates: dict[str, str], force: bool) -> dict[str, int]:
    """Insert new periods' lines; an existing line is replaced only with
    --force. Every other line is written back byte-for-byte."""
    header, lines = read_csv_lines(path)
    if header.split(",") != CSV_COLUMNS:
        raise SystemExit(f"{path}: unexpected header {header!r}")
    stats = {"added": 0, "updated": 0, "unchanged": 0, "skipped": 0}
    index = {line_key(l): i for i, l in enumerate(lines)}
    for period, new in sorted(updates.items()):
        key = (period, VARIANT)
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


# --------------------------------------------------------------------------
# Governance
# --------------------------------------------------------------------------

def year_check(src: Source, year: int, quarters: list[str],
               per_q: dict[str, dict[str, int]]) -> str:
    """Geostat's own year (quarter=99, i.e. January to the newest published
    quarter) must equal the sum of the quarters, category by category.
    Returns '' when it does, else the difference (the run stops on it)."""
    year_cats = src.fuels(year, "99")
    summed: collections.Counter = collections.Counter()
    for q in quarters:
        summed.update(per_q[q])
    diffs = [f"{k}: year {year_cats.get(k, 0)} vs quarters {summed.get(k, 0)}"
             for k in sorted(set(year_cats) | set(summed))
             if year_cats.get(k, 0) != summed.get(k, 0)]
    return "; ".join(diffs)


def completeness(counts: dict[str, int], year_ago: dict[str, str] | None) -> tuple[str, float | None]:
    """TOTAL against the same quarter a year earlier: ('ok'|'warn'|'abort', ratio)."""
    if not year_ago:
        return "ok", None
    base = row_counts(year_ago)["TOTAL"]
    if not base:
        return "ok", None
    r = counts["TOTAL"] / base
    if r < GUARD_ABORT:
        return "abort", r
    if r < GUARD_WARN:
        return "warn", r
    return "ok", r


# --------------------------------------------------------------------------
# Brand / model table
# --------------------------------------------------------------------------

def treemap_units(tree: dict, total: int, where: str) -> dict[tuple[str, str, str], int]:
    """{brand: {model: n, "დანარჩენი": n}, "დანარჩენი": {...}} → market_top units
    (class ALL). Geostat's own "others" lines count towards the total but are
    never ranked; whatever the treemap does not list (it should list the whole
    quarter) is added as unranked rest so shares stay of the whole market."""
    if not isinstance(tree, dict) or not tree:
        raise ValueError(f"treemap {where}: empty or not an object")
    units: dict[tuple[str, str, str], int] = collections.Counter()
    for brand, models in tree.items():
        if not isinstance(models, dict):
            raise ValueError(f"treemap {where}: brand {brand!r} has no model map")
        b = market_top.REST if brand.strip() == OTHERS_KA else market_top.clean(brand)
        for model, n in models.items():
            n = int(n)
            m = "" if (b == market_top.REST or model.strip() == OTHERS_KA) \
                else market_top.clean(model)
            units[(market_top.ALL, b, m)] += n
    listed = sum(units.values())
    if listed > total:
        raise ValueError(f"treemap {where}: lists {listed} vehicles, more than the "
                         f"quarter's total {total}")
    if listed < total:
        units[(market_top.ALL, market_top.REST, "")] += total - listed
    return dict(units)


def build_georgia_top(src: Source, quarters: list[tuple[int, str]],
                      totals: dict[str, int]) -> dict:
    """Trailing four quarters → market/georgia_top.json (class ALL)."""
    units: collections.Counter = collections.Counter()
    total = 0
    for y, q in quarters:
        p = period_of(y, q)
        t = totals[p]
        units.update(treemap_units(src.treemap(y, q), t, label(y, q)))
        total += t
    last_y, last_q = quarters[-1]
    first_y, first_q = quarters[0]
    top = market_top.build_top(COUNTRY, SOURCE, period_of(last_y, last_q),
                               dict(units), total, TOP_UNIT)
    start_m = MID_MONTH[first_q] - 1
    end_m = MID_MONTH[last_q] + 1
    top["window"] = {"from": f"{first_y:04d}-{start_m:02d}",
                     "to": f"{last_y:04d}-{end_m:02d}",
                     "months": 3 * len(quarters)}
    top["quarters"] = [label(y, q) for y, q in quarters]
    return top


def refresh_top(src: Source, published: list[tuple[int, str]],
                totals: dict[str, int], report: list[str]) -> None:
    last4 = published[-4:]
    top = build_georgia_top(src, last4, totals)
    wrote = market_top.write_top(top, TOP_PATH)
    market_top.report(top, TOP_PATH, wrote)
    report.append(f"- market/georgia_top.json: {', '.join(top['quarters'])} "
                  f"({'written' if wrote else 'unchanged'})")


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def published_quarters(src: Source, today, through: int | None = None) -> list[tuple[int, str]]:
    """Every quarter from FIRST_YEAR on that the portal's picker lists."""
    last_year = through or today.year
    out = []
    for y in range(FIRST_YEAR, last_year + 1):
        out += [(y, q) for q in src.quarters(y)]
    return out


def newest_published(src: Source, today) -> list[tuple[int, str]]:
    """The current year's picker (and last year's while the current one is
    empty) — the cheap first request of every run."""
    for y in (today.year, today.year - 1):
        qs = src.quarters(y)
        if qs:
            return [(y, q) for q in qs]
    return []


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--quarter", help="target quarter YYYY-Qn (default: newest published)")
    ap.add_argument("--backfill", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--from-dir")
    ap.add_argument("--dump-dir")
    ap.add_argument("--csv", default=str(CSV_PATH))
    ap.add_argument("--no-top", action="store_true", help="skip market/georgia_top.json")
    ap.add_argument("--today", help=argparse.SUPPRESS)  # tests: pin the date
    ap.add_argument("--github-output", default=os.environ.get("GITHUB_OUTPUT"))
    ap.add_argument("--summary", default=os.environ.get("GITHUB_STEP_SUMMARY"))
    args = ap.parse_args(argv)

    src = Source(args.from_dir, args.dump_dir)
    csv_path = Path(args.csv)
    have = existing_rows(csv_path)
    today = (datetime.strptime(args.today, "%Y-%m-%d").date() if args.today
             else datetime.now(timezone.utc).date())
    report: list[str] = [f"### Georgia (Geostat) — run of {today}", ""]

    # 1) Which quarters exist? One small request in a normal run.
    recent = newest_published(src, today)
    if not recent:
        print(f"::error title=Georgia: no quarter published::the Geostat period picker "
              f"lists no quarter for {today.year} or {today.year - 1} (runbook §8)")
        return 1
    if args.quarter:
        target = parse_quarter_arg(args.quarter)
    else:
        target = recent[-1]
    target_p = period_of(*target)

    top_current = market_top.top_as_of(TOP_PATH) == period_of(*recent[-1])
    row = have.get(target_p)
    if (not args.force and not args.backfill and not args.quarter and row is not None
            and (top_current or args.no_top)):
        print(f"{label(*target)} ({target_p}) already in {csv_path.name} and "
              "market/georgia_top.json is current — nothing to do "
              f"({src.requests} request(s)).")
        return emit(args, set())

    # 2) The quarters to read: a backfill reads everything; a normal run the
    #    target and the three quarters before it (to report Geostat revisions
    #    and to rebuild the four-quarter brand table).
    if args.backfill:
        todo = published_quarters(src, today, through=target[0])
        todo = [t for t in todo if qkey(t) <= qkey(target)]
    else:
        todo = [target]
        while len(todo) < 4:
            todo.insert(0, prev_quarter(*todo[0]))
    published_years: dict[int, list[str]] = {}
    for y in sorted({y for y, _ in todo}):
        published_years[y] = src.quarters(y)
    todo = [t for t in todo if t[1] in published_years.get(t[0], [])]
    if target not in todo:
        print(f"::error title=Georgia: quarter not published::{label(*target)} is not in "
              "Geostat's period picker yet")
        return 1

    per_year: dict[int, dict[str, dict[str, int]]] = collections.defaultdict(dict)
    totals: dict[str, int] = {}
    updates: dict[str, str] = {}
    table = ["| Quarter | Row | BEV | HEV | PETROL | DIESEL | OTHERS | TOTAL | vs CSV |",
             "|---|---|---:|---:|---:|---:|---:|---:|---|"]
    for y, q in todo:
        where = label(y, q)
        cats = src.fuels(y, q)
        if not cats:
            raise SystemExit(f"{where}: listed in the picker but mobile/fuels is empty "
                             "(runbook §8)")
        counts = to_counts(cats, where)
        p = period_of(y, q)
        per_year[y][q] = cats
        totals[p] = counts["TOTAL"]
        diff = compare(counts, have.get(p))
        table.append(f"| {where} | {p} | " + " | ".join(str(counts[c]) for c in FUELS + ["TOTAL"])
                     + f" | {diff or 'identical'} |")
        if p not in have:
            if (y, q) == target or args.backfill:
                status, ratio = completeness(counts, have.get(period_of(y - 1, q)))
                if status == "abort" and not args.force:
                    print(f"::error title=Georgia completeness guard::{where} TOTAL "
                          f"{counts['TOTAL']} is {ratio:.0%} of the same quarter a year "
                          "earlier — a partial upload? Re-run with force if it is real "
                          "(runbook §8)")
                    return 1
                if status == "warn":
                    report.append(f"- ⚠️ {where}: TOTAL is {ratio:.0%} of a year earlier")
            updates[p] = render_line(p, counts)
        elif diff:
            if args.force:
                updates[p] = render_line(p, counts)
            report.append(f"- {where} differs from the CSV ({have[p].get('source')}): {diff}"
                          + (" — overwritten (force)" if args.force else " — kept unless force"))

    # 3) Geostat's year figure must equal the sum of its quarters.
    for y, by_q in sorted(per_year.items()):
        qs = published_years[y]
        if set(qs) <= set(by_q):
            bad = year_check(src, y, qs, by_q)
            if bad:
                print(f"::error title=Georgia year cross-check::{y}: {bad} (runbook §8)")
                return 1
            report.append(f"- {y}: the year figure (quarter=99) equals the sum of "
                          f"{', '.join(qs)} ✓")

    changed: set[str] = set()
    if updates and not args.dry_run:
        stats = upsert_lines(csv_path, updates, args.force)
        print(f"{csv_path.name}: {stats}")
        report.append(f"- {csv_path.name}: {stats}")
        if stats["added"] or stats["updated"]:
            changed.add(VARIANT)
    elif updates:
        print("dry run — would write:\n" + "\n".join(updates.values()))

    if not args.no_top and not args.dry_run:
        market_top.guarded(refresh_top, src, todo, totals, report)

    text = "\n".join(report + ["", *table])
    print(text)
    print(f"{src.requests} request(s)")
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
    sys.exit(main())
