#!/usr/bin/env python3
"""
Snapshot the Builder-tab aggregated BEV/ICE/PHEV curves into builder_history/.

This script mirrors the in-page Builder logic from index.html (the same
weighted Weibull aggregation, the same group definitions, the same v1=0
"Indonesia-style" anchor recovery) and writes the result as a CSV plus a
metadata entry into builder_history/index.json.

Usage
-----
    python scripts/snapshot_builder.py
    python scripts/snapshot_builder.py --date 2026-05-20
    python scripts/snapshot_builder.py --params params.csv --weights weights.csv --out builder_history

Cadence
-------
Triggered monthly by .github/workflows/snapshot-builder.yml. Each run produces
exactly one snapshot file named <date>.csv. Re-running on the same date
overwrites that file; the workflow only commits when the content changed.

Output
------
builder_history/<YYYY-MM-DD>.csv with columns

    group,year,bev_share,ice_share,phev_share

`year` is a fractional calendar year (2015.0 to 2050.0 in 0.1-year steps).
`bev/ice/phev_share` are weighted aggregate percentages in [0, 100]; ICE and
PHEV cells are empty when no row in the group carries the ICE Weibull
parameters needed to compute them.

builder_history/index.json indexes the snapshots with per-group metadata:
country count, total weight covered, and the latest `data_per` that
contributed.

Faithfulness to the in-page Builder
-----------------------------------
`params.csv` in production has no `baseline_year` column and an empty
`baseline_date`, so there is no baseline at all and `t0` is already a calendar
year. Both sides therefore route every calendar-year field through a guard
(`calendarYearOrNaN` in `index.html`, `calendar_year_or_nan()` here) that
rejects the `0` which `Number('')` / `norm_number('')` yield for an absent
field. Without it the baseline branch fires with `by = 0` and returns
`(t0 - 0) + 1` — one year too late.

BASELINE OFF-BY-ONE FIX (2026-09, #219): `index.html` gained that guard in the
2026-09 UI overhaul (#218); this script mirrored the pre-fix behaviour until
#219. The affected band was **narrower than #219 assumed** — it opened at the
2026-06 calendar-year fix, not at #218:

  * up to 2026-05-31 — `x = year + 1` *and* `t0 + 1`. The two offsets cancel,
    so `z = x - t0 = year - t0`: the correct calendar basis, by accident.
  * 2026-06-25 … 2026-09-09 — the calendar-year fix moved this script to
    `x = year` and left `get_t0_years()` returning `t0 + 1`, so
    `z = year - t0 - 1`: one year late.
  * from this fix onward — `x = year`, `t0` unshifted.

**Those snapshots were rebuilt rather than annotated, so the whole series is
now on one basis and needs no correction to compare any two entries.** #219
assumed the band could not be regenerated "without a historical parameter
store (#220)" — that premise was wrong: `params.csv` and `weights.csv` are
versioned, so git *is* that store. `scripts/rebuild_builder_history.py`
recovers each date's inputs with `git show` and re-runs this module over them.

Proven before it was used: rebuilding 2026-09-09 from that date's commit
reproduces the committed file to 0.0000 pp once the known one-year shift is
applied, and rebuilding the four already-correct May snapshots reproduces them
to within 0.008 years (params moving inside the snapshot day). The six offset
snapshots moved by exactly -1.000 years each.

The same mechanism extends the series **backwards**: it now starts 2025-12-25,
the first date `weights.csv` exists, instead of 2026-05-20.

Note that `baseline_year_of()` now returns NaN for a production row, as it does
on the page. It is *not* part of the finiteness gate in `compute_group_curve()`
— `index.html` computes it and does not gate on it either.

CALENDAR-YEAR FIX (2026-06): The curve is evaluated at the calendar year
directly (`x = year`). The canonical share formula is
`S(C) = 1 - exp(v1 * (C - t0)^v2)` where C is the calendar year and t0 is
a calendar-year integer (R's `verschiebung` = `floor(min(data$year_calendar))`
= first calendar year of data). `bev_share_index(x, v1, v2, t0)` computes
`1 - exp(v1 * (x - t0)^v2)`, so feeding `x = year` (calendar year) is correct.

Before the 2026-06 fix, index.html's Builder used `x = year - by + 1` where
`by = baseline_year_of(r) = 0` (absent column), so `x = year + 1`, which
evaluated the curve one calendar year ahead of where it should be. This script
previously mirrored that bug intentionally. After the fix both index.html and
this script feed the calendar year directly.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
from collections import defaultdict
from datetime import date as date_cls
from pathlib import Path


# --- Builder curve resolution ------------------------------------------------

YEAR_START = 2015.0
YEAR_END = 2050.0
YEAR_STEP = 0.1  # 351 points; ~36-day resolution. Builder uses 0.05 for live
                 # plot smoothness; 0.1 is plenty for time-lapse frames and
                 # halves file size.

# Single-country series for the Time-lapse spotlight.
#
# These are NOT part of BUILDER_GROUPS and must not be added to it: that dict
# mirrors index.html, and a country is not a group there. They are written as
# extra rows under a `country_<slug>` key, which cannot collide with a group
# name and is safe as a filename.
#
# A country only belongs here if it is worth a single-case discussion AND is
# present in every snapshot -- otherwise its time-lapse has holes. Check
# `builder_history/cohort/index.json` before adding one.
SPOTLIGHT_COUNTRIES = [
    "Germany",    # largest EU market
    "China",      # the volume story
    "Norway",     # furthest along, the shape everyone else is walking into
    "USA",        # large market, visibly slower
    "Japan",      # large market, slower still
    "France",     # second EU market, different policy mix
]


def country_key(name: str) -> str:
    """`Germany` -> `country_germany`. Safe as a filename and a URL."""
    slug = "".join(ch.lower() if ch.isalnum() else "_" for ch in name)
    return f"country_{slug.strip('_')}"


# Mirror index.html `BUILDER_GROUPS`. Weight-based groups (small/medium/big
# markets) are computed dynamically from weights.csv.
GROUPS_STATIC = {
    "world": None,  # populated to "all countries present in params.csv"
    "western_europe": [
        "Austria", "Belgium", "France", "Germany", "Netherlands",
        "Luxembourg", "Switzerland", "Ireland", "United Kingdom", "UK",
    ],
    "northern_europe": ["Norway", "Sweden", "Denmark", "Finland", "Iceland"],
    "southern_europe": ["Spain", "Portugal", "Italy", "Greece", "Malta", "Cyprus"],
    "eastern_europe": [
        "Poland", "Czechia", "Slovakia", "Hungary", "Romania",
        "Bulgaria", "Croatia", "Slovenia", "Latvia", "Lithuania", "Estonia",
    ],
    "eu": [
        "Austria", "Belgium", "Bulgaria", "Croatia", "Cyprus", "Czechia", "Denmark",
        "Estonia", "Finland", "France", "Germany", "Greece", "Hungary", "Ireland",
        "Italy", "Latvia", "Lithuania", "Luxembourg", "Malta", "Netherlands",
        "Poland", "Portugal", "Romania", "Slovakia", "Slovenia", "Spain", "Sweden",
    ],
    "g7": ["USA", "Canada", "Japan", "Germany", "France", "United Kingdom", "Italy", "UK"],
    "north_america": ["United States", "Canada", "Mexico", "USA"],
    "south_america": ["Brazil", "Argentina", "Chile", "Colombia", "Peru", "Uruguay"],
    "americas": [
        "United States", "Canada", "Mexico",
        "Brazil", "Argentina", "Chile", "Colombia", "Peru", "Uruguay", "USA",
    ],
    "asia": [
        "China", "Japan", "South Korea", "India",
        "Thailand", "Malaysia", "Indonesia",
        "Vietnam", "Philippines", "Singapore", "Taiwan", "Hong Kong",
    ],
}

SMALL_MARKET_LIMIT = 50_000
BIG_MARKET_LIMIT = 1_000_000

DEFAULT_VARIANT = "whole"  # the Builder default + what the issue context names

ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
YEAR_MONTH_RE = re.compile(r"^(\d{4})-(\d{2})$")

# Which x-basis the `year` column of a snapshot is on. Stamped onto every
# snapshot entry in index.json so a consumer can tell the two eras apart
# without knowing the date of the seam. See the module docstring and #219.
#   calendar_year        — z = year - t0; agrees with the live Builder.
#   calendar_year_plus_1 — z = year - t0 - 1; the 2026-06-25 … 2026-09-09 band,
#                          which reaches any given share one year later.
CURVE_BASIS = "calendar_year"
LEGACY_CURVE_BASIS = "calendar_year_plus_1"


# --- Number / variant helpers (mirror index.html) ----------------------------

def norm_number(x) -> float:
    """Mirrors the JS `const normNumber = x => Number(String(x||'').trim().replace(',','.'))`.

    Returns 0.0 (NOT NaN) for empty/None inputs, because in JS
    `Number('') === 0`. Callers that read a *calendar year* out of a possibly
    absent column must not use this directly — route them through
    `calendar_year_or_nan()`, which rejects the 0 (see its docstring).
    """
    if x is None:
        return 0.0
    s = str(x).strip().replace(",", ".")
    if s == "":
        return 0.0
    try:
        n = float(s)
    except (ValueError, TypeError):
        return math.nan
    return n if math.isfinite(n) else math.nan


def calendar_year_or_nan(v) -> float:
    """Mirror `calendarYearOrNaN` in index.html.

    `norm_number('')` and `norm_number(None)` are 0.0 (the JS `Number('') === 0`
    quirk). 0 is not a calendar year, so anything outside [1800, 3000) becomes
    NaN. This is what keeps an absent `baseline_year` column from being read as
    "baseline year 0" and shifting every curve a year — see #219.
    """
    n = norm_number(v)
    return n if (math.isfinite(n) and 1800 <= n < 3000) else math.nan


def normalize_base(s) -> str:
    k = str(s or "").strip().lower()
    if not k:
        return ""
    if k in {"all", "total", "overall", "whole", "total market", "market total",
             "entire", "entire market", "total vehicles", "fleet total"}:
        return "whole"
    if k in {"hdv", "heavy duty", "heavy-duty", "heavy duty vehicles",
             "trucks", "truck", "commercial heavy", "heavy vehicles"}:
        return "hdv"
    if k in {"bus", "buses"}:
        return "buses"
    return k


def canonical_country_key(c) -> str:
    return re.sub(r"\s+", "", str(c or "").lower())


def iso_date_to_year_frac(iso: str) -> float:
    if not ISO_DATE_RE.match(str(iso or "")):
        return math.nan
    try:
        y, m, d = (int(p) for p in iso.split("-"))
        start = date_cls(y, 1, 1).toordinal()
        end = date_cls(y + 1, 1, 1).toordinal()
        return y + (date_cls(y, m, d).toordinal() - start) / (end - start)
    except (ValueError, TypeError):
        return math.nan


# --- Per-row model parameter extraction (mirror index.html) ------------------

def baseline_year_of(r: dict) -> float:
    """Mirror `baselineYearOf` in index.html. NaN when the row carries no
    usable baseline — which is the production case, `params.csv` having no
    `baseline_year` column and an empty `baseline_date`."""
    by = calendar_year_or_nan(r.get("baseline_year"))
    if math.isfinite(by):
        return round(by)
    bd = str(r.get("baseline_date") or "")
    if ISO_DATE_RE.match(bd):
        return int(bd[:4])
    return math.nan


def get_t0_years(r: dict, t0_key: str = "t0") -> float:
    """Mirror `getT0Years` in index.html."""
    base_date = str(r.get("baseline_date") or "")
    base_year = calendar_year_or_nan(r.get("baseline_year"))
    t0_raw = str(r.get(t0_key) or "").strip()
    t0_n = calendar_year_or_nan(t0_raw)

    # Production params.csv has no baseline: t0 is already a calendar year.
    # An empty baseline_year must NOT parse as 0 (norm_number('') == 0.0) or we
    # return (t0 - 0) + 1 and shift every curve by a year.
    if math.isfinite(t0_n) and (math.isfinite(base_year) or ISO_DATE_RE.match(base_date)):
        if math.isfinite(base_year):
            by = round(base_year)
        else:
            by = int(base_date[:4])
        if math.isfinite(by) and by >= 1800:
            return (t0_n - by) + 1

    if ISO_DATE_RE.match(t0_raw):
        t0_yf = iso_date_to_year_frac(t0_raw)
        by_frac = base_year if math.isfinite(base_year) else iso_date_to_year_frac(base_date)
        if math.isfinite(by_frac) and by_frac >= 1800 and math.isfinite(t0_yf):
            return (t0_yf - by_frac) + 1

    return t0_n


# --- v1=0 anchor recovery (mirror recoverV1FromAnchor) -----------------------

def recover_v1_from_anchor(v2_in, t0_in, data_per) -> float:
    """Replicate `recoverV1FromAnchor` from index.html.

    See docs/architecture/08-deploy-ops.md § "Indonesia v1=0 corruption" for
    the calibration story. Fallback is -1e-24, the legacy defensive constant.
    """
    v2n = norm_number(v2_in)
    t0n = norm_number(t0_in)
    if not math.isfinite(v2n) or v2n <= 0:
        return -1e-24
    if not math.isfinite(t0n) or t0n < 1800:
        return -1e-24
    m = YEAR_MONTH_RE.match(str(data_per or "").strip())
    if not m:
        return -1e-24
    cal_year = int(m.group(1))
    month = int(m.group(2))
    year_model = (cal_year - 1) + (month - 1) / 12.0
    dt = year_model - (t0n - 1)
    if not (dt > 0):
        return -1e-24
    anchor_share = 0.28 if v2n >= 10 else 0.50
    try:
        rec = math.log(1 - anchor_share) / (dt ** v2n)
    except (ValueError, OverflowError, ZeroDivisionError):
        return -1e-24
    if not math.isfinite(rec) or rec >= 0:
        return -1e-24
    return rec


def apply_v1_recovery(rows: list[dict]) -> list[dict]:
    """Mirror `applyV1Recovery` in index.html. Mutates rows in place."""
    for r in rows:
        v1_raw = str(r.get("v1") or "").strip()
        if v1_raw and norm_number(v1_raw) == 0:
            r["v1"] = str(recover_v1_from_anchor(r.get("v2"), r.get("t0"), r.get("data_per")))
        ice_raw = str(r.get("ice_v1") or "").strip()
        if ice_raw and norm_number(ice_raw) == 0:
            t0_ice = r.get("ice_t0")
            if not (t0_ice and str(t0_ice).strip()):
                t0_ice = r.get("t0")
            r["ice_v1"] = str(recover_v1_from_anchor(r.get("ice_v2"), t0_ice, r.get("data_per")))
    return rows


# --- Defensive dedupe (mirror dedupeParamRows; lighter, no UI warnings) ------

def dedupe_param_rows(rows: list[dict]) -> list[dict]:
    by_key: dict[str, dict] = {}
    by_key_dp: dict[str, str] = {}
    country_by_canon: dict[str, str] = {}

    for r in rows:
        raw = str(r.get("country") or "").strip()
        if not raw:
            continue
        canon = canonical_country_key(raw)
        if not canon:
            continue
        existing = country_by_canon.get(canon)
        if existing is None:
            country_by_canon[canon] = raw
            continue
        if existing == raw:
            continue
        existing_has_space = bool(re.search(r"\s", existing))
        new_has_space = bool(re.search(r"\s", raw))
        if new_has_space and not existing_has_space:
            country_by_canon[canon] = raw

    for r in rows:
        raw = str(r.get("country") or "").strip()
        if not raw:
            continue
        canon = canonical_country_key(raw)
        chosen = country_by_canon.get(canon, raw)
        variant = normalize_base(r.get("variant") or "")
        key = f"{chosen}|||{variant}"
        dp = str(r.get("data_per") or "").strip()
        patched = {**r, "country": chosen}
        prev_dp = by_key_dp.get(key, "")
        if key not in by_key or (dp and dp > prev_dp):
            by_key[key] = patched
            by_key_dp[key] = dp

    return list(by_key.values())


# --- Weibull share (mirror bevShareIndex / iceShareIndex) --------------------

def bev_share_index(x: float, v1: float, v2: float, t0: float) -> float:
    if x <= 0:
        return 0.0
    z = x - t0
    if z <= 0:
        return 0.0
    try:
        return 1.0 - math.exp(v1 * (z ** v2))
    except (ValueError, OverflowError):
        return math.nan


def ice_share_index(x: float, v1: float, v2: float, t0: float) -> float:
    if x <= 0:
        return 1.0
    z = x - t0
    if z <= 0:
        return 1.0
    try:
        return math.exp(v1 * (z ** v2))
    except (ValueError, OverflowError):
        return math.nan


# --- I/O ---------------------------------------------------------------------

def load_params(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    rows = dedupe_param_rows(rows)
    apply_v1_recovery(rows)
    return rows


def load_weights(path: Path) -> dict[str, float]:
    out: dict[str, float] = {}
    with path.open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            country = str(r.get("country") or "").strip()
            variant = normalize_base(r.get("variant") or "whole")
            w = norm_number(r.get("weight"))
            if country and math.isfinite(w):
                out[f"{country}|{variant}"] = w
    return out


# --- Group resolution --------------------------------------------------------

def resolve_groups(param_rows: list[dict],
                   weights: dict[str, float]) -> dict[str, list[str]]:
    """Build the static groups (filtered to countries that actually have a
    Whole-variant params row) plus the three weight-based dynamic groups.
    Mirrors `BUILDER_GROUPS` in index.html (with the `BUILDER_GROUPS.world`
    rule = "all countries present in params.csv").
    """
    countries_with_whole = sorted({
        r["country"] for r in param_rows
        if r.get("country") and normalize_base(r.get("variant") or "") == DEFAULT_VARIANT
    })
    available = set(countries_with_whole)

    groups: dict[str, list[str]] = {}
    groups["world"] = countries_with_whole

    for name, members in GROUPS_STATIC.items():
        if name == "world":
            continue
        groups[name] = [c for c in members if c in available]

    small: list[str] = []
    medium: list[str] = []
    big: list[str] = []
    for c in countries_with_whole:
        w = weights.get(f"{c}|{DEFAULT_VARIANT}")
        if w is None or not math.isfinite(w):
            continue
        if w < SMALL_MARKET_LIMIT:
            small.append(c)
        elif w < BIG_MARKET_LIMIT:
            medium.append(c)
        else:
            big.append(c)
    groups["small_markets"] = small
    groups["medium_markets"] = medium
    groups["big_markets"] = big

    # Spotlight countries: a group of one. Appended after the mirrored groups
    # so nothing above this line changes meaning, and skipped silently when a
    # country is not in this snapshot rather than writing an empty series.
    for name in SPOTLIGHT_COUNTRIES:
        if name in available:
            groups[country_key(name)] = [name]

    return groups


# --- The aggregation itself --------------------------------------------------

def weight_for_row(r: dict, weights: dict[str, float]) -> float:
    """Mirror the Builder's `weightForRow`: exact (country, variant) first,
    then (country, whole), then 1."""
    country = r.get("country") or ""
    rv = normalize_base(r.get("variant") or "")
    exact = weights.get(f"{country}|{rv}")
    if exact is not None and math.isfinite(exact):
        return exact
    whole = weights.get(f"{country}|{DEFAULT_VARIANT}")
    if whole is not None and math.isfinite(whole):
        return whole
    return 1.0


def yrange(start: float, end: float, step: float):
    """Inclusive float range with a small epsilon guard."""
    n = int(round((end - start) / step)) + 1
    for i in range(n):
        yield round(start + i * step, 10)


def compute_group_curve(countries: list[str],
                        param_rows: list[dict],
                        weights: dict[str, float],
                        variant_canonical: str = DEFAULT_VARIANT
                        ) -> tuple[list[float], list[float], list[float], list[float], dict]:
    """Aggregate BEV/ICE/PHEV curves for one group, returning xs and three
    share series in [0, 100], plus a metadata dict.

    Returns
    -------
    (xs, bev_pct, ice_pct, phev_pct, meta)
        ice_pct[i] / phev_pct[i] may be `nan` for a year where no row in the
        group carries ICE parameters. Caller renders nan as empty cells.
    """
    countries_set = set(countries)
    rows = [
        r for r in param_rows
        if r.get("country") in countries_set
        and normalize_base(r.get("variant") or "") == variant_canonical
    ]

    total_weight = 0.0
    latest_dp = ""
    for r in rows:
        w = weight_for_row(r, weights)
        if math.isfinite(w):
            total_weight += w
        dp = str(r.get("data_per") or "").strip()
        if dp and dp > latest_dp:
            latest_dp = dp

    xs: list[float] = []
    bev: list[float] = []
    ice: list[float] = []
    phev: list[float] = []

    for year in yrange(YEAR_START, YEAR_END, YEAR_STEP):
        y_sum = 0.0
        w_sum = 0.0
        ice_sum = 0.0
        ice_w_sum = 0.0
        phev_sum = 0.0
        phev_w_sum = 0.0

        for r in rows:
            v1 = norm_number(r.get("v1"))
            v2 = norm_number(r.get("v2"))
            t0 = get_t0_years(r, "t0")
            # Gate on v1/v2/t0 only — mirror of index.html's
            # `if (!isFinite(v1) || !isFinite(v2) || !isFinite(t0)) return;`.
            # A baseline year is NOT required: production params.csv has none,
            # and `baseline_year_of()` correctly returns NaN there (#219).
            # Gating on it would silently empty every snapshot.
            if any(not math.isfinite(x) for x in (v1, v2, t0)):
                continue

            ice_v1 = norm_number(r.get("ice_v1"))
            ice_v2 = norm_number(r.get("ice_v2"))
            ice_t0 = get_t0_years({**r, "t0": r.get("ice_t0")}, "t0")
            has_ice = all(math.isfinite(x) for x in (ice_v1, ice_v2, ice_t0))

            w = weight_for_row(r, weights)
            if not math.isfinite(w):
                continue

            # CALENDAR-YEAR FIX (2026-06): feed the calendar year directly.
            # See the module docstring and the inv_x_years comment in index.html.
            x = year
            y_bev = bev_share_index(x, v1, v2, t0)

            if math.isfinite(y_bev):
                y_sum += w * y_bev
                w_sum += w

            if has_ice:
                y_ice = ice_share_index(x, ice_v1, ice_v2, ice_t0)
                if math.isfinite(y_ice):
                    y_phev = max(0.0, 1.0 - y_bev - y_ice) if math.isfinite(y_bev) else math.nan
                    ice_sum += w * y_ice
                    ice_w_sum += w
                    if math.isfinite(y_phev):
                        phev_sum += w * y_phev
                        phev_w_sum += w

        xs.append(year)
        bev.append(100.0 * y_sum / w_sum if w_sum > 0 else 0.0)
        ice.append(100.0 * ice_sum / ice_w_sum if ice_w_sum > 0 else math.nan)
        phev.append(100.0 * phev_sum / phev_w_sum if phev_w_sum > 0 else math.nan)

    meta = {
        "n_countries": len(rows),
        "total_weight": int(round(total_weight)) if math.isfinite(total_weight) else 0,
        "latest_data_per": latest_dp or None,
    }
    return xs, bev, ice, phev, meta


# --- Output writers ----------------------------------------------------------

def _fmt_year(y: float) -> str:
    return f"{y:.1f}"


def _fmt_pct(p: float) -> str:
    if not math.isfinite(p):
        return ""
    return f"{p:.4f}"


def write_snapshot_csv(out_path: Path, per_group: dict[str, tuple[list, list, list, list]]) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["group", "year", "bev_share", "ice_share", "phev_share"])
        for group, (xs, bev, ice, phev) in per_group.items():
            for i, x in enumerate(xs):
                w.writerow([group, _fmt_year(x), _fmt_pct(bev[i]), _fmt_pct(ice[i]), _fmt_pct(phev[i])])


def update_index_json(index_path: Path, snapshot_date: str,
                      snapshot_file: str, per_group_meta: dict[str, dict]) -> None:
    """Insert or replace this snapshot's entry, keep entries sorted by date asc."""
    data = {"snapshots": []}
    if index_path.exists():
        try:
            data = json.loads(index_path.read_text(encoding="utf-8"))
            if "snapshots" not in data or not isinstance(data["snapshots"], list):
                data = {"snapshots": []}
        except json.JSONDecodeError:
            data = {"snapshots": []}

    snapshots = [s for s in data["snapshots"] if s.get("date") != snapshot_date]
    snapshots.append({
        "date": snapshot_date,
        "file": snapshot_file,
        "basis": CURVE_BASIS,
        "groups": per_group_meta,
    })
    snapshots.sort(key=lambda s: s.get("date", ""))
    data["snapshots"] = snapshots
    data["updated"] = snapshots[-1]["date"] if snapshots else snapshot_date
    # Any other top-level key already in the file (notably `basis_history`,
    # which documents the #219 seam) is left untouched.

    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


# --- Entry point -------------------------------------------------------------

def write_cohort_snapshot(out_dir: Path, snapshot_date: str, snapshot_file: str,
                          param_rows: list[dict], weights: dict[str, float],
                          groups: dict[str, list[str]], variant: str) -> dict | None:
    """Also write the fixed-cohort frame, if a cohort has been established.

    The cohort is the country set the Time-lapse panel and the GIFs default to.
    It lives in `builder_history/cohort/index.json`, written by
    `rebuild_builder_history.py --cohort`. Without this, a cron run adds an
    all-countries frame with no cohort counterpart, and every consumer silently
    falls back to the all-countries curve while still labelling it as the
    cohort -- which injects exactly the composition artefact the cohort exists
    to remove, into the newest frame.

    The stored cohort list is used **as-is and never recomputed**. Recomputing
    the intersection on each run would let the cohort drift, and two frames on
    different country sets are not comparable -- which is the whole point.
    """
    cdir = out_dir / "cohort"
    cindex = cdir / "index.json"
    if not cindex.is_file():
        print("  note: no cohort/index.json — skipping the cohort frame. "
              "Run scripts/rebuild_builder_history.py --cohort to establish one.")
        return None

    doc = json.loads(cindex.read_text(encoding="utf-8"))
    cohort = doc.get("cohort") or []
    if not cohort:
        print("  note: cohort/index.json carries no cohort list — skipping.")
        return None

    keep = {"".join(c.split()).casefold() for c in cohort}
    present = {"".join(c.split()).casefold() for c in groups.get("world", [])}
    missing = sorted(c for c in cohort
                     if "".join(c.split()).casefold() not in present)
    if missing:
        # Loud on purpose: a cohort country that stops appearing makes every
        # later frame quietly incomparable with the earlier ones.
        print(f"  WARNING: {len(missing)} cohort countries absent from this "
              f"snapshot: {', '.join(missing)}", file=sys.stderr)

    curves: dict[str, tuple[list, list, list, list]] = {}
    meta: dict[str, dict] = {}
    for name, countries in groups.items():
        members = [c for c in countries
                   if "".join(c.split()).casefold() in keep]
        if not members:
            continue
        xs, bev, ice, phev, m = compute_group_curve(
            members, param_rows, weights, variant)
        if m["n_countries"] == 0:
            continue
        curves[name] = (xs, bev, ice, phev)
        meta[name] = m

    if not curves:
        print("  note: cohort produced no rows — skipping the cohort frame.")
        return None

    cdir.mkdir(parents=True, exist_ok=True)
    write_snapshot_csv(cdir / snapshot_file, curves)

    entry = {"date": snapshot_date, "file": snapshot_file, "groups": meta}
    snaps = [e for e in doc.get("snapshots", []) if e.get("date") != snapshot_date]
    snaps.append(entry)
    snaps.sort(key=lambda e: e["date"])
    doc["snapshots"] = snaps
    doc["updated"] = max(e["date"] for e in snaps)
    cindex.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n",
                      encoding="utf-8")

    w = meta.get("world", {})
    print(f"Wrote {cdir / snapshot_file} "
          f"({len(curves)} groups, cohort: {w.get('n_countries')} countries)")
    return meta


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[1] if __doc__ else "")
    p.add_argument("--params", default="params.csv", type=Path,
                   help="Path to params.csv (default: %(default)s)")
    p.add_argument("--weights", default="weights.csv", type=Path,
                   help="Path to weights.csv (default: %(default)s)")
    p.add_argument("--out", default="builder_history", type=Path,
                   help="Output directory (default: %(default)s)")
    p.add_argument("--date", default=None,
                   help="Snapshot date YYYY-MM-DD (default: today UTC)")
    p.add_argument("--variant", default=DEFAULT_VARIANT,
                   help="Variant to aggregate (default: %(default)s)")
    args = p.parse_args(argv)

    if not args.params.exists():
        print(f"ERROR: {args.params} not found", file=sys.stderr)
        return 2
    if not args.weights.exists():
        print(f"ERROR: {args.weights} not found", file=sys.stderr)
        return 2

    snapshot_date = args.date or date_cls.today().isoformat()
    if not ISO_DATE_RE.match(snapshot_date):
        print(f"ERROR: --date must be YYYY-MM-DD, got {snapshot_date!r}", file=sys.stderr)
        return 2

    param_rows = load_params(args.params)
    weights = load_weights(args.weights)
    groups = resolve_groups(param_rows, weights)

    per_group_curves: dict[str, tuple[list, list, list, list]] = {}
    per_group_meta: dict[str, dict] = {}

    for name, countries in groups.items():
        if not countries:
            continue
        xs, bev, ice, phev, meta = compute_group_curve(
            countries, param_rows, weights, normalize_base(args.variant)
        )
        if meta["n_countries"] == 0:
            continue
        per_group_curves[name] = (xs, bev, ice, phev)
        per_group_meta[name] = meta

    if not per_group_curves:
        print("ERROR: no group produced any rows (empty params/weights?)", file=sys.stderr)
        return 1

    snapshot_file = f"{snapshot_date}.csv"
    write_snapshot_csv(args.out / snapshot_file, per_group_curves)
    update_index_json(args.out / "index.json", snapshot_date, snapshot_file, per_group_meta)

    write_cohort_snapshot(args.out, snapshot_date, snapshot_file,
                          param_rows, weights, groups, normalize_base(args.variant))

    world_meta = per_group_meta.get("world", {})
    print(
        f"Wrote {args.out / snapshot_file} "
        f"({len(per_group_curves)} groups, "
        f"world: {world_meta.get('n_countries')} countries, "
        f"total weight {world_meta.get('total_weight'):,}, "
        f"latest data_per {world_meta.get('latest_data_per')})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
