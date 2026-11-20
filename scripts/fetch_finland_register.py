"""Shadow the Traficom open register against StatFin. Writes nothing.

StatFin 121d stays the published TOTAL / BEV / PHEV / DIESEL. The open
snapshot (Ajoneuvorekisteri.zip) can split the full hybrid that 121d folds
into petrol, and can separate a used import from a new car. Neither number
is written until a shadow window is accepted.

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


def enrich_statfin(statfin: dict, register: dict) -> dict | None:
    """Keep StatFin's total and the columns it already publishes.

    HEV and pure petrol come from the register. The gap lands in OTHERS so
    the row still sums. A negative gap refuses the month — register diesel
    is not copied onto the row to force it.
    """
    total = statfin["TOTAL"]
    bev, phev, die = statfin["BEV"], statfin["PHEV"], statfin["DIESEL"]
    hev, petrol = register["HEV"], register["PETROL"]
    others = total - bev - phev - hev - petrol - die
    if others < 0:
        return None
    return {"TOTAL": total, "BEV": bev, "PHEV": phev, "HEV": hev,
            "PETROL": petrol, "DIESEL": die, "OTHERS": others}


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
        print(f"{period}  StatFin {sf['TOTAL']:.0f}  register {reg_total} ({delta * 100:+.1f}%)  "
              f"HEV {whole.get('HEV', 0)}  petrol {whole.get('PETROL', 0)}  "
              f"used {sum(used.values())}  {'sums' if enriched else 'refused'}")
        lines.append({"period": period, "statfin": sf["TOTAL"], "register": reg_total,
                      "delta": delta, "hev": whole.get("HEV", 0),
                      "petrol": whole.get("PETROL", 0), "used": sum(used.values()),
                      "ok": enriched is not None})
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
    """Print the register split against the StatFin row. Writes nothing."""
    counted = count_rows(iter_snapshot(snapshot), period)
    whole, used = counted["whole"], counted["used"]
    statfin = statfin_month(period, csv_path)
    register = {k: whole.get(k, 0) for k in FUELS}
    enriched = enrich_statfin(statfin, register) if statfin else None
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shadow-hev", metavar="YYYY-MM")
    parser.add_argument("--shadow-window", action="store_true",
                        help="Every StatFin month in one pass. Writes nothing.")
    parser.add_argument("--snapshot", type=Path, required=False)
    args = parser.parse_args()
    if not args.snapshot:
        parser.error("--snapshot PATH is required")
    if args.shadow_window:
        shadow_window(args.snapshot)
        return
    if not args.shadow_hev:
        parser.error("--shadow-hev YYYY-MM or --shadow-window is required")
    shadow_hev(args.shadow_hev, args.snapshot)


if __name__ == "__main__":
    main()
