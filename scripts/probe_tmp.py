"""TEMPORARY probe (42-adding-a-country.md Phase 0). Removed before merge.

Runs the one-cohort HEV plan against the live RDW register (through the
Socrata edge if opendata.rdw.nl still has no DNS), then writes the register
HEV onto data/Netherlands.csv for the longest hole-free stretch of that
cohort. Output: probe_out/netherlands_plan.txt and the CSV, committed back
to the branch for review.
"""
import contextlib
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_netherlands as fn  # noqa: E402

out = io.StringIO()
try:
    with contextlib.redirect_stdout(out):
        print(f"== fill: cohort {fn.HEV_COHORT}, {fn.HEV_FROM}..2026-10")
        filled = fn.fill_register_hev(start=fn.HEV_FROM, end="2026-10",
                                      cohort=fn.HEV_COHORT, limit=None)
        print(f"filled {len(filled)}: {filled[:3]} .. {filled[-3:]}")
finally:
    Path("probe_out").mkdir(exist_ok=True)
    Path("probe_out/netherlands_fill.txt").write_text(out.getvalue(), encoding="utf-8")
    print(out.getvalue())
