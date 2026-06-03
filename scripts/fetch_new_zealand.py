#!/usr/bin/env python3
"""
Fetch New Zealand light motor vehicle new-registration data from the
Ministry of Transport (transport.govt.nz) and upsert data/New\ Zealand.csv.

Source
------
  Primary: transport.govt.nz fleet-statistics dashboard (AJAX /inner endpoint)
    https://www.transport.govt.nz/statistics-and-insights/fleet-statistics/
    light-motor-vehicle-registrations/inner
  Fallback: data.govt.nz CKAN resource (monthly EV/hybrid registrations CSV)
    https://catalogue.data.govt.nz/dataset/vehicle-fleet-statistics
    resource fc87b220-59ec-4678-a09a-88497bb1018d

Only one variant is available ("Whole" = all light new registrations).
Light vehicles = GVM < 3,500 kg (passenger cars + light commercial combined).
No Private / Rental / Industry split is available from this source.

Usage
-----
    python scripts/fetch_new_zealand.py
    python scripts/fetch_new_zealand.py --months 6
    python scripts/fetch_new_zealand.py --since 2020-01   # backfill
    python scripts/fetch_new_zealand.py --force           # re-fetch even if current
    python scripts/fetch_new_zealand.py --debug           # print raw response

How the source works (reverse-engineered June 2026)
-----------------------------------------------------
transport.govt.nz/statistics-and-insights/fleet-statistics runs on
Silverstripe CMS. Each "sheet" page loads its chart data by GETting the same
path with /inner appended; that endpoint returns a JSON-serialised chart
payload (Highcharts-style or a custom tabular format).

Response formats handled (checked in order):
  A) Highcharts: top-level "series" list + "xAxis.categories" list of month
     labels ("Jan 2020", "January 2020", "Jan-20", …).
  B) Tabular:    top-level "data" or "rows" list of objects with per-row
     period and fuel-type keys.
  C) HTML fragment: JSON embedded in <script>…</script> or data-chart= attrs.

Fallback (data.govt.nz CKAN):
  When /inner fails or returns no usable data, the script queries the CKAN
  resource_show API, downloads the CSV at the returned url, and maps columns.
  Only BEV/PHEV/HEV columns are populated from this source (the resource
  covers EV/hybrid only). PETROL/DIESEL/TOTAL are set to 0 / unknown; the
  script prints a WARNING and the operator should re-run once the primary
  source recovers.

Fuel-type label → canonical column
-----------------------------------
  "Battery Electric" / "BEV" / "Electric"      → BEV
  "Plug-in Hybrid" / "PHEV" / "Plugin Hybrid"  → PHEV
  "Full Hybrid" / "Hybrid" / "HEV"             → HEV
  "Petrol"                                      → PETROL
  "Diesel"                                      → DIESEL
  "LPG" / "Gas" / "Other" / "Other Fuel"       → OTHERS

See docs/architecture/19-source-new-zealand.md for the full playbook.
"""
import argparse
import csv
import json
import os
import re
import sys
from datetime import date
from pathlib import Path

import requests

INNER_URL = (
    "https://www.transport.govt.nz/statistics-and-insights/fleet-statistics/"
    "light-motor-vehicle-registrations/inner"
)
CKAN_API  = "https://catalogue.data.govt.nz/api/3/action/resource_show"
CKAN_RID  = "fc87b220-59ec-4678-a09a-88497bb1018d"   # monthly EV/hybrid registrations
SOURCE    = "transport.govt.nz"
CSV_PATH  = "data/New Zealand.csv"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

CSV_COLUMNS = [
    "period", "time_interval", "variant", "source",
    "BEV", "PHEV", "HEV", "PETROL", "DIESEL", "OTHERS", "TOTAL", "notes",
]

# Fuel-type label → canonical column (case-insensitive matching done at call site)
FUEL_MAP: dict[str, str] = {
    "battery electric": "BEV",
    "battery electric (bev)": "BEV",
    "bev": "BEV",
    "electric": "BEV",
    "electric vehicle": "BEV",
    "plug-in hybrid": "PHEV",
    "plug in hybrid": "PHEV",
    "plugin hybrid": "PHEV",
    "phev": "PHEV",
    "plug-in hybrid electric vehicle": "PHEV",
    "full hybrid": "HEV",
    "hybrid": "HEV",
    "hev": "HEV",
    "hybrid electric vehicle": "HEV",
    "petrol": "PETROL",
    "gasoline": "PETROL",
    "petrol/lpg": "PETROL",   # count against petrol; LPG share negligible
    "diesel": "DIESEL",
    "lpg": "OTHERS",
    "gas": "OTHERS",
    "cng": "OTHERS",
    "compressed natural gas": "OTHERS",
    "other": "OTHERS",
    "other fuel": "OTHERS",
    "other fuels": "OTHERS",
    "other fuel types": "OTHERS",
}

# Month-name → number (for category label parsing)
_MONTH_ABBR = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
_MONTH_FULL = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
}


# ── helpers ──────────────────────────────────────────────────────────────────

def _http_get(url: str, **kwargs) -> requests.Response:
    r = requests.get(
        url, headers={"User-Agent": USER_AGENT}, timeout=30, **kwargs
    )
    r.raise_for_status()
    return r


def _fuel_col(label: str) -> str | None:
    """Map a fuel-type label to a canonical column, or None if unknown."""
    return FUEL_MAP.get(label.strip().lower())


def _parse_period_label(label: str) -> str | None:
    """
    Convert a month label ("Jan 2020", "January 2020", "Jan-20", "2020-01")
    to "YYYY-MM".  Returns None if the label cannot be parsed.
    """
    label = label.strip()
    # ISO: "2020-01"
    m = re.fullmatch(r"(\d{4})-(\d{2})", label)
    if m:
        return label

    # "Jan 2020" / "January 2020"
    m = re.fullmatch(r"([A-Za-z]+)\s+(\d{4})", label)
    if m:
        mon_str, yr_str = m.group(1).lower(), m.group(2)
        mon = _MONTH_ABBR.get(mon_str[:3]) or _MONTH_FULL.get(mon_str)
        if mon:
            return f"{yr_str}-{mon:02d}"

    # "Jan-20" / "Jan-2020"
    m = re.fullmatch(r"([A-Za-z]+)-(\d{2,4})", label)
    if m:
        mon_str, yr_str = m.group(1).lower(), m.group(2)
        mon = _MONTH_ABBR.get(mon_str[:3]) or _MONTH_FULL.get(mon_str)
        if mon:
            yr = int(yr_str)
            if yr < 100:
                yr += 2000 if yr < 50 else 1900
            return f"{yr}-{mon:02d}"

    return None


# ── Format-A: Highcharts-style ────────────────────────────────────────────────

def _parse_highcharts(payload: dict) -> dict[str, dict[str, int]] | None:
    """
    Extract {period: {column: count}} from a Highcharts-style dict:
      {"xAxis": {"categories": [...]}, "series": [{"name": "...", "data": [...]}, ...]}
    Returns None if the structure doesn't match.
    """
    # xAxis may be a dict or a list; data may be nested one level deeper
    x_axis = payload.get("xAxis") or payload.get("xaxis")
    series = payload.get("series")
    if not series:
        return None

    cats: list[str] = []
    if isinstance(x_axis, dict):
        cats = x_axis.get("categories") or []
    elif isinstance(x_axis, list) and x_axis:
        cats = x_axis[0].get("categories") or []

    if not cats:
        return None

    periods = [_parse_period_label(c) for c in cats]

    result: dict[str, dict[str, int]] = {}
    for s in series:
        label = s.get("name") or s.get("label") or ""
        col = _fuel_col(label)
        if col is None:
            print(f"  WARNING: unmapped fuel label {label!r} — add to FUEL_MAP")
            continue
        data_vals = s.get("data") or []
        for i, val in enumerate(data_vals):
            if i >= len(periods) or periods[i] is None:
                continue
            period = periods[i]
            count = int(val) if val else 0
            result.setdefault(period, {})
            result[period][col] = result[period].get(col, 0) + count

    return result if result else None


# ── Format-B: tabular rows ────────────────────────────────────────────────────

def _parse_tabular(payload: dict) -> dict[str, dict[str, int]] | None:
    """
    Extract {period: {column: count}} from a tabular-rows format:
      {"data": [{"period": "...", "fuel_type": "...", "count": N}, ...]}
    or
      {"rows": [...]}
    """
    rows = payload.get("data") or payload.get("rows") or []
    if not rows or not isinstance(rows, list) or not isinstance(rows[0], dict):
        return None

    # Try to identify which keys hold period and fuel type
    sample = rows[0]
    period_keys = [k for k in sample if re.search(r"period|month|date", k, re.I)]
    fuel_keys   = [k for k in sample if re.search(r"fuel|type|label|name", k, re.I)]
    count_keys  = [k for k in sample if re.search(r"count|registrations?|units?|value", k, re.I)]

    if not period_keys or not fuel_keys or not count_keys:
        return None

    pk, fk, ck = period_keys[0], fuel_keys[0], count_keys[0]
    result: dict[str, dict[str, int]] = {}
    for row in rows:
        period_raw = str(row.get(pk) or "")
        period = _parse_period_label(period_raw)
        if period is None:
            continue
        col = _fuel_col(str(row.get(fk) or ""))
        if col is None:
            continue
        count = int(float(row.get(ck) or 0))
        result.setdefault(period, {})
        result[period][col] = result[period].get(col, 0) + count

    return result if result else None


# ── Try to extract JSON from HTML ─────────────────────────────────────────────

def _extract_json_from_html(html: str) -> list[dict]:
    """
    Find all JSON objects embedded in <script> tags or data-chart= attributes.
    Returns a list of parsed dict candidates.
    """
    candidates: list[dict] = []

    # data-chart='{"series":...}' or data-highcharts-chart='...'
    for m in re.finditer(r'data-[^=]*chart[^=]*=\'({.*?})\'', html, re.S):
        try:
            candidates.append(json.loads(m.group(1)))
        except ValueError:
            pass
    for m in re.finditer(r'data-[^=]*chart[^=]*="({.*?})"', html, re.S):
        try:
            candidates.append(json.loads(m.group(1)))
        except ValueError:
            pass

    # <script>var chartData = {...}</script>
    for m in re.finditer(r"<script[^>]*>(.*?)</script>", html, re.S):
        block = m.group(1)
        # Look for JSON objects assigned to variables
        for jm in re.finditer(r"(?:=|\()\s*(\{(?:[^{}]|\{[^{}]*\})*\})\s*[;,)]", block):
            try:
                obj = json.loads(jm.group(1))
                if isinstance(obj, dict):
                    candidates.append(obj)
            except ValueError:
                pass
        # Entire block is JSON
        stripped = block.strip()
        if stripped.startswith("{"):
            try:
                candidates.append(json.loads(stripped))
            except ValueError:
                pass

    return candidates


# ── Primary source: transport.govt.nz /inner ─────────────────────────────────

def fetch_from_inner(debug: bool = False) -> dict[str, dict[str, int]] | None:
    """
    Fetch data from the transport.govt.nz /inner endpoint.
    Returns {period: {col: count}} or None on failure.
    """
    print(f"  Fetching {INNER_URL} …")
    try:
        r = _http_get(INNER_URL, allow_redirects=True)
    except requests.RequestException as exc:
        print(f"  WARN: transport.govt.nz /inner request failed: {exc}")
        return None

    content_type = r.headers.get("content-type", "")
    if debug:
        print(f"  [debug] status={r.status_code}  content-type={content_type}")
        print(f"  [debug] first 2000 chars of response:\n{r.text[:2000]}\n")

    # Try as JSON directly
    payload = None
    if "json" in content_type or r.text.lstrip().startswith("{"):
        try:
            payload = r.json()
        except ValueError:
            pass

    if payload is not None:
        result = _parse_highcharts(payload) or _parse_tabular(payload)
        if result:
            return result
        if debug:
            print(f"  [debug] Parsed as JSON but no recognised structure. Keys: {list(payload.keys())[:20]}")

    # Try embedded JSON in HTML
    candidates = _extract_json_from_html(r.text)
    if debug:
        print(f"  [debug] Found {len(candidates)} JSON candidate(s) in HTML")
    for cand in candidates:
        result = _parse_highcharts(cand) or _parse_tabular(cand)
        if result:
            return result

    print("  WARN: /inner response not in any recognised format.")
    if not debug:
        print("  Tip: re-run with --debug to see the raw response.")
    return None


# ── Fallback source: data.govt.nz CKAN ───────────────────────────────────────

def fetch_from_ckan(debug: bool = False) -> dict[str, dict[str, int]] | None:
    """
    Download the 'Monthly electric and hybrid light vehicle registrations' CSV
    from data.govt.nz via the CKAN resource_show API.
    Returns {period: {col: count}} — NOTE: only BEV/PHEV/HEV populated.
    """
    print(f"  Querying CKAN resource {CKAN_RID} …")
    try:
        meta = _http_get(CKAN_API, params={"id": CKAN_RID}).json()
    except Exception as exc:
        print(f"  WARN: CKAN API request failed: {exc}")
        return None

    if not meta.get("success"):
        print(f"  WARN: CKAN returned success=false: {meta.get('error')}")
        return None

    csv_url = meta["result"].get("url")
    if not csv_url:
        print("  WARN: CKAN resource has no url field.")
        return None

    print(f"  Downloading {csv_url} …")
    try:
        r = _http_get(csv_url)
    except Exception as exc:
        print(f"  WARN: CKAN CSV download failed: {exc}")
        return None

    if debug:
        print(f"  [debug] CKAN CSV first 500 chars:\n{r.text[:500]}\n")

    reader = csv.DictReader(r.text.splitlines())
    fieldnames = reader.fieldnames or []
    if debug:
        print(f"  [debug] CKAN CSV columns: {fieldnames}")

    # Identify period and count columns heuristically
    period_cols = [c for c in fieldnames if re.search(r"period|month|date", c, re.I)]
    if not period_cols:
        print(f"  WARN: cannot identify period column in CKAN CSV. Columns: {fieldnames}")
        return None

    result: dict[str, dict[str, int]] = {}
    for row in reader:
        period_raw = row.get(period_cols[0], "")
        period = _parse_period_label(period_raw)
        if period is None:
            continue
        # Try to map each column
        for k, v in row.items():
            col = _fuel_col(k)
            if col:
                try:
                    result.setdefault(period, {})
                    result[period][col] = result[period].get(col, 0) + int(float(v or 0))
                except (ValueError, TypeError):
                    pass

    if not result:
        print("  WARN: CKAN CSV parsed but yielded no data rows.")
        return None

    print("  WARNING: CKAN source covers EV/hybrid only — PETROL/DIESEL/TOTAL "
          "will be 0/partial. Verify against transport.govt.nz dashboard.")
    return result


# ── CSV helpers ───────────────────────────────────────────────────────────────

def _load_existing(csv_path: str) -> dict[str, dict]:
    existing: dict[str, dict] = {}
    if not os.path.exists(csv_path):
        return existing
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            for c in CSV_COLUMNS:
                row.setdefault(c, "")
            existing[row["period"]] = row
    return existing


def _upsert(csv_path: str, new_data: dict[str, dict[str, int]]) -> tuple[int, int]:
    """
    Merge new_data into csv_path.  Returns (added, updated).
    Prints a WARNING for >50% changes on existing rows to catch fetch errors.
    """
    existing = _load_existing(csv_path)
    added = updated = 0

    for period, cols in sorted(new_data.items()):
        total = cols.get("TOTAL") or (
            cols.get("BEV", 0) + cols.get("PHEV", 0) + cols.get("HEV", 0)
            + cols.get("PETROL", 0) + cols.get("DIESEL", 0) + cols.get("OTHERS", 0)
        )
        if total <= 0:
            print(f"  SKIP {period}: total={total}")
            continue

        new_row: dict = {
            "period": period, "time_interval": "monthly", "variant": "Whole",
            "source": SOURCE,
            "BEV":    cols.get("BEV", 0),
            "PHEV":   cols.get("PHEV", 0),
            "HEV":    cols.get("HEV", 0),
            "PETROL": cols.get("PETROL", 0),
            "DIESEL": cols.get("DIESEL", 0),
            "OTHERS": cols.get("OTHERS", 0),
            "TOTAL":  total,
            "notes":  "",
        }

        if period in existing:
            old = existing[period]
            for col in ("BEV", "PHEV", "HEV", "PETROL", "DIESEL", "OTHERS", "TOTAL"):
                try:
                    ov, nv = float(old.get(col) or 0), float(new_row[col] or 0)
                except (ValueError, TypeError):
                    continue
                if ov > 100 and nv > 0 and abs(nv - ov) / ov > 0.5:
                    print(f"  WARNING {period} {col}: existing={ov:.0f} "
                          f"new={nv:.0f} (>50% change) — please verify")
            if not new_row["notes"]:
                new_row["notes"] = old.get("notes", "")
            existing[period] = new_row
            updated += 1
        else:
            existing[period] = new_row
            added += 1

    Path(csv_path).parent.mkdir(parents=True, exist_ok=True)
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS, lineterminator="\n")
        w.writeheader()
        for p in sorted(existing.keys()):
            w.writerow(existing[p])

    return added, updated


def _latest_period(csv_path: str) -> str | None:
    if not os.path.exists(csv_path):
        return None
    with open(csv_path, newline="", encoding="utf-8") as f:
        periods = [r["period"] for r in csv.DictReader(f)]
    return max(periods) if periods else None


def _previous_month() -> tuple[int, int]:
    t = date.today()
    return (t.year - 1, 12) if t.month == 1 else (t.year, t.month - 1)


# ── main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--months", type=int, default=3,
                    help="Trailing window of recent months to include (default 3).")
    ap.add_argument("--since", type=str, default=None,
                    help="Backfill start 'YYYY-MM'; fetches through last month.")
    ap.add_argument("--force", action="store_true",
                    help="Re-fetch and overwrite periods already in the CSV.")
    ap.add_argument("--debug", action="store_true",
                    help="Print raw response details for troubleshooting.")
    ap.add_argument("--csv", default=CSV_PATH,
                    help=f"CSV path (default: {CSV_PATH}).")
    args = ap.parse_args()

    prev_y, prev_m = _previous_month()
    prev_period = f"{prev_y}-{prev_m:02d}"

    # Early-exit if CSV already has the previous month (and not --force/--since)
    if not args.force and not args.since:
        latest = _latest_period(args.csv)
        if latest and latest >= prev_period:
            print(f"CSV already has {latest}; nothing to do (use --force to re-fetch).")
            return

    # Try primary source
    print("Fetching from transport.govt.nz …")
    data = fetch_from_inner(debug=args.debug)

    # Fallback
    if not data:
        print("Primary source failed; trying data.govt.nz CKAN fallback …")
        data = fetch_from_ckan(debug=args.debug)

    if not data:
        sys.exit(
            "ERROR: Both sources failed.\n"
            "  – Check that transport.govt.nz is accessible from this runner.\n"
            "  – Re-run with --debug to see raw responses.\n"
            "  – If the /inner format changed, update FUEL_MAP or the parser."
        )

    # Filter to the requested window (unless --force, keep all fetched)
    if not args.force:
        if args.since:
            m = re.match(r"(\d{4})-(\d{2})", args.since)
            if not m:
                sys.exit("--since must be YYYY-MM")
            cutoff = args.since
        else:
            total_months = prev_y * 12 + (prev_m - 1) - (args.months - 1)
            cutoff_y, cutoff_m = total_months // 12, total_months % 12 + 1
            cutoff = f"{cutoff_y}-{cutoff_m:02d}"

        existing_latest = _latest_period(args.csv)
        data = {
            p: v for p, v in data.items()
            if p >= cutoff
            and (args.force or not existing_latest or p > existing_latest)
        }

    if not data:
        print("No new data to write.")
        return

    print(f"Periods to write: {sorted(data.keys())}")
    added, updated = _upsert(args.csv, data)
    print(f"Done. added={added}  updated={updated}  → {args.csv}")


if __name__ == "__main__":
    main()
