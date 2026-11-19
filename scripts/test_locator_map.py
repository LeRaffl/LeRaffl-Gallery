"""Locator maps on the briefs: frame choice, highlights, small-country rings."""
import re

import locator_map as lm


def test_gallery_names_resolve():
    for name, iso in [("UK", "GBR"), ("USA", "USA"), ("Türkiye", "TUR"), ("Czechia", "CZE"),
                      ("South Korea", "KOR"), ("Hong Kong", "HKG"), ("Ireland", "IRL"),
                      ("New Zealand", "NZL"), ("Vietnam", "VNM")]:
        assert lm.iso_for(name) == iso, name


def test_frames():
    assert lm.pick_frame(["IRL"]) == "europe"
    assert lm.pick_frame(["ISL"]) == "europe"
    assert lm.pick_frame(["CYP"]) == "europe"
    assert lm.pick_frame(["ISR"]) == "europe"
    assert lm.pick_frame(["VNM"]) == "asia"
    assert lm.pick_frame(["SGP"]) == "asia"
    assert lm.pick_frame(["IND"]) == "asia"
    assert lm.pick_frame(["USA"]) == "world"
    assert lm.pick_frame(["NZL"]) == "world"
    # A group spanning two frames falls back to the world map.
    assert lm.pick_frame(["DEU", "CHN"]) == "world"
    assert lm.pick_frame([]) is None


def test_highlight_and_ring():
    svg = lm.build(["Germany"], 74, label="Where Germany is")
    assert svg.startswith("<svg") and 'data-frame="europe"' in svg
    assert 'height="74"' in svg
    assert "<circle" not in svg            # big enough to see
    malta = lm.build(["Malta"], 74)
    assert "<circle" in malta              # too small: ringed
    assert lm.build(["Atlantis"], 74) == ""  # unknown: no map, no crash


def test_group_uses_dots_not_rings():
    eu = ["Austria", "Belgium", "Bulgaria", "Croatia", "Cyprus", "Czechia", "Denmark",
          "Estonia", "Finland", "France", "Germany", "Greece", "Hungary", "Ireland", "Italy",
          "Latvia", "Lithuania", "Luxembourg", "Malta", "Netherlands", "Poland", "Portugal",
          "Romania", "Slovakia", "Slovenia", "Spain", "Sweden"]
    svg = lm.build(eu, 118)
    assert 'data-frame="europe"' in svg
    assert 'fill="none"' not in svg        # no open rings in a many-country map
    assert len(re.findall("<circle", svg)) >= 1   # Malta / Luxembourg as dots


if __name__ == "__main__":
    test_gallery_names_resolve()
    test_frames()
    test_highlight_and_ring()
    test_group_uses_dots_not_rings()
    print("ok")
