#!/usr/bin/env python3
"""Regression tests for scripts/fetch_fleet_mileage.py (no network).

Run:  python scripts/test_fetch_fleet_mileage.py

Pins the SSB and Eurostat JSON-stat decoding (fuel codes, registration
concepts, missing cells), the gate that keeps a petrol figure that may hide
the hybrids out of the file, the precedence between sources, and the
committed file the Energy view's kilometres come from.
"""
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_fleet_mileage as fm  # noqa: E402

checks = []


def check(ok, msg):
    checks.append((bool(ok), msg))


def ssb(cells, years=("2024", "2025")):
    """Tiny JSON-stat2 document in SSB's dimension order; cells[(fuel, content, year)] = value."""
    dims = {"Kjoretoytype": ["15"], "DrivstoffType": ["0", "1", "18", "13"],
            "ContentsCode": [fm.SSB_TOTAL, fm.SSB_CONTENT], "Tid": list(years)}
    ids = list(dims)
    values = [cells.get((f, c, y)) for f in dims["DrivstoffType"] for c in dims["ContentsCode"] for y in dims["Tid"]]
    return {"id": ids, "size": [len(dims[k]) for k in ids],
            "dimension": {k: {"category": {"index": {v: i for i, v in enumerate(dims[k])}}} for k in ids},
            "value": values}


doc = ssb({("0", fm.SSB_CONTENT, "2025"): 11350, ("0", fm.SSB_TOTAL, "2025"): 36091.1,
           ("1", fm.SSB_CONTENT, "2025"): 7622, ("1", fm.SSB_TOTAL, "2025"): 5987.0,
           ("18", fm.SSB_CONTENT, "2025"): 13453, ("18", fm.SSB_TOTAL, "2025"): 13227,
           ("18", fm.SSB_CONTENT, "2024"): 250,                       # a handful of cars: noise
           ("13", fm.SSB_CONTENT, "2025"): 9000})                     # hydrogen: not a class we carry
rows = fm.parse_ssb(doc)
by = {(r["year"], r["fuel"]): r for r in rows}
check(set(by) == {(2025, "ALL"), (2025, "PETROL"), (2025, "BEV")}, f"fuel codes map to our classes; nulls, noise and other fuels dropped: {sorted(by)}")
check(by[(2025, "BEV")]["km_per_car"] == 13453 and by[(2025, "BEV")]["total_mkm"] == "13227", "average and total land in their own columns")
check(by[(2025, "ALL")]["total_mkm"] == "36091.1" and by[(2025, "PETROL")]["total_mkm"] == "5987", "totals keep their decimals, no trailing zeros")
check(all(r["country"] == "Norway" and r["source"] == fm.SSB_SOURCE for r in rows), "rows are Norway's and carry the SSB source")

# --- Eurostat: vehicle-km by fuel --------------------------------------------
def jsonstat(dims, cells):
    ids = list(dims)
    size = [len(dims[k]) for k in ids]

    def flat(key):
        f = 0
        for k, sz, v in zip(ids, size, key):
            f = f * sz + dims[k].index(v)
        return str(f)
    return {"id": ids, "size": size,
            "dimension": {k: {"category": {"index": {v: i for i, v in enumerate(dims[k])}}} for k in ids},
            "value": {flat(k): v for k, v in cells.items()}}


GEO = {"SE": "Sweden", "DE": "Germany", "NL": "Netherlands", "NO": "Norway", "CH": "Switzerland", "AT": "Austria"}
VA = {"freq": ["A"], "mot_nrg": ["TOTAL", *fm.VEHAGE_ALL_FUELS], "age": ["TOTAL", "Y_LT2"],
      "vehicle": ["CAR", "LOR"], "unit": ["MIO_VKM"], "geo": ["SE", "DE", "NL", "PL"], "time": ["2014", "2024"]}
va = lambda f, g, v, age="TOTAL", veh="CAR", y="2024": {("A", f, age, veh, "MIO_VKM", g, y): v}  # noqa: E731
cells = {}
for c in [va("TOTAL", "SE", 1000), va("PET", "SE", 400), va("DIE", "SE", 300), va("ELC", "SE", 100),
          va("ELC_PET_HYB_PI", "SE", 150), va("ELC_DIE_HYB_PI", "SE", 10), va("OTH", "SE", 40),
          va("TOTAL", "DE", 1000), va("PET", "DE", 480), va("DIE", "DE", 380),            # 86 %: the rest is elsewhere
          va("TOTAL", "NL", 1000), va("PET", "NL", 800), va("DIE", "NL", 200),            # 100 %: petrol hides the hybrids
          va("TOTAL", "PL", 1000), va("PET", "PL", 500),                                  # not a fleet country
          va("TOTAL", "SE", 5, age="Y_LT2"), va("TOTAL", "SE", 7, veh="LOR"),             # another age / vehicle
          va("TOTAL", "SE", 900, y="2014")]:                                              # before EUROSTAT_FROM
    cells.update(c)
ev = fm.parse_vehage(jsonstat(VA, cells), GEO)
got = {(r["country"], r["year"], r["fuel"]): r["total_mkm"] for r in ev}
check(got == {("Sweden", 2024, "ALL"): "1000", ("Sweden", 2024, "PETROL"): "400", ("Sweden", 2024, "DIESEL"): "300",
              ("Sweden", 2024, "BEV"): "100", ("Sweden", 2024, "HYBRID"): "160",
              ("Germany", 2024, "ALL"): "1000", ("Germany", 2024, "PETROL"): "480", ("Germany", 2024, "DIESEL"): "380",
              ("Netherlands", 2024, "ALL"): "1000"},
      f"by-fuel rows only where petrol and diesel cannot be hiding the hybrids; hybrid codes summed: {sorted(got)}")
check(all(r["source"] == fm.VEHAGE_SOURCE and r["km_per_car"] == "" for r in ev), "Eurostat rows carry totals only, and their source")

VE = {"freq": ["A"], "mot_nrg": ["TOTAL", "PET"], "regisveh": ["TERNAT_REG", "TERNAT_REGNAT", "TER_REGNAT"],
      "vehicle": ["CAR"], "unit": ["MIO_VKM"], "geo": ["NO", "CH", "AT"], "time": ["2024"]}
ve = lambda rv, g, v, f="TOTAL": {("A", f, rv, "CAR", "MIO_VKM", g, "2024"): v}  # noqa: E731
cells = {}
for c in [ve("TER_REGNAT", "NO", 36000), ve("TERNAT_REGNAT", "NO", 35500), ve("TERNAT_REG", "NO", 36100),
          ve("TERNAT_REGNAT", "CH", 49912), ve("TERNAT_REG", "CH", 57000), ve("TERNAT_REG", "AT", 73000),
          ve("TER_REGNAT", "NO", 9000, f="PET")]:
    cells.update(c)
tv = {r["country"]: r for r in fm.parse_veh(jsonstat(VE, cells), GEO)}
check(set(tv) == {"Norway", "Switzerland"}, "traffic on national roads incl. foreign cars (TERNAT_REG) is never used: no Austria")
check(tv["Norway"]["total_mkm"] == "36000" and tv["Norway"]["source"] == fm.VEH_SOURCES["TER_REGNAT"], "the national-fleet concept is preferred")
check(tv["Switzerland"]["source"] == fm.VEH_SOURCES["TERNAT_REGNAT"] and "abroad" in tv["Switzerland"]["notes"],
      "the national-territory-only fallback is labelled as such")
check(all(r["fuel"] == "ALL" for r in tv.values()), "road_tf_veh contributes all-car totals only")

# --- precedence: national office > by-fuel table > totals only ---------------
no_ssb = {"country": "Norway", "year": 2024, "fuel": "ALL", "km_per_car": 11215, "total_mkm": "35442.9", "source": fm.SSB_SOURCE, "notes": ""}
no_va = {"country": "Norway", "year": 2024, "fuel": "ALL", "km_per_car": "", "total_mkm": "35400", "source": fm.VEHAGE_SOURCE, "notes": ""}
merged0 = fm.upsert([no_ssb, no_va, tv["Norway"]], [], {fm.SSB_SOURCE, *fm.EUROSTAT_SOURCES})
check(len(merged0) == 1 and merged0[0]["source"] == fm.SSB_SOURCE, "one row per key; the first (preferred) source wins")

curated = [{"country": "Germany", "year": "2025", "fuel": "BEV", "km_per_car": "11312", "total_mkm": "", "source": "KBA", "notes": "n"},
           {"country": "Norway", "year": "2025", "fuel": "BEV", "km_per_car": "1", "total_mkm": "", "source": "hand", "notes": ""},
           {"country": "Norway", "year": "2019", "fuel": "ALL", "km_per_car": "999", "total_mkm": "", "source": fm.SSB_SOURCE, "notes": ""}]
merged = fm.upsert(rows, curated, fm.SSB_SOURCE)
key = {(r["country"], int(r["year"]), r["fuel"]): r for r in merged}
check(key[("Germany", 2025, "BEV")]["source"] == "KBA", "a curated row of another country is kept")
check(key[("Norway", 2025, "BEV")]["source"] == "hand", "a fetched row never overwrites another source's row with the same key")
check(("Norway", 2019, "ALL") not in key, "this script's own stale rows are replaced, not accumulated")
check([r["country"] for r in merged] == sorted(r["country"] for r in merged), "output is sorted by country")
text = fm.to_csv(merged)
check(text.splitlines()[0] == ",".join(fm.COLUMNS) and fm.to_csv(fm.upsert(rows, merged, fm.SSB_SOURCE)) == text, "writing is idempotent")

# --- the committed file ------------------------------------------------------
with fm.OUT_PATH.open(newline="", encoding="utf-8") as fh:
    live = list(csv.DictReader(fh))
latest = {}
for r in live:
    latest[(r["country"], r["fuel"])] = r
check(len({r["country"] for r in live}) >= 15 and {"Norway", "Germany", "Sweden", "France"} <= {r["country"] for r in live},
      "the file covers 15+ countries")
check(all(r["source"] == fm.SSB_SOURCE or r["source"] in fm.EUROSTAT_SOURCES for r in live),
      "every committed row is fetched from a primary source (no hand-entered figures)")
de = {r["fuel"]: float(r["total_mkm"]) for r in live if r["country"] == "Germany" and r["year"] == "2024"}
check(abs(de["ALL"] - 594136) < 1 and de["PETROL"] + de["DIESEL"] < fm.FUELS_COMPLETE * de["ALL"],
      "Germany 2024 = 594.1 bn km (the KBA figure), petrol + diesel visibly short of it")
nl = {r["fuel"] for r in live if r["country"] == "Netherlands"}
check(nl == {"ALL"}, f"Netherlands: totals only (its petrol figure includes the hybrids): {nl}")
check(all(r["fuel"] in fm.FUELS for r in live), "only known fuel classes")
check(all(r["km_per_car"] == "" or fm.MIN_KM <= float(r["km_per_car"]) <= fm.MAX_KM for r in live), "per-car averages are plausible")
check(all(r["km_per_car"] or r["total_mkm"] for r in live), "every row carries an average or a total")
check(all(r["source"] for r in live), "every row names its source")
latest = {k: r for k, r in latest.items() if r["km_per_car"]}
no = lambda f: float(latest[("Norway", f)]["km_per_car"])  # noqa: E731
check(no("PETROL") < no("ALL") < no("BEV"), "Norway: petrol cars are driven least, battery cars most (the point of the file)")

bad = [msg for ok, msg in checks if not ok]
for msg in bad:
    print("FAIL:", msg)
print(f"{len(checks) - len(bad)}/{len(checks)} passed")
sys.exit(1 if bad else 0)
