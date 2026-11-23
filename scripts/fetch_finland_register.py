"""Finland's HEV: StatFin's petrol split by a hybrid share.

StatFin 121d stays the published TOTAL / BEV / PHEV / DIESEL / OTHERS and
has no full-hybrid code (they sit in petrol). Neither do Traficom's monthly
tables. Every row splits only StatFin's petrol, HEV = petrol x a share, so
HEV + PETROL is StatFin's petrol exactly:

  from 2025-01, covered by the latest register snapshot
      the share Traficom's open register (Ajoneuvorekisteri.zip, about
      quarterly) counts: hybrid class 02 / (class 02 + pure petrol)
  newer months, once ACEA has published them
      estimate: ACEA's HEV share of HEV+petrol
  newer months before that
      estimate: the previous month's share
  2014-01 .. 2024-12
      estimate, written once by backfill_hev_history.py from the
      register's monthly split (reference/fi_register_fuel_split.csv)

A share, not the register's counts: the snapshot has lost a few percent of
each month's cars since, and the gap would land in OTHERS. ACEA is never a
count either: its HEV+petrol runs 10-30 cars above StatFin's petrol
(2024-11 .. 2026-09). Every estimate says so in `notes` (invariant 6), and
the next snapshot replaces it with the register's share.

fetch_finland.py keeps the split when StatFin restates a month
(carry_split) and estimates a new month (estimate_newest); fetch_acea.py
puts ACEA's share on (apply_acea); fetch-finland.yml applies a new
snapshot (--write-register --download). --shadow-* print and write nothing.

Dates are not ISO. ``ensirekisterointipvm`` is DD.MM.YYYY.
``kayttoonottopvm`` is YYYYMMDD. Whole is M1+M1G with both dates in the
registration month. Used is the same classes with first use before that
month. A later or empty use-date is neither.
"""
from __future__ import annotations

import argparse
import csv
import io
import zipfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = ROOT / "data" / "Finland.csv"
PASSENGER = {"M1", "M1G"}
FUELS = ("BEV", "PHEV", "HEV", "PETROL", "DIESEL", "OTHERS")

# Same shape as acea_split.NOTE, so a row says where every column came
# from. StatFin has no full-hybrid code; the register does.
REGISTER_NOTE = ("TOTAL/BEV/PHEV/DIESEL/OTHERS StatFin 121d; HEV/PETROL = StatFin "
                 "petrol split by the Traficom register's counted HEV share of "
                 "HEV+petrol (M1+M1G, first use in the registration month)")

ACEA_NOTE = ("TOTAL/BEV/PHEV/DIESEL/OTHERS StatFin 121d; HEV/PETROL estimated: "
             "StatFin petrol split by ACEA's HEV share of HEV+petrol for the month, "
             "until a Traficom register snapshot covers it")
PREVIOUS_NOTE = ("TOTAL/BEV/PHEV/DIESEL/OTHERS StatFin 121d; HEV/PETROL estimated: "
                 "StatFin petrol split by {prev}'s HEV share, until ACEA or a "
                 "Traficom register snapshot covers the month")
PREVIOUS_PREFIX = PREVIOUS_NOTE.split("{prev}")[0]
# The one-off back-estimate before 2025 (scripts/backfill_hev_history.py):
# StatFin petrol split by the register's monthly HEV share.
HISTORY_PREFIX = "HEV estimated"
# ACEA's Finland row must be StatFin's month (the acea_split / Greece bands).
ACEA_TOTAL_TOLERANCE = 0.01
ACEA_PLUGIN_TOLERANCE = 0.02
SNAPSHOT_URL = "https://opendata.traficom.fi/Content/Ajoneuvorekisteri.zip"
# A snapshot is published 2-3 weeks after its data date, then quarterly.
# Anything modified more than this after the newest data date already in
# the CSV is a new snapshot worth the 200 MB download.
SNAPSHOT_NEWER_DAYS = 31


def register_note(as_of: str) -> str:
    return f"{REGISTER_NOTE}; snapshot {as_of}"


def split_kind(row: dict) -> str | None:
    """Which counted source put HEV on this row: "register", "acea" or None."""
    notes = row.get("notes") or ""
    if not (row.get("HEV") or "").strip():
        return None
    if notes.startswith(REGISTER_NOTE):
        return "register"
    if notes.startswith(ACEA_NOTE):
        return "acea"
    if notes.startswith(PREVIOUS_PREFIX):
        return "previous"
    if notes.startswith(HISTORY_PREFIX):
        return "history"
    return None


def hev_share(row: dict) -> float | None:
    """HEV / (HEV + pure petrol) of a row that has a split."""
    hev, pet = _f(row, "HEV"), _f(row, "PETROL")
    return hev / (hev + pet) if hev + pet > 0 else None


def split_petrol(petrol: float, share: float) -> tuple[float, float]:
    """StatFin's petrol (full hybrids included) into (HEV, pure petrol)."""
    hev = float(round(petrol * share))
    return hev, petrol - hev


def statfin_petrol(row: dict) -> float:
    """StatFin's own petrol figure, hybrids included, for a row that is
    blank or carries an estimate (an estimate never changes the sum)."""
    if split_kind(row) is not None:
        return _f(row, "HEV") + _f(row, "PETROL")
    return _f(row, "PETROL")


def _f(row: dict, k: str) -> float:
    return float(row.get(k) or 0)


def carry_split(old: dict, new: dict) -> dict:
    """A StatFin restatement of a month that already has the split.

    StatFin rewrites its months with HEV blank and hybrids inside petrol.
    Every split here — the register's counted share, ACEA's share, the
    previous month's or the pre-2025 back-estimate — is a share of
    StatFin's petrol, so it is applied to the restated petrol: HEV + PETROL
    stays StatFin's petrol, OTHERS stays StatFin's own.
    """
    if split_kind(old) is None:
        return new
    share = hev_share(old)
    if share is None:
        return new
    hev, pet = split_petrol(_f(new, "PETROL"), share)
    return {**new, "HEV": hev, "PETROL": pet, "notes": old["notes"]}


def same_month(row: dict, acea: dict) -> bool:
    """ACEA's TOTAL / BEV / PHEV are StatFin's month (Greece's bands)."""
    for k, tol, floor in (("TOTAL", ACEA_TOTAL_TOLERANCE, 0.0),
                          ("BEV", ACEA_PLUGIN_TOLERANCE, 5.0),
                          ("PHEV", ACEA_PLUGIN_TOLERANCE, 5.0)):
        n, a = _f(row, k), float(acea.get(k) or 0)
        if abs(a - n) > max(floor, tol * n):
            return False
    return True


def acea_merge(row: dict, acea: dict) -> dict | None:
    """StatFin's petrol split by ACEA's HEV share for the month, or None.

    Only from HEV_FILL_FROM, never over a register count, and only when
    ACEA's TOTAL / BEV / PHEV are StatFin's month. TOTAL, BEV, PHEV,
    DIESEL and OTHERS stay StatFin's; HEV + PETROL = StatFin's petrol.
    """
    if (row.get("period", "") < HEV_FILL_FROM or split_kind(row) == "register"
            or not same_month(row, acea)):
        return None
    a_hev, a_pet = float(acea.get("HEV") or 0), float(acea.get("PETROL") or 0)
    if a_hev + a_pet <= 0:
        return None
    hev, pet = split_petrol(statfin_petrol(row), a_hev / (a_hev + a_pet))
    return {"HEV": hev, "PETROL": pet, "OTHERS": _f(row, "OTHERS"), "notes": ACEA_NOTE}


def estimate_newest(csv_path: Path = CSV_PATH) -> list[str]:
    """Give every month from HEV_FILL_FROM that has no split yet the
    previous month's HEV share of StatFin's petrol. StatFin is out weeks
    before ACEA and months before the next snapshot; without this the
    newest month would be HEV-blank and the TTM would stop a month early.
    Returns the periods written."""
    rows = whole_rows(csv_path)
    filled: dict[str, dict] = {}
    prev = None
    for period in sorted(rows):
        row = {**rows[period], **filled.get(period, {})}
        if period >= HEV_FILL_FROM and split_kind(row) is None and prev is not None:
            share = hev_share(prev)
            if share is not None:
                hev, pet = split_petrol(statfin_petrol(row), share)
                filled[period] = {"HEV": hev, "PETROL": pet, "OTHERS": _f(row, "OTHERS"),
                                  "notes": PREVIOUS_NOTE.format(prev=prev["period"])}
                row = {**row, **{k: str(v) for k, v in filled[period].items()}}
                print(f"  {period}: HEV {hev:.0f} estimated from {prev['period']}'s share "
                      f"({share:.1%} of petrol)")
        prev = row if split_kind(row) else None
    if filled:
        write_split(csv_path, filled)
    return sorted(filled)


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
        for k in ("HEV", "PETROL", "OTHERS"):
            rec[k] = _fmt(upd[k])
        rec["notes"] = upd["notes"]
        buf = io.StringIO()
        csv.writer(buf, lineterminator="\n").writerow([rec.get(h, "") for h in header])
        out.append(buf.getvalue())
    Path(csv_path).write_text("".join(out), encoding="utf-8")


def whole_rows(csv_path: Path = CSV_PATH) -> dict[str, dict]:
    with open(csv_path, encoding="utf-8", newline="") as f:
        return {r["period"]: r for r in csv.DictReader(f)
                if r["variant"] == "Whole" and r["time_interval"] == "monthly"
                and r.get("TOTAL")}


def apply_acea(period: str, acea: dict, csv_path: Path = CSV_PATH) -> bool:
    """fetch_acea.py's hook: merge one ACEA month. True if the CSV changed."""
    row = whole_rows(csv_path).get(period)
    if row is None:
        print(f"    Finland {period}: no StatFin row yet; ACEA split waits for it")
        return False
    upd = acea_merge(row, acea)
    if upd is None:
        why = ("register counts kept" if split_kind(row) == "register"
               else f"before {HEV_FILL_FROM}" if period < HEV_FILL_FROM
               else "ACEA's TOTAL/BEV/PHEV are not StatFin's month")
        print(f"    Finland {period}: ACEA HEV not merged ({why})")
        return False
    if (split_kind(row) == "acea" and all(abs(_f(row, k) - float(upd[k])) < 0.5
                                          for k in ("HEV", "PETROL", "OTHERS"))):
        return False
    write_split(csv_path, {period: upd})
    print(f"    Finland {period}: HEV {upd['HEV']:.0f} / petrol {upd['PETROL']:.0f} "
          f"(StatFin petrol split by ACEA's HEV share)")
    return True


def latest_registration(rows) -> str | None:
    """Newest first-registration date of a passenger car in the snapshot
    (ISO). The snapshot's data date, as far as the file itself says."""
    best = None
    for row in rows:
        if (row.get("ajoneuvoluokka") or "") not in PASSENGER:
            continue
        v = row.get("ensirekisterointipvm") or ""
        if len(v) == 10 and v[2] == "." and v[5] == ".":
            iso = f"{v[6:10]}-{v[3:5]}-{v[0:2]}"
            if best is None or iso > best:
                best = iso
    return best


def covered_through(as_of: str) -> str:
    """The last month a snapshot holds in full: its own month when the data
    date is in the month's last days, otherwise the month before."""
    y, m, d = int(as_of[:4]), int(as_of[5:7]), int(as_of[8:10])
    if d >= 28:
        return f"{y}-{m:02d}"
    return f"{y - 1}-12" if m == 1 else f"{y}-{m - 1:02d}"


def apply_register(snapshot: Path, csv_path: Path = CSV_PATH) -> list[str]:
    """Split StatFin's petrol by the register's counted HEV share of HEV +
    pure petrol, for every month from HEV_FILL_FROM the snapshot covers in
    full. Replaces an ACEA or previous-month estimate. Returns the periods
    written.

    The share, not the register's absolute count: the snapshot has lost a
    few percent of each month's cars since (exports, scrapping), which
    would land in OTHERS and pull HEV about a point of TOTAL low; the share
    of HEV in what remains matched ACEA's to well within a point in every
    quarter checked. A month the register has already split keeps that
    share: the earliest snapshot is the least thinned (proposal 66 §4 — a
    later snapshot does not silently revise a month).
    """
    rows = list(iter_snapshot(snapshot))
    as_of = latest_registration(rows)
    if as_of is None:
        raise RuntimeError(f"{snapshot}: no passenger-car registration dates")
    through = covered_through(as_of)
    tallied = tally(rows)
    filled = {}
    for period, row in sorted(whole_rows(csv_path).items()):
        if not in_fill_window(period) or period > through or split_kind(row) == "register":
            continue
        whole = tallied.get(period, {}).get("whole", Counter())
        hev_n, pet_n = whole.get("HEV", 0), whole.get("PETROL", 0)
        if hev_n + pet_n <= 0:
            continue
        hev, pet = split_petrol(statfin_petrol(row), hev_n / (hev_n + pet_n))
        filled[period] = {"HEV": hev, "PETROL": pet, "OTHERS": _f(row, "OTHERS"),
                          "notes": register_note(as_of)}
        print(f"{period}  register share {hev_n / (hev_n + pet_n):.3f}: HEV {hev:.0f} "
              f"petrol {pet:.0f} (was {split_kind(row) or 'blank'})")
    if filled:
        write_split(csv_path, filled)
    print(f"snapshot {as_of} (complete through {through}): {len(filled)} month(s) written")
    return sorted(filled)


def newest_snapshot_date(csv_path: Path = CSV_PATH) -> str | None:
    dates = [r["notes"].rsplit("snapshot ", 1)[-1][:10]
             for r in whole_rows(csv_path).values() if split_kind(r) == "register"]
    return max(dates) if dates else None


def snapshot_is_new(last_modified: str | None, csv_path: Path = CSV_PATH,
                    newer_days: int = SNAPSHOT_NEWER_DAYS) -> bool:
    """Is the published snapshot newer than the one already in the CSV?

    `last_modified` is the http Last-Modified header. The CSV records the
    snapshot's data date; a file published more than `newer_days` after
    that date is the next quarter's.
    """
    from datetime import date, timedelta
    from email.utils import parsedate_to_datetime
    have = newest_snapshot_date(csv_path)
    if have is None or not last_modified:
        return True
    published = parsedate_to_datetime(last_modified).date()
    return published > date.fromisoformat(have) + timedelta(days=newer_days)


def fetch_snapshot(dest: Path, url: str = SNAPSHOT_URL, force: bool = False,
                   csv_path: Path = CSV_PATH) -> Path | None:
    """Download the snapshot when it is new (or `force`). None = nothing new."""
    import requests
    import http_retry
    http = http_retry.mount(requests.Session())
    head = http.head(url, timeout=60, allow_redirects=True)
    head.raise_for_status()
    lm = head.headers.get("Last-Modified")
    if not force and not snapshot_is_new(lm, csv_path):
        print(f"Traficom snapshot ({lm}) already applied "
              f"(newest in CSV: {newest_snapshot_date(csv_path)}); skipping")
        return None
    print(f"Downloading Traficom snapshot ({lm}) ...")
    with http.get(url, timeout=600, stream=True) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
    return dest


# The review call in 12-source-finland.md: the register is thinned by
# snapshot drift (about -15% in 2014, -6% to -11% in 2022) and only stays
# inside about -6% from 2025-01. Register HEV on a full StatFin total
# before that understates the hybrid share, so those months use ACEA.
HEV_FILL_FROM = "2025-01"


def in_fill_window(period: str, start: str = HEV_FILL_FROM) -> bool:
    """May the register supply HEV for this month at all?

    Before ``start`` the answer is no: the snapshot has lost too many of
    that month's cars for its HEV count to sit on a full StatFin total.
    """
    return period >= start


def registration_period(value: str) -> str | None:
    """DD.MM.YYYY → YYYY-MM. ISO is refused, not misread."""
    if len(value) != 10 or value[2] != "." or value[5] != ".":
        return None
    year, month = value[6:10], value[3:5]
    if not (year.isdigit() and month.isdigit()):
        return None
    return f"{year}-{month}"


def use_period(value: str) -> str | None:
    """YYYYMMDD → YYYY-MM. A dotted date is refused."""
    if len(value) != 8 or not value.isdigit():
        return None
    return f"{value[:4]}-{value[4:6]}"


def fuel_bucket(kayttovoima: str, hybrid: str, hybrid_class: str) -> str:
    """luokka 01 is plug-in, 02 is the full hybrid 121d has no code for."""
    if hybrid == "true" and hybrid_class == "01":
        return "PHEV"
    if hybrid == "true" and hybrid_class == "02":
        return "HEV"
    if hybrid == "true":
        return "OTHERS"
    if kayttovoima == "04":
        return "BEV"
    if kayttovoima == "01":
        return "PETROL"
    if kayttovoima == "02":
        return "DIESEL"
    return "OTHERS"


def cohort(vehicle_class: str, registered: str | None, used: str | None) -> str | None:
    if vehicle_class not in PASSENGER or not registered or not used:
        return None
    if used == registered:
        return "whole"
    if used < registered:
        return "used"
    return None


def enrich_statfin(statfin: dict | None, register: dict) -> dict | None:
    """Shadow view only (--shadow-*): the register's absolute counts on the
    StatFin row. The write path uses the share instead (apply_register).

    Keep StatFin's total and the columns it already publishes.

    HEV and pure petrol come from the register. The gap lands in OTHERS so
    the row still sums. A negative gap refuses the month — register diesel
    is not copied onto the row to force it. A month StatFin has not
    published yet returns None instead of crashing.
    """
    if not statfin:
        return None
    total = statfin["TOTAL"]
    bev, phev, die = statfin["BEV"], statfin["PHEV"], statfin["DIESEL"]
    hev, petrol = register["HEV"], register["PETROL"]
    others = total - bev - phev - hev - petrol - die
    if others < 0:
        return None
    return {"TOTAL": total, "BEV": bev, "PHEV": phev, "HEV": hev,
            "PETROL": petrol, "DIESEL": die, "OTHERS": others,
            "notes": REGISTER_NOTE}


def classify(row: dict) -> tuple[str, str, str] | None:
    registered = registration_period(row.get("ensirekisterointipvm") or "")
    if not registered:
        return None
    kind = cohort(row.get("ajoneuvoluokka") or "", registered,
                  use_period(row.get("kayttoonottopvm") or ""))
    if not kind:
        return None
    fuel = fuel_bucket(row.get("kayttovoima") or "", row.get("sahkohybridi") or "",
                       row.get("sahkohybridinluokka") or "")
    return registered, kind, fuel


def tally(rows) -> dict[str, dict[str, Counter]]:
    """Every month in one pass. A month with no used cars has no used counter."""
    out: dict[str, dict[str, Counter]] = {}
    for row in rows:
        got = classify(row)
        if not got:
            continue
        period, kind, fuel = got
        out.setdefault(period, {})
        out[period].setdefault(kind, Counter())[fuel] += 1
    return out


def count_rows(rows, period: str) -> dict[str, Counter]:
    counted = {"whole": Counter(), "used": Counter()}
    for row in rows:
        got = classify(row)
        if not got or got[0] != period:
            continue
        counted[got[1]][got[2]] += 1
    return counted


def statfin_months(csv_path: Path = CSV_PATH) -> dict[str, dict]:
    out = {}
    with open(csv_path, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            if (row["variant"] == "Whole" and row["time_interval"] == "monthly"
                    and row.get("TOTAL")):
                out[row["period"]] = {k: float(row[k] or 0)
                                      for k in ("TOTAL", "BEV", "PHEV", "PETROL", "DIESEL", "OTHERS")}
    return out


def shadow_window(snapshot: Path, csv_path: Path = CSV_PATH) -> list[dict]:
    """One pass over the snapshot, every StatFin month. Writes nothing."""
    tallied = tally(iter_snapshot(snapshot))
    published = statfin_months(csv_path)
    lines = []
    for period in sorted(published):
        whole = tallied.get(period, {}).get("whole", Counter())
        used = tallied.get(period, {}).get("used", Counter())
        sf = published[period]
        reg_total = sum(whole.values())
        if not reg_total or not sf["TOTAL"]:
            print(f"{period}  blank")
            lines.append({"period": period, "choice": "blank"})
            continue
        register = {k: whole.get(k, 0) for k in FUELS}
        enriched = enrich_statfin(sf, register)
        delta = reg_total / sf["TOTAL"] - 1
        fillable = enriched is not None and in_fill_window(period)
        verdict = "sums" if fillable else ("before window" if enriched else "refused")
        print(f"{period}  StatFin {sf['TOTAL']:.0f}  register {reg_total} ({delta * 100:+.1f}%)  "
              f"HEV {whole.get('HEV', 0)}  petrol {whole.get('PETROL', 0)}  "
              f"used {sum(used.values())}  {verdict}")
        lines.append({"period": period, "statfin": sf["TOTAL"], "register": reg_total,
                      "delta": delta, "hev": whole.get("HEV", 0),
                      "petrol": whole.get("PETROL", 0), "used": sum(used.values()),
                      "ok": fillable})
    print("wrote nothing")
    return lines


def statfin_month(period: str, csv_path: Path = CSV_PATH) -> dict | None:
    return statfin_months(csv_path).get(period)


def iter_snapshot(path: Path):
    with zipfile.ZipFile(path) as zf:
        name = zf.namelist()[0]
        with zf.open(name) as raw:
            yield from csv.DictReader(io.TextIOWrapper(raw, encoding="iso-8859-1"), delimiter=";")


def shadow_hev(period: str, snapshot: Path, csv_path: Path = CSV_PATH) -> dict | None:
    """Print the register split against the StatFin row. Writes nothing.

    A month StatFin has not published yet is printed and refused, not
    crashed — the snapshot can run ahead of the 121d row.
    """
    counted = count_rows(iter_snapshot(snapshot), period)
    whole, used = counted["whole"], counted["used"]
    statfin = statfin_month(period, csv_path)
    register = {k: whole.get(k, 0) for k in FUELS}
    enriched = enrich_statfin(statfin, register)
    if enriched is not None and not in_fill_window(period):
        print(f"{period}  before {HEV_FILL_FROM}: register HEV not used, ACEA fills this month")
        enriched = None
    print(f"{period}  register whole {sum(whole.values())}  "
          + " ".join(f"{k}={whole.get(k, 0)}" for k in FUELS))
    print(f"{period}  register used  {sum(used.values())}  "
          + " ".join(f"{k}={used.get(k, 0)}" for k in FUELS))
    if statfin:
        print(f"{period}  StatFin total {statfin['TOTAL']:.0f}  "
              f"BEV {statfin['BEV']:.0f}  PHEV {statfin['PHEV']:.0f}  "
              f"petrol {statfin['PETROL']:.0f}")
    if enriched:
        print(f"{period}  enriched  "
              + " ".join(f"{k}={enriched[k]}" for k in ("TOTAL", "BEV", "PHEV", "HEV", "PETROL", "DIESEL", "OTHERS")))
    else:
        print(f"{period}  refused")
    print("  wrote nothing")
    return enriched


def acea_backfill(start: str, end: str, csv_path: Path = CSV_PATH) -> list[str]:
    """Merge ACEA's Finland HEV / petrol month by month from the public
    release PDFs (fetch_acea's URL and parser). Months the register already
    covers are left alone. Returns the periods changed."""
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parent))
    import fetch_acea as fa
    changed = []
    y, m = int(start[:4]), int(start[5:7])
    while f"{y}-{m:02d}" <= end:
        period = f"{y}-{m:02d}"
        url = fa.ACEA_URL_TEMPLATE.format(month_name=fa.ENGLISH_MONTHS[m - 1], year=y)
        try:
            pdf = Path("/tmp/_acea_fi.pdf")
            pdf.write_bytes(fa.load_pdf_bytes(url))
            parsed, label = fa.parse_monthly_table(str(pdf), ["Finland"])
        except Exception as e:      # a missing release (July) or an odd layout
            print(f"{period}: no ACEA table ({type(e).__name__}: {e})")
        else:
            fi = parsed.get("Finland")
            if fi is None:
                print(f"{period}: Finland not in the release")
            else:
                acea = {k: float(v[0]) for k, v in fi.items()}
                if apply_acea(period, acea, csv_path):
                    changed.append(period)
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    print(f"ACEA backfill {start}..{end}: {len(changed)} month(s) changed")
    return changed


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--shadow-hev", metavar="YYYY-MM",
                      help="One month against StatFin. Writes nothing.")
    mode.add_argument("--shadow-window", action="store_true",
                      help="Every StatFin month in one pass. Writes nothing.")
    mode.add_argument("--write-register", action="store_true",
                      help="Apply the snapshot's HEV / pure petrol to data/Finland.csv "
                           "(every month from 2025-01 it covers in full).")
    mode.add_argument("--acea-backfill", metavar="YYYY-MM:YYYY-MM",
                      help="Merge ACEA's monthly HEV / petrol for each month in the "
                           "range from the public release PDFs (HEV share, from 2025-01).")
    parser.add_argument("--snapshot", type=Path,
                        help="Traficom open-data Ajoneuvorekisteri.zip (a local copy).")
    parser.add_argument("--download", action="store_true",
                        help="With --write-register: fetch the snapshot when it is "
                             "newer than the one already applied.")
    parser.add_argument("--force", action="store_true",
                        help="With --download: fetch even if it looks applied.")
    args = parser.parse_args()
    if args.acea_backfill:
        start, end = args.acea_backfill.split(":")
        acea_backfill(start, end)
        return
    if args.write_register and args.download:
        args.snapshot = fetch_snapshot(args.snapshot or Path("/tmp/Ajoneuvorekisteri.zip"),
                                       force=args.force)
        if args.snapshot is None:
            return
    if not args.snapshot:
        parser.error("--snapshot PATH (or --write-register --download) is required")
    if args.write_register:
        apply_register(args.snapshot)
    elif args.shadow_window:
        shadow_window(args.snapshot)
    else:
        shadow_hev(args.shadow_hev, args.snapshot)


if __name__ == "__main__":
    main()
