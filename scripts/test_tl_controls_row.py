#!/usr/bin/env python3
"""Static test: Builder time-lapse transport is one row, prev | play | next.

Run:  python scripts/test_tl_controls_row.py
.field is a column flexbox, so the three buttons stacked vertically; the
transport block must override it to a row and list prev before play before next.
"""
import pathlib, re, sys
HTML = (pathlib.Path(__file__).resolve().parent.parent / "index.html").read_text(encoding="utf-8")
order = [HTML.find(f'id="{i}"') for i in ("tlPrev", "tlPlay", "tlNext")]
checks = [
    ("DOM order prev < play < next", all(o > 0 for o in order) and order == sorted(order)),
    ("transport overrides .field column -> row",
     bool(re.search(r"\.tl-controls \.field\.tl-transport\s*\{[^}]*flex-direction:\s*row", HTML))),
    ("mobile rule keeps the transport on its own full-width row",
     bool(re.search(r"@media \(max-width: 620px\)\s*\{[^@]*\.tl-controls \.field\.tl-transport\s*\{\s*flex:\s*1 1 100%", HTML))),
    ("buttons are not forced to 100% width",
     bool(re.search(r"\.tl-controls \.tl-transport \.btn\s*\{[^}]*width:\s*auto", HTML))),
]
bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("PASS " if ok else "FAIL ") + n)
print(f"{len(checks)-len(bad)}/{len(checks)} passed"); sys.exit(1 if bad else 0)
