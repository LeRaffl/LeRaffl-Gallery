#!/usr/bin/env python3
"""Regression tests for the gallery tag system v2 in index.html (#294).

Run:  python scripts/test_tag_system.py   (needs node on PATH)

Loads the real functions from index.html via scripts/tag_system_report.js and
checks: grouping (Whole + Private + Industry = Cars; every other variant its
own group), per-group timing and speed quartiles, extrapolated 10 % years
counting, the 4-country minimum, and the #294 symptom itself — HDV must be
able to carry "Early starter" on the live params.csv.
"""
import json, pathlib, shutil, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

JS = r"""
const api = require(process.argv[1]);
const R = {};
R.groups = ['Whole','','Private','Industry','HDV','Vans','Buses','Used','Rental'].map(api.tagGroupOf);
const mk = (group, country, t10, speed, eligible=true) => ({group, label: group, country, t10, speed, eligible});
// HDV: 5 countries, all crossing 10 % late in calendar terms (2025-2030)
const hdv = [mk('hdv','A',2025,0.2), mk('hdv','B',2026,0.3), mk('hdv','C',2027,0.4),
             mk('hdv','D',2028,0.5), mk('hdv','E',2030,0.6),
             mk('hdv','X',2010,9.9,false)];            // ineligible: ignored
const small = [mk('buses','A',2020,0.1), mk('buses','B',2021,0.2), mk('buses','C',2022,0.3)];
// Cars: one country with three rows (Whole/Private/Industry) counts once
const cars = [mk('whole','A',2018,0.1), mk('whole','A',2018.5,0.1), mk('whole','A',2019,0.1),
              mk('whole','B',2022,0.2), mk('whole','C',2024,0.3)];
const c = api.tagGroupCutoffs([...hdv, ...small, ...cars]);
R.hdv = c.hdv; R.buses = c.buses; R.cars = c.whole;
R.early = api.timingTagFor(2025, c.hdv.timing);
R.mid   = api.timingTagFor(2027, c.hdv.timing);
R.late  = api.timingTagFor(2030, c.hdv.timing);
R.smallTiming = api.timingTagFor(2020, c.buses.timing);
R.smallSpeed  = api.speedTagFor(0.1, c.buses.speed);
R.fast = api.speedTagFor(0.6, c.hdv.speed);
R.slow = api.speedTagFor(0.2, c.hdv.speed);
R.avg  = api.speedTagFor(0.4, c.hdv.speed);
R.nan  = api.timingTagFor(NaN, c.hdv.timing);
console.log(JSON.stringify(R));
"""

def node(args):
    return subprocess.run(["node", *args], capture_output=True, text=True, check=True, cwd=ROOT).stdout

def main():
    if not shutil.which("node"):
        print("SKIP: node not found"); return 0
    lib = str(ROOT / "scripts/tag_system_report.js")
    r = json.loads(node(["-e", JS, lib]))
    live = json.loads(node([lib, "--json"]))
    hdv_live = live["dist"].get("hdv", {})
    checks = [
        (r["groups"] == ["whole"]*4 + ["hdv","vans","buses","used","rental"], "grouping"),
        (r["hdv"]["timing"]["n"] == 5 and r["hdv"]["timing"]["ok"], "HDV pool = 5 eligible countries"),
        (r["hdv"]["timing"]["lo"] == 2026 and r["hdv"]["timing"]["hi"] == 2028, "HDV quartiles 2026/2028"),
        (r["early"] == {"v":"early","label":"Early starter"}, "earliest quarter → Early starter"),
        (r["mid"] is None, "middle half → no timing pill"),
        (r["late"]["v"] == "late_start", "latest quarter → Late starter"),
        (r["nan"] is None, "no crossing year → no pill"),
        (r["buses"]["timing"]["ok"] is False and r["smallTiming"] is None, "<4 countries → no timing tag"),
        (r["smallSpeed"] is None, "<4 countries → no speed tag"),
        (r["cars"]["timing"]["n"] == 3, "countries counted once across Whole/Private/Industry"),
        ((r["fast"]["v"], r["slow"]["v"], r["avg"]["v"]) == ("fast","slow","avg"), "per-group speed quartiles"),
        (hdv_live.get("timing", {}).get("early", 0) > 0, "#294: live HDV rows can be Early starter"),
    ]
    html = (ROOT / "index.html").read_text()
    checks.append(("EARLY_BY" not in html and "LATE_AFTER" not in html, "fixed 2023/2025 cut removed"))
    bad = [m for ok, m in checks if not ok]
    for m in bad: print("FAIL:", m)
    print(f"{len(checks)-len(bad)}/{len(checks)} passed")
    return 1 if bad else 0

if __name__ == "__main__":
    sys.exit(main())
