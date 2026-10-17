#!/usr/bin/env python3
"""Regression tests for the gallery tag system v2 in index.html (#294).

Run:  python scripts/test_tag_system.py   (needs node on PATH)

Loads the real functions from index.html via scripts/tag_system_report.js and
checks: reference groups (only base variants define a distribution; subsets
such as Private / Industry / Used are classified against their parent via
TAG_PARENT), per-group timing and speed quartiles, extrapolated 10 % years
counting, the 4-country minimum, and the #294 symptom itself — HDV must be
able to carry "Early starter" on the live params.csv.
"""
import json, pathlib, shutil, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

JS = r"""
const api = require(process.argv[1]);
const R = {};
R.groups = ['Whole','','Private','Industry','HDV','Vans','Buses','Used','Rental','Pickups'].map(api.tagGroupOf);
R.refs = ['Whole','','Private','Industry','HDV','Used','Pickups'].map(api.tagIsReference);
const mk = (group, country, t10, speed, eligible=true, ref=true) => ({group, label: group, country, t10, speed, eligible, ref});
// HDV: 5 countries, all crossing 10 % late in calendar terms (2025-2030)
const hdv = [mk('hdv','A',2025,0.2), mk('hdv','B',2026,0.3), mk('hdv','C',2027,0.4),
             mk('hdv','D',2028,0.5), mk('hdv','E',2030,0.6),
             mk('hdv','X',2010,9.9,false)];            // ineligible: ignored
const small = [mk('buses','A',2020,0.1), mk('buses','B',2021,0.2), mk('buses','C',2022,0.3)];
// Cars: Whole rows A..D define the scale; subset rows (ref=false) must not move it,
// and a duplicated Whole row for A counts once.
const cars = [mk('whole','A',2018,0.1), mk('whole','A',2030,9,true), mk('whole','B',2020,0.2),
              mk('whole','C',2022,0.3), mk('whole','D',2024,0.4),
              mk('whole','A',1990,50,true,false), mk('whole','E',1991,60,true,false),
              mk('whole','F',1992,70,true,false)];
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
R.subsetEarly = api.timingTagFor(2019, c.whole.timing);   // a Private row on Whole's scale
console.log(JSON.stringify(R));
"""

BOXPLOT_JS = r"""
const fs = require('fs');
global.window = {};
eval(fs.readFileSync(process.argv[1], 'utf8'));
const TB = window.TagBoxplots, src = fs.readFileSync(process.argv[2], 'utf8');
const missing = TB.TAG_API_NAMES.filter(n => !new RegExp('^(?:function '+n+'\\s*\\(|(?:const|let|var) '+n+'\\b)', 'm').test(src));
const api = TB.apiFrom(src);
const { enriched, cutoffs } = api.tagComputeAll(api.parseCSV(fs.readFileSync(process.argv[3], 'utf8')), 0.8);
const cuts = {}; for (const [k, v] of Object.entries(cutoffs)) cuts[k] = [v.timing.lo, v.timing.hi];
const hl = enriched.find(e => e.group === 'hdv' && e.eligible);
const svg = TB.svg({ group: 'hdv', metric: 'timing', cut: cutoffs.hdv, points: enriched, highlight: hl });
console.log(JSON.stringify({ missing, cuts, svg_ok: /<path d="M/.test(svg) && /tbp-hl/.test(svg) && /Early starter/.test(svg) }));
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
        (r["groups"] == ["whole"]*4 + ["hdv","vans","buses","whole","whole","pickups"], "subset → parent mapping"),
        (r["refs"] == [True, True, False, False, True, False, True], "only base variants are reference rows"),
        (r["hdv"]["timing"]["n"] == 5 and r["hdv"]["timing"]["ok"], "HDV pool = 5 eligible countries"),
        (r["hdv"]["timing"]["lo"] == 2026 and r["hdv"]["timing"]["hi"] == 2028, "HDV quartiles 2026/2028"),
        (r["early"] == {"v":"early","label":"Early starter"}, "earliest quarter → Early starter"),
        (r["mid"] is None, "middle half → no timing pill"),
        (r["late"]["v"] == "late_start", "latest quarter → Late starter"),
        (r["nan"] is None, "no crossing year → no pill"),
        (r["buses"]["timing"]["ok"] is False and r["smallTiming"] is None, "<4 countries → no timing tag"),
        (r["smallSpeed"] is None, "<4 countries → no speed tag"),
        (r["cars"]["timing"]["n"] == 4, "Whole: one row per country, subsets ignored"),
        ((r["cars"]["timing"]["lo"], r["cars"]["timing"]["hi"]) == (2019.5, 2022.5), "Whole quartiles unaffected by subsets"),
        (r["subsetEarly"]["v"] == "early", "subset classified on parent's scale"),
        ((r["fast"]["v"], r["slow"]["v"], r["avg"]["v"]) == ("fast","slow","avg"), "per-group speed quartiles"),
        (hdv_live.get("timing", {}).get("early", 0) > 0, "#294: live HDV rows can be Early starter"),
    ]
    # assets/tag_boxplots.js must load every function it names from index.html
    # and produce the same cut-offs as the report (sources/tags.html relies on it).
    bp = json.loads(node(["-e", BOXPLOT_JS, str(ROOT / "assets/tag_boxplots.js"),
                          str(ROOT / "index.html"), str(ROOT / "params.csv")]))
    checks += [
        (bp["missing"] == [], f"tag_boxplots.js finds all functions (missing: {bp['missing']})"),
        (bp["cuts"] == {k: [v["timing"]["lo"], v["timing"]["hi"]] for k, v in live["cuts"].items()},
         "boxplot page cut-offs == report cut-offs"),
        (bp["svg_ok"], "boxplot SVG renders with braces and highlight"),
    ]
    html = (ROOT / "index.html").read_text()
    checks.append(("EARLY_BY" not in html and "LATE_AFTER" not in html, "fixed 2023/2025 cut removed"))
    bad = [m for ok, m in checks if not ok]
    for m in bad: print("FAIL:", m)
    print(f"{len(checks)-len(bad)}/{len(checks)} passed")
    return 1 if bad else 0

if __name__ == "__main__":
    sys.exit(main())
