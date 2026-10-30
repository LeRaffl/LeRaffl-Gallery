#!/usr/bin/env python3
"""Static checks for Compare's "Fill with region top-N" button.

    python scripts/test_compare_region_topn.py
"""
import sys
from pathlib import Path

H = (Path(__file__).resolve().parent.parent / "index.html").read_text(encoding="utf-8")
fails = []


def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        fails.append(name)


check("fill controls exist", all(i in H for i in ('id="compareFillRegion"', 'id="compareFillN"', 'id="compareFillBtn"')))
tip = H.split('id="compareFillBtn"')[1][:700] if 'id="compareFillBtn"' in H else ""
check("tooltip defines top as latest TTM BEV share", "latest TTM BEV share" in tip)
check("top-N ranks by params ttm_bev_share, descending",
      "function compareTopNForRegion(" in H and "normNumber(r.ttm_bev_share)" in H.split("function compareTopNForRegion(")[1][:900]
      and "b.ttm - a.ttm" in H)
check("region filter uses the shared matcher", "rankRegionMatcher(regionKey)" in H)
check("uses the chosen Variant", "normalizeBase(document.getElementById('compareVariant')" not in H and "const vc = normalizeBase(variant)" in H)
check("extras are rebuilt via addCompareExtra", "addCompareExtra();" in H.split("function fillCompareWithRegionTopN(")[1][:2500]
      if "function fillCompareWithRegionTopN(" in H else False)
check("fill runs Compare", "getElementById('compareBuild')?.click()" in H)
check("button click wired", "getElementById('compareFillBtn')?.addEventListener('click'" in H)
check("note states the ranking basis", "by latest TTM BEV share:" in H)
check("percent shown in fixed international format", "(t.ttm * 100).toFixed(1)" in H)
import re
for _id in ("compareFillRegion", "compareFillN"):
    _tag = re.search(r'<select[^>]*id="%s"[^>]*>' % _id, H)
    check(f"#{_id} uses the shared .country-field look (needs #377)", bool(_tag and "country-field" in _tag.group(0)))
sys.exit(1 if fails else 0)
