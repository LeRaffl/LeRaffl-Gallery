#!/usr/bin/env python3
"""Compare the Vietnam series with independently published figures.

Reads data/raw/vietnam/components.csv (every input of data/Vietnam.csv) and
the hand-kept checks/vietnam_reference.csv, writes market/vietnam_checks.json
(rendered on the source page under "Why other figures differ", doc 03
§ 3.16b) and lists what is due to be looked up:

  media_total   the monthly "whole market" figure Vietnamese media print
                (VAMA total industry + VinFast + TC Group, every vehicle
                type) — must match our inputs; a gap means a revision or a
                typo on one side
  media_year    the same for a calendar year
  csgt          the traffic police's new-registration count (cars incl.
                trucks, 15 Dec → 14 Jun / 14 Dec) — a different measure,
                shown for scale only

Due: a media total for each of the three newest months once the 20th of the
following month has passed (older gaps stay open: such reports are hard to
find later); CSGT H1 from 1 July, the CSGT year from 5 January; any row
without a URL. `--due FILE` writes that list as Markdown (for the reminder
issue) and prints it; the exit code is 0 either way.

Run:  python scripts/check_vietnam_reference.py [--due due.md] [--today YYYY-MM-DD]
"""
import argparse
import csv
import datetime as dt
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
COMPONENTS = REPO / "data" / "raw" / "vietnam" / "components.csv"
REFERENCE = REPO / "checks" / "vietnam_reference.csv"
OUT = REPO / "market" / "vietnam_checks.json"
FIRST_CSGT_YEAR = 2025          # the series starts 2024-09: CSGT 2025 (from 15 Dec 2024) is the first full one

RECENT = 3                      # media totals are chased for the newest months only
TOL_EXACT = 0.001               # 0.1 % — media sometimes carry a first-reported VinFast figure
TOL_ROUNDED = 0.005             # "hơn / gần / khoảng N" — rounded to the hundred or thousand


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def all_vehicles(row: dict) -> int | None:
    """VAMA total industry + VinFast + TC Group total: what the media add up."""
    try:
        return int(row["vama_ti"]) + int(row["vinfast"]) + int(row["tc_total"])
    except (KeyError, ValueError):
        return None


def months(a: str, b: str) -> list[str]:
    y, m = int(a[:4]), int(a[5:7])
    out = []
    while f"{y:04d}-{m:02d}" <= b[:7]:
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def check_rows(comp: dict[str, dict], refs: list[dict]) -> list[dict]:
    checks = []
    for r in refs:
        kind, fig = r["kind"], int(r["figure"]) if r.get("figure") else None
        rounded = r.get("rounded", "").strip().lower() == "yes"
        base = {"url": r.get("url", ""), "note": r.get("note", "")}
        if kind == "media_total":
            p = r["period_from"]
            ours = all_vehicles(comp.get(p, {}))
            tol = TOL_ROUNDED if rounded else TOL_EXACT
            c = {"period": p, "check": "Media: whole market, every vehicle type",
                 "source": "VAMA total industry + VinFast + TC Group (our inputs, summed the same way)",
                 "tolerance": f"±{tol:.1%}" + (" (published figure rounded)" if rounded else "")}
        elif kind == "media_year":
            ms = months(r["period_from"], r["period_to"])
            vals = [all_vehicles(comp.get(p, {})) for p in ms]
            ours = sum(vals) if all(v is not None for v in vals) else None
            tol = TOL_ROUNDED if rounded else 0.01
            c = {"period": r["period_from"][:4], "check": "Media: year total, every vehicle type",
                 "source": "sum of our monthly inputs (VAMA + VinFast + TC Group)",
                 "tolerance": f"±{tol:.1%}"}
            if ours is None:
                base["note"] = "; ".join(x for x in (base["note"], f"our series starts {min(comp)}") if x)
        elif kind == "csgt":
            # 15 Dec → 14 Jun / 14 Dec: compare with our Dec → May / Dec → Nov months
            start = r["period_from"][:7]
            end_m = r["period_to"][:7]
            y, m = int(end_m[:4]), int(end_m[5:7])
            end = f"{y:04d}-{m - 1:02d}" if m > 1 else f"{y - 1:04d}-12"
            ms = months(start, end)
            vals = [all_vehicles(comp.get(p, {})) for p in ms]
            ours = sum(vals) if all(v is not None for v in vals) else None
            tol = None
            c = {"period": f"{r['period_from']} → {r['period_to']}",
                 "check": "Traffic police (CSGT): new car registrations",
                 "source": f"vs. our inputs {ms[0]} … {ms[-1]} — a different measure (registrations incl. "
                           "trucks; sales are reported, registrations follow), shown for scale",
                 "tolerance": "none (information)"}
        else:
            continue
        theirs = fig
        gap = (ours - theirs) if ours is not None and theirs is not None else None
        pct = round(gap / theirs * 100, 2) if gap is not None and theirs else None
        if theirs is None:
            status = "missing"
        elif tol is None or ours is None:
            status = "info"
        else:
            status = "pass" if abs(gap) <= tol * theirs + 0.5 else "warn"
        c.update(ours=ours, theirs=theirs, gap=gap, gap_pct=pct, status=status, **base)
        checks.append(c)
    return checks


def due_items(comp: dict[str, dict], refs: list[dict], today: dt.date) -> tuple[list[str], list[dict]]:
    """→ (Markdown bullet lines, placeholder 'missing' checks)."""
    have = {(r["kind"], r["period_from"], r["period_to"]) for r in refs}
    lines, missing = [], []
    for p in sorted(comp)[-RECENT:]:
        y, m = int(p[:4]), int(p[5:7])
        ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
        if today >= dt.date(ny, nm, 20) and ("media_total", p, p) not in have:
            lines.append(f"- **Media total {p}**: the whole-market figure (VAMA + VinFast + TC Group) "
                         f"a Vietnamese outlet printed for {p} — our inputs add up to "
                         f"{all_vehicles(comp[p]) or 0:,}.")
            missing.append({"period": p, "check": "Media: whole market, every vehicle type",
                            "source": "", "url": "", "ours": all_vehicles(comp[p]), "theirs": None,
                            "gap": None, "gap_pct": None, "tolerance": "", "status": "missing",
                            "note": "reference figure not entered yet"})
    for year in range(FIRST_CSGT_YEAR, today.year + 1):
        h1 = ("csgt", f"{year - 1}-12-15", f"{year}-06-14")
        fy = ("csgt", f"{year - 1}-12-15", f"{year}-12-14")
        if today >= dt.date(year, 7, 1) and h1 not in have:
            lines.append(f"- **CSGT H1 {year}** (15 Dec {year - 1} → 14 Jun {year}): new car registrations "
                         "from the traffic police's half-year press conference.")
        if today >= dt.date(year + 1, 1, 5) and fy not in have:
            lines.append(f"- **CSGT year {year}** (15 Dec {year - 1} → 14 Dec {year}): new car registrations "
                         "from the traffic police's year-end report.")
    for r in refs:
        if not r.get("url"):
            lines.append(f"- **URL missing** for {r['kind']} {r['period_from']} → {r['period_to']} "
                         f"({r.get('figure') or 'no figure'}).")
    return lines, missing


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--due", default="", help="Write the due list as Markdown to this file")
    ap.add_argument("--today", default="", help="Override today's date (YYYY-MM-DD, tests)")
    ap.add_argument("--no-write", action="store_true", help="Do not write market/vietnam_checks.json")
    args = ap.parse_args(argv)
    today = dt.date.fromisoformat(args.today) if args.today else dt.date.today()
    comp = {r["period"]: r for r in read_csv(COMPONENTS)}
    if not comp:
        print(f"{COMPONENTS.relative_to(REPO)} missing — nothing to check")
        return 0
    refs = read_csv(REFERENCE)
    checks = check_rows(comp, refs)
    lines, missing = due_items(comp, refs, today)
    checks = sorted(checks + missing, key=lambda c: (c["check"].startswith("Traffic"),
                                                     c["check"].startswith("Media: year"),
                                                     str(c["period"])), reverse=False)
    complete = [p for p, r in comp.items() if all_vehicles(r) is not None]
    doc = {"schema": 1, "country": "Vietnam", "as_of": max(complete) if complete else max(comp),
           "title": "Our inputs against published totals",
           "checks": checks}
    text = json.dumps(doc, ensure_ascii=False, indent=1) + "\n"
    if not args.no_write:
        old = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if old != text:
            OUT.write_text(text, encoding="utf-8")
            print(f"{OUT.relative_to(REPO)} written")
        else:
            print(f"{OUT.relative_to(REPO)} unchanged")
    for c in checks:
        if c["status"] == "warn":
            print(f"::warning title=Vietnam check {c['period']}::{c['check']}: ours {c['ours']:,} vs "
                  f"{c['theirs']:,} ({c['gap_pct']:+.2f} %) — {c['note']}")
    md = "\n".join(lines)
    print(md or "Nothing due.")
    if args.due:
        Path(args.due).write_text(md + ("\n" if md else ""), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
