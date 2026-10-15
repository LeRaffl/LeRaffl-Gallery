#!/usr/bin/env python3
"""
Fetch Belgium's vehicle registrations from the FPS Mobility and Transport
(FOD Mobiliteit en Vervoer / SPF Mobilité et Transports, Directorate for
Vehicle Registration "DIV") and upsert data/Belgium*.csv (Whole, Private,
Industry, Vans, HDV, Buses).

Source (free, no login, licence CC0)
------------------------------------
The open-data page "Inschrijvingen van voertuigen" (mobilit.belgium.be) shows
the monthly figures as a Power BI report whose last page ("Downloaden")
links the source CSVs on a plain file server:

  https://datafiles.mobilit.belgium.be/OPENDATA/DGTRSR/MonthlyRegistrations/
      YYYYMM_Immatriculations-Inschrijvingen.csv        one file per month
                                                        (from 2025-01)
      2013_2024_Immatriculations-Inschrijvingen.csv     the history 2013–2024

The file server has no directory index and no bot challenge (unlike the web
page), so months are discovered by probing the URL pattern forward: a 404
means "not published yet". FOD writes a month's file once, on the 2nd of the
following month at about 16:00 UTC (Last-Modified headers 2026-07…09).

Every file has the same 14 columns (an aggregate, one row per combination):

  Month End Date            "2026-08-31 23:59:59" — the registration month
  New Plate Flag Label      New Plate / Plate reused (plates follow the owner)
  New Vehicle Flag Label    New vehicle / Used vehicle
  Titular Type Label        Legal Person (VAT) / Natural/Legal Person
  Cylinder Capacity Range   '- / 0001-0799 / … / 3000+
  Vehicle Use Group Fr|Nl|De|En   Passenger car, Light goods vehicle, Lorry,
                            Tractor unit for semitrailer, Bus, …
  Fuel Plus Fr|Nl|De|En     Electricity, Petrol, Gasoil, Hybrid Petrol,
                            Plug-in Hybrid Petrol, LPG, CNG, …
  N Rowcount                number of registrations

Record → CSV (New Vehicle Flag = "New vehicle", either plate flag)
------------------------------------------------------------------
  Whole     Passenger car
  Private   Whole, keeper "Natural/Legal Person" (not VAT-registered — in
            practice private persons; see the source doc §3)
  Industry  Whole, keeper "Legal Person (VAT)"
  Vans      Light goods vehicle               (camionnette, ≤ 3.5 t)
  HDV       Lorry + Tractor unit for semitrailer  (> 3.5 t)
  Buses     Bus                               (autobus and coaches)

Powertrain (Fuel Plus En):
  Electricity                         → BEV
  Plug-in Hybrid <fuel>               → PHEV
  Hybrid Petrol / Gasoil / LPG        → HEV   (full AND mild hybrids — DIV
                                               does not tell them apart)
  Petrol                              → PETROL (without any hybrid)
  Gasoil                              → DIESEL (without any hybrid)
  LPG, CNG, LNG, Hydrogen, Other, ''  → OTHERS

Not written: Used. DIV's "Used vehicle" counts every registration of a used
car — imports AND domestic changes of keeper — and the file cannot tell the
two apart, so it does not fit this repo's Used definition (first national
registration). See the source doc §6 (open decision).

Governance (every real run)
---------------------------
* the header must be exactly the 14 columns (schema drift aborts);
* every row's Month End Date must be the month of its file;
* unknown use-group / fuel / keeper / flag values above 2 % of a
  variant-month abort (below: OTHERS + a warning);
* completeness: a Whole month below 25 % of the trailing-12 median is not
  written, below 50 % is written with a warning;
* ACEA cross-check (reported, not enforced): Whole TOTAL vs the ACEA row of
  the month. DIV is ACEA's source; DIV runs ~0.4 % above ACEA every month;
* rows from a foreign source other than ACEA are never overwritten without
  --force.

Usage
-----
  python scripts/fetch_belgium.py                 # normal run (new months)
  python scripts/fetch_belgium.py --backfill      # every month from 2013-01
  python scripts/fetch_belgium.py --from-dir DIR  # offline: DIR/YYYYMM.csv, DIR/hist.csv

Docs: docs/architecture/59-source-belgium.md (method, validation, runbook).
"""
from __future__ import annotations

import argparse
import collections
import csv
import datetime as dt
import io
import json
import os
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
REPO = SCRIPTS.parent

SOURCE = "DIV"
REPLACEABLE = {"ACEA"}            # the legacy writer this source supersedes
FIRST_PERIOD = "2013-01"          # the history file starts here
FIRST_MONTHLY_FILE = "2025-01"    # months before this live in the history file
RECENT_MONTHS = 3                 # a normal run re-reads this many months
BASE_URL = "https://datafiles.mobilit.belgium.be/OPENDATA/DGTRSR/MonthlyRegistrations/"
MONTH_FILE = "{ym}_Immatriculations-Inschrijvingen.csv"
HISTORY_FILE = "2013_2024_Immatriculations-Inschrijvingen.csv"
UA = {"User-Agent": "LeRaffl-Gallery data fetcher (+https://github.com/LeRaffl/LeRaffl-Gallery)"}

HEADER = ["Month End Date", "New Plate Flag Label", "New Vehicle Flag Label",
          "Titular Type Label", "Cylinder Capacity Range",
          "Vehicle Use Group Fr", "Vehicle Use Group Nl", "Vehicle Use Group De",
          "Vehicle Use Group En", "Fuel Plus Fr", "Fuel Plus Nl", "Fuel Plus De",
          "Fuel Plus En", "N Rowcount"]

VARIANT_CSV = {
    "Whole": "data/Belgium.csv",
    "Private": "data/Belgium_Private.csv",
    "Industry": "data/Belgium_Industry.csv",
    "Vans": "data/Belgium_Vans.csv",
    "HDV": "data/Belgium_HDV.csv",
    "Buses": "data/Belgium_Buses.csv",
}
COLUMNS = ["BEV", "PHEV", "HEV", "PETROL", "DIESEL", "OTHERS"]

FUEL_CLASS = {
    "electricity": "BEV",
    "hybrid petrol": "HEV", "hybrid gasoil": "HEV", "hybrid lpg": "HEV",
    "hybrid cng": "HEV", "hybrid other": "HEV",
    "petrol": "PETROL",
    "gasoil": "DIESEL",
    "lpg": "OTHERS", "cng": "OTHERS", "lng": "OTHERS", "hydrogen": "OTHERS",
    "other": "OTHERS", "": "OTHERS",
}
USE_VARIANT = {
    "passenger car": "Whole",
    "light goods vehicle": "Vans",
    "lorry": "HDV",
    "tractor unit for semitrailer": "HDV",
    "bus": "Buses",
}
# every other use group is known and deliberately not counted
USE_IGNORED = {
    "trailer caravan", "trailer", "semi-trailer", "agricultural vehicle",
    "heavy two-, three- or four-wheel vehicle", "light two-, three- or four-wheel vehicle",
    "special purpose vehicle", "motor caravan", "~?~", "undetermined",
}
NEW, USED = "new vehicle", "used vehicle"
KEEPER_PRIVATE, KEEPER_VAT = "natural/legal person", "legal person (vat)"

MAX_UNKNOWN_SHARE = 0.02
MIN_MONTH_FRACTION = 0.25
WARN_MONTH_FRACTION = 0.50
ACEA_WARN = 0.02                  # report a Whole month > 2 % off ACEA

NOTES = {
    "Whole": "new passenger cars by fuel (HEV incl. mild hybrids)",
    "Private": "new passenger cars, keeper not VAT-registered (Natural/Legal Person)",
    "Industry": "new passenger cars, keeper a VAT-registered legal person",
    "Vans": "new light goods vehicles (camionnettes) by fuel",
    "HDV": "new lorries + tractor units by fuel",
    "Buses": "new buses and coaches by fuel",
}


# ── values ─────────────────────────────────────────────────────────────────

def key(x) -> str:
    return " ".join(str(x or "").split()).casefold()


def fuel_class(fuel) -> str | None:
    """DIV 'Fuel Plus En' → CSV column (None = unknown value)."""
    k = key(fuel)
    if k.startswith("plug-in hybrid"):
        return "PHEV"
    return FUEL_CLASS.get(k)


def zero() -> dict[str, int]:
    return {k: 0 for k in COLUMNS}


# ── parsing ────────────────────────────────────────────────────────────────

def parse_file(blob: bytes, expect: set[str] | None = None) -> dict:
    """One DIV CSV → {period: month dict}. `expect` (the file's month for a
    monthly file) makes a row of another month an error."""
    text = blob.decode("utf-8-sig")
    rd = csv.reader(io.StringIO(text))
    header = [h.strip() for h in next(rd)]
    if header != HEADER:
        raise ValueError(f"unexpected header {header} (expected {HEADER})")
    ix = {h: i for i, h in enumerate(HEADER)}
    months: dict[str, dict] = {}
    for r in rd:
        if not r or not any(r):
            continue
        p = r[ix["Month End Date"]][:7]
        if expect is not None and p not in expect:
            raise ValueError(f"row of month {p!r} in the file for {sorted(expect)}")
        m = months.setdefault(p, {"rows": {v: zero() for v in VARIANT_CSV},
                                  "unknown": collections.defaultdict(lambda: [0, set()]),
                                  "used_cars": 0})
        n = int(r[ix["N Rowcount"]] or 0)
        use = key(r[ix["Vehicle Use Group En"]])
        v = USE_VARIANT.get(use)
        if v is None:
            if use not in USE_IGNORED:
                m["unknown"]["Whole"][0] += n
                m["unknown"]["Whole"][1].add(f"use group {r[ix['Vehicle Use Group En']]}")
            continue
        status = key(r[ix["New Vehicle Flag Label"]])
        if status == USED:
            if v == "Whole":
                m["used_cars"] += n
            continue
        if status != NEW:
            m["unknown"][v][0] += n
            m["unknown"][v][1].add(f"vehicle flag {r[ix['New Vehicle Flag Label']]}")
            continue
        cls = fuel_class(r[ix["Fuel Plus En"]])
        if cls is None:
            m["unknown"][v][0] += n
            m["unknown"][v][1].add(f"fuel {r[ix['Fuel Plus En']]}")
            cls = "OTHERS"
        m["rows"][v][cls] += n
        if v == "Whole":
            keeper = key(r[ix["Titular Type Label"]])
            if keeper not in (KEEPER_PRIVATE, KEEPER_VAT):
                m["unknown"]["Private"][0] += n
                m["unknown"]["Private"][1].add(f"keeper {r[ix['Titular Type Label']]}")
                continue
            m["rows"]["Private" if keeper == KEEPER_PRIVATE else "Industry"][cls] += n
    for m in months.values():
        for row in m["rows"].values():
            row["TOTAL"] = sum(row[k] for k in COLUMNS)
        m["unknown"] = {v: (n, sorted(l)) for v, (n, l) in m["unknown"].items()}
    return months


# ── CSV line-level upsert (invariant 2) ────────────────────────────────────

def csv_columns() -> list[str]:
    return ["period", "time_interval", "variant", "source"] + COLUMNS + ["TOTAL", "notes"]


def fmt(v: int) -> str:
    return f"{float(v):.1f}"


def render_line(period: str, variant: str, counts: dict[str, int], notes: str) -> str:
    buf = io.StringIO()
    csv.writer(buf, lineterminator="").writerow(
        [period, "monthly", variant, SOURCE] + [fmt(counts[k]) for k in COLUMNS]
        + [fmt(counts["TOTAL"]), notes])
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
    """When an ACEA row is replaced, keep ACEA's figure in the note (the
    correction trail: ACEA stays the cross-check)."""
    if not old or (old.get("source") or "").strip().upper() != "ACEA":
        return ""
    if old.get("time_interval") != "monthly" or not old.get("TOTAL"):
        return f"; replaces ACEA {old.get('time_interval')} row"
    diffs = []
    for k in COLUMNS + ["TOTAL"]:
        a = int(round(float(old[k]))) if old.get(k) else 0
        if a != counts[k]:
            diffs.append(f"{k} {a}")
    if not diffs:
        return "; = ACEA"
    a = int(round(float(old["TOTAL"])))
    return f"; replaces ACEA (TOTAL {a}, {counts['TOTAL'] - a:+d}; ACEA had " + " / ".join(diffs) + ")"


# ── months & checks ────────────────────────────────────────────────────────

def month_range(first: str, last: str) -> list[str]:
    y, m = map(int, first.split("-"))
    out = []
    while f"{y}-{m:02d}" <= last:
        out.append(f"{y}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def previous_month(today: dt.date) -> str:
    y, m = (today.year - 1, 12) if today.month == 1 else (today.year, today.month - 1)
    return f"{y}-{m:02d}"


def month_url(p: str) -> str:
    return BASE_URL + MONTH_FILE.format(ym=p.replace("-", ""))


def months_to_read(have: dict[str, dict], target: str, backfill: bool) -> list[str]:
    """Monthly files to request: every month after the last DIV month of
    data/Belgium.csv up to `target`, plus the last RECENT_MONTHS DIV months
    (a replaced file would be picked up). Never before FIRST_MONTHLY_FILE."""
    if backfill:
        first = FIRST_MONTHLY_FILE
    else:
        div = sorted(p for p, r in have.items() if r.get("source") == SOURCE)
        first = month_range("2000-01", div[-1])[-RECENT_MONTHS] if div else FIRST_MONTHLY_FILE
        first = max(first, FIRST_MONTHLY_FILE)
    return month_range(first, target) if first <= target else []


def median_fraction(period: str, total: int, have: dict[str, dict]) -> float | None:
    prior = sorted(p for p in have if p < period and have[p].get("time_interval") == "monthly"
                   and have[p].get("TOTAL"))[-12:]
    if len(prior) < 6:
        return None
    vals = sorted(float(have[p]["TOTAL"]) for p in prior)
    median = vals[len(vals) // 2]
    return total / median if median else None


def acea_check(p: str, row: dict, old: dict | None) -> str | None:
    """Whole vs the ACEA row being replaced — a line for the report, or None."""
    if not old or (old.get("source") or "").upper() != "ACEA" or old.get("time_interval") != "monthly":
        return None
    a = float(old.get("TOTAL") or 0)
    if not a:
        return None
    d = (row["TOTAL"] - a) / a
    return f"{p}: DIV {row['TOTAL']:,} vs ACEA {a:,.0f} ({d:+.2%})" + (" — CHECK" if abs(d) > ACEA_WARN else "")


# ── main ───────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--variant", default="all", help="all | " + " | ".join(VARIANT_CSV))
    ap.add_argument("--period", default="", help="Target month YYYY-MM (default: last month)")
    ap.add_argument("--backfill", action="store_true",
                    help=f"Write every month from {FIRST_PERIOD} on (reads the history file).")
    ap.add_argument("--force", action="store_true",
                    help="Ignore the self-throttle, the guards and foreign source strings.")
    ap.add_argument("--from-dir", default="",
                    help="Offline: DIR/YYYYMM.csv per month and DIR/hist.csv.")
    ap.add_argument("--dump-dir", default="", help="Save every downloaded file here.")
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

    session = None
    if not args.from_dir:
        import requests
        session = requests.Session()
        session.headers.update(UA)

    def fetch(name: str, url: str) -> bytes | None:
        if args.from_dir:
            f = Path(args.from_dir) / name
            return f.read_bytes() if f.exists() else None
        r = session.get(url, timeout=300)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        if b"<html" in r.content[:500].lower():
            raise SystemExit(f"{url}: got an HTML page, not a CSV (bot challenge?) — not writing.")
        if args.dump_dir:
            Path(args.dump_dir).mkdir(parents=True, exist_ok=True)
            (Path(args.dump_dir) / name).write_bytes(r.content)
        return r.content

    months: dict[str, dict] = {}
    if args.backfill:
        blob = fetch("hist.csv", BASE_URL + HISTORY_FILE)
        if blob is None:
            sys.exit(f"history file {HISTORY_FILE} not found — not writing.")
        months.update({p: m for p, m in parse_file(blob).items()
                       if FIRST_PERIOD <= p < FIRST_MONTHLY_FILE})
    for p in months_to_read(have["Whole"], target, args.backfill):
        blob = fetch(p.replace("-", "") + ".csv", month_url(p))
        if blob is None:
            print(f"{p}: not published yet (404) — stopping the forward probe here.")
            break
        months.update(parse_file(blob, {p}))
    if not months:
        print(f"No new DIV month up to {target} — retry next run.")
        return emit(args, set())
    if target not in months and not args.backfill:
        print(f"::notice title=Belgium {target}::not published by DIV yet; "
              f"writing what is out ({min(months)} … {max(months)}).")

    problems: list[str] = []
    for p in sorted(months):
        for v, (n, labels) in months[p]["unknown"].items():
            tot = months[p]["rows"]["Whole" if v == "Private" else v]["TOTAL"] or 1
            if n / tot > MAX_UNKNOWN_SHARE and not args.force:
                problems.append(f"{p} {v}: {n} vehicles ({n / tot:.1%}) with unknown values {labels}")
            elif labels:
                print(f"::warning title=New value {p} {v}::{labels} → OTHERS / skipped")
    if problems:
        sys.exit("Governance check failed — not writing:\n  " + "\n  ".join(problems[:20]))

    changed: set[str] = set()
    report_rows, acea_lines = [], []
    for v in variants:
        updates = {}
        for p in sorted(months):
            row = months[p]["rows"][v]
            tot = row["TOTAL"]
            frac = median_fraction(p, tot, have[v])
            if v == "Whole" and frac is not None and not args.force and not args.backfill:
                if frac < MIN_MONTH_FRACTION:
                    print(f"Whole {p}: TOTAL {tot:,} is {frac:.0%} of the trailing median — "
                          "looks partial; not writing (--force if genuine).")
                    continue
                if frac < WARN_MONTH_FRACTION:
                    print(f"::warning title=Belgium Whole {p} unusually low::TOTAL {tot:,} = "
                          f"{frac:.0%} of the trailing-12 median — written; check it.")
            old = have[v].get(p)
            if v == "Whole":
                line = acea_check(p, row, old)
                if line:
                    acea_lines.append(line)
            if old and old.get("source") == SOURCE and old.get("notes"):
                notes = old["notes"]           # keep the first write's ACEA trail
            else:
                notes = f"DIV {p}: {NOTES[v]}" + acea_note(old, row)
            updates[(p, v)] = render_line(p, v, row, notes)
            report_rows.append((v, p, row, old))
        if args.dry_run:
            print(f"{VARIANT_CSV[v]}: dry run, {len(updates)} row(s) computed")
            continue
        stats = upsert_lines(paths[v], updates, args.force)
        print(f"{VARIANT_CSV[v]}: {stats}")
        if stats["added"] or stats["updated"]:
            changed.add(v)

    rep = report(report_rows, target, acea_lines)
    print("\n" + rep)
    if args.step_summary:
        with open(args.step_summary, "a", encoding="utf-8") as fh:
            fh.write(rep)
    return emit(args, changed)


def report(rows, target: str, acea_lines: list[str]) -> str:
    out = [f"## Belgium (DIV) — up to {target}", ""]
    out += [f"- ACEA cross-check {l}" for l in acea_lines[-6:]]
    out += ["", "| variant | month | TOTAL | BEV | PHEV | HEV | PETROL | DIESEL | OTHERS | Δ TOTAL vs old row |",
            "|---|---|---:|---:|---:|---:|---:|---:|---:|---|"]
    for v, p, r, old in rows[-40:]:
        d = ""
        if old and old.get("TOTAL"):
            d = f"{r['TOTAL'] - int(round(float(old['TOTAL']))):+d} ({old.get('source')})"
        out.append(f"| {v} | {p} | {r['TOTAL']:,} | {r['BEV']:,} | {r['PHEV']:,} | {r['HEV']:,} | "
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
