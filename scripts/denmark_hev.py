"""Denmark's HEV: Statbank's combustion cars split by ACEA's shares.

Statistics Denmark (StatBank BIL51 / BIL53) has no code for non-plug-in
hybrids. BIL51's "Hybrid/petrol" + "Hybrid/diesel" are the plug-in
hybrids: they equal BIL53's "Pluginhybrid" in every month 2018-01 ..
2026-10. Full and mild hybrids sit inside BIL53's Petrol and Diesel, and
the DMR open extract cannot tell them apart either (it records a hybrid
only through an electric consumption, i.e. a plug-in).

ACEA's Danish HEV is Mobility Denmark's (bilstatistik.dk) "Hybrid" +
"Mild Hybrid": 25,128 in 2025 on both sides. About three quarters of it are
mild hybrids (70% in 2024, 75% in 2025, 78% in Jan-Oct 2026), and
about half of Statbank's diesel are diesel mild hybrids (2025: Statbank
diesel 9,707, Mobility Denmark pure diesel 4,774). So unlike Finland,
where every hybrid sits in StatFin's petrol, Denmark's split has to take
hybrids out of petrol AND diesel:

    pool    = Statbank petrol + Statbank diesel       (kept exactly)
    HEV     = round(pool x ACEA HEV    / ACEA (HEV + petrol + diesel))
    DIESEL  = round(pool x ACEA diesel / ACEA (HEV + petrol + diesel))
    PETROL  = pool - HEV - DIESEL

TOTAL, BEV, PHEV and OTHERS stay Statbank's; HEV + PETROL + DIESEL is
Statbank's petrol + diesel exactly, so every row still sums to TOTAL.
A share, not ACEA's count: ACEA's combustion pool runs 0.6-6.1% below
Statbank's (a slightly narrower scope), and a count would push that gap
into PETROL. HEV means full + mild hybrids, ACEA's definition, as for the
Netherlands, Finland and Czechia.

Where each split comes from (notes, invariant 6):

  ACEA's month, once ACEA publishes it (about the 22nd of the next month)
      ACEA_NOTE
  newer months before that (Statbank is out about the 10th)
      estimate: the previous month's shares, PREVIOUS_NOTE
  history months ACEA has no figure for on their own (2022's quarters,
  three two-month spans in 2023; scripts/backfill_denmark_hev.py)
      estimate: the span's shares, HISTORY_NOTE

Two gates:

* HEV_FILL_FROM (2022-01): the first month ACEA's Danish HEV means full +
  mild hybrids. Older rows keep HEV blank (unknown).
* ready(): no HEV is written while a Whole row has a TOTAL but neither
  PETROL nor DIESEL (2014-01 .. 2017-12 until 2026-11-22). build_series.py stage 3
  only turns a remainder into ICE when every electrified column of the
  file is present, so a single HEV row would drop those 48 months from
  the interactive series (154 -> 106 points). Filling their petrol/diesel
  from BIL51 (scripts/backfill_denmark_bil51.py --write) lifts the gate.

fetch_denmark.py keeps a split when Statbank restates a month
(carry_split) and estimates a new month (estimate_newest); fetch_acea.py
puts ACEA's month on (apply_acea). Only data/Denmark.csv (Whole): ACEA
has no Private / Industry split.
"""
from __future__ import annotations

import argparse
import csv
import io
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = ROOT / "data" / "Denmark.csv"

# First month that may carry a split. ACEA's Danish HEV counts mild
# hybrids from 2022-Q1 on (the quarter its HEV jumps ~4x while HEV +
# petrol + diesel stays flat: a reclassification, not a market move), so
# from 2022-01 the split means one thing throughout. 2014-2021 keep HEV
# blank (unknown): ACEA's Danish HEV before 2022 is a different quantity.
# History 2022-01 .. 2026-09 was filled once by
# scripts/backfill_denmark_hev.py (reference/acea_denmark_hev.csv).
HEV_FILL_FROM = "2022-01"

ACEA_NOTE = ("TOTAL/BEV/PHEV/OTHERS api.statbank.dk (BIL53); HEV/PETROL/DIESEL = "
             "Statbank petrol+diesel split by ACEA's HEV:petrol:diesel shares for "
             "the month (HEV = full + mild hybrids, Mobility Denmark via ACEA)")
PREVIOUS_NOTE = ("TOTAL/BEV/PHEV/OTHERS api.statbank.dk (BIL53); HEV/PETROL/DIESEL "
                 "estimated: Statbank petrol+diesel split by {prev}'s shares, until "
                 "ACEA covers the month")
PREVIOUS_PREFIX = PREVIOUS_NOTE.split("{prev}")[0]
# History rows with no ACEA month of their own (2022's quarters, a few
# 2023 two-month spans where a release is missing): the span's shares.
HISTORY_NOTE = ("TOTAL/BEV/PHEV/OTHERS api.statbank.dk (BIL53); HEV/PETROL/DIESEL "
                "estimated: Statbank petrol+diesel split by ACEA's {span} shares "
                "(no ACEA figure for the month alone)")
HISTORY_PREFIX = HISTORY_NOTE.split("{span}")[0]
# A split row keeps Statbank's own petrol and diesel in its notes, so the
# published figures are never lost and a restatement is recognised.
STATBANK_TAG = " [Statbank petrol {petrol:.0f}, diesel {diesel:.0f}]"
_TAG_RE = re.compile(r" \[Statbank petrol (\d+), diesel (\d+)\]$")

# ACEA's Danish row must be Statbank's month. TOTAL and BEV only: the two
# relay the same register but count a few dozen plug-in hybrids
# differently (2025-12: 420 vs 437, 2026-04: 113 vs 119), and PHEV is
# Statbank's anyway, so a PHEV gate would only refuse good months.
ACEA_TOTAL_TOLERANCE = 0.015
ACEA_BEV_TOLERANCE = 0.02
SPLIT = ("HEV", "PETROL", "DIESEL")


def _f(row: dict, k: str) -> float:
    return float(row.get(k) or 0)


def _blank(row: dict, k: str) -> bool:
    v = row.get(k)
    return v is None or (isinstance(v, str) and not v.strip())


def split_kind(row: dict) -> str | None:
    """Which step put HEV on this row: "acea", "history", "previous" or None."""
    if _blank(row, "HEV"):
        return None
    notes = row.get("notes") or ""
    if notes.startswith(ACEA_NOTE):
        return "acea"
    if notes.startswith(HISTORY_PREFIX):
        return "history"
    if notes.startswith(PREVIOUS_PREFIX):
        return "previous"
    return None


def statbank_fuels(row: dict) -> tuple[float, float]:
    """Statbank's own (petrol, diesel) for any row, split or not."""
    if split_kind(row) is not None:
        m = _TAG_RE.search(row.get("notes") or "")
        if m:
            return float(m.group(1)), float(m.group(2))
    return _f(row, "PETROL"), _f(row, "DIESEL")


def note(base: str, row: dict) -> str:
    petrol, diesel = statbank_fuels(row)
    return base + STATBANK_TAG.format(petrol=petrol, diesel=diesel)


def base_note(row: dict) -> str:
    return _TAG_RE.sub("", row.get("notes") or "")


def pool(row: dict) -> float:
    """Statbank's own petrol + diesel (hybrids included) for any row."""
    return _f(row, "HEV") + _f(row, "PETROL") + _f(row, "DIESEL")


def shares(row: dict) -> tuple[float, float] | None:
    """(HEV, diesel) shares of the combustion pool of a row with a split."""
    p = pool(row)
    if split_kind(row) is None or p <= 0:
        return None
    return _f(row, "HEV") / p, _f(row, "DIESEL") / p


def split_pool(total: float, hev_share: float, diesel_share: float) -> dict:
    hev = float(round(total * hev_share))
    die = float(round(total * diesel_share))
    pet = total - hev - die
    if pet < 0:                      # rounding on a tiny pool
        die += pet
        pet = 0.0
    return {"HEV": hev, "PETROL": pet, "DIESEL": die}


def carry_split(old: dict, new: dict) -> dict:
    """A Statbank restatement of a month that already has a split.

    Statbank writes its months with HEV blank and hybrids inside petrol
    and diesel. The month's shares are re-applied to the restated pool,
    so HEV + PETROL + DIESEL stays Statbank's petrol + diesel.
    """
    sh = shares(old)
    if sh is None:
        return new
    return {**new, **split_pool(pool(new), *sh), "notes": note(base_note(old), new)}


def same_month(row: dict, acea: dict) -> bool:
    for k, tol, floor in (("TOTAL", ACEA_TOTAL_TOLERANCE, 0.0),
                          ("BEV", ACEA_BEV_TOLERANCE, 5.0)):
        n, a = _f(row, k), float(acea.get(k) or 0)
        if abs(a - n) > max(floor, tol * n):
            return False
    return True


def acea_merge(row: dict, acea: dict) -> dict | None:
    """Statbank's petrol + diesel split by ACEA's shares, or None."""
    if row.get("period", "") < HEV_FILL_FROM or not same_month(row, acea):
        return None
    h, p, d = (float(acea.get(k) or 0) for k in SPLIT)
    if h + p + d <= 0:
        return None
    return {**split_pool(pool(row), h / (h + p + d), d / (h + p + d)),
            "notes": note(ACEA_NOTE, row)}


def whole_rows(csv_path: Path = CSV_PATH) -> dict[str, dict]:
    with open(csv_path, encoding="utf-8", newline="") as f:
        return {r["period"]: r for r in csv.DictReader(f)
                if r["variant"] == "Whole" and r["time_interval"] == "monthly"
                and r.get("TOTAL")}


def unsplit_history(rows: dict[str, dict]) -> list[str]:
    """Rows build_series.py would drop once any row has HEV: a TOTAL and
    no combustion split at all (petrol and diesel both blank)."""
    return sorted(p for p, r in rows.items()
                  if _blank(r, "HEV") and _blank(r, "PETROL") and _blank(r, "DIESEL"))


def ready(csv_path: Path = CSV_PATH, quiet: bool = False) -> bool:
    gap = unsplit_history(whole_rows(csv_path))
    if gap and not quiet:
        print(f"    Denmark: HEV split waits — {len(gap)} Whole rows ({gap[0]} .. {gap[-1]}) "
              f"have no petrol/diesel; one HEV row would drop them from the "
              f"interactive series (scripts/backfill_denmark_bil51.py)")
    return not gap


def _fmt(v) -> str:
    return f"{float(v):.1f}"


def write_split(csv_path: Path, filled: dict[str, dict]) -> None:
    """Rewrite only the Whole lines of the filled periods (invariant 2)."""
    lines = Path(csv_path).read_text(encoding="utf-8").splitlines(keepends=True)
    header = next(csv.reader([lines[0]]))
    out = [lines[0]]
    for line in lines[1:]:
        rec = dict(zip(header, next(csv.reader([line]))))
        upd = filled.get(rec.get("period")) if rec.get("variant") == "Whole" else None
        if upd is None:
            out.append(line)
            continue
        for k in SPLIT:
            rec[k] = _fmt(upd[k])
        rec["notes"] = upd["notes"]
        buf = io.StringIO()
        csv.writer(buf, lineterminator="\n").writerow([rec.get(h, "") for h in header])
        out.append(buf.getvalue())
    Path(csv_path).write_text("".join(out), encoding="utf-8")


def _chain(rows: dict[str, dict], targets: set[str]) -> dict[str, dict]:
    """Split each target month by the shares of the month before it, in
    date order, so a chain of estimates follows its first real month."""
    filled: dict[str, dict] = {}
    prev = None
    for period in sorted(rows):
        row = rows[period]
        if period in targets and prev is not None:
            sh = shares(prev)
            if sh is not None:
                filled[period] = {**split_pool(pool(row), *sh),
                                  "notes": note(PREVIOUS_NOTE.format(prev=prev["period"]), row)}
                row = {**row, **{k: str(v) for k, v in filled[period].items()}}
                print(f"  Denmark {period}: HEV {filled[period]['HEV']:.0f} estimated "
                      f"from {prev['period']}'s shares")
        prev = row if split_kind(row) else None
    return filled


def estimate_newest(csv_path: Path = CSV_PATH) -> list[str]:
    """Give every month from HEV_FILL_FROM without a split the previous
    month's shares (flagged). Statbank is out about twelve days before
    ACEA; without this the newest month would be HEV-blank and the TTM
    would stop a month early. Returns the periods written."""
    if not ready(csv_path):
        return []
    rows = whole_rows(csv_path)
    targets = {p for p, r in rows.items() if p >= HEV_FILL_FROM and split_kind(r) is None}
    filled = _chain(rows, targets)
    if filled:
        write_split(csv_path, filled)
    return sorted(filled)


def apply_acea(period: str, acea: dict, csv_path: Path = CSV_PATH) -> bool:
    """fetch_acea.py's hook: merge one ACEA month. True if the CSV changed."""
    row = whole_rows(csv_path).get(period)
    if row is None:
        print(f"    Denmark {period}: no Statbank row yet; ACEA split waits for it")
        return False
    if period < HEV_FILL_FROM:
        print(f"    Denmark {period}: before {HEV_FILL_FROM}; HEV stays blank (no backfill)")
        return False
    if not ready(csv_path):
        return False
    upd = acea_merge(row, acea)
    if upd is None:
        print(f"    Denmark {period}: ACEA HEV not merged (ACEA's TOTAL/BEV are not "
              f"Statbank's month)")
        return False
    if split_kind(row) == "acea" and all(abs(_f(row, k) - upd[k]) < 0.5 for k in SPLIT):
        return False
    write_split(csv_path, {period: upd})
    print(f"    Denmark {period}: HEV {upd['HEV']:.0f} / petrol {upd['PETROL']:.0f} / "
          f"diesel {upd['DIESEL']:.0f} (Statbank petrol+diesel split by ACEA's shares)")
    # A later month estimated from this one's old shares follows it.
    rows = whole_rows(csv_path)
    later = {p for p, r in rows.items() if p > period and split_kind(r) == "previous"}
    if later:
        write_split(csv_path, _chain(rows, later))
    return True


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", type=Path, default=CSV_PATH)
    ap.add_argument("--check", action="store_true",
                    help="print whether the HEV split may write, write nothing")
    ap.add_argument("--acea-pdf", type=Path,
                    help="apply one downloaded ACEA press-release PDF (with --period)")
    ap.add_argument("--period", help="YYYY-MM of --acea-pdf")
    args = ap.parse_args()
    if args.check:
        ok = ready(args.csv)
        print("ready" if ok else "not ready")
        return
    if args.acea_pdf:
        import fetch_acea
        parsed, _ = fetch_acea.parse_monthly_table(str(args.acea_pdf), ["Denmark"])
        if "Denmark" not in parsed:
            raise SystemExit("Denmark not found in the PDF")
        acea = {k: float(v[0]) for k, v in parsed["Denmark"].items()}
        apply_acea(args.period, acea, args.csv)
        return
    ap.print_help()


if __name__ == "__main__":
    main()
