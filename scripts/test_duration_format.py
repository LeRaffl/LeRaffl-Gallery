#!/usr/bin/env python3
"""Regression test: duration labels never read '2y 12m' (index.html).

Run:  python scripts/test_duration_format.py   (needs node on PATH)

fmtYearsMonths (Durations table) and wmDurationFmt (World map) used to round the
month remainder separately, so 2.98 years became "2y 12m". They must carry over.
"""
import pathlib, re, shutil, subprocess, sys, json

SRC = (pathlib.Path(__file__).resolve().parent.parent / "index.html").read_text(encoding="utf-8")


def grab(name):
    m = re.search(r"^[ \t]*function %s\s*\(" % name, SRC, re.M)
    i = m.start(); j = SRC.index("{", SRC.index(")", i)); d = 0
    for k in range(j, len(SRC)):
        d += (SRC[k] == "{") - (SRC[k] == "}")
        if d == 0:
            return SRC[i:k + 1]

CASES = {2.0: "2y", 2.98: "3y", 2.5: "2y 6m", 0.99: "1y", 0.25: "3m", 0.0: "0m", 11.99: "12y", 3.49: "3y 6m"}


def main():
    if not shutil.which("node"):
        print("SKIP: node not found"); return 0
    js = grab("fmtYearsMonths") + "\n" + grab("wmDurationFmt") + """
const cases = %s; const out = {};
for (const k of Object.keys(cases)) out[k] = [fmtYearsMonths(+k), wmDurationFmt(+k)];
out.neg = [fmtYearsMonths(NaN), wmDurationFmt(NaN), wmDurationFmt(-2.98)];
console.log(JSON.stringify(out));""" % json.dumps(CASES)
    out = json.loads(subprocess.run(["node", "-e", js], capture_output=True, text=True, check=True).stdout)
    bad = 0
    for k, want in CASES.items():
        got = out[str(k)]
        ok = got == [want, want]
        bad += not ok
        print(("PASS " if ok else "FAIL ") + f"{k} -> {got} (want {want})")
    ok = out["neg"] == ["—", "—", "-3y"]; bad += not ok
    print(("PASS " if ok else "FAIL ") + f"NaN / negative -> {out['neg']}")
    print(f"{len(CASES)+1-bad}/{len(CASES)+1} passed")
    return 1 if bad else 0

sys.exit(main())
