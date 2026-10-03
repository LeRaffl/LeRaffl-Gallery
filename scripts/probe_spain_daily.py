#!/usr/bin/env python3
"""
TEMPORARY probe — remove once the daily-file decision is made.

Question: can the sum of DGT's daily matriculaciones files
(export_mat_YYYYMMDD.zip) stand in for the monthly file
(export_mensual_mat_YYYYMM.zip) on the 1st/2nd of the following month?

For each probed month it:
  * GETs every daily file of the month plus the first days of the next one
    (status, size, Last-Modified, record count, record lengths);
  * reads the FEC_MATRICULA month mix per daily file (cut-off drift);
  * aggregates every variant with fetch_spain's own logic over
      (a) all daily files of the month,
      (b) the same filtered to FEC_MATRICULA in-month, plus in-month records
          from the next month's first daily files,
    and diffs both against the monthly file per variant and fuel;
  * diffs the top brands/models (Whole) daily-sum vs monthly.

Also lists which daily files of the newest month exist right now, with
Last-Modified, to see how fast DGT publishes them.
"""
from __future__ import annotations

import calendar
import collections
import io
import json
import os
import sys
import zipfile
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fetch_spain as fs  # noqa: E402

DAILY_TPL = ("https://www.dgt.es/microdatos/salida/{y}/{m}/vehiculos/"
             "matriculaciones/export_mat_{ymd}.zip")
SL_FEC = fs._slice("FEC_MATRICULA")
VARIANTS = list(fs.VARIANT_CONFIG)
NEXT_DAYS = 5


def get_daily(session, d: date):
    url = DAILY_TPL.format(y=d.year, m=d.month, ymd=d.strftime("%Y%m%d"))
    r = session.get(url, timeout=180)
    info = {"date": d.isoformat(), "dow": d.strftime("%a"),
            "status": r.status_code, "bytes": len(r.content),
            "last_modified": r.headers.get("Last-Modified")}
    if r.status_code != 200 or len(r.content) < 100:
        return info, None
    try:
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            names = [n for n in z.namelist() if n.lower().endswith(".txt")]
            info["zip_names"] = z.namelist()
            if not names:
                return info, None
            return info, z.read(names[0])
    except zipfile.BadZipFile:
        info["bad_zip"] = True
        return info, None


def records(txt: bytes):
    stream = io.TextIOWrapper(io.BytesIO(txt), encoding="latin-1")
    for i, line in enumerate(stream):
        if i == 0 and not line[:1].isdigit():
            continue
        line = line.rstrip("\r\n")
        if line.strip():
            yield line


def fec_month(line: str) -> str:
    """FEC_MATRICULA -> YYYY-MM; DDMMYYYY or YYYYMMDD, whichever parses."""
    s = line[SL_FEC[0]:SL_FEC[1]]
    if s[4:8].isdigit() and 1900 < int(s[4:8]) < 2100:      # DDMMYYYY
        return f"{s[4:8]}-{s[2:4]}"
    if s[:4].isdigit() and 1900 < int(s[:4]) < 2100:        # YYYYMMDD
        return f"{s[:4]}-{s[4:6]}"
    return "??"


def empty_counts():
    return {v: collections.Counter() for v in VARIANTS}


def add(counts, line):
    if len(line) != fs.RECORD_LEN:
        return
    mem = fs.record_variants(line)
    if not mem:
        return
    fuel = fs.classify_fuel(line)
    for v in mem:
        counts[v][fuel] += 1
        counts[v]["TOTAL"] += 1


def model_key(line):
    brand = fs.market_top.clean(line[fs.SL_MARCA[0]:fs.SL_MARCA[1]])
    model = fs.market_top.strip_brand(
        brand, fs.market_top.clean(line[fs.SL_MODELO[0]:fs.SL_MODELO[1]]))
    return (fs.classify_fuel(line), brand, model)


def diff_table(label, got, ref):
    print(f"\n### {label}")
    print(f"{'variant':<11}{'fuel':<8}{'daily':>9}{'monthly':>9}"
          f"{'diff':>8}{'rel%':>8}")
    worst = 0.0
    for v in VARIANTS:
        for k in fs.FUEL_COLUMNS + ["TOTAL"]:
            g, r = got[v][k], ref[v][k]
            if g == 0 and r == 0:
                continue
            rel = (g - r) / r * 100 if r else float("inf")
            if r >= 100:
                worst = max(worst, abs(rel))
            print(f"{v:<11}{k:<8}{g:>9,}{r:>9,}{g - r:>+8,}{rel:>+8.2f}")
        g, r = got[v], ref[v]
        if r["TOTAL"] and g["TOTAL"]:
            sg = g["BEV"] / g["TOTAL"] * 100
            sr = r["BEV"] / r["TOTAL"] * 100
            print(f"{v:<11}{'BEV%':<8}{sg:>9.3f}{sr:>9.3f}{sg - sr:>+8.3f}pp")
    print(f"worst |rel%| (cells with monthly >= 100): {worst:.2f}")
    return worst


def probe_month(session, period: str) -> dict:
    y, m = map(int, period.split("-"))
    ndays = calendar.monthrange(y, m)[1]
    first_next = date(y, m, ndays) + timedelta(days=1)
    days = [date(y, m, d) for d in range(1, ndays + 1)]
    days += [first_next + timedelta(days=i) for i in range(NEXT_DAYS)]

    print(f"\n\n======== {period} ========")
    txt_m, url_m = fs.download_month(session, period)
    r = session.head(url_m, timeout=60)
    print(f"monthly: {url_m}  Last-Modified={r.headers.get('Last-Modified')}")
    ref = empty_counts()
    ref_models = collections.Counter()
    ref_fec = collections.Counter()
    for line in records(txt_m):
        ref_fec[fec_month(line)] += 1
        add(ref, line)
        if len(line) == fs.RECORD_LEN and "Whole" in fs.record_variants(line):
            ref_models[model_key(line)] += 1
    del txt_m
    print(f"monthly FEC_MATRICULA mix: {dict(ref_fec.most_common(5))}")

    all_in = empty_counts()     # (a) every record of the month's daily files
    fec_in = empty_counts()     # (b) FEC_MATRICULA in month, incl. next days
    d_models = collections.Counter()
    files = []
    sample_shown = False
    for d in days:
        info, txt = get_daily(session, d)
        in_month_file = d.month == m
        if txt is not None:
            fec = collections.Counter()
            lens = collections.Counter()
            n = 0
            for line in records(txt):
                n += 1
                lens[len(line)] += 1
                fm = fec_month(line)
                fec[fm] += 1
                if not sample_shown:
                    print(f"sample FEC_MATRICULA={line[SL_FEC[0]:SL_FEC[1]]!r} "
                          f"FEC_TRAMITACION={line[9:17]!r} "
                          f"FEC_PROCESO={line[-8:]!r}")
                    sample_shown = True
                if in_month_file:
                    add(all_in, line)
                if fm == period:
                    add(fec_in, line)
                    if (len(line) == fs.RECORD_LEN
                            and "Whole" in fs.record_variants(line)):
                        d_models[model_key(line)] += 1
            info.update(records=n, lengths=dict(lens.most_common(3)),
                        fec_mix=dict(fec.most_common(4)))
            del txt
        files.append(info)
        print(json.dumps(info, ensure_ascii=False))

    missing_weekdays = [f["date"] for f in files
                        if f["status"] != 200 and f["dow"] not in ("Sat", "Sun")
                        and f["date"][:7] == period]
    present_weekend = [f["date"] for f in files
                       if f["status"] == 200 and f["dow"] in ("Sat", "Sun")]
    print(f"\nweekdays without a file: {missing_weekdays}")
    print(f"weekend days with a file: {present_weekend}")

    w_a = diff_table(f"{period} (a) sum of all daily files vs monthly",
                     all_in, ref)
    w_b = diff_table(f"{period} (b) daily records with FEC_MATRICULA in "
                     f"month (incl. next {NEXT_DAYS} days) vs monthly",
                     fec_in, ref)

    print(f"\n### {period} top models (Whole) — daily (b) vs monthly")
    top_ref = ref_models.most_common(25)
    rank_d = {k: i for i, (k, _) in enumerate(d_models.most_common(25))}
    for i, (k, n) in enumerate(top_ref):
        print(f"{i + 1:>2}. {k[0]:<6} {k[1]:<15} {k[2]:<25} "
              f"monthly={n:>6,} daily={d_models[k]:>6,} "
              f"rank_daily={rank_d[k] + 1 if k in rank_d else '-'}")
    by_brand_r, by_brand_d = collections.Counter(), collections.Counter()
    for (c, b, _), n in ref_models.items():
        by_brand_r[(c, b)] += n
    for (c, b, _), n in d_models.items():
        by_brand_d[(c, b)] += n
    print(f"\n### {period} top BEV brands — daily (b) vs monthly")
    for (c, b), n in [x for x in by_brand_r.most_common() if x[0][0] == "BEV"][:15]:
        print(f"  {b:<15} monthly={n:>6,} daily={by_brand_d[(c, b)]:>6,} "
              f"diff={by_brand_d[(c, b)] - n:>+5,}")
    return {"period": period, "worst_a": w_a, "worst_b": w_b,
            "missing_weekdays": missing_weekdays}


def list_current(session, period: str) -> None:
    y, m = map(int, period.split("-"))
    ndays = calendar.monthrange(y, m)[1]
    print(f"\n\n======== currently published daily files for {period} ========")
    today = date.today()
    d = date(y, m, 1)
    end = min(date(y, m, ndays) + timedelta(days=NEXT_DAYS), today)
    while d <= end:
        url = DAILY_TPL.format(y=d.year, m=d.month, ymd=d.strftime("%Y%m%d"))
        r = session.head(url, timeout=60, allow_redirects=True)
        print(f"{d} {d.strftime('%a')} {r.status_code} "
              f"len={r.headers.get('Content-Length')} "
              f"Last-Modified={r.headers.get('Last-Modified')}")
        d += timedelta(days=1)


def daily_only(session, period: str) -> None:
    """Aggregate a month from its daily files alone (no monthly yet) and
    print the per-variant counts + top models as JSON for a later diff."""
    y, m = map(int, period.split("-"))
    ndays = calendar.monthrange(y, m)[1]
    first_next = date(y, m, ndays) + timedelta(days=1)
    days = [date(y, m, d) for d in range(1, ndays + 1)]
    days += [first_next + timedelta(days=i) for i in range(NEXT_DAYS)]
    print(f"\n\n======== {period} from daily files only ========")
    all_in, fec_in = empty_counts(), empty_counts()
    models = collections.Counter()
    for d in days:
        info, txt = get_daily(session, d)
        if txt is None:
            print(f"{d} {d.strftime('%a')} {info['status']}")
            continue
        fec = collections.Counter()
        n = 0
        for line in records(txt):
            n += 1
            fm = fec_month(line)
            fec[fm] += 1
            if d.month == m:
                add(all_in, line)
            if fm == period:
                add(fec_in, line)
                if (len(line) == fs.RECORD_LEN
                        and "Whole" in fs.record_variants(line)):
                    models[model_key(line)] += 1
        print(f"{d} {d.strftime('%a')} records={n} fec_mix="
              f"{dict(fec.most_common(4))}")
        if n < 10:
            print(f"   tiny file, first lines: "
                  f"{[l[:60] for l in records(txt)][:3]} raw={txt[:200]!r}")
    for label, c in (("all", all_in), ("fec_in", fec_in)):
        print(f"\nCOUNTS_{label} " + json.dumps(
            {v: dict(c[v]) for v in VARIANTS}, sort_keys=True))
        w = c["Whole"]
        if w["TOTAL"]:
            print(f"Whole {label}: TOTAL={w['TOTAL']:,} "
                  f"BEV={w['BEV']:,} ({w['BEV'] / w['TOTAL'] * 100:.2f} %) "
                  f"PHEV+EREV={w['PHEV'] + w['EREV']:,}")
    by_brand = collections.Counter()
    for (c, b, _), n in models.items():
        by_brand[(c, b)] += n
    print("\ntop BEV brands: " + ", ".join(
        f"{b} {n:,}" for (c, b), n in by_brand.most_common() if c == "BEV")[:600])
    print("top BEV models: " + ", ".join(
        f"{b} {mo} {n:,}" for (c, b, mo), n in models.most_common()
        if c == "BEV")[:600])


def main() -> int:
    months = [p for p in (os.environ.get("PROBE_MONTHS") or "").split(",")
              if p.strip()]
    current = os.environ.get("PROBE_CURRENT") or "2026-09"
    session = fs.make_session()
    list_current(session, current)
    daily_only(session, current)
    summary = [probe_month(session, p.strip()) for p in months]
    print("\n\n======== SUMMARY ========")
    for s in summary:
        print(json.dumps(s))
    return 0


if __name__ == "__main__":
    sys.exit(main())
