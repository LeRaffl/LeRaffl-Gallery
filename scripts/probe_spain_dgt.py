#!/usr/bin/env python3
"""
Probe DGT (Dirección General de Tráfico) monthly matriculaciones microdata
for Spain and check consistency against the ACEA rows in data/Spain.csv.

⚠ This is a PROBE, not a fetcher. It never writes to data/. Its job is to
answer, from a network position that can actually reach dgt.es (GitHub
Actions runner or the maintainer's machine — the Claude sandbox proxy
denies CONNECT to *.dgt.es / *.dgt.gob.es), the questions that block a real
scripts/fetch_spain.py:

  1. Does the monthly microdata zip download without login/certificate,
     and from which exact URL?  (Candidate patterns tried in order; the
     first hit is reported.)
  2. What is the record layout?  The .txt is fixed-width with NO column
     header (the first line is an informational banner: "Vehículos
     matriculados. Letras de la serie …").  Positions come from the
     MATRICULACIONES_MATRABA.pdf design document, which this probe also
     downloads and auto-parses (pdftotext -layout).
  3. Do DGT-derived fuel splits reconcile with ACEA/ANFAC?  ACEA's Spain
     figures come via DGT → Ideauto/MSI → ANFAC → ACEA, so they should be
     close but are known not to be identical (different market definition
     and cut-off).  The probe aggregates the gallery fuel split for
     "turismos y todoterrenos" under several candidate filters and prints
     per-fuel deltas against the existing data/Spain.csv row.
  4. What would the extra variants look like?  One scan prints counts by
     EU homologation category (M1/N1/N2/N3/M2/M3/L → Whole/Vans/HDV/Buses),
     new-vs-used (IND_NUEVO_USADO → Used Imports), and rental service
     (SERVICIO/RENTING → Italy-style Rental/NonRental).

Every stage degrades to diagnostics instead of failing silently: if the
design PDF can't be auto-parsed, the probe dumps its text to the report
directory so the layout can be transcribed manually; if a fuel column
can't be located, it prints the candidate field names it saw.

Fuel mapping being probed (gallery schema BEV/PHEV/HEV/PETROL/DIESEL/OTHERS):

    CATEGORIA_VEHICULO_ELECTRICO:  BEV → BEV        PHEV → PHEV
                                   REEV → reported separately (ACEA counts
                                          EREV under BEV; decide on evidence)
                                   HEV → HEV        FCEV/HICEV → OTHERS
    else by COD_PROPULSION_ITV:    0/Gasolina → PETROL   1/Diésel → DIESEL
                                   anything else (GLP, GNC, GNL, H2, …) → OTHERS

Usage
-----
    python scripts/probe_spain_dgt.py --period 2026-05 [--period 2026-04 …]
        [--report-dir probe_report] [--zip-url URL] [--design-pdf PATH_OR_URL]
        [--keep-sample N]

Writes a Markdown report to <report-dir>/report.md (used as the GitHub
Actions step summary) plus raw diagnostics (design-pdf text dump, first
data lines, unmatched-field lists).

See docs/architecture/28-source-spain.md for the full investigation context.
"""
import argparse
import collections
import csv
import io
import re
import subprocess
import sys
import unicodedata
import zipfile
from pathlib import Path

import requests

# ── constants ──────────────────────────────────────────────────────────────

# Candidate URL patterns for the monthly matriculaciones microdata zip.
# Pattern 1 is the one documented on the "Microdatos de Matriculaciones de
# Vehículos (mensual)" page (dgt.es → DGT en cifras); the others are
# fallbacks in case of zero-padding or naming drift. {y}=year, {m}=2-digit
# month, {ym}=YYYYMM.
ZIP_URL_CANDIDATES = [
    # Verified by probe run #1 (2026-07-08): month directory is NOT
    # zero-padded ("2026/4/", not "2026/04/"); the zero-padded variant 404s.
    "https://www.dgt.es/microdatos/salida/{y}/{m_nopad}/vehiculos/matriculaciones/export_mensual_mat_{ym}.zip",
    "https://www.dgt.es/microdatos/salida/{y}/{m}/vehiculos/matriculaciones/export_mensual_mat_{ym}.zip",
    "https://www.dgt.es/microdatos/salida/{y}/{m}/vehiculos/matriculaciones/export_mensual_mat_{ym}.txt.gz",
]

# The record-design PDF (field name / start position / length table).
DESIGN_PDF_CANDIDATES = [
    "https://www.dgt.es/export/sites/web-DGT/.galleries/downloads/dgt-en-cifras/matraba/MATRICULACIONES_MATRABA.pdf",
    "https://sedeapl.dgt.gob.es/IEST_INTER/pdfs/disenoRegistro/vehiculos/matriculaciones/MATRICULACIONES_MATRABA.pdf",
]

SPAIN_CSV = Path("data/Spain.csv")

# dgt.es sits behind a WAF that 403s non-browser clients (same class of
# problem as ACEA, see scripts/fetch_acea.py). Full browser header set +
# a homepage warmup GET on the same session.
HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
    "Referer": "https://www.dgt.es/",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Upgrade-Insecure-Requests": "1",
}

# Tolerant field-name matching: design-doc names vary in accents/underscores
# across MATRABA revisions, so we match normalised substrings.
FIELD_PATTERNS = {
    "fec_matricula":   r"FEC.?MATRICULA$",
    "clase_mat":       r"CLASE.?MAT",
    "cod_tipo":        r"(COD.?TIPO(?!.*SERVICIO)|TIPO.?VEHICULO)",
    "propulsion":      r"PROPULSION",
    "nuevo_usado":     r"NUEVO.?USADO",
    "servicio":        r"SERVICIO",
    "renting":         r"RENTING",
    "categoria_homologacion": r"CATEGORIA.?HOMOLOGACION",
    "categoria_electrico":    r"CATEGORIA.?VEHICULO.?ELECTRICO",
    "clasificacion_reglamento": r"CLASIFICACION.?REGLAMENTO",
}

GALLERY_FUELS = ("BEV", "PHEV", "HEV", "PETROL", "DIESEL", "OTHERS", "TOTAL")


def norm(s: str) -> str:
    """Uppercase, strip accents and non-alphanumerics → matching key."""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^A-Z0-9]+", "_", s.upper()).strip("_")


# ── download ───────────────────────────────────────────────────────────────

def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HTTP_HEADERS)
    try:  # warmup: lets the WAF set whatever cookies it wants on the session
        s.get("https://www.dgt.es/", timeout=30)
    except requests.RequestException as e:
        print(f"  warmup GET failed (non-fatal): {e}")
    return s


def try_download(session: requests.Session, urls: list[str],
                 dest: Path, log: list[str]) -> str | None:
    """First URL that returns 200 wins; logs every attempt. Returns the URL."""
    for url in urls:
        try:
            r = session.get(url, timeout=180)
        except requests.RequestException as e:
            log.append(f"- `{url}` → request error: {e}")
            continue
        log.append(f"- `{url}` → HTTP {r.status_code}, "
                   f"{len(r.content):,} bytes, "
                   f"content-type `{r.headers.get('content-type', '?')}`")
        if r.status_code == 200 and len(r.content) > 1024:
            dest.write_bytes(r.content)
            return url
    return None


# ── design-PDF parsing ─────────────────────────────────────────────────────

def parse_design_pdf(pdf_path: Path, dump_path: Path) -> list[tuple[str, int, int]]:
    """Extract (field_name, start_1based, length) from the MATRABA design PDF.

    The design table lists one row per field with the field name and either
    (position, length) or (from, to) columns. We accept any line shaped like
        <NAME with letters/underscores/accents>  …  <int>  <int>
    and disambiguate (position,length) vs (from,to) afterwards: if the second
    integer of every row equals first_int_of_next_row - first_int (i.e. it
    behaves like a length that tiles the record), treat as (pos,len); if
    second ≥ first and next row starts at second+1, treat as (from,to).
    Always dumps the raw pdftotext output for manual fallback.
    """
    try:
        out = subprocess.run(["pdftotext", "-layout", str(pdf_path), "-"],
                             check=True, capture_output=True, text=True)
    except FileNotFoundError:
        sys.exit("pdftotext not found. Install poppler-utils.")
    text = out.stdout
    dump_path.write_text(text, encoding="utf-8")

    rows: list[tuple[str, int, int]] = []
    line_re = re.compile(
        r"^\s*([A-ZÁÉÍÓÚÜÑa-záéíóúüñ][A-ZÁÉÍÓÚÜÑa-záéíóúüñ0-9_ ./()-]*?)"
        r"\s{2,}.*?(\d{1,4})\s+(\d{1,4})\s*$"
    )
    for line in text.splitlines():
        m = line_re.match(line)
        if not m:
            continue
        name = m.group(1).strip()
        a, b = int(m.group(2)), int(m.group(3))
        if norm(name) in ("", "POSICION", "LONGITUD", "CAMPO", "NOMBRE"):
            continue
        rows.append((name, a, b))

    if len(rows) < 10:
        return []

    # Decide (pos,len) vs (from,to) by checking which interpretation tiles.
    poslen_hits = sum(
        1 for (_, a1, b1), (_, a2, _) in zip(rows, rows[1:]) if a1 + b1 == a2
    )
    fromto_hits = sum(
        1 for (_, _, b1), (_, a2, _) in zip(rows, rows[1:]) if b1 + 1 == a2
    )
    fields: list[tuple[str, int, int]] = []
    if fromto_hits > poslen_hits:
        for name, a, b in rows:
            if b >= a:
                fields.append((name, a, b - a + 1))
    else:
        for name, a, b in rows:
            fields.append((name, a, b))
    return fields


def locate_fields(fields: list[tuple[str, int, int]]) -> dict[str, tuple[int, int]]:
    """Map our logical keys to (start_0based, end_0based) slices."""
    located: dict[str, tuple[int, int]] = {}
    for key, pat in FIELD_PATTERNS.items():
        rex = re.compile(pat)
        for name, start, length in fields:
            if rex.search(norm(name)):
                located[key] = (start - 1, start - 1 + length)
                break
    return located


# ── record iteration & aggregation ─────────────────────────────────────────

def iter_records(txt_bytes: bytes, skip_banner: bool = True):
    """Yield decoded fixed-width lines. First line is an informational banner
    ('Vehículos matriculados. Letras de la serie …'), not data."""
    stream = io.TextIOWrapper(io.BytesIO(txt_bytes), encoding="latin-1")
    for i, line in enumerate(stream):
        if i == 0 and skip_banner and not line[:1].isdigit():
            continue
        line = line.rstrip("\r\n")
        if line.strip():
            yield line


def field(line: str, sl: tuple[int, int]) -> str:
    return line[sl[0]:sl[1]].strip()


def classify_fuel(cat_elec: str, propulsion: str) -> str:
    """Gallery fuel bucket for one record (REEV kept separate for reporting)."""
    ce = norm(cat_elec)
    if ce == "BEV":
        return "BEV"
    if ce == "REEV":
        return "REEV"
    if ce == "PHEV":
        return "PHEV"
    if ce == "HEV":
        return "HEV"
    if ce in ("FCEV", "HICEV"):
        return "OTHERS"
    p = norm(propulsion)
    if p in ("0", "GASOLINA"):
        return "PETROL"
    if p in ("1", "DIESEL"):
        return "DIESEL"
    if p in ("2", "ELECTRICO"):   # electric propulsion w/o category → BEV-ish
        return "BEV?"
    return "OTHERS"


def aggregate(lines, loc: dict[str, tuple[int, int]]) -> dict:
    """One pass over all records collecting every distribution the probe needs."""
    agg = {
        "n_total": 0,
        "clase_mat": collections.Counter(),
        "cod_tipo": collections.Counter(),
        "cat_homologacion": collections.Counter(),
        "nuevo_usado": collections.Counter(),
        "servicio": collections.Counter(),
        "renting": collections.Counter(),
        "cat_electrico": collections.Counter(),
        "propulsion": collections.Counter(),
        # fuel split under candidate "turismos" filters:
        "fuel_m1_new": collections.Counter(),        # M1 homologation, new
        "fuel_turismo_new": collections.Counter(),   # tipo=turismo/todoterreno, new
        "fuel_m1_new_ord": collections.Counter(),    # + clase matrícula ordinaria
    }
    turismo_re = re.compile(r"^(40|TURISMO|TODO.?TERRENO)", re.IGNORECASE)

    for line in lines:
        agg["n_total"] += 1
        clase = field(line, loc["clase_mat"]) if "clase_mat" in loc else ""
        tipo = field(line, loc["cod_tipo"]) if "cod_tipo" in loc else ""
        cathom = field(line, loc["categoria_homologacion"]) if "categoria_homologacion" in loc else ""
        nu = field(line, loc["nuevo_usado"]) if "nuevo_usado" in loc else ""
        serv = field(line, loc["servicio"]) if "servicio" in loc else ""
        rent = field(line, loc["renting"]) if "renting" in loc else ""
        ce = field(line, loc["categoria_electrico"]) if "categoria_electrico" in loc else ""
        prop = field(line, loc["propulsion"]) if "propulsion" in loc else ""

        agg["clase_mat"][clase] += 1
        agg["cod_tipo"][tipo] += 1
        agg["cat_homologacion"][cathom] += 1
        agg["nuevo_usado"][nu] += 1
        agg["servicio"][serv] += 1
        agg["renting"][rent] += 1
        agg["cat_electrico"][ce] += 1
        agg["propulsion"][prop] += 1

        is_new = norm(nu) in ("N", "NUEVO")
        fuel = classify_fuel(ce, prop)
        if is_new and cathom.upper().startswith("M1"):
            agg["fuel_m1_new"][fuel] += 1
            if clase in ("0", "00") or norm(clase).startswith("ORDINARIA"):
                agg["fuel_m1_new_ord"][fuel] += 1
        if is_new and turismo_re.match(tipo or ""):
            agg["fuel_turismo_new"][fuel] += 1
    return agg


# ── ACEA comparison ────────────────────────────────────────────────────────

def spain_csv_row(period: str) -> dict | None:
    if not SPAIN_CSV.exists():
        return None
    with open(SPAIN_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["period"] == period and row.get("variant", "Whole") == "Whole":
                return row
    return None


def gallery_split(counter: collections.Counter, reev_to: str = "BEV") -> dict[str, int]:
    """Fold the probe's fuel counter into the 7-column gallery split.
    `reev_to` controls where REEV lands (ACEA counts EREVs as BEV)."""
    out = {k: 0 for k in GALLERY_FUELS}
    for fuel, n in counter.items():
        key = fuel
        if fuel == "REEV":
            key = reev_to
        elif fuel == "BEV?":
            key = "BEV"
        if key in out:
            out[key] += n
    out["TOTAL"] = sum(out[k] for k in GALLERY_FUELS if k != "TOTAL")
    return out


def compare_table(dgt: dict[str, int], acea_row: dict) -> list[str]:
    lines = ["| Fuel | DGT (probe) | ACEA (Spain.csv) | Δ abs | Δ % |",
             "|---|---|---|---|---|"]
    for f in GALLERY_FUELS:
        try:
            acea = float(acea_row.get(f) or 0)
        except ValueError:
            acea = 0.0
        d = dgt.get(f, 0)
        delta = d - acea
        pct = (delta / acea * 100) if acea else float("nan")
        lines.append(f"| {f} | {d:,} | {acea:,.0f} | {delta:+,.0f} | {pct:+.2f}% |")
    return lines


def counter_table(title: str, c: collections.Counter, top: int = 15) -> list[str]:
    lines = [f"**{title}**", "", "| value | count |", "|---|---|"]
    for val, n in c.most_common(top):
        lines.append(f"| `{val or '(empty)'}` | {n:,} |")
    rest = len(c) - top
    if rest > 0:
        lines.append(f"| … {rest} more distinct values | |")
    lines.append("")
    return lines


# ── main ───────────────────────────────────────────────────────────────────

def probe_period(session, period: str, args, report: list[str]) -> None:
    year, month = period.split("-")
    ym = f"{year}{month}"
    report.append(f"\n## Period {period}\n")

    # 1. download the monthly zip
    zip_path = Path(args.report_dir) / f"export_mensual_mat_{ym}.zip"
    urls = ([args.zip_url] if args.zip_url else
            [u.format(y=year, m=month, m_nopad=str(int(month)), ym=ym)
             for u in ZIP_URL_CANDIDATES])
    attempts: list[str] = []
    hit = try_download(session, urls, zip_path, attempts)
    report.append("### Download attempts\n")
    report.extend(attempts)
    if not hit:
        report.append("\n**✗ No candidate URL worked.** If all attempts were "
                      "403: the WAF is blocking this runner (compare with the "
                      "ACEA warmup approach). If 404: the naming pattern is "
                      "wrong or the month isn't published yet — check the "
                      "'Microdatos de Matriculaciones (mensual)' page in a "
                      "browser and pass the real URL via `--zip-url`.")
        return
    report.append(f"\n**✓ Downloaded** from `{hit}`\n")

    # 2. extract the txt
    if hit.endswith(".txt.gz"):
        import gzip
        txt_bytes = gzip.decompress(zip_path.read_bytes())
        inner_name = "(gzip)"
    else:
        with zipfile.ZipFile(zip_path) as z:
            names = z.namelist()
            report.append(f"Zip contents: {names}\n")
            txt_names = [n for n in names if n.lower().endswith(".txt")]
            if not txt_names:
                report.append("**✗ No .txt inside the zip** — inspect the "
                              "artifact manually.")
                return
            inner_name = txt_names[0]
            txt_bytes = z.read(inner_name)

    all_lines = list(iter_records(txt_bytes))
    first = txt_bytes.decode("latin-1", errors="replace").splitlines()[:2]
    lengths = collections.Counter(len(l) for l in all_lines)
    report.append(f"Extracted `{inner_name}`: {len(all_lines):,} data records; "
                  f"record lengths {dict(lengths.most_common(3))}\n")
    report.append(f"Banner line: `{first[0][:120] if first else '?'}`\n")

    sample_path = Path(args.report_dir) / f"sample_{ym}.txt"
    sample_path.write_text("\n".join(all_lines[: args.keep_sample]),
                           encoding="latin-1", errors="replace")
    report.append(f"First {args.keep_sample} records saved to `{sample_path.name}` "
                  "(artifact) for manual layout verification.\n")
    report.append("Two raw records inline (for log-only debugging):\n\n```")
    for l in all_lines[:2]:
        report.append(l)
    report.append("```\n")

    # 3. layout
    if not args.fields:
        report.append("**✗ Design PDF not parsed** — aggregation skipped for "
                      "this period. Transcribe the layout from the pdftotext "
                      "dump in the artifact, then extend the probe.")
        return
    loc = locate_fields(args.fields)
    missing = [k for k in FIELD_PATTERNS if k not in loc]
    report.append("### Field location\n")
    report.append("| logical field | slice (0-based) |")
    report.append("|---|---|")
    for k, (a, b) in sorted(loc.items()):
        report.append(f"| {k} | [{a}:{b}] |")
    if missing:
        report.append(f"\n⚠ Not located: {missing} — check the design dump; "
                      "the corresponding distributions below will be empty.\n")

    # 4. aggregate + report
    agg = aggregate(all_lines, loc)
    report.append(f"\n### Distributions ({agg['n_total']:,} records)\n")
    report.extend(counter_table("Clase matrícula", agg["clase_mat"]))
    report.extend(counter_table("Tipo vehículo", agg["cod_tipo"]))
    report.extend(counter_table("Categoría homologación (M1=cars, N1=vans, "
                                "N2/N3=HDV, M2/M3=buses, L=2-wheelers)",
                                agg["cat_homologacion"]))
    report.extend(counter_table("Nuevo/Usado", agg["nuevo_usado"]))
    report.extend(counter_table("Servicio (rental = alquiler sin conductor)",
                                agg["servicio"]))
    report.extend(counter_table("Renting", agg["renting"]))
    report.extend(counter_table("Categoría vehículo eléctrico", agg["cat_electrico"]))
    report.extend(counter_table("Propulsión", agg["propulsion"]))

    # 5. ACEA consistency check under each candidate filter
    acea_row = spain_csv_row(period)
    report.append("\n### ACEA consistency check\n")
    if acea_row is None:
        report.append(f"No `{period}` Whole row in data/Spain.csv to compare "
                      "against — distributions above still stand.")
        return
    report.append(f"Existing row source: `{acea_row.get('source')}`\n")
    for label, counter in [
        ("Filter A — homologation M1, new", agg["fuel_m1_new"]),
        ("Filter B — M1, new, clase matrícula ordinaria", agg["fuel_m1_new_ord"]),
        ("Filter C — tipo turismo/todoterreno, new", agg["fuel_turismo_new"]),
    ]:
        split = gallery_split(counter)
        reev = counter.get("REEV", 0)
        bevq = counter.get("BEV?", 0)
        report.append(f"\n**{label}**  (REEV folded into BEV: {reev:,}; "
                      f"electric-propulsion w/o category: {bevq:,})\n")
        report.extend(compare_table(split, acea_row))
    report.append(
        "\nReading guide: the filter whose TOTAL and per-fuel deltas sit "
        "consistently within ~±1–2% of ACEA across probed months is the one "
        "fetch_spain.py should adopt. Systematic offsets (e.g. HEV much "
        "higher on ACEA) usually mean a bucket-definition difference "
        "(mild hybrids), not a data problem — document, don't tune away."
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--period", action="append", required=True,
                    help="Target month as YYYY-MM (repeatable).")
    ap.add_argument("--report-dir", default="probe_report")
    ap.add_argument("--zip-url", default="",
                    help="Direct zip URL override (single-period runs).")
    ap.add_argument("--design-pdf", default="",
                    help="Path or URL of MATRICULACIONES_MATRABA.pdf override.")
    ap.add_argument("--keep-sample", type=int, default=50,
                    help="Data lines to keep in the sample artifact (default 50).")
    args = ap.parse_args()

    report_dir = Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    report: list[str] = ["# Spain / DGT microdata probe\n"]

    session = make_session()

    # Design PDF first — shared by all periods.
    design_path = report_dir / "MATRICULACIONES_MATRABA.pdf"
    if args.design_pdf and not args.design_pdf.startswith("http"):
        design_path = Path(args.design_pdf)
        design_ok = design_path.exists()
        report.append(f"Design PDF: local `{design_path}` "
                      f"({'found' if design_ok else 'MISSING'})\n")
    else:
        cands = [args.design_pdf] if args.design_pdf else DESIGN_PDF_CANDIDATES
        attempts: list[str] = []
        design_ok = try_download(session, cands, design_path, attempts) is not None
        report.append("## Design PDF download\n")
        report.extend(attempts)

    args.fields = []
    if design_ok:
        args.fields = parse_design_pdf(design_path,
                                       report_dir / "design_pdftotext.txt")
        if args.fields:
            report.append(f"\n**✓ Design parsed:** {len(args.fields)} fields. "
                          "Full list in `design_fields.txt` (artifact).\n")
            (report_dir / "design_fields.txt").write_text(
                "\n".join(f"{n}\tstart={a}\tlen={b}" for n, a, b in args.fields),
                encoding="utf-8")
        else:
            report.append("\n**⚠ Design PDF downloaded but auto-parse found "
                          "<10 field rows.** Raw text dumped to "
                          "`design_pdftotext.txt` — transcribe manually.\n")
            # Inline dump so the layout is fixable from the job log alone
            # (the Claude sandbox cannot download Actions artifacts).
            dump = (report_dir / "design_pdftotext.txt").read_text(
                encoding="utf-8", errors="replace")
            lines = [l for l in dump.splitlines() if l.strip()]
            report.append("<details><summary>pdftotext output, first 250 "
                          "non-empty lines</summary>\n\n```")
            report.extend(lines[:250])
            report.append("```\n</details>\n")
    else:
        report.append("\n**✗ Design PDF unreachable** — layout unknown, "
                      "aggregation will be skipped.\n")

    for period in args.period:
        if not re.fullmatch(r"\d{4}-\d{2}", period):
            sys.exit(f"Bad --period {period!r}, expected YYYY-MM.")
        probe_period(session, period, args, report)

    out = report_dir / "report.md"
    out.write_text("\n".join(report), encoding="utf-8")
    print("\n".join(report))
    print(f"\nReport written to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
