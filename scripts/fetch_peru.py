#!/usr/bin/env python3
"""
Fetch Peru registration data (SUNARP first registrations of new vehicles, as
compiled by the Asociación Automotriz del Perú) and upsert data/Peru*.csv
(Whole + Vans).

Source
------
Every new vehicle sold in Peru is first registered ("inmatriculado") with
SUNARP, the national public-registry authority. The Asociación Automotriz del
Perú (AAP — the national automotive association, OICA member) compiles those
registrations and publishes them, free and without login, as the public
Power BI report "BI-AAP":

    https://aap.org.pe/estadisticas/biaap        (the page embedding the report)

The report's data model is queryable through the same public Power BI API the
browser uses (`publish to web`, resource key in the embed URL — no account).
Its table `Base` holds one row per

    registration date × office × vehicle group/class/body × brand × model ×
    fuel (`Comb`, the registry's value) × AAP's powertrain class (`Elect`)

with a count `nTotal`, from 2019-01-02 on. AAP's printed monthly report
("Informe del Sector Automotor", aap.org.pe/estadisticas/informes-del-sector-
automotor) is built from the same data; its month-by-month table of new light
+ heavy vehicles is the cross-check (see Governance).

Discovery, never hard-coded: the embed URL is read from the BI-AAP page (the
`r=` parameter is base64 JSON with the resource key `k`); the API host comes
from the embed page's `resolvedClusterUri`; the model id from
`modelsAndExploration`. The constants below are only the fallback when the
page cannot be read.

Record → CSV
------------
AAP's vehicle groups: LIVIANOS (light), PESADOS (heavy), MENORES (motorcycles
and three-wheelers, from 2022, no fuel). Within LIVIANOS, class (`Clase`) and
body (`Carroceria`) give the EU class:

  Whole  data/Peru.csv       AUTOMOVIL, STATION WAGON, SUV/TODOTERRENOS,
                             CAMIONETAS with body MULTIPROPOSITO (MPVs)   (EU M1)
  Vans   data/Peru_Vans.csv  PICK UP Y FURGONETAS (pickups, chassis-cabs,
                             dropside, box vans), CAMIONETAS body PANEL    (EU N1)

Not in any variant: CAMIONETAS bodies MICROBUS (minibuses, M2), AMBULANCIA,
FUNERARIO, CASA RODANTE; all PESADOS (trucks, tractors, buses); all MENORES.

AAP reports these first registrations as sales of new vehicles. The table
has no new/used flag; used imports are legal only up to two model years old
(D.L. 843; used diesel light vehicles are banned outright, D.S. 005-2020-MTC),
so the series is new vehicles in all but a small near-new remainder.

Fuel → columns
--------------
AAP's `Elect` is the powertrain column — the registry's fuel value
harmonised across SUNARP's coding change of 2025 (before: ELECTRICO /
HIBRIDO; from 2025: BEV / PHEV / HEV / MHEV) and with the plug-in split AAP
makes for the old HIBRIDO code:

  BEV → BEV · PHEV → PHEV · HEV → HEV (full AND mild hybrids — see below)
  GASOLINA → PETROL · DIESEL → DIESEL
  GNV, BI-GNV, DUAL GNV → CNG · GLP, BI-GLP, DUAL GLP → LPG
  GNL, BI-GNL, DUAL GNL (LNG), "-" (not stated) → OTHERS

Mild hybrids: before 2025 the registry's HIBRIDO lumped full and mild
hybrids together (Suzuki, Mercedes, Audi 48 V systems), and AAP's `Elect`
keeps them in HEV throughout. HEV is therefore full + mild for the whole
series; there is no MHEV column. From 2025 the registry separates them (`Comb`
= MHEV), which the top-brands/models table uses.

When a month is complete — the rows are dated by registration day, but AAP
reloads the model irregularly (2026-09-02 for the last one), and the newest
month of each reload is a preliminary cut (2026-08 stopped at the 22nd) with
no powertrain class. A month is written only when all three hold:
  1. it is strictly before the month of the model's last refresh (a reload on
     the 2nd can never yield that month);
  2. AAP has classified it (no light vehicle with an empty `Elect`);
  3. AAP's printed monthly report has it and agrees on the month's total
     (the report's totals are never revised once printed — five editions
     compared — so a match proves the month is complete).
A month that passes 1–2 but not yet 3 is held back and written once the
report appears.

Revisions — AAP re-classifies the powertrain split of earlier months in
BI-AAP after the fact (compared with the printed reports: up to ~25 PHEVs a
month moved to BEV/HEV, as far back as 2024), while month totals stay fixed.
Every real run therefore re-reads the WHOLE history, and every new BI-AAP
refresh triggers a real run (the refresh stamp processed last is kept in
market/peru_top.json as `source_refreshed`). Changed rows are listed in the
step summary.

Governance (every real run)
---------------------------
* the model must still have table `Base` with every column used (schema
  drift aborts);
* every month query must come back complete (the API's `IC` flag) and the
  detailed rows must add up to an independent aggregate query of the same
  month (a decoding or truncation error aborts);
* unknown fuel values above 2 % of the month's Whole abort; unknown classes /
  bodies are listed; a LIVIANOS class that maps to no variant above 1 %
  aborts;
* a month below 40 % of the trailing-12 median Whole is not written
  (--force overrides);
* cross-check: new light + heavy vehicles per month must match the
  "Evolución mensual" table of AAP's newest printed report (±2 units or
  0.5 %); a real mismatch aborts (--force overrides). An unreachable or
  unparsable report is a warning — no new month is written then, only
  revisions of months already in the CSVs;
* fuels sum to TOTAL for every row written.

Writes are line-level upserts keyed on (period, variant) (invariant 2); a row
whose `source` is not ours is never overwritten without --force.
Also writes market/peru_top.json (top BEV / PHEV / HEV / MHEV brands and
models, trailing 12 months, Whole) via scripts/market_top.py.

Usage
-----
    python scripts/fetch_peru.py                    # newest confirmed month
    python scripts/fetch_peru.py --period 2026-07
    python scripts/fetch_peru.py --backfill         # 2019-01 → now
    python scripts/fetch_peru.py --from-json DUMP [--report-pdf FILE]  # offline
    python scripts/fetch_peru.py --backfill --dump-json DUMP            # save raw

`--from-json` reads month rows saved by `--dump-json` (the exact query
result, one list per month) instead of calling the API; used by the tests and
for offline rebuilds.
"""

from __future__ import annotations

import argparse
import base64
import collections
import csv
import datetime as dt
import io
import json
import os
import re
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import market_top  # noqa: E402

SOURCE = "SUNARP via AAP (BI-AAP)"
FIRST_PERIOD = "2019-01"          # first month in the BI-AAP model

BIAAP_PAGE = "https://aap.org.pe/estadisticas/biaap"
REPORTS_PAGE = "https://aap.org.pe/estadisticas/informes-del-sector-automotor"
# Fallback only — discovered from BIAAP_PAGE on every run.
FALLBACK_RESOURCE_KEY = "d5e6cab8-73a3-48c7-87e7-f93e349c261f"
FALLBACK_API = "https://wabi-south-central-us-api.analysis.windows.net"

ENTITY = "Base"
DIMS = ["Grupo", "Clase", "Carroceria", "Comb", "Elect", "Marca", "Modelo"]
REQUIRED_PROPS = set(DIMS) | {"Fecha", "nTotal"}

VARIANT_CSV = {
    "Whole": "data/Peru.csv",
    "Vans":  "data/Peru_Vans.csv",
}
RENDERED_VARIANTS = tuple(VARIANT_CSV)

FUELS = ["BEV", "PHEV", "HEV", "PETROL", "DIESEL", "CNG", "LPG", "OTHERS"]
CSV_COLUMNS = (["period", "time_interval", "variant", "source"]
               + FUELS + ["TOTAL", "notes"])

# ── scope ──────────────────────────────────────────────────────────────────

GROUP_LIGHT = "LIVIANOS"
KNOWN_GROUPS = frozenset({"LIVIANOS", "PESADOS", "MENORES"})
M1_CLASSES = frozenset({"AUTOMOVIL", "STATION WAGON", "SUV,TODOTERRENOS"})
N1_CLASSES = frozenset({"PICK UP Y FURGONETAS"})
MIXED_CLASS = "CAMIONETAS"                 # split by body
MIXED_M1_BODIES = frozenset({"MULTIPROPOSITO"})
MIXED_N1_BODIES = frozenset({"PANEL"})
# CAMIONETAS bodies deliberately in no variant (M2 minibuses, special purpose).
MIXED_EXCLUDED_BODIES = frozenset({"MICROBUS", "AMBULANCIA", "FUNERARIO", "CASA RODANTE"})

FUEL_MAP = {
    "BEV": "BEV", "PHEV": "PHEV", "HEV": "HEV",
    "GASOLINA": "PETROL", "DIESEL": "DIESEL",
    "GNV": "CNG", "BI-GNV": "CNG", "DUAL GNV": "CNG",
    "GLP": "LPG", "BI-GLP": "LPG", "DUAL GLP": "LPG",
    "GNL": "OTHERS", "BI-GNL": "OTHERS", "DUAL GNL": "OTHERS",
    "-": "OTHERS",
}
# `Elect` values that mean "not classified yet" (the preliminary month).
UNCLASSIFIED = frozenset({"", "(EN BLANCO)", "#N/D"})

MIN_MONTH_FRACTION = 0.40
MAX_UNKNOWN_FUEL_SHARE = 0.02
MAX_UNMAPPED_CLASS_SHARE = 0.01
XCHECK_ABS_TOL = 2
XCHECK_REL_TOL = 0.005
MAX_ROWS = 30000                  # the API's window per query

HTTP_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (compatible; LeRaffl-Gallery/1.0; "
                   "+https://leraffl.github.io/LeRaffl-Gallery/)"),
}

REPO = Path(__file__).resolve().parent.parent
TOP_PATH = market_top.MARKET_DIR / "peru_top.json"
TOP_UNIT = ("first registrations of new vehicles (SUNARP, compiled by AAP; brand = "
            "'Marca', model = the registry's 'Modelo' with the brand prefix removed — "
            "some imports are registered under a type-approval code rather than a "
            "commercial name). HEV = full hybrids, MHEV = mild hybrids, as the registry "
            "has coded them since 2025")


def norm(s) -> str:
    return " ".join(str(s if s is not None else "").split()).upper()


def variant_for(group: str, vclass: str, body: str) -> str | None:
    g, c, b = norm(group), norm(vclass), norm(body)
    if g != GROUP_LIGHT:
        return None
    if c in M1_CLASSES:
        return "Whole"
    if c in N1_CLASSES:
        return "Vans"
    if c == MIXED_CLASS:
        if b in MIXED_M1_BODIES:
            return "Whole"
        if b in MIXED_N1_BODIES:
            return "Vans"
    return None


def fuel_class(elect: str) -> str | None:
    """Gallery column for AAP's powertrain value; None if unknown."""
    return FUEL_MAP.get(norm(elect))


def market_class(elect: str, comb: str) -> str | None:
    """Class for the top-brands/models table: HEV split into HEV / MHEV where
    the registry codes it (2025 →)."""
    col = fuel_class(elect)
    if col == "HEV" and norm(comb) == "MHEV":
        return "MHEV"
    return col


def is_unclassified(elect) -> bool:
    return elect is None or norm(elect) in UNCLASSIFIED


# ── display names for the top-brands/models table (not used for the data) ──

# Registry spellings of one brand, merged for the ranking only.
BRAND_ALIASES = {
    "MERCEDES BENZ": "MERCEDES-BENZ",
    "BIYADI": "BYD",                       # pinyin of 比亚迪, on a few imports
    "CHANA": "CHANGAN",                    # Changan's former export name
    "WULING BAOJUN": "BAOJUN", "WULING BAOJUN YEP": "BAOJUN",
    "G.A.P.": "GAP", "KINGONE": "KING ONE",
}


def display_brand(make: str) -> str:
    b = market_top.clean(make)
    return BRAND_ALIASES.get(b, b)


def display_model(make: str, model: str) -> str:
    raw_make = market_top.clean(make)
    m = market_top.clean(model)
    for prefix in {raw_make, display_brand(make)}:
        m = market_top.strip_brand(prefix, m)
    return m or market_top.clean(model)


# ── Power BI public API ────────────────────────────────────────────────────

class Api:
    """The public ("publish to web") Power BI endpoints the embed page uses."""

    def __init__(self, session: requests.Session) -> None:
        self.s = session
        self.key, self.host = self.discover()
        self.model_id: int | None = None
        self.refreshed: dt.datetime | None = None

    def discover(self) -> tuple[str, str]:
        key, host = FALLBACK_RESOURCE_KEY, FALLBACK_API
        try:
            r = self.s.get(BIAAP_PAGE, timeout=60)
            r.raise_for_status()
            m = re.search(r"https://app\.powerbi\.com/view\?r=([A-Za-z0-9_\-=%]+)", r.text)
            if not m:
                raise ValueError("no app.powerbi.com/view link on the BI-AAP page")
            token = requests.utils.unquote(m.group(1))
            info = json.loads(base64.b64decode(token + "=" * (-len(token) % 4)))
            key = info["k"]
            r = self.s.get(m.group(0), timeout=60)
            r.raise_for_status()
            c = re.search(r"resolvedClusterUri\s*=\s*'([^']+)'", r.text)
            if c:
                host = c.group(1).rstrip("/").replace("-redirect.", "-api.")
            if key != FALLBACK_RESOURCE_KEY:
                print(f"::notice title=BI-AAP report key changed::{key} "
                      f"(fallback {FALLBACK_RESOURCE_KEY}) — update FALLBACK_RESOURCE_KEY")
        except Exception as e:  # noqa: BLE001 — the constants are the fallback
            print(f"::warning title=BI-AAP discovery failed, using fallback::"
                  f"{type(e).__name__}: {e}")
        return key, host

    def headers(self) -> dict:
        return {"X-PowerBI-ResourceKey": self.key, "Content-Type": "application/json"}

    def post(self, path: str, body: dict) -> dict:
        for attempt in range(4):
            try:
                r = self.s.post(f"{self.host}{path}", headers=self.headers(),
                                data=json.dumps(body), timeout=180)
                if r.status_code in (429, 500, 502, 503, 504):
                    raise requests.HTTPError(f"HTTP {r.status_code}")
                r.raise_for_status()
                return r.json()
            except (requests.ConnectionError, requests.Timeout, requests.HTTPError) as e:
                if attempt == 3:
                    raise
                print(f"  retry {path} after {type(e).__name__}: {e}")
                time.sleep(5 * (attempt + 1))
        raise AssertionError("unreachable")

    def load_model(self) -> None:
        r = self.s.get(f"{self.host}/public/reports/{self.key}/modelsAndExploration"
                       "?preferReadOnlySession=true", headers=self.headers(), timeout=120)
        r.raise_for_status()
        model = r.json()["models"][0]
        self.model_id = int(model["id"])
        stamp = model.get("LastRefreshTime") or ""
        try:
            self.refreshed = dt.datetime.fromisoformat(stamp[:19])
        except ValueError:
            self.refreshed = None
        schema = self.post("/public/reports/conceptualschema",
                           {"ModelIds": [self.model_id], "UserPreferredLocale": "es-ES"})
        props = set()
        for sch in schema.get("schemas", []):
            for ent in sch["schema"]["Entities"]:
                if ent["Name"] == ENTITY:
                    props = {p["Name"] for p in ent.get("Properties", [])}
        missing = sorted(REQUIRED_PROPS - props)
        if missing:
            raise SystemExit(f"schema drift: table {ENTITY!r} lacks {missing} "
                             f"(has {sorted(props)}) — not writing.")

    def query(self, dims: list[str], period: str) -> list[list]:
        """Rows [dim values..., nTotal] of table Base for one month."""
        body = build_query(dims, period, self.model_id)
        return decode_dsr(self.post("/public/reports/querydata?synchronous=true", body),
                          len(dims) + 1)


def month_bounds(period: str) -> tuple[str, str]:
    y, m = map(int, period.split("-"))
    y2, m2 = (y + 1, 1) if m == 12 else (y, m + 1)
    return f"{y:04d}-{m:02d}-01T00:00:00", f"{y2:04d}-{m2:02d}-01T00:00:00"


def build_query(dims: list[str], period: str, model_id: int | None) -> dict:
    def col(p):
        return {"Column": {"Expression": {"SourceRef": {"Source": "b"}}, "Property": p}}
    select = [{**col(d), "Name": f"{ENTITY}.{d}"} for d in dims]
    select.append({"Aggregation": {"Expression": col("nTotal"), "Function": 0},
                   "Name": f"Sum({ENTITY}.nTotal)"})
    lo, hi = month_bounds(period)
    where = [{"Condition": {"And": {
        "Left": {"Comparison": {"ComparisonKind": 2, "Left": col("Fecha"),
                                "Right": {"Literal": {"Value": f"datetime'{lo}'"}}}},
        "Right": {"Comparison": {"ComparisonKind": 3, "Left": col("Fecha"),
                                 "Right": {"Literal": {"Value": f"datetime'{hi}'"}}}}}}}]
    q = {"Version": 2, "From": [{"Name": "b", "Entity": ENTITY, "Type": 0}],
         "Select": select, "Where": where}
    return {"version": "1.0.0", "queries": [{"Query": {"Commands": [
        {"SemanticQueryDataShapeCommand": {
            "Query": q,
            "Binding": {"Primary": {"Groupings": [{"Projections": list(range(len(select)))}]},
                        "DataReduction": {"DataVolume": 4,
                                          "Primary": {"Window": {"Count": MAX_ROWS}}},
                        "Version": 1},
            "ExecutionMetricsKind": 1}}]}}],
        "cancelQueries": [], "modelId": model_id}


def decode_dsr(js: dict, ncols: int) -> list[list]:
    """Decode Power BI's compressed data-shape result into plain rows.

    Each row carries only the values that changed: bit i of `R` = column i
    repeats the previous row's value, bit i of `Ø` = column i is null; `C`
    holds the remaining values in column order. Columns with a `DN` in the
    schema are indexes into `ValueDicts[DN]`."""
    data = js["results"][0]["result"]["data"]
    dsr = data["dsr"]
    if "DataShapes" in dsr and dsr["DataShapes"] and "odata.error" in dsr["DataShapes"][0]:
        raise SystemExit(f"query error: {dsr['DataShapes'][0]['odata.error']}")
    ds = dsr["DS"][0]
    if ds.get("IC") is False or "RT" in ds:
        raise SystemExit(f"query result incomplete (more than {MAX_ROWS:,} rows?) — not writing.")
    dicts = ds.get("ValueDicts", {})
    rows_raw = ds["PH"][0].get("DM0", []) if ds.get("PH") else []
    schema = None
    out, prev = [], [None] * ncols
    for r in rows_raw:
        if "S" in r:
            schema = r["S"]
        vals, ci = [], 0
        rep, nul, c = r.get("R", 0), r.get("Ø", 0), r.get("C", [])
        for i in range(ncols):
            if rep >> i & 1:
                v = prev[i]
            elif nul >> i & 1:
                v = None
            else:
                v = c[ci]
                ci += 1
                dn = schema[i].get("DN") if schema else None
                if dn is not None and isinstance(v, int):
                    v = dicts[dn][v]
            vals.append(v)
        prev = vals
        out.append(vals)
    return out


# ── aggregation ────────────────────────────────────────────────────────────

def empty_counts() -> dict[str, int]:
    return {k: 0 for k in FUELS + ["TOTAL"]}


class Aggregator:
    def __init__(self) -> None:
        self.counts: dict[str, dict[str, dict[str, int]]] = \
            collections.defaultdict(lambda: collections.defaultdict(empty_counts))
        self.units: collections.Counter = collections.Counter()           # (period, class, brand, model), Whole
        self.unknown_fuel: collections.Counter = collections.Counter()    # (period, variant, value)
        self.unknown_group: collections.Counter = collections.Counter()   # (period, group)
        self.unmapped: collections.Counter = collections.Counter()        # (period, class, body) LIVIANOS in no variant, unexpected
        self.excluded: collections.Counter = collections.Counter()        # (period, class, body) deliberately out
        self.unclassified: collections.Counter = collections.Counter()    # period -> LIVIANOS units without Elect
        self.light: collections.Counter = collections.Counter()           # period -> LIVIANOS units
        self.light_heavy: collections.Counter = collections.Counter()     # period -> LIVIANOS + PESADOS (cross-check)
        self.rows: collections.Counter = collections.Counter()            # period -> units

    def add(self, period: str, group, vclass, body, comb, elect, make, model, n) -> None:
        n = int(n or 0)
        if not n:
            return
        g = norm(group)
        self.rows[period] += n
        if g not in KNOWN_GROUPS:
            self.unknown_group[(period, g)] += n
        if g in ("LIVIANOS", "PESADOS"):
            self.light_heavy[period] += n
        if g != GROUP_LIGHT:
            return
        self.light[period] += n
        if is_unclassified(elect):
            self.unclassified[period] += n
        v = variant_for(group, vclass, body)
        if v is None:
            key = (period, norm(vclass), norm(body))
            if norm(vclass) == MIXED_CLASS and norm(body) in MIXED_EXCLUDED_BODIES:
                self.excluded[key] += n
            else:
                self.unmapped[key] += n
            return
        col = fuel_class(elect)
        if col is None:
            self.unknown_fuel[(period, v, norm(elect))] += n
            col = "OTHERS"
        c = self.counts[period][v]
        c[col] += n
        c["TOTAL"] += n
        if v == "Whole":
            self.units[(period, market_class(elect, comb) or "OTHERS",
                        display_brand(make), display_model(make, model))] += n

    def add_rows(self, period: str, rows: list[list]) -> None:
        for r in rows:
            self.add(period, *r)


def month_totals(rows: list[list]) -> collections.Counter:
    """(group, elect) -> units, from detailed rows (for the self-check)."""
    out = collections.Counter()
    for r in rows:
        out[(norm(r[0]), "" if is_unclassified(r[4]) else norm(r[4]))] += int(r[-1] or 0)
    return out


# ── cross-check against AAP's printed monthly report ───────────────────────

MONTHS_ES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "set", "oct", "nov", "dic"]


def parse_report_table(text: str) -> dict[str, int]:
    """New light + heavy vehicles per month from the "Evolución mensual" page
    of AAP's report: rows "YYYY m1 m2 … [total-to-date [annual]]"."""
    out: dict[str, int] = {}
    for line in text.splitlines():
        m = re.match(r"^\s*(20\d\d)\s+((?:[\d,]+|-)(?:\s+(?:[\d,]+|-))*)\s*$", line)
        if not m:
            continue
        year = int(m.group(1))
        toks = m.group(2).split()
        if len(toks) == 14:              # 12 months + to-date + annual
            months = toks[:12]
        elif 2 <= len(toks) <= 12:       # current year: k months + to-date
            months = toks[:-1]
        else:
            continue
        for i, t in enumerate(months, start=1):
            out[f"{year}-{i:02d}"] = 0 if t == "-" else int(t.replace(",", ""))
    return out


def report_table_from_pdf(pdf_bytes: bytes) -> dict[str, int]:
    import pdfplumber  # only needed for the cross-check
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages[:15]:
            t = page.extract_text() or ""
            if "Evolución mensual" in t and "livianos y pesados" in t:
                return parse_report_table(t)
    raise ValueError("no 'Evolución mensual' page for livianos y pesados in the report")


def latest_report_url(session: requests.Session) -> str:
    r = session.get(REPORTS_PAGE, timeout=60)
    r.raise_for_status()
    links = re.findall(r'https://aap\.org\.pe/storage/estadisticas/informes-mensuales/[^"\s]+\.pdf',
                       r.text)
    if not links:
        raise ValueError("no monthly report link on the reports page")
    return links[0]                       # the page lists the newest first


def within_tolerance(a: int, b: int) -> bool:
    return abs(a - b) <= max(XCHECK_ABS_TOL, XCHECK_REL_TOL * max(a, b))


def cross_check(agg: Aggregator, periods: list[str],
                table: dict[str, int]) -> tuple[list[str], list[str], list[str]]:
    compared, small, problems = [], [], []
    for p in periods:
        if p not in table:
            continue
        compared.append(p)
        got, want = agg.light_heavy[p], table[p]
        if got == want:
            continue
        msg = f"{p} new light + heavy vehicles: BI-AAP {got:,} vs report {want:,}"
        (small if within_tolerance(got, want) else problems).append(msg)
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

def median_fraction(period: str, total: int, have: dict[str, dict]) -> float | None:
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


def build_top(agg: Aggregator, target: str) -> dict:
    window = set(market_top.month_window(target))
    units = market_top.per_month({k: n for k, n in agg.units.items() if k[0] in window})
    monthly = {p: (units.get(p, {}), agg.counts[p]["Whole"]["TOTAL"])
               for p in window if p in agg.counts and agg.counts[p]["Whole"]["TOTAL"]}
    return market_top.build_top_monthly("Peru", SOURCE, target, monthly, TOP_UNIT)


def report(agg: Aggregator, target: str, periods: list[str], xcheck: str,
           refreshed: str) -> str:
    t = agg.counts[target]
    out = [f"## Peru (SUNARP first registrations via BI-AAP) — {target}\n",
           f"BI-AAP model last refreshed: {refreshed}\n",
           "| variant | " + " | ".join(FUELS) + " | TOTAL | BEV share | PHEV share |",
           "|---|" + "---:|" * (len(FUELS) + 3)]
    for v in VARIANT_CSV:
        c = t[v]
        tot = c["TOTAL"] or 1
        out.append(f"| {v} | " + " | ".join(f"{c[k]:,}" for k in FUELS)
                   + f" | {c['TOTAL']:,} | {c['BEV'] / tot:.2%} | {c['PHEV'] / tot:.2%} |")
    out.append(f"\nMonths processed: {periods[0]} → {periods[-1]} ({len(periods)})")
    out.append(f"\n### Cross-check against AAP's printed monthly report\n\n{xcheck}")
    for cls in ("BEV", "PHEV"):
        brands = collections.Counter()
        for (p, c, b, m), n in agg.units.items():
            if p == target and c == cls:
                brands[b] += n
        out.append(f"\n### {cls} brands this month (Whole)\n")
        out.append(", ".join(f"{b} {n:,}" for b, n in brands.most_common(12)) or "—")
    unk = {k: n for k, n in agg.unknown_fuel.items() if k[0] == target}
    out.append("\n### Unknown powertrain values this month (counted as OTHERS)\n")
    out.append("\n".join(f"- {v}: `{f or '(blank)'}` × {n:,}" for (_, v, f), n in unk.items())
               or "None.")
    um = {k: n for k, n in agg.unmapped.items() if k[0] == target}
    ug = {k: n for k, n in agg.unknown_group.items() if k[0] == target}
    out.append("\n### Light-vehicle classes / bodies in no variant, unexpected (review!)\n")
    out.append("\n".join([f"- `{c}` / `{b or '(blank)'}`: {n:,}" for (_, c, b), n in um.items()]
                         + [f"- unknown group `{g}`: {n:,}" for (_, g), n in ug.items()])
               or "None.")
    ex = {k: n for k, n in agg.excluded.items() if k[0] == target}
    out.append("\n### Excluded on purpose (CAMIONETAS minibuses / special bodies)\n")
    out.append(", ".join(f"{b}: {n:,}" for (_, c, b), n in sorted(ex.items())) or "None.")
    return "\n".join(out) + "\n"


# ── month selection ────────────────────────────────────────────────────────

def months_between(a: str, b: str) -> list[str]:
    out = []
    y, m = int(a[:4]), int(a[5:7])
    while f"{y}-{m:02d}" <= b:
        out.append(f"{y}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def prev_month(p: str) -> str:
    y, m = int(p[:4]), int(p[5:7])
    return f"{y - 1}-12" if m == 1 else f"{y}-{m - 1:02d}"


def newest_final_month(is_final, refreshed: dt.datetime | None,
                       today: dt.date | None = None) -> str | None:
    """Newest month strictly before the refresh month that AAP has
    classified. `is_final(period)` → bool."""
    ref = refreshed.date() if refreshed else (today or dt.date.today())
    p = prev_month(f"{ref.year}-{ref.month:02d}")
    for _ in range(4):
        if p < FIRST_PERIOD:
            return None
        if is_final(p):
            return p
        p = prev_month(p)
    return None


# ── main ───────────────────────────────────────────────────────────────────

def load_report(session: requests.Session, args) -> tuple[dict[str, int] | None, str]:
    """AAP's printed report table (period -> new light + heavy vehicles) and
    where it came from; (None, reason) when it cannot be had."""
    try:
        if args.report_pdf:
            return (report_table_from_pdf(Path(args.report_pdf).read_bytes()),
                    Path(args.report_pdf).name)
        if args.from_json:
            return None, "offline run without --report-pdf"
        url = latest_report_url(session)
        r = session.get(url, timeout=180)
        r.raise_for_status()
        return report_table_from_pdf(r.content), url.rsplit("/", 1)[-1]
    except Exception as e:  # noqa: BLE001 — reported by the caller
        return None, f"{type(e).__name__}: {e}"


def stored_refresh() -> str:
    """BI-AAP refresh stamp the last full run processed (kept in the top file)."""
    try:
        return json.loads(TOP_PATH.read_text(encoding="utf-8")).get("source_refreshed") or ""
    except (OSError, ValueError):
        return ""


def revisions(path: Path, updates: dict[tuple[str, str], str]) -> list[str]:
    """Human-readable list of existing rows that `updates` would change."""
    _, lines = read_csv_lines(path)
    old = {line_key(l): l for l in lines}
    out = []
    for key, new in sorted(updates.items()):
        if key not in old or old[key] == new:
            continue
        a = dict(zip(CSV_COLUMNS, next(csv.reader([old[key]]))))
        b = dict(zip(CSV_COLUMNS, next(csv.reader([new]))))
        diffs = []
        for c in FUELS + ["TOTAL"]:
            if a.get(c) != b.get(c):
                fa = float(a[c]) if a.get(c) else 0.0
                diffs.append(f"{c} {fa:g}→{float(b[c]):g}")
        if a.get("source") != b.get("source"):
            diffs.append(f"source `{a.get('source')}`→`{b.get('source')}`")
        out.append(f"{key[0]} {key[1]}: " + ", ".join(diffs))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--variant", default="all",
                    help=f"all | {' | '.join(VARIANT_CSV)} (default: all)")
    ap.add_argument("--period", default="",
                    help="Newest month to write, YYYY-MM (default: newest confirmed month).")
    ap.add_argument("--backfill", action="store_true",
                    help="Ignore the self-throttle and re-derive every month from "
                         f"{FIRST_PERIOD} (a real run always re-reads the whole history; "
                         "this only forces one).")
    ap.add_argument("--force", action="store_true",
                    help="Ignore the self-throttle, the report confirmation, the "
                         "completeness and cross-check guards, and foreign source strings.")
    ap.add_argument("--from-json", default="",
                    help="Offline: month rows saved by --dump-json.")
    ap.add_argument("--dump-json", default="",
                    help="Save the month rows read from the API to this file.")
    ap.add_argument("--report-pdf", default="",
                    help="Offline: AAP monthly report PDF (month confirmation + cross-check).")
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

    session = requests.Session()
    session.headers.update(HTTP_HEADERS)
    api = None
    if args.from_json:
        dump = json.loads(Path(args.from_json).read_text(encoding="utf-8"))
        months = dump["months"]
        refreshed_s = dump.get("refreshed") or ""
        refreshed = dt.datetime.fromisoformat(refreshed_s) if refreshed_s else None

        def load(p):
            if p not in months:
                raise SystemExit(f"{p} not in {args.from_json}")
            return months[p]

        def aggregate(p):
            # A month the dump does not hold counts as not published (yet).
            return month_totals(months[p]) if p in months else collections.Counter()
    else:
        api = Api(session)
        api.load_model()
        refreshed = api.refreshed
        refreshed_s = refreshed.isoformat() if refreshed else ""
        months = {}

        def load(p):
            if p not in months:
                months[p] = api.query(DIMS, p)
            return months[p]

        def aggregate(p):
            rows = api.query(["Grupo", "Elect"], p)
            out = collections.Counter()
            for g, e, n in rows:
                out[(norm(g), "" if is_unclassified(e) else norm(e))] += int(n or 0)
            return out
    print(f"BI-AAP model last refreshed: {refreshed_s or 'unknown'}")

    def classified(p: str) -> bool:
        tot = aggregate(p)
        light = sum(n for (g, e), n in tot.items() if g == GROUP_LIGHT)
        pending = sum(n for (g, e), n in tot.items() if g == GROUP_LIGHT and e == "")
        return light > 0 and pending == 0

    # Step 1 — the newest month BI-AAP could hold complete: strictly before
    # the refresh month (a refresh on the 2nd must never yield "September")
    # and fully classified (the preliminary month is cut mid-month and has no
    # powertrain class).
    newest = newest_final_month(classified, refreshed)
    if newest is None:
        sys.exit("No classified month found in BI-AAP — report layout changed? Not writing.")
    last = min(args.period, newest) if args.period else newest
    print(f"Newest classified month in BI-AAP: {newest}")

    # Step 2 — self-throttle. Nothing to do when the CSVs already hold that
    # month AND this BI-AAP refresh has been processed (AAP revises earlier
    # months at every refresh, so a new refresh always means a full re-read).
    in_csv = all(have[v].get(newest, {}).get("source") == SOURCE for v in variants)
    seen = bool(refreshed_s) and stored_refresh() == refreshed_s
    if not backfill and not args.force and in_csv and seen:
        print(f"{newest} already fetched and BI-AAP refresh {refreshed_s} already "
              "processed; nothing to do.")
        return emit(args, set())

    # Step 3 — AAP's printed monthly report confirms a month as complete: its
    # month totals are never revised once printed (five editions compared,
    # 2026-03 → 2026-08), so a match proves BI-AAP holds the whole month.
    table, where = load_report(session, args)
    if table is None:
        print(f"::warning title=AAP report unavailable::{where} — no new month can be "
              "confirmed; only months already in the CSVs are revised.")
    if (not backfill and not args.force and seen and not in_csv
            and (table is None or newest not in table)):
        print(f"{newest} is classified in BI-AAP but not confirmed by AAP's printed "
              f"report yet ({where}); waiting — nothing to do.")
        return emit(args, set())

    # Step 4 — a real run re-reads the whole history (≈ 90 small queries):
    # BI-AAP revisions of the powertrain split reach back two years and more.
    todo = months_between(FIRST_PERIOD, last)
    agg = Aggregator()
    for p in todo:
        rows = load(p)
        agg.add_rows(p, rows)
        # Self-check: the detailed rows must add up to an independent
        # aggregate query of the same month (decoding / truncation errors).
        if api is not None:
            want = aggregate(p)
            got = month_totals(rows)
            if +want != +got:
                diff = {k: (got.get(k, 0), want.get(k, 0)) for k in set(got) | set(want)
                        if got.get(k, 0) != want.get(k, 0)}
                sys.exit(f"{p}: detailed rows disagree with the month aggregate "
                         f"{diff} — decoding or truncation error, not writing.")
        print(f"  {p}: {sum(int(r[-1] or 0) for r in rows):,} registrations "
              f"({len(rows):,} rows), light {agg.light[p]:,}")
    if args.dump_json:
        Path(args.dump_json).write_text(json.dumps(
            {"refreshed": refreshed_s, "months": {p: load(p) for p in todo}},
            ensure_ascii=False), encoding="utf-8")
        print(f"Raw month rows saved to {args.dump_json}")

    # Months AAP has not classified yet are never written (preliminary load).
    periods = sorted(p for p in todo if agg.light[p] and not agg.unclassified[p])
    pending = [p for p in todo if agg.unclassified[p]]
    if pending:
        print(f"::warning title=Unclassified months skipped::{pending} still have "
              "light vehicles without AAP's powertrain class — not written.")

    for p in periods:
        whole = agg.counts[p]["Whole"]["TOTAL"]
        unk = sum(n for (pp, v, f), n in agg.unknown_fuel.items() if pp == p and v == "Whole")
        if whole and unk / whole > MAX_UNKNOWN_FUEL_SHARE and not args.force:
            sys.exit(f"{p}: {unk:,} Whole registrations with unknown powertrain values "
                     f"({unk / whole:.1%}) — schema drift, not writing. Values: "
                     f"{sorted({f for (pp, v, f) in agg.unknown_fuel if pp == p})}")
        um = sum(n for (pp, c, b), n in agg.unmapped.items() if pp == p)
        if agg.light[p] and um / agg.light[p] > MAX_UNMAPPED_CLASS_SHARE and not args.force:
            sys.exit(f"{p}: {um:,} light vehicles in a class/body no variant knows "
                     f"({um / agg.light[p]:.1%}): "
                     f"{sorted({(c, b) for (pp, c, b) in agg.unmapped if pp == p})} — "
                     "map them in variant_for(), not writing.")

    problems = check_sums(agg, periods)
    if problems:
        sys.exit("Consistency check failed:\n  " + "\n  ".join(problems[:20]))

    # Cross-check every month against the printed report; a real mismatch
    # aborts (a truncated month, a scope change, a decoding bug).
    if table:
        compared, small, mism = cross_check(agg, periods, table)
        if mism and not args.force:
            sys.exit("Cross-check against AAP's printed report failed — BI-AAP and the "
                     "report disagree; not writing (--force overrides):\n  "
                     + "\n  ".join(mism[:30]))
        xcheck = (f"`{where}`: {len(compared)} month(s) compared "
                  f"({compared[0] if compared else '—'} → {compared[-1] if compared else '—'}), "
                  "new light + heavy vehicles: "
                  + ("exact match." if not (small or mism) else "")
                  + (f" {len(small)} difference(s) within tolerance: " + "; ".join(small[:10])
                     if small else "")
                  + (f" {len(mism)} MISMATCHES (forced): " + "; ".join(mism[:10])
                     if mism else ""))
    else:
        xcheck = f"Report not available this run ({where}) — not compared."
    print("Cross-check: " + xcheck)

    # Which months may be written: confirmed by the report — or, without a
    # report, only months already in the CSVs (their revisions). --force
    # writes every classified month.
    known = set.intersection(*[{p for p, r in have[v].items() if r.get("source") == SOURCE}
                               for v in variants])
    if args.force:
        writable = list(periods)
    elif table:
        writable = [p for p in periods if p in table]
    else:
        writable = [p for p in periods if p in known]
    held = [p for p in periods if p not in writable]
    if held:
        print(f"::notice title=Months held back::{held} — classified in BI-AAP but not "
              "yet confirmed by AAP's printed report; written once it is.")
    if not writable:
        print("No confirmed month to write.")
        return emit(args, set())
    # A new month far below the trailing median is held back (a belt-and-braces
    # completeness guard behind the report confirmation); revisions still go in.
    for p in [p for p in writable if p not in known]:
        whole_total = agg.counts[p]["Whole"]["TOTAL"]
        frac = median_fraction(p, whole_total, have.get("Whole", {}))
        if not backfill and not args.force and frac is not None and frac < MIN_MONTH_FRACTION:
            print(f"::warning title=Peru {p} looks incomplete::Whole TOTAL {whole_total:,} "
                  f"is {frac:.0%} of the trailing median — not written. Re-run with "
                  "force if genuine.")
            writable.remove(p)
    if not writable:
        print("No confirmed month to write.")
        return emit(args, set())
    target = max(writable)
    print(f"Newest confirmed month: {target}")

    changed: set[str] = set()
    revised: list[str] = []
    for v in variants:
        updates = {(p, v): render_line(p, v, agg.counts[p][v])
                   for p in writable if agg.counts[p][v]["TOTAL"] > 0}
        revised += revisions(paths[v], updates)
        stats = upsert_lines(paths[v], updates, args.force)
        print(f"{VARIANT_CSV[v]}: {stats}")
        if stats["added"] or stats["updated"]:
            changed.add(v)
    if revised:
        print(f"::notice title=Earlier months revised by BI-AAP::{len(revised)} row(s) "
              "changed — see the step summary.")

    def refresh_top() -> None:
        top = build_top(agg, target)
        top["source_refreshed"] = refreshed_s     # the self-throttle's memory
        print(f"{TOP_PATH.relative_to(REPO)}: "
              f"{'updated' if market_top.write_top(top, TOP_PATH) else 'unchanged'}")
    if "Whole" in variants:
        market_top.guarded(refresh_top)

    rep = report(agg, target, periods, xcheck, refreshed_s or "unknown")
    rep += "\n### Earlier months revised in this run\n\n"
    rep += ("\n".join(f"- {r}" for r in revised) if revised else "None.") + "\n"
    if held:
        rep += f"\n### Held back (not yet in AAP's printed report)\n\n{', '.join(held)}\n"
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
