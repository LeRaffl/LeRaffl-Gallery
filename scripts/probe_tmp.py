"""TEMPORARY probe (42-adding-a-country.md Phase 0). Removed before merge.

The Finland HEV backfill, run where ACEA and Traficom are reachable:
ACEA's monthly Finland row 2022-01..2026-10, then the Traficom register
snapshot for 2025-01 on. Also prints ACEA against the register for the
months both cover, so the 2025-01 seam can be checked. Writes
data/Finland.csv and probe_out/finland_backfill.txt (committed for review).
"""
import contextlib
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_finland_register as fr  # noqa: E402

out = io.StringIO()
with contextlib.redirect_stdout(out):
    before = fr.whole_rows()
    acea_seen = {}
    real = fr.apply_acea

    def spy(period, acea, csv_path=fr.CSV_PATH):
        acea_seen[period] = acea
        return real(period, acea, csv_path)
    fr.apply_acea = spy
    print("== ACEA backfill")
    fr.acea_backfill("2022-01", "2026-10")
    fr.apply_acea = real
    print("\n== Traficom register")
    snap = fr.fetch_snapshot(Path("/tmp/Ajoneuvorekisteri.zip"), force=True)
    fr.apply_register(snap)
    print("\n== ACEA vs register / StatFin, 2025-01 on")
    after = fr.whole_rows()
    for p, row in sorted(after.items()):
        if p < "2022-01":
            continue
        a = acea_seen.get(p)
        line = (f"{p} StatFin T{float(row['TOTAL']):.0f} | {fr.split_kind(row) or 'blank':8s} "
                f"HEV {row['HEV'] or '-':>7s} PET {row['PETROL']:>7s} OTH {row['OTHERS']:>6s}")
        if a:
            line += (f" | ACEA T{a['TOTAL']:.0f} B{a['BEV']:.0f} P{a['PHEV']:.0f} "
                     f"HEV {a['HEV']:.0f} PET {a['PETROL']:.0f} DIE {a['DIESEL']:.0f}")
        print(line)
Path("probe_out").mkdir(exist_ok=True)
Path("probe_out/finland_backfill.txt").write_text(out.getvalue(), encoding="utf-8")
print(out.getvalue())
