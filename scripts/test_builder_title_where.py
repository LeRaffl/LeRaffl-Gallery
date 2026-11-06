#!/usr/bin/env python3
"""Static checks: Builder chart title follows the current country selection.

Run:  python scripts/test_builder_title_where.py

Bug: Quick groups defaulted to World, region chips only changed #builderCountries,
and the title read builderGroups.selectedOptions — so Europe/Asia chips (and
manual edits) still titled the chart "… — World". PNG download used the same
title. builderTitleWhere() must derive a truthful label from the selection.
"""
import pathlib, sys

HTML = (pathlib.Path(__file__).resolve().parent.parent / "index.html").read_text(encoding="utf-8")
fails = []


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        fails.append(name)


check("builderTitleWhere helper exists", "function builderTitleWhere(" in HTML)
check("builderGroupMatchesSelection helper exists", "function builderGroupMatchesSelection(" in HTML)
check("builderRegionPresetLabel helper exists", "function builderRegionPresetLabel(" in HTML)
check("build() uses builderTitleWhere(chosen)", "const where = builderTitleWhere(chosen);" in HTML)
check("title no longer trusts selectedOptions[0] alone",
      "groupSelNow && groupSelNow.selectedOptions[0]" not in HTML)
check("applyBuilderGroup guards against clearing itself",
      "let applyingBuilderGroup = false;" in HTML
      and "applyingBuilderGroup = true;" in HTML)
check("country change clears a stale Quick group",
      "groupSel.value = '';" in HTML
      and "builderGroupMatchesSelection(groupSel.value, chosen)" in HTML)
region_fn = HTML.split("function builderRegionPresetLabel(")[1][:1200]
check("region preset path can return Europe",
      "return r;" in region_fn and "REGION_PRESET_ORDER" in region_fn)
check("publication title still uses where",
      "'BEV, ICE & PHEV share — ' + where" in HTML)

print(f"{9 - len(fails)}/9 passed")
sys.exit(1 if fails else 0)
