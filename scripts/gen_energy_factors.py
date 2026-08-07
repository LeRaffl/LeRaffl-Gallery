#!/usr/bin/env python3
"""
Generate the in-page ``FE_F`` energy-factor constant in index.html from the
single source of truth, energy_factors.csv.

The fleet energy view (the primary-energy Sankey and the CO2e timeline) reads a
JavaScript object ``const FE_F = {...}`` in index.html. That object is NOT
hand-maintained: it is generated here from energy_factors.csv so the page and
the CSV can never drift apart. R/energy_flows.R reads the same CSV directly.

Usage
-----
    python scripts/gen_energy_factors.py           # rewrite FE_F in index.html
    python scripts/gen_energy_factors.py --check    # verify only; exit 1 on drift

Run --check in CI so a hand-edit to either file is caught.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = ROOT / "energy_factors.csv"
HTML_PATH = ROOT / "index.html"

# Matches `const FE_F = { ... };` (single object, no nested braces), possibly
# spanning several lines. Non-greedy so it stops at the first closing `};`.
FE_F_RE = re.compile(r"const FE_F = \{.*?\};", re.S)


def read_factors(path: Path = CSV_PATH) -> dict[str, float]:
    """Ordered key -> numeric value, skipping `#` comments and blank lines."""
    factors: dict[str, float] = {}
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.reader(fh):
            if not row:
                continue
            key = row[0].strip()
            if not key or key.startswith("#"):
                continue
            if key == "key":  # header
                continue
            try:
                factors[key] = float(row[1])
            except (IndexError, ValueError) as exc:
                raise SystemExit(f"energy_factors.csv: bad numeric value for '{key}': {exc}")
    if not factors:
        raise SystemExit("energy_factors.csv: no factors parsed")
    return factors


def fe_f_literal(factors: dict[str, float]) -> str:
    """The exact `const FE_F = {...};` line the page should contain."""
    body = json.dumps(factors, separators=(",", ":"))  # compact, no spaces
    return f"const FE_F = {body};"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="verify index.html matches the CSV; exit 1 on drift")
    args = ap.parse_args()

    factors = read_factors()
    literal = fe_f_literal(factors)
    html = HTML_PATH.read_text(encoding="utf-8")

    if not FE_F_RE.search(html):
        raise SystemExit("index.html: could not find `const FE_F = {...};`")

    new_html = FE_F_RE.sub(lambda _m: literal, html, count=1)

    if args.check:
        if new_html == html:
            print(f"OK: FE_F in index.html matches energy_factors.csv ({len(factors)} factors)")
            return 0
        print("DRIFT: index.html FE_F is out of sync with energy_factors.csv.\n"
              "       Run: python scripts/gen_energy_factors.py", file=sys.stderr)
        return 1

    if new_html == html:
        print(f"FE_F already up to date ({len(factors)} factors); no change.")
        return 0
    HTML_PATH.write_text(new_html, encoding="utf-8")
    print(f"Updated FE_F in index.html from energy_factors.csv ({len(factors)} factors).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
