"""Shared builder for the per-country "top brands / top models" summary.

Every fetcher whose source carries brand + model per registration (record-level
registries such as DNRPA, DGT, data.gov.my) feeds its trailing-twelve-month
counts in here and gets back the same country-neutral JSON document, which
scripts/build_source_pages.py renders as the "Who sells the electrified cars"
section of the country's source page (front-matter key ``market_breakdown:``).

Schema (docs/architecture/03-data-objects.md §3.9):

    {"country", "variant", "source", "as_of": "YYYY-MM",
     "window": {"from", "to", "months"},
     "total_registrations": int,            # whole market in the window
     "unit": "...",                          # what one unit / one model string is
     "classes": {"BEV": {"units", "share_of_market",
                         "brands": [{"brand", "units", "share_of_class"}, ...],
                         "models": [{"brand", "model", "units", "share_of_class"}, ...]},
                 "PHEV": ..., "EREV": ..., "HEV": ..., "MHEV": ...}}

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
TOP_BRANDS = 10
TOP_MODELS = 15


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


def build_top(country: str, source: str, target: str,
              units: dict[tuple[str, str, str], int], total: int,
              unit: str, variant: str = "Whole",
              top_brands: int = TOP_BRANDS, top_models: int = TOP_MODELS) -> dict:
    """`units` maps (class, brand, model) -> registrations inside the window
    ending at `target`; `total` is the whole market in that window."""
    window = month_window(target)
    per_class = {c: {"brands": collections.Counter(),
                     "models": collections.Counter()} for c in ELECTRIFIED}
    for (cls, brand, model), n in units.items():
        if cls not in per_class or not n:
            continue
        per_class[cls]["brands"][brand] += n
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
                       for b, u in ranked(per_class[cls]["brands"], top_brands)],
            "models": [{"brand": b, "model": m, "units": u,
                        "share_of_class": round(u / cls_units, 4)}
                       for (b, m), u in ranked(per_class[cls]["models"], top_models)],
        }
    return {
        "country": country, "variant": variant, "source": source,
        "as_of": target, "window": {"from": window[0], "to": window[-1],
                                    "months": len(window)},
        "total_registrations": total,
        "unit": unit,
        "classes": classes,
    }


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
