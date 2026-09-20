#!/usr/bin/env python3
"""Rebuild `builder_history/` from the parameters git already holds.

Usage
-----
    python scripts/rebuild_builder_history.py --list
    python scripts/rebuild_builder_history.py --dry-run
    python scripts/rebuild_builder_history.py            # rewrite every snapshot
    python scripts/rebuild_builder_history.py --date 2026-06-25

Why this exists (#219, #235-era follow-up)
------------------------------------------
Issue #219 offered two ways to deal with the one-year basis error in the
2026-06-25…2026-09-09 snapshots, and ruled out the better one:

    "Fix the script and rewrite history. `builder_history/` is derived from
     `params.csv` + `weights.csv`, but only *today's* — past snapshots
     captured past parameters […] Cannot be regenerated without a historical
     parameter store, so this is blocked on #220."

**That premise is wrong: git is the historical parameter store.** Both
`params.csv` and `weights.csv` are versioned, so the inputs to any past
snapshot can be recovered exactly with `git show <commit>:<file>`.

Verified before this script was written: regenerating 2026-09-09 from the
params/weights commit of that date reproduces the committed snapshot **to
0.0000 pp** once you account for the known one-year shift — i.e. the committed
file is exactly this script's output with `year` moved by one. So the rebuild
is not an approximation of the old snapshots; it is the same computation with
the basis corrected.

That has two consequences:

  * the offset band can be repaired rather than merely labelled, and
  * the series can be extended **backwards**, because params/weights exist in
    git from long before the first snapshot was ever taken.

How a date is resolved
----------------------
For each target date, the newest commit touching `params.csv` (and separately
`weights.csv`) at or before 23:59:59 on that date. They are usually the same
commit — a render writes both — but not always, so they are resolved
independently rather than assumed to move together.

Both files must exist. `weights.csv` first appears 2025-12-22, which is the
hard floor for a *weighted* aggregate; earlier params-only dates are skipped
rather than silently aggregated unweighted, because an unweighted curve is a
different quantity wearing the same name.

What this does NOT do
---------------------
It does not invent snapshots for dates no one asked for. The date list is
explicit (`SNAPSHOT_DATES`) so the series stays a deliberate record rather
than an arbitrarily dense resampling of git.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from datetime import date as date_cls
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import snapshot_builder as sb  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
OUT_DIR = REPO / "builder_history"

# weights.csv's first commit. Before this a weighted aggregate is impossible.
WEIGHTS_FLOOR = "2025-12-22"

# The snapshots the series is meant to carry.
#
#   * the ten dates already in builder_history/ — preserved because each one
#     records a run that really happened, and renaming history is worse than
#     correcting it;
#   * a monthly backfill on the 25th (the snapshot-builder cron day) from the
#     first date weights.csv exists, which is what turns ten scattered points
#     into a series you can actually watch move.
SNAPSHOT_DATES = [
    # backfill — monthly, matching .github/workflows/snapshot-builder.yml
    "2025-12-25", "2026-01-25", "2026-02-25", "2026-03-25", "2026-04-25",
    # the runs that actually happened
    "2026-05-20", "2026-05-21", "2026-05-25", "2026-05-31",
    "2026-06-25", "2026-07-01", "2026-07-25", "2026-08-25",
    "2026-09-04", "2026-09-09",
]


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO, check=True, capture_output=True, text=True
    ).stdout


def commit_for(path: str, on: str) -> str | None:
    """Newest commit touching `path` at or before the end of `on`."""
    out = git("rev-list", "-1", f"--before={on} 23:59:59", "origin/master",
              "--", path).strip()
    return out or None


def blob_at(commit: str, path: str) -> str:
    return git("show", f"{commit}:{path}")


def norm_country(name: str) -> str:
    """Key a country by identity rather than by spelling.

    `params.csv` carried "New Zealand" until 2026-01, "NewZealand" through
    2026-03, and "New Zealand" again after. A cohort built on the raw strings
    therefore drops a country that was present the whole time, which is
    exactly the kind of artefact the cohort exists to remove.
    """
    return "".join(name.split()).casefold()


def load_at(target: str):
    """params/weights as they stood on `target`, or None if either is missing."""
    pc = commit_for("params.csv", target)
    wc = commit_for("weights.csv", target)
    if not pc or not wc:
        return None
    with tempfile.TemporaryDirectory() as tmp:
        tmpd = Path(tmp)
        (tmpd / "params.csv").write_text(blob_at(pc, "params.csv"), encoding="utf-8")
        (tmpd / "weights.csv").write_text(blob_at(wc, "weights.csv"), encoding="utf-8")
        rows = sb.load_params(tmpd / "params.csv")
        weights = sb.load_weights(tmpd / "weights.csv")
    return pc, wc, rows, weights


def cohort_countries(dates: list[str]) -> list[str]:
    """Countries carried by *every* snapshot date, matched on identity.

    The `world` group grows from 44 to 52 countries across the series, so a
    naive time-lapse animates the gallery being built as much as the market
    moving. Restricting every frame to the countries common to all of them
    separates the two: what is left can only be data revision and new months.
    """
    seen: list[dict[str, str]] = []
    for d in dates:
        got = load_at(d)
        if got is None:
            continue
        _, _, rows, weights = got
        world = sb.resolve_groups(rows, weights)["world"]
        # keep one real spelling per identity, preferring the newest seen
        seen.append({norm_country(c): c for c in world})
    if not seen:
        return []
    keys = set.intersection(*(set(m) for m in seen))
    # Spell them as the most recent snapshot does.
    return sorted(seen[-1][k] for k in keys)


def rebuild_one(target: str, out_dir: Path, dry_run: bool = False,
                cohort: list[str] | None = None) -> dict | None:
    """Regenerate one snapshot from the params/weights git held on that date.

    With `cohort`, every group is intersected with that country set first, so
    the frame answers "what did we estimate for *these* countries" rather than
    "for whatever we happened to cover".
    """
    if target < WEIGHTS_FLOOR:
        print(f"  skip {target} — before weights.csv exists ({WEIGHTS_FLOOR})")
        return None

    got = load_at(target)
    if got is None:
        pc = commit_for("params.csv", target)
        wc = commit_for("weights.csv", target)
        print(f"  skip {target} — params={pc or 'missing'} weights={wc or 'missing'}")
        return None

    pc, wc, rows, weights = got
    groups = sb.resolve_groups(rows, weights)

    if cohort is not None:
        keep = {norm_country(c) for c in cohort}
        groups = {n: [c for c in cs if norm_country(c) in keep]
                  for n, cs in groups.items()}

    curves, meta = {}, {}
    for name, countries in groups.items():
        if not countries:
            continue
        xs, bev, ice, phev, m = sb.compute_group_curve(
            countries, rows, weights, sb.DEFAULT_VARIANT)
        if m["n_countries"] == 0:
            continue
        curves[name] = (xs, bev, ice, phev)
        meta[name] = m

    if not curves:
        print(f"  skip {target} — no group produced rows")
        return None

    world = meta.get("world", {})
    print(f"  {target}  params@{pc[:8]} weights@{wc[:8]}  "
          f"{len(curves):2d} groups, world {world.get('n_countries')} countries, "
          f"weight {world.get('total_weight'):,}, data_per {world.get('latest_data_per')}"
          + ("  [dry-run]" if dry_run else ""))

    if not dry_run:
        sb.write_snapshot_csv(out_dir / f"{target}.csv", curves)
    return meta


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--out", default=OUT_DIR, type=Path)
    p.add_argument("--date", action="append",
                   help="Rebuild only this date (repeatable). Default: all.")
    p.add_argument("--dry-run", action="store_true",
                   help="Resolve and compute, write nothing.")
    p.add_argument("--list", action="store_true",
                   help="Show the target dates and their resolved commits, then exit.")
    p.add_argument("--cohort", action="store_true",
                   help="Also write builder_history/cohort/, every frame "
                        "restricted to the countries common to all dates.")
    args = p.parse_args(argv)

    targets = args.date or SNAPSHOT_DATES

    if args.list:
        for t in targets:
            pc, wc = commit_for("params.csv", t), commit_for("weights.csv", t)
            print(f"  {t}  params={pc[:8] if pc else 'MISSING':8s}  "
                  f"weights={wc[:8] if wc else 'MISSING'}")
        return 0

    args.out.mkdir(parents=True, exist_ok=True)
    built: dict[str, dict] = {}
    for t in targets:
        m = rebuild_one(t, args.out, dry_run=args.dry_run)
        if m:
            built[t] = m

    if args.dry_run:
        print(f"\n{len(built)} snapshot(s) would be written.")
        return 0

    # Rewrite index.json from scratch: every entry is now on one basis, so the
    # per-entry `basis` field stays (a consumer should not have to know that
    # the answer is currently uniform) but `basis_history` becomes a record of
    # a closed episode rather than a live seam.
    index = args.out / "index.json"
    snapshots = [{
        "date": d,
        "file": f"{d}.csv",
        "basis": sb.CURVE_BASIS,
        "groups": built[d],
    } for d in sorted(built)]

    index.write_text(json.dumps({
        "basis_history": [{
            "basis": sb.CURVE_BASIS,
            "from": min(built) if built else None,
            "issue": 219,
            "note": (
                "Every snapshot is on one basis (z = year - t0), because the "
                "whole series is regenerated by scripts/rebuild_builder_history.py "
                "from the params.csv/weights.csv git holds for each date. The "
                "2026-06-25…2026-09-09 files previously carried a one-year "
                "offset (calendar_year_plus_1); they were rebuilt rather than "
                "annotated, so no correction is needed when comparing any two "
                "snapshots."
            ),
        }],
        "snapshots": snapshots,
        "updated": max(built) if built else None,
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"\nWrote {len(snapshots)} snapshots + {index}")
    if snapshots:
        print(f"  span {snapshots[0]['date']} .. {snapshots[-1]['date']}")

    if args.cohort:
        cohort = cohort_countries(targets)
        print(f"\nCohort: {len(cohort)} countries common to all {len(targets)} dates")
        cdir = args.out / "cohort"
        cdir.mkdir(parents=True, exist_ok=True)
        cbuilt: dict[str, dict] = {}
        for t in targets:
            m = rebuild_one(t, cdir, cohort=cohort)
            if m:
                cbuilt[t] = m
        (cdir / "index.json").write_text(json.dumps({
            "basis": sb.CURVE_BASIS,
            "cohort": cohort,
            "n_cohort": len(cohort),
            "note": (
                "Every frame is restricted to the countries present in all "
                "snapshot dates, so movement here is data revision and new "
                "months only -- not the gallery gaining countries. Countries "
                "are matched on identity, not spelling: params.csv carried "
                "both 'New Zealand' and 'NewZealand' during 2026-01..03."
            ),
            "snapshots": [{
                "date": d,
                "file": f"{d}.csv",
                "groups": cbuilt[d],
            } for d in sorted(cbuilt)],
            "updated": max(cbuilt) if cbuilt else None,
        }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"Wrote {len(cbuilt)} cohort snapshots + {cdir / 'index.json'}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
