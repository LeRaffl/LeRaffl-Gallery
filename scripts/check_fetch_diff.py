#!/usr/bin/env python3
"""Refuse to commit a fetch that emptied or shrank a data CSV.

Runs in every fetch workflow right before its commit step, on the working
tree the fetcher just wrote:

    python scripts/check_fetch_diff.py            # checks data/*.csv vs HEAD

For each data/*.csv that is new or modified it fails (exit 1) when

  * the file is empty or header-only,
  * it has fewer data rows than at HEAD (a fetcher only appends or rewrites
    rows; a row that vanishes is a parse that came back short), or
  * a row it added or changed carries no value at all — every column after
    period,time_interval,variant,source (bar notes) blank.

The fetchers already refuse most bad payloads themselves; this is the one
check they all share, so a new fetcher or a quiet regression cannot commit
an empty month and have it rendered. Set FETCH_ALLOW_SHRINK=1 for a run that
removes rows on purpose (a reclassification moved by hand).
"""
from __future__ import annotations

import csv
import io
import os
import subprocess
import sys
from pathlib import Path

KEY_COLS = ("period", "time_interval", "variant", "source")


def git(*args: str, cwd: Path) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True,
                          capture_output=True, text=True).stdout


def changed_csvs(repo: Path) -> list[str]:
    out = git("status", "--porcelain", "--untracked-files=all", "--", "data",
              cwd=repo)
    paths = []
    for line in out.splitlines():
        status, path = line[:2], line[3:].strip().strip('"')
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        if path.endswith(".csv") and "D" not in status:
            paths.append(path)
    return sorted(set(paths))


def rows_of(text: str) -> tuple[list[str], list[list[str]]]:
    rdr = list(csv.reader(io.StringIO(text)))
    rdr = [r for r in rdr if any(c.strip() for c in r)]
    if not rdr:
        return [], []
    return rdr[0], rdr[1:]


def blank_value_rows(header: list[str], rows: list[list[str]]) -> list[list[str]]:
    """Rows whose value columns are all empty (only for the standard layout)."""
    if tuple(h.strip() for h in header[:4]) != KEY_COLS:
        return []
    vals = [i for i, h in enumerate(header)
            if i >= 4 and h.strip().lower() != "notes"]
    if not vals:
        return []
    return [r for r in rows
            if all(i >= len(r) or not r[i].strip() for i in vals)]


def check_file(path: str, new_text: str, old_text: str | None) -> list[str]:
    problems = []
    header, rows = rows_of(new_text)
    if not header or not rows:
        return [f"{path}: empty or header-only after the fetch"]
    old_rows: list[list[str]] = []
    if old_text is not None:
        _, old_rows = rows_of(old_text)
        if len(rows) < len(old_rows) and os.environ.get("FETCH_ALLOW_SHRINK") != "1":
            problems.append(f"{path}: {len(old_rows)} → {len(rows)} data rows; "
                            "a fetch should never drop rows")
    old_set = {tuple(r) for r in old_rows}
    touched = [r for r in rows if tuple(r) not in old_set]
    for r in blank_value_rows(header, touched):
        problems.append(f"{path}: row {','.join(r[:3])} has no values at all")
    return problems


def main(argv: list[str] | None = None) -> int:
    repo = Path(git("rev-parse", "--show-toplevel", cwd=Path.cwd()).strip())
    problems: list[str] = []
    paths = changed_csvs(repo)
    for path in paths:
        new_text = (repo / path).read_text(encoding="utf-8-sig")
        try:
            old_text = git("show", f"HEAD:{path}", cwd=repo)
        except subprocess.CalledProcessError:
            old_text = None                      # a new file
        problems += check_file(path, new_text, old_text)
    for p in problems:
        print(f"::error title=Fetch output guard::{p}")
    if problems:
        print(f"{len(problems)} problem(s) — not committing this fetch.")
        return 1
    print(f"Fetch output guard: {len(paths)} changed data CSV(s) look sane.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
