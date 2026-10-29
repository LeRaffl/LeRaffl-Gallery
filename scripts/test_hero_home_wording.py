#!/usr/bin/env python3
"""Static regression test for the home-page hero (index.html).

Run:  python scripts/test_hero_home_wording.py

Reader feedback (Bluesky, 2026-10): "TTM? No explanation", "97.8% which of
what?", "Monthly new-car registrations... but it's just BEVs", and "Hungary - you"
(browser time zone Europe/Budapest covers Prague/Bratislava/Belgrade too).
The hero must therefore (1) spell out TTM and BEV, (2) never call the
time-zone guess "you", (3) offer a persisted way to change/hide the guess.
"""
import pathlib, re, sys

HTML = (pathlib.Path(__file__).resolve().parent.parent / "index.html").read_text(encoding="utf-8")
checks = [
    ("lede says BEV share", "Battery-electric (BEV) share of monthly new-car registrations" in HTML),
    ("TTM spelled out in hero title", "trailing 12 months (TTM) as of" in HTML),
    ("BEV spelled out in hero subtitle", "Battery Electric Vehicles (BEV) as a share of new-car registrations" in HTML),
    ("no '· you' label left", "· you<" not in HTML and ">· you" not in HTML),
    ("home label says where it comes from", "your time zone" in HTML and "your selection" in HTML),
    ("home choice persisted in localStorage", "bevHomeCountry" in HTML and "localStorage.setItem(HOME_KEY" in HTML),
    ("change control present", 'id="galHeroHome"' in HTML and "galHeroHomeBtn" in HTML),
    ("hide option present", "No highlight" in HTML),
    ("compare tab honours the choice", "homeInfo(NAMES).country" in HTML),
]
bad = [n for n, ok in checks if not ok]
for n, ok in checks:
    print(("PASS " if ok else "FAIL ") + n)
print(f"{len(checks)-len(bad)}/{len(checks)} passed")
sys.exit(1 if bad else 0)
