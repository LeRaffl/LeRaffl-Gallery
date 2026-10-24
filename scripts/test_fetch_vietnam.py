#!/usr/bin/env python3
"""Regression tests for scripts/fetch_vietnam.py (no network).

Run:  python scripts/test_fetch_vietnam.py

Vietnam is stitched from three publishers (VAMA member sales, VinFast's
monthly release, TC Group's Hyundai release), and every one of them fails
quietly: a reworded sentence, a mis-uploaded detail sheet, a cumulative
figure read as a monthly one. These cases pin the parsers on real samples
(the September 2026 VAMA PDFs in scripts/fixtures/vietnam/, snippets of the
VinFast and TC pages), the powertrain split of VAMA's hybrid block, the YTD
derivation for a missing detail sheet, the VinFast revision rule and the
column composition (September 2026 = 51,013).

The PDF cases need pdftotext (poppler-utils) and pdfplumber; they are
skipped with a note when either is missing.
"""
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_vietnam as fv  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures" / "vietnam"
FAILS: list[str] = []


def check(cond, msg):
    if not cond:
        FAILS.append(msg)
        print("FAIL:", msg)


def eq(got, want, msg):
    check(got == want, f"{msg}: got {got!r}, want {want!r}")


def have_pdf_tools() -> bool:
    try:
        import pdfplumber  # noqa: F401
    except ImportError:
        return False
    return shutil.which("pdftotext") is not None


# ── helpers ────────────────────────────────────────────────────────────────
def test_months():
    eq(fv.month_of("Deember"), 12, "VAMA's 'Deember' typo")
    eq(fv.month_of("Sept"), 9, "abbreviation")
    eq(fv.prev_period("2026-01"), "2025-12", "prev across the year")
    eq(fv.next_period("2025-12"), "2026-01", "next across the year")
    import datetime as dt
    eq(fv.default_target(dt.date(2026, 10, 3)), "2026-09", "default target = previous month")
    eq(fv.num("23.624"), 23624, "Vietnamese thousands dot")
    eq(fv.num("23,624"), 23624, "English thousands comma")


# ── VAMA ───────────────────────────────────────────────────────────────────
LISTING = """
<ul class="document-list">
<li class="item"><h3 class="item__title"><b><a href="/Data/upload/files/2026/BCBH/Cover%20Letter%20Sales%20report%20-%20September%202026%20(ENG).pdf">Sales report September 2026</a></b></h3></li>
<li class="item"><h3 class="item__title"><a href="/Data/upload/files/2026/BCBH/VAMA%20sales%20report%20September%202026%20-%20%20BMW-Mini.pdf">* VAMA sales report September 2026 - BMW-Mini.pdf</a></h3></li>
<li class="item"><h3 class="item__title"><a href="/Data/upload/files/2026/BCBH/VAMA%20sales%20report%20September%202026%20-%20%20Detail.pdf">* VAMA sales report September 2026 - Detail.pdf</a></h3></li>
<li class="item"><h3 class="item__title"><b><a href="/Data/upload/files/2024/T12/Cover.pdf">Sales report Deember 2024</a></b></h3></li>
</ul>"""


def test_vama_listing():
    got = fv.vama_listing(LISTING)
    eq(sorted(got), ["2024-12", "2026-09"], "listing periods")
    check(got["2026-09"]["cover"].endswith("September%202026%20(ENG).pdf"), "cover link")
    check(got["2026-09"]["detail"].endswith("Detail.pdf"), "detail link (not BMW-Mini)")
    check("detail" not in got["2024-12"], "no detail attachment → none")


def test_cover_fixture():
    f = fv.parse_cover(fv.pdf_text((FIX / "vama-cover-2026-09.pdf").read_bytes()))
    eq(f["period"], "2026-09", "cover period")
    eq((f["ti"], f["ti_pc"], f["ti_cv"], f["ti_spv"]), (35094, 24655, 9807, 632), "total industry split")
    eq((f["members_pc"], f["members_bev"], f["members_hybrid"]), (17440, 3, 2168), "member subtotals")


def test_cover_ti_typo():
    # 2024-11: the letter printed 40,200 while PC+CV+SPV = 44,200 → the sum wins.
    text = ("The November 2024 industry is at 44,200 units.\n"
            "Total industry was at 40,200 units, of which 34,000 units were Passenger Cars; 9,900 units\n"
            "were Commercial Vehicles and 300 units were Special-Purpose Vehicles.\n")
    f = fv.parse_cover(text)
    eq(f.get("ti"), 44200, "TI typo replaced by PC+CV+SPV")
    check("ti_note" in f, "TI typo leaves a note")


def test_detail_fixture():
    d = fv.parse_detail((FIX / "vama-detail-2026-09.pdf").read_bytes())
    eq(d["period"], "2026-09", "detail header period")
    u = fv.detail_units(d["rows"])
    eq(fv.exceptions(u), {"vama_mhev": 113, "vama_hev_in_pc": 116, "vama_bev_in_pc": 0},
       "Sep 2026 exceptions (XL7 Hybrid MHEV, Land Cruiser Hybrid in the PC block)")
    eq(u.get(("MHEV", "SUZUKI", "XL7 HYBRID")), 113, "XL7 Hybrid = MHEV")
    hy = sum(n for (c, _, m), n in u.items() if c in ("HEV", "MHEV") and "#pc" not in m)
    eq(hy, 2168, "hybrid block = cover subtotal")
    check(all(b != "THACO KIA" for (_, b, _) in u), "THACO KIA → KIA")


def test_classify():
    r = lambda model, cls, maker="TOYOTA": {"maker": maker, "model": model, "cls": cls}  # noqa: E731
    eq(fv.classify(r("XL7 HYBRID", "Hybrid", "SUZUKI")), "MHEV", "XL7 Hybrid")
    eq(fv.classify(r("ERTIGA HYBRID", "Hybrid", "SUZUKI")), "MHEV", "Ertiga Hybrid")
    eq(fv.classify(r("COROLLA CROSS HEV", "Hybrid")), "HEV", "Toyota HEV")
    eq(fv.classify(r("NEW SORENTO HEV/PHEV", "Hybrid", "THACO KIA")), "HEV", "Sorento HEV/PHEV pooled → HEV")
    eq(fv.classify(r("LANDCRUISER HYBRID", "SUV")), "HEV", "hybrid in the PC block")
    eq(fv.classify(r("VIOS", "Sedan")), "ICE", "plain PC")
    eq(fv.classify(r("HILUX", "Pick-up")), None, "commercial classes out of scope")
    eq(fv.brand_model({"maker": "THACO MAZDA", "model": "CX-5 (CKD)", "cls": "SUV"}), ("MAZDA", "CX-5"),
       "maker map + CKD tag stripped")


def test_derive_from_ytd():
    # VAMA uploaded January's sheet as May 2025 and February 2026: the month is
    # rebuilt as YTD[M+1] − month[M+1] − YTD[M−1].
    prev = {"rows": [{"maker": "SUZUKI", "model": "XL7 HYBRID", "cls": "Hybrid", "month": 50, "ytd": 400}]}
    nxt = {"rows": [{"maker": "SUZUKI", "model": "XL7 HYBRID", "cls": "Hybrid", "month": 70, "ytd": 600}]}
    eq(fv.derive_units_from_ytd(prev, nxt, "2025-05"), {("MHEV", "SUZUKI", "XL7 HYBRID"): 130}, "YTD derivation")
    eq(fv.derive_units_from_ytd(None, nxt, "2026-01"), {("MHEV", "SUZUKI", "XL7 HYBRID"): 530},
       "January: YTD of February − February")


# ── VinFast ────────────────────────────────────────────────────────────────
VG_VN = (  # vingroup.net, 10-10-2026 (excerpt)
    "Hà Nội, ngày 10/10/2026 - VinFast công bố đã bàn giao 23.624 ô tô điện các loại tại thị trường Việt Nam "
    "trong tháng 9/2026, đạt mức tăng trưởng 17% so với tháng 8. Lũy kế 9 tháng đầu năm, VinFast đã bán ra "
    "thị trường tổng cộng 177.697 xe, tương đương với mức trung bình gần 20.000 xe bán ra mỗi tháng. "
    "Trong số 23.624 xe VinFast bán ra thị trường trong tháng 9, có tới 6.474 chiếc VF 3, khẳng định mạnh mẽ "
    "vị thế “xe điện quốc dân”. Tính lũy kế từ đầu năm, đã có 42.272 xe VF 3 được bàn giao tới khách hàng. "
    "Xếp thứ hai trong danh sách xe bán chạy nhất của VinFast tháng 9 là mẫu MPV 7 chỗ Limo Green, "
    "với 5.027 xe bán ra. Lũy kế từ đầu năm, đã có 40.018 xe Limo Green đến tay khách hàng. "
    "Xếp tiếp theo trong danh sách là hai mẫu SUV đô thị VF 6 và VF 5/Herio Green, với doanh số tương ứng là "
    "3.083 xe và 2.472 xe bán ra trong tháng 9, nâng tổng số lũy kế từ đầu năm lên lần lượt là 19.026 xe VF 6 "
    "và 30.420 xe VF 5/Herio Green.")
SEC_EN = ("VinFast Auto Ltd. announced its preliminary domestic Vietnam deliveries of 13,914 electric vehicles "
          "(“EVs”) 1 in September 2025. Cumulatively, during the first nine months of 2025, the Company "
          "delivered a total of 103,884 EVs 1 to customers in Vietnam. Notably, 3,847 VF 5 vehicles 1 were "
          "delivered in September 2025. The VF 3 ranked second, with 2,682 vehicles 1 delivered. The Herio "
          "Green ranked third with 2,173 vehicles 1 delivered, followed by the VF 6 with 1,933 vehicles 1 and "
          "the VF 7 with 778 vehicles 1 . For the first nine months of 2025, the VF 3 and the VF 5 were "
          "VinFast’s two best-selling models with cumulative deliveries of 31,386 and 30,956 vehicles 1 , "
          "respectively. The Company also delivered 14,425 VF 6 vehicles 1 during the period.")
ROUNDED = "VinFast đã bàn giao hơn 9.300 xe ô tô điện tới khách hàng trong tháng 9/2024."


def test_vinfast():
    v = fv.parse_vinfast(VG_VN)
    eq((v["units"], v["exact"], v["period"], v["ytd"]), (23624, True, "2026-09", 177697), "VN article")
    eq(v["models"], {"VF 3": 6474, "LIMO GREEN": 5027, "VF 6": 3083, "VF 5 / HERIO GREEN": 2472},
       "VN models, YTD clauses ignored")
    v = fv.parse_vinfast(SEC_EN)
    eq((v["units"], v["period"], v["ytd"]), (13914, "2025-09", 103884), "6-K text")
    eq(v["models"], {"VF 5 / HERIO GREEN": 6020, "VF 3": 2682, "VF 6": 1933, "VF 7": 778},
       "6-K models: Herio Green pooled with VF 5, footnote digits and cumulative figures ignored")
    v = fv.parse_vinfast(ROUNDED)
    eq((v["units"], v["exact"]), (9300, False), "'hơn' = rounded")


def test_vingroup_links():
    h = ('<a href="/vi/tin-tuc-su-kien/bai-viet/9096/vinfast-ban-giao-23624-o-to-dien-tai-viet-nam-trong-thang-9">x</a>'
         '<a href="/vi/tin-tuc-su-kien/bai-viet/9001/vinhomes-mo-ban">y</a>')
    links = fv.vingroup_article_links(h)
    eq(len(links), 1, "only VinFast sales articles")


# ── TC Group (Hyundai) ─────────────────────────────────────────────────────
def tc_table(rows):
    cells = lambda r: "".join(f"<td><p>{c}</p></td>" for c in r)  # noqa: E731
    return ("<table><tr><td colspan='5'>KẾT QUẢ BÁN HÀNG XE Ô TÔ HYUNDAI THÁNG 9/2026</td></tr>"
            + "".join(f"<tr>{cells(r)}</tr>" for r in rows) + "</table>")


TC_ROWS = [["Mẫu xe", "CBU/CKD", "Tháng 8/2026", "Tháng 9/2026", "Cả năm 2026"],
           ["Hyundai Grand i10", "CKD", "91", "165", "1.637"],
           ["Hyundai Tucson", "607", "1.004", "6.716"],          # rowspan: no CKD cell
           ["Hyundai Stargazer", "CBU", "153", "200", "2.597"],
           ["XE THƯƠNG MẠI", "CKD/CBU", "995", "1.138", "10.687"],
           ["Mẫu khác", "", "3", "5", "40"],
           ["TỔNG", "", "2.928", "3.872", "35.000"]]


def test_tc():
    r = fv.parse_tc(tc_table(TC_ROWS), "2026-09")
    eq((r["total"], r["commercial"]), (3872, 1138), "TC total / commercial")
    eq(r["models"], {"GRAND I10": 165, "TUCSON": 1004, "STARGAZER": 200, "": 5}, "Hyundai models")
    eq(r["prev_models"]["TUCSON"], 607, "previous-month column kept for gaps")
    eq(fv.tc_article_links('<a href="https://thanhcong.vn/tin-tuc/tc-group-thong-bao-ket-qua-ban-hang-hyundai-thang-9-2026.html">'
                           '</a><a href="https://thanhcong.vn/tin-tuc/ban-hang-thang-9-2025.html"></a>', "2026-09"),
       ["https://thanhcong.vn/tin-tuc/tc-group-thong-bao-ket-qua-ban-hang-hyundai-thang-9-2026.html"], "TC link by month")


# ── composition & revision ─────────────────────────────────────────────────
SEP26 = {"period": "2026-09", "vama_ti": "35094", "vama_ti_pc": "24655", "vama_ti_cv": "9807",
         "vama_ti_spv": "632", "vama_members_pc": "17440", "vama_members_hybrid": "2168",
         "vama_members_bev": "3", "vama_mhev": "113", "vama_hev_in_pc": "116", "vama_bev_in_pc": "0",
         "vama_detail": "ok", "vinfast": "23624", "vinfast_ytd": "177697", "vinfast_kind": "exact",
         "vinfast_models": "", "tc_total": "3872", "tc_commercial": "1138", "hyundai_models": "",
         "src_vama": "", "src_vinfast": "", "src_tc": "", "note": ""}


def test_compose():
    c = fv.compose(dict(SEP26))
    got = {k: float(c[k]) for k in ("BEV", "HEV", "MHEV", "ICE", "OTHERS", "TOTAL")}
    eq(got, {"BEV": 23627, "HEV": 2171, "MHEV": 113, "ICE": 20058, "OTHERS": 5044, "TOTAL": 51013},
       "Sep 2026 composition")
    check(fv.complete(SEP26), "complete row")
    check(not fv.complete(dict(SEP26, tc_total="")), "TC missing → incomplete")


def test_revision():
    comp = {"2026-07": dict(SEP26, period="2026-07", vinfast="21781", vinfast_ytd="137697"),
            "2026-06": dict(SEP26, period="2026-06", vinfast="17955", vinfast_ytd="115916"),
            "2026-08": dict(SEP26, period="2026-08", vinfast="20161", vinfast_ytd="154073")}
    msg = fv.apply_vinfast_revision(comp, "2026-08")
    check(msg and "17,996" in msg, f"July 2026 revised: {msg}")
    eq((comp["2026-07"]["vinfast"], comp["2026-07"]["vinfast_kind"]), ("17996", "revised"), "revised row")
    eq(fv.apply_vinfast_revision(comp, "2026-08"), None, "idempotent")
    comp["2026-01"] = dict(SEP26, period="2026-01", vinfast="16172", vinfast_ytd="16172")
    eq(fv.apply_vinfast_revision(comp, "2026-01"), None, "no revision across the year")


def test_models_roundtrip():
    d = {"VF 3": 6474, "": 5}
    eq(fv.parse_models(fv.fmt_models(d)), d, "model list round trip")


def test_csv_roundtrip():
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "Vietnam.csv"
        fv.write_csv({"2026-09": dict(SEP26)}, p)
        text = p.read_text()
        check("2026-09,monthly,Whole,VAMA + VinFast + TC Group,23627.0,,2171.0,113.0,20058.0,5044.0,51013.0,"
              in text, f"CSV row layout: {text!r}")
        eq(fv.write_csv({"2026-09": dict(SEP26)}, p), [], "unchanged rewrite reports nothing")


# ── reference checks (scripts/check_vietnam_reference.py) ─────────────────
def test_reference_checks():
    import datetime as dt
    import check_vietnam_reference as cr
    comp = {"2026-08": dict(SEP26, period="2026-08", vama_ti="29000", vinfast="17000", tc_total="2484"),
            "2026-09": dict(SEP26)}
    refs = [{"kind": "media_total", "period_from": "2026-09", "period_to": "2026-09", "figure": "62590",
             "rounded": "no", "url": "https://x", "note": ""},
            {"kind": "media_total", "period_from": "2026-08", "period_to": "2026-08", "figure": "48600",
             "rounded": "no", "url": "", "note": "first-reported VinFast"},
            {"kind": "csgt", "period_from": "2025-12-15", "period_to": "2026-09-14", "figure": "513679",
             "rounded": "no", "url": "https://y", "note": ""}]
    got = {c["period"]: c for c in cr.check_rows(comp, refs)}
    eq((got["2026-09"]["ours"], got["2026-09"]["status"]), (62590, "pass"), "media total = our inputs")
    eq(got["2026-08"]["status"], "warn", "gap beyond 0.1 % warns")
    eq(got["2025-12-15 → 2026-09-14"]["status"], "info", "CSGT is information only")
    lines, missing = cr.due_items(comp, refs[2:], dt.date(2026, 10, 24))
    eq([m["period"] for m in missing], ["2026-08", "2026-09"], "media totals due after the 20th")
    check(any("URL missing" in x for x in cr.due_items(comp, refs, dt.date(2026, 10, 24))[0]),
          "empty URL is due")
    check(any("CSGT H1 2026" in x for x in lines), "CSGT H1 due from July")


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    pdf = have_pdf_tools()
    for t in tests:
        if t.__name__ in ("test_cover_fixture", "test_detail_fixture") and not pdf:
            print(f"skip {t.__name__}: pdftotext/pdfplumber missing")
            continue
        t()
    print(f"{len(tests)} groups, {len(FAILS)} failures")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
