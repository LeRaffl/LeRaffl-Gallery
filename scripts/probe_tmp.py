"""TEMPORARY probe (42-adding-a-country.md Phase 0). Removed before merge.

Runs the one-cohort HEV plan against the live RDW register, then writes the
register HEV onto data/Netherlands.csv for the longest hole-free stretch of
that cohort. Output: probe_out/netherlands_plan.txt and the CSV (committed
back to the branch for review).
"""
import contextlib
import io
import socket
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_netherlands as fn  # noqa: E402

for attempt in range(180):          # opendata.rdw.nl had no DNS record for a while
    try:
        socket.getaddrinfo("opendata.rdw.nl", 443)
        print(f"DNS ok after {attempt} wait(s)")
        break
    except OSError as e:
        if attempt % 10 == 0:
            print(f"DNS attempt {attempt + 1}: {e}; waiting")
        time.sleep(20)
else:
    sys.exit("opendata.rdw.nl never resolved")

out = io.StringIO()
with contextlib.redirect_stdout(out):
    plan = fn.backfill_plan("2018-01", "2026-10")
    window = fn.window_cohort(plan)
    run = fn.fill_run(plan) if window else None
    print(f"\n== fill: cohort {window}, run {run}")
    if run:
        filled = fn.fill_register_hev(start=run[0], end=run[1], cohort=window, limit=None)
        print(f"filled {len(filled)}: {filled[:3]} .. {filled[-3:]}")
Path("probe_out").mkdir(exist_ok=True)
Path("probe_out/netherlands_plan.txt").write_text(out.getvalue(), encoding="utf-8")
print(out.getvalue())
