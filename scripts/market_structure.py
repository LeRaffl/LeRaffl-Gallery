"""Who sells the battery-electric cars: the BEV market structure block.

MOCKUP (local branch mockup/brands-block, not a PR). Reads the generated
brand table `market/<slug>_top.json` (front-matter key `market_breakdown`)
and turns its BEV class into one classification, one plain sentence and one
ranked list of a variable number of brands — enough for a rough reading of
the market, from one brand in a dominated market up to five in a spread
one — plus a last row for the rest as "N other brands" when the table
accounts for every car. Every named row shows the logo (when we have one)
and the brand name, then a bar on a 0–100 % scale and the share.

Data rule, same as the 12-month BEV share: only a genuinely full 12-month
window that ends at the country CSV's latest period counts. A year-to-date
table, a window with gaps, a table that ends earlier than the CSV, a source
without a brand x fuel split ("ALL") or a pooled leader ("IMPORTS (ALL
BRANDS)") means no block. Nothing is estimated.

Shares are of the brand table's own BEV total (the registry's count in that
window); it can differ from the CSV's BEV sum by a fraction of a percent.
"""
from __future__ import annotations

import json
from pathlib import Path

import model_card as mc
from model_card import esc

DOMINANT_SHARE = 40.0     # leader holds at least this much of BEV ...
DOMINANT_RATIO = 2.0      # ... or more than twice the number two
CLOSE_POINTS = 5.0        # number one and two within this many points
SPREAD_TOP3 = 50.0        # top three together below this
MODEL_SHARE = 15.0        # name a model only from this share of BEV
SHOW_MAX = 5              # never more named brands than this
SHOW_MIN = 2              # at least this many in a non-dominant market
COVERAGE = 50.0           # stop once the named brands reach this share of BEV
NEXT_MIN = 5.0            # do not add a brand below this (after the minimum)
DOMINANT_SECOND = 10.0    # in a dominant market, also name a follower this large
LIST_DOMINANT_FLOOR = 25.0  # the 2× path only if the leader is at least this
OTHERS_MIN = 0.05         # skip the others row when the rest is effectively 0

# Registry spellings -> how a reader writes the brand.
BRAND_NAME = {
    "TESLA MOTORS": "Tesla", "TESLA": "Tesla", "KIA": "Kia", "SKODA": "Škoda",
    "ŠKODA": "Škoda", "MG": "MG", "BYD": "BYD", "BAIC": "BAIC", "CHEVROLET": "Chevrolet",
    "VOLKSWAGEN": "Volkswagen", "MERCEDES-BENZ": "Mercedes-Benz", "BMW": "BMW",
    "VINFAST": "VinFast", "XPENG": "XPeng", "ZEEKR": "Zeekr", "LEAPMOTOR": "Leapmotor",
    "RENAULT": "Renault", "VOLVO": "Volvo", "HYUNDAI": "Hyundai", "TOYOTA": "Toyota",
    "AUDI": "Audi", "JMEV": "JMEV", "ARCFOX": "Arcfox", "DONGFENG": "Dongfeng",
    "GEELY": "Geely", "GWM": "GWM", "GREAT WALL": "Great Wall", "JAC": "JAC",
    "JAECOO": "Jaecoo", "CUPRA": "Cupra",
}
# One fixed colour per brand for the chip variant (approximate brand colours).
BRAND_COLOUR = {
    "BYD": "#c4161c", "Tesla": "#e31937", "Chevrolet": "#cd9834", "BAIC": "#d7000f",
    "MG": "#a6192e", "Kia": "#05141f", "Škoda": "#0e3a2f", "Volkswagen": "#001e50",
    "Hyundai": "#002c5f", "Volvo": "#1c3f94", "Proton": "#0b2c6e", "VinFast": "#1464f4",
}
# Logo files in assets/brands/ (Wikimedia Commons, see assets/brands/SOURCES.md):
# file, width/height of the drawn logo, and whether it spells the brand (a
# wordmark needs no name next to it; a symbol does).
BRAND_LOGO = {
    "BYD": ("byd.svg", 4.0, True), "Kia": ("kia.svg", 4.0, True),
    "Škoda": ("skoda.svg", 7.14, True), "Hyundai": ("hyundai.svg", 7.78, True),
    "BAIC": ("baic.png", 3.4, True), "MG": ("mg.svg", 1.0, False),
    "Tesla": ("tesla.svg", 1.0, False), "Volkswagen": ("volkswagen.svg", 1.0, False),
    "Chevrolet": ("chevrolet.svg", 3.13, False),
}
# Rank 1-5, dark to light; Others uses OTHERS.
SEGMENT = ("#1f6a43", "#2e7d52", "#4f9a70", "#7fb594", "#b5d4c2")
SEGMENT_TEXT = ("#fff", "#fff", "#fff", "#0b2416", "#0b2416")
OTHERS = "#dedbd3"
POOLED = ("ALL BRANDS",)


def brand_name(raw: str) -> str:
    raw = " ".join(str(raw).split())
    if raw.upper() in BRAND_NAME:
        return BRAND_NAME[raw.upper()]
    return " ".join(w if len(w) <= 3 else w.capitalize() for w in raw.split())


def model_name(brand: str, model: str) -> str:
    words = []
    for w in str(model).split():
        keep = len(w) <= 3 or any(c.isdigit() or c == "." for c in w)
        words.append(w if keep else w.capitalize())
    return f"{brand_name(brand)} {' '.join(words)}"


def _months_between(a: str, b: str) -> int | None:
    ia, ib = mc.month_index(a), mc.month_index(b)
    return None if ia is None or ib is None else ib - ia + 1


def classify(shares: list[float]) -> str:
    """'dominant', 'ahead', 'spread', 'close' or 'leader' from the top brands'
    shares (percent of BEV, largest first). A market is dominant only if the
    leader holds at least 40 %, or more than twice #2 with the leader at
    least 25 % — the same bar as list_dominant(). A 2× lead under 25 % is
    'ahead' (a wide lead, not domination). A fragmented market whose top
    two happen to be level is 'spread'."""
    if not shares:
        return "spread"
    s1 = shares[0]
    s2 = shares[1] if len(shares) > 1 else 0.0
    if list_dominant(shares):
        return "dominant"
    if s2 > 0 and s1 > DOMINANT_RATIO * s2:
        return "ahead"
    if len(shares) >= 3 and sum(shares[:3]) < SPREAD_TOP3:
        return "spread"
    if s1 - s2 <= CLOSE_POINTS:
        return "close"
    return "leader"



def list_dominant(shares: list[float]) -> bool:
    """Whether this is a dominated market (badge and list use the same bar).

    The leader holds at least 40 % of BEV, or more than twice #2 with the
    leader at least 25 %. A 19 % leader that is merely twice #2 is not
    dominant: it is a wide lead (classify: 'ahead').
    """
    if not shares:
        return False
    s1 = shares[0]
    s2 = shares[1] if len(shares) > 1 else 0.0
    return s1 >= DOMINANT_SHARE or (s1 >= LIST_DOMINANT_FLOOR and s1 > DOMINANT_RATIO * s2)


def select_named(listed: list[dict]) -> list[dict]:
    """The brands that appear as rows: enough for a basic reading of the market.

    Dominant (leader ≥ 40 %, or > 2× #2 with the leader ≥ 25 %): the leader,
    plus any following brand that still holds at least 10 % (so a 41 / 18 / 11
    split names all three; a 73 / 7 market names only the leader).

    Otherwise: add brands in rank order until their shares sum to ≥ 50 % of
    BEV, or the next brand is below about 5 %, or five brands are shown,
    whichever comes first. At least two brands are shown.
    """
    if not listed:
        return []
    if list_dominant([b["share"] for b in listed]):
        named = [listed[0]]
        for b in listed[1:]:
            if len(named) >= SHOW_MAX or b["share"] < DOMINANT_SECOND:
                break
            named.append(b)
        return named
    named = listed[: min(SHOW_MIN, len(listed))]
    for b in listed[len(named):]:
        if len(named) >= SHOW_MAX:
            break
        if sum(x["share"] for x in named) >= COVERAGE:
            break
        if b["share"] < NEXT_MIN:
            break
        named.append(b)
    return named


def load(fm: dict, rows: list[dict]) -> dict | None:
    """The block's numbers, or None when there is no full 12-month BEV table."""
    rel = fm.get("market_breakdown")
    path = mc.REPO / rel if rel else None
    if not path or not path.is_file() or not rows:
        return None
    try:
        top = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return None
    win = top.get("window") or {}
    ttm = mc.ttm_window(rows)
    if (top.get("variant", "Whole") != "Whole" or win.get("months") != 12
            or win.get("missing") or not ttm or mc.interval_of(rows[-1]) != "monthly"
            or win.get("to") != rows[-1]["period"] or win.get("to") != ttm["end"]
            or _months_between(win.get("from", ""), win.get("to", "")) != 12):
        return None
    bev = (top.get("classes") or {}).get("BEV") or {}
    units = bev.get("units") or 0
    brands = [b for b in bev.get("brands") or []
              if not any(p in b["brand"].upper() for p in POOLED)]
    if units <= 0 or len(brands) < 2 or len(brands) != len(bev.get("brands") or []):
        return None
    listed = [{"brand": brand_name(b["brand"]), "units": b["units"],
               "share": 100 * b["units"] / units} for b in brands]
    top3 = listed[:3]
    named = select_named(listed)
    others = 100 - sum(b["share"] for b in named)
    # The table stores a top-N cut. "N other brands" is only honest when
    # those listed brands account for every car in the class total.
    leftover = units - sum(b["units"] for b in brands)
    if leftover <= 0:
        others_n = len(listed) - len(named)
    else:
        others_n = None
    s3sum = sum(b["share"] for b in top3)
    kind = classify([b["share"] for b in top3])
    model = None
    models = bev.get("models") or []
    if models:
        m = models[0]
        share = 100 * m["units"] / units
        if share >= MODEL_SHARE:
            model = {"name": model_name(m["brand"], m["model"]), "share": share}
    return {"kind": kind, "top3": top3, "named": named, "others": others,
            "others_n": others_n, "top3_sum": s3sum,
            "units": units, "from": win["from"], "to": win["to"], "model": model,
            "path": rel, "source": top.get("source", ""), "csv_bev": ttm["bev"]}


LABEL = {"dominant": "One brand dominates", "ahead": "Wide lead",
         "close": "Close race", "spread": "Spread out", "leader": "Clear leader"}


def _pct(v: float) -> str:
    return f"{v:.1f}%"


def others_label(ms: dict) -> str:
    """The rest of the bar: '5 other brands' when the count is known."""
    n = ms.get("others_n")
    if n is None:
        return "other brands"
    if n == 1:
        return "1 other brand"
    return f"{n} other brands"


def sentence(ms: dict) -> str:
    """One short sentence from the numbers, no causes."""
    a, b = ms["top3"][0], ms["top3"][1]
    if ms["kind"] == "dominant":
        if a["share"] >= 90:
            return f"Nearly every battery-electric car is a {a['brand']}."
        return f"{a['brand']} holds {_pct(a['share'])} of battery-electric registrations."
    if ms["kind"] == "ahead":
        return (f"{a['brand']} leads with {_pct(a['share'])}, "
                f"twice the next brand.")
    if ms["kind"] == "spread":
        return f"No brand dominates: the top three hold {_pct(ms['top3_sum'])}."
    if ms["kind"] == "close":
        return f"{a['brand']} and {b['brand']} almost level."
    return f"{a['brand']} leads clearly, {b['brand']} is second."


def brand_source(fm: dict, ms: dict | None) -> str:
    """The brand table's source when it is not the share data's own source
    (Netherlands: shares from Swing/ABF, brands from RDW), else ''."""
    if not ms or not ms.get("source"):
        return ""
    generic = {"open", "data", "register", "registry", "motor", "vehicle", "stats", "www",
               "the", "and", "com", "org", "gov"}
    def toks(text):
        import re
        return {t for t in re.split(r"[^a-z0-9]+", text.lower()) if len(t) >= 3} - generic
    return "" if toks(ms["source"]) & toks(fm.get("source_name") or "") else ms["source"]


def _logo_img(brand: str, logo_href: str, h: float) -> str:
    file, _aspect, _word = BRAND_LOGO[brand]
    # Height is a cap: wide wordmarks shrink to the slot via object-fit, so
    # Škoda / Hyundai stay modest next to the printed name. Compact marks
    # (the T, the VW, MG, the bowtie) use the full cap.
    return (f'<img class="ms-logo" alt="{esc(brand)}" '
            f'src="{esc(logo_href)}/{file}">')


def build_bar(ms: dict, mode: str, logo_href: str, width: float = 702,
              base: float = 17, fs: float = 13, row_h: float = 18,
              gap: float = 2, info: dict | None = None) -> str:
    """A compact ranked list: logo + name, a slim bar, and the share.

    Every named row has the same structure: a small logo (when we have one)
    in a fixed slot, the brand name immediately after it at a shared x, a
    slim bar scaled to the top named brand (not to 100 %), and a
    right-aligned share. Brands with no logo leave the slot blank — no
    chip — so the name still lines up. 'Other brands' is the last row,
    in grey, with the remainder as a number only (no bar — on a spread
    market the rest is often larger than the leader, and a 0–100 %
    track was mostly empty grey). It is omitted only when the rest is
    effectively zero.
    """
    named = list(ms.get("named") or ms["top3"])
    items = list(named)
    rest_share = ms["others"]
    if rest_share >= OTHERS_MIN:
        items.append({"brand": others_label(ms), "share": rest_share, "others": True})
    logo_h = max(12.0, 0.52 * base)         # social base=30 → 16; flyer 17 → 12
    # Slot is only wide enough for a modest wordmark. Names start together
    # just after it, and the bars start just after the names.
    logo_slot = min(4.2 * logo_h, 0.08 * width)
    name_w = max(8.0 * fs, 0.16 * width)
    pct_w = 4.8 * fs
    track_h = max(6.0, 0.34 * row_h)
    top_share = max((b["share"] for b in named), default=0) or 1

    rows = []
    for i, b in enumerate(items):
        if b.get("others"):
            slot = '<div class="ms-logo-slot"></div>'
            name = f'<div class="ms-name ms-mute">{esc(b["brand"])}</div>'
            klass = "ms-row ms-rest"
            # Quiet residual bar on the same top-brand scale as the ranked
            # rows, capped at full width: on a spread market the rest is
            # larger than the leader (cap), on a dominant market it is a
            # short proportional bar. When capped, the bar's right end fades
            # out and a small chevron below it says the value runs on beyond
            # the scale — quieter and sturdier than a turned elbow.
            rest_w = min(100.0, 100.0 * rest_share / top_share)
            over = " ms-fill-over" if rest_w >= 99.99 else ""
            cue = ('<svg class="ms-over-cue" width="12" height="12" viewBox="0 0 12 12" aria-hidden="true">'
                   '<path d="M2 1 L8 6 L2 11" fill="none" stroke="#a5a196" stroke-width="2.5" '
                   'stroke-linecap="round" stroke-linejoin="round"/></svg>') if over else ""
            fill = (f'<div class="ms-track" style="height:{track_h:.0f}px">'
                    f'<span class="ms-fill ms-fill-rest{over}" style="width:{rest_w:.2f}%">{cue}</span></div>')
        else:
            colour = SEGMENT[min(i, len(SEGMENT) - 1)]
            if mode == "logos" and b["brand"] in BRAND_LOGO:
                mark = _logo_img(b["brand"], logo_href, logo_h)
            else:
                mark = ""
            slot = f'<div class="ms-logo-slot">{mark}</div>'
            name = f'<div class="ms-name">{esc(b["brand"])}</div>'
            klass = "ms-row"
            rel = 100.0 * b["share"] / top_share
            fill = (f'<div class="ms-track" style="height:{track_h:.0f}px">'
                    f'<span class="ms-fill" style="width:{rel:.2f}%;background:{colour}">'
                    f'</span></div>')
        ident = f'<div class="ms-id">{slot}{name}</div>'
        rows.append(
            f'<div class="{klass}">{ident}{fill}'
            f'<div class="ms-val">{esc(_pct(b["share"]))}</div></div>')

    style = (f'--ms-logo:{logo_slot:.0f}px;--ms-name:{name_w:.0f}px;--ms-pct:{pct_w:.0f}px;'
             f'--ms-row:{row_h:.0f}px;--ms-logo-h:{logo_h:.0f}px;--ms-bar-h:{track_h:.0f}px')
    n = len(items)
    height = n * row_h + max(0, n - 1) * 3
    if info is not None:
        info["rows"] = n
        info["named"] = len(named)
        info["height"] = height
    return f'<div class="ms-list" style="{style}">{"".join(rows)}</div>'


def gap_note(ms: dict, where: str = "above") -> str:
    """Say so when the brand table counts a different BEV total than the CSV.

    Any difference, not just a large one: two totals on one sheet that
    disagree by 15 cars are still a question the reader should not have
    to guess at."""
    csv = ms.get("csv_bev")
    if not csv or ms["units"] == csv:
        return ""
    return f" The brand table counts slightly differently from the {mc.units(csv)} {where}."


HEADING = "Top brands · battery-electric registrations, last 12 months"
SCALE_NOTE = " Bars are scaled to the top brand, not to 100 %."


def base_line(ms: dict) -> str:
    return (f'{mc.period_label(ms["from"])} to {mc.period_label(ms["to"])}, '
            f'of {mc.units(ms["units"])} battery-electric cars.')


def build_block(ms: dict | None, mode: str, logo_href: str,
                compact: bool = False) -> str:
    """The brief's section. `mode`: 'logos' or 'chips'.

    `compact` is a tighter list: shorter heading, narrower columns, no
    best-selling-model line. Ready if a later layout needs a narrow column.
    """
    if not ms:
        return ""
    model = ""
    if ms["model"] and not compact:
        model = (f'<p class="ms-model">Best-selling model: <b>{esc(ms["model"]["name"])}</b>, '
                 f'{esc(_pct(ms["model"]["share"]))} of battery-electric cars.</p>')
    heading = "Top brands" if compact else HEADING
    klass = "fl-sec ms ms-compact" if compact else "fl-sec ms"
    return (
        f'<section class="{klass}"><h2>{esc(heading)}</h2>'
        f'<p class="fl-sub">{esc(base_line(ms))}{esc(gap_note(ms))}</p>'
        f'<p class="ms-line"><span class="ms-kind ms-{ms["kind"]}">{esc(LABEL[ms["kind"]])}</span>'
        f'{esc(sentence(ms))}</p>'
        f'{build_bar(ms, mode, logo_href)}{model}</section>')


CSS = """
.ms-line{font-family:var(--font-display);font-size:15.5px;line-height:1.35;margin:0 0 8px}
.ms-kind{display:inline-block;font-family:var(--font-ui),sans-serif;font-size:11px;font-weight:700;
  letter-spacing:.05em;text-transform:uppercase;padding:2px 8px;border-radius:999px;margin-right:8px;
  vertical-align:2px;background:#eceae4;color:#3a3935}
.ms-dominant{background:#1f6a43;color:#fff}
.ms-close{background:#f3e3b5;color:#5c4400}
.ms-spread{background:#e4ece6;color:#1f4a33}
.ms-leader{background:#e4ece6;color:#1f4a33}
.ms-ahead{background:#e8ddd0;color:#5a3a16}
.ms-list{--ms-logo:50px;--ms-name:112px;--ms-pct:64px;--ms-row:18px;--ms-logo-h:12px}
.ms-row{display:grid;grid-template-columns:calc(var(--ms-logo) + 8px + var(--ms-name)) minmax(0,1fr) var(--ms-pct);
  column-gap:12px;align-items:center;height:var(--ms-row);min-height:var(--ms-row)}
.ms-list .ms-row + .ms-row{margin-top:3px}
.ms-id{display:grid;grid-template-columns:var(--ms-logo) minmax(0,1fr);column-gap:8px;
  align-items:center;min-width:0;height:100%}
.ms-logo-slot{display:flex;align-items:center;justify-content:flex-start;height:100%;
  width:var(--ms-logo);min-width:0}
.ms-logo{display:block;height:var(--ms-logo-h);max-width:100%;width:auto;object-fit:contain;
  object-position:center left;flex:none}
.ms-name{font-weight:600;line-height:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;
  min-width:0}
.ms-mute{font-weight:400;color:#55534c}
.ms-track{display:block;background:transparent;border-radius:3px;overflow:visible;min-width:0;
  align-self:center}
.ms-track-empty{height:0}
.ms-fill{display:block;height:100%;border-radius:3px}
.ms-val{text-align:right;font-variant-numeric:tabular-nums;font-weight:700;line-height:1;
  white-space:nowrap;color:#1a1a18;align-self:center}
.ms-rest .ms-val{font-weight:600;color:#3a3935}
.ms-rest{margin-top:7px;padding-bottom:18px}
.ms-fill-rest{background:#c7c3b7;position:relative}
.ms-fill-over{background:linear-gradient(to right,#c7c3b7 calc(100% - 26px),rgba(199,195,183,0))}
.ms-over-cue{position:absolute;right:1px;top:100%;margin-top:2px;overflow:visible}
.ms-model{font-size:12.5px;margin:6px 0 0;color:#3a3935}
.ms-compact{--ms-logo:28px;--ms-name:88px;--ms-pct:42px;--ms-row:16px;--ms-logo-h:11px}
.ms-compact .ms-line{font-size:13.5px;margin:0 0 6px}
.ms-compact .ms-row{column-gap:8px}
"""
