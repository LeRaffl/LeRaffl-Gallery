#!/usr/bin/env python3
"""Static test: Status tag labels are Done / On track / Behind (owner decision, 2026-10-29).

Run:  python scripts/test_status_labels.py
Internal keys (past / ontrack / late, data-tag-value, CSS hooks) stay unchanged;
the Start group keeps Early / Mid / Late.
"""
import pathlib, re, sys
R = pathlib.Path(__file__).resolve().parent.parent
HTML = (R / "index.html").read_text(encoding="utf-8")
TS = (R / "assets/tag_system.js").read_text(encoding="utf-8")
DOC = (R / "docs/architecture/61-tag-system.md").read_text(encoding="utf-8")
TAGS = (R / "sources/tags.html").read_text(encoding="utf-8")
checks = [
    ("card tag: past -> Done", "{ v: 'past',    label: 'Done' }" in TS),
    ("card tag: late -> Behind", "{ v: 'late',    label: 'Behind' }" in TS),
    ("card tag: On track unchanged", "label: 'On track'" in TS),
    ("filter list in tag_system.js", "[['past', 'Done'], ['ontrack', 'On track'], ['late', 'Behind']]" in TS),
    ("Start group list unchanged", "[['early', 'Early'], ['mid', 'Mid'], ['late_start', 'Late']]" in TS),
    ("sidebar chip Done (key past)", bool(re.search(r'value="past" data-tag-value="past"/><span class="fx-tl">Done</span>', HTML))),
    ("sidebar chip Behind (key late)", bool(re.search(r'value="late" data-tag-value="late"/><span class="fx-tl">Behind</span>', HTML))),
    ("sidebar Start chip still Late (key late_start)", bool(re.search(r'value="late_start" data-tag-value="late_start"/><span class="fx-tl">Late</span>', HTML))),
    ("CATS status labels", "past:    { label: 'Done'" in HTML and "late:    { label: 'Behind'" in HTML),
    ("FAQ tag text", "<b>Done</b> = projected" in HTML and "<b>Behind</b> = projected" in HTML),
    ("no old status label left in app/assets", "Past 80" not in TS and "Past 80" not in HTML and "<b>Late</b> = projected" not in HTML),
    ("doc source updated", "Status (Done, On track, Behind)" in DOC and "Past 80" not in DOC),
    ("generated sources/tags.html in sync", "Done, On track, Behind" in TAGS and "Past 80" not in TAGS),
]
bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("PASS " if ok else "FAIL ") + n)
print(f"{len(checks)-len(bad)}/{len(checks)} passed"); sys.exit(1 if bad else 0)
