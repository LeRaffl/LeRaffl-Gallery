"""Small locator maps for the briefs and social cards.

Paths are pre-projected in assets/maps/locator.json (Natural Earth, public
domain; built offline by scripts/build_locator_maps.py, see
assets/maps/SOURCES.md). This module only picks a frame and colours the
countries in it.

    europe  every country (or group) whose label point lies in the Europe
            frame: the European countries, Türkiye, Georgia, Cyprus, Israel
    asia    the same test for the Asia frame (India to Japan and Indonesia)
    world   everything else, and any group that spans frames

A country too small to see at the printed size gets a ring around its
label point, so Malta or Singapore can still be found.
"""
from __future__ import annotations

import json
from functools import lru_cache
from html import escape as _esc
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "assets" / "maps" / "locator.json"

# Gallery names that are not Natural Earth names.
ALIASES = {
    "UK": "GBR", "USA": "USA", "Türkiye": "TUR", "Czechia": "CZE",
    "South Korea": "KOR", "Hong Kong": "HKG", "Taiwan": "TWN",
    "Bosnia": "BIH", "Bosnia and Herzegovina": "BIH", "Cyprus": "CYP",
}
ORDER = ("europe", "asia", "world")
SEA = "#efede7"
LAND = "#c9c4b7"
EDGE = "#fdfdfc"
HIT = "#2c7a50"
MIN_PX2 = 30.0      # below this printed area a country also gets a ring
RING_PX = 5.0       # ring radius in printed px


@lru_cache(maxsize=1)
def _data() -> dict:
    try:
        return json.loads(DATA.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def iso_for(name: str) -> str | None:
    if not name:
        return None
    if name in ALIASES:
        return ALIASES[name]
    return (_data().get("names") or {}).get(name)


def _inside(frame: dict, iso: str, margin: float = 0.0) -> bool:
    pt = (frame.get("label") or {}).get(iso)
    if not pt:
        return False
    x, y = pt
    return (-margin <= x <= frame["w"] + margin) and (-margin <= y <= frame["h"] + margin)


def pick_frame(isos: list[str]) -> str | None:
    frames = _data().get("frames") or {}
    isos = [i for i in isos if i]
    if not isos or not frames:
        return None
    for name in ORDER:
        fr = frames.get(name)
        if not fr:
            continue
        if name == "world" or all(_inside(fr, i) for i in isos):
            return name
    return None


def build(names: list[str], height: int, label: str = "", cls: str = "loc-map",
          frame: str | None = None) -> str:
    """Inline SVG, `height` px tall, the named countries highlighted.

    Returns "" when no name is on the map, so a brief without a match
    simply has no map.
    """
    data = _data()
    isos = []
    for n in names:
        i = iso_for(n)
        if i and i not in isos:
            isos.append(i)
    frame = frame or pick_frame(isos)
    fr = (data.get("frames") or {}).get(frame or "")
    if not fr:
        return ""
    isos = [i for i in isos if i in fr["paths"] or i in (fr.get("label") or {})]
    if not isos:
        return ""
    W, H = fr["w"], fr["h"]
    width = round(height * W / H)
    scale = height / H
    hit = set(isos)
    base = "".join(p for iso, p in sorted(fr["paths"].items()) if iso not in hit)
    lit = "".join(fr["paths"].get(i, "") for i in isos)
    rings = []
    many = len(isos) > 6
    for i in isos:
        a = (fr.get("area") or {}).get(i, 0.0) * scale * scale
        pt = (fr.get("label") or {}).get(i)
        if pt and a < MIN_PX2:
            if many:
                rings.append(f'<circle cx="{pt[0]}" cy="{pt[1]}" r="{1.6 / scale:.2f}" fill="{HIT}"/>')
            else:
                rings.append(f'<circle cx="{pt[0]}" cy="{pt[1]}" r="{RING_PX / scale:.2f}" '
                             f'fill="none" stroke="{HIT}" stroke-width="{1.3 / scale:.2f}"/>')
    sw = f"{0.4 / scale:.2f}"
    title = f"<title>{_esc(label)}</title>" if label else ""
    return (f'<svg class="{cls}" viewBox="0 0 {W} {H}" width="{width}" height="{height}" '
            f'role="img" aria-label="{_esc(label)}" data-frame="{frame}">{title}'
            f'<clipPath id="loc-clip"><rect width="{W}" height="{H}" rx="{3 / scale:.1f}"/></clipPath>'
            f'<rect width="{W}" height="{H}" rx="{3 / scale:.1f}" fill="{SEA}"/><g clip-path="url(#loc-clip)">'
            f'<path d="{base}" fill="{LAND}" stroke="{EDGE}" stroke-width="{sw}" stroke-linejoin="round"/>'
            f'<path d="{lit}" fill="{HIT}" stroke="{EDGE}" stroke-width="{sw}" stroke-linejoin="round"/>'
            f'</g>{"".join(rings)}</svg>')
