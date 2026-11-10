#!/usr/bin/env python3
"""Regression tests for scripts/build_fleet_calibration.py (no network).

Run:  python scripts/test_build_fleet_calibration.py

The calibration is arithmetic on two files, and every way it can go wrong is
silent: a half-reported year understates registrations and inflates attrition,
a blank fuel column read as zero invents a petrol/diesel split, a quarterly
file counted as monthly drops every year. These cases pin the stock-flow
identity, the completeness gates, the 12-month inflow mix and the file itself.
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_fleet_calibration as bc  # noqa: E402

FLEET_HEADER = ("country,variant,year,source,BEV,PHEV,EREV,HEV,MHEV,PETROL,DIESEL,"
                "GAS,CNG,LPG,FLEXFUEL,ETHANOL,OTHERS,TOTAL,notes")
REG_HEADER = "period,time_interval,variant,source,BEV,PHEV,HEV,PETROL,DIESEL,OTHERS,TOTAL,notes"

checks = []


def check(ok, msg):
    checks.append((bool(ok), msg))


def fleet_row(country, year, bev, petrol, diesel, total="", variant="Whole", phev="", hev=""):
    return f"{country},{variant},{year},,{bev},{phev},,{hev},,{petrol},{diesel},,,,,,0,{total},"


def monthly(year, bev, phev, hev, petrol, diesel, total, months=range(1, 13), variant="Whole"):
    return [f"{year}-{m:02d},monthly,{variant},src,{bev},{phev},{hev},{petrol},{diesel},0,{total},"
            for m in months]


def world(fleet_lines, reg_files):
    d = Path(tempfile.mkdtemp())
    (d / "fleet.csv").write_text(FLEET_HEADER + "\n" + "\n".join(fleet_lines) + "\n", encoding="utf-8")
    (d / "data").mkdir()
    for name, (header, lines) in reg_files.items():
        (d / "data" / f"{name}.csv").write_text(header + "\n" + "\n".join(lines) + "\n", encoding="utf-8")
    return bc.build(d / "fleet.csv", d / "data")["countries"]


# --- 1. the stock-flow identity ------------------------------------------
# Stock 1,000,000 flat; 60,000 registered a year -> 60,000 left: 6.0 %.
fleet = [fleet_row("Aland", y, 10000 + 5000 * (y - 2019), 600000, 390000 - 5000 * (y - 2019))
         for y in range(2019, 2026)]
reg = []
for y in range(2020, 2026):
    reg += monthly(y, 500, 100, 400, 2500, 1500, 5000)
out = world(fleet, {"Aland": (REG_HEADER, reg)})["Aland"]
a = out["attrition"]
check(abs(a["rate"] - 0.06) < 1e-9, f"attrition = (s0 + reg - s1) / s0 = 0.06, got {a['rate']}")
check((a["n"], a["from"], a["to"]) == (5, 2021, 2025), f"median over the last 5 stock years, got {a}")
# BEV: 6,000 registered, stock +5,000 -> 1,000 left of the year-start stock.
check(abs(a["by_fuel"]["BEV"] - 1000 / 30000) < 0.02, f"per-fuel BEV attrition, got {a['by_fuel']}")

# --- 2. the inflow mix: shares of TOTAL - BEV - PHEV -----------------------
m = out["inflow_mix"]
check(m["window"] == "2025-01..2025-12", f"mix window = last 12 months, got {m['window']}")
check(abs(m["HEV"] - 400 / 4400) < 1e-3 and abs(m["PETROL"] - 2500 / 4400) < 1e-3
      and abs(m["DIESEL"] - 1500 / 4400) < 1e-3, f"mix shares of the combustion side, got {m}")
check(abs(m["HEV"] + m["PETROL"] + m["DIESEL"] + m["OTHERS"] - 1) < 1e-3, "mix adds up to 1")

# --- 3. registrations by year, incl. the combustion side -------------------
r = out["reg_by_year"]
check(r["BEV"]["2025"] == 6000 and r["HEV"]["2024"] == 4800, f"yearly BEV / HEV registrations, got {r}")
check(r["COMBUSTION"]["2025"] == 12 * (5000 - 500 - 100 - 400),
      f"COMBUSTION = TOTAL - BEV - PHEV - HEV, got {r['COMBUSTION']['2025']}")

# --- 4. an incomplete year is not a year -----------------------------------
reg_gap = []
for y in range(2020, 2026):
    reg_gap += monthly(y, 500, 100, 400, 2500, 1500, 5000,
                       months=range(1, 13) if y != 2023 else range(1, 10))
gap = world(fleet, {"Aland": (REG_HEADER, reg_gap)})["Aland"]
check("2023" not in gap["attrition"]["by_year"], "a 9-month year yields no attrition figure")
check(gap["attrition"]["n"] == 4, f"...and the median runs over the other four, got {gap['attrition']['n']}")
check("2023" not in gap["reg_by_year"]["BEV"], "a 9-month year is not in reg_by_year either")

# --- 5. too few years: no rate at all ---------------------------------------
few = world(fleet[-3:], {"Aland": (REG_HEADER, reg)})["Aland"]
check("attrition" not in few, "two stock steps are below MIN_YEARS: no attrition published")

# --- 6. blank petrol/diesel = no split, never zero (invariant 4) -----------
reg_blank = []
for y in range(2020, 2026):
    reg_blank += [f"{y}-{mm:02d},monthly,Whole,src,500,100,,,,0,5000," for mm in range(1, 13)]
blank = world(fleet, {"Aland": (REG_HEADER, reg_blank)})["Aland"]
check("inflow_mix" not in blank, "an empty PETROL/DIESEL column publishes no inflow mix")
check("attrition" in blank and "PETROL" not in blank["attrition"].get("by_fuel", {}),
      "...and no per-fuel petrol attrition, while the total still calibrates")

# --- 7. quarterly files: one row per quarter and spread-over-months --------
q_single, q_spread = [], []
for y in range(2020, 2026):
    q_single += [f"{y}-{mm:02d},quarterly,Whole,src,1500,300,1200,7500,4500,0,15000," for mm in (2, 5, 8, 11)]
    q_spread += [f"{y}-{mm:02d},quarterly,Whole,src,500,100,400,2500,1500,0,5000," for mm in range(1, 13)]
for label, lines in (("one row per quarter", q_single), ("quarterly spread over months", q_spread)):
    q = world(fleet, {"Aland": (REG_HEADER, lines)})["Aland"]
    check(abs(q["attrition"]["rate"] - 0.06) < 1e-9, f"{label}: a full year is recognised (rate 0.06)")
    check(abs(q.get("inflow_mix", {}).get("PETROL", 0) - 2500 / 4400) < 1e-3,
          f"{label}: the inflow mix covers exactly the last 12 months")
check(bc.months_covered([{"time_interval": "yearly"}]) == 12, "one yearly row covers 12 months")
check(bc.months_covered([{"time_interval": "yearly"}] * 12) == 12, "a yearly figure spread over 12 rows covers 12")
check(bc.months_covered([{"time_interval": "monthly"}] * 11) == 11, "11 monthly rows are not a year")

# --- 8. other variants are not passenger cars ------------------------------
fleet_v = fleet + [fleet_row("Aland", y, 1, 5000000, 5000000, variant="HDV") for y in range(2019, 2026)]
reg_v = reg + [l for y in range(2020, 2026) for l in monthly(y, 9, 9, 9, 9000, 9000, 99999, variant="Vans")]
v = world(fleet_v, {"Aland": (REG_HEADER, reg_v)})["Aland"]
check(abs(v["attrition"]["rate"] - 0.06) < 1e-9, "HDV stock rows and Vans registrations are ignored")

# --- 9. TOTAL column wins; without it the fuels are summed ------------------
fleet_t = [fleet_row("Aland", y, 10000, 600000, 390000, total=2000000) for y in range(2019, 2026)]
t = world(fleet_t, {"Aland": (REG_HEADER, reg)})["Aland"]
check(abs(t["attrition"]["rate"] - 0.03) < 1e-9, f"a reported TOTAL is the denominator, got {t['attrition']['rate']}")

# --- 10. name mapping and the committed file --------------------------------
uk = world([l.replace("Aland", "United Kingdom") for l in fleet], {"UK": (REG_HEADER, reg)})
check("attrition" in uk.get("United Kingdom", {}), "United Kingdom reads data/UK.csv")

# --- 11. age bands, long history and mileage ---------------------------------
d = Path(tempfile.mkdtemp())
(d / "fleet.csv").write_text(FLEET_HEADER + "\n" + "\n".join(fleet) + "\n", encoding="utf-8")
(d / "data").mkdir()
(d / "data" / "Aland.csv").write_text(REG_HEADER + "\n" + "\n".join(reg) + "\n", encoding="utf-8")
(d / "age.csv").write_text("country,year,lt2,y2_5,y5_10,y10_20,gt20,total,source\n"
                           "Aland,2025,100,150,250,300,200,1000,x\nAland,2024,,150,250,300,200,900,x\n", encoding="utf-8")
(d / "hist.csv").write_text("country,year,new_registrations,source\n"
                            + "".join(f"Aland,{y},{50000 + y},x\n" for y in (2005, 2016, 2018, 2019, 2021)), encoding="utf-8")
(d / "km.csv").write_text("country,year,fuel,km_per_car,total_mkm,source,notes\n"
                          "Aland,2025,ALL,10000,12000,office,\nAland,2025,PETROL,8000,6000,office,\n"
                          "Aland,2025,BEV,13000,,office,\nAland,2025,DIESEL,,99999999,office,\n"
                          "Aland,2019,ALL,9000,9000,office,\n", encoding="utf-8")
x = bc.build(d / "fleet.csv", d / "data", d / "age.csv", d / "hist.csv", d / "km.csv")["countries"]["Aland"]
check(x["age_bands"] == {"2025": [0.25, 0.25, 0.3, 0.2]}, f"age bands: two youngest merged, shares of the stock, incomplete year dropped: {x.get('age_bands')}")
comb = x["reg_by_year"]["COMBUSTION"]
check(list(comb)[:4] == ["2016", "2017", "2018", "2019"] and comb["2019"] == 52019 and comb["2017"] == 52017,
      f"long history is prepended where it joins the country's own series; a one-year hole is interpolated: {list(comb)[:5]}")
check("2005" not in comb and comb["2021"] != 52021, "...not across an 11-year hole, and never over the country's own years")
km = x["mileage"]
check(km["year"] == 2025 and km["ALL"] == 12000 and abs(km["basis_ratio"] - 1.2) < 1e-9,
      f"km per STOCK car = total km / year-end stock (1,000,000 cars), not the office's average: {km}")
check(km["PETROL"] == 10000, f"a fuel with a total: total / that fuel's stock (600,000), got {km.get('PETROL')}")
check(km["BEV"] == 15600 and km["scaled_from_average"] == ["BEV"], f"a fuel without a total: its average x the ALL ratio, got {km.get('BEV')}")
check("DIESEL" not in km, "an impossible figure (scope mismatch) is left out")
# Hybrids reported together, a fuel whose classes do not match, a stale year.
fleet_h = [fleet_row("Aland", y, 100000, 500000, 300000, phev=40000, hev=60000) for y in range(2019, 2026)]
(d / "fleet_h.csv").write_text(FLEET_HEADER + "\n" + "\n".join(fleet_h) + "\n", encoding="utf-8")
(d / "km_h.csv").write_text("country,year,fuel,km_per_car,total_mkm,source,notes\n"
                            "Aland,2024,ALL,,12000,office,\nAland,2024,PETROL,,4500,office,\n"
                            "Aland,2024,DIESEL,,9000,office,\nAland,2024,HYBRID,,1500,office,\n"
                            "Aland,2024,BEV,,1300,office,\nAland,2025,ALL,,0,office,\n", encoding="utf-8")
h = bc.build(d / "fleet_h.csv", d / "data", None, None, d / "km_h.csv")["countries"]["Aland"]["mileage"]
check(h["year"] == 2024 and h["ALL"] == 12000 and h["PETROL"] == 9000 and h["BEV"] == 13000, f"latest year WITH a total is used: {h}")
check(h["PHEV"] == 15000 and h["HEV"] == 15000 and h["hybrids_combined"] == ["PHEV", "HEV"],
      "hybrids reported together: total / (PHEV + HEV stock), given to both")
check("DIESEL" not in h, "a fuel at 2.5x the all-car figure is a class mismatch and is left out (30,000 vs 12,000)")
(d / "km_old.csv").write_text("country,year,fuel,km_per_car,total_mkm,source,notes\nAland,2020,ALL,,12000,office,\n", encoding="utf-8")
old_only = bc.build(d / "fleet_h.csv", d / "data", None, None, d / "km_old.csv")["countries"].get("Aland", {})
check("mileage" not in old_only, f"nothing before {bc.MILEAGE_MIN_YEAR} is published (pandemic year, ended series)")
md = bc.mileage_default({c: {"mileage": m} for c, m in {
    "A": {"ALL": 10000, "PETROL": 8000, "DIESEL": 14000, "BEV": 12000},
    "B": {"ALL": 12000, "PETROL": 9000, "DIESEL": 15000, "BEV": 13000},
    "C": {"ALL": 14000, "PETROL": 10000, "DIESEL": 16000},
    "D": {"ALL": 99999}}.items()})
check(md["countries"] == ["A", "B", "C"] and md["ALL"] == 12000 and md["PETROL"] == 9000 and md["DIESEL"] == 15000,
      f"default = median over the countries that report petrol and diesel: {md}")
check("BEV" not in md, "a class fewer than three of them report gets no default")
check(bc.mileage_default({"A": {"mileage": {"ALL": 1, "PETROL": 1, "DIESEL": 1}}}) is None, "too few countries: no default at all")

none = bc.build(d / "fleet.csv", d / "data", None, None, None)["countries"]["Aland"]
check("age_bands" not in none and "mileage" not in none and "attrition" in none, "without the optional files the core calibration still builds")

doc = json.loads(bc.OUT_PATH.read_text(encoding="utf-8"))
cs = doc["countries"]
check(len(cs) >= 30, f"committed calibration covers the fleet countries, got {len(cs)}")
check(all(-0.1 < c["attrition"]["rate"] < 0.2 for c in cs.values() if "attrition" in c),
      "every committed attrition rate is in a believable range")
check(all(abs(sum(c["inflow_mix"][k] for k in ("HEV", "PETROL", "DIESEL", "OTHERS")) - 1) < 2e-3
          for c in cs.values() if "inflow_mix" in c), "every committed inflow mix adds up to 1")
check(all(abs(v) <= 0.5 for c in cs.values() for v in c.get("attrition", {}).get("by_fuel", {}).values()),
      "per-fuel figures beyond +-50 % (scope mismatch) are left out")
check(all(abs(sum(b) - 1) < 2e-3 for c in cs.values() for b in c.get("age_bands", {}).values()),
      "every committed age-band row adds up to 1")
check(sum("age_bands" in c for c in cs.values()) >= 20 and sum("mileage" in c for c in cs.values()) >= 12
      and {"Norway", "Germany", "Sweden", "France"} <= {k for k, c in cs.items() if "mileage" in c},
      "age bands for 20+ countries; own mileage for 12+")
dflt = doc.get("mileage_default", {})
check(len(dflt.get("countries", [])) >= 8 and dflt["PETROL"] < dflt["ALL"] < dflt["DIESEL"],
      f"committed default mileage: petrol below the average, diesel above: {dflt}")
check(all(c["mileage"]["year"] >= bc.MILEAGE_MIN_YEAR for c in cs.values() if "mileage" in c), "no committed mileage is older than the minimum year")
no = cs["Norway"]["mileage"]
check(no["PHEV"] != no["HEV"] and "hybrids_combined" not in no, "Norway keeps plug-in and full hybrids apart (SSB)")
check(all(bc.KM_MIN <= v <= bc.KM_MAX for c in cs.values() for k, v in c.get("mileage", {}).items()
          if k in bc.MILEAGE_STOCK), "every committed km-per-car figure is plausible")
check("generated_by" in doc and "T" not in json.dumps(doc.get("generated_at", "")),
      "the file carries no timestamp (a rebuild on unchanged data is a no-op)")

bad = [msg for ok, msg in checks if not ok]
for msg in bad:
    print("FAIL:", msg)
print(f"{len(checks) - len(bad)}/{len(checks)} passed")
sys.exit(1 if bad else 0)
