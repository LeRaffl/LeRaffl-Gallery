#!/usr/bin/env python3
"""
Fetch Czechia registration data from the national vehicle register RSV
(Registr silničních vozidel, Ministry of Transport — open data) and upsert
data/Czechia*.csv (Whole + Used + Vans + HDV + Buses).

Source
------
The Ministry of Transport publishes the whole register as one open-data CSV —
free, no login, no key — with one row per vehicle ever registered in Czechia
(deregistered ones included, status ZÁNIK):

    https://download.dataovozidlech.cz/vypiszregistru/vypisvozidel
      → RSV_vypis_vozidel_<YYYYMMDD>.csv  (Content-Disposition; the date is
        the day the extract was generated)

About 19.4 million rows, ~7.5 GB on the wire with gzip (~25 GB raw). The
server builds the file on the fly: no Content-Length, no range requests. The
fetcher therefore never stores it — it streams it (gzip, decompressed on the
fly), counts, and drops every row; a dropped connection restarts the stream
from the beginning (DOWNLOAD_ATTEMPTS). Before downloading, one request reads
only the response headers to learn the extract's date, so a run with nothing
to do downloads nothing.

The register is what SDA (the importers' association) counts, and SDA's
figures are what ACEA publishes for Czechia: TOTAL and BEV agree to the unit
in most months (docs/architecture/51-source-czechia.md §4).

Record → variant
----------------
A vehicle is NEW when its first registration anywhere ("Datum 1. registrace")
is its first registration in Czechia ("Datum 1. registrace v ČR"); otherwise
it is a USED import. Every row is dated by its first Czech registration.
Category is the register's own EU vehicle category (the G suffix = off-road):

  Whole  data/Czechia.csv        new  ∧ M1, M1G
  Used   data/Czechia_Used.csv   used ∧ M1, M1G   (imported, first registered abroad)
  Vans   data/Czechia_Vans.csv   new  ∧ N1, N1G
  HDV    data/Czechia_HDV.csv    new  ∧ N2, N2G, N3, N3G
  Buses  data/Czechia_Buses.csv  new  ∧ M2, M2G, M3, M3G

Only vehicles of the road register proper (Zařazení vozidla = RSV; RHSV is the
historic-vehicle register) are counted.

Fuel → columns
--------------
"Palivo" is the fuel line P.3 of the registration certificate, as tokens joined
by "+" (BA petrol, NM diesel, EL electricity, LPG, CNG, …):

  EL alone                                → BEV
  any of LPG / CNG / LNG / VODÍK / E 85,
  or no BA / NM / EL at all               → OTHERS (gas, hydrogen, ethanol)
  BA or NM together with EL               → PHEV when the plug-in test passes,
                                            otherwise a non-plug-in hybrid
  BA                                      → PETROL
  NM                                      → DIESEL

Plug-in test (in order): hybrid class OVC-HEV → plug-in; NOVC-HEV → not;
combined CO2 ≤ 60 g/km → plug-in; otherwise the majority of the explicit
hybrid classes recorded for the same type-approval variant (make, type,
variant, version) anywhere in the register; no evidence → not a plug-in.
The class field is free text in the register ("NOVC - HEV", "N0VC-HEV",
"ovc-hev") — normalised before the test.

Full and mild hybrids are NOT identifiable: the register's hybrid flag is
filled only for part of the cars (well kept only since mid-2025) and mild
hybrids almost never carry it. So:

* Whole: the register gives BEV, PHEV, OTHERS and TOTAL. HEV, PETROL and
  DIESEL follow SDA's definition (petrol/diesel WITHOUT any hybrid), which
  the register cannot reproduce — they are written as an ESTIMATE: the
  register's remainder (TOTAL − BEV − PHEV − OTHERS) split in the proportions
  of the newest ACEA-sourced month, flagged in `notes`. Czechia stays on
  ACEA's always-list (scripts/fetch_acea.py): when ACEA publishes the month
  (third to fourth week) it overwrites the row with SDA's official split.
  A month ACEA never publishes (July) keeps the register row.
* Used, Vans, HDV, Buses: no HEV column; full and mild hybrids are inside
  PETROL / DIESEL (the CSVs say so in footnotes.csv).

Rows are written once and never revised (invariant 3): a month a CSV already
has is skipped, whatever its source, unless --force (which still never
overwrites a row from another source than ours). Whole is written only from
WHOLE_FROM on — its history is ACEA/SDA.

Governance (every real run)
---------------------------
* required columns must resolve; a missing one aborts;
* the extract must hold at least MIN_ROWS rows (a truncated stream that did
  not raise is caught here);
* a new month whose Whole TOTAL is below 50 % of the median of the 12 months
  before it is not written (--force overrides);
* unknown fuel strings above 0.5 % of the month's Whole abort; vehicle
  categories outside the scope are just not counted;
* fuels sum to TOTAL for every row written.

Usage
-----
    python scripts/fetch_czechia.py                     # newest complete month
    python scripts/fetch_czechia.py --backfill          # every month a CSV lacks
    python scripts/fetch_czechia.py --from-file F.csv[.gz]   # offline (tests, rebuilds)
"""
from __future__ import annotations

import argparse
import collections
import csv
import datetime as dt
import gzip
import io
import json
import os
import re
import statistics
import sys
import time
import zlib
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import market_top  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
SOURCE = "RSV (dataovozidlech.cz)"
URL = "https://download.dataovozidlech.cz/vypiszregistru/vypisvozidel"

VARIANT_CSV: dict[str, str] = {
    "Whole": "data/Czechia.csv",
    "Used":  "data/Czechia_Used.csv",
    "Vans":  "data/Czechia_Vans.csv",
    "HDV":   "data/Czechia_HDV.csv",
    "Buses": "data/Czechia_Buses.csv",
}
CATEGORIES = {
    "M1": "Whole", "M1G": "Whole",
    "N1": "Vans", "N1G": "Vans",
    "N2": "HDV", "N2G": "HDV", "N3": "HDV", "N3G": "HDV",
    "M2": "Buses", "M2G": "Buses", "M3": "Buses", "M3G": "Buses",
}

# Whole keeps the ACEA/SDA history and its column set (HEV = SDA's hybrids).
WHOLE_FUELS = ["BEV", "PHEV", "HEV", "PETROL", "DIESEL", "OTHERS"]
WHOLE_ESTIMATED = ("HEV", "PETROL", "DIESEL")
# The register-only series: hybrids without a plug sit in PETROL / DIESEL.
REG_FUELS = ["BEV", "PHEV", "PETROL", "DIESEL", "OTHERS"]


def fuels_of(variant: str) -> list[str]:
    return WHOLE_FUELS if variant == "Whole" else REG_FUELS


def csv_columns(variant: str) -> list[str]:
    return ["period", "time_interval", "variant", "source",
            *fuels_of(variant), "TOTAL", "notes"]


WHOLE_FROM = "2026-09"            # first month the register writes into Whole
HISTORY_FROM = "2016-01"          # first month of Used / Vans / HDV / Buses
MIN_ROWS = 15_000_000             # the 2026-10 extract has 19.4 M
COMPLETENESS_FLOOR = 0.5          # × trailing-12 median of Whole
UNKNOWN_FUEL_MAX = 0.005          # share of the month's Whole
PHEV_CO2_MAX = 60.0               # g/km combined
DOWNLOAD_ATTEMPTS = 4
RETRY_WAIT = (60, 180, 600)       # seconds before attempts 2, 3, 4

# Brand / model top lists (market_top), by register make + trade name.
TOP_SLUGS = {"Whole": "czechia", "Used": "czechia_used"}
TOP_UNIT = ("registrations (brand = RSV make, 'Tovární značka'; "
            "model = trade name, 'Obchodní označení')")

C_FIRST = "Datum 1. registrace"
C_FIRST_CZ = "Datum 1. registrace v ČR"
C_CAT = "Kategorie vozidla"
C_FUEL = "Palivo"
C_HCLASS = "Třída hybridního vozidla"
C_CO2 = "CO2 město /mimo město/kombinované [g.km-1]"
C_MAKE = "Tovární značka"
C_TYPE = "Typ"
C_VAR = "Varianta"
C_VER = "Verze"
C_MODEL = "Obchodní označení"
C_REGISTER = "Zařazení vozidla"
REQUIRED = (C_FIRST, C_FIRST_CZ, C_CAT, C_FUEL, C_HCLASS, C_CO2, C_MAKE,
            C_TYPE, C_VAR, C_VER, C_MODEL, C_REGISTER)

HTTP_HEADERS = {
    "User-Agent": "LeRaffl-Gallery data fetcher (+https://github.com/LeRaffl/LeRaffl-Gallery)",
    "Accept": "text/csv,*/*;q=0.8",
    "Accept-Encoding": "gzip",
}


# ── classification ─────────────────────────────────────────────────────────

GAS_TOKENS = {"LPG", "CNG", "LNG", "VODÍK", "E 85", "E85", "BIOPLYN"}
TOKEN_ALIASES = {"BIO NM": "NM", "BA SMĚS": "BA", "NAFTA": "NM", "BENZIN": "BA"}


def fuel_tokens(palivo: str) -> frozenset[str]:
    out = set()
    for t in (palivo or "").upper().split("+"):
        t = " ".join(t.split())
        if t:
            out.add(TOKEN_ALIASES.get(t, t))
    return frozenset(out)


def hybrid_class(raw: str) -> str:
    """'OVC', 'NOVC' or '' from the free-text hybrid class (OVC-HEV,
    'NOVC - HEV', 'N0VC-HEV', 'ovc-hev', VHE-RE / VHE-NRE, PHEV, …)."""
    c = re.sub(r"[^A-Z]", "", (raw or "").upper().replace("0", "O"))
    if not c:
        return ""
    if "NOVC" in c or "NOV" in c or c in ("HEV", "VHENRE"):
        return "NOVC"
    if c.startswith("OVC") or c in ("PHEV", "VHERE") or c.endswith("OVCHEV"):
        return "OVC"
    return ""


def co2_combined(raw: str) -> float | None:
    """The last positive number of 'city / extra-urban / combined'."""
    for part in reversed((raw or "").split("/")):
        try:
            v = float(part.strip().replace(",", "."))
        except ValueError:
            continue
        if v > 0:
            return v
    return None


def base_fuel(tokens: frozenset[str]) -> str:
    """BEV / OTHERS / HYBRID (combustion + EL, plug-in test pending) /
    PETROL / DIESEL / UNKNOWN."""
    if tokens == {"EL"}:
        return "BEV"
    if tokens & GAS_TOKENS:
        return "OTHERS"
    known = tokens & {"BA", "NM", "EL"}
    if not known:
        return "OTHERS" if tokens else "UNKNOWN"
    if "EL" in tokens:
        return "HYBRID"
    if tokens - {"BA", "NM"}:
        return "OTHERS"
    return "PETROL" if "BA" in tokens else "DIESEL"


def plug_in_direct(hclass: str, co2: float | None) -> bool | None:
    """The record's own evidence: True / False, or None (look at the variant)."""
    if hclass == "OVC":
        return True
    if hclass == "NOVC":
        return False
    if co2 is not None and co2 <= PHEV_CO2_MAX:
        return True
    return None


def combustion_of(tokens: frozenset[str]) -> str:
    return "DIESEL" if "NM" in tokens and "BA" not in tokens else "PETROL"


# ── tally ──────────────────────────────────────────────────────────────────

class Tally:
    """One pass over the extract. counts[variant][period][column]; hybrids
    whose plug-in test needs the variant's evidence wait in `pending` until
    the whole file has been read."""

    def __init__(self) -> None:
        self.counts = collections.defaultdict(
            lambda: collections.defaultdict(collections.Counter))
        # (variant, period, key, combustion column) -> n
        self.pending: collections.Counter = collections.Counter()
        # key -> Counter(OVC=…, NOVC=…)
        self.key_evidence = collections.defaultdict(collections.Counter)
        # (variant, period, fuel column, brand, model) -> n   (TOP_SLUGS only)
        self.models: collections.Counter = collections.Counter()
        self.pending_models: collections.Counter = collections.Counter()
        self.unknown_fuel = collections.defaultdict(collections.Counter)
        self.rows = 0
        self.snapshot: dt.date | None = None
        self.models_from = HISTORY_FROM   # brand/model tallies only from here
        self.resolved = False

    @property
    def complete_to(self) -> str | None:
        return complete_month(self.snapshot)

    def add(self, get) -> None:
        self.rows += 1
        cat = (get(C_CAT) or "").strip().upper()
        variant = CATEGORIES.get(cat)
        if variant is None:
            return
        if (get(C_REGISTER) or "RSV").strip().upper() not in ("RSV", ""):
            return
        d_cz = (get(C_FIRST_CZ) or "").strip()
        d_any = (get(C_FIRST) or "").strip()
        if len(d_cz) < 7 or not d_any:
            return
        if d_any != d_cz:
            if variant != "Whole":
                return
            variant = "Used"
        period = d_cz[:7]
        if period < HISTORY_FROM:
            return
        tokens = fuel_tokens(get(C_FUEL))
        fuel = base_fuel(tokens)
        key = (get(C_MAKE).strip().upper(), get(C_TYPE).strip(),
               get(C_VAR).strip(), get(C_VER).strip())
        if fuel == "HYBRID":
            hc = hybrid_class(get(C_HCLASS))
            if hc:
                self.key_evidence[key][hc] += 1
            direct = plug_in_direct(hc, co2_combined(get(C_CO2)))
            if direct is None:
                comb = combustion_of(tokens)
                self.pending[(variant, period, key, comb)] += 1
                if variant in TOP_SLUGS and period >= self.models_from:
                    self.pending_models[(variant, period, key, comb,
                                         *self._brand_model(get))] += 1
                return
            fuel = "PHEV" if direct else combustion_of(tokens)
        elif fuel == "UNKNOWN":
            self.unknown_fuel[(variant, period)][(get(C_FUEL) or "").strip()] += 1
            fuel = "OTHERS"
        self.counts[variant][period][fuel] += 1
        if variant in TOP_SLUGS and period >= self.models_from:
            self.models[(variant, period, fuel, *self._brand_model(get))] += 1

    @staticmethod
    def _brand_model(get) -> tuple[str, str]:
        brand = market_top.clean(get(C_MAKE))
        return brand, market_top.strip_brand(brand, market_top.clean(get(C_MODEL)))

    def resolve(self) -> None:
        """Settle the pending hybrids by their variant's recorded classes."""
        if self.resolved:
            return
        for (variant, period, key, comb), n in self.pending.items():
            self.counts[variant][period][self._resolve(key, comb)] += n
        for (variant, period, key, comb, brand, model), n in self.pending_models.items():
            self.models[(variant, period, self._resolve(key, comb), brand, model)] += n
        self.pending.clear()
        self.pending_models.clear()
        self.resolved = True

    def _resolve(self, key, comb: str) -> str:
        ev = self.key_evidence.get(key, {})
        return "PHEV" if ev.get("OVC", 0) > ev.get("NOVC", 0) else comb

    def month(self, variant: str, period: str) -> dict[str, int]:
        """Register counts of one month in the variant's register columns
        (REG_FUELS — for Whole too: HEV is filled later by estimate)."""
        self.resolve()
        c = self.counts[variant].get(period, collections.Counter())
        out = {k: c[k] for k in REG_FUELS}
        out["TOTAL"] = sum(out.values())
        return out

    def periods(self, variant: str) -> list[str]:
        self.resolve()
        return sorted(self.counts[variant])


def complete_month(snapshot: dt.date | None) -> str | None:
    """The newest month an extract generated on `snapshot` covers in full —
    always the month before the snapshot's month (the extract of 1 Oct holds
    a few hundred cars of 1 Oct itself)."""
    if snapshot is None:
        return None
    first = snapshot.replace(day=1) - dt.timedelta(days=1)
    return f"{first.year}-{first.month:02d}"


def snapshot_from_disposition(value: str | None) -> dt.date | None:
    m = re.search(r"RSV_vypis_vozidel_(\d{4})(\d{2})(\d{2})", value or "")
    if not m:
        return None
    return dt.date(int(m[1]), int(m[2]), int(m[3]))


def tally_lines(lines, snapshot: dt.date | None = None) -> Tally:
    """Count an iterable of text lines (the extract, header first)."""
    reader = csv.reader(lines)
    header = [h.strip().lstrip("﻿") for h in next(reader)]
    ix = {h: i for i, h in enumerate(header)}
    missing = [c for c in REQUIRED if c not in ix]
    if missing:
        sys.exit(f"RSV extract: required columns missing {missing} — schema drift, "
                 "update fetch_czechia.py")
    t = Tally()
    t.snapshot = snapshot
    upto = complete_month(snapshot)
    if upto:   # the top lists need the newest STORE_MONTHS months only
        y, m = int(upto[:4]), int(upto[5:7]) - market_top.STORE_MONTHS
        t.models_from = f"{y + (m - 1) // 12}-{(m - 1) % 12 + 1:02d}"
    width = len(header)
    for row in reader:
        if len(row) < width:
            continue
        t.add(lambda k, row=row: row[ix[k]])
    t.resolve()
    return t


# ── download ───────────────────────────────────────────────────────────────

class Truncated(RuntimeError):
    pass


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HTTP_HEADERS)
    return s


def probe_snapshot(session: requests.Session) -> dt.date | None:
    """The extract's date from the response headers only — the body (GBs)
    is never read: the connection is closed right after the headers."""
    try:
        with session.get(URL, stream=True, timeout=120) as r:
            r.raise_for_status()
            return snapshot_from_disposition(r.headers.get("Content-Disposition"))
    except requests.RequestException as e:
        print(f"  header probe failed ({e}); will download")
        return None


def stream_lines(response: requests.Response):
    """Decoded text lines of a (possibly gzip-encoded) streamed response."""
    gz = "gzip" in (response.headers.get("Content-Encoding") or "").lower()
    dec = zlib.decompressobj(16 + zlib.MAX_WBITS) if gz else None
    buf = b""
    first = True
    for chunk in response.raw.stream(1 << 20, decode_content=False):
        data = dec.decompress(chunk) if dec else chunk
        if not data:
            continue
        buf += data
        *complete, buf = buf.split(b"\n")
        for line in complete:
            s = line.decode("utf-8", "replace")
            if first:
                s = s.lstrip("﻿")
                first = False
            yield s + "\n"
    if dec:
        buf += dec.flush()
        if not dec.eof:
            raise Truncated("gzip stream ended early")
    if buf:
        yield buf.decode("utf-8", "replace")


def download_tally(session: requests.Session) -> Tally:
    """Stream the extract and count it; restart from the top on a dropped
    connection (the server cannot resume)."""
    for attempt in range(1, DOWNLOAD_ATTEMPTS + 1):
        started = time.time()
        try:
            with session.get(URL, stream=True, timeout=(60, 600)) as r:
                r.raise_for_status()
                if "html" in (r.headers.get("Content-Type") or ""):
                    raise RuntimeError(f"{URL}: got {r.headers.get('Content-Type')!r}, "
                                       "not the CSV")
                snap = snapshot_from_disposition(r.headers.get("Content-Disposition"))
                print(f"  extract {snap} — streaming (attempt {attempt}) …", flush=True)
                # csv.reader joins quoted multi-line fields itself.
                t = tally_lines(stream_lines(r), snap)
            if t.rows < MIN_ROWS:
                raise Truncated(f"only {t.rows:,} rows (expected ≥ {MIN_ROWS:,})")
            print(f"  {t.rows:,} rows in {(time.time() - started) / 60:.0f} min")
            return t
        except (requests.ConnectionError, requests.Timeout,
                requests.exceptions.ChunkedEncodingError,
                Truncated, zlib.error) as e:
            if attempt == DOWNLOAD_ATTEMPTS:
                raise
            wait = RETRY_WAIT[attempt - 1]
            print(f"  stream failed after {(time.time() - started) / 60:.0f} min "
                  f"({type(e).__name__}: {e}); restart {attempt + 1}/"
                  f"{DOWNLOAD_ATTEMPTS} in {wait}s", flush=True)
            time.sleep(wait)
    raise AssertionError("unreachable")


def tally_file(path: Path) -> Tally:
    """Offline: a saved extract (.csv or .csv.gz). The snapshot date comes
    from the file name if it has one."""
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8-sig", newline="") as f:
        return tally_lines(f, snapshot_from_disposition(path.name))


# ── CSV line-level upsert (invariant 2) ────────────────────────────────────

def fmt(v: int | None) -> str:
    return "" if v is None else f"{float(v):.1f}"


def render_line(variant: str, period: str, counts: dict, notes: str = "") -> str:
    buf = io.StringIO()
    csv.writer(buf, lineterminator="").writerow(
        [period, "monthly", variant, SOURCE]
        + [fmt(counts.get(k)) for k in fuels_of(variant) + ["TOTAL"]] + [notes])
    return buf.getvalue()


def read_csv_lines(path: Path, variant: str) -> tuple[str, list[str], str]:
    if not path.exists():
        return ",".join(csv_columns(variant)) + "\n", [], "\n"
    with open(path, encoding="utf-8", newline="") as f:
        text = f.read()
    eol = "\r\n" if "\r\n" in text else "\n"
    raw = text.splitlines(keepends=True)
    if not raw:
        return ",".join(csv_columns(variant)) + eol, [], eol
    return raw[0], [l for l in raw[1:] if l.strip()], eol


def _fields(line: str) -> list[str]:
    return next(csv.reader([line.rstrip("\r\n")]))


def upsert_lines(path: Path, variant: str, updates: dict[str, str],
                 force: bool) -> dict[str, int]:
    """Replace/insert only the given periods' lines; every other line is
    written back byte for byte. A new line goes before the first line with a
    later period. A line from another source is never replaced; an own line
    only with `force`."""
    header, lines, eol = read_csv_lines(path, variant)
    if header.rstrip("\r\n").split(",") != csv_columns(variant):
        sys.exit(f"{path}: unexpected header {header!r} — expected {csv_columns(variant)}")
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += eol
    stats = {"added": 0, "updated": 0, "unchanged": 0, "skipped": 0}
    for period, new in sorted(updates.items()):
        index = {(_fields(l)[0], _fields(l)[2]): i for i, l in enumerate(lines)}
        key = (period, variant)
        if key in index:
            old = lines[index[key]]
            if old.rstrip("\r\n") == new:
                stats["unchanged"] += 1
            elif _fields(old)[3] != SOURCE or not force:
                stats["skipped"] += 1
            else:
                lines[index[key]] = new + old[len(old.rstrip("\r\n")):]
                stats["updated"] += 1
        else:
            at = next((i for i, l in enumerate(lines) if _fields(l)[0] > period),
                      len(lines))
            lines.insert(at, new + eol)
            stats["added"] += 1
    if stats["added"] or stats["updated"]:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(header + "".join(lines))
    return stats


def csv_rows(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    with open(path, newline="", encoding="utf-8") as f:
        return {r["period"]: r for r in csv.DictReader(f)
                if (r.get("time_interval") or "monthly") == "monthly"}


def _num(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ── Whole: the estimated HEV / PETROL / DIESEL split ──────────────────────

def reference_split(have: dict[str, dict], before: str) -> tuple[str, dict[str, float]] | None:
    """Shares of HEV / PETROL / DIESEL in the newest month before `before`
    whose row is not ours (ACEA/SDA) and carries all three."""
    for p in sorted(have, reverse=True):
        if p >= before:
            continue
        r = have[p]
        if (r.get("source") or "") == SOURCE:
            continue
        vals = {k: _num(r.get(k)) for k in WHOLE_ESTIMATED}
        if any(v is None for v in vals.values()):
            continue
        s = sum(vals.values())
        if s > 0:
            return p, {k: v / s for k, v in vals.items()}
    return None


def split_remainder(remainder: int, shares: dict[str, float]) -> dict[str, int]:
    """Largest-remainder rounding, so the parts sum to `remainder` exactly."""
    raw = {k: remainder * shares[k] for k in WHOLE_ESTIMATED}
    out = {k: int(raw[k]) for k in WHOLE_ESTIMATED}
    rest = remainder - sum(out.values())
    for k in sorted(WHOLE_ESTIMATED, key=lambda k: raw[k] - out[k], reverse=True)[:rest]:
        out[k] += 1
    return out


def whole_row(reg: dict[str, int], have: dict[str, dict], period: str) -> tuple[dict, str]:
    """Register counts → a Whole row (with the estimated split) and its note."""
    ref = reference_split(have, period)
    if ref is None:
        sys.exit("Czechia.csv has no ACEA/SDA month with HEV/PETROL/DIESEL to "
                 "estimate the split from")
    ref_period, shares = ref
    remainder = reg["PETROL"] + reg["DIESEL"]
    est = split_remainder(remainder, shares)
    row = {"BEV": reg["BEV"], "PHEV": reg["PHEV"], "OTHERS": reg["OTHERS"], **est}
    row["TOTAL"] = sum(row[k] for k in WHOLE_FUELS)
    assert row["TOTAL"] == reg["TOTAL"], (row, reg)
    note = ("register count (BEV/PHEV/OTHERS/TOTAL); HEV/PETROL/DIESEL estimated "
            f"from the {ref_period} ACEA split — replaced by ACEA's figures when "
            "they are published")
    return row, note


# ── month selection & checks ───────────────────────────────────────────────

def months_to_write(t: Tally, variant: str, have: dict[str, dict], upto: str,
                    backfill: bool, force: bool) -> list[str]:
    """Backfill: every month from the variant's first month. Otherwise the
    months after the CSV's newest row (normally just `upto`; more if a
    monthly run was missed). Months a CSV has are skipped unless `force`."""
    first = WHOLE_FROM if variant == "Whole" else HISTORY_FROM
    if not backfill and have:
        first = max(first, min(upto, _next_month(max(have))))
    cand = [p for p in t.periods(variant) if first <= p <= upto]
    return [p for p in cand if force or p not in have]


def _next_month(period: str) -> str:
    y, m = int(period[:4]), int(period[5:7])
    return f"{y + m // 12}-{m % 12 + 1:02d}"


def completeness_ok(t: Tally, period: str) -> tuple[bool, str]:
    y, m = int(period[:4]), int(period[5:7])
    prev = []
    for i in range(1, 13):
        mm = m - i
        yy = y + (mm - 1) // 12
        mm = (mm - 1) % 12 + 1
        prev.append(t.month("Whole", f"{yy}-{mm:02d}")["TOTAL"])
    prev = [v for v in prev if v]
    if len(prev) < 6:
        return True, "too little history to judge"
    med = statistics.median(prev)
    cur = t.month("Whole", period)["TOTAL"]
    return cur >= COMPLETENESS_FLOOR * med, f"{cur:,} vs trailing median {med:,.0f}"


def unknown_fuel_ok(t: Tally, period: str) -> bool:
    unk = sum(t.unknown_fuel.get(("Whole", period), {}).values())
    tot = t.month("Whole", period)["TOTAL"] or 1
    if unk:
        print(f"  unknown fuel strings in Whole {period}: "
              f"{dict(t.unknown_fuel[('Whole', period)].most_common(10))}")
    return unk / tot <= UNKNOWN_FUEL_MAX


# ── top brands / models ────────────────────────────────────────────────────

def refresh_top(t: Tally, upto: str) -> None:
    months = sorted({p for (v, p, *_r) in t.models if p <= upto})[-market_top.STORE_MONTHS:]
    for variant, slug in TOP_SLUGS.items():
        fresh: dict[str, tuple[dict, int]] = {}
        for p in months:
            units = collections.Counter()
            for (v, pp, fuel, brand, model), n in t.models.items():
                if v == variant and pp == p:
                    units[(fuel, brand, model)] += n
            if units:
                fresh[p] = (dict(units), t.month(variant, p)["TOTAL"])
        if fresh:
            market_top.refresh_from_store("Czechia", SOURCE, TOP_UNIT, slug,
                                          fresh, variant)


# ── main ───────────────────────────────────────────────────────────────────

def selected(arg: str) -> list[str]:
    if arg == "all":
        return list(VARIANT_CSV)
    out = [v.strip() for v in arg.split(",") if v.strip()]
    bad = [v for v in out if v not in VARIANT_CSV]
    if bad or not out:
        sys.exit(f"Unknown variant {bad or arg!r}. Valid: {list(VARIANT_CSV)} or 'all'.")
    return out


def write(t: Tally, variants: list[str], backfill: bool, force: bool) -> set[str]:
    upto = t.complete_to
    if upto is None:
        sys.exit("extract date unknown — cannot tell which month is complete")
    print(f"Extract of {t.snapshot}: complete to {upto}")
    ok, why = completeness_ok(t, upto)
    if not ok and not force:
        sys.exit(f"Whole {upto} looks incomplete ({why}) — not written; --force overrides")
    if not unknown_fuel_ok(t, upto) and not force:
        sys.exit(f"too many unknown fuel strings in {upto} — extend fuel_tokens()")
    changed: set[str] = set()
    for v in variants:
        path = REPO / VARIANT_CSV[v]
        have = csv_rows(path)
        periods = months_to_write(t, v, have, upto, backfill or not path.exists(), force)
        updates = {}
        for p in periods:
            reg = t.month(v, p)
            if not reg["TOTAL"]:
                continue
            if v == "Whole":
                row, note = whole_row(reg, have, p)
            else:
                row, note = reg, ""
            assert sum(row[k] for k in fuels_of(v)) == row["TOTAL"], (v, p, row)
            updates[p] = render_line(v, p, row, note)
        if not updates:
            print(f"  {VARIANT_CSV[v]}: nothing to write")
            continue
        for p in sorted(updates)[-3:]:
            print(f"  {v} {p}: {updates[p]}")
        stats = upsert_lines(path, v, updates, force)
        print(f"  {VARIANT_CSV[v]}: {stats}")
        if stats["added"] or stats["updated"]:
            changed.add(v)
    market_top.guarded(refresh_top, t, upto)
    return changed


def summary(t: Tally, upto: str) -> None:
    out = os.environ.get("GITHUB_STEP_SUMMARY")
    if not out:
        return
    lines = [f"### Czechia — RSV extract of {t.snapshot} ({t.rows:,} rows)", "",
             "| variant | month | BEV | PHEV | PETROL* | DIESEL* | OTHERS | TOTAL |",
             "|---|---|---|---|---|---|---|---|"]
    for v in VARIANT_CSV:
        c = t.month(v, upto)
        lines.append(f"| {v} | {upto} | " + " | ".join(f"{c[k]:,}" for k in REG_FUELS)
                     + f" | {c['TOTAL']:,} |")
    lines += ["", "\\* register counts incl. full/mild hybrids; Whole's HEV/PETROL/DIESEL "
              "are written as an estimate until ACEA publishes the month."]
    with open(out, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--variant", default="all",
                    help=f"all | {' | '.join(VARIANT_CSV)} — or several, comma-separated")
    ap.add_argument("--backfill", action="store_true",
                    help="Write every month a CSV lacks (Whole from "
                         f"{WHOLE_FROM}, the others from {HISTORY_FROM}).")
    ap.add_argument("--force", action="store_true",
                    help="Ignore the self-throttle and the guards; rewrite own rows.")
    ap.add_argument("--from-file", type=Path,
                    help="Count a saved extract (.csv / .csv.gz) instead of downloading.")
    ap.add_argument("--snapshot", help="Extract date YYYY-MM-DD for --from-file "
                                       "(default: from the file name).")
    ap.add_argument("--github-output", default=os.environ.get("GITHUB_OUTPUT"))
    args = ap.parse_args()
    variants = selected(args.variant)

    if args.from_file:
        t = tally_file(args.from_file)
        if args.snapshot:
            t.snapshot = dt.date.fromisoformat(args.snapshot)
    else:
        session = make_session()
        snap = probe_snapshot(session)
        upto = complete_month(snap)
        if upto and not (args.force or args.backfill):
            todo = [v for v in variants
                    if upto >= (WHOLE_FROM if v == "Whole" else HISTORY_FROM)
                    and upto not in csv_rows(REPO / VARIANT_CSV[v])]
            if not todo:
                print(f"Extract of {snap} is complete to {upto}; every CSV has it — "
                      "nothing to do.")
                return emit(args, set())
        t = download_tally(session)

    changed = write(t, variants, args.backfill, args.force)
    if t.complete_to:
        summary(t, t.complete_to)
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
