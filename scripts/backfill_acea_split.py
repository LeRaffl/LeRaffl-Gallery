#!/usr/bin/env python3
"""One-time backfill: ACEA's counted HEV/PETROL/DIESEL onto the national
Denmark and Finland rows, month by month from the public release PDFs
(scripts/acea_split.py, the Greece/SEAA pattern).

The national registry stays authoritative for TOTAL/BEV/PHEV; ACEA only
contributes the fuel split its release counts, because BIL53 and StatFin
121d park hybrids inside petrol/diesel. A row is merged only when ACEA's
TOTAL/BEV/PHEV match the national row within acea_split's tolerances —
a refusal leaves the national row exactly as it was. No row is ever
created here, and no month outside the national series is touched.

July 2026 has no ACEA release (summer break). Like the always-list
countries in #249, it is derived per fuel from the August year-to-date
table minus the June year-to-date table minus the August monthly table,
then merged against the national July row with the same tolerances.

Run from the repo root:
    python scripts/backfill_acea_split.py --from 2023-11 --to 2026-09 --dry-run
    python scripts/backfill_acea_split.py --from 2023-11 --to 2026-09

PDFs are cached under --cache (default: a scratch dir) so a re-run does
not re-download. Nothing is rendered here; dispatch render-country.yml
afterwards if the chart inputs changed.
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import acea_split  # noqa: E402
import fetch_acea as fa  # noqa: E402

COUNTRIES = fa.SPLIT_ONLY_COUNTRIES
JULY_2026 = "2026-07"


def month_index(period: str) -> int:
    y, m = period.split("-")[:2]
    return int(y) * 12 + int(m)


def periods(lo: str, hi: str) -> list[str]:
    a, b = month_index(lo), month_index(hi)
    return [f"{i // 12}-{i % 12 + 1:02d}" for i in range(a, b + 1)]


def _wayback_pdf(url: str, cache_path: Path) -> bool:
    """ACEA's edge 520s older releases from some IPs; the Wayback Machine
    has them. Only accept a snapshot whose bytes start with %PDF-."""
    import requests
    candidates: list[str] = []
    try:
        cdx = requests.get("http://web.archive.org/cdx/search/cdx",
                           params={"url": url, "output": "json", "limit": 30,
                                   "filter": "statuscode:200",
                                   "collapse": "timestamp:8"},
                           timeout=30)
        for row in reversed(cdx.json()[1:]):
            candidates.append(row[1])
        r = requests.get("http://archive.org/wayback/available",
                         params={"url": url}, timeout=30)
        snap = (r.json().get("archived_snapshots") or {}).get("closest") or {}
        if snap.get("available") and snap.get("timestamp"):
            candidates.append(snap["timestamp"])
    except Exception as e:
        print(f"    Wayback lookup failed: {e}")
        return False
    seen = set()
    for ts in candidates:
        if ts in seen:
            continue
        seen.add(ts)
        try:
            resp = requests.get(f"http://web.archive.org/web/{ts}if_/{url}",
                                timeout=90, headers={"User-Agent": "Mozilla/5.0 (gallery-backfill)"})
        except Exception:
            continue
        if resp.status_code == 200 and resp.content[:5] == b"%PDF-":
            cache_path.write_bytes(resp.content)
            print(f"    via Wayback snapshot {ts}")
            return True
    return False


def pdf_for(period: str, cache: Path, tries: int = 3) -> Path:
    y, m = int(period[:4]), int(period[5:7])
    name = f"{fa.ENGLISH_MONTHS[m - 1]}_{y}.pdf"
    path = cache / name
    if not path.is_file():
        url = fa.ACEA_URL_TEMPLATE.format(month_name=fa.ENGLISH_MONTHS[m - 1], year=y)
        try:
            for attempt in range(tries):
                try:
                    path.write_bytes(fa.load_pdf_bytes(url))
                    break
                except FileNotFoundError:
                    raise  # genuinely unpublished — no retry helps
                except Exception:
                    if attempt == tries - 1:
                        raise
                    time.sleep(3 * (attempt + 1))  # ACEA's edge (520/403) is moody
        except FileNotFoundError:
            raise
        except Exception:
            if not _wayback_pdf(url, path):
                raise
    return path


def _ytd_page(pdf):
    """The release's YEAR TO DATE market-grid page, or None.

    Both the YTD and MONTHLY grids share the "BY MARKET AND POWER
    SOURCE" header; the YTD one is the page whose extract_text() also
    names the heading (garbled spacing and all — pdfplumber keeps "YEAR"
    and "TO" and "DATE" as separate runs but on the same line, so the
    loose regex still matches on every release observed so far).
    """
    for page in pdf.pages:
        text = page.extract_text() or ""
        if "BY MARKET AND POWER SOURCE" in text and re.search(r"YEAR[- ]TO[- ]DATE", text):
            return page, text
    return None, None


def _country_key(s: str) -> str:
    return re.sub(r"\s+", "", s or "").casefold()


def _ytd_via_text(text: str, countries: list[str]) -> dict:
    """Clean text layer: "Denmark 60,845 40,797 …" as one line (most
    2024-2026 releases — the YTD page is unaffected by the MONTHLY page's
    pre-April-2026 broken-spacing quirk on most, not all, releases)."""
    out: dict[str, dict[str, tuple[int, int]]] = {}
    m = re.search(r"YEAR[- ]TO[- ]DATE", text)
    seg = text[m.end():]
    m2 = re.search(r"\bMONTHLY\b", seg)
    if m2:
        seg = seg[:m2.start()]
    for line in seg.split("\n"):
        line = line.strip()
        for c in countries:
            if line.startswith(c + " "):
                pairs = fa._parse_country_pairs(line[len(c):])
                if pairs is not None:
                    out[c] = dict(zip(fa.PDF_FUEL_ORDER, pairs))
                break
    return out


def _ytd_via_tables(page, countries: list[str]) -> dict:
    """Legacy table-cell parser — the YTD counterpart of fetch_acea.py's
    _parse_via_tables, which explicitly skips the YTD table (it only wants
    MONTHLY) because country names and fuel values are newline-joined in
    one cell per column (default extract_tables() cell-rule detection)."""
    wanted = set(countries)
    out: dict[str, dict[str, tuple[int, int]]] = {}
    for cand in (page.extract_tables() or []):
        if not cand or len(cand) < 3:
            continue
        header_norm = [fa._normalise_header(c) for c in cand[0]]
        if "BATTERYELECTRIC" not in header_norm or "TOTAL" not in header_norm:
            continue
        fuel_col: dict[str, int] = {}
        for ci, cell in enumerate(cand[0]):
            key = fa.HEADER_TO_FUEL.get(fa._normalise_header(cell))
            if key and key not in fuel_col:
                fuel_col[key] = ci
        if set(fa.HEADER_TO_FUEL.values()) - set(fuel_col.keys()):
            continue
        for row in cand[1:]:
            names = [n.strip() for n in (row[0] or "").split("\n") if n.strip()]
            if not names:
                continue
            fuel_lines = {fuel: (row[ci] or "").split("\n") for fuel, ci in fuel_col.items()}
            for i, country in enumerate(names):
                if country not in wanted:
                    continue
                parsed: dict[str, tuple[int, int]] = {}
                ok = True
                for fuel in fa.HEADER_TO_FUEL.values():
                    lines = fuel_lines[fuel]
                    cell = fa._parse_cell(lines[i]) if i < len(lines) else None
                    if cell is None:
                        ok = False
                        break
                    parsed[fuel] = cell
                if ok:
                    out[country] = parsed
    return out


def _ytd_via_position(page, countries: list[str]) -> dict:
    """Positional parser for the hardest layout: each row is one clean
    table but every text run carries stray spaces ("A ustria", "B A T T E
    R Y E L E C T R IC"), so no header or name can be matched by string
    equality. The column *order* is still fixed — country name, a blank
    spacer column, then 7 fuels in fa.PDF_FUEL_ORDER at 3 columns each
    (current year, prior year, % change) — so this reads by position:
    column 2+3*i is the current-year count for fuel i, 3+3*i the prior
    year's. Matched against `countries` by comparing with all whitespace
    stripped, case-folded.
    """
    wanted = {_country_key(c): c for c in countries}
    out: dict[str, dict[str, tuple[int, int]]] = {}
    for strategy in (("text", "text"), ("lines", "text"), ("text", "lines")):
        try:
            tables = page.extract_tables(
                {"vertical_strategy": strategy[0], "horizontal_strategy": strategy[1]})
        except Exception:
            continue
        for cand in tables:
            if not cand or len(cand[0]) < 2 + 3 * len(fa.PDF_FUEL_ORDER):
                continue
            for row in cand:
                if not row or not row[0]:
                    continue
                key = _country_key(row[0])
                country = wanted.get(key)
                if not country or country in out:
                    continue
                parsed: dict[str, tuple[int, int]] = {}
                ok = True
                for i, fuel in enumerate(fa.PDF_FUEL_ORDER):
                    cur_cell, pri_cell = row[2 + 3 * i], row[3 + 3 * i]

                    def num(cell):
                        s = re.sub(r"[^0-9,]", "", (cell or "").replace(" ", ""))
                        return int(s.replace(",", "")) if s else None

                    cur, pri = num(cur_cell), num(pri_cell)
                    if cur is None or pri is None:
                        ok = False
                        break
                    parsed[fuel] = (cur, pri)
                if ok:
                    out[country] = parsed
        if out:
            return out
    return out


def parse_ytd_markets_full(pdf_path: Path, countries: list[str]) -> dict:
    """{country: {fuel: (this-year YTD units, prior-year YTD units)}}.

    Every ACEA release's YEAR TO DATE table carries both columns side by
    side (the same release that shows "Jan-Sep 2024" also shows "Jan-Sep
    2023"), so one release gives both years at once — this is what makes
    deriving a month from two releases' YTD tables possible even when the
    release's own MONTHLY grid cannot be parsed. Three layouts are tried
    in order of how much they trust the text layer (clean text, explicit
    table-cell rules with newline-joined values, positional columns on a
    run-fragmented table), because which one a given release needs is
    independent of the MONTHLY page's own layout (October 2024: MONTHLY
    is broken text, YTD needs the positional parser; September 2024 is
    the opposite — clean YTD text, broken MONTHLY).
    """
    import pdfplumber
    with pdfplumber.open(str(pdf_path)) as pdf:
        page, text = _ytd_page(pdf)
        if page is None:
            return {}
        got = _ytd_via_text(text, countries)
        if got:
            return got
        got = _ytd_via_tables(page, countries)
        if got:
            return got
        return _ytd_via_position(page, countries)


def parse_ytd_markets(pdf_path: Path, countries: list[str]) -> dict:
    """{country: {fuel: current-year YTD units}} — this-year column only,
    for the July 2026 derivation (no equivalent prior-year release needed
    there, see july_2026())."""
    full = parse_ytd_markets_full(pdf_path, countries)
    return {c: {f: v[0] for f, v in fuels.items()} for c, fuels in full.items()}


def _ytd_subtract(hi: dict, lo: dict) -> dict[str, dict[str, tuple[int, int]]] | None:
    """hi's YTD minus lo's YTD, per country per fuel, both columns. None on
    a negative result (a mismatched pair) rather than a wrong month."""
    out: dict[str, dict[str, tuple[int, int]]] = {}
    for c in COUNTRIES:
        if c not in hi or c not in lo:
            continue
        fuels: dict[str, tuple[int, int]] = {}
        ok = True
        for f in fa.PDF_FUEL_ORDER:
            if f not in hi[c] or f not in lo[c]:
                ok = False
                break
            cur = hi[c][f][0] - lo[c][f][0]
            pri = hi[c][f][1] - lo[c][f][1]
            if cur < 0 or pri < 0:
                ok = False
                break
            fuels[f] = (cur, pri)
        if ok:
            out[c] = fuels
    return out or None


def ytd_diff_month(period: str, cache: Path) -> dict[str, dict[str, tuple[int, int]]] | None:
    """A month's (this-year, prior-year) units per country per fuel, from
    two releases' YTD tables: this period's own two columns (cur year,
    prior year) minus the same two columns one release earlier — or, when
    the earlier release can't be fetched (ACEA's edge serves only some
    IPs some releases, and not every month has a Wayback copy), the next
    release's columns minus this one's, the same subtraction the other
    way round.

    January needs no neighbour (YTD(Jan) *is* January).

    The fallback this backs: scripts/fetch_acea.py's direct monthly-table
    parser needs the post-April-2026 Word layout; every release before
    that renders the monthly country grid with broken spacing (e.g.
    "D enm ark") this derivation does not depend on — the YTD page's text
    layer is unaffected.
    """
    y, m = int(period[:4]), int(period[5:7])
    this = parse_ytd_markets_full(pdf_for(period, cache), COUNTRIES)
    if m == 1:
        return this or None

    def neighbour(dy: int, dm: int) -> dict | None:
        ny, nm = y + dy, m + dm
        if nm == 0:
            ny, nm = ny - 1, 12
        elif nm == 13:
            ny, nm = ny + 1, 1
        n_period = f"{ny}-{nm:02d}"
        try:
            return parse_ytd_markets_full(pdf_for(n_period, cache), COUNTRIES)
        except Exception as e:
            print(f"    {period}: neighbour {n_period} unavailable ({e})")
            return None

    # Only the BACKWARD difference is this month: YTD(M) - YTD(M-1) = M.
    # The forward difference YTD(M+1) - YTD(M) is month M+1, NOT M — using
    # it here would silently write next month's counts into this month's
    # row (caught 2026-11-19: Denmark 2024-02 came out +49.7% on TOTAL).
    # So if the previous release is unavailable, this month is not
    # derivable; the caller marks it and moves on.
    prev = neighbour(0, -1)
    if prev is not None:
        return _ytd_subtract(this, prev)
    return None


def july_2026(cache: Path) -> dict[str, dict[str, tuple[int, int]]]:
    jun = parse_ytd_markets(pdf_for("2026-06", cache), COUNTRIES)
    aug_pdf = pdf_for("2026-08", cache)
    aug_ytd = parse_ytd_markets(aug_pdf, COUNTRIES)
    aug_month, _ = fa.parse_monthly_table(str(aug_pdf), countries=COUNTRIES)
    out = {}
    for c in COUNTRIES:
        if c not in jun or c not in aug_ytd or c not in aug_month:
            print(f"  {JULY_2026} {c}: cannot derive (missing YTD or monthly grid)")
            continue
        fuels = {}
        for f in fa.PDF_FUEL_ORDER:
            v = aug_ytd[c][f] - jun[c][f] - aug_month[c][f][0]
            if v < 0:
                print(f"  {JULY_2026} {c}: negative {f} ({v}) — not derived")
                fuels = {}
                break
            fuels[f] = (v, v)
        if fuels:
            out[c] = fuels
    return out


def merge_month(data_dir: Path, country: str, period: str,
                parsed: dict[str, tuple[int, int]], note_suffix: str = "") -> str:
    path = data_dir / f"{country}.csv"
    fields, rows = fa.load_csv(path)
    by_period = {r["period"]: r for r in rows}
    existing = by_period.get(period)
    if existing is None or existing.get("variant") not in ("", "Whole") \
            or existing.get("time_interval") != "monthly":
        return "no-national-row"
    src = (existing.get("source") or "").strip()
    if src not in (acea_split.NATIONAL_SOURCE[country],
                   acea_split.MERGED_SOURCE[country]):
        return f"foreign-source ({src})"
    order = [r["period"] for r in rows]
    changed = fa.merge_split(country, period, "backfill", existing, parsed,
                             False, by_period)
    if not changed:
        return "unchanged-or-refused"
    if note_suffix:
        by_period[period]["notes"] += note_suffix
    fa.write_csv(path, fields, list(by_period.values()), original_order=order)
    return "merged"


def reference_shas() -> dict[str, str]:
    """pdf_sha256 per release month from reference/acea_eu_shares.csv —
    the bytes CI fetched. A Wayback copy must match them exactly."""
    import csv
    path = Path(__file__).resolve().parent.parent / "reference" / "acea_eu_shares.csv"
    out: dict[str, str] = {}
    if path.is_file():
        for r in csv.DictReader(path.open(encoding="utf-8")):
            if r.get("pdf_sha256") and r.get("period_to"):
                out[r["period_to"]] = r["pdf_sha256"]
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--from", dest="lo", default="2023-11")
    ap.add_argument("--to", dest="hi", default="2026-09")
    ap.add_argument("--data-dir", default="data")
    ap.add_argument("--cache", default="/Users/leraffl/.hermes/cache/scratch/acea-pdf-cache")
    ap.add_argument("--dry-run", action="store_true",
                    help="parse and check tolerances, write nothing")
    args = ap.parse_args()
    cache = Path(args.cache)
    cache.mkdir(parents=True, exist_ok=True)
    data_dir = Path(args.data_dir)

    stats = {c: {} for c in COUNTRIES}
    shas = reference_shas()
    for period in periods(args.lo, args.hi):
        if period == JULY_2026:
            try:
                derived = july_2026(cache)
            except Exception as e:
                print(f"  {JULY_2026}: derivation failed ({e})")
                derived = {}
            for c in COUNTRIES:
                if c not in derived:
                    stats[c][period] = "no-release-not-derived"
                    continue
                if args.dry_run:
                    stats[c][period] = "would-merge (derived)"
                    continue
                stats[c][period] = merge_month(
                    data_dir, c, period, derived[c],
                    "; July derived from Aug YTD minus Jun YTD minus Aug monthly "
                    "(ACEA has no July release)")
            continue
        try:
            pdf = pdf_for(period, cache)
        except Exception as e:
            print(f"  {period}: PDF unavailable ({e})")
            for c in COUNTRIES:
                stats[c][period] = "no-pdf"
            continue
        time.sleep(2)  # be polite to ACEA's edge; 35 releases in a row
        sha = shas.get(period)
        if sha:
            import hashlib
            got = hashlib.sha256(pdf.read_bytes()).hexdigest()
            if got != sha:
                print(f"  {period}: sha256 differs from reference/acea_eu_shares.csv — skipped")
                for c in COUNTRIES:
                    stats[c][period] = "sha-mismatch"
                continue
        source_tag = ""
        try:
            parsed_all, label = fa.parse_monthly_table(str(pdf), countries=COUNTRIES)
            if label and label != f"{fa.ENGLISH_MONTHS[int(period[5:7]) - 1]} {period[:4]}":
                print(f"  {period}: PDF reports {label!r} — skipped")
                for c in COUNTRIES:
                    stats[c][period] = "label-mismatch"
                continue
        except Exception as e:
            # Pre-April-2026 releases render the monthly country grid with
            # broken spacing (fetch_acea.py's _parse_via_text/_parse_via_tables
            # both miss it); fall back to the YTD-diff derivation, which reads
            # the unaffected YTD page instead (ytd_diff_month).
            print(f"  {period}: monthly parse failed ({e}) — trying YTD diff")
            try:
                parsed_all = ytd_diff_month(period, cache) or {}
            except Exception as e2:
                print(f"  {period}: YTD diff also failed ({e2})")
                parsed_all = {}
            if not parsed_all:
                for c in COUNTRIES:
                    stats[c][period] = "parse-failed"
                continue
            source_tag = " (derived: ACEA YTD minus the prior month's YTD)"
        for c in COUNTRIES:
            if c not in parsed_all:
                stats[c][period] = "not-in-grid"
                continue
            if args.dry_run:
                import csv as _csv
                rows = list(_csv.DictReader(open(data_dir / f"{c}.csv", encoding="utf-8")))
                nat = next((r for r in rows if r["period"] == period
                            and r.get("variant") in ("", "Whole")
                            and r.get("time_interval") == "monthly"), None)
                if nat is None:
                    stats[c][period] = "no-national-row"
                    continue
                acea = {f: float(v[0]) for f, v in parsed_all[c].items()}
                m = acea_split.merge(nat, acea, country=c)
                stats[c][period] = ("would-merge (derived)" if source_tag and m
                                    else "would-merge" if m else "would-refuse")
                continue
            stats[c][period] = merge_month(data_dir, c, period, parsed_all[c], source_tag)

    print("\n=== report ===")
    for c in COUNTRIES:
        counts: dict[str, int] = {}
        for s in stats[c].values():
            counts[s] = counts.get(s, 0) + 1
        print(f"{c}: {counts}")
        bad = {p: s for p, s in stats[c].items()
               if s not in ("merged", "unchanged-or-refused", "would-merge", "would-merge (derived)")}
        if bad:
            print(f"  attention: {bad}")
    return 0


if __name__ == "__main__":
    sys.exit(main())