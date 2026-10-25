#!/usr/bin/env python3
"""Offline tests for the source-page generator's reconciliation section
(`reconciliation:` front-matter tables and the `checks_file:` check table,
scripts/build_source_pages.py). No network, writes nothing to the repo.

    python scripts/test_build_source_pages.py
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_source_pages as bsp  # noqa: E402

TABLE = {
    "title": "From the headline to the charted total",
    "lead": "Lead text.",
    "rows": [
        ["Published national total", "62,590"],
        ["− commercial vehicles", "−9,807"],
        ["= Whole", "51,013"],
        {"cells": ["Police 2025", "624,300"], "url": "https://example.org/p",
         "note": "15 Dec – 14 Dec"},
    ],
    "note": "Under the table.",
}


def test_no_reconciliation_renders_nothing():
    assert bsp.build_reconciliation({}) == ""
    assert bsp.validate_reconciliation({}, "x") == []


def test_table_renders_rows_bold_result_numbers_and_links():
    html = bsp.build_reconciliation({"reconciliation": TABLE})
    assert "<h2>Why other figures differ</h2>" in html
    assert "<h3>From the headline to the charted total</h3>" in html
    assert '<p class="fig-lead">Lead text.</p>' in html
    assert '<th>Step</th><th class="num">Units</th>' in html  # default head
    assert '<tr class="strong"><td>= Whole</td><td class="num">51,013</td></tr>' in html
    assert '<td class="num">−9,807</td>' in html
    assert '<a href="https://example.org/p">Police 2025</a>' in html
    assert '<div class="dim rnote">15 Dec – 14 Dec</div>' in html
    assert '<p class="fig-note">Under the table.</p>' in html
    assert html.count("<tr") == 5  # head + 4 rows


def test_list_of_tables_custom_head_and_heading():
    fm = {"reconciliation_heading": "Reconciliation",
          "reconciliation": [TABLE, {"title": "Second", "head": ["Figure", "Theirs", "Ours", "Why"],
                                     "rows": [["CSGT 2025", "624,300", "592,798", "registrations, not sales"]]}]}
    html = bsp.build_reconciliation(fm)
    assert "<h2>Reconciliation</h2>" in html and "<h3>Second</h3>" in html
    assert '<td>registrations, not sales</td>' in html  # text stays left-aligned
    assert '<td class="num">592,798</td>' in html
    assert bsp.validate_reconciliation(fm, "x") == []


def test_text_is_escaped():
    html = bsp.build_reconciliation({"reconciliation": {"title": "<b>", "rows": [["a & b", "<i>"]]}})
    assert "<h3>&lt;b&gt;</h3>" in html
    assert "a &amp; b" in html and "&lt;i&gt;" in html


def test_numeric_detection():
    for v in ("62,590", "−9,807", "+5.3 %", "23,627 · 2,171 · 113", "0", "±100", "51,013 ✓"):
        assert bsp._NUMERIC.match(v), v
    for v in ("VAMA", "2025-07", "about 5 %", "−2 % to +10 %"):
        assert not bsp._NUMERIC.match(v), v


def test_validation_catches_shape_errors():
    bad = {"reconciliation": [{"rows": [["only one cell"], "not a row"]}, "x"],
           "checks_file": "market/x_checks.csv"}
    probs = bsp.validate_reconciliation(bad, "doc.md")
    assert any("has no title" in p for p in probs)
    assert any("row 1 has 1 cells, head has 2" in p for p in probs)
    assert any("row 2 is neither a list nor a mapping" in p for p in probs)
    assert any("reconciliation[1] is not a mapping" in p for p in probs)
    assert any("checks_file must be a .json path" in p for p in probs)
    assert bsp.validate_reconciliation({"reconciliation": "text"}, "d")[0].endswith(
        "must be a table or a list of tables")
    assert any("has no rows" in p for p in bsp.validate_reconciliation(
        {"reconciliation": {"title": "t"}}, "d"))


def test_checks_file_renders_and_missing_file_is_silent():
    doc = {"as_of": "2026-09", "checks": [
        {"period": "2026-09", "check": "Media total (VnEconomy)", "url": "https://e.org/a",
         "ours": 62590, "theirs": 62590, "gap": 0, "gap_pct": 0.0,
         "tolerance": "0", "status": "pass"},
        {"period": "2025-07", "check": "Media total", "ours": 46819, "theirs": 46830,
         "gap": -11, "gap_pct": -0.02, "tolerance": "0", "status": "warn",
         "note": "article used VinFast 11,490"},
        {"period": "2026-H1", "check": "Police registrations", "ours": 343126,
         "theirs": None, "status": "missing", "tolerance": "−2 % … +15 %"},
    ]}
    with tempfile.TemporaryDirectory() as tmp:
        old = bsp.REPO
        try:
            bsp.REPO = Path(tmp)
            (Path(tmp) / "market").mkdir()
            (Path(tmp) / "market" / "x_checks.json").write_text(json.dumps(doc))
            html = bsp.build_reconciliation({"checks_file": "market/x_checks.json"})
            assert bsp.build_reconciliation({"checks_file": "market/none.json"}) == ""
        finally:
            bsp.REPO = old
    assert "Checked through <code>2026-09</code>" in html
    assert '<a href="https://e.org/a">Media total (VnEconomy)</a>' in html
    assert '<td class="num">62,590</td>' in html
    assert "−11" in html and "(−0.02 %)" in html
    assert "chk--ok" in html and "chk--warn" in html and "chk--miss" in html
    assert "article used VinFast 11,490" in html
    assert '<td class="num">—</td>' in html  # missing reference figure


def test_page_places_section_after_how_it_works():
    fm = {"country": "Testland", "slug": "testland", "source_name": "S",
          "variants": ["Whole"], "method": "pdf", "notes": ["How."],
          "reconciliation": TABLE}
    page = bsp.build_page(fm, {})
    assert page.index("<h2>How it works</h2>") < page.index("<h2>Why other figures differ</h2>")
    assert "table.recon{" in page


def test_repo_front_matter_still_valid():
    entries, problems = bsp.collect_entries()
    assert not problems, problems
    assert entries


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    for name, fn in tests:
        fn()
        print(f"ok  {name}")
    print(f"{len(tests)} tests passed")
