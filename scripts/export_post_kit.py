#!/usr/bin/env python3
"""Export the images of one country's post kit, plus the facts the texts need.

    python3 scripts/export_post_kit.py turkiye --out ~/kits/turkiye
    python3 scripts/export_post_kit.py turkiye --out DIR --roles mix,shift

For one country it writes, into DIR:

    <slug>_social.png     the 1080x1350 social card
    <slug>_<role>.png     one snippet per role the data supports
                          (see snippet_card.ROLES), 1080 px wide
    <slug>_brief_a4.png   the A4 brief as one image
    <slug>_brief.pdf      the same page as PDF (X and Bluesky take no PDF)
    <slug>_kit.json       what exists, the data month, the source and the
                          rank figures behind the box plots, so a thread's
                          text can quote the same numbers the images print

Everything is built from the repo's data, the same way `build_source_pages.py`
builds the brief, so it never depends on which pages happen to be committed.
Each page is drawn once in headless Chrome. Nothing is kept in the repo: the
images belong to the post that uses them, and the data they came from is in
git history.

Needs Chrome or Chromium. For the A4 PNG it uses `pdftoppm` (poppler) if
installed and `sips` on macOS otherwise.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import build_source_pages as bsp  # noqa: E402
import flyer  # noqa: E402
import model_card as mc  # noqa: E402
import snippet_card  # noqa: E402
from export_social_cards import find_chrome  # noqa: E402

REPO = HERE.parent
FLYER_DIR = REPO / "sources" / "flyer"
SCALE = 2
MAX_BYTES = 950_000          # Bluesky takes images up to about this size


def _run(cmd: list[str], timeout: int = 90) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def page_height(chrome: str, html: Path, width: int) -> int:
    """The page's own height, read from the DOM after it has laid out."""
    r = _run([chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars",
              "--virtual-time-budget=8000", f"--window-size={width},4000",
              "--dump-dom", html.as_uri()])
    m = re.search(r'data-h="(\d+)"', r.stdout)
    if not m:
        raise RuntimeError(f"no height in {html.name}: {r.stderr.strip()[-200:]}")
    return int(m.group(1))


def screenshot(chrome: str, html: Path, png: Path, width: int, height: int,
               scale: int = SCALE) -> None:
    for sc in (scale, 1):
        _run([chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars",
              "--virtual-time-budget=8000", f"--force-device-scale-factor={sc}",
              f"--window-size={width},{height}", f"--screenshot={png}", html.as_uri()])
        if png.exists() and png.stat().st_size and png.stat().st_size <= MAX_BYTES:
            return
        if sc == 1:
            break
    if not png.exists() or not png.stat().st_size:
        raise RuntimeError(f"no screenshot for {html.name}")


def print_pdf(chrome: str, html: Path, pdf: Path) -> None:
    _run([chrome, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
          "--virtual-time-budget=10000", f"--print-to-pdf={pdf}", html.as_uri()])
    if not pdf.exists() or not pdf.stat().st_size:
        raise RuntimeError("print-to-pdf produced nothing")


def pdf_to_png(pdf: Path, png: Path) -> None:
    """Page 1 of the brief as PNG, about 200 dpi (1653 x 2339)."""
    if shutil.which("pdftoppm"):
        stem = png.with_suffix("")
        _run(["pdftoppm", "-png", "-r", "200", "-f", "1", "-l", "1", "-singlefile",
              str(pdf), str(stem)])
        if png.exists():
            return
    if shutil.which("sips"):
        _run(["sips", "-s", "format", "png", "--resampleWidth", "1653", str(pdf),
              "--out", str(png)])
        if png.exists():
            return
    raise RuntimeError("need pdftoppm (brew install poppler) or sips to make the A4 PNG")


def rank_facts(ctx: dict, role: str) -> dict | None:
    """The figures a box plot prints, as numbers and as the strings it prints
    (None when the role is empty). The `*_text` fields are what the image
    shows, so a post that quotes them cannot disagree with it."""
    m = snippet_card._strip(ctx, role)
    if not m:
        return None
    s = m["stats"]
    own = m["own"]["value"]
    fmt = mc.share if m["kind"] == "share" else mc.year_text
    out = {"kind": m["kind"], "own": own, "n": s["n"], "median": s["median"],
           "q1": s["q1"], "q3": s["q3"],
           "rank": flyer._rank_of(own, [v for _, v in m["values"]],
                                  higher_first=(m["kind"] == "share"))}
    for key in ("own", "median", "q1", "q3"):
        out[f"{key}_text"] = fmt(out[key])
    out["rank_text"] = f"{flyer.ordinal(out['rank'])} of {s['n']}"
    if m.get("kind") == "year" and m.get("ci"):
        out["ci"] = list(m["ci"])
        out["ci_text"] = mc._ci_text(m["ci"])
    return out


def build_ctx(slug: str) -> tuple[dict, dict]:
    entries, problems = bsp.collect_entries()
    if problems:
        raise SystemExit("front-matter problems: " + "; ".join(problems[:3]))
    params = bsp.load_params()
    fm = next((f for f, _ in entries if f.get("slug") == slug), None)
    if fm is None:
        raise SystemExit(f"unknown slug {slug!r}")
    peers = bsp.flyer_peers(entries, params)
    peer_years = bsp.flyer_peer_years(entries, params)
    peer_years_80 = bsp.flyer_peer_years(entries, params, level=0.8)
    return fm, {"params": params, "peers": peers, "peer_years": peer_years,
                "peer_years_80": peer_years_80}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("slug")
    ap.add_argument("--out", required=True, help="directory for the images and kit.json")
    ap.add_argument("--roles", help="comma list; default: every role the data supports")
    ap.add_argument("--scale", type=int, default=SCALE)
    ap.add_argument("--chrome", default=None)
    args = ap.parse_args()

    fm, shared = build_ctx(args.slug)
    if fm.get("region"):
        raise SystemExit("region briefs have no post kit yet")
    slug = fm["slug"]
    ctx = bsp.snippet_context(fm, shared["params"], shared["peers"],
                              shared["peer_years"], shared["peer_years_80"])
    rows = ctx["rows"]
    if not rows:
        raise SystemExit(f"{slug}: no rows")
    chrome = args.chrome or find_chrome()
    out = Path(args.out).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    FLYER_DIR.mkdir(parents=True, exist_ok=True)

    wanted = [r.strip() for r in args.roles.split(",")] if args.roles else None
    roles = snippet_card.available(ctx)
    if wanted:
        roles = [r for r in roles if r in wanted]
    files: dict[str, str] = {}
    temps: list[Path] = []
    try:
        theme = "../../assets/theme.css"
        # snippets
        for role in roles:
            html = FLYER_DIR / f".kit_{slug}_{role}.html"
            temps.append(html)
            html.write_text(snippet_card.build_page(ctx, role, theme), encoding="utf-8")
            h = page_height(chrome, html, snippet_card.W)
            png = out / f"{slug}_{role}.png"
            screenshot(chrome, html, png, snippet_card.W, h, args.scale)
            files[role] = png.name
            print(f"  {role:7s} {snippet_card.W}x{h} -> {png.name} ({png.stat().st_size // 1024} KB)")
        # social card
        if not wanted or "social" in wanted:
            html = FLYER_DIR / f".kit_{slug}_social.html"
            temps.append(html)
            html.write_text(bsp.build_social_page(fm, shared["params"], shared["peers"]),
                            encoding="utf-8")
            png = out / f"{slug}_social.png"
            screenshot(chrome, html, png, 1080, 1350, args.scale)
            files["social"] = png.name
            print(f"  social  1080x1350 -> {png.name} ({png.stat().st_size // 1024} KB)")
        # A4 brief
        if not wanted or "brief" in wanted:
            html = FLYER_DIR / f".kit_{slug}_brief.html"
            temps.append(html)
            html.write_text(bsp.build_flyer_page(
                fm, shared["params"], shared["peers"], peer_years=shared["peer_years"],
                peer_years_80=shared["peer_years_80"]), encoding="utf-8")
            pdf = out / f"{slug}_brief.pdf"
            print_pdf(chrome, html, pdf)
            png = out / f"{slug}_brief_a4.png"
            pdf_to_png(pdf, png)
            files["brief"] = png.name
            files["brief_pdf"] = pdf.name
            print(f"  brief   A4 -> {png.name} ({png.stat().st_size // 1024} KB), {pdf.name}")
    finally:
        for t in temps:
            t.unlink(missing_ok=True)

    last = rows[-1]["period"]
    source = re.sub(r"\s*\(.*?\)", "", (fm.get("source_name") or "").split("—")[0]).strip()
    facts = {role: rank_facts(ctx, role) for role in ("share", "year50", "year80")}
    ttm = ctx["figures"].get("ttm") or {}
    kit = {
        "slug": slug, "country": ctx["country"],
        # the generator's own file stem (posts/<posts_slug>_YYYY-MM.txt)
        "posts_slug": mc.band_slug(ctx["country"]),
        "data_through": last,
        "data_through_label": mc.period_label(last, long=True),
        "interval": mc.interval_of(rows[-1]),
        "source": source, "ttm_share": ttm.get("share"),
        "ttm_share_text": mc.share(ttm["share"]) if ttm.get("share") is not None else None,
        "roles": roles, "files": files,
        "rank": {k: v for k, v in facts.items() if v},
        "brief_url": f"{mc.SITE}/sources/flyer/{slug}.html",
        "generated": mc.generated_line(last),
    }
    kit_path = out / f"{slug}_kit.json"
    if wanted and kit_path.exists():
        # A partial run (--roles) adds to the kit that is already there.
        try:
            old = json.loads(kit_path.read_text(encoding="utf-8"))
        except ValueError:
            old = {}
        if old.get("data_through") == last:
            kit["files"] = {**old.get("files", {}), **kit["files"]}
            have = set(old.get("roles", [])) | set(kit["roles"])
            kit["roles"] = [r for r in snippet_card.ROLES if r in have]
    kit_path.write_text(json.dumps(kit, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"✓ {slug}: {len(files)} images + kit.json -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
