"""TEMPORARY probe (42-adding-a-country.md Phase 0). Removed before merge.

What is inside Traficom's hybrid class 02 (the HEV column): the top makes
and models of new cars by registration year. Writes
probe_out/fi_hev_models.txt. Nothing to data/.
"""
import collections
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_finland_register as fr  # noqa: E402

snap = Path("/tmp/Ajoneuvorekisteri.zip")
fr.fetch_snapshot(snap, force=True)
Path("probe_out").mkdir(exist_ok=True)
out = open("probe_out/fi_hev_models.txt", "w", encoding="utf-8")


def p(*a):
    print(*a, file=out, flush=True)
    print(*a, flush=True)


hev = collections.defaultdict(collections.Counter)
pet = collections.defaultdict(collections.Counter)
first = True
for row in fr.iter_snapshot(snap):
    if first:
        p("columns:", ", ".join(row.keys()))
        first = False
    got = fr.classify(row)
    if not got or got[1] != "whole":
        continue
    period, _, fuel = got
    year = period[:4]
    if year not in ("2019", "2022", "2026"):
        continue
    name = (row.get("merkkiSelvakielinen") or "").strip(), \
        (row.get("kaupallinenNimi") or row.get("mallimerkinta") or "").strip()
    if fuel == "HEV":
        hev[year][name] += 1
    elif fuel == "PETROL":
        pet[year][name] += 1
for year in sorted(hev):
    p(f"\n=== {year}: HEV {sum(hev[year].values())}, pure petrol {sum(pet[year].values())}")
    for m, n in hev[year].most_common(50):
        p(f"{n:6d}  {m[0]} {m[1]}")
    p("top pure-petrol:", "; ".join(f"{m[0]} {m[1]} {n}" for m, n in pet[year].most_common(15)))
