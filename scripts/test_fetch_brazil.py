#!/usr/bin/env python3
"""Regression tests for the ANFAVEA Central de Dados parser in fetch_brazil.py.

Run with plain Python, no test framework and no network:

    python scripts/test_fetch_brazil.py

The fixture is the exact markup admin-ajax.php (action=anfavea_dashboard1)
returned on 2026-09-23 for Total Leves by fuel, trimmed to two months plus the
closing TOTAL row.
"""
import csv
import sys
import tempfile
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import fetch_brazil as fb  # noqa: E402

B = 'style="border-left:2px solid #dee2e6"'


def cell(v: int, display: str) -> str:
    return f'<td data-valor-export="{v}">{display}</td>'


def row(label: str, vals: list[tuple[int, str]], total: tuple[int, str]) -> str:
    return (f"<tr><td><strong>{label}</strong></td>" + "".join(cell(*v) for v in vals)
            + f'<td {B}><strong data-valor-export="{total[0]}">{total[1]}</strong></td></tr>')


HEADER = ["DIESEL", "ELÉTRICO", "ETANOL", "FLEX FUEL", "GASOLINA", "HÍBRIDO", "HÍBRIDO PLUG-IN"]
FIXTURE = (
    '<div style="overflow-x:auto;"><table class="table table-striped anfavea-table" '
    'data-formato="numero"><caption>Emplacamento de Total Leves</caption><thead><tr>'
    "<th>PERÍODO</th>" + "".join(f"<th>TOTAL LEVES - {h}</th>" for h in HEADER)
    + f"<th {B}>TOTAL</th></tr></thead><tbody>"
    + row("2026 - JUL", [(23814, "23.814"), (25858, "25.858"), (523, "523"), (172957, "172.957"),
                         (6049, "6.049"), (16716, "16.716"), (19749, "19.749")], (265666, "265.666"))
    + row("2026 - AGO", [(22423, "22.423"), (27251, "27.251"), (796, "796"), (170145, "170.145"),
                         (5528, "5.528"), (17823, "17.823"), (19125, "19.125")], (263091, "263.091"))
    + row("TOTAL", [(46237, "46.237"), (53109, "53.109"), (1319, "1.319"), (343102, "343.102"),
                    (11577, "11.577"), (34539, "34.539"), (38874, "38.874")], (528757, "528.757"))
    + "</tbody></table></div>"
)


def test_parse_table():
    rows = fb.parse_table(FIXTURE)
    assert sorted(rows) == ["2026-07", "2026-08"], rows.keys()
    aug = rows["2026-08"]
    assert aug["BEV"] == 27251 and aug["PHEV"] == 19125 and aug["HEV"] == 17823
    assert aug["PETROL"] == 5528 and aug["DIESEL"] == 22423 and aug["FLEXFUEL"] == 170145
    assert aug["OTHERS"] == 796  # ETANOL
    assert aug["TOTAL"] == 263091
    assert aug["variant"] == "Whole" and aug["source"] == "ANFAVEA"


def test_unknown_fuel_aborts():
    bad = FIXTURE.replace("TOTAL LEVES - ETANOL", "TOTAL LEVES - HIDROGÊNIO")
    try:
        fb.parse_table(bad)
    except RuntimeError as e:
        assert "HIDROGÊNIO" in str(e)
    else:
        raise AssertionError("unknown fuel column was silently accepted")


def test_total_mismatch_aborts():
    bad = FIXTURE.replace('data-valor-export="263091"', 'data-valor-export="263092"')
    try:
        fb.parse_table(bad)
    except RuntimeError as e:
        assert "2026-08" in str(e)
    else:
        raise AssertionError("TOTAL mismatch went unnoticed")


def test_parse_period():
    assert fb.parse_period("2026 - AGO") == "2026-08"
    assert fb.parse_period("2025 - DEZ") == "2025-12"
    assert fb.parse_period("TOTAL") is None


def test_default_window():
    assert fb.default_window(date(2026, 9, 23)) == ("2026-01", "2026-09")
    # Jan/Feb still re-read the previous year so December lands.
    assert fb.default_window(date(2027, 1, 10)) == ("2026-01", "2027-01")
    assert fb.default_window(date(2027, 3, 10)) == ("2027-01", "2027-03")


def test_upsert_keeps_untouched_rows_byte_identical():
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "Brazil.csv"
        original = (
            ",".join(fb.CSV_COLUMNS) + "\n"
            "2012-01,monthly,Whole,ANFAVEA,0.6370529281764102,0.0,9.0,24554.0,16687.0,"
            "211422.0,0.0,252672.6371,\n"
            "2026-07,monthly,Whole,ANFAVEA,25787.0,19138.0,17375.0,6065.0,23809.0,172964.0,"
            "0.0,265138.0,siteautoveiculos2026.xlsx\n"
        )
        path.write_text(original, encoding="utf-8")
        added, updated = fb.upsert_csv(str(path), fb.parse_table(FIXTURE), fb.PROVENANCE)
        assert (added, updated) == (1, 1)
        lines = path.read_text(encoding="utf-8").splitlines()
        assert lines[1] == original.splitlines()[1]
        with open(path, newline="", encoding="utf-8") as f:
            got = {r["period"]: r for r in csv.DictReader(f)}
        assert got["2026-07"]["BEV"] == "25858.0" and got["2026-07"]["OTHERS"] == "523.0"
        assert got["2026-08"]["TOTAL"] == "263091.0"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"ok  {t.__name__}")
    print(f"{len(tests)} passed")
