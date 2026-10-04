#!/usr/bin/env python3
"""
Fetch UK new-car registrations from SMMT and update data/UK.csv.

Usage
-----
    python scripts/fetch_uk.py [--period YYYY-MM] [--backfill] [--force]
                               [--dry-run] [--from-html PATH]
                               [--github-output PATH] [--summary PATH]

* --period     Target month (default: the calendar month that just ended).
* --backfill   Read every release from FIRST_RELEASE (2024-11) on and add the
               months data/UK.csv does not have yet. Months it already has are
               compared, never overwritten (see "History" below).
* --force      Overwrite an existing row for the target month (and rows with a
               foreign `source`), and skip the plausibility guard. Not needed
               to replace a provisional row (see "Preliminary figures").
* --dry-run    Parse, validate and print; write nothing. Re-reading a month
               the CSV already holds this way is the regression test for a
               parser change: it must reproduce the committed row.
* --from-html  Parse a saved release / data page instead of the network
               (offline debugging; the month is read from the table itself).

Invoked by .github/workflows/fetch-uk.yml (daily in the publication window,
plus workflow_dispatch). Full method, governance checks and a debugging
runbook: docs/architecture/50-source-uk.md.

Data source
-----------
SMMT (Society of Motor Manufacturers and Traders) compiles the UK's new-car
registrations from DVLA data and publishes them on the morning of the
fourth working day or so of the next month (2026: Jan 6, Feb 5, Mar 5, Apr 7,
May 6, Jun 4, Jul 6, Aug 5, Sep 4, Oct 2), as a news post on smmt.co.uk.
Since the November 2024 release the post carries real HTML tables (earlier
releases are images):

    <Month> | <year> | <year-1> | % change | Mkt share '<yy> | Mkt share '<yy-1>
    BEV     | 99,199 | 72,775   | 36.3%    | 28.3%           | 23.3%
    HEV / PHEV / PETROL / DIESEL ...
    TOTAL   | 350,518| 312,793  | 12.1%

followed by the same table year-to-date, private/fleet/business, the top-10
models (month and year-to-date) and the top-10 battery-electric models.

The posts are found through the site's WordPress REST API
(/wp-json/wp/v2/posts, no key): SMMT tags nothing, so the fetcher lists the
posts published in the month after the target and keeps the one whose
fuel table is headed by the target month. The vehicle-data page
(/vehicle-data/car-registrations/) shows the newest month's tables too, plus a
full brand ("MARQUE") table for the month and the year to date; it is the
fallback for the fuel table and the only source of the brand table.

Fuel mapping (SMMT -> CSV column)
---------------------------------
    BEV    -> BEV
    PHEV   -> PHEV      (plug-in hybrids, range extenders included)
    HEV    -> HEV       (full hybrids)
    PETROL -> PETROL    (mild-hybrid petrol cars included — SMMT folded its
    DIESEL -> DIESEL     former MHEV rows into petrol/diesel)
    TOTAL  -> TOTAL
    OTHERS = TOTAL - the five above (0 in every release so far)

Labels outside FUEL_LABELS abort the run: a new SMMT row (an MHEV line coming
back, a hydrogen line) needs a human decision about its column.

Preliminary figures
-------------------
When SMMT releases early (the September 2026 release came on 2 October), the
tables are "SMMT preliminary figures ... subject to change", and the full and
final figures follow a working day or so later — usually by editing the same
post and the data page in place. The fetcher spots SMMT's own wording
(PRELIM_RE) and writes such a month with notes "provisional: SMMT preliminary
figures; <url>" (the 03-data-objects.md convention). A provisional row does
not satisfy the self-throttle, so the next runs read the release again and
replace the row — without --force — as soon as the numbers or the
preliminary flag change. A final row is never replaced by a provisional one
(only with --force).

History
-------
Rows up to 2026-09 were transcribed by hand from the same releases (with the
same `source` string, "SMMT"). SMMT restates its previous-year column, so a
release's year-ago figures can differ slightly from what was published a year
earlier; the CSV keeps the figures as first published (invariant 3, "don't
rewrite the past") and the run reports the restatement in the step summary.
"""
from __future__ import annotations

import argparse
import csv
import difflib
import io
import json
import os
import re
import sys
import time
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import market_top  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
CSV_PATH = REPO / "data" / "UK.csv"
COUNTRY = "UK"
SOURCE = "SMMT"
VARIANT = "Whole"
FIRST_RELEASE = "2024-11"     # first release with HTML tables (older: images)

SITE = "https://www.smmt.co.uk"
POSTS_API = SITE + "/wp-json/wp/v2/posts"
DATA_PAGE = SITE + "/vehicle-data/car-registrations/"

CSV_COLUMNS = ["period", "time_interval", "variant", "source", "BEV", "PHEV",
               "HEV", "PETROL", "DIESEL", "OTHERS", "TOTAL", "notes"]
FUELS = ["BEV", "PHEV", "HEV", "PETROL", "DIESEL", "OTHERS"]
FUEL_LABELS = {
    "BEV": "BEV", "PHEV": "PHEV", "HEV": "HEV",
    "PETROL": "PETROL", "DIESEL": "DIESEL",
    # Petrol / diesel including their mild hybrids, as some year-to-date
    # tables word it (2024-11, 2026-08); older layouts listed MHEV apart.
    "ALL PETROL": "PETROL", "ALL DIESEL": "DIESEL",
    "MHEV PETROL": "PETROL", "MHEV DIESEL": "DIESEL",
}
REQUIRED = {"BEV", "PHEV", "HEV", "PETROL", "DIESEL"}

MONTHS = ["january", "february", "march", "april", "may", "june", "july",
          "august", "september", "october", "november", "december"]

# Governance thresholds (docs/architecture/50-source-uk.md §5).
PCT_TOL = 0.25          # printed % change / market share vs recomputed, in pp
YEAR_AGO_WARN = 0.02    # restated year-ago TOTAL vs the CSV row
YTD_WARN = 0.01         # YTD minus the CSV's earlier months vs this month
YTD_ABORT = 0.05
PLAUSIBLE = (0.5, 2.0)  # TOTAL / same month a year earlier
LATE_DAY = 10           # after this day of M+1, "no release found" is an error

# SMMT's caption under every table of an early release ("SMMT preliminary
# figures are subject to change. Full and final figures published <date>").
PRELIM_RE = re.compile(r"preliminary\s+figures\s+are\s+subject\s+to\s+change", re.I)
PROVISIONAL = "provisional: SMMT preliminary figures; "

HTTP_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"),
    "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
}
HTTP_TRIES = 4

TOP_PATH = market_top.MARKET_DIR / "uk_top.json"
STORE_PATH = market_top.MARKET_DIR / "uk_months.json"
TOP_UNIT = ("new car registrations by marque as SMMT publishes them — every "
            "powertrain, as SMMT's brand table has no fuel split; models are "
            "SMMT's top 10, the rest of the market is unranked")


# ── HTML tables ────────────────────────────────────────────────────────────

class _Tables(HTMLParser):
    """Every <table> of a page as a list of rows of cell texts."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[str]]] = []
        self._depth = 0
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self._depth += 1
            if self._depth == 1:
                self.tables.append([])
        elif self._depth == 1 and tag == "tr":
            self._row = []
        elif self._depth == 1 and tag in ("td", "th") and self._row is not None:
            self._cell = []
        elif tag == "br" and self._cell is not None:
            self._cell.append(" ")

    def handle_endtag(self, tag):
        if tag == "table":
            self._depth = max(0, self._depth - 1)
        elif self._depth == 1 and tag in ("td", "th") and self._cell is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif self._depth == 1 and tag == "tr" and self._row is not None:
            if any(self._row):
                self.tables[-1].append(self._row)
            self._row = None

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)


def tables_of(page: str) -> list[list[list[str]]]:
    p = _Tables()
    p.feed(page)
    return [t for t in p.tables if t]


def to_int(cell: str) -> int | None:
    s = cell.replace(",", "").replace(" ", "").strip()
    return int(s) if re.fullmatch(r"-?\d+", s) else None


def to_pct(cell: str) -> float | None:
    s = cell.replace(",", "").replace("%", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def month_in(text: str) -> int | None:
    """Month named in a table header — tolerant of SMMT's typos ("Feburary",
    2025-02) and abbreviations ("Sept")."""
    for word in re.findall(r"[a-z]+", text.lower()):
        for i, name in enumerate(MONTHS, 1):
            if word == name or word in (name[:3], name[:4]):
                return i
        if len(word) >= 5:
            close = difflib.get_close_matches(word, MONTHS, n=1, cutoff=0.8)
            if close:
                return MONTHS.index(close[0]) + 1
    return None


def is_ytd(text: str) -> bool:
    return bool(re.search(r"year[\s-]*to[\s-]*date|\bytd\b", text.lower()))


def header_text(table: list[list[str]]) -> str:
    """Text of the rows before the first row with a number in column 2."""
    out = []
    for row in table:
        if len(row) > 1 and to_int(row[1]) is not None and not re.fullmatch(r"\d{4}", row[1]):
            break
        out.append(" ".join(row))
    return " ".join(out)


def header_years(table: list[list[str]]) -> tuple[int, int] | None:
    for row in table:
        ys = [int(c) for c in row if re.fullmatch(r"(19|20)\d{2}", c)]
        if len(ys) >= 2:
            return ys[0], ys[1]
    return None


# ── fuel table ─────────────────────────────────────────────────────────────

def parse_fuel_table(table: list[list[str]]) -> dict | None:
    """One SMMT fuel table -> {kind, month, year, prev_year, cur, prev, pct,
    share}. None if `table` is not a fuel table. Raises on a fuel table that
    does not have the expected shape (schema drift)."""
    labels = [r[0].strip().upper() for r in table if r]
    if "BEV" not in labels or "TOTAL" not in labels:
        return None
    head = header_text(table)
    years = header_years(table)
    if not years:
        raise RuntimeError(f"fuel table without a year header: {head!r}")
    kind = "ytd" if is_ytd(head) else "month"
    month = month_in(head)      # None: header without a month (2025-08, 2026-06)
    cur, prev, pct, share, unknown = {}, {}, {}, {}, []
    seen: dict[str, int] = {}
    for row in table:
        label = " ".join(row[0].upper().split()) if row else ""
        if label in ("", ) or to_int(row[1] if len(row) > 1 else "") is None:
            continue
        if len(row) < 3:
            raise RuntimeError(f"fuel row {row!r}: expected at least 3 cells")
        a, b = to_int(row[1]), to_int(row[2])
        if a is None or b is None:
            raise RuntimeError(f"fuel row {row!r}: non-numeric count")
        if label == "TOTAL":
            col = "TOTAL"
        elif label in FUEL_LABELS:
            col = FUEL_LABELS[label]
        else:
            unknown.append(label)
            continue
        cur[col] = cur.get(col, 0) + a
        prev[col] = prev.get(col, 0) + b
        seen[col] = seen.get(col, 0) + 1
        if col != "TOTAL":
            pct[col] = to_pct(row[3]) if len(row) > 3 else None
            share[col] = to_pct(row[4]) if len(row) > 4 else None
    if unknown:
        raise RuntimeError(f"unknown SMMT fuel row(s) {unknown} — map them in "
                           "FUEL_LABELS (docs/architecture/50-source-uk.md §4)")
    missing = REQUIRED - set(cur)
    if missing or "TOTAL" not in cur:
        raise RuntimeError(f"fuel table lacks {sorted(missing | ({'TOTAL'} - set(cur)))}")
    # Two SMMT rows summed into one column: their printed percentages
    # describe the rows, not the column, so they cannot be checked.
    for col, n in seen.items():
        if n > 1:
            pct.pop(col, None)
            share.pop(col, None)
    return {"kind": kind, "month": month, "year": years[0], "prev_year": years[1],
            "cur": cur, "prev": prev, "pct": pct, "share": share}


def fuel_tables(page: str) -> list[dict]:
    out = []
    for t in tables_of(page):
        f = parse_fuel_table(t)
        if f:
            out.append(f)
    return out


def month_table(page: str, hint: str | None = None) -> dict | None:
    """The single-month fuel table of a release / the data page, with its
    year-to-date twin attached as ["ytd"] when present.

    Some releases print no month above the table (2025-08, 2026-06). `hint`
    is the month a release found in the publication window must be about
    (find_release passes the target); it is used only when the header has no
    month and its year column agrees. Without a hint such a table raises."""
    found = fuel_tables(page)
    month = next((f for f in found if f["kind"] == "month"), None)
    if month and month["month"] is None:
        hy, hm = map(int, hint.split("-")) if hint else (None, None)
        if hy != month["year"]:
            raise RuntimeError("single-month fuel table without a month in its header"
                               + (f" and year {month['year']} ≠ expected {hint}" if hint else ""))
        month["month"] = hm
        month["month_from"] = "publication window"
    if month:
        month["ytd"] = next((f for f in found if f["kind"] == "ytd"
                             and f["year"] == month["year"]), None)
    return month


def period_of(f: dict) -> str:
    return f"{f['year']}-{f['month']:02d}"


def to_counts(values: dict[str, int]) -> dict[str, int]:
    """SMMT's columns -> the CSV's, OTHERS as the residual."""
    out = {k: int(values.get(k, 0)) for k in FUELS if k != "OTHERS"}
    out["OTHERS"] = int(values["TOTAL"]) - sum(out.values())
    out["TOTAL"] = int(values["TOTAL"])
    return out


def validate(f: dict) -> list[str]:
    """Internal consistency of one month table. Returns problems (abort)."""
    problems = []
    for side, year in (("cur", f["year"]), ("prev", f["prev_year"])):
        c = to_counts(f[side])
        if c["OTHERS"] < 0:
            problems.append(f"{year}: fuels sum to {c['TOTAL'] - c['OTHERS']:,} > "
                            f"TOTAL {c['TOTAL']:,}")
    if f["year"] != f["prev_year"] + 1:
        problems.append(f"year columns {f['year']} / {f['prev_year']} are not consecutive "
                        "— columns shifted?")
    total = f["cur"]["TOTAL"]
    for col, printed in f["share"].items():
        if printed is None or not total:
            continue
        got = 100 * f["cur"][col] / total
        if abs(got - printed) > PCT_TOL:
            problems.append(f"{col}: printed share {printed}% but {f['cur'][col]:,} / "
                            f"{total:,} = {got:.2f}% — columns shifted?")
    for col, printed in f["pct"].items():
        if printed is None or not f["prev"].get(col):
            continue
        got = 100 * (f["cur"][col] / f["prev"][col] - 1)
        if abs(got - printed) > PCT_TOL and abs(got) < 1000:
            problems.append(f"{col}: printed change {printed}% but recomputed "
                            f"{got:.2f}% — columns shifted?")
    return problems


# ── brand + top-model tables (data page only) ──────────────────────────────

def parse_marque(table: list[list[str]]) -> dict | None:
    """MARQUE table -> {kind, month, year, brands: {brand: n}, others, total}.
    SMMT's "Other British" / "Other Imports" lines are its own rest (counted,
    never ranked); "Grand Total" must equal brands + others exactly."""
    head = header_text(table)
    if "MARQUE" not in head.upper():
        return None
    years = header_years(table)
    brands, others, total = {}, 0, None
    for row in table:
        if len(row) < 2 or to_int(row[1]) is None or re.fullmatch(r"\d{4}", row[1]):
            continue
        name = market_top.clean(row[0])
        if not name or name == "MARQUE":
            continue
        n = to_int(row[1])
        if "TOTAL" in name:
            total = n
        elif name.startswith("OTHER"):
            others += n
        else:
            brands[name] = brands.get(name, 0) + n
    if total is None:
        raise RuntimeError(f"marque table ({head!r}) has no Grand Total row")
    if sum(brands.values()) + others != total:
        raise RuntimeError(f"marque table ({head!r}): brands + others = "
                           f"{sum(brands.values()) + others:,} ≠ Grand Total {total:,}")
    return {"kind": "ytd" if is_ytd(head) else "month", "month": month_in(head),
            "year": years[0] if years else None, "brands": brands,
            "others": others, "total": total}


def parse_top_models(table: list[list[str]]) -> dict | None:
    """A top-10 model table (rank | 'BRAND Model' | units) -> {kind, models}.
    kind: month / ytd / bev (the battery-electric list has no period header)."""
    rows = [r for r in table if len(r) >= 3 and re.fullmatch(r"\d{1,2}", r[0].strip())
            and to_int(r[-1]) is not None]
    if len(rows) < 5:
        return None
    head = header_text(table)
    kind = "ytd" if is_ytd(head) else ("month" if month_in(head) else "bev")
    return {"kind": kind, "models": [(" ".join(r[1].split()), to_int(r[-1])) for r in rows]}


def split_model(label: str, brands: list[str]) -> tuple[str, str]:
    """'TESLA Model 3' -> ('TESLA', 'MODEL 3') against the marque names."""
    s = market_top.clean(label)
    for b in sorted(brands, key=len, reverse=True):
        if s.startswith(b + " "):
            return b, s[len(b) + 1:]
    head, _, rest = s.partition(" ")
    return head, rest or s


def market_tables(page: str) -> dict:
    """{fuel, marque_month, marque_ytd, top_month, top_ytd} of the data page."""
    out = {"fuel": month_table(page)}
    for t in tables_of(page):
        m = parse_marque(t)
        if m:
            out[f"marque_{m['kind']}"] = m
            continue
        tm = parse_top_models(t)
        if tm and tm["kind"] in ("month", "ytd"):
            out.setdefault(f"top_{tm['kind']}", tm)
    return out


def units_of(marque: dict, top: dict | None, total: int) -> tuple[dict, dict]:
    """(brand units, model units) in market_top's shape (class ALL); what the
    brand table / the top 10 do not list counts as the unranked REST."""
    brands = {(market_top.ALL, b, ""): n for b, n in marque["brands"].items() if n}
    listed = sum(brands.values())
    if listed > total:
        raise RuntimeError(f"marque table lists {listed:,} > TOTAL {total:,}")
    brands[(market_top.ALL, market_top.REST, "")] = total - listed
    models: dict = {}
    names = list(marque["brands"])
    for label, n in (top or {}).get("models", []):
        b, m = split_model(label, names)
        models[(market_top.ALL, b, m)] = models.get((market_top.ALL, b, m), 0) + n
    models[(market_top.ALL, market_top.REST, "")] = total - sum(models.values())
    return brands, models


def build_uk_top(page: str, store: dict | None = None) -> tuple[dict, dict]:
    """market/uk_top.json from the data page. Headline = January to the
    newest month (SMMT's own year-to-date marque table and top 10 — exact,
    unlike a sum of monthly top-10 lists); single months come from the
    month store, which the fetcher fills one data page at a time.
    Returns (top, updated store)."""
    t = market_tables(page)
    fuel, mm, my = t.get("fuel"), t.get("marque_month"), t.get("marque_ytd")
    if not fuel or not mm or not my or not fuel.get("ytd"):
        raise RuntimeError("data page lacks the month / year-to-date fuel or marque table")
    period = period_of(fuel)
    total, ytd_total = fuel["cur"]["TOTAL"], fuel["ytd"]["cur"]["TOTAL"]
    if mm["month"] != fuel["month"]:
        raise RuntimeError(f"marque table is for month {mm['month']}, fuel table for {period}")
    for what, tab, ref in (("month", mm, total), ("year-to-date", my, ytd_total)):
        if tab["total"] != ref:
            raise RuntimeError(f"{what} marque Grand Total {tab['total']:,} ≠ fuel table "
                               f"TOTAL {ref:,}")
    store = dict(store or {})
    b, m = units_of(mm, t.get("top_month"), total)
    # One store holds both tables: brand rows have model "", model rows a model.
    store[period] = ({**{k: n for k, n in b.items()},
                      **{k: n for k, n in m.items() if k[2]}}, total)
    months_b = {p: ({k: n for k, n in u.items() if not k[2]}, tot)
                for p, (u, tot) in store.items()}
    months_m = {}
    for p, (u, tot) in store.items():
        mu = {k: n for k, n in u.items() if k[2]}
        mu[(market_top.ALL, market_top.REST, "")] = tot - sum(mu.values())
        months_m[p] = (mu, tot)
    top = market_top.build_top_monthly(COUNTRY, SOURCE, period, months_b, TOP_UNIT)
    market_top.splice_models(top, market_top.build_top_monthly(
        COUNTRY, SOURCE, period, months_m, TOP_UNIT))
    yb, ym = units_of(my, t.get("top_ytd"), ytd_total)
    head = market_top.build_top(COUNTRY, SOURCE, period, yb, ytd_total, TOP_UNIT)
    market_top.splice_models(head, market_top.build_top(COUNTRY, SOURCE, period, ym,
                                                        ytd_total, TOP_UNIT))
    top["classes"], top["total_registrations"] = head["classes"], ytd_total
    top["window"] = {"from": f"{fuel['year']}-01", "to": period, "months": fuel["month"]}
    return top, store


def refresh_top(page: str) -> None:
    store = market_top.load_store(STORE_PATH)
    top, store = build_uk_top(page, store)
    market_top.save_store(STORE_PATH, store, COUNTRY, SOURCE)
    market_top.report(top, TOP_PATH, market_top.write_top(top, TOP_PATH))


# ── network ────────────────────────────────────────────────────────────────

def http_get(url: str, params: dict | None = None) -> str:
    import requests
    last = None
    for attempt in range(HTTP_TRIES):
        try:
            r = requests.get(url, params=params, headers=HTTP_HEADERS, timeout=(20, 90))
            if r.status_code == 200:
                return r.text
            last = f"HTTP {r.status_code}"
            if r.status_code in (400, 401, 403, 404):
                break
        except requests.RequestException as e:
            last = f"{type(e).__name__}: {e}"
        time.sleep(2 ** (attempt + 1))
    raise RuntimeError(f"GET {url} {params or ''} failed: {last}")


def shift_month(p: str, k: int) -> str:
    y, m = map(int, p.split("-"))
    m += k
    y += (m - 1) // 12
    m = (m - 1) % 12 + 1
    return f"{y:04d}-{m:02d}"


def find_release(period: str) -> tuple[str, str] | None:
    """(post URL, post HTML) of SMMT's release for `period`, or None.
    Lists the posts published from the 1st of the next month to the 1st of
    the month after, newest first, and keeps the one whose single-month fuel
    table is for `period`. SMMT posts 10-25 items a month, so one page of
    100 (the API's maximum) covers the window."""
    after, before = shift_month(period, 1), shift_month(period, 2)
    posts = json.loads(http_get(POSTS_API, {"after": f"{after}-01T00:00:00",
                                            "before": f"{before}-01T00:00:00",
                                            "per_page": 100,
                                            "_fields": "id,date,link,content"}))
    hits = []
    for p in posts:
        body = (p.get("content") or {}).get("rendered") or ""
        if "BEV" not in body:
            continue
        try:
            f = month_table(body, hint=period)
        except RuntimeError as e:
            # A fuel-shaped table that does not parse is schema drift, not
            # "someone else's post" — surface it.
            raise RuntimeError(f"{p.get('link')}: {e}") from e
        if f and period_of(f) == period:
            hits.append((f["cur"]["TOTAL"], p.get("date", ""), p["link"], body))
    if not hits:
        return None
    # Should a van (LCV) release ever carry the same table, the car market is
    # always the larger one; a re-issued car release has the same TOTAL, and
    # then the newest post wins.
    hits.sort(reverse=True)
    for _, _, link, _ in hits[1:]:
        print(f"  also matched {period}, ignored: {link}")
    return hits[0][2], hits[0][3]


def is_preliminary(page: str) -> bool:
    """True if the release / data page carries SMMT's preliminary caption."""
    return bool(PRELIM_RE.search(" ".join(page.split())))


def is_provisional(row: dict[str, str] | None) -> bool:
    """A CSV row this fetcher wrote from preliminary figures."""
    return bool(row and row.get("source") == SOURCE
                and (row.get("notes") or "").startswith("provisional:"))


# ── CSV line-level upsert (invariant 2) ────────────────────────────────────

def render_line(period: str, counts: dict[str, int], notes: str = "") -> str:
    buf = io.StringIO()
    csv.writer(buf, lineterminator="").writerow(
        [period, "monthly", VARIANT, SOURCE]
        + [str(counts[k]) for k in FUELS + ["TOTAL"]] + [notes])
    return buf.getvalue()


def read_csv_lines(path: Path) -> tuple[str, list[str]]:
    if not path.exists():
        return ",".join(CSV_COLUMNS), []
    lines = path.read_text(encoding="utf-8").splitlines()
    return (lines[0], lines[1:]) if lines else (",".join(CSV_COLUMNS), [])


def line_key(line: str) -> tuple[str, str]:
    f = next(csv.reader([line]))
    return f[0], f[2]


def existing_rows(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    with open(path, newline="", encoding="utf-8") as f:
        return {r["period"]: r for r in csv.DictReader(f)
                if (r.get("variant") or "Whole") == VARIANT}


def upsert_lines(path: Path, updates: dict[str, str], force: bool,
                 replace: frozenset[str] = frozenset()) -> dict[str, int]:
    """Insert the given periods' lines; an existing line is replaced only with
    --force or when its period is in `replace` (a provisional row). Every
    other line is written back byte-for-byte."""
    header, lines = read_csv_lines(path)
    if header.split(",") != CSV_COLUMNS:
        raise SystemExit(f"{path}: unexpected header {header!r}")
    stats = {"added": 0, "updated": 0, "unchanged": 0, "skipped": 0}
    index = {line_key(l): i for i, l in enumerate(lines)}
    for period, new in sorted(updates.items()):
        key = (period, VARIANT)
        if key not in index:
            lines.append(new)
            stats["added"] += 1
        elif lines[index[key]] == new:
            stats["unchanged"] += 1
        elif force or period in replace:
            lines[index[key]] = new
            stats["updated"] += 1
        else:
            stats["skipped"] += 1
    if stats["added"]:
        lines.sort(key=line_key)
    if stats["added"] or stats["updated"]:
        path.write_text("\n".join([header] + lines) + "\n", encoding="utf-8")
    return stats


def row_counts(row: dict[str, str]) -> dict[str, int]:
    return {k: int(float(row[k])) if row.get(k) not in (None, "") else 0
            for k in FUELS + ["TOTAL"]}


def compare(counts: dict[str, int], row: dict[str, str] | None) -> str:
    """'' if identical, else a one-line description of the differences."""
    if row is None:
        return "not in the CSV"
    old = row_counts(row)
    diffs = [f"{k} {old[k]:,}→{counts[k]:,}" for k in FUELS + ["TOTAL"] if old[k] != counts[k]]
    return ", ".join(diffs)


# ── checks against the committed history ───────────────────────────────────

def year_ago_check(f: dict, have: dict[str, dict]) -> tuple[str, float | None]:
    """The release's restated year-ago column vs the CSV's row for that month.
    Information only: the CSV keeps the figures as first published."""
    p = f"{f['prev_year']}-{f['month']:02d}"
    if p not in have:
        return f"{p}: not in the CSV", None
    restated = to_counts(f["prev"])
    diff = compare(restated, have[p])
    t_old = row_counts(have[p])["TOTAL"]
    dev = (restated["TOTAL"] - t_old) / t_old if t_old else None
    return (f"{p}: identical" if not diff else f"{p} restated: {diff}"), dev


def ytd_check(f: dict, have: dict[str, dict]) -> tuple[str, float | None]:
    """Year-to-date column minus the CSV's January..previous month must give
    this month again (up to SMMT's restatements of earlier months)."""
    y = f.get("ytd")
    if not y or f["month"] == 1:
        return "no year-to-date table" if not y else "January: YTD = month", None
    earlier = [f"{f['year']}-{m:02d}" for m in range(1, f["month"])]
    if any(p not in have for p in earlier):
        return "CSV lacks earlier months of the year — skipped", None
    implied = y["cur"]["TOTAL"] - sum(row_counts(have[p])["TOTAL"] for p in earlier)
    got = f["cur"]["TOTAL"]
    dev = (implied - got) / got if got else None
    per_fuel = []
    for k in ("BEV", "PHEV", "HEV", "PETROL", "DIESEL"):
        imp = y["cur"].get(k, 0) - sum(row_counts(have[p])[k] for p in earlier)
        if imp != f["cur"].get(k, 0):
            per_fuel.append(f"{k} {imp:,} vs {f['cur'].get(k, 0):,}")
    msg = (f"YTD {y['cur']['TOTAL']:,} − CSV Jan..{earlier[-1][-2:]} = {implied:,} "
           f"vs month {got:,} ({dev:+.2%})")
    if per_fuel:
        msg += "; " + ", ".join(per_fuel)
    return msg, dev


def plausibility(period: str, total: int, have: dict[str, dict]) -> float | None:
    """TOTAL / same month a year earlier (UK registrations are strongly
    seasonal — March and September plate months — so this beats a median)."""
    p = shift_month(period, -12)
    if p not in have:
        return None
    old = row_counts(have[p])["TOTAL"]
    return total / old if old else None


# ── main ───────────────────────────────────────────────────────────────────

def default_period(today: date) -> str:
    return shift_month(f"{today.year:04d}-{today.month:02d}", -1)


def summary_table(period: str, counts: dict[str, int], url: str) -> str:
    total = counts["TOTAL"]
    lines = [f"### UK {period} — SMMT", "", f"Release: {url}", "",
             "| column | units | share |", "|---|---:|---:|"]
    for k in FUELS + ["TOTAL"]:
        lines.append(f"| {k} | {counts[k]:,} | {100 * counts[k] / total:.1f}% |")
    return "\n".join(lines)


def process(period: str, url: str, page: str, have: dict, force: bool,
            report: list[str]) -> tuple[str, dict]:
    """Parse + validate one release. Returns (line, counts) or raises."""
    f = month_table(page, hint=period)
    if not f:
        raise RuntimeError(f"{url}: no single-month fuel table")
    if period_of(f) != period:
        raise RuntimeError(f"{url}: fuel table is for {period_of(f)}, not {period}")
    problems = validate(f)
    if problems:
        raise RuntimeError(f"{period}: " + "; ".join(problems))
    counts = to_counts(f["cur"])
    report.append(summary_table(period, counts, url))
    if f.get("month_from"):
        report.append(f"- the table header names no month; {period} taken from the "
                      "publication window (year column agrees)")
    prelim = is_preliminary(page)
    if prelim:
        report.append("- SMMT marks these figures as **preliminary** — stored as a "
                      "provisional row, replaced once the final figures are out")
    msg, dev = year_ago_check(f, have)
    flag = " ⚠️" if dev is not None and abs(dev) > YEAR_AGO_WARN else ""
    report.append(f"- year-ago column: {msg}{flag}")
    msg, dev = ytd_check(f, have)
    report.append(f"- year-to-date check: {msg}")
    if dev is not None and abs(dev) > YTD_ABORT and not force:
        raise RuntimeError(f"{period}: year-to-date check off by {dev:+.1%} (> "
                           f"{YTD_ABORT:.0%}) — wrong month, or SMMT revised earlier "
                           "months heavily; check by hand, then --force")
    if dev is not None and abs(dev) > YTD_WARN:
        print(f"::warning title=UK year-to-date check::{msg}")
    ratio = plausibility(period, counts["TOTAL"], have)
    if ratio is not None:
        report.append(f"- TOTAL vs same month a year earlier: ×{ratio:.2f}")
        if not PLAUSIBLE[0] <= ratio <= PLAUSIBLE[1] and not force:
            raise RuntimeError(f"{period}: TOTAL {counts['TOTAL']:,} is ×{ratio:.2f} the "
                               "same month a year earlier — implausible; check, then --force")
    note = url if url.startswith("http") else ""
    if prelim:
        note = PROVISIONAL + note
    return render_line(period, counts, note), counts


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--period")
    ap.add_argument("--backfill", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--from-html")
    ap.add_argument("--csv", default=str(CSV_PATH))
    ap.add_argument("--no-top", action="store_true", help="skip market/uk_top.json")
    ap.add_argument("--github-output", default=os.environ.get("GITHUB_OUTPUT"))
    ap.add_argument("--summary", default=os.environ.get("GITHUB_STEP_SUMMARY"))
    args = ap.parse_args(argv)

    csv_path = Path(args.csv)
    have = existing_rows(csv_path)
    today = datetime.now(timezone.utc).date()
    report: list[str] = []
    updates: dict[str, str] = {}

    if args.from_html:
        page = Path(args.from_html).read_text(encoding="utf-8")
        f = month_table(page, hint=args.period)
        if not f:
            raise SystemExit(f"{args.from_html}: no single-month fuel table")
        period = period_of(f)
        line, counts = process(period, args.from_html, page, have, True, report)
        diff = compare(counts, have.get(period))
        report.append(f"- vs CSV: {diff or 'identical'}")
        print("\n".join(report))
        print(line)
        return 0

    if args.backfill:
        periods, p = [], FIRST_RELEASE
        while p <= default_period(today):
            periods.append(p)
            p = shift_month(p, 1)
    else:
        periods = [args.period or default_period(today)]
    target = periods[-1]

    top_current = market_top.top_as_of(TOP_PATH) == target
    cur_row = have.get(target)
    if (not args.force and not args.backfill and cur_row and cur_row.get("source") == SOURCE
            and not is_provisional(cur_row) and (top_current or args.no_top)):
        print(f"{target} already in {csv_path.name} from {SOURCE} and market/uk_top.json "
              "is current — nothing to do.")
        return emit(args, set())

    data_page: list[str] = []

    def get_data_page() -> str:
        if not data_page:
            data_page.append(http_get(DATA_PAGE))
        return data_page[0]

    replace: set[str] = set()
    for period in periods:
        found = find_release(period)
        if found is None and period == target:
            # Fallback: the vehicle-data page shows the newest month too.
            try:
                f = month_table(get_data_page())
                if f and period_of(f) == period:
                    found = (DATA_PAGE, get_data_page())
            except RuntimeError as e:
                print(f"::warning title=UK data page unreadable::{e}")
        if found is None:
            due = date(*map(int, shift_month(period, 1).split("-")), LATE_DAY)
            msg = f"{period}: no SMMT release found yet"
            if today > due and period == target:
                print(f"::error title=UK release not found::{msg} — SMMT normally "
                      "publishes in the first week; see 50-source-uk.md §8")
                return 1
            print(msg)
            report.append(f"- {msg}")
            continue
        url, page = found
        line, counts = process(period, url, page, have, args.force, report)
        diff = compare(counts, have.get(period))
        old = have.get(period)
        new_prov = next(csv.reader([line]))[-1].startswith("provisional:")
        if is_provisional(old) and not new_prov:
            replace.add(period)
            report.append(f"- {period}: final figures replace the provisional row"
                          + (f" ({diff})" if diff else " (numbers unchanged)"))
        elif is_provisional(old) and diff:
            replace.add(period)
            report.append(f"- {period}: SMMT revised its preliminary figures: {diff}")
        elif period in have and diff:
            report.append(f"- {period} differs from the CSV ({old.get('source')}): "
                          f"{diff} — kept unless --force")
        elif period in have:
            report.append(f"- {period}: identical to the CSV")
        if period not in have or args.force or period in replace:
            updates[period] = line

    changed: set[str] = set()
    if updates and not args.dry_run:
        stats = upsert_lines(csv_path, updates, args.force, frozenset(replace))
        print(f"{csv_path.name}: {stats}")
        if stats["added"] or stats["updated"]:
            changed.add(VARIANT)
    elif updates:
        print("dry run — would write:\n" + "\n".join(updates.values()))

    if not args.no_top and not args.dry_run:
        market_top.guarded(lambda: refresh_top(get_data_page()))

    text = "\n".join(report)
    print(text)
    if args.summary:
        with open(args.summary, "a", encoding="utf-8") as fh:
            fh.write(text + "\n")
    return emit(args, changed)


def emit(args, changed: set[str]) -> int:
    if args.github_output:
        with open(args.github_output, "a", encoding="utf-8") as f:
            f.write(f"changed={'true' if changed else 'false'}\n")
            f.write(f"changed_variants={json.dumps(sorted(changed))}\n")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except RuntimeError as e:
        print(f"::error title=UK fetch failed::{e}")
        sys.exit(1)
