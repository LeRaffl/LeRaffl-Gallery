#!/usr/bin/env python3
"""Regression tests for the gallery tag system v2 in index.html (#294).

Run:  python scripts/test_tag_system.py   (needs node on PATH)

Loads assets/fit_core.js + assets/tag_system.js (the files index.html and
sources/tags.html load) via scripts/tag_system_report.js and
checks: reference groups (only base variants define a distribution; subsets
such as Private / Industry / Used are classified against their parent via
TAG_PARENT), per-group timing and speed quartiles, extrapolated 10 % years
counting, the 4-country minimum, and the #294 symptom itself — HDV must be
able to carry "Early starter" on the live params.csv. Also the sidebar
tag filter (OR within a group, AND across groups, facet counts, no-transition
and small-group handling) and the gallery Show-more step.
"""
import json, pathlib, shutil, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

JS = r"""
const api = require(process.argv[1]).loadTagApi();
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
const lib = require(process.argv[1]);
const api = lib.loadTagApi();
const fs = require('fs');
const { enriched, cutoffs } = api.tagComputeAll(api.parseCSV(fs.readFileSync(process.argv[2], 'utf8')));
const cuts = {}; for (const [k, v] of Object.entries(cutoffs)) cuts[k] = [v.timing.lo, v.timing.hi];
const hl = enriched.find(e => e.group === 'hdv' && e.eligible);
const svg = api.TagBoxplots.svg({ group: 'hdv', metric: 'timing', cut: cutoffs.hdv, points: enriched, highlight: hl });
const st = [api.statusTagFor(2020, new Date(Date.UTC(2026,9,1))), api.statusTagFor(2030), api.statusTagFor(2040)].map(x => x.v);
console.log(JSON.stringify({ cuts, st, svg_ok: /<path d="M/.test(svg) && /tbp-hl/.test(svg) && /Early starter/.test(svg) }));
"""

DEGENERATE_JS = r"""
// Degenerate fits must not carry Status / Speed / Timing (Malta Buses, Greece HDV ...).
const api = require(process.argv[1]).loadTagApi();
const fs = require('fs');
const now = new Date();
const dp = `${now.getUTCFullYear()}-${String(now.getUTCMonth() + 1).padStart(2, '0')}`;
const base = { t0: '2021', data_per: dp, refit_swing: '1' };
const row = (country, v1, v2, obs, extra = {}) =>
  ({ country, variant: 'Buses', v1: String(v1), v2: String(v2), ttm_bev_share: String(obs), ...base, ...extra });
const rows = {
  maltaLike:   row('Malta',   -1.756e-18, 24.57, 0.597),   // step in 7 months, data at 60 %
  greeceLike:  row('Greece',  -2.53e-59,  71.23, 0.176),   // step in 3 months, data at 18 %
  croatiaLike: row('Croatia', -5.85e-54,  64.87, 0.255),
  romaniaLike: row('Romania', -1.53e-5,    7.73, 0.817),   // step the data has fully passed
  healthy:     row('Healthy', -2.97e-8,    6.37, 0.075),   // ordinary S-curve
  concave:     row('Concave', -0.1253,     0.806, 0.338),  // v2 <= 1: valid shape, no inflection
  posV1:       row('PosV1',    0.5,        4.2,  0.30),    // no S-shape: span is NaN
  negV2:       row('NegV2',   -6.17e79,   -131.5, 0.30),
};
const R = {};
for (const [k, r] of Object.entries(rows)) {
  const f = api.fitReliability(r, now);
  R[k] = { status: f.status, reasons: f.reasons, span: f.span };
}
// the same rows through the whole pipeline: group of 5 Buses markets
const all = ['maltaLike', 'greeceLike', 'croatiaLike', 'romaniaLike', 'healthy', 'concave', 'posV1']
  .map(k => ({ ...rows[k], variant: k === 'concave' ? '' : 'Buses' }));
const { enriched, cutoffs } = api.tagComputeAll(all, 0.8);
R.eligible = Object.fromEntries(enriched.map(e => [e.country, e.eligible]));
R.status = Object.fromEntries(enriched.map(e => [e.country, e.eligible && api.statusTagFor(e.t80) ? api.statusTagFor(e.t80).label : null]));
R.pool = cutoffs.buses && cutoffs.buses.speed.n;
// independence: Done + Slow is a legal pair on a healthy S-curve (docs/61)
R.doneSlow = [api.statusTagFor(2020, new Date(Date.UTC(2026, 9, 1))).label,
              api.speedTagFor(0.01, { ok: true, lo: 0.05, hi: 0.1 }).label];
console.log(JSON.stringify(R));
"""

FILTER_JS = r"""
// Sidebar tag filter (filter sidebar v2): assets/tag_system.js
// tagFilterValue / tagFilterPasses / tagFilterCounts.
const api = require(process.argv[1]).loadTagApi();
const T = {
  big:   { status: {v:'late'}, speed: {v:'avg'},  timing: {v:'early'} },
  fast:  { status: {v:'ontrack'}, speed: {v:'fast'}, timing: {v:'early'} },
  mid:   { status: {v:'late'}, speed: {v:'avg'} },                       // middle half: no timing pill
  small: { status: {v:'late'}, noscale: { timing: true, speed: true } }, // group < 4 markets
  notr:  { notrans: {v:'notrans'} },
  unrel: { unsettled: {v:'unsettled'} },
  none:  undefined,                                                     // no params row
};
const f = o => Object.fromEntries(Object.entries(o).map(([k, v]) => [k, new Set(v)]));
const P = (k, o) => api.tagFilterPasses(T[k], f(o));
const R = { pass: {}, val: {} };
for (const k of Object.keys(T)) {
  R.val[k] = Object.fromEntries(['fit','status','speed','timing'].map(c => [c, api.tagFilterValue(T[k], c)]));
  R.pass[k] = {
    nothing:    P(k, {}),
    timingMid:  P(k, { timing: ['mid'] }),
    speedAvg:   P(k, { speed: ['avg'] }),
    statusLate: P(k, { status: ['late'] }),
    reliable:   P(k, { fit: ['reliable'] }),
    notrans:    P(k, { fit: ['notrans'] }),
    orWithin:   P(k, { speed: ['fast', 'avg'] }),
    andAcross:  P(k, { speed: ['fast'], timing: ['early'] }),
    andAcross2: P(k, { speed: ['avg'], timing: ['early'] }),
  };
}
const items = Object.keys(T).map(k => ({ k }));
const tagsOf = it => T[it.k];
R.countsNone = api.tagFilterCounts(items, {}, tagsOf);
R.countsFast = api.tagFilterCounts(items, f({ speed: ['fast'] }), tagsOf);
R.groups = api.TAG_FILTER_GROUPS.map(g => [g.cat, g.label, g.values.map(v => v[0]).join(',')]);
// live params.csv: every chart lands in exactly one Fit value
console.log(JSON.stringify(R));
"""

FMT_JS = r"""
const api = require(process.argv[1]).loadTagApi();
const f = api.tagFmtYearMonth;
const out = [2021.0, 2021.999, 2021.9, 2021.5, 2021 + 1/12, 2021 + 1/12 - 1e-6, 2022 - 1e-12, 2025.0147, 2026.666951, NaN, Infinity, null].map(f);
const svg = api.TagBoxplots.svg({ group: 'hdv', metric: 'timing', cut: { timing: { ok: true, lo: 2025.0147, hi: 2028.76, n: 5 } },
  points: [2024, 2025, 2026, 2027, 2029].map((t, i) => ({ group: 'hdv', eligible: true, ref: true, country: 'C' + i, t10: t, speed: 0.1 })) });
console.log(JSON.stringify({ out, svgMonths: /≤ Jan 2025/.test(svg) && /≥ Oct 2028/.test(svg), svgDecimal: /20\d\d\.\d/.test(svg.replace(/<[^>]*>/g, ' ')) }));
"""

PAGER_JS = r"""
const src = require('child_process').execFileSync('node', [process.argv[1], process.argv[2], 'galleryNextRows']).toString();
eval(src);
console.log(JSON.stringify([galleryNextRows(6, 100, 24), galleryNextRows(6, 40, 24), galleryNextRows(6, 30, 24),
                            galleryNextRows(6, 6, 24), galleryNextRows(30, 31, 24)]));
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
        (r["groups"] == ["whole"]*4 + ["hdv","vans","buses","whole","whole","vans"], "subset → parent mapping"),
        (r["refs"] == [True, True, False, False, True, False, False], "only base variants are reference rows"),
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
    bp = json.loads(node(["-e", BOXPLOT_JS, lib, str(ROOT / "params.csv")]))
    checks += [
        (bp["cuts"] == {k: [v["timing"]["lo"], v["timing"]["hi"]] for k, v in live["cuts"].items()},
         "boxplot cut-offs == report cut-offs"),
        (bp["svg_ok"], "boxplot SVG renders with braces and highlight"),
        (bp["st"] == ["past", "ontrack", "late"], "status tag unchanged (80 % / 2035)"),
    ]
    dg = json.loads(node(["-e", DEGENERATE_JS, lib]))
    collapsed = lambda k: dg[k]["status"] == "excluded" and "collapsed" in dg[k]["reasons"]
    checks += [
        (collapsed("maltaLike"), "degenerate: Malta-Buses-like step (obs 60 %) is collapsed"),
        (collapsed("greeceLike") and collapsed("croatiaLike"), "degenerate: step at 18 % / 26 % observed is collapsed"),
        (dg["romaniaLike"]["status"] == "ok", "degenerate: a step the data has fully passed (82 %) stays"),
        (dg["healthy"]["status"] == "ok" and dg["concave"]["status"] == "ok", "degenerate: healthy and concave (v2 <= 1) fits stay"),
        (collapsed("posV1") and dg["posV1"]["span"] is None, "degenerate: v1 >= 0 (span NaN) is collapsed"),
        (collapsed("negV2"), "degenerate: v2 <= 0 is collapsed"),
        (dg["eligible"] == {"Malta": False, "Greece": False, "Croatia": False, "Romania": True, "Healthy": True, "Concave": True, "PosV1": False},
         "degenerate rows are not eligible for tags"),
        (all(dg["status"][c] is None for c in ["Malta", "Greece", "Croatia", "PosV1"]) and dg["status"]["Romania"] == "Done",
         "degenerate rows get no Done; Romania keeps it"),
        (dg["pool"] == 2, "degenerate rows stay out of the speed pool (only Romania + Healthy count)"),
        (dg["doneSlow"] == ["Done", "Slow"], "Status and Speed are independent: Done + Slow is a legal pair"),
    ]
    fl = json.loads(node(["-e", FILTER_JS, lib]))
    P, V = fl["pass"], fl["val"]
    checks += [
        (all(P[k]["nothing"] for k in P), "no chip selected: every chart shows"),
        (V["notr"] == {"fit": "notrans", "status": None, "speed": None, "timing": None}, "no transition: only Fit=No transition"),
        (not P["notr"]["reliable"] and P["notr"]["notrans"], "no transition is not counted as Reliable"),
        (V["unrel"]["fit"] == "unreliable" and not P["unrel"]["statusLate"], "unreliable: no status/speed/start"),
        (V["none"]["fit"] == "reliable" and not P["none"]["statusLate"], "no params row: reliable, no tags"),
        (P["mid"]["timingMid"] and V["mid"]["timing"] == "mid", "scaled row without timing pill = Mid"),
        (not P["small"]["timingMid"] and not P["small"]["speedAvg"], "small group drops out once Speed/Start is picked"),
        (P["small"]["statusLate"], "small group still filtered normally by Status"),
        (P["big"]["orWithin"] and P["fast"]["orWithin"] and not P["small"]["orWithin"], "OR within a group"),
        (P["fast"]["andAcross"] and not P["big"]["andAcross"] and P["big"]["andAcross2"] and not P["mid"]["andAcross2"], "AND across groups"),
        (fl["countsNone"]["fit"] == {"reliable": 5, "unreliable": 1, "notrans": 1}, "counts: Fit partitions all charts"),
        (fl["countsNone"]["timing"] == {"early": 2, "mid": 1, "late_start": 0}, "counts: Start ignores unscaled rows"),
        (fl["countsFast"]["speed"] == {"fast": 1, "avg": 2, "slow": 0}, "counts: own group ignores its own selection"),
        (fl["countsFast"]["timing"]["early"] == 1 and fl["countsFast"]["fit"]["reliable"] == 1, "counts: other groups apply the selection"),
        ([g[1] for g in fl["groups"]] == ["Fit", "Status", "Speed", "Start"], "four chip groups in sidebar order"),
    ]
    fm = json.loads(node(["-e", FMT_JS, lib]))
    checks += [
        (fm["out"][:4] == ["Jan 2021", "Dec 2021", "Nov 2021", "Jul 2021"], "year-month: .0 → Jan, .999 → Dec, .9 → Nov, .5 → Jul"),
        (fm["out"][4:7] == ["Feb 2021", "Jan 2021", "Jan 2022"], "year-month: month boundaries, float noise does not slip a month/year"),
        (fm["out"][7:9] == ["Jan 2025", "Sep 2026"], "year-month: live cut-offs (HDV P25, Cars P75)"),
        (fm["out"][9:] == ["—", "—", "—"], "year-month: NaN / Infinity / null → —"),
        (fm["svgMonths"] and not fm["svgDecimal"], "boxplot brace labels show month + year, no decimal years"),
    ]
    pg = json.loads(node(["-e", PAGER_JS, str(ROOT / "scripts/js_extract.js"), str(ROOT / "index.html")]))
    checks += [
        (pg == [30, 40, 30, 6, 31], "Show more: +24 per step, all of the rest once ≤ 12 would be left"),
    ]
    html = (ROOT / "index.html").read_text()
    checks += [
        (all(f'data-tag-cat="{c}"' in html and all(f'data-tag-value="{v}"' in html for v in vals.split(","))
             for c, _, vals in fl["groups"]), "sidebar markup has every chip of TAG_FILTER_GROUPS"),
        (" checked/>" not in html.split('id="tagFilters"')[1].split('id="moreFilters"')[0], "tag chips start unselected"),
        (html.index('id="tagFilters"') < html.index('id="moreFilters"') and
         'id="periodSelect"' in html.split('id="moreFilters"')[1].split("</details>")[0] and
         'id="latestOnly"' in html.split('id="moreFilters"')[1].split("</details>")[0],
         "tag chips visible by default; Month + Latest only under More filters"),
        (all(f'id="{i}"' not in html for i in ["sortField", "sortDir", "sortCombo"]) and "GALLERY_SORT = { field: 'created', dir: 'desc' }" in html,
         "no sort control; fixed newest-first order"),
        ('id="tagsHowLink"' in html.split('id="tagFilters"')[1].split('data-tag-cat="fit"')[0] and
         "<p" not in html.split('id="tagFilters"')[1].split('data-tag-cat="fit"')[0],
         "Tags section: heading + How-the-tags-work link only, no explainer paragraph"),
        ("cols.replaceChildren(frag)" in html and "function appendCards(" in html, "Show more appends instead of rebuilding"),
    ]
    html = (ROOT / "index.html").read_text()
    tags_html = (ROOT / "sources/tags.html").read_text() if (ROOT / "sources/tags.html").exists() else ""
    checks += [
        ('src="assets/fit_core.js"' in html and 'src="assets/tag_system.js"' in html, "gallery loads the shared files"),
        (html.index('src="assets/fit_core.js"') < html.index('<script>\n'), "shared files load before the inline scripts"),
        (all(f"function {n}(" not in html for n in ["rowHasNoTransition", "fitReliability", "tagComputeAll", "inv_x_years"]),
         "no second copy of the shared logic in index.html"),
        ("../assets/tag_system.js" in tags_html and "index.html" not in tags_html.split("tagBoxplots")[-1],
         "sources/tags.html uses the shared files, not index.html"),
    ]
    html = (ROOT / "index.html").read_text()
    checks.append(("EARLY_BY" not in html and "LATE_AFTER" not in html, "fixed 2023/2025 cut removed"))
    bad = [m for ok, m in checks if not ok]
    for m in bad: print("FAIL:", m)
    print(f"{len(checks)-len(bad)}/{len(checks)} passed")
    return 1 if bad else 0

if __name__ == "__main__":
    sys.exit(main())
