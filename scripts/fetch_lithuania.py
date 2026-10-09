#!/usr/bin/env python3
"""
Fetch Lithuania's first registrations from Regitra (the state enterprise that
keeps the national road-vehicle register) and upsert data/Lithuania*.csv
(Whole + Used).

Sources (all on regitra.lt, free, no login)
-------------------------------------------
1. **Monthly fuel table** — "Pirmą kartą įregistruotų Lietuvoje M1 klasės
   transporto priemonių skaičius pagal degalų rūšį <year>" (table 5 on
   https://www.regitra.lt/paslaugos/duomenu-teikimas/statistika/). One XLSX
   per calendar year (2024 onwards), restated every month, with every M1
   vehicle (M1 and M1G) first registered in Lithuania, split by Regitra's own
   status **Nauja** (new) / **Naudota** (used, previously registered abroad)
   and by the register's fuel field (DEGALAI, e.g. "Benzinas/Elektra").
   This is where every count in the CSV comes from.
2. **Monthly totals** — "Pirmą kartą Lietuvoje įregistruotų transporto
   priemonių skaičius <year>" on the same page: new and used M1 per month.
   A separate Regitra publication, used as the cross-check (must match the
   fuel table's own "Suma" lines exactly).
3. **Open register snapshot** — "Atviri įregistruotų kelių transporto
   priemonių parko duomenys" (https://www.regitra.lt/imone/atviri-duomenys/):
   one CSV row per registered vehicle (~2.5 M rows, 167 MB zip), refreshed
   about quarterly. It carries the EU certificate-of-conformity field 23.1
   HIBRIDINES_TP_KATEGORIJA (OVC-HEV = plug-in, NOVC-HEV = not externally
   chargeable) that the fuel table lacks, plus brand and model. Used for the
   PHEV/HEV split (tier 2 below) and for market/lithuania_top.json and
   market/lithuania_used_top.json.

Record → CSV
------------
  Whole  data/Lithuania.csv       status Nauja,   M1 + M1G   (EU M1, new)
  Used   data/Lithuania_Used.csv  status Naudota, M1 + M1G   (used imports)

Fuel (DEGALAI, "/"-separated components) → columns, first match wins:
  exactly "Elektra"                         → BEV
  contains "Vandenilis" (hydrogen)          → OTHERS   (fuel cell, as ACEA)
  contains "Elektra" (any combination)      → hybrid   (PHEV + HEV, split below)
  exactly "Benzinas"                        → PETROL
  exactly "Dyzelinas"                       → DIESEL
  anything else (LPG/CNG/ethanol bi-fuel,
  "Nenurodyta" = not stated, …)             → OTHERS
Mild hybrids are type-approved as NOVC-HEV and registered as "…/Elektra", so
they sit in HEV — exactly as in ACEA's Lithuanian figures (the legacy series).

The PHEV / HEV split (the fuel table has one hybrid number)
-----------------------------------------------------------
For each month the hybrid count H from table 5 is split with a PHEV share,
taken from the best source available, re-evaluated on every run:

  tier 1  ACEA's counted PHEV/HEV for that month (Whole only). ACEA's
          Lithuanian figures come from the same register and reproduce
          Regitra's totals to within a few cars (doc §5). The share is read
          from the existing ACEA row (fetch-acea writes it first) or from the
          "ACEA PHEV a / HEV b" note this script leaves behind.
  tier 2  the register snapshot: OVC-HEV / (OVC-HEV + NOVC-HEV) among that
          month's first registrations still in the register. Counted, but
          cars re-exported since are missing — accurate for recent months,
          biased for old ones (doc §4.3). The only source for Used.
  tier 3  provisional: the trailing three final months' share. Written with
          source "Regitra (provisional)" so fetch-acea may replace the row
          and this script upgrades it once ACEA or a newer snapshot covers it.

  PHEV = round(H × share), HEV = H − PHEV. The note column records the tier.

Governance (every real run)
---------------------------
* the year file must have the expected layout (month header, Nauja/Naudota
  blocks, Suma lines); every block must sum to its Suma line;
* unknown fuel components above 2 % of a month abort (they are listed);
* cross-check: table 5's monthly M1 totals must equal the separate totals
  publication exactly (--force overrides);
* completeness: a newest month below 25 % of the trailing-12 median is not
  written, below 50 % is written with a warning;
* rows from a foreign source (other than ACEA, which this source replaces
  from 2024-01) are never overwritten without --force.

Usage
-----
  python scripts/fetch_lithuania.py                 # normal run
  python scripts/fetch_lithuania.py --backfill      # every year file (2024-)
  python scripts/fetch_lithuania.py --fleet         # force the register snapshot
  python scripts/fetch_lithuania.py --from-dir DIR  # offline: year files in DIR
  python scripts/fetch_lithuania.py --fleet-file F  # offline register zip/CSV

Docs: docs/architecture/55-source-lithuania.md (method, validation, runbook).
"""
from __future__ import annotations

import argparse
import collections
import csv
import datetime as dt
import html
import io
import json
import os
import re
import sys
import zipfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
REPO = SCRIPTS.parent
sys.path.insert(0, str(SCRIPTS))
import market_top  # noqa: E402

SOURCE = "Regitra"
SOURCE_PROVISIONAL = "Regitra (provisional)"
OWN_SOURCES = {SOURCE, SOURCE_PROVISIONAL}
# Foreign sources this fetcher replaces without --force: ACEA's copy of the
# same register numbers (fetch-acea.yml wrote Lithuania until 2026-10).
REPLACEABLE = {"ACEA"}
FIRST_PERIOD = "2024-01"          # first year file Regitra publishes
STATS_URL = "https://www.regitra.lt/paslaugos/duomenu-teikimas/statistika/"
OPEN_URL = "https://www.regitra.lt/imone/atviri-duomenys/"
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"}

VARIANT_CSV = {"Whole": "data/Lithuania.csv", "Used": "data/Lithuania_Used.csv"}
RENDERED_VARIANTS = {"Whole", "Used"}
FUELS = ["BEV", "PHEV", "HEV", "PETROL", "DIESEL", "OTHERS"]
CSV_COLUMNS = ["period", "time_interval", "variant", "source"] + FUELS + ["TOTAL", "notes"]
FLEET_STORE = market_top.MARKET_DIR / "lithuania_fleet.json"
TOP_PATHS = {"Whole": market_top.MARKET_DIR / "lithuania_top.json",
             "Used": market_top.MARKET_DIR / "lithuania_used_top.json"}

MAX_UNKNOWN_SHARE = 0.02
MIN_MONTH_FRACTION = 0.25
WARN_MONTH_FRACTION = 0.50
MIN_SPLIT_BASE = 20               # tier 2 needs this many classified hybrids
TRAILING_MONTHS = 3               # tier 3 window

KNOWN_COMPONENTS = {
    "benzinas", "dyzelinas", "elektra", "dujos", "suskystintos naftos dujos",
    "suskystintos gamtinės dujos", "suslėgtos gamtinės dujos", "gamtinės dujos",
    "etanolis", "biometanas", "vandenilis", "kita", "nenurodyta", "",
}
LT_MONTHS = ["sausis", "vasaris", "kovas", "balandis", "gegužė", "birželis",
             "liepa", "rugpjūtis", "rugsėjis", "spalis", "lapkritis", "gruodis"]


# ── fuel mapping ───────────────────────────────────────────────────────────

def components(label: str) -> list[str]:
    return [" ".join(c.split()).lower() for c in str(label or "").split("/")]


def fuel_class(label: str) -> str:
    """Register fuel string → BEV / HYB / PETROL / DIESEL / OTHERS."""
    comps = components(label)
    s = set(comps)
    if s == {"elektra"}:
        return "BEV"
    if "vandenilis" in s:
        return "OTHERS"
    if "elektra" in s:
        return "HYB"
    if s == {"benzinas"}:
        return "PETROL"
    if s == {"dyzelinas"}:
        return "DIESEL"
    return "OTHERS"


def is_known(label: str) -> bool:
    return all(c in KNOWN_COMPONENTS for c in components(label))


def status_of(label) -> str | None:
    """Regitra's status label → 'new' / 'used' (None for anything else)."""
    s = str(label or "").strip().lower()
    if s.startswith("nauj"):
        return "new"
    if s.startswith("naudot"):
        return "used"
    return None


STATUS_VARIANT = {"new": "Whole", "used": "Used"}


# ── table 5: monthly M1 first registrations by fuel ────────────────────────

def _rows(xlsx: bytes) -> list[list]:
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(xlsx), read_only=True, data_only=True)
    return [list(r) for r in wb.worksheets[0].iter_rows(values_only=True)]


def _month_header(cells: list, year: int | None) -> dict[int, str]:
    """{column: "YYYY-MM"} if this is the month header row: "YYYY-MM" strings
    (2025 on) or the integers 1..12 with the year taken from the title (2024)."""
    out = {}
    for i, c in enumerate(cells):
        if isinstance(c, str) and re.fullmatch(r"\d{4}-\d{2}", c.strip()):
            out[i] = c.strip()
    if out:
        return out
    ints = {i: c for i, c in enumerate(cells[2:], start=2)
            if isinstance(c, (int, float)) and not isinstance(c, bool)}
    if year and len(ints) >= 6 and not str(cells[0]).strip() and not str(cells[1]).strip() and \
            all(1 <= int(v) <= 12 for v in ints.values()) and \
            [int(v) for v in ints.values()] == list(range(1, len(ints) + 1)):
        return {i: f"{year}-{int(v):02d}" for i, v in ints.items()}
    return {}


def parse_fuel_table(xlsx: bytes) -> tuple[dict, dict]:
    """→ ({(period, status): {fuel_label: n}}, {(period, status): subtotal}).

    Layout: a title row naming the year; a month header row — "YYYY-MM"
    cells (2025, 2026) or 1..12 (2024); then one block per status: column A
    carries "Nauja"/"Naudota" on the block's first row, column B the fuel
    label, the month columns the counts; the block closes with a subtotal
    line ("Nauja Suma" / "Nauja viso") and the table with a grand total
    ("Bendroji suma" / "IŠ VISO")."""
    rows = _rows(xlsx)
    year = None
    months: dict[int, str] = {}
    counts: dict = collections.defaultdict(dict)
    sums: dict = {}
    status = None
    for r in rows:
        cells = ["" if c is None else c for c in r]
        if not cells:
            continue
        if year is None and isinstance(cells[0], str):
            m = re.search(r"(20\d\d)\s*m\.", cells[0])
            year = int(m.group(1)) if m else None
        found = _month_header(cells, year) if not months else {}
        if found:
            months = found
            continue
        if not months:
            continue
        a = " ".join(str(cells[0]).split())
        low = a.lower()
        if low.endswith("suma") or low.endswith("viso"):
            st = status_of(a)
            if st:
                for i, p in months.items():
                    v = cells[i] if i < len(cells) else ""
                    sums[(p, st)] = int(v or 0)
            status = None
            continue
        if a:
            status = status_of(a) or status
        if status is None or len(cells) < 2:
            continue
        label = str(cells[1]).strip()
        for i, p in months.items():
            v = cells[i] if i < len(cells) else ""
            if v not in ("", None):
                counts[(p, status)][label] = counts[(p, status)].get(label, 0) + int(v)
    if not months:
        raise ValueError("fuel table: no month header row — layout changed")
    if not counts:
        raise ValueError("fuel table: no Nauja/Naudota rows — layout changed")
    return dict(counts), sums


def parse_totals_table(xlsx: bytes, year: int) -> dict:
    """The separate monthly totals publication → {(period, status): M1 count}.
    Columns: Mėnuo · used (all) · used M1 · new (all) · new M1."""
    out = {}
    for r in _rows(xlsx):
        if not r or not isinstance(r[0], str):
            continue
        name = r[0].strip().lower()
        if name in LT_MONTHS and len(r) >= 5 and r[2] is not None and r[4] is not None:
            p = f"{year}-{LT_MONTHS.index(name) + 1:02d}"
            out[(p, "used")] = int(r[2])
            out[(p, "new")] = int(r[4])
    return out


def classify_month(fuels: dict[str, int]) -> tuple[collections.Counter, int, list[str]]:
    """{label: n} → (Counter by class incl. HYB, unknown n, unknown labels)."""
    c = collections.Counter()
    unk, unk_labels = 0, []
    for label, n in fuels.items():
        c[fuel_class(label)] += n
        if not is_known(label):
            unk += n
            unk_labels.append(label)
    return c, unk, unk_labels


# ── register snapshot (tier 2 + brand/model tables) ────────────────────────

def hybrid_kind(cat: str) -> str:
    c = (cat or "").strip().upper()
    if c.startswith("OVC"):
        return "PHEV"
    if c.startswith("NOVC"):
        return "HEV"
    return "UNK"


def display_brand(marke: str) -> str:
    b = market_top.clean(marke).split(".")[0].split("/")[0].strip()
    return {"LYNK&CO": "LYNK & CO"}.get(b, b)


# Trim / power / drive words in the register's commercial name (KOMERCINIS_PAV
# is typed per approval: "ID.4 PRO 210KW", "Q5 220KW TFSI E", "GLC 200 4MATIC").
MODEL_NOISE = re.compile(
    r"\d+(?:[.,]\d+)?\s?KWH?\b"
    r"|\b(?:PRO S|PRO|PURE|MAX|LR|GTX|PERF\.?|PERFORMANCE|QUATTRO|SPORTBACK|"
    r"TOURER|AVANT|SUV|E-TECH ELECTRIC|E-TECH HYBRID|E-TECH|ELECTRIC|HYBRID\+?|"
    r"DM-I|EM-I|PHEV|PLUG[- ]IN|RECHARGE|TFSI E|TFSI|XDRIVE\d*E?|4MATIC\+?|4MOTION)(?!\S)")


def display_model(brand: str, model: str) -> str:
    """Commercial name -> the model as buyers know it, for the ranking only.
    "TUCSON. ix35" lists two names: the first is kept. The dot inside a name
    ("ID.4") is part of it."""
    m = re.split(r"(?<=[A-Z0-9]{3})\. ", market_top.clean(model))[0].strip()
    m = market_top.strip_brand(brand, m)
    m = re.sub(r"\([^)]*\)", " ", m)
    toks = m.split()
    if brand in ("MERCEDES-BENZ", "AUDI") and toks:
        m = toks[0]                                   # "GLC 200 4MATIC" -> GLC
    elif brand == "TESLA":
        m = " ".join(toks[:2])                        # "MODEL Y LONG RANGE"
    elif brand == "LEXUS":
        m = re.sub(r"^([A-Z]{2})\d{3}.*$", r"\1", m)   # NX450H+ -> NX
    elif brand == "BMW" and toks:
        m = toks[0]
    elif brand == "SKODA":                            # ENYAQ 85X, ELROQ 85
        m = " ".join(t for t in toks if not re.fullmatch(r"\d{2,3}X?", t))
    m = " ".join(MODEL_NOISE.sub(" ", m).split())
    return m or market_top.clean(model)


def snapshot_status(row: dict) -> str | None:
    """new = first registration anywhere == first registration in Lithuania.
    Only used inside the snapshot (split shares, brand tables) — the counts in
    the CSVs carry Regitra's own Nauja/Naudota classification from table 5."""
    lt, first = row.get("PIRM_REG_DATA_LT") or "", row.get("PIRM_REG_DATA") or ""
    if not lt:
        return None
    return "new" if first == lt else "used"


def scan_fleet(text_stream, first_month: str) -> tuple[dict, dict, str]:
    """Stream the register CSV → (split, units, newest first-registration date).

    split: {(period, status): {"PHEV": n, "HEV": n, "UNK": n}}
    units: {status: {(period, class, brand, model): n}}  (class incl. ICE)"""
    split: dict = collections.defaultdict(collections.Counter)
    units = {"new": collections.Counter(), "used": collections.Counter()}
    newest = ""
    reader = csv.DictReader(text_stream)
    need = {"KATEGORIJA_KLASE", "DEGALAI", "HIBRIDINES_TP_KATEGORIJA",
            "PIRM_REG_DATA", "PIRM_REG_DATA_LT", "MARKE", "KOMERCINIS_PAV"}
    missing = need - set(reader.fieldnames or [])
    if missing:
        raise ValueError(f"register snapshot: missing columns {sorted(missing)}")
    for row in reader:
        if row["KATEGORIJA_KLASE"] != "M1":
            continue
        lt = row["PIRM_REG_DATA_LT"] or ""
        newest = max(newest, lt)
        p = lt[:7]
        if p < first_month:
            continue
        st = snapshot_status(row)
        if st is None:
            continue
        cls = fuel_class(row["DEGALAI"])
        if cls == "HYB":
            cls = hybrid_kind(row["HIBRIDINES_TP_KATEGORIJA"])
            split[(p, st)][cls] += 1
        brand = display_brand(row["MARKE"])
        units[st][(p, cls, brand, display_model(brand, row["KOMERCINIS_PAV"]))] += 1
    return dict(split), units, newest


def open_fleet(blob: bytes):
    if blob[:2] == b"PK":
        z = zipfile.ZipFile(io.BytesIO(blob))
        info = max(z.infolist(), key=lambda i: i.file_size)
        stamp = "%04d-%02d-%02d" % info.date_time[:3]
        return io.TextIOWrapper(z.open(info), encoding="utf-8-sig", newline=""), stamp
    return io.StringIO(blob.decode("utf-8-sig")), ""


def covered_months(newest_date: str) -> str:
    """Last month fully inside a snapshot whose newest first registration is
    `newest_date`: the month before that date's month."""
    y, m = int(newest_date[:4]), int(newest_date[5:7])
    y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    return f"{y}-{m:02d}"


def load_store() -> dict:
    try:
        return json.loads(FLEET_STORE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_store(store: dict) -> bool:
    text = json.dumps(store, ensure_ascii=False, sort_keys=True, indent=1) + "\n"
    if FLEET_STORE.exists() and FLEET_STORE.read_text(encoding="utf-8") == text:
        return False
    FLEET_STORE.parent.mkdir(parents=True, exist_ok=True)
    FLEET_STORE.write_text(text, encoding="utf-8")
    return True


def build_store(split: dict, newest: str, label: str, stamp: str) -> dict:
    last = covered_months(newest)
    return {
        "note": "generated by scripts/fetch_lithuania.py from Regitra's open "
                "register snapshot — M1 first registrations still registered, "
                "hybrids by EU CoC field 23.1; never hand-edit",
        "snapshot": {"label": label, "file_date": stamp, "newest_first_registration": newest,
                     "covers_to": last},
        "months": {f"{p}|{st}": dict(sorted(c.items()))
                   for (p, st), c in sorted(split.items()) if p <= last},
    }


def write_tops(units: dict, last: str, totals: dict) -> None:
    for st, variant in STATUS_VARIANT.items():
        monthly = {}
        for p in market_top.month_window(last):
            u = {(c, b, m): n for (pp, c, b, m), n in units[st].items() if pp == p}
            if u:
                monthly[p] = (u, sum(u.values()))
        if not monthly:
            continue
        unit = ("new passenger cars (M1) first registered in Lithuania and still "
                "in the register" if st == "new" else
                "used passenger cars (M1) imported and first registered in "
                "Lithuania, still in the register")
        top = market_top.build_top_monthly("Lithuania", "Regitra open register",
                                           last, monthly, unit, variant)
        # Cars re-exported since are missing from the snapshot (doc §4.3), so
        # the tables lag the CSV's counts; only a gross scope break aborts.
        market_top.check_scope({p: v[1] for p, v in monthly.items()},
                               totals.get(variant, {}), warn=0.15, abort=0.40)
        path = TOP_PATHS[variant]
        wrote = market_top.write_top(top, path)
        market_top.report(top, path, wrote)


# ── split tiers ────────────────────────────────────────────────────────────

class NoSplit(Exception):
    """No tier can split this month's hybrids — the row is not written."""


ACEA_NOTE = re.compile(r"ACEA PHEV (\d+) / HEV (\d+)")


def acea_split(row: dict | None) -> tuple[int, int] | None:
    """(PHEV, HEV) from an ACEA row, or from this script's tier-1 note."""
    if not row:
        return None
    if (row.get("source") or "").strip().upper() == "ACEA":
        try:
            return int(float(row.get("PHEV") or 0)), int(float(row.get("HEV") or 0))
        except ValueError:
            return None
    m = ACEA_NOTE.search(row.get("notes") or "")
    return (int(m.group(1)), int(m.group(2))) if m else None


def split_hybrids(period: str, status: str, hyb: int, existing: dict | None,
                  store: dict, done: dict[str, tuple[int, int]]) -> tuple[int, int, str, bool]:
    """→ (PHEV, HEV, note, provisional). `done` maps already-final months of
    this variant to (PHEV, HEV) — the tier-3 base."""
    if hyb == 0:
        return 0, 0, "no hybrids", False
    if status == "new":
        a = acea_split(existing)
        if a and sum(a):
            phev = round(hyb * a[0] / sum(a))
            return phev, hyb - phev, f"PHEV/HEV split from ACEA PHEV {a[0]} / HEV {a[1]}", False
    snap = store.get("snapshot", {})
    k = store.get("months", {}).get(f"{period}|{status}")
    if k and k.get("PHEV", 0) + k.get("HEV", 0) >= MIN_SPLIT_BASE:
        o, n = k.get("PHEV", 0), k.get("HEV", 0)
        phev = round(hyb * o / (o + n))
        return (phev, hyb - phev,
                f"PHEV/HEV split from the register snapshot {snap.get('label') or snap.get('file_date')} "
                f"(OVC {o} / NOVC {n})", False)
    base = [done[p] for p in sorted(done) if p < period][-TRAILING_MONTHS:]
    o, n = sum(b[0] for b in base), sum(b[1] for b in base)
    if o + n == 0:
        raise NoSplit(f"{period} {status}: no ACEA split, no register snapshot month and "
                      "no earlier final month to estimate from")
    share = o / (o + n) if o + n else 0.0
    phev = round(hyb * share)
    return (phev, hyb - phev,
            f"provisional: PHEV/HEV split estimated from the previous {len(base)} months' "
            f"share ({share:.1%}) until ACEA or a newer register snapshot covers this month",
            True)


# ── CSV line-level upsert (invariant 2) ────────────────────────────────────

def fmt(v: int) -> str:
    return f"{float(v):.1f}"


def render_line(period: str, variant: str, counts: dict[str, int], source: str,
                notes: str) -> str:
    buf = io.StringIO()
    csv.writer(buf, lineterminator="").writerow(
        [period, "monthly", variant, source]
        + [fmt(counts[k]) for k in FUELS + ["TOTAL"]] + [notes])
    return buf.getvalue()


def read_csv_lines(path: Path) -> tuple[str, list[str], str]:
    if not path.exists():
        return ",".join(CSV_COLUMNS), [], "\n"
    raw = path.read_bytes().decode("utf-8")
    eol = "\r\n" if "\r\n" in raw else "\n"
    lines = raw.splitlines()
    return (lines[0], lines[1:], eol) if lines else (",".join(CSV_COLUMNS), [], eol)


def parse_line(line: str) -> list[str]:
    return next(csv.reader([line]))


def upsert_lines(path: Path, updates: dict[tuple[str, str], str],
                 force: bool) -> dict[str, int]:
    """Replace/insert only the given (period, variant) lines; every other line
    is written back byte for byte (line endings kept). New lines are inserted
    in period order."""
    header, lines, eol = read_csv_lines(path)
    if header.split(",") != CSV_COLUMNS:
        sys.exit(f"{path}: unexpected header {header!r}")
    stats = {"added": 0, "updated": 0, "unchanged": 0, "skipped": 0}
    index = {}
    for i, l in enumerate(lines):
        f = parse_line(l)
        index[(f[0], f[2])] = i
    for key, new in sorted(updates.items()):
        if key in index:
            old = lines[index[key]]
            src = parse_line(old)[3].strip()
            if old == new:
                stats["unchanged"] += 1
            elif src not in OWN_SOURCES and src not in REPLACEABLE and not force:
                stats["skipped"] += 1
                print(f"  {path.name} {key[0]}: kept (foreign source {src!r}; --force overrides)")
            else:
                lines[index[key]] = new
                stats["updated"] += 1
        else:
            pos = len(lines)
            for i, l in enumerate(lines):
                f = parse_line(l)
                if (f[0], f[2]) > key:
                    pos = i
                    break
            lines.insert(pos, new)
            index = {(parse_line(l)[0], parse_line(l)[2]): i for i, l in enumerate(lines)}
            stats["added"] += 1
    if stats["added"] or stats["updated"]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((eol.join([header] + lines) + eol).encode("utf-8"))
    return stats


def existing_rows(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    with open(path, newline="", encoding="utf-8") as f:
        return {r["period"]: r for r in csv.DictReader(f)}


# ── network ────────────────────────────────────────────────────────────────

def make_session():
    import requests
    s = requests.Session()
    s.headers.update(UA)
    return s


def page_links(page: str) -> list[tuple[str, str]]:
    out = []
    for m in re.finditer(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', page, re.S):
        out.append((html.unescape(m.group(1)),
                    " ".join(html.unescape(re.sub(r"<[^>]+>", " ", m.group(2))).split())))
    return out


def find_year_files(page: str) -> tuple[dict[int, str], dict[int, str]]:
    """→ ({year: fuel-table url}, {year: totals url}) from the statistics page."""
    fuel, totals = {}, {}
    for href, text in page_links(page):
        h = href.lower()
        if not re.search(r"\.xlsx?($|\?)", h):
            continue
        year = re.search(r"(20\d\d)", text) or re.search(r"(20\d\d)-m", h)
        if not year:
            continue
        y = int(year.group(1))
        if "degalu-rusi" in h and "m1" in h and "pirma-karta" in h:
            fuel.setdefault(y, href)
        elif re.search(r"/pirma-karta-lietuvoje-iregistruotu-transporto-priemoniu-skaicius", h):
            totals.setdefault(y, href)
    return fuel, totals


def find_fleet(page: str) -> tuple[str, str] | None:
    """→ (zip url, date label) of the vehicle-fleet open data (not the
    legal-entity extract)."""
    for href, text in page_links(page):
        if href.rsplit("/", 1)[-1].lower() == "atviri_tp_parko_duomenys.zip":
            d = re.search(r"(\d{4}-\d{2}-\d{2})", text)
            return href, d.group(1) if d else ""
    return None


# ── checks & report ────────────────────────────────────────────────────────

def median_fraction(period: str, total: int, have: dict[str, dict]) -> float | None:
    prior = sorted(p for p in have if p < period and have[p].get("time_interval") == "monthly")[-12:]
    if len(prior) < 6:
        return None
    vals = sorted(float(have[p]["TOTAL"]) for p in prior)
    median = vals[len(vals) // 2]
    return total / median if median else None


def previous_month(today: dt.date) -> str:
    y, m = (today.year - 1, 12) if today.month == 1 else (today.year, today.month - 1)
    return f"{y}-{m:02d}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--variant", default="all", help="all | Whole | Used")
    ap.add_argument("--period", default="", help="Target month YYYY-MM (default: last month)")
    ap.add_argument("--backfill", action="store_true",
                    help=f"Read every year file from {FIRST_PERIOD[:4]} on.")
    ap.add_argument("--force", action="store_true",
                    help="Ignore the self-throttle, the guards and foreign source strings.")
    ap.add_argument("--fleet", action="store_true",
                    help="Download the register snapshot even if its date is unchanged.")
    ap.add_argument("--no-fleet", action="store_true", help="Never download the snapshot.")
    ap.add_argument("--from-dir", default="",
                    help="Offline: year files named fuel_<year>.xlsx / totals_<year>.xlsx.")
    ap.add_argument("--fleet-file", default="", help="Offline: register snapshot zip/CSV.")
    ap.add_argument("--dry-run", action="store_true", help="Report, write nothing.")
    ap.add_argument("--github-output", default=os.environ.get("GITHUB_OUTPUT"))
    ap.add_argument("--step-summary", default=os.environ.get("GITHUB_STEP_SUMMARY"))
    args = ap.parse_args()

    variants = list(VARIANT_CSV) if args.variant == "all" else [args.variant]
    for v in variants:
        if v not in VARIANT_CSV:
            sys.exit(f"Unknown variant {v!r}. Valid: {list(VARIANT_CSV)} or all.")
    paths = {v: REPO / VARIANT_CSV[v] for v in VARIANT_CSV}
    have = {v: existing_rows(paths[v]) for v in VARIANT_CSV}
    target = args.period or previous_month(dt.date.today())
    backfill = args.backfill or not paths["Used"].exists()
    store = load_store()

    def settled(v: str) -> bool:
        rows = have[v]
        if rows.get(target, {}).get("source") != SOURCE:
            return False
        return not any(r.get("source") == SOURCE_PROVISIONAL for r in rows.values())

    if (not backfill and not args.force and not args.fleet
            and all(settled(v) for v in variants)):
        print(f"{target} already final from {SOURCE} in every CSV and no provisional "
              "row left — nothing to do (no HTTP).")
        return emit(args, set())

    session = None
    if args.from_dir:
        d = Path(args.from_dir)
        fuel_src = {int(m.group(1)): f for f in d.glob("fuel_*.xlsx")
                    if (m := re.search(r"(\d{4})", f.name))}
        tot_src = {int(m.group(1)): f for f in d.glob("totals_*.xlsx")
                   if (m := re.search(r"(\d{4})", f.name))}
        load = lambda ref: Path(ref).read_bytes()  # noqa: E731
    else:
        session = make_session()
        r = session.get(STATS_URL, timeout=120)
        r.raise_for_status()
        fuel_src, tot_src = find_year_files(r.text)

        def load(ref):
            resp = session.get(ref, timeout=300)
            resp.raise_for_status()
            return resp.content
    if not fuel_src:
        sys.exit("No fuel-table year files found on the statistics page — layout "
                 "changed? Not writing. See the runbook in 55-source-lithuania.md.")
    print("Fuel tables: " + ", ".join(f"{y}" for y in sorted(fuel_src)))

    ty = int(target[:4])
    years = sorted(y for y in fuel_src if y >= int(FIRST_PERIOD[:4])) if backfill else \
        sorted({y for y in fuel_src if y in (ty, ty - 1)} |
               {int(p[:4]) for v in VARIANT_CSV for p, r in have[v].items()
                if r.get("source") == SOURCE_PROVISIONAL and int(p[:4]) in fuel_src})
    counts: dict = {}
    sums: dict = {}
    xref: dict = {}
    for y in years:
        c, s = parse_fuel_table(load(fuel_src[y]))
        counts.update(c)
        sums.update(s)
        print(f"  {y}: {len({p for p, _ in c})} month(s) in the fuel table")
        if y in tot_src:
            try:
                xref.update(parse_totals_table(load(tot_src[y]), y))
            except Exception as e:  # noqa: BLE001 — a check, not the data
                print(f"::warning title=Totals table {y} unreadable::{type(e).__name__}: {e}")

    periods = sorted({p for p, _ in counts if FIRST_PERIOD <= p <= target})
    if not periods:
        print(f"No month up to {target} in the fuel tables yet — retry next run.")
        return emit(args, set())

    # Governance: block sums, unknown fuels, cross-check.
    problems, mism, compared = [], [], 0
    per = {}
    for p in periods:
        for st in ("new", "used"):
            fuels = counts.get((p, st), {})
            c, unk, unk_labels = classify_month(fuels)
            tot = sum(fuels.values())
            if (p, st) in sums and sums[(p, st)] != tot:
                problems.append(f"{p} {st}: fuel rows sum to {tot} but the Suma line says "
                                f"{sums[(p, st)]}")
            if tot and unk / tot > MAX_UNKNOWN_SHARE:
                problems.append(f"{p} {st}: {unk} cars ({unk / tot:.1%}) with unknown fuel "
                                f"components {unk_labels}")
            elif unk_labels:
                print(f"::warning title=New fuel label {p}::{unk_labels} → mapped by rule")
            if (p, st) in xref:
                compared += 1
                if xref[(p, st)] != tot:
                    mism.append(f"{p} {st}: fuel table {tot} vs totals table {xref[(p, st)]}")
            per[(p, st)] = (c, tot)
    if problems:
        sys.exit("Consistency check failed — not writing:\n  " + "\n  ".join(problems[:20]))
    if mism and not args.force:
        sys.exit("Cross-check against Regitra's monthly totals failed — not writing "
                 "(--force overrides):\n  " + "\n  ".join(mism))
    xcheck = (f"{compared} month×status pairs compared with the monthly totals "
              f"publication: " + ("exact match." if not mism else f"{len(mism)} mismatches (forced)"))
    print("Cross-check: " + xcheck)

    # Register snapshot (tier 2 + brand/model tables) — only when it moved.
    fleet_note = "not checked (offline run)" if args.from_dir and not args.fleet_file else ""
    if not args.no_fleet:
        try:
            blob = label = None
            if args.fleet_file:
                blob, label = Path(args.fleet_file).read_bytes(), ""
            elif session is not None:
                r = session.get(OPEN_URL, timeout=120)
                r.raise_for_status()
                found = find_fleet(r.text)
                if not found:
                    raise ValueError("register snapshot link not found on the open-data page")
                url, label = found
                known = store.get("snapshot", {}).get("label", "")
                if args.fleet or not known or (label and label > known):
                    print(f"Register snapshot {label or '?'} (stored: {known or 'none'}) — downloading")
                    resp = session.get(url, timeout=900)
                    resp.raise_for_status()
                    blob = resp.content
                else:
                    fleet_note = f"snapshot {label} unchanged"
            if blob is not None:
                stream, stamp = open_fleet(blob)
                first = market_top.month_window(target, 15)[0]
                split, units, newest = scan_fleet(stream, min(first, FIRST_PERIOD))
                store = build_store(split, newest, label or stamp, stamp)
                last = store["snapshot"]["covers_to"]
                fleet_note = (f"snapshot {label or stamp} read (first registrations to {newest}, "
                              f"split months to {last})")
                totals = {v: {p: int(float(r["TOTAL"])) for p, r in have[v].items()
                              if r.get("TOTAL")} for v in VARIANT_CSV}
                for v in VARIANT_CSV:
                    st = "new" if v == "Whole" else "used"
                    totals[v].update({p: per[(p, st)][1] for p in periods if (p, st) in per})
                if not args.dry_run:
                    save_store(store)
                    market_top.guarded(write_tops, units, last, totals)
        except Exception as e:  # noqa: BLE001 — the snapshot only refines the split
            fleet_note = f"snapshot not read: {type(e).__name__}: {e}"
            print(f"::warning title=Regitra register snapshot::{fleet_note}")
    print("Register: " + fleet_note)

    # Build the rows.
    changed: set[str] = set()
    report_rows = []
    for v in variants:
        st = "new" if v == "Whole" else "used"
        done: dict[str, tuple[int, int]] = {}
        for p, r in have[v].items():          # final rows already in the CSV
            if r.get("source") in (SOURCE, "ACEA") and r.get("time_interval") == "monthly":
                try:
                    done[p] = (int(float(r["PHEV"])), int(float(r["HEV"])))
                except (KeyError, ValueError):
                    pass
        updates = {}
        for p in periods:
            if (p, st) not in per:
                continue
            c, tot = per[(p, st)]
            if tot == 0:
                continue
            frac = median_fraction(p, tot, have[v])
            if p == periods[-1] and frac is not None and not args.force:
                if frac < MIN_MONTH_FRACTION:
                    print(f"{v} {p}: TOTAL {tot:,} is {frac:.0%} of the trailing median — "
                          "looks like a partial file; not writing (--force if genuine).")
                    continue
                if frac < WARN_MONTH_FRACTION:
                    print(f"::warning title=Lithuania {v} {p} unusually low::TOTAL {tot:,} = "
                          f"{frac:.0%} of the trailing-12 median — written; check it.")
            try:
                phev, hev, note, prov = split_hybrids(p, st, c["HYB"], have[v].get(p), store, done)
            except NoSplit as e:
                print(f"  {v} {p}: not written — {e}")
                continue
            if not prov:
                done[p] = (phev, hev)
            row = {"BEV": c["BEV"], "PHEV": phev, "HEV": hev, "PETROL": c["PETROL"],
                   "DIESEL": c["DIESEL"], "OTHERS": c["OTHERS"], "TOTAL": tot}
            assert sum(row[k] for k in FUELS) == tot
            notes = f"Regitra table 5 ({'Nauja' if st == 'new' else 'Naudota'} M1 by fuel); {note}"
            updates[(p, v)] = render_line(p, v, row, SOURCE_PROVISIONAL if prov else SOURCE, notes)
            old = have[v].get(p)
            report_rows.append((v, p, row, note, old))
        if args.dry_run:
            print(f"{VARIANT_CSV[v]}: dry run, {len(updates)} row(s) computed")
            continue
        stats = upsert_lines(paths[v], updates, args.force)
        print(f"{VARIANT_CSV[v]}: {stats}")
        if stats["added"] or stats["updated"]:
            changed.add(v)

    rep = report(report_rows, target, xcheck, fleet_note)
    print("\n" + rep)
    if args.step_summary:
        with open(args.step_summary, "a", encoding="utf-8") as fh:
            fh.write(rep)
    return emit(args, changed)


def report(rows, target: str, xcheck: str, fleet_note: str) -> str:
    out = [f"## Lithuania (Regitra) — up to {target}", "",
           f"- Cross-check: {xcheck}", f"- Register snapshot: {fleet_note}", "",
           "| variant | month | TOTAL | BEV | PHEV | HEV | PETROL | DIESEL | OTHERS | split | Δ TOTAL vs old row |",
           "|---|---|---:|---:|---:|---:|---:|---:|---:|---|---|"]
    for v, p, r, note, old in rows[-30:] if len(rows) > 30 else rows:
        tier = ("provisional" if note.startswith("provisional") else "ACEA" if "ACEA" in note
                else "register" if "register" in note else note)
        d = ""
        if old and old.get("TOTAL"):
            d = f"{r['TOTAL'] - int(float(old['TOTAL'])):+d} ({old.get('source')})"
        out.append(f"| {v} | {p} | {r['TOTAL']:,} | {r['BEV']:,} | {r['PHEV']:,} | {r['HEV']:,} | "
                   f"{r['PETROL']:,} | {r['DIESEL']:,} | {r['OTHERS']:,} | {tier} | {d} |")
    return "\n".join(out) + "\n"


def emit(args, changed: set[str]) -> int:
    if args.github_output:
        with open(args.github_output, "a", encoding="utf-8") as f:
            f.write(f"changed={'true' if changed else 'false'}\n")
            f.write(f"changed_variants={json.dumps(sorted(changed & RENDERED_VARIANTS))}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
