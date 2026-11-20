"""TEMPORARY probe (42-adding-a-country.md Phase 0). Removed before merge.

Runs the one-cohort HEV backfill plan against the live RDW register and
saves its output to probe_out/netherlands_plan.txt. Writes nothing to data/.
"""
import contextlib
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_netherlands as fn  # noqa: E402

out = io.StringIO()
with contextlib.redirect_stdout(out):
    fn.backfill_plan("2018-01", "2026-10")
Path("probe_out").mkdir(exist_ok=True)
Path("probe_out/netherlands_plan.txt").write_text(out.getvalue(), encoding="utf-8")
print(out.getvalue())
