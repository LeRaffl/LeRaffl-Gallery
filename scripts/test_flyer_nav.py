#!/usr/bin/env python3
"""Offline tests: previous / next navigation on the country and region briefs.

Each brief (sources/flyer/<slug>.html) links the brief before and after it in
the directory's order (highest BEV share first, wrapping around), shows
"pos / total" and steps with the arrow keys. None of it may reach the PDF.

    python scripts/test_flyer_nav.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import build_source_pages as bsp  # noqa: E402
import flyer  # noqa: E402

FLYER_DIR = ROOT / "sources" / "flyer"


def _items(n):
    return [{"country": f"C{i}", "slug": f"c{i}", "share": float(n - i)} for i in range(n)]


def test_nav_html_links_both_neighbours_and_position():
    html = flyer.nav_html({"country": "UK", "slug": "uk"},
                          {"country": "Côte & Co", "slug": "cote"}, 22, 61)
    assert 'class="fl-nav-prev" rel="prev" href="uk.html"' in html
    assert 'class="fl-nav-next" rel="next" href="cote.html"' in html
    assert ">22 / 61<" in html
    assert "Côte &amp; Co" in html and "Côte & Co" not in html
    assert "ArrowLeft" in html and "ArrowRight" in html
    # typing in a field or using a shortcut must not page away
    assert "INPUT|TEXTAREA|SELECT" in html and "e.metaKey" in html


def test_flyer_nav_follows_the_directory_order_and_wraps():
    items = _items(4)[::-1]          # shuffled input; order comes from shares
    nav = bsp.flyer_nav(items, "Country")
    order = [i["slug"] for i in flyer.index_order(items)]
    assert order == ["c0", "c1", "c2", "c3"]
    assert 'href="c3.html"' in nav["c0"].split("fl-nav-pos")[0]   # first wraps to last
    assert 'href="c0.html"' in nav["c3"].split("fl-nav-pos")[1]   # last wraps to first
    assert ">1 / 4<" in nav["c0"] and ">4 / 4<" in nav["c3"]
    assert bsp.flyer_nav(_items(1), "Country") == {}


def test_template_has_one_slot_in_the_bar_and_print_hides_it():
    bar = flyer.FLYER_TEMPLATE.split('<div class="fl-bar">')[1].split("</div>")[0]
    assert flyer.NAV_SLOT in bar
    assert flyer.FLYER_TEMPLATE.count(flyer.NAV_SLOT) == 1
    prn = flyer.FLYER_CSS.split("@media print{")[1].split("\n}")[0]
    assert ".fl-nav" in prn and "display:none" in prn
    # the A4 sheet itself is untouched by the navigation styles
    assert ".sheet{width:794px;height:1123px" in flyer.FLYER_CSS
    assert flyer.with_nav("a" + flyer.NAV_SLOT + "b", "N") == "aNb"
    # dark desk around the paper, screen only (never in print)
    assert "@media screen and (prefers-color-scheme:dark){" in flyer.FLYER_CSS
    dark = flyer.FLYER_CSS.split("@media screen and (prefers-color-scheme:dark){")[1].split("\n}")[0]
    assert ".fl-nav a{" in dark and ".sheet{background" not in dark


def test_generated_briefs_form_one_ring_per_kind():
    if not FLYER_DIR.is_dir():
        return
    pages = {p.stem: p.read_text(encoding="utf-8") for p in FLYER_DIR.glob("*.html")
             if p.stem != "index" and not p.stem.endswith("_social")}
    if not any("fl-nav" in h for h in pages.values()):
        return  # pages not regenerated yet; CI's build-source-pages.yml does
    for kind in ("Country", "Region"):
        ring = {}
        for slug, h in pages.items():
            m = re.search(r'title="%s (\d+) of (\d+)' % kind, h)
            if not m:
                continue
            prev = re.search(r'fl-nav-prev" rel="prev" href="([^"]+)\.html"', h).group(1)
            nxt = re.search(r'fl-nav-next" rel="next" href="([^"]+)\.html"', h).group(1)
            ring[slug] = (int(m.group(1)), int(m.group(2)), prev, nxt)
        if not ring:
            continue
        totals = {t for _, t, _, _ in ring.values()}
        assert totals == {len(ring)}, (kind, totals, len(ring))
        assert sorted(p for p, _, _, _ in ring.values()) == list(range(1, len(ring) + 1))
        for slug, (_, _, prev, nxt) in ring.items():
            assert ring[nxt][2] == slug and ring[prev][3] == slug, slug
    for p in FLYER_DIR.glob("*_social.html"):
        assert "fl-nav" not in p.read_text(encoding="utf-8"), p.name   # PNG canvas


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"ok  {name}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL {name}: {exc!r}")
    print(f"{len(tests) - failed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
