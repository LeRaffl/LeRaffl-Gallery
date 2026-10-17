#!/usr/bin/env python3
"""Regression test for the world map classifier in index.html (#266).

Run:  python scripts/test_worldmap_classify.py   (needs node on PATH)

#266: Portugal HDV is a collapsed fit (v2 < 0). The tables label it
"No transition", but the map painted it as a Pioneer because a collapsed curve
yields a fitted "year at threshold" before data_per. wmClassify must decide
'notrans' before any value-based check, and wmRender must keep those rows out
of the colour ramp and the Pioneers list.
"""
import json, pathlib, shutil, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
NAMES = ["MIN_TRANSITION_SLOPE", "normNumber", "toYYYYMM", "getDataPer",
         "rowHasNoTransition", "wmPioneerCutoff", "wmClassify"]

HARNESS = r"""
const code = require('child_process').execFileSync('node',
  [process.argv[1], process.argv[2], ...JSON.parse(process.argv[3])]).toString();
eval(code);
const pt = {country:'Portugal', variant:'HDV', v1:'-0.0137973527002662',
            v2:'-0.49121649765089', t0:'2025', data_per:'2026-08', ttm_bev_share:''};
const nt = rowHasNoTransition(pt);
const row = {noTrans: nt, v1: -0.0138, dataPer: '2026-08'};
const live = {noTrans: false, v1: -1e-6, dataPer: '2026-08'};
console.log(JSON.stringify({
  nt,
  year_past: wmClassify('year', 2020, row),
  duration: wmClassify('duration', 5, row),
  share: wmClassify('share', 3, row),
  live_pioneer: wmClassify('year', 2020, live),
  live_normal: wmClassify('year', 2030, live),
}));
"""

def main():
    if not shutil.which("node"):
        print("SKIP: node not found"); return 0
    out = subprocess.run(["node", "-e", HARNESS, str(ROOT / "scripts/js_extract.js"),
                          str(ROOT / "index.html"), json.dumps(NAMES)],
                         capture_output=True, text=True, check=True).stdout
    r = json.loads(out)
    checks = [
        (r["nt"] is True, "Portugal HDV must be no-transition"),
        (r["year_past"] == "notrans", "collapsed fit must not be a pioneer (#266)"),
        (r["duration"] == "notrans", "duration mode: notrans"),
        (r["share"] == "normal", "share mode keeps the fitted share"),
        (r["live_pioneer"] == "pioneer", "real pioneers still detected"),
        (r["live_normal"] == "normal", "normal rows unchanged"),
    ]
    html = (ROOT / "index.html").read_text()
    checks.append(("d.cls === 'stalled' || d.cls === 'notrans'" in html,
                   "wmRender routes notrans into the grey layer"))
    bad = [m for ok, m in checks if not ok]
    for m in bad: print("FAIL:", m)
    print(f"{len(checks)-len(bad)}/{len(checks)} passed")
    return 1 if bad else 0

if __name__ == "__main__":
    sys.exit(main())
