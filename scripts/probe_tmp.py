"""TEMPORARY probe (42-adding-a-country.md Phase 0). Removed before merge.

The Traficom register's monthly fuel split for the HEV back-estimate: every
month in the snapshot (Whole cohort, M1+M1G, first use in the registration
month). Writes probe_out/fi_register_split.csv. Nothing written to data/.
"""
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_finland_register as fr  # noqa: E402

snap = fr.fetch_snapshot(Path("/tmp/Ajoneuvorekisteri.zip"), force=True)
tallied = fr.tally(fr.iter_snapshot(snap))
Path("probe_out").mkdir(exist_ok=True)
with open("probe_out/fi_register_split.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["period", "plates"] + list(fr.FUELS))
    for period in sorted(tallied):
        whole = tallied[period].get("whole")
        if not whole or period < "2010-01":
            continue
        w.writerow([period, sum(whole.values())] + [whole.get(k, 0) for k in fr.FUELS])
print("done")
