#!/usr/bin/env python3
"""Build the monthly Gallery release note. Does not publish a release.

The note keeps Release: lines from pull requests merged in the stand month,
plus a short data-through summary. The full title list is a collapsed appendix.
"""
from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def stand_month(today: date, explicit: str = "") -> str:
    if explicit:
        return explicit
    return f"{today.year}-{today.month:02d}"


def next_month(month: str) -> str:
    year, mon = (int(p) for p in month.split("-"))
    if mon == 12:
        return f"{year + 1}-01"
    return f"{year}-{mon + 1:02d}"


def release_lines(bodies: list[str]) -> list[str]:
    out = []
    for body in bodies:
        for line in (body or "").splitlines():
            if line.startswith("Release:"):
                text = line.split(":", 1)[1].strip()
                if text:
                    out.append(text)
    return out


def latest_periods(data_dir: Path) -> dict[str, str]:
    found = {}
    for path in sorted(data_dir.glob("*.csv")):
        if "_" in path.stem:
            continue
        latest = ""
        with path.open(newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                period = (row.get("period") or "").strip()
                if period > latest:
                    latest = period
        if latest:
            found[path.stem] = latest
    return found


def data_half(latest: dict[str, str]) -> str:
    if not latest:
        return "No country series found."
    lead = max(latest.values())
    at_lead = sorted(name for name, period in latest.items() if period == lead)
    behind = sorted(
        ((name, period) for name, period in latest.items() if period != lead),
        key=lambda item: item[1],
    )
    lines = [f"{len(at_lead)} series through {lead}."]
    if behind:
        shown = ", ".join(f"{name} {period}" for name, period in behind[:8])
        more = len(behind) - 8
        tail = f", and {more} more" if more > 0 else ""
        lines.append(f"Still earlier: {shown}{tail}.")
    else:
        lines.append("No series is behind that month.")
    return " ".join(lines)


def render_note(month: str, lines: list[str], data: str, titles: list[str]) -> str:
    parts = [f"## v{month}", ""]
    if lines:
        parts.extend(f"- {line}" for line in lines)
    else:
        parts.append("No reading changes were marked this month.")
    parts.extend(["", data, ""])
    if titles:
        folded = "\n".join(f"- {title}" for title in titles)
        parts.append("<details>")
        parts.append(f"<summary>Merged pull requests ({len(titles)})</summary>")
        parts.append("")
        parts.append(folded)
        parts.append("</details>")
        parts.append("")
    return "\n".join(parts)


def citation(tag: str, released: str) -> str:
    return f"""cff-version: 1.2.0
message: >-
  Cite this release, not the moving branch. Cite the original source for a
  number, and the Gallery for a fit or a chart. Code is MIT; charts and fits
  are CC BY 4.0. Registration figures are not licensed here.
title: BEV Trajectory Gallery
version: {tag}
date-released: {released}
url: https://github.com/LeRaffl/LeRaffl-Gallery/releases/tag/{tag}
authors:
  - family-names: Wellmann
    given-names: Raphael
license: MIT
"""


def _gh_prs(repo: str, month: str) -> list[dict]:
    end = next_month(month)
    search = f"merged:>={month}-01 merged:<{end}-01"
    raw = subprocess.check_output(
        [
            "gh", "pr", "list", "-R", repo, "--state", "merged",
            "--limit", "200", "--search", search,
            "--json", "number,title,body,mergedAt",
        ],
        text=True,
    )
    return json.loads(raw)


def build(month: str, data_dir: Path, prs: list[dict]) -> str:
    lines = release_lines([pr.get("body") or "" for pr in prs])
    titles = [f"#{pr['number']} {pr['title']}" for pr in prs if pr.get("title")]
    return render_note(month, lines, data_half(latest_periods(data_dir)), titles)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--month", default="")
    ap.add_argument("--write", default="")
    ap.add_argument("--citation-out", default="")
    ap.add_argument("--released", default="")
    ap.add_argument("--repo", default="LeRaffl/LeRaffl-Gallery")
    ap.add_argument("--data-dir", default=str(ROOT / "data"))
    args = ap.parse_args(argv)
    month = stand_month(date.today(), args.month)
    prs = _gh_prs(args.repo, month)
    note = build(month, Path(args.data_dir), prs)
    if args.write:
        Path(args.write).write_text(note, encoding="utf-8")
    else:
        sys.stdout.write(note)
    if args.citation_out:
        tag = f"v{month}"
        released = args.released or date.today().isoformat()
        Path(args.citation_out).write_text(citation(tag, released), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
