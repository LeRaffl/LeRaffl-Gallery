#!/usr/bin/env python3
"""
Fetch Argentina new-registration data from the DNRPA open-data microdata
and upsert data/Argentina*.csv (Whole + Private + Industry + Pickups).

Source
------
DNRPA (Dirección Nacional de los Registros Nacionales de la Propiedad del
Automotor y de Créditos Prendarios, Ministerio de Justicia) publishes one
record per *inscripción inicial* (first registration) on the Justice
Ministry's CKAN portal — free, no login, no ID number, CSV:

    https://datos.jus.gob.ar/dataset/inscripciones-iniciales-de-autos

  * one zip per year (`dnrpa-inscripciones-iniciales-autos-YYYY.zip`, one
    CSV member per month, refreshed monthly for the current year), plus
  * the newest month as a loose CSV (`…-autos-YYYYMM.csv`).

Resources are discovered through the CKAN API (`package_show`), never by
hard-coded URL: the resource ids change when DNRPA re-uploads a file.
DNRPA publishes month M around the 11th of M+1. It is the registry itself
(every 0 km registration, every brand — BYD and the other Chinese imports
included), and since March 2026 it is also the registry behind ACARA's
monthly market report, which is co-signed "DNRPA-ACARA".

Why this source clears the bar that shelved Argentina in 2026-05
(docs/architecture/14-data-source-gaps.md): the ACARA/SIOMAA electromobility
report is paid and ID-gated; this open dataset is neither, and because it is
record-level we can build the full fuel split ourselves.

What the records do NOT carry: a fuel / propulsion field. The powertrain is
recovered from the model designation (`automotor_modelo_descripcion`), which
in Argentina spells out the drivetrain for almost every electrified car
("DOLPHIN MINI EV GS", "ATTO 2 DM-I GS", "COROLLA CROSS XEI HEV 1.8 ECVT",
"TIGGO 7 PRO HYBRID 1.5T MHEV", …). `classify_rule()` walks a first-match
rule table that lives in DATA, not code — classification/argentina_rules.csv
(one row per rule: id, class, brand scope, pattern, reason, evidence, a real
example) — made of generic tokens plus brand-scoped rules for the
designations that do not say it (Volvo "T8", BMW "330E", Toyota "HV", BYD
naming, …) and for the traps where a generic token lies ("HYBRID" on a 12 V
Suzuki, a 48 V Stellantis car or the Argentine Arkana is a mild hybrid,
"PACK ELECTRICO" on a Hilux is electric windows, a DS "T8" is an 8-speed
gearbox). Validated against ACARA's published electrified totals —
docs/architecture/39-source-argentina.md §4–5.

Every run also writes classification/argentina_models.csv (every
designation ever registered in scope → class → deciding rule, units,
first/last seen) and classification/argentina_top.json (top BEV/PHEV/…
brands and designations, last 12 months); the source page renders both.
New designations and ICE-classified designations of new-energy brands are
reported in the log and the GitHub step summary (the new-vehicle net, §7).

There is no petrol/diesel split to recover reliably from model strings, so
the combustion remainder goes into the `ICE` column (Chile/Colombia
convention); PETROL/DIESEL are simply not in the file (invariant 4: no
fabricated fuel split).

Variants — one download, one pass, every CSV
--------------------------------------------
Only true new registrations count: `tramite_tipo` ∈ {INSCRIPCION INICIAL
NACIONAL, INSCRIPCION INICIAL IMPORTADO}. Classic cars, auctioned vehicles
(Form. 05) and registrations "x dictamen/oficio" are excluded.

  Whole     data/Argentina.csv           passenger-car body types (≈ EU M1):
                                         sedán, rural (SUV/estate), todo
                                         terreno, coupé, convertible,
                                         familiar, … — `body_class() == "M1"`.
  Private   data/Argentina_Private.csv   Whole ∧ first owner is a natural
                                         person (titular_tipo_persona Física).
  Industry  data/Argentina_Industry.csv  Whole ∧ first owner is a legal
                                         person (Jurídica). Private+Industry
                                         = Whole exactly.
  Pickups   data/Argentina_Pickups.csv   every PICK-UP body type (simple,
                                         doble, cabina y media, carrozada) —
                                         Canada/Indonesia-style country
                                         variant; overwhelmingly N1.

Vans / HDV / Buses are deliberately not produced: the records carry no
gross weight or seat count, and the FURGÓN / CHASIS / TRANS. DE PASAJEROS
body types mix N1 with N2 (Sprinter 314 vs 517) and M1 with M2/M3, so they
cannot be anchored to the EU classes (glossary invariant). Quadricycles
(L6/L7: Coradir Tita, Sero, XEV Yoyo) are EU L-category and not in Whole.

Writes are line-level upserts keyed on (period, variant): untouched lines
stay byte-identical (invariant 2). Every real run re-derives the FULL history
from the yearly zips (2018 →), so a rule change re-classifies every past
month and DNRPA's corrections to any year land (it re-uploads past years —
the 2025 zip was refreshed in 2026-08); only lines whose numbers changed are
rewritten.

Usage
-----
    python scripts/fetch_argentina.py                    # previous month
    python scripts/fetch_argentina.py --period 2026-08
    python scripts/fetch_argentina.py --backfill         # 2018-01 → now
    python scripts/fetch_argentina.py --from-agg agg.csv # offline, see below

`--from-agg` reads a pre-aggregated CSV (month, tramite, tipo, marca, modelo,
persona, n) instead of downloading — used to test the classifier offline.
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
import unicodedata
import zipfile
from datetime import date
from pathlib import Path

import requests

SOURCE = "DNRPA"
PACKAGE_URL = ("https://datos.jus.gob.ar/api/3/action/package_show"
               "?id=inscripciones-iniciales-de-autos")
BACKFILL_FROM_DEFAULT = "2018-01"   # first month of the microdata

VARIANT_CSV = {
    "Whole":    "data/Argentina.csv",
    "Private":  "data/Argentina_Private.csv",
    "Industry": "data/Argentina_Industry.csv",
    "Pickups":  "data/Argentina_Pickups.csv",
}
FUELS = ["BEV", "PHEV", "EREV", "HEV", "MHEV", "ICE"]
CSV_COLUMNS = (["period", "time_interval", "variant", "source"]
               + FUELS + ["TOTAL", "notes"])

NEW_TRAMITES = {"INSCRIPCION INICIAL NACIONAL", "INSCRIPCION INICIAL IMPORTADO"}

HTTP_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (compatible; LeRaffl-Gallery/1.0; "
                   "+https://leraffl.github.io/LeRaffl-Gallery/)"),
}

# A newly published month whose Whole total falls below this fraction of the
# trailing-12 median is treated as an incomplete upload and not written
# (--force overrides; backfills skip the check — 2020-04 was genuinely ~10 %).
MIN_MONTH_FRACTION = 0.4


# ── scope ──────────────────────────────────────────────────────────────────

def norm(s: str) -> str:
    """Upper-case, strip accents, collapse whitespace."""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", s.upper()).strip()


_M1_BODY = re.compile(
    r"^(SEDAN|RURAL|TODO TERRENO|CAMIONETA TODO TERRENO|COUPE|DESCAPOTABLE|"
    r"CONVERTIBLE|CONVER$|CABRIOLET|ROADSTER|FAMILIAR|AUTOMOVIL|"
    r"STATION WAGON|SUV|JEEP|SPORT|BERLINA|LIMOUSINE|LIMUSINA|MICRO ?COUPE|"
    r"TWO ?DOOR|PHAETON|TRANSFORMABILE|SPIDER|SPYDER|SPEEDSTER|TARGA|4X4$)")
_PICKUP_BODY = re.compile(r"^(PICK ?-? ?UP|PCK UP)")


def body_class(tipo: str) -> str | None:
    """'M1' (Whole), 'PICKUP' or None (out of scope) for a DNRPA body type."""
    t = norm(tipo)
    if _PICKUP_BODY.match(t):
        return "PICKUP"
    if _M1_BODY.match(t):
        return "M1"
    return None


# ── powertrain classifier ──────────────────────────────────────────────────
#
# The rules are DATA, not code: classification/argentina_rules.csv, one row
# per rule, evaluated top to bottom, first match wins. Columns:
#
#   order    evaluation order (must be 1..N, no gaps — the tests check it)
#   id       stable slug; written into classification/argentina_models.csv
#            next to every designation it decides, so "why is X a PHEV?" is
#            always one lookup away
#   class    BEV | PHEV | EREV | HEV | MHEV | ICE (ICE rows are explicit
#            exclusions that must win over a later token rule)
#   brand    regex on the normalised brand (automotor_marca_descripcion);
#            empty = any brand
#   pattern  regex on the normalised designation (automotor_modelo_descripcion)
#   kind     exclusion | token | brand-code | model | brand-all (documentation
#            only — see docs/architecture/39-source-argentina.md §4)
#   reason / evidence   why the rule exists and how it was verified
#   example_brand / example_model   a real designation this rule decides; the
#            tests assert that it is classified by THIS rule (so a rule that
#            gets shadowed by an earlier one fails CI). Empty for rules written
#            ahead of the first registration ("anticipatory").
#
# "Normalised" = upper-case, accents stripped, whitespace collapsed (norm()).
# Anything that matches no rule is ICE ("default-ice").

REPO = Path(__file__).resolve().parent.parent
RULES_CSV = REPO / "classification" / "argentina_rules.csv"
MODELS_CSV = REPO / "classification" / "argentina_models.csv"
TOP_JSON = REPO / "classification" / "argentina_top.json"
CLASSES = {"BEV", "PHEV", "EREV", "HEV", "MHEV", "ICE"}
DEFAULT_RULE = "default-ice"


def load_rules(path: Path = RULES_CSV) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as fh:
        rules = list(csv.DictReader(fh))
    for r in rules:
        if r["class"] not in CLASSES:
            raise ValueError(f"rule {r['id']}: unknown class {r['class']!r}")
        r["_brand"] = re.compile(r["brand"]) if r["brand"] else None
        r["_pattern"] = re.compile(r["pattern"])
    return rules


RULES = load_rules()


def classify_rule(marca: str, modelo: str) -> tuple[str, str]:
    """(class, rule id) for one brand + designation."""
    b, m = norm(marca), norm(modelo)
    for r in RULES:
        if r["_brand"] is not None and not r["_brand"].search(b):
            continue
        if r["_pattern"].search(m):
            return r["class"], r["id"]
    return "ICE", DEFAULT_RULE


def classify(marca: str, modelo: str) -> str:
    return classify_rule(marca, modelo)[0]


# Safety net for new vehicles: ICE-classified designations of these brands
# are listed in the run log and the GitHub step summary every run, so a new
# electrified designation that no rule catches is visible the month it is
# first registered. Chinese makers (most of Argentina's electrified imports
# under the 0 %-duty quota) plus the premium brands whose plug-ins hide
# behind codes. Extend freely — it only affects reporting, never the data.
REVIEW_BRANDS = re.compile(
    r"^(CHERY|JAC|JETOUR|GEELY|GREAT WALL|HAVAL|GWM|TANK|CHANGAN|DONGFENG|"
    r"DFAC DONGFENG|BAIC|GAC|FORTHING|KAIYI|DFSK|SHINERAY|SWM|MG|HONGQI|"
    r"MAXUS|FOTON|JMC|KYC|OMODA|JAECOO|WULING|SOUEAST|EXEED|LYNK & CO|"
    r"VOLVO|BMW|MINI|MERCEDES BENZ|AUDI|PORSCHE|LAND ROVER|LEXUS|FERRARI|"
    r"MASERATI|LAMBORGHINI|MCLAREN|BENTLEY|ROLLS ROYCE|ACURA|GENESIS)$")


# ── aggregation ────────────────────────────────────────────────────────────

def empty_counts() -> dict[str, int]:
    return {k: 0 for k in FUELS + ["TOTAL"]}


class Aggregator:
    def __init__(self) -> None:
        # period -> variant -> counts
        self.counts: dict[str, dict[str, dict[str, int]]] = \
            collections.defaultdict(lambda: collections.defaultdict(empty_counts))
        # (scope, brand, designation) -> period -> units, scope ∈ {Whole, Pickups}
        self.designations: dict[tuple[str, str, str], collections.Counter] = \
            collections.defaultdict(collections.Counter)
        self._cls_cache: dict[tuple[str, str], tuple[str, str]] = {}

    def classify_cached(self, marca: str, modelo: str) -> tuple[str, str]:
        key = (norm(marca), norm(modelo))
        hit = self._cls_cache.get(key)
        if hit is None:
            hit = self._cls_cache[key] = classify_rule(*key)
        return hit

    def add(self, period: str, tramite: str, tipo: str, marca: str,
            modelo: str, persona: str, n: int = 1) -> None:
        if norm(tramite) not in NEW_TRAMITES:
            return
        body = body_class(tipo)
        if body is None:
            return
        fuel, _ = self.classify_cached(marca, modelo)
        if body == "PICKUP":
            variants = ["Pickups"]
        else:
            p = norm(persona)[:1]
            variants = ["Whole"] + (["Private"] if p == "F"
                                    else ["Industry"] if p == "J" else [])
        for v in variants:
            c = self.counts[period][v]
            c[fuel] += n
            c["TOTAL"] += n
        self.designations[(variants[0], norm(marca), norm(modelo))][period] += n

    def add_csv(self, fh) -> int:
        k = 0
        for row in csv.DictReader(fh):
            self.add((row.get("tramite_fecha") or "")[:7],
                     row.get("tramite_tipo") or "",
                     row.get("automotor_tipo_descripcion") or "",
                     row.get("automotor_marca_descripcion") or "",
                     row.get("automotor_modelo_descripcion") or "",
                     row.get("titular_tipo_persona") or "")
            k += 1
        return k


# ── classification outputs (mapping table, top models, review) ─────────────

MODELS_COLUMNS = ["brand", "model", "scope", "class", "rule", "units_total",
                  "units_last_12m", "first_seen", "last_seen"]


def month_window(target: str, months: int = 12) -> list[str]:
    y, m = map(int, target.split("-"))
    out = []
    for _ in range(months):
        out.append(f"{y}-{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return sorted(out)


def build_models_rows(agg: Aggregator, target: str) -> list[dict]:
    window = set(month_window(target))
    rows = []
    for (scope, brand, model), per in agg.designations.items():
        periods = sorted(p for p in per if p <= target)
        if not periods:
            continue
        cls, rule = agg.classify_cached(brand, model)
        rows.append({
            "brand": brand, "model": model, "scope": scope,
            "class": cls, "rule": rule,
            "units_total": sum(per[p] for p in periods),
            "units_last_12m": sum(per[p] for p in periods if p in window),
            "first_seen": periods[0], "last_seen": periods[-1],
        })
    rows.sort(key=lambda r: (r["brand"], r["model"], r["scope"]))
    return rows


def write_if_changed(path: Path, text: str) -> bool:
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return True


def write_models_csv(rows: list[dict], path: Path = MODELS_CSV) -> bool:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=MODELS_COLUMNS, lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    return write_if_changed(path, buf.getvalue())


def _ranked(counter: collections.Counter, n: int) -> list:
    return sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))[:n]


def build_top(agg: Aggregator, target: str, variant: str = "Whole",
              top_brands: int = 10, top_models: int = 15) -> dict:
    """Generic top-brands/top-models summary (schema documented in
    docs/architecture/39-source-argentina.md §6 — reusable by any country)."""
    window = month_window(target)
    total = sum(agg.counts[p][variant]["TOTAL"] for p in window)
    per_class = {c: {"brands": collections.Counter(),
                     "models": collections.Counter()} for c in FUELS}
    for (scope, brand, model), per in agg.designations.items():
        if scope != variant:
            continue
        units = sum(per[p] for p in window)
        if not units:
            continue
        cls, _ = agg.classify_cached(brand, model)
        per_class[cls]["brands"][brand] += units
        per_class[cls]["models"][(brand, model)] += units
    classes = {}
    for cls in FUELS:
        cls_units = sum(per_class[cls]["brands"].values())
        if cls == "ICE" or not cls_units:
            continue
        classes[cls] = {
            "units": cls_units,
            "share_of_market": round(cls_units / total, 5) if total else None,
            # Ties are broken alphabetically so the file is byte-stable no
            # matter in which order the records arrived (no spurious commits).
            "brands": [{"brand": b, "units": u,
                        "share_of_class": round(u / cls_units, 4)}
                       for b, u in _ranked(per_class[cls]["brands"], top_brands)],
            "models": [{"brand": b, "model": m, "units": u,
                        "share_of_class": round(u / cls_units, 4)}
                       for (b, m), u in _ranked(per_class[cls]["models"], top_models)],
        }
    return {
        "country": "Argentina", "variant": variant, "source": SOURCE,
        "as_of": target, "window": {"from": window[0], "to": window[-1],
                                    "months": len(window)},
        "total_registrations": total,
        "unit": "registrations (designation = exact DNRPA model string)",
        "classes": classes,
    }


def write_top_json(top: dict, path: Path = TOP_JSON) -> bool:
    return write_if_changed(path, json.dumps(top, ensure_ascii=False, indent=1) + "\n")


def review_report(rows: list[dict], target: str, top: int = 25) -> str:
    """Markdown for the log and $GITHUB_STEP_SUMMARY: the new-vehicle net."""
    out = []
    new = [r for r in rows if r["first_seen"] == target]
    out.append(f"### New designations first registered in {target} ({len(new)})\n")
    if new:
        out.append("Every designation DNRPA had never registered before, with the "
                   "class and the rule that decided it. **Check every ⚠️ row** "
                   "(ICE from a brand with electrified models) against the "
                   "importer's spec sheet; if it is electrified, add a rule "
                   "(docs/architecture/39-source-argentina.md §7).\n")
        out.append("| | brand | designation | scope | units | class | rule |")
        out.append("|---|---|---|---|---:|---|---|")
        for r in sorted(new, key=lambda r: (-int(r["units_total"]), r["brand"])):
            flag = "⚠️" if (r["class"] == "ICE" and REVIEW_BRANDS.match(r["brand"])) else ""
            out.append(f"| {flag} | {r['brand']} | {r['model']} | {r['scope']} | "
                       f"{r['units_total']} | {r['class']} | `{r['rule']}` |")
    else:
        out.append("None.")
    ice = sorted((r for r in rows if r["class"] == "ICE" and r["units_last_12m"]
                  and REVIEW_BRANDS.match(r["brand"])),
                 key=lambda r: -int(r["units_last_12m"]))[:top]
    out.append(f"\n### Largest ICE-classified designations of new-energy brands "
               f"(last 12 months, top {top})\n")
    out.append("A hybrid or EV hiding behind a designation with no marker would "
               "sit here.\n")
    out.append("| brand | designation | scope | units 12m | first seen |")
    out.append("|---|---|---|---:|---|")
    for r in ice:
        out.append(f"| {r['brand']} | {r['model']} | {r['scope']} | "
                   f"{r['units_last_12m']} | {r['first_seen']} |")
    unused = [r["id"] for r in RULES if not any(x["rule"] == r["id"] for x in rows)]
    out.append(f"\n### Rules that decide no registration yet ({len(unused)})\n")
    out.append(", ".join(f"`{u}`" for u in unused) or "None.")
    return "\n".join(out) + "\n"


# ── download ───────────────────────────────────────────────────────────────

def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HTTP_HEADERS)
    return s


def list_resources(session: requests.Session) -> list[dict]:
    r = session.get(PACKAGE_URL, timeout=60)
    r.raise_for_status()
    return r.json()["result"]["resources"]


def find_resource(resources: list[dict], suffix: str) -> str | None:
    for res in resources:
        url = res.get("url") or ""
        if url.endswith(suffix):
            return url
    return None


def ingest_year(session, resources, year: int, agg: Aggregator) -> str | None:
    url = find_resource(resources, f"-autos-{year}.zip")
    if not url:
        return None
    r = session.get(url, timeout=900)
    r.raise_for_status()
    z = zipfile.ZipFile(io.BytesIO(r.content))
    for name in sorted(z.namelist()):
        if name.lower().endswith(".csv"):
            with z.open(name) as fh:
                k = agg.add_csv(io.TextIOWrapper(fh, encoding="utf-8-sig"))
            print(f"  {name}: {k:,} records")
    return url


def ingest_month_csv(session, resources, period: str,
                     agg: Aggregator) -> str | None:
    url = find_resource(resources, f"-autos-{period.replace('-', '')}.csv")
    if not url:
        return None
    r = session.get(url, timeout=600)
    r.raise_for_status()
    k = agg.add_csv(io.StringIO(r.content.decode("utf-8-sig")))
    print(f"  {url.rsplit('/', 1)[-1]}: {k:,} records")
    return url


def ingest_agg_file(path: str, agg: Aggregator) -> None:
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            agg.add(row["month"], row["tramite"], row["tipo"], row["marca"],
                    row["modelo"], row["persona"], int(row["n"]))


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
                stats["skipped"] += 1           # someone else's row
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
    """period -> row dict, for the self-throttle and the sanity check."""
    if not path.exists():
        return {}
    with open(path, newline="", encoding="utf-8") as f:
        return {r["period"]: r for r in csv.DictReader(f)}


# ── main ───────────────────────────────────────────────────────────────────

def previous_month(today: date) -> str:
    if today.month == 1:
        return f"{today.year - 1}-12"
    return f"{today.year}-{today.month - 1:02d}"


def looks_incomplete(period: str, total: int, have: dict[str, dict]) -> bool:
    prior = sorted(p for p in have if p < period)[-12:]
    if len(prior) < 6:
        return False
    vals = sorted(float(have[p]["TOTAL"]) for p in prior)
    median = vals[len(vals) // 2]
    return total < MIN_MONTH_FRACTION * median


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--variant", default="all",
                    help=f"all | {' | '.join(VARIANT_CSV)} (default: all)")
    ap.add_argument("--period", default="",
                    help="Target month YYYY-MM (default: previous month).")
    ap.add_argument("--backfill", action="store_true",
                    help="Treat the run as a (re)build of history: skips the "
                         "incomplete-month guard. Every real run re-derives "
                         "the full history anyway. Implied when a selected "
                         "CSV does not exist yet.")
    ap.add_argument("--backfill-from", default=BACKFILL_FROM_DEFAULT)
    ap.add_argument("--force", action="store_true",
                    help="Ignore the self-throttle, the completeness check "
                         "and foreign source strings. Use after a rule change "
                         "so the whole history is re-classified.")
    ap.add_argument("--from-agg", default="",
                    help="Offline: read a pre-aggregated CSV instead of "
                         "downloading (implies --backfill).")
    ap.add_argument("--github-output", default=os.environ.get("GITHUB_OUTPUT"))
    ap.add_argument("--step-summary", default=os.environ.get("GITHUB_STEP_SUMMARY"))
    args = ap.parse_args()

    variants = list(VARIANT_CSV) if args.variant == "all" else [args.variant]
    for v in variants:
        if v not in VARIANT_CSV:
            sys.exit(f"Unknown variant {v!r}. Valid: {list(VARIANT_CSV)} or all.")
    paths = {v: Path(VARIANT_CSV[v]) for v in variants}
    have = {v: existing_periods(paths[v]) for v in variants}

    target = args.period or previous_month(date.today())
    backfill = (args.backfill or bool(args.from_agg)
                or any(not paths[v].exists() for v in variants))

    if not backfill and not args.force and all(
            have[v].get(target, {}).get("source") == SOURCE for v in variants):
        print(f"{target} already fetched from {SOURCE} for {variants}; "
              "nothing to do.")
        return emit(args, set())

    # Every real run re-derives the FULL history (2018 →): nine yearly zips,
    # ~100 MB, a few minutes, once or twice a month. That keeps the CSVs, the
    # mapping table and the rules consistent by construction — a rule added
    # today re-classifies 2019 as well, and DNRPA corrections to any year land.
    agg = Aggregator()
    urls: list[str] = []
    if args.from_agg:
        ingest_agg_file(args.from_agg, agg)
        urls.append(args.from_agg)
    else:
        session = make_session()
        resources = list_resources(session)
        for year in range(int(args.backfill_from[:4]), int(target[:4]) + 1):
            print(f"Year {year}:")
            url = ingest_year(session, resources, year, agg)
            if url:
                urls.append(url)
            else:
                print(f"  no yearly zip for {year} on the portal")
        if target not in agg.counts:
            url = ingest_month_csv(session, resources, target, agg)
            if url:
                urls.append(url)

    if target not in agg.counts:
        print(f"{target} is not published on datos.jus.gob.ar yet — will "
              "retry on the next scheduled run.")
        return emit(args, set())

    periods = sorted(p for p in agg.counts if args.backfill_from <= p <= target)

    whole_total = agg.counts[target]["Whole"]["TOTAL"]
    if (not backfill and not args.force and "Whole" in variants
            and looks_incomplete(target, whole_total, have["Whole"])):
        print(f"{target}: Whole TOTAL {whole_total:,} is below "
              f"{MIN_MONTH_FRACTION:.0%} of the trailing median — looks like "
              "an incomplete upload; not writing. Re-run with --force if the "
              "month is genuinely that small.")
        return emit(args, set())

    changed: set[str] = set()
    for v in variants:
        updates = {(p, v): render_line(p, v, agg.counts[p][v])
                   for p in periods if agg.counts[p][v]["TOTAL"] > 0}
        stats = upsert_lines(paths[v], updates, args.force)
        print(f"{VARIANT_CSV[v]}: {stats}")
        if stats["added"] or stats["updated"]:
            changed.add(v)

    # Classification outputs: the full designation → class → rule mapping and
    # the top brands/models. Committed next to the data; the source page
    # renders both (build_source_pages.py).
    rows = build_models_rows(agg, target)
    top = build_top(agg, target)
    print(f"{MODELS_CSV.relative_to(REPO)}: "
          f"{'updated' if write_models_csv(rows) else 'unchanged'} ({len(rows):,} designations)")
    print(f"{TOP_JSON.relative_to(REPO)}: "
          f"{'updated' if write_top_json(top) else 'unchanged'}")

    t = agg.counts[target]
    lines = [f"## Argentina (DNRPA) — {target}\n",
             "| variant | BEV | PHEV | EREV | HEV | MHEV | ICE | TOTAL | BEV share |",
             "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for v in variants:
        c = t[v]
        tot = c["TOTAL"] or 1
        print(f"{target} {v:8s} " + " ".join(f"{k}={c[k]:,}" for k in FUELS)
              + f" TOTAL={c['TOTAL']:,}  BEV share {c['BEV'] / tot:.2%}")
        lines.append(f"| {v} | " + " | ".join(f"{c[k]:,}" for k in FUELS)
                     + f" | {c['TOTAL']:,} | {c['BEV'] / tot:.2%} |")
    report = "\n".join(lines) + "\n\n" + review_report(rows, target)
    print("\n" + report)
    if args.step_summary:
        with open(args.step_summary, "a", encoding="utf-8") as fh:
            fh.write(report)
    print("Sources: " + ", ".join(urls))
    return emit(args, changed)


def emit(args, changed: set[str]) -> int:
    if args.github_output:
        with open(args.github_output, "a", encoding="utf-8") as f:
            f.write(f"changed={'true' if changed else 'false'}\n")
            f.write(f"changed_variants={json.dumps(sorted(changed))}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
