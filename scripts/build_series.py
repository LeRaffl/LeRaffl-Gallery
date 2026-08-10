#!/usr/bin/env python3
"""Project the country CSVs into a drawable series artifact for the Raw Data tab.

    python3 scripts/build_series.py            # write series/ + the 35b checklist
    python3 scripts/build_series.py --check    # validate only, write nothing
    python3 scripts/build_series.py --country Romania --explain

Everything the chart needs in order to decide *what it is allowed to draw* is
decided here, once, at build time. The client stacks what it is given and never
re-derives a category or a granularity.

The rules and the counter-example behind each of them are documented in
`docs/architecture/35-proposal-raw-data-tab.md` § 4.2, stage by stage, together
with a change-one-check-the-other table. Read that before editing this file —
several of these stages were wrong the first time precisely because they ran in
the wrong order, and the tests that catch it are named countries, not units.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
OUT_DIR = ROOT / "series"
TODO_PATH = ROOT / "docs" / "architecture" / "35b-raw-data-quality-todo.md"

# Columns that mean "combustion, broken out". ETHANOL folds into FLEXFUEL and
# the gas fuels into OTHERS: they are the same thing under different source
# vocabularies, and no country reports enough of them to earn their own band.
SPLIT_ICE = ("PETROL", "DIESEL", "FLEXFUEL", "ETHANOL", "GAS", "CNG", "LPG")
ICE_COLS = ("ICE", "PETROL", "DIESEL", "FLEXFUEL")
ELECTRIFIED = ("BEV", "PHEV", "EREV", "HEV", "MHEV", "Hybrid")
BAND_ORDER = ("BEV", "PHEV", "EREV", "Hybrid", "HEV", "MHEV",
              "ICE", "PETROL", "DIESEL", "FLEXFUEL", "OTHERS")

# § 2.4 — a rendering tolerance, not an audit one. See the stage 6 notes.
RECONCILE_TOL = 0.03
# § 4.2 stage 6 — above this share, OTHERS is not a fuel mix, it is everything
# the source did not break out.
OTHERS_MAX = 0.80
# § 4.2 stage 3 — below this, the unnamed remainder is rounding, not a category.
RESIDUAL_MIN = 0.05
# § 4.2 stage 4 — a repeated value has to be material before it reads as a smear.
SMEAR_MIN_SHARE = 0.01
SMEAR_MIN_RUN = 3
# § 4.2 stage 7 — a band missing from more than this share of the drawn series
# is a definition change, not a seam.
FOLD_MISSING = 0.40
FOLD_MIN_ROWS = 24


# ---------------------------------------------------------------- primitives

def num(value):
    """Float, or None for an empty/unparseable cell.

    The distinction between None and 0.0 is load-bearing (§ 2.1b): an empty cell
    means the source did not report, a `0` means it reported none.
    """
    # A ragged row — an unquoted comma inside `notes` — lands in DictReader's
    # restkey as a list. Two files had one. Never let that reach float().
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def midx(period):
    """Months since year 0 — the shared calendar grid every stage works on.

    A bare `YYYY` lands on July so it sits mid-cycle rather than pretending to
    be January.
    """
    m = re.match(r"^(\d{4})(?:-(\d{2}))?$", (period or "").strip())
    if not m:
        return None
    return int(m.group(1)) * 12 + (int(m.group(2)) if m.group(2) else 7) - 1


def plabel(m):
    return f"{m // 12:04d}-{m % 12 + 1:02d}"


def slugify(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


# ---------------------------------------------------------------- the pipeline

def build_country(country, rows):
    """One `Whole` CSV → one drawable series, or None if nothing survives."""
    rows = [r for r in rows if midx(r.get("period")) is not None]
    rows.sort(key=lambda r: midx(r["period"]))
    if len(rows) < 3:
        return None
    idx = [midx(r["period"]) for r in rows]
    n = len(rows)

    # -- stage 1: native step, from the SPACING and never from time_interval.
    # 22 files carry a label that contradicts their own row spacing; the
    # spacing is a fact about the file, the label is an annotation.
    gaps = [b - a for a, b in zip(idx, idx[1:])]
    step = max(set(gaps), key=gaps.count)
    if step not in (1, 3, 12):
        return None

    # -- stage 2: resolve bands per row.
    # Decided per FILE, not per row: a country that starts reporting PHEV
    # separately must not flip its band set mid-series.
    hybrid_combined = (any(num(r.get("HEV")) for r in rows)
                       and not any(num(r.get("PHEV")) for r in rows))

    vals = []
    for r in rows:
        v = {}
        ice = num(r.get("ICE"))
        if ice is not None:
            v["ICE"] = ice                      # aggregate-ICE row wins outright
        else:
            for col in SPLIT_ICE:
                x = num(r.get(col))
                if not x:                       # truthiness: see below
                    continue
                key = ("FLEXFUEL" if col in ("FLEXFUEL", "ETHANOL")
                       else "OTHERS" if col in ("GAS", "CNG", "LPG") else col)
                v[key] = v.get(key, 0.0) + x
        # `is not None` for the electrified columns, truthiness for combustion.
        # The asymmetry is § 2.1b and it is deliberate: a zero in BEV/PHEV/HEV
        # is an ordinary observation, a zero in PETROL/DIESEL never is.
        if hybrid_combined:
            if num(r.get("HEV")) is not None:
                v["Hybrid"] = num(r.get("HEV"))
        else:
            for col in ("PHEV", "EREV", "HEV", "MHEV"):
                if num(r.get(col)) is not None:
                    v[col] = num(r.get(col))
        if num(r.get("BEV")) is not None:
            v["BEV"] = num(r.get("BEV"))
        if num(r.get("OTHERS")) is not None:
            v["OTHERS"] = v.get("OTHERS", 0.0) + num(r.get("OTHERS"))
        vals.append(v)

    total = [num(r.get("TOTAL")) or 0.0 for r in rows]

    # -- stage 3: the unnamed remainder is combustion, when it can only be that.
    # Both guards have a counter-example. Without the first, a half-reported
    # split gets papered over. Without the second, France 2015-2017 (BEV+PHEV
    # only, HEV from 2021) folds six years of hybrids into ICE while the same
    # file draws a hybrid band later.
    ev_cols = [c for c in ELECTRIFIED if any(c in v for v in vals)]
    residual_ice = 0
    for i, v in enumerate(vals):
        if total[i] <= 0 or any(c in v for c in ICE_COLS):
            continue
        if not all(c in v for c in ev_cols):
            continue
        rest = total[i] - sum(v.values())
        if rest / total[i] > RESIDUAL_MIN:
            v["ICE"] = rest
            residual_ice += 1

    cols = sorted(set().union(*vals) if vals else set(), key=BAND_ORDER.index)
    if not cols:
        return None

    # -- stage 4: granularity per (column, period), in months.
    # Where one series had monthly numbers and another only annual, the annual
    # one was divided by 12 and the monthly one left alone. Granularity is
    # therefore a property of the cell, not of the row.
    gcol = {c: [step] * n for c in cols}
    for c in cols:
        xs = [v.get(c, 0.0) for v in vals]
        i = 0
        while i < n:
            j = i
            while j + 1 < n and xs[j + 1] == xs[i] and xs[i] > 0:
                j += 1
            run = j - i + 1
            if run >= SMEAR_MIN_RUN:
                material = (abs(xs[i] - round(xs[i])) > 1e-9
                            or xs[i] / max(total[i], 1.0) >= SMEAR_MIN_SHARE)
                if material:
                    # snap to a real calendar cycle rather than the raw run
                    span = (12 if run >= 6 else 3) * step
                    for k in range(i, j + 1):
                        gcol[c][k] = max(gcol[c][k], span)
            i = j + 1

    # -- stage 5b: a row alone in its cycle already IS that cycle.
    # The only place time_interval is trusted, and "alone in its cycle" is what
    # makes trusting it safe — Singapore's 2018 is labelled yearly for twelve
    # rows of monthly totals and is untouched.
    per_cycle = {12: Counter(), 3: Counter()}
    for m in idx:
        per_cycle[12][m // 12] += 1
        per_cycle[3][m // 3] += 1
    whole = [0] * n
    for i, r in enumerate(rows):
        label = (r.get("time_interval") or "").strip().lower()
        cyc = 12 if label == "yearly" else 3 if label == "quarterly" else 0
        if cyc <= step or per_cycle[cyc][idx[i] // cyc] != 1:
            continue
        whole[i] = cyc
        for c in cols:
            gcol[c][i] = max(gcol[c][i], cyc)

    # -- stage 6: reconcile every ORIGINAL row, before aggregating anything.
    # A period whose combustion side is EXACTLY zero while its neighbours carry
    # thousands is a row where only the EV columns were filled. The test is the
    # exact zero, not a collapsed total: April 2020 is a real lockdown trough in
    # a dozen countries and has to survive.
    ice_like = [c for c in cols if c in ("ICE", "PETROL", "DIESEL", "FLEXFUEL",
                                         "HEV", "Hybrid")]
    ice_series = [sum(vals[i].get(c, 0.0) for c in ice_like) for i in range(n)]
    ev_only = [False] * n
    for i in range(n):
        window = [x for x in ice_series[max(0, i - 6):i + 7] if x > 0]
        if len(window) >= 5 and ice_series[i] == 0 and statistics.median(window) > 100:
            ev_only[i] = True

    why = [None] * n

    def reconcile(bands):
        ok = [False] * n
        for i in range(n):
            if ev_only[i]:
                why[i] = "EV-only row: the combustion side is exactly zero"
                continue
            if total[i] <= 0:
                why[i] = "TOTAL missing or not positive"
                continue
            # A negative band cannot be drawn and must not be clamped. It is
            # the row that is unrenderable, not the country — Norway's single
            # -1 in 2008-11 should not cost Norway its chart. `--check` still
            # calls the same value fatal, so a new one cannot be merged.
            neg = [c for c in bands if vals[i].get(c, 0.0) < 0]
            if neg:
                why[i] = (f"{', '.join(neg)} is negative "
                          f"({vals[i][neg[0]]:g}) — cannot be drawn")
                continue
            # Checked HERE, before the fold decision below, so the fold sees the
            # same rows the reader will. After aggregation it also "works" — and
            # Japan then folds its hybrids away on the strength of eight
            # pre-2020 years that never reach the chart.
            share = vals[i].get("OTHERS", 0.0) / total[i]
            if share > OTHERS_MAX:
                why[i] = f"OTHERS carries {share * 100:.0f}% of TOTAL"
                continue
            d = (sum(vals[i].get(c, 0.0) for c in bands) - total[i]) / total[i]
            if abs(d) <= RECONCILE_TOL:
                ok[i] = True
                why[i] = None
            else:
                why[i] = f"bands miss TOTAL by {d * 100:+.1f}%"
        return ok

    okrow = reconcile(cols)

    # -- stage 7: one band set for the whole series.
    # A band that exists for only part of a series is a definition change.
    # Decided on the DRAWABLE rows, which is why stage 6 has to run first — and
    # why it runs again afterwards, since folding changes the sums.
    folded = []
    for child, parents in (("HEV", ("PETROL", "ICE")), ("MHEV", ("PETROL", "ICE")),
                           ("FLEXFUEL", ("PETROL", "ICE")), ("EREV", ("PHEV",))):
        if child not in cols:
            continue
        shown = [i for i in range(n) if okrow[i]]
        if len(shown) < FOLD_MIN_ROWS:
            continue
        missing = sum(1 for i in shown if not vals[i].get(child))
        if missing / len(shown) <= FOLD_MISSING:
            continue
        parent = next((p for p in parents if p in cols), None)
        if parent is None:
            continue
        for v in vals:
            if child in v:
                v[parent] = v.get(parent, 0.0) + v.pop(child)
        folded.append((child, parent))
    if folded:
        cols = sorted(set().union(*vals), key=BAND_ORDER.index)
        gcol = {c: gcol.get(c, [step] * n) for c in cols}
        okrow = reconcile(cols)

    # -- stage 8: aggregate to whole calendar cycles.
    G = [max(gcol[c][i] for c in cols) for i in range(n)]
    out_m, out_g, out_t = [], [], []
    out_b = {c: [] for c in cols}
    partial = 0
    i = 0
    while i < n:
        if not okrow[i]:
            i += 1
            continue
        gi = G[i]

        if gi == step or whole[i]:
            # Stamped at the CYCLE END in both branches. A quarterly file stamps
            # its rows on the middle month (Canada, Georgia: Feb/May/Aug/Nov);
            # keeping that stamp here while the aggregated branch uses the cycle
            # end makes a quarterly bar overlap the yearly bar before it.
            span = whole[i] or step
            out_m.append((idx[i] // span) * span + span - 1)
            out_g.append(span)
            out_t.append(sum(vals[i].get(c, 0.0) for c in cols))
            for c in cols:
                out_b[c].append(vals[i].get(c, 0.0))
            i += 1
            continue

        cycle = idx[i] // gi
        j = i
        while (j + 1 < n and okrow[j + 1] and not whole[j + 1]
               and G[j + 1] == gi and idx[j + 1] // gi == cycle):
            j += 1
        complete = (idx[j] - idx[i] + step == gi) and (idx[j] % gi == gi - step)
        if not complete:
            # Drawn short, a half-year summed and drawn a year wide would be a
            # lie about the level. Dropping it is the honest option.
            partial += j - i + 1
            for k in range(i, j + 1):
                why[k] = (f"incomplete {gi}-month cycle "
                          f"({j - i + 1} of {gi // step} rows present)")
            i = j + 1
            continue
        acc = {c: sum(vals[x].get(c, 0.0) for x in range(i, j + 1)) for c in cols}
        out_m.append(idx[j])
        out_g.append(gi)
        out_t.append(sum(acc.values()))          # closes by construction
        for c in cols:
            out_b[c].append(acc[c])
        i = j + 1

    if not out_m:
        return None

    return {
        "country": country,
        "slug": slugify(country),
        "source": rows[-1].get("source", ""),
        "step": step,
        "ice_split": "ICE" not in cols,
        "hybrid_combined": hybrid_combined,
        "held_from": rows[0]["period"],
        "held_to": rows[-1]["period"],
        "dropped": sum(1 for i in range(n) if why[i] is not None),
        "coarse": sum(1 for g in out_g if g > step),
        "residual_ice": residual_ice,
        "folded": [f"{a} into {b}" for a, b in folded],
        "m": out_m,
        "g": out_g,
        "t": [round(x, 1) for x in out_t],
        "b": {c: [round(x, 1) for x in out_b[c]] for c in cols},
        "why": {rows[i]["period"]: why[i] for i in range(n) if why[i]},
    }


# ---------------------------------------------------------------- validation

def validate(country, rows, series):
    """Fatal problems first, then things worth recording.

    Negatives are fatal and nothing else catches them: a negative band still
    lets a row sum to TOTAL, and a zero-height rectangle is invisible.
    """
    fatal, noted = [], []
    seen = set()
    for r in rows:
        p = (r.get("period") or "").strip()
        # More fields than headers: an unquoted comma inside `notes`. Harmless
        # for the numeric columns, which is exactly why it goes unnoticed — but
        # any consumer that maps by position reads shifted columns.
        if None in r:
            noted.append(f"{country} {p}: row has more fields than headers "
                         f"(unquoted comma in a text cell?)")
        if p in seen:
            fatal.append(f"{country} {p}: duplicate period")
        seen.add(p)

        ice = num(r.get("ICE"))
        split = [c for c in ("PETROL", "DIESEL") if num(r.get(c))]
        if ice and split:
            fatal.append(f"{country} {p}: ICE and {'/'.join(split)} both populated")

        for col, value in r.items():
            if col in ("period", "time_interval", "variant", "source", "notes", "note"):
                continue
            x = num(value)
            if x is not None and x < 0:
                fatal.append(f"{country} {p}: {col} = {x:g} is negative")

    if series:
        for i, t in enumerate(series["t"]):
            s = sum(series["b"][c][i] for c in series["b"])
            if abs(s - t) > max(1.0, abs(t) * 1e-6):
                fatal.append(f"{country} {plabel(series['m'][i])}: "
                             f"emitted TOTAL {t} != Σ bands {s}")

    # A band that drops to exactly zero between two populated neighbours still
    # closes to TOTAL when ICE is a residual — Colombia 2025-07 BEV, between
    # 1,143 and 1,647. Recorded, not fatal: Colombia 2020-04 is the lockdown.
    for col in ("BEV", "PHEV", "HEV", "OTHERS"):
        xs = [num(r.get(col)) for r in rows]
        for i in range(1, len(xs) - 1):
            if xs[i] == 0 and (xs[i - 1] or 0) > 20 and (xs[i + 1] or 0) > 20:
                noted.append(f"{country} {rows[i]['period']}: {col} drops to 0 "
                             f"between {xs[i-1]:g} and {xs[i+1]:g}")
    return fatal, noted


# ---------------------------------------------------------------- the checklist

def _runs(periods, cap=3):
    out, ix, i = [], sorted(midx(p) for p in periods), 0
    while i < len(ix):
        j = i
        while j + 1 < len(ix) and ix[j + 1] - ix[j] <= 1:
            j += 1
        out.append(plabel(ix[i]) if i == j else f"{plabel(ix[i])}…{plabel(ix[j])}")
        i = j + 1
    return ", ".join(out[:cap]) + (" …" if len(out) > cap else "")


def write_todo(built, raw_rows, noted):
    """Regenerate `35b-raw-data-quality-todo.md` from the build's own reasons.

    Two tiers on purpose. Tier 1 costs bars and is what the checkboxes are for;
    tier 2 records the shape of each file so nobody re-discovers it as a bug.
    """
    blocking, shape, cost = defaultdict(list), defaultdict(list), Counter()

    for country, s in built.items():
        rows = raw_rows[country]
        idx = [midx(r["period"]) for r in rows]

        for line in [x for x in noted if x.startswith(country + " ") and "drops to 0" in x]:
            # Keep the period: "OTHERS drops to 0 between 43 and 1420" is not
            # something anyone can look up without knowing which month it is.
            where, what = line.split(": ", 1)
            blocking[country].append(f"`{where.split(' ', 1)[1]}` — {what}. The row still "
                                     f"closes to `TOTAL`, so no sum check sees it.")

        # months the file genuinely says nothing about. A gap between rows is
        # not evidence: a yearly row covers the eleven months behind it.
        covered = set()
        for m, g in zip(s["m"], s["g"]):
            covered |= set(range(m - g + 1, m + 1))
        for i, r in enumerate(rows):
            if r["period"] not in s["why"]:
                continue
            label = (r.get("time_interval") or "").strip().lower()
            cyc = 12 if label == "yearly" else 3 if label == "quarterly" else 1
            base = (idx[i] // cyc) * cyc
            covered |= set(range(base, base + cyc))
        absent = sorted(set(range(idx[0], idx[-1] + 1)) - covered)
        k = 0
        while k < len(absent):
            j = k
            while j + 1 < len(absent) and absent[j + 1] == absent[j] + 1:
                j += 1
            blocking[country].append(
                f"**No rows for {plabel(absent[k])}…{plabel(absent[j])}** — "
                f"{j - k + 1} periods the CSV says nothing about.")
            k = j + 1

        by_reason = defaultdict(list)
        for period, w in s["why"].items():
            key = ("cycle" if "cycle" in w else "others" if "OTHERS" in w
                   else "total" if "TOTAL missing" in w else
                   "evonly" if "EV-only" in w else "sum")
            by_reason[key].append((period, w))
        for key, ps in sorted(by_reason.items(), key=lambda kv: -len(kv[1])):
            span = _runs([p for p, _ in ps])
            if key == "sum":
                worst = max(ps, key=lambda x: abs(float(
                    re.search(r"([-+][\d.]+)%", x[1]).group(1))))
                text = (f"**{len(ps)} rows whose bands do not add up to `TOTAL`** "
                        f"(worst {worst[0]}: {worst[1]})")
            elif key == "cycle":
                text = (f"**{len(ps)} rows in an incomplete cycle** — the coarse "
                        f"figure they carry needs the whole cycle present to be "
                        f"summed back ({ps[0][1]})")
            elif key == "others":
                text = (f"**{len(ps)} rows where `OTHERS` carries more than "
                        f"{OTHERS_MAX:.0%} of `TOTAL`** — the source broke out "
                        f"almost nothing, so there is no mix to stack")
            elif key == "evonly":
                text = (f"**{len(ps)} rows with an exactly-zero combustion side** "
                        f"— only the EV columns were filled and `TOTAL` computed "
                        f"from them")
            else:
                text = f"**{len(ps)} rows with no usable `TOTAL`**"
            blocking[country].append(f"{text} · {span}")
            cost[country] += len(ps)

        visible = [(s["m"][i - 1], s["m"][i], s["m"][i] - s["g"][i] - s["m"][i - 1])
                   for i in range(1, len(s["m"]))
                   if s["m"][i] - s["g"][i] > s["m"][i - 1]]
        if visible:
            w = max(visible, key=lambda x: x[2])
            blocking[country].append(
                f"→ *Symptom:* {len(visible)} visible gap"
                f"{'s' if len(visible) > 1 else ''} in the chart, "
                f"{sum(x[2] for x in visible)} months "
                f"(worst {plabel(w[0] + 1)}…{plabel(w[1])}).")
            cost[country] += sum(x[2] for x in visible)

        # tier 2 — real, already handled, listed so the provenance is on record
        smear = {}
        for col in ("BEV", "PHEV", "EREV", "HEV", "MHEV", "PETROL", "DIESEL",
                    "ICE", "OTHERS", "TOTAL"):
            xs = [num(r.get(col)) for r in rows]
            rep, i = [], 0
            while i < len(xs):
                j = i
                while j + 1 < len(xs) and xs[j + 1] is not None and xs[j + 1] == xs[i]:
                    j += 1
                if xs[i] and j - i + 1 >= SMEAR_MIN_RUN:
                    rep.append((i, j))
                i = j + 1
            total_rows = sum(j - i + 1 for i, j in rep)
            if total_rows >= 9:
                smear[col] = (total_rows, rows[rep[0][0]]["period"],
                              rows[rep[-1][1]]["period"])
        if smear:
            widest = max(v[0] for v in smear.values())
            shape[country].append(
                f"A coarse figure is written across finer rows in "
                f"**{', '.join('`' + k + '`' for k in smear)}** — up to {widest} "
                f"rows, {min(v[1] for v in smear.values())}…"
                f"{max(v[2] for v in smear.values())}. Recovered by summing the "
                f"cycle; the cycle is then the finest resolution the chart can "
                f"offer for that span.")

        mism = Counter()
        for i, r in enumerate(rows):
            gap = (idx[i + 1] - idx[i]) if i + 1 < len(rows) else (
                idx[i] - idx[i - 1] if i else None)
            want = {1: "monthly", 3: "quarterly", 12: "yearly"}.get(gap)
            got = (r.get("time_interval") or "").strip().lower()
            if want and got and got != want:
                mism[(got, want)] += 1
        for (got, want), k in mism.most_common(2):
            if k >= 6:
                shape[country].append(
                    f"`time_interval` says **{got}** on {k} rows whose spacing is "
                    f"**{want}**. Nothing reads the label except § 3.2b (a row "
                    f"alone in its cycle), but it misleads every future consumer.")

    clean = sorted(c for c in built if not blocking.get(c))
    lines = [
        "# 35b · Raw Data — data-quality checklist\n",
        "**Generated, not hand-written** — `python3 scripts/build_series.py` rewrites "
        "this file on every build. Items disappear when the rows behind them are "
        "fixed, so `git diff` on this file is the progress report. Nothing here is a "
        "rendering bug: every entry is a statement about what is in "
        "`data/<Country>.csv`, phrased so it can be checked against the file.\n",
        f"**Status:** {len(built)} countries · "
        f"{sum(len(s['m']) for s in built.values()):,} periods drawable · "
        f"{sum(s['dropped'] for s in built.values()):,} held back · "
        f"**{len(clean)} of {len(built)} files cost the chart nothing.**\n",
        "---\n", "## Tier 1 — costs bars\n",
        "Ordered by what it costs. A period lost at T1M costs up to twelve bars at "
        "T12M, because a trailing window needs every month inside it (§ 7b), so the "
        "*Symptom* line is usually much larger than the row count above it.\n",
    ]
    for country in sorted(blocking, key=lambda c: (-cost[c], c)):
        if not cost[country]:
            continue
        lines.append(f"### {country}  ·  costs {cost[country]} periods\n")
        lines += [t if t.startswith("→") else f"- [ ] {t}" for t in blocking[country]]
        lines.append("")
    free = [c for c in sorted(blocking) if not cost[c]]
    if free:
        lines.append("### Costs no bars, but still wrong\n")
        for country in free:
            lines.append(f"**{country}**")
            lines += [t if t.startswith("→") else f"- [ ] {t}" for t in blocking[country]]
            lines.append("")

    lines += ["---\n", "## Tier 2 — the shape of the file\n",
              "Real, and already handled by the pipeline. Listed so the provenance of "
              "each file is on record and so nobody re-discovers it as a bug. Fixing "
              "these buys resolution, not bars.\n"]
    for country in sorted(shape):
        lines.append(f"### {country}\n")
        lines += [f"- {t}" for t in shape[country]]
        lines.append("")
    lines += ["---\n", "## Costs the chart nothing\n", ", ".join(clean) + "\n"]
    TODO_PATH.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------- driver

def read_whole(path):
    with path.open(encoding="utf-8") as fh:
        return [r for r in csv.DictReader(fh) if r.get("variant") == "Whole"]


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true",
                    help="validate only; write nothing, exit non-zero on a fatal")
    ap.add_argument("--country", help="build one country instead of all 51")
    ap.add_argument("--explain", action="store_true",
                    help="print every held-back period and its reason")
    args = ap.parse_args()

    files = sorted(p for p in DATA_DIR.glob("*.csv") if "_" not in p.stem)
    if args.country:
        files = [p for p in files if p.stem.lower() == args.country.lower()]
        if not files:
            print(f"no Whole CSV named {args.country!r}", file=sys.stderr)
            return 2

    built, raw_rows, fatal, noted = {}, {}, [], []
    for path in files:
        country = path.stem
        rows = read_whole(path)
        if not rows:
            continue
        raw_rows[country] = [r for r in rows if midx(r.get("period")) is not None]
        raw_rows[country].sort(key=lambda r: midx(r["period"]))
        try:
            series = build_country(country, rows)
        except Exception as exc:                      # noqa: BLE001 — report, continue
            fatal.append(f"{country}: {type(exc).__name__}: {exc}")
            continue
        f, nt = validate(country, raw_rows[country], series)
        fatal += f
        noted += nt
        if series:
            built[country] = series

    kept = sum(len(s["m"]) for s in built.values())
    dropped = sum(s["dropped"] for s in built.values())
    coarse = sum(s["coarse"] for s in built.values())
    print(f"  {len(built)} countries · {kept:,} periods drawable · "
          f"{dropped:,} held back · {coarse:,} coarser than native")

    if args.explain:
        for country, s in sorted(built.items()):
            if not s["why"]:
                continue
            print(f"\n  {country}")
            for period, w in sorted(s["why"].items()):
                print(f"    {period}  {w}")

    if noted:
        print(f"  {len(noted)} recorded (not fatal):")
        for line in noted[:10]:
            print(f"    · {line}")
        if len(noted) > 10:
            print(f"    · … and {len(noted) - 10} more")

    # `--check` is the gate: it runs on PRs and refuses to let a NEW impossible
    # value in. The write path reports the same list and still writes, because
    # the artifact has to reflect whatever the data currently says — a workflow
    # that stops regenerating `series/` until an old defect is fixed just makes
    # the tab stale. Rows carrying the defect are held back either way, so
    # nothing wrong is ever drawn.
    if fatal:
        stream = sys.stderr if args.check else sys.stdout
        print(f"\n  ✗ {len(fatal)} rows fail --check:", file=stream)
        for line in fatal[:40]:
            print(f"    · {line}", file=stream)
        if len(fatal) > 40:
            print(f"    · … and {len(fatal) - 40} more", file=stream)
        if args.check:
            return 1
        print("    (held back, not drawn — see docs/architecture/"
              "35b-raw-data-quality-todo.md)\n")

    if args.check:
        print("  ✓ --check passed, nothing written")
        return 0

    OUT_DIR.mkdir(exist_ok=True)
    # `--country` writes that one series and nothing else. Rewriting the index
    # from a single-country run would leave the tab with a one-entry catalogue
    # and no way to notice — it fails silently and looks like a fetch problem.
    if args.country:
        s = next(iter(built.values()))
        (OUT_DIR / f"{s['slug']}.json").write_text(
            json.dumps(s, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        print(f"  ✓ series/{s['slug']}.json (index and checklist left alone)")
        return 0

    index = {
        "generated": __import__("datetime").date.today().isoformat(),
        "countries": [
            {k: s[k] for k in ("country", "slug", "source", "step", "ice_split",
                               "hybrid_combined", "held_from", "held_to",
                               "dropped", "coarse", "folded")}
            | {"bands": list(s["b"]), "from": plabel(s["m"][0]),
               "to": plabel(s["m"][-1]), "periods": len(s["m"])}
            for s in sorted(built.values(), key=lambda s: s["country"])
        ],
    }
    (OUT_DIR / "index.json").write_text(
        json.dumps(index, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    for s in built.values():
        (OUT_DIR / f"{s['slug']}.json").write_text(
            json.dumps(s, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    write_todo(built, raw_rows, noted)
    print(f"  ✓ series/ ({len(built) + 1} files) + {TODO_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
