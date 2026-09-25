#!/usr/bin/env python3
"""Build the side-by-side sheet for a render preview (preview-render.yml).

Input layout (one directory per rendered series, written by the matrix jobs):

    <root>/<slug>/meta.txt          "country|variant"
    <root>/<slug>/base/*.png        charts rendered with the base branch's R/
    <root>/<slug>/head/*.png        charts rendered with the PR's R/
    <root>/<slug>/base_params.csv   that series' params.csv row after the base render
    <root>/<slug>/head_params.csv   … after the PR render
    <root>/<slug>/{base,head}_failed  present when that render exited non-zero
    <root>/<slug>/{base,head}_bands.json  bands/<slug>.json from that render, if written

Output, written into <root>:

    compare/<slug>__<chart>.png     base | PR, one image per chart, labelled
    index.html                      every series, both images, params before/after
    summary.md                      short table for the PR comment

Charts are paired by filename: both renders run on the same day from the same
data, so render_country.R gives them identical names.

Nothing here reads or writes the repository; it only turns the preview
artifact into something a reviewer can scan (on a phone, too: the compare/
PNGs open without the HTML).
"""
from __future__ import annotations

import argparse
import csv
import html
import io
import sys
from pathlib import Path

PARAM_COLS = ("v1", "v2", "t0", "refit_swing", "ttm_bev_share", "data_per")


def read_params(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    rows = list(csv.DictReader(io.StringIO(path.read_text(encoding="utf-8"))))
    return rows[-1] if rows else {}


def bands_80(path: Path) -> str:
    """'2038.1 (95 % CI 2033.8–2052.7)' from a bands/<slug>.json, or '—'."""
    import json
    if not path.is_file():
        return "—"
    try:
        b = json.loads(path.read_text(encoding="utf-8"))
        c = next(c for c in b["crossing"] if abs(c["share"] - 0.8) < 1e-9)
        f = lambda v: "—" if v is None else f"{v:.1f}"
        hi = "2100+" if c["ci"][1] is None else f(c["ci"][1])
        return f"{f(c['fit'])} (95 % CI {f(c['ci'][0])}–{hi})"
    except Exception:
        return "unreadable"


def crossing_year(p: dict[str, str], share: float) -> float | None:
    """Calendar year the fitted BEV curve reaches `share`.

    fit.R works on an internal axis one year below the calendar; the calendar
    curve is S(C) = 1 - exp(v1 * (C - t0)^v2), so the crossing is t0 + z
    (the frontend's "CALENDAR-YEAR FIX" in index.html)."""
    import math
    try:
        v1, v2, t0 = float(p["v1"]), float(p["v2"]), float(p["t0"])
    except (KeyError, ValueError):
        return None
    if not (v1 < 0 and v2 > 0):
        return None
    try:
        z = (math.log(1 - share) / v1) ** (1 / v2)
    except (OverflowError, ValueError, ZeroDivisionError):
        return None
    y = t0 + z
    return y if math.isfinite(y) and y < 1e5 else None


def fmt_year(y: float | None) -> str:
    return "—" if y is None else f"{y:.1f}"


def side_by_side(base: Path | None, head: Path | None, out: Path) -> bool:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return False
    imgs = [Image.open(p).convert("RGB") if p else None for p in (base, head)]
    ref = next(i for i in imgs if i is not None)
    w, h = ref.size
    imgs = [i if i is not None else Image.new("RGB", (w, h), "#eeeeee") for i in imgs]
    band = max(40, h // 25)
    gap = 12
    sheet = Image.new("RGB", (w * 2 + gap, h + band), "white")
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", int(band * 0.6))
    except OSError:
        font = ImageFont.load_default()
    for k, (img, label) in enumerate(zip(imgs, ("BASE (current R code)", "PR (new R code)"))):
        x = k * (w + gap)
        draw.text((x + 12, band * 0.15), label, fill="#222222", font=font)
        sheet.paste(img.resize((w, h)), (x, band))
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out, optimize=True)
    return True


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("root", type=Path, help="directory holding one sub-directory per series")
    ap.add_argument("--title", default="Render preview")
    ap.add_argument("--run-url", default="")
    args = ap.parse_args(argv)
    root: Path = args.root

    series = sorted(d for d in root.iterdir() if d.is_dir() and (d / "meta.txt").is_file())
    if not series:
        print(f"no series found under {root}", file=sys.stderr)
        return 1

    cards, md_rows = [], []
    for d in series:
        country, _, variant = (d / "meta.txt").read_text(encoding="utf-8").strip().partition("|")
        label = country if variant in ("", "Whole") else f"{country} ({variant})"
        pb, ph = read_params(d / "base_params.csv"), read_params(d / "head_params.csv")
        failed = [s for s in ("base", "head") if (d / f"{s}_failed").exists()]

        names = sorted({p.name for s in ("base", "head") for p in (d / s).glob("*.png")})
        changed = []
        figs = []
        for n in names:
            b, h = d / "base" / n, d / "head" / n
            b = b if b.is_file() else None
            h = h if h.is_file() else None
            same = b is not None and h is not None and b.read_bytes() == h.read_bytes()
            if not same:
                changed.append(n)
            cmp_name = f"{d.name}__{Path(n).stem}.png"
            side_by_side(b, h, root / "compare" / cmp_name)
            figs.append(
                f'<figure class="{"same" if same else "diff"}"><figcaption>{html.escape(n)}'
                f'{" — identical" if same else ""}</figcaption>'
                f'<div class="pair">'
                + "".join(
                    f'<div><div class="lab">{lab}</div>'
                    + (f'<a href="{html.escape(d.name)}/{s}/{html.escape(n)}"><img loading="lazy" src="{html.escape(d.name)}/{s}/{html.escape(n)}"></a>'
                       if p else '<div class="missing">not rendered</div>')
                    + "</div>"
                    for lab, s, p in (("Base", "base", b), ("PR", "head", h))
                )
                + "</div></figure>"
            )

        prow = "".join(
            f"<tr><th>{c}</th><td>{html.escape(pb.get(c, ''))}</td><td>{html.escape(ph.get(c, ''))}</td></tr>"
            for c in PARAM_COLS
        ) + (
            f"<tr><th>80 % year, bands/</th><td>{html.escape(bands_80(d / 'base_bands.json'))}</td>"
            f"<td>{html.escape(bands_80(d / 'head_bands.json'))}</td></tr>"
        ) + "".join(
            f"<tr><th>{int(s*100)} % year</th><td>{fmt_year(crossing_year(pb, s))}</td>"
            f"<td>{fmt_year(crossing_year(ph, s))}</td></tr>"
            for s in (0.1, 0.5, 0.8)
        )
        status = ("render failed: " + ", ".join(failed)) if failed else (
            f"{len(changed)} of {len(names)} charts differ" if names else "no charts")
        cards.append(
            f'<section id="{html.escape(d.name)}"><h2>{html.escape(label)} '
            f'<span class="st">{html.escape(status)}</span></h2>'
            f'<table><tr><th></th><th>Base</th><th>PR</th></tr>{prow}</table>{"".join(figs)}</section>'
        )
        md_rows.append(
            f"| {label} | {status} | {fmt_year(crossing_year(pb, 0.8))} | {fmt_year(crossing_year(ph, 0.8))} "
            f"| {pb.get('v2', '')[:6]} → {ph.get('v2', '')[:6]} | {bands_80(d / 'head_bands.json')} |"
        )

    toc = "".join(f'<a href="#{html.escape(d.name)}">{html.escape(d.name)}</a> ' for d in series)
    run = f'<p><a href="{html.escape(args.run_url)}">Workflow run</a></p>' if args.run_url else ""
    (root / "index.html").write_text(f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(args.title)}</title>
<style>
body{{font:14px/1.5 system-ui,sans-serif;margin:0 auto;max-width:1400px;padding:16px;color:#222;background:#fff}}
h2{{margin:32px 0 8px;font-size:18px}} .st{{font-weight:400;color:#666;font-size:13px}}
table{{border-collapse:collapse;margin:8px 0}} th,td{{border:1px solid #ddd;padding:3px 8px;text-align:left;font-variant-numeric:tabular-nums}}
.pair{{display:grid;grid-template-columns:1fr 1fr;gap:8px}} .pair img{{width:100%;border:1px solid #ddd}}
figure{{margin:12px 0}} figcaption{{color:#666;font-size:12px}} figure.same{{opacity:.55}}
.lab{{font-weight:600;font-size:12px}} .missing{{padding:40px;background:#f3f3f3;color:#888;text-align:center}}
nav a{{margin-right:8px;white-space:nowrap}}
@media (max-width:700px){{.pair{{grid-template-columns:1fr}}}}
</style></head><body><h1>{html.escape(args.title)}</h1>{run}
<p>Each series is rendered twice from the same data: once with the base branch's <code>R/</code>, once with the PR's.
Charts that come out byte-identical are dimmed.</p><nav>{toc}</nav>{"".join(cards)}</body></html>
""", encoding="utf-8")

    (root / "summary.md").write_text(
        "| Series | Charts | 80 % year (base) | 80 % year (PR) | v2 base → PR | 80 % from bands/ (PR) |\n"
        "|---|---|---|---|---|---|\n" + "\n".join(md_rows) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {root / 'index.html'} for {len(series)} series")
    return 0


if __name__ == "__main__":
    sys.exit(main())
