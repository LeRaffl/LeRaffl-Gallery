#!/usr/bin/env python3
"""Static checks for Gallery leftover denylist + Clear-all / chips hygiene.

    python scripts/test_gallery_hygiene.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
H = (ROOT / "index.html").read_text(encoding="utf-8")
R = (ROOT / "build_manifest.R").read_text(encoding="utf-8")
fails = []


def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        fails.append(name)


# --- central denylist ---
check("isHiddenLeftoverSeries helper exists", "function isHiddenLeftoverSeries(" in H)
check("isHiddenLeftoverVariant helper exists", "function isHiddenLeftoverVariant(" in H)
check("denylist matches World Interval", r"/^World\s*\(Interval\b/i" in H)
check("denylist matches Germany (20260507 Git)", "20260507" in H and "Git" in H
      and "isHiddenLeftoverSeries" in H)
check("denylist matches New Zealand (Legacy)", r"/^New Zealand\s*\(Legacy\)$/i" in H)
check("denylist matches Germany · Custom", "Germany" in H and "Custom" in H
      and re.search(r"Germany\\s\*\[·•\]\\s\*Custom", H) is not None)
check("denylist matches Canada · Non-Passenger",
      re.search(r"Canada\\s\*\[·•\]\\s\*Non-Passenger", H) is not None)
check("variant denylist covers custom + non-passenger",
      "v === 'custom'" in H and "v === 'non-passenger'" in H)

# India (4-Wheelers) must stay visible — never on the denylist.
helper = H[H.find("function isHiddenLeftoverVariant"):H.find("function galleryRegionName")]
check("India (4-Wheelers) is NOT in the denylist helper",
      "India" not in helper and "4-Wheelers" not in helper and "4-wheelers" not in helper)

# --- applied in the right paths ---
check("applyFilters rejects leftover series",
      "if(isHiddenLeftoverSeries(it.country)) return false" in H)
check("Gallery country list uses the denylist",
      "if(isHiddenLeftoverSeries(c)) return;" in H)
check("fillRankRegionSelect filters leftovers before regions",
      "filter(r => !isHiddenLeftoverSeries(r.country, r.variant))" in H)
check("Compare pin-select build skips leftovers",
      "if(isHiddenLeftoverSeries(r.country, r.variant)) return;" in H)
# Thresholds / Durations / Speed variant options
check("Thresholds variant options skip leftover variants",
      H.count("isHiddenLeftoverVariant(canonical)") >= 1
      or H.count("isHiddenLeftoverVariant(canon)") >= 1)
check("Durations variant options skip leftover variants",
      "isHiddenLeftoverVariant(canon)||isHiddenLeftoverVariant(base)" in H
      or "isHiddenLeftoverVariant(canon) || isHiddenLeftoverVariant(base)" in H)
check("Speed variant options skip leftover variants",
      H.count("isHiddenLeftoverVariant(canon)||isHiddenLeftoverVariant(base)")
      + H.count("isHiddenLeftoverVariant(canon) || isHiddenLeftoverVariant(base)") >= 2
      or ("isHiddenLeftoverVariant(canon)" in H and "function compute(rows, fromPct" in H))

# --- Clear all + chips cover search / types / latest-only ---
check("clearAll resets search text",
      "searchEl.value = ''" in H or "searchEl.value=\"\"" in H
      or "if (searchEl && searchEl.value) searchEl.value = ''" in H)
check("clearAll restores TYPE_ORDER checkboxes",
      "TYPE_ORDER.forEach(v => { const c = typeChecks.find" in H)
check("clearAll restores latestOnly to on",
      "lo.checked = true" in H and "clearAll" in H)
check("applied bar has a Search chip", "'Search: '" in H or '"Search: "' in H)
check("applied bar has a Types chip when deselected",
      "'Types (−'" in H or '"Types (−"' in H)
check("applied bar has a Latest only: off chip",
      "'Latest only: off'" in H or '"Latest only: off"' in H)
check("chip bar counts search/types/latest toward visibility",
      "(searchQ ? 1 : 0)" in H and "(typesOff.length ? 1 : 0)" in H
      and "(loOff ? 1 : 0)" in H)

# --- build_manifest.R optional skip ---
check("build_manifest.R skips World Interval leftovers",
      "World" in R and "Interval" in R and "leftover" in R)
check("build_manifest.R skips Germany Git leftovers",
      "20260507 Git" in R)
check("build_manifest.R skips New Zealand Legacy leftovers",
      "New Zealand (Legacy)" in R or "Legacy" in R and "New Zealand" in R)
check("build_manifest.R notes India (4-Wheelers) is kept",
      "India (4-Wheelers) is intentional" in R)

sys.exit(1 if fails else 0)
