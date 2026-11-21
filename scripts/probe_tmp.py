"""TEMPORARY probe (42-adding-a-country.md Phase 0). Removed before merge.

What is inside RDW's NOVC-HEV class: the top models per month among new cars
still in the country, and per model the median electric power from the
fuel table (a full hybrid drives on 50-90 kW electric, a 48 V mild hybrid
has 10-20 kW). Writes probe_out/nl_hev_models.txt. Nothing to data/.
"""
import collections
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_netherlands as fn  # noqa: E402

s = fn.rdw_session()
Path("probe_out").mkdir(exist_ok=True)
out = open("probe_out/nl_hev_models.txt", "w", encoding="utf-8")


def p(*a):
    print(*a, file=out, flush=True)
    print(*a, flush=True)


for period in ("2019-06", "2022-06", "2026-09"):
    cars = fn.fetch_new_cars(s, period, "Whole", exported=False)
    model = {c["kenteken"]: (c.get("merk") or "", c.get("handelsbenaming") or "") for c in cars}
    fuels = fn.fetch_fuels(s, list(model))
    hev = [k for k in model if fn.plate_bucket(fuels.get(k, [])) == "HEV"]
    pet = [k for k in model if fn.plate_bucket(fuels.get(k, [])) == "PETROL"]
    full = collections.defaultdict(list)
    for i in range(0, len(hev), fn.FUEL_BATCH):
        inlist = ",".join(f"'{x}'" for x in hev[i:i + fn.FUEL_BATCH])
        for r in fn.rdw_get(s, fn.RDW_FUEL, {"$where": f"kenteken in({inlist})", "$limit": fn.PAGE}):
            full[r["kenteken"]].append(r)
    keys = sorted({k for rows in full.values() for r in rows for k in r})
    p(f"\n=== {period}: {len(cars)} cars, HEV {len(hev)}, pure petrol {len(pet)}")
    p("fuel-table fields:", ", ".join(keys))
    elec = {}
    for k, rows in full.items():
        vals = []
        for r in rows:
            for f in ("netto_max_vermogen_elektrisch", "nominaal_continu_maximumvermogen"):
                try:
                    vals.append(float(r[f]))
                except (KeyError, TypeError, ValueError):
                    pass
        if vals:
            elec[k] = max(vals)
    cnt = collections.Counter(model[k] for k in hev)
    p(f"plates with an electric power figure: {len(elec)} of {len(hev)}")
    p("units  model  | median electric kW (n with figure)")
    for m, n in cnt.most_common(60):
        kw = [elec[k] for k in hev if model[k] == m and k in elec]
        med = f"{statistics.median(kw):.0f} kW ({len(kw)})" if kw else "-"
        p(f"{n:5d}  {m[0]} {m[1]}  | {med}")
    small = sum(1 for v in elec.values() if v < 25)
    p(f"HEV plates with electric power < 25 kW: {small} of {len(elec)} with a figure")
    pc = collections.Counter(model[k] for k in pet)
    p("top pure-petrol models:", "; ".join(f"{m[0]} {m[1]} {n}" for m, n in pc.most_common(15)))
