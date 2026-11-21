"""TEMPORARY probe (42-adding-a-country.md Phase 0). Removed before merge.

The register's monthly fuel split for the HEV back-estimate: every month
2018-01..2024-06, both cohorts (export_indicator=Nee, and the
since-exported plates put back), counted with plate_bucket. Writes
probe_out/nl_register_split.csv (period, cohort, plates, BEV, PHEV, HEV,
PETROL, DIESEL, OTHERS). Nothing is written to data/.
"""
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_netherlands as fn  # noqa: E402

session = fn.rdw_session()
Path("probe_out").mkdir(exist_ok=True)
out = Path("probe_out/nl_register_split.csv")
cols = ["BEV", "PHEV", "HEV", "PETROL", "DIESEL", "OTHERS"]
with open(out, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["period", "cohort", "plates"] + cols)
    y, m = 2018, 1
    while (y, m) <= (2024, 6):
        period = f"{y}-{m:02d}"
        cars = fn.fetch_new_cars(session, period, "Whole", exported=None)
        fuels = fn.fetch_fuels(session, [c["kenteken"] for c in cars])
        exported = {c["kenteken"] for c in fn.fetch_new_cars(session, period, "Whole", exported=True)}
        for cohort, plates in (("with_exports", [c["kenteken"] for c in cars]),
                               ("stay", [c["kenteken"] for c in cars if c["kenteken"] not in exported])):
            counts = fn.count_plates({p: fuels.get(p, []) for p in plates})
            w.writerow([period, cohort, len(plates)] + [counts[c] for c in cols])
        f.flush()
        print(period, len(cars), "plates,", len(exported), "exported", flush=True)
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
