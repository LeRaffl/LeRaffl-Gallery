#!/usr/bin/env python3
"""
Fetch Switzerland registration data from ASTRA's record-level IVZ open data
and upsert data/Switzerland*.csv (Whole + Vans + HDV + Buses + Used +
2-Wheelers).

Source
------
ASTRA (Bundesamt für Strassen) publishes extracts of the national vehicle
register IVZ (Informationssystem Verkehrszulassung) as open data — free, no
login, tab-separated UTF-8 text, one row per vehicle:

    https://opendata.astra.admin.ch/ivzod/1000-Fahrzeuge_IVZ/
      1200-Neuzulassungen/1210-Datensaetze_monatlich/NEUZU.txt
          every first registration in CH/FL of the running year, refreshed
          every two weeks (data as of the 1st and the middle of the month);
          in January it still holds the whole previous year
      1200-…/1213-Vorjahresdaten/NEUZU-<YYYY>.txt     closed years, 2016+
      1500-Gebrauchtimporte/GEBR.txt                  used imports, monthly
      1500-…/1503-Vorjahresdaten/GEBR-<YYYY>.txt      closed years, 2017+

The server's WAF rejects a bare "Mozilla/5.0" user agent and requests without
an Accept header — HTTP_HEADERS below pass it.

Variants — one pass over the records, every CSV
-----------------------------------------------
Every filter is the register's own EU vehicle class (Fahrzeugklasse) plus its
vehicle kind (Fahrzeugart). Each one was calibrated against ACEA, which the
maintainer treats as the source of truth for the cross-check (see
docs/architecture/46-source-switzerland.md §4 for the numbers):

  Whole       data/Switzerland.csv             M1 ∧ Fahrzeugart = Personenwagen
                                               (campers and other "Leichter
                                               Motorwagen" are M1 too but not
                                               cars — ACEA leaves them out)
  Vans        data/Switzerland_Vans.csv        N1 ∧ Fahrzeugart = Lieferwagen
  HDV         data/Switzerland_HDV.csv         N2/N3 ∧ Fahrzeugart ∈ {Lastwagen,
                                               Sattelschlepper} (lorries and
                                               tractor units; not work machines)
  Buses       data/Switzerland_Buses.csv       M2/M3 ∧ gross weight > 3.5 t
                                               (ACEA's "buses and coaches")
  2-Wheelers  data/Switzerland_2-Wheelers.csv  L1 (mopeds) + L3 (motorcycles);
                                               trikes, sidecars and quads out
  Used        data/Switzerland_Used.csv        GEBR (used imports — first
                                               registered abroad) with
                                               Fahrzeugart = Personenwagen

Liechtenstein is in every variant: CH and FL are one registration market (one
register, a customs union) and ACEA's Swiss figure includes it. Vehicles taken
off the road since are still counted (they were registered new that month).

Fuel → columns (Treibstoff_Code, Hybridcode)
--------------------------------------------
  E Elektrisch                         → BEV
  R Elektrisch mit Range Extender      → PHEV (EREV folds into PHEV, as ACEA)
  C / F Benzin|Diesel / Elektrisch     → PHEV if Hybridcode = OVC-HEV,
                                         HEV  if Hybridcode = NOVC-HEV;
                                         without a hybrid code (vehicles on a
                                         national type approval): PHEV if an
                                         electric consumption is recorded or
                                         CO2 ≤ 60 g/km, else HEV.
                                         Mild hybrids are HEV — as at ACEA.
  B Benzin                             → PETROL
  D Diesel                             → DIESEL
  everything else (gas, hydrogen, …)   → OTHERS

Month attribution — the ACEA rule
---------------------------------
ACEA's Swiss months are year-to-date totals at a cut-off shortly after month
end, differenced: a car registered on 30 June but keyed into the register on
2 July counts in July. The register itself dates it 30 June. To reproduce
ACEA, a live month M is written ONCE, from the first snapshot after M ends:

    M = (snapshot's year-to-date through M) − (rows already in the CSV for
        the earlier months of that year)

so late registrations for already-written months flow into M, and nothing
written is ever revised (invariant 3). History (--backfill, closed years)
has no snapshots left, so it is counted by registration month from the
year-end files.

Modes
-----
* Monthly (default): read the newest snapshot (a 16 KB range request first —
  exits without downloading ~90 MB when every CSV already has the month), then
  write each variant's newest complete month by the ACEA rule. Also refreshes
  market/switzerland_top.json.
* --backfill [--from YYYY]: count closed years from the year files (NEUZU
  2016+, GEBR 2017+) plus the running year from the current snapshot, by
  registration month, for every month a CSV does not have yet. Implied for a
  variant whose CSV does not exist.
* --acea-check: compare the newest ASTRA months of data/Switzerland.csv with
  ACEA's press release for that month (when it is out) and warn on a gap.

Overwrite rule: a row whose source is not "ASTRA" is never touched without
--force (the BFS/ACEA history of Whole stays as it is).

Usage
-----
    python scripts/fetch_switzerland.py
    python scripts/fetch_switzerland.py --variant Vans --backfill --from 2016
    python scripts/fetch_switzerland.py --acea-check
"""
from __future__ import annotations

import argparse
import collections
import csv
import datetime as dt
import io
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import market_top  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
SOURCE = "ASTRA"

BASE = "https://opendata.astra.admin.ch/ivzod/1000-Fahrzeuge_IVZ/"
NEUZU_URL = BASE + "1200-Neuzulassungen/1210-Datensaetze_monatlich/NEUZU.txt"
NEUZU_YEAR_URL = (BASE + "1200-Neuzulassungen/1210-Datensaetze_monatlich/"
                  "1213-Vorjahresdaten/NEUZU-{year}.txt")
GEBR_URL = BASE + "1500-Gebrauchtimporte/GEBR.txt"
GEBR_YEAR_URL = BASE + "1500-Gebrauchtimporte/1503-Vorjahresdaten/GEBR-{year}.txt"

NEUZU_FIRST_YEAR = 2016   # NEUZU_ARCHIV-2011..2015 has no EU class / hybrid data
GEBR_FIRST_YEAR = 2017

HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.8",
    "Accept-Language": "de-CH,de;q=0.9,en;q=0.8",
}

VARIANT_CSV: dict[str, str] = {
    "Whole":      "data/Switzerland.csv",
    "Vans":       "data/Switzerland_Vans.csv",
    "HDV":        "data/Switzerland_HDV.csv",
    "Buses":      "data/Switzerland_Buses.csv",
    "2-Wheelers": "data/Switzerland_2-Wheelers.csv",
    "Used":       "data/Switzerland_Used.csv",
}
NEUZU_VARIANTS = ("Whole", "Vans", "HDV", "Buses", "2-Wheelers")
GEBR_VARIANTS = ("Used",)

FUELS = ["BEV", "PHEV", "HEV", "PETROL", "DIESEL", "OTHERS"]
CSV_COLUMNS = ["period", "time_interval", "variant", "source",
               *FUELS, "TOTAL", "notes"]

PHEV_CO2_MAX = 60   # g/km; only used when the register has no hybrid code

# Top brands / models: one summary per variant that has them (market_top).
TOP_SLUGS = {"Whole": "switzerland", "Used": "switzerland_used"}
TOP_UNIT = ("registrations (brand = IVZ Marke; model = IVZ type designation "
            "Typ2, with Typ3 where Typ2 alone is no model name)")

# A month whose flow-in of late registrations exceeds this share of the month
# is written but flagged — usually a frozen row that was wrong to begin with.
FLOW_WARN = 0.03
# ACEA cross-check tolerances (Whole).
ACEA_WARN_TOTAL = 0.01
ACEA_WARN_FUEL = 0.03
# ACEA publishes month M in the third/fourth week of M+1.
ACEA_DUE_DAY = 20


# ── classification ─────────────────────────────────────────────────────────

def _int(s: str | None) -> int:
    try:
        return int(float((s or "").replace(",", ".")))
    except ValueError:
        return 0


def _has_value(s: str | None) -> bool:
    s = (s or "").strip()
    return s not in ("", "0", "0.0", "0,0")


def fuel_of(get) -> str:
    """Gallery fuel column of one register row (see module docstring)."""
    code = (get("Treibstoff_Code") or "").strip().upper()
    text = (get("Treibstoff") or "").strip()
    if not code:   # older files: fall back to the label
        code = {"Elektrisch": "E", "Benzin": "B", "Diesel": "D",
                "Benzin / Elektrisch": "C", "Diesel / Elektrisch": "F"}.get(text, "")
        if text.startswith("Elektrisch mit"):
            code = "R"
    if code == "E":
        return "BEV"
    if code == "R":
        return "PHEV"
    if code in ("C", "F"):
        hc = (get("Hybridcode") or "").strip().upper()
        if hc == "OVC-HEV":
            return "PHEV"
        if hc == "NOVC-HEV":
            return "HEV"
        if _has_value(get("El-Verbrauch")):
            return "PHEV"
        co2 = _int(get("CO2-WLTP")) or _int(get("CO2-NEFZ")) or _int(get("CO2"))
        return "PHEV" if 0 < co2 <= PHEV_CO2_MAX else "HEV"
    if code in ("B", "P"):
        return "PETROL"
    if code == "D":
        return "DIESEL"
    return "OTHERS"


def variant_of(get) -> str | None:
    """NEUZU row -> variant (or None). Keep in sync with the docstring and
    46-source-switzerland.md §3."""
    klasse = (get("Fahrzeugklasse") or "").strip().upper()
    art = (get("Fahrzeugart") or "").strip()
    if art == "Personenwagen" and klasse in ("M1", ""):
        return "Whole"
    if klasse == "N1" and art == "Lieferwagen":
        return "Vans"
    if klasse in ("N2", "N3") and art in ("Lastwagen", "Sattelschlepper"):
        return "HDV"
    if klasse in ("M2", "M3") and _int(get("Gesamtgewicht")) > 3500:
        return "Buses"
    if klasse in ("L1", "L3"):
        return "2-Wheelers"
    return None


def used_variant_of(get) -> str | None:
    """GEBR row -> 'Used' for used-import passenger cars."""
    klasse = (get("Fahrzeugklasse") or "").strip().upper()
    if (get("Fahrzeugart") or "").strip() == "Personenwagen" and klasse in ("M1", ""):
        return "Used"
    return None


def neuzu_period(get) -> str | None:
    y, m = (get("Erstinverkehrsetzung_Jahr") or "").strip(), \
           (get("Erstinverkehrsetzung_Monat") or "").strip()
    return f"{y}-{int(m):02d}" if y.isdigit() and m.isdigit() else None


def gebr_period(get) -> str | None:
    """Used imports are dated by their first Swiss registration."""
    y, m = (get("Ersterfassung_Jahr") or "").strip(), \
           (get("Ersterfassung_Monat") or "").strip()
    return f"{y}-{int(m):02d}" if y.isdigit() and m.isdigit() else None


# Type families whose Typ3 is the model itself — Model Y, Seal U, Ioniq 5,
# RR Evoque, AMG GLC, Atto 2 — where everywhere else Typ3 is trim or power
# (ENYAQ 85X, X1 xDrive30e, GLC 400, 2 HYBRID). Found by listing every Typ2
# of the electrified cars with its Typ3 values (2026 register; the rule is
# also stated in 46-source-switzerland.md, market_designation_note).
MODEL_FAMILIES = {"MODEL", "RR", "AMG", "IONIQ", "SEAL", "SEALION", "ATTO", "ID."}
# A Typ3 that names a model: a word ("Evoque", "GLC") or one character
# ("Y", "5"); engine codes like P550e / D350 never are.
_MODEL_TOKEN = re.compile(r"[A-Za-z][A-Za-z-]*|[A-Za-z0-9]")


def model_name(get) -> str:
    """Typ2 is the model ("ENYAQ", "EX30", "iX3", Renault "5"); Typ3 completes
    it only for MODEL_FAMILIES. A model typed with the brand glued on ("MG4"
    next to "4") is reduced to the part after the brand, so it ranks once."""
    t2 = (get("Typ2") or "").strip()
    t3 = (get("Typ3") or "").strip()
    if not t2:
        return market_top.clean(get("Typ1") or "")
    family = t2.upper() in MODEL_FAMILIES or t2.endswith(".")
    model = f"{t2} {t3}" if t3 and family and _MODEL_TOKEN.fullmatch(t3) else t2
    model = market_top.clean(model)
    brand = market_top.clean(get("Marke") or "").replace(" ", "")
    if brand and model.startswith(brand) and model[len(brand):].isdigit():
        model = model[len(brand):]
    return model


# ── download & parse ───────────────────────────────────────────────────────

def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HTTP_HEADERS)
    return s


class NotPublished(RuntimeError):
    pass


DOWNLOAD_ATTEMPTS = 4
RETRY_WAIT = (10, 30, 60)   # seconds before attempts 2, 3, 4


def download(session: requests.Session, url: str) -> Path:
    """Stream one register file to a temp file (they are ~100 MB). A dropped
    connection — at the start or mid-stream — is retried; a 404 or a WAF
    page is not."""
    for attempt in range(1, DOWNLOAD_ATTEMPTS + 1):
        name = None
        try:
            r = session.get(url, stream=True, timeout=600)
            if r.status_code == 404:
                raise NotPublished(url)
            r.raise_for_status()
            ctype = r.headers.get("content-type", "")
            if "html" in ctype:
                raise RuntimeError(f"{url}: got {ctype!r}, not the data file "
                                   "(WAF page?)")
            fd, name = tempfile.mkstemp(suffix=".txt", prefix="astra_")
            with os.fdopen(fd, "wb") as f:
                for chunk in r.iter_content(1 << 20):
                    f.write(chunk)
            return Path(name)
        except (requests.ConnectionError, requests.Timeout,
                requests.exceptions.ChunkedEncodingError) as e:
            if name:
                Path(name).unlink(missing_ok=True)
            if attempt == DOWNLOAD_ATTEMPTS:
                raise
            wait = RETRY_WAIT[attempt - 1]
            print(f"  download failed ({type(e).__name__}); retry {attempt + 1}/"
                  f"{DOWNLOAD_ATTEMPTS} in {wait}s")
            time.sleep(wait)
    raise AssertionError("unreachable")


def open_rows(path: Path):
    """(header index, row iterator) — UTF-8, falling back to cp1252."""
    for enc in ("utf-8", "cp1252"):
        try:
            with open(path, encoding=enc) as f:
                f.read(1 << 20)
            break
        except UnicodeDecodeError:
            continue
    fh = open(path, encoding=enc, newline="")
    reader = csv.reader(fh, delimiter="\t", quoting=csv.QUOTE_NONE)
    header = [h.strip() for h in next(reader)]
    return {k: i for i, k in enumerate(header)}, reader, fh


def parse_date(s: str) -> dt.date | None:
    try:
        d, m, y = (int(x) for x in s.strip().split("."))
        return dt.date(y, m, d)
    except (ValueError, AttributeError):
        return None


def last_complete_month(datenstand: dt.date | None, bis: dt.date | None) -> str | None:
    """Newest month the snapshot covers in full. `bis` (NEUZU's
    Neuzulassungen_bis) if present, else the day before the data date."""
    end = bis or (datenstand - dt.timedelta(days=1) if datenstand else None)
    if end is None:
        return None
    if (end + dt.timedelta(days=1)).month != end.month:   # last day of a month
        return f"{end.year}-{end.month:02d}"
    first = end.replace(day=1) - dt.timedelta(days=1)
    return f"{first.year}-{first.month:02d}"


def snapshot_meta(header: list[str], first_row: list[str]) -> tuple[dt.date | None, dt.date | None]:
    ix = {k.strip(): i for i, k in enumerate(header)}
    get = lambda k: first_row[ix[k]] if k in ix and ix[k] < len(first_row) else ""
    return parse_date(get("Datenstand")), parse_date(get("Neuzulassungen_bis"))


def probe_meta(session: requests.Session, url: str) -> str | None:
    """Last complete month of a snapshot from its first 16 KB (header + one
    row), so a run with nothing to do downloads nothing big."""
    try:
        r = session.get(url, headers={"Range": "bytes=0-16383"}, timeout=60)
    except requests.RequestException as e:
        print(f"  range probe failed ({e}); will download the file")
        return None
    if r.status_code not in (200, 206) or "html" in r.headers.get("content-type", ""):
        print(f"  range probe HTTP {r.status_code}; will download the file")
        return None
    lines = r.content.decode("utf-8", "replace").split("\n")
    if len(lines) < 2:
        return None
    header, row = lines[0].rstrip("\r").split("\t"), lines[1].rstrip("\r").split("\t")
    return last_complete_month(*snapshot_meta(header, row))


class Tally:
    """Counts of one register file: {variant: {period: Counter(fuel)}}, the
    brand/model tallies for the top lists ({variant: {period: Counter}}, the
    TOP_SLUGS variants only), and the snapshot's dates."""

    def __init__(self) -> None:
        self.counts: dict[str, dict[str, collections.Counter]] = \
            collections.defaultdict(lambda: collections.defaultdict(collections.Counter))
        self.models: dict[str, dict[str, collections.Counter]] = \
            collections.defaultdict(lambda: collections.defaultdict(collections.Counter))
        self.datenstand: dt.date | None = None
        self.bis: dt.date | None = None
        self.rows = 0

    @property
    def complete_to(self) -> str | None:
        return last_complete_month(self.datenstand, self.bis)

    def month(self, variant: str, period: str) -> dict[str, int]:
        c = self.counts[variant].get(period, collections.Counter())
        out = {k: c[k] for k in FUELS}
        out["TOTAL"] = sum(out.values())
        return out


def tally_file(path: Path, kind: str, keep_models: bool = False) -> Tally:
    """One pass over a NEUZU or GEBR file."""
    pick = variant_of if kind == "NEUZU" else used_variant_of
    period_of = neuzu_period if kind == "NEUZU" else gebr_period
    ix, reader, fh = open_rows(path)
    t = Tally()
    try:
        for row in reader:
            if not row or len(row) < len(ix) // 2:
                continue
            get = lambda k: row[ix[k]] if k in ix and ix[k] < len(row) else ""
            if t.rows == 0:
                t.datenstand = parse_date(get("Datenstand"))
                t.bis = parse_date(get("Neuzulassungen_bis"))
            t.rows += 1
            v = pick(get)
            if v is None:
                continue
            p = period_of(get)
            if p is None:
                continue
            fuel = fuel_of(get)
            t.counts[v][p][fuel] += 1
            if keep_models and v in TOP_SLUGS:
                brand = market_top.clean(get("Marke"))
                t.models[v][p][(fuel, brand, model_name(get))] += 1
    finally:
        fh.close()
    return t


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


def read_csv_lines(path: Path) -> tuple[str, list[str], str]:
    """(header, data lines, line ending). Lines keep their own terminator so
    an untouched line is written back byte for byte — some Swiss CSVs are
    CRLF (the ACEA-era files), new ones are LF."""
    if not path.exists():
        return ",".join(CSV_COLUMNS) + "\n", [], "\n"
    with open(path, encoding="utf-8", newline="") as f:
        text = f.read()
    eol = "\r\n" if "\r\n" in text else "\n"
    raw = text.splitlines(keepends=True)
    if not raw:
        return ",".join(CSV_COLUMNS) + eol, [], eol
    return raw[0], [l for l in raw[1:] if l.strip()], eol


def line_key(line: str) -> tuple[str, str]:
    f = next(csv.reader([line.rstrip("\r\n")]))
    return f[0], f[2]


def line_source(line: str) -> str:
    return next(csv.reader([line.rstrip("\r\n")]))[3]


def upsert_lines(path: Path, updates: dict[tuple[str, str], str],
                 force: bool) -> dict[str, int]:
    """Replace/insert only the given (period, variant) lines; every other
    line — terminator included — is written back byte for byte, in its
    original place. A new line goes before the first line with a later
    period (the rest of the file is never re-sorted); a foreign-source line
    is never replaced without `force`."""
    header, lines, eol = read_csv_lines(path)
    if header.rstrip("\r\n").split(",") != CSV_COLUMNS:
        sys.exit(f"{path}: unexpected header {header!r} — expected {CSV_COLUMNS}")
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += eol          # a file without a final newline gets one
    stats = {"added": 0, "updated": 0, "unchanged": 0, "skipped": 0}
    for key, new in sorted(updates.items()):
        new = new.rstrip("\r\n")
        index = {line_key(l): i for i, l in enumerate(lines)}
        if key in index:
            old = lines[index[key]]
            if old.rstrip("\r\n") == new:
                stats["unchanged"] += 1
            elif line_source(old) != SOURCE and not force:
                stats["skipped"] += 1
            else:
                lines[index[key]] = new + old[len(old.rstrip("\r\n")):]
                stats["updated"] += 1
        else:
            at = next((i for i, l in enumerate(lines) if line_key(l)[0] > key[0]),
                      len(lines))
            lines.insert(at, new + eol)
            stats["added"] += 1
    if stats["added"] or stats["updated"]:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(header + "".join(lines))
    return stats


def csv_rows(path: Path) -> dict[str, dict]:
    """{period: row} of one variant CSV (monthly rows only)."""
    if not path.exists():
        return {}
    with open(path, newline="", encoding="utf-8") as f:
        return {r["period"]: r for r in csv.DictReader(f)
                if (r.get("time_interval") or "monthly") == "monthly"}


def row_counts(row: dict) -> dict[str, int]:
    out = {k: int(round(float(row.get(k) or 0))) for k in FUELS}
    out["TOTAL"] = int(round(float(row.get("TOTAL") or 0)))
    return out


# ── month attribution ──────────────────────────────────────────────────────

def months_of_year(year: int, upto: str) -> list[str]:
    last = int(upto[5:7]) if int(upto[:4]) == year else 12
    return [f"{year}-{m:02d}" for m in range(1, last + 1)]


def flow_months(tally: Tally, variant: str, have: dict[str, dict],
                upto: str) -> dict[str, tuple[dict[str, int], int]]:
    """The ACEA rule. Months of `upto`'s year up to `upto` that the CSV does
    not have yet get their registration-month counts; the first of them also
    absorbs every late registration of the year's months already written by
    us (snapshot count − CSV row). Rows from another source (the BFS/ACEA
    history) are not differenced: their gap to the register is classification
    and definition, not late registrations, and must not land in one month.
    Returns {period: (counts, flow_in_total)}."""
    year = int(upto[:4])
    months = months_of_year(year, upto)
    todo = [p for p in months if p not in have]
    if not todo:
        return {}
    delta = {k: 0 for k in FUELS}
    for p in months:
        if p in have and (have[p].get("source") or "") == SOURCE:
            got, written = tally.month(variant, p), row_counts(have[p])
            for k in FUELS:
                delta[k] += got[k] - written[k]
    out = {}
    for i, p in enumerate(todo):
        c = tally.month(variant, p)
        flow = 0
        if i == 0:
            for k in FUELS:
                c[k] += delta[k]
            flow = sum(delta.values())
            for k in FUELS:   # a corrected-down fuel can't go below zero
                c[k] = max(c[k], 0)
            c["TOTAL"] = sum(c[k] for k in FUELS)
        out[p] = (c, flow)
    return out


def exact_months(tally: Tally, variant: str, have: dict[str, dict],
                 periods: list[str], force: bool) -> dict[str, dict[str, int]]:
    """Registration-month counts for the given periods (history mode). Only
    months the CSV does not have yet — a written month is never revised
    (invariant 3) unless `force`."""
    out = {}
    for p in periods:
        if p in have and not force:
            continue
        c = tally.month(variant, p)
        if c["TOTAL"]:
            out[p] = c
    return out


# ── ACEA cross-check ───────────────────────────────────────────────────────

def acea_deltas(ours: dict[str, int], acea: dict[str, int]) -> list[str]:
    """Human-readable gaps beyond tolerance (empty list = within)."""
    issues = []
    t_ours, t_acea = ours.get("TOTAL", 0), acea.get("TOTAL", 0)
    if t_acea and abs(t_ours - t_acea) / t_acea > ACEA_WARN_TOTAL:
        issues.append(f"TOTAL {t_ours:,} vs ACEA {t_acea:,} "
                      f"({(t_ours - t_acea) / t_acea:+.2%})")
    for k in ("BEV", "PHEV", "HEV", "PETROL", "DIESEL"):
        a, o = acea.get(k, 0), ours.get(k, 0)
        if a >= 200 and abs(o - a) / a > ACEA_WARN_FUEL:
            issues.append(f"{k} {o:,} vs ACEA {a:,} ({(o - a) / a:+.2%})")
    return issues


def acea_check(months_back: int = 3) -> int:
    """Compare the newest ASTRA months of Switzerland.csv with ACEA's press
    releases. Log-only: a gap is a ::warning::, a missing release a note."""
    import fetch_acea  # lazy: needs pdfplumber, only this mode does
    rows = csv_rows(REPO / VARIANT_CSV["Whole"])
    ours = sorted(p for p, r in rows.items() if (r.get("source") or "") == SOURCE)
    if not ours:
        print("No ASTRA rows in Switzerland.csv yet — nothing to check.")
        return 0
    today = dt.date.today()
    for period in ours[-months_back:]:
        y, m = int(period[:4]), int(period[5:7])
        due = dt.date(y + (m == 12), m % 12 + 1, ACEA_DUE_DAY)
        if today < due:
            # ACEA's edge answers 403, not 404, for a file that isn't there yet.
            print(f"{period}: ACEA release not due before {due} — skipped.")
            continue
        url = fetch_acea.ACEA_URL_TEMPLATE.format(
            month_name=fetch_acea.ENGLISH_MONTHS[m - 1], year=y)
        try:
            pdf = fetch_acea.load_pdf_bytes(url)
        except FileNotFoundError:
            print(f"{period}: ACEA release not published (yet) — skipped.")
            continue
        except Exception as e:  # noqa: BLE001 — a cross-check never fails the run
            print(f"::warning::{period}: ACEA release could not be read ({e})")
            continue
        if not pdf.startswith(b"%PDF"):
            print(f"::warning::{period}: ACEA answered with a non-PDF page "
                  "(bot challenge?) — skipped.")
            continue
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(pdf)
        try:
            parsed, _ = fetch_acea.parse_monthly_table(f.name, ["Switzerland"])
        except Exception as e:  # noqa: BLE001
            print(f"::warning::{period}: ACEA release could not be parsed ({e})")
            continue
        finally:
            os.unlink(f.name)
        ch = parsed.get("Switzerland")
        if not ch:
            print(f"::warning::{period}: Switzerland missing from the ACEA release")
            continue
        acea = {k: v[0] for k, v in ch.items()}
        mine = row_counts(rows[period])
        line = "  ".join(f"{k} {mine.get(k, 0) - acea.get(k, 0):+d}"
                         for k in ("BEV", "PHEV", "HEV", "PETROL", "DIESEL", "TOTAL"))
        print(f"{period}: ASTRA − ACEA  {line}")
        for issue in acea_deltas(mine, acea):
            print(f"::warning::Switzerland {period} vs ACEA: {issue}")
    return 0


# ── top brands / models ────────────────────────────────────────────────────

def refresh_top(monthly_tallies: list[Tally]) -> None:
    """Merge the complete months of these tallies into each variant's month
    store and rebuild its top summary (market_top.refresh_from_store)."""
    for variant, slug in TOP_SLUGS.items():
        fresh: dict[str, tuple[dict, int]] = {}
        # oldest snapshot first, so a month two files share comes from the newest
        for t in sorted(monthly_tallies, key=lambda t: t.complete_to or ""):
            upto = t.complete_to
            for p, units in t.models.get(variant, {}).items():
                if upto and p > upto:
                    continue   # the running month is incomplete
                fresh[p] = (dict(units), sum(units.values()))
        if fresh:
            market_top.refresh_from_store("Switzerland", SOURCE, TOP_UNIT, slug,
                                          fresh, variant)


# ── main ───────────────────────────────────────────────────────────────────

def selected(args) -> list[str]:
    """'all', one variant, or several comma-separated (one download each)."""
    if args.variant == "all":
        return list(VARIANT_CSV)
    out = [v.strip() for v in args.variant.split(",") if v.strip()]
    bad = [v for v in out if v not in VARIANT_CSV]
    if bad or not out:
        sys.exit(f"Unknown variant {bad or args.variant!r}. Valid: {list(VARIANT_CSV)} or 'all'.")
    return out


def write_months(variant: str, months: dict[str, dict[str, int]],
                 notes: dict[str, str], force: bool) -> bool:
    path = REPO / VARIANT_CSV[variant]
    updates = {(p, variant): render_line(p, variant, c, notes.get(p, ""))
               for p, c in months.items()}
    if not updates:
        return False
    stats = upsert_lines(path, updates, force)
    print(f"  {VARIANT_CSV[variant]}: {stats}")
    return bool(stats["added"] or stats["updated"])


def run_monthly(session, variants: list[str], force: bool) -> set[str]:
    changed: set[str] = set()
    tallies: list[Tally] = []
    for kind, url, group in (("NEUZU", NEUZU_URL, NEUZU_VARIANTS),
                             ("GEBR", GEBR_URL, GEBR_VARIANTS)):
        todo = [v for v in variants if v in group]
        if not todo:
            continue
        upto = probe_meta(session, url)
        if upto and not force and all(upto in csv_rows(REPO / VARIANT_CSV[v])
                                      for v in todo):
            print(f"{kind}: snapshot complete to {upto}; every CSV has it — nothing to do.")
            continue
        print(f"{kind}: downloading {url} …")
        path = download(session, url)
        try:
            t = tally_file(path, kind, keep_models=True)
        finally:
            path.unlink(missing_ok=True)
        upto = t.complete_to
        print(f"  {t.rows:,} rows, data as of {t.datenstand}, complete to {upto}")
        if upto is None:
            print(f"::warning::{kind}: snapshot has no data date — skipped")
            continue
        tallies.append(t)
        for v in todo:
            have = csv_rows(REPO / VARIANT_CSV[v])
            months = flow_months(t, v, have, upto)
            notes = {}
            for p, (c, flow) in months.items():
                print(f"  {v} {p}: " + " ".join(f"{k}={c[k]:,}" for k in FUELS + ["TOTAL"])
                      + (f"  (incl. {flow:+,} late registrations of earlier "
                         f"{p[:4]} months)" if flow else ""))
                if c["TOTAL"] and abs(flow) > FLOW_WARN * c["TOTAL"]:
                    print(f"::warning::Switzerland {v} {p}: {flow:+,} late "
                          f"registrations flowed in ({flow / c['TOTAL']:+.1%} of "
                          "the month) — check the earlier rows of the year.")
            if write_months(v, {p: c for p, (c, _) in months.items()}, notes, force):
                changed.add(v)
    if tallies:
        market_top.guarded(refresh_top, tallies)
    return changed


def run_backfill(session, variants: list[str], first: int | None,
                 force: bool) -> set[str]:
    changed: set[str] = set()
    tallies: list[Tally] = []
    this_year = dt.date.today().year
    for kind, cur_url, year_url, group, start in (
            ("NEUZU", NEUZU_URL, NEUZU_YEAR_URL, NEUZU_VARIANTS, NEUZU_FIRST_YEAR),
            ("GEBR", GEBR_URL, GEBR_YEAR_URL, GEBR_VARIANTS, GEBR_FIRST_YEAR)):
        todo = [v for v in variants if v in group]
        if not todo:
            continue
        # The running year first: it fixes which year the year files end at
        # (in January the current file still holds the previous year).
        path = download(session, cur_url)
        try:
            cur = tally_file(path, kind, keep_models=True)
        finally:
            path.unlink(missing_ok=True)
        upto = cur.complete_to or f"{this_year - 1}-12"
        cur_year = int(upto[:4])
        jobs = [(y, None) for y in range(max(first or start, start), cur_year)]
        jobs.append((cur_year, cur))
        tallies.append(cur)
        for year, t in jobs:
            if t is None:
                url = year_url.format(year=year)
                print(f"{kind} {year}: downloading …")
                try:
                    path = download(session, url)
                except NotPublished:
                    print(f"  {url} not found — skipped")
                    continue
                try:
                    t = tally_file(path, kind, keep_models=(year == cur_year - 1))
                finally:
                    path.unlink(missing_ok=True)
                if year == cur_year - 1:
                    tallies.append(t)
            periods = months_of_year(year, upto)
            for v in todo:
                have = csv_rows(REPO / VARIANT_CSV[v])
                months = exact_months(t, v, have, periods, force)
                if write_months(v, months, {}, force):
                    changed.add(v)
            print(f"  {kind} {year}: {', '.join(todo)} done")
    if tallies:
        market_top.guarded(refresh_top, tallies)
    return changed


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--variant", default="all",
                    help=f"all | {' | '.join(VARIANT_CSV)} — or several, comma-separated "
                         "(default: all)")
    ap.add_argument("--backfill", action="store_true",
                    help="Count closed years from the year files (implied for "
                         "a variant whose CSV does not exist yet).")
    ap.add_argument("--from", dest="first", type=int, default=None,
                    help="First year of a backfill (default: 2016, Used 2017).")
    ap.add_argument("--force", action="store_true",
                    help="Ignore the self-throttle and overwrite foreign rows.")
    ap.add_argument("--acea-check", action="store_true",
                    help="Compare the newest ASTRA months with ACEA and exit.")
    ap.add_argument("--github-output", default=os.environ.get("GITHUB_OUTPUT"))
    args = ap.parse_args()

    if args.acea_check:
        return acea_check()

    variants = selected(args)
    session = make_session()
    missing = [v for v in variants if not (REPO / VARIANT_CSV[v]).exists()]
    changed: set[str] = set()
    if args.backfill or missing:
        todo = variants if args.backfill else missing
        print(f"Backfill for {todo} …")
        changed |= run_backfill(session, todo, args.first, args.force)
    rest = [v for v in variants if not (args.backfill or v in missing)]
    if rest:
        changed |= run_monthly(session, rest, args.force)
    if not changed:
        print("No changes.")
    return emit(args, changed)


def emit(args, changed: set[str]) -> int:
    if args.github_output:
        with open(args.github_output, "a", encoding="utf-8") as f:
            f.write(f"changed={'true' if changed else 'false'}\n")
            f.write(f"changed_variants={json.dumps(sorted(changed))}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
