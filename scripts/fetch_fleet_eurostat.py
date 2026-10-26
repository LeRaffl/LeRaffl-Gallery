#!/usr/bin/env python3
"""
Fetch passenger-car FLEET (stock) by motor energy from Eurostat for the
countries in ``COUNTRIES`` and upsert them into ``fleet/fleet_initial.csv``.

The multi-country sibling of ``scripts/fetch_fleet_germany.py`` (the pattern of
``docs/architecture/37-fleet-data-harmonization.md`` §5 "roll the pattern out"),
the fleet-side analogue of what ``fetch_acea.py`` is for registrations. Annual,
writes the *stock* dataset only, **no render** (the Fleet tab computes in the
browser). Run it by hand or by an agent once a year; Eurostat refreshes the
table in autumn.

Source
------
Eurostat ``road_eqs_carpda`` "Passenger cars by type of motor energy",
JSON-stat 2.0 from the dissemination API (open, no key):
  https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/road_eqs_carpda
Unit NR, legal form TOTAL, stock **at 31 December** of the reference year, which
is the fleet CSV's ``year`` convention (checked: Eurostat DE 2024 BEV 1,651,643
= KBA stock on 1 January 2025).

Hierarchy (checked on SE/CH/AT/DE/FR rows, every level sums exactly)::

    TOTAL = PET + DIE + ALT
    PET   = PET_X_HYB + ELC_PET_HYB + ELC_PET_PI      (same for DIE)
    ALT  >= ELC + HYD_FCELL + REN_OTH + GAS + LPG + OTH

Mapping::

    BEV    = ELC
    PHEV   = ELC_PET_PI + ELC_DIE_PI
    HEV    = the rest of the hybrids: (PET - PET_X_HYB) - ELC_PET_PI, same for DIE
    PETROL = PET_X_HYB        DIESEL = DIE_X_HYB
    CNG    = GAS (natural gas)   LPG = LPG
    OTHERS = HYD_FCELL + REN_OTH + OTH + whatever of ALT has no leaf
    TOTAL  = TOTAL

Countries report unevenly, so the decomposition degrades per row the way the
category contract (doc 37 §2.2) says:

* no plug-in leaf → PHEV empty, HEV holds the combined hybrid bucket (noted);
* no "excluding hybrids" leaf → PETROL/DIESEL = the family total less the
  hybrid leaves that are there; hybrids not split out stay in ICE (noted,
  ``hev_in_ice``);
* no hybrid leaf and nothing to derive one from (PET == PET_X_HYB) → PHEV and
  HEV empty, noted as "no hybrid figure" (empty is not zero);
* no petrol or no diesel figure at all → the row is skipped (an empty ICE would
  make the row's stock vanish in the Fleet tab);
* the populated columns miss TOTAL by more than ``RESIDUAL_LIMIT`` → skipped.

Countries that already have rows from a national source (Austria, Germany,
Denmark, …) are deliberately not in ``COUNTRIES``, and ``upsert`` refuses to
replace any row whose ``source`` is not Eurostat.

Usage
-----
    python scripts/fetch_fleet_eurostat.py [--file PATH] [--dry-run] [--only SE,CH]

``--file`` parses a saved JSON-stat response (offline / testing).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
FLEET_CSV = REPO_ROOT / "fleet" / "fleet_initial.csv"

VARIANT = "Whole"
SOURCE = "Eurostat road_eqs_carpda (31 Dec)"
URL = ("https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/"
       "road_eqs_carpda?format=JSON&lang=EN")

# Harmonized fleet schema (docs/architecture/37). Keep in sync with the CSV
# header, scripts/fetch_fleet_germany.py and index.html:loadFleetObserved.
FLEET_COLUMNS = [
    "country", "variant", "year", "source",
    "BEV", "PHEV", "EREV", "HEV", "MHEV",
    "PETROL", "DIESEL", "GAS", "CNG", "LPG", "FLEXFUEL", "ETHANOL",
    "OTHERS", "TOTAL", "notes",
]
NUMERIC = [c for c in FLEET_COLUMNS[4:-1]]

# A row whose columns miss TOTAL by more than this share is not written.
RESIDUAL_LIMIT = 0.03

# Eurostat geo code -> gallery country name (as in params.csv / SD_COUNTRIES,
# which is what the Fleet tab joins on), first year to write, and caveats
# that the numbers alone cannot show: (from_year, to_year, text).
# Left out on purpose: Greece, Slovakia (no petrol/diesel figure in any
# year), Poland (none in 2015-2023 or 2025, and the register keeps cars that
# no longer drive), Iceland (one usable year). Doc 37 §4c has the reasons.
COUNTRIES: dict[str, dict] = {
    "AL": {"name": "Albania",
           "caveats": [(2014, 2019, "OTHERS likely holds most hybrids (HEV only in 2020)"),
                       (2021, 2025, "OTHERS likely holds most hybrids (HEV only in 2020)")]},
    "BE": {"name": "Belgium"},
    "BG": {"name": "Bulgaria"},
    "CH": {"name": "Switzerland"},
    "CY": {"name": "Cyprus"},
    "CZ": {"name": "Czechia",
           "caveats": [(2018, 2018, "break in LPG/OTHERS (Eurostat flag b)"),
                       (2023, 2023, "break in DIESEL (Eurostat flag b)")]},
    "EE": {"name": "Estonia",
           "caveats": [(2025, 2025, "stock drop most likely from the 2025 car tax")]},
    "ES": {"name": "Spain"},
    "FR": {"name": "France"},
    "HR": {"name": "Croatia"},
    "HU": {"name": "Hungary",
           "caveats": [(2013, 2023, "hybrids counted in OTHERS by the source")]},
    "IE": {"name": "Ireland"},
    "IT": {"name": "Italy"},
    "LT": {"name": "Lithuania", "from": 2014},  # 2013 misses 17 % of TOTAL
    "LU": {"name": "Luxembourg"},
    "LV": {"name": "Latvia"},
    "MT": {"name": "Malta"},
    "PT": {"name": "Portugal"},
    # Before 2018 ELC drops tenfold when the hybrid leaves first appear, so
    # the electric figure held hybrids: start where it is BEV only.
    "RO": {"name": "Romania", "from": 2018},
    "SE": {"name": "Sweden"},
    "SI": {"name": "Slovenia"},
    "TR": {"name": "Türkiye"},
}


# --------------------------------------------------------------------------- #
# JSON-stat parsing
# --------------------------------------------------------------------------- #
def parse_jsonstat(doc: dict) -> tuple[dict, dict]:
    """Return ``(values, flags)`` keyed by ``(geo, year, mot_nrg)``.

    Only unit NR / legal form TOTAL / annual cells are kept.
    """
    ids = doc["id"]
    sizes = doc["size"]
    labels = {}
    for dim in ids:
        index = doc["dimension"][dim]["category"]["index"]
        if isinstance(index, list):
            index = {code: i for i, code in enumerate(index)}
        labels[dim] = {i: code for code, i in index.items()}

    def key_of(flat: int) -> dict:
        pos = {}
        for dim, size in zip(reversed(ids), reversed(sizes)):
            pos[dim] = labels[dim][flat % size]
            flat //= size
        return pos

    def keep(pos: dict) -> bool:
        return (pos.get("unit", "NR") == "NR"
                and pos.get("leg_form", "TOTAL") == "TOTAL"
                and pos.get("freq", "A") == "A")

    values, flags = {}, {}
    for flat, val in doc.get("value", {}).items():
        pos = key_of(int(flat))
        if keep(pos) and val is not None:
            values[(pos["geo"], int(pos["time"]), pos["mot_nrg"])] = int(round(val))
    for flat, flag in doc.get("status", {}).items():
        pos = key_of(int(flat))
        if keep(pos):
            flags[(pos["geo"], int(pos["time"]), pos["mot_nrg"])] = flag
    return values, flags


# --------------------------------------------------------------------------- #
# One country-year -> one harmonized row
# --------------------------------------------------------------------------- #
def decompose(obs: dict) -> tuple[dict, list[str]] | None:
    """Map one country-year's Eurostat cells (``mot_nrg -> int``) to the fleet
    columns. Returns ``(columns, notes)`` or None if the row cannot be split.
    """
    def g(code):
        return obs.get(code)

    total = g("TOTAL")
    if total is None:
        return None

    notes: list[str] = []
    ice: dict[str, int] = {}
    plug_in: list[int] = []        # one entry per family that has a PI leaf
    non_plug: list[int] = []       # hybrids that are known not to be plug-in
    combined: list[int] = []       # hybrids with no plug-in split
    in_ice = False
    no_figure = False              # no hybrid leaf and nothing to derive one from
    for col, fam in (("PETROL", "PET"), ("DIESEL", "DIE")):
        tot, excl = g(fam), g(f"{fam}_X_HYB")
        hyb, pi = g(f"ELC_{fam}_HYB"), g(f"ELC_{fam}_PI")
        if tot is None and excl is None:
            return None            # no petrol (or diesel) figure: unusable
        # `hybrids` = every hybrid of the family, or None when not known.
        if excl is not None:
            ice[col] = excl
            if tot is not None:
                hybrids = tot - excl
            elif hyb is not None:
                hybrids = hyb + (pi or 0)
            else:
                hybrids = None
        else:
            ice[col] = tot - (hyb or 0) - (pi or 0)
            hybrids = hyb + (pi or 0) if hyb is not None else None
            if hyb is None:
                in_ice = True      # the non-plug-in hybrids sit in ICE
        if excl is not None and hyb is None and pi is None and not hybrids:
            # PET == PET_X_HYB with no hybrid leaf (Slovenia until 2021):
            # the hybrids are in some other column, not measured as zero.
            no_figure = True
        if pi is not None:
            plug_in.append(pi)
            if hybrids is not None:
                non_plug.append(hybrids - pi)
        elif hybrids:
            combined.append(hybrids)

    if plug_in and not combined:
        phev = sum(plug_in)
        hev = sum(non_plug) if non_plug else None
    elif plug_in or combined:
        # Plug-ins split in one family only: keep every hybrid as one bucket.
        phev = None
        hev = sum(plug_in) + sum(non_plug) + sum(combined)
        notes.append("HEV = combined PHEV+HEV (source did not split)")
    else:
        phev = None
        hev = None
    if in_ice:
        notes.append("hybrids not split out are in PETROL/DIESEL")
    elif no_figure:
        notes.append("no hybrid figure (hybrids sit in another column)")

    leaves = ["ELC", "HYD_FCELL", "REN_OTH", "GAS", "LPG", "OTH"]
    alt_rest = 0
    if g("ALT") is not None:
        alt_rest = max(g("ALT") - sum(g(c) or 0 for c in leaves), 0)
    other_parts = [g("HYD_FCELL"), g("REN_OTH"), g("OTH")]
    others = sum(v or 0 for v in other_parts) + alt_rest
    if all(v is None for v in other_parts) and not alt_rest:
        others = None

    cols = {
        "BEV": g("ELC"),
        "PHEV": phev,
        "HEV": hev,
        "PETROL": ice["PETROL"],
        "DIESEL": ice["DIESEL"],
        "CNG": g("GAS"),
        "LPG": g("LPG"),
        "OTHERS": others,
        "TOTAL": total,
    }
    return cols, notes


def residual(cols: dict) -> float:
    parts = sum(v or 0 for k, v in cols.items() if k != "TOTAL")
    return (parts - cols["TOTAL"]) / cols["TOTAL"] if cols["TOTAL"] else 0.0


def build_rows(values: dict, flags: dict, countries: dict = COUNTRIES,
               log=print) -> list[dict]:
    """All writable rows for ``countries``, sorted by country then year."""
    rows = []
    years = sorted({y for (_, y, _) in values})
    for geo, spec in sorted(countries.items(), key=lambda kv: kv[1]["name"]):
        for year in years:
            if year < spec.get("from", 0):
                continue
            obs = {m: v for (g_, y, m), v in values.items() if g_ == geo and y == year}
            if not obs:
                continue
            out = decompose(obs)
            if out is None:
                log(f"[skip] {spec['name']} {year}: no petrol/diesel split")
                continue
            cols, notes = out
            r = residual(cols)
            if abs(r) > RESIDUAL_LIMIT:
                log(f"[skip] {spec['name']} {year}: columns miss TOTAL by {r:+.1%}")
                continue
            used = {m for m in obs}
            row_flags = {flags[(geo, year, m)] for m in used if (geo, year, m) in flags}
            if "i" in row_flags:
                notes.append("some cells imputed by Eurostat")
            if "p" in row_flags:
                notes.append("provisional")
            for lo, hi, text in spec.get("caveats", []):
                if lo <= year <= hi:
                    notes.append(text)
            row = {c: None for c in FLEET_COLUMNS}
            row.update(cols)
            row.update(country=spec["name"], variant=VARIANT, year=year,
                       source=SOURCE, notes="; ".join(notes))
            rows.append(row)
    return rows


# --------------------------------------------------------------------------- #
# Line-level upsert into fleet/fleet_initial.csv
# --------------------------------------------------------------------------- #
def _fmt(v) -> str:
    if v is None:
        return ""
    s = str(v)
    # The writer does not quote; a comma would shift every later column.
    if "," in s or "\n" in s:
        raise ValueError(f"unquotable value in fleet row: {s!r}")
    return s


def row_to_line(r: dict) -> str:
    return ",".join(_fmt(r.get(c)) for c in FLEET_COLUMNS)


def upsert(rows: list[dict], csv_path: Path = FLEET_CSV) -> tuple[int, int]:
    """Replace the Whole rows of every country in ``rows``; keep every other
    line byte-for-byte. A country new to the file is appended at the end.
    Refuses to touch a country that has rows from another source.
    """
    lines = csv_path.read_text(encoding="utf-8").splitlines()
    if not lines:
        raise RuntimeError(f"{csv_path} is empty.")
    header = lines[0]
    if [c.strip() for c in header.split(",")] != FLEET_COLUMNS:
        raise RuntimeError("fleet CSV header does not match the harmonized "
                           "schema (docs/architecture/37 §2.1).")

    by_country: dict[str, list[dict]] = {}
    for r in rows:
        by_country.setdefault(r["country"], []).append(r)

    src_idx = FLEET_COLUMNS.index("source")
    for line in lines[1:]:
        cells = [c.strip() for c in line.split(",")]
        if (len(cells) > src_idx and cells[0] in by_country
                and cells[1] in (VARIANT, "")
                and not cells[src_idx].startswith("Eurostat")):
            raise RuntimeError(
                f"{cells[0]} already has fleet rows from another source "
                f"({cells[src_idx] or 'no source'}); not overwriting them.")

    kept: list[str] = []
    slot: dict[str, int] = {}
    for line in lines[1:]:
        if not line.strip():
            continue
        cells = [c.strip() for c in line.split(",")]
        if cells[0] in by_country and (len(cells) < 2 or cells[1] in (VARIANT, "")):
            slot.setdefault(cells[0], len(kept))
            continue
        kept.append(line)

    # Insert from the back so earlier slot indices stay valid.
    out = list(kept)
    placed = sorted(((slot[c], c) for c in by_country if c in slot), reverse=True)
    for idx, country in placed:
        out[idx:idx] = [row_to_line(r) for r in by_country[country]]
    for country in by_country:
        if country not in slot:
            out.extend(row_to_line(r) for r in by_country[country])

    csv_path.write_text("\n".join([header] + out) + "\n", encoding="utf-8")
    return len(rows), len(kept)


# --------------------------------------------------------------------------- #
def fetch() -> dict:
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry

    session = requests.Session()
    session.headers["User-Agent"] = "LeRaffl-Gallery/fleet-eurostat-fetch"
    retry = Retry(total=5, backoff_factor=3,
                  status_forcelist=[429, 500, 502, 503, 504],
                  allowed_methods=["GET"])
    session.mount("https://", HTTPAdapter(max_retries=retry))
    resp = session.get(URL, timeout=120)
    resp.raise_for_status()
    return resp.json()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--file", help="parse a saved JSON-stat response instead of downloading")
    ap.add_argument("--only", help="comma-separated Eurostat geo codes (default: all in COUNTRIES)")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the rows and exit without writing")
    args = ap.parse_args()

    countries = COUNTRIES
    if args.only:
        wanted = [c.strip().upper() for c in args.only.split(",") if c.strip()]
        unknown = [c for c in wanted if c not in COUNTRIES]
        if unknown:
            sys.exit(f"not in COUNTRIES: {', '.join(unknown)}")
        countries = {c: COUNTRIES[c] for c in wanted}

    if args.file:
        print(f"[src] parsing local file {args.file}")
        doc = json.loads(Path(args.file).read_text(encoding="utf-8"))
    else:
        print(f"[src] downloading {URL}")
        doc = fetch()
    updated = doc.get("updated", "?")
    values, flags = parse_jsonstat(doc)
    rows = build_rows(values, flags, countries)
    n_countries = len({r["country"] for r in rows})
    print(f"[parse] Eurostat data updated {updated}: {len(rows)} rows "
          f"for {n_countries} countries")
    if args.dry_run:
        for r in rows:
            print(row_to_line(r))
        return
    n_new, n_kept = upsert(rows)
    print(f"[write] {FLEET_CSV.relative_to(REPO_ROOT)}: {n_new} Eurostat rows, "
          f"{n_kept} other lines preserved")


if __name__ == "__main__":
    main()
