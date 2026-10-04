#!/usr/bin/env python3
"""
Fetch Ecuador's new-vehicle sales from the tax authority's record-level open
data and upsert data/Ecuador*.csv (Whole + Vans).

Source
------
Every new vehicle sold in Ecuador is invoiced, and the Servicio de Rentas
Internas (SRI, the national tax authority) records each invoice of a new
vehicle with the vehicle's catalogue data — the same register from which the
vehicle tax and the first registration are later derived. The SRI publishes
the register as open data, one CSV per calendar year, free and without login:

    https://descargas.sri.gob.ec/download/datosAbiertos/SRI_Vehiculos_Nuevos_<YYYY>.csv
    listed on datosabiertos.gob.ec as "Estadísticas Vehículos <YYYY>"

One row per processing of a vehicle (";"-separated, ~400-650k rows a year,
motorcycles included). The columns used here:

    CÓDIGO DE VEHÍCULO (the vehicle's id) · MARCA · MODELO (the SRI catalogue
    description, e.g. "YUAN PRO GS AC 5P 4X2 TA EV") · CLASE · TIPO COMBUSTIBLE
    · FECHA PROCESO (date the SRI processed the record)

The yearly files exist from 2017; the current year's file is regenerated
early each month with the month just ended (2026: Last-Modified Sep 4 for
August). AEADE, the importers' and assemblers' association, builds the
country's official monthly sales statistics from exactly this register
("FUENTE: SRI"); its monthly press bulletin is the cross-check (Governance).

Vehicle → month
---------------
A vehicle is processed one to several times (invoice, corrections, transfer
of the invoice to the registry), always with the same catalogue data. It is
counted ONCE, in the month of its first processing — unless it was already
processed in either of the two preceding calendar years (LOOKBACK_YEARS;
then it was counted there). This reproduces AEADE's annual market totals
within 0.2 % for 2019-2024 and its monthly fuel split within ~1 %. The same
rule applies in backfills and in monthly runs, so both give the same rows.

History starts 2018-01: the 2017 file has no processing date (only a month
of sale, and no 2016 file to deduplicate its January against). It is read
as lookback for 2018-2019 only.

Record → CSV
------------
SRI's CLASE (motorcycles are skipped first):

  Whole  data/Ecuador.csv       AUTOMOVIL (sedans, hatchbacks, wagons, coupés)
                                + JEEP (SUVs)                       (EU M1)
                                = AEADE's segments "automóvil" + "SUV"
  Vans   data/Ecuador_Vans.csv  CAMIONETA — pickups, panel vans and van-based
                                minibuses ("furgonetas")            (≈ EU N1)

Not in any variant: CAMION, VOLQUETA, TANQUERO, TRAILER (tractor units),
OMNIBUS (buses, minibuses), ESPECIAL (armoured, cranes, ambulances).
All of these, but not motorcycles, are in AEADE's market total, so the
cross-check uses the all-segment count.

New vehicles only: the dataset is the register of NEW vehicles ("Vehículos
Nuevos"); Ecuador bans imports of used vehicles. TIPO TRANSACCIÓN COMPRA LOCAL
(dealer sale) and IMPORTACIÓN DIRECTA (a new vehicle imported by its buyer)
both count.

Fuel → columns
--------------
The catalogue description (MODELO) ends in the powertrain for every electric,
hybrid and diesel model ("... TA EV", "... TA HYBRID", "... TM DIESEL"); the
invoice's TIPO COMBUSTIBLE is filled per record and is less reliable (about
2,100 cars 2018-2026 whose description says HYBRID were invoiced as
GASOLINA — Toyota Corolla Cross, Kia Niro, Suzuki mild hybrids). The
description therefore decides, ordered rules, first match wins
(DESCRIPTION_RULES):

  "E-POWER" anywhere      → HEV  (Nissan X-Trail e-POWER: a series hybrid
                                  without a plug, which SRI codes ELECTRICO
                                  and catalogues as "EV")
  ends in HYBRID          → HEV
  ends in EV / EV CN      → BEV
  ends in DIESEL [CN]     → DIESEL
  otherwise TIPO COMBUSTIBLE:
    GASOLINA → PETROL · DIESEL → DIESEL · ELECTRICO → BEV
    HIBRIDO_GASOLINA_BATERIAS, HIBRIDO_DIESEL_BATERIAS → HEV
    DUAL_GAS_GASOLINA, GAS_NATURAL_COMPRIMIDO, GAS_LICUADO_PETROLEO,
    ALCOHOL, OTROS, SOLAR, NO_UTILIZA → OTHERS

HEV is every hybrid: SRI has a single hybrid code and the description a
single "HYBRID" suffix, so mild, full, plug-in and range-extender hybrids
cannot be told apart (AEADE's own catalogue puts 2025 at 49 % mild, 34 %
full, 14 % plug-in, 3 % e-POWER). The gallery convention for a combined
hybrid figure applies: HEV column, no PHEV column (hev_split false — the
chart draws no PHEV curve). Mild hybrids that the description does not call
HYBRID stay in PETROL.

Governance (every real run)
---------------------------
* every column used must be in the header (schema drift aborts);
* the download must match Content-Length;
* a month is only taken once its year's file was regenerated after the month
  ended (Last-Modified ≥ the 1st of the next month) — never a partial month;
* processing dates that do not parse, or fall outside the file's year, above
  MAX_BAD_DATE_SHARE of a file's vehicle rows abort (date-format drift; the
  files have used six date formats since 2017);
* unknown CLASE values above MAX_UNKNOWN_SHARE of the month, and unknown fuel
  codes above MAX_UNKNOWN_SHARE of Whole, abort; both are listed;
* a month below MIN_MONTH_FRACTION of the trailing-12 median Whole is not
  written (--force overrides);
* cross-check: AEADE's newest monthly press bulletin (built from the same
  register) — all-segment total and BEV, and Whole against its automóvil +
  SUV segments, for every month the bulletin shows. Beyond XCHECK_TOL the run
  aborts (--force overrides); an unreachable or unreadable bulletin is a
  warning (AEADE has uploaded bulletins up to three months late);
* fuels sum to TOTAL for every row written.

Writes are line-level upserts keyed on (period, variant) (invariant 2); a row
whose `source` is not ours is never overwritten without --force. Every real
run re-derives the newest two years and lists changed earlier rows in the
step summary. Also writes market/ecuador_top.json (top BEV and hybrid brands
and models, trailing 12 months, Whole) via scripts/market_top.py.

Usage
-----
    python scripts/fetch_ecuador.py                   # newest complete month
    python scripts/fetch_ecuador.py --period 2026-07
    python scripts/fetch_ecuador.py --backfill        # 2018-01 → now
    python scripts/fetch_ecuador.py --from-dir DIR [--bulletin FILE]   # offline

`--from-dir` reads SRI_Vehiculos_Nuevos_<YYYY>.csv[.gz] from a local
directory (every month in the files counts as complete); `--bulletin` is an
AEADE press-bulletin PDF (or its extracted text) for the cross-check.
"""

from __future__ import annotations

import argparse
import collections
import csv
import datetime as dt
import email.utils
import gzip
import io
import json
import os
import re
import sys
import time
import unicodedata
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import market_top  # noqa: E402

SOURCE = "SRI new-vehicle register (open data)"
FILE_URL = "https://descargas.sri.gob.ec/download/datosAbiertos/SRI_Vehiculos_Nuevos_{year}.csv"
FILE_RE = re.compile(r"SRI_Vehiculos_Nuevos_(\d{4})\.csv(\.gz)?$")
FIRST_FILE_YEAR = 2017            # oldest file SRI publishes (lookback only)
FIRST_PERIOD = "2018-01"
LOOKBACK_YEARS = 2

BULLETIN_PAGE = "https://www.aeade.net/boletines-de-prensa-venta-de-vehiculos/"
BULLETIN_DOWNLOAD = "https://www.aeade.net/?sdm_process_download=1&download_id={id}"
BULLETIN_CANDIDATES = 8           # newest download ids resolved per run

VARIANT_CSV = {
    "Whole": "data/Ecuador.csv",
    "Vans": "data/Ecuador_Vans.csv",
}
RENDERED_VARIANTS = ("Whole", "Vans")

FUELS = ["BEV", "HEV", "PETROL", "DIESEL", "OTHERS"]
CSV_COLUMNS = (["period", "time_interval", "variant", "source"]
               + FUELS + ["TOTAL", "notes"])

MOTORCYCLE = "MOTOCICLETA"
CLASS_VARIANT = {"AUTOMOVIL": "Whole", "JEEP": "Whole", "CAMIONETA": "Vans"}
OTHER_CLASSES = frozenset({"CAMION", "VOLQUETA", "TANQUERO", "TRAILER", "OMNIBUS", "ESPECIAL"})

FUEL_CODE = {
    "GASOLINA": "PETROL",
    "DIESEL": "DIESEL",
    "ELECTRICO": "BEV",
    "HIBRIDO_GASOLINA_BATERIAS": "HEV",
    "HIBRIDO_DIESEL_BATERIAS": "HEV",
    "DUAL_GAS_GASOLINA": "OTHERS",
    "GAS_NATURAL_COMPRIMIDO": "OTHERS",
    "GAS_LICUADO_PETROLEO": "OTHERS",
    "ALCOHOL": "OTHERS",
    "OTROS": "OTHERS",
    "SOLAR": "OTHERS",
    "NO_UTILIZA": "OTHERS",
}

# (pattern on the catalogue description, column, why) — ordered, first match wins.
DESCRIPTION_RULES = [
    (r"\bE-?POWER\b", "HEV",
     "Nissan e-POWER: series hybrid without a plug (SRI codes ELECTRICO, catalogue says EV)"),
    (r"\bHYBRID$", "HEV", "catalogue description ends in HYBRID"),
    (r"\bEV(?: CN)?$", "BEV", "catalogue description ends in EV"),
    (r"\bDIESEL(?: CN)?$", "DIESEL", "catalogue description ends in DIESEL"),
]
_RULES = [(re.compile(rx), col, why) for rx, col, why in DESCRIPTION_RULES]

MIN_MONTH_FRACTION = 0.40
WARN_MONTH_FRACTION = 0.60
MAX_UNKNOWN_SHARE = 0.02
MAX_BAD_DATE_SHARE = 0.005
# Cross-check tolerance against AEADE (relative; BEV also passes within
# XCHECK_BEV_ABS units). Observed over every bulletin with an energy table
# (16 bulletins, 2024-05..2026-08): total and Whole within 1.5 %, BEV within
# 3.4 % — except AEADE's first edition for October/November 2025, which put
# ~500 vehicles in October that the register (and AEADE's later figures for
# the two months together, -0.5 %) put in November: total -4.2 % / +3.4 %,
# car+SUV -6.3 % / +5.2 %. Beyond XCHECK_WARN a month is flagged; beyond
# XCHECK_TOL the run aborts.
XCHECK_TOL = 0.10
XCHECK_WARN = 0.03
XCHECK_BEV_ABS = 15

HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; LeRaffl-Gallery data fetcher; "
                  "+https://github.com/LeRaffl/LeRaffl-Gallery)",
}

REPO = Path(__file__).resolve().parent.parent
SLUG = "ecuador"
TOP_PATH = market_top.MARKET_DIR / f"{SLUG}_top.json"
TOP_UNIT = ("new cars and SUVs invoiced (SRI new-vehicle register: brand = 'MARCA', "
            "model = the start of SRI's catalogue description 'MODELO', up to the first "
            "trim or specification word). HEV = every hybrid — the register does not "
            "separate mild, full and plug-in hybrids")


# ── normalisation ──────────────────────────────────────────────────────────

def norm(s) -> str:
    """Upper case, accents stripped, whitespace collapsed (headers and codes)."""
    s = unicodedata.normalize("NFKD", str(s if s is not None else ""))
    return " ".join(s.encode("ascii", "ignore").decode().upper().split())


MONTHS = {"ENE": 1, "JAN": 1, "FEB": 2, "MAR": 3, "ABR": 4, "APR": 4, "MAY": 5,
          "JUN": 6, "JUL": 7, "AGO": 8, "AUG": 8, "SEP": 9, "SET": 9, "OCT": 10,
          "NOV": 11, "DIC": 12, "DEC": 12}
DATE_RE = re.compile(r"^(\d{1,2})[/-]([A-Za-z]{3,5}|\d{1,2})[/-](\d{2}|\d{4})$")


def parse_date(s: str) -> dt.date | None:
    """Day-first dates in every spelling the files have used: 28/12/2018 21:50,
    27/12/2019 22:46:06, 27-Nov-20, 29-Ago-20, 30-Sept-20, 2-dic-21, 9/12/2024,
    17/9/2025, 24/06/2026. (The 2018/2019 headers say MM/DD/AA; the data is
    day first.)"""
    m = DATE_RE.match(str(s).strip().split(" ")[0])
    if not m:
        return None
    d, mon, y = m.groups()
    month = int(mon) if mon.isdigit() else MONTHS.get(norm(mon)[:3])
    year = int(y) + (2000 if len(y) == 2 else 0)
    try:
        return dt.date(year, month, int(d))
    except (TypeError, ValueError):
        return None


def fuel_column(model: str, code: str) -> tuple[str | None, str | None]:
    """(column, rule) for one record: the catalogue description decides when it
    names the powertrain, else the invoice's fuel code. Column None = unknown
    fuel code (counted as OTHERS by the caller, and listed)."""
    m = norm(model)
    for rx, col, why in _RULES:
        if rx.search(m):
            return col, why
    return FUEL_CODE.get(norm(code)), None


# ── reading a yearly file ──────────────────────────────────────────────────

COLUMN_NAMES = {
    "code": ("CODIGO DE VEHICULO", "CODIGO VEHICULO", "CODIGO VEHICULO 1"),
    "make": ("MARCA",),
    "model": ("MODELO",),
    "cls": ("CLASE",),
    "fuel": ("TIPO COMBUSTIBLE",),
}


def resolve_columns(header: list[str], need_date: bool) -> dict[str, int]:
    names = [norm(h) for h in header]
    idx: dict[str, int] = {}
    for key, options in COLUMN_NAMES.items():
        for o in options:
            if o in names:
                idx[key] = names.index(o)
                break
    dates = [i for i, n in enumerate(names) if n.startswith("FECHA PROCESO")]
    if dates:
        idx["date"] = dates[0]
    missing = [k for k in COLUMN_NAMES if k not in idx]
    if need_date and "date" not in idx:
        missing.append("FECHA PROCESO")
    if missing:
        raise SystemExit(f"Schema drift: columns {missing} not in header {header} — not writing.")
    return idx


def decode(raw: bytes) -> str:
    """The 2017-2025 files are Windows-1252, the 2026 file UTF-8 with BOM."""
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("cp1252")


class YearFile:
    """One yearly file reduced to what the counting needs: every vehicle code
    (for the lookback) and, per code, its first processing date and catalogue
    data. Motorcycles are dropped on read."""

    def __init__(self, year: int) -> None:
        self.year = year
        self.codes: set[str] = set()
        self.first: dict[str, tuple[dt.date, str, str, str, str]] = {}
        self.rows = 0
        self.vehicle_rows = 0
        self.bad_dates = 0
        self.dated = False

    @classmethod
    def parse(cls, text: str, year: int, need_date: bool = True) -> "YearFile":
        yf = cls(year)
        reader = csv.reader(io.StringIO(text), delimiter=";")
        header = next(reader)
        idx = resolve_columns(header, need_date)
        yf.dated = "date" in idx
        ic, im, imo, icl, ifu = (idx[k] for k in ("code", "make", "model", "cls", "fuel"))
        idt = idx.get("date")
        width = max(idx.values()) + 1
        for row in reader:
            if len(row) < width:
                if any(c.strip() for c in row):
                    yf.bad_dates += 1
                continue
            yf.rows += 1
            vclass = norm(row[icl])
            if vclass == MOTORCYCLE:
                continue
            code = row[ic].strip()
            if not code:
                continue
            yf.vehicle_rows += 1
            yf.codes.add(code)
            if idt is None:
                continue
            d = parse_date(row[idt])
            if d is None or d.year != year:
                yf.bad_dates += 1
                continue
            prev = yf.first.get(code)
            if prev is None or d < prev[0]:
                yf.first[code] = (d, norm(row[im]), norm(row[imo]), vclass, norm(row[ifu]))
        return yf

    def bad_date_share(self) -> float:
        return self.bad_dates / self.vehicle_rows if self.vehicle_rows else 0.0


# ── counting ───────────────────────────────────────────────────────────────

def empty_counts() -> dict[str, int]:
    return {k: 0 for k in FUELS + ["TOTAL"]}


class Aggregator:
    def __init__(self) -> None:
        self.counts = collections.defaultdict(
            lambda: {v: empty_counts() for v in VARIANT_CSV})
        self.allseg = collections.defaultdict(empty_counts)   # AEADE scope
        self.units = collections.Counter()                    # (p, cls, brand, model) Whole
        self.reclassed = collections.Counter()                # (p, variant, code, col, make, model)
        self.unknown_fuel = collections.Counter()             # (p, code)
        self.unknown_class = collections.Counter()            # (p, class)
        self.other_class = collections.Counter()              # (p, class)
        self.lookback_hits = collections.Counter()            # p

    def add_year(self, yf: YearFile, lookback: set[str]) -> None:
        for code, (d, make, model, vclass, fcode) in yf.first.items():
            p = f"{d.year:04d}-{d.month:02d}"
            if code in lookback:
                self.lookback_hits[p] += 1
                continue
            col, rule = fuel_column(model, fcode)
            if col is None:
                self.unknown_fuel[(p, fcode)] += 1
                col = "OTHERS"
            seg = self.allseg[p]
            seg[col] += 1
            seg["TOTAL"] += 1
            variant = CLASS_VARIANT.get(vclass)
            if variant is None:
                if vclass in OTHER_CLASSES:
                    self.other_class[(p, vclass)] += 1
                else:
                    self.unknown_class[(p, vclass)] += 1
                continue
            c = self.counts[p][variant]
            c[col] += 1
            c["TOTAL"] += 1
            base = FUEL_CODE.get(fcode)
            if rule and base != col:
                self.reclassed[(p, variant, fcode or "(blank)", col, make, model)] += 1
            if variant == "Whole":
                self.units[(p, col, display_brand(make), display_model(make, model))] += 1

    def periods(self) -> list[str]:
        return sorted(self.allseg)


def count_years(files: dict[int, YearFile], years: list[int]) -> Aggregator:
    """Count the vehicles of `years`, each against the codes of the
    LOOKBACK_YEARS years before it (those that exist)."""
    agg = Aggregator()
    for y in years:
        lookback: set[str] = set()
        for b in range(y - LOOKBACK_YEARS, y):
            if b in files:
                lookback |= files[b].codes
        agg.add_year(files[y], lookback)
    return agg


# ── display names for the top-brands/models table (not used for the data) ──

BRAND_ALIASES = {
    "MERCEDES BENZ": "MERCEDES-BENZ",
    "URVANE MOVILITY": "URVANE MOBILITY",
    "LYNK AND CO": "LYNK & CO",
}
# Words that end the model name in SRI's catalogue description: the
# specification block (AC, displacement, doors, drive, gearbox, cab, fuel) …
SPEC_WORD = re.compile(r"^(AC|\d+\.\d+|\d+P|\d+X\d+|TA|TM|CVT|AT|MT|CD|CS|EV|HYBRID|DIESEL|CN|"
                       r"\d+PAS|\d+S|\d+KM)$")
# … and trim / version words.
TRIM_WORDS = frozenset({
    "GS", "GL", "GLX", "GLS", "GX", "LX", "EX", "SX", "FWD", "AWD", "RWD", "2WD", "4WD",
    "AIR", "LIGHT", "WAVE", "CORE", "MID", "HIGH", "LUX", "LUXURY", "COMFORT", "ELITE",
    "SUPREME", "EXCLUSIVE", "ADVANCE", "TOURING", "BASE", "STD", "STANDARD", "SR", "LR",
    "PREMIUM", "PREMIER", "LIMITED", "SPORT", "DISTINGUISHED", "FULL", "PLATINUM", "TITANIUM",
    "TREND", "XLT", "XLE", "LE", "SE", "XSE", "HGS", "ISG", "DSBS", "FHEV", "HEV", "MHEV",
    "PHEV", "DM-I", "DMI", "DM-P", "DMO", "REEV", "EREV", "EPOWER", "E-POWER", "CREW", "CAB",
    "T", "TSS", "NEW",
})
MODEL_WORDS = 2


def display_brand(make: str) -> str:
    b = market_top.clean(make)
    return BRAND_ALIASES.get(b, b)


def display_model(make: str, model: str) -> str:
    """'YUAN PRO GS AC 5P 4X2 TA EV' → 'YUAN PRO'; 'TIGGO 4 PRO COMFORT AC 1.5 …'
    → 'TIGGO 4'; 'NETA V AC 5P …' → 'NETA V' (a brand repeat is dropped only
    when more than a one- or two-letter rest remains)."""
    toks = norm(model).replace(",", " ").split()
    if toks and toks[0] == "NEW":
        toks = toks[1:]
    out: list[str] = []
    for t in toks:
        if SPEC_WORD.match(t) or t in TRIM_WORDS:
            break
        out.append(t)
        if len(out) == MODEL_WORDS:
            break
    if len(out) > 1 and out[0] == norm(make).split()[0] and len(" ".join(out[1:])) > 2:
        out = out[1:]
    return " ".join(out) or (toks[0] if toks else "")


# ── AEADE press bulletin (cross-check) ─────────────────────────────────────

MES = {"ENE": 1, "FEB": 2, "MAR": 3, "ABR": 4, "MAY": 5, "JUN": 6, "JUL": 7, "AGO": 8,
       "SEP": 9, "SET": 9, "OCT": 10, "NOV": 11, "DIC": 12}
MES_LONG = {"ENERO": 1, "FEBRERO": 2, "MARZO": 3, "ABRIL": 4, "MAYO": 5, "JUNIO": 6,
            "JULIO": 7, "AGOSTO": 8, "SEPTIEMBRE": 9, "SETIEMBRE": 9, "OCTUBRE": 10,
            "NOVIEMBRE": 11, "DICIEMBRE": 12}
NUM_TOKEN = re.compile(r"^\d{1,3}(?:[.,]\d{3})*$")
ENERGY_ROWS = {"GASOLINA": "PETROL", "DIESEL": "DIESEL", "HIBRIDO": "HEV",
               "ELECTRICO BEV": "BEV", "ELECTRICO EREV": "EREV", "TOTAL": "TOTAL"}
SEGMENT_ROWS = {"SUV": "SUV", "CAMIONETA": "CAMIONETA", "AUTOMOVIL": "AUTOMOVIL",
                "TOTAL": "TOTAL"}


def _table(text: str, head: str, rows: dict[str, str]) -> dict[str, dict[str, int]]:
    """Parse one of the bulletin's small month tables:

        Energía   Ago 25  Ago 26  Ene-Ago 25  Ene-Ago 26
        GASOLINA  5.689   6.407   41.620      50.769
        ...

    → {"2025-08": {...}, "2026-08": {...}, "ytd:2025-08": {...}, ...}. Thousands
    separators are "." or ","; a row whose cells do not all parse keeps only its
    leading clean cells (the single months come first)."""
    lines = [unicodedata.normalize("NFC", ln) for ln in text.splitlines()]
    head_re = re.compile(rf"^\s*{head}\b(.*)$", re.I)
    for i, line in enumerate(lines):
        hm = head_re.match(norm(line))
        if not hm:
            continue
        cols = re.findall(r"(ENE-)?([A-Z]{3}) (\d{2})(?![\d/])", hm.group(1).split(" VAR ")[0])
        if not cols:
            continue
        keys = []
        for ytd, mon, yy in cols:
            if mon not in MES:
                break
            keys.append(("ytd:" if ytd else "") + f"20{yy}-{MES[mon]:02d}")
        else:
            out: dict[str, dict[str, int]] = {k: {} for k in keys}
            for row in lines[i + 1:i + 14]:
                r = norm(row)
                label = next((lab for lab in sorted(rows, key=len, reverse=True)
                              if r == lab or r.startswith(lab + " ")), None)
                if label is None:
                    continue
                toks = r[len(label):].split()
                if not toks or toks[0].endswith("%"):
                    continue                      # a share-of-market line, not the table
                for k, t in zip(keys, toks):
                    if not NUM_TOKEN.match(t):
                        break
                    out[k][rows[label]] = int(re.sub(r"[.,]", "", t))
                if label == "TOTAL":
                    break
            if any(out.values()):
                return out
    return {}


def parse_bulletin(text: str) -> dict[str, dict[str, int]]:
    """{period: {PETROL, DIESEL, HEV, BEV, TOTAL, WHOLE}} for every single
    month the bulletin's energy table shows (WHOLE = automóvil + SUV from the
    light-vehicle segment table, where present), plus "ytd:<period>" entries."""
    energy = _table(text, "ENERGIA", ENERGY_ROWS)
    segments = _table(text, "SEGMENTO", SEGMENT_ROWS)
    out = {k: dict(v) for k, v in energy.items() if v}
    for k, v in segments.items():
        if "SUV" in v and "AUTOMOVIL" in v and k in out:
            out[k]["WHOLE"] = v["SUV"] + v["AUTOMOVIL"]
    return out


def bulletin_text_from_pdf(pdf: bytes) -> str:
    import logging
    import pdfplumber  # only needed for the cross-check
    logging.getLogger("pdfminer").setLevel(logging.ERROR)   # font-metric noise
    with pdfplumber.open(io.BytesIO(pdf)) as doc:
        return "\n".join(page.extract_text() or "" for page in doc.pages)


def bulletin_month(name: str) -> str | None:
    """'Boletin-de-Prensa-Agosto-2026.pdf' → '2026-08'."""
    n = norm(name.replace("-", " ").replace("_", " "))
    m = re.search(r"\b(" + "|".join(MES_LONG) + r")\s*(20\d\d)\b", n)
    return f"{m.group(2)}-{MES_LONG[m.group(1)]:02d}" if m else None


def find_bulletins(session: requests.Session) -> dict[str, str]:
    """{period: pdf url} for the newest BULLETIN_CANDIDATES downloads on
    AEADE's bulletin page (each download id redirects to the PDF)."""
    r = session.get(BULLETIN_PAGE, timeout=60)
    r.raise_for_status()
    ids = sorted({int(i) for i in re.findall(r"sdm_process_download=1&(?:amp;|#038;)?download_id=(\d+)",
                                             r.text)}, reverse=True)
    out: dict[str, str] = {}
    for i in ids[:BULLETIN_CANDIDATES]:
        h = session.get(BULLETIN_DOWNLOAD.format(id=i), allow_redirects=False, timeout=60)
        loc = h.headers.get("Location", "")
        p = bulletin_month(loc.rsplit("/", 1)[-1]) if loc.lower().endswith(".pdf") else None
        if p and p not in out:
            out[p] = loc
    return out


def load_bulletin(session: requests.Session | None, args, target: str,
                  periods: list[str]) -> tuple[dict | None, str]:
    """(parsed table, where from) for the bulletin of `target`, else the newest
    bulletin of a month this run derived; (None, reason) when there is none."""
    try:
        if args.bulletin:
            p = Path(args.bulletin)
            raw = p.read_bytes()
            text = bulletin_text_from_pdf(raw) if raw[:4] == b"%PDF" else raw.decode("utf-8")
            return parse_bulletin(text), p.name
        if session is None:
            return None, "offline run without --bulletin"
        found = find_bulletins(session)
        usable = [p for p in found if p in periods]
        if not usable:
            return None, (f"no AEADE bulletin for a month of this run among the newest "
                          f"downloads (found: {sorted(found) or 'none'})")
        pick = target if target in usable else max(usable)
        r = session.get(found[pick], timeout=180)
        r.raise_for_status()
        table = parse_bulletin(bulletin_text_from_pdf(r.content))
        if not table:
            return None, f"{found[pick].rsplit('/', 1)[-1]}: energy table not found"
        return table, found[pick].rsplit("/", 1)[-1]
    except Exception as e:  # noqa: BLE001 — reported by the caller
        return None, f"{type(e).__name__}: {e}"


def within(got: int, want: int, tol: float, abs_tol: int = 0) -> bool:
    return abs(got - want) <= max(abs_tol, tol * want)


def cross_check(agg: Aggregator, table: dict,
                periods: list[str]) -> tuple[list[str], list[str], list[str]]:
    """(report lines, problems, flagged). Compared: all-segment TOTAL and BEV,
    and Whole against automóvil + SUV, for each single month in the table;
    problems are beyond XCHECK_TOL, flagged beyond XCHECK_WARN. Hybrids are
    shown, not judged (AEADE moves hybrids between months, Oct/Nov 2025)."""
    lines = ["| month | AEADE total | ours | AEADE BEV | ours | AEADE hybrid | ours "
             "| AEADE car+SUV | Whole |", "|---|" + "---:|" * 8]
    problems, flagged = [], []
    for p in sorted(k for k in table if not k.startswith("ytd:")):
        if p not in periods:
            continue
        a, s, w = table[p], agg.allseg[p], agg.counts[p]["Whole"]["TOTAL"]

        def cell(key, ours, abs_tol=0, check=True):
            if key not in a:
                return "—", "—"
            msg = f"{p} {key}: ours {ours:,} vs AEADE {a[key]:,} ({ours / a[key] - 1:+.1%})"
            close = within(ours, a[key], XCHECK_WARN, abs_tol)
            if check and not within(ours, a[key], XCHECK_TOL, abs_tol):
                problems.append(msg)
            elif check and not close:
                flagged.append(msg)
            mark = "" if close else " ⚠"
            return f"{a[key]:,}", f"{ours:,} ({ours / a[key] - 1:+.1%}){mark}"

        t = cell("TOTAL", s["TOTAL"])
        b = cell("BEV", s["BEV"], XCHECK_BEV_ABS)
        h = cell("HEV", s["HEV"], check=False)           # AEADE moves hybrids between months
        wh = cell("WHOLE", w)
        lines.append(f"| {p} | {t[0]} | {t[1]} | {b[0]} | {b[1]} | {h[0]} | {h[1]} | "
                     f"{wh[0]} | {wh[1]} |")
    ytd = sorted(k for k in table if k.startswith("ytd:") and k[4:] in periods)
    for k in ytd:
        p = k[4:]
        months = [q for q in periods if q[:4] == p[:4] and q <= p]
        if len(months) != int(p[5:7]):
            continue
        tot = sum(agg.allseg[q]["TOTAL"] for q in months)
        bev = sum(agg.allseg[q]["BEV"] for q in months)
        a = table[k]
        if "TOTAL" in a and "BEV" in a:
            lines.append(f"\nJanuary–{p}: total {tot:,} vs AEADE {a['TOTAL']:,} "
                         f"({tot / a['TOTAL'] - 1:+.1%}); BEV {bev:,} vs {a['BEV']:,} "
                         f"({bev / a['BEV'] - 1:+.1%}).")
    return lines, problems, flagged


# ── network ────────────────────────────────────────────────────────────────

def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HTTP_HEADERS)
    return s


def with_retries(fn, *args, tries: int = 4, **kw):
    for attempt in range(tries):
        try:
            return fn(*args, **kw)
        except (requests.ConnectionError, requests.Timeout, requests.HTTPError) as e:
            if attempt == tries - 1:
                raise
            print(f"  retry after {type(e).__name__}: {e}")
            time.sleep(10 * (attempt + 1))
    raise AssertionError("unreachable")


def head(session: requests.Session, year: int) -> tuple[int, dt.datetime | None] | None:
    """(size, Last-Modified UTC) of a yearly file, None when SRI has no file."""
    def _head():
        r = session.head(FILE_URL.format(year=year), timeout=60, allow_redirects=True)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        lm = r.headers.get("Last-Modified")
        stamp = email.utils.parsedate_to_datetime(lm).replace(tzinfo=None) if lm else None
        return int(r.headers.get("Content-Length") or 0), stamp
    return with_retries(_head)


def download(session: requests.Session, year: int, size: int) -> bytes:
    def _get():
        r = session.get(FILE_URL.format(year=year), timeout=900)
        r.raise_for_status()
        if size and len(r.content) != size:
            raise requests.HTTPError(f"got {len(r.content):,} bytes, Content-Length {size:,}")
        return r.content
    t = time.time()
    raw = with_retries(_get)
    print(f"    {year}: downloaded {len(raw) / 1e6:.0f} MB in {time.time() - t:.0f}s")
    return raw


def list_dir_files(d: Path) -> dict[int, Path]:
    out = {}
    for f in sorted(d.iterdir()):
        m = FILE_RE.search(f.name)
        if m:
            out[int(m.group(1))] = f
    return out


# ── CSV line-level upsert (invariant 2) ────────────────────────────────────

def fmt(v: int) -> str:
    return f"{float(v):.1f}"


def render_line(period: str, variant: str, counts: dict[str, int], notes: str = "") -> str:
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


def revisions(path: Path, updates: dict[tuple[str, str], str]) -> list[str]:
    """Existing rows that `updates` changes, as 'period variant: COL a→b, …'."""
    _, lines = read_csv_lines(path)
    old = {line_key(l): l for l in lines}
    out = []
    for key, new in sorted(updates.items()):
        if key not in old or old[key] == new:
            continue
        a = dict(zip(CSV_COLUMNS, next(csv.reader([old[key]]))))
        b = dict(zip(CSV_COLUMNS, next(csv.reader([new]))))
        diffs = [f"{c} {float(a[c] or 0):g}→{float(b[c]):g}"
                 for c in FUELS + ["TOTAL"] if a.get(c) != b.get(c)]
        if a.get("source") != b.get("source"):
            diffs.append(f"source `{a.get('source')}`→`{b.get('source')}`")
        out.append(f"{key[0]} {key[1]}: " + ", ".join(diffs))
    return out


# ── checks & report ────────────────────────────────────────────────────────

def median_fraction(period: str, total: int, have: dict[str, dict]) -> float | None:
    """`total` as a fraction of the trailing-12 median TOTAL (None if < 6 months)."""
    prior = sorted(p for p in have if p < period)[-12:]
    if len(prior) < 6:
        return None
    vals = sorted(float(have[p]["TOTAL"]) for p in prior)
    median = vals[len(vals) // 2]
    return total / median if median else None


def check_sums(agg: Aggregator, periods: list[str]) -> list[str]:
    problems = []
    for p in periods:
        for v, c in agg.counts[p].items():
            if sum(c[k] for k in FUELS) != c["TOTAL"]:
                problems.append(f"{p} {v}: fuels do not sum to TOTAL")
        s = agg.allseg[p]
        if sum(s[k] for k in FUELS) != s["TOTAL"]:
            problems.append(f"{p} all segments: fuels do not sum to TOTAL")
    return problems


def unknown_shares(agg: Aggregator, period: str) -> tuple[float, float]:
    """(unknown CLASE share of all vehicles, unknown fuel share of Whole)."""
    seg = agg.allseg[period]["TOTAL"] or 1
    whole = agg.counts[period]["Whole"]["TOTAL"] or 1
    uc = sum(n for (p, _), n in agg.unknown_class.items() if p == period)
    uf = sum(n for (p, _), n in agg.unknown_fuel.items() if p == period)
    return uc / seg, uf / whole


def build_top(agg: Aggregator, target: str) -> dict:
    window = set(market_top.month_window(target))
    units = market_top.per_month({k: n for k, n in agg.units.items() if k[0] in window})
    monthly = {p: (units.get(p, {}), agg.counts[p]["Whole"]["TOTAL"])
               for p in window if p in agg.counts and agg.counts[p]["Whole"]["TOTAL"]}
    return market_top.build_top_monthly("Ecuador", SOURCE, target, monthly, TOP_UNIT)


def write_top(agg: Aggregator, target: str) -> None:
    top = build_top(agg, target)
    market_top.report(top, TOP_PATH, market_top.write_top(top, TOP_PATH))


def report(agg: Aggregator, target: str, periods: list[str], xcheck: list[str],
           xsource: str, revised: list[str], stamps: dict[int, str]) -> str:
    t = agg.counts[target]
    out = [f"## Ecuador (SRI new-vehicle register, open data) — {target}\n",
           "Files: " + ", ".join(f"{y} ({s})" for y, s in sorted(stamps.items())) + "\n",
           "| variant | " + " | ".join(FUELS) + " | TOTAL | BEV share | hybrid share |",
           "|---|" + "---:|" * (len(FUELS) + 3)]
    for v in VARIANT_CSV:
        c = t[v]
        tot = c["TOTAL"] or 1
        out.append(f"| {v} | " + " | ".join(f"{c[k]:,}" for k in FUELS)
                   + f" | {c['TOTAL']:,} | {c['BEV'] / tot:.2%} | {c['HEV'] / tot:.1%} |")
    s = agg.allseg[target]
    out.append(f"\nAll segments (AEADE's scope, motorcycles excluded): {s['TOTAL']:,} "
               f"(BEV {s['BEV']:,}, hybrid {s['HEV']:,}). Vehicles skipped as already "
               f"counted in an earlier year: {agg.lookback_hits[target]:,}.")
    out.append(f"\nMonths processed: {periods[0]} → {periods[-1]} ({len(periods)})")
    out.append(f"\n### Cross-check against AEADE's press bulletin ({xsource})\n")
    out.append("\n".join(xcheck))
    out.append("\n### Earlier rows changed by this run (SRI revisions)\n")
    out.append("\n".join(f"- {r}" for r in revised[:40]) or "None.")
    rc = collections.Counter()
    for (p, v, f, col, mk, mo), n in agg.reclassed.items():
        if p == target:
            rc[(v, f, col, mk, mo)] += n
    out.append("\n### Fuel code overridden by the catalogue description this month (review)\n")
    out.append("\n".join(f"- {v}: `{f}` → {col}: {mk} `{mo}` × {n}"
                         for (v, f, col, mk, mo), n in sorted(rc.items(), key=lambda kv: -kv[1])[:30])
               or "None.")
    for cls in ("BEV", "HEV"):
        models = collections.Counter()
        for (p, c, b, m), n in agg.units.items():
            if p == target and c == cls:
                models[(b, m)] += n
        out.append(f"\n### {cls} models this month (Whole)\n")
        out.append(", ".join(f"{b} {m} {n:,}" for (b, m), n in models.most_common(15)) or "—")
    oc = {c: n for (p, c), n in agg.other_class.items() if p == target}
    out.append("\n### Classes in no variant (trucks, buses, special) this month\n")
    out.append(", ".join(f"{c} {n:,}" for c, n in sorted(oc.items())) or "None.")
    unk = ([f"- CLASE `{c or '(blank)'}`: {n:,}" for (p, c), n in agg.unknown_class.items() if p == target]
           + [f"- TIPO COMBUSTIBLE `{f or '(blank)'}`: {n:,} (counted as OTHERS)"
              for (p, f), n in agg.unknown_fuel.items() if p == target])
    out.append("\n### Unknown classes / fuel codes this month (review!)\n")
    out.append("\n".join(unk) or "None.")
    return "\n".join(out) + "\n"


# ── month selection ────────────────────────────────────────────────────────

def month_after(period: str) -> dt.datetime:
    y, m = int(period[:4]), int(period[5:7])
    return dt.datetime(y + (m == 12), 1 if m == 12 else m + 1, 1)


def complete_months(agg: Aggregator, stamps: dict[int, dt.datetime | None],
                    offline: bool) -> list[str]:
    """Months in the data whose year's file was regenerated after they ended."""
    out = []
    for p in agg.periods():
        if p < FIRST_PERIOD:
            continue
        lm = stamps.get(int(p[:4]))
        if offline or (lm is not None and lm >= month_after(p)):
            out.append(p)
    return out


def expected_target(year: int, lm: dt.datetime | None) -> str | None:
    """Newest month a file regenerated at `lm` can hold completely."""
    if lm is None:
        return None
    if lm.year > year:
        return f"{year}-12"
    if lm.month == 1:                      # a new year's file, nothing complete in it yet
        return f"{year - 1}-12"
    return f"{year}-{lm.month - 1:02d}"


# ── main ───────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--variant", default="all",
                    help=f"all | {' | '.join(VARIANT_CSV)} (default: all)")
    ap.add_argument("--period", default="",
                    help="Target month YYYY-MM (default: newest complete month).")
    ap.add_argument("--backfill", action="store_true",
                    help=f"Re-derive every month from {FIRST_PERIOD}. Implied when a CSV "
                         "does not exist yet.")
    ap.add_argument("--force", action="store_true",
                    help="Ignore the self-throttle, the completeness guard, the AEADE "
                         "cross-check and foreign source strings.")
    ap.add_argument("--from-dir", default="",
                    help="Offline: read SRI_Vehiculos_Nuevos_<YYYY>.csv[.gz] from here.")
    ap.add_argument("--bulletin", default="",
                    help="AEADE press-bulletin PDF (or extracted text) for the cross-check.")
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
    offline = bool(args.from_dir)
    session = None if offline else make_session()

    # Which yearly files exist, and when were they last regenerated?
    stamps: dict[int, dt.datetime | None] = {}
    sizes: dict[int, int] = {}
    if offline:
        local = list_dir_files(Path(args.from_dir))
        if not local:
            sys.exit(f"No SRI_Vehiculos_Nuevos_<YYYY>.csv in {args.from_dir}")
        newest = max(local)
        stamps = {y: None for y in local}
    else:
        newest = None
        for y in (dt.date.today().year, dt.date.today().year - 1):
            h = head(session, y)
            if h is not None:
                newest = y
                sizes[y], stamps[y] = h
                break
        if newest is None:
            sys.exit("No SRI_Vehiculos_Nuevos file for this or last year — URL changed? "
                     "Not writing.")
        print(f"Newest file: {newest} (Last-Modified {stamps[newest]})")

        guess = expected_target(newest, stamps[newest])
        target_guess = args.period or guess
        if (not backfill and not args.force and target_guess
                and all(have[v].get(target_guess, {}).get("source") == SOURCE for v in variants)):
            print(f"{target_guess} already fetched from {SOURCE} for {variants}; nothing to do.")
            return emit(args, set())

    # Years written: the newest two (re-derived every run — SRI revisions), or
    # every year in a backfill; each needs LOOKBACK_YEARS earlier files.
    first_year = int(FIRST_PERIOD[:4])
    write_years = (list(range(first_year, newest + 1)) if backfill
                   else [y for y in (newest - 1, newest) if y >= first_year])
    load_years = sorted({b for y in write_years for b in range(y - LOOKBACK_YEARS, y + 1)
                         if b >= FIRST_FILE_YEAR})

    files: dict[int, YearFile] = {}
    for y in load_years:
        if offline:
            if y not in local:
                if y in write_years:
                    sys.exit(f"{local and args.from_dir}: SRI_Vehiculos_Nuevos_{y}.csv missing.")
                print(f"  {y}: no local file (lookback only) — skipped")
                continue
            raw = local[y].read_bytes()
        else:
            if y not in stamps:
                h = head(session, y)
                if h is None:
                    if y in write_years:
                        sys.exit(f"SRI has no file for {y} — not writing.")
                    print(f"  {y}: no file at SRI (lookback only) — skipped")
                    continue
                sizes[y], stamps[y] = h
            raw = download(session, y, sizes[y])
        yf = YearFile.parse(decode(raw), y, need_date=y in write_years)
        del raw
        files[y] = yf
        print(f"  {y}: {yf.rows:,} rows, {yf.vehicle_rows:,} non-motorcycle, "
              f"{len(yf.codes):,} vehicles" + (f", {yf.bad_dates:,} bad dates" if yf.dated else
                                              " (no processing date — lookback only)"))
        if y in write_years and yf.bad_date_share() > MAX_BAD_DATE_SHARE:
            sys.exit(f"{y}: {yf.bad_dates:,} rows ({yf.bad_date_share():.1%}) with an unreadable "
                     "processing date or one outside the year — date format changed? Not writing.")

    agg = count_years(files, [y for y in write_years if y in files])
    complete = complete_months(agg, stamps, offline)
    if not complete:
        sys.exit("No complete month in the files — not writing.")
    target = args.period or complete[-1]
    if target not in complete:
        print(f"{target} is not (completely) in the SRI files yet (newest complete: "
              f"{complete[-1]}) — will retry on the next scheduled run.")
        return emit(args, set())
    periods = [p for p in complete if p <= target]
    print(f"Complete months derived: {periods[0]} → {periods[-1]} ({len(periods)})")

    shares = unknown_shares(agg, target)
    if (shares[0] > MAX_UNKNOWN_SHARE or shares[1] > MAX_UNKNOWN_SHARE) and not args.force:
        sys.exit(f"{target}: unknown CLASE {shares[0]:.1%} of vehicles / unknown fuel code "
                 f"{shares[1]:.1%} of Whole — schema drift, not writing.\n"
                 + report(agg, target, periods, [], "not run", [], {}))

    problems = check_sums(agg, periods)
    if problems:
        sys.exit("Consistency check failed:\n  " + "\n  ".join(problems[:20]))

    table, xsource = load_bulletin(session, args, target, periods)
    if table is None:
        xlines = [f"Not compared: {xsource}."]
        print(f"::warning title=Ecuador: AEADE cross-check not run::{xsource}")
    else:
        xlines, xproblems, xflagged = cross_check(agg, table, periods)
        if xflagged:
            print("::warning title=Ecuador: AEADE cross-check differences above "
                  f"{XCHECK_WARN:.0%}::" + "; ".join(xflagged))
        if xproblems and not args.force:
            sys.exit("AEADE cross-check failed (SRI file incomplete or the counting rule "
                     "broke?) — not writing:\n  " + "\n  ".join(xproblems) + "\n\n"
                     + "\n".join(xlines))

    whole_total = agg.counts[target]["Whole"]["TOTAL"]
    frac = median_fraction(target, whole_total,
                           {p: {"TOTAL": agg.counts[p]["Whole"]["TOTAL"]} for p in periods})
    if not args.force and frac is not None and frac < MIN_MONTH_FRACTION:
        print(f"{target}: Whole TOTAL {whole_total:,} is {frac:.0%} of the trailing median "
              "— looks like a broken file; not writing. --force if genuine.")
        return emit(args, set())
    if frac is not None and frac < WARN_MONTH_FRACTION:
        print(f"::warning title=Ecuador {target} unusually low::Whole TOTAL {whole_total:,} "
              f"= {frac:.0%} of the trailing-12 median — written; check it is real.")

    changed: set[str] = set()
    revised: list[str] = []
    for v in variants:
        updates = {(p, v): render_line(p, v, agg.counts[p][v])
                   for p in periods if agg.counts[p][v]["TOTAL"] > 0}
        revised += revisions(paths[v], {k: u for k, u in updates.items() if k[0] != target})
        stats = upsert_lines(paths[v], updates, args.force)
        print(f"{VARIANT_CSV[v]}: {stats}")
        if stats["added"] or stats["updated"]:
            changed.add(v)

    if "Whole" in variants:
        market_top.guarded(write_top, agg, target)

    shown = {y: (stamps[y].strftime("%Y-%m-%d") if stamps.get(y) else "local")
             for y in files if y in write_years}
    rep = report(agg, target, periods, xlines, xsource, revised, shown)
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
