#!/usr/bin/env python3
"""
Fetch Hong Kong registration data from the Transport Department's record-level
"Particulars of first registered vehicles" and upsert data/Hong Kong*.csv
(Whole + Used + Vans).

Source
------
The Transport Department (TD) publishes one CSV per month on the government
open-data portal DATA.GOV.HK — free, no login, no key — with one row per
vehicle first registered in Hong Kong that month:

    https://data.gov.hk/en-data/dataset/hk-td-wcms_11-first-reg-vehicle
    «Particulars of first registered vehicles» (from November 2019)

Resources are discovered through the portal's CKAN `package_show`, never by a
hard-coded URL (the file names follow a pattern, but TD has changed the header
and the resource naming before). Columns (the header has drifted: a " (Note)"
suffix on the status column in some months, "Rated Power (kW)" added later,
a trailing empty column in early files — all normalised in resolve_columns()):

    Vehicle Class · Vehicle Make · Vehicle Model · Fuel Type ·
    Cylinder Capacity Of Engine (c.c.) · [Rated Power (kW)] · Body Type ·
    First Registration Vehicle Status · Permitted Gross Vehicle Weight ·
    Number Of Passenger Seats · Taxable Value (HK$) · Year Of Manufacture

The record files match TD's own aggregate table 4.1(e) of the Monthly Traffic
and Transport Digest exactly, month by month and status by status, for every
month published in both (checked on every run — see Governance).

Record → CSV
------------
"First Registration Vehicle Status" is TD's own classification of the
vehicle's history before it reached Hong Kong (data specification):

  A   never registered outside HK (or registered but not permitted on roads)
  B   never registered outside HK, as declared by the importer
  C1  registered outside HK for fewer than 15 days (documented)
  C2  registered outside HK before import — a used import
  D   imported by the registered owner for own use
  E   assembled in HK with specified additions to an imported chassis
  F   acquired through a HK SAR Government auction

  Whole  data/Hong Kong.csv        Vehicle Class = Private Car ∧ status A/B/C1   (EU M1)
  Used   data/Hong Kong_Used.csv   Vehicle Class = Private Car ∧ status C2       (used imports)
  Vans   data/Hong Kong_Vans.csv   Vehicle Class = LGV ∧ gross weight ≤ 3.5 t
                                   ∧ status A/B/C1/E                            (EU N1)

D (own-use imports, new or used — a dozen a month) and F (auctions) are in no
variant; taxis (their own vehicle class, ~100 a month) are not in Whole —
TD's "private car" is the headline series and the cross-check target.

Fuel → columns
--------------
TD's fuel field follows Cap. 311L (Electric / Petrol / Diesel / LPG /
Hydrogen): it has no hybrid value. Plug-in hybrids register as "Petrol".

  Electric                         → BEV (the register's own value)
  Petrol/Diesel + plug-in rule     → PHEV or EREV (classified from the model
                                     designation — PHEV_RULES below)
  Petrol / Diesel otherwise        → PETROL / DIESEL (full and mild hybrids
                                     included: not identifiable, see doc)
  LPG, Hydrogen, anything else     → OTHERS

Plug-ins are rare in Hong Kong (first-registration tax treats them as petrol
cars): ~0.2–1 % of new private cars. The rules are explicit, ordered, first
match wins, each with its reason — a wrong rule moves a handful of cars.
Petrol/Diesel records of brands that sell mainly NEVs and match no rule are
listed in the run report every month (the net for new plug-in models).

Governance (every real run)
---------------------------
* required columns must resolve; a missing one aborts the run;
* each month's file must parse (> 0.1 % unparsable rows aborts);
* a month below 40 % of the trailing-12 median Whole is treated as a broken
  upload and not written (--force overrides);
* unknown fuel strings above 2 % of the month's Whole abort; unknown vehicle
  classes / statuses are listed in the report;
* cross-check: for every month also in TD table 4.1(e), private-car counts by
  status (A, B, C1, C2) and electric private cars must match the table —
  a mismatch aborts (--force overrides); an unreachable table is a warning;
* fuels must sum to TOTAL for every row written.

Writes are line-level upserts keyed on (period, variant) (invariant 2); a row
whose `source` is not ours is never overwritten without --force.
Also writes market/hong_kong_top.json (top BEV / PHEV brands and models,
trailing 12 months, Whole) via scripts/market_top.py.

Usage
-----
    python scripts/fetch_hong_kong.py                   # newest published month(s)
    python scripts/fetch_hong_kong.py --period 2026-07
    python scripts/fetch_hong_kong.py --backfill        # 2019-11 → now
    python scripts/fetch_hong_kong.py --from-dir DIR [--table41e FILE]   # offline

`--from-dir` reads TD's monthly files (as named on the portal,
particulars_of_first_registered_vehicle_<mon>_<yyyy>_eng.csv) from a local
directory instead of downloading; used by the tests and for offline rebuilds.
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
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import market_top  # noqa: E402

SOURCE = "Transport Department (data.gov.hk)"
PACKAGE_URL = ("https://data.gov.hk/en-data/api/3/action/package_show"
               "?id=hk-td-wcms_11-first-reg-vehicle")
TABLE41E_URL = "https://www.td.gov.hk/datagovhk_tis/mttd-csv/en/table41e_eng.csv"
FIRST_PERIOD = "2019-11"          # first month of the record-level files

VARIANT_CSV = {
    "Whole": "data/Hong Kong.csv",
    "Used":  "data/Hong Kong_Used.csv",
    "Vans":  "data/Hong Kong_Vans.csv",
}
RENDERED_VARIANTS = tuple(VARIANT_CSV)

FUELS = ["BEV", "PHEV", "EREV", "PETROL", "DIESEL", "OTHERS"]
CSV_COLUMNS = (["period", "time_interval", "variant", "source"]
               + FUELS + ["TOTAL", "notes"])

NEW_STATUS = frozenset({"A", "B", "C1"})
USED_STATUS = frozenset({"C2"})
KNOWN_STATUS = NEW_STATUS | USED_STATUS | {"D", "E", "F"}
CLASS_M1 = "PRIVATE CAR"
CLASS_LGV = "LGV"
N1_MAX_TONNES = 3.5
KNOWN_CLASSES = frozenset({
    "PRIVATE CAR", "MOTORCYCLE", "TAXI", "LGV", "MGV", "HGV", "PUBLIC BUS",
    "PRIVATE BUS", "PUBLIC LIGHT BUS", "PRIVATE LIGHT BUS", "SPECIAL PURPOSE VEHICLE",
    "GOVERNMENT VEHICLE", "INVALID CARRIAGE", "TRAILER", "MOTOR TRICYCLE",
})

FUEL_MAP = {
    "ELECTRIC": "BEV",
    "PETROL": "PETROL",
    "DIESEL": "DIESEL",
    "LPG": "OTHERS",
    "HYDROGEN": "OTHERS",
}

# ── plug-in classification ─────────────────────────────────────────────────
# Applied to Petrol/Diesel records only (an "Electric" record is a BEV by the
# register's own value). Ordered, first match wins. (make regex or None,
# model regex, class, min year of manufacture or None, reason).
# `make` is matched against the cleaned make (upper case, single spaces).
PHEV_RULES: list[tuple[str | None, str, str, int | None, str]] = [
    (None, r"\bREEV\b|\bEREV\b|RANGE[- ]?EXTEND", "EREV", None,
     "range extender named in the designation (e.g. FORTHING FRIDAY REEV)"),
    (None, r"\bPHEV\b|\bPHV\b|PLUG-?IN|E:PHEV", "PHEV", None,
     "plug-in named in the designation (GAC E9 PHEV, OUTLANDER PHEV, PRIUS PHV, ALPHARD PLUG-IN)"),
    (None, r"\bU?DM-?[IPO]\b|UDM-?I\b", "PHEV", None,
     "BYD DM-i / DM-p / DM-o plug-in drive (SEAL U DM-I)"),
    (None, r"E-HYBRID", "PHEV", None, "Porsche / VW E-Hybrid plug-ins"),
    (None, r"\bT8\b|RECHARGE", "PHEV", None, "Volvo T8 / Recharge plug-ins"),
    (None, r"\bE PERFORMANCE\b", "PHEV", None, "Mercedes-AMG E Performance plug-ins (C63 S E)"),
    (None, r"\bGTE\b|TFSI ?E\b|\b4XE\b|HYBRID4\b|\d{3}H\+", "PHEV", None,
     "VW GTE, Audi TFSI e, Jeep 4xe, Peugeot Hybrid4, Lexus 450h+"),
    (r"^(LANDROVER|LAND ROVER|JAGUAR|RANGE ROVER)$", r"\bP\d{3}E\b", "PHEV", 2015,
     "JLR PxxxE plug-ins (P300E, P400E, P440E, P550E)"),
    (r"^(B\.M\.W\.|BMW|BMW I)$", r"(?<!\d)\d{3}L?E\b|XDRIVE\d{2}E\b|(?<!\d)\d{3}XE\b|\bI8\b|^XM\b", "PHEV", 2014,
     "BMW xxxe / xDriveNNe / i8 / XM plug-ins"),
    (r"^(MERCEDES BENZ|MERCEDES-BENZ|MAYBACH)$", r"(?<!\d)\d{3} ?D?E\b|\b53 HYBRID\b", "PHEV", 2015,
     "Mercedes xxx e / xxx de and AMG 53 Hybrid plug-ins (older 190E/300E are pre-2015)"),
    (r"^MINI$", r"COOPER S E COUNTRYMAN|\bSE ALL4\b", "PHEV", None,
     "MINI Countryman Cooper S E ALL4 plug-in"),
    (r"^BENTLEY$", r"\bHYBRID\b", "PHEV", None, "Bentley Hybrid models are plug-ins"),
    (r"^FERRARI$", r"\bSF90\b|\b296\s?(GT[BS]|SPECIALE)", "PHEV", None, "Ferrari SF90 / 296 plug-ins"),
    (r"^LAMBORGHINI$", r"REVUELTO|URUS SE\b|TEMERARIO", "PHEV", None,
     "Lamborghini Revuelto / Urus SE / Temerario plug-ins"),
    (r"^MCLAREN$", r"ARTURA", "PHEV", None, "McLaren Artura plug-in"),
    (r"^GAC$", r"\bE9\b", "PHEV", None, "GAC (Trumpchi) E9 is sold only as a plug-in"),
    (r"^(BYD|DENZA)$", r".", "PHEV", None,
     "BYD and Denza sell no pure-combustion car in HK: a Petrol record is a DM-i / DM-o plug-in"),
]
_RULES = [(re.compile(mk) if mk else None, re.compile(mo), cls, yom, why)
          for mk, mo, cls, yom, why in PHEV_RULES]

# Brands whose HK line-up is (mostly) electric: a Petrol/Diesel record of one
# of these that matches no rule is listed in the report (possible new plug-in).
NEV_BRANDS = frozenset({
    "AION", "GAC AION", "AITO", "AVATR", "DEEPAL", "FIREFLY", "FORTHING", "HYPTEC",
    "ICAUR", "IM", "JAECOO", "LEAPMOTOR", "LI AUTO", "LYNK & CO", "NETA", "NIO",
    "OMODA", "POLESTAR", "VOYAH", "XIAOMI", "XPENG", "ZEEKR", "CHANGAN",
    "GEELY", "WULING", "DONGFENG", "SKYWORTH", "JMEV", "KAIYI",
})

HTTP_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (compatible; LeRaffl-Gallery/1.0; "
                   "+https://leraffl.github.io/LeRaffl-Gallery/)"),
}
MIN_MONTH_FRACTION = 0.4
MAX_UNKNOWN_FUEL_SHARE = 0.02
MAX_BAD_ROW_SHARE = 0.001
# Record files vs TD table 4.1(e): the two are cut from the register at
# different times, so a late correction can leave them a unit apart (2020-06
# used imports: 777 records vs 778 in the table). Up to this much is reported;
# more aborts the run.
XCHECK_ABS_TOL = 2
XCHECK_REL_TOL = 0.005
NORMAL_WINDOW = 12                # months re-read on a normal run (top list)

REPO = Path(__file__).resolve().parent.parent
TOP_PATH = market_top.MARKET_DIR / "hong_kong_top.json"
TOP_UNIT = ("first registrations (brand = TD 'Vehicle Make', aliases merged; "
            "model = TD 'Vehicle Model' with the brand prefix, chassis codes and "
            "trim words removed — see MODEL_TRIM in scripts/fetch_hong_kong.py)")

MONTHS = {m: i for i, m in enumerate(
    ("jan feb mar apr may jun jul aug sep oct nov dec").split(), start=1)}


# ── scope ──────────────────────────────────────────────────────────────────

def norm(s) -> str:
    return " ".join(str(s or "").replace(" ", " ").split()).upper()


def parse_tonnes(s: str) -> float | None:
    try:
        return float(str(s).replace(",", "").strip())
    except ValueError:
        return None


def parse_year(s: str) -> int | None:
    m = re.match(r"\s*(\d{4})", str(s or ""))
    return int(m.group(1)) if m else None


def variant_for(vclass: str, status: str, gvw_tonnes: float | None) -> str | None:
    vclass, status = norm(vclass), norm(status)
    if vclass == CLASS_M1:
        if status in NEW_STATUS:
            return "Whole"
        if status in USED_STATUS:
            return "Used"
        return None
    if (vclass == CLASS_LGV and status in NEW_STATUS | {"E"}
            and gvw_tonnes is not None and gvw_tonnes <= N1_MAX_TONNES):
        return "Vans"
    return None


def plugin_class(make: str, model: str, yom: int | None) -> tuple[str, str] | None:
    """(class, reason) if a plug-in rule matches, else None."""
    make, model = norm(make), norm(model)
    for mk, mo, cls, min_yom, why in _RULES:
        if mk is not None and not mk.search(make):
            continue
        if min_yom is not None and (yom is None or yom < min_yom):
            continue
        if mo.search(model):
            return cls, why
    return None


def fuel_class(fuel: str, make: str, model: str, yom: int | None) -> str | None:
    """Gallery column for a record; None if the fuel string is unknown."""
    base = FUEL_MAP.get(norm(fuel))
    if base in ("PETROL", "DIESEL"):
        hit = plugin_class(make, model, yom)
        if hit:
            return hit[0]
    return base


# ── display names for the top-brands/models table (not used for the data) ──

BRAND_ALIASES = {
    "B.M.W.": "BMW", "BMW I": "BMW", "M.G.": "MG", "MERCEDES BENZ": "MERCEDES-BENZ",
    "LANDROVER": "LAND ROVER", "ROLLS ROYCE": "ROLLS-ROYCE", "IM": "IM MOTORS",
}
# Trim / equipment words TD appends to the commercial name. Removed from the
# model string for the top-models table only, so "MODEL Y RWD" and "MODEL Y
# LONG RANGE DUAL MOTOR ALL WHEEL DRIVE" rank as one model.
MODEL_TRIM = re.compile(
    r"\b(RWD|AWD|FWD|4WD|2WD|4MATIC|4M|XDRIVE|SDRIVE|LONG RANGE|STANDARD RANGE|"
    r"STANDARD|PERFORMANCE|DUAL MOTOR|ALL WHEEL DRIVE|PLATINUM|PLUS|PREMIUM|LUXURY|"
    r"ELITE|DELUXE|ULTRA|SPORT|PRO|MAX|LIMITED|EDITION|FIRST|FACELIFT|FL|M SPORT|"
    r"AMG LINE|XLINE|X LINE|R-DESIGN|INSCRIPTION|MOMENTUM|HIGHLINE|HL|EXCLUSIVE|"
    r"AVANTGARDE|S LINE|GT-LINE|BLACK|BASIC|HOME|LUXE|FLAGSHIP|ADVANCED|EXECUTIVE|"
    r"LOUNGE|SIGNATURE|LAUNCH|STD|LR|SR|AUTO|A/T|CVT|DCT|GL|GX|GS|SE|HSE|DYN|DYNAMIC|"
    r"PHEV|DM-I|REEV|EREV|EV|ELECTRIC)\b")


def display_brand(make: str) -> str:
    b = market_top.clean(make)
    return BRAND_ALIASES.get(b, b)


def display_model(make: str, model: str) -> str:
    raw_make = market_top.clean(make)
    m = market_top.clean(model)
    for prefix in {raw_make, display_brand(make)}:
        m = market_top.strip_brand(prefix, m)
    m = re.sub(r"^MERCEDES-(AMG|MAYBACH) ", r"\1 ", m)  # MERCEDES-AMG E 53 → AMG E 53
    m = re.sub(r"\([^)]*\)", " ", m)                   # chassis codes (G20), (F30BR)
    first, _, rest = m.partition(" ")
    rest = MODEL_TRIM.sub(" ", rest)
    rest = re.sub(r"(?<![\w+])\d{3,}(?![\w+])", " ", rest)   # range figures: G6 580 → G6
    rest = re.sub(r"(?<!\S)\+(?!\S)", " ", rest)          # "4MATIC+" leaves a lone "+"
    out = " ".join((first + " " + rest).split())
    return out or market_top.clean(model)


# ── aggregation ────────────────────────────────────────────────────────────

def empty_counts() -> dict[str, int]:
    return {k: 0 for k in FUELS + ["TOTAL"]}


class Aggregator:
    def __init__(self) -> None:
        self.counts: dict[str, dict[str, dict[str, int]]] = \
            collections.defaultdict(lambda: collections.defaultdict(empty_counts))
        # (period, class, brand, model) -> units, Whole only (market top)
        self.units: collections.Counter = collections.Counter()
        self.unknown_fuel: collections.Counter = collections.Counter()    # (period, fuel)
        self.unknown_class: collections.Counter = collections.Counter()   # (period, class)
        self.unknown_status: collections.Counter = collections.Counter()  # (period, class, status)
        self.excluded: collections.Counter = collections.Counter()        # (period, class, status)
        self.plugins: collections.Counter = collections.Counter()         # (period, variant, cls, make, model)
        self.nev_watch: collections.Counter = collections.Counter()       # (period, variant, make, model, fuel)
        # cross-check against table 4.1(e): (period, status) -> private cars;
        # (period, status, 'ELECTRIC') -> electric private cars
        self.pc_status: collections.Counter = collections.Counter()
        self.pc_status_el: collections.Counter = collections.Counter()
        self.rows: collections.Counter = collections.Counter()            # period -> records
        self.bad: collections.Counter = collections.Counter()             # period -> unparsable

    def add(self, period: str, vclass: str, make: str, model: str, fuel: str,
            status: str, gvw: str, yom: str, n: int = 1) -> None:
        vc, st = norm(vclass), norm(status)
        self.rows[period] += n
        if vc not in KNOWN_CLASSES:
            self.unknown_class[(period, vc)] += n
        if st not in KNOWN_STATUS:
            self.unknown_status[(period, vc, st)] += n
        if vc == CLASS_M1:
            self.pc_status[(period, st)] += n
            if norm(fuel) == "ELECTRIC":
                self.pc_status_el[(period, st)] += n
        v = variant_for(vc, st, parse_tonnes(gvw))
        if v is None:
            if vc in (CLASS_M1, CLASS_LGV):
                self.excluded[(period, vc, st)] += n
            return
        y = parse_year(yom)
        cls = fuel_class(fuel, make, model, y)
        if cls is None:
            self.unknown_fuel[(period, norm(fuel))] += n
            cls = "OTHERS"
        c = self.counts[period][v]
        c[cls] += n
        c["TOTAL"] += n
        if cls in ("PHEV", "EREV"):
            self.plugins[(period, v, cls, norm(make), norm(model))] += n
        elif cls in ("PETROL", "DIESEL") and norm(make) in NEV_BRANDS:
            self.nev_watch[(period, v, norm(make), norm(model), cls)] += n
        if v == "Whole":
            self.units[(period, cls, display_brand(make), display_model(make, model))] += n


# ── download / parse ───────────────────────────────────────────────────────

FIELDS = {   # logical name -> normalised header
    "class": "VEHICLE CLASS",
    "make": "VEHICLE MAKE",
    "model": "VEHICLE MODEL",
    "fuel": "FUEL TYPE",
    "status": "FIRST REGISTRATION VEHICLE STATUS",
    "gvw": "PERMITTED GROSS VEHICLE WEIGHT",
    "yom": "YEAR OF MANUFACTURE",
}


def norm_header(h: str) -> str:
    h = norm(h.strip().strip('"').lstrip("﻿"))
    return re.sub(r"\s*\(NOTE\)$", "", h)


def resolve_columns(header: list[str]) -> dict[str, int]:
    hdr = [norm_header(h) for h in header]
    ix = {h: i for i, h in enumerate(hdr)}
    missing = [f for f, h in FIELDS.items() if h not in ix]
    if missing:
        raise SystemExit(f"schema drift: columns {[FIELDS[m] for m in missing]} "
                         f"not in header {hdr}")
    return {f: ix[h] for f, h in FIELDS.items()}


def add_text(period: str, text: str, agg: Aggregator) -> int:
    """Feed one month's CSV text (header first) into the aggregator.
    Returns the number of records."""
    rows = csv.reader(io.StringIO(text.lstrip("﻿")))
    col = resolve_columns(next(rows))
    need = max(col.values())
    n = 0
    for row in rows:
        if not any(c.strip() for c in row):
            continue
        n += 1
        if len(row) <= need or not row[col["class"]].strip():
            agg.bad[period] += 1
            continue
        g = lambda k: row[col[k]]
        agg.add(period, g("class"), g("make"), g("model"), g("fuel"), g("status"),
                g("gvw"), g("yom"))
    if n and agg.bad[period] / n > MAX_BAD_ROW_SHARE:
        raise SystemExit(f"{period}: {agg.bad[period]:,} of {n:,} rows are short or "
                         "have no vehicle class — schema drift, not writing.")
    return n


def decode(raw: bytes) -> str:
    for enc in ("utf-8-sig", "cp950", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    raise SystemExit("undecodable file")


def period_of(text: str) -> str | None:
    """'…_jul_2026_eng.csv' or '… - July 2026' → '2026-07'."""
    m = re.search(r"_([a-z]{3})[a-z]*_(20\d\d)_eng\.csv", text, re.I)
    if m and m.group(1).lower() in MONTHS:
        return f"{m.group(2)}-{MONTHS[m.group(1).lower()]:02d}"
    m = re.search(r"\b([A-Za-z]{3})[a-z]*\.?\s+(20\d\d)\b", text)
    if m and m.group(1).lower() in MONTHS:
        return f"{m.group(2)}-{MONTHS[m.group(1).lower()]:02d}"
    return None


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HTTP_HEADERS)
    return s


def list_month_urls(session: requests.Session) -> dict[str, str]:
    """period -> URL of the English CSV, from the portal's package_show."""
    r = session.get(PACKAGE_URL, timeout=120)
    r.raise_for_status()
    best: dict[str, tuple[str, str]] = {}
    for res in r.json()["result"]["resources"]:
        if (res.get("format") or "").upper() != "CSV":
            continue
        if (res.get("inLanguage") or "en") != "en":
            continue
        url = res.get("url") or ""
        p = period_of(url) or period_of(res.get("name") or "")
        if not p:
            continue
        stamp = res.get("metadata_modified") or res.get("created") or ""
        if p not in best or stamp > best[p][0]:
            best[p] = (stamp, url)
    return {p: u for p, (_, u) in best.items()}


def list_dir_files(d: Path) -> dict[str, Path]:
    out = {}
    for f in sorted(d.glob("particulars_of_first_registered_vehicle_*_eng.csv")):
        p = period_of(f.name)
        if p:
            out[p] = f
    return out


# ── cross-check against TD table 4.1(e) ────────────────────────────────────

def parse_table41e(text: str) -> tuple[dict, dict]:
    """(period, status) -> private cars; (period, status) -> electric ones.
    Status is FIRST_REG_STATUS_REV (A/B/C1/C2/Others, 2019 →)."""
    tot, el = collections.Counter(), collections.Counter()
    for r in csv.DictReader(io.StringIO(text.lstrip("﻿"))):
        st = (r.get("FIRST_REG_STATUS_REV") or "").strip()
        ym = (r.get("YR_MTH") or "").strip()
        if not st or len(ym) != 6:
            continue
        p = f"{ym[:4]}-{ym[4:]}"
        n = int(float(r.get("FIRST_REG") or 0))
        tot[(p, st)] += n
        if (r.get("FUEL_TYPE_CODE") or "").strip().upper() == "ELECTRIC":
            el[(p, st)] += n
    return tot, el


def within_tolerance(a: int, b: int) -> bool:
    return abs(a - b) <= max(XCHECK_ABS_TOL, XCHECK_REL_TOL * max(a, b))


def cross_check(agg: Aggregator, periods: list[str],
                text: str) -> tuple[list[str], list[str], list[str]]:
    """Returns (compared periods, small differences, mismatches). A small
    difference (within tolerance) is reported, a mismatch aborts the run."""
    tot, el = parse_table41e(text)
    have = {p for p, _ in tot}
    compared, small, problems = [], [], []
    for p in periods:
        if p not in have:
            continue
        compared.append(p)
        for st in ("A", "B", "C1", "C2"):
            for what, t, r in (("private cars", tot[(p, st)], agg.pc_status[(p, st)]),
                               ("electric private cars", el[(p, st)],
                                agg.pc_status_el[(p, st)])):
                if t == r:
                    continue
                msg = f"{p} {what} status {st}: records {r:,} vs table {t:,}"
                (small if within_tolerance(r, t) else problems).append(msg)
    return compared, small, problems


# ── CSV line-level upsert (invariant 2) ────────────────────────────────────

def fmt(v: int) -> str:
    return f"{float(v):.1f}"


def render_line(period: str, variant: str, counts: dict[str, int],
                notes: str = "") -> str:
    buf = io.StringIO()
    csv.writer(buf, lineterminator="").writerow(
        [period, "monthly", variant, SOURCE]
        + [fmt(counts[k]) for k in FUELS + ["TOTAL"]] + [notes])
    return buf.getvalue()


def read_csv_lines(path: Path) -> tuple[str, list[str]]:
    if not path.exists():
        return ",".join(CSV_COLUMNS), []
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines:
        return ",".join(CSV_COLUMNS), []
    return lines[0], lines[1:]


def line_key(line: str) -> tuple[str, str]:
    f = next(csv.reader([line]))
    return f[0], f[2]


def line_source(line: str) -> str:
    return next(csv.reader([line]))[3]


def upsert_lines(path: Path, updates: dict[tuple[str, str], str],
                 force: bool) -> dict[str, int]:
    """Replace/insert only the given (period, variant) lines; every other
    line is written back byte-for-byte. Keeps rows sorted by period."""
    header, lines = read_csv_lines(path)
    if header.split(",") != CSV_COLUMNS:
        sys.exit(f"{path}: unexpected header {header!r}")
    stats = {"added": 0, "updated": 0, "unchanged": 0, "skipped": 0}
    index = {line_key(l): i for i, l in enumerate(lines)}
    for key, new in sorted(updates.items()):
        if key in index:
            old = lines[index[key]]
            if old == new:
                stats["unchanged"] += 1
            elif line_source(old) != SOURCE and not force:
                stats["skipped"] += 1
            else:
                lines[index[key]] = new
                stats["updated"] += 1
        else:
            lines.append(new)
            stats["added"] += 1
    if stats["added"]:
        lines.sort(key=line_key)
    if stats["added"] or stats["updated"]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join([header] + lines) + "\n", encoding="utf-8")
    return stats


def existing_periods(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    with open(path, newline="", encoding="utf-8") as f:
        return {r["period"]: r for r in csv.DictReader(f)}


# ── checks & report ────────────────────────────────────────────────────────

def looks_incomplete(period: str, total: int, have: dict[str, dict]) -> bool:
    prior = sorted(p for p in have if p < period)[-12:]
    if len(prior) < 6:
        return False
    vals = sorted(float(have[p]["TOTAL"]) for p in prior)
    median = vals[len(vals) // 2]
    return total < MIN_MONTH_FRACTION * median


def check_sums(agg: Aggregator, periods: list[str]) -> list[str]:
    problems = []
    for p in periods:
        for v, c in agg.counts[p].items():
            if sum(c[k] for k in FUELS) != c["TOTAL"]:
                problems.append(f"{p} {v}: fuels do not sum to TOTAL")
    return problems


def build_top(agg: Aggregator, target: str) -> dict:
    window = set(market_top.month_window(target))
    units = collections.Counter()
    for (p, cls, b, m), n in agg.units.items():
        if p in window:
            units[(cls, b, m)] += n
    total = sum(agg.counts[p]["Whole"]["TOTAL"] for p in window if p in agg.counts)
    return market_top.build_top("Hong Kong", SOURCE, target, units, total, TOP_UNIT)


def report(agg: Aggregator, target: str, periods: list[str], xcheck: str) -> str:
    t = agg.counts[target]
    out = [f"## Hong Kong (TD first registrations, data.gov.hk) — {target}\n",
           "| variant | BEV | PHEV | EREV | PETROL | DIESEL | OTHERS | TOTAL | BEV share |",
           "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for v in VARIANT_CSV:
        c = t[v]
        tot = c["TOTAL"] or 1
        out.append(f"| {v} | " + " | ".join(f"{c[k]:,}" for k in FUELS)
                   + f" | {c['TOTAL']:,} | {c['BEV'] / tot:.2%} |")
    out.append(f"\nMonths processed: {periods[0]} → {periods[-1]} ({len(periods)})")
    out.append(f"\n### Cross-check against TD table 4.1(e)\n\n{xcheck}")
    brands = collections.Counter()
    for (p, cls, b, m), n in agg.units.items():
        if p == target:
            brands[b] += n
    out.append("\n### Top 10 brands, new private cars\n")
    out.append(", ".join(f"{b} {n:,}" for b, n in brands.most_common(10)) or "—")
    pl = collections.Counter()
    for (p, v, cls, mk, mo), n in agg.plugins.items():
        if p == target:
            pl[(v, cls, mk, mo)] += n
    out.append("\n### Records classified as plug-in this month (PHEV_RULES — review)\n")
    out.append("\n".join(f"- {v} {cls}: {mk} `{mo}` × {n}" for (v, cls, mk, mo), n
                         in sorted(pl.items(), key=lambda kv: -kv[1])) or "None.")
    nw = collections.Counter()
    for (p, v, mk, mo, cls), n in agg.nev_watch.items():
        if p == target:
            nw[(v, mk, mo, cls)] += n
    out.append("\n### Petrol/Diesel records of NEV brands matching no plug-in rule (review!)\n")
    out.append("\n".join(f"- {v}: {mk} `{mo}` ({cls}) × {n}" for (v, mk, mo, cls), n
                         in sorted(nw.items(), key=lambda kv: -kv[1])) or "None.")
    unk = {k: n for k, n in agg.unknown_fuel.items() if k[0] == target}
    out.append("\n### Unknown fuel strings this month (counted as OTHERS)\n")
    out.append("\n".join(f"- `{f or '(blank)'}`: {n:,}" for (_, f), n in unk.items()) or "None.")
    us = {k: n for k, n in agg.unknown_status.items() if k[0] == target}
    uc = {k: n for k, n in agg.unknown_class.items() if k[0] == target}
    out.append("\n### Unknown vehicle classes / statuses this month (review!)\n")
    out.append("\n".join([f"- class `{c}`: {n:,}" for (_, c), n in uc.items()]
                         + [f"- `{c}` status `{s or '(blank)'}`: {n:,}"
                            for (_, c, s), n in us.items()]) or "None.")
    ex = {k: n for k, n in agg.excluded.items() if k[0] == target}
    out.append("\n### Private cars / LGVs in no variant (D own-use imports, F auctions, "
               "LGV > 3.5 t, used LGVs)\n")
    out.append(", ".join(f"{c} {s}: {n:,}" for (_, c, s), n in sorted(ex.items())) or "None.")
    return "\n".join(out) + "\n"


# ── main ───────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--variant", default="all",
                    help=f"all | {' | '.join(VARIANT_CSV)} (default: all)")
    ap.add_argument("--period", default="",
                    help="Target month YYYY-MM (default: newest month on the portal).")
    ap.add_argument("--backfill", action="store_true",
                    help=f"Re-derive every month from {FIRST_PERIOD}. Implied when a "
                         "CSV does not exist yet.")
    ap.add_argument("--force", action="store_true",
                    help="Ignore the self-throttle, the completeness and cross-check "
                         "guards, and foreign source strings.")
    ap.add_argument("--from-dir", default="",
                    help="Offline: read TD's monthly CSVs from this directory.")
    ap.add_argument("--table41e", default="",
                    help="Offline: TD table 4.1(e) CSV for the cross-check.")
    ap.add_argument("--github-output", default=os.environ.get("GITHUB_OUTPUT"))
    ap.add_argument("--step-summary", default=os.environ.get("GITHUB_STEP_SUMMARY"))
    args = ap.parse_args()

    variants = list(VARIANT_CSV) if args.variant == "all" else [args.variant]
    for v in variants:
        if v not in VARIANT_CSV:
            sys.exit(f"Unknown variant {v!r}. Valid: {list(VARIANT_CSV)} or all.")
    paths = {v: REPO / VARIANT_CSV[v] for v in variants}
    have = {v: existing_periods(paths[v]) for v in variants}
    backfill = args.backfill or any(not paths[v].exists() for v in variants)

    session = None
    if args.from_dir:
        files = list_dir_files(Path(args.from_dir))
        load = lambda p: decode(files[p].read_bytes())
        where = {p: str(f) for p, f in files.items()}
    else:
        session = make_session()
        files = list_month_urls(session)

        def load(p):
            r = session.get(files[p], timeout=300)
            r.raise_for_status()
            return decode(r.content)
        where = dict(files)
    if not files:
        sys.exit("No monthly files found — portal layout changed? Not writing.")
    published = sorted(p for p in files if p >= FIRST_PERIOD)
    print(f"Monthly files published: {published[0]} → {published[-1]} ({len(published)})")
    gaps = [p for p in market_top.month_window(published[-1], len(published))
            if p not in files]
    if gaps:
        print(f"::warning::months missing on the portal: {gaps}")

    target = args.period or published[-1]
    if target not in files:
        print(f"{target} is not published on the portal yet (newest: {published[-1]}) "
              "— will retry on the next scheduled run.")
        return emit(args, set())

    if not backfill and not args.force and all(
            have[v].get(target, {}).get("source") == SOURCE for v in variants):
        print(f"{target} already fetched from {SOURCE} for {variants}; nothing to do.")
        return emit(args, set())

    if backfill:
        todo = [p for p in published if p <= target]
    else:
        todo = [p for p in market_top.month_window(target, NORMAL_WINDOW) if p in files]

    agg = Aggregator()
    for p in todo:
        n = add_text(p, load(p), agg)
        if n == 0:
            sys.exit(f"{p}: file has no records — broken upload, not writing.")
        print(f"  {p}: {n:,} records ({where[p].rsplit('/', 1)[-1]})")

    periods = sorted(p for p in agg.counts if p <= target)

    unk = sum(n for (p, _), n in agg.unknown_fuel.items() if p == target)
    whole_total = agg.counts[target]["Whole"]["TOTAL"]
    if whole_total and unk / whole_total > MAX_UNKNOWN_FUEL_SHARE:
        sys.exit(f"{target}: {unk:,} records with unknown fuel strings "
                 f"({unk / whole_total:.1%} of Whole) — schema drift, not writing. "
                 f"Strings: {sorted({f for (p, f) in agg.unknown_fuel if p == target})}")

    problems = check_sums(agg, periods)
    if problems:
        sys.exit("Consistency check failed:\n  " + "\n  ".join(problems[:20]))

    # Cross-check against TD's own aggregate table.
    xtext = None
    try:
        if args.table41e:
            xtext = Path(args.table41e).read_text(encoding="utf-8-sig")
        elif session is not None:
            r = session.get(TABLE41E_URL, timeout=120)
            r.raise_for_status()
            xtext = decode(r.content)
    except Exception as e:  # noqa: BLE001 — the table is a check, not the data
        print(f"::warning title=TD table 4.1(e) unavailable::{type(e).__name__}: {e}")
    if xtext:
        compared, small, mism = cross_check(agg, periods, xtext)
        if mism and not args.force:
            sys.exit("Cross-check against TD table 4.1(e) failed — the record files "
                     "and TD's published aggregate disagree; not writing "
                     "(--force overrides):\n  " + "\n  ".join(mism[:30]))
        xcheck = (f"{len(compared)} month(s) compared "
                  f"({compared[0] if compared else '—'} → {compared[-1] if compared else '—'}), "
                  "private cars by status A/B/C1/C2 and electric: "
                  + ("exact match." if not (small or mism) else "")
                  + (f" {len(small)} difference(s) within tolerance: " + "; ".join(small[:10])
                     if small else "")
                  + (f" {len(mism)} MISMATCHES (forced): " + "; ".join(mism[:10])
                     if mism else ""))
        if not compared:
            xcheck += " The table does not cover these months yet (it lags the record files)."
    else:
        xcheck = "Table not available this run — not compared."
    print("Cross-check: " + xcheck)

    if (not backfill and not args.force and "Whole" in variants
            and looks_incomplete(target, whole_total, have["Whole"])):
        print(f"{target}: Whole TOTAL {whole_total:,} is below "
              f"{MIN_MONTH_FRACTION:.0%} of the trailing median — looks like a broken "
              "upload; not writing. Re-run with --force if genuine.")
        return emit(args, set())

    changed: set[str] = set()
    for v in variants:
        updates = {(p, v): render_line(p, v, agg.counts[p][v])
                   for p in periods if agg.counts[p][v]["TOTAL"] > 0}
        stats = upsert_lines(paths[v], updates, args.force)
        print(f"{VARIANT_CSV[v]}: {stats}")
        if stats["added"] or stats["updated"]:
            changed.add(v)

    def refresh_top() -> None:
        top = build_top(agg, target)
        print(f"{TOP_PATH.relative_to(REPO)}: "
              f"{'updated' if market_top.write_top(top, TOP_PATH) else 'unchanged'}")
    if "Whole" in variants:
        market_top.guarded(refresh_top)

    rep = report(agg, target, periods, xcheck)
    print("\n" + rep)
    if args.step_summary:
        with open(args.step_summary, "a", encoding="utf-8") as fh:
            fh.write(rep)
    return emit(args, changed)


def render_list(changed: set[str]) -> list[str]:
    return sorted(v for v in changed if v in RENDERED_VARIANTS)


def emit(args, changed: set[str]) -> int:
    if args.github_output:
        with open(args.github_output, "a", encoding="utf-8") as f:
            f.write(f"changed={'true' if changed else 'false'}\n")
            f.write(f"changed_variants={json.dumps(render_list(changed))}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
