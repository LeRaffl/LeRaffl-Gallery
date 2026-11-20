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

import socket
import time

for attempt in range(12):          # the runner's resolver blipped once (run 66)
    try:
        socket.getaddrinfo("opendata.rdw.nl", 443)
        break
    except OSError as e:
        print(f"DNS attempt {attempt + 1}: {e}; waiting 20 s")
        time.sleep(20)

out = io.StringIO()
with contextlib.redirect_stdout(out):
    fn.backfill_plan("2018-01", "2026-10")
    print("\n== shadow 2026-10 (own pick)")
    fn.shadow_hev("2026-10")
Path("probe_out").mkdir(exist_ok=True)
Path("probe_out/netherlands_plan.txt").write_text(out.getvalue(), encoding="utf-8")
print(out.getvalue())
