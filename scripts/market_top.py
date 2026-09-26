"""Shared builder for the per-country "top brands / top models" summary.

Every fetcher whose source carries brand + model per registration (record-level
registries such as DNRPA, DGT, data.gov.my) feeds its trailing-twelve-month
counts in here and gets back the same country-neutral JSON document, which
scripts/build_source_pages.py renders as the "Who sells the electrified cars"
section of the country's source page (front-matter key ``market_breakdown:``).

Schema (docs/architecture/03-data-objects.md §3.16):

    {"country", "variant", "source", "as_of": "YYYY-MM",
     "window": {"from", "to", "months"},
     "total_registrations": int,            # whole market in the window
     "unit": "...",                          # what one unit / one model string is
     "classes": {"BEV": {"units", "share_of_market",
                         "brands": [{"brand", "units", "share_of_class"}, ...],
                         "models": [{"brand", "model", "units", "share_of_class"}, ...]},
                 "PHEV": ..., "EREV": ..., "HEV": ..., "MHEV": ...},
     "months": [{"period", "total_registrations", "classes": {...}}, ...]}
                                             # build_top_monthly: newest first

``window`` describes the months actually summed (``months`` < 12 and a
``missing`` list when the source does not cover the full year).

ICE classes are never listed (the section is about who sells the electrified
cars). Ties are broken alphabetically so the file is byte-stable whatever order
the records arrived in — no spurious commits.

Output location: ``market/<slug>_top.json`` (generated, never hand-edited).
Argentina's predates the folder and lives in ``classification/``.
"""
from __future__ import annotations

import collections
import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MARKET_DIR = REPO / "market"

# Classes that get a ranking, in display order. Anything else a fetcher passes
# (PETROL, DIESEL, ICE, OTHERS, ...) only counts towards the market total.
ELECTRIFIED = ("BEV", "PHEV", "EREV", "HEV", "MHEV")
# Brand of a top-N source's own "all others" line (see _classes).
REST = ""
TOP_BRANDS = 10
TOP_MODELS = 15
# Single-month rankings are shorter: twelve of them sit behind one picker.
TOP_BRANDS_MONTH = 10
TOP_MODELS_MONTH = 10


def month_window(target: str, months: int = 12) -> list[str]:
    """The `months` months ending at `target` (inclusive), ascending."""
    y, m = map(int, target.split("-"))
    out = []
    for _ in range(months):
        out.append(f"{y}-{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return sorted(out)


def ranked(counter: collections.Counter, n: int) -> list:
    return sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))[:n]


def _classes(units: dict, total: int, top_brands: int, top_models: int) -> dict:
    """Rank one window's `units` ({(class, brand, model): n}) per electrified
    class. A brand-only source passes model "" — it gets brand rankings and an
    empty model list. Brand "" (REST) is a source's own "all others" line for
    a top-N table: it counts towards the class, never into a ranking."""
    per_class = {c: {"brands": collections.Counter(),
                     "models": collections.Counter()} for c in ELECTRIFIED}
    for (cls, brand, model), n in units.items():
        if cls not in per_class or not n:
            continue
        per_class[cls]["brands"][brand] += n
        if model and brand:
            per_class[cls]["models"][(brand, model)] += n
    classes = {}
    for cls in ELECTRIFIED:
        cls_units = sum(per_class[cls]["brands"].values())
        if not cls_units:
            continue
        classes[cls] = {
            "units": cls_units,
            "share_of_market": round(cls_units / total, 5) if total else None,
            "brands": [{"brand": b, "units": u,
                        "share_of_class": round(u / cls_units, 4)}
                       for b, u in ranked(per_class[cls]["brands"], top_brands + 1)
                       if b != REST][:top_brands],
            "models": [{"brand": b, "model": m, "units": u,
                        "share_of_class": round(u / cls_units, 4)}
                       for (b, m), u in ranked(per_class[cls]["models"], top_models)],
        }
    return classes


def build_top(country: str, source: str, target: str,
              units: dict[tuple[str, str, str], int], total: int,
              unit: str, variant: str = "Whole",
              top_brands: int = TOP_BRANDS, top_models: int = TOP_MODELS) -> dict:
    """`units` maps (class, brand, model) -> registrations inside the window
    ending at `target`; `total` is the whole market in that window."""
    window = month_window(target)
    return {
        "country": country, "variant": variant, "source": source,
        "as_of": target, "window": {"from": window[0], "to": window[-1],
                                    "months": len(window)},
        "total_registrations": total,
        "unit": unit,
        "classes": _classes(units, total, top_brands, top_models),
    }


def build_top_monthly(country: str, source: str, target: str,
                      monthly: dict[str, tuple[dict, int]], unit: str,
                      variant: str = "Whole") -> dict:
    """Trailing-twelve-month summary PLUS one ranking per single month.

    `monthly` maps "YYYY-MM" -> ({(class, brand, model): n}, whole-market
    total of that month). Only months inside the twelve ending at `target`
    count. When the source does not (yet) cover all twelve — a register that
    starts mid-window, or a file that only ever restates the current year —
    the window says so honestly: `from`/`months` describe the months actually
    summed and `missing` lists the gaps, so the page never calls eight months
    "the last twelve"."""
    window = month_window(target)
    have = [p for p in window if p in monthly]
    if not have:
        raise ValueError(f"no month of {window[0]}..{window[-1]} available")
    units: collections.Counter = collections.Counter()
    total = 0
    for p in have:
        u, t = monthly[p]
        units.update({k: n for k, n in u.items() if n})
        total += t
    top = build_top(country, source, target, units, total, unit, variant)
    top["window"] = {"from": have[0], "to": have[-1], "months": len(have)}
    missing = [p for p in window if p not in monthly and p > have[0]]
    if missing:
        top["window"]["missing"] = missing
    top["months"] = [
        {"period": p, "total_registrations": monthly[p][1],
         "classes": _classes(monthly[p][0], monthly[p][1],
                             TOP_BRANDS_MONTH, TOP_MODELS_MONTH)}
        for p in reversed(have)]
    return top


def splice_models(top: dict, models_top: dict) -> dict:
    """For a source that publishes brands and models in two separate tables
    (Traficom): keep `top`'s brand-table classes and totals, take the model
    rankings from `models_top` (built the same way from the model table),
    with shares re-based on the brand table's class units."""
    def graft(dst: dict, src: dict) -> None:
        for cls, v in dst.items():
            models = (src.get(cls) or {}).get("models") or []
            v["models"] = [{**m, "share_of_class": round(m["units"] / v["units"], 4)}
                           for m in models]
    graft(top["classes"], models_top.get("classes") or {})
    src_months = {m["period"]: m for m in models_top.get("months") or []}
    for m in top.get("months") or []:
        graft(m["classes"], (src_months.get(m["period"]) or {}).get("classes") or {})
    return top


def per_month(counter: dict) -> dict[str, dict]:
    """{(period, class, brand, model): n} -> {period: {(class, brand, model): n}}
    — the shape build_top_monthly wants, from the per-record tallies the
    record-level fetchers keep anyway."""
    out: dict[str, dict] = collections.defaultdict(collections.Counter)
    for (p, cls, b, m), n in counter.items():
        out[p][(cls, b, m)] += n
    return dict(out)


# --------------------------------------------------------------------------
# Month store — for sources whose files only ever carry a few recent months
# --------------------------------------------------------------------------
#
# Record-level registries (DGT, data.gov.my, …) let a fetcher re-read twelve
# months whenever it likes. Summary publications don't: JADA's workbook holds
# four months, LTA's M03 the current half-year, ACAU's the current calendar
# year. For those the fetcher keeps every month it has seen in
# ``market/<slug>_months.json`` (generated, never hand-edited) and builds the
# twelve-month view from that store. Only electrified classes are kept per
# brand/model — combustion only ever counts towards the month's total — so the
# file stays small. A month the source restates simply overwrites the stored
# one; months older than STORE_MONTHS are dropped.

STORE_MONTHS = 15


def load_store(path: Path) -> dict[str, tuple[dict, int]]:
    """{period: ({(class, brand, model): n}, total)} from a month store
    (empty if there is none yet or it is unreadable)."""
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out = {}
    for p, m in (doc.get("months") or {}).items():
        out[p] = ({(c, b, mo): int(n) for c, b, mo, n in m.get("units", [])},
                  int(m.get("total") or 0))
    return out


def save_store(path: Path, monthly: dict[str, tuple[dict, int]],
               country: str, source: str) -> bool:
    """Write the newest STORE_MONTHS months (electrified rows only, sorted so
    the file is byte-stable). Returns True if the file changed."""
    keep = sorted(monthly)[-STORE_MONTHS:]
    doc = {"country": country, "source": source,
           "note": "generated by the fetcher (scripts/market_top.py) — "
                   "per-month electrified brand/model counts, never hand-edit",
           "months": {p: {"total": monthly[p][1],
                          "units": sorted([c, b, m, n] for (c, b, m), n
                                          in monthly[p][0].items()
                                          if n and c in ELECTRIFIED)}
                      for p in keep}}
    text = json.dumps(doc, ensure_ascii=False, separators=(",", ":"))
    text = text.replace('},"', '},\n"') + "\n"     # one month per line
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return True


def refresh_from_store(country: str, source: str, unit: str, slug: str,
                       fresh: dict[str, tuple[dict, int]],
                       variant: str = "Whole") -> dict | None:
    """Merge the months a fetch just parsed into ``market/<slug>_months.json``,
    then rebuild ``market/<slug>_top.json`` for the newest stored month.
    Returns the summary (None if nothing is stored yet)."""
    store_path = MARKET_DIR / f"{slug}_months.json"
    monthly = load_store(store_path)
    monthly.update({p: v for p, v in fresh.items() if v[1]})
    if not monthly:
        return None
    save_store(store_path, monthly, country, source)
    target = max(monthly)
    top = build_top_monthly(country, source, target, monthly, unit, variant)
    wrote = write_top(top, MARKET_DIR / f"{slug}_top.json")
    report(top, MARKET_DIR / f"{slug}_top.json", wrote)
    return top


def report(top: dict, path: Path, wrote: bool) -> None:
    """One log line per refresh: what moved, and the leading BEV brand."""
    bev = top["classes"].get("BEV", {})
    lead = (bev.get("brands") or [{}])[0]
    win = top["window"]
    shown = path.relative_to(REPO) if path.is_relative_to(REPO) else path
    print(f"{shown}: {'updated' if wrote else 'unchanged'} "
          f"({win['from']}..{win['to']}, {win['months']} months) — BEV "
          f"{bev.get('units', 0):,} units, top brand {lead.get('brand')} "
          f"{lead.get('share_of_class')}")


def dumps(top: dict) -> str:
    return json.dumps(top, ensure_ascii=False, indent=1) + "\n"


def write_top(top: dict, path: Path) -> bool:
    """Write only when the content changed. Returns True if written."""
    text = dumps(top)
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return True


def top_as_of(path: Path) -> str | None:
    """`as_of` of an existing summary, or None if there is none (yet)."""
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("as_of")
    except (OSError, ValueError):
        return None


def top_is_current(path: Path, target: str) -> bool:
    """True when an existing summary is for `target` AND already carries the
    single-month rankings — files written before those existed are rebuilt
    once even though their `as_of` matches."""
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return doc.get("as_of") == target and "months" in doc


def guarded(fn, *args) -> None:
    """Run a fetcher's top-list refresh without letting it break the fetch:
    the data CSVs are already written by then, and a schema change or a
    network hiccup in this optional extra must not keep them from being
    committed. Failures surface as a GitHub Actions warning annotation."""
    try:
        fn(*args)
    except Exception as e:  # noqa: BLE001 — deliberately broad, see docstring
        print(f"::warning title=top brands/models not refreshed::"
              f"{type(e).__name__}: {e}")


def strip_brand(brand: str, model: str) -> str:
    """Drop a leading repeat of the brand from the model string (DGT writes
    both "BYD DOLPHIN SURF" and "DOLPHIN SURF" for the same car), so one model
    is one row. Only a whole-word prefix, and never down to an empty string."""
    if brand and model.startswith(brand + " ") and len(model) > len(brand) + 1:
        return model[len(brand) + 1:]
    return model


def clean(s) -> str:
    """Registry strings → display strings: trimmed, inner whitespace collapsed,
    upper-cased so the same model typed two ways counts once."""
    return " ".join(str(s or "").split()).upper()
