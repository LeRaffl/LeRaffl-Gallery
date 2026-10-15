#!/usr/bin/env python3
"""
Fetch Estonia's first registrations from Transpordiamet (the Estonian
Transport Administration, keeper of the traffic register "liiklusregister")
and upsert data/Estonia*.csv (Whole, Private, Industry, Used, Vans, HDV,
Buses).

Source (free, no login)
-----------------------
Transpordiamet publishes one workbook a month, "Infoleht MM-YYYY (esmaste ja
uute sõidukite statistika)", on
https://www.transpordiamet.ee/soidukitega-tehtud-toimingute-statistika
(XLS until 2025-11, XLSX since; the month's file is up in the first days of
the next month and never restated). Three sheets are read:

1. **"Uued sõidukid"** — every *new* vehicle first registered in the month,
   aggregated to one row per identical vehicle (category, make, model, fuel
   combination, engine type, EU hybrid type OVC_HEV / NOVC_HEV, owner type
   FÜÜSILINE / JURIIDILINE, …) with a count column ("Arv" / "tk"). Whole,
   Private, Industry, Vans, HDV, Buses and the brand/model tables come from
   here. The hybrid-type column exists from the 2021-01 workbook on, so this
   source writes from 2021-01 (ACEA before).
2. **"Kytus_esm ( sh uued)"** — first registrations (new + used) and the new
   ones among them, by EU category × engine type. Used = first − new.
3. **"Esm(üldtabel)"** — the month's headline totals (passenger cars, lorries,
   buses: all first registrations and "sh uued" = of which new). The
   cross-check for sheets 1 and 2.

Record → CSV
------------
  Whole     new M1 + M1G                       (EU M1, new)
  Private   Whole, owner type FÜÜSILINE         (private person)
  Industry  Whole − Private                     (companies, state, …)
  Used      M1 + M1G first registrations − new (used imports)
  Vans      new N1 + N1G
  HDV       new N2 + N3 (+ G)
  Buses     new M2 + M3 (+ G)

Powertrain (new vehicles, first match wins):
  hybrid type *FCHV, engine VESINIK          → OTHERS  (fuel cell, as ACEA)
  hybrid type OVC_HEV                        → PHEV    (externally chargeable)
  hybrid type NOVC_HEV                       → HEV     (full + mild)
  engine ELEKTER                             → BEV
  engine *_HYBRIID without a hybrid type     → HEV     (a few cars a year; listed)
  engine BENSIIN*                            → PETROL  (incl. petrol/LPG and
                                                         petrol/CNG bi-fuel)
  engine DIISEL*                             → DIESEL
  anything else (CNG, GAAS, LPG engines, …)  → OTHERS
The engine type decides bi-fuel cars (petrol engine with an LPG kit stays
PETROL): that is how ACEA's Estonian figure — the legacy series — counts them
(OTHERS is 0 there since 2025), and the only rule the Used sheet (engine type
only) can follow too.

Used has engine types only (BENSIIN_HYBRIID / DIISEL_HYBRIID, no OVC/NOVC), so
its hybrids are one combined number in HEV and Estonia_Used.csv has no PHEV
column — the Lithuania / Türkiye convention.

Governance (every real run)
---------------------------
* each sheet must be found with its header (schema drift aborts);
* unknown engine / hybrid / owner values above 2 % of a variant-month abort;
* cross-check: new M1 from "Uued sõidukid" = "sh uued" passenger cars, and
  the Kytus sheet's first registrations = "Kokku" passenger cars, lorries and
  buses — off by more than 0.5 % (and 3 vehicles) aborts (--force overrides);
* completeness: a month below 25 % of the trailing-12 median is not written,
  below 50 % is written with a warning;
* rows from a foreign source other than ACEA (which this source replaces from
  2021-01) are never overwritten without --force.

Usage
-----
  python scripts/fetch_estonia.py                 # normal run (last month)
  python scripts/fetch_estonia.py --backfill      # every workbook from 2021-01
  python scripts/fetch_estonia.py --from-dir DIR  # offline: DIR/YYYY-MM.xls[x]

Docs: docs/architecture/57-source-estonia.md (method, validation, runbook).
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
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
REPO = SCRIPTS.parent
sys.path.insert(0, str(SCRIPTS))
import market_top  # noqa: E402

SOURCE = "Transpordiamet"
REPLACEABLE = {"ACEA"}            # the legacy writer this source supersedes
FIRST_PERIOD = "2021-01"          # first workbook with the EU hybrid type
STATS_URL = "https://www.transpordiamet.ee/soidukitega-tehtud-toimingute-statistika"
BASE_URL = "https://www.transpordiamet.ee"
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"}

VARIANT_CSV = {
    "Whole": "data/Estonia.csv",
    "Private": "data/Estonia_Private.csv",
    "Industry": "data/Estonia_Industry.csv",
    "Used": "data/Estonia_Used.csv",
    "Vans": "data/Estonia_Vans.csv",
    "HDV": "data/Estonia_HDV.csv",
    "Buses": "data/Estonia_Buses.csv",
}
FUELS = ["BEV", "PHEV", "HEV", "PETROL", "DIESEL", "OTHERS"]
VARIANT_FUELS = {v: FUELS for v in VARIANT_CSV}
VARIANT_FUELS["Used"] = [f for f in FUELS if f != "PHEV"]
USED_HYBRID_NOTE = ("hybrids combined in HEV (the first-registration sheet has engine "
                    "types only; no counted PHEV/HEV split for used imports)")

# EU category → variant (new vehicles). "G" = off-road version of the class.
CATEGORY_VARIANT = {
    "M1": "Whole", "M1G": "Whole",
    "N1": "Vans", "N1G": "Vans",
    "N2": "HDV", "N2G": "HDV", "N3": "HDV", "N3G": "HDV",
    "M2": "Buses", "M2G": "Buses", "M3": "Buses", "M3G": "Buses",
}
PASSENGER = {"M1", "M1G"}
LORRY = {"N1", "N1G", "N2", "N2G", "N3", "N3G"}
BUS = {"M2", "M2G", "M3", "M3G"}

KNOWN_ENGINES = {"ELEKTER", "BENSIIN", "BENSIIN_KATALYSAATOR", "DIISEL",
                 "BENSIIN_HYBRIID", "DIISEL_HYBRIID", "CNG", "LNG", "GAAS", "LPG",
                 "VESINIK", "ETANOOL", "BIOMETAAN", ""}
KNOWN_HYBRID = {"", "OVC_HEV", "NOVC_HEV", "OVC_FCHV", "NOVC_FCHV"}
# Owner type of the responsible user / owner, ASCII-folded (2024-06..08 wrote
# FYYSILINE): FYYSILINE = private person → Private; JURIIDILINE = legal person,
# RIIGI = state, ASUTAMISEL = company being founded, VALIS = foreign → Industry.
PRIVATE_OWNER = "FYYSILINE"
KNOWN_OWNER = {PRIVATE_OWNER, "JURIIDILINE", "RIIGI", "ASUTAMISEL", "VALIS", ""}

MAX_UNKNOWN_SHARE = 0.02
XCHECK_TOL = 0.005
XCHECK_MIN = 3
MIN_MONTH_FRACTION = 0.25
WARN_MONTH_FRACTION = 0.50
TOP_SLUG = "estonia"


# ── powertrain ─────────────────────────────────────────────────────────────

def up(x) -> str:
    s = "" if x is None else str(x)
    s = " ".join(s.split()).upper()
    return "" if s in ("NONE", "-") else s


def engine_code(engine) -> str:
    """Engine-type spellings over the years → one code: "BENSIIN HÜBRIID" →
    BENSIIN_HYBRIID, "BENSIIN KAT" → BENSIIN_KATALYSAATOR."""
    e = re.sub(r"[\s-]+", "_", up(engine).replace("Ü", "Y").replace("Ä", "A"))
    return {"BENSIIN_KAT": "BENSIIN_KATALYSAATOR"}.get(e, e)


def owner_code(owner) -> str:
    return up(owner).replace("Ü", "Y").replace("Ä", "A").replace("Õ", "O").replace("Ö", "O")


def fuel_class(engine: str, hybrid: str = "") -> str:
    """Engine type + EU hybrid type → BEV/PHEV/HEV/PETROL/DIESEL/OTHERS."""
    e, h = engine_code(engine), up(hybrid)
    if "FCHV" in h or "VESINIK" in e:
        return "OTHERS"
    if h == "OVC_HEV":
        return "PHEV"
    if h == "NOVC_HEV":
        return "HEV"
    if e == "ELEKTER":
        return "BEV"
    if "HYBRIID" in e:
        return "HEV"
    if e.startswith("BENSIIN"):
        return "PETROL"
    if e.startswith("DIISEL"):
        return "DIESEL"
    return "OTHERS"


def used_class(engine: str) -> str:
    """Engine type only (Kytus sheet) → BEV/HEV(combined)/PETROL/DIESEL/OTHERS."""
    return fuel_class(engine, "")


def is_known(engine: str, hybrid: str = "") -> bool:
    return engine_code(engine) in KNOWN_ENGINES and up(hybrid) in KNOWN_HYBRID


# ── workbook reading ───────────────────────────────────────────────────────

def norm(x) -> str:
    return re.sub(r"[^a-zõäöüšž0-9]", "", str(x or "").lower())


def num(x) -> int | None:
    """Cell → int (handles 3 005 with a no-break space, '12.0'); None if not a number."""
    if x is None or isinstance(x, bool):
        return None
    if isinstance(x, (int, float)):
        return int(round(x))
    s = str(x).replace("\xa0", "").replace(" ", "").replace(",", ".")
    try:
        return int(round(float(s)))
    except ValueError:
        return None


def read_sheets(blob: bytes) -> dict[str, list[list]]:
    """Workbook bytes (XLS or XLSX) → {sheet name: rows}."""
    if blob[:2] == b"PK":
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(blob), read_only=True, data_only=True)
        return {ws.title: [list(r) for r in ws.iter_rows(values_only=True)] for ws in wb}
    import xlrd
    wb = xlrd.open_workbook(file_contents=blob)
    return {s.name: [s.row_values(i) for i in range(s.nrows)] for s in wb.sheets()}


def find_sheet(sheets: dict, prefix: str) -> list[list]:
    for name, rows in sheets.items():
        if norm(name).startswith(prefix):
            return rows
    raise ValueError(f"sheet {prefix!r} not found (sheets: {list(sheets)}) — layout changed")


def _header(rows: list[list], first: str, within: int = 10) -> int:
    for i, r in enumerate(rows[:within]):
        if r and norm(r[0]) == first:
            return i
    raise ValueError(f"no header row starting with {first!r} — layout changed")


def parse_new(rows: list[list]) -> list[dict]:
    """"Uued sõidukid" → [{cat, brand, model, engine, hybrid, owner, n}].

    Header names moved over the years ("Mootori tüüp" / "MOOTORI_TYYP",
    "Hübriidi tüüp" / "HYBRIIDI_TYYP", "Arv" / "tk"); the owner type is the
    column just before the count ("Tüüp", "Tüüp (isik)", "V.KAS/OM TYYP")."""
    hi = _header(rows, "kategooria")
    h = [norm(c) for c in rows[hi]]
    counts = [i for i, c in enumerate(h) if c in ("arv", "tk")]
    if not counts:
        raise ValueError("'Uued sõidukid': no count column (Arv / tk)")
    ia = counts[-1]

    def col(pred):
        return next((i for i, c in enumerate(h) if pred(c)), None)
    ie = col(lambda c: c.startswith("mootori") and ("tüüp" in c or "tyyp" in c))
    ih = col(lambda c: c.startswith("hübriid") or c.startswith("hybriid"))
    ib = col(lambda c: c == "mark")
    im = col(lambda c: c == "mudel")
    if ie is None or ih is None or ib is None or im is None:
        raise ValueError(f"'Uued sõidukid': missing engine/hybrid/make/model column in {h}")
    io_ = ia - 1
    out = []
    for r in rows[hi + 1:]:
        if not r or len(r) <= ia:
            continue
        cat = up(r[0])
        n = num(r[ia])
        if not cat or n is None or cat.startswith("KOKKU"):
            continue
        out.append({"cat": cat, "brand": r[ib], "model": r[im], "engine": engine_code(r[ie]),
                    "hybrid": up(r[ih]), "owner": owner_code(r[io_]), "n": n})
    if not out:
        raise ValueError("'Uued sõidukid': no vehicle rows")
    return out


def parse_fuel_sheet(rows: list[list]) -> list[tuple[str, str, int, int]]:
    """"Kytus_esm ( sh uued)" → [(category, engine, first registrations, of which new)].
    Category sums sit in extra columns on a category's last row — ignored."""
    hi = _header(rows, "kategooria")
    out = []
    for r in rows[hi + 1:]:
        if not r or len(r) < 4:
            continue
        cat, eng, first, new = up(r[0]), up(r[1]), num(r[2]), num(r[3])
        if not cat or first is None or cat.startswith("KOKKU"):
            continue
        out.append((cat, eng, first, new or 0))
    if not out:
        raise ValueError("'Kytus_esm': no rows")
    return out


def parse_headline(rows: list[list]) -> dict[str, dict[str, int]]:
    """"Esm(üldtabel)" → {"all"|"new": {"cars", "lorries", "buses"}}."""
    hdr = None
    out = {}
    for r in rows:
        if not r:
            continue
        cells = [norm(c) for c in r]
        if hdr is None and any(c.startswith("sõiduautod") for c in cells):
            hdr = {k: next((i for i, c in enumerate(cells) if c.startswith(p)), None)
                   for k, p in (("cars", "sõiduautod"), ("lorries", "veoautod"),
                                ("buses", "bussid"))}
            continue
        if hdr is None:
            continue
        key = "all" if cells[0] == "kokku" else "new" if cells[0] == "shuued" else None
        if key and key not in out:
            out[key] = {k: num(r[i]) for k, i in hdr.items() if i is not None and i < len(r)}
    if "all" not in out or "new" not in out:
        raise ValueError("'Esm(üldtabel)': Kokku / sh uued rows not found")
    return out


# ── one month ──────────────────────────────────────────────────────────────

def zero() -> dict[str, int]:
    return {k: 0 for k in FUELS}


def build_month(sheets: dict) -> dict:
    """Workbook sheets → {"rows": {variant: counts}, "units": {...}, "checks": [...],
    "unknown": {variant: (n, labels)}, "no_category": n}."""
    new = parse_new(find_sheet(sheets, "uuedsõidukid"))
    fuel = parse_fuel_sheet(find_sheet(sheets, "kytus"))
    head = parse_headline(find_sheet(sheets, "esmüld"))

    rows = {v: zero() for v in VARIANT_CSV}
    unknown = collections.defaultdict(lambda: [0, set()])
    units = collections.Counter()
    no_cat = 0
    for rec in new:
        v = CATEGORY_VARIANT.get(rec["cat"])
        if v is None:
            continue
        cls = fuel_class(rec["engine"], rec["hybrid"])
        n = rec["n"]
        rows[v][cls] += n
        if not is_known(rec["engine"], rec["hybrid"]):
            unknown[v][0] += n
            unknown[v][1].add(f"{rec['engine']}/{rec['hybrid']}")
        if v == "Whole":
            if "HYBRIID" in rec["engine"] and not rec["hybrid"]:
                no_cat += n
            owner = rec["owner"]
            if owner not in KNOWN_OWNER:
                unknown["Private"][0] += n
                unknown["Private"][1].add(f"owner {owner}")
            rows["Private" if owner == PRIVATE_OWNER else "Industry"][cls] += n
            brand = display_brand(rec["brand"])
            units[(cls, brand, display_model(brand, rec["model"]))] += n
    used = zero()
    first_by = collections.Counter()
    new_by = collections.Counter()
    for cat, eng, first, nnew in fuel:
        grp = "cars" if cat in PASSENGER else "lorries" if cat in LORRY else \
              "buses" if cat in BUS else None
        if grp:
            first_by[grp] += first
            new_by[grp] += nnew
        if cat in PASSENGER:
            k = used_class(eng)
            used[k] += first - nnew
            if engine_code(eng) not in KNOWN_ENGINES:
                unknown["Used"][0] += first - nnew
                unknown["Used"][1].add(eng)
    used["HEV"] += used.pop("PHEV")
    rows["Used"] = used
    for v, r in rows.items():
        r["TOTAL"] = sum(r[k] for k in VARIANT_FUELS[v])

    new_cars = rows["Whole"]["TOTAL"]
    checks = [
        ("new passenger cars (Uued sõidukid vs sh uued)", new_cars, head["new"].get("cars")),
        ("new passenger cars (Kytus vs sh uued)", new_by["cars"], head["new"].get("cars")),
        ("first-registered passenger cars (Kytus vs Kokku)", first_by["cars"], head["all"].get("cars")),
        ("new lorries N1-N3 (Uued sõidukid vs sh uued)",
         rows["Vans"]["TOTAL"] + rows["HDV"]["TOTAL"], head["new"].get("lorries")),
        ("new buses M2-M3 (Uued sõidukid vs sh uued)", rows["Buses"]["TOTAL"], head["new"].get("buses")),
    ]
    return {"rows": rows, "units": dict(units), "checks": checks,
            "unknown": {v: (n, sorted(l)) for v, (n, l) in unknown.items()},
            "no_category": no_cat}


def check_failures(checks) -> list[str]:
    bad = []
    for label, got, ref in checks:
        if ref is None:
            continue
        if abs(got - ref) > max(XCHECK_MIN, XCHECK_TOL * ref):
            bad.append(f"{label}: {got} vs {ref}")
    return bad


# ── brand / model display ──────────────────────────────────────────────────

def display_brand(mark) -> str:
    b = market_top.clean(mark).split(",")[0].strip()
    # SKODA: the 2025-08 workbook spells the make without the háček.
    return {"VW": "VOLKSWAGEN", "MERCEDES BENZ": "MERCEDES-BENZ", "SKODA": "ŠKODA"}.get(b, b)


def display_model(brand: str, model) -> str:
    m = market_top.clean(model)
    if m in ("", "-"):
        return "(unnamed)"
    return market_top.strip_brand(brand, m)


# ── CSV line-level upsert (invariant 2) ────────────────────────────────────

def csv_columns(variant: str) -> list[str]:
    return (["period", "time_interval", "variant", "source"] + VARIANT_FUELS[variant]
            + ["TOTAL", "notes"])


def fmt(v: int) -> str:
    return f"{float(v):.1f}"


def render_line(period: str, variant: str, counts: dict[str, int], notes: str) -> str:
    buf = io.StringIO()
    csv.writer(buf, lineterminator="").writerow(
        [period, "monthly", variant, SOURCE]
        + [fmt(counts[k]) for k in VARIANT_FUELS[variant] + ["TOTAL"]] + [notes])
    return buf.getvalue()


def parse_line(line: str) -> list[str]:
    return next(csv.reader([line]))


def upsert_lines(path: Path, updates: dict[tuple[str, str], str], force: bool,
                 columns: list[str]) -> dict[str, int]:
    """Replace/insert only the given (period, variant) lines; every other line
    is written back byte for byte. New lines go in period order."""
    if path.exists():
        raw = path.read_bytes().decode("utf-8")
        eol = "\r\n" if "\r\n" in raw else "\n"
        lines = raw.splitlines()
        header, lines = (lines[0], lines[1:]) if lines else (",".join(columns), [])
    else:
        header, lines, eol = ",".join(columns), [], "\n"
    if header.split(",") != columns:
        sys.exit(f"{path}: unexpected header {header!r} (expected {columns})")
    stats = {"added": 0, "updated": 0, "unchanged": 0, "skipped": 0}
    index = {(f[0], f[2]): i for i, f in enumerate(parse_line(l) for l in lines)}
    for key, new in sorted(updates.items()):
        if key in index:
            old = lines[index[key]]
            src = parse_line(old)[3].strip()
            if old == new:
                stats["unchanged"] += 1
            elif src != SOURCE and src not in REPLACEABLE and not force:
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
            index = {(f[0], f[2]): i for i, f in enumerate(parse_line(l) for l in lines)}
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


def acea_note(old: dict | None, total: int) -> str:
    """When an ACEA row is replaced, keep ACEA's figure in the note (the
    correction trail: ACEA stays the cross-check of the legacy series)."""
    if not old or (old.get("source") or "").strip().upper() != "ACEA":
        return ""
    if old.get("time_interval") != "monthly" or not old.get("TOTAL"):
        return f"; replaces ACEA {old.get('time_interval')} row"
    keys = [k for k in ("BEV", "PHEV", "HEV", "PETROL", "DIESEL", "OTHERS") if old.get(k)]
    vals = " / ".join(f"{k} {int(float(old[k]))}" for k in keys)
    a = int(float(old["TOTAL"]))
    return f"; replaces ACEA (TOTAL {a}, {total - a:+d}; {vals})"


ACEA_TRAIL = "; replaces ACEA"


def row_notes(base: str, old: dict | None, total: int) -> str:
    """`base` plus the ACEA trail: written when an ACEA row is replaced and
    carried over when our own row is rewritten later (--backfill / --force),
    which would otherwise drop it — the old row is ours by then."""
    if old and (old.get("source") or "").strip() == SOURCE:
        prev = old.get("notes") or ""
        return base + (prev[prev.index(ACEA_TRAIL):] if ACEA_TRAIL in prev else "")
    return base + acea_note(old, total)


# ── network ────────────────────────────────────────────────────────────────

def find_workbooks(page: str) -> dict[str, str]:
    """Statistics page → {"YYYY-MM": url} for every "Infoleht MM-YY(YY)" link."""
    out = {}
    for m in re.finditer(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', page, re.S):
        href = html.unescape(m.group(1))
        text = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", m.group(2))).split())
        t = re.search(r"infoleht\s*(\d{1,2})\s*-\s*(\d{2}(?:\d{2})?)", text, re.I)
        if not t or not re.search(r"\.xlsx?($|\?)", href.lower()):
            continue
        mo, y = int(t.group(1)), int(t.group(2))
        y = y + 2000 if y < 100 else y
        if not 1 <= mo <= 12:
            continue
        url = href if href.startswith("http") else BASE_URL + href
        out.setdefault(f"{y}-{mo:02d}", url)
    return out


# ── checks & report ────────────────────────────────────────────────────────

def median_fraction(period: str, total: int, have: dict[str, dict]) -> float | None:
    prior = sorted(p for p in have if p < period and have[p].get("time_interval") == "monthly"
                   and have[p].get("TOTAL"))[-12:]
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
    ap.add_argument("--variant", default="all", help="all | " + " | ".join(VARIANT_CSV))
    ap.add_argument("--period", default="", help="Target month YYYY-MM (default: last month)")
    ap.add_argument("--backfill", action="store_true",
                    help=f"Read every workbook from {FIRST_PERIOD} on.")
    ap.add_argument("--force", action="store_true",
                    help="Ignore the self-throttle, the guards and foreign source strings.")
    ap.add_argument("--from-dir", default="", help="Offline: workbooks named YYYY-MM.xls[x].")
    ap.add_argument("--dump-dir", default="", help="Save every downloaded workbook here.")
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

    if (not args.backfill and not args.force
            and all(have[v].get(target, {}).get("source") == SOURCE for v in variants)):
        print(f"{target} already written from {SOURCE} in every CSV — nothing to do (no HTTP).")
        return emit(args, set())

    if args.from_dir:
        d = Path(args.from_dir)
        books = {f.stem[:7]: f for f in sorted(d.glob("*.xls*"))
                 if re.fullmatch(r"\d{4}-\d{2}", f.stem[:7])}
        load = lambda ref: Path(ref).read_bytes()  # noqa: E731
    else:
        import requests
        session = requests.Session()
        session.headers.update(UA)
        r = session.get(STATS_URL, timeout=120)
        r.raise_for_status()
        books = find_workbooks(r.text)

        def load(ref):
            resp = session.get(ref, timeout=300)
            resp.raise_for_status()
            if args.dump_dir:
                Path(args.dump_dir).mkdir(parents=True, exist_ok=True)
                ext = ".xlsx" if resp.content[:2] == b"PK" else ".xls"
                (Path(args.dump_dir) / f"{p}{ext}").write_bytes(resp.content)
            return resp.content
    if not books:
        sys.exit("No 'Infoleht' workbook links found on the statistics page — layout "
                 "changed? Not writing. See the runbook in 57-source-estonia.md.")
    if args.backfill:
        want = sorted(p for p in books if FIRST_PERIOD <= p <= target)
    else:
        # the target month plus any month since FIRST_PERIOD a CSV still lacks
        missing = {p for p in books if FIRST_PERIOD <= p <= target and
                   any(have[v].get(p, {}).get("source") != SOURCE for v in variants)}
        want = sorted(missing | ({target} & set(books)))[-6:]
    if not want:
        print(f"No workbook for {target} on the page yet — retry next run.")
        return emit(args, set())
    print("Workbooks: " + ", ".join(want))

    months: dict[str, dict] = {}
    problems: list[str] = []
    for p in want:
        try:
            months[p] = build_month(read_sheets(load(books[p])))
        except ValueError as e:
            problems.append(f"{p}: {e}")
            continue
        m = months[p]
        bad = check_failures(m["checks"])
        if bad and not args.force:
            problems.append(f"{p}: cross-check failed — " + "; ".join(bad))
        elif bad:
            print(f"::warning title=Estonia {p} cross-check (forced)::" + "; ".join(bad))
        for v, (n, labels) in m["unknown"].items():
            tot = m["rows"]["Whole" if v in ("Private", "Industry") else v]["TOTAL"] or 1
            if n / tot > MAX_UNKNOWN_SHARE:
                problems.append(f"{p} {v}: {n} vehicles ({n / tot:.1%}) with unknown values {labels}")
            elif labels:
                print(f"::warning title=New value {p} {v}::{labels} → mapped by rule")
        if m["no_category"]:
            print(f"  {p}: {m['no_category']} new car(s) with a hybrid engine but no EU "
                  "hybrid type → HEV")
    if problems:
        sys.exit("Governance check failed — not writing:\n  " + "\n  ".join(problems[:20]))

    changed: set[str] = set()
    report_rows = []
    periods = sorted(months)
    for v in variants:
        updates = {}
        for p in periods:
            row = months[p]["rows"][v]
            tot = row["TOTAL"]
            if tot == 0 and v not in ("Buses", "HDV"):
                continue
            frac = median_fraction(p, tot, have[v])
            if p == periods[-1] and frac is not None and not args.force and v in ("Whole", "Used"):
                if frac < MIN_MONTH_FRACTION:
                    print(f"{v} {p}: TOTAL {tot:,} is {frac:.0%} of the trailing median — "
                          "looks partial; not writing (--force if genuine).")
                    continue
                if frac < WARN_MONTH_FRACTION:
                    print(f"::warning title=Estonia {v} {p} unusually low::TOTAL {tot:,} = "
                          f"{frac:.0%} of the trailing-12 median — written; check it.")
            old = have[v].get(p)
            what = {"Used": "M1 first registrations minus new, by engine type; " + USED_HYBRID_NOTE,
                    "Private": "new M1, owner type FÜÜSILINE (private person)",
                    "Industry": "new M1, owner not a private person (legal person, state, foreign)"}.get(
                        v, "new vehicles by engine and EU hybrid type")
            notes = row_notes(f"Transpordiamet Infoleht {p}: {what}", old, tot)
            updates[(p, v)] = render_line(p, v, row, notes)
            report_rows.append((v, p, row, old))
        if args.dry_run:
            print(f"{VARIANT_CSV[v]}: dry run, {len(updates)} row(s) computed")
            continue
        stats = upsert_lines(paths[v], updates, args.force, csv_columns(v))
        print(f"{VARIANT_CSV[v]}: {stats}")
        if stats["added"] or stats["updated"]:
            changed.add(v)

    if not args.dry_run and "Whole" in variants:
        fresh = {p: (months[p]["units"], months[p]["rows"]["Whole"]["TOTAL"]) for p in periods}
        market_top.guarded(market_top.refresh_from_store, "Estonia",
                           "Transpordiamet (Infoleht, new vehicles)",
                           "new passenger cars (M1, incl. M1G) first registered in Estonia",
                           TOP_SLUG, fresh)

    rep = report(report_rows, target, months)
    print("\n" + rep)
    if args.step_summary:
        with open(args.step_summary, "a", encoding="utf-8") as fh:
            fh.write(rep)
    return emit(args, changed)


def report(rows, target: str, months: dict) -> str:
    out = [f"## Estonia (Transpordiamet) — up to {target}", ""]
    for p in sorted(months)[-3:]:
        out.append(f"- Cross-check {p}: " + "; ".join(
            f"{l} {g} = {r}" if g == r else f"{l} {g} vs {r}" for l, g, r in months[p]["checks"]))
    out += ["", "| variant | month | TOTAL | BEV | PHEV | HEV | PETROL | DIESEL | OTHERS | Δ TOTAL vs old row |",
            "|---|---|---:|---:|---:|---:|---:|---:|---:|---|"]
    for v, p, r, old in rows[-40:]:
        phev = "–" if "PHEV" not in VARIANT_FUELS[v] else f"{r['PHEV']:,}"
        d = ""
        if old and old.get("TOTAL"):
            d = f"{r['TOTAL'] - int(round(float(old['TOTAL']))):+d} ({old.get('source')})"
        out.append(f"| {v} | {p} | {r['TOTAL']:,} | {r['BEV']:,} | {phev} | {r['HEV']:,} | "
                   f"{r['PETROL']:,} | {r['DIESEL']:,} | {r['OTHERS']:,} | {d} |")
    return "\n".join(out) + "\n"


def emit(args, changed: set[str]) -> int:
    if args.github_output:
        with open(args.github_output, "a", encoding="utf-8") as f:
            f.write(f"changed={'true' if changed else 'false'}\n")
            f.write(f"changed_variants={json.dumps(sorted(changed))}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
