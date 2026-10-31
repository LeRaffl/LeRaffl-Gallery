#!/usr/bin/env python3
"""Static test: user-visible strings in assets/*.js follow the site wording rules.

Run:  python scripts/test_assets_wording.py

Rules (same as the index.html / sources checks in test_percent_spacing.py and
test_wording_pp_markets_uk.py, which only look at index.html and sources/):
  * percentages are written without a space: "10% BEV share", not "10 % BEV share"
  * a slope is in percentage points per year: "pp/yr", never "%/yr" or "%/year"
Comments are ignored (they are not user-visible). Needs nothing but the repo.
"""
import pathlib, re, sys

ASSETS = pathlib.Path(__file__).resolve().parent.parent / "assets"
SPACED = re.compile(r"\d %(?! ?\d)")                                  # "80 %", not "i % 2"
DYN = re.compile(r"\}\s%(?!\d)|\+\s*'\s%'|\)\s*\+\s*'\s%[^/]")        # `${x} %`, + ' %'
PER_YEAR = re.compile(r"%/(?:yr|year)\b")


def strip_comments(text):
    text = re.sub(r"/\*.*?\*/", lambda m: re.sub(r"[^\n]", " ", m.group(0)), text, flags=re.S)
    return re.sub(r"(?<![:'\"\w])//.*", "", text)                      # keep "http://" inside strings


bad = []
files = sorted(ASSETS.glob("*.js"))
for p in files:
    for i, line in enumerate(strip_comments(p.read_text(encoding="utf-8")).split("\n"), 1):
        if SPACED.search(line) or DYN.search(line):
            bad.append(f"assets/{p.name}:{i}: spaced percent: {line.strip()[:100]}")
        if PER_YEAR.search(line):
            bad.append(f"assets/{p.name}:{i}: use pp/yr, not %/yr: {line.strip()[:100]}")

box = (ASSETS / "tag_boxplots.js").read_text(encoding="utf-8")
checks = [
    ("scans at least the known asset scripts", len(files) >= 3),
    ("no spaced '%' and no '%/yr' in user-visible asset strings", not bad),
    ("tag boxplot Speed axis says pp/yr", "slope at inflection, pp/yr" in box),
    ("tag boxplot Speed value says pp/yr", "+ ' pp/yr'" in box),
    ("tag boxplot Timing axis says 10% BEV share", "fitted year at 10% BEV share" in box),
]
for n, ok in checks:
    print(("PASS " if ok else "FAIL ") + n)
for b in bad[:30]:
    print("  " + b)
failed = [n for n, ok in checks if not ok]
print(f"{len(checks)-len(failed)}/{len(checks)} passed")
sys.exit(1 if failed else 0)
