#!/usr/bin/env python3
"""Static checks for the shared region preset chips (regionPresets) on the
Fleet and Builder country pickers.

    python scripts/test_region_presets.py
"""
import re
import sys
from pathlib import Path

H = (Path(__file__).resolve().parent.parent / "index.html").read_text(encoding="utf-8")
fails = []


def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        fails.append(name)


check("regionPresets helper exists", "function regionPresets(" in H)
check("regionOfCountryName helper exists", "function regionOfCountryName(" in H)
check("helper reads COUNTRY_REGION lazily", "window.COUNTRY_REGION" in H)
check("helper offers an EU chip from BUILDER_GROUPS", "BUILDER_GROUPS" in H and "'EU'" in H)
check("helper re-renders on option changes", "MutationObserver" in H.split("function regionPresets(")[1][:6000])
check("click replaces, ctrl/meta/shift adds",
      re.search(r"ctrlKey\s*\|\|\s*e\.metaKey\s*\|\|\s*e\.shiftKey", H) is not None)
check("chip CSS mirrors the Raw Data presets",
      re.search(r"\.region-presets button\s*\{[^}]*border-radius:2px[^}]*padding:3px 8px[^}]*font-size:11\.5px", H) is not None)
check("enhanceCountryMultiSelect wires opts.regions",
      "if(opts.regions)" in H and "regionPresets(sel, wrap" in H)
check("Builder picker passes regions:true",
      "placeholder: 'Search countries', regions: true" in H)
check("Fleet picker passes regions:true",
      "placeholder: 'Search fleet countries', regions: true" in H)
check("#builderGroups quick-groups select is kept", 'id="builderGroups"' in H)
check("compact variant filters do not get region chips",
      "compact: true, regions" not in H and "compact:true, regions" not in H)

sys.exit(1 if fails else 0)
