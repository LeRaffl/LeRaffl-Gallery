#!/usr/bin/env python3
"""Regression tests for the Fleet explainer page (sources/fleet.html).

Run:  python scripts/test_fleet_explainer.py   (the chart checks need node)

The page is what people are pointed at when they ask how a Fleet number comes
about, so it must exist, be reachable from the Fleet tab, draw its charts from
the live files, and not contradict the code. Pinned here:

* docs/architecture/65-fleet-model.md is a valid explainer and the committed
  sources/fleet.html is what the generator produces from it;
* every `figure:` the document names exists in assets/fleet_figures.js, and
  every figure draws from the real fleet/ files without a NaN or `undefined`;
* the Fleet tab links to the page, and every anchor it deep-links to exists;
* the counts and defaults the prose states still match the data and the code.
"""
import json
import pathlib
import re
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import build_source_pages as bsp  # noqa: E402

DOC = "65-fleet-model.md"
checks = []


def check(ok, msg):
    checks.append((bool(ok), msg))


fm = bsp.read_front_matter(ROOT / "docs" / "architecture" / DOC)
explainers, problems = bsp.collect_explainers()
check(not problems and any(d == DOC for _, d in explainers), f"{DOC} is a valid explainer ({problems})")
check(fm.get("slug") == "fleet" and fm.get("figures") == "fleet" and fm.get("flow_position") == "top",
      "slug fleet, live figures, flow first")

page_path = ROOT / "sources" / "fleet.html"
page = page_path.read_text(encoding="utf-8") if page_path.exists() else ""
check(page and page == bsp.build_explainer_page(fm, DOC),
      "sources/fleet.html is what the generator builds from the document (re-run build_source_pages.py)")
check('src="../assets/fleet_figures.js"' in page and 'FleetFigures.mount(document,{base:"../"})' in page,
      "the page loads and mounts the figure script")
check("The calculation, step by step" in page and page.index("The calculation, step by step") < page.index("What this is, and what it is not"),
      "the step-by-step flow comes first")
check(page.count('class="dt-q"') >= 6, "the flow carries its decision gateways")

# --- figures -------------------------------------------------------------------
js = (ROOT / "assets" / "fleet_figures.js").read_text(encoding="utf-8")
names = re.search(r"const FIGURES = \{([^}]*)\}", js).group(1).replace(" ", "").split(",")
wanted = [s["figure"] for s in fm["sections"] if s.get("figure")]
check(wanted and set(wanted) <= set(names), f"every figure the document names exists in the script: {wanted}")
check(set(names) <= set(wanted), f"no chart in the script is left unused: {sorted(set(names) - set(wanted))}")
check(all(f'data-fleet-fig="{n}"' in page for n in wanted), "every figure has its mount point on the page")
for f in ("fleet/fleet_calibration.json", "fleet/survival_fit.csv", "fleet/grid_mix.csv"):
    check(f in js and (ROOT / f).exists(), f"figures read {f}, which exists")

HARNESS = r"""
const fs = require('fs'), root = process.argv[1];
global.window = {};
eval(fs.readFileSync(root + '/assets/fleet_figures.js', 'utf8'));
const F = window.FleetFigures;
const data = { cal: JSON.parse(fs.readFileSync(root + '/fleet/fleet_calibration.json', 'utf8')),
               fit: F.parseCSV(fs.readFileSync(root + '/fleet/survival_fit.csv', 'utf8')),
               grid: F.parseCSV(fs.readFileSync(root + '/fleet/grid_mix.csv', 'utf8')) };
const out = {};
for (const name of F.names) {
  const el = { innerHTML: '', querySelector: () => ({}), querySelectorAll: () => [] };
  try { F.draw(name, el, data); out[name] = el.innerHTML; } catch (e) { out[name] = 'ERROR ' + e.message; }
}
console.log(JSON.stringify(out));
"""
if shutil.which("node"):
    res = subprocess.run(["node", "-e", HARNESS, str(ROOT)], capture_output=True, text=True)
    check(res.returncode == 0, "figure script runs under node " + res.stderr[-400:])
    drawn = json.loads(res.stdout) if res.returncode == 0 else {}
    for name in names:
        html = drawn.get(name, "")
        check("<svg" in html and "</svg>" in html and not html.startswith("ERROR"), f"figure '{name}' draws ({html[:60]!r})")
        check("NaN" not in html and "undefined" not in html and "Infinity" not in html, f"figure '{name}' has no NaN / undefined")
        check("<details" in html and html.count("<tr>") >= 5, f"figure '{name}' ships its numbers as a table")
        check("data-tip=" in html and "ff-legend" in html, f"figure '{name}' has a hover readout and a legend")
    cal = json.loads((ROOT / "fleet" / "fleet_calibration.json").read_text(encoding="utf-8"))
    for country in ("Germany", "Norway", "Finland"):
        check(all(country in drawn.get(n, "") for n in ("turnover", "ages", "grid")), f"{country} appears in the turnover, age and grid charts")
    check("Median" in drawn.get("mileage", "") and "World" in drawn.get("grid", ""), "the mileage median and the world grid are drawn as references")
else:
    print("SKIP: node not found (chart checks)")
    cal = json.loads((ROOT / "fleet" / "fleet_calibration.json").read_text(encoding="utf-8"))

# --- reachable from the UI -------------------------------------------------------
index = (ROOT / "index.html").read_text(encoding="utf-8")
fleet_tab = index[index.index('<section id="tab-fleet"'):]
fleet_tab = fleet_tab[:fleet_tab.index("</section>")]
check('href="sources/fleet.html"' in fleet_tab and "How this is calculated" in fleet_tab, "the Fleet tab links to the explainer")
anchors = set(re.findall(r'sources/fleet\.html#([a-z]+)', index))
ids = set(re.findall(r'<section id="([a-z]+)"', page))
check(anchors and anchors <= ids, f"every anchor the tab deep-links to exists on the page: {sorted(anchors)} vs {sorted(ids)}")
faq = index[index.index("// ----- FLEET -----"):]
check("sources/fleet.html" in faq[:1500], "the first Fleet FAQ entry points to the explainer")
wf = (ROOT / ".github" / "workflows" / "build-source-pages.yml").read_text(encoding="utf-8")
check(wf.count(DOC) == 2, "build-source-pages.yml rebuilds the page when the document changes (push and PR)")

# --- the prose still matches data and code ---------------------------------------
text = json.dumps(fm)
cs = cal["countries"]
n_age = sum("age_bands" in c for c in cs.values())
n_fuel = sum("PETROL" in c.get("mileage", {}) and "DIESEL" in c["mileage"] for c in cs.values())
n_all = sum("mileage" in c for c in cs.values()) - n_fuel
check(f"yes ({n_age} countries)" in text and f"for {n_age} of the fleet countries" in text, f"age bands: the page says {n_age} countries")
check(f"yes, by fuel ({n_fuel} countries)" in text and f"yes, for all cars only ({n_all} countries)" in text,
      f"mileage: the page says {n_fuel} by fuel and {n_all} totals only")
floor = float(re.search(r"FLEET_TURNOVER_FLOOR = ([0-9.]+)", index).group(1))
check(floor == 0.01 and "below 1%" in text and "1% of the fleet leaves" in text, "the 1% floor in the prose is the floor in the code")
check(re.search(r'name="feGridScen" value="trend" checked', index) and "recent trend continues (the default)" in text,
      "the default grid scenario named in the prose is the default in the page")
check(re.search(r'name="hazardMode" value="weibull" checked', index) and "Per-vintage Weibull (the default)" in text,
      "the default hazard model named in the prose is the default in the page")
dflt = cal["mileage_default"]
check(abs(dflt["PETROL"] - 9100) < 300 and abs(dflt["DIESEL"] - 14400) < 400 and "about 9,100 and 14,400" in text,
      f"the median mileage quoted in the prose is still about right ({dflt['PETROL']}, {dflt['DIESEL']})")
check(not re.search(r"\d %", text), "percentages are written without a space")

bad = [msg for ok, msg in checks if not ok]
for msg in bad:
    print("FAIL:", msg)
print(f"{len(checks) - len(bad)}/{len(checks)} passed")
sys.exit(1 if bad else 0)
