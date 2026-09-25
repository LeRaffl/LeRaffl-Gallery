#!/usr/bin/env python3
"""Check that every gallery country is wired into every place it has to be.

Adding a country touches ~15 files (docs/architecture/42-adding-a-country.md
is the walkthrough). Most of them fail *silently* when forgotten: a missing
flag file just renders a chart without a flag, a country missing from the
Builder's region group just isn't in the Asia curve, a country missing from
the backtest just isn't in the Time-lapse GIF. This script turns each of those
into a named, explained failure.

    python scripts/check_country_integration.py                 # every country
    python scripts/check_country_integration.py --country "Hong Kong"
    python scripts/check_country_integration.py --list-checks

Countries are derived from data/<Country>[_<Variant>].csv, the same way
R/render_country.R and R/build_backtest.R derive them.

Every check is an ERROR unless it is listed for that country in KNOWN_GAPS
below (pre-existing gaps, each with the reason it is accepted). A new country
therefore has to pass everything or add itself there with a reason — which a
reviewer will see in the diff. Exit status 1 on any error, and also on a
stale KNOWN_GAPS entry (a gap that has since been fixed), so the list can
only shrink.

Two checks can only pass after the PR's CI has run once (see the playbook):
`backtest` (dispatch snapshot-builder.yml on the PR branch with
backtest_only=true) — and `params` which is a WARNING only, because the first
render happens after merge.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

# Groups in BUILDER_GROUPS that describe geography (the rest are political
# or size-based: eu, g7, world, none, small/medium/big_markets).
GEO_GROUPS = ("western_europe", "northern_europe", "southern_europe", "eastern_europe",
              "north_america", "south_america", "americas", "asia")

# Series a Weibull fit needs before the backtest fits it (R/build_backtest.R).
MIN_ROWS = 24
# Mirror of DATA_ONLY_SERIES in R/build_backtest.R.
DATA_ONLY_SERIES = {"Argentina|Pickups"}
# Variant names that are archives, not series (data/France_legacy.csv, …).
ARCHIVE_VARIANTS = {"legacy"}

# Pre-existing gaps, accepted with a reason. {country: {check: reason}}.
# Do not add a new country here to make CI green without a reason a reviewer
# would accept.
KNOWN_GAPS: dict[str, dict[str, str]] = {
    # Region groups: BUILDER_GROUPS has no Oceania / Middle East / Caucasus /
    # South Asia group, and Türkiye and Albania were never assigned one.
    # Each is an owner decision still open (2026-09-25).
    "Australia": {"geo_group": "open: no Oceania group in BUILDER_GROUPS"},
    "New Zealand": {"geo_group": "open: no Oceania group in BUILDER_GROUPS",
                    "flag_png": "open: flag stored as newzealand.png, render looks for new_zealand.png"},
    "Georgia": {"geo_group": "open: Caucasus — no fitting group"},
    "Israel": {"geo_group": "open: no Middle-East group (COUNTRY_REGION files it under Asia)",
               "flag_png": "open: no assets/flags/israel.png",
               "sd_countries": "open: not offered in Submit-Data",
               "glossary": "open: Israel_Vans missing from the 09 glossary tables",
               "workflow_docs": "open: fetch-israel.yml missing from 02/08 tables and render_schedule.R"},
    "Nepal": {"geo_group": "open: customs imports, not registrations — Asia membership undecided",
              "sd_countries": "open: not offered in Submit-Data"},
    "Türkiye": {"geo_group": "open: COUNTRY_REGION says Europe, but no Europe sub-group chosen"},
    "Albania": {"geo_group": "open: Western Balkans — no Europe sub-group chosen",
                "sd_countries": "open: not offered in Submit-Data"},
    "South Korea": {"flag_png": "open: flag stored as southkorea.png, render looks for south_korea.png"},
    "Malta": {"flag_png": "open: no assets/flags/malta.png"},
    "France": {"workflow_docs": "open: fetch-france.yml missing from 02/08 tables and render_schedule.R"},
    "India": {"sd_countries": "open: not offered in Submit-Data",
              "timezone": "open: Asia/Kolkata not in TZ_COUNTRY"},
    "Colombia": {"sd_countries": "open: not offered in Submit-Data"},
    "Denmark": {"sd_countries": "open: not offered in Submit-Data"},
    "Finland": {"sd_countries": "open: not offered in Submit-Data"},
    "Malaysia": {"sd_countries": "open: not offered in Submit-Data"},
    "Netherlands": {"sd_countries": "open: not offered in Submit-Data"},
}


# ── readers ────────────────────────────────────────────────────────────────

def read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


def country_of(base: str) -> tuple[str, str]:
    """data file base name -> (country, variant) like R/build_backtest.R."""
    if "_" not in base:
        return base, "Whole"
    return base.rsplit("_", 1)[0], base.rsplit("_", 1)[1]


def data_series() -> dict[str, dict[str, int]]:
    """{country: {variant: row count}} from data/*.csv."""
    out: dict[str, dict[str, int]] = {}
    for f in sorted((REPO / "data").glob("*.csv")):
        country, variant = country_of(f.stem)
        if variant in ARCHIVE_VARIANTS:
            continue
        with open(f, newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        by_v: dict[str, int] = {}
        for r in rows:
            v = (r.get("variant") or "Whole").strip()
            by_v[v] = by_v.get(v, 0) + 1
        for v, n in by_v.items():
            out.setdefault(country, {})[v] = n
    return out


def js_block(src: str, start: str) -> str:
    """Text from `start` to the first line that closes the block at col 0."""
    i = src.index(start)
    j = src.index("\n};", i) if "\n};" in src[i:] else len(src)
    k = src.find("\n];", i)
    if k != -1 and k < j:
        j = k
    return src[i:j]


def builder_groups_js(html: str) -> dict[str, list[str]]:
    block = js_block(html, "const BUILDER_GROUPS = {")
    groups = {}
    for m in re.finditer(r"^\s*([a-z_]+):\s*rows\s*=>\s*\[(.*?)\]", block, re.S | re.M):
        groups[m.group(1)] = re.findall(r"'([^']+)'", m.group(2))
    return groups


def builder_groups_py() -> dict[str, list[str]]:
    import snapshot_builder as sb  # noqa: E402
    return {k: list(v) for k, v in sb.GROUPS_STATIC.items() if v is not None}


def sd_countries(html: str) -> set[str]:
    return set(re.findall(r"\{\s*country:\s*'([^']+)'", js_block(html, "const SD_COUNTRIES = [")))


def tz_countries(html: str) -> set[str]:
    """Countries reachable from TZ_COUNTRY (exact zones) or TZ_PREFIX."""
    block = js_block(html, "const TZ_COUNTRY = {")
    out = set(re.findall(r"'[^']+':'([^']+)'", block))
    i = html.index("const TZ_PREFIX = [")
    prefix = html[i:html.index("]];", i)]
    return out | set(re.findall(r"\['[^']+','([^']+)'\]", prefix))


def region_countries(html: str) -> set[str]:
    block = js_block(html, "const COUNTRY_REGION={")
    return set(re.findall(r"'([^']+)':'[A-Za-z ]+'", block))


def post_text_flags() -> set[str]:
    src = read("R/post_text.R")
    names = re.findall(r"(?:`([^`]+)`|\b([A-Z][A-Za-zÀ-ſ]*))\s*=\s*\"\\U0001F1", src)
    return {a or b for a, b in names}


def schedule_keys() -> tuple[set[str], set[str]]:
    src = read("R/render_schedule.R")
    def keys(block_name):
        b = src[src.index(f"{block_name} <- c("):]
        b = b[:b.index("\n)")]
        return {a or b2 for a, b2 in re.findall(r"(?:`([^`]+)`|\b([a-z_]+))\s*=", b)}
    return keys("FLAG"), keys("LABEL")


def r_slug(country: str) -> str:
    """R/render_country.R slug_country() for the Whole variant."""
    pairs = [("ü", "ue"), ("ö", "oe"), ("ä", "ae"), ("ß", "ss"), ("Ü", "Ue"), ("Ö", "Oe"),
             ("Ä", "Ae"), ("ı", "i"), ("İ", "I"), ("ş", "s"), ("Ş", "S"), ("ğ", "g"),
             ("Ğ", "G"), ("ç", "c"), ("Ç", "C")]
    for a, b in pairs:
        country = country.replace(a, b)
    return re.sub(r"[^A-Za-z0-9]+", "_", country).lower()


def source_entries() -> dict[str, dict]:
    """{country: front-matter} from source docs and the stub registry."""
    import yaml
    out = {}
    for p in sorted((REPO / "docs/architecture").glob("*-source-*.md")):
        m = re.match(r"^---\n(.*?)\n---\n", p.read_text(encoding="utf-8"), re.S)
        if m:
            fm = yaml.safe_load(m.group(1)) or {}
            if fm.get("country"):
                out[fm["country"]] = {**fm, "_file": str(p.relative_to(REPO))}
    stubs = yaml.safe_load(read("docs/architecture/country_source_stubs.yaml")) or {}
    for s in stubs.get("stubs", []):
        out.setdefault(s["country"], {**s, "_file": "country_source_stubs.yaml"})
    return out


def footnote_keys() -> set[tuple[str, str]]:
    with open(REPO / "footnotes.csv", newline="", encoding="utf-8") as fh:
        return {(r["country"], r["variant"]) for r in csv.DictReader(fh)}


def backtest_keys() -> set[str]:
    keys = set()
    for f in (REPO / "backtest/params").glob("*.csv"):
        with open(f, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                keys.add(f"{r['country']}|{r['variant']}")
    return keys


def params_keys() -> set[str]:
    with open(REPO / "params.csv", newline="", encoding="utf-8") as fh:
        return {f"{r['country']}|{r['variant']}" for r in csv.DictReader(fh)}


# ── checks ─────────────────────────────────────────────────────────────────

CHECKS = {
    "sd_countries": "listed in SD_COUNTRIES (index.html) — Submit-Data tab",
    "flag_png": "assets/flags/<slug>.png exists, slug as R/render_country.R derives it",
    "flag_emoji": "flag emoji in R/post_text.R (.pt_flag) — post text",
    "region_color": "in COUNTRY_REGION (index.html) — continent colour in Compare / map",
    "geo_group": "in a geographic BUILDER_GROUPS group (index.html + snapshot_builder.py) — Builder / Time-lapse regional curves",
    "timezone": "an IANA zone in TZ_COUNTRY (index.html) — home-country detection",
    "source_page": "a docs/architecture/NN-source-*.md front-matter or a country_source_stubs.yaml entry — public source page",
    "footnote": "(warning) footnotes.csv has a (country, Whole) caveat row",
    "glossary": "multi-variant countries appear in docs/architecture/09-glossary.md",
    "workflow_docs": "the source's fetch workflow is listed in 02-components and 08-deploy-ops, and has FLAG/LABEL in R/render_schedule.R",
    "backtest": "the Whole series (>= 24 rows) is in backtest/params — Time-lapse panel and GIFs",
    "params": "(warning) params.csv has the Whole row — appears after the first render",
}


def run(only: str | None) -> int:
    html = read("index.html")
    series = data_series()
    sd = sd_countries(html)
    tz = tz_countries(html)
    region = region_countries(html)
    flags = post_text_flags()
    js_groups = builder_groups_js(html)
    py_groups = builder_groups_py()
    geo_members = {c for g in GEO_GROUPS for c in js_groups.get(g, [])}
    sources = source_entries()
    notes = footnote_keys()
    glossary = read("docs/architecture/09-glossary.md")
    bt = backtest_keys()
    params = params_keys()
    sched_flag, sched_label = schedule_keys()
    docs_02 = read("docs/architecture/02-components.md")
    docs_08 = read("docs/architecture/08-deploy-ops.md")

    errors: list[str] = []
    warnings: list[str] = []
    used_gaps: set[tuple[str, str]] = set()

    # Global: the Builder group mirror must be identical.
    for g in sorted(set(js_groups) | set(py_groups)):
        if g in ("world", "none"):
            continue
        a, b = js_groups.get(g), py_groups.get(g)
        if a is not None and b is not None and a != b:
            errors.append(f"[mirror] BUILDER_GROUPS.{g} differs: index.html {a} vs "
                          f"snapshot_builder.py {b}")
        elif (a is None) != (b is None) and g in GEO_GROUPS:
            errors.append(f"[mirror] BUILDER_GROUPS.{g} only in "
                          f"{'index.html' if b is None else 'snapshot_builder.py'}")

    countries = sorted(series) if not only else [only]
    if only and only not in series:
        print(f"No data/{only}*.csv found.")
        return 1

    for c in countries:
        gaps = KNOWN_GAPS.get(c, {})
        variants = series[c]
        failures: dict[str, str] = {}

        if c not in sd:
            failures["sd_countries"] = "add `{ country: '%s', variants: ['Whole'] }` to SD_COUNTRIES" % c
        slug = r_slug(c)
        if not (REPO / f"assets/flags/{slug}.png").exists():
            failures["flag_png"] = f"assets/flags/{slug}.png missing"
        if c not in flags:
            failures["flag_emoji"] = "add the regional-indicator pair to the map in R/post_text.R"
        if c not in region:
            failures["region_color"] = "add to COUNTRY_REGION in index.html"
        if "Whole" in variants and c not in geo_members:
            failures["geo_group"] = ("add to a geographic group in BUILDER_GROUPS (index.html) "
                                     "AND GROUPS_STATIC (scripts/snapshot_builder.py)")
        if c not in tz:
            failures["timezone"] = "add its IANA zone(s) to TZ_COUNTRY in index.html"
        fm = sources.get(c)
        if not fm:
            failures["source_page"] = "write docs/architecture/NN-source-<slug>.md or a stub entry"
        if (c, "Whole") not in notes and "Whole" in variants:
            warnings.append(f"{c}: [footnote] no footnotes.csv Whole row — add one if the "
                            "source has any caveat (scope, missing split, estimates)")
        if len([v for v in variants if v != "Whole"]) and c not in glossary:
            failures["glossary"] = "add the country's variants to 09-glossary.md (scope + variant tables)"
        wf = (fm or {}).get("workflow")
        if wf:
            name = Path(wf).name
            wslug = re.sub(r"^fetch-|\.yml$", "", name)
            missing = [where for where, text in (("02-components", docs_02),
                                                 ("08-deploy-ops", docs_08)) if name not in text]
            if wslug not in sched_flag or wslug not in sched_label:
                missing.append(f"R/render_schedule.R FLAG/LABEL `{wslug}`")
            if not (REPO / wf).exists():
                missing.append(f"{wf} does not exist")
            if missing:
                failures["workflow_docs"] = "missing in: " + ", ".join(missing)
        # Whole only: the regional curves and GIFs are Whole, and a variant
        # whose fit fails is deliberately never retried by build_backtest.R.
        if (variants.get("Whole", 0) >= MIN_ROWS and f"{c}|Whole" not in DATA_ONLY_SERIES
                and f"{c}|Whole" not in bt):
            failures["backtest"] = ("Whole is in no backtest/params month — dispatch "
                                    "snapshot-builder.yml with backtest_only=true on the branch")
        if "Whole" in variants and f"{c}|Whole" not in params:
            warnings.append(f"{c}: [params] no params.csv Whole row yet — render after merge "
                            "(render-country.yml)")

        for check, msg in failures.items():
            if check in gaps:
                used_gaps.add((c, check))
                continue
            errors.append(f"{c}: [{check}] {msg}")

    if not only:
        for c, gaps in KNOWN_GAPS.items():
            for check in gaps:
                if (c, check) not in used_gaps and c in series:
                    errors.append(f"{c}: KNOWN_GAPS[{check!r}] is stale — the gap is fixed; "
                                  "remove the entry")

    foot = [w for w in warnings if "[footnote]" in w]
    for w in warnings:
        if only or w not in foot:
            print(f"WARN  {w}")
    if foot and not only:
        print(f"WARN  {len(foot)} countries have no footnotes.csv Whole row "
              "(fine when the source has no caveat; --country shows each)")
    for e in errors:
        print(f"ERROR {e}")
    n = len(countries)
    print(f"{n} countr{'y' if n == 1 else 'ies'} checked, {len(errors)} error(s), "
          f"{len(warnings)} warning(s), {len(used_gaps)} known gap(s) accepted.")
    return 1 if errors else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--country", help="check one country only")
    ap.add_argument("--list-checks", action="store_true")
    args = ap.parse_args()
    if args.list_checks:
        for k, v in CHECKS.items():
            print(f"{k:14s} {v}")
        return 0
    return run(args.country)


if __name__ == "__main__":
    sys.exit(main())
