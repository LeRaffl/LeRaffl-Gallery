#!/usr/bin/env python3
"""
Fetch Paraguay's car imports from the customs administration's record-level
open data and upsert data/Paraguay*.csv (Whole + Used).

Source
------
Paraguay builds no cars: every car that reaches its roads is imported, and the
market is measured by its imports (CADAM, the distributors' chamber, reports
"importación de vehículos 0 km" as the market figure). The customs
administration (Dirección Nacional de Ingresos Tributarios, ex Dirección
Nacional de Aduanas, system SOFIA) publishes every import declaration item —
free, no login, no key — on its open-data portal:

    https://datosabiertos.aduana.gov.py/ddaa/app/#/inicio
    file list:  GET /ddaa/mainctrl/listaArchivos   (JSON, ~1,800 files)
    one month:  /all_data/<YYYY>/<MES>/<YYYY>_<MES>_Nivel_Item.csv

One CSV per month (Spanish month names), one row per declaration ITEM, with
42 columns — the ones used here:

    OPERACION (IMPORTACION / EXPORTACION) · DESTINACION (customs regime code)
    · USO (NUEVO / USADO — the declared state of the goods) · POSICION (NCM
    tariff line, 8703.80.00.000X) · CANTIDAD ESTADISTICA · KILO NETO ·
    MARCA ITEM · MERCADERIA (free-text description: brand, model, year)

The register of the motor-vehicle registry itself (DNRA, www.dnra.gov.py)
is not reachable from outside Paraguay (connect timeout from GitHub
runners, 2026-10) and publishes no monthly series; see the source doc.

The files are large (≈ 300 MB per month in 2026, all goods); the server is
slow per connection (~0.4 MB/s) but honours HTTP Range, so a month is fetched
as PARTS parallel ranges (≈ 1 min) and checked against Content-Length.

Record → CSV
------------
Only cars (NCM heading 87.03) imported for consumption:

  Whole  data/Paraguay.csv        87.03 ∧ USO = NUEVO   (new cars, EU M1)
  Used   data/Paraguay_Used.csv   87.03 ∧ USO = USADO   (used-car imports) — DATA ONLY,
                                  never rendered (RENDERED_VARIANTS)

  OPERACION = IMPORTACION, and DESTINACION in CONSUMPTION_REGIMES (import for
  consumption, from a bonded warehouse, from a free zone, diplomatic). Entries
  INTO a bonded warehouse or free zone (IDA*, ZF01) are not counted — the car
  is counted when it leaves for consumption (IC09 / ZF2I), so nothing counts
  twice. Temporary imports (IT*), leasing (IML*) and "complementary fractions"
  (IFC1 — not a definitive regime, and seen to repeat a car of the main
  declaration) are not counted. A chassis number (VIN) quoted twice in one
  month counts once.
  8703.10 (golf carts, snow vehicles) is in no variant.

Units: one item is one vehicle. CANTIDAD ESTADISTICA is unreliable for cars —
thousands of items a month carry 7.0 for one vehicle (the weight and value
are one car's). A quantity ≥ 2 is believed only when the item's net weight
is at least MIN_KG_PER_CAR per unit; otherwise the item is one vehicle.

Fuel → columns (the NCM / HS 2017 subheading, i.e. what the importer declares
and customs accepts; HS 2017 split 87.03 by powertrain):

  8703.21–.24  spark ignition only            → PETROL (flex-fuel included)
  8703.31–.33  compression ignition only      → DIESEL
  8703.40      spark ignition + electric,
               not externally chargeable      → HEV  (full AND mild hybrids)
  8703.50      diesel + electric, not plug-in → HEV
  8703.60      spark ignition + electric,
               externally chargeable          → PHEV (range extenders included)
  8703.70      diesel + electric, plug-in     → PHEV
  8703.80      electric motor only            → BEV
  8703.90      other                          → OTHERS

Governance (every real run)
---------------------------
* the header must carry every column used; a missing one aborts;
* the downloaded size must equal Content-Length;
* a month is only taken once its file was generated after the month ended
  (Last-Modified ≥ the 1st of the next month) — never a partial month;
* any 87.03 subheading outside the map, and any import regime not known to
  be counted or excluded, is listed; above MAX_UNKNOWN_SHARE of Whole aborts;
* a month below MIN_MONTH_FRACTION of the trailing-12 median Whole is treated
  as a broken file and not written (--force overrides);
* fuels must sum to TOTAL for every row written.

Writes are line-level upserts keyed on (period, variant) (invariant 2); a row
whose `source` is not ours is never overwritten without --force.
Also writes market/paraguay_top.json (top BEV / PHEV / HEV brands and models,
trailing 12 months, Whole) through the month store market/paraguay_months.json
(scripts/market_top.py), so a normal run downloads only what it writes.

Usage
-----
    python scripts/fetch_paraguay.py                    # newest complete month
    python scripts/fetch_paraguay.py --period 2026-08
    python scripts/fetch_paraguay.py --backfill         # 2017-01 → now
    python scripts/fetch_paraguay.py --from-dir DIR     # offline

`--from-dir` reads <YYYY>_<MES>_Nivel_Item.csv[.gz] files from a local
directory (the tests use small excerpts in scripts/fixtures/paraguay/).
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
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import market_top  # noqa: E402

SOURCE = "DNIT customs import declarations (datosabiertos.aduana.gov.py)"
PORTAL = "https://datosabiertos.aduana.gov.py"
LIST_URL = PORTAL + "/ddaa/mainctrl/listaArchivos"
# First month of the HS 2017 nomenclature (powertrain subheadings 8703.40–.80).
FIRST_PERIOD = "2017-01"

VARIANT_CSV = {
    "Whole": "data/Paraguay.csv",
    "Used":  "data/Paraguay_Used.csv",
}
# Variants that are rendered into the gallery. Used is fetch-only: its CSV is
# kept up to date, but it is never passed to render-country.yml (owner
# decision 2026-10: BEV is ~0.03 % of used imports, the fit is flat, the chart
# says nothing). Mirror of DATA_ONLY_SERIES in R/build_backtest.R.
RENDERED_VARIANTS = ("Whole",)
USO_VARIANT = {"NUEVO": "Whole", "USADO": "Used"}

FUELS = ["BEV", "PHEV", "HEV", "PETROL", "DIESEL", "OTHERS"]
CSV_COLUMNS = (["period", "time_interval", "variant", "source"]
               + FUELS + ["TOTAL", "notes"])

# NCM subheading (first 7 characters of POSICION, "8703.80") -> column.
POSITION_FUEL = {
    "8703.21": "PETROL", "8703.22": "PETROL", "8703.23": "PETROL", "8703.24": "PETROL",
    "8703.31": "DIESEL", "8703.32": "DIESEL", "8703.33": "DIESEL",
    "8703.40": "HEV", "8703.50": "HEV",
    "8703.60": "PHEV", "8703.70": "PHEV",
    "8703.80": "BEV",
    "8703.90": "OTHERS",
}
NOT_CARS = frozenset({"8703.10"})   # snow vehicles, golf carts

# ── corrections of the declared tariff line ─────────────────────────────────
# The subheading is the importer's declaration. Within the ELECTRIFIED lines
# (BEV / PHEV / HEV) a few models are declared on the wrong one, and the
# description says so. Ordered, first match wins: (declared column(s), regex on
# the description, corrected column, reason). Petrol/diesel lines are never
# moved — a plug-in or hybrid word there is only listed in the run report.
RECLASS_RULES: list[tuple[frozenset, str, str, str]] = [
    (frozenset({"BEV"}), r"\bE-?POWER\b", "HEV",
     "Nissan e-POWER is a series hybrid with no plug (the petrol engine only "
     "charges the battery); declared on 8703.80 'electric motor only' because "
     "only the electric motor drives the wheels — HS 2017 puts it in 8703.40. "
     "X-Trail e-POWER, ~290 cars 2025-26."),
    (frozenset({"BEV", "HEV"}), r"\b(PHEV|REEV|EREV|DM-?[IP]|PLUG-?IN)|RANGE ?EXTEND|PHEV\d",
     "PHEV", "a plug-in or range extender named in the designation "
     "(Leapmotor C10 REEV on 8703.80; GWM New H6 PHEV, BMW X5 PHEV xDrive45e "
     "on 8703.40)"),
    (frozenset({"BEV"}), r"\b(HEV|HYBRID|HIBRIDO|H[IÍ]BRIDO)\b|AHEV\b", "HEV",
     "a non-plug-in hybrid named in the designation on 8703.80"),
]
_RECLASS = [(cols, re.compile(rx), to, why) for cols, rx, to, why in RECLASS_RULES]
# Plug-in / hybrid words on a petrol or diesel line: reported, not moved.
WATCH_RE = re.compile(r"\b(PHEV|REEV|EREV|HEV|HYBRID|H[IÍ]BRIDO|E-?POWER|DM-?I)\b")


def reclass(fuel: str, text: str) -> tuple[str, str] | None:
    """(corrected column, reason) if a correction rule matches, else None."""
    t = norm(text)
    for cols, rx, to, why in _RECLASS:
        if fuel in cols and to != fuel and rx.search(t):
            return to, why
    return None

# Customs regimes (DESTINACION, first characters) — see LISTADO_DE_DESTINACIONES
# on the portal. Counted: the car enters the Paraguayan market.
CONSUMPTION_REGIMES = (
    "IC",     # importación a consumo (IC04 with transport document, IC09 from a
              # bonded warehouse, IC20 advance OEA, IC07 temporary → definitive …)
    "ID",     # importación diplomática (but not IDA = into a bonded warehouse)
    "ZF2I",   # importación de zona franca (free zone → consumption)
)
# Not counted: the car is not (yet) in the market, or will be counted later.
EXCLUDED_REGIMES = (
    "IDA",    # ingreso a depósito aduanero — counted when it leaves (IC09)
    "ZF01",   # ingreso a zona franca — counted when it leaves (ZF2I)
    "IT",     # importación temporaria
    "IFC",    # importación de fracciones complementarias — not a definitive
              # regime in DNIT's own list (type "*"), and a fraction can repeat a
              # car of the main declaration (VIN JY43GGA0XPA051489: IC04 + IFC1,
              # 2025-03). ≤ 1.3 % of new cars a year (2026: 392, mostly GWM/Jetour).
    "IML",    # leasing (suspensive)
    "IR",     # reimportación
)

MIN_KG_PER_CAR = 600
# Bump when a counting rule changes: month caches (--cache-dir) of another
# version are not reused.
RULES_VERSION = 3
REQUIRED = ("OPERACION", "DESTINACION", "USO", "POSICION", "CANTIDAD ESTADISTICA",
            "KILO NETO", "MARCA ITEM", "MERCADERIA", "AÑO", "MES")

MESES = ["ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO", "JULIO", "AGOSTO",
         "SEPTIEMBRE", "OCTUBRE", "NOVIEMBRE", "DICIEMBRE"]
MES_NUM = {m: i for i, m in enumerate(MESES, start=1)}
MES_NUM["SETIEMBRE"] = 9

HTTP_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (compatible; LeRaffl-Gallery/1.0; "
                   "+https://leraffl.github.io/LeRaffl-Gallery/)"),
}
PARTS = 12
RANGE_TRIES = 9
MIN_MONTH_FRACTION = 0.25
WARN_MONTH_FRACTION = 0.5
MAX_UNKNOWN_SHARE = 0.02

REPO = Path(__file__).resolve().parent.parent
SLUG = "paraguay"
TOP_UNIT = ("new cars imported for consumption (brand = customs 'MARCA ITEM', "
            "aliases merged; model = the designation after MODELO in the "
            "declaration's free-text description, first words only — see "
            "model_of() in scripts/fetch_paraguay.py)")


# ── classification ─────────────────────────────────────────────────────────

def norm(s) -> str:
    return " ".join(str(s or "").split()).upper()


def num(s) -> float:
    """Customs numbers use a decimal comma and no thousands separator: '1435,0', ',0'."""
    s = str(s or "").strip().replace(".", "").replace(",", ".")
    try:
        return float(s) if s not in ("", ".") else 0.0
    except ValueError:
        return 0.0


def regime_counted(dest: str) -> bool | None:
    """True = counted, False = known and not counted, None = unknown."""
    d = norm(dest)
    if d.startswith(EXCLUDED_REGIMES):
        return False
    if d.startswith(CONSUMPTION_REGIMES):
        return True
    return None


def units_of(qty: float, kg: float) -> int:
    """Vehicles in one item (see 'Units' in the module docstring)."""
    q = int(round(qty))
    if q >= 2 and abs(qty - q) < 1e-6 and kg / q >= MIN_KG_PER_CAR:
        return q
    return 1


def subheading(pos: str) -> str:
    """'8703.80.00.000X' -> '8703.80' (also tolerates '87038000')."""
    p = re.sub(r"[^0-9]", "", pos or "")
    return f"{p[:4]}.{p[4:6]}" if len(p) >= 6 else ""


# ── display names for the top-brands/models table (not used for the data) ──

BRAND_ALIASES = {
    "GREATWALL": "GREAT WALL", "GWM": "GREAT WALL", "MERCEDES BENZ": "MERCEDES-BENZ",
    "LYNK CO": "LYNK & CO", "LYNK  CO": "LYNK & CO", "LYNK&CO": "LYNK & CO",
    "LAND-ROVER": "LAND ROVER", "LANDROVER": "LAND ROVER", "ROLLS ROYCE": "ROLLS-ROYCE",
    "M.G.": "MG", "B.M.W.": "BMW", "VW": "VOLKSWAGEN",
}
MODEL_RE = re.compile(r"\bMOD(?:ELO|\.)?\s*[:.\-]?\s*(.+)")
MODEL_STOP = re.compile(
    r"[,;(]|\s-\s|\b(A[ÑN¿?]O|ANIO|ANO|AÑO|AO|FABRICACION|CHASIS|CHASSI|VIN|COLOR|CON SUS|"
    r"CON ACCESORIOS|MOTOR|NUEVO|USADO|TIPO|VERSION|CILINDRADA|COMBUSTIBLE|PASAJEROS|"
    r"LUGARES|PUERTAS|ELECTRICO|HIBRIDO|\d{4}\b)")
MODEL_WORDS = 3


def display_brand(make: str) -> str:
    b = norm(make)
    return BRAND_ALIASES.get(b, BRAND_ALIASES.get(b.replace(" ", ""), b))


def model_of(brand: str, text: str) -> str:
    """Model designation from the free-text MERCADERIA, best effort:
    'UN AUTOMOVIL MARCA BYD MODELO: YUAN PLUS EV AÑO 2026' -> 'YUAN PLUS EV'.
    Descriptions without 'MODELO' that are short (GWM declares just
    'JOLION PRO HEV HIGH') are taken as the designation. Returns '' when
    nothing usable is found — the unit still counts for the brand."""
    t = norm(text).replace("¿", "Ñ")
    m = MODEL_RE.search(t)
    if m:
        cand = m.group(1)
    elif len(t.split()) <= 6:
        cand = t
    else:
        return ""
    cand = MODEL_STOP.split(cand, maxsplit=1)[0]
    for prefix in {norm(brand), display_brand(brand)}:
        cand = market_top.strip_brand(prefix, cand.strip())
    cand = re.sub(r"\b\d[.,]\d\b", " ", cand)            # engine size: "T7 PRO 1.5" → "T7 PRO"
    words = [w for w in re.sub(r"[^A-Z0-9+\-/ ]", " ", cand).split()][:MODEL_WORDS]
    return " ".join(words)


# ── aggregation ────────────────────────────────────────────────────────────

def empty_counts() -> dict[str, int]:
    return {k: 0 for k in FUELS + ["TOTAL"]}


class Aggregator:
    def __init__(self) -> None:
        self.counts: dict[str, dict[str, dict[str, int]]] = \
            collections.defaultdict(lambda: collections.defaultdict(empty_counts))
        self.units: collections.Counter = collections.Counter()      # (period, cls, brand, model)
        self.unknown_pos: collections.Counter = collections.Counter()  # (period, subheading, uso)
        self.unknown_regime: collections.Counter = collections.Counter()  # (period, dest)
        self.unknown_uso: collections.Counter = collections.Counter()  # (period, uso)
        self.excluded: collections.Counter = collections.Counter()   # (period, dest)
        self.regimes: collections.Counter = collections.Counter()    # (period, dest) counted
        self.qty_fixed: collections.Counter = collections.Counter()  # period -> items whose quantity was not believed
        self.items: collections.Counter = collections.Counter()      # period -> 87.03 import items
        self.exports: collections.Counter = collections.Counter()    # (period, uso) -> 87.03 export units
        self.reclassed: collections.Counter = collections.Counter()  # (period, variant, from, to, brand, model)
        self.ice_watch: collections.Counter = collections.Counter()  # (period, variant, fuel, brand, model)
        self.dup_vin: collections.Counter = collections.Counter()    # period -> repeated VINs skipped
        self.regime_brand: collections.Counter = collections.Counter()  # (period, regime, brand), regimes other than IC04
        # VIN -> [[period, regime, variant], ...] for counted single-car items
        # whose description quotes a chassis number: the double-count check.
        self.vins: dict[str, list] = collections.defaultdict(list)

    def merge(self, other: "Aggregator") -> None:
        for p, vs in other.counts.items():
            for v, c in vs.items():
                mine = self.counts[p][v]
                for k, n in c.items():
                    mine[k] += n
        for name in COUNTERS:
            getattr(self, name).update(getattr(other, name))
        for vin, where in other.vins.items():
            self.vins[vin].extend(where)

    def to_json(self) -> dict:
        return {"counts": {p: {v: dict(c) for v, c in vs.items()} for p, vs in self.counts.items()},
                **{name: [[list(k) if isinstance(k, tuple) else k, n]
                          for k, n in sorted(getattr(self, name).items())] for name in COUNTERS},
                "vins": dict(sorted(self.vins.items()))}

    @classmethod
    def from_json(cls, doc: dict) -> "Aggregator":
        a = cls()
        for p, vs in doc["counts"].items():
            for v, c in vs.items():
                a.counts[p][v].update(c)
        for name in COUNTERS:
            getattr(a, name).update({tuple(k) if isinstance(k, list) else k: n
                                     for k, n in doc.get(name, [])})
        for vin, where in doc.get("vins", {}).items():
            a.vins[vin].extend(where)
        return a

    def export(self, period: str, uso: str, pos: str, qty: str, kg: str) -> None:
        sub = subheading(pos)
        if sub.startswith("8703") and sub not in NOT_CARS:
            self.exports[(period, norm(uso))] += units_of(num(qty), num(kg))

    def add(self, period: str, dest: str, uso: str, pos: str, qty: str, kg: str,
            brand: str, text: str) -> None:
        sub = subheading(pos)
        if not sub.startswith("8703") or sub in NOT_CARS:
            return
        self.items[period] += 1
        counted = regime_counted(dest)
        d = norm(dest)
        n = units_of(num(qty), num(kg))
        if n == 1 and num(qty) >= 2:
            self.qty_fixed[period] += 1
        if counted is False:
            self.excluded[(period, d)] += n
            return
        if counted is None:
            self.unknown_regime[(period, d)] += n
            return
        variant = USO_VARIANT.get(norm(uso))
        if variant is None:
            self.unknown_uso[(period, norm(uso))] += n
            return
        fuel = POSITION_FUEL.get(sub)
        if fuel is None:
            self.unknown_pos[(period, sub, variant)] += n
            return
        self.regimes[(period, d)] += n
        if d != "IC04":
            self.regime_brand[(period, d, display_brand(brand))] += n
        vin = vin_of(text) if n == 1 else None
        if vin and any(w[0] == period and w[2] == variant for w in self.vins.get(vin, [])):
            # The same chassis twice in one month (7 cases in 2017-2026, all
            # within one declaration): one car.
            self.dup_vin[period] += 1
            return
        if vin:
            self.vins[vin].append([period, d, variant])
        fix = reclass(fuel, text)
        if fix:
            self.reclassed[(period, variant, fuel, fix[0], display_brand(brand),
                            model_of(brand, text))] += n
            fuel = fix[0]
        elif fuel in ("PETROL", "DIESEL") and WATCH_RE.search(norm(text)):
            self.ice_watch[(period, variant, fuel, display_brand(brand),
                            model_of(brand, text))] += n
        c = self.counts[period][variant]
        c[fuel] += n
        c["TOTAL"] += n
        if variant == "Whole":
            b = display_brand(brand)
            self.units[(period, fuel, b, model_of(brand, text) if fuel in
                        market_top.ELECTRIFIED else "")] += n


COUNTERS = ("units", "unknown_pos", "unknown_regime", "unknown_uso", "excluded",
            "regimes", "qty_fixed", "items", "exports", "regime_brand", "dup_vin", "reclassed", "ice_watch")
VIN_RE = re.compile(r"(?<![A-Z0-9])([A-HJ-NPR-Z0-9]{17})(?![A-Z0-9])")


def vin_of(text: str) -> str | None:
    """A 17-character VIN quoted in the description (letters I, O, Q never
    occur in one), if any — must mix letters and digits."""
    for m in VIN_RE.finditer(norm(text)):
        v = m.group(1)
        if re.search(r"\d", v) and re.search(r"[A-Z]", v):
            return v
    return None


def double_counts(agg: Aggregator) -> list[tuple[str, list]]:
    """VINs counted more than once (in any month / regime)."""
    return sorted((v, w) for v, w in agg.vins.items() if len(w) > 1)


def resolve_columns(header: list[str]) -> dict[str, int]:
    idx = {norm(h): i for i, h in enumerate(header)}
    missing = [c for c in REQUIRED if c not in idx]
    if missing:
        raise SystemExit(f"Schema drift: columns {missing} not in the header "
                         f"{[norm(h) for h in header]} — not writing.")
    return {c: idx[c] for c in REQUIRED}


def add_text(text: str, agg: Aggregator, expect: str | None = None) -> int:
    """Parse one month's item-level CSV; returns the number of rows read."""
    rd = csv.reader(io.StringIO(text))
    col = resolve_columns(next(rd))
    width = max(col.values())
    rows = 0
    for r in rd:
        if len(r) <= width:
            continue
        rows += 1
        op = r[col["OPERACION"]]
        if op not in ("IMPORTACION", "EXPORTACION") or not r[col["POSICION"]].startswith("8703"):
            continue
        mes = MES_NUM.get(norm(r[col["MES"]]))
        period = f"{r[col['AÑO']].strip()}-{mes:02d}" if mes else None
        if period is None or (expect and period != expect):
            raise SystemExit(f"Row for {r[col['AÑO']]}/{r[col['MES']]} in the file for "
                             f"{expect} — layout changed? Not writing.")
        if op == "EXPORTACION":
            agg.export(period, r[col["USO"]], r[col["POSICION"]],
                       r[col["CANTIDAD ESTADISTICA"]], r[col["KILO NETO"]])
            continue
        agg.add(period, r[col["DESTINACION"]], r[col["USO"]], r[col["POSICION"]],
                r[col["CANTIDAD ESTADISTICA"]], r[col["KILO NETO"]],
                r[col["MARCA ITEM"]], r[col["MERCADERIA"]])
    return rows


def decode(raw: bytes) -> str:
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return raw.decode("utf-8", errors="replace").lstrip("﻿")


# ── portal ─────────────────────────────────────────────────────────────────

def period_of_entry(year: str, mes: str) -> str | None:
    m = MES_NUM.get(norm(mes))
    return f"{int(year):04d}-{m:02d}" if m and str(year).isdigit() else None


def with_retries(fn, *args, tries: int = 6, **kw):
    """The portal drops connections now and then (RemoteDisconnected on a
    HEAD after 30 good months): retry with backoff before giving up."""
    for attempt in range(tries):
        try:
            return fn(*args, **kw)
        except requests.RequestException as e:
            if attempt == tries - 1:
                raise
            wait = 2 ** attempt * 5
            print(f"    {type(e).__name__}: {e} — retry in {wait}s")
            time.sleep(wait)


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HTTP_HEADERS)
    return s


def list_month_urls(session: requests.Session) -> dict[str, str]:
    """{period: URL of the item-level CSV} from the portal's own file list."""
    r = with_retries(session.get, LIST_URL, timeout=120)
    r.raise_for_status()
    out = {}
    for f in r.json():
        if f.get("ext") != "csv" or not str(f.get("fileName", "")).endswith("_Nivel_Item"):
            continue
        parts = f.get("separatePath") or []
        if len(parts) < 3:
            continue
        p = period_of_entry(parts[1], parts[2])
        if p:
            out[p] = f"{PORTAL}/{f['directory'].strip('/')}/{f['fileName']}.csv"
    return out


def month_end(period: str) -> dt.datetime:
    y, m = map(int, period.split("-"))
    y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return dt.datetime(y, m, 1, tzinfo=dt.timezone.utc)


def head(session: requests.Session, url: str) -> tuple[int, dt.datetime | None]:
    h = with_retries(session.head, url, timeout=120)
    h.raise_for_status()
    lm = h.headers.get("Last-Modified")
    return int(h.headers.get("Content-Length") or 0), (
        email.utils.parsedate_to_datetime(lm) if lm else None)


def download(session: requests.Session, url: str, size: int) -> bytes:
    """Fetch `url` as PARTS parallel byte ranges (the server is slow per
    connection); falls back to one plain GET if ranges are refused."""
    if size <= 0:
        r = with_retries(session.get, url, timeout=1800)
        r.raise_for_status()
        return r.content
    step = size // PARTS + 1

    def part(i: int) -> bytes:
        a, b = i * step, min(size - 1, (i + 1) * step - 1)
        last = None
        # The portal cuts a long transfer now and then (IncompleteRead in the
        # middle of a 20 MB range, 2026-10-02): retry the range, up to ~6 min.
        for attempt in range(RANGE_TRIES):
            try:
                r = session.get(url, headers={"Range": f"bytes={a}-{b}"}, timeout=300)
                if r.status_code == 206 and len(r.content) == b - a + 1:
                    return r.content
                last = f"HTTP {r.status_code}, {len(r.content)} bytes"
            except requests.RequestException as e:
                last = f"{type(e).__name__}: {e}"
            time.sleep(min(60, 3 * 2 ** attempt))
        raise RuntimeError(f"range {a}-{b} of {url} failed: {last}")

    with ThreadPoolExecutor(PARTS) as ex:
        data = b"".join(ex.map(part, range(PARTS)))
    if len(data) != size:
        raise RuntimeError(f"{url}: got {len(data):,} bytes, Content-Length {size:,}")
    return data


def list_dir_files(d: Path) -> dict[str, Path]:
    out = {}
    for f in sorted(d.iterdir()):
        m = re.match(r"(\d{4})_([A-Z]+)_Nivel_Item\.csv(\.gz)?$", f.name)
        if m and (p := period_of_entry(m.group(1), m.group(2))):
            out[p] = f
    return out


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
    return problems


def unknown_share(agg: Aggregator, period: str) -> tuple[int, float]:
    unk = (sum(n for (p, *_), n in agg.unknown_pos.items() if p == period)
           + sum(n for (p, _), n in agg.unknown_regime.items() if p == period)
           + sum(n for (p, _), n in agg.unknown_uso.items() if p == period))
    whole = agg.counts[period]["Whole"]["TOTAL"] or 1
    return unk, unk / whole


def store_months(agg: Aggregator, periods: list[str]) -> dict[str, tuple[dict, int]]:
    units = market_top.per_month({k: n for k, n in agg.units.items() if k[0] in periods})
    return {p: (units.get(p, {}), agg.counts[p]["Whole"]["TOTAL"]) for p in periods}


def report(agg: Aggregator, target: str, periods: list[str]) -> str:
    t = agg.counts[target]
    out = [f"## Paraguay (customs import declarations, DNIT open data) — {target}\n",
           "| variant | " + " | ".join(FUELS) + " | TOTAL | BEV share | electrified |",
           "|---|" + "---:|" * (len(FUELS) + 3)]
    for v in VARIANT_CSV:
        c = t[v]
        tot = c["TOTAL"] or 1
        out.append(f"| {v} | " + " | ".join(f"{c[k]:,}" for k in FUELS)
                   + f" | {c['TOTAL']:,} | {c['BEV'] / tot:.2%} | "
                   f"{(c['BEV'] + c['PHEV'] + c['HEV']) / tot:.1%} |")
    out.append(f"\nMonths processed: {periods[0]} → {periods[-1]} ({len(periods)})")
    reg = {d: n for (p, d), n in agg.regimes.items() if p == target}
    out.append("\n### Counted import regimes (units, both variants)\n")
    out.append(", ".join(f"`{d}` {n:,}" for d, n in sorted(reg.items())) or "—")
    ex = {d: n for (p, d), n in agg.excluded.items() if p == target}
    rc = collections.Counter()
    for (p, v, f, to, b, m), n in agg.reclassed.items():
        if p == target:
            rc[(v, f, to, b, m)] += n
    out.append("\n### Tariff line corrected by RECLASS_RULES this month (review)\n")
    out.append("\n".join(f"- {v}: {f} → {to}: {b} `{m or '?'}` × {n}" for (v, f, to, b, m), n
                         in sorted(rc.items(), key=lambda kv: -kv[1])) or "None.")
    iw = collections.Counter()
    for (p, v, f, b, m), n in agg.ice_watch.items():
        if p == target:
            iw[(v, f, b, m)] += n
    out.append("\n### Petrol/diesel lines whose description names a hybrid or plug-in "
               "(NOT moved — review; a correction belongs in RECLASS_RULES)\n")
    out.append("\n".join(f"- {v} {f}: {b} `{m or '?'}` × {n}" for (v, f, b, m), n
                         in sorted(iw.items(), key=lambda kv: -kv[1])[:25]) or "None.")
    dup = [(v, w) for v, w in double_counts(agg) if any(x[0] == target for x in w)]
    quoted = sum(1 for ws in agg.vins.values() for x in ws if x[0] == target)
    out.append(f"\n### Double-count check\n\n{quoted:,} counted cars quote a VIN this month; "
               f"{len(dup)} of them are counted more than once in the months read"
               + (": " + "; ".join(f"`{v}` {w}" for v, w in dup[:10]) if dup else "."))
    ex = {u: n for (p, u), n in agg.exports.items() if p == target}
    out.append("\n### Cars exported this month (NCM 87.03, not subtracted)\n")
    out.append(", ".join(f"{u} {n:,}" for u, n in sorted(ex.items())) or "None.")
    out.append("\n### Not counted (bonded warehouse / free-zone entries, temporary)\n")
    out.append(", ".join(f"`{d}` {n:,}" for d, n in sorted(ex.items())) or "None.")
    out.append(f"\nItems whose declared quantity was not believed (≥ 2 units but "
               f"< {MIN_KG_PER_CAR} kg per unit → counted as one car): "
               f"{agg.qty_fixed[target]:,} of {agg.items[target]:,} car items.")
    brands = collections.Counter()
    el = collections.Counter()
    for (p, cls, b, m), n in agg.units.items():
        if p == target:
            brands[b] += n
            if cls in ("BEV", "PHEV"):
                el[(cls, b, m)] += n
    out.append("\n### Top 10 brands, new cars\n")
    out.append(", ".join(f"{b} {n:,}" for b, n in brands.most_common(10)) or "—")
    out.append("\n### Plug-ins this month (BEV / PHEV by brand and model — review the tariff lines)\n")
    out.append("\n".join(f"- {cls}: {b} `{m or '?'}` × {n}" for (cls, b, m), n
                         in sorted(el.items(), key=lambda kv: (-kv[1], kv[0]))[:40]) or "None.")
    unk = ([f"- subheading `{s}` ({v}): {n:,}" for (p, s, v), n in agg.unknown_pos.items() if p == target]
           + [f"- regime `{d or '(blank)'}`: {n:,}" for (p, d), n in agg.unknown_regime.items() if p == target]
           + [f"- USO `{u or '(blank)'}`: {n:,}" for (p, u), n in agg.unknown_uso.items() if p == target])
    out.append("\n### Unknown subheadings / regimes / USO values this month (review!)\n")
    out.append("\n".join(unk) or "None.")
    return "\n".join(out) + "\n"


# ── main ───────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--variant", default="all",
                    help=f"all | {' | '.join(VARIANT_CSV)} (default: all)")
    ap.add_argument("--period", default="",
                    help="Target month YYYY-MM (default: newest complete month on the portal).")
    ap.add_argument("--backfill", action="store_true",
                    help=f"Re-derive every month from {FIRST_PERIOD}. Implied when a "
                         "CSV does not exist yet.")
    ap.add_argument("--force", action="store_true",
                    help="Ignore the self-throttle, the completeness guard and foreign "
                         "source strings.")
    ap.add_argument("--from-dir", default="",
                    help="Offline: read <YYYY>_<MES>_Nivel_Item.csv[.gz] files from here.")
    ap.add_argument("--cache-dir", default="",
                    help="Keep each parsed month here as JSON and reuse it on the next run "
                         "(resumes an interrupted backfill; delete the files to re-read).")
    ap.add_argument("--audit", default="",
                    help="Also write a per-month audit CSV (regime × USO × subheading units).")
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

    if args.from_dir:
        files = list_dir_files(Path(args.from_dir))
        complete = sorted(files)
        load = lambda p: decode(files[p].read_bytes())
    else:
        session = make_session()
        files = list_month_urls(session)
        if not files:
            sys.exit("No monthly files in the portal's file list — layout changed? Not writing.")
        # A month is complete once its file was generated after the month ended.
        newest = sorted(files)[-2:]
        complete = sorted(p for p in files if p not in newest)
        sizes: dict[str, int] = {}
        for p in newest:
            size, lm = head(session, files[p])
            sizes[p] = size
            if lm and lm >= month_end(p):
                complete.append(p)
            else:
                print(f"{p}: file generated {lm} — before the month ended; not used yet.")
        complete.sort()

        def load(p):
            size = sizes.get(p) or head(session, files[p])[0]
            t = time.time()
            raw = download(session, files[p], size)
            print(f"    downloaded {len(raw) / 1e6:.0f} MB in {time.time() - t:.0f}s")
            return decode(raw)
    published = [p for p in complete if p >= FIRST_PERIOD]
    if not published:
        sys.exit("No complete month on the portal — not writing.")
    print(f"Complete months on the portal: {published[0]} → {published[-1]} ({len(published)})")

    target = args.period or published[-1]
    if target not in published:
        print(f"{target} is not (completely) published yet (newest: {published[-1]}) "
              "— will retry on the next scheduled run.")
        return emit(args, set())

    if not backfill and not args.force and all(
            have[v].get(target, {}).get("source") == SOURCE for v in variants):
        print(f"{target} already fetched from {SOURCE} for {variants}; nothing to do.")
        return emit(args, set())

    if backfill:
        todo = [p for p in published if p <= target]
    else:
        # The newest month plus the one before it (late corrections land in the
        # file of the month they are made in, but the previous file has been
        # seen to be regenerated).
        todo = [p for p in published if p <= target][-2:]

    agg = Aggregator()
    cache = Path(args.cache_dir) if args.cache_dir else None
    for p in todo:
        hit = cache / f"{p}.v{RULES_VERSION}.json" if cache else None
        if hit and hit.exists():
            month = Aggregator.from_json(json.loads(hit.read_text(encoding="utf-8")))
            n = sum(month.items.values())
            print(f"  {p}: from cache {hit}")
        else:
            month = Aggregator()
            n = add_text(load(p), month, expect=p)
            if n == 0:
                sys.exit(f"{p}: file has no rows — broken upload, not writing.")
            if hit:
                hit.parent.mkdir(parents=True, exist_ok=True)
                hit.write_text(json.dumps(month.to_json(), ensure_ascii=False),
                               encoding="utf-8")
        agg.merge(month)
        w = agg.counts[p]
        print(f"  {p}: {n:,} rows, {agg.items[p]:,} car items → Whole "
              f"{w['Whole']['TOTAL']:,}, Used {w['Used']['TOTAL']:,}")

    periods = sorted(p for p in todo if p in agg.counts)
    if target not in periods:
        sys.exit(f"{target}: no car imports found — broken file? Not writing.")

    unk, share = unknown_share(agg, target)
    if share > MAX_UNKNOWN_SHARE and not args.force:
        sys.exit(f"{target}: {unk:,} car units with an unknown subheading / regime / USO "
                 f"({share:.1%} of Whole) — schema or nomenclature drift, not writing.\n"
                 + report(agg, target, periods))

    problems = check_sums(agg, periods)
    if problems:
        sys.exit("Consistency check failed:\n  " + "\n  ".join(problems[:20]))

    whole_total = agg.counts[target]["Whole"]["TOTAL"]
    frac = median_fraction(target, whole_total, have.get("Whole", {}))
    if not backfill and not args.force and frac is not None and frac < MIN_MONTH_FRACTION:
        print(f"{target}: Whole TOTAL {whole_total:,} is {frac:.0%} of the trailing "
              "median — looks like a broken file; not writing. --force if genuine.")
        return emit(args, set())
    if frac is not None and frac < WARN_MONTH_FRACTION:
        print(f"::warning title=Paraguay {target} unusually low::Whole TOTAL "
              f"{whole_total:,} = {frac:.0%} of the trailing-12 median — written; "
              "check it is a real drop and not a partial file.")

    changed: set[str] = set()
    for v in variants:
        updates = {(p, v): render_line(p, v, agg.counts[p][v])
                   for p in periods if agg.counts[p][v]["TOTAL"] > 0}
        stats = upsert_lines(paths[v], updates, args.force)
        print(f"{VARIANT_CSV[v]}: {stats}")
        if stats["added"] or stats["updated"]:
            changed.add(v)

    if "Whole" in variants:
        market_top.guarded(market_top.refresh_from_store, "Paraguay", SOURCE, TOP_UNIT,
                           SLUG, store_months(agg, periods))

    if args.audit:
        with open(args.audit, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["period", "kind", "key", "units"])
            for (p, d), n in sorted(agg.regimes.items()):
                w.writerow([p, "counted_regime", d, n])
            for (p, d), n in sorted(agg.excluded.items()):
                w.writerow([p, "excluded_regime", d, n])
            for (p, d), n in sorted(agg.unknown_regime.items()):
                w.writerow([p, "unknown_regime", d, n])
            for (p, s, v), n in sorted(agg.unknown_pos.items()):
                w.writerow([p, "unknown_subheading", f"{s}|{v}", n])
            for p in sorted(agg.items):
                w.writerow([p, "qty_not_believed", "", agg.qty_fixed[p]])
                w.writerow([p, "vins_quoted", "", sum(1 for ws in agg.vins.values()
                                                     for x in ws if x[0] == p)])
            for (p, d, b), n in sorted(agg.regime_brand.items()):
                w.writerow([p, f"regime_brand_{d}", b, n])
            for (p, v, f, to, b, m), n in sorted(agg.reclassed.items()):
                w.writerow([p, f"reclassed_{v}_{f}_to_{to}", f"{b}|{m}", n])
            for (p, v, f, b, m), n in sorted(agg.ice_watch.items()):
                w.writerow([p, f"ice_watch_{v}_{f}", f"{b}|{m}", n])
            for (p, u), n in sorted(agg.exports.items()):
                w.writerow([p, "export_units", u, n])
            for vin, where in double_counts(agg):
                w.writerow([where[0][0], "vin_counted_twice", vin, json.dumps(where)])
            brands = collections.Counter()
            for (p, cls, b, m), n in agg.units.items():
                if cls in ("BEV", "PHEV", "HEV"):
                    brands[(p, cls, b)] += n
            for (p, cls, b), n in sorted(brands.items()):
                w.writerow([p, f"brand_{cls}", b, n])

    rep = report(agg, target, periods)
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
