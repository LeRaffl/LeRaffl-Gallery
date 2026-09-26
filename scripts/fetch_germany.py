#!/usr/bin/env python3
"""
Fetch Germany's monthly passenger-car FIRST REGISTRATIONS (Neuzulassungen) by
fuel type from the Kraftfahrt-Bundesamt (KBA) monthly press release and upsert
the current month into ``data/Germany.csv``.

This is the registration-side counterpart of ``scripts/fetch_fleet_germany.py``
(which writes the *stock* dataset). Unlike the fleet fetcher, this one:

  * writes ``data/Germany.csv`` (registrations, **monthly**), and
  * **dispatches ``render-country.yml`` for Germany/Whole** after a data commit
    (registration charts are rendered server-side; fleet charts are not).

Germany historically had no dedicated registration fetcher — it rode ACEA, and
recent months were typed by hand from the KBA press releases (the URLs live in
each row's ``notes`` column). This script automates exactly that source.

Source
------
KBA monthly press release "Fahrzeugzulassungen im Monat <Month>", the
"…_merkmale.xlsx" workbook ("Neuzulassungen … nach ausgewählten Merkmalen").
Landing page (lists the monthly releases):
  https://www.kba.de/DE/Presse/Pressemitteilungen/Fahrzeugzulassungen/fahrzeugzulassungen_node.html
Each release links a "…_komplett.html" page, which links the SharedDocs xlsx:
  https://www.kba.de/SharedDocs/Downloads/DE/Pressemitteilungen/<YYYY>/pm_<NN>_<YYYY>_fahrzeugzulassungen_<MM>_<YYYY>_merkmale.xlsx?__blob=publicationFile

Why the press-release "…_merkmale.xlsx" and not FZ 14? This workbook is the
exact source the maintainer already transcribed by hand (verified: the parser
reproduces the last hand-entered month byte-for-byte — see the sheet layout
below), so automating it keeps the series internally consistent and needs no
re-basing of scope. FZ 14 is a candidate alternative if the press-release
layout ever changes (docs/architecture/NN-source-germany.md).

Sheet layout (single sheet "xls"; verified against 08/2026)
-----------------------------------------------------------
Title (row ~2, col B): "Neuzulassungen von Personenkraftwagen im <Monat> <YYYY>
nach ausgewählten Merkmalen" — the reporting month.
Rows under the "Kraftstoffarten" block carry the fuel label in **column C**
(sub-category) and the month's count in **column D** ("Anzahl <Monat> <YYYY>"):

    Pkw insgesamt              (label in col B) -> TOTAL
    Benzin                                      -> PETROL
    Diesel                                      -> DIESEL
    Flüssiggas / Erdgas / Wasserstoff / …       -> fold into OTHERS (see below)
    Hybrid                                      -> HYBRID total
      darunter Plug-in                          -> PHEV   (HEV = Hybrid − Plug-in)
    Elektro (BEV)                               -> BEV

``OTHERS`` is taken as the **residual** ``TOTAL − BEV − PHEV − HEV − PETROL −
DIESEL`` (= LPG + CNG + hydrogen + fuel-cell + any unlisted "Sonstige"). This
matches the hand-entered convention exactly and is robust to KBA adding or
dropping a minor fuel row. ``"-"`` in a cell means a measured zero.

Data/CSV schema
---------------
``data/Germany.csv`` columns:
    period,time_interval,variant,source,BEV,PHEV,HEV,PETROL,DIESEL,OTHERS,TOTAL,notes
``source`` stays ``"KBA"``; the press-release URL goes in ``notes`` (matching
the existing hand-entered rows). Only the fetched period(s) for variant=Whole
are upserted; every other line is preserved byte-for-byte (invariant #2).

Network
-------
KBA may drop datacenter IPs. Same escape hatches as fetch_fleet_germany.py /
fetch_austria.py: ``KBA_FETCH_RELAY`` (+ optional ``KBA_RELAY_TOKEN``) or
``KBA_PROXY``; otherwise a direct connection / ambient ``HTTPS_PROXY`` is used.

Usage
-----
    python scripts/fetch_germany.py [--file PATH] [--url URL]
                                    [--listing URL] [--force] [--dry-run]

Discovery: KBA retired the listing page in 2026 (it now 404s). The release
page is then derived from the newest one recorded in the CSV's ``notes``
column: KBA numbers its press releases per publication year, so the next
month's page is one of the following pm numbers (``release_candidates``).

``--file`` parses a local "…_merkmale.xlsx" (offline / testing).
``--url``  downloads a specific xlsx, skipping discovery.
``--dry-run`` prints the parsed row and the diff without writing the CSV.
"""
from __future__ import annotations

import argparse
import csv
import io
import os
import re
import sys
from pathlib import Path
from urllib.parse import quote, urljoin

import openpyxl

REPO_ROOT = Path(__file__).resolve().parent.parent
GERMANY_CSV = REPO_ROOT / "data" / "Germany.csv"

COUNTRY = "Germany"
VARIANT = "Whole"
SOURCE = "KBA"

KBA_BASE = "https://www.kba.de"
LISTING_URL = (
    "https://www.kba.de/DE/Presse/Pressemitteilungen/Fahrzeugzulassungen/"
    "fahrzeugzulassungen_node.html"
)

# data/Germany.csv header (single source of truth for the output line order).
CSV_COLUMNS = [
    "period", "time_interval", "variant", "source",
    "BEV", "PHEV", "HEV", "PETROL", "DIESEL", "OTHERS", "TOTAL", "notes",
]

GERMAN_MONTHS = {
    m: i for i, m in enumerate(
        ["januar", "februar", "märz", "april", "mai", "juni", "juli",
         "august", "september", "oktober", "november", "dezember"], 1)
}


# --------------------------------------------------------------------------- #
# Networking (mirrors scripts/fetch_fleet_germany.py::_make_session)
# --------------------------------------------------------------------------- #
def _make_session():
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry

    session = requests.Session()
    session.headers.update({
        # A browser-like UA — harmless hygiene against edge/WAF UA filtering.
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0.0.0 Safari/537.36"
        ),
    })
    session.relay_base = None  # type: ignore[attr-defined]

    relay = os.environ.get("KBA_FETCH_RELAY", "").strip()
    if relay:
        session.relay_base = relay  # type: ignore[attr-defined]
        token = os.environ.get("KBA_RELAY_TOKEN", "").strip()
        if token:
            session.headers["X-Relay-Token"] = token
        print(f"[net] routing via KBA_FETCH_RELAY = "
              f"{re.sub(r'//[^/]+', '//<host>', relay, count=1)}")
    else:
        proxy = os.environ.get("KBA_PROXY", "").strip()
        if proxy:
            session.proxies.update({"http": proxy, "https": proxy})
            print("[net] routing via KBA_PROXY")
        elif os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy"):
            print("[net] using HTTPS_PROXY from environment")
        else:
            print("[net] WARNING: no relay/proxy set; connecting directly.")

    retry = Retry(total=5, connect=5, read=3, backoff_factor=3,
                  status_forcelist=[429, 500, 502, 503, 504],
                  allowed_methods=["GET"])
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def _get(session, url, **kwargs):
    base = getattr(session, "relay_base", None)
    if base:
        url = base + quote(url, safe="")
    return session.get(url, timeout=60, **kwargs)


# --------------------------------------------------------------------------- #
# Discovery: newest "…_merkmale.xlsx" from the monthly press-release listing.
# --------------------------------------------------------------------------- #
_XLSX_RE = re.compile(
    r'href="([^"]*pm_\d+_\d{4}_fahrzeugzulassungen_(\d{2})_(\d{4})_merkmale\.xlsx[^"]*)"',
    re.I,
)
_KOMPLETT_RE = re.compile(
    r'href="([^"]*pm\d+_\d{4}_n_(\d{2})_(\d{2})_pm_komplett\.html[^"]*)"',
    re.I,
)


def _newest(matches):
    """matches: list of (href, mm, yyyy-or-yy). Return newest href by (year, month)."""
    def key(m):
        _href, mm, yr = m
        y = int(yr)
        if y < 100:              # 2-digit year (komplett filenames use YY)
            y += 2000
        return (y, int(mm))
    return max(matches, key=key)[0]


def probe_links(html: str, where: str) -> None:
    """Log-only probe for a future top-brands table (docs 03 §3.16): every
    spreadsheet / PDF download and every link about makes or alternative
    powertrains (KBA's monthly "… nach Marken und alternativen Antrieben"
    release) on a page this fetch reads anyway. Never raises."""
    try:
        hrefs = sorted(set(re.findall(r'href="([^"]+)"', html)))
        keep = [h for h in hrefs
                if re.search(r"\.(xlsx?|csv|pdf)\b", h, re.I)
                or re.search(r"antriebe|marke|fz10|fz 10", h, re.I)]
        print(f"[probe] {where}: {len(keep)} relevant links")
        for h in keep[:40]:
            print(f"[probe]   {h.replace('&amp;', '&')[:200]}")
    except Exception as e:  # noqa: BLE001 — a probe must never break the fetch
        print(f"[probe] link listing failed: {type(e).__name__}: {e}")


_PM_RE = re.compile(r"/(\d{4})/pm(\d+)_(\d{4})_n_(\d{2})_(\d{2})_pm_komplett\.html")
_RELEASE_URL = ("https://www.kba.de/DE/Presse/Pressemitteilungen/{kind}/{year}/"
                "pm{nn:02d}_{year}_{slug}_{mm:02d}_{yy:02d}{tail}_komplett.html")


def _last_release(csv_path: Path = None) -> tuple[int, int, str, str] | None:
    """(publication year, pm number, period, url) of the newest release page
    recorded in data/Germany.csv's notes column — the anchor for guessing the
    next one when the listing page is unavailable."""
    best = None
    path = csv_path or GERMANY_CSV
    if not path.exists():
        return None
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            m = _PM_RE.search(r.get("notes") or "")
            if m:
                key = (r["period"], int(m.group(1)), int(m.group(2)))
                if best is None or key > best[0]:
                    best = (key, r["notes"].split("?")[0])
    if best is None:
        return None
    (period, year, nn), url = best
    return year, nn, period, url


def release_candidates(period: str, anchor: tuple | None, kind: str = "Fahrzeugzulassungen",
                       slug: str = "n", tail: str = "_pm", span: int = 14) -> list[str]:
    """Likely URLs of the release page for `period` (YYYY-MM): KBA numbers its
    press releases per publication year (pm01 … ), so the next one follows the
    anchor's number; a January-published release restarts at pm01."""
    y, m = map(int, period.split("-"))
    pub_year = y + 1 if m == 12 else y
    start = 1
    if anchor and anchor[0] == pub_year:
        start = anchor[1] + 1
    return [_RELEASE_URL.format(kind=kind, year=pub_year, nn=nn, slug=slug, mm=m,
                                yy=y % 100, tail=tail)
            for nn in range(start, start + span)]


def _first_ok(session, urls: list[str]) -> str | None:
    for u in urls:
        try:
            r = _get(session, u)
        except Exception:  # noqa: BLE001 — a dead candidate is just skipped
            continue
        if r.ok and "komplett" in r.url:
            return u
    return None


def discover_latest_xlsx(session, listing_url: str = LISTING_URL) -> str:
    """Find the newest "…_merkmale.xlsx". One hop if the listing links the xlsx
    directly; otherwise follow the newest "…_komplett.html" page and pull it
    from there. KBA retired the listing page in 2026 (404): then the release
    page is found from the last one recorded in data/Germany.csv."""
    resp = _get(session, listing_url)
    if resp.status_code == 404:
        return discover_from_anchor(session)
    resp.raise_for_status()
    html = resp.text
    probe_links(html, "listing")

    direct = _XLSX_RE.findall(html)
    if direct:
        href = _newest(direct)
        return urljoin(KBA_BASE, href.replace("&amp;", "&"))

    komplett = _KOMPLETT_RE.findall(html)
    if not komplett:
        raise RuntimeError(
            "No '…_merkmale.xlsx' or '…_komplett.html' links found on the "
            f"listing page ({listing_url}); the KBA page layout may have "
            "changed. Pass --url to download a specific xlsx, or update "
            "LISTING_URL / the discovery regexes (docs/architecture/"
            "NN-source-germany.md).")
    page_url = urljoin(KBA_BASE, _newest(komplett).replace("&amp;", "&"))
    print(f"[discover] newest release page: {page_url}")
    presp = _get(session, page_url)
    presp.raise_for_status()
    probe_links(presp.text, "release page")
    xhrefs = _XLSX_RE.findall(presp.text)
    if not xhrefs:
        raise RuntimeError(
            f"No '…_merkmale.xlsx' link on the release page {page_url}; the "
            "page layout may have changed.")
    return urljoin(KBA_BASE, _newest(xhrefs).replace("&amp;", "&"))


def discover_from_anchor(session, period: str | None = None) -> str:
    """Release page for `period` (default: the previous calendar month) —
    the recorded page itself when it is that month, else the next pm numbers
    after it — then its "…_merkmale.xlsx" link."""
    period = period or _previous_month_period()
    anchor = _last_release()
    if anchor and anchor[2] == period:
        page = anchor[3]
    else:
        page = _first_ok(session, release_candidates(period, anchor))
    if page is None:
        raise RuntimeError(f"No KBA release page found for {period} "
                           f"(anchor {anchor}); not published yet?")
    print(f"[discover] release page (from anchor): {page}")
    presp = _get(session, page)
    presp.raise_for_status()
    probe_links(presp.text, "release page")
    xhrefs = _XLSX_RE.findall(presp.text)
    if not xhrefs:
        raise RuntimeError(f"No '…_merkmale.xlsx' link on the release page {page}")
    return urljoin(KBA_BASE, _newest(xhrefs).replace("&amp;", "&"))


def probe_marken(session, merkmale_url: str) -> None:
    """Log-only: the release's sibling "…_marken.xlsx" (same URL, `_marken`
    for `_merkmale`) — every sheet's first rows, to wire a make × powertrain
    table against the real layout (docs 03 §3.16). Never raises."""
    try:
        url = merkmale_url.replace("_merkmale.xlsx", "_marken.xlsx")
        r = _get(session, url)
        print(f"[probe] marken.xlsx: HTTP {r.status_code} {url}")
        if not r.ok:
            return
        wb = openpyxl.load_workbook(io.BytesIO(r.content), data_only=True)
        for ws in wb.worksheets:
            print(f"[probe]   sheet {ws.title!r} {ws.max_row}x{ws.max_column}")
            for i, row in enumerate(ws.iter_rows(values_only=True)):
                cells = [str(c)[:22] for c in row if c is not None]
                if cells:
                    print(f"[probe]     r{i + 1}: {cells[:14]}")
                if i >= 45:
                    break
    except Exception as e:  # noqa: BLE001 — a probe must never break the fetch
        print(f"[probe] marken probe failed: {type(e).__name__}: {e}")


def probe_antriebe(session, period: str) -> None:
    """Log-only: find KBA's "… nach Marken und alternativen Antrieben" release
    for `period` and list its downloads (docs 03 §3.16). Never raises."""
    try:
        anchor = _last_release()
        urls = release_candidates(period, anchor and (anchor[0], anchor[1] - 4),
                                  kind="AlternativeAntriebe", slug="Antriebe",
                                  tail="", span=12)
        page = _first_ok(session, urls)
        print(f"[probe] Antriebe release for {period}: {page or 'not found'}")
        if page:
            probe_links(_get(session, page).text, "Antriebe release page")
    except Exception as e:  # noqa: BLE001 — a probe must never break the fetch
        print(f"[probe] Antriebe probe failed: {type(e).__name__}: {e}")


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #
def _num(v):
    """Numeric cell -> int; '-' ('nichts vorhanden') -> 0; else None (unknown)."""
    if isinstance(v, (int, float)):
        return int(round(v))
    if isinstance(v, str) and v.strip() == "-":
        return 0
    return None


def parse_merkmale(source) -> dict:
    """Parse a KBA "…_merkmale.xlsx" into one harmonized registration row."""
    wb = openpyxl.load_workbook(source, data_only=True)
    ws = wb[wb.sheetnames[0]]

    # Reporting month from the title row.
    period = None
    for i in range(1, min(ws.max_row, 10) + 1):
        for j in (2, 1, 3):
            v = ws.cell(i, j).value
            if v and "Neuzulassungen von Personenkraftwagen" in str(v):
                m = re.search(r"im\s+([A-Za-zÄÖÜäöü]+)\s+(\d{4})", str(v))
                if m:
                    mon = GERMAN_MONTHS.get(m.group(1).casefold())
                    if mon:
                        period = f"{int(m.group(2))}-{mon:02d}"
                break
        if period:
            break
    if not period:
        raise RuntimeError("Could not read the reporting month from the sheet "
                           "title (expected '… im <Monat> <YYYY> …').")

    # Label -> August-count. Fuel labels sit in col C, section headers in col B;
    # "Pkw insgesamt" sits in col B. Value is always col D.
    values: dict[str, object] = {}
    for i in range(1, ws.max_row + 1):
        label = ws.cell(i, 3).value or ws.cell(i, 2).value
        if label is None:
            continue
        values.setdefault(str(label).strip().casefold(), ws.cell(i, 4).value)

    def need(*keys):
        for k in keys:
            if k in values:
                return _num(values[k])
        raise RuntimeError(
            f"Expected fuel row {keys!r} not found in sheet; labels present: "
            f"{sorted(values)}")

    total = need("pkw insgesamt")
    petrol = need("benzin")
    diesel = need("diesel")
    bev = need("elektro (bev)", "elektro(bev)", "elektro")
    hyb = need("hybrid")
    # "darunter Plug-in" — tolerate leading/trailing spaces & hyphen variants.
    plugin = None
    for k, v in values.items():
        if "plug-in" in k or "plug in" in k:
            plugin = _num(v)
            break
    if plugin is None:
        raise RuntimeError("Plug-in hybrid row ('darunter Plug-in') not found.")

    if None in (total, petrol, diesel, bev, hyb, plugin):
        raise RuntimeError(
            f"Non-numeric value in a required fuel cell for {period}: "
            f"total={total} petrol={petrol} diesel={diesel} bev={bev} "
            f"hybrid={hyb} plugin={plugin}")

    hev = hyb - plugin
    others = total - bev - plugin - hev - petrol - diesel
    if others < 0:
        raise RuntimeError(
            f"Computed OTHERS < 0 for {period} ({others}); the fuel split does "
            "not reconcile with TOTAL — check the sheet layout.")

    return {
        "period": period,
        "time_interval": "monthly",
        "variant": VARIANT,
        "source": SOURCE,
        "BEV": bev,
        "PHEV": plugin,
        "HEV": hev,
        "PETROL": petrol,
        "DIESEL": diesel,
        "OTHERS": others,
        "TOTAL": total,
        "notes": "",
    }


# --------------------------------------------------------------------------- #
# Line-level upsert into data/Germany.csv (invariant #2: keyed on
# (period, variant); every untouched line preserved byte-for-byte).
# --------------------------------------------------------------------------- #
def _fmt(v) -> str:
    return "" if v is None else str(v)


def _row_to_line(r: dict) -> str:
    return ",".join(_fmt(r.get(c)) for c in CSV_COLUMNS)


def upsert(row: dict, csv_path: Path = GERMANY_CSV) -> str:
    """Replace or insert the (period, Whole) line; keep every other line exact.
    Returns 'added' | 'updated' | 'unchanged'."""
    text = csv_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if not lines:
        raise RuntimeError(f"{csv_path} is empty.")
    header = lines[0]
    if [c.strip() for c in header.split(",")] != CSV_COLUMNS:
        raise RuntimeError(
            f"{csv_path} header does not match the expected schema.\n"
            f"  expected: {CSV_COLUMNS}\n  found:    {header.split(',')}")

    new_line = _row_to_line(row)
    period, variant = row["period"], row["variant"]

    body = lines[1:]
    out_body: list[str] = []
    status = "added"
    replaced = False
    for line in body:
        if not line.strip():
            out_body.append(line)
            continue
        cells = line.split(",")
        if len(cells) >= 3 and cells[0] == period and cells[2] == variant:
            if line == new_line:
                return "unchanged"
            out_body.append(new_line)
            status = "updated"
            replaced = True
        else:
            out_body.append(line)

    if not replaced:
        # Insert keeping period-ascending order among rows (append if newest).
        insert_at = len(out_body)
        for idx, line in enumerate(out_body):
            cells = line.split(",")
            if cells and cells[0] and cells[0] > period:
                insert_at = idx
                break
        out_body.insert(insert_at, new_line)

    csv_path.write_text("\n".join([header] + out_body) + "\n", encoding="utf-8")
    return status


# --------------------------------------------------------------------------- #
def _previous_month_period() -> str:
    from datetime import date
    t = date.today()
    return f"{t.year - 1}-12" if t.month == 1 else f"{t.year}-{t.month - 1:02d}"


def _csv_has(period: str, csv_path: Path = GERMANY_CSV) -> bool:
    if not csv_path.exists():
        return False
    with csv_path.open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["period"] == period and r["variant"] == VARIANT:
                return True
    return False


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--file", help="parse a local …_merkmale.xlsx instead of downloading")
    ap.add_argument("--url", help="download this xlsx directly, skipping discovery")
    ap.add_argument("--listing", default=LISTING_URL,
                    help="override the press-release listing page for discovery")
    ap.add_argument("--force", action="store_true",
                    help="write even if the CSV already has the previous month")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the parsed row and the diff without writing")
    args = ap.parse_args()

    # Early-exit: if the previous calendar month is already present, most runs
    # are no-ops (the release lands early in the month; before that, nothing new).
    if not args.file and not args.url and not args.force:
        prev = _previous_month_period()
        if _csv_has(prev):
            print(f"CSV already has {prev}; nothing to do (use --force to re-fetch).")
            return

    src_url = None
    if args.file:
        print(f"[src] parsing local file {args.file}")
        row = parse_merkmale(args.file)
    else:
        session = _make_session()
        src_url = args.url or discover_latest_xlsx(session, args.listing)
        print(f"[src] downloading {src_url}")
        resp = _get(session, src_url)
        resp.raise_for_status()
        row = parse_merkmale(io.BytesIO(resp.content))
        row["notes"] = src_url

    print(f"[parse] {row['period']} Whole -> {_row_to_line(row)}")

    if not args.force and _csv_has(row["period"]):
        print(f"CSV already has {row['period']}; nothing to do "
              f"(use --force to overwrite).")
        if not args.dry_run:
            return

    if args.dry_run:
        if not args.file:
            probe_marken(session, src_url)
            probe_antriebe(session, row["period"])
        print("[dry-run] not writing.")
        return

    status = upsert(row)
    print(f"[write] {GERMANY_CSV.relative_to(REPO_ROOT)}: {row['period']} {status}")


if __name__ == "__main__":
    main()
