#!/usr/bin/env python3
"""Build `sources/schedule.json` — the data behind the gallery's Schedule tab.

The old `schedule.html` plotted **cron slots**, which is why it read as flag
soup: most fetchers poll daily through a window, so a month showed ~460 chips
for ~30 real data arrivals. A polling tick is not an event a reader cares
about. What they want to know is:

    "Is my country up to date, and when does the next point arrive?"

So this emits per-country *freshness*, not per-day cron ticks:

  * `latest_period`  — the newest period actually in our CSV.
  * `last_render`    — when a chart for it was last produced (manifest date),
                       i.e. when data genuinely last landed.
  * `expected_period`— what we ought to hold today, derived from the cadence
                       and the fetcher's polling window (see `expected_for`).
  * `status`         — current / due / late / manual, from those two.
  * `window`         — the days of the month the fetcher polls, which is also
                       the earliest plausible publication day. The compact
                       calendar uses the *start* of this window, not every day
                       in it.

Everything is derived at build time from the workflows, the CSVs and
manifest.json — nothing here is hand-maintained.

    python3 scripts/build_schedule.py
"""

from __future__ import annotations

import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_source_pages import (  # noqa: E402
    REPO, apply_group_defaults, collect_entries, read_variant_facts,
    variant_file,
)

WORKFLOWS = REPO / ".github" / "workflows"
MANIFEST = REPO / "manifest.json"
OUT = REPO / "sources" / "schedule.json"


# --------------------------------------------------------------------------
# Cron
# --------------------------------------------------------------------------

def _field(spec: str, lo: int, hi: int) -> list[int]:
    if spec == "*":
        return list(range(lo, hi + 1))
    out: set[int] = set()
    for part in spec.split(","):
        step = 1
        if "/" in part:
            part, step_s = part.split("/", 1)
            step = int(step_s)
        if part == "*":
            a, b = lo, hi
        elif "-" in part:
            a, b = (int(x) for x in part.split("-", 1))
        else:
            a = b = int(part)
        out.update(range(a, b + 1, step))
    return sorted(out)


def read_workflow_schedule(slug: str) -> dict | None:
    """Cron facts for a fetch workflow: polling days, months and times.

    A workflow whose cron is commented out (New Zealand) reports
    `enabled: False` rather than vanishing — a disabled fetcher is a fact
    worth showing, not an absence.
    """
    path = WORKFLOWS / f"fetch-{slug}.yml"
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8")
    live = re.findall(r"^\s*-\s*cron:\s*'([^']+)'", text, re.M)
    dead = re.findall(r"^\s*#\s*-\s*cron:\s*'([^']+)'", text, re.M)
    crons = live or dead
    if not crons:
        return None

    days: set[int] = set()
    months: set[int] = set()
    times: set[str] = set()
    for expr in crons:
        parts = expr.split()
        if len(parts) != 5:
            continue
        minute, hour, dom, mon, _dow = parts
        days.update(_field(dom, 1, 31))
        months.update(_field(mon, 1, 12))
        for h in _field(hour, 0, 23):
            times.add(f"{h:02d}:{int(minute.split(',')[0]):02d}")

    return {
        "enabled": bool(live),
        "days": sorted(days),
        "months": sorted(months),
        "times": sorted(times),
        "workflow": f".github/workflows/fetch-{slug}.yml",
    }


# --------------------------------------------------------------------------
# Periods
# --------------------------------------------------------------------------

def shift(period: str, months: int) -> str:
    y, m = int(period[:4]), int(period[5:7])
    total = y * 12 + (m - 1) + months
    return f"{total // 12:04d}-{total % 12 + 1:02d}"


def months_between(a: str, b: str) -> int:
    """How many months `b` is ahead of `a` (both YYYY-MM)."""
    ay, am = int(a[:4]), int(a[5:7])
    by, bm = int(b[:4]), int(b[5:7])
    return (by * 12 + bm) - (ay * 12 + am)


def expected_for(interval: str, sched: dict | None, today: date) -> str:
    """The newest period we should already hold, given cadence + poll window.

    The cron's **first polling day** is the maintainer's encoding of "the
    earliest this source plausibly publishes" — ACEA polls from the 16th
    because ACEA publishes in the third or fourth week. So before that day
    we have no business expecting last month's figure yet.
    """
    prev_month = shift(f"{today.year:04d}-{today.month:02d}", -1)

    if interval == "quarterly":
        # Quarters are stored at their middle month (…-02, -05, -08, -11).
        # Expect the newest quarter whose polling window has already opened.
        months = (sched or {}).get("months") or [3, 6, 9, 12]
        start = min((sched or {}).get("days") or [1])
        cur = date(today.year, today.month, 1)
        for _ in range(12):
            if cur.month in months and (cur < date(today.year, today.month, 1)
                                        or today.day >= start):
                # A window in month M releases the quarter that ended ~2.5
                # months earlier; that quarter's middle month is M − 4.
                return shift(f"{cur.year:04d}-{cur.month:02d}", -4)
            cur = date(cur.year - 1, 12, 1) if cur.month == 1 else \
                date(cur.year, cur.month - 1, 1)
        return prev_month

    if interval == "yearly":
        return f"{today.year - 1:04d}-12"

    # Monthly. Before the polling window opens, last month isn't due yet.
    start = min((sched or {}).get("days") or [1])
    if sched and sched.get("enabled") and today.day < start:
        return shift(prev_month, -1)
    return prev_month


# --------------------------------------------------------------------------
# Build
# --------------------------------------------------------------------------

def manifest_last_render() -> dict[str, dict]:
    """Newest chart render per country — when data genuinely last landed.

    Keyed by the manifest's **country name**, not its `country_slug`: the two
    slug conventions disagree (`new-zealand` here vs `new_zealand`/`newzealand`
    there, and `turkiye` vs `tuerkiye`), which silently blanked those rows.
    The manifest's `country` carries the variant in brackets — "Canada
    (Pickups)" — so the base name before the bracket is what we match on.
    """
    if not MANIFEST.is_file():
        return {}
    images = json.loads(MANIFEST.read_text(encoding="utf-8")).get("images") or []
    best: dict[str, dict] = {}
    for img in images:
        name = (img.get("country") or "").split(" (")[0].strip()
        if not name or not img.get("date"):
            continue
        cur = best.get(name)
        if cur is None or img["date"] > cur["date"]:
            best[name] = {"date": img["date"], "period": img.get("period")}
    return best


def build(today: date | None = None) -> dict:
    today = today or datetime.now(timezone.utc).date()
    renders = manifest_last_render()
    entries, problems = collect_entries()
    if problems:
        for p in problems:
            print(f"  ! {p}", file=sys.stderr)

    rows = []
    for fm, _is_stub in entries:
        fm = apply_group_defaults(fm)
        slug = fm["slug"]
        wf_slug = Path(fm["workflow"]).stem.replace("fetch-", "") if fm.get("workflow") else None
        sched = read_workflow_schedule(wf_slug) if wf_slug else None

        variants = []
        for name in (fm.get("variants") or []):
            facts = read_variant_facts(variant_file(fm, name))
            variants.append({
                "name": name,
                "latest": facts["last"] if facts else None,
                "first": facts["first"] if facts else None,
                "rows": facts["rows"] if facts else 0,
                "cadence": (facts["cadence"][0] if facts and facts["cadence"] else None),
                "in_repo": facts is not None,
            })

        whole = next((v for v in variants if v["name"] == "Whole"), None)
        latest = whole["latest"] if whole else None
        interval = (whole or {}).get("cadence") or "monthly"
        automated = bool(sched and sched.get("enabled"))

        # `expected` is only meaningful where a cron encodes the publication
        # window. For a hand-maintained source we don't know when the
        # publisher releases, so we say nothing rather than inventing a lag
        # (Georgia is quarterly and manual — guessing a window there produced
        # an "expected" two quarters behind what we actually held).
        expected = expected_for(interval, sched, today) if (latest and automated) else None
        behind = months_between(latest, expected) if (latest and expected) else None
        step = 3 if interval == "quarterly" else (12 if interval == "yearly" else 1)

        if latest is None:
            status = "unknown"
        elif not automated:
            status = "manual"
        elif behind is None or behind <= 0:
            status = "current"
        elif behind <= step:
            status = "due"
        else:
            status = "late"

        # Factual regardless of automation: how far the newest period sits
        # behind the month that just ended.
        now_period = f"{today.year:04d}-{today.month:02d}"
        behind_now = months_between(latest, shift(now_period, -1)) if latest else None

        rows.append({
            "country": fm["country"],
            "slug": slug,
            "method": fm.get("method"),
            "source_name": fm.get("source_name"),
            "source_url": fm.get("source_url"),
            "cadence_text": fm.get("cadence"),
            "interval": interval,
            "latest_period": latest,
            "expected_period": expected,
            "behind": behind,
            "behind_now": behind_now,
            "status": status,
            "automated": automated,
            "schedule": sched,
            "last_render": (renders.get(fm["country"]) or {}).get("date"),
            "variants": variants,
        })

    rows.sort(key=lambda r: r["country"])
    return {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "today": today.isoformat(),
        "countries": rows,
    }


def main() -> int:
    data = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    counts: dict[str, int] = {}
    for r in data["countries"]:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    summary = ", ".join(f"{v} {k}" for k, v in sorted(counts.items()))
    print(f"  ✓ sources/schedule.json — {len(data['countries'])} countries ({summary})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
