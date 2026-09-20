#!/usr/bin/env python3
"""Compact `builder_history/` into one file per group, for the Time-lapse UI.

    python3 scripts/build_builder_series.py

Why this exists
---------------
`builder_history/<date>.csv` is the archival form: every group, every
0.1-year step, full precision — about 197 KB per snapshot, and 5.8 MB once
the cohort set is counted too. That is the right shape for an archive and
the wrong shape for a browser, which wants *one* group across *all* dates
and would otherwise download all fourteen groups fifteen times over.

So this pivots the data: `builder_history/series/<group>.json` carries that
one group's curve for every snapshot date, both country sets, on a shared
half-year grid at two decimals. About 40 KB per group, and the Time-lapse
tab fetches exactly the one the reader is looking at.

Half-year steps are deliberate. The stored curves are smooth fits sampled
every 0.1 years; at animation speed nobody can see the difference, and the
finer grid costs five times the bytes for it.

The two country sets
--------------------
`all`    — whatever the gallery covered on that date (44 -> 52 countries)
`cohort` — only the countries present on *every* date (44)

Both are kept because they answer different questions, and the difference
between them is itself the point: roughly half of the world curve's apparent
movement over this series is the gallery gaining countries, not the market
changing. See `builder_history/cohort/index.json`.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

REPO = Path(__file__).resolve().parent.parent
HIST = REPO / "builder_history"
OUT = HIST / "series"

# Display names, written into each file as `label` so the browser and the GIF
# renderer read one source instead of each keeping its own copy.
GROUP_LABELS = {
    "world": "World", "eu": "EU", "g7": "G7",
    "western_europe": "Western Europe", "northern_europe": "Northern Europe",
    "southern_europe": "Southern Europe", "eastern_europe": "Eastern Europe",
    "north_america": "North America", "south_america": "South America",
    "americas": "Americas", "asia": "Asia",
    "small_markets": "Small markets", "medium_markets": "Medium markets",
    "big_markets": "Big markets",
}


def label_for(key: str) -> str:
    if key in GROUP_LABELS:
        return GROUP_LABELS[key]
    if key.startswith("country_"):
        # Recover the real spelling from the spotlight list rather than
        # un-slugging, which would turn `usa` into "Usa".
        import snapshot_builder as sb
        for name in sb.SPOTLIGHT_COUNTRIES:
            if sb.country_key(name) == key:
                return name
    return key

STEP = 0.5          # years between samples in the emitted grid
DECIMALS = 2


def read_snapshot(path: Path) -> dict[str, dict[str, dict[float, float]]]:
    """{group: {series: {year: share}}} for one snapshot CSV.

    An empty cell is **skipped, not zeroed**. A group whose members carry no
    ICE fit writes an empty `ice_share`, and a 0.0 there would draw a curve
    claiming "no combustion cars" — the chart-level form of the
    no-split-column invariant in AGENTS.md. A missing year simply has no
    point, and `sample()` turns it into a gap.
    """
    out: dict[str, dict[str, dict[float, float]]] = {}
    with path.open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            g = out.setdefault(r["group"], {"bev": {}, "ice": {}, "phev": {}})
            y = float(r["year"])
            for key, col in (("bev", "bev_share"), ("ice", "ice_share"),
                             ("phev", "phev_share")):
                raw = (r.get(col) or "").strip()
                if raw:
                    g[key][y] = float(raw)
    return out


def grid_for(years: list[float]) -> list[float]:
    lo, hi = min(years), max(years)
    out, y = [], lo
    while y <= hi + 1e-9:
        out.append(round(y, 4))
        y += STEP
    return out


def sample(series: dict[float, float], grid: list[float]) -> list[float | None]:
    """Pick the stored point nearest each grid year, or None if none is close.

    The stored grid is 0.1-year spaced, so `nearest` is always within 0.05 of
    the target; the tolerance only guards against a snapshot with a different
    or truncated range, where inventing a value would be worse than a gap.
    """
    keys = sorted(series)
    out: list[float | None] = []
    for g in grid:
        best = min(keys, key=lambda k: abs(k - g)) if keys else None
        if best is None or abs(best - g) > STEP / 2:
            out.append(None)
        else:
            out.append(round(series[best], DECIMALS))
    return out


def main() -> int:
    index = json.loads((HIST / "index.json").read_text(encoding="utf-8"))
    dates = [s["date"] for s in index["snapshots"]]

    cohort_dir = HIST / "cohort"
    cohort_index = None
    if (cohort_dir / "index.json").is_file():
        cohort_index = json.loads(
            (cohort_dir / "index.json").read_text(encoding="utf-8"))

    # Load every snapshot once, both sets.
    loaded: dict[str, dict] = {}
    for d in dates:
        entry = {"all": read_snapshot(HIST / f"{d}.csv")}
        cpath = cohort_dir / f"{d}.csv"
        if cpath.is_file():
            entry["cohort"] = read_snapshot(cpath)
        loaded[d] = entry

    groups = sorted(loaded[dates[0]]["all"].keys())
    all_years = sorted(loaded[dates[0]]["all"][groups[0]]["bev"].keys())
    grid = grid_for(all_years)

    meta_by_date = {s["date"]: s.get("groups", {}) for s in index["snapshots"]}
    cohort_meta = {}
    if cohort_index:
        cohort_meta = {s["date"]: s.get("groups", {})
                       for s in cohort_index["snapshots"]}

    OUT.mkdir(parents=True, exist_ok=True)
    written = []
    for g in groups:
        frames = []
        for d in dates:
            m = (meta_by_date.get(d) or {}).get(g, {})
            cm = (cohort_meta.get(d) or {}).get(g, {})
            frame = {
                "date": d,
                "n_countries": m.get("n_countries"),
                "total_weight": m.get("total_weight"),
                "data_per": m.get("latest_data_per"),
                "all": {
                    s: sample(loaded[d]["all"][g][s], grid)
                    for s in ("bev", "ice", "phev")
                },
            }
            if "cohort" in loaded[d] and g in loaded[d]["cohort"]:
                frame["cohort"] = {
                    s: sample(loaded[d]["cohort"][g][s], grid)
                    for s in ("bev", "ice", "phev")
                }
                frame["n_cohort"] = cm.get("n_countries")
                frame["cohort_weight"] = cm.get("total_weight")
            frames.append(frame)

        doc = {
            "group": g,
            "label": label_for(g),
            "basis": index.get("basis_history", [{}])[0].get("basis", "calendar_year"),
            "years": grid,
            "n_cohort": (cohort_index or {}).get("n_cohort"),
            "frames": frames,
        }
        path = OUT / f"{g}.json"
        path.write_text(json.dumps(doc, ensure_ascii=False,
                                   separators=(",", ":")) + "\n", encoding="utf-8")
        written.append((g, path.stat().st_size))

    manifest = {
        "groups": [g for g, _ in written],
        "labels": {g: label_for(g) for g, _ in written},
        "dates": dates,
        "years": [grid[0], grid[-1]],
        "step": STEP,
        "n_cohort": (cohort_index or {}).get("n_cohort"),
        "cohort": (cohort_index or {}).get("cohort", []),
    }
    (OUT / "index.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    total = sum(s for _, s in written)
    print(f"  ✓ builder_history/series/ — {len(written)} groups, "
          f"{len(dates)} frames each, {len(grid)} points "
          f"({total/1024:.0f} KB total, "
          f"{max(s for _, s in written)/1024:.0f} KB largest)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
