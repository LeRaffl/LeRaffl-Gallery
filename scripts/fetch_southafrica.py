#!/usr/bin/env python3
"""
Fetch South Africa new-vehicle sales from naamsa (the Automotive Business
Council) and upsert data/South Africa.csv.

Usage
-----
    python scripts/fetch_southafrica.py [--dry-run] [--force] [--probe]
                                        [--qbr-url URL] [--industry-url URL]

Source
------
naamsa's public Quarterly Review of Business Conditions (PDF) plus the
companion "Industry Vehicle Sales, Production, Export and Import Data"
workbook-as-PDF, both listed on https://naamsa.net/quarterly-reviews/.

The NEV drivetrain table in each QBR carries yearly BEV / PHEV / HEV
counts (2020–present) and two quarter columns (this quarter + the same
quarter last year). Quarterly industry TOTAL is passenger-car sales +
commercial-vehicle sales from the same QBR's "Business Conditions"
prose. Yearly TOTAL is the "TOTAL AGGREGATE MARKET" row of the Industry
Vehicle Sales PDF (actual years only — the last two columns are
projections).

Cadence
-------
Quarterly, Canada-style: each quarter is stored under its middle month
(Q1→YYYY-02, Q2→YYYY-05, Q3→YYYY-08, Q4→YYYY-11). Yearly history
2020–2023 sits at mid-year (YYYY-06) and stops where the quarterly
series begins, so TTM never mixes annual and quarterly volumes.

Scope
-----
Whole = naamsa's **all-vehicle** domestic market (passenger + LCV +
MCV/HCV + buses), not EU M1. The NEV table is not split by body type;
mixing a passenger-only TOTAL with all-vehicle NEV would repeat the
Mexico two-universes mistake. ICE = TOTAL − BEV − PHEV − HEV (USA
convention — no petrol/diesel split). Manufacturer-reported: some
importers (Geely, Dongfeng, …) do not report; 2026 NEV volumes include
new reporters joining naamsa/Lightstone.

See docs/architecture/38-source-south-africa.md.
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import subprocess
import tempfile
import urllib.error
import urllib.request
from datetime import date
from html.parser import HTMLParser
from pathlib import Path

UA = (
    "Mozilla/5.0 (compatible; LeRaffl-Gallery/1.0; "
    "+https://leraffl.github.io/LeRaffl-Gallery/)"
)
LISTING = "https://naamsa.net/quarterly-reviews/"
CSV_PATH = "data/South Africa.csv"
VARIANT = "Whole"
SOURCE = "naamsa.net"
CSV_COLUMNS = [
    "period", "time_interval", "variant", "source",
    "BEV", "PHEV", "HEV", "ICE", "TOTAL", "notes",
]
VALUE_COLUMNS = ["BEV", "PHEV", "HEV", "ICE", "TOTAL"]

Q_MONTH = {1: 2, 2: 5, 3: 8, 4: 11}
ORDINAL = {
    "first": 1, "1st": 1,
    "second": 2, "2nd": 2,
    "third": 3, "3rd": 3,
    "fourth": 4, "4th": 4,
}
ROW_LABELS = (
    ("plug-in hybrid", "PHEV"),
    ("plug in hybrid", "PHEV"),
    ("traditional hybrid", "HEV"),
    ("electric", "BEV"),
    ("total nevs", "NEV_TOTAL"),
)

YEARLY_NOTE = (
    "annual figure at mid-year; naamsa all-vehicle market (not M1-only)"
)
QUARTERLY_NOTE = (
    "naamsa all-vehicle market (passenger + commercial); not M1-only"
)
NOTE_2026 = (
    "2026 NEV coverage expanded as new reporters joined naamsa/Lightstone; "
    "all-vehicle market (not M1-only)"
)


# --------------------------------------------------------------------------- #
# HTTP / PDF text
# --------------------------------------------------------------------------- #
def http_get(url: str, timeout: int = 90) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def pdftotext(data: bytes) -> str:
    """Layout-preserving text via poppler. Raises if pdftotext is missing."""
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(data)
        tmp_path = tmp.name
    try:
        r = subprocess.run(
            ["pdftotext", "-layout", tmp_path, "-"],
            check=True, capture_output=True,
        )
    except FileNotFoundError as exc:
        raise SystemExit(
            "pdftotext (poppler-utils) is required"
        ) from exc
    finally:
        os.unlink(tmp_path)
    return r.stdout.decode("utf-8", "replace")


def normalise_pdf_text(text: str) -> str:
    """Undo common ligature / substitution artefacts from naamsa PDFs."""
    text = (text.replace("ﬁ", "fi").replace("ﬂ", "fl").replace("ﬀ", "ff")
                .replace("ﬃ", "ffi").replace("ﬄ", "ffl")
                .replace("\u00a0", " "))
    text = re.sub(r";rst", "first", text, flags=re.I)
    text = re.sub(r"\bNrst\b", "first", text)
    return text


def parse_int(token: str) -> int:
    return int(re.sub(r"[^\d]", "", token))


# --------------------------------------------------------------------------- #
# Discovery
# --------------------------------------------------------------------------- #
class _HrefParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag != "a":
            return
        for k, v in attrs:
            if k == "href" and v:
                self.hrefs.append(v)


def _abs(url: str) -> str:
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("/"):
        return "https://naamsa.net" + url
    return url


def classify_pdf(url: str) -> str | None:
    """Return 'qbr', 'industry', or None."""
    u = url.lower()
    if not u.endswith(".pdf"):
        return None
    if "industry-vehicle-sales" in u or "actual-and-projections" in u:
        return "industry"
    if "confidence-index" in u or "accelerator" in u:
        return None
    if "media-release" in u or "flash" in u:
        return None
    if re.search(r"quarter|q[1-4]|business-review|review-of-business", u):
        return "qbr"
    return None


def discover_pdfs(html: str) -> tuple[list[str], list[str]]:
    """(qbr_urls newest-first, industry_urls newest-first)."""
    p = _HrefParser()
    p.feed(html)
    qbr, industry = [], []
    seen = set()
    for href in p.hrefs:
        url = _abs(href.split("?")[0])
        if url in seen:
            continue
        kind = classify_pdf(url)
        if kind == "qbr":
            qbr.append(url)
            seen.add(url)
        elif kind == "industry":
            industry.append(url)
            seen.add(url)
    return qbr, industry


def qbr_sort_key(url: str) -> tuple:
    """Newest first from the /YYYY/MM/ upload path, else filename date."""
    m = re.search(r"/uploads/(\d{4})/(\d{2})/", url)
    if m:
        return (int(m.group(1)), int(m.group(2)), url)
    m = re.search(r"(20\d{2})(\d{2})(\d{2})", Path(url).name)
    if m:
        return (int(m.group(1)), int(m.group(2)), url)
    return (0, 0, url)


# --------------------------------------------------------------------------- #
# NEV drivetrain table
# --------------------------------------------------------------------------- #
def _row_label(line: str) -> str | None:
    stripped = re.sub(r"^[\s•§\-–*]+", "", line.strip().lower())
    stripped = re.sub(r"\s+", " ", stripped)
    for needle, col in ROW_LABELS:
        if stripped.startswith(needle):
            return col
    return None


def parse_nev_table(text: str) -> dict[str, dict]:
    """period -> {BEV,PHEV,HEV,NEV_TOTAL,time_interval,q?} from one QBR."""
    text = normalise_pdf_text(text)
    idx = text.lower().find("diversity of drivetrain")
    if idx < 0:
        idx = text.lower().find("south african nev landscape")
    if idx < 0:
        return {}
    block = text[idx:idx + 2800]
    # Stop at the Total-NEVs row so later prose ("SAAM 2035", White Paper, …)
    # cannot leak extra 20xx tokens into the year list.
    cut = re.search(r"(?im)^[^\n]*total nevs[^\n]*", block)
    if cut:
        block = block[:cut.end()]
    lines = block.splitlines()
    this_year = date.today().year

    def _sane_year(y: int) -> bool:
        return 2016 <= y <= this_year + 1


    years: list[int] = []
    quarters: list[tuple[int, int]] = []  # (year, q)
    for ln in lines[:16]:
        qs = [(int(y), int(q)) for q, y in
              re.findall(r"Q([1-4])\s*:\s*(20\d{2})", ln, re.I)
              if _sane_year(int(y))]
        if qs:
            quarters.extend(qs)
            continue
        ys = [int(y) for y in re.findall(r"20\d{2}", ln) if _sane_year(int(y))]
        if ys and not re.search(r"year", ln, re.I):
            years = ys

    rows: dict[str, list[int]] = {}
    for ln in lines:
        label = _row_label(ln)
        if not label:
            continue
        values = [parse_int(x) for x in
                  re.findall(r"\d{1,3}(?:,\d{3})+|\d+", ln)]
        if not values:
            continue
        expected = len(years) + len(quarters)
        if expected and len(values) != expected:
            if len(values) > expected:
                values = values[-expected:]
            else:
                continue
        rows[label] = values

    if "BEV" not in rows or "PHEV" not in rows or "HEV" not in rows:
        return {}
    n = len(rows["BEV"])
    if not years and quarters:
        # couldn't read the year line; treat every column as a quarter? no.
        return {}
    if years and quarters and n != len(years) + len(quarters):
        # realign years to the leftover columns
        n_y = n - len(quarters)
        if n_y <= 0:
            return {}
        years = years[-n_y:] if len(years) >= n_y else years

    out: dict[str, dict] = {}
    n_y = len(years)

    def rec_at(i: int) -> dict:
        rec = {
            "BEV": rows["BEV"][i],
            "PHEV": rows["PHEV"][i],
            "HEV": rows["HEV"][i],
        }
        if "NEV_TOTAL" in rows:
            rec["NEV_TOTAL"] = rows["NEV_TOTAL"][i]
        return rec

    for i, year in enumerate(years):
        rec = rec_at(i)
        rec["time_interval"] = "yearly"
        out[f"{year}-06"] = rec
    for j, (year, q) in enumerate(quarters):
        rec = rec_at(n_y + j)
        rec["time_interval"] = "quarterly"
        rec["q"] = q
        out[f"{year}-{Q_MONTH[q]:02d}"] = rec
    return out


def checksum_ok(rec: dict, tol: int = 2) -> bool:
    got = rec["BEV"] + rec["PHEV"] + rec["HEV"]
    if "NEV_TOTAL" not in rec:
        return True
    return abs(got - rec["NEV_TOTAL"]) <= tol


def repair_swapped_quarter_hybrids(nev: dict[str, dict]) -> None:
    """naamsa's Q4-2025 table (and possibly others) prints the PHEV and HEV
    *quarter* columns swapped — yearly columns on the same rows stay correct.
    Detect: quarterly PHEV exceeds that year's yearly PHEV, while HEV is below
    the yearly HEV. Swap is checksum-preserving.
    """
    yearly = {int(p[:4]): r for p, r in nev.items()
              if r.get("time_interval") == "yearly"}
    for period, rec in nev.items():
        if rec.get("time_interval") != "quarterly":
            continue
        yr = yearly.get(int(period[:4]))
        if not yr:
            continue
        if rec["PHEV"] > yr["PHEV"] and rec["HEV"] < yr["HEV"]:
            rec["PHEV"], rec["HEV"] = rec["HEV"], rec["PHEV"]
            print(f"  repaired {period}: swapped PHEV/HEV "
                  f"(quarter PHEV {rec['HEV']} > yearly {yr['PHEV']})")



# --------------------------------------------------------------------------- #
# Quarterly TOTAL (passenger + commercial prose)
# --------------------------------------------------------------------------- #
PASSENGER_RE = re.compile(
    r"(20\d{2})\s+(First|Second|Third|Fourth|1st|2nd|3rd|4th)\s+quarter\s+"
    r"aggregate industry new passenger car sales at\s+([\d, ]+)\s+units",
    re.I,
)
COMMERCIAL_RE = re.compile(
    r"commercial vehicle sales during the\s+"
    r"(?:First|Second|Third|Fourth|1st|2nd|3rd|4th)\s+quarter"
    r"(?:\s+of\s+20\d{2})?,?\s+at\s+([\d, ]+)\s+units",
    re.I,
)


def parse_quarter_total(text: str) -> tuple[str, int] | None:
    """Return (period, TOTAL) for the QBR's own quarter, or None."""
    text = normalise_pdf_text(text)
    pm = PASSENGER_RE.search(text)
    cm = COMMERCIAL_RE.search(text)
    if not pm or not cm:
        return None
    year = int(pm.group(1))
    q = ORDINAL[pm.group(2).lower()]
    passenger = parse_int(pm.group(3))
    commercial = parse_int(cm.group(1))
    total = passenger + commercial
    period = f"{year}-{Q_MONTH[q]:02d}"
    return period, total


# --------------------------------------------------------------------------- #
# Industry Vehicle Sales — yearly TOTAL AGGREGATE MARKET
# --------------------------------------------------------------------------- #
def parse_industry_totals(text: str) -> dict[int, int]:
    """year -> aggregate domestic market (actual years, not projections)."""
    text = normalise_pdf_text(text)
    years: list[int] = []
    for ln in text.splitlines()[:12]:
        ys = [int(y) for y in re.findall(r"20\d{2}", ln)]
        if len(ys) >= 8:
            years = ys
            break
    market_line = None
    for ln in text.splitlines():
        if re.search(r"TOTAL\s+AGGREGATE\s+MARKET", ln, re.I):
            market_line = ln
            break
    if not years or not market_line:
        return {}
    # Tokens split on 2+ spaces; drop the label.
    parts = re.split(r"\s{2,}", market_line.strip())
    nums = []
    for p in parts[1:]:
        p = p.replace(" ", "").replace(",", "")
        if re.fullmatch(r"\d+", p):
            nums.append(int(p))
    if len(nums) != len(years):
        # fall back to "numbers with optional interior spaces"
        raw = re.findall(r"\d[\d ]*\d|\d+", market_line.split("MARKET", 1)[-1])
        nums = [int(x.replace(" ", "")) for x in raw]
    if len(nums) != len(years):
        return {}
    this_year = date.today().year
    out = {}
    for y, n in zip(years, nums):
        if y >= this_year:
            continue  # current year is incomplete; later years are forecasts
        out[y] = n
    return out


# --------------------------------------------------------------------------- #
# Merge + CSV
# --------------------------------------------------------------------------- #
MIN_YEARLY_YEAR = 2020
MIN_QUARTERLY_PERIOD = "2024-02"  # 2023 Q4 NEV split is not in the QBR table


def build_rows(
    nev_by_period: dict[str, dict],
    quarter_totals: dict[str, int],
    yearly_totals: dict[int, int],
) -> dict[str, dict]:
    """Build gallery rows. Yearly stops where quarterly begins."""
    quarterly_periods = sorted(
        p for p, r in nev_by_period.items()
        if r.get("time_interval") == "quarterly"
        and p in quarter_totals
        and p >= MIN_QUARTERLY_PERIOD
    )
    first_q = quarterly_periods[0] if quarterly_periods else None
    first_q_year = int(first_q[:4]) if first_q else 9999

    rows: dict[str, dict] = {}
    for period, rec in nev_by_period.items():
        if not checksum_ok(rec):
            print(f"  skip {period}: NEV checksum "
                  f"{rec['BEV']}+{rec['PHEV']}+{rec['HEV']}"
                  f" != {rec.get('NEV_TOTAL')}")
            continue
        ti = rec["time_interval"]
        if ti == "yearly":
            year = int(period[:4])
            if year < MIN_YEARLY_YEAR or year >= first_q_year:
                continue
            if year not in yearly_totals:
                continue
            total = yearly_totals[year]
            note = YEARLY_NOTE
        elif ti == "quarterly":
            if period < MIN_QUARTERLY_PERIOD or period not in quarter_totals:
                continue
            total = quarter_totals[period]
            year = int(period[:4])
            note = NOTE_2026 if year >= 2026 else QUARTERLY_NOTE
        else:
            continue
        bev, phev, hev = rec["BEV"], rec["PHEV"], rec["HEV"]
        ice = total - bev - phev - hev
        if ice < 0:
            print(f"  skip {period}: ICE={ice} (TOTAL {total} < NEV)")
            continue
        rows[period] = {
            "period": period,
            "time_interval": ti,
            "variant": VARIANT,
            "source": SOURCE,
            "BEV": bev,
            "PHEV": phev,
            "HEV": hev,
            "ICE": ice,
            "TOTAL": total,
            "notes": note,
        }
    return rows


def upsert_csv(csv_path: str, new_rows: dict) -> tuple[int, int]:
    existing: dict = {}
    if os.path.exists(csv_path):
        with open(csv_path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                existing[(row["period"], row["variant"])] = row

    added = updated = 0
    for period, new_row in sorted(new_rows.items()):
        key = (period, new_row["variant"])
        if key not in existing:
            existing[key] = new_row
            added += 1
            print(f"  + {period}")
        else:
            old = existing[key]
            for col in VALUE_COLUMNS:
                try:
                    old_val = float(old.get(col) or 0)
                    new_val = float(new_row[col] or 0)
                except ValueError:
                    continue
                if old_val > 100 and abs(new_val - old_val) / old_val > 0.5:
                    print(f"  WARNING {period} {col}: existing={old_val:.0f}, "
                          f"new={new_val:.0f} — diff >50%")
            if not new_row.get("notes"):
                new_row["notes"] = old.get("notes", "")
            existing[key] = {**old, **new_row}
            updated += 1

    Path(csv_path).parent.mkdir(parents=True, exist_ok=True)
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, lineterminator="\n")
        writer.writeheader()
        for key in sorted(existing.keys(), key=lambda k: (k[1], k[0])):
            writer.writerow({c: existing[key].get(c, "") for c in CSV_COLUMNS})
    return added, updated


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def fetch_and_parse(
    qbr_urls: list[str],
    industry_url: str | None,
    max_qbr: int = 16,
) -> tuple[dict, dict, dict]:
    nev_merged: dict[str, dict] = {}
    quarter_totals: dict[str, int] = {}

    # Newest QBR first so its yearly NEV figures (revisions) win.
    ordered = sorted(qbr_urls, key=qbr_sort_key, reverse=True)[:max_qbr]
    for url in ordered:
        print(f"[qbr] {url}")
        try:
            text = normalise_pdf_text(pdftotext(http_get(url)))
        except (urllib.error.URLError, urllib.error.HTTPError, subprocess.CalledProcessError) as e:
            print(f"  FAILED: {e}")
            continue
        table = parse_nev_table(text)
        if not table:
            print("  no NEV table")
        else:
            print(f"  NEV periods: {', '.join(sorted(table))}")
            # newest PDF wins on overlap
            for period, rec in table.items():
                if period not in nev_merged:
                    nev_merged[period] = rec
        qt = parse_quarter_total(text)
        if qt:
            period, total = qt
            if period not in quarter_totals:
                quarter_totals[period] = total
                print(f"  quarter TOTAL {period} = {total}")
        else:
            print("  no passenger+commercial total")

    yearly_totals: dict[int, int] = {}
    if industry_url:
        print(f"[industry] {industry_url}")
        try:
            yearly_totals = parse_industry_totals(
                pdftotext(http_get(industry_url))
            )
            print(f"  yearly TOTALs: {yearly_totals}")
        except (urllib.error.URLError, urllib.error.HTTPError, subprocess.CalledProcessError) as e:
            print(f"  FAILED: {e}")
    repair_swapped_quarter_hybrids(nev_merged)
    return nev_merged, quarter_totals, yearly_totals


def probe() -> None:
    print("=== PROBE: naamsa quarterly-reviews listing ===", flush=True)
    html = http_get(LISTING).decode("utf-8", "replace")
    qbr, industry = discover_pdfs(html)
    qbr = sorted(qbr, key=qbr_sort_key, reverse=True)
    industry = sorted(industry, key=qbr_sort_key, reverse=True)
    print(f"QBR PDFs ({len(qbr)}):")
    for u in qbr[:12]:
        print(f"  {u}")
    print(f"Industry Vehicle Sales PDFs ({len(industry)}):")
    for u in industry[:4]:
        print(f"  {u}")
    if not qbr:
        return
    print("\n=== parse newest QBR ===")
    text = normalise_pdf_text(pdftotext(http_get(qbr[0])))
    table = parse_nev_table(text)
    for period in sorted(table):
        r = table[period]
        print(f"  {period} {r['time_interval']:10} "
              f"BEV={r['BEV']} PHEV={r['PHEV']} HEV={r['HEV']} "
              f"NEV={r.get('NEV_TOTAL', '?')}")
    print("quarter total:", parse_quarter_total(text))
    if industry:
        print("\n=== parse newest Industry Vehicle Sales ===")
        print(parse_industry_totals(pdftotext(http_get(industry[0]))))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true",
                    help="Accepted for parity; this fetcher always re-parses.")
    ap.add_argument("--qbr-url", default="",
                    help="Parse only this QBR PDF (skip discovery).")
    ap.add_argument("--industry-url", default="",
                    help="Industry Vehicle Sales PDF URL (skip discovery).")
    args = ap.parse_args()

    if args.probe:
        probe()
        return

    if args.qbr_url:
        qbr_urls = [args.qbr_url]
        industry_url = args.industry_url or None
    else:
        print(f"[list] {LISTING}")
        html = http_get(LISTING).decode("utf-8", "replace")
        qbr_urls, industry_urls = discover_pdfs(html)
        industry_url = args.industry_url or (
            sorted(industry_urls, key=qbr_sort_key, reverse=True)[0]
            if industry_urls else None
        )
        if not qbr_urls:
            raise SystemExit("no QBR PDFs found on " + LISTING)

    nev, qtot, ytot = fetch_and_parse(qbr_urls, industry_url)
    rows = build_rows(nev, qtot, ytot)
    if not rows:
        raise SystemExit("parsed nothing that could become a CSV row")
    print(f"built {len(rows)} rows ({min(rows)} .. {max(rows)})")
    for period in sorted(rows):
        r = rows[period]
        print(f"  {period} {r['time_interval']:10} "
              f"BEV={r['BEV']} PHEV={r['PHEV']} HEV={r['HEV']} "
              f"ICE={r['ICE']} TOTAL={r['TOTAL']}")

    if args.dry_run:
        print("(dry-run: CSV not written)")
        return
    added, updated = upsert_csv(CSV_PATH, rows)
    print(f"{added} added, {updated} updated -> {CSV_PATH}")


if __name__ == "__main__":
    main()
