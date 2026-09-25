#!/usr/bin/env python3
"""
Fetch South Korea's monthly domestic sales by powertrain from the Ministry of
Trade, Industry and Resources' «자동차산업 동향» (automotive industry trends)
press release and upsert data/South Korea.csv (variant Whole).

Source
------
MOTIR (산업통상부, formerly MOTIE) publishes one press release per month on
its board «보도·참고자료», usually between the 13th and the 20th of M+1, with
a PDF attachment. Two tables in the PDF are used:

  표 3  «자동차 생산, 내수, 수출량»  → 내수 판매량  (domestic sales, all
        vehicle types, domestic makers + imports)                  → TOTAL
  참고 2 «친환경차 차종별 내수 판매 현황» (eco-friendly cars by type):
        하이브리드 → HEV · 전기차 → BEV · 플러그인 하이브리드 → PHEV ·
        수소차 → OTHERS (hydrogen FCEV)
  ICE = TOTAL − 친환경차 내수 (no petrol/diesel split is published)

The ministry's own footnote names the underlying data: KAMA (한국자동차
모빌리티산업협회, domestic makers) and KAIDA (한국수입자동차협회, imports,
whose hybrid figure **includes mild hybrids**).

Every table has three monthly columns — the same month a year earlier, the
previous month and the current month — whose labels are read from the table
header, never from the release title (quarterly and half-year releases are
titled «1분기», «상반기 및 6월»). A month with no release of its own on the
board (2026-07, as of 2026-09-25) is filled from the next release's
previous-month column. The current and the previous month are written; the
previous month is the ministry's revised figure (MOTIR revises it in the
following release, e.g. 2026-05 BEV 35,416 → 35,455). The year-earlier
column is only compared with the CSV and reported — history is not
rewritten (invariant 3).

Row source string `motir.go.kr` — the same as the hand-entered rows
2017-01 → 2026-06, which come from these releases. The cross-check of
every release in the current PDF format (2025 →) against those rows found
them equal to MOTIR's revised figures, except two transcription errors
that the backfill corrected (2025-09, 2026-04) —
docs/architecture/43-source-south-korea.md §5.

Governance (every real run)
---------------------------
* the release list must parse and the target release must have a PDF;
* the eco table's header must yield exactly the three expected months
  (current, current−1, current−12);
* 하이브리드 + 전기차 + 플러그인 + 수소차 must equal 친환경차 내수 (±2);
* 내수 판매량 (표 3) must equal 내 수 (참고 1) when both are present;
* ICE = TOTAL − eco must be ≥ 0;
* a month below 25 % of the trailing-12 median TOTAL is not written
  (--force overrides);
* the year-earlier column and the previous-month revision are compared with
  the CSV and listed in the step summary.

Usage
-----
    python scripts/fetch_south_korea.py                 # newest release(s)
    python scripts/fetch_south_korea.py --releases 12   # re-read 12 releases
    python scripts/fetch_south_korea.py --pdf FILE ...  # offline, local PDFs
"""

from __future__ import annotations

import argparse
import csv
import html
import io
import json
import os
import re
import sys
import time
from pathlib import Path

import requests

SOURCE = "motir.go.kr"
BASE = "https://www.motir.go.kr"
LIST_URL = (BASE + "/kor/article/ATCL3f49a5a8c?searchCondition=1&searchKeyword="
            "%EC%9E%90%EB%8F%99%EC%B0%A8%EC%82%B0%EC%97%85+%EB%8F%99%ED%96%A5&pageIndex={page}")
CSV_PATH = Path(__file__).resolve().parent.parent / "data" / "South Korea.csv"
FUELS = ["BEV", "PHEV", "HEV", "OTHERS", "ICE"]
CSV_COLUMNS = ["period", "time_interval", "variant", "source"] + FUELS + ["TOTAL", "notes"]

# 참고 2 row labels → gallery column (the export table below it uses the same
# labels, so parsing stops at the first footnote line after the domestic table).
ECO_ROWS = {"하이브리드": "HEV", "전기차": "BEV", "플러그인 하이브리드": "PHEV", "수소차": "OTHERS"}
SUM_TOLERANCE = 2
MIN_MONTH_FRACTION = 0.25

HTTP_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like "
                   "Gecko) Chrome/124 Safari/537.36 LeRaffl-Gallery/1.0"),
}


# ── PDF text → numbers ─────────────────────────────────────────────────────

NUM = r"(\d{1,3}(?:,\d{3})+|\d+)"
MONTH_LABEL = re.compile(r"[‘'’]?(\d{2})\.\s?(\d{1,2})월")


def to_int(s: str) -> int:
    return int(s.replace(",", ""))


def month_add(period: str, k: int) -> str:
    y, m = int(period[:4]), int(period[5:7])
    m += k
    while m < 1:
        y, m = y - 1, m + 12
    while m > 12:
        y, m = y + 1, m - 12
    return f"{y:04d}-{m:02d}"


def header_months(line: str) -> list[str]:
    """'구 분 ‘25.8월 '26.7월 '26.8월 '25.1∼8월 …' → ['2025-08', '2026-07', '2026-08']."""
    out = []
    for yy, mm in MONTH_LABEL.findall(line):
        out.append(f"20{yy}-{int(mm):02d}")
        if len(out) == 3:
            break
    return out


class ParseError(Exception):
    pass


def parse_release(text: str) -> dict:
    """Parse one release's text. Returns
    {"months": [yoy, prev, cur], "total": [..3], "eco": [..3],
     "parts": {col: [..3]}, "total_ref1": [..3] | None}."""
    lines = [l.strip() for l in text.splitlines()]

    # 참고 2 domestic eco table: the line «친환경차 내수 N N N …»
    eco_i = next((i for i, l in enumerate(lines)
                  if re.match(rf"친환경차 내수(?: 판매량)? {NUM} {NUM} {NUM}\b", l)), None)
    if eco_i is None:
        raise ParseError("eco-car domestic table (친환경차 내수 …) not found")
    hdr_i = next((i for i in range(eco_i, max(eco_i - 12, -1), -1)
                  if lines[i].startswith("구 분") and len(header_months(lines[i])) == 3), None)
    if hdr_i is None:
        raise ParseError("no «구 분» header with three month labels above the eco table")
    months = header_months(lines[hdr_i])
    eco = [to_int(x) for x in re.match(rf"친환경차 내수(?: 판매량)? {NUM} {NUM} {NUM}", lines[eco_i]).groups()]

    parts: dict[str, list[int]] = {}
    for l in lines[eco_i + 1: eco_i + 10]:
        if l.startswith("*") or l.startswith("□"):
            break
        for label, col in ECO_ROWS.items():
            m = re.match(rf"{label} {NUM} {NUM} {NUM}\b", l)
            if m and col not in parts:
                parts[col] = [to_int(x) for x in m.groups()]
    missing = [c for c in ECO_ROWS.values() if c not in parts]
    if missing:
        raise ParseError(f"eco table rows missing: {missing}")

    # 표 3 total domestic sales; 참고 1 «내 수» as a consistency reference
    tot = next((re.match(rf"내수 판매량 {NUM} {NUM} {NUM}\b", l) for l in lines
                if re.match(rf"내수 판매량 {NUM} {NUM} {NUM}\b", l)), None)
    ref = next((re.match(rf"내 수 {NUM} {NUM} {NUM}\b", l) for l in lines
                if re.match(rf"내 수 {NUM} {NUM} {NUM}\b", l)), None)
    if tot is None and ref is None:
        raise ParseError("total domestic sales (내수 판매량 / 내 수) not found")
    total = [to_int(x) for x in (tot or ref).groups()]
    total_ref1 = [to_int(x) for x in ref.groups()] if (tot and ref) else None
    return {"months": months, "total": total, "eco": eco, "parts": parts,
            "total_ref1": total_ref1}


def rows_of(parsed: dict) -> dict[str, dict[str, int]]:
    """{period: counts} for the three columns of one release (validated)."""
    months = parsed["months"]
    yoy, prev, cur = months
    if prev != month_add(cur, -1) or yoy != month_add(cur, -12):
        raise ParseError(f"header months {months} are not (cur−12, cur−1, cur)")
    if parsed["total_ref1"] and parsed["total_ref1"] != parsed["total"]:
        raise ParseError(f"내수 판매량 {parsed['total']} ≠ 내 수 {parsed['total_ref1']}")
    out = {}
    for k, p in enumerate(months):
        c = {col: parsed["parts"][col][k] for col in ECO_ROWS.values()}
        eco_sum = sum(c.values())
        if abs(eco_sum - parsed["eco"][k]) > SUM_TOLERANCE:
            raise ParseError(f"{p}: eco parts sum {eco_sum} ≠ 친환경차 내수 {parsed['eco'][k]}")
        total = parsed["total"][k]
        ice = total - parsed["eco"][k]
        if ice < 0:
            raise ParseError(f"{p}: ICE would be negative ({total} − {parsed['eco'][k]})")
        c["ICE"] = ice
        c["TOTAL"] = total
        out[p] = c
    return out


def pdf_text(data: bytes) -> str:
    import pdfplumber
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        return "\n".join((pg.extract_text() or "") for pg in pdf.pages)


# ── discovery / download ───────────────────────────────────────────────────

def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HTTP_HEADERS)
    return s


def get(session, url, **kw) -> requests.Response:
    """MOTIR sometimes drops connections from datacenter IPs; retry politely."""
    last = None
    for attempt in range(5):
        try:
            r = session.get(url, timeout=90, **kw)
            r.raise_for_status()
            return r
        except requests.RequestException as e:
            last = e
            time.sleep(5 * (attempt + 1))
    raise SystemExit(f"{url}: {last}")


def list_releases(session, pages: int = 2) -> list[tuple[str, str]]:
    """[(title, view path)] newest first, «자동차산업 동향» releases only."""
    seen: dict[str, str] = {}
    for page in range(1, pages + 1):
        s = get(session, LIST_URL.format(page=page)).text
        for m in re.finditer(r'<a[^>]+href="([^"]*/view[^"]*)"[^>]*>(.*?)</a>', s, re.S):
            t = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", m.group(2)))).strip()
            if "자동차산업" in t and "동향" in t and m.group(1) not in seen:
                seen[m.group(1)] = t
        time.sleep(1)
    if not seen:
        raise SystemExit("No «자동차산업 동향» release on the MOTIR list — layout changed? Not writing.")
    return [(t, h) for h, t in seen.items()]


def release_pdf(session, view_path: str) -> tuple[str, bytes]:
    """(file name, bytes) of the release's PDF attachment."""
    s = get(session, BASE + view_path).text
    links = re.findall(r'href="(/attach/down/[^"]+)"', s)
    names = re.findall(r"([^<>\"]+?\.(?:pdf|hwpx?|hwp))\s*\[", html.unescape(s))
    for link, name in zip(links, names):
        if name.lower().endswith(".pdf"):
            r = get(session, BASE + link, headers={"Referer": BASE + view_path})
            if not r.content.startswith(b"%PDF"):
                raise SystemExit(f"{name}: attachment is not a PDF — not writing.")
            return name.strip(), r.content
    raise SystemExit(f"{view_path}: no PDF attachment (names: {names}) — not writing.")


# ── CSV line-level upsert (invariant 2) ────────────────────────────────────

def fmt(v: int) -> str:
    return f"{float(v):.1f}"


def render_line(period: str, counts: dict[str, int], notes: str = "") -> str:
    buf = io.StringIO()
    csv.writer(buf, lineterminator="").writerow(
        [period, "monthly", "Whole", SOURCE] + [fmt(counts[k]) for k in FUELS + ["TOTAL"]] + [notes])
    return buf.getvalue()


def read_lines(path: Path) -> tuple[str, list[str]]:
    # Split on "\n" only: the 2017-04 row's source URL holds mojibake with a
    # U+0085 (NEL), which str.splitlines() would treat as a line break.
    lines = path.read_text(encoding="utf-8").rstrip("\n").split("\n")
    return lines[0], lines[1:]


def key_of(line: str) -> tuple[str, str]:
    f = next(csv.reader([line]))
    return f[0], f[2]


def upsert(path: Path, updates: dict[str, str], force: bool) -> dict[str, int]:
    header, lines = read_lines(path)
    if header.split(",") != CSV_COLUMNS:
        sys.exit(f"{path}: unexpected header {header!r}")
    stats = {"added": 0, "updated": 0, "unchanged": 0, "skipped": 0}
    index = {key_of(l): i for i, l in enumerate(lines)}
    for period, new in sorted(updates.items()):
        k = (period, "Whole")
        if k in index:
            old = lines[index[k]]
            old_f, new_f = next(csv.reader([old])), next(csv.reader([new]))
            same = (old_f[3] == new_f[3]
                    and all(float(a or 0) == float(b or 0) for a, b in zip(old_f[4:10], new_f[4:10])))
            if same:
                stats["unchanged"] += 1          # numerically equal: keep the line byte-for-byte
            elif old_f[3] != SOURCE and not force:
                stats["skipped"] += 1
            else:
                lines[index[k]] = new
                stats["updated"] += 1
        else:
            lines.append(new)
            stats["added"] += 1
    if stats["added"]:
        lines.sort(key=key_of)
    if stats["added"] or stats["updated"]:
        path.write_text("\n".join([header] + lines) + "\n", encoding="utf-8")
    return stats


def existing(path: Path) -> dict[str, dict[str, str]]:
    with open(path, newline="", encoding="utf-8") as f:
        return {r["period"]: r for r in csv.DictReader(f) if r["variant"] == "Whole"}


def differs(a: dict[str, int], row: dict[str, str]) -> list[str]:
    out = []
    for k in FUELS + ["TOTAL"]:
        v = float(row.get(k) or 0)
        if abs(v - a[k]) > 0.5:
            out.append(f"{k} {v:,.0f}→{a[k]:,}")
    return out


def median_fraction(period: str, total: int, have: dict[str, dict]) -> float | None:
    prior = sorted(p for p in have if p < period)[-12:]
    if len(prior) < 6:
        return None
    vals = sorted(float(have[p]["TOTAL"]) for p in prior)
    med = vals[len(vals) // 2]
    return total / med if med else None


# ── main ───────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--releases", type=int, default=3,
                    help="How many of the newest releases to read (default 3 — the "
                         "newest plus two earlier ones, which fills a skipped month).")
    ap.add_argument("--pdf", nargs="*", default=[],
                    help="Offline: parse these local PDFs instead of downloading.")
    ap.add_argument("--force", action="store_true",
                    help="Ignore the self-throttle, the completeness guard and foreign rows.")
    ap.add_argument("--dry-run", action="store_true", help="Parse and report; write nothing.")
    ap.add_argument("--github-output", default=os.environ.get("GITHUB_OUTPUT"))
    ap.add_argument("--step-summary", default=os.environ.get("GITHUB_STEP_SUMMARY"))
    args = ap.parse_args()

    have = existing(CSV_PATH)
    releases: list[tuple[str, str]] = []            # (label, text)
    if args.pdf:
        for f in args.pdf:
            releases.append((Path(f).name, pdf_text(Path(f).read_bytes())))
    else:
        session = make_session()
        listed = list_releases(session)
        print("Newest releases:", [t for t, _ in listed[:6]])
        for title, path in listed[:max(1, args.releases)]:
            name, data = release_pdf(session, path)
            releases.append((f"{title} — {name}", pdf_text(data)))
            time.sleep(1)

    # Oldest release first, so the newest publication of a month wins.
    parsed = []
    for label, text in releases:
        try:
            p = parse_release(text)
            rows = rows_of(p)
        except ParseError as e:
            sys.exit(f"{label}: {e} — schema drift, not writing.")
        parsed.append((label, p["months"], rows))
    parsed.sort(key=lambda x: x[1][2])
    target = parsed[-1][1][2]
    print("Parsed:", [(lbl[:30], m) for lbl, m, _ in parsed])

    if (not args.force and not args.pdf and have.get(target, {}).get("source") == SOURCE
            and not differs(parsed[-1][2][target], have[target])
            and not differs(parsed[-1][2][month_add(target, -1)],
                            have.get(month_add(target, -1), {}))):
        print(f"{target} already in the CSV from {SOURCE}, previous month unchanged; nothing to do.")
        return emit(args, False)

    writes: dict[str, dict[str, int]] = {}
    checks: list[str] = []
    for label, months, rows in parsed:
        yoy, prev, cur = months
        writes[cur] = rows[cur]
        writes[prev] = rows[prev]                    # MOTIR's revised previous month
        if yoy in have:
            d = differs(rows[yoy], have[yoy])
            checks.append(f"- {yoy} (year-earlier column of {cur}): "
                          + ("matches the CSV" if not d else "differs: " + ", ".join(d)))

    frac = median_fraction(target, writes[target]["TOTAL"], have)
    if frac is not None and frac < MIN_MONTH_FRACTION and not args.force:
        sys.exit(f"{target}: TOTAL {writes[target]['TOTAL']:,} is {frac:.0%} of the trailing "
                 "median — looks wrong; not writing (--force overrides).")

    revisions = []
    for p, c in sorted(writes.items()):
        if p in have:
            d = differs(c, have[p])
            if d:
                revisions.append(f"- {p}: " + ", ".join(d))

    report = [f"## South Korea (MOTIR «자동차산업 동향») — newest month {target}\n",
              "| period | BEV | PHEV | HEV | H2 (OTHERS) | ICE | TOTAL | BEV share |",
              "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for p, c in sorted(writes.items()):
        report.append(f"| {p} | " + " | ".join(f"{c[k]:,}" for k in FUELS + ["TOTAL"])
                      + f" | {c['BEV'] / c['TOTAL']:.1%} |")
    report += ["\n### Changes against the CSV (new months, MOTIR revisions)\n",
               "\n".join(revisions) or "None — every written month equals the CSV.",
               "\n### Cross-check: year-earlier columns vs the CSV (not written)\n",
               "\n".join(checks) or "—"]
    rep = "\n".join(report) + "\n"
    print(rep)
    if args.step_summary:
        with open(args.step_summary, "a", encoding="utf-8") as fh:
            fh.write(rep)
    if args.dry_run:
        return emit(args, False)

    stats = upsert(CSV_PATH, {p: render_line(p, c) for p, c in writes.items()}, args.force)
    print(f"{CSV_PATH.name}: {stats}")
    return emit(args, bool(stats["added"] or stats["updated"]))


def emit(args, changed: bool) -> int:
    if args.github_output:
        with open(args.github_output, "a", encoding="utf-8") as f:
            f.write(f"changed={'true' if changed else 'false'}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
