#!/usr/bin/env python3
"""Static wording test for index.html: abbreviations are explained where a reader first meets them.

Run:  python scripts/test_ttm_bev_wording.py
Origin: reader feedback "TTM? No explanation." (Bluesky, 2026-10-26).
"""
import pathlib, sys

HTML = (pathlib.Path(__file__).resolve().parent.parent / "index.html").read_text(encoding="utf-8")
checks = [
    ("Durations note spells out TTM", "BEV share (trailing 12 months, TTM) below 1%" in HTML),
    ("Raw Data intro spells out TTM", "trailing-12-months (TTM) charts roll" in HTML),
    ("gallery column title spells out TTM", "ttm_shares:'Trailing 12 months (TTM) market split'" in HTML),
    ("gallery chips carry tooltips", HTML.count('<label class="chip" title="') >= 4),
    ("map lede is plain English", "as per smoothed out model" not in HTML and "BEV transition by country, based on the smoothed model." in HTML),
    ("HDV explained on the map", "HDV (heavy-duty vehicles)" in HTML),
    ("About: parameter count matches FAQ", "two free shape parameters (plus a time shift)" in HTML),
]
bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("PASS " if ok else "FAIL ") + n)
print(f"{len(checks)-len(bad)}/{len(checks)} passed")
sys.exit(1 if bad else 0)
