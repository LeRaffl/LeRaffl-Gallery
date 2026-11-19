#!/usr/bin/env python3
"""The model-card sections of a country source page.

`build_source_pages.py` documents where a country's numbers come from. This
module adds what the numbers *say*, so that one page can be handed out as a
card with a reference date: the key figures, which powertrain gained and
which lost share, the latest periods as a table, and the fitted S-curve with
its milestone years.

Everything here is derived at build time from committed files and nothing is
hand-maintained: `data/<Country>.csv` (the source of truth), `params.csv`,
`weights.csv`, `bands/<slug>.json`, `manifest.json` and `footnotes.csv`. A
section the data cannot carry is left out, never drawn from zeros: an empty
fuel cell is unknown (AGENTS.md, invariant 4).

Two pieces mirror code elsewhere and must change together with it:
`band_slug()` mirrors `slug_country()` in R/data.R and `bandSlug()` in
index.html; `fit_reliability()` and `has_no_transition()` mirror
`fitReliability()` and `rowHasNoTransition()` in assets/fit_core.js.
"""

from __future__ import annotations

import csv
import datetime as dt
import html
import json
import itertools
import os
import math
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SITE = "https://leraffl.github.io/LeRaffl-Gallery"
GH_BLOB = "https://github.com/LeRaffl/LeRaffl-Gallery/blob/master"

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
MONTHS_LONG = ["January", "February", "March", "April", "May", "June", "July",
               "August", "September", "October", "November", "December"]

# Same hues as the mix chart in the poster, so one colour means one thing
# on the whole page.
COLORS = {
    "BEV": "#3d9a68", "PHEV": "#6f9ed4", "HEV": "#e0c36a", "MHEV": "#ecdca6",
    "PETROL": "#b3a48c", "DIESEL": "#8d897c", "FLEXFUEL": "#c9b27e",
    "ETHANOL": "#c9b27e", "LPG": "#bdb7a8", "CNG": "#bdb7a8", "GAS": "#bdb7a8",
    "REST": "#cfcabe",
}


def esc(value) -> str:
    return html.escape("" if value is None else str(value), quote=True)


# --------------------------------------------------------------------------
# Reading
# --------------------------------------------------------------------------

def num(row: dict, col: str) -> float | None:
    """A cell as a number. Empty or absent is None, never 0."""
    raw = row.get(col)
    if raw is None or str(raw).strip() == "":
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def month_index(period: str) -> int | None:
    found = re.match(r"^(\d{4})-(\d{2})$", period or "")
    if not found:
        return None
    return int(found.group(1)) * 12 + int(found.group(2)) - 1


def interval_of(row: dict) -> str:
    label = (row.get("time_interval") or "").strip().lower()
    return "monthly" if label == "monthly_est" else label


def is_estimated(row: dict) -> bool:
    return (row.get("time_interval") or "").strip().lower() == "monthly_est"


def whole_rows(data_file: str | None) -> list[dict]:
    """Every Whole row of the country CSV, oldest period first."""
    return series_rows(data_file, "Whole")


def series_rows(data_file: str | None, variant: str = "Whole") -> list[dict]:
    """Every row of one series in the CSV, oldest period first.

    Not every CSV is in period order (Malta's appends a late block after
    older rows), so "the last row" would not be the latest period. The sort
    is stable: rows of the same period keep their file order.
    """
    path = REPO / (data_file or "")
    if not data_file or not path.is_file():
        return []
    wanted = ("", "Whole") if variant in ("", "Whole", None) else (variant,)
    with path.open(encoding="utf-8") as fh:
        rows = [row for row in csv.DictReader(fh)
                if row.get("period") and row.get("variant") in wanted]
    return sorted(rows, key=lambda row: _period_key(row["period"]))


def _period_key(period: str) -> int:
    """Sort key: a month by its index, a bare year as its December."""
    idx = month_index(period)
    if idx is not None:
        return idx
    found = re.match(r"^(\d{4})$", period or "")
    return int(found.group(1)) * 12 + 11 if found else -1


def read_keyed(name: str) -> dict[tuple[str, str], dict]:
    path = REPO / name
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8") as fh:
        return {(row["country"], row["variant"]): row for row in csv.DictReader(fh)}


def band_slug(country: str, variant: str = "Whole") -> str:
    pairs = (("ü", "ue"), ("ö", "oe"), ("ä", "ae"), ("ß", "ss"), ("Ü", "Ue"),
             ("Ö", "Oe"), ("Ä", "Ae"), ("ı", "i"), ("İ", "I"), ("ş", "s"),
             ("Ş", "S"), ("ğ", "g"), ("Ğ", "G"), ("ç", "c"), ("Ç", "C"))

    def part(text: str) -> str:
        for a, b in pairs:
            text = text.replace(a, b)
        return re.sub(r"[^A-Za-z0-9]+", "_", text).lower()

    base = part(country or "")
    return base if variant in ("", "Whole", None) else f"{base}_{part(variant)}"


def flag_filename(slug: str = "", country: str = "") -> str | None:
    """Basename under assets/flags/ if a PNG exists.

    Page slugs sometimes use hyphens (`new-zealand`) while flag files use
    the underscore form from band_slug (`new_zealand.png`). Try both, then
    the country name.
    """
    seen: list[str] = []
    for raw in (slug, (slug or "").replace("-", "_"),
                band_slug(country) if country else ""):
        if raw and raw not in seen:
            seen.append(raw)
    for name in seen:
        if (REPO / "assets" / "flags" / f"{name}.png").is_file():
            return f"{name}.png"
    return None


def flag_src(slug: str = "", country: str = "",
             prefix: str = "../../assets/flags") -> str | None:
    name = flag_filename(slug, country)
    return f"{prefix}/{name}" if name else None


def flag_img(slug: str = "", country: str = "", cls: str = "fl-flag",
             prefix: str = "../../assets/flags", alt: str = "") -> str:
    src = flag_src(slug, country, prefix)
    if not src:
        return ""
    return f'<img class="{esc(cls)}" src="{esc(src)}" alt="{esc(alt)}">'


def load_bands(country: str) -> dict | None:
    path = REPO / "bands" / f"{band_slug(country)}.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def latest_images(country: str) -> list[dict]:
    """The newest chart of each type for the country's Whole series."""
    path = REPO / "manifest.json"
    if not path.is_file():
        return []
    try:
        images = json.loads(path.read_text(encoding="utf-8")).get("images") or []
    except (OSError, ValueError):
        return []
    newest: dict[str, dict] = {}
    for item in images:
        if item.get("country") != country:
            continue
        kind = item.get("type") or ""
        key = (item.get("period") or "", item.get("date") or "")
        seen = newest.get(kind)
        if not seen or key > (seen.get("period") or "", seen.get("date") or ""):
            newest[kind] = item
    order = ("ICE_BEV", "share", "ttm_shares", "time")
    return [newest[kind] for kind in order if kind in newest]


def footnote(country: str, variant: str = "Whole") -> str:
    path = REPO / "footnotes.csv"
    if not path.is_file():
        return ""
    with path.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if row.get("country") == country and row.get("variant") == variant:
                return (row.get("footnote") or "").strip()
    return ""


# --------------------------------------------------------------------------
# Formatting
# --------------------------------------------------------------------------

def period_label(period: str, long: bool = False) -> str:
    idx = month_index(period)
    if idx is None:
        return period
    names = MONTHS_LONG if long else MONTHS
    return f"{names[idx % 12]} {idx // 12}"



def generated_stamp(now: dt.datetime | None = None) -> str:
    """UTC clock time for a 'Generated …' footer, reproducible when pinned.

    Honours SOURCE_DATE_EPOCH (seconds since the Unix epoch, the standard
    reproducible-build pin) or, if that is unset, GENERATED_AT (an ISO-8601
    or 'YYYY-MM-DD HH:MM' string, treated as UTC when it has no zone).
    Otherwise uses the current UTC time. Always printed as
    'YYYY-MM-DD HH:MM UTC'. Tests and unchanged rebuilds should set one of
    the env vars (or pass `now`) so the line does not drift.
    """
    when = now if now is not None else _generated_now()
    if when.tzinfo is None:
        when = when.replace(tzinfo=dt.timezone.utc)
    else:
        when = when.astimezone(dt.timezone.utc)
    return when.strftime("%Y-%m-%d %H:%M UTC")


def generated_line(through_period: str | None = "") -> str:
    """'Generated 2026-11-17 21:38 UTC · data through Oct 2026'."""
    line = f"Generated {generated_stamp()}"
    if through_period:
        label = (period_label(through_period)
                 if month_index(through_period) is not None else through_period)
        line += f" · data through {label}"
    return line


def _generated_now() -> dt.datetime:
    raw = (os.environ.get("SOURCE_DATE_EPOCH") or "").strip()
    if raw:
        try:
            return dt.datetime.fromtimestamp(int(raw), dt.timezone.utc)
        except (ValueError, OverflowError, OSError):
            pass
    raw = (os.environ.get("GENERATED_AT") or "").strip()
    if raw:
        parsed = _parse_generated_at(raw)
        if parsed is not None:
            return parsed
    return dt.datetime.now(dt.timezone.utc)


def _parse_generated_at(raw: str) -> dt.datetime | None:
    text = raw.replace(" UTC", "").strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    if "T" not in text and " " in text:
        text = text.replace(" ", "T", 1)
    try:
        when = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=dt.timezone.utc)
    return when


def row_label(row: dict, long: bool = False) -> str:
    label = period_label(row["period"], long)
    interval = interval_of(row)
    if interval == "quarterly" and month_index(row["period"]) is not None:
        return f"Quarter to {label}"
    return label


def units(value: float) -> str:
    if value >= 9_950_000:
        return f"{value / 1e6:.1f} M"
    if value >= 1_000_000:
        return f"{value / 1e6:.2f} M"
    return f"{value:,.0f}"


def share(value: float) -> str:
    """A share in percent. Two decimals below 1 % so small markets do not read 0.0."""
    if 0 < abs(value) < 0.995:
        return f"{value:.2f}%"
    return f"{value:.1f}%"


def points(value: float) -> str:
    """A signed change in percentage points."""
    if abs(value) < 0.05:
        return "±0"
    return ("+" if value > 0 else "−") + f"{abs(value):.1f}"


def growth_phrase(pct: float) -> str:
    """Year-on-year change of a count (not of a share). From +100 %
    (doubled or more) as a multiplier: ×9.6, not +855 %."""
    if pct >= 100:
        times = 1 + pct / 100.0
        if abs(times - round(times)) < 0.05:
            return f"×{times:.0f}"
        return f"×{times:.1f}"
    if abs(pct) < 0.05:
        return "±0%"
    sign = "+" if pct > 0 else "−"
    num_ = f"{abs(pct):.0f}" if abs(pct) >= 10 else f"{abs(pct):.1f}"
    return f"{sign}{num_}%"


def year_text(value: float | None) -> str:
    if value is None or not math.isfinite(value):
        return "—"
    return str(int(math.floor(value)))


# --------------------------------------------------------------------------
# The two windows
# --------------------------------------------------------------------------

def tail_windows(rows: list[dict]) -> dict | None:
    """Last 12 months against the 12 before (or 4 quarters against 4).

    None unless the tail of the series is one cadence without a gap.
    """
    if not rows:
        return None
    interval = interval_of(rows[-1])
    size, step = {"monthly": (12, 1), "quarterly": (4, 3)}.get(interval, (0, 0))
    if not size or len(rows) < 2 * size:
        return None
    tail = rows[-2 * size:]
    if any(interval_of(row) != interval for row in tail):
        return None
    idx = [month_index(row["period"]) for row in tail]
    if None in idx or any(b - a != step for a, b in zip(idx, idx[1:])):
        return None
    return {
        "interval": interval,
        "before": tail[:size],
        "after": tail[size:],
        "estimated": any(is_estimated(row) for row in tail),
        # First month covered by a window is `step - 1` months before its first label.
        "span": tuple(
            (_shift(part[0]["period"], -(step - 1)), part[-1]["period"])
            for part in (tail[:size], tail[size:])),
    }


def ttm_window(rows: list[dict]) -> dict | None:
    """BEV share of the last 12 months (or 4 quarters), from the CSV only.

    Only a full window that ends at the series' latest period counts: one
    cadence, no gap, BEV and TOTAL filled in every period. Anything less is
    unknown, not an older window passed off as the latest one.
    """
    if not rows:
        return None
    interval = interval_of(rows[-1])
    size, step = {"monthly": (12, 1), "quarterly": (4, 3)}.get(interval, (0, 0))
    if not size or len(rows) < size:
        return None
    window = rows[-size:]
    if any(interval_of(row) != interval for row in window):
        return None
    idx = [month_index(row["period"]) for row in window]
    if None in idx or any(b - a != step for a, b in zip(idx, idx[1:])):
        return None
    total, bev = _full_sum(window, "TOTAL"), _full_sum(window, "BEV")
    if total is None or bev is None or total <= 0:
        return None
    return {"share": 100 * bev / total, "total": total, "bev": bev,
            "end": window[-1]["period"], "interval": interval}


YTD_MIN_MONTHS = 3      # fewer months would be a single-month figure in disguise


def ytd_window(rows: list[dict]) -> dict | None:
    """BEV share of the current year so far: every month from January to the
    latest period present, monthly, BEV and TOTAL filled; else None."""
    if not rows or interval_of(rows[-1]) != "monthly":
        return None
    last = month_index(rows[-1]["period"])
    if last is None:
        return None
    year, n = last // 12, last % 12 + 1
    if n < YTD_MIN_MONTHS or len(rows) < n:
        return None
    window = rows[-n:]
    idx = [month_index(r["period"]) for r in window]
    if (any(interval_of(r) != "monthly" for r in window)
            or idx != list(range(year * 12, year * 12 + n))):
        return None
    total, bev = _full_sum(window, "TOTAL"), _full_sum(window, "BEV")
    if not total or bev is None:
        return None
    return {"share": 100 * bev / total, "from": window[0]["period"],
            "to": window[-1]["period"], "year": year}


def share_range(rows: list[dict]) -> dict | None:
    """Min and max of the last 12 single-month BEV shares.

    Only a full monthly window that ends at the series' latest period,
    with BEV and TOTAL filled in every month. Anything less is unknown,
    not a shorter window and not a 0.
    """
    if not rows or interval_of(rows[-1]) != "monthly" or len(rows) < 12:
        return None
    window = rows[-12:]
    if any(interval_of(row) != "monthly" for row in window):
        return None
    idx = [month_index(row["period"]) for row in window]
    if None in idx or any(b - a != 1 for a, b in zip(idx, idx[1:])):
        return None
    shares = [_bev_share(row) for row in window]
    if any(s is None for s in shares):
        return None
    lo, hi = min(shares), max(shares)
    # First occurrence in the window on a tie, so the sentence names a
    # real month rather than the latest of several matching ones.
    min_i = next(i for i, s in enumerate(shares) if s == lo)
    max_i = next(i for i, s in enumerate(shares) if s == hi)
    return {"min": lo, "max": hi, "latest": shares[-1],
            "end": window[-1]["period"],
            "min_period": window[min_i]["period"],
            "max_period": window[max_i]["period"]}


def range_sentence(rng: dict, short: bool = False) -> str:
    """Name the min and max months of the last-12-month range. `short` is
    the social card's one-line form."""
    lo, hi = rng["min"], rng["max"]
    a = period_label(rng["min_period"])
    b = period_label(rng["max_period"])
    if short:
        return (f"Single months, last 12: {lo:.1f}% ({a}) to "
                f"{hi:.1f}% ({b}).")
    return (f"BEV share fluctuated between {lo:.1f}% ({a}) and "
            f"{hi:.1f}% ({b}) over the last 12 months.")


def range_bar_svg(rng: dict, width: float = 120, height: float = 16) -> str:
    """Tiny bar for the last-12-month range; marker at the latest month."""
    lo, hi, last = rng["min"], rng["max"], rng["latest"]
    pad, mid = 3.5, height / 2
    inner = max(1.0, width - 2 * pad)
    span = hi - lo

    def x_of(v: float) -> float:
        if span <= 0:
            return pad + inner / 2
        return pad + inner * (v - lo) / span

    x = x_of(last)
    return (
        f'<svg class="rg-bar" width="{width:.0f}" height="{height:.0f}" '
        f'viewBox="0 0 {width:.0f} {height:.0f}" aria-hidden="true">'
        f'<rect x="{pad}" y="{mid - 2.2:.1f}" width="{inner:.1f}" height="4.4" rx="2.2" fill="#b9b6ae"/>'
        f'<circle cx="{x:.1f}" cy="{mid:.1f}" r="5" fill="#154a30"/>'
        f'<circle cx="{x:.1f}" cy="{mid:.1f}" r="2.2" fill="#fdfdfc"/>'
        f'</svg>')


def range_chip(rng: dict, width: float = 120, height: float = 16,
               bar: bool = False) -> str:
    """Sentence naming the min and max months. The tiny bar is off by
    default: the sentence is enough on its own."""
    label = range_sentence(rng)
    if not bar:
        return f'<span class="rg rg-sent">{esc(label)}</span>'
    return (f'<span class="rg rg-sent">{esc(label)}'
            f'{range_bar_svg(rng, width, height)}</span>')


def window_span_label(end: str, months: int = 12) -> str:
    """'Nov 2025–Oct 2026' for a window of `months` ending at `end`."""
    start = _shift(end, -(months - 1))
    return f"{period_label(start)}–{period_label(end)}"


def vs_prior_phrase(end: str) -> str:
    """The last 12 months against the 12 before, with both ends named."""
    return f"{window_span_label(end)} vs the 12 months before"


def _shift(period: str, months: int) -> str:
    idx = month_index(period) + months
    return f"{idx // 12:04d}-{idx % 12 + 1:02d}"


def _full_sum(rows: list[dict], col: str) -> float | None:
    """Sum of a column, or None when any row leaves it empty."""
    total = 0.0
    for row in rows:
        value = num(row, col)
        if value is None:
            return None
        total += value
    return total


def _used(rows: list[dict], col: str) -> bool:
    return any(num(row, col) is not None for row in rows)


# Named columns after the hybrids, in display order.
_COMBUSTION = (
    ("PETROL", "Petrol"), ("DIESEL", "Diesel"), ("FLEXFUEL", "Flex-fuel"),
    ("ETHANOL", "Ethanol"), ("LPG", "LPG"), ("CNG", "CNG"), ("GAS", "Gas"),
)


def powertrain_shift(rows: list[dict], hev_full: bool = False) -> dict | None:
    """Share of each powertrain in the two windows, and the change.

    A column is its own row only when every row of both windows fills it.
    Everything not named lands in one residual row (`TOTAL − named`), so the
    changes always sum to zero and nothing is counted twice.
    """
    windows = tail_windows(rows)
    if not windows:
        return None
    both = windows["before"] + windows["after"]
    sums = {}
    for key, part in (("before", windows["before"]), ("after", windows["after"])):
        total = _full_sum(part, "TOTAL")
        bev = _full_sum(part, "BEV")
        if total is None or bev is None or total <= 0:
            return None
        sums[key] = {"TOTAL": total, "BEV": bev}

    groups = [("BEV", "Battery electric", ("BEV",))]
    if _full_sum(both, "PHEV") is not None:
        # EREV folds into PHEV, as in the three-curve chart. A window that
        # fills EREV only in part cannot be added up, so plug-ins then stay
        # in the residual rather than showing a PHEV row that lacks them.
        erev_used = _used(both, "EREV")
        if not erev_used:
            groups.append(("PHEV", "Plug-in hybrid", ("PHEV",)))
        elif _full_sum(both, "EREV") is not None:
            groups.append(("PHEV", "Plug-in hybrid incl. range extenders",
                           ("PHEV", "EREV")))
    hev_known = _full_sum(both, "HEV") is not None
    if hev_known:
        groups.append(("HEV", "Full hybrid" if hev_full else "Hybrid", ("HEV",)))
    if _full_sum(both, "MHEV") is not None:
        groups.append(("MHEV", "Mild hybrid", ("MHEV",)))
    split = (_full_sum(both, "PETROL") is not None
             and _full_sum(both, "DIESEL") is not None)
    if split:
        for col, label in _COMBUSTION:
            if _full_sum(both, col) is None:
                continue
            biggest = max(_full_sum(windows[key], col) / sums[key]["TOTAL"]
                          for key in ("before", "after"))
            if col in ("PETROL", "DIESEL") or biggest >= 0.005:
                groups.append((col, label, (col,)))

    plug_known = any(key == "PHEV" for key, _, _ in groups)
    if split:
        rest_label = "Other fuels"
    elif hev_known and plug_known:
        rest_label = "Petrol, diesel and other combustion"
    elif hev_known:
        rest_label = "Combustion and anything not split out"
    else:
        rest_label = "Combustion incl. hybrids"

    out = []
    named = {"before": 0.0, "after": 0.0}
    for key, label, cols in groups:
        item = {"key": key, "label": label}
        for when in ("before", "after"):
            value = sum(_full_sum(windows[when], col) for col in cols)
            named[when] += value
            item[when] = 100 * value / sums[when]["TOTAL"]
        item["delta"] = item["after"] - item["before"]
        out.append(item)
    rest = {"key": "REST", "label": rest_label}
    for when in ("before", "after"):
        rest[when] = 100 * (sums[when]["TOTAL"] - named[when]) / sums[when]["TOTAL"]
    # Named columns that add up to more than TOTAL overlap each other (a
    # subset column, a scope mismatch). Do not draw a picture of that.
    if min(rest["before"], rest["after"]) < -0.5:
        return None
    rest["before"], rest["after"] = max(0.0, rest["before"]), max(0.0, rest["after"])
    rest["delta"] = rest["after"] - rest["before"]
    if not split or max(rest["before"], rest["after"]) >= 0.05:
        out.append(rest)
    return {
        "rows": out,
        "interval": windows["interval"],
        "span": windows["span"],
        "estimated": windows["estimated"],
        "total_before": sums["before"]["TOTAL"],
        "total_after": sums["after"]["TOTAL"],
        "bev_after": sums["after"]["BEV"],
        "bev_before": sums["before"]["BEV"],
    }


def _join(parts: list[str]) -> str:
    if len(parts) <= 1:
        return "".join(parts)
    return ", ".join(parts[:-1]) + " and " + parts[-1]


def shift_sentence(shift: dict) -> str:
    """One plain sentence: who lost, who gained."""
    moved = [row for row in shift["rows"] if abs(row["delta"]) >= 0.3]
    if not moved:
        return "No powertrain moved by more than 0.3 points."
    gains = sorted((r for r in moved if r["delta"] > 0), key=lambda r: -r["delta"])
    losses = sorted((r for r in moved if r["delta"] < 0), key=lambda r: r["delta"])

    def phrase(items: list[dict]) -> str:
        return _join([f"{r['label'].lower() if i else r['label']} "
                      f"{abs(r['delta']):.1f}" for i, r in enumerate(items[:3])])

    parts = []
    if losses:
        parts.append(f"Lost share: {phrase(losses)}.")
    if gains:
        parts.append(f"Gained: {phrase(gains)}.")
    return " ".join(parts) + " In percentage points of all new registrations."


def build_shift(shift: dict | None) -> str:
    if not shift:
        return ""
    rows = shift["rows"]
    neg = max([-r["delta"] for r in rows] + [0.0])
    pos = max([r["delta"] for r in rows] + [0.0])
    span = (neg + pos) or 1.0
    # Zero sits where the data puts it, kept off the edges so a one-sided
    # market still shows which side is which.
    zero = min(78.0, max(22.0, 100 * neg / span))
    scale = min(zero / neg if neg else 1e9, (100 - zero) / pos if pos else 1e9)
    body = []
    for row in rows:
        width = abs(row["delta"]) * scale
        left = zero if row["delta"] >= 0 else zero - width
        color = COLORS.get(row["key"], COLORS["REST"])
        body.append(
            '<div class="gl-row" role="row">'
            f'<span class="gl-name" role="cell">{esc(row["label"])}</span>'
            f'<span class="gl-pp" role="cell">{points(row["delta"])}</span>'
            f'<span class="gl-lvl" role="cell">{share(row["before"])} → '
            f'<b>{share(row["after"])}</b></span>'
            '<span class="gl-track" role="presentation">'
            f'<i class="gl-zero" style="left:{zero:.2f}%"></i>'
            f'<i class="gl-bar" style="left:{left:.2f}%;width:{width:.2f}%;'
            f'background:{color}"></i></span></div>')
    (b0, b1), (a0, a1) = shift["span"]
    what = "12 months" if shift["interval"] == "monthly" else "four quarters"
    keys = {row["key"] for row in rows}
    folded = (" This source does not split hybrids out, so they are inside the "
              "combustion rows." if "HEV" not in keys and "PETROL" in keys else "")
    est = (" Some months in these windows are estimated from annual data."
           if shift["estimated"] else "")
    return (
        '<section id="shift"><h2>Who gained, who lost</h2>'
        f'<p class="card-line">{esc(shift_sentence(shift))}</p>'
        '<div class="gl" role="table" aria-label="Change in share by powertrain">'
        '<div class="gl-row gl-head" role="row">'
        '<span class="gl-name" role="columnheader">Powertrain</span>'
        '<span class="gl-pp" role="columnheader">Change</span>'
        '<span class="gl-lvl" role="columnheader">Share before → now</span>'
        '<span class="gl-track" role="presentation"></span></div>'
        f'{"".join(body)}</div>'
        f'<p class="fig-note">Share of new registrations in the last {what} '
        f'({esc(period_label(a0))} to {esc(period_label(a1))}) against the '
        f'{what} before ({esc(period_label(b0))} to {esc(period_label(b1))}). '
        'The changes add up to zero: what one row gains, the others lose. '
        'A row appears only where the source fills that column in every '
        f'period of both windows; everything else is in the last row.{folded}{est}</p>'
        '</section>')


# --------------------------------------------------------------------------
# Fit reliability (mirror of assets/fit_core.js)
# --------------------------------------------------------------------------

FIT_UNSETTLED_SWING = 25
FIT_PROVISIONAL_SWING = 5
FIT_COLLAPSE_SPAN = 3
FIT_COLLAPSE_OBS = 0.80
FIT_STALE_MONTHS = 12
MIN_TRANSITION_SLOPE = 0.01

REASON_TEXT = {
    "unsettled": "the 80% date still moves by more than 25 years from one re-fit to the next",
    "collapsed": "the curve is a near-vertical step the data has not reached",
    "stale": "the newest data point is more than twelve months old",
}


def _f(raw) -> float:
    try:
        return float(str(raw).strip().replace(",", "."))
    except (TypeError, ValueError):
        return math.nan


def fit_share(year: float, v1: float, v2: float, t0: float) -> float:
    """BEV share of the fitted curve at a calendar decimal year."""
    z = year - t0
    if z <= 0:
        return 0.0
    try:
        return 1 - math.exp(v1 * z ** v2)
    except OverflowError:
        return 1.0


def fit_year(level: float, v1: float, v2: float, t0: float) -> float:
    """Calendar year at which the fitted curve reaches `level` (0..1)."""
    if not (0 < level < 1 and v1 < 0 and v2 > 0):
        return math.nan
    return t0 + (math.log(1 - level) / v1) ** (1 / v2)


def has_no_transition(row: dict) -> bool:
    ttm = _f(row.get("ttm_bev_share")) if str(row.get("ttm_bev_share") or "").strip() else math.nan
    if math.isfinite(ttm) and ttm < 0.01:
        return True
    if math.isfinite(ttm) and ttm >= 0.05:
        return False
    v1, v2, t0 = _f(row.get("v1")), _f(row.get("v2")), _f(row.get("t0"))
    if not (math.isfinite(v1) and math.isfinite(v2)) or v1 >= 0:
        return True
    try:
        if v2 > 1:
            inv = (-v1) ** (1 / v2)
            u = ((v2 - 1) / v2) ** (1 / v2)
            slope = v2 * inv * u ** (v2 - 1) * math.exp(-u ** v2)
        else:
            idx = month_index(row.get("data_per") or "")
            if idx is None or not math.isfinite(t0):
                return True
            z = idx / 12 - t0
            if z <= 0:
                return True
            slope = abs(v1) * v2 * z ** (v2 - 1) * math.exp(v1 * z ** v2)
    except (OverflowError, ZeroDivisionError, ValueError):
        return True
    return not math.isfinite(slope) or slope < MIN_TRANSITION_SLOPE


def fit_reliability(row: dict, today: dt.date | None = None) -> dict:
    v1, v2 = _f(row.get("v1")), _f(row.get("v2"))
    obs = _f(row.get("ttm_bev_share")) if str(row.get("ttm_bev_share") or "").strip() else math.nan
    swing = math.nan
    if "refit_swing" in row:
        raw = str(row.get("refit_swing") or "").strip()
        swing = _f(raw) if raw and not re.match(r"^-?inf(inity)?$", raw, re.I) else math.inf
        if math.isnan(swing):
            swing = math.inf
    valid = math.isfinite(v1) and v1 < 0 and math.isfinite(v2) and v2 > 0
    span = fit_year(0.8, v1, v2, 0) - fit_year(0.1, v1, v2, 0) if valid else math.nan
    reasons = []
    if swing > FIT_UNSETTLED_SWING:
        reasons.append("unsettled")
    if not valid or (span < FIT_COLLAPSE_SPAN and not obs >= FIT_COLLAPSE_OBS):
        reasons.append("collapsed")
    idx = month_index(row.get("data_per") or "")
    if idx is not None:
        today = today or dt.date.today()
        if today.year * 12 + today.month - 1 - idx > FIT_STALE_MONTHS:
            reasons.append("stale")
    status = "excluded" if reasons else (
        "provisional" if swing > FIT_PROVISIONAL_SWING else "ok")
    return {"status": status, "reasons": reasons, "swing": swing}


def model_state(param: dict | None, bands: dict | None,
                today: dt.date | None = None) -> dict | None:
    """What may be said about the fitted curve of one series."""
    if not param:
        return None
    v1, v2, t0 = _f(param.get("v1")), _f(param.get("v2")), _f(param.get("t0"))
    if not all(math.isfinite(x) for x in (v1, v2, t0)):
        return None
    flat = has_no_transition(param)
    rel = fit_reliability(param, today)
    quotable = not flat and rel["status"] != "excluded"
    band_ok = bool(quotable and bands and (bands.get("quality") or {}).get("usable")
                   and bands.get("data_per") == param.get("data_per"))
    crossings = []
    if quotable:
        by_level = {round(c.get("share", 0), 3): c for c in (bands or {}).get("crossing") or []}
        for level in (0.1, 0.2, 0.5, 0.8, 0.9):
            entry = {"level": level, "fit": fit_year(level, v1, v2, t0), "ci": None}
            band = by_level.get(level)
            if band_ok and band and band.get("ci"):
                entry["ci"] = tuple(band["ci"])
            crossings.append(entry)
    return {"v1": v1, "v2": v2, "t0": t0, "flat": flat, "rel": rel,
            "quotable": quotable, "band_ok": band_ok, "crossings": crossings,
            "data_per": param.get("data_per") or "",
            "model_date": param.get("model_date") or "",
            "band_reasons": (bands.get("quality") or {}).get("reasons") or [] if bands else [],
            "persistence": (bands or {}).get("persistence")}


# --------------------------------------------------------------------------
# Key figures
# --------------------------------------------------------------------------

def _bev_share(row: dict) -> float | None:
    bev, total = num(row, "BEV"), num(row, "TOTAL")
    if bev is None or not total:
        return None
    return 100 * bev / total


def key_figures(rows: list[dict], shift: dict | None, param: dict | None,
                weight: dict | None) -> dict:
    out: dict = {}
    if rows:
        last = rows[-1]
        now = _bev_share(last)
        if now is not None:
            out["latest"] = {"row": last, "share": now, "delta": None}
            idx = month_index(last["period"])
            for row in rows[:-1]:
                if (idx is not None and month_index(row["period"]) == idx - 12
                        and interval_of(row) == interval_of(last)):
                    before = _bev_share(row)
                    if before is not None:
                        out["latest"]["delta"] = now - before
            peers = [(s, row) for row in rows
                     if interval_of(row) == interval_of(last) and not is_estimated(row)
                     and (s := _bev_share(row)) is not None]
            if len(peers) >= 12:
                best, best_row = max(peers, key=lambda item: item[0])
                out["record"] = {"row": best_row, "share": best,
                                 "is_latest": best_row is last}
    if shift:
        bev = next(r for r in shift["rows"] if r["key"] == "BEV")
        out["ttm"] = {"share": bev["after"], "delta": bev["delta"], "end": shift["span"][1][1]}
        out["volume"] = {"total": shift["total_after"], "bev": shift["bev_after"],
                         "growth": 100 * (shift["total_after"] / shift["total_before"] - 1),
                         "interval": shift["interval"]}
    else:
        # Without the two-window comparison the 12-month figures still come
        # from the CSV, and only from a full window ending at its latest
        # period. params.csv's ttm_bev_share is not used here: it may be an
        # older complete window and does not say which one.
        window = ttm_window(rows)
        if window:
            out["ttm"] = {"share": window["share"], "delta": None, "end": window["end"]}
            out["volume"] = {"total": window["total"], "bev": window["bev"],
                             "growth": None, "interval": window["interval"]}
    return out


def _tile(value: str, label: str, sub: str = "") -> str:
    sub_html = f'<div class="s">{sub}</div>' if sub else ""
    return (f'<div class="stat"><div class="l">{esc(label)}</div>'
            f'<div class="n">{value}</div>{sub_html}</div>')


def build_glance(figures: dict, state: dict | None) -> str:
    tiles = []
    latest = figures.get("latest")
    if latest:
        sub = esc(row_label(latest["row"]))
        if latest["delta"] is not None:
            sub += f' · {points(latest["delta"])} points vs the 12 months before'
        tiles.append(_tile(esc(share(latest["share"])), "BEV share, latest period", sub))
    ttm = figures.get("ttm")
    if ttm:
        sub = f'through {esc(period_label(ttm["end"]))}'
        if ttm["delta"] is not None:
            sub += f' · {points(ttm["delta"])} points vs the 12 months before'
        tiles.append(_tile(esc(share(ttm["share"])), "BEV share, last 12 months", sub))
    volume = figures.get("volume")
    if volume:
        sub = "last 12 months"
        if volume["growth"] is not None:
            sub += f' · {points(volume["growth"])}% vs the 12 months before'
        tiles.append(_tile(esc(units(volume["total"])), "New registrations", sub))
        if volume["bev"] is not None:
            tiles.append(_tile(esc(units(volume["bev"])), "Battery electric registered",
                               "last 12 months"))
    record = figures.get("record")
    if record:
        sub = esc(row_label(record["row"]))
        if record["is_latest"]:
            sub += " · the latest period"
        tiles.append(_tile(esc(share(record["share"])), "Highest BEV share so far", sub))
    if state and state["quotable"]:
        # The next milestone the curve has not passed yet.
        idx = month_index(state["data_per"])
        today = idx / 12 if idx is not None else math.inf
        ahead = [c for c in state["crossings"]
                 if c["level"] >= 0.5 and math.isfinite(c["fit"]) and c["fit"] > today]
        if ahead:
            nxt = ahead[0]
            sub = "fitted S-curve, not a forecast"
            if nxt["ci"]:
                sub = f'95% confidence band {esc(_ci_text(nxt["ci"]))} · ' + sub
            tiles.append(_tile(esc(year_text(nxt["fit"])),
                               f'Curve reaches {nxt["level"] * 100:.0f}% BEV', sub))
    if not tiles:
        return ""
    return f'<section id="glance" class="glance"><div class="stats">{"".join(tiles)}</div></section>'


# --------------------------------------------------------------------------
# Latest periods table
# --------------------------------------------------------------------------

def build_latest_table(rows: list[dict], hev_full: bool, count: int = 13) -> str:
    tail = [row for row in rows[-count:] if num(row, "TOTAL")]
    if len(tail) < 2:
        return ""
    cols = [("BEV", "BEV")]
    if all(num(row, "PHEV") is not None for row in tail):
        erev = any(num(row, "EREV") is not None for row in tail)
        if not erev or all(num(row, "EREV") is not None for row in tail):
            cols.append(("PHEV", "PHEV + EREV" if erev else "PHEV"))
    if all(num(row, "HEV") is not None for row in tail):
        cols.append(("HEV", "HEV" if hev_full else "Hybrid"))
    body = []
    flagged = False
    for row in reversed(tail):
        total = num(row, "TOTAL")
        bev = num(row, "BEV")
        named = 0.0
        cells = []
        for key, _ in cols:
            value = num(row, key)
            if value is None:
                # Only BEV can be empty here (the other columns are shown
                # only when every row fills them): unknown, never 0.
                cells.append('<td class="num">—</td>')
                continue
            if key == "PHEV":
                value += num(row, "EREV") or 0.0
            named += value
            cells.append(f'<td class="num">{share(100 * value / total)[:-2]}</td>')
        mark = ""
        if is_estimated(row):
            mark, flagged = '<sup title="partly estimated">e</sup>', True
        rest = ("—" if bev is None else
                share(max(0.0, 100 * (total - named) / total))[:-2])
        body.append(
            f'<tr><th>{esc(row_label(row))}{mark}</th>'
            f'<td class="num">{total:,.0f}</td>'
            f'<td class="num">{"—" if bev is None else f"{bev:,.0f}"}</td>{"".join(cells)}'
            f'<td class="num">{rest}</td></tr>')
    head = "".join(f'<th class="num">{esc(label)}%</th>' for _, label in cols)
    note = ("<sup>e</sup> partly estimated from annual data, see the row's "
            "<code>notes</code> in the CSV. " if flagged else "")
    rest = "All other" if len(cols) == 3 else "Everything else"
    return (
        '<section id="latest"><h2>The latest periods</h2>'
        '<div class="scroll"><table class="vars latest">'
        '<tr><th>Period</th><th class="num">All registrations</th>'
        f'<th class="num">BEV</th>{head}<th class="num">{rest}%</th></tr>'
        f'{"".join(body)}</table></div>'
        f'<p class="fig-note">{note}Shares are the column divided by the '
        "source's own total. The last column is what remains after the columns "
        'to its left. Newest first.</p></section>')


# --------------------------------------------------------------------------
# The model
# --------------------------------------------------------------------------

def _ci_text(ci) -> str:
    if not ci:
        return "—"
    lo, hi = ci
    if lo is None and hi is None:
        return "not reached before 2100"
    if hi is None:
        return f"{year_text(lo)} or later"
    if lo is None:
        return f"by {year_text(hi)}"
    a, b = year_text(lo), year_text(hi)
    return a if a == b else f"{a}–{b}"


def _sci(value: float) -> str:
    mantissa, exponent = f"{value:.3e}".split("e")
    return f"{mantissa.replace('-', '−')} × 10<sup>{int(exponent)}</sup>".replace(
        "<sup>-", "<sup>−")


# Observed shares are drawn as a step line, one flat step per period.
# STEP_VOLUME_OPACITY: a step's opacity follows the registrations of its
# period (lighter = fewer), so a tiny month does not look as solid as a big
# one. Set to False for one even tone. STEP_LINE = False brings the old dots
# back everywhere.
STEP_LINE = True
STEP_VOLUME_OPACITY = True
STEP_MIN_OPACITY = 0.28
# The bold line: rolling 12-month share, only where a full window exists.
# With it on, the single months are drawn faint behind it.
STEP_TTM = True
STEP_FAINT = 0.38
# Do not let the x-axis run past the last data year plus this many years
# (a slow fit can otherwise stretch to 2050+).
CURVE_HORIZON_YEARS = 15
TTM_STROKE = "#154a30"   # dark green; the fit stays #2c7a50


def step_legend(state: dict | None = None) -> str:
    """The words for the observed series, matching build_curve_svg."""
    if not STEP_LINE:
        return "Dots: observed share per period."
    if STEP_TTM:
        text = "Bold: trailing 12-month share; faint: single months"
    else:
        text = "Steps: observed share per period"
    if STEP_VOLUME_OPACITY:
        text += ", lighter = fewer registrations"
    return text + "."


def chart_legend(state: dict | None, model_note: bool = True) -> str:
    """Compact visual key for the step line, the months and the fit."""
    def step(color: str, width: float, opacity: float = 1.0) -> str:
        return (f'<svg class="cv-g" width="28" height="10" viewBox="0 0 28 10" aria-hidden="true">'
                f'<path d="M1 7h10V3h16" fill="none" stroke="{color}" stroke-width="{width}" '
                f'stroke-linejoin="round" stroke-opacity="{opacity}"/></svg>')

    def band() -> str:
        return ('<svg class="cv-g" width="28" height="10" viewBox="0 0 28 10" aria-hidden="true">'
                '<rect x="0" y="1" width="28" height="8" fill="#3d9a68" fill-opacity=".22"/>'
                '<path d="M0 5.5C8 7 20 3 28 5" fill="none" stroke="#2c7a50" stroke-width="1.6"/>'
                '</svg>')

    items = [
        f'{step(TTM_STROKE, 2.4)} trailing 12-month share',
        f'{step("#3a3935", 1.6, 0.55)} single month',
    ]
    if state and state.get("quotable"):
        if state.get("band_ok"):
            items.append(f'{band()} S-curve + 95% confidence band')
        else:
            items.append(f'{step("#2c7a50", 1.8)} S-curve fit')
            items.append('<span class="cv-leg-note">no confidence band available</span>')
        if model_note:
            note = "a model, not a forecast"
            if (state.get("rel") or {}).get("status") == "provisional":
                note = "provisional · " + note
            items.append(f'<span class="cv-leg-note">{note}</span>')
    else:
        items.append('<span class="cv-leg-note">No projection: no stable fit yet</span>')
    return ('<div class="cv-leg">' +
            "".join(f'<span class="cv-leg-i">{i}</span>' for i in items) +
            "</div>")


def _step_segments(rows: list[dict], x_of, y_of) -> list[str]:
    """One path per period: up/down from the previous level, then flat."""
    items = []
    for row in rows:
        idx, value = month_index(row["period"]), _bev_share(row)
        if idx is None or value is None:
            continue
        months = {"quarterly": 3}.get(interval_of(row), 1)
        total = num(row, "TOTAL")
        per_month = total / months if total else None
        # A period label is its last month: a quarter "2018-03" spans Jan-Mar.
        items.append((idx - (months - 1), idx + 1, value, per_month, is_estimated(row)))
    if not items:
        return []
    vols = sorted(v for *_, v, _ in items if v)
    ref = vols[min(len(vols) - 1, int(0.95 * len(vols)))] if vols else None
    out, prev = [], None
    for a, b, value, vol, est in items:
        op = 1.0
        if STEP_VOLUME_OPACITY and ref and vol:
            op = STEP_MIN_OPACITY + (1 - STEP_MIN_OPACITY) * min(1.0, vol / ref)
        if STEP_TTM:
            op *= STEP_FAINT
        x0, x1, y = x_of(a / 12), x_of(b / 12), y_of(value)
        if prev and prev[0] == a:
            # Contiguous: a thin, faint riser from the last level, so the
            # flat steps (and their volume tone) carry the reading.
            out.append(f'<path d="M{x0:.1f},{prev[1]:.1f}V{y:.1f}" class="cv-rise" '
                       f'stroke-opacity="{0.45 * min(op, prev[2]):.2f}"/>')
        cls = "cv-step cv-step-est" if est else "cv-step"
        out.append(f'<path d="M{x0:.1f},{y:.1f}H{x1:.1f}" class="{cls}" stroke-opacity="{op:.2f}"/>')
        prev = (b, y, op)
    return out


_CLIP_IDS = itertools.count(1)


def ttm_series(rows: list[dict]) -> list[tuple[int, int, float]]:
    """Rolling 12-month BEV share: (first month, month after, share) per period
    whose trailing 12 months (or 4 quarters) are complete: one cadence, no
    gap, BEV and TOTAL filled in every period. No window, no point."""
    out = []
    for i, row in enumerate(rows):
        interval = interval_of(row)
        size, step = {"monthly": (12, 1), "quarterly": (4, 3)}.get(interval, (0, 0))
        if not size or i + 1 < size:
            continue
        window = rows[i - size + 1:i + 1]
        if any(interval_of(r) != interval for r in window):
            continue
        idx = [month_index(r["period"]) for r in window]
        if None in idx or any(b - a != step for a, b in zip(idx, idx[1:])):
            continue
        total, bev = _full_sum(window, "TOTAL"), _full_sum(window, "BEV")
        if not total or bev is None:
            continue
        out.append((idx[-1] - (step - 1), idx[-1] + 1, 100 * bev / total))
    return out


def _ttm_path(series, x_of, y_of) -> str:
    d, prev_end, prev_y = [], None, None
    for a, b, share in series:
        y = y_of(share)
        if prev_end == a:
            d.append(f"V{y:.1f}H{x_of(b / 12):.1f}")
        else:
            d.append(f"M{x_of(a / 12):.1f},{y:.1f}H{x_of(b / 12):.1f}")
        prev_end, prev_y = b, y
    return "".join(d)


def first_year_over(rows: list[dict], level: float = 1.0) -> int | None:
    for row in rows:
        idx, value = month_index(row["period"]), _bev_share(row)
        if idx is not None and value is not None and value >= level:
            return idx // 12
    return None


def build_curve_svg(rows: list[dict], state: dict, bands: dict | None,
                    width: int = 720, height: int = 300, weak_fit: bool = True,
                    x_range: tuple[float, float] | None = None,
                    left: int = 42) -> str:
    """Observed shares and the fitted curve. `weak_fit=False` leaves the line
    of a fit that carries no dates off the chart instead of dashing it.
    `x_range` (start year, end year) overrides the default span."""
    observed = []
    for row in rows:
        idx, value = month_index(row["period"]), _bev_share(row)
        if idx is not None and value is not None:
            observed.append((idx / 12, value, is_estimated(row)))
    if len(observed) < 6:
        return ""
    v1, v2, t0 = state["v1"], state["v2"], state["t0"]
    data_end = observed[-1][0]
    start = math.floor(observed[0][0])
    reach = fit_year(0.9, v1, v2, t0)
    end = data_end + (CURVE_HORIZON_YEARS if weak_fit else 4)
    if state["quotable"] and math.isfinite(reach):
        end = min(max(reach + 2, data_end + 6), data_end + CURVE_HORIZON_YEARS)
    end = float(math.ceil(end))
    if x_range:
        start, end = float(x_range[0]), float(x_range[1])

    right, top, bottom = 10, 20, 26
    plot_w, plot_h = width - left - right, height - top - bottom

    def x_of(year: float) -> float:
        return left + plot_w * (year - start) / (end - start)

    def in_x(rows_):
        return [r for r in rows_ if (month_index(r["period"]) or 0) / 12 >= start]

    # Without a curve to show, zoom in on the observed shares.
    draw_fit = state["quotable"] or weak_fit
    ymax = 100.0
    if not draw_fit:
        peak = max(value for t, value, _ in observed if t >= start) * 1.15
        ymax = next((float(m) for m in (2, 4, 10, 20, 40, 100) if m >= peak), 100.0)

    def y_of(pct: float) -> float:
        return top + plot_h * (1 - max(0.0, min(ymax, pct)) / ymax)

    clip = f"cvclip{next(_CLIP_IDS)}"
    parts = [f'<defs><clipPath id="{clip}"><rect x="{left}" y="0" width="{plot_w}" '
             f'height="{top + plot_h}"/></clipPath></defs>']
    for mark in (ymax * k / 4 for k in range(5)):
        y = y_of(mark)
        parts.append(f'<line x1="{left}" y1="{y:.1f}" x2="{left + plot_w}" y2="{y:.1f}" class="cv-grid"/>')
        parts.append(f'<text x="{left - 6}" y="{y + 3.5:.1f}" text-anchor="end">{mark:g}%</text>')
    span = end - start
    step = 2 if span <= 20 else 5 if span <= 45 else 10
    year = int(math.ceil(start / step) * step)
    while year <= end:
        anchor = "end" if year == end else "start" if year == start else "middle"
        parts.append(f'<text x="{x_of(year):.1f}" y="{height - 8}" text-anchor="{anchor}">{year}</text>')
        year += step

    body = []
    if state["band_ok"] and bands:
        ts, (lo, hi) = bands.get("t") or [], (bands.get("ci") or [[], []])
        pts = [(t, a, b) for t, a, b in zip(ts, lo, hi)
               if a is not None and b is not None and start <= t <= end]
        if len(pts) > 2:
            path = [f"M{x_of(pts[0][0]):.1f},{y_of(100 * pts[0][2]):.1f}"]
            path += [f"L{x_of(t):.1f},{y_of(100 * b):.1f}" for t, _, b in pts[1:]]
            path += [f"L{x_of(t):.1f},{y_of(100 * a):.1f}" for t, a, _ in reversed(pts)]
            body.append(f'<path d="{" ".join(path)} Z" class="cv-ci"/>')

    xd = x_of(data_end)
    parts.append(f'<line x1="{xd:.1f}" y1="{top}" x2="{xd:.1f}" y2="{top + plot_h}" class="cv-now"/>')
    side = "end" if xd > left + plot_w * 0.5 else "start"
    off = -5 if side == "end" else 5
    # Keep the label off the points, and off a wide future band: below them
    # once the series is high, or when the now-line sits in the left half.
    recent = [v for t, v, _ in observed if t >= data_end - 2] or [0.0]
    if max(recent) >= 0.85 * ymax or (state["quotable"] and xd < left + plot_w * 0.45):
        label_y = top + plot_h - 6
    else:
        label_y = top + 12
    parts.append(f'<text x="{xd + off:.1f}" y="{label_y}" text-anchor="{side}">'
                 f'data through {esc(period_label(state["data_per"]))}</text>')

    shown = in_x(rows)
    if STEP_LINE:
        body.extend(_step_segments(shown, x_of, y_of))
    if not STEP_LINE or draw_fit:
        # The dots are the fit's input: with the step line they stay only
        # where a curve is drawn, faint, behind it.
        faint = " cv-pt-bg" if STEP_LINE else ""
        for t, value, est in observed:
            if t < start:
                continue
            cls = ("cv-pt cv-est" if est else "cv-pt") + faint
            body.append(f'<circle cx="{x_of(t):.1f}" cy="{y_of(value):.1f}" r="1.9" class="{cls}"/>')
    if STEP_TTM:
        ttm = [w for w in ttm_series(rows) if w[0] / 12 >= start]
        if ttm:
            body.append(f'<path d="{_ttm_path(ttm, x_of, y_of)}" class="cv-ttm"/>')

    line = []
    n = 240
    for i in range(n + 1):
        t = start + span * i / n
        line.append(f'{"M" if not i else "L"}{x_of(t):.1f},{y_of(100 * fit_share(t, v1, v2, t0)):.1f}')
    cls = "cv-fit" if state["quotable"] else "cv-fit cv-weak"
    if draw_fit:
        body.append(f'<path d="{" ".join(line)}" class="{cls}"/>')
    parts.append(f'<g clip-path="url(#{clip})">{"".join(body)}</g>')

    label = (f"BEV share of new registrations, observed and fitted S-curve, "
             f"{int(start)} to {int(end)}.")
    return (f'<svg class="curve" width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}" role="img" '
            f'aria-label="{esc(label)}">{"".join(parts)}</svg>')


IMAGE_LABEL = {
    "ICE_BEV": "Combustion, battery electric and hybrid curves",
    "share": "BEV share with the fitted curve",
    "ttm_shares": "Market split, trailing twelve months",
    "time": "Time to reach each BEV share",
}


def build_model(country: str, rows: list[dict], state: dict | None,
                bands: dict | None, images: list[dict]) -> str:
    if not state and not images:
        return ""
    out = ['<section id="model"><h2>The fitted curve</h2>']
    if state:
        curve = build_curve_svg(rows, state, bands)
        if curve:
            seen = step_legend().rstrip(".")
            legend = [f'<span class="key key-pt">{seen}</span>',
                      '<span class="key key-fit">fitted S-curve</span>']
            if state["band_ok"]:
                legend.append('<span class="key key-ci">95% confidence band of the curve</span>')
            out.append(f'<figure class="curve-fig" data-theme="light">{curve}'
                       f'<figcaption>{"".join(legend)}</figcaption></figure>')
        if state["flat"]:
            out.append('<p class="card-line">The series shows no transition yet, so the '
                       'curve carries no dates.</p>')
        elif not state["quotable"]:
            why = _join([REASON_TEXT[r] for r in state["rel"]["reasons"]])
            out.append(f'<p class="card-line">This fit is not reliable enough to quote '
                       f'dates from: {esc(why)}.</p>')
        else:
            body = []
            for c in state["crossings"]:
                ci = f'<td>{esc(_ci_text(c["ci"]))}</td>' if state["band_ok"] else ""
                body.append(f'<tr><th>{c["level"] * 100:.0f}%</th>'
                            f'<td>{esc(year_text(c["fit"]))}</td>{ci}</tr>')
            ci_head = "<th>95% confidence band</th>" if state["band_ok"] else ""
            out.append('<div class="scroll"><table class="vars miles">'
                       f'<tr><th>BEV share</th><th>Curve reaches it in</th>{ci_head}</tr>'
                       f'{"".join(body)}</table></div>')
            notes = []
            if state["rel"]["status"] == "provisional":
                notes.append("The fit is provisional: its 80% date moved by "
                             f"{state['rel']['swing']:.0f} years across recent re-fits.")
            if not state["band_ok"]:
                reasons = "; ".join(state["band_reasons"])
                notes.append("No confidence band is shown: none can be stated "
                             "reliably for this series" + (f" ({reasons})." if reasons else "."))
            else:
                notes.append("The band is for the fitted line, point by point, and "
                             "holds only if the transition keeps following an S-shape.")
            out.append(f'<p class="fig-note">{esc(" ".join(notes))} '
                       f'<a href="{GH_BLOB}/docs/architecture/44-uncertainty-bands.md">'
                       'How the bands are calculated</a>.</p>')
        fitted = period_label(state["data_per"], long=True)
        run = f', model run {esc(state["model_date"])}' if state["model_date"] else ""
        out.append(
            '<p class="model-note">The gallery fits a generalized Weibull curve to the '
            'BEV share of each period: '
            '<span class="eq">share(t) = 1 − exp(v<sub>1</sub> · (t − t<sub>0</sub>)'
            '<sup>v<sub>2</sub></sup>)</span>, t in calendar years. '
            f'For {esc(country)}: v<sub>1</sub> = {_sci(state["v1"])}, '
            f'v<sub>2</sub> = {state["v2"]:.3f}, t<sub>0</sub> = {state["t0"]:.0f}, '
            f'fitted through {esc(fitted)}{run}. This is the project\'s own model, '
            'not an official forecast. A policy change or a stall is not in it.</p>')
    if images:
        figs = []
        for item in images:
            url = "../" + (item.get("url") or "")
            label = IMAGE_LABEL.get(item.get("type"), item.get("alt") or "")
            figs.append(
                f'<a class="chart" href="{esc(url)}"><img loading="lazy" decoding="async" '
                f'src="{esc(url)}" alt="{esc(item.get("alt") or label)}">'
                f'<span>{esc(label)}</span></a>')
        stamp = images[0].get("date") or ""
        out.append('<h3>The gallery charts</h3>'
                   f'<div class="charts">{"".join(figs)}</div>'
                   f'<p class="fig-note">Rendered {esc(stamp)} from data through '
                   f'{esc(period_label(images[0].get("period") or ""))}. '
                   'Charts are CC BY 4.0; open one for the full size.</p>')
    out.append("</section>")
    return "".join(out)


# --------------------------------------------------------------------------
# Reference line, variants, citation
# --------------------------------------------------------------------------

def reference_line(rows: list[dict], state: dict | None, chip: str) -> str:
    bits = []
    if rows:
        bits.append(f'Data through <b>{esc(period_label(rows[-1]["period"], long=True))}</b>')
    if state and state["model_date"]:
        bits.append(f'curve fitted {esc(state["model_date"])}')
    if not bits and not chip:
        return ""
    text = " · ".join(bits)
    return f'<p class="asof">{text} {chip}</p>'


def variant_figures(data_file: str | None, variant: str) -> tuple[str, str]:
    """(12-month BEV share, 12-month volume) cells for the variants table.

    Same rule and same source as the key figures: the variant's own CSV
    rows, a full window ending at its latest period, else "—".
    """
    window = ttm_window(series_rows(data_file, variant))
    if not window:
        return "—", "—"
    return share(window["share"]), units(window["total"])


def build_cite(country: str, slug: str, rows: list[dict], source_name: str) -> str:
    through = period_label(rows[-1]["period"], long=True) if rows else ""
    stand = f", data through {through}" if through else ""
    url = f"{SITE}/sources/{slug}.html"
    owner = (source_name or "its source").split("—")[0].strip()
    return (
        '<section id="cite" class="cite"><h2>Using this card</h2>'
        f'<p>Cite as: <span class="cite-text">LeRaffl BEV Trajectory Gallery, {esc(country)} '
        f'model card{esc(stand)}. <a href="{esc(url)}">{esc(url)}</a></span></p>'
        '<p class="fig-note">Charts, fitted curves and text are CC BY 4.0: name the '
        f'gallery when you use them. The registration figures stay with {esc(owner)}. '
        'The card is rebuilt whenever the data changes, so quote it with its '
        '"data through" month.</p></section>')


CARD_CSS = """
/* --- model card ---------------------------------------------------------- */
.asof{margin:4px 0 0;font-size:14px;color:var(--muted)}
.asof b{color:var(--text);font-weight:600}
.asof .chip{margin-left:6px}
.cardbar{display:flex;flex-wrap:wrap;gap:6px 14px;align-items:center;margin:0 0 18px;
  font-size:13px}
.cardbar .back{margin:0}
.cardbar .flyer-link{margin-left:auto}
.cardbar nav{display:flex;flex-wrap:wrap;gap:4px 14px;flex-basis:100%;order:3}
.cardbar nav a{color:var(--muted)}
.cardbar .flyer-link{padding:4px 12px;border-radius:8px;font-weight:600;
  border:1px solid var(--text);background:var(--text);color:var(--bg)}
.glance{margin:0 0 6px}
.glance .stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:12px}
.glance .stat{padding:12px 14px}
.glance .stat .l{text-transform:none;letter-spacing:0;font-size:13px}
.glance .stat .n{font-size:26px;line-height:1.2;margin:2px 0;font-variant-numeric:tabular-nums}
.glance .stat .s{font-size:12.5px;color:var(--muted)}
.card-line{font-family:var(--font-display);font-size:17px;line-height:1.4;margin:0 0 14px;
  max-width:38em}
.gl{display:grid;grid-template-columns:minmax(7.5em,auto) minmax(90px,1fr) auto auto;
  grid-auto-flow:row dense;column-gap:12px;row-gap:0;align-items:center;font-size:14px}
.gl-name{grid-column:1}.gl-track{grid-column:2}.gl-pp{grid-column:3}.gl-lvl{grid-column:4}
.gl-row{display:contents}
.gl-row>span{padding:5px 0}
.gl-head>span{color:var(--muted);font-weight:600;font-size:13px;align-self:stretch;
  border-bottom:1px solid var(--border);padding-bottom:6px;margin-bottom:4px}
.gl-head .gl-track{height:auto}
.gl-track{position:relative;height:30px;padding:0!important}
.gl-zero{position:absolute;top:0;bottom:0;border-left:1px solid var(--muted)}
.gl-bar{position:absolute;top:6px;bottom:6px;border-radius:2px;min-width:2px;
  -webkit-print-color-adjust:exact;print-color-adjust:exact}
.gl-pp{text-align:right;font-weight:700;font-variant-numeric:tabular-nums;white-space:nowrap}
.gl-lvl{text-align:right;color:var(--muted);font-variant-numeric:tabular-nums;white-space:nowrap}
.gl-lvl b{color:var(--text);font-weight:600}
table.latest th,table.latest td{padding:6px 10px;white-space:nowrap}
table.latest td.num,table.latest th.num{text-align:right}
table.latest tr:nth-child(2) th,table.latest tr:nth-child(2) td{font-weight:700}
table.miles{max-width:520px}
.curve-fig{margin:0 0 14px;background:var(--bg);padding:6px 8px 8px;border-radius:2px}
.curve{display:block;width:100%;height:auto}
.curve text{fill:#55534c;font-size:11px;font-family:var(--font-ui),sans-serif}
.cv-grid{stroke:#e4e2dd;stroke-width:1}
.cv-ci{fill:#3d9a68;fill-opacity:.2}
.cv-fit{fill:none;stroke:#2c7a50;stroke-width:2}
.cv-weak{stroke-dasharray:5 4;stroke:#8d897c}
.cv-pt{fill:#55534c;fill-opacity:.55}
.cv-est{fill:none;stroke:#55534c}
.cv-step{fill:none;stroke:#3a3935;stroke-width:1.4;stroke-linejoin:miter}
.cv-step-est{stroke-dasharray:3 2}
.cv-rise{fill:none;stroke:#3a3935;stroke-width:.8}
.cv-ttm{fill:none;stroke:#154a30;stroke-width:2.2;stroke-linejoin:round}
.cv-pt-bg{fill-opacity:.18}
.cv-now{stroke:#8d897c;stroke-width:1;stroke-dasharray:2 3}
.curve-fig figcaption{display:flex;flex-wrap:wrap;gap:4px 16px;font-size:12px;color:#55534c;
  margin:2px 4px 0}
.key::before{content:"";display:inline-block;margin-right:6px;vertical-align:middle}
.key-pt::before{width:6px;height:6px;border-radius:50%;background:#55534c;opacity:.6}
.key-fit::before{width:16px;border-top:2px solid #2c7a50}
.key-ci::before{width:14px;height:9px;background:#3d9a68;opacity:.25}
.model-note{font-size:14px;color:var(--muted)}
.eq{white-space:nowrap;color:var(--text)}
h3{font-size:15px;margin:22px 0 10px}
.charts{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px}
.chart{display:block;border:1px solid var(--border);border-radius:10px;overflow:hidden;
  background:#fff;color:var(--muted);font-size:12.5px}
.chart img{display:block;width:100%;height:auto}
.chart span{display:block;padding:6px 10px;background:var(--panel)}
.cite-text{color:var(--text)}
.cite p{margin:0 0 6px}
@media (max-width:560px){
  .glance .stats{grid-template-columns:1fr 1fr;gap:8px}
  .glance .stat .n{font-size:22px}
  .gl{grid-template-columns:minmax(0,1fr) auto auto;column-gap:10px;font-size:13.5px}
  .gl-head{display:none}
  .gl-name{font-weight:600;padding-bottom:0!important}
  .gl-pp{grid-column:2;padding-bottom:0!important}
  .gl-lvl{grid-column:3;padding-bottom:0!important}
  .gl-track{grid-column:1/-1;height:20px;margin-bottom:6px}
  .gl-bar{top:3px;bottom:3px}
  .mix text,.curve text{font-size:17px}
  table.latest th,table.latest td{padding:6px 7px;font-size:13px}
}
@media print{
  :root{color-scheme:light}
  body{background:#fff}
  .wrap{max-width:none;padding:0}
  .cardbar,.mkt-toggle,input.filter,.source-btn--dead{display:none!important}
  h2{break-after:avoid;margin-top:22px}
  section,figure,table,.stat,.flow-node,.chart{break-inside:avoid}
  .tall{max-height:none;overflow:visible}
  .scroll{overflow:visible}
  a{color:inherit}
  .poster,.glance,#shift,#latest{break-inside:avoid}
  #model{break-before:page}
  .stat,.chart,.curve-fig,.mix-panel{-webkit-print-color-adjust:exact;print-color-adjust:exact}
  @page{margin:14mm}
}
"""

# Builds the section menu from the page's own headings, so a section that
# was left out for lack of data is never linked.
CARD_JS = """<script>
(function(){
  var nav=document.querySelector('.cardbar nav');if(!nav)return;
  var short={'Who gained, who lost':'Gains and losses','The latest periods':'Latest periods',
    'The fitted curve':'Curve','Raw source':'Source','How the data flows':'Data flow',
    'Definitions & scope':'Scope','Variants':'Variants','Caveats':'Caveats'};
  document.querySelectorAll('.wrap h2').forEach(function(h,i){
    var t=h.textContent.trim();if(!short[t])return;
    var host=h.closest('section')||h;if(!host.id)host.id='s'+i;
    var a=document.createElement('a');a.href='#'+host.id;a.textContent=short[t];nav.appendChild(a);
  });
})();
</script>"""
