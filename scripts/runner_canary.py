#!/usr/bin/env python3
"""Runner canary: does a job produce the same result on the next runner image?

Used by .github/workflows/runner-canary.yml. Every job pins `ubuntu-24.04`
(docs/architecture/06-tech-stack.md); before that label moves, the canary runs
the jobs most exposed to an OS change on the pinned image and on the next one,
and compares what they produce. Risk register and how to read the report:
docs/architecture/56-runner-upgrades.md.

Two subcommands, both standard library only (the render and system-python legs
run on the runner's own Python, which is 3.14 on Ubuntu 26.04):

    runner_canary.py leg <target> --out DIR --image LABEL
        Run <target> the way its production workflow does, inside a throwaway
        checkout: never commits, never pushes. Every command's exit code is
        recorded instead of failing the step, so a leg that breaks on one image
        still uploads what it has. Afterwards every file the run changed is
        copied to DIR/files/, which is what `compare` looks at.

    runner_canary.py compare ROOT --base LABEL --next LABEL --report FILE
        ROOT holds one directory per leg (the downloaded artifacts). Writes a
        Markdown report and exits 1 when the next image differs from the base
        image anywhere that matters.

Why comparing two live runs works: both images fetch the same upstream
document within minutes, so a difference between their outputs comes from the
OS (tesseract, poppler, ImageMagick, Chromium, R's system libraries), not from
the source.
"""
from __future__ import annotations

import argparse
import difflib
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

# ── legs ────────────────────────────────────────────────────────────────────
# Commands mirror the production workflow of each target; keep them in step
# when a fetch-*.yml changes its apt/pip line. `--force` re-parses the newest
# period even though master already has it, so an unchanged source gives an
# empty diff on a healthy image.
LEGS: dict[str, dict[str, str]] = {
    # OCR (tesseract, Turkish) on an image upscaled with ImageMagick `convert`.
    "turkey": {
        "kind": "fetch",
        "apt": "poppler-utils tesseract-ocr tesseract-ocr-tur imagemagick",
        "pip": "requests pypdf cryptography",
        "main": "python scripts/fetch_turkey.py --force",
    },
    # OCR (tesseract, simplified Chinese) on the CPCA table images.
    "china": {
        "kind": "fetch",
        "apt": "tesseract-ocr tesseract-ocr-chi-sim",
        "pip": "requests beautifulsoup4 Pillow",
        "main": "python scripts/fetch_china.py --force",
    },
    # pdftotext -layout on the UNRAE PDFs.
    "italy": {
        "kind": "fetch",
        "apt": "poppler-utils",
        "pip": "requests",
        "main": "python scripts/fetch_italy.py --force",
    },
    # pdftotext -layout on the bulletin; --debug-dir keeps the text so the
    # report can show a layout change even when the parsed numbers agree.
    "colombia": {
        "kind": "fetch",
        "apt": "poppler-utils",
        "pip": "requests",
        "main": "python scripts/fetch_colombia.py --force --debug-dir {files}/colombia-bulletin",
    },
    # Headless Chromium via Playwright; `--with-deps` apt-installs its libraries.
    "albania": {
        "kind": "fetch",
        "pip": "requests playwright",
        "pre": "python -m playwright install --with-deps chromium",
        "main": "python scripts/fetch_albania.py",
    },
    # The R model and plots (render-country.yml's command for one series).
    "render": {
        "kind": "render",
        "main": "Rscript R/render_country.R Sweden Whole",
    },
    # preview-render.yml's collect job: pip into the runner's own Python
    # (no setup-python), which PEP 668 may refuse on a newer image.
    "system-python": {
        "kind": "system",
        "main": "python3 --version && pip install --quiet pillow"
                " && python3 -c 'import PIL; print(\"Pillow\", PIL.__version__)'"
                " && python3 -m py_compile scripts/build_render_preview.py",
    },
}

# Tool versions recorded for every leg ("name", shell command). A missing tool
# is reported as such: `convert` disappearing is itself a finding.
VERSIONS = [
    ("OS", "lsb_release -ds"),
    ("image", "echo \"$ImageOS $ImageVersion\""),
    ("python (job)", "python --version"),
    ("python3 (system)", "/usr/bin/python3 --version"),
    ("R", "R --version"),
    ("tesseract", "tesseract --version"),
    ("pdftotext", "pdftotext -v"),
    ("convert (ImageMagick 6 name)", "convert -version"),
    ("magick (ImageMagick 7 name)", "magick -version"),
    ("playwright", "python -m playwright --version"),
]

# Changed paths never worth comparing (byte-code caches the fetchers leave).
SKIP_PATH = re.compile(r"(^|/)__pycache__/|\.pyc$")


def _sh(cmd: str, log: Path | None = None) -> int:
    print(f"::group::{cmd}", flush=True)
    proc = subprocess.run(["bash", "-o", "pipefail", "-c", cmd],
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    text = proc.stdout.decode("utf-8", "replace")
    print(text, flush=True)
    print("::endgroup::", flush=True)
    if log is not None:
        log.write_text(text, encoding="utf-8")
    return proc.returncode


def run_leg(target: str, out: Path, image: str) -> int:
    if target not in LEGS:
        print(f"unknown target {target!r}; known: {', '.join(LEGS)}", file=sys.stderr)
        return 2
    leg = LEGS[target]
    files = out / "files"
    files.mkdir(parents=True, exist_ok=True)
    (out / "meta.txt").write_text(f"{target}\n{leg['kind']}\n{image}\n", encoding="utf-8")

    exits: list[str] = []
    # Setup actions that ran before this script (setup-python / setup-r) pass
    # their outcome in; with continue-on-error they don't stop the leg.
    for name, var in (("setup-python", "SETUP_PY"), ("setup-r", "SETUP_R"),
                      ("setup-r-dependencies", "SETUP_RDEPS")):
        outcome = os.environ.get(var, "")
        if outcome and outcome != "skipped":
            exits.append(f"{name} {0 if outcome == 'success' else 1}")

    steps = []
    if leg.get("apt"):
        steps.append(("apt", "sudo apt-get update -qq && sudo apt-get install -y "
                             f"--no-install-recommends {leg['apt']}"))
    if leg.get("pip"):
        steps.append(("pip", f"pip install {leg['pip']}"))
    if leg.get("pre"):
        steps.append(("pre", leg["pre"]))
    steps.append(("main", leg["main"].format(files=files)))
    for name, cmd in steps:
        rc = _sh(cmd, out / f"{name}.log")
        exits.append(f"{name} {rc}")
        if rc:
            print(f"::warning title=canary {target}: {name} exited {rc}::{cmd}")
    (out / "exit_codes.txt").write_text("\n".join(exits) + "\n", encoding="utf-8")

    lines = []
    for name, cmd in VERSIONS:
        proc = subprocess.run(["bash", "-c", cmd], stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT)
        first = proc.stdout.decode("utf-8", "replace").strip().splitlines()
        lines.append(f"{name}: {first[0] if proc.returncode == 0 and first else '(not found)'}")
    (out / "versions.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

    # Everything the run changed in the working tree: stage it (index only,
    # nothing is committed) so new files show up too, then copy it out.
    subprocess.run(["git", "add", "-A"], check=False)
    names = subprocess.run(["git", "diff", "--cached", "--name-only", "-z"],
                           stdout=subprocess.PIPE, check=False).stdout.decode()
    changed = [p for p in names.split("\0") if p and not SKIP_PATH.search(p)]
    for rel in changed:
        src = Path(rel)
        dst = files / rel
        if src.is_file():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        else:  # deleted by the run
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.with_name(dst.name + ".DELETED").write_text("", encoding="utf-8")
    stat = subprocess.run(["git", "diff", "--cached", "--stat"], stdout=subprocess.PIPE,
                          check=False).stdout.decode("utf-8", "replace")
    (out / "diff_stat.txt").write_text(stat or "(no changes)\n", encoding="utf-8")
    print(stat or "(no changes)")
    return 0


# ── compare ─────────────────────────────────────────────────────────────────
NUM = re.compile(r"[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][-+]?\d+)?")
NOISE = 1e-9   # relative; floating-point noise from a different libm/BLAS
DRIFT = 1e-4   # relative; above this a number has visibly changed
BINARY = {".png", ".pdf", ".jpg", ".jpeg", ".gif", ".xlsx", ".xls", ".zip"}

# Verdict levels, worst last. Only RED fails the run.
SAME, INFO, NOISY, WARN, RED = range(5)
ICON = {SAME: "🟢", INFO: "⚪", NOISY: "🟢", WARN: "🟡", RED: "🔴"}


def _diff_excerpt(a: str, b: str, name: str, base: str, nxt: str, n: int = 30) -> str:
    lines = list(difflib.unified_diff(a.splitlines(), b.splitlines(),
                                      f"{name} ({base})", f"{name} ({nxt})", lineterm="", n=1))
    more = f"\n… {len(lines) - n} more lines" if len(lines) > n else ""
    return "\n".join(lines[:n]) + more


def compare_file(name: str, a: bytes | None, b: bytes | None,
                 base: str, nxt: str) -> tuple[int, str, str]:
    """Return (level, one-line summary, detail)."""
    if a is None or b is None:
        only = base if b is None else nxt
        level = INFO if Path(name).suffix.lower() in BINARY else RED
        return level, f"`{name}` changed on {only} only", ""
    if a == b:
        return SAME, f"`{name}` identical", ""
    if Path(name).suffix.lower() in BINARY:
        return INFO, f"`{name}` differs (binary; compare by eye)", ""
    ta, tb = a.decode("utf-8", "replace"), b.decode("utf-8", "replace")
    detail = _diff_excerpt(ta, tb, name, base, nxt)
    na, nb = NUM.findall(ta), NUM.findall(tb)
    if NUM.sub("#", ta) != NUM.sub("#", tb) or len(na) != len(nb):
        return RED, f"`{name}` differs in text", detail
    worst = 0.0
    for x, y in zip(na, nb):
        fx, fy = float(x), float(y)
        if fx != fy:
            worst = max(worst, abs(fx - fy) / max(abs(fx), abs(fy), 1e-300))
    if worst <= NOISE:
        return NOISY, f"`{name}` equal within float noise (max rel. Δ {worst:.1e})", detail
    if worst <= DRIFT:
        return WARN, f"`{name}` small numeric drift (max rel. Δ {worst:.1e})", detail
    return RED, f"`{name}` numbers differ (max rel. Δ {worst:.1e})", detail


def _load(leg_dir: Path) -> dict:
    target, kind, image = (leg_dir / "meta.txt").read_text(encoding="utf-8").split("\n")[:3]
    exits = {}
    p = leg_dir / "exit_codes.txt"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            step, _, rc = line.rpartition(" ")
            exits[step] = int(rc)
    versions = {}
    p = leg_dir / "versions.txt"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            k, _, v = line.partition(": ")
            versions[k] = v
    files = {}
    root = leg_dir / "files"
    if root.exists():
        for f in sorted(root.rglob("*")):
            if f.is_file():
                files[f.relative_to(root).as_posix()] = f.read_bytes()
    return {"target": target, "kind": kind, "image": image, "exits": exits,
            "versions": versions, "files": files}


def compare(root: Path, base: str, nxt: str, report: Path) -> int:
    legs: dict[str, dict[str, dict]] = {}
    for meta in sorted(root.glob("*/meta.txt")):
        leg = _load(meta.parent)
        legs.setdefault(leg["target"], {})[leg["image"]] = leg
    targets = [t for t in LEGS if t in legs] + sorted(set(legs) - set(LEGS))
    for t in LEGS:  # a leg that died before uploading anything
        if t not in legs:
            targets.append(t)
            legs[t] = {}

    def status(leg: dict | None) -> str:
        if not leg:
            return "no result"
        bad = [f"{k} exit {v}" for k, v in leg["exits"].items() if v]
        return "ok" if not bad else ", ".join(bad)

    rows, details, worst_all = [], [], SAME
    for t in targets:
        b, n = legs[t].get(base), legs[t].get(nxt)
        findings: list[tuple[int, str, str]] = []
        if not n and not b:
            findings.append((RED, "no result on either image (the leg died before uploading)", ""))
        elif not n:
            findings.append((RED, f"no result on {nxt} (the leg died before uploading; see its job log)", ""))
        elif not b:
            findings.append((INFO, f"no result on {base}; nothing to compare", ""))
        else:
            for step in sorted(set(b["exits"]) | set(n["exits"])):
                rb, rn = b["exits"].get(step), n["exits"].get(step)
                if rb == 0 and rn not in (0, None):
                    findings.append((RED, f"`{step}` fails on {nxt} only", ""))
                elif rn == 0 and rb not in (0, None):
                    findings.append((WARN, f"`{step}` fails on {base} only", ""))
            main_b, main_n = b["exits"].get("main"), n["exits"].get("main")
            if main_b and main_n:
                findings.append((INFO, "main step fails on both images (source down or a "
                                       "parser problem, not the OS); inconclusive", ""))
            elif main_b == 0 and main_n == 0:
                for name in sorted(set(b["files"]) | set(n["files"])):
                    findings.append(compare_file(name, b["files"].get(name),
                                                 n["files"].get(name), base, nxt))
                if not b["files"] and not n["files"]:
                    findings.append((SAME, "no changes on either image (reproduces master)", ""))
        level = max((f[0] for f in findings), default=SAME)
        worst_all = max(worst_all, level)
        # The worst findings, plus the informational ones (a differing PNG)
        # that a worse but harmless finding would otherwise hide.
        shown = [f for f in findings if f[0] in (level, INFO)] or findings
        summary = "<br>".join(f[1] for f in shown[:4])
        if len(shown) > 4:
            summary += f"<br>… and {len(shown) - 4} more"
        rows.append(f"| {ICON[level]} | `{t}` | {status(b)} | {status(n)} | {summary} |")
        for lvl, line, detail in findings:
            if detail and lvl >= WARN:
                details.append(f"<details><summary>{ICON[lvl]} {t}: {line}</summary>\n\n"
                               f"```diff\n{detail}\n```\n</details>")

    tools: dict[str, dict[str, str]] = {}
    for per_image in legs.values():
        for image, leg in per_image.items():
            for k, v in leg["versions"].items():
                if v != "(not found)" or k not in tools.get(image, {}):
                    tools.setdefault(image, {})[k] = v
    keys = [k for k, _ in VERSIONS]
    repo = (f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/"
            f"{os.environ.get('GITHUB_REPOSITORY', 'LeRaffl/LeRaffl-Gallery')}")

    out = [
        f"## Runner canary: `{base}` → `{nxt}`",
        "",
        {SAME: "🟢 **No difference that matters.** The next image reproduces the pinned one.",
         INFO: "🟢 **No difference that matters** (some informational notes below).",
         NOISY: "🟢 **No difference that matters** (float noise only).",
         WARN: "🟡 **Small differences: look before migrating.**",
         RED: "🔴 **The next image changes or breaks something. Don't migrate yet.**"}[worst_all],
        "",
        "| | Leg | " + base + " | " + nxt + " | Finding |",
        "|---|---|---|---|---|",
        *rows,
        "",
        "### Tool versions",
        "",
        f"| Tool | {base} | {nxt} |",
        "|---|---|---|",
        *[f"| {k} | {tools.get(base, {}).get(k, '–')} | {tools.get(nxt, {}).get(k, '–')} |"
          for k in keys],
        "",
        "How to read this, and the list of known risks: "
        f"[docs/architecture/56-runner-upgrades.md]({repo}/blob/master/docs/architecture/56-runner-upgrades.md).",
    ]
    if details:
        out += ["", "### Differences", "", *details]
    report.write_text("\n".join(out) + "\n", encoding="utf-8")
    print("\n".join(out))
    return 1 if worst_all == RED else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("leg")
    p.add_argument("target")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--image", required=True)
    p = sub.add_parser("compare")
    p.add_argument("root", type=Path)
    p.add_argument("--base", required=True)
    p.add_argument("--next", dest="nxt", required=True)
    p.add_argument("--report", type=Path, required=True)
    a = ap.parse_args()
    if a.cmd == "leg":
        return run_leg(a.target, a.out, a.image)
    return compare(a.root, a.base, a.nxt, a.report)


if __name__ == "__main__":
    sys.exit(main())
