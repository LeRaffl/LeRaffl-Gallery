#!/usr/bin/env python3
"""Static test: user-visible percentages are written without a space ("80%", not "80 %").

Run:  python scripts/test_percent_spacing.py
Scope: index.html (code and markup; comment lines are ignored), the generated
source pages (sources/*.html, sources/tags.html included) and the generator's
own gap text. Numbers keep their international format; only the space before
"%" goes. German comments ("8 %") and modulo arithmetic ("i % 2") are not
user-visible and not matched.
"""
import pathlib, re, sys
R = pathlib.Path(__file__).resolve().parent.parent
SPACED = re.compile(r"\d %(?! ?\d)")               # "80 %", not "i % 2"
DYN = re.compile(r"\}\s%(?!\d)|\+\s*'\s%'|\)\s*\+\s*'\s%[^/]")  # `${x} %`, + ' %'
def code_lines(text):
    for i, l in enumerate(text.split("\n"), 1):
        s = l.lstrip()
        if s.startswith(("//", "/*", "*")):
            continue
        yield i, l
bad = []
html = (R / "index.html").read_text(encoding="utf-8")
for i, l in code_lines(html):
    if i in (13094, 15303) or "nicht trennen" in l or "gegen 45,2" in l:   # German block-comment lines
        continue
    if SPACED.search(l) or DYN.search(l):
        bad.append(f"index.html:{i}: {l.strip()[:100]}")
for p in sorted((R / "sources").glob("*.html")):
    t = p.read_text(encoding="utf-8")
    for m in SPACED.finditer(t):
        bad.append(f"{p.name}: …{t[max(0, m.start()-30):m.end()+20]!r}")
gen = (R / "scripts/build_source_pages.py").read_text(encoding="utf-8")
if "({g_txt} %)" in gen:
    bad.append("scripts/build_source_pages.py: gap text still spaced")
checks = [
    ("no spaced 'N %' in index.html code / markup", not any(b.startswith("index.html") for b in bad)),
    ("no spaced 'N %' in generated sources/*.html", not any(b.startswith(tuple(p.name for p in (R/'sources').glob('*.html'))) for b in bad)),
    ("generator gap text unspaced", "({g_txt}%)</span>" in gen),
    ("map legend: '4.2% BEV'", "toFixed(1)}% BEV in the last 12 months" in html),
    ("pct() helper unspaced", "replace(/\\.0$/, '') + '%';" in html),
    ("band label unspaced", "'95% confidence band'" in html),
]
for n, ok in checks: print(("PASS " if ok else "FAIL ") + n)
for b in bad[:30]: print("  spaced:", b)
failed = [n for n, ok in checks if not ok]
print(f"{len(checks)-len(failed)}/{len(checks)} passed"); sys.exit(1 if failed else 0)
