"""
Counted HEV / PETROL / DIESEL from ACEA on top of a national row whose
TOTAL / BEV / PHEV are exact but whose fuel split is only derived.

Greece (scripts/fetch_greece.py): SEAA publishes TOTAL, BEV and PHEV as counts
but the rest only as one-decimal shares. ACEA's release carries SEAA's counted
split about a week later. Whichever of the two fetchers runs second merges the
row, so the order they publish in does not matter:

  TOTAL, BEV, PHEV    national row (unchanged)
  HEV, PETROL, DIESEL ACEA
  OTHERS              TOTAL − BEV − PHEV − HEV − PETROL − DIESEL

The merge is refused — the national row stays as it is — when ACEA's TOTAL,
BEV or PHEV is not the same month as the national one (more than
TOTAL_TOLERANCE / PLUGIN_TOLERANCE apart: ACEA's wrong 2022-12 and 2023-07
Greek rows) or when the residual OTHERS would be negative.

See docs/architecture/53-source-greece.md §3.
"""
from __future__ import annotations

MERGED_SOURCE = {"Greece": "SEAA / ACEA"}
NATIONAL_SOURCE = {"Greece": "SEAA"}
TOTAL_TOLERANCE = 0.01      # share of the national TOTAL
PLUGIN_TOLERANCE = 0.02     # share of the national BEV / PHEV, at least 5 cars
SPLIT = ("HEV", "PETROL", "DIESEL")
NOTE = ("TOTAL/BEV/PHEV {nat} statistics; HEV/PETROL/DIESEL ACEA (counted); "
        "OTHERS = TOTAL minus the rest")


def _num(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def merge(national: dict, acea: dict) -> tuple[dict, str] | None:
    """`national` and `acea` map BEV/PHEV/HEV/PETROL/DIESEL/TOTAL to numbers
    (or numeric strings). Returns (row, why) with the merged fuel values, or
    None and the reason is printed by the caller via `why_not`."""
    n = {k: _num(national.get(k)) for k in ("TOTAL", "BEV", "PHEV")}
    a = {k: _num(acea.get(k)) for k in ("TOTAL", "BEV", "PHEV") + SPLIT}
    if None in n.values() or None in a.values():
        return None
    if abs(a["TOTAL"] - n["TOTAL"]) > TOTAL_TOLERANCE * n["TOTAL"]:
        return None
    for k in ("BEV", "PHEV"):
        if abs(a[k] - n[k]) > max(5.0, PLUGIN_TOLERANCE * n[k]):
            return None
    others = n["TOTAL"] - n["BEV"] - n["PHEV"] - sum(a[k] for k in SPLIT)
    if others < 0:
        return None
    row = dict(n)
    row.update({k: a[k] for k in SPLIT})
    row["OTHERS"] = others
    return row, (f"ACEA TOTAL {a['TOTAL']:,.0f} vs {n['TOTAL']:,.0f}, "
                 f"BEV {a['BEV']:,.0f} vs {n['BEV']:,.0f}, "
                 f"PHEV {a['PHEV']:,.0f} vs {n['PHEV']:,.0f}")


def why_not(national: dict, acea: dict) -> str:
    return (f"ACEA TOTAL/BEV/PHEV {acea.get('TOTAL')}/{acea.get('BEV')}/"
            f"{acea.get('PHEV')} vs national {national.get('TOTAL')}/"
            f"{national.get('BEV')}/{national.get('PHEV')} — not the same month "
            "or the split does not fit; national row kept")
