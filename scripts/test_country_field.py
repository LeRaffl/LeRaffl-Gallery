#!/usr/bin/env python3
"""Static checks for the shared country-selector look (.country-field).
No network, writes nothing.

    python scripts/test_country_field.py
"""
import re
import sys
from pathlib import Path

HTML = (Path(__file__).resolve().parent.parent / "index.html").read_text(encoding="utf-8")
fails = []


def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        fails.append(name)


m = re.search(r"/\* ── Shared country-selector look \(\.country-field\).*?</style>", HTML, re.S)
check("shared .country-field CSS block exists", bool(m))
css = m.group(0) if m else ""

rule = re.search(r"\.country-field,[^{]*\{([^}]*)\}", css)
body = rule.group(1) if rule else ""
check("base rule uses Public Sans (--font-ui)", "font-family:var(--font-ui)" in body)
check("base rule 13.5px", "font-size:13.5px" in body)
check("base rule --line-3 hairline", "border:1px solid var(--line-3)" in body)
check("base rule 2px radius", "border-radius:2px" in body)
check("base rule --surface-2 fill", "background-color:var(--surface-2)" in body)
check("Raw metrics: padding 7px 11px, line-height 1.5 (=36.25px)", "padding:7px 11px" in css and "line-height:1.5" in body)
check("no fixed 36px height (follows Raw box model)", "height:36px" not in css)
check("select arrow restored", "background-image:var(--select-arrow)" in css)

for sel in ("#countryPick", "#sdCountry", "#galHeroHomeSel", ".compare-slot",
            '.country-picker__top input[type="search"]', ".country-picker select[multiple]"):
    check(f"rule covers {sel}", sel in (rule.group(0) if rule else ""))

check("hero select no longer full width", re.search(r"#galHeroHomeSel\{[^}]*width:auto", css) is not None)
check("no 44px mobile override on country fields (Raw is 36px on mobile too)", "min-height:44px" not in css)
check("gallery sidebar 44px rule neutralised for #countryPick", re.search(r"@media \(max-width:880px\)\{\s*#countryPick\{\s*min-height:0", css) is not None)
check("Raw Data picker itself untouched by the shared block", ".rd-picksum" not in re.sub(r"/\*.*?\*/", "", css, flags=re.S))
check("compare slots min-width 270px like Raw", re.search(r"\.compare-slot\{[^}]*min-width:270px", css) is not None)
check("submit grid single column on phones", re.search(r"max-width:600px\)\{\s*\.sd-grid\{[^}]*1fr", css) is not None)

for ident in ("sdCountry", "countryPick"):
    tag = re.search(r'<(?:select|input)[^>]*id="%s"[^>]*>' % ident, HTML)
    check(f"#{ident} carries class country-field", bool(tag and "country-field" in tag.group(0)))
for i in (1, 2, 3):
    tag = re.search(r'<select[^>]*id="compareSlot%d"[^>]*>' % i, HTML)
    check(f"#compareSlot{i} carries class country-field", bool(tag and "country-field" in tag.group(0)))

sys.exit(1 if fails else 0)
