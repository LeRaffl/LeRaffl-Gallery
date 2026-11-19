#!/usr/bin/env python3
"""Offline tests: the brief directory grid, its light theme, and A4 logos.

    python scripts/test_flyer_index.py
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_source_pages as bsp  # noqa: E402
import flyer  # noqa: E402


def test_index_cards_keep_the_grid_when_a_flag_is_missing():
    entries, _ = bsp.collect_entries()
    params = bsp.load_params()
    items = [bsp.flyer_summary(fm, params) for fm, _ in entries]
    naive = [i for i in items
             if not (bsp.mc.REPO / "assets" / "flags" / f"{i['slug']}.png").is_file()]
    assert naive, "fixture: at least one slug without a naive flag file"
    html = flyer.build_index(items, "../../assets/theme.css")
    cards = re.findall(r'<a class="ix-card".*?</a>', html, re.S)
    assert len(cards) == len(items)
    for card in cards:
        # rank, then a flag slot (img or empty span) — never a shifted grid
        assert re.search(r'<span class="ix-rank">[^<]*</span>'
                         r'(?:<img |<span class="ix-noflag">)', card), card[:160]


def test_index_pins_light_and_lists_regions():
    import inspect
    html = flyer.build_index([], "../../assets/theme.css")
    assert 'data-theme="light"' in html
    if "regions" not in inspect.signature(flyer.build_index).parameters:
        return  # the region section arrives with the region-flyer branch
    html = flyer.build_index([], "../../assets/theme.css", regions=[
        {"country": "EU", "slug": "eu", "share": 24.1, "delta": 7.2,
         "head": "About 1 in 4 new cars is battery electric.", "through": "Oct 2026"}])
    assert "Region briefs" in html and 'href="eu.html"' in html
    assert re.search(r'<span class="ix-rank"></span>'
                     r'(?:<img |<span class="ix-noflag">)', html)


def test_a4_brand_block_shows_logos():
    try:
        import market_structure  # noqa: F401
    except ImportError:
        return  # the brand block arrives with #452
    entries, _ = bsp.collect_entries()
    fm = next(fm for fm, _ in entries if fm.get("country") == "Ireland")
    params = bsp.load_params()
    html = bsp.build_flyer_page(fm, params)
    assert 'class="ms-logo"' in html


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    for name, fn in tests:
        fn()
        print(f"ok  {name}")
    print(f"{len(tests)} tests passed")
