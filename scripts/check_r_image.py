#!/usr/bin/env python3
"""Guard for the prebuilt R image (docs/architecture/63-r-render-image.md).

Fails (exit 1) when
  1. any workflow still uses r-lib/actions (setup-r, setup-r-dependencies, …):
     R must come from ghcr.io/leraffl/r-render, not be installed per job;
  2. a workflow references the image with a tag other than
     v<docker/r-render/IMAGE_VERSION> (all workflows run the same image);
  3. with --base REF: something under docker/r-render/ changed against REF but
     IMAGE_VERSION did not — the build workflow never rebuilds an existing vN,
     so such a change would silently not ship.

Standard library only.  Usage:
    python scripts/check_r_image.py [--base origin/master]
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
WORKFLOWS = REPO / ".github" / "workflows"
IMAGE_DIR = "docker/r-render"
VERSION_FILE = REPO / IMAGE_DIR / "IMAGE_VERSION"
IMAGE = "ghcr.io/leraffl/r-render"

USES_RLIB = re.compile(r"^\s*(-\s*)?uses:\s*['\"]?r-lib/actions", re.IGNORECASE)
IMAGE_REF = re.compile(re.escape(IMAGE) + r":([A-Za-z0-9._-]+)", re.IGNORECASE)


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO, check=True,
                          stdout=subprocess.PIPE, text=True).stdout


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--base", help="git ref to diff docker/r-render/ against (PRs)")
    args = ap.parse_args()

    errors: list[str] = []
    version = "v" + VERSION_FILE.read_text(encoding="utf-8").strip()
    users = 0
    for wf in sorted(WORKFLOWS.glob("*.y*ml")):
        for no, line in enumerate(wf.read_text(encoding="utf-8").splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue
            where = f"{wf.relative_to(REPO)}:{no}"
            if USES_RLIB.search(line):
                errors.append(f"{where}: uses r-lib/actions — use the R image instead "
                              f"(container: {IMAGE}:{version}; see doc 63)")
            for tag in IMAGE_REF.findall(line):
                users += 1
                if tag != version:
                    errors.append(f"{where}: {IMAGE}:{tag}, expected :{version} "
                                  f"(docker/r-render/IMAGE_VERSION)")

    if args.base:
        changed = git("diff", "--name-only", f"{args.base}...HEAD", "--", IMAGE_DIR).split()
        if changed and f"{IMAGE_DIR}/IMAGE_VERSION" not in changed:
            errors.append(f"{IMAGE_DIR}/ changed ({', '.join(changed)}) without bumping "
                          f"{IMAGE_DIR}/IMAGE_VERSION — an existing image tag is never rebuilt")

    for e in errors:
        print(f"::error::{e}")
    print(f"{users} image reference(s) checked against {IMAGE}:{version}; "
          f"{len(errors)} error(s).")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
