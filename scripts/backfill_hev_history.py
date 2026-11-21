#!/usr/bin/env python3
"""HEV back-estimates for the months a country's own source has no hybrid
split, so a TTM chart shows hybrids for its whole span instead of a band
that switches on mid-chart (the late-start fold, docs 02).

Accuracy of a long-past month matters less here than a consistent picture
of the market; every estimated cell says so in the row's `notes`
(invariant 6), names the file it came from, and the source doc records the
seam to the counted months. Only rows whose HEV is blank are written;
counted rows are never touched. Writes are line-level (invariant 2).

Methods
-------
acea      Czechia. The month's pool TOTAL - BEV - PHEV - OTHERS (petrol,
          diesel and the hybrids the CSV leaves unsplit) is split by ACEA's
          quarterly HEV : petrol : diesel shares (reference/acea_country_
          quarterly.csv — SDA's own figures, the source of Czechia's HEV from
          2022). Quarters with HEV only (the 2014-2017 alternative-fuel
          releases): HEV = ACEA's HEV as a share of the quarter's pool, and
          the rest keeps the month's own petrol : diesel ratio.
register  Netherlands, Finland. HEV = the published petrol (full hybrids
          included) times the register's HEV share of HEV + pure petrol in
          that month (reference/<slug>_register_fuel_split.csv). The register
          is thinned for old months, but a share survives thinning better
          than a count, and it is the same classification as the counted
          months that follow.

    python scripts/backfill_hev_history.py --country Czechia --method acea \\
        --from 2014-01 --to 2021-12
    python scripts/backfill_hev_history.py --country Finland --method register \\
        --split reference/fi_register_fuel_split.csv --from 2014-01 --to 2024-12
"""
from __future__ import annotations

import argparse
import csv
import io
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ACEA_Q = ROOT / "reference" / "acea_country_quarterly.csv"
HISTORY_PREFIX = "HEV estimated"
NOTE_ACEA = (HISTORY_PREFIX + " (with PETROL/DIESEL): TOTAL-BEV-PHEV-OTHERS split by ACEA's "
             "{q} HEV:petrol:diesel shares (reference/acea_country_quarterly.csv)")
NOTE_ACEA_HEV = (HISTORY_PREFIX + " (with PETROL/DIESEL): ACEA's {q} HEV as a share of the "
                 "quarter's TOTAL-BEV-PHEV-OTHERS, petrol:diesel as in the month "
                 "(reference/acea_country_quarterly.csv)")
NOTE_REGISTER = (HISTORY_PREFIX + " (with PETROL): {src} petrol split by the {register}'s "
                 "HEV share of HEV+petrol in the month (reference/{file})")


def _f(row: dict, k: str) -> float:
    return float(row.get(k) or 0)


def quarter(period: str) -> str:
    return f"{period[:4]}-Q{(int(period[5:7]) - 1) // 3 + 1}"


def load_acea(country: str, path: Path = ACEA_Q) -> dict[str, dict]:
    with open(path, encoding="utf-8", newline="") as f:
        return {r["quarter"]: r for r in csv.DictReader(f) if r["country"] == country}


def pool(row: dict) -> float:
    return _f(row, "TOTAL") - _f(row, "BEV") - _f(row, "PHEV") - _f(row, "OTHERS")


def acea_estimate(row: dict, q: dict, quarter_pool: float) -> dict | None:
    """HEV / PETROL / DIESEL for one month from ACEA's quarter."""
    p = pool(row)
    if p <= 0:
        return None
    hev_q, pet_q, die_q = (float(q[k]) if q.get(k) not in ("", None) else None
                           for k in ("HEV", "PETROL", "DIESEL"))
    if hev_q is None:
        return None
    if pet_q is not None and die_q is not None and hev_q + pet_q + die_q > 0:
        s = hev_q + pet_q + die_q
        hev, die = round(p * hev_q / s), round(p * die_q / s)
        note = NOTE_ACEA.format(q=q["quarter"])
    else:
        if quarter_pool <= 0:
            return None
        hev = round(p * min(1.0, hev_q / quarter_pool))
        pd = _f(row, "PETROL") + _f(row, "DIESEL")
        die = round((p - hev) * (_f(row, "DIESEL") / pd)) if pd > 0 else 0
        note = NOTE_ACEA_HEV.format(q=q["quarter"])
    return {"HEV": float(hev), "PETROL": float(p - hev - die), "DIESEL": float(die), "notes": note}


def register_estimate(row: dict, reg: dict, src: str, register: str, file: str) -> dict | None:
    hev, pet = float(reg["HEV"]), float(reg["PETROL"])
    if hev + pet <= 0:
        return None
    petrol = _f(row, "PETROL")
    h = round(petrol * hev / (hev + pet))
    return {"HEV": float(h), "PETROL": petrol - h,
            "notes": NOTE_REGISTER.format(src=src, register=register, file=file)}


def _fmt(v) -> str:
    return f"{float(v):.1f}"


def write(csv_path: Path, filled: dict[str, dict]) -> None:
    lines = Path(csv_path).read_text(encoding="utf-8").splitlines(keepends=True)
    header = next(csv.reader([lines[0]]))
    out = [lines[0]]
    for line in lines[1:]:
        rec = dict(zip(header, next(csv.reader([line]))))
        upd = filled.get(rec.get("period")) if rec.get("variant") == "Whole" else None
        if upd is None:
            out.append(line)
            continue
        for k, v in upd.items():
            if k != "notes":
                rec[k] = _fmt(v)
        old = (rec.get("notes") or "").strip()
        rec["notes"] = upd["notes"] + (f"; {old}" if old else "")
        buf = io.StringIO()
        csv.writer(buf, lineterminator="\n").writerow([rec.get(h, "") for h in header])
        out.append(buf.getvalue())
    Path(csv_path).write_text("".join(out), encoding="utf-8")


def candidates(csv_path: Path, start: str, end: str) -> list[dict]:
    with open(csv_path, encoding="utf-8", newline="") as f:
        return [r for r in csv.DictReader(f)
                if r["variant"] == "Whole" and r["time_interval"] == "monthly"
                and start <= r["period"] <= end and r.get("TOTAL")
                and not (r.get("HEV") or "").strip()]


def run(country: str, method: str, start: str, end: str, split: Path | None = None,
        cohort: str | None = None, csv_path: Path | None = None) -> dict[str, dict]:
    csv_path = csv_path or ROOT / "data" / f"{country}.csv"
    rows = candidates(csv_path, start, end)
    filled: dict[str, dict] = {}
    if method == "acea":
        acea = load_acea(country)
        qpool: dict[str, float] = {}
        for r in rows:
            qpool[quarter(r["period"])] = qpool.get(quarter(r["period"]), 0.0) + pool(r)
        for r in rows:
            q = acea.get(quarter(r["period"]))
            est = acea_estimate(r, q, qpool[quarter(r["period"])]) if q else None
            if est:
                filled[r["period"]] = est
    else:
        with open(split, encoding="utf-8", newline="") as f:
            reg = {x["period"]: x for x in csv.DictReader(f)
                   if not cohort or x.get("cohort") == cohort}
        src = {"Netherlands": "Swing", "Finland": "StatFin"}.get(country, country)
        register = {"Netherlands": "RDW register" + (f" ({cohort} cohort)" if cohort else ""),
                    "Finland": "Traficom register"}.get(country, "register")
        for r in rows:
            m = reg.get(r["period"])
            est = register_estimate(r, m, src, register, Path(split).name) if m else None
            if est:
                filled[r["period"]] = est
    if filled:
        write(csv_path, filled)
    return filled


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--country", required=True)
    ap.add_argument("--method", choices=("acea", "register"), required=True)
    ap.add_argument("--from", dest="start", required=True)
    ap.add_argument("--to", dest="end", required=True)
    ap.add_argument("--split", type=Path, help="register fuel split (method register)")
    ap.add_argument("--cohort", help="register cohort to use (Netherlands)")
    args = ap.parse_args()
    if args.method == "register" and not args.split:
        ap.error("--split is required for --method register")
    filled = run(args.country, args.method, args.start, args.end, args.split, args.cohort)
    print(f"{args.country}: {len(filled)} month(s) estimated "
          f"({min(filled, default='-')} .. {max(filled, default='-')})")


if __name__ == "__main__":
    main()
