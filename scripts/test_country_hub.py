#!/usr/bin/env python3
"""Offline tests: country briefs and sources up front in the Gallery.

The Gallery shows each country's brief, social card and source page in a
panel above its charts (index.html #galCountryHub), fed by sources/briefs.json
(scripts/build_source_pages.py). These pin both halves so neither drifts.

    python scripts/test_country_hub.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
H = (ROOT / "index.html").read_text(encoding="utf-8")


def test_panel_markup_sits_above_the_charts():
    hub = H.index('id="galCountryHub"')
    assert H.index('id="appliedBar"') < hub < H.index('<div id="cols" class="cols">')


def test_panel_is_repainted_with_every_filter_change():
    assert "renderCountryHub(list.length>0)" in H
    assert "fetch('sources/briefs.json'" in H


def test_panel_links_brief_card_source_and_csv():
    body = H.split("function renderCountryHub(")[1].split("\n}\n")[0]
    for needle in ("sources/flyer/${slug}.html", "sources/flyer/${slug}_social.html",
                   "sources/${slug}.html", "b.data_file", 'href="sources/flyer/"',
                   'href="sources/"'):
        assert needle in body, needle
    # variants ("Austria (Vans)") resolve to the base country's brief
    assert "replace(/\\s*\\(.*\\)\\s*$/, '')" in body


def test_variant_switch_updates_note_and_offers_variant_csv():
    # the panel keeps its previews per country, so a switch Germany ->
    # Germany (Vans) must still repaint the variant line in place
    body = H.split("function renderCountryHub(")[1].split("\n}\n")[0]
    assert body.count("renderCountryHubVariant(hub, picked, base)") == 2
    var = H.split("function renderCountryHubVariant(")[1].split("\n}\n")[0]
    assert "b.data_file.replace(/\\.csv$/, '_' + variant + '.csv')" in var
    assert "method: 'HEAD'" in var          # offered only if the file exists


def test_every_card_links_its_brief():
    assert 'class="btn btn--brief" href="sources/flyer/${srcSlug}.html"' in H
    assert "${srcLink}${briefLink}" in H


def test_generator_writes_one_entry_per_country_page():
    import build_source_pages as bsp
    entries, _ = bsp.collect_entries()
    params = bsp.load_params()
    items = [bsp.flyer_summary(fm, params) for fm, _ in entries]
    briefs = bsp.briefs_map(entries, items)
    pages = {fm["country"]: fm["slug"] for fm, _ in entries}
    assert set(briefs) == set(pages)
    for country, b in briefs.items():
        assert b["slug"] == pages[country]
        assert set(b) >= {"slug", "head", "share", "delta", "through",
                          "source", "source_url", "data_file", "is_stub"}
        assert b["share"] is None or isinstance(b["share"], float)
    json.dumps(briefs)  # serialisable as written


def test_committed_briefs_match_sources_json():
    briefs = ROOT / "sources" / "briefs.json"
    if not briefs.is_file():
        return  # written by build-source-pages.yml after the merge
    b = json.loads(briefs.read_text(encoding="utf-8"))
    s = json.loads((ROOT / "sources" / "sources.json").read_text(encoding="utf-8"))
    assert {k: v["slug"] for k, v in b.items()} == s


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
