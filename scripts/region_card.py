"""Region flyers and social cards from Gallery country aggregates.

The headline figure is a weighted average of member 12-month BEV shares,
using the Gallery's existing registration weights, not a pool of raw units:

    share = sum(w_i * share_i) / sum(w_i)

A member is included only when it has a genuinely full 12-month window
(monthly, no gap, BEV and TOTAL filled in every month). An empty cell is
unknown, never a zero. The common end month T is the latest month at which
the members that can form such a window ending at T cover at least 80 % of
the group's known weight. If no month reaches 80 %, T is the month with the
highest coverage (latest month on a tie). A member may therefore contribute
a window that is not its own latest month, so everyone in the figure is
measured to the same month.

Latest-month share, the 12-month range, and the change versus the prior
12 months are shown only when the same contributors all have the months
needed to compute them. The S-curve is the existing Builder/backtest
group fit, labelled as a model, not a forecast. There is no brand block:
brand tables cover too few members to describe a region honestly.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import model_card as mc
import snapshot_builder as sb
import flyer
import social_card
import market_structure as mstr
from model_card import esc

COVERAGE_TARGET = 80.0
REPO = mc.REPO
BACKTEST = REPO / "backtest" / "series"

# Groups this module can build. Fluid small/medium/big markets and
# single-country spotlights are out of scope.
REGION_LABELS = {
    "world": "World",
    "eu": "EU",
    "western_europe": "Western Europe",
    "northern_europe": "Northern Europe",
    "southern_europe": "Southern Europe",
    "eastern_europe": "Eastern Europe",
    "g7": "G7",
    "north_america": "North America",
    "south_america": "South America",
    "americas": "Americas",
    "asia": "Asia",
    "oceania": "Oceania",
}


ACEA_EU = REPO / "reference" / "acea_eu_shares.csv"
# ACEA publishes month M around the 22nd–27th of M+1; national data for the
# EU's 12-month window usually ends one month later than ACEA's latest
# year-to-date row. More than this many months behind means the monthly
# fetch (scripts/fetch_acea.py → reference/acea_eu_shares.csv) stopped.
ACEA_MAX_LAG = 2


def acea_eu_shares(path: Path = ACEA_EU) -> dict | None:
    """ACEA's own EU powertrain shares, latest release (reference/SOURCES.md).

    Shown on the EU brief as a separate, labelled line: ACEA's figure for
    the EU, not part of the weighted split from national data.
    """
    import csv
    try:
        with path.open(encoding="utf-8", newline="") as fh:
            rows = [r for r in csv.DictReader(fh) if (r.get("scope") or "") == "EU"]
    except OSError:
        return None
    rows = [r for r in rows if mc.month_index(r.get("period_to") or "") is not None
            and (r.get("HEV_share") or "").strip()]
    if not rows:
        return None
    r = max(rows, key=lambda r: mc.month_index(r["period_to"]))
    def num(k):
        try:
            return float(r[k])
        except (KeyError, TypeError, ValueError):
            return None
    a, b = mc.period_label(r["period_from"]), mc.period_label(r["period_to"])
    ya, yb = a.split()[-1], b.split()[-1]
    period = f"{a.split()[0]}–{b}" if ya == yb else f"{a}–{b}"
    return {"hev": num("HEV_share"), "bev": num("BEV_share"), "phev": num("PHEV_share"),
            "period": period, "from": r["period_from"], "to": r["period_to"],
            "definition": r.get("hev_definition") or "", "url": r.get("source_url") or "",
            "release": r.get("release") or ""}


def acea_lag_months(acea: dict | None, t: str) -> int | None:
    """Months between ACEA's period end and the brief's data end `t`."""
    if not acea:
        return None
    a, b = mc.month_index(acea.get("to") or ""), mc.month_index(t or "")
    if a is None or b is None:
        return None
    return b - a


def acea_for_brief(t: str, path: Path = ACEA_EU) -> dict | None:
    """acea_eu_shares() plus its lag behind `t`. A lag above ACEA_MAX_LAG
    (or a missing file) prints a warning; the brief then says on the line
    itself how old the ACEA figure is. `--check-acea` turns it into a failure."""
    import sys
    acea = acea_eu_shares(path)
    lag = acea_lag_months(acea, t)
    if acea is None:
        print(f"WARNING: no ACEA EU row in {path}; EU brief prints no HEV line",
              file=sys.stderr)
        return None
    acea["lag"] = lag
    acea["stale"] = lag is None or lag > ACEA_MAX_LAG
    if acea["stale"]:
        print(f"WARNING: ACEA EU figure ends {acea['to']}, {lag} months before the "
              f"EU data ({t}); limit {ACEA_MAX_LAG}. Check fetch-acea.yml.",
              file=sys.stderr)
    return acea


def acea_line(acea: dict, social: bool = False) -> str:
    """'ACEA, EU · Jan–Sep 2026  Hybrids (HEV): 36.3 % of new cars …'.

    A separate, labelled line: ACEA's own EU count (full and mild hybrids),
    never folded into the brief's BEV / PHEV / combustion split, which is
    weighted from members' national data. The brief adds ACEA's BEV and
    PHEV for the same period, so the reader can compare like with like."""
    if not acea or acea.get("hev") is None:
        return ""
    stale = ""
    if acea.get("stale"):
        # Visible on the page, not only in a log: the figure is older than usual.
        stale = (f' <span class="acea-stale">Latest ACEA figure, '
                 f'{acea.get("lag")} months before the data above.</span>')
    chip = f'<span class="acea-chip">ACEA, EU · {esc(acea["period"])}</span> '
    hev = f'<b>Hybrids (HEV): {esc(mc.share(acea["hev"]))}</b>'
    if social:
        return (f'<span class="sc-acea">{chip}{hev} (full + mild), '
                f'ACEA\'s own count.{stale}</span>')
    cmp_ = ""
    if acea.get("bev") is not None and acea.get("phev") is not None:
        cmp_ = (f" (same count: BEV {mc.share(acea['bev'])}, "
                f"PHEV {mc.share(acea['phev'])})")
    return (f'<p class="fh-acea">{chip}{hev} of new cars{esc(cmp_)}. Full + mild '
            f'hybrids; ACEA\'s own figure, not in the split above.{stale}</p>')


def _csv_for(country: str) -> Path:
    return REPO / "data" / f"{country}.csv"


def _weight(weights: dict[str, float], country: str) -> float:
    w = weights.get(f"{country}|whole")
    return w if w is not None and math.isfinite(w) else 0.0


def _month_map(rows: list[dict]) -> dict[int, dict]:
    out: dict[int, dict] = {}
    for row in rows:
        if mc.interval_of(row) != "monthly":
            continue
        idx = mc.month_index(row["period"])
        if idx is not None:
            out[idx] = row
    return out


def window_ending(rows: list[dict], end: str, size: int = 12) -> dict | None:
    """A full monthly window of `size` months ending at `end`, or None."""
    idx_end = mc.month_index(end)
    if idx_end is None:
        return None
    by = _month_map(rows)
    window = []
    for i in range(idx_end - size + 1, idx_end + 1):
        row = by.get(i)
        if row is None:
            return None
        window.append(row)
    total, bev = mc._full_sum(window, "TOTAL"), mc._full_sum(window, "BEV")
    if total is None or bev is None or total <= 0:
        return None
    return {"share": 100 * bev / total, "total": total, "bev": bev,
            "end": end, "from": window[0]["period"]}


# A printed one-decimal share is unchanged if the move is under half a tenth.
SPLIT_BEV_TOL = 0.05


def window_powertrains(rows: list[dict], end: str, size: int = 12) -> dict | None:
    """BEV share plus PHEV/HEV when those columns are complete.

    Empty is unknown, never 0. EREV folds into PHEV only when the window
    uses that column and fills it; an used-but-empty EREV leaves PHEV unset.
    """
    base = window_ending(rows, end, size=size)
    if not base:
        return None
    idx_end = mc.month_index(end)
    by = _month_map(rows)
    window = [by[i] for i in range(idx_end - size + 1, idx_end + 1)]
    total = base["total"]
    out = {**base, "phev": None, "hev": None}
    phev = mc._full_sum(window, "PHEV")
    if phev is not None:
        if mc._used(window, "EREV"):
            erev = mc._full_sum(window, "EREV")
            if erev is None:
                phev = None
            else:
                phev = phev + erev
        if phev is not None:
            out["phev"] = 100 * phev / total
    hev = mc._full_sum(window, "HEV")
    if hev is not None:
        out["hev"] = 100 * hev / total
    return out


def _col_ready(win: dict | None, col: str) -> bool:
    if not win:
        return False
    if col == "BEV":
        return win.get("share") is not None
    return win.get(col.lower()) is not None


def weighted_powertrains(contrib: list[dict], end: str) -> dict | None:
    """Weight-average of window_powertrains across every member.

    phev/hev are set only when every member has that column in the window.
    Returns None if any member lacks a BEV window (same-set rule).
    """
    num = {"share": 0.0, "phev": 0.0, "hev": 0.0}
    have = {"phev": True, "hev": True}
    den = 0.0
    for m in contrib:
        win = window_powertrains(m["rows"], end)
        if not win:
            return None
        w = m["weight"]
        den += w
        num["share"] += w * win["share"]
        if win["phev"] is None:
            have["phev"] = False
        else:
            num["phev"] += w * win["phev"]
        if win["hev"] is None:
            have["hev"] = False
        else:
            num["hev"] += w * win["hev"]
    if den <= 0:
        return None
    return {
        "share": num["share"] / den,
        "phev": (num["phev"] / den) if have["phev"] else None,
        "hev": (num["hev"] / den) if have["hev"] else None,
    }


def _subset_gate(subset: list[dict], contrib: list[dict], t: str,
                 bev_all: float) -> bool:
    if not subset:
        return False
    w_sub = sum(m["weight"] for m in subset)
    w_all = sum(m["weight"] for m in contrib)
    if w_all <= 0 or 100 * w_sub / w_all < COVERAGE_TARGET:
        return False
    bev_sub = weighted_share(subset, t)
    return bev_sub is not None and abs(bev_sub - bev_all) < SPLIT_BEV_TOL


def _members_with(contrib: list[dict], ends: list[str], col: str) -> list[dict]:
    out = []
    for m in contrib:
        if all(_col_ready(window_powertrains(m["rows"], end), col) for end in ends):
            out.append(m)
    return out


def choose_mix_split(contrib: list[dict], t: str, prior_end: str | None
                     ) -> dict:
    """Pick the member set and extra bands for the mix and who-gained.

    The headline contributor set is kept when it can carry a band. A
    smaller set is used only if it covers at least COVERAGE_TARGET of
    contributor weight and leaves the headline BEV unchanged at one
    decimal, so the stack still matches the hero. Empty cells are never
    treated as 0; members without a series are omitted or the band is
    dropped, never filled in.
    """
    ends = [t] + ([prior_end] if prior_end else [])
    bev_all = weighted_share(contrib, t)
    bands: list[str] = []
    members = list(contrib)
    skipped: dict[str, list[str]] = {}

    def full_on(group: list[dict], col: str) -> bool:
        return len(_members_with(group, ends, col)) == len(group)

    for col in ("PHEV", "HEV"):
        if full_on(members, col):
            bands.append(col)
        else:
            skipped[col] = [m["country"] for m in members
                            if m not in _members_with(members, ends, col)]

    if "PHEV" not in bands:
        sub = _members_with(contrib, ends, "PHEV")
        if bev_all is not None and _subset_gate(sub, contrib, t, bev_all):
            members = sub
            bands.append("PHEV")
            skipped["PHEV"] = [m["country"] for m in contrib if m not in sub]
            if full_on(members, "HEV"):
                bands.append("HEV")
                skipped.pop("HEV", None)
            else:
                skipped["HEV"] = [m["country"] for m in members
                                  if m not in _members_with(members, ends, "HEV")]
        # else: keep the headline set, no PHEV band

    short, long = _split_note(contrib, members, bands, skipped, t, bev_all)
    return {"members": members, "bands": bands, "note": short,
            "note_long": long, "skipped": skipped, "bev_all": bev_all}


def _split_note(contrib: list[dict], members: list[dict], bands: list[str],
                skipped: dict[str, list[str]], t: str,
                bev_all: float | None) -> tuple[str, str]:
    """Return (short who-gained line, longer footer line)."""
    short: list[str] = []
    long: list[str] = []
    if len(members) != len(contrib):
        omitted = [m["country"] for m in contrib if m not in members]
        w_sub = sum(m["weight"] for m in members)
        w_all = sum(m["weight"] for m in contrib)
        cov = 100 * w_sub / w_all if w_all else 0
        bev_sub = weighted_share(members, t)
        same = (bev_all is not None and bev_sub is not None
                and round(bev_sub, 1) == round(bev_all, 1))
        short.append(
            f"Powertrain split from {len(members)} of {len(contrib)} countries "
            f"in the headline ({cov:.0f} % of contributor weight).")
        long.append(
            f"The mix and who-gained split use {len(members)} of "
            f"{len(contrib)} headline countries ({cov:.0f} % of contributor "
            f"weight); not in that split: {_and_list(omitted)}"
            + ("." if same else
               f" (BEV in this subset is {bev_sub:.1f} %, against "
               f"{bev_all:.1f} % in the headline)."))
    hev_miss = skipped.get("HEV") or []
    if "HEV" not in bands and hev_miss:
        if "PHEV" in bands:
            reason = "Full hybrid is kept in “Combustion + hybrids”"
        else:
            reason = "The mix is battery electric against everything else"
        line = (f"{reason}: {_and_list(hev_miss)} "
                f"{'has' if len(hev_miss) == 1 else 'have'} no HEV series "
                "in the source files.")
        # Keep the who-gained line short when many members are named.
        if len(hev_miss) <= 3:
            short.append(line)
        else:
            short.append(
                f"{reason}: {len(hev_miss)} members have no HEV series "
                "in the source files.")
        long.append(line)
    phev_miss = skipped.get("PHEV") or []
    if "PHEV" not in bands and phev_miss and len(members) == len(contrib):
        sub = [m for m in contrib if m["country"] not in phev_miss]
        bev_sub = weighted_share(sub, t) if sub else None
        if bev_all is not None and bev_sub is not None:
            line = (f"Plug-in hybrid is not split out: leaving out "
                    f"{_and_list(phev_miss)}, who have no PHEV series, would "
                    f"move BEV from {bev_all:.1f} % to {bev_sub:.1f} %.")
        else:
            line = (f"Plug-in hybrid is not split out: {_and_list(phev_miss)} "
                    f"{'has' if len(phev_miss) == 1 else 'have'} no PHEV series.")
        short.append(line)
        long.append(line)
    return " ".join(short), " ".join(long)


def mix_points_for(members: list[dict], t: str, bands: list[str],
                   years: int = 10) -> list[dict]:
    """Trailing-window weighted shares, walking back on a fixed member set."""
    t_idx = mc.month_index(t)
    if t_idx is None or not members:
        return []
    out = []
    i = t_idx
    while True:
        end = None
        # Recover the period string from any member that has this month.
        for m in members:
            by = _month_map(m["rows"])
            if i in by:
                end = by[i]["period"]
                break
        if end is None:
            break
        split = weighted_powertrains(members, end)
        if not split or split["share"] is None:
            break
        if "PHEV" in bands and split["phev"] is None:
            break
        if "HEV" in bands and split["hev"] is None:
            break
        phev = split["phev"] if "PHEV" in bands else None
        hev = split["hev"] if "HEV" in bands else None
        rest = 100 - split["share"] - (phev or 0) - (hev or 0)
        out.append({"t": i / 12, "period": end, "BEV": split["share"],
                    "PHEV": phev, "HEV": hev, "REST": max(0.0, rest)})
        i -= 1
    out.reverse()
    if len(out) < 13:
        return []
    last = out[-1]["t"]
    return [p for p in out if p["t"] >= last - years]


def split_shift(members: list[dict], t: str, prior_end: str,
                bands: list[str], hev_full: bool) -> dict | None:
    after = weighted_powertrains(members, t)
    before = weighted_powertrains(members, prior_end)
    if not after or not before or after["share"] is None or before["share"] is None:
        return None
    def row(key, label, a, b):
        return {"key": key, "label": label, "delta": a - b, "after": a, "before": b}
    rows = [row("BEV", "Battery electric", after["share"], before["share"])]
    rest_after = after["share"]
    rest_before = before["share"]
    if "PHEV" in bands and after["phev"] is not None and before["phev"] is not None:
        rows.append(row("PHEV", "Plug-in hybrid", after["phev"], before["phev"]))
        rest_after += after["phev"]
        rest_before += before["phev"]
    if "HEV" in bands and after["hev"] is not None and before["hev"] is not None:
        hev_lab = "Full hybrid" if hev_full else "Hybrid"
        rows.append(row("HEV", hev_lab, after["hev"], before["hev"]))
        rest_after += after["hev"]
        rest_before += before["hev"]
    if "PHEV" in bands and "HEV" in bands:
        rest_lab = "Combustion"
    elif "PHEV" in bands:
        rest_lab = "Combustion + hybrids"
    else:
        # Plug-ins stay in the residual when they are not their own band.
        rest_lab = "Everything else"
    rows.append(row("REST", rest_lab, 100 - rest_after, 100 - rest_before))
    return {
        "span": ((mc._shift(prior_end, -11), prior_end),
                 (mc._shift(t, -11), t)),
        "rows": rows,
        "interval": "monthly",
        "bev_before": 0, "bev_after": 0,
    }


def month_share(rows: list[dict], period: str) -> float | None:
    by = _month_map(rows)
    idx = mc.month_index(period)
    if idx is None:
        return None
    row = by.get(idx)
    return mc._bev_share(row) if row else None


def pick_common_end(members: list[dict], target: float = COVERAGE_TARGET
                    ) -> tuple[str | None, list[dict], float]:
    """Return (T, contributors, coverage_pct).

    `members` is a list of dicts with `weight` and `rows`. Coverage is
    against the sum of every member's weight, including those that cannot
    form a window at T.
    """
    total_w = sum(m["weight"] for m in members)
    if total_w <= 0:
        return None, [], 0.0
    candidates: set[str] = set()
    for m in members:
        for idx, row in _month_map(m["rows"]).items():
            # A possible window end is any month that could close a 12-month run.
            candidates.add(row["period"])
    best_t, best_c, best_cov = None, [], -1.0
    # Prefer the latest T that meets the target; otherwise the highest
    # coverage, latest month on a tie.
    for t in sorted(candidates, key=lambda p: mc.month_index(p) or 0, reverse=True):
        contrib = [m for m in members if window_ending(m["rows"], t)]
        cov = 100 * sum(m["weight"] for m in contrib) / total_w
        if cov >= target:
            return t, contrib, cov
        if cov > best_cov + 1e-9 or (abs(cov - best_cov) <= 1e-9 and best_t is None):
            best_t, best_c, best_cov = t, contrib, cov
    return best_t, best_c, (best_cov if best_cov >= 0 else 0.0)


def weighted_share(contrib: list[dict], end: str, size: int = 12) -> float | None:
    num = den = 0.0
    for m in contrib:
        win = window_ending(m["rows"], end, size=size)
        if not win:
            return None
        num += m["weight"] * win["share"]
        den += m["weight"]
    return num / den if den else None


def weighted_month(contrib: list[dict], period: str) -> float | None:
    num = den = 0.0
    for m in contrib:
        s = month_share(m["rows"], period)
        if s is None:
            return None
        num += m["weight"] * s
        den += m["weight"]
    return num / den if den else None


def _and_list(names: list[str]) -> str:
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f"{names[0]} and {names[1]}"
    return ", ".join(names[:-1]) + f" and {names[-1]}"


def coverage_notes(label: str, members: list[dict], contrib: list[dict],
                   t: str, cov: float) -> tuple[str, str]:
    """Return (short social note, longer A4 note)."""
    n, N = len(contrib), len(members)
    through = mc.period_label(t, long=True)
    short = (f"{n} of {N} {label} countries, {cov:.0f} % of registration "
             f"weight, 12 months to {through}")
    if n == N:
        short = (f"All {N} {label} countries, 12 months to {through}")
    used = {m["country"] for m in contrib}
    missing = [m["country"] for m in members if m["country"] not in used]
    long = (f"Weighted 12-month BEV share of {n} of {N} {label} countries, "
            f"12 months to {through}, covering {cov:.0f} % of the group's "
            f"registration weight.")
    if n == N:
        if N <= 6:
            long = (f"Weighted 12-month BEV share of all {N} {label} countries "
                    f"({_and_list([m['country'] for m in contrib])}), "
                    f"12 months to {through}.")
        else:
            long = (f"Weighted 12-month BEV share of all {N} {label} countries, "
                    f"12 months to {through}.")
    elif missing:
        if len(missing) <= 8:
            named = _and_list(missing)
        else:
            named = ", ".join(missing[:6]) + f" and {len(missing) - 6} more"
        long += (f" Not in this figure: {named} "
                 f"(no full 12-month window ending {mc.period_label(t)}).")
    later = [m["country"] for m in contrib
             if m["rows"] and mc.month_index(m["rows"][-1]["period"]) is not None
             and mc.month_index(m["rows"][-1]["period"]) > (mc.month_index(t) or 0)]
    if later:
        long += (" Some members have later months that were not used, so "
                 "everyone is measured to the same month.")
    return short, long


def synthetic_rows(contrib: list[dict], t: str) -> list[dict]:
    """Monthly rows of the weighted share, walking back while the same
    contributors all have that month. TOTAL is a constant so the rows
    carry shares only, not a fabricated registration count."""
    t_idx = mc.month_index(t)
    if t_idx is None:
        return []
    maps = [(m, _month_map(m["rows"])) for m in contrib]
    # Walk back from T to the first missing month in the common set.
    months: list[int] = []
    i = t_idx
    while True:
        if any(mc._bev_share(by.get(i) or {}) is None for _, by in maps):
            break
        months.append(i)
        i -= 1
    months.reverse()
    rows = []
    for idx in months:
        num = den = 0.0
        period = None
        for m, by in maps:
            row = by[idx]
            s = mc._bev_share(row)
            num += m["weight"] * s
            den += m["weight"]
            period = row["period"]
        share = num / den
        rows.append({
            "period": period,
            "time_interval": "monthly",
            "TOTAL": 1000.0,
            "BEV": 10.0 * share,  # 1000 * share/100
        })
    return rows


def _load_backtest(slug: str) -> dict | None:
    path = BACKTEST / f"{slug}.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text())


def _pick_frame(data: dict, t: str) -> dict | None:
    frames = data.get("frames") or []
    if not frames:
        return None
    t_idx = mc.month_index(t) or 0
    usable = []
    for fr in frames:
        per = fr.get("data_per") or fr.get("date")
        idx = mc.month_index(per) if per else None
        if idx is not None and idx <= t_idx:
            usable.append(fr)
    return usable[-1] if usable else frames[-1]


def region_mark(slug: str, kind: str = "fl") -> str:
    """A simple glyph in place of a flag. `kind` is 'fl' or 'sc'."""
    cls = "fl-mark" if kind == "fl" else "sc-mark"
    wh = (54, 37) if kind == "fl" else (90, 60)
    ink, pale, mid = "#154a30", "#dcefe4", "#2c7a50"
    # Common frame.
    body = {
        "world": (
            f'<circle cx="45" cy="30" r="18" fill="{pale}" stroke="{ink}" stroke-width="2"/>'
            f'<ellipse cx="45" cy="30" rx="7" ry="18" fill="none" stroke="{mid}" stroke-width="1.4"/>'
            f'<line x1="27" y1="30" x2="63" y2="30" stroke="{mid}" stroke-width="1.4"/>'
            f'<path d="M29 20h32M29 40h32" fill="none" stroke="{ink}" stroke-width="1" opacity=".55"/>'
        ),
        "eu": "".join(
            f'<circle cx="{45 + 16*math.cos(math.radians(-90+i*30)):.1f}" '
            f'cy="{30 + 16*math.sin(math.radians(-90+i*30)):.1f}" r="2.2" fill="{ink}"/>'
            for i in range(12)
        ),
        "northern_europe": (
            f'<circle cx="45" cy="32" r="16" fill="{pale}" stroke="{ink}" stroke-width="1.6"/>'
            f'<path d="M45 10 L51 22 H39 Z" fill="{ink}"/>'
            f'<text x="45" y="38" text-anchor="middle" font-size="13" font-weight="700" '
            f'fill="{ink}" font-family="sans-serif">N</text>'
        ),
        "south_america": (
            f'<path d="M48 10 C56 14 58 22 54 30 C60 38 58 48 50 54 C42 56 38 50 38 42 '
            f'C34 34 36 22 42 14 C44 10 46 9 48 10Z" fill="{mid}" stroke="{ink}" stroke-width="1.2"/>'
        ),
        "north_america": (
            f'<path d="M30 16 C38 8 52 10 58 18 C62 22 60 30 54 34 L58 44 C50 48 40 44 '
            f'36 36 C28 30 24 22 30 16Z" fill="{mid}" stroke="{ink}" stroke-width="1.2"/>'
        ),
        "americas": (
            f'<path d="M32 12 C42 6 54 12 54 22 C50 28 44 30 40 28 C34 24 28 20 32 12Z" fill="{mid}"/>'
            f'<path d="M44 32 C52 36 52 48 46 54 C38 56 36 46 38 40 C38 34 40 32 44 32Z" fill="{ink}"/>'
        ),
        "western_europe": (
            f'<rect x="28" y="14" width="34" height="32" rx="4" fill="{pale}" stroke="{ink}" stroke-width="1.6"/>'
            f'<text x="45" y="36" text-anchor="middle" font-size="11" font-weight="700" '
            f'fill="{ink}" font-family="sans-serif">W</text>'
        ),
        "eastern_europe": (
            f'<rect x="28" y="14" width="34" height="32" rx="4" fill="{pale}" stroke="{ink}" stroke-width="1.6"/>'
            f'<text x="45" y="36" text-anchor="middle" font-size="11" font-weight="700" '
            f'fill="{ink}" font-family="sans-serif">E</text>'
        ),
        "southern_europe": (
            f'<rect x="28" y="14" width="34" height="32" rx="4" fill="{pale}" stroke="{ink}" stroke-width="1.6"/>'
            f'<text x="45" y="36" text-anchor="middle" font-size="11" font-weight="700" '
            f'fill="{ink}" font-family="sans-serif">S</text>'
        ),
        "asia": (
            f'<circle cx="45" cy="30" r="18" fill="{pale}" stroke="{ink}" stroke-width="1.6"/>'
            f'<text x="45" y="35" text-anchor="middle" font-size="11" font-weight="700" '
            f'fill="{ink}" font-family="sans-serif">AS</text>'
        ),
        "oceania": (
            f'<circle cx="38" cy="28" r="10" fill="{mid}"/>'
            f'<circle cx="56" cy="38" r="6" fill="{ink}"/>'
        ),
        "g7": (
            f'<circle cx="45" cy="30" r="18" fill="{pale}" stroke="{ink}" stroke-width="1.6"/>'
            f'<text x="45" y="35" text-anchor="middle" font-size="14" font-weight="700" '
            f'fill="{ink}" font-family="sans-serif">G7</text>'
        ),
    }.get(slug)
    if not body:
        letters = REGION_LABELS.get(slug, slug)[:2].upper()
        body = (
            f'<rect x="16" y="12" width="58" height="36" rx="4" fill="{pale}" stroke="{ink}" stroke-width="1.6"/>'
            f'<text x="45" y="36" text-anchor="middle" font-size="12" font-weight="700" '
            f'fill="{ink}" font-family="sans-serif">{esc(letters)}</text>'
        )
    return (
        f'<svg class="{cls}" viewBox="0 0 90 60" width="{wh[0]}" height="{wh[1]}" '
        f'aria-hidden="true">{body}</svg>')


def build_region_curve_svg(rows: list[dict], years: list[float],
                           model: list[float], width: int, height: int,
                           left: int = 42) -> str:
    """Observed monthly shares and the backtest model polyline."""
    observed = []
    for row in rows:
        idx = mc.month_index(row["period"])
        value = mc._bev_share(row)
        if idx is not None and value is not None:
            observed.append((idx / 12, value))
    if len(observed) < 6 and not (years and model):
        return ""
    data_end = observed[-1][0] if observed else (years[0] if years else 2020)
    start = math.floor(observed[0][0] if observed else (years[0] if years else 2015))
    end = data_end + mc.CURVE_HORIZON_YEARS
    if years:
        end = min(end, years[-1])
    end = float(math.ceil(end))
    if end <= start:
        end = start + 5

    right, top, bottom = 28, 20, 26
    plot_w, plot_h = width - left - right, height - top - bottom
    span = max(end - start, 0.5)

    def x_of(year: float) -> float:
        return left + plot_w * (year - start) / span

    peak = 0.0
    if observed:
        peak = max(peak, max(v for _, v in observed))
    if model and years:
        vis = [s for y, s in zip(years, model) if start <= y <= end]
        if vis:
            peak = max(peak, max(vis))
    ymax = next((float(m) for m in (20, 40, 60, 80, 100) if m >= peak * 1.1 or m == 100), 100.0)

    def y_of(v: float) -> float:
        return top + plot_h * (1 - v / ymax)

    parts = []
    # Grid and y ticks.
    step = 20 if ymax >= 60 else 10 if ymax >= 30 else 5
    for v in range(0, int(ymax) + 1, step):
        y = y_of(v)
        parts.append(f'<line class="cv-grid" x1="{left}" x2="{left+plot_w}" y1="{y:.1f}" y2="{y:.1f}"/>')
        parts.append(f'<text class="ax" x="{left-6}" y="{y+4:.1f}" text-anchor="end">{v}</text>')
    y0 = int(math.ceil(start))
    y1 = int(math.floor(end))
    year_step = 5 if (y1 - y0) > 16 else 2 if (y1 - y0) > 8 else 1
    for year in range(y0, y1 + 1, year_step):
        x = x_of(year)
        parts.append(f'<line class="cv-grid" x1="{x:.1f}" x2="{x:.1f}" y1="{top}" y2="{top+plot_h}"/>')
        if x <= width - 16:
            parts.append(f'<text class="ax" x="{x:.1f}" y="{top+plot_h+16}" text-anchor="middle">{year}</text>')
    # Now marker.
    xn = x_of(data_end)
    parts.append(f'<line class="cv-now" x1="{xn:.1f}" x2="{xn:.1f}" y1="{top}" y2="{top+plot_h}"/>')
    # Model polyline.
    if years and model:
        pts = []
        for y, s in zip(years, model):
            if start - 0.05 <= y <= end + 0.05:
                pts.append(f"{x_of(y):.1f},{y_of(s):.1f}")
        if len(pts) >= 2:
            parts.append(f'<polyline class="cv-fit" points="{" ".join(pts)}"/>')
    # Trailing 12-month observed line, if we have a year of monthly points.
    if len(observed) >= 12:
        ttm_pts = []
        for i in range(11, len(observed)):
            window = observed[i-11:i+1]
            if any(b - a > 1 / 12 + 0.01 for a, b in zip(
                    [t for t, _ in window], [t for t, _ in window][1:])):
                continue
            share = sum(v for _, v in window) / 12  # unweighted months of already-weighted shares
            # The honest TTM is a re-weight of member windows, not the mean of
            # monthly regional shares. Use the last point only if we stored it
            # on the row? Monthly mean of weighted shares ≈ TTM only when
            # member volumes (weights) are constant. Weights are fixed, so
            # the average of monthly weighted shares is the weighted TTM.
            # Yes: each monthly share is already weight-averaged, and weights
            # do not change month to month, so mean of 12 monthly shares
            # equals the 12-month weighted share. Good.
            ttm_pts.append(f"{x_of(window[-1][0]):.1f},{y_of(share):.1f}")
        if len(ttm_pts) >= 2:
            parts.append(f'<polyline class="cv-ttm" points="{" ".join(ttm_pts)}"/>')
    # Monthly dots (thin out if crowded).
    step_pt = 1 if len(observed) <= 80 else 2
    for t, v in observed[::step_pt]:
        parts.append(f'<circle class="cv-pt" cx="{x_of(t):.1f}" cy="{y_of(v):.1f}" r="2"/>')
    return (
        f'<svg class="curve" viewBox="0 0 {width} {height}" width="{width}" '
        f'height="{height}" role="img" aria-label="BEV share and fitted model">'
        f'{"".join(parts)}</svg>')


def region_legend() -> str:
    return (
        '<div class="cv-leg">'
        '<span class="cv-leg-i"><svg class="cv-g" width="22" height="10">'
        '<line x1="1" y1="5" x2="21" y2="5" stroke="#154a30" stroke-width="3"/></svg>'
        'trailing 12-month share</span>'
        '<span class="cv-leg-i"><svg class="cv-g" width="22" height="10">'
        '<line x1="1" y1="5" x2="21" y2="5" stroke="#2c7a50" stroke-width="2.4"/></svg>'
        'Fitted model</span>'
        '<span class="cv-leg-i"><svg class="cv-g" width="14" height="10">'
        '<circle cx="7" cy="5" r="2.2" fill="#55534c" fill-opacity=".55"/></svg>'
        'single month</span>'
        '<span class="cv-leg-note">no confidence band available</span>'
        '<span class="cv-leg-note">The curve is a model, not a forecast.</span>'
        '</div>')


def _crossings_state(frame: dict) -> dict:
    cross = frame.get("cross_all") or {}
    crossings = []
    for key, level in (("20", 0.2), ("50", 0.5), ("80", 0.8)):
        year = cross.get(key)
        if year is not None and math.isfinite(float(year)):
            crossings.append({"level": level, "fit": float(year), "ci": None})
    return {
        "quotable": bool(crossings),
        "flat": False,
        "band_ok": False,
        "rel": {"status": "ok", "reasons": [], "swing": 0},
        "crossings": crossings,
        "data_per": frame.get("data_per") or frame.get("date") or "",
    }


def load_members(slug: str) -> tuple[list[dict], list[dict], dict[str, float]]:
    params = sb.load_params(REPO / "params.csv")
    weights = sb.load_weights(REPO / "weights.csv")
    groups = sb.resolve_groups(params, weights)
    if slug not in groups:
        raise KeyError(f"unknown region {slug}")
    members = []
    for country in groups[slug]:
        path = _csv_for(country)
        rows = mc.whole_rows(str(path.relative_to(REPO))) if path.is_file() else []
        members.append({
            "country": country,
            "weight": _weight(weights, country),
            "rows": rows,
        })
    return members, params, weights


def load(slug: str) -> dict:
    """Compute the region payload used to build a flyer and a social card."""
    label = REGION_LABELS.get(slug, slug.replace("_", " ").title())
    members, _, _ = load_members(slug)
    t, contrib, cov = pick_common_end(members)
    if not t or not contrib:
        raise RuntimeError(f"no common 12-month window for {slug}")
    share = weighted_share(contrib, t)
    if share is None:
        raise RuntimeError(f"could not form a weighted share for {slug}")
    prior_end = mc._shift(t, -12)
    prior = weighted_share(contrib, prior_end)
    # Same-set rule: omit the delta unless every contributor has the prior window.
    delta = (share - prior) if prior is not None else None
    latest = weighted_month(contrib, t)
    latest_yoy = weighted_month(contrib, prior_end)
    latest_delta = (latest - latest_yoy) if (latest is not None and latest_yoy is not None) else None

    rows = synthetic_rows(contrib, t)
    # Range from the same 12 months that enter the TTM.
    rng = None
    monthly = []
    for k in range(11, -1, -1):
        period = mc._shift(t, -k)
        s = weighted_month(contrib, period)
        if s is None:
            monthly = []
            break
        monthly.append((period, s))
    if len(monthly) == 12:
        lo_p, lo = min(monthly, key=lambda x: (x[1], x[0]))
        # first occurrence already from min of (share, period) — period tie-break
        # is chronological because YYYY-MM sorts. Prefer first occurrence by scan:
        lo_p, lo = next((p, s) for p, s in monthly if s == min(s for _, s in monthly))
        hi_p, hi = next((p, s) for p, s in monthly if s == max(s for _, s in monthly))
        rng = {"min": lo, "max": hi, "latest": monthly[-1][1], "end": t,
               "min_period": lo_p, "max_period": hi_p}

    short_note, long_note = coverage_notes(label, members, contrib, t, cov)

    figures: dict = {"ttm": {"share": share, "delta": delta, "end": t}}
    if latest is not None:
        figures["latest"] = {
            "row": {"period": t, "time_interval": "monthly"},
            "share": latest,
            "delta": latest_delta,
        }

    # Who-gained and the mix use a powertrain split on a member set that
    # keeps the headline BEV at one decimal. See choose_mix_split.
    choice = choose_mix_split(contrib, t, prior_end if prior is not None else None)
    mix_members = choice["members"]
    mix_bands = choice["bands"]
    mix_note = choice["note"]
    mix_note_long = choice.get("note_long") or mix_note
    shift = None
    if delta is not None and prior is not None:
        shift = split_shift(mix_members, t, prior_end, mix_bands, hev_full=False)
        if shift is None:
            # Fall back to a BEV / everything-else row on the headline set.
            shift = {
                "span": ((mc._shift(prior_end, -11), prior_end),
                         (mc._shift(t, -11), t)),
                "rows": [
                    {"key": "BEV", "label": "Battery electric",
                     "delta": delta, "after": share, "before": prior},
                    {"key": "REST", "label": "Everything else",
                     "delta": -delta, "after": 100 - share, "before": 100 - prior},
                ],
                "interval": "monthly",
                "bev_before": 0, "bev_after": 0,
            }

    backtest = _load_backtest(slug)
    frame = _pick_frame(backtest, t) if backtest else None
    years = (backtest or {}).get("years") or []
    model = (frame or {}).get("all", {}).get("bev") or []
    state = _crossings_state(frame) if frame else None
    model_per = (frame or {}).get("data_per") or ""

    def curve_builder(width, height, left):
        svg = build_region_curve_svg(rows, years, model, width, height, left)
        return svg, region_legend()

    side = ""
    sub = ("An S-curve fitted to the group's BEV share so far. It is this "
           "project's model, not an official forecast: a policy change or a "
           "stall is not in it.")
    if state and state["quotable"]:
        note = ""
        if model_per and model_per != t:
            note = (f'<p class="fm-note">Model fitted through '
                    f'{esc(mc.period_label(model_per, long=True))}.</p>')
        note += '<p class="fm-note">No confidence band available.</p>'
        side = (
            '<div class="fm-side"><div class="fm-head">The curve reaches</div>'
            f'<div class="fm">{flyer.build_miles(state)}</div>{note}</div>')
    elif frame:
        side = ('<div class="fm-side"><div class="fm-head">No projection</div>'
                '<p class="fm-none">The published model for this group does not '
                "name milestone years.</p></div>")
        sub = ("Battery-electric share of new registrations. The line is this "
               "project's fitted model for the group, not an official forecast.")

    mix = mix_points_for(mix_members, t, mix_bands)

    carriers, carrier_total = carrier_rows(contrib, t)

    acea = acea_for_brief(t) if slug == "eu" else None
    scope_note = (long_note + (" " + mix_note_long if mix_note_long else "")).strip()
    if acea and acea.get("hev") is not None:
        scope_note += (f" Mix and who-gained from members' national data; the HEV "
                       f"share is ACEA's own EU figure (year to date {acea['period']}, full "
                       f"and mild hybrids, from ACEA's monthly press release).")
    fm = {
        "country": label,
        "slug": slug,
        "region": True,
        "region_mix_points": mix,
        "source_name": "BEV Trajectory Gallery, weighted from member sources",
        "scope_note": scope_note.strip(),
        "coverage_note": short_note,
        "region_curve": curve_builder,
        "region_curve_side": side,
        "region_curve_sub": sub,
        "hev_split": "HEV" in mix_bands,
        # ACEA's own EU HEV share, printed beside (never inside) our split.
        "acea_hev": acea,
        "acea_html": acea_line(acea),
        "acea_social": acea_line(acea, social=True),
        # Locator map: every member of the group, in or out of the figure.
        "map_countries": [m["country"] for m in members],
        "mix_note": mix_note,
        "mix_note_long": mix_note_long,
    }
    return {
        "fm": fm,
        "rows": rows,
        "figures": figures,
        "shift": shift,
        "range": rng,
        "t": t,
        "coverage": cov,
        "contributors": [m["country"] for m in contrib],
        "members": [m["country"] for m in members],
        "excluded": [m["country"] for m in members
                     if m["country"] not in {c["country"] for c in contrib}],
        "share": share,
        "delta": delta,
        "latest": latest,
        "model_per": model_per,
        "n_contrib": len(contrib),
        "n_members": len(members),
        "carriers": carriers,
        "carrier_total": carrier_total,
        "label": label,
        "mix_members": [m["country"] for m in mix_members],
        "mix_bands": mix_bands,
        "mix_note": mix_note,
    }


def carrier_rows(contrib: list[dict], t: str,
                 limit: int = 5) -> tuple[list[dict], float]:
    """Members ranked by BEV volume contribution (weight × 12-month share)."""
    items = []
    for m in contrib:
        win = window_ending(m["rows"], t)
        if not win:
            continue
        items.append({
            "country": m["country"],
            "bev_share": win["share"],
            "weight": m["weight"],
            "contrib": m["weight"] * win["share"],
        })
    total = sum(i["contrib"] for i in items)
    if total <= 0:
        return [], 0.0
    items.sort(key=lambda i: -i["contrib"])
    for i in items:
        i["of_group"] = 100.0 * i["contrib"] / total
    return items, total


def build_carriers_html(info: dict, width: float = 702, base: float = 17,
                        fs: float = 13, row_h: float = 20,
                        social: bool = False) -> tuple[str, int]:
    """Who-carries block: flag, name, member BEV share, 0–100% bar, share of
    the group's BEV total. Visual language matches the brand rows."""
    items = list(info.get("carriers") or [])
    if not items:
        return "", 0
    top, rest_items = items[:5], items[5:]
    rest = sum(i["of_group"] for i in rest_items)
    rows_data = list(top)
    show_rest = rest >= 0.05
    logo_slot = 24 if not social else 36
    name_w = 120 if not social else 180
    pct_w = 56 if not social else 72
    bev_w = 56 if not social else 72
    style = (f'--ms-logo:{logo_slot}px;--ms-name:{name_w}px;--ms-pct:{pct_w}px;'
             f'--ms-row:{row_h:.0f}px')
    head = (
        f'<div class="wc-head" style="grid-template-columns:'
        f'calc(var(--ms-logo) + 8px + var(--ms-name)) {bev_w}px minmax(0,1fr) var(--ms-pct)">'
        f'<span></span><span>BEV share</span><span></span>'
        f'<span>of group BEV</span></div>')
    out = []
    colours = mstr.SEGMENT
    for i, row in enumerate(rows_data):
        src = mc.flag_src(country=row["country"]) or ""
        flag = (f'<img class="wc-flag" src="{esc(src)}" alt="">' if src else "")
        colour = colours[min(i, len(colours) - 1)]
        out.append(
            f'<div class="wc-row" style="grid-template-columns:'
            f'calc(var(--ms-logo) + 8px + var(--ms-name)) {bev_w}px minmax(0,1fr) var(--ms-pct)">'
            f'<div class="ms-id"><div class="ms-logo-slot">{flag}</div>'
            f'<div class="ms-name">{esc(row["country"])}</div></div>'
            f'<div class="wc-bev">{esc(mc.share(row["bev_share"]))}</div>'
            f'<div class="ms-track" style="height:{max(8, 0.42*row_h):.0f}px"><span class="ms-fill" style="width:{row["of_group"]:.2f}%;'
            f'background:{colour}"></span></div>'
            f'<div class="ms-val">{esc(mstr._pct(row["of_group"]))}</div></div>')
    if show_rest:
        out.append(
            f'<div class="wc-row ms-rest" style="grid-template-columns:'
            f'calc(var(--ms-logo) + 8px + var(--ms-name)) {bev_w}px minmax(0,1fr) var(--ms-pct)">'
            f'<div class="ms-id"><div class="ms-logo-slot"></div>'
            f'<div class="ms-name ms-mute">other members</div></div>'
            f'<div class="wc-bev"></div>'
            f'<div class="ms-track" style="height:{max(8, 0.42*row_h):.0f}px"><span class="ms-fill" style="width:{rest:.2f}%;'
            f'background:{mstr.OTHERS}"></span></div>'
            f'<div class="ms-val">{esc(mstr._pct(rest))}</div></div>')
    n = len(rows_data) + (1 if show_rest else 0)
    height = 28 + 36 + 22 + n * row_h + max(0, n - 1) * 3  # heading + sub + head + rows
    through = mc.period_label(info["t"], long=True)
    sub = (
        "Largest members by battery-electric volume in this figure "
        "(registration weight × 12-month BEV share). Bars are each country's "
        "share of the group's BEV total, same window as the headline "
        f"(12 months to {through}).")
    if social:
        short = (f"Registration weight × 12-month BEV share, 12 months to {through}. "
                 f"Bars: share of the group's BEV total.")
        html = (
            f'<div class="sc-ms wc-list" style="{style}"><div class="sc-mshead">'
            f'Who carries it</div>'
            f'<p class="sc-msline" style="font-size:17px;line-height:1.35;'
            f'margin:0 0 8px;font-family:var(--font-ui),sans-serif;font-weight:400">'
            f'{esc(short)}</p>{head}{"".join(out)}</div>')
        height = 36 + 52 + 20 + n * row_h + max(0, n - 1) * 4
    else:
        html = (
            f'<section class="fl-sec wc-list" style="{style}"><h2>Who carries it</h2>'
            f'<p class="fl-sub">{esc(sub)}</p>{head}{"".join(out)}</section>')
    return html, int(round(height))


_REF_CACHE: list[dict] | None = None
REF_SPEC = (
    ("Norway", "norway", "country"),
    ("China", "china", "country"),
    ("EU", "eu", "region"),
    ("World", "world", "region"),
    ("Germany", "germany", "country"),
    ("USA", "usa", "country"),
)


def reference_points() -> list[dict]:
    """Honest last-12-month shares for the compare-strip highlights.

    Countries use ttm_window on the CSV (empty ≠ 0). Regions use the same
    weighted headline as the region briefs. A name is omitted when that
    window cannot be formed.
    """
    global _REF_CACHE
    if _REF_CACHE is not None:
        return _REF_CACHE
    out: list[dict] = []
    for name, slug, kind in REF_SPEC:
        if kind == "country":
            path = REPO / "data" / f"{name}.csv"
            win = (mc.ttm_window(mc.whole_rows(str(path.relative_to(REPO))))
                   if path.is_file() else None)
            if not win:
                continue
            out.append({"name": name, "slug": slug, "share": win["share"],
                        "end": win["end"], "kind": kind})
        else:
            info = load(slug)
            out.append({"name": name, "slug": slug, "share": info["share"],
                        "end": info["t"], "kind": kind,
                        "coverage": info["coverage"]})
    _REF_CACHE = out
    return out


def build(slug: str, theme_href: str, logo_href: str = "../../assets/brands",
          peers: list | None = None) -> tuple[str, str, dict]:
    """Return (flyer_html, social_html, info)."""
    info = load(slug)
    fm_fl = dict(info["fm"])
    fm_sc = dict(info["fm"])
    if mc.flag_filename(slug, info["fm"]["country"]):
        fm_fl.pop("mark_html", None)
        fm_sc.pop("mark_html", None)
    else:
        fm_fl["mark_html"] = region_mark(slug, "fl")
        fm_sc["mark_html"] = region_mark(slug, "sc")
    fm_fl["compare_highlights"] = reference_points()
    carriers_fl, _ = build_carriers_html(info, width=702, social=False)
    carriers_sc, sc_h = build_carriers_html(info, width=960, base=30, fs=20,
                                            row_h=28, social=True)
    fm_fl["carriers_html"] = carriers_fl
    fm_sc["carriers_social"] = (carriers_sc, sc_h)
    brief = flyer.build_flyer(fm_fl, info["rows"], info["shift"], info["figures"],
                              None, None, theme_href, peers=peers or [], market=None)
    social = social_card.build_social(fm_sc, info["rows"], info["figures"],
                                      None, None, None, "list", theme_href, logo_href)
    return brief, social, info


def check_acea(path: Path = ACEA_EU) -> int:
    """CI guard: 0 when ACEA's EU row is at most ACEA_MAX_LAG months behind
    the EU brief's data end, 1 otherwise (missing file included)."""
    members, _, _ = load_members("eu")
    t, contrib, _ = pick_common_end(members)
    acea = acea_eu_shares(path)
    lag = acea_lag_months(acea, t)
    if acea is None or lag is None:
        print(f"FAIL: no usable EU row in {path}")
        return 1
    msg = (f"ACEA EU figure {acea['period']} (to {acea['to']}); EU data ends {t}; "
           f"lag {lag} month(s), limit {ACEA_MAX_LAG}")
    if lag > ACEA_MAX_LAG:
        print(f"FAIL: {msg}. The monthly ACEA fetch (fetch-acea.yml) has not "
              "written a newer year-to-date row.")
        return 1
    print(f"ok: {msg}")
    return 0


if __name__ == "__main__":
    import sys
    if sys.argv[1:] == ["--check-acea"]:
        sys.exit(check_acea())
    sys.exit("usage: region_card.py --check-acea")
