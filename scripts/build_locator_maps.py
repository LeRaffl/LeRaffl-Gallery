#!/usr/bin/env python3
"""Build assets/maps/locator.json, the small locator maps on the briefs.

One-off generator, not part of CI. Input is Natural Earth 1:50m Admin 0
countries (public domain), version 5.1.2:

    curl -L -o ne_50m.geojson \
      https://raw.githubusercontent.com/nvkelso/natural-earth-vector/v5.1.2/geojson/ne_50m_admin_0_countries.geojson
    python scripts/build_locator_maps.py ne_50m.geojson

Three frames, each an SVG path per country (ADM0_A3), projected,
clipped and simplified offline so the briefs only paste strings:

    europe  Lambert azimuthal equal-area at 15°E 52°N (the EU's own
            map projection family), Iceland to the Caucasus, Israel to
            the North Cape
    asia    Lambert azimuthal equal-area at 105°E 25°N, India to Japan
            and Indonesia
    world   Equal Earth, Antarctica left out

Pure Python on purpose (no GIS dependency). See assets/maps/SOURCES.md.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "assets" / "maps" / "locator.json"

FRAMES = {
    # name: projection, centre, lon/lat clip window, points that must fit, viewBox w×h
    "europe": {"proj": "laea", "lon0": 15.0, "lat0": 52.0,
               "clip": (-45.0, 20.0, 100.0, 85.0),
               "fit": [(-24.5, 63.3), (-9.5, 37.0), (-6, 36.0), (35.5, 30.2),
                       (46.5, 41.5), (31, 71.2), (15, 71), (41, 64)],
               "w": 300, "h": 210},
    "asia": {"proj": "laea", "lon0": 105.0, "lat0": 25.0,
             "clip": (30.0, -40.0, 180.0, 80.0),
             "fit": [(68.0, 23.0), (78, 8), (97, 28), (145.8, 44.5), (141, 45.5),
                     (95, -11), (125, -10.5), (120, 53.5), (88, 49)],
             "w": 300, "h": 210},
    "world": {"proj": "eqearth", "lon0": 0.0, "lat0": 0.0,
              "clip": None, "fit": None, "w": 300, "h": 150},
}
TOL = 0.55          # Douglas–Peucker tolerance in viewBox units
MIN_RING = 1.2      # drop islands smaller than this (viewBox units²) ...
                    # ... unless they are a country's only ring


def laea(lon, lat, lon0, lat0):
    l, p = math.radians(lon - lon0), math.radians(lat)
    p0 = math.radians(lat0)
    k = math.sqrt(2 / (1 + math.sin(p0) * math.sin(p) + math.cos(p0) * math.cos(p) * math.cos(l)))
    return (k * math.cos(p) * math.sin(l),
            -k * (math.cos(p0) * math.sin(p) - math.sin(p0) * math.cos(p) * math.cos(l)))


A1, A2, A3, A4 = 1.340264, -0.081106, 0.000893, 0.003796
M = math.sqrt(3) / 2


def eqearth(lon, lat, lon0, _lat0):
    lam, phi = math.radians(lon - lon0), math.radians(lat)
    th = math.asin(M * math.sin(phi))
    t2 = th * th
    t6 = t2 * t2 * t2
    x = 2 * math.sqrt(3) * lam * math.cos(th) / (3 * (9 * A4 * t6 * t2 + 7 * A3 * t6 + 3 * A2 * t2 + A1))
    y = th * (A1 + A2 * t2 + t6 * (A3 + A4 * t2))
    return x, -y


PROJ = {"laea": laea, "eqearth": eqearth}


def clip_ring(ring, box):
    """Sutherland–Hodgman against a lon/lat rectangle."""
    x0, y0, x1, y1 = box
    def cut(pts, inside, inter):
        out = []
        for i, cur in enumerate(pts):
            prev = pts[i - 1]
            if inside(cur):
                if not inside(prev):
                    out.append(inter(prev, cur))
                out.append(cur)
            elif inside(prev):
                out.append(inter(prev, cur))
        return out
    def ix(x):
        return lambda a, b: (x, a[1] + (b[1] - a[1]) * (x - a[0]) / (b[0] - a[0]))
    def iy(y):
        return lambda a, b: (a[0] + (b[0] - a[0]) * (y - a[1]) / (b[1] - a[1]), y)
    pts = list(ring)
    for inside, inter in ((lambda p: p[0] >= x0, ix(x0)), (lambda p: p[0] <= x1, ix(x1)),
                          (lambda p: p[1] >= y0, iy(y0)), (lambda p: p[1] <= y1, iy(y1))):
        if not pts:
            break
        pts = cut(pts, inside, inter)
    return pts


def dp(pts, tol):
    if len(pts) < 3:
        return pts
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        a, b = stack.pop()
        ax, ay = pts[a]; bx, by = pts[b]
        dx, dy = bx - ax, by - ay
        n = math.hypot(dx, dy) or 1e-12
        best, idx = -1.0, -1
        for i in range(a + 1, b):
            px, py = pts[i]
            d = abs(dy * px - dx * py + bx * ay - by * ax) / n if (dx or dy) else math.hypot(px - ax, py - ay)
            if d > best:
                best, idx = d, i
        if best > tol and idx > 0:
            keep[idx] = True
            stack += [(a, idx), (idx, b)]
    return [p for p, k in zip(pts, keep) if k]


def area(pts):
    return abs(sum(pts[i - 1][0] * pts[i][1] - pts[i][0] * pts[i - 1][1] for i in range(len(pts)))) / 2


def rings_of(geom):
    if geom["type"] == "Polygon":
        return [geom["coordinates"][0]] + geom["coordinates"][1:]
    out = []
    for poly in geom["coordinates"]:
        out += poly
    return out


def main(src: str) -> None:
    data = json.load(open(src, encoding="utf-8"))
    feats = [f for f in data["features"] if f["properties"]["ADM0_A3"] != "ATA"]
    out = {"source": "Natural Earth 1:50m Admin 0 countries v5.1.2 (public domain)",
           "frames": {}, "names": {}, "meta": {}}
    for f in feats:
        p = f["properties"]
        iso = p["ADM0_A3"]
        out["meta"][iso] = {"continent": p["CONTINENT"], "subregion": p["SUBREGION"]}
        for k in ("NAME", "NAME_LONG", "ADMIN", "NAME_EN"):
            if p.get(k):
                out["names"].setdefault(p[k], iso)
    for name, fr in FRAMES.items():
        proj = PROJ[fr["proj"]]
        P = lambda lon, lat: proj(lon, lat, fr["lon0"], fr["lat0"])
        if fr["fit"]:
            pts = [P(*q) for q in fr["fit"]]
        else:
            pts = [P(lon, lat) for lon in (-180, 180) for lat in range(-60, 85, 5)] + \
                  [P(0, 84), P(0, -58)]
        xs, ys = [q[0] for q in pts], [q[1] for q in pts]
        bx0, bx1, by0, by1 = min(xs), max(xs), min(ys), max(ys)
        # Pad the box to the viewBox aspect, centred.
        W, H = fr["w"], fr["h"]
        s = min(W / (bx1 - bx0), H / (by1 - by0)) * 0.97
        cx, cy = (bx0 + bx1) / 2, (by0 + by1) / 2
        def V(lon, lat):
            x, y = P(lon, lat)
            return (W / 2 + (x - cx) * s, H / 2 + (y - cy) * s)
        paths, areas, cents = {}, {}, {}
        for f in feats:
            iso = f["properties"]["ADM0_A3"]
            parts, total, best = [], 0.0, None
            rings = rings_of(f["geometry"])
            cand = []
            for ring in rings:
                r = clip_ring(ring, fr["clip"]) if fr["clip"] else ring
                if len(r) < 3:
                    continue
                v = [V(*q) for q in r]
                # Skip rings entirely outside the viewBox.
                if max(q[0] for q in v) < -2 or min(q[0] for q in v) > W + 2 or \
                   max(q[1] for q in v) < -2 or min(q[1] for q in v) > H + 2:
                    continue
                a = area(v)
                cand.append((a, v))
            if not cand:
                continue
            cand.sort(key=lambda c: -c[0])
            for i, (a, v) in enumerate(cand):
                if a < MIN_RING and i > 0:
                    continue
                sv = dp(v + [v[0]], TOL)[:-1]
                if len(sv) < 3:
                    sv = v          # a tiny island: keep it as drawn
                total += a
                if best is None:
                    best = v
                parts.append("M" + "L".join(f"{x:.1f} {y:.1f}" for x, y in sv) + "Z")
            if not parts:
                continue
            paths[iso] = "".join(parts)
            areas[iso] = round(total, 2)
            lx, ly = f["properties"].get("LABEL_X"), f["properties"].get("LABEL_Y")
            if lx is not None:
                cents[iso] = [round(c, 1) for c in V(lx, ly)]
        out["frames"][name] = {"w": W, "h": H, "paths": paths, "area": areas, "label": cents}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, separators=(",", ":"), sort_keys=True, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    print(OUT, OUT.stat().st_size, {k: len(v["paths"]) for k, v in out["frames"].items()})


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "ne_50m.geojson")
