#!/usr/bin/env python3
"""Tests for scripts/build_updates.py (home page "Latest updates" feed) and
its section in index.html.

    python scripts/test_build_updates.py
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import build_updates as bu  # noqa: E402

fails: list[str] = []


def check(name: str, cond: bool) -> None:
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        fails.append(name)


H = "period,time_interval,variant,source,BEV,PETROL,TOTAL,notes"
LOG = "\n".join([
    # a new month for the headline series plus a revised earlier month
    "\x1eCOMMIT aaaa1111 2026-11-21T19:27:54Z p1|chore: update Türkiye data from TÜİK",
    "",
    "diff --git a/data/Türkiye.csv b/data/Türkiye.csv",
    "index 1..2 100644",
    "--- a/data/Türkiye.csv",
    "+++ b/data/Türkiye.csv",
    f"@@ -130 +130,2 @@ {H}",
    "-2026-09,monthly,Whole,TUIK,1.0,2.0,3.0,",
    "+2026-09,monthly,Whole,TUIK,1.0,2.5,3.5,",
    "+2026-10,monthly,Whole,TUIK,4.0,5.0,9.0,",
    # a quarterly variant gains a period in the same commit
    "diff --git a/data/Türkiye_Vans.csv b/data/Türkiye_Vans.csv",
    "index 1..2 100644",
    "--- a/data/Türkiye_Vans.csv",
    "+++ b/data/Türkiye_Vans.csv",
    "@@ -9,0 +10 @@",
    "+2026-08,quarterly,Vans,TUIK,1.0,2.0,3.0,",
    # a legacy series is not news
    "diff --git a/data/Türkiye_legacy.csv b/data/Türkiye_legacy.csv",
    "--- a/data/Türkiye_legacy.csv",
    "+++ b/data/Türkiye_legacy.csv",
    "@@ -9,0 +10 @@",
    "+2020-01,monthly,legacy,X,1.0,2.0,3.0,",
    # a brand-new country with a backfilled history, merged as a PR
    "\x1eCOMMIT bbbb2222 2026-11-20T10:00:00+01:00 p2|feat: add Vietnam (#470)",
    "diff --git a/data/Vietnam.csv b/data/Vietnam.csv",
    "new file mode 100644",
    "--- /dev/null",
    "+++ b/data/Vietnam.csv",
    "@@ -0,0 +1,3 @@",
    f"+{H}",
    "+2024-01,monthly,Whole,VAMA,1.0,2.0,3.0,",
    "+2026-10,monthly,Whole,VAMA,1.0,2.0,3.0,",
    # a new fuel column fills every old row: a column, not a revision
    "\x1eCOMMIT cccc3333 2026-11-17T12:00:00Z p3|chore: update South Korea data from MOTIR",
    "diff --git a/data/South Korea.csv b/data/South Korea.csv",
    "--- a/data/South Korea.csv",
    "+++ b/data/South Korea.csv",
    "@@ -1,2 +1,2 @@",
    f"-{H}",
    "+period,time_interval,variant,source,BEV,FCEV,PETROL,TOTAL,notes",
    "-2026-09,monthly,Whole,MOTIR,1.0,2.0,3.0,",
    "+2026-09,monthly,Whole,MOTIR,1.0,0.0,2.0,3.0,",
    # a re-classification PR: only revisions, explained by its Release: line
    "\x1eCOMMIT dddd4444 2026-11-16T12:00:00Z p4|feat(fi): HEV for Finland (#461)",
    "diff --git a/data/Finland.csv b/data/Finland.csv",
    "--- a/data/Finland.csv",
    "+++ b/data/Finland.csv",
    "@@ -2 +2 @@",
    "-2014-01,monthly,Whole,S,1.0,2.0,3.0,",
    "+2014-01,monthly,Whole,S,1.0,1.5,3.0,",
    # the root / shallow boundary shows every file as created: skipped
    "\x1eCOMMIT eeee5555 2026-10-01T12:00:00Z |chore: render Croatia (HDV)",
    "diff --git a/data/Austria.csv b/data/Austria.csv",
    "new file mode 100644",
    "--- /dev/null",
    "+++ b/data/Austria.csv",
    "@@ -0,0 +1,2 @@",
    f"+{H}",
    "+2026-09,monthly,Whole,SA,1.0,2.0,3.0,",
    "",
])
META = {"Türkiye": {"flag": "🇹🇷", "slug": "turkiye"},
        "Vietnam": {"flag": "🇻🇳", "slug": "vietnam"}}
PRS = [{"number": 461, "title": "feat(fi): HEV", "mergedAt": "2026-11-16T12:05:00Z",
        "body": "Text.\n\nRelease: Finland's charts now show hybrids separately.\n"},
       {"number": 480, "title": "ci: no line", "mergedAt": "2026-11-18T12:00:00Z",
        "body": "Just CI.\n  Release: indented, not a release line"}]

feed = bu.build(60, [], LOG, PRS, META, today=date(2026, 11, 22))
E = feed["entries"]
by = {(e["type"], e.get("country") or e.get("pr")): e for e in E}

tr = by.get(("data", "Türkiye"), {})
check("new month headline on the headline series", tr.get("headline") == "Oct 2026 data")
check("variants listed headline first, labelled", tr.get("variants") == ["Whole", "Vans"]
      and tr.get("detail", "").startswith("Cars, Vans"))
check("revision counted in the detail", "1 earlier period revised" in tr.get("detail", ""))
check("source read from the data commit subject", tr.get("source") == "TÜİK")
check("flag and slug from schedule.json", tr.get("flag") == "🇹🇷" and tr.get("slug") == "turkiye")
check("legacy series ignored", "legacy" not in tr.get("variants", []))

vn = by.get(("data", "Vietnam"), {})
check("new file of the headline series is a new country", vn.get("kind") == "country")
check("new country shows its history span", "Jan 2024 to Oct 2026" in vn.get("detail", ""))
check("PR number kept from the squash subject", vn.get("pr") == 470)
check("date in UTC", vn.get("date") == "2026-11-20")

kr = by.get(("data", "South Korea"), {})
check("new column reported", kr.get("kind") == "fields" and kr.get("headline") == "FCEV added")
check("column fill not counted as revisions", "revised" not in kr.get("detail", ""))

check("revisions explained by a Release: line are folded into it",
      ("data", "Finland") not in by and ("site", 461) in by)
check("only lines starting with Release: count", ("site", 480) not in by)
check("root/shallow boundary commit skipped", ("data", "Austria") not in by)
check("newest first", [e["date"] for e in E] == sorted((e["date"] for e in E), reverse=True))

# Carry-over: older entries survive, site entries survive a gh outage.
prev = [{"type": "data", "kind": "data", "date": "2026-08-01", "time": "2026-08-01T00:00:00Z",
         "country": "Norway", "headline": "Jul 2026 data"},
        {"type": "site", "kind": "site", "date": "2026-11-10", "time": "2026-11-10T00:00:00Z",
         "pr": 414, "headline": "Fleet."}]
feed2 = bu.build(60, prev, LOG, None, META, today=date(2026, 11, 22))
keys = {(e["type"], e.get("country") or e.get("pr")) for e in feed2["entries"]}
check("entries older than the window are carried over", ("data", "Norway") in keys)
check("site entries kept when gh is unavailable", ("site", 414) in keys)
feed3 = bu.build(60, prev, LOG, [], META, today=date(2026, 11, 22))
keys3 = {(e["type"], e.get("country") or e.get("pr")) for e in feed3["entries"]}
check("a fresh gh answer replaces in-window site entries", ("site", 414) not in keys3)

check("quarterly and yearly periods read naturally",
      bu.pretty_period("2026-08", "quarterly") == "Q3 2026"
      and bu.pretty_period("2022-07", "yearly") == "2022"
      and bu.pretty_period("2026-10") == "Oct 2026")

# The committed feed parses and the home section reads it.
try:
    committed = json.loads((ROOT / "sources" / "updates.json").read_text(encoding="utf-8"))
    ok = isinstance(committed.get("entries"), list) and committed.get("generated")
except (OSError, ValueError):
    ok = False
check("sources/updates.json is valid", bool(ok))
HTML = (ROOT / "index.html").read_text(encoding="utf-8")
check("home has the Latest updates section", 'id="latestUpdates"' in HTML and ">Latest updates<" in HTML)
check("section reads sources/updates.json via location.href first",
      "new URL('sources/updates.json', location.href).href" in HTML)
check("section hides itself without a feed", "box.hidden=true" in HTML)
check("data rows link to Raw Data and the source page",
      "#rawdata?c='+encodeURIComponent(e.country)" in HTML and "sources/'+encodeURIComponent(e.slug)" in HTML)

print(f"{'FAILED' if fails else 'passed'}: {len(fails)} failure(s)")
sys.exit(1 if fails else 0)
