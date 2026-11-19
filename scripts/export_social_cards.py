#!/usr/bin/env python3
"""Export the social cards (sources/flyer/<slug>_social.html) as postable PNGs.

The cards are generated HTML; X/Bluesky need images. This renders each card
with headless Chrome at its native 1080x1350 (4:5) — no preview server needed,
Chrome loads the file:// URL and relative assets resolve from the worktree.

Usage (from the worktree, any Python 3):
    python3 scripts/export_social_cards.py                  # all cards -> ~/workspace/social-cards
    python3 scripts/export_social_cards.py --slugs ireland eu
    python3 scripts/export_social_cards.py --out DIR --scale 2

No CI workflow on purpose: 73 PNGs per data push would bloat the repo.
Export on demand and copy the ones you post into the post dir.
"""
import argparse
import shutil
import subprocess
import sys
from pathlib import Path

CHROME_MAC = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def find_chrome():
    if Path(CHROME_MAC).exists():
        return CHROME_MAC
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        p = shutil.which(name)
        if p:
            return p
    sys.exit("Chrome/Chromium not found — pass --chrome")


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--slugs", nargs="*",
                    help="country/region slugs (default: every *_social.html)")
    ap.add_argument("--out", default=str(Path.home() / "workspace" / "social-cards"))
    ap.add_argument("--scale", type=int, default=1,
                    help="device scale factor (2 = retina 2160x2700)")
    ap.add_argument("--chrome", default=None)
    args = ap.parse_args()

    root = Path(__file__).resolve().parent.parent
    flyer = root / "sources" / "flyer"
    chrome = args.chrome or find_chrome()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    if args.slugs:
        files = [flyer / f"{s}_social.html" for s in args.slugs]
        missing = [str(f) for f in files if not f.exists()]
        if missing:
            sys.exit("missing: " + ", ".join(missing))
    else:
        files = sorted(flyer.glob("*_social.html"))
    if not files:
        sys.exit(f"no *_social.html under {flyer} — run scripts/build_source_pages.py first")

    ok = 0
    for f in files:
        png = out / (f.stem + ".png")
        cmd = [chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars",
               f"--force-device-scale-factor={args.scale}",
               "--window-size=1080,1350", f"--screenshot={png}", f.as_uri()]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if png.exists() and png.stat().st_size > 0:
            ok += 1
        else:
            print(f"FAIL {f.stem}: {r.stderr.strip()[-200:]}", file=sys.stderr)
    print(f"✓ {ok}/{len(files)} cards -> {out} ({1080 * args.scale}x{1350 * args.scale})")
    if ok != len(files):
        sys.exit(1)


if __name__ == "__main__":
    main()
