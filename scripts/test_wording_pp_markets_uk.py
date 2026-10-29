#!/usr/bin/env python3
"""Static test for owner-approved wording changes in index.html (2026-10-29).

Run:  python scripts/test_wording_pp_markets_uk.py
 - Durations 'Numerical speed' is a slope in percentage points per year -> 'pp/year' (not '%/year')
 - hero lede says '~60 markets'
 - Fleet picker / chart footer show 'UK' (display only; data key stays 'United Kingdom')
"""
import pathlib, re, sys
HTML = (pathlib.Path(__file__).resolve().parent.parent / "index.html").read_text(encoding="utf-8")
checks = [
    ("no '%/year' / '%/yr' left", not re.search(r"%/(year|yr)", HTML)),
    ("durations cells use pp/year", "' pp/year'" in HTML),
    ("tag tooltip uses pp/yr", "' pp/yr'" in HTML),
    ("Numerical speed header explains pp", 'data-k="_speed" title="Steepest slope' in HTML),
    ("hero lede ~60 markets", "Open data. ~60 markets" in HTML and "40+ markets" not in HTML),
    ("fleet display helper", "function fleetDisplayName(name){ return name === 'United Kingdom' ? 'UK' : name; }" in HTML),
    ("fleet option label uses helper", "opt.textContent = fleetDisplayName(label);" in HTML),
    ("fleet chart footer uses helper", "selectedCountries.map(fleetDisplayName)" in HTML),
    ("fleet option value stays the data key", "opt.value = c;" in HTML),
]
bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("PASS " if ok else "FAIL ") + n)
print(f"{len(checks)-len(bad)}/{len(checks)} passed"); sys.exit(1 if bad else 0)
