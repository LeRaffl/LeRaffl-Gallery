#!/usr/bin/env python3
"""
Fetch Netherlands vehicle registration data from duurzamemobiliteit.databank.nl
and upsert per-variant CSVs under data/.

Usage
-----
    python scripts/fetch_netherlands.py [--variant {whole,used,hdv,all}] [--force]

Output files
------------
    data/Netherlands.csv       <- variant=Whole (Personenauto Nieuw)
    data/Netherlands_Used.csv  <- variant=Used  (Personenauto Occasion import)
    data/Netherlands_HDV.csv   <- variant=HDV   (Zware bedrijfsvoertuigen Nieuw)

The script is invoked by .github/workflows/fetch-netherlands.yml on a daily
cron (1st-15th, 06:30 UTC) and via manual workflow_dispatch. When it produces
changes, the workflow commits each touched CSV and triggers render-country.yml
for the corresponding variant.

Full pipeline context — Swing endpoint flow, variant rationale, HEV gap,
FCEV folding, schedule, fragility, maintenance recipes — lives in
docs/architecture/10-source-netherlands.md. Read that before changing the
TEMPLATES constant, the parser, or the column mapping.

Brief recap (so the script reads on its own):

* duurzamemobiliteit.databank.nl is RDW data served by Swing (ABF Research).
  No documented public API. We open pre-saved workspace permalinks the
  maintainer set up in the Swing UI, the way the viewer's own SPA does
  (since 2026-09; before that GetTableStart returned the pivot):
    1. GET /viewer?workspace_guid=<TEMPLATE>  -> anonymous session; the page
       defines Globals.workspaceId, the session's own workspace.
    2. POST /viewer/api/workspace/<ws>/presentationfromurl
       {"entries": {"workspace_guid": <TEMPLATE>}}  -> {presentationID, isValid}
    3. GET /viewer/api/workspace/<ws>/presentation/<id>  -> {title, table:
       {columnHeaderRows, rows: [{cells: [{text}]}]}} — the whole table.
  swing_table_to_legacy() maps that onto the headRows/headCols/rowData shape
  the parsers were written for. The POST needs the POST-capable relay
  (worker/deno-relay.ts, 2026-09 version). --dry-run compares with the CSVs,
  --probe-swing / --probe-open diagnose the portal (docs 10, section 11).
* Dutch label -> canonical column:
      BEV -> BEV;  PHEV -> PHEV;  Benzine -> PETROL;  Diesel -> DIESEL;
      FCEV + Overig -> OTHERS;  HEV column is always blank (RDW doesn't
      split it; full hybrids fold into Benzine/Diesel upstream).
* Dutch locale: "." is thousands separator (6.863 == 6863). Empty cell == 0.
* Table orientation varies by view. Whole/HDV return periods-in-rows with one
  column per fuel. Used returns periods-in-rows too, but with fuels on the
  OUTER column level, each spanning two sub-columns ("Occasion import > 90 dgn"
  / "<= 90 dgn") which the parser sums. (An older Used template returned
  fuels-in-rows; _parse_fuels_in_rows is kept for that shape.) The parser
  picks the branch from the headRows labels and locates the fuel header level
  by matching NL_FUELS.

Top brands / models (market/netherlands_top.json)
-------------------------------------------------
The Swing pivots carry no brand or model. The same register is also published
record by record as RDW open data (opendata.rdw.nl, Socrata, no key), so every
run also keeps the trailing-twelve-month top brands and models per electrified
class (Whole only; BEV and PHEV, the classes the CSV splits) current, in the
country-neutral schema of scripts/market_top.py; the source page renders it.

* Scope = the Swing "Personenauto Nieuw" instroom, rebuilt from the records:
  voertuigsoort Personenauto, first registration in NL in the month AND first
  admission (datum eerste toelating) in the same month, export_indicator Nee.
  That lands within about 1-3 % of the CSV per month (RDW is a live register,
  Swing a snapshot), so each month is checked against data/Netherlands.csv and
  a window deviating by more than 10 % aborts the refresh (market_top.check_scope;
  guarded: a warning, the data commit is unaffected).
* Class = fuel table 8ys7-d773 keyed by kenteken: BEV = Elektriciteit only;
  PHEV = a row with klasse_hybride_elektrisch_voertuig OVC-HEV. Full hybrids
  stay unsplit like in the CSV; fuel-cell cars count as OTHERS there and are
  not ranked.
* The fuel table cannot be joined server-side, so the fuels of a month are read
  in batches of FUEL_BATCH plates (about one minute per month). Months are kept
  in market/netherlands_months.json (the month store of market_top.py), so a
  normal run reads only the newest month; the very first run reads twelve.
* --no-top skips all of it.
"""
import argparse
import base64
import collections
import csv
import json
import os
import re
import sys
import time
from datetime import date
from pathlib import Path
from urllib.parse import quote as urlquote, urljoin

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

sys.path.insert(0, str(Path(__file__).resolve().parent))
import market_top  # noqa: E402

BASE = "https://duurzamemobiliteit.databank.nl"

# Saved Swing workspace templates (configured in the Swing UI via Share Permalink).
# Each is pre-set to monthly granularity and the relevant Voertuigsoort /
# Aanvoertype dimension picks. The period dimension uses Swing's dynamic
# "last N months" option (N=36) rather than a fixed month list, so the views
# auto-include new months as RDW publishes them — see docs/architecture/
# 10-source-netherlands.md §3. (The old templates had a *static* month list
# that silently capped at 2026-04; re-saved 2026-07 with the rolling window.)
# The 36-month window always overlaps the CSV's existing tail, and upsert never
# deletes rows, so the full 2018-→ history is preserved.
TEMPLATES = {
    "Whole": "29fcfefb-b82b-47cb-a601-b7c31ebd2901",  # Personenauto Nieuw
    "Used":  "7f40022a-d4cf-4030-abaf-adf5edf412b3",  # Personenauto Occasion import (>90 + <=90)
    "HDV":   "3ca8fa6f-52a6-4b29-8f43-7bae5200c74c",  # Zware bedrijfsvoertuigen Nieuw
}

# Each variant writes to its own CSV. Whole keeps the canonical filename
# (no suffix) — that's the convention for the country's "default" slice and
# what the gallery's world-map + aggregate computations pick up.
CSV_PATHS = {
    "Whole": "data/Netherlands.csv",
    "Used":  "data/Netherlands_Used.csv",
    "HDV":   "data/Netherlands_HDV.csv",
}

# Short, stable source string for the CSV (matches the pattern other countries
# use: pxdata.stat.fi, dpshtrr.al, etc.). The variant-specific template GUID
# goes in the per-row `notes` column for debugging.
SOURCE = "duurzamemobiliteit.databank.nl (RDW)"

HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/18.5 Safari/605.1.15"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "nl-NL,nl;q=0.9,en;q=0.8",
}

CSV_COLUMNS = [
    "period", "time_interval", "variant", "source",
    "BEV", "PHEV", "HEV", "PETROL", "DIESEL", "FLEXFUEL",
    "OTHERS", "TOTAL", "notes",
]

# Fuel label set used to detect axis orientation in the JSON response.
NL_FUELS = {"BEV", "FCEV", "PHEV", "Benzine", "Diesel", "Overig"}

NL_MONTHS = {
    "januari": 1, "februari": 2, "maart": 3, "april": 4, "mei": 5, "juni": 6,
    "juli": 7, "augustus": 8, "september": 9, "oktober": 10, "november": 11,
    "december": 12,
}

def swing_token(html: str) -> str:
    """The antiforgery token the SPA sends as the __RequestVerificationToken
    header on its POSTs (document.querySelector("input[name=__RequestVerificationToken]"))."""
    m = re.search(r"<input[^>]*name=[\"']?__RequestVerificationToken[\"']?[^>]*>", html)
    v = re.search(r"value=[\"']([^\"']*)[\"']", m.group(0)) if m else None
    return v.group(1) if v else ""


DATE_RE = re.compile(r"(\d{1,2})\s+(\w+)\s+(\d{4})")

# Relay redirect chain: followed client-side so the cookie jar in
# session.relay_cookies travels with it (see _get / _relay_once).
REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
MAX_RELAY_REDIRECTS = 10


def _get(session: requests.Session, url: str,
         headers: dict | None = None, **kwargs) -> requests.Response:
    """session.get that routes through the fetch relay when relay_base is set.

    If ``session.relay_base`` is set (monkey-patched in main() from
    ``NL_FETCH_RELAY``), every request is forwarded via the relay so the
    runner's Azure IP is not the one hitting duurzamemobiliteit.databank.nl.
    Cookies from upstream Set-Cookie headers are harvested into
    ``session.relay_cookies`` and re-forwarded on subsequent requests via
    X-Fwd-Cookie.

    For the Netherlands the relay must be the **Deno Deploy** one
    (``worker/deno-relay.ts``) — duurzamemobiliteit 403s Cloudflare egress,
    so the Austria Cloudflare Worker relay this protocol was first written
    for does not work here. The wire format is identical either way.
    """
    relay_base = getattr(session, "relay_base", None)
    merged_headers = {**HTTP_HEADERS, **(headers or {})}

    if not relay_base:
        return session.get(url, headers=merged_headers, **kwargs)

    target = url
    for hop in range(MAX_RELAY_REDIRECTS + 1):
        resp = _relay_once(session, target, merged_headers, **kwargs)
        if resp.status_code not in REDIRECT_STATUSES:
            return resp
        # No X-Upstream-Location means the deployed relay predates manual-
        # redirect support and followed the chain itself; hand the response
        # back rather than guessing where it wanted to go.
        location = resp.headers.get("X-Upstream-Location")
        if not location:
            return resp
        target = urljoin(target, location)
        print(f"[net] relay redirect {resp.status_code} (hop {hop + 1}) -> {target}")

    raise RuntimeError(
        f"[net] more than {MAX_RELAY_REDIRECTS} relay redirects starting at {url} — "
        f"upstream is looping; last target {target}"
    )


# Request headers a POST needs that the relay forwards under an X-Fwd- name
# (see worker/deno-relay.ts).
RELAY_EXTRA_HEADERS = {
    "Content-Type": "X-Fwd-Content-Type",
    "Accept": "X-Fwd-Accept",
    "X-Page-Type": "X-Fwd-Page-Type",
    "__RequestVerificationToken": "X-Fwd-Antiforgery",
    "Origin": "X-Fwd-Origin",
}


def _post_json(session: requests.Session, url: str, payload: dict,
               headers: dict | None = None, **kwargs) -> requests.Response:
    """POST a JSON body — directly, or through the relay (which must be the
    2026-09 version of worker/deno-relay.ts: earlier ones answer 404 to POST)."""
    body = json.dumps(payload).encode("utf-8")
    merged = {**HTTP_HEADERS, "Accept": "application/json, text/plain, */*",
              "Content-Type": "application/json", **(headers or {})}
    if not getattr(session, "relay_base", None):
        return session.post(url, headers=merged, data=body, **kwargs)
    return _relay_once(session, url, merged, method="POST", body=body, **kwargs)


def _relay_once(session: requests.Session, url: str, merged_headers: dict,
                method: str = "GET", body: bytes | None = None,
                **kwargs) -> requests.Response:
    """One relay round-trip, harvesting upstream Set-Cookie into the jar."""
    relay_base = session.relay_base  # type: ignore[attr-defined]
    relay_token = getattr(session, "relay_token", "")
    relay_cookies: dict = getattr(session, "relay_cookies", {})

    fwd = {
        "X-Relay-Token":          relay_token,
        "X-Fwd-User-Agent":       HTTP_HEADERS["User-Agent"],
        "X-Fwd-Accept-Language":  HTTP_HEADERS["Accept-Language"],
        # Own the redirect chain here: the relay's own fetch has no cookie jar,
        # so a session-cookie redirect loop on databank.nl exhausted its 20-hop
        # limit and came back as a 502. See worker/deno-relay.ts.
        "X-Relay-Redirect":       "manual",
    }
    if relay_cookies:
        fwd["X-Fwd-Cookie"] = "; ".join(f"{k}={v}" for k, v in relay_cookies.items())
    if merged_headers.get("Referer"):
        fwd["X-Fwd-Referer"] = merged_headers["Referer"]

    relay_url = relay_base + urlquote(url, safe="")
    if method == "POST":
        for name, wire in RELAY_EXTRA_HEADERS.items():
            if merged_headers.get(name):
                fwd[wire] = merged_headers[name]
        resp = session.post(relay_url, headers=fwd, data=body, **kwargs)
    else:
        resp = session.get(relay_url, headers=fwd, **kwargs)

    # Harvest upstream Set-Cookie into the manual cookie jar. The Deno relay
    # base64-encodes the \n-joined blob (X-Upstream-Set-Cookie-B64) because
    # header values can't carry raw newlines and databank.nl returns 6 cookies.
    # Fall back to the plain header for the CF worker / single-cookie hosts.
    b64 = resp.headers.get("X-Upstream-Set-Cookie-B64", "")
    if b64:
        cookie_block = base64.b64decode(b64).decode("utf-8", "replace")
    else:
        cookie_block = resp.headers.get("X-Upstream-Set-Cookie", "")
    for raw in cookie_block.split("\n"):
        raw = raw.strip()
        if not raw:
            continue
        kv = raw.split(";")[0].strip()
        if "=" in kv:
            name, _, value = kv.partition("=")
            relay_cookies[name.strip()] = value.strip()

    return resp


def parse_nl_number(s: str) -> float:
    """'6.863' -> 6863.0; '&nbsp;' / '' -> 0.0. NL uses '.' as thousands sep."""
    if not s or s == "&nbsp;":
        return 0.0
    return float(s.replace(".", "").replace(",", "."))


def parse_nl_period(label: str) -> str:
    """'31 januari 2018' -> '2018-01'."""
    m = DATE_RE.search(label)
    if not m:
        raise ValueError(f"Unrecognised period label: {label!r}")
    _day, month_nl, year = m.groups()
    month = NL_MONTHS.get(month_nl.lower())
    if not month:
        raise ValueError(f"Unrecognised Dutch month: {month_nl!r}")
    return f"{year}-{month:02d}"


def swing_table_to_legacy(presentation: dict) -> dict:
    """Map the SPA's presentation JSON ({title, table: {columnHeaderRows,
    rows, headColCount, colCount, …}}) onto the shape the parsers below were
    written for ({caption, headRows, headCols, rowData, totalRows, totalCols}) —
    the old GetTableStart response — so Whole, Used and HDV keep one parse path.

    * headCols: one list per header level, one {"d": label} per value column.
      The SPA already emits a blank continuation cell (type 4) after a cell
      with colSpan 2 (Used: each fuel over "> 90 dgn" / "<= 90 dgn"), which is
      exactly the old span-continuation convention; should a payload ever leave
      them out, they are added from colSpan.
    * headRows / rowData: the first headColCount cells of each row are its
      header, the rest its values. colCount counts the value columns only, and
      every header level and row must carry exactly that many — else the
      labels would slide, which is a hard error."""
    t = presentation["table"]
    hc = t.get("headColCount", 1)
    ncols = t.get("colCount", 0)          # value columns only (Whole 6, Used 12)
    head_cols = []
    for level in t.get("columnHeaderRows") or []:
        cells = [{"d": c.get("text", "")} for c in level["cells"][hc:]]
        if len(cells) != ncols:                   # continuation cells left out: expand
            cells = []
            for c in level["cells"][hc:]:
                cells.append({"d": c.get("text", "")})
                cells.extend({"d": ""} for _ in range(int(c.get("colSpan", 1)) - 1))
        if len(cells) != ncols:
            raise RuntimeError(f"Swing header level has {len(cells)} columns, the table "
                               f"declares {ncols} — the payload shape changed (--probe-open)")
        head_cols.append(cells)
    rows = t.get("rows") or []
    for i, r in enumerate(rows):
        if len(r["cells"]) - hc != ncols:
            raise RuntimeError(f"Swing row {i} has {len(r['cells']) - hc} value cells, the "
                               f"table declares {ncols} — the payload shape changed")
    return {
        "caption": presentation.get("title", ""),
        "totalRows": len(rows),
        "totalCols": ncols,
        "headRows": [[{"d": c.get("text", "")} for c in r["cells"][:hc]] for r in rows],
        "headCols": head_cols,
        "rowData": [[{"d": c.get("text", "")} for c in r["cells"][hc:]] for r in rows],
    }


def fetch_table(variant: str, session: requests.Session) -> dict:
    """The variant's saved Swing view as {caption, headRows, headCols, rowData}
    (see open_presentation for the flow, swing_table_to_legacy for the shape).
    The presentation carries the whole table — no paging."""
    presentation = open_presentation(session, variant)
    data = swing_table_to_legacy(presentation)
    print(f"[{variant}] {presentation.get('title')!r}: {data['totalRows']} rows x "
          f"{data['totalCols']} cols, period {presentation.get('info', {}).get('period')}")
    return data


def parse_table(data: dict, variant: str) -> dict[str, dict[str, float]]:
    """
    Parse the table (swing_table_to_legacy shape) into {period: {fuel: value}}.

    Two layouts are possible:
      A. Periods in headRows, fuels in headCols   (Whole, HDV, Used)
      B. Fuels in headRows, periods in headCols   (legacy Used template)

    In layout A, Used carries the fuel names on the OUTER headCols level with
    each fuel spanning two sub-columns ("> 90 dgn" / "<= 90 dgn") that get
    summed; _parse_periods_in_rows handles both the one-column-per-fuel and the
    sub-column shapes. Layout B is the older fuels-in-rows Used template.
    """
    row_first = data["headRows"][0][0]["d"]
    fuels_in_rows = row_first in NL_FUELS

    if fuels_in_rows:
        return _parse_fuels_in_rows(data, variant)
    return _parse_periods_in_rows(data, variant)


def _parse_periods_in_rows(data: dict, variant: str) -> dict[str, dict[str, float]]:
    """Layout A: periods are rows, fuels are columns.

    Handles two column shapes with one code path:
      * Whole/HDV — one column per fuel (single-level, or fuels at the
        innermost level).
      * Used — fuels on the OUTER header level, each spanning two sub-columns
        ("Occasion import > 90 dgn" / "<= 90 dgn") which we sum. (Swing emits
        this shape after the workspace was re-saved with the rolling window.)

    We locate whichever headCols level actually carries fuel names, propagate
    each fuel label across the sub-columns it spans (blank cell = span
    continuation), then sum all columns belonging to the same fuel per period.
    """
    # Find the header level whose labels include recognisable fuel names.
    fuel_level: list[str] | None = None
    for level in data["headCols"]:
        labels = [c.get("d", "") for c in level]
        if any(lbl in NL_FUELS for lbl in labels):
            fuel_level = labels
            break
    if fuel_level is None:
        # No fuel header found → let the caller's 0-rows diagnostic dump fire.
        return {}

    # Propagate the fuel label across every column it spans.
    fuel_per_col: list[str | None] = []
    current: str | None = None
    for lbl in fuel_level:
        if lbl:
            current = lbl
        fuel_per_col.append(current)

    period_labels = [r[0]["d"] for r in data["headRows"]]
    out: dict[str, dict[str, float]] = {}
    for i, period_label in enumerate(period_labels):
        period = parse_nl_period(period_label)
        row_cells = data["rowData"][i]
        acc: dict[str, float] = {}
        for j, fuel in enumerate(fuel_per_col):
            if fuel is None or j >= len(row_cells):
                continue
            acc[fuel] = acc.get(fuel, 0.0) + parse_nl_number(row_cells[j]["d"])
        out[period] = acc
    return out


def _parse_fuels_in_rows(data: dict, variant: str) -> dict[str, dict[str, float]]:
    """Layout B: fuels are rows, periods are columns. Used Imports has 2-level
    column header where each period covers two sub-columns we sum together."""
    fuel_labels = [r[0]["d"] for r in data["headRows"]]
    period_level = data["headCols"][0]  # outer level: period labels (with blanks for spans)

    # Propagate period labels across the sub-columns they span.
    period_per_col: list[str] = []
    current: str | None = None
    for cell in period_level:
        label = cell.get("d", "")
        if label:
            current = label
        if current is None:
            raise RuntimeError(f"[{variant}] period header starts with empty cell")
        period_per_col.append(current)

    out: dict[str, dict[str, float]] = {}
    for fuel_idx, fuel in enumerate(fuel_labels):
        for col_idx, period_label in enumerate(period_per_col):
            period = parse_nl_period(period_label)
            value = parse_nl_number(data["rowData"][fuel_idx][col_idx]["d"])
            out.setdefault(period, {}).setdefault(fuel, 0.0)
            out[period][fuel] += value
    return out


def to_csv_rows(parsed: dict[str, dict[str, float]], variant: str) -> dict[str, dict]:
    """Map parsed {period: {NL_fuel: value}} to canonical CSV row dicts."""
    out: dict[str, dict] = {}
    for period, fuels in parsed.items():
        bev    = fuels.get("BEV", 0.0)
        phev   = fuels.get("PHEV", 0.0)
        petrol = fuels.get("Benzine", 0.0)
        diesel = fuels.get("Diesel", 0.0)
        others = fuels.get("FCEV", 0.0) + fuels.get("Overig", 0.0)
        total  = bev + phev + petrol + diesel + others

        # Skip future months that Swing pre-fills with zeros (every fuel = 0)
        if total == 0.0:
            continue

        out[period] = {
            "period": period,
            "time_interval": "monthly",
            "variant": variant,
            "source": SOURCE,
            "BEV": bev,
            "PHEV": phev,
            "HEV": "",          # Netherlands does not split HEV
            "PETROL": petrol,
            "DIESEL": diesel,
            "FLEXFUEL": "",
            "OTHERS": others,
            "TOTAL": total,
            "notes": f"workspace_guid={TEMPLATES[variant]}",
        }
    return out


def dry_run_report(csv_path: str, rows: dict[str, dict], variant: str) -> None:
    """--dry-run: how the freshly parsed rows relate to what the CSV already
    holds — new months, and every cell that moved (Swing restates recent
    months; a real historic difference would show up here)."""
    cols = ["BEV", "PHEV", "PETROL", "DIESEL", "OTHERS", "TOTAL"]
    have: dict[str, dict] = {}
    if os.path.exists(csv_path):
        with open(csv_path, newline="", encoding="utf-8") as f:
            have = {r["period"]: r for r in csv.DictReader(f)
                    if (r.get("variant") or variant) == variant}
    same = 0
    for period in sorted(rows):
        new, old = rows[period], have.get(period)
        if old is None:
            print(f"[{variant}] NEW     {period}: "
                  + " ".join(f"{c}={new[c]:.0f}" for c in cols))
            continue
        moved = [f"{c} {float(old[c] or 0):.0f}->{new[c]:.0f}" for c in cols
                 if float(old[c] or 0) != float(new[c] or 0)]
        if moved:
            print(f"[{variant}] CHANGED {period}: " + ", ".join(moved))
        else:
            same += 1
    gone = sorted(set(have) - set(rows))
    print(f"[{variant}] dry run: {same} months identical to {csv_path}, "
          f"{sum(1 for p_ in rows if p_ not in have)} new, "
          f"{sum(1 for p_ in rows if p_ in have) - same} changed"
          + (f"; {len(gone)} CSV months not in the view ({gone[0]}..{gone[-1]})" if gone else ""))


def upsert_csv(csv_path: str, new_rows: dict[tuple[str, str], dict]) -> tuple[int, int]:
    """Upsert by (period, variant). Returns (added, updated). Warns on >50% delta."""
    existing: dict[tuple[str, str], dict] = {}
    if os.path.exists(csv_path):
        with open(csv_path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                existing[(row["period"], row["variant"])] = row

    added = updated = 0
    for key, new_row in sorted(new_rows.items()):
        if key not in existing:
            existing[key] = new_row
            added += 1
            print(f"  + {key[1]} {key[0]}")
        else:
            old = existing[key]
            for col in ["BEV", "PHEV", "PETROL", "DIESEL", "OTHERS"]:
                old_val = float(old.get(col) or 0)
                new_val = float(new_row[col] or 0)
                if old_val > 100 and abs(new_val - old_val) / old_val > 0.5:
                    print(
                        f"  WARNING {key[1]} {key[0]} {col}: existing={old_val:.0f}, "
                        f"new={new_val:.0f} — diff >50%, please verify"
                    )
            existing[key] = {**old, **new_row}
            updated += 1

    Path(csv_path).parent.mkdir(parents=True, exist_ok=True)
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, lineterminator="\n")
        writer.writeheader()
        # Sort by variant then period — keeps each variant's history contiguous.
        for key in sorted(existing.keys(), key=lambda k: (k[1], k[0])):
            writer.writerow(existing[key])

    return added, updated


# ── Top brands / models (RDW open data; not used for the data CSV) ─────────

RDW_BASE = "https://opendata.rdw.nl/resource/"
RDW_VEHICLES = "m9d7-ebf2"        # Gekentekende voertuigen (one row per plate)
RDW_FUEL = "8ys7-d773"            # ... brandstof (one row per plate x fuel)
TOP_SOURCE = "RDW open data"
TOP_PATH = market_top.MARKET_DIR / "netherlands_top.json"
STORE_PATH = market_top.MARKET_DIR / "netherlands_months.json"
TOP_UNIT = ("first registrations (brand = RDW 'merk'; model = RDW "
            "'handelsbenaming' with the brand prefix, engine / power / trim "
            "codes removed — see display_model in scripts/fetch_netherlands.py)")
FUEL_BATCH = 800                  # plates per fuel query (URL limit ~ 1000)
PAGE = 50000                      # Socrata's maximum page size
RDW_TRIES = 5


def rdw_session() -> requests.Session:
    """A plain session for opendata.rdw.nl — deliberately not the Swing
    session: NL_PROXY / NL_FETCH_RELAY exist because duurzamemobiliteit
    blocks GitHub, RDW's open-data host does not."""
    s = requests.Session()
    s.headers["User-Agent"] = "LeRaffl-Gallery/1.0 (+https://github.com/LeRaffl/LeRaffl-Gallery)"
    return s


def rdw_get(session: requests.Session, resource: str, params: dict) -> list:
    """One Socrata query, retried with backoff (RDW answers an occasional 500
    under load)."""
    err = None
    for attempt in range(RDW_TRIES):
        try:
            r = session.get(f"{RDW_BASE}{resource}.json", params=params, timeout=180)
            if r.status_code == 200:
                return r.json()
            err = f"HTTP {r.status_code}"
        except requests.RequestException as e:
            err = f"{type(e).__name__}: {e}"
        time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"RDW {resource} failed after {RDW_TRIES} tries: {err}")


def next_month(period: str) -> str:
    y, m = map(int, period.split("-"))
    return f"{y + m // 12}-{m % 12 + 1:02d}"


def fetch_new_cars(session: requests.Session, period: str) -> list[dict]:
    """The plates counted as "new passenger cars registered in `period`":
    first NL registration in the month, first admission in the same month (a
    car admitted earlier is a used import), not exported since."""
    a, b = f"{period}-01", f"{next_month(period)}-01"
    where = ("voertuigsoort='Personenauto' "
             f"and datum_eerste_tenaamstelling_in_nederland_dt >= '{a}' "
             f"and datum_eerste_tenaamstelling_in_nederland_dt < '{b}' "
             f"and datum_eerste_toelating_dt >= '{a}' "
             f"and datum_eerste_toelating_dt < '{b}' "
             "and export_indicator='Nee'")
    rows: list[dict] = []
    while True:
        page = rdw_get(session, RDW_VEHICLES, {
            "$select": "kenteken,merk,handelsbenaming", "$where": where,
            "$order": "kenteken", "$limit": PAGE, "$offset": len(rows)})
        rows += page
        if len(page) < PAGE:
            return rows


def fetch_fuels(session: requests.Session, plates: list[str]) -> dict[str, list]:
    """{plate: [(fuel, hybrid class), ...]} from the fuel table. It cannot be
    joined on the server, so the plates go in as IN lists."""
    out: dict[str, list] = collections.defaultdict(list)
    for i in range(0, len(plates), FUEL_BATCH):
        inlist = ",".join(f"'{p}'" for p in plates[i:i + FUEL_BATCH])
        for r in rdw_get(session, RDW_FUEL, {
                "$select": "kenteken,brandstof_omschrijving,klasse_hybride_elektrisch_voertuig",
                "$where": f"kenteken in({inlist})", "$limit": PAGE}):
            out[r["kenteken"]].append((r.get("brandstof_omschrijving") or "",
                                       r.get("klasse_hybride_elektrisch_voertuig") or ""))
    return out


def powertrain_class(fuels: list) -> str:
    """The CSV's split: BEV = electricity as the only fuel, PHEV = an
    externally chargeable hybrid (OVC-HEV). Everything else — including the
    full hybrids the CSV leaves unsplit and fuel-cell cars (OTHERS) — is ""."""
    kinds = {k for _, k in fuels if k}
    if any(k.startswith("OVC-HEV") for k in kinds):
        return "PHEV"
    if fuels and {f for f, _ in fuels} == {"Elektriciteit"} and not kinds:
        return "BEV"
    return ""


# Display names only — the CSV never sees them. RDW's `merk` is consistent
# apart from a handful of spellings; `handelsbenaming` is the type-approval
# trade name and carries engine, power and trim ("ID.4 PRO 210KW", "IX3 50
# XDRIVE", "CLA 250+"), so several strings are one model on the road.
BRAND_ALIASES = {"DS AUTOMOBILES": "DS", "LYNK&CO": "LYNK & CO",
                 "MERCEDES BENZ": "MERCEDES-BENZ", "LAND-ROVER": "LAND ROVER",
                 "BURSTNER GMBH": "BURSTNER", "LUCID MOTORS": "LUCID"}
# Equipment / drive / body words removed from any brand's model string.
MODEL_NOISE = re.compile(
    r"\d+(?:[.,]\d+)?\s?KWH?\b|\b\d+/\d+\s?KWH\b"          # 210KW, 150 KW, 60/63 KWH
    r"|\b(?:PRO S|PRO|PURE|MAX|LR|KR|GTX|PERF\.?|PERFORMANCE|QUATTRO|SPORTBACK|"
    r"SPORTS TOURER|TOURER|AVANT|AV|SB|SUV|TOURING|CROSS COUNTRY|E-TECH ELECTRIC|"
    r"E-TECH|ELECTRIC|EV|EVO|DM-I|EM-I|PHEV|E-HYBRID\d*|HYBRID|TFSI E|TFSI|"
    r"XDRIVE\d*E?|EDRIVE\d*|SDRIVE\d*|4MATIC\+?|ALL4|WITH EQ TE|SP|URBAN)\b")
# Brands whose trade names are a family name followed by numbers / suffixes.
FIRST_TOKEN = {"BMW", "PORSCHE"}
DROP_NUMBERS = {"SKODA"}


def display_brand(merk: str) -> str:
    b = market_top.clean(merk)
    return BRAND_ALIASES.get(b, b)


def display_model(merk: str, model: str) -> str:
    """RDW trade name -> the model as buyers know it, for the ranking only."""
    brand = display_brand(merk)
    m = market_top.clean(model)
    for prefix in {market_top.clean(merk), brand}:
        m = market_top.strip_brand(prefix, m)
        if m.startswith(prefix) and m[len(prefix):len(prefix) + 1].isdigit():
            m = m[len(prefix):]                       # "MG4 ELECTRIC" -> "4 ELECTRIC"
    m = re.sub(r"\([^)]*\)", " ", m)
    if brand == "MERCEDES-BENZ":
        toks = m.split()
        keep = []
        for t in toks:
            if any(ch.isdigit() for ch in t):
                break
            keep.append(t)
        m = " ".join(keep or toks[:1])
    elif brand == "AUDI":
        toks = m.split()
        fam = toks[:2] if toks[:1] in (["RS"], ["S"]) and len(toks) > 1 else toks[:1]
        m = " ".join(fam + (["E-TRON"] if "E-TRON" in toks and "E-TRON" not in fam else []))
    elif brand == "TESLA":
        m = " ".join(m.split()[:2])
    elif brand == "LEXUS":
        m = re.sub(r"^([A-Z]{2})\d{3}.*$", r"\1", m)
    elif brand == "HYUNDAI":
        m = re.sub(r"^IONIQ ?(\d)", r"IONIQ \1", m)
    elif brand in FIRST_TOKEN:
        m = m.split(" ")[0]
    m = MODEL_NOISE.sub(" ", m)
    if brand in DROP_NUMBERS:
        m = re.sub(r"(?<!\S)\d{2,3}(?!\S)|(?<!\S)RS(?!\S)", " ", m)
    if brand == "MINI":
        m = re.sub(r"(?<!\S)(?:E|SE|JCW)(?!\S)", " ", m)
    m = " ".join(m.split())
    return m or market_top.clean(model)


def aggregate_month(session: requests.Session, period: str) -> tuple[dict, int]:
    """({(class, brand, model): n} for BEV/PHEV, all new cars of the month)."""
    cars = fetch_new_cars(session, period)
    fuels = fetch_fuels(session, [c["kenteken"] for c in cars])
    units: collections.Counter = collections.Counter()
    for c in cars:
        cls = powertrain_class(fuels.get(c["kenteken"], []))
        if cls:
            units[(cls, display_brand(c.get("merk")),
                   display_model(c.get("merk"), c.get("handelsbenaming")))] += 1
    return dict(units), len(cars)


def refresh_top(session: requests.Session | None = None) -> None:
    """Bring market/netherlands_top.json up to the newest Whole month of the CSV,
    reading only the months the month store does not have yet."""
    totals = market_top.csv_totals(CSV_PATHS["Whole"])
    if not totals:
        return
    target = max(totals)
    stored = market_top.load_store(STORE_PATH)
    need = [p for p in market_top.month_window(target) if p not in stored]
    if not need and market_top.top_is_current(TOP_PATH, target):
        print(f"{TOP_PATH.relative_to(market_top.REPO)}: current ({target}).")
        return
    print(f"Top brands/models: reading {len(need)} month(s) from RDW: {need or '-'}")
    session = session or rdw_session()
    fresh = {}
    for p in need:
        fresh[p] = aggregate_month(session, p)
        print(f"  {p}: {fresh[p][1]:,} new cars, "
              f"{sum(fresh[p][0].values()):,} BEV/PHEV")
    window = market_top.month_window(target)
    market_top.check_scope({p: v[1] for p, v in {**stored, **fresh}.items() if p in window},
                           totals)
    market_top.refresh_from_store("Netherlands", TOP_SOURCE, TOP_UNIT,
                                  "netherlands", fresh)


def open_presentation(session: requests.Session, variant: str) -> dict:
    """Open a saved workspace the way the Swing SPA does and return its
    presentation JSON ({title, table: {rows, columnHeaderRows, …}, info, …}).

    1. GET /viewer?workspace_guid=<template>  — anonymous login bounce; the page
       carries the session's own workspace id (Globals.workspaceId).
    2. POST api/workspace/<ws>/presentationfromurl {"entries": {"workspace_guid":
       <template>}} — the SPA sends every query parameter of its URL; the server
       copies the saved workspace's presentation into the session workspace.
    3. GET api/workspace/<ws>/presentation/<id> — the presentation with its table.
    """
    template = TEMPLATES[variant]
    init_url = f"{BASE}/viewer?workspace_guid={template}"
    r = _get(session, init_url, timeout=30)
    r.raise_for_status()
    m = re.search(r'Globals\.workspaceId\s*=\s*"([0-9a-f-]{36})"', r.text)
    if not m:
        raise RuntimeError(f"[{variant}] Globals.workspaceId not found in /viewer — "
                           "did Swing change the page again? (--probe-swing)")
    ws = m.group(1)
    page = re.search(r'<html[^>]*data-page-type="([^"]+)"', r.text)
    hdrs = {"Referer": init_url, "Origin": BASE,
            "X-Page-Type": page.group(1) if page else "Index"}
    token = swing_token(r.text)
    if token:
        hdrs["__RequestVerificationToken"] = token
    pr = _post_json(session, f"{BASE}/viewer/api/workspace/{ws}/presentationfromurl",
                    {"entries": {"workspace_guid": template}}, hdrs, timeout=60)
    pr.raise_for_status()
    meta = pr.json()
    if not (meta.get("isValid") and meta.get("presentationID")):
        raise RuntimeError(
            f"[{variant}] presentationfromurl gave no valid presentation ({meta}); the saved "
            f"workspace {template} may be gone — re-save the view in Swing (see 10-source-"
            "netherlands.md, 'Rotate one of the three Swing template GUIDs').")
    g = _get(session, f"{BASE}/viewer/api/workspace/{ws}/presentation/{meta['presentationID']}",
             headers={"Referer": init_url}, timeout=60)
    g.raise_for_status()
    return g.json()


def probe_open(variant: str = "Whole") -> None:
    """--probe-open: run open_presentation and print the shape of what comes back."""
    session = make_swing_session()
    p = open_presentation(session, variant)
    t = p.get("table") or {}
    print(f"[probe] title={p.get('title')!r} views={p.get('allowedViewTypes')} "
          f"current={p.get('currentViewType')} info={p.get('info')}")
    print(f"[probe] table: rows={t.get('rowCount')} cols={t.get('colCount')} "
          f"headRows={t.get('headRowCount')} headCols={t.get('headColCount')} "
          f"keys={sorted(t)}")
    for i, row in enumerate(t.get("columnHeaderRows") or []):
        print(f"[probe] columnHeaderRows[{i}] ({len(row['cells'])} cells): "
              f"{json.dumps(row['cells'][:14], ensure_ascii=False)[:1400]}")
    rows = t.get("rows") or []
    for i in list(range(min(4, len(rows)))) + ([len(rows) - 1] if len(rows) > 4 else []):
        print(f"[probe] rows[{i}] ({len(rows[i]['cells'])} cells): "
              f"{json.dumps(rows[i]['cells'][:14], ensure_ascii=False)[:1400]}")
    print(f"[probe] legend/info: {json.dumps({k: p[k] for k in p if k not in ('table',)}, ensure_ascii=False)[:800]}")


def probe_swing(variant: str = "Whole", greps: list[str] | None = None,
                gets: list[str] | None = None) -> None:
    """Diagnose how the Swing viewer opens a saved workspace — no data written.

    Bootstraps the way fetch_table does, then prints what a client needs to
    know: the Globals.* the page defines, its script tags, and every URL-like
    string / ajax call site in the same-origin bundles. Run it from CI through
    the relay (workflow input `probe`), because the portal drops the
    connections of datacentre IPs.
    """
    session = make_swing_session()
    init_url = f"{BASE}/viewer?workspace_guid={TEMPLATES[variant]}"
    r = _get(session, init_url, timeout=30)
    html = r.text
    print(f"[probe] init -> HTTP {r.status_code}, {len(html):,} chars, "
          f"cookies {sorted(getattr(session, 'relay_cookies', {}))}")
    ws = (re.search(r'Globals\.workspaceId\s*=\s*"([0-9a-f-]{36})"', html) or [None, ""])[1]
    tag = re.search(r"<html[^>]*>", html)
    tok = re.search(r"<input[^>]*__RequestVerificationToken[^>]*>", html)
    masked = re.sub(r"value=[^ >]+", "value=<masked>", tok.group(0)) if tok else None
    jar = {k: len(v) for k, v in getattr(session, "relay_cookies", {}).items()}
    print(f"[probe] <html> tag: {tag.group(0)[:200] if tag else None}")
    print(f"[probe] antiforgery input: {masked}; token chars: {len(swing_token(html))}; "
          f"cookies (name: length) {jar}")
    if greps or gets:
        probe_targets(session, html, ws, greps or [], gets or [])
        return
    for i, line in enumerate(html.splitlines(), 1):
        if "Globals." in line or "workspace_guid" in line or "swing" in line.lower() and "=" in line and len(line) < 240:
            print(f"[probe] html L{i}: {line.strip()[:260]}")
    srcs = re.findall(r'<script[^>]+src="([^"]+)"', html)
    links = re.findall(r'<link[^>]+href="([^"]+)"', html)
    print(f"[probe] script src: {srcs}")
    print(f"[probe] link href : {links[:30]}")
    for j, body in enumerate(re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", html, re.S), 1):
        body = body.strip()
        if body:
            print(f"[probe] inline script #{j} ({len(body)} chars): {body[:700]!r}")

    url_like = re.compile(
        r"""["'`]((?:/|\.\./)?(?:[Vv]iewer|[Aa]pi|[Hh]andlers|[Pp]resentation|[Jj]ive|[Ss]wing|[Ww]orkspace|[Dd]ata)"""
        r"""[^"'`\s]{0,140})["'`]""")
    call_site = re.compile(
        r"(?:fetch|\.ajax|\.getJSON|\.get|\.post|XMLHttpRequest|\.open|sendBeacon)\s*\(\s*[^)]{0,140}")
    seen: set[str] = set()
    for src in srcs:
        u = urljoin(f"{BASE}/viewer", src)
        if not u.startswith(BASE) or u in seen:
            continue
        seen.add(u)
        try:
            b = _get(session, u, headers={"Referer": f"{BASE}/viewer"}, timeout=60)
        except Exception as e:  # noqa: BLE001 - diagnostics must not stop at one bundle
            print(f"[probe] {u}: {type(e).__name__}: {e}")
            continue
        text = b.text
        print(f"[probe] === {u} -> HTTP {b.status_code}, {len(text):,} chars")
        urls = sorted(set(m.group(1) for m in url_like.finditer(text)))
        for x in urls[:150]:
            print(f"[probe]   url  {x}")
        calls = [m.group(0).replace("\n", " ")[:170] for m in call_site.finditer(text)]
        for x in list(dict.fromkeys(calls))[:60]:
            print(f"[probe]   call {x}")


def probe_targets(session: requests.Session, html: str, ws: str,
                  greps: list[str], gets: list[str]) -> None:
    """--probe-grep / --probe-get: print the code around regex matches in the
    page's same-origin bundles, and fetch API paths ({ws} = the session's
    Globals.workspaceId) through the relay."""
    referer = {"Referer": f"{BASE}/viewer"}
    pres = ""
    if any("{pres}" in g for g in gets):
        try:
            w = _get(session, f"{BASE}/viewer/api/workspace/{ws}", headers=referer, timeout=60).json()
            pres = (w.get("presentSheets") or [{}])[0].get("presentationID", "")
        except Exception as e:  # noqa: BLE001
            print(f"[probe] workspace lookup for {{pres}} failed: {e}")
    if greps:
        bundles = {}
        for src in re.findall(r'<script[^>]+src="([^"]+)"', html):
            u = urljoin(f"{BASE}/viewer", src)
            if u.startswith(BASE) and u not in bundles:
                bundles[u] = _get(session, u, headers=referer, timeout=60).text
        for pat in greps:
            rx = re.compile(pat)
            print(f"[probe] ### grep {pat!r}")
            for u, text in bundles.items():
                hits = list(rx.finditer(text))
                for m in hits[:6]:
                    a, b = max(0, m.start() - 350), min(len(text), m.end() + 350)
                    print(f"[probe]   {u.rsplit('/', 1)[-1].split('?')[0]}@{m.start()}: "
                          f"{text[a:b]!r}")
                if hits:
                    print(f"[probe]   ({len(hits)} hit(s) in {u.rsplit('/', 1)[-1].split('?')[0]})")
    for path in gets:
        url = urljoin(BASE, path.replace("{ws}", ws).replace("{pres}", pres)
                      .replace("{tpl}", TEMPLATES["Whole"]))
        try:
            r = _get(session, url, headers=referer, timeout=60)
        except Exception as e:  # noqa: BLE001 - keep probing the other paths
            print(f"[probe] GET {url}: {type(e).__name__}: {e}")
            continue
        print(f"[probe] GET {url} -> HTTP {r.status_code} {r.headers.get('content-type')} "
              f"{len(r.content):,} bytes")
        print(f"[probe]   body: {r.text[:2500]!r}")


def make_swing_session() -> requests.Session:
    """The session every duurzamemobiliteit.databank.nl request goes through,
    routed per NL_PROXY / NL_FETCH_RELAY (see _get)."""
    session = requests.Session()
    # Retry up to 3 times on connection errors with exponential backoff (2s, 4s, 8s).
    # Handles transient network-unreachable failures seen on GitHub Actions runners.
    _retry = Retry(connect=3, read=2, backoff_factor=2, raise_on_status=False)
    _adapter = HTTPAdapter(max_retries=_retry)
    session.mount("https://", _adapter)
    session.mount("http://", _adapter)

    # Network routing — duurzamemobiliteit.databank.nl blocks both GitHub
    # datacenter IPs *and* Cloudflare egress IPs, so neither a direct connection
    # nor the CF relay works from a hosted runner.
    # Precedence:
    #   1. NL_PROXY (http/https/socks5) — direct proxy, most reliable
    #   2. NL_FETCH_RELAY — Cloudflare Worker relay (works if CF IPs not blocked)
    #   3. Neither → direct (only works on unblocked networks)
    proxy = os.environ.get("NL_PROXY", "").strip()
    if proxy:
        session.proxies.update({"http": proxy, "https": proxy})
        masked = re.sub(r"//[^@/]+@", "//***@", proxy)
        print(f"[net] routing via NL_PROXY = {masked}")
    else:
        relay_base = os.environ.get("NL_FETCH_RELAY")
        if relay_base:
            session.relay_base = relay_base.rstrip("?url=") + "?url="  # normalise
            session.relay_token = os.environ.get("NL_RELAY_TOKEN", "")
            session.relay_cookies: dict = {}
            print(f"[net] routing via relay: {relay_base}")
    return session


def previous_month_period() -> str:
    """YYYY-MM for the calendar month before today (UTC)."""
    today = date.today()
    if today.month == 1:
        return f"{today.year - 1}-12"
    return f"{today.year}-{today.month - 1:02d}"


def csv_has_period(csv_path: str, period: str) -> bool:
    """Return True if csv_path exists and contains any row for `period`."""
    if not os.path.exists(csv_path):
        return False
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["period"] == period:
                return True
    return False


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--variant",
        choices=["whole", "used", "hdv", "all"],
        default="all",
        help="Which slice to fetch (default: all)",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Skip the 'already current' early-exit check.",
    )
    parser.add_argument(
        "--probe-swing", action="store_true",
        help="Diagnose how the Swing viewer opens a workspace (prints, writes nothing).",
    )
    parser.add_argument(
        "--probe-open", action="store_true",
        help="Open the Whole workspace like the SPA does and print the table's shape.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Fetch and parse, print how the rows differ from the CSV, write nothing.",
    )
    parser.add_argument(
        "--no-top", action="store_true",
        help="Skip the top brands/models refresh (market/netherlands_top.json).",
    )
    args = parser.parse_args()

    if args.probe_open:
        probe_open({"used": "Used", "hdv": "HDV"}.get(args.variant, "Whole"))
        return
    if args.probe_swing:
        split = lambda v: [x for x in (v or "").split("||") if x.strip()]  # noqa: E731
        probe_swing(greps=split(os.environ.get("PROBE_GREP")),
                    gets=[x for x in (os.environ.get("PROBE_GET") or "").split() if x])
        return

    variant_aliases = {"whole": "Whole", "used": "Used", "hdv": "HDV"}
    targets = (
        list(variant_aliases.values())
        if args.variant == "all"
        else [variant_aliases[args.variant]]
    )

    # Early exit per variant: skip those whose CSV already has last month's
    # row. RDW occasionally restates older months but those don't need
    # same-day pickup; --force is the override for restatement runs.
    if not args.force and not args.dry_run:
        prev = previous_month_period()
        current = [v for v in targets if csv_has_period(CSV_PATHS[v], prev)]
        targets = [v for v in targets if v not in current]
        for v in current:
            print(f"[{v}] CSV already has {prev}; skipping (use --force to re-fetch).")
        if not targets:
            print("All requested variants are current; nothing to do.")
            if not args.no_top:
                market_top.guarded(refresh_top)
            return

    session = make_swing_session()

    for variant in targets:
        data = fetch_table(variant, session)
        print(f"[{variant}] caption: {data['caption']}")
        parsed = parse_table(data, variant)
        rows = to_csv_rows(parsed, variant)
        print(f"[{variant}] parsed {len(rows)} non-zero months "
              f"({min(rows, default='—')} .. {max(rows, default='—')})")
        if not rows:
            # A variant returning zero rows is NOT normal — it means the parser
            # couldn't read the pivot (e.g. a re-saved workspace changed shape).
            # Dump the raw header structure so the format change is diagnosable,
            # then keep going so the other variants still update.
            import json as _json
            def _shape(x, depth=0):
                if isinstance(x, list):
                    head = x[:4]
                    return [_shape(e, depth + 1) for e in head] + (
                        ["…(+%d)" % (len(x) - 4)] if len(x) > 4 else [])
                if isinstance(x, dict):
                    return {k: _shape(v, depth + 1) for k, v in list(x.items())[:8]}
                return x
            print(f"[{variant}] WARNING: 0 rows parsed — pivot shape follows")
            print(f"[{variant}]   caption : {data.get('caption')!r}")
            print(f"[{variant}]   totalRows/Cols: {data.get('totalRows')}/{data.get('totalCols')}")
            print(f"[{variant}]   headRows: {_json.dumps(_shape(data.get('headRows')), ensure_ascii=False)[:1200]}")
            print(f"[{variant}]   headCols: {_json.dumps(_shape(data.get('headCols')), ensure_ascii=False)[:1200]}")
            print(f"[{variant}]   rowData[0:2]: {_json.dumps(_shape(data.get('rowData'))[:2], ensure_ascii=False)[:800]}")
            continue
        if args.dry_run:
            dry_run_report(CSV_PATHS[variant], rows, variant)
            continue
        keyed = {(p, variant): r for p, r in rows.items()}
        added, updated = upsert_csv(CSV_PATHS[variant], keyed)
        print(f"[{variant}] {added} added, {updated} updated -> {CSV_PATHS[variant]}")

    if not args.no_top and not args.dry_run:
        market_top.guarded(refresh_top)


if __name__ == "__main__":
    main()
