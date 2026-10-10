#!/usr/bin/env python3
"""Regression tests for scripts/fetch_norway.py (no network).

Run:  python scripts/test_fetch_norway.py

OFV's article is CMS-made HTML and its failure modes are quiet: a new fuel
row (hydrogen, a range-extender line), a column added in front of the counts,
the van release mistaken for the car release, the JSON export and the article
drifting apart. These cases pin every fuel label, the column-shift check, the
car/van distinction, both cross-checks against export.json, the derived
fallback, the RSS / sitemap date filter, the CRLF-preserving line-level upsert
and the brand / model tables.
"""
import copy
import json
import sys
import tempfile
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_norway as fn  # noqa: E402
import market_top  # noqa: E402

# Every OFV label the fetcher accepts, and the column it lands in.
LABEL_CASES = {
    "elektrisitet": "BEV",
    "bensin plugin hybrid": "PHEV", "diesel plugin hybrid": "PHEV",
    "bensin hybrid": "HEV", "diesel hybrid": "HEV",
    "bensin": "PETROL", "diesel": "DIESEL",
    "hydrogen": "OTHERS", "gass": "OTHERS", "biogass": "OTHERS",
    "parafin": "OTHERS", "annet drivstoff": "OTHERS", "annet": "OTHERS",
}

# September 2026 as published on 1 October 2026 (cars), and its van twin.
SEP26 = [("Elektrisitet", "18 511", "98,81 %", "112 825", "97,94 %"),
         ("Bensin hybrid", "99", "0,53 %", "708", "0,61 %"),
         ("Diesel", "77", "0,41 %", "851", "0,74 %"),
         ("Bensin plugin hybrid", "29", "0,15 %", "584", "0,51 %"),
         ("Bensin", "14", "0,07 %", "186", "0,16 %"),
         ("Diesel plugin hybrid", "3", "0,02 %", "41", "0,04 %"),
         ("Diesel hybrid", "0", "0,00 %", "1", "0,00 %")]
SEP26_TOTAL = ("18 733", "115 196")
VANS_SEP26 = [("Elektrisitet", "1 518", "74,56 %", "9 928", "55,54 %"),
              ("Diesel", "468", "22,99 %", "7 506", "41,99 %"),
              ("Bensin plugin hybrid", "32", "1,57 %", "276", "1,54 %"),
              ("Bensin", "18", "0,88 %", "167", "0,93 %")]
VANS_TOTAL = ("2 036", "17 877")

BRANDS = [("Tesla", "4 935"), ("Toyota", "1 333"), ("Volkswagen", "1 182"),
          ("Mercedes-Benz", "886"), ("Polestar", "346"), ("MG", "483")]
MODELS = [("Tesla Model Y", "4 810"), ("Mercedes-Benz GLC", "568"),
          ("Polestar Polestar 2", "174"), ("MG MG4", "219")]


def fuel_html(rows=SEP26, total=SEP26_TOTAL, month="september 2026") -> str:
    """OFV's fuel table in the article's own markup (caption, two header rows)."""
    tr = lambda tag, xs: "<tr>" + "".join(f"<{tag}>{x}</{tag}>" for x in xs) + "</tr>"
    out = [f'<table class="w-full"><caption class="sr-only">Fordeling per drivstoff i {month} '
           "og hittil i år (hittil i 2026: 1. januar–30. september 2026)</caption><thead>",
           tr("th", ["", month, "Hittil i 2026"]),
           tr("th", ["Drivstoff", "Antall", "Andel", "Antall", "Andel"]), "</thead><tbody>"]
    out += [tr("td", r) for r in rows]
    out.append(tr("td", ["Total", total[0], "100,00 %", total[1], "100,00 %"]))
    return "".join(out) + "</tbody></table>"


def ranking_html(kind: str, items, what="bil", month="september 2026") -> str:
    head = "Merke" if kind == "merkene" else "Modell"
    rows = "".join(f"<tr><td>{a}</td><td>{n}</td><td>1,00 %</td></tr>" for a, n in items)
    return (f"<table><caption>De 30 mest solgte {what}{kind} i {month} – antall</caption>"
            f"<thead><tr><th>{head}</th><th>Antall</th><th>Andel</th></tr></thead>"
            f"<tbody>{rows}</tbody></table>")


def car_article(**kw) -> str:
    return ("<html><body><h1>Sterk vekst</h1>" + ranking_html("merkene", BRANDS)
            + ranking_html("modellene", MODELS) + fuel_html(**kw) + "</body></html>")


def van_article() -> str:
    return ("<html><body>" + ranking_html("merkene", [("Volkswagen", "774")], what="varebil")
            + fuel_html(VANS_SEP26, VANS_TOTAL) + "</body></html>")


EXPORT = {"data": {"personbiler": {
    "thisYearLabel": "2026", "prevYearLabel": "2025",
    "fuelRangeLabel": "1. januar 2026 til 30. september 2026",
    "monthly": [{"label": m, "current": c, "previous": p} for m, c, p in [
        ("Jan", 2218, 9343), ("Feb", 7271, 8949), ("Mar", 17685, 13304), ("Apr", 11111, 11286),
        ("Mai", 15560, 14260), ("Jun", 19558, 18374), ("Jul", 9609, 9563),
        ("Aug", 13451, 13917), ("Sep", 18733, 14329)]],
    "fuelMix": [{"name": "Elektrisitet", "value": 112825}, {"name": "Diesel", "value": 851},
                {"name": "Bensin hybrid", "value": 708},
                {"name": "Bensin plugin hybrid", "value": 584}, {"name": "Bensin", "value": 186},
                {"name": "Diesel plugin hybrid", "value": 41},
                {"name": "Diesel hybrid", "value": 1}]}}}

# data/Norway.csv January-August 2026 as committed (CRLF, ACEA's float style).
HEADER = "period,time_interval,variant,source,BEV,PHEV,HEV,PETROL,DIESEL,OTHERS,TOTAL,notes"
HISTORY = [
    "2025-09,monthly,Whole,ofv.no & ACEA,14084.0,85.0,115.0,25.0,105.0,0.0,14414.0,",
    "2026-01,monthly,Whole,ofv.no & ACEA,2084.0,17.0,12.0,7.0,98.0,0.0,2218.0,",
    "2026-02,monthly,Whole,ofv.no & ACEA,7127.0,46.0,20.0,12.0,67.0,0.0,7272.0,",
    "2026-03,monthly,Whole,ofv.no & ACEA,17406.0,126.0,5.0,22.0,126.0,0.0,17685.0,",
    "2026-04,monthly,Whole,ACEA,10952.0,25.0,8.0,31.0,87.0,0.0,11103.0,",
    "2026-05,monthly,Whole,ACEA,15210.0,97.0,103.0,32.0,118.0,0.0,15560.0,",
    "2026-06,monthly,Whole,ACEA,18875.0,175.0,334.0,23.0,151.0,0.0,19558.0,",
    "2026-07,monthly,Whole,ACEA,9387.0,56.0,96.0,15.0,63.0,0.0,9617.0,",
    "2026-08,monthly,Whole,ACEA,13274.0,51.0,31.0,30.0,65.0,0.0,13451.0,",
]
SEP26_LINE = "2026-09,monthly,Whole,OFV,18511,32,99,14,77,0,18733,https://ofv.no/aktuelt/x"


def tmp_csv(lines=HISTORY) -> Path:
    p = Path(tempfile.mkdtemp()) / "Norway.csv"
    p.write_bytes(("\r\n".join([HEADER] + lines) + "\r\n").encode())
    return p


def parse(html: str) -> dict:
    t = fn.tables_of(html)
    return next(fn.parse_fuel_table(x) for x in t if fn.is_fuel_table(x))


def raises(fn_, *a, contains="") -> None:
    try:
        fn_(*a)
    except RuntimeError as e:
        assert contains in str(e), e
        return
    raise AssertionError(f"{fn_.__name__} did not raise")


# ── labels and the fuel table ──────────────────────────────────────────────

def test_every_label_has_a_case():
    assert set(LABEL_CASES) == set(fn.FUEL_LABELS), set(LABEL_CASES) ^ set(fn.FUEL_LABELS)


def test_label_mapping():
    for label, col in LABEL_CASES.items():
        rows = [("Elektrisitet", "100", "", "", "")] if col != "BEV" else []
        rows.append((label.title(), "7", "", "", ""))
        f = parse(fuel_html(rows, ("107" if col != "BEV" else "7", "")))
        assert f["cur"][col] == 7, (label, f["cur"])


def test_september_2026():
    f = parse(car_article())
    assert fn.period_of(f) == "2026-09"
    assert fn.to_counts(f["cur"]) == {"BEV": 18511, "PHEV": 32, "HEV": 99, "PETROL": 14,
                                      "DIESEL": 77, "OTHERS": 0, "TOTAL": 18733}
    assert f["ytd"]["TOTAL"] == 115196 and f["ytd"]["PHEV"] == 625
    assert fn.validate(f) == []


def test_unknown_label_aborts():
    rows = SEP26 + [("Ammoniakk", "1", "0,01 %", "1", "0,00 %")]
    raises(parse, fuel_html(rows, ("18 734", "115 197")), contains="unknown OFV fuel")


def test_sum_mismatch_is_caught():
    f = parse(fuel_html(SEP26, ("18 800", "115 196")))
    assert any("sum to" in p for p in fn.validate(f))


def test_shifted_column_is_caught():
    rows = [(a, b, "12,00 %", c, d) if a == "Diesel" else (a, b, s, c, d)
            for a, b, s, c, d in SEP26]
    assert any("columns shifted" in p for p in fn.validate(parse(fuel_html(rows))))


def test_month_from_caption():
    assert fn.month_year("Fordeling per drivstoff i desember 2025 og hittil i år") == (2025, 12)
    assert fn.month_year("hittil i år") is None
    raises(fn.parse_fuel_table, {"caption": "Fordeling per drivstoff",
                                 "rows": [["Drivstoff", "Antall"], ["Elektrisitet", "1"],
                                          ["Total", "1"]]}, contains="without a month")


def test_numbers_with_nbsp_and_narrow_space():
    assert fn.to_int("18 511") == 18511 and fn.to_int("112 825") == 112825
    assert fn.to_int("98,81 %") is None and fn.to_pct("98,81 %") == 98.81


# ── cars vs vans ───────────────────────────────────────────────────────────

def test_van_article_is_skipped():
    assert fn.article_for("2026-09", "u", van_article()) is None
    hit = fn.article_for("2026-09", "u", car_article())
    assert hit and hit["fuel"]["cur"]["TOTAL"] == 18733


def test_other_month_is_skipped():
    assert fn.article_for("2026-08", "u", car_article()) is None


# ── export.json ────────────────────────────────────────────────────────────

def test_export_parsing():
    assert fn.export_month_total(EXPORT, "2026-09") == 18733
    assert fn.export_month_total(EXPORT, "2025-01") == 9343
    assert fn.export_month_total(EXPORT, "2024-01") is None
    end, mix = fn.export_fuel_ytd(EXPORT)
    assert end == "2026-09" and mix["PHEV"] == 625 and mix["HEV"] == 709 and mix["TOTAL"] == 115196


def test_export_agrees_with_article():
    assert fn.export_check(parse(car_article()), EXPORT) == []


def test_export_disagreement_aborts():
    e = copy.deepcopy(EXPORT)
    e["data"]["personbiler"]["monthly"][8]["current"] = 18700
    assert any("export.json has" in p for p in fn.export_check(parse(car_article()), e))
    e = copy.deepcopy(EXPORT)
    e["data"]["personbiler"]["fuelMix"][0]["value"] = 112000
    assert any("fuel mix" in p for p in fn.export_check(parse(car_article()), e))


def test_export_disagreement_passes_with_force():
    e = copy.deepcopy(EXPORT)
    e["data"]["personbiler"]["monthly"][8]["current"] = 18700
    have = fn.existing_rows(tmp_csv())
    art = fn.article_for("2026-09", "https://ofv.no/aktuelt/x", car_article())
    raises(fn.process, art, have, e, False, [], contains="export.json has")
    line, _ = fn.process(art, have, e, True, [])
    assert line == SEP26_LINE


def test_export_unknown_fuel_aborts():
    e = copy.deepcopy(EXPORT)
    e["data"]["personbiler"]["fuelMix"].append({"name": "Ammoniakk", "value": 1})
    raises(fn.export_fuel_ytd, e, contains="unknown fuel")


def test_derive_from_export():
    have = fn.existing_rows(tmp_csv())
    d = fn.derive_from_export("2026-09", EXPORT, have)
    # The committed Jan-Aug rows are one car off OFV's year-to-date per fuel.
    assert d["TOTAL"] == 18732 and d["BEV"] == 18510 and d["PHEV"] == 32
    assert fn.derive_from_export("2026-08", EXPORT, have) is None   # export is to 09
    assert fn.derive_from_export("2026-09", EXPORT, {}) is None     # earlier months missing


# ── checks against the history ─────────────────────────────────────────────

def test_ytd_check():
    have = fn.existing_rows(tmp_csv())
    msg, dev = fn.ytd_check(parse(car_article()), have)
    assert abs(dev) < fn.YTD_WARN, msg


def test_plausibility():
    have = fn.existing_rows(tmp_csv())
    assert round(fn.plausibility("2026-09", 18733, have), 2) == 1.30


def test_process_writes_ofv_line():
    have = fn.existing_rows(tmp_csv())
    art = fn.article_for("2026-09", "https://ofv.no/aktuelt/x", car_article())
    line, counts = fn.process(art, have, EXPORT, False, [])
    assert line == SEP26_LINE, line


# ── upsert ─────────────────────────────────────────────────────────────────

def test_upsert_keeps_crlf_and_untouched_bytes():
    p = tmp_csv()
    before = p.read_bytes()
    stats = fn.upsert_lines(p, {"2026-09": SEP26_LINE}, force=False)
    after = p.read_bytes()
    assert stats["added"] == 1
    assert after.startswith(before) and after[len(before):] == (SEP26_LINE + "\r\n").encode()


def test_upsert_keeps_a_stray_lf_line():
    # data/Norway.csv is CRLF except the 2026-07 row (LF): it must stay LF.
    p = tmp_csv()
    raw = p.read_bytes().replace(b"9617.0,\r\n", b"9617.0,\n")
    p.write_bytes(raw)
    fn.upsert_lines(p, {"2026-09": SEP26_LINE}, force=False)
    assert p.read_bytes() == raw + (SEP26_LINE + "\r\n").encode()


def test_upsert_inserts_in_order():
    p = tmp_csv(HISTORY[:-1])                       # without 2026-08
    line = "2026-08,monthly,Whole,OFV,1,0,0,0,0,0,1,"
    fn.upsert_lines(p, {"2026-08": line, "2026-09": SEP26_LINE}, force=False)
    assert p.read_text().splitlines()[-2:] == [line, SEP26_LINE]


def test_upsert_replaces_only_when_allowed():
    p = tmp_csv()
    new = "2026-08,monthly,Whole,OFV,13274,51,31,30,65,0,13451,https://ofv.no/aktuelt/y"
    assert fn.upsert_lines(p, {"2026-08": new}, force=False)["skipped"] == 1
    assert fn.upsert_lines(p, {"2026-08": new}, force=False,
                           replace=frozenset({"2026-08"}))["updated"] == 1
    assert new in p.read_text()


def test_replaceable():
    assert fn.replaceable(None)
    assert fn.replaceable({"source": "ACEA", "notes": ""})
    assert fn.replaceable({"source": "OFV", "notes": fn.EXPORT_NOTE})
    assert not fn.replaceable({"source": "OFV", "notes": "https://ofv.no/aktuelt/x"})
    assert not fn.replaceable({"source": "ofv.no & ACEA", "notes": ""})


# ── discovery ──────────────────────────────────────────────────────────────

RSS = """<rss><channel>
<item><title>Sterk vekst</title><link>https://ofv.no/aktuelt/a</link>
<pubDate>Thu, 01 Oct 2026 05:37:00 GMT</pubDate></item>
<item><title>Gammel</title><link>https://ofv.no/aktuelt/b</link>
<pubDate>Mon, 14 Sep 2026 20:00:00 GMT</pubDate></item>
</channel></rss>"""
SITEMAP = """<urlset><url><loc>https://ofv.no/aktuelt/a</loc><lastmod>2026-10-02T08:00:00Z</lastmod></url>
<url><loc>https://ofv.no/aktuelt/b</loc><lastmod>2026-06-25T00:00:00Z</lastmod></url>
<url><loc>https://ofv.no/om-ofv</loc><lastmod>2026-10-02T00:00:00Z</lastmod></url></urlset>"""


def test_rss_and_sitemap_window():
    assert fn.rss_candidates(RSS, date(2026, 10, 1)) == [("https://ofv.no/aktuelt/a", "Sterk vekst")]
    assert fn.sitemap_candidates(SITEMAP, date(2026, 10, 1)) == [("https://ofv.no/aktuelt/a", "")]


# ── brand + model tables ───────────────────────────────────────────────────

def test_split_model():
    brands = ["TESLA", "MERCEDES-BENZ", "POLESTAR", "MG", "LAND ROVER"]
    assert fn.split_model("Polestar Polestar 2", brands) == ("POLESTAR", "POLESTAR 2")
    assert fn.split_model("MG MG4", brands) == ("MG", "MG4")
    assert fn.split_model("Land Rover Defender", brands) == ("LAND ROVER", "DEFENDER")
    assert fn.split_model("Zeekr 7GT", brands) == ("ZEEKR", "7GT")


def test_month_units_and_top():
    units = fn.month_units(fn.tables_of(car_article()), "2026-09", 18733)
    assert units[(market_top.ALL, "TESLA", "")] == 4935
    assert units[(market_top.ALL, "TESLA", "MODEL Y")] == 4810
    top = fn.build_norway_top({"2026-09": (units, 18733)})
    cls = top["classes"]["ALL"]
    assert cls["brands"][0]["brand"] == "TESLA" and cls["models"][0]["model"] == "MODEL Y"
    assert top["total_registrations"] == 18733 and top["as_of"] == "2026-09"


def test_month_units_wrong_month_raises():
    html = (ranking_html("merkene", BRANDS, month="august 2026") + fuel_html())
    raises(fn.month_units, fn.tables_of(html), "2026-09", 18733, contains="is for 2026-08")


def main() -> int:
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    failed = 0
    for name, f in tests:
        try:
            f()
            print(f"ok   {name}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"FAIL {name}: {type(e).__name__}: {e}")
    print(f"{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
