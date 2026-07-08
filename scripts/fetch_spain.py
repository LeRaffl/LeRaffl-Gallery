#!/usr/bin/env python3
"""
Fetch Spain new-registration data from DGT monthly matriculaciones microdata
and upsert data/Spain.csv.

Source
------
DGT (Dirección General de Tráfico) publishes one fixed-width record per
registered vehicle, monthly, free, no login:

    https://www.dgt.es/microdatos/salida/{Y}/{M}/vehiculos/matriculaciones/
        export_mensual_mat_{YYYYMM}.zip

The month directory is NOT zero-padded ("2026/4/", the padded variant 404s).
Records are 714 chars over 69 fields per the MATRICULACIONES_MATRABA.pdf
record design; the layout below was transcribed and verified against real
records by scripts/probe_spain_dgt.py (probe runs #1–#7, 2026-07-08). The
first line of the file is an informational banner, not data.

Market definition ("Filter C" from the probe)
---------------------------------------------
    COD_TIPO ∈ {40 turismo, 25 todo terreno}  AND  IND_NUEVO_USADO = N

This is the registry-side reading of "turismos y todoterrenos". It is
deliberately NOT identical to ANFAC/ACEA's market: ANFAC segments M1 people
movers (Multivan, V-Class, ID.Buzz, …) into light commercials on a per-model
basis, which cannot be replicated from DGT attributes. Expected steady-state
deltas vs ACEA (measured on 2026-01/02/03/05): TOTAL ≈ +2 %, DIESEL ≈ +30 %,
BEV/PHEV ≈ +3 %, HEV/PETROL ≈ identical. This is a definitional difference,
not an error — documented in footnotes.csv and
docs/architecture/28-source-spain.md §4. Consistency with the ACEA series
was gate-checked by the probe before this fetcher was built.

Fuel mapping (gallery schema with EREV column, China-style)
-----------------------------------------------------------
    CATEGORIA_VEHICULO_ELECTRICO:  BEV → BEV     PHEV → PHEV
                                   REEV → EREV   (renderer folds EREV into
                                   PHEV for the 3-curve plot and shows it as
                                   its own TTM band — same as China)
                                   HEV → HEV     FCEV/HICEV → OTHERS
    else COD_PROPULSION_ITV:       0 → PETROL    1 → DIESEL
                                   2 → BEV (electric propulsion without a
                                       category label; 0–1 per month)
                                   anything else (GLP/GNC/GNL/H2/…) → OTHERS

Components sum to TOTAL exactly (single-pass count over the same records);
the sanity check is therefore an exact assertion, not a tolerance.

Modes
-----
* Monthly (default): fetch the previous calendar month, upsert one row.
  Self-throttles via the latest period already in the CSV.
* Bootstrap/backfill (--backfill, or automatically when data/Spain.csv does
  not exist): walk months DESCENDING from the previous month down to
  --backfill-from (default 2015-01). Stops at the first month whose download
  404s or whose record length ≠ 714 (older MATRABA layout era — extend the
  layout table before trusting offsets there). Afterwards, any period still
  missing is spliced from data/Spain_legacy.csv (the pre-DGT curated series,
  source "ACEA / DGT / asierlizarraga"), keeping its original source string,
  so the gallery's fit window stays fully populated. The seam is visible in
  the source column and documented.

Overwrite rule (mirrors the fetch_acea.py courtesy rule): a row is
overwritten only if it doesn't exist or its source is exactly "DGT" or
"ACEA". Blend/legacy rows are never touched without --force.

Usage
-----
    python scripts/fetch_spain.py                      # monthly
    python scripts/fetch_spain.py --backfill           # explicit bootstrap
    python scripts/fetch_spain.py --period 2026-05     # one specific month
    python scripts/fetch_spain.py --backfill --backfill-from 2018-01
    [--csv data/Spain.csv] [--legacy data/Spain_legacy.csv] [--force]

See docs/architecture/28-source-spain.md for the full investigation record.
"""
import argparse
import csv
import io
import os
import sys
import zipfile
from datetime import date
from pathlib import Path

import requests

CSV_PATH_DEFAULT = "data/Spain.csv"
LEGACY_PATH_DEFAULT = "data/Spain_legacy.csv"
SOURCE = "DGT"
BACKFILL_FROM_DEFAULT = "2015-01"

CSV_COLUMNS = [
    "period", "time_interval", "variant", "source",
    "BEV", "PHEV", "EREV", "HEV", "PETROL", "DIESEL", "OTHERS",
    "TOTAL", "notes",
]
FUEL_COLUMNS = ["BEV", "PHEV", "EREV", "HEV", "PETROL", "DIESEL", "OTHERS"]

ZIP_URL_CANDIDATES = [
    # Verified: month directory not zero-padded; keep the padded variant as
    # a fallback in case DGT ever normalises it.
    "https://www.dgt.es/microdatos/salida/{y}/{m_nopad}/vehiculos/matriculaciones/export_mensual_mat_{ym}.zip",
    "https://www.dgt.es/microdatos/salida/{y}/{m}/vehiculos/matriculaciones/export_mensual_mat_{ym}.zip",
]

# dgt.es 403s bare clients; browser headers + homepage warmup (same class of
# WAF handling as fetch_acea.py).
HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
    "Referer": "https://www.dgt.es/",
    "Upgrade-Insecure-Requests": "1",
}

# MATRABA record layout: (field name, CHAR length), positions cumulative.
# Transcribed from MATRICULACIONES_MATRABA.pdf Tabla 1 and verified against
# real records (probe run #3). Lengths sum to 714 == observed record length.
MATRABA_LAYOUT: list[tuple[str, int]] = [
    ("FEC_MATRICULA", 8), ("COD_CLASE_MAT", 1), ("FEC_TRAMITACION", 8),
    ("MARCA_ITV", 30), ("MODELO_ITV", 22), ("COD_PROCEDENCIA_ITV", 1),
    ("BASTIDOR_ITV", 21), ("COD_TIPO", 2), ("COD_PROPULSION_ITV", 1),
    ("CILINDRADA_ITV", 5), ("POTENCIA_ITV", 6), ("TARA", 6),
    ("PESO_MAX", 6), ("NUM_PLAZAS", 3), ("IND_PRECINTO", 2),
    ("IND_EMBARGO", 2), ("NUM_TRANSMISIONES", 2), ("NUM_TITULARES", 2),
    ("LOCALIDAD_VEHICULO", 24), ("COD_PROVINCIA_VEH", 2),
    ("COD_PROVINCIA_MAT", 2), ("CLAVE_TRAMITE", 1), ("FEC_TRAMITE", 8),
    ("CODIGO_POSTAL", 5), ("FEC_PRIM_MATRICULACION", 8),
    ("IND_NUEVO_USADO", 1), ("PERSONA_FISICA_JURIDICA", 1),
    ("CODIGO_ITV", 9), ("SERVICIO", 3), ("COD_MUNICIPIO_INE_VEH", 5),
    ("MUNICIPIO", 30), ("KW_ITV", 7), ("NUM_PLAZAS_MAX", 3),
    ("CO2_ITV", 5), ("RENTING", 1), ("COD_TUTELA", 1), ("COD_POSESION", 1),
    ("IND_BAJA_DEF", 1), ("IND_BAJA_TEMP", 1), ("IND_SUSTRACCION", 1),
    ("BAJA_TELEMATICA", 11), ("TIPO_ITV", 25), ("VARIANTE_ITV", 25),
    ("VERSION_ITV", 35), ("FABRICANTE_ITV", 70),
    ("MASA_ORDEN_MARCHA_ITV", 6), ("MASA_MAXIMA_TECNICA_ADMISIBLE_ITV", 6),
    ("CATEGORIA_HOMOLOGACION_EUROPEA_ITV", 4), ("CARROCERIA", 4),
    ("PLAZAS_PIE", 3), ("NIVEL_EMISIONES_EURO_ITV", 8),
    ("CONSUMO_WH_KM_ITV", 4), ("CLASIFICACION_REGLAMENTO_VEHICULOS_ITV", 4),
    ("CATEGORIA_VEHICULO_ELECTRICO", 4), ("AUTONOMIA_VEHICULO_ELECTRICO", 6),
    ("MARCA_VEHICULO_BASE", 30), ("FABRICANTE_VEHICULO_BASE", 50),
    ("TIPO_VEHICULO_BASE", 35), ("VARIANTE_VEHICULO_BASE", 25),
    ("VERSION_VEHICULO_BASE", 35), ("DISTANCIA_EJES_12_ITV", 4),
    ("VIA_ANTERIOR_ITV", 4), ("VIA_POSTERIOR_ITV", 4),
    ("TIPO_ALIMENTACION_ITV", 1), ("CONTRASENA_HOMOLOGACION_ITV", 25),
    ("ECO_INNOVACION_ITV", 1), ("REDUCCION_ECO_ITV", 4),
    ("CODIGO_ECO_ITV", 25), ("FEC_PROCESO", 8),
]
RECORD_LEN = sum(l for _, l in MATRABA_LAYOUT)  # 714


def _slice(name: str) -> tuple[int, int]:
    pos = 0
    for n, length in MATRABA_LAYOUT:
        if n == name:
            return pos, pos + length
        pos += length
    raise KeyError(name)


SL_TIPO = _slice("COD_TIPO")
SL_PROPULSION = _slice("COD_PROPULSION_ITV")
SL_NUEVO_USADO = _slice("IND_NUEVO_USADO")
SL_CAT_ELECTRICO = _slice("CATEGORIA_VEHICULO_ELECTRICO")

TURISMO_TIPOS = {"40", "25"}


class LayoutMismatch(RuntimeError):
    """Record length ≠ 714 — an older MATRABA layout era."""


class NotPublished(RuntimeError):
    """All URL candidates 404ed — month not (or no longer) available."""


# ── download & parse ───────────────────────────────────────────────────────

def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HTTP_HEADERS)
    try:
        s.get("https://www.dgt.es/", timeout=30)
    except requests.RequestException as e:
        print(f"  warmup GET failed (non-fatal): {e}")
    return s


def download_month(session: requests.Session, period: str) -> tuple[bytes, str]:
    """Return (txt_bytes, zip_url) for YYYY-MM, or raise NotPublished."""
    y, m = period.split("-")
    last_status = "?"
    for tpl in ZIP_URL_CANDIDATES:
        url = tpl.format(y=y, m=m, m_nopad=str(int(m)), ym=y + m)
        r = session.get(url, timeout=180)
        last_status = str(r.status_code)
        if r.status_code == 200 and len(r.content) > 1024:
            with zipfile.ZipFile(io.BytesIO(r.content)) as z:
                txt_names = [n for n in z.namelist()
                             if n.lower().endswith(".txt")]
                if not txt_names:
                    raise RuntimeError(f"{period}: no .txt inside {url}")
                return z.read(txt_names[0]), url
    raise NotPublished(f"{period}: no candidate URL worked "
                       f"(last HTTP {last_status})")


def aggregate_whole(txt_bytes: bytes, period: str) -> dict[str, int]:
    """One pass: gallery fuel split for tipo 40/25, new. Exact by design."""
    counts = {k: 0 for k in FUEL_COLUMNS}
    n_records = 0
    bad_len = 0
    stream = io.TextIOWrapper(io.BytesIO(txt_bytes), encoding="latin-1")
    for i, line in enumerate(stream):
        if i == 0 and not line[:1].isdigit():
            continue  # informational banner
        line = line.rstrip("\r\n")
        if not line.strip():
            continue
        n_records += 1
        if len(line) != RECORD_LEN:
            bad_len += 1
            continue
        if line[SL_TIPO[0]:SL_TIPO[1]].strip() not in TURISMO_TIPOS:
            continue
        if line[SL_NUEVO_USADO[0]:SL_NUEVO_USADO[1]] != "N":
            continue
        cat = line[SL_CAT_ELECTRICO[0]:SL_CAT_ELECTRICO[1]].strip().upper()
        if cat == "BEV":
            counts["BEV"] += 1
        elif cat == "REEV":
            counts["EREV"] += 1
        elif cat == "PHEV":
            counts["PHEV"] += 1
        elif cat == "HEV":
            counts["HEV"] += 1
        elif cat in ("FCEV", "HICEV"):
            counts["OTHERS"] += 1
        else:
            prop = line[SL_PROPULSION[0]:SL_PROPULSION[1]]
            if prop == "0":
                counts["PETROL"] += 1
            elif prop == "1":
                counts["DIESEL"] += 1
            elif prop == "2":
                counts["BEV"] += 1  # electric propulsion w/o category label
            else:
                counts["OTHERS"] += 1

    if n_records == 0:
        raise RuntimeError(f"{period}: file contained no data records.")
    if bad_len > n_records * 0.01:
        raise LayoutMismatch(
            f"{period}: {bad_len}/{n_records} records deviate from length "
            f"{RECORD_LEN} — older MATRABA layout era; refusing to aggregate "
            f"with these offsets. Extend MATRABA_LAYOUT for that era first."
        )
    counts["TOTAL"] = sum(counts[k] for k in FUEL_COLUMNS)
    if counts["TOTAL"] < 20_000:
        raise RuntimeError(f"{period}: implausibly small market "
                           f"({counts['TOTAL']}); refusing to write.")
    return counts


# ── CSV handling ───────────────────────────────────────────────────────────

def load_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return [dict(r) for r in csv.DictReader(f)]


def write_rows(path: Path, rows: list[dict]) -> None:
    rows.sort(key=lambda r: (r.get("variant") or "", r["period"]))
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS, lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in CSV_COLUMNS})


def may_overwrite(existing: dict | None, force: bool) -> bool:
    if existing is None or force:
        return True
    src = (existing.get("source") or "").strip().upper()
    return src in ("DGT", "ACEA")


def upsert(rows: list[dict], period: str, counts: dict[str, int],
           zip_url: str, force: bool) -> str:
    """Returns 'added' | 'updated' | 'unchanged' | 'skipped'."""
    existing = next((r for r in rows
                     if r["period"] == period
                     and (r.get("variant") or "Whole") == "Whole"), None)
    if not may_overwrite(existing, force):
        return "skipped"
    new_row = {
        "period": period, "time_interval": "monthly", "variant": "Whole",
        "source": SOURCE, "notes": zip_url,
        **{k: f"{counts[k]:.1f}" for k in FUEL_COLUMNS + ["TOTAL"]},
    }
    if existing is not None:
        same = all(float(existing.get(k) or 0) == counts[k]
                   for k in FUEL_COLUMNS + ["TOTAL"])
        if same and (existing.get("source") or "") == SOURCE:
            return "unchanged"
        rows.remove(existing)
        rows.append(new_row)
        return "updated"
    rows.append(new_row)
    return "added"


def splice_legacy(rows: list[dict], legacy_path: Path) -> int:
    """Copy legacy rows for periods the DGT series doesn't cover (pre-layout
    era / gaps), preserving their original source string. EREV stays empty —
    the renderer treats absent EREV as zero, and the TTM partial-window guard
    keeps the EREV band flat until real coverage starts."""
    if not legacy_path.exists():
        print(f"  legacy file {legacy_path} not found — no splice.")
        return 0
    have = {(r["period"], r.get("variant") or "Whole") for r in rows}
    n = 0
    for lr in load_rows(legacy_path):
        key = (lr["period"], lr.get("variant") or "Whole")
        if key in have:
            continue
        rows.append({k: lr.get(k, "") for k in CSV_COLUMNS})
        n += 1
    return n


# ── main ───────────────────────────────────────────────────────────────────

def previous_month(today: date) -> str:
    if today.month == 1:
        return f"{today.year - 1}-12"
    return f"{today.year}-{today.month - 1:02d}"


def month_range_desc(newest: str, oldest: str) -> list[str]:
    y, m = map(int, newest.split("-"))
    oy, om = map(int, oldest.split("-"))
    out = []
    while (y, m) >= (oy, om):
        out.append(f"{y}-{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--csv", default=CSV_PATH_DEFAULT)
    ap.add_argument("--legacy", default=LEGACY_PATH_DEFAULT)
    ap.add_argument("--period", default="",
                    help="Specific month YYYY-MM (default: previous month).")
    ap.add_argument("--backfill", action="store_true",
                    help="Walk months descending to --backfill-from. Implied "
                         "when the CSV does not exist yet (bootstrap).")
    ap.add_argument("--backfill-from", default=BACKFILL_FROM_DEFAULT)
    ap.add_argument("--force", action="store_true",
                    help="Overwrite rows regardless of their source string.")
    ap.add_argument("--github-output",
                    default=os.environ.get("GITHUB_OUTPUT"),
                    help="Write `changed=true|false` for the workflow.")
    args = ap.parse_args()

    csv_path = Path(args.csv)
    rows = load_rows(csv_path)
    bootstrap = not csv_path.exists()
    backfill = args.backfill or bootstrap
    if bootstrap:
        print(f"{csv_path} does not exist — bootstrap backfill from "
              f"{args.backfill_from}.")

    newest = args.period or previous_month(date.today())
    periods = (month_range_desc(newest, args.backfill_from)
               if backfill else [newest])

    # Monthly self-throttle: skip HTTP entirely if the row is already there.
    if not backfill and not args.force:
        if any(r["period"] == newest and (r.get("source") or "") == SOURCE
               for r in rows):
            print(f"{newest} already fetched from DGT; nothing to do.")
            return emit(args, False)

    session = make_session()
    changed = False
    stopped_at: str | None = None

    for period in periods:
        try:
            txt, url = download_month(session, period)
            counts = aggregate_whole(txt, period)
        except NotPublished as e:
            if backfill and period != newest:
                print(f"  {e} — stopping the walk here.")
                stopped_at = period
                break
            print(f"{e} — will retry on the next scheduled run.")
            continue
        except LayoutMismatch as e:
            print(f"  {e}")
            stopped_at = period
            break
        status = upsert(rows, period, counts, url, args.force)
        if status in ("added", "updated"):
            changed = True
        print(f"{period}: {status}  "
              + " ".join(f"{k}={counts[k]:,}" for k in FUEL_COLUMNS + ["TOTAL"]))

    if backfill:
        n = splice_legacy(rows, Path(args.legacy))
        if n:
            changed = True
        print(f"Legacy splice: {n} rows copied from {args.legacy}"
              + (f" (DGT walk stopped at {stopped_at})" if stopped_at else ""))

    if changed:
        write_rows(csv_path, rows)
        print(f"Wrote {csv_path} ({len(rows)} rows).")
    else:
        print("No changes.")
    return emit(args, changed)


def emit(args, changed: bool) -> int:
    if args.github_output:
        with open(args.github_output, "a", encoding="utf-8") as f:
            f.write(f"changed={'true' if changed else 'false'}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
