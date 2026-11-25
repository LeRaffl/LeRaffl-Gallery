#!/usr/bin/env python3
"""Offline tests: the post-kit snippets (scripts/snippet_card.py).

    python3 scripts/test_snippet_card.py

They check HTML only, so no browser is needed. Nothing here pins a data value
(those move every month); they pin what has to hold for every country.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_source_pages as bsp  # noqa: E402
import flyer  # noqa: E402
import snippet_card as sc  # noqa: E402

THEME = "../../assets/theme.css"
_CACHE: dict = {}


def _shared():
    if not _CACHE:
        entries, _ = bsp.collect_entries()
        params = bsp.load_params()
        _CACHE.update(
            entries=entries, params=params,
            peers=bsp.flyer_peers(entries, params),
            years=bsp.flyer_peer_years(entries, params),
            years80=bsp.flyer_peer_years(entries, params, level=0.8))
    return _CACHE


def _fm(slug: str) -> dict:
    return next(f for f, _ in _shared()["entries"] if f.get("slug") == slug)


def _ctx(slug: str) -> dict:
    s = _shared()
    return bsp.snippet_context(_fm(slug), s["params"], s["peers"], s["years"], s["years80"])


def _brief(slug: str) -> str:
    s = _shared()
    return bsp.build_flyer_page(_fm(slug), s["params"], s["peers"],
                                peer_years=s["years"], peer_years_80=s["years80"])


def test_every_country_builds_and_roles_are_known():
    s = _shared()
    built = 0
    for fm, _ in s["entries"]:
        ctx = bsp.snippet_context(fm, s["params"], s["peers"], s["years"], s["years80"])
        if not ctx["rows"]:
            continue
        for role in sc.available(ctx):
            assert role in sc.ROLES, (fm["slug"], role)
            page = sc.build_page(ctx, role, THEME)
            assert f'data-role="{role}"' in page and 'id="kit"' in page, (fm["slug"], role)
            assert "dataset.h" in page, "the exporter reads the height from the page"
            built += 1
    assert built > 100, built


def test_a_role_without_data_is_empty_not_half_drawn():
    ctx = _ctx("turkiye")
    assert "brands" not in sc.available(ctx)          # no market file
    assert sc.build_page(ctx, "brands", THEME) == ""
    # Malta has no full 12-month window: no headline number, so no mix
    malta = _ctx("malta")
    assert "mix" not in sc.available(malta)
    assert sc.build_page(malta, "mix", THEME) == ""


def test_rank_figures_are_the_briefs_figures():
    """'28th of 60' on a snippet is the text the brief prints."""
    for slug in ("turkiye", "ireland", "albania"):
        ctx = _ctx(slug)
        brief = _brief(slug)
        in_brief = set(re.findall(r"\d+(?:st|nd|rd|th) of \d+", brief))
        for role in ("share", "year50", "year80"):
            if role not in sc.available(ctx):
                continue
            page = sc.build_page(ctx, role, THEME)
            ranks = set(re.findall(r"\d+(?:st|nd|rd|th) of \d+", page))
            assert ranks and ranks <= in_brief, (slug, role, ranks, in_brief)


def test_year_strip_alone_keeps_its_year_axis():
    ctx = _ctx("turkiye")
    page = sc.build_page(ctx, "year80", THEME)
    labels = re.findall(r'class="ax"[^>]*>(\d{4})<', page)
    assert len(labels) >= 3, labels      # a lone strip is not the shared-axis layout
    assert "Fitted curve reaches 80%" in page and "Fitted curve reaches 50%" not in page
    assert "not from a forecast" in page  # the model caveat travels with the years


def test_sections_come_from_the_briefs_own_builders():
    """The brief and the snippets share one builder per section."""
    for slug in ("turkiye", "ireland"):
        ctx = _ctx(slug)
        brief = _brief(slug)
        bars = flyer.bars_section(ctx["shift"], ctx["fm"])
        assert bars and bars in brief
        assert flyer.hero_number(ctx["figures"], ctx["rows"]) in brief
        assert flyer.facts_section(ctx["fm"], ctx["figures"], ctx["shift"]) in brief


def test_scope_line_keeps_whole_sentences():
    text = ("First sentence names the scope (a list, a, b). "
            "Second one adds a caveat. Third is long " + "x" * 200 + ".")
    out = sc.scope_line(text, limit=120)
    assert out == "First sentence names the scope (a list, a, b). Second one adds a caveat."
    assert sc.scope_line("Short.", limit=120) == "Short."
    only = "One very long first sentence " + "word " * 80 + "end."
    assert sc.scope_line(only, limit=100).endswith("…")      # first sentence alone too long


def test_facts_fill_the_row():
    ctx = _ctx("turkiye")
    page = sc.build_page(ctx, "shift", THEME)
    n = len(re.findall(r'class="ff"', page))
    assert n and f"fl-n{n}" in page


def test_footer_names_source_address_and_licence():
    page = sc.build_page(_ctx("turkiye"), "share", THEME)
    for needle in ("Source:", "leraffl.github.io/LeRaffl-Gallery", "@LeRaffl",
                   "CC BY 4.0", "QR code", "data through"):
        assert needle in page, needle


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    for name, fn in tests:
        fn()
        print(f"ok  {name}")
    print(f"{len(tests)} tests passed")
