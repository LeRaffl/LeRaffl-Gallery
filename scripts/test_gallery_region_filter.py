#!/usr/bin/env python3
"""Static checks for the Gallery sidebar region filter (#regionGal).

    python scripts/test_gallery_region_filter.py
"""
import sys
from pathlib import Path

H = (Path(__file__).resolve().parent.parent / "index.html").read_text(encoding="utf-8")
fails = []


def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        fails.append(name)


check("region select exists in the Gallery sidebar", 'id="regionGal"' in H)
check("region row sits before the Country row",
      0 < H.find('id="regionGal"') < H.find('for="countryPick"'))
check("applyFilters uses the shared region matcher",
      "rankRegionMatcher(regionGal" in H and "if(!inRegion(it.country)) return false" in H)
check("options filled with the shared helper", "fillRankRegionSelect(regionGal" in H)
check("region change re-renders the gallery", "regionGal.addEventListener('change',reset)" in H)
check("country suggestions follow the region", "inR(o.value)" in H)
check("applied bar shows a Region chip", "'Region: '" in H)
check("Clear all resets the region", "regionSel.value = ''; sync();" in H)
check("original country select still the source of truth", 'id="countrySelect" hidden' in H)
sys.exit(1 if fails else 0)
