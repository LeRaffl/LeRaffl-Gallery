#!/usr/bin/env python3
"""Regression test for the Fleet > Energy number format in index.html.

Run:  python scripts/test_fleet_energy_format.py   (needs node on PATH)

The Energy view (KPIs, Sankey labels, hover readout, CO2 axis/headline) used
`toLocaleString('de-DE')` plus `.replace('.', ',')`, so an English page showed
"3.412" for 3,412 TWh and "4,5" for 4.5. feFmt must be international and
locale-independent: ',' thousands, '.' decimals, whatever the browser locale.
The harness runs twice, once under a German default locale.
"""
import json, os, pathlib, re, shutil, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
NAMES = ["fmtInt", "feFmt"]
CASES = [3412.4, 1234567, 10, 9.96, 4.5, 0.25, 0, 52.4]
WANT = ["3,412", "1,234,567", "10", "10.0", "4.5", "0.3", "0.0", "52"]

HARNESS = r"""
const {execFileSync} = require('child_process');
eval(execFileSync('node', [process.argv[1], process.argv[2], ...JSON.parse(process.argv[3])]).toString()
     + '\nconsole.log(JSON.stringify({out: JSON.parse(process.argv[4]).map(feFmt), nan: feFmt(NaN)}));');
"""


def run(lang):
    env = dict(os.environ, LANG=lang, LC_ALL=lang)
    out = subprocess.run(["node", "-e", HARNESS, str(ROOT / "scripts/js_extract.js"),
                          str(ROOT / "index.html"), json.dumps(NAMES), json.dumps(CASES)],
                         capture_output=True, text=True, check=True, env=env).stdout
    return json.loads(out)


def main():
    if not shutil.which("node"):
        print("SKIP: node not found"); return 0
    checks = []
    for lang in ("en_US.UTF-8", "de_DE.UTF-8"):
        r = run(lang)
        for v, got, want in zip(CASES, r["out"], WANT):
            checks.append((got == want, f"[{lang}] feFmt({v}) = {got!r}, want {want!r}"))
        checks.append((r["nan"] == "\u2014", f"[{lang}] feFmt(NaN) must be an em dash"))
    html = (ROOT / "index.html").read_text()
    m = re.search(r"\nfunction feSvg\(.*?\nfunction feGridScenario", html, re.S)
    energy = m.group(0) if m else ""
    checks.append((bool(energy), "Energy view code found"))
    checks.append(("toLocaleString('de-DE')" not in energy, "no de-DE formatting left in the Energy view"))
    checks.append((".replace('.',',')" not in energy, "no decimal-comma replace left in the Energy view"))
    bad = [msg for ok, msg in checks if not ok]
    for msg in bad: print("FAIL:", msg)
    print(f"{len(checks)-len(bad)}/{len(checks)} passed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
