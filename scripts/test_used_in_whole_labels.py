#!/usr/bin/env python3
"""Static checks for #342: countries whose Whole includes used imports.

Gallery cards, Compare, Rankings, Fleet and the Builder must mark Georgia
and Malaysia, and must leave Albania's gallery / cross-country labels
unchanged (the source still cannot be split).

    python scripts/test_used_in_whole_labels.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
H = (ROOT / "index.html").read_text(encoding="utf-8")
GLOSS = (ROOT / "docs/architecture/09-glossary.md").read_text(encoding="utf-8")
fails = []


def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        fails.append(name)


def block_between(src, start, end_fn):
    i = src.find(start)
    if i < 0:
        return ""
    j = end_fn(src, i)
    return src[i:j]


# --- maps exist and have the documented members ---
check("SCOPE_BADGES is defined", "const SCOPE_BADGES = {" in H)
check("USED_IN_WHOLE is defined", "const USED_IN_WHOLE = {" in H)
check("usedInWholeScope helper exists", "function usedInWholeScope(" in H)
check("usedInWholeMark helper exists", "function usedInWholeMark(" in H)
check("usedInWholeNote helper exists", "function usedInWholeNote(" in H)
check("renderUsedInWholeNote helper exists", "function renderUsedInWholeNote(" in H)
check("updateFleetUsedNote helper exists", "function updateFleetUsedNote(" in H)

# Extract the two object literals (next top-level '};' after the const).
scope_block = block_between(
    H, "const SCOPE_BADGES = {",
    lambda s, i: s.find("};", i) + 2,
)
used_block = block_between(
    H, "const USED_IN_WHOLE = {",
    lambda s, i: s.find("};", i) + 2,
)
check("SCOPE_BADGES lists USA", "USA:" in scope_block)
check("SCOPE_BADGES lists Georgia", "Georgia:" in scope_block)
check("SCOPE_BADGES lists Malaysia", "Malaysia:" in scope_block)
check("SCOPE_BADGES does not list Albania", "Albania:" not in scope_block)
check("USED_IN_WHOLE lists Georgia", "Georgia:" in used_block)
check("USED_IN_WHOLE lists Malaysia", "Malaysia:" in used_block)
check("USED_IN_WHOLE does not list Albania", "Albania:" not in used_block)
check("USED_IN_WHOLE does not list Peru", "Peru:" not in used_block)
check("Albania omission is documented next to the maps",
      "Albania is deliberately omitted" in H or "Albania is left unmarked" in H
      or "deliberately omitted" in scope_block)

# Mark character is †, distinct from the ACEA * caveat.
check("usedInWholeMark uses a dagger", " ? ' †' : ''" in H or '? " †" : ""' in H)
check("ACEA caveat still uses a star", "hasEvLabel" in H and "' *'" in H)

# --- wired into the four views + Builder (same country list as Compare) ---
check("gallery cards still call scopeBadgeFor",
      "${scopeBadgeFor(it.country)}" in H or "scopeBadgeFor(it.country)" in H)
check("Builder country list uses usedInWholeMark",
      "usedInWholeMark(r.country, r.variant)" in H
      and "usedInWholeNote(usedMarked)" in H)
check("Compare country list uses usedInWholeMark",
      "usedInWholeMark(r.country, vc)" in H
      and "usedInWholeNote(usedMarked)" in H)
check("Thresholds table marks the country cell",
      "thresholdsUsedNote" in H
      and "usedInWholeMark(r.country, r.variant)" in H)
check("Durations table marks the country cell",
      "durationsUsedNote" in H
      and "renderUsedInWholeNote(document.getElementById('durationsUsedNote')" in H)
check("Speed interval chart marks labels and the note",
      "speedUsedNote" in H
      and "usedInWholeMark(d.country, d.baseCanon)" in H
      and "renderUsedInWholeNote(document.getElementById('speedUsedNote')" in H)
check("Fleet picker marks countries whose Whole includes used imports",
      "fleetUsedNote" in H
      and "usedInWholeMark(c, 'whole')" in H
      and "updateFleetUsedNote()" in H)

# HTML mounts exist.
for mid in ("thresholdsUsedNote", "durationsUsedNote", "speedUsedNote", "fleetUsedNote"):
    check(f"#{mid} mount exists", f'id="{mid}"' in H)

# Glossary records the policy, including leaving Albania's UI labels as they are.
check("glossary mentions the gallery / † marks",
      "SCOPE_BADGES" in GLOSS and "USED_IN_WHOLE" in GLOSS)
check("glossary still leaves Albania's UI labels to the source split",
      "gallery and cross-country labels stay as" in GLOSS
      or "labels stay as they are until the source can be split" in GLOSS)

# usedInWholeNote / rankings cells call escapeHtml. The helper inside the
# Builder IIFE is not visible to them, so a top-level copy must exist above
# that IIFE (regression: "escapeHtml is not defined" on Compare).
builder = H.find("// -------- BUILDER")
top = H[:builder] if builder != -1 else H
check("top-level escapeHtml exists before the Builder IIFE",
      "function escapeHtml(" in top)

if fails:
    print(f"\n{len(fails)} failed:")
    for n in fails:
        print(" -", n)
    sys.exit(1)
print("\nall used-in-whole label checks passed")
