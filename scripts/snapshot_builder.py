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
The in-page Builder relies on a JavaScript quirk: `Number('') === 0`, so when
the CSV has no `baseline_year` column at all (which is the case in the live
`params.csv`), `baselineYearOf()` silently returns 0, `getT0Years()` returns
`t0_raw + 1`, and the loop iterates `x = year + 1`. The math collapses to
`share(year) = 1 - exp(v1 * (year - t0_raw)^v2)`. We mirror this by making
`norm_number('') -> 0.0` instead of the more idiomatic NaN.
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
        "Vietnam", "Philippines", "Singapore", "Taiwan",
    ],
}

SMALL_MARKET_LIMIT = 50_000
BIG_MARKET_LIMIT = 1_000_000

DEFAULT_VARIANT = "whole"  # the Builder default + what the issue context names

ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
YEAR_MONTH_RE = re.compile(r"^(\d{4})-(\d{2})$")


# --- Number / variant helpers (mirror index.html) ----------------------------

def norm_number(x) -> float:
    """Mirrors the JS `const normNumber = x => Number(String(x||'').trim().replace(',','.'))`.

    Crucially returns 0.0 (NOT NaN) for empty/None inputs, because in JS
    `Number('') === 0` and the in-page Builder math relies on that quirk to
    treat missing baseline_year fields as 0.
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
    """Mirror `baselineYearOf` in index.html. Returns 0.0 for absent fields
    (matching the JS Number('') === 0 quirk that the in-page math depends on)."""
    by = norm_number(r.get("baseline_year"))
    if math.isfinite(by):
        return round(by)
    bd = str(r.get("baseline_date") or "")
    if ISO_DATE_RE.match(bd):
        return int(bd[:4])
    return math.nan


def get_t0_years(r: dict, t0_key: str = "t0") -> float:
    """Mirror `getT0Years` in index.html."""
    base_date = str(r.get("baseline_date") or "")
    base_year = norm_number(r.get("baseline_year"))
    t0_raw = str(r.get(t0_key) or "").strip()
    t0_n = norm_number(t0_raw)

    if math.isfinite(t0_n) and t0_n >= 1800 and (math.isfinite(base_year) or ISO_DATE_RE.match(base_date)):
        if math.isfinite(base_year):
            by = round(base_year)
        else:
            by = int(base_date[:4])
        return (t0_n - by) + 1

    if ISO_DATE_RE.match(t0_raw):
        t0_yf = iso_date_to_year_frac(t0_raw)
        by_frac = base_year if math.isfinite(base_year) else iso_date_to_year_frac(base_date)
        if math.isfinite(by_frac) and math.isfinite(t0_yf):
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
            by = baseline_year_of(r)
            if any(not math.isfinite(x) for x in (v1, v2, t0, by)):
                continue

            ice_v1 = norm_number(r.get("ice_v1"))
            ice_v2 = norm_number(r.get("ice_v2"))
            ice_t0 = get_t0_years({**r, "t0": r.get("ice_t0")}, "t0")
            has_ice = all(math.isfinite(x) for x in (ice_v1, ice_v2, ice_t0))

            w = weight_for_row(r, weights)
            if not math.isfinite(w):
                continue

            x = year - by + 1
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
        "groups": per_group_meta,
    })
    snapshots.sort(key=lambda s: s.get("date", ""))
    data["snapshots"] = snapshots
    data["updated"] = snapshots[-1]["date"] if snapshots else snapshot_date

    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


# --- Entry point -------------------------------------------------------------

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
