#!/usr/bin/env python3
"""Build sources/updates.json, the "Latest updates" feed on the home page.

Content updates only, never renders. Two inputs, both already in the repo's
history, so nothing is maintained by hand:

* Data: every first-parent commit that touched data/<Country>[_<Variant>].csv
  in the last --days days. The CSVs are written as line-level upserts keyed on
  (period, variant) (R/upsert.R), so a commit's diff says exactly what changed:
  a key only on the + side is a new period, a key on both sides a revised one,
  a new file a new country or variant, a changed header a new fuel column.
* Site: the "Release:" line of every pull request merged in the window, the
  same line the monthly release note uses (scripts/build_release_note.py,
  AGENTS.md "Conventions"). Read with gh; without gh or a token this half is
  carried over from the previous feed instead of being dropped.

Entries older than the window are carried over from the previous feed, so a
shallow checkout never empties it. docs/architecture/66-latest-updates.md.

    python3 scripts/build_updates.py            # writes sources/updates.json
    python3 scripts/build_updates.py --stdout   # print, write nothing
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "sources" / "updates.json"
SCHEDULE = ROOT / "sources" / "schedule.json"
REPO = "LeRaffl/LeRaffl-Gallery"
MAX_ENTRIES = 80
BULK_COUNTRIES = 3

# Series that are not shown anywhere in the gallery (frozen pre-definition
# histories) are not news.
SKIP_VARIANTS = {"legacy"}

VARIANT_LABEL = {
    "Whole": "Cars",
    "HDV": "Trucks",
    "NonRental": "Non-rental",
    "2-Wheelers": "Two-wheelers",
    "4-Wheelers": "Four-wheelers",
}
# Order in which variants are listed: the headline series first.
VARIANT_ORDER = ["Whole", "Private", "Industry", "Used", "Rental", "NonRental",
                 "Resale", "Wholesale", "Vans", "Pickups", "HDV", "Buses"]
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
META_COLS = {"period", "time_interval", "variant", "source", "notes"}
KIND_RANK = {"country": 0, "series": 1, "data": 2, "fields": 3, "revised": 4}


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------
def split_name(stem: str) -> tuple[str, str]:
    """data/<Country>[_<Variant>].csv -> (country, variant)."""
    if "_" in stem:
        country, variant = stem.split("_", 1)
        return country, variant
    return stem, "Whole"


def variant_label(v: str) -> str:
    return VARIANT_LABEL.get(v, v)


def variant_sort_key(v: str):
    return (VARIANT_ORDER.index(v) if v in VARIANT_ORDER else len(VARIANT_ORDER), v)


def pretty_period(period: str, interval: str = "monthly") -> str:
    m = re.fullmatch(r"(\d{4})-(\d{2})", period or "")
    if not m:
        return period or ""
    year, mon = m.group(1), int(m.group(2))
    if interval == "quarterly":
        return f"Q{(mon - 1) // 3 + 1} {year}"
    if interval in ("yearly", "annual"):
        return year
    return f"{MONTHS[mon - 1]} {year}"


def source_from_subject(subject: str) -> str:
    """'chore: update Türkiye data from TÜİK' -> 'TÜİK'."""
    m = re.match(r"chore: update .+? data from (.+)$", subject or "")
    return m.group(1).strip() if m else ""


def pr_from_subject(subject: str) -> int | None:
    m = re.search(r"\(#(\d+)\)\s*$", subject or "") or \
        re.match(r"Merge pull request #(\d+)", subject or "")
    return int(m.group(1)) if m else None


def parse_row(line: str) -> list[str]:
    try:
        return next(csv.reader(io.StringIO(line)))
    except (StopIteration, csv.Error):
        return []


# --------------------------------------------------------------------------
# diff parsing
# --------------------------------------------------------------------------
class FileChange:
    def __init__(self, path: str):
        self.path = path
        self.created = False
        self.deleted = False
        self.added: dict[tuple[str, str], str] = {}     # key -> interval
        self.removed: set[tuple[str, str]] = set()
        self.old_header: list[str] = []
        self.new_header: list[str] = []

    @property
    def stem(self) -> str:
        return Path(self.path).stem

    def new_periods(self) -> list[tuple[str, str]]:
        return sorted((k[0], iv) for k, iv in self.added.items() if k not in self.removed)

    def revised(self) -> int:
        return sum(1 for k in self.added if k in self.removed)

    def new_columns(self) -> list[str]:
        if not self.new_header or not self.old_header or self.created:
            return []
        old = set(self.old_header)
        return [c for c in self.new_header if c not in old and c not in META_COLS]


def parse_diff(text: str) -> list[dict]:
    """Parse `git log -p -U0` output into commits with per-file changes.

    Each commit starts with a line '\\x1eCOMMIT <sha> <iso-date> <parents>|<subject>'.
    A commit without parents (the root, or the boundary of a shallow clone)
    shows every file as new, so it is marked and later skipped.
    """
    commits: list[dict] = []
    cur = None
    fc: FileChange | None = None
    for raw in text.split("\n"):
        if raw.startswith("\x1eCOMMIT "):
            head, _, subject = raw[len("\x1eCOMMIT "):].partition("|")
            parts = head.split(" ", 2)
            cur = {"sha": parts[0], "date": parts[1] if len(parts) > 1 else "",
                   "root": len(parts) < 3 or not parts[2].strip(),
                   "subject": subject, "files": []}
            commits.append(cur)
            fc = None
            continue
        if cur is None:
            continue
        if raw.startswith("diff --git "):
            m = re.match(r'diff --git "?a/(.+?)"? "?b/(.+?)"?$', raw)
            path = m.group(2) if m else raw.split(" b/", 1)[-1]
            fc = FileChange(path)
            cur["files"].append(fc)
            continue
        if fc is None:
            continue
        if raw.startswith("new file mode"):
            fc.created = True
        elif raw.startswith("deleted file mode"):
            fc.deleted = True
        elif raw.startswith("+++ ") or raw.startswith("--- ") or raw.startswith("@@"):
            continue
        elif raw.startswith("+") or raw.startswith("-"):
            row = parse_row(raw[1:])
            if not row:
                continue
            if row[0] == "period":
                (fc.new_header if raw[0] == "+" else fc.old_header)[:] = row
                continue
            if len(row) < 3 or not re.fullmatch(r"\d{4}-\d{2}", row[0]):
                continue
            key = (row[0], row[2])
            if raw[0] == "+":
                fc.added[key] = row[1]
            else:
                fc.removed.add(key)
    return commits


# --------------------------------------------------------------------------
# entries
# --------------------------------------------------------------------------
def load_schedule(path: Path = SCHEDULE) -> dict[str, dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {c["country"]: c for c in data.get("countries", []) if c.get("country")}


def collect(commits: list[dict]) -> dict[tuple[str, str], dict]:
    """Aggregate commits into one bucket per (UTC day, country)."""
    buckets: dict[tuple[str, str], dict] = {}
    for c in commits:
        if c.get("root"):
            continue
        # A commit that creates the headline file of many countries at once
        # is a bulk import or a restructure, not news about each of them.
        created = {split_name(f.stem)[0] for f in c["files"]
                   if f.created and split_name(f.stem)[1] == "Whole"}
        bulk = len(created) > BULK_COUNTRIES
        try:
            when = datetime.fromisoformat(c["date"].replace("Z", "+00:00"))
        except ValueError:
            continue
        day = when.astimezone(timezone.utc).date().isoformat()
        src = source_from_subject(c["subject"])
        pr = pr_from_subject(c["subject"])
        for fc in c["files"]:
            p = Path(fc.path)
            if p.parent.as_posix() != "data" or p.suffix != ".csv" or fc.deleted:
                continue
            country, variant = split_name(fc.stem)
            if variant in SKIP_VARIANTS:
                continue
            b = buckets.setdefault((day, country), {
                "date": day, "country": country, "new_country": False,
                "new_variants": set(), "periods": {}, "revised": set(),
                "fields": set(), "sources": [], "prs": [], "commits": [],
                "time": "",
            })
            b["time"] = max(b["time"], c["date"])
            if c["sha"] not in b["commits"]:
                b["commits"].append(c["sha"])
            if src and src not in b["sources"]:
                b["sources"].append(src)
            if pr and pr not in b["prs"]:
                b["prs"].append(pr)
            if fc.created and not bulk:
                if variant == "Whole":
                    b["new_country"] = True
                else:
                    b["new_variants"].add(variant)
            new = fc.new_periods()
            if new:
                b["periods"].setdefault(variant, []).extend(new)
            if fc.revised():
                b["revised"].update(k for k in fc.added if k in fc.removed)
            b["fields"].update(fc.new_columns())
    return buckets


def describe(b: dict, meta: dict) -> dict | None:
    periods = b["periods"]
    variants = sorted(set(periods) | b["new_variants"], key=variant_sort_key)
    newest_by_v = {v: max(periods[v]) for v in periods}
    n_new = sum(len(set(p for p, _ in v)) for v in periods.values())
    revised = len(b["revised"])
    fields = sorted(b["fields"])

    if b["new_country"]:
        kind = "country"
        headline = "New country"
    elif b["new_variants"]:
        kind = "series"
        names = ", ".join(variant_label(v) for v in sorted(b["new_variants"], key=variant_sort_key))
        headline = f"New series: {names}"
    elif periods:
        kind = "data"
        # Headline on the newest period added to the headline series if it
        # moved, else to whichever series moved furthest.
        pick = newest_by_v.get("Whole") or max(newest_by_v.values())
        headline = f"{pretty_period(*pick)} data"
    elif fields:
        kind = "fields"
        headline = f"{' and '.join(fields)} added"
    elif revised:
        kind = "revised"
        headline = "Figures revised"
    else:
        return None

    bits = []
    if variants and kind != "series":
        bits.append(", ".join(variant_label(v) for v in variants))
    # History backfills (many periods at once) read as a range, not a month.
    span_periods = sorted({p for v in periods.values() for p, _ in v})
    if kind in ("country", "series") and span_periods:
        bits.append(f"{pretty_period(span_periods[0])} to {pretty_period(span_periods[-1])}")
    elif kind == "data" and n_new > 3 and len(span_periods) > 1:
        bits.append(f"history back to {pretty_period(span_periods[0])}")
    if fields and kind != "fields":
        bits.append(f"{' and '.join(fields)} added")
    # A new column fills every old row too; that is the column, not a revision.
    if revised and kind != "revised" and not fields:
        bits.append(f"{revised} earlier {'period' if revised == 1 else 'periods'} revised")
    elif kind == "revised":
        bits.append(f"{revised} {'period' if revised == 1 else 'periods'}")

    m = meta.get(b["country"], {})
    entry = {
        "date": b["date"],
        "time": b["time"],
        "type": "data",
        "kind": kind,
        "country": b["country"],
        "flag": m.get("flag", ""),
        "slug": m.get("slug", ""),
        "headline": headline,
        "detail": " · ".join(bits),
        "variants": variants,
        "source": " + ".join(b["sources"]),
        "commit": b["commits"][0][:12] if b["commits"] else "",
    }
    if b["prs"]:
        entry["pr"] = b["prs"][0]
    return entry


def data_entries(commits: list[dict], meta: dict) -> list[dict]:
    out = []
    for b in collect(commits).values():
        e = describe(b, meta)
        if e:
            out.append(e)
    return out


def release_lines(body: str) -> list[str]:
    out = []
    for line in (body or "").splitlines():
        if line.startswith("Release:"):
            text = line.split(":", 1)[1].strip()
            if text:
                out.append(text)
    return out


def site_entries(prs: list[dict]) -> list[dict]:
    out = []
    for pr in prs:
        merged = pr.get("mergedAt") or ""
        for text in release_lines(pr.get("body") or ""):
            out.append({
                "date": merged[:10],
                "time": merged,
                "type": "site",
                "kind": "site",
                "headline": text,
                "title": pr.get("title", ""),
                "pr": pr.get("number"),
            })
    return out


# --------------------------------------------------------------------------
# I/O
# --------------------------------------------------------------------------
def git_log(days: int, root: Path = ROOT) -> str:
    since = (date.today() - timedelta(days=days)).isoformat()
    return subprocess.run(
        ["git", "-c", "core.quotepath=off", "log", "--first-parent",
         "--diff-merges=first-parent", f"--since={since}", "-p", "-U0",
         "--no-color", "--no-renames", "--format=%x1eCOMMIT %H %cI %P|%s",
         "--", "data/*.csv"],
        cwd=root, check=True, capture_output=True, text=True,
    ).stdout


def gh_prs(days: int, repo: str = REPO) -> list[dict] | None:
    since = (date.today() - timedelta(days=days)).isoformat()
    try:
        raw = subprocess.run(
            ["gh", "pr", "list", "-R", repo, "--state", "merged", "--limit", "200",
             "--search", f"merged:>={since}", "--json", "number,title,body,mergedAt"],
            check=True, capture_output=True, text=True, timeout=120,
        ).stdout
        return json.loads(raw)
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        print(f"[updates] gh unavailable, keeping previous site entries: {exc}", file=sys.stderr)
        return None


def entry_key(e: dict) -> tuple:
    if e.get("type") == "site":
        return ("site", e.get("pr"), e.get("headline"))
    return ("data", e.get("date"), e.get("country"))


def merge(fresh: list[dict], previous: list[dict], window_start: str,
          site_fresh: bool) -> list[dict]:
    """Fresh entries win inside the window; older ones are carried over."""
    out = {entry_key(e): e for e in fresh}
    for e in previous:
        k = entry_key(e)
        if k in out:
            continue
        older = (e.get("date") or "") < window_start
        if older or (e.get("type") == "site" and not site_fresh):
            out[k] = e
    # A re-classification merged as a pull request ("HEV for Finland") shows
    # up as thousands of revised rows; its Release: line already says it
    # better, so the bare data entry is dropped.
    explained = {e.get("pr") for e in out.values() if e.get("type") == "site"}
    entries = [e for e in out.values()
               if not (e.get("type") == "data" and e.get("kind") in ("revised", "fields")
                       and e.get("pr") in explained)]
    entries.sort(key=lambda e: (e.get("time") or e.get("date") or "",
                                -KIND_RANK.get(e.get("kind"), 9)), reverse=True)
    return entries[:MAX_ENTRIES]


def build(days: int, previous: list[dict], log_text: str, prs: list[dict] | None,
          meta: dict, today: date | None = None) -> dict:
    today = today or date.today()
    window_start = (today - timedelta(days=days)).isoformat()
    fresh = data_entries(parse_diff(log_text), meta)
    if prs is not None:
        fresh += site_entries(prs)
    return {
        "generated": today.isoformat(),
        "window_days": days,
        "entries": merge(fresh, previous, window_start, prs is not None),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--days", type=int, default=60)
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--no-gh", action="store_true", help="skip the Release: lines")
    ap.add_argument("--stdout", action="store_true")
    args = ap.parse_args(argv)

    out = Path(args.out)
    try:
        previous = json.loads(out.read_text(encoding="utf-8")).get("entries", [])
    except (OSError, ValueError):
        previous = []
    prs = None if args.no_gh else gh_prs(args.days)
    feed = build(args.days, previous, git_log(args.days), prs, load_schedule())
    text = json.dumps(feed, ensure_ascii=False, indent=1) + "\n"
    if args.stdout:
        sys.stdout.write(text)
    else:
        out.write_text(text, encoding="utf-8")
        print(f"[updates] {len(feed['entries'])} entries -> {out.relative_to(ROOT) if out.is_relative_to(ROOT) else out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
