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
check("single-line height 36px", "height:36px" in css)
check("select arrow restored", "background-image:var(--select-arrow)" in css)

for sel in ("#countryPick", "#sdCountry", "#galHeroHomeSel", ".compare-slot",
            '.country-picker__top input[type="search"]', ".country-picker select[multiple]"):
    check(f"rule covers {sel}", sel in (rule.group(0) if rule else ""))

check("hero select no longer full width", re.search(r"#galHeroHomeSel\{[^}]*width:auto", css) is not None)
check("mobile 44px touch target", re.search(r"@media \(max-width:880px\)\{[^}]*\.country-field[^}]*min-height:44px", css) is not None)

for ident in ("sdCountry", "countryPick"):
    tag = re.search(r'<(?:select|input)[^>]*id="%s"[^>]*>' % ident, HTML)
    check(f"#{ident} carries class country-field", bool(tag and "country-field" in tag.group(0)))
for i in (1, 2, 3):
    tag = re.search(r'<select[^>]*id="compareSlot%d"[^>]*>' % i, HTML)
    check(f"#compareSlot{i} carries class country-field", bool(tag and "country-field" in tag.group(0)))

sys.exit(1 if fails else 0)
