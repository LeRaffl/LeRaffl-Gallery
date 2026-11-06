#!/usr/bin/env python3
"""Static checks for UI polish: Raw Data picker catch-up, multiselect search,
label wiring, region wording, Fleet title case, empty-state Clear all, card footer.

    python scripts/test_ui_polish.py
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


# --- 10. Raw Data picker catch-up ---
check("Raw Data summary is a button (labelable, Gallery-like)",
      re.search(r'<button[^>]*id="rdPickSum"', H) is not None)
check("Raw Data summary has a chevron via --select-arrow",
      ".rd-picksum{" in H and "background-image:var(--select-arrow)" in H.split(".rd-picksum{")[1][:500])
check("Raw Data list has continent headings (.rd-pick-h)",
      ".rd-pick-h{" in H and "rd-pick-h" in H.split("function paintPicker()")[1][:2500])
check("Raw Data Escape closes the picker",
      "e.key==='Escape'" in H.split("function wire()")[1][:1200]
      and "closePick()" in H.split("function wire()")[1][:1200])
check("Raw Data open focuses the search box",
      "qIn.focus({ preventScroll: true })" in H.split("function wire()")[1][:1200]
      or "qIn.focus({preventScroll:true})" in H.split("function wire()")[1][:1200])
check("Raw Data search uses SEARCH_ALIASES (UK / United Kingdom)",
      "SEARCH_ALIASES[n]" in H.split("function paintPicker()")[1][:2000])
check("Raw Data Countries label is wired with for/id",
      'for="rdPickSum"' in H and 'id="rdPickSum"' in H)

# --- 11. Builder / Fleet multiselect search ---
check("multiselect search has an aria-label",
      "search.setAttribute('aria-label'" in H)
check("multiselect search does not rely on option.hidden alone",
      "o.hidden = q &&" not in H
      and "optionPool" in H
      and "replaceChildren" in H.split("applySearchFilter")[1][:800])
check("Builder options get SEARCH_ALIASES on dataset.search",
      "SEARCH_ALIASES[c]" in H.split("function initBuilder")[1][:900]
      or "SEARCH_ALIASES[c]" in H.split("initBuilder(rows)")[1][:1200])
check("Fleet search keeps UK aliases",
      "SEARCH_ALIASES[shown]" in H.split("function populateFleetCountries")[1][:2000])

# --- 12. Labels without for ---
for sid in ("compareSlot1", "compareSlot2", "compareSlot3", "fleetCountries", "compareVariant"):
    check(f'label for="{sid}" present', f'for="{sid}"' in H)
check("Powertrain uses aria-labelledby group",
      'id="comparePowertrainLabel"' in H and 'aria-labelledby="comparePowertrainLabel"' in H)
check("Compare extras get a visible Series label",
      "compare-extra-lab" in H and "Series " in H.split("function addCompareExtra()")[1][:800])
check("Raw Data Units/Show/Axes use aria-labelledby",
      all(x in H for x in ("rdUnitsLab", "rdTfLab", "rdQualLab", "rdAxLab")))

# --- 13. Region dropdowns ---
for rid in ("regionThr", "regionDur", "speedRegion"):
    tag = re.search(r'<select[^>]*id="%s"[^>]*>' % rid, H)
    check(f"#{rid} carries country-field", bool(tag and "country-field" in tag.group(0)))
check("fillRankRegionSelect default is All regions",
      '<option value="">All regions</option>' in H)
check("Compare fill default option text is All regions",
      "fillRegion.options[0].textContent = 'All regions'" in H)
check("no region-filter 'All countries' left in fillRankRegionSelect",
      "All countries</option><optgroup label=\"Continents\">" not in H)

# --- 14. Group label wording ---
check("Builder Small Markets has a single space before (",
      "Small Markets (&lt;50k units/year)" in H
      and "Small Markets  (" not in H)
check("Compare Small Markets uses units/year like Builder",
      "Small Markets (<50k units/year)" in H
      and "new cars/yr" not in H)
check("Compare Pin 1 placeholder is not Choose region",
      "Choose region" not in H
      and ("— Choose —" in H or "— Choose country —" in H))

# --- 15. Fleet category capitalization ---
check("Fleet checkbox labels use title case Diesel/Petrol/Hybrid/Other",
      "label: 'Diesel'" in H and "label: 'Petrol'" in H
      and "label: 'Hybrid (combined PHEV+HEV)'" in H
      and "label: 'Other'" in H)
check("Fleet plot labels are not ALL CAPS for those categories",
      "label:'Diesel'" in H and "label:'Petrol'" in H
      and "label:'Hybrid'" in H and "label:'Other'" in H)
check("Fleet data keys stay uppercase (DIESEL/PETROL/HYBRID/OTHERS)",
      "key:'DIESEL'" in H and "key:'PETROL'" in H
      and "key:'HYBRID'" in H and "key:'OTHERS'" in H)

# --- 17. Card footer height ---
foot = H.split(".card.g .footer{")[1][:400]
check("Gallery card footer uses a 3-column grid for actions",
      "grid-template-columns:auto auto auto" in foot)
check("filename spans the full footer row",
      "grid-column:1 / -1" in H.split(".card.g .footer .filename{")[1][:120])

# --- 18. Empty state Clear all ---
check("empty state has a Clear all control",
      'id="emptyClear"' in H and "No matches. Relax filters." in H)
check("empty Clear all hooks the shared clearAll / __fxClearAll",
      "window.__fxClearAll = clearAll" in H
      and "emptyClear.addEventListener('click', clearAll)" in H)

sys.exit(1 if fails else 0)
