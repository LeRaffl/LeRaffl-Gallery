#!/usr/bin/env python3
"""Fetch Thailand new-vehicle registrations by fuel type from the TAI / AIU
member portal and upsert monthly rows into data/Thailand.csv.

Background
----------
The old public table on ``data.thaiauto.or.th`` (the ``...-energy-menu`` page)
froze in early 2026 and now sits behind a member wall, so it is no longer a
usable feed. The live figures are published on the AIU member portal
``aiu.thaiauto.or.th``, a single-page app backed by a JSON API on
``taiapi.thaiauto.or.th`` (port 3000). This script talks to that API:

    GET  /websites             -> resolve the AIU ``website_id``
    POST /login_with_website   -> {username, password, website_id} -> auth token
    GET  /veh_reg_fuel/report  -> ?period_mode=year&year=<Y>&type_code=ALL

Auth uses a member login; credentials come from the environment:

    THAILAND_AIU_THAIAUTO_USER
    THAILAND_AIU_THAIAUTO_PW

Data mapping
------------
The report returns one row per (month, vehicle-type) with a fuel split. Our
``Whole`` series maps to the "Passenger Car and Pickup Truck" category — this
reproduces the manually maintained history exactly (2026-02..05 line up to the
unit). Column mapping:

    BEV    <- bev_units
    PHEV   <- phev_units
    HEV    <- hev_units
    ICE    <- icev_units
    OTHERS <- other_units + not_specific_units
    TOTAL  <- total_units

Network note
------------
The API listens on the non-standard port 3000, which some egress proxies block
(including Claude Code's sandbox, which only permits 443). GitHub-hosted runners
reach it directly. If a runner's egress IP is blocked, point requests through a
permissive proxy with ``THAILAND_HTTPS_PROXY``.

Usage
-----
    python scripts/fetch_thailand.py                 # current year, upsert
    python scripts/fetch_thailand.py --years 2026
    python scripts/fetch_thailand.py --years 2018-2026   # full backfill / rebase
    python scripts/fetch_thailand.py --force
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from datetime import date
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

API_BASE = os.environ.get("THAILAND_AIU_API", "https://taiapi.thaiauto.or.th:3000").rstrip("/")
SOURCE = "aiu.thaiauto.or.th"
CSV_PATH = "data/Thailand.csv"
CSV_COLUMNS = [
    "period", "time_interval", "variant", "source",
    "BEV", "PHEV", "HEV", "OTHERS", "ICE", "TOTAL", "notes",
]

# Vehicle-type category that our "Whole" series tracks. Matched as a
# case-insensitive substring against the report's type label so minor label
# punctuation/spacing changes don't break the mapping.
WHOLE_TYPE_MATCH = "passenger"

USER_ENV = "THAILAND_AIU_THAIAUTO_USER"
PW_ENV = "THAILAND_AIU_THAIAUTO_PW"

THAI_MONTHS = {
    "มกราคม": 1, "กุมภาพันธ์": 2, "มีนาคม": 3, "เมษายน": 4,
    "พฤษภาคม": 5, "มิถุนายน": 6, "กรกฎาคม": 7, "สิงหาคม": 8,
    "กันยายน": 9, "ตุลาคม": 10, "พฤศจิกายน": 11, "ธันวาคม": 12,
}
ENG_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
}


# ── network ──────────────────────────────────────────────────────────────────

def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": "LeRaffl-Gallery/thailand-fetch",
        "Origin": "https://aiu.thaiauto.or.th",
        "Referer": "https://aiu.thaiauto.or.th/",
        "Accept": "application/json",
    })
    proxy = os.environ.get("THAILAND_HTTPS_PROXY", "").strip()
    if proxy:
        s.proxies.update({"http": proxy, "https": proxy})
        print(f"[net] routing via THAILAND_HTTPS_PROXY")
    retry = Retry(total=4, backoff_factor=1.5,
                  status_forcelist=[429, 500, 502, 503, 504],
                  allowed_methods=["GET", "POST"])
    adapter = HTTPAdapter(max_retries=retry)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    return s


def _as_rows(payload) -> list:
    """Unwrap the various envelope shapes an endpoint might return into a list."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for k in ("data", "result", "rows", "items", "records"):
            v = payload.get(k)
            if isinstance(v, list):
                return v
            if isinstance(v, dict):
                for k2 in ("rows", "data", "items", "records"):
                    if isinstance(v.get(k2), list):
                        return v[k2]
    return []


def resolve_website_id(session: requests.Session) -> int:
    """Resolve the AIU website_id, mirroring the portal's own logic: match any
    of site/name/title/url against "AIU" and take that entry's id."""
    override = os.environ.get("THAILAND_AIU_WEBSITE_ID", "").strip()
    if override.isdigit():
        return int(override)
    r = session.get(f"{API_BASE}/websites", timeout=(20, 60))
    r.raise_for_status()
    sites = _as_rows(r.json())
    for w in sites:
        fields = [w.get(k) for k in ("site", "name", "title", "url",
                                     "domain", "host", "website_key", "key")]
        if any("AIU" in str(v).upper() for v in fields if v):
            wid = w.get("id") or w.get("website_id")
            if wid:
                return int(wid)
    labels = [str(w.get("site") or w.get("name") or w.get("title") or w.get("id"))
              for w in sites]
    raise RuntimeError(f"no AIU site in /websites; saw: {labels[:12]}")


def login(session: requests.Session, website_id: int) -> None:
    """Authenticate. The portal is cookie-session based (there is no bearer
    token); a successful login sets a session cookie on ``session`` that the
    subsequent report calls ride on."""
    user = os.environ.get(USER_ENV, "").strip()
    pw = os.environ.get(PW_ENV, "")
    if not user or not pw:
        raise SystemExit(f"missing credentials: set {USER_ENV} and {PW_ENV}")
    r = session.post(f"{API_BASE}/login_with_website",
                     json={"username": user, "password": pw, "website_id": website_id},
                     timeout=(20, 60))
    r.raise_for_status()
    try:
        body = r.json()
    except ValueError:
        body = {}
    uid = (body.get("user_id") or body.get("id")
           or (body.get("user") or {}).get("id") if isinstance(body, dict) else None)
    if uid:
        print(f"[auth] logged in (user_id={uid})")
    else:
        keys = list(body)[:8] if isinstance(body, dict) else type(body).__name__
        msg = body.get("message") or body.get("error") if isinstance(body, dict) else ""
        print(f"[auth] WARNING: login response had no user_id "
              f"(keys={keys}, message={msg!r}); relying on session cookies")


def fetch_report(session: requests.Session, year: int) -> list:
    r = session.get(
        f"{API_BASE}/veh_reg_fuel/report",
        params={"period_mode": "year", "year": year, "type_code": "ALL"},
        timeout=(20, 120),
    )
    r.raise_for_status()
    rows = _as_rows(r.json())
    if rows:
        sample = {k: rows[0].get(k) for k in list(rows[0])[:12]} if isinstance(rows[0], dict) else rows[0]
        print(f"[{year}] report: {len(rows)} rows; first-row keys sample: {sample}")
    else:
        print(f"[{year}] report returned no rows (payload keys: "
              f"{list(r.json())[:8] if isinstance(r.json(), dict) else 'list'})")
    return rows


# ── parsing / mapping (pure, unit-testable) ──────────────────────────────────

def _num(x) -> int:
    try:
        return int(round(float(x)))
    except (TypeError, ValueError):
        return 0


def _month_no(row: dict) -> int | None:
    for k in ("period_month_no", "month_no", "period_month_number", "month_number"):
        v = row.get(k)
        if v not in (None, ""):
            try:
                return int(v)
            except (TypeError, ValueError):
                pass
    m = str(row.get("period_month") or row.get("month") or "").strip()
    if m.isdigit():
        return int(m)
    return THAI_MONTHS.get(m) or ENG_MONTHS.get(m.lower())


def _type_label(row: dict) -> str:
    return str(row.get("type_label") or row.get("type_name")
               or row.get("type_code") or "")


def report_rows_to_monthly(rows: list, year: int,
                           type_match: str = WHOLE_TYPE_MATCH) -> dict:
    """Sum the matching vehicle-type rows per month -> our column schema."""
    out: dict[str, dict] = {}
    for row in rows:
        if type_match.lower() not in _type_label(row).lower():
            continue
        mo = _month_no(row)
        if not mo:
            continue
        ry = row.get("period_year") or row.get("year") or year
        try:
            ry = int(ry)
        except (TypeError, ValueError):
            ry = year
        period = f"{ry}-{mo:02d}"
        acc = out.setdefault(period, {"BEV": 0, "PHEV": 0, "HEV": 0,
                                      "OTHERS": 0, "ICE": 0, "TOTAL": 0})
        acc["BEV"] += _num(row.get("bev_units"))
        acc["PHEV"] += _num(row.get("phev_units"))
        acc["HEV"] += _num(row.get("hev_units"))
        acc["ICE"] += _num(row.get("icev_units"))
        acc["OTHERS"] += _num(row.get("other_units")) + _num(row.get("not_specific_units"))
        acc["TOTAL"] += _num(row.get("total_units"))
    return out


def to_csv_rows(monthly: dict, variant: str = "Whole") -> dict:
    rows: dict = {}
    for period, cols in monthly.items():
        if cols["TOTAL"] <= 0:
            continue  # skip future / empty months
        parts = cols["BEV"] + cols["PHEV"] + cols["HEV"] + cols["OTHERS"] + cols["ICE"]
        if parts != cols["TOTAL"]:
            print(f"  WARNING {period}: fuel parts {parts} != TOTAL {cols['TOTAL']}")
        rows[period] = {
            "period": period,
            "time_interval": "monthly",
            "variant": variant,
            "source": SOURCE,
            "BEV": cols["BEV"],
            "PHEV": cols["PHEV"],
            "HEV": cols["HEV"],
            "OTHERS": cols["OTHERS"],
            "ICE": cols["ICE"],
            "TOTAL": cols["TOTAL"],
            "notes": "",
        }
    return rows


# ── CSV upsert ───────────────────────────────────────────────────────────────

def upsert_csv(csv_path: str, new_rows: dict) -> tuple[int, int]:
    """Upsert by (period, variant). Returns (added, updated). Warns on >50% delta."""
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
            print(f"  + {key[1]} {key[0]}")
        else:
            old = existing[key]
            for col in ("BEV", "PHEV", "HEV", "ICE"):
                old_val = float(old.get(col) or 0)
                new_val = float(new_row[col] or 0)
                if old_val > 100 and abs(new_val - old_val) / old_val > 0.5:
                    print(f"  WARNING {key[1]} {key[0]} {col}: existing={old_val:.0f}, "
                          f"new={new_val:.0f} — diff >50%, please verify")
            existing[key] = {**old, **new_row}
            updated += 1

    Path(csv_path).parent.mkdir(parents=True, exist_ok=True)
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, lineterminator="\n")
        writer.writeheader()
        for key in sorted(existing.keys(), key=lambda k: (k[1], k[0])):
            writer.writerow({c: existing[key].get(c, "") for c in CSV_COLUMNS})

    return added, updated


# ── driver ───────────────────────────────────────────────────────────────────

def parse_years(spec: str) -> list[int]:
    years: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            years.update(range(int(a), int(b) + 1))
        elif part:
            years.add(int(part))
    return sorted(years)


def previous_month_period() -> str:
    today = date.today()
    if today.month == 1:
        return f"{today.year - 1}-12"
    return f"{today.year}-{today.month - 1:02d}"


def csv_has_period(csv_path: str, period: str, variant: str) -> bool:
    if not os.path.exists(csv_path):
        return False
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["period"] == period and row["variant"] == variant:
                return True
    return False


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--years", default=str(date.today().year),
        help="Year(s) to fetch: '2026', '2018-2026', or '2024,2025' "
             "(default: current year).",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Skip the 'already current' early-exit check.",
    )
    args = parser.parse_args()

    years = parse_years(args.years)
    single_current = len(years) == 1 and years[0] == date.today().year

    if not args.force and single_current:
        prev = previous_month_period()
        if prev.startswith(str(years[0])) and csv_has_period(CSV_PATH, prev, "Whole"):
            print(f"CSV already has {prev} for Whole; nothing to do "
                  f"(use --force to re-fetch).")
            return

    session = make_session()
    website_id = resolve_website_id(session)
    print(f"[auth] website_id={website_id}")
    login(session, website_id)

    all_rows: dict = {}
    for year in years:
        report = fetch_report(session, year)
        monthly = report_rows_to_monthly(report, year)
        rows = to_csv_rows(monthly)
        if rows:
            print(f"[{year}] parsed {len(rows)} months "
                  f"({min(rows)} .. {max(rows)})")
        else:
            print(f"[{year}] no non-zero '{WHOLE_TYPE_MATCH}' months in response")
        all_rows.update(rows)

    if not all_rows:
        print("No rows fetched; leaving CSV unchanged.")
        return

    added, updated = upsert_csv(CSV_PATH, all_rows)
    print(f"{added} added, {updated} updated -> {CSV_PATH}")


if __name__ == "__main__":
    main()
