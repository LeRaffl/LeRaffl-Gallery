#!/usr/bin/env python3
"""
Fetch France passenger-car registration data from the SDES (Service des
données et études statistiques, Ministère de la Transition écologique)
"Immatriculations mensuelles de voitures neuves par motorisation" series and
upsert `data/France.csv` (variant `Whole`).

Why SDES (and not ACEA)
-----------------------
France was the last large market still served by the ACEA aggregate. SDES is
the national registry-statistics branch of the same SIV registry ACEA/PFA/AAA
sit on, published monthly, free and open (Licence Ouverte). The detailed
"motorisation" series is the only SDES product that keeps a real **HEV**
column (the coarse open-data "source d'énergie" taxonomy folds HEV into
petrol/diesel — see docs/architecture/36-source-france.md). It also carries the
**full fuel split back to 2011-01**, where the old ACEA series was sparse /
quarterly-interpolated before ~2025.

Source workbook
---------------
`https://www.statistiques.developpement-durable.gouv.fr/media/<id>/download`
One .xlsx, one sheet, a monthly time series from 2011_01. Columns (row 3):

    Gazole (thermique) | Essence (thermique) |
    hybride gazole non rechargeable | hybride essence non rechargeable |
    gazole (y compris hybrides non rechargeables) |       <- aggregate, IGNORED
    essence (y compris hybrides non rechargeables) |       <- aggregate, IGNORED
    hybride rechargeable | Electrique | Gaz & ND | Total

Footer row is `Source : SDES-RSVERO`. NB the sheet TAB is misnamed one month
behind (e.g. tab `2026_05` for a file whose last row is `2026_06`), so we read
the latest month from the period column, never the tab name.

Mapping to the canonical CSV columns
------------------------------------
    BEV     <- Electrique
    PHEV    <- hybride rechargeable
    HEV     <- hybride gazole non rechargeable + hybride essence non rechargeable
    PETROL  <- Essence (thermique)          (pure petrol, excl. non-recharg. hybrids)
    DIESEL  <- Gazole (thermique)           (pure diesel,  excl. non-recharg. hybrids)
    OTHERS  <- Gaz & ND                      (LPG/CNG + non-déterminé)
    TOTAL   <- Total   (asserted == sum of the seven base columns above)

The two "(y compris hybrides)" columns are convenience aggregates
(= thermique + non-rechargeable hybride) and are deliberately NOT summed in.

Consistency with the ACEA target (documented, not tuned away)
-------------------------------------------------------------
Totals reconcile with ACEA/AAA to within ~0.2 % (the SDES "hors provisoires et
transit temporaire" residual). Per-fuel there is a small, systematic
definitional step: SDES puts ~3 % less in HEV / ~3.5 % more in PETROL than
ACEA (ACEA/PFA count 48 V mild-hybrids as HEV; SDES counts them as pure
petrol — SDES is actually closer to this project's MHEV->ICE glossary
convention), and SDES OTHERS is higher because "Gaz & ND" carries the
not-yet-coded "ND" bucket. BEV share is essentially unchanged (~+0.3 pp).
See docs/architecture/36-source-france.md § "Fachlich".

Usage
-----
    python scripts/fetch_france.py --file <local.xlsx>   # parse a local workbook
    python scripts/fetch_france.py --url  <media url>    # download one workbook
    python scripts/fetch_france.py                       # resolve latest, then fetch
    #   optional: --out data/France.csv (default) · --dry-run · --page <hub url>

The live download resolves the current `media/<id>/download` by scraping the
SDES landing page (the id rotates every publication). That resolution is the
one part that cannot be tested from the Claude sandbox (egress to every French
host is policy-denied) — it must be validated from GitHub Actions. The parser
and the upsert are fully validated locally against the published workbook.
Invoked by `.github/workflows/fetch-france.yml` (added once the download path
is confirmed).
"""
import argparse
import csv
import io
import re
import sys
from html import unescape
from pathlib import Path

import requests
from openpyxl import load_workbook

REPO = Path(__file__).resolve().parent.parent
OUT_DEFAULT = REPO / "data" / "France.csv"
SOURCE = "SDES"

# Stable landing page that links the current série workbook. The média id in the
# download URL rotates each publication, so we resolve it from here rather than
# hardcode it. VALIDATE IN GHA (see module docstring).
LANDING_PAGE = (
    "https://www.statistiques.developpement-durable.gouv.fr/"
    "immatriculation-des-vehicules-routiers"
)
# SDES média download URLs are opaque — "/media/<id>/download" carries NO
# filename — so the série is identified by the human-readable LABEL near the
# link, not by the href. The média id rotates every publication.
MEDIA_HREF_RE = re.compile(r'href="([^"]*?/media/(\d+)/download[^"]*)"', re.I)
_VP_POS = ("particuli",)                         # voitures particulières (VP)
_ENERGY_POS = ("énergie", "energie", "motorisation")
_OTHER_NEG = ("utilitaire", "poids lourd", "autobus", "autocar", "deux-roues",
              "deux roues", "cyclomoteur", "camion")  # the VUL/PL/bus/2-roues séries

CSV_COLUMNS = [
    "period", "time_interval", "variant", "source",
    "BEV", "PHEV", "HEV", "PETROL", "DIESEL", "OTHERS", "TOTAL", "notes",
]
PERIOD_RE = re.compile(r"^\s*(\d{4})_(\d{2})\s*$")


def _norm(s) -> str:
    """Normalise a header cell: lowercase, collapse whitespace/newlines."""
    return re.sub(r"\s+", " ", str(s or "").strip().lower())


def _column_index(header: list, *, contains=(), equals=None, exclude=()) -> int:
    """Find the single column whose normalised header matches. Raises if 0 or >1."""
    hits = []
    for i, cell in enumerate(header):
        h = _norm(cell)
        if not h:
            continue
        if equals is not None and h != equals:
            continue
        if any(tok not in h for tok in contains):
            continue
        if any(tok in h for tok in exclude):
            continue
        hits.append(i)
    if len(hits) != 1:
        raise ValueError(
            f"expected exactly one column for "
            f"{equals or contains!r} (excl {exclude!r}); found {hits} "
            f"in header {[_norm(c) for c in header]}"
        )
    return hits[0]


def _resolve_columns(header: list) -> dict:
    """Map canonical fuel keys -> source column indices, by header text."""
    return {
        "DIESEL": _column_index(header, contains=("gazole", "thermique")),
        "PETROL": _column_index(header, contains=("essence", "thermique")),
        # the two non-rechargeable hybrid columns are summed into HEV; the
        # "(y compris hybrides ...)" aggregates must be excluded — they also
        # contain "hybride"/"gazole"/"non recharg".
        "HEV_D": _column_index(header, contains=("hybride", "gazole", "non recharg"),
                               exclude=("y compris",)),
        "HEV_E": _column_index(header, contains=("hybride", "essence", "non recharg"),
                               exclude=("y compris",)),
        "PHEV": _column_index(header, equals="hybride rechargeable"),
        "BEV": _column_index(header, contains=("electrique",)),
        "OTHERS": _column_index(header, contains=("gaz", "nd"), exclude=("gazole",)),
        "TOTAL": _column_index(header, equals="total"),
    }


def _find_header_and_period_col(rows: list) -> tuple:
    """Locate the header row (the one carrying 'Total') and the period column."""
    for r_idx, row in enumerate(rows):
        if any(_norm(c) == "total" for c in row):
            # period column: the one whose *next* data rows look like YYYY_MM
            for c_idx, _ in enumerate(row):
                for probe in rows[r_idx + 1: r_idx + 6]:
                    if c_idx < len(probe) and PERIOD_RE.match(str(probe[c_idx] or "")):
                        return r_idx, list(row), c_idx
    raise ValueError("could not locate the header row (no 'Total' column found)")


def _num(x) -> float:
    return 0.0 if x in (None, "") else float(x)


def parse_workbook(data: bytes) -> list:
    """Parse the SDES workbook bytes -> list of canonical row dicts (period asc)."""
    wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    h_idx, header, period_col = _find_header_and_period_col(rows)
    cols = _resolve_columns(header)

    out = []
    for row in rows[h_idx + 1:]:
        m = PERIOD_RE.match(str(row[period_col] if period_col < len(row) else "" or ""))
        if not m:
            continue  # blank separators and the 'Source : SDES-RSVERO' footer
        year, month = m.group(1), m.group(2)
        bev = _num(row[cols["BEV"]])
        phev = _num(row[cols["PHEV"]])
        hev = _num(row[cols["HEV_D"]]) + _num(row[cols["HEV_E"]])
        petrol = _num(row[cols["PETROL"]])
        diesel = _num(row[cols["DIESEL"]])
        others = _num(row[cols["OTHERS"]])
        total = _num(row[cols["TOTAL"]])
        base = bev + phev + hev + petrol + diesel + others
        if abs(base - total) > 1.0:  # the file's own Total must close to the parts
            raise ValueError(
                f"{year}-{month}: parts {base:.0f} != Total {total:.0f} "
                f"(check column mapping)"
            )
        out.append({
            "period": f"{year}-{month}",
            "time_interval": "monthly",
            "variant": "Whole",
            "source": SOURCE,
            "BEV": bev, "PHEV": phev, "HEV": hev,
            "PETROL": petrol, "DIESEL": diesel, "OTHERS": others,
            "TOTAL": total,
            "notes": "",
        })
    if not out:
        raise ValueError("no data rows parsed")
    return out


def _clean(fragment: str) -> str:
    """Strip HTML tags + entities from a fragment; collapse whitespace."""
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


# Block-level tags used to bound a link's label to its own list item / row /
# card, so an adjacent série's keywords don't bleed into this link's score.
# Row-level containers only — NOT <td>/<th>/<span>, so a table row's label cell
# is kept with its download-link cell while neighbouring rows still don't bleed.
_BLOCK = re.compile(
    r"</?(?:li|ul|ol|tr|div|p|h[1-6]|section|article|dl|table|nav)\b[^>]*>", re.I)


def _label_for(doc: str, a_start: int, a_end: int) -> str:
    """The human-readable label of the anchor, bounded to its enclosing block."""
    left_region = doc[max(0, a_start - 400): a_start]
    bounds = list(_BLOCK.finditer(left_region))
    left = (max(0, a_start - 400) + bounds[-1].end()) if bounds else max(0, a_start - 400)
    tail = doc[a_end: a_end + 200]
    nb = _BLOCK.search(tail)
    right = a_end + (nb.start() if nb else 80)
    return _clean(doc[left:right])


def resolve_latest_url(session: requests.Session, page: str) -> str:
    """Find the current 'VP neuves par énergie' média download URL on the page.

    SDES média URLs carry no filename, so each candidate is scored by the text of
    its enclosing block (VP + énergie, minus the VUL/PL/bus séries). On failure the
    error dumps every média link it saw (id + label) so the next fix is one-shot
    rather than another blind guess.
    """
    r = session.get(page, timeout=60)
    r.raise_for_status()
    doc = r.text
    cands = []  # (score, media_id, absolute_url, label)
    for m in MEDIA_HREF_RE.finditer(doc):
        href, mid = m.group(1), int(m.group(2))
        label = _label_for(doc, m.start(), m.end())
        low = label.lower()
        score = (2 * any(k in low for k in _VP_POS)
                 + 2 * any(k in low for k in _ENERGY_POS)
                 + ("neuv" in low)
                 + ("serie" in low or "série" in low)
                 - 4 * any(k in low for k in _OTHER_NEG))
        cands.append((score, mid, requests.compat.urljoin(page, href), label))
    cands.sort(key=lambda c: (c[0], c[1]), reverse=True)  # best label, then newest id
    if cands and cands[0][0] >= 3:
        print(f"[france] resolved média/{cands[0][1]} (score {cands[0][0]}): {cands[0][3][:120]}")
        return cands[0][2]

    if cands:
        seen = " || ".join(f"[{s}] media/{mid}: {lab[:90]}" for s, mid, _u, lab in cands[:12])
        detail = f"{len(cands)} média link(s) found, none scored as the VP-énergie série: {seen}"
    else:
        detail = (f"NO /media/<id>/download links in the {len(doc)}-byte page — the download "
                  f"list is likely JavaScript-rendered (a static endpoint or headless fetch is needed)")
    raise ValueError(f"could not identify the VP-énergie série link on {page}. {detail}. "
                     f"Workaround: pass --url with the média URL explicitly.")


def fetch_bytes(args, session: requests.Session) -> bytes:
    if args.file:
        return Path(args.file).read_bytes()
    url = args.url or resolve_latest_url(session, args.page)
    print(f"[france] downloading {url}")
    r = session.get(url, timeout=120)
    r.raise_for_status()
    fetch_bytes.url = url  # remember for the notes column
    return r.content


def upsert(out_path: Path, new_rows: list, *, dry_run: bool, src_url: str) -> None:
    """Write new_rows into out_path, honouring the ACEA-courtesy rule.

    Overwrite an existing row only if its source is exactly ``ACEA`` (the
    fallback we are replacing) or already ``SDES``. Never touch a row written by
    any other source. New months are appended.
    """
    existing: dict[str, dict] = {}
    order: list[str] = []
    if out_path.exists():
        with out_path.open(encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                existing[row["period"]] = row
                order.append(row["period"])

    latest = max(r["period"] for r in new_rows)
    changed = skipped = added = 0
    for nr in new_rows:
        p = nr["period"]
        # only the newest row carries the source URL in notes (repo convention)
        nr = {**nr, "notes": (src_url if (p == latest and src_url) else "")}
        old = existing.get(p)
        if old is None:
            existing[p] = nr
            order.append(p)
            added += 1
        elif (old.get("source") or "").strip() in (SOURCE, "ACEA"):
            # full overwrite: the row is now SDES-sourced, so a stale ACEA note
            # (e.g. an acea.auto PDF URL) must not survive on it.
            existing[p] = nr
            changed += 1
        else:
            skipped += 1

    order = sorted(dict.fromkeys(order))
    print(f"[france] {added} added, {changed} updated, {skipped} preserved "
          f"(non-ACEA/SDES source) -> {out_path}")
    if dry_run:
        print("[france] --dry-run: not writing")
        return
    with out_path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        w.writeheader()
        for p in order:
            w.writerow({c: existing[p].get(c, "") for c in CSV_COLUMNS})


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Fetch France (SDES) registrations.")
    ap.add_argument("--file", help="parse a local .xlsx instead of downloading")
    ap.add_argument("--url", help="download this exact média .xlsx URL")
    ap.add_argument("--page", default=LANDING_PAGE, help="landing page to resolve the média link")
    ap.add_argument("--out", default=str(OUT_DEFAULT), help="output CSV (default data/France.csv)")
    ap.add_argument("--dry-run", action="store_true", help="report changes, do not write")
    args = ap.parse_args(argv)

    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 (LeRaffl-Gallery fetch_france)"})
    fetch_bytes.url = ""
    try:
        data = fetch_bytes(args, session)
        rows = parse_workbook(data)
    except Exception as exc:  # noqa: BLE001 - surface a clean CI failure
        print(f"[france] ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"[france] parsed {len(rows)} months: {rows[0]['period']} .. {rows[-1]['period']}")
    upsert(Path(args.out), rows, dry_run=args.dry_run, src_url=getattr(fetch_bytes, "url", "") or (args.url or ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
