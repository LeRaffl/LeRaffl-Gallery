#!/usr/bin/env python3
"""Static checks: Submit Data variant dropdown + chevron CSS.

Run:  python scripts/test_submit_variants.py

Bugs:
1. #sdVariant stayed hardcoded to Whole; SD_COUNTRIES.variants was never read.
2. Shorthand `background:` on .sd-grid / .sd-row-grid selects wiped the global
   select chevron (background-image). Country got an ID restore; Variant and
   the Interval/Month/Quarter/Year row selects stayed flat.
"""
import re
import sys
from pathlib import Path

HTML = (Path(__file__).resolve().parent.parent / "index.html").read_text(encoding="utf-8")
fails = []


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        fails.append(name)


# --- Variant refill ---
check("sdFillVariants helper exists", "function sdFillVariants(" in HTML)
check("sdVariantLabel helper exists", "function sdVariantLabel(" in HTML)
check("Whole keeps the long label", 'Whole (= "New Cars")' in HTML)
check("sdInit calls sdFillVariants", "sdFillVariants();" in HTML)
check("country change refills variants then reloads",
      "() => { sdFillVariants(); sdOnCountryChange(); }" in HTML
      or "()=>{ sdFillVariants(); sdOnCountryChange(); }" in HTML
      or re.search(r"addEventListener\('change',\s*\(\)\s*=>\s*\{\s*sdFillVariants\(\);\s*sdOnCountryChange\(\);", HTML) is not None)
check("variant change reloads schema",
      re.search(r"sdEl\('sdVariant'\)\.addEventListener\('change',\s*sdOnCountryChange\)", HTML) is not None)
check("sdFillVariants reads SD_COUNTRIES.variants",
      "entry.variants" in HTML[HTML.find("function sdFillVariants"):HTML.find("function sdInit")])
check("defaults to Whole when present",
      "variants.includes('Whole') ? 'Whole'" in HTML)
# Belgium still lists the multi-variant set the form must expose.
m = re.search(r"\{\s*country:\s*'Belgium',\s*variants:\s*\[([^\]]+)\]", HTML)
bel = m.group(1) if m else ""
check("Belgium lists Private/Vans/HDV/Buses in SD_COUNTRIES",
      all(v in bel for v in ("'Whole'", "'Private'", "'Vans'", "'HDV'", "'Buses'")))
# Markup must not hardcode a lone Whole option that overrides the refill.
tag = re.search(r'<select[^>]*id="sdVariant"[^>]*>.*?</select>', HTML, re.S)
inner = tag.group(0) if tag else ""
check("#sdVariant has no hardcoded lone Whole option",
      'id="sdVariant"' in HTML and "<option" not in inner)

# --- Chevron CSS: no shorthand background: that drops background-image ---
# Narrow to the Submit Data CSS block + the later shared override that named
# .sd-grid select / .sd-row-grid .sd-cell select.
sd_css = HTML[HTML.find("/* ── Submit Data tab"):HTML.find(".sd-msg.error")]
# The early rules must use background-color, not background:
check(".sd-grid select uses background-color (not shorthand background)",
      re.search(r"\.sd-grid input,\.sd-grid select\{[^}]*background-color:var\(--surface-2\)", sd_css) is not None)
check(".sd-grid select rule has no shorthand background:",
      re.search(r"\.sd-grid input,\.sd-grid select\{[^}]*\bbackground:", sd_css) is None)
check(".sd-row-grid cell select uses background-color",
      re.search(r"\.sd-row-grid \.sd-cell input,\.sd-row-grid \.sd-cell select\{[^}]*background-color:var\(--surface-2\)", sd_css) is not None)
check(".sd-row-grid cell select rule has no shorthand background:",
      re.search(r"\.sd-row-grid \.sd-cell input,\.sd-row-grid \.sd-cell select\{[^}]*\bbackground:", sd_css) is None)
check(".sd-grid select keeps chevron padding-right gutter",
      re.search(r"\.sd-grid select\{[^}]*padding:[^;]*36px", sd_css) is not None
      or re.search(r"\.sd-grid select\{[^}]*padding-right:\s*36px", sd_css) is not None)
check(".sd-row-grid cell select keeps chevron padding-right gutter",
      re.search(r"\.sd-row-grid \.sd-cell select\{[^}]*padding:[^;]*36px", sd_css) is not None
      or re.search(r"\.sd-row-grid \.sd-cell select\{[^}]*padding-right:\s*36px", sd_css) is not None)

# Later theme override that previously re-wiped background-image.
override = re.search(
    r"\.sd-grid input,\s*\.sd-grid select,\s*\.sd-row-grid \.sd-cell input,\s*\.sd-row-grid \.sd-cell select\{([^}]*)\}",
    HTML,
)
obody = override.group(1) if override else ""
check("later sd select override uses background-color",
      "background-color:var(--surface-2)" in obody)
check("later sd select override has no shorthand background:",
      re.search(r"(?<!-)background:", obody) is None)

print(f"{18 - len(fails)}/18 passed")
sys.exit(1 if fails else 0)
