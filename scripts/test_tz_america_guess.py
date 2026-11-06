#!/usr/bin/env python3
"""Static regression: TZ → country must not mark Latin America as USA.

Run:  python scripts/test_tz_america_guess.py

The old TZ_PREFIX catch-all ['America/','USA'] mapped Mexico City, Costa Rica,
Panama, Caracas, La Paz, and unlisted Canada/Brazil/Chile zones to USA. US
zones are listed explicitly; unmatched zones fall through. The hero copy must
also distinguish "country not in data" from "could not guess from time zone".
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HTML = (ROOT / "index.html").read_text(encoding="utf-8")
fails = []


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        fails.append(name)


# --- extract TZ tables (mirrors index.html) ---------------------------------
m = re.search(r"const TZ_COUNTRY = \{([\s\S]*?)\n  \};", HTML)
check("TZ_COUNTRY block found", m is not None)
tz_country = {}
if m:
    tz_country = dict(re.findall(r"'([^']+)':'([^']+)'", m.group(1)))

i = HTML.find("const TZ_PREFIX = [")
check("TZ_PREFIX block found", i >= 0)
prefix_src = HTML[i:HTML.index("]];", i) + 2]
# Drop block comments so 'America/' inside a comment is not a false positive.
prefix_code = re.sub(r"/\*[\s\S]*?\*/", "", prefix_src)
tz_prefix = re.findall(r"\['([^']+)','([^']+)'\]", prefix_code)


def tz_country_of(tz: str):
    c = tz_country.get(tz)
    if c:
        return c
    for p, country in tz_prefix:
        if tz.startswith(p):
            return country
    return None


# --- Bug 1: no America/ catch-all; US zones explicit ------------------------
check("no catch-all America/ → USA in TZ_PREFIX",
      "['America/','USA']" not in prefix_code
      and not any(p == "America/" and c == "USA" for p, c in tz_prefix))
check("Pacific/Honolulu still maps to USA", tz_country_of("Pacific/Honolulu") == "USA")
check("America/New_York maps to USA", tz_country_of("America/New_York") == "USA")
check("America/Chicago maps to USA", tz_country_of("America/Chicago") == "USA")
check("America/Los_Angeles maps to USA", tz_country_of("America/Los_Angeles") == "USA")
check("America/Indiana/Indianapolis maps to USA",
      tz_country_of("America/Indiana/Indianapolis") == "USA")
check("America/Kentucky/Louisville maps to USA",
      tz_country_of("America/Kentucky/Louisville") == "USA")
check("America/North_Dakota/Center maps to USA",
      tz_country_of("America/North_Dakota/Center") == "USA")
check("America/Phoenix maps to USA", tz_country_of("America/Phoenix") == "USA")
check("America/Denver maps to USA", tz_country_of("America/Denver") == "USA")
check("America/Anchorage maps to USA", tz_country_of("America/Anchorage") == "USA")

check("America/Mexico_City does NOT map to USA",
      tz_country_of("America/Mexico_City") != "USA")
check("America/Mexico_City is unmapped (falls through)",
      tz_country_of("America/Mexico_City") is None)
check("America/Costa_Rica does NOT map to USA",
      tz_country_of("America/Costa_Rica") is None)
check("America/Caracas does NOT map to USA",
      tz_country_of("America/Caracas") is None)
check("America/La_Paz does NOT map to USA",
      tz_country_of("America/La_Paz") is None)
check("America/Panama does NOT map to USA",
      tz_country_of("America/Panama") is None)
check("America/Regina (Canada leftover) does NOT map to USA",
      tz_country_of("America/Regina") is None)
check("America/Bahia (Brazil leftover) does NOT map to USA",
      tz_country_of("America/Bahia") is None)
check("America/Punta_Arenas (Chile leftover) does NOT map to USA",
      tz_country_of("America/Punta_Arenas") is None)

# Existing non-US mappings still win before any US entry
check("America/Toronto still Canada", tz_country_of("America/Toronto") == "Canada")
check("America/Sao_Paulo still Brazil", tz_country_of("America/Sao_Paulo") == "Brazil")
check("America/Argentina/Buenos_Aires still Argentina",
      tz_country_of("America/Argentina/Buenos_Aires") == "Argentina"
      or tz_country_of("America/Buenos_Aires") == "Argentina")
check("Europe/Vienna still Austria (exact)", tz_country_of("Europe/Vienna") == "Austria")
check("UTC is unmapped", tz_country_of("UTC") is None)

# --- Bug 2: hero distinguishes missing vs unknown TZ ------------------------
check("homeInfo has source missing for known-but-absent country",
      "source:'missing'" in HTML and "if (c) return { country:null, source:'missing' }" in HTML)
check("missing-country hero copy kept",
      "Your country isn’t in the data; Germany is shown for comparison." in HTML)
check("unknown-TZ hero copy is honest (not 'isn't in the data')",
      "We couldn’t guess your country from the time zone; Germany is shown for comparison." in HTML)
# The catch-all else branch must use the unknown-TZ sentence, not the missing one.
paint = HTML[HTML.find("function paintHomeControl"):HTML.find("function paintHomeControl") + 2500]
check("paintHomeControl branches missing before unknown fallback",
      "info.source==='missing'" in paint
      and paint.index("info.source==='missing'")
      < paint.index("We couldn’t guess your country from the time zone"))
check("Germany still shown for missing and unknown sources",
      "(info.source==='fallback' || info.source==='missing')" in HTML
      or "(info.source==='missing' || info.source==='fallback')" in HTML)

print(('FAILED: ' + ', '.join(fails)) if fails else 'all checks passed')
sys.exit(1 if fails else 0)
