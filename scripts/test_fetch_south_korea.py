#!/usr/bin/env python3
"""Regression tests for scripts/fetch_south_korea.py (no network).

Run:  python scripts/test_fetch_south_korea.py

The fixtures are the text pdfplumber extracts from real MOTIR releases
(«2026년 8월 자동차산업 동향», «2025년 1분기 …»), trimmed to the lines the
parser reads. They pin: the header-driven month mapping (also for quarterly
releases), the eco table ending before the export table that repeats the
same row labels, the sum and ICE checks, and the line-level upsert that
leaves numerically equal rows byte-for-byte alone.
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_south_korea as fk  # noqa: E402

AUG_2026 = """표 3) '26년 8월 자동차 생산, 내수, 수출량
[단위 : 대, %]
‘25.8월 ‘26.7월 ‘25.1~8월
구 분 ‘25.8월 '26.7월 '26.8월 '25.1∼8월 '26.1∼8월
대비 대비 대비
생산량 320,942 351,973 206,064 △35.8 △41.5 2,748,324 2,668,941 △2.9
내수 판매량 138,824 139,231 109,920 △20.8 △21.1 1,103,955 1,096,740 △0.7
국산차 110,352 106,953 78,881 △28.5 △26.2 900,524 839,869 △6.7
참고 1 '26년 8월 업체별 자동차 생산·내수·수출 동향
구 분 ‘25.8월 '26.7월 '26.8월 '25.1∼8월 '26.1∼8월
내 수 138,824 139,231 109,920 △20.8 △21.1 1,103,955 1,096,740 △0.7
현대 58,330 48,088 34,333 △41.1 △28.6 469,462 399,086 △15.0
참고 2 '26년 8월 친환경차 내수·수출 동향
□ (내수) '26년 8월 친환경차 내수 판매량은 68,808대(전년동월비 △2.3%)
《 ’26년 8월 친환경차 차종별 내수 판매 현황 》
[단위 : 대, %]
‘25.8월 ‘26.7월 ‘25.1~8월
구 분 ‘25.8월 '26.7월 '26.8월 '25.1∼8월 '26.1∼8월
대비 대비 대비
증감률 증감률 증감률
친환경차 내수 70,442 84,186 68,808 △2.3 △18.3 528,243 647,556 22.6
하이브리드 43,809 46,092 36,102 △17.6 △21.7 374,212 366,504 △2.1
전기차 24,344 35,936 31,060 27.6 △13.6 140,952 268,092 90.2
플러그인 하이브리드 997 1,073 1,334 33.8 24.3 9,462 8,259 △12.7
수소차 1,292 1,085 312 △75.9 △71.2 3,617 4,701 30.0
* 출처 : 한국자동차모빌리티산업협회, 한국수입자동차협회(수입차는 MHEV 포함)
《 ’26년 8월 친환경차 차종별 수출 현황 》
구 분 ‘25.8월 '26.7월 '26.8월 '25.1∼8월 '26.1∼8월
친환경차 수출 69,500 87,865 58,126 △16.4 △33.8 560,423 679,137 21.2
하이브리드 43,277 58,091 35,723 △17.5 △38.5 348,763 460,801 32.1
전기차 22,529 27,760 21,404 △5.0 △22.9 170,917 203,660 19.2
"""

Q1_2025 = """참고 1 '25년 3월 업체별 자동차 생산·내수·수출 동향
‘24.3월 ‘25.2월 ‘24.1분기
구 분 ‘24.3월 '25.2월 '25.3월 '24.1분기 '25.1분기
내 수 146,019 132,854 149,512 2.4 12.5 378,228 388,294 2.7
참고 2 '25년 3월 친환경차 내수·수출 동향
‘24.3월 ‘25.2월 ‘24.1분기
구 분 ‘24.3월 '25.2월 '25.3월 '24.1분기 '25.1분기
대비 대비 대비
친환경차 내수 61,497 60,294 69,879 13.6 15.9 139,577 169,013 21.1
하이브리드 40,402 44,615 49,527 22.6 11.0 111,766 130,197 16.5
전기차 20,225 14,179 18,708 △7.5 31.9 25,461 34,550 35.7
플러그인 하이브리드 585 1,204 1,302 122.6 8.1 1,718 3,598 109.4
수소차 285 296 342 20.0 15.5 632 668 5.7
* 출처 : 한국자동차모빌리티산업협회, 한국수입자동차협회(수입차는 MHEV 포함)
"""


def test_aug_2026_release():
    p = fk.parse_release(AUG_2026)
    assert p["months"] == ["2025-08", "2026-07", "2026-08"]
    rows = fk.rows_of(p)
    assert rows["2026-08"] == {"HEV": 36102, "BEV": 31060, "PHEV": 1334, "OTHERS": 312,
                               "ICE": 109920 - 68808, "TOTAL": 109920}
    # the previous month fills a month without a release of its own
    assert rows["2026-07"]["BEV"] == 35936 and rows["2026-07"]["TOTAL"] == 139231
    # the export table below repeats 하이브리드/전기차 — must not leak in
    assert rows["2026-08"]["HEV"] != 35723


def test_quarterly_release_header():
    """«1분기» releases have only 내 수 (참고 1) and a quarter label in the header."""
    rows = fk.rows_of(fk.parse_release(Q1_2025))
    assert sorted(rows) == ["2024-03", "2025-02", "2025-03"]
    assert rows["2025-03"]["TOTAL"] == 149512 and rows["2025-03"]["ICE"] == 149512 - 69879


def test_month_labels():
    assert fk.header_months("구 분 ‘25.8월 '26.7월 '26.8월 '25.1∼8월 '26.1∼8월") == \
        ["2025-08", "2026-07", "2026-08"]
    assert fk.header_months("구 분 ‘25.12월 '26.11월 '26.12월 '25년 '26년") == \
        ["2025-12", "2026-11", "2026-12"]
    assert fk.month_add("2026-01", -1) == "2025-12" and fk.month_add("2026-01", -12) == "2025-01"


def expect_parse_error(text, words):
    try:
        fk.rows_of(fk.parse_release(text))
    except fk.ParseError as e:
        assert words in str(e), str(e)
    else:
        raise AssertionError(f"expected ParseError with {words!r}")


def test_guards():
    expect_parse_error(AUG_2026.replace("수소차 1,292 1,085 312", "수소차 1,292 1,085 9,312"),
                       "eco parts sum")
    expect_parse_error(AUG_2026.replace("'26.7월 '26.8월 '25.1∼8월", "'26.6월 '26.8월 '25.1∼8월"),
                       "not (cur−12, cur−1, cur)")
    expect_parse_error(AUG_2026.replace("내 수 138,824 139,231 109,920", "내 수 138,824 139,231 109,921"),
                       "≠ 내 수")
    expect_parse_error(AUG_2026.replace("친환경차 내수 70,442", "친환경 내수 70,442"), "not found")
    expect_parse_error(AUG_2026.replace("플러그인 하이브리드 997", "플러그인하이브리드 997"),
                       "rows missing")


def test_upsert_keeps_equal_rows():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "South Korea.csv"
        p.write_text(",".join(fk.CSV_COLUMNS) + "\n"
                     "2026-06,monthly,Whole,motir.go.kr,39031,1113,53578,500,65503,159725,\n"
                     "2026-07,monthly,Whole,someone else,1,1,1,1,1,5,\n", encoding="utf-8")
        same = {"BEV": 39031, "PHEV": 1113, "HEV": 53578, "OTHERS": 500, "ICE": 65503, "TOTAL": 159725}
        new = {"BEV": 31060, "PHEV": 1334, "HEV": 36102, "OTHERS": 312, "ICE": 41112, "TOTAL": 109920}
        st = fk.upsert(p, {"2026-06": fk.render_line("2026-06", same),
                           "2026-07": fk.render_line("2026-07", new),
                           "2026-08": fk.render_line("2026-08", new)}, force=False)
        assert st == {"added": 1, "updated": 0, "unchanged": 1, "skipped": 1}, st
        lines = p.read_text(encoding="utf-8").splitlines()
        assert lines[1].endswith(",159725,")               # integer formatting kept
        assert lines[3].startswith("2026-08,monthly,Whole,motir.go.kr,31060.0,1334.0,")


def test_upsert_survives_nel_in_a_source_field():
    """The real 2017-04 row carries mojibake with U+0085 (NEL) in its source
    URL; str.splitlines() would split the row in two."""
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "South Korea.csv"
        row = "2017-04,monthly,Whole,https://x/?q=\u00c3\u0085+\u00c3,862.0,25.0,6364.0,1.0,146326.0,153578.0,"
        p.write_text(",".join(fk.CSV_COLUMNS) + "\n" + row + "\n", encoding="utf-8")
        c = {"BEV": 1, "PHEV": 1, "HEV": 1, "OTHERS": 1, "ICE": 1, "TOTAL": 5}
        fk.upsert(p, {"2026-08": fk.render_line("2026-08", c)}, force=False)
        lines = p.read_text(encoding="utf-8").split("\n")
        assert lines[1] == row and lines[2].startswith("2026-08,"), lines


def main() -> int:
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"ok   {name}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"FAIL {name}: {type(e).__name__}: {e}")
    print(f"{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
