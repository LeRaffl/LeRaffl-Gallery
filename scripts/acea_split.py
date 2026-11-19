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

Denmark uses a second mode (`merge(..., country="Denmark")`). statbank BIL53
and ACEA relay the same register but revise it independently, so their
TOTAL/BEV agree to <1% while PHEV (a few hundred cars a month) drifts by
more than the strict 2% plugin gate in many months — the counted Greece
merge would refuse ~13 of 35 backfill months and leave holes. Instead
Denmark keeps ACEA's *counted HEV* (the figure the brief's hybrid row
needs) and splits the national combustion residual (TOTAL − BEV − PHEV −
OTHERS) after HEV into petrol/diesel by ACEA's own petrol:diesel ratio.
TOTAL/BEV/PHEV/OTHERS stay national, HEV is a count, petrol/diesel are a
marked ratio-scale, and the seven columns still sum to TOTAL exactly. The
gate only confirms same-month (TOTAL/BEV within 2%); PHEV is not gated
because the national PHEV is kept, not ACEA's.

See docs/architecture/53-source-greece.md §3 and 11-source-denmark.md.
"""
from __future__ import annotations

MERGED_SOURCE = {
    "Greece": "SEAA / ACEA",
    "Denmark": "api.statbank.dk (BIL53) / ACEA",
    "Finland": "pxdata.stat.fi (StatFin 121d) / ACEA",
}
NATIONAL_SOURCE = {
    "Greece": "SEAA",
    "Denmark": "api.statbank.dk (BIL53)",
    "Finland": "pxdata.stat.fi (StatFin 121d)",
}
TOTAL_TOLERANCE = 0.01      # share of the national TOTAL
PLUGIN_TOLERANCE = 0.02     # share of the national BEV / PHEV, at least 5 cars
SPLIT = ("HEV", "PETROL", "DIESEL")
NOTE = ("TOTAL/BEV/PHEV {nat} statistics; HEV/PETROL/DIESEL ACEA (counted); "
        "OTHERS = TOTAL minus the rest")
# Denmark: same register, independent revisions — a looser same-month gate
# and a counted-HEV / ratio-scaled-petrol-diesel split (see module docstring).
DK_TOTAL_TOLERANCE = 0.02
DK_BEV_TOLERANCE = 0.02
DK_NOTE = ("TOTAL/BEV/PHEV {nat} statistics; HEV ACEA (counted); petrol/diesel "
           "split the national combustion residual after HEV by ACEA's ratio "
           "(statbank and ACEA revise the same register independently)")


def _num(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _merge_denmark(national: dict, acea: dict) -> tuple[dict, str] | None:
    """Counted HEV from ACEA; petrol/diesel ratio-scale the national residual.

    Keeps national TOTAL/BEV/PHEV/OTHERS, takes ACEA's counted HEV, and
    splits (TOTAL − BEV − PHEV − OTHERS − HEV) into petrol/diesel by ACEA's
    petrol:diesel ratio. The seven columns sum to TOTAL exactly. Refused
    when ACEA's TOTAL/BEV are not the same month (>2%), when ACEA's HEV
    exceeds the national combustion residual, or when ACEA reports no
    petrol+diesel to ratio from.
    """
    n = {k: _num(national.get(k)) for k in ("TOTAL", "BEV", "PHEV")}
    n["OTHERS"] = _num(national.get("OTHERS")) or 0.0
    a = {k: _num(acea.get(k)) for k in ("TOTAL", "BEV", "HEV", "PETROL", "DIESEL")}
    if None in n.values() or None in a.values():
        return None
    if abs(a["TOTAL"] - n["TOTAL"]) > DK_TOTAL_TOLERANCE * n["TOTAL"]:
        return None
    if abs(a["BEV"] - n["BEV"]) > max(5.0, DK_BEV_TOLERANCE * n["BEV"]):
        return None
    residual = n["TOTAL"] - n["BEV"] - n["PHEV"] - n["OTHERS"]
    if a["HEV"] > residual:
        return None
    acea_pd = a["PETROL"] + a["DIESEL"]
    if acea_pd <= 0:
        return None
    pd = residual - a["HEV"]
    petrol = round(pd * a["PETROL"] / acea_pd)
    diesel = pd - petrol
    row = dict(n)
    row["HEV"] = a["HEV"]
    row["PETROL"] = float(petrol)
    row["DIESEL"] = float(diesel)
    return row, (f"ACEA TOTAL {a['TOTAL']:,.0f} vs {n['TOTAL']:,.0f}, "
                 f"BEV {a['BEV']:,.0f} vs {n['BEV']:,.0f}; HEV {a['HEV']:,.0f} counted, "
                 f"petrol/diesel ratio-scaled on the national residual")


def merge(national: dict, acea: dict, country: str | None = None) -> tuple[dict, str] | None:
    """`national` and `acea` map BEV/PHEV/HEV/PETROL/DIESEL/TOTAL to numbers
    (or numeric strings). Returns (row, why) with the merged fuel values, or
    None and the reason is printed by the caller via `why_not`.

    `country` selects the mode: Denmark uses the counted-HEV / ratio-scaled
    split (_merge_denmark); every other country (Greece, Finland) uses the
    strict counted split below."""
    if country == "Denmark":
        return _merge_denmark(national, acea)
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
