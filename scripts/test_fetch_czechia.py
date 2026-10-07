#!/usr/bin/env python3
"""Regression tests for scripts/fetch_czechia.py (no network).

Run:  python scripts/test_fetch_czechia.py

The fetcher's failure modes are silent: a new spelling of the free-text hybrid
class, a fuel token it does not know, or a wrong new/used rule would move
vehicles between variants or columns without any error. These cases pin the
scope (category × new/used → variant), the fuel tokens, the plug-in test
(class, CO2, the type-approval variant's evidence), the snapshot's "complete
to" month, the estimated Whole split, the line-level upsert, the month
selection, the gzip stream reader, and one end-to-end tally of a small file.
"""
import csv
import datetime as dt
import gzip
import io
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_czechia as fc  # noqa: E402

HEADER = [fc.C_FIRST, fc.C_FIRST_CZ, "ZTP", fc.C_CAT, fc.C_MAKE, fc.C_TYPE, fc.C_VAR,
          fc.C_VER, fc.C_MODEL, fc.C_FUEL, fc.C_HCLASS, fc.C_CO2, fc.C_REGISTER]


def rec(first="2026-09-10", first_cz=None, cat="M1", make="ŠKODA", typ="NX",
        var="A", ver="B", model="OCTAVIA", fuel="BA", hclass="", co2="", reg="RSV"):
    return [first, first if first_cz is None else first_cz, "x", cat, make, typ, var,
            ver, model, fuel, hclass, co2, reg]


def extract(rows) -> list[str]:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(HEADER)
    w.writerows(rows)
    return buf.getvalue().splitlines(keepends=True)


def test_fuel_tokens():
    cases = [
        ("EL", "BEV"), ("BA", "PETROL"), ("NM", "DIESEL"), ("NM + BIO NM", "DIESEL"),
        ("BA SMĚS", "PETROL"), ("BA + EL", "HYBRID"), ("EL + BA", "HYBRID"),
        ("NM + EL", "HYBRID"), ("BA + LPG", "OTHERS"), ("CNG+BA", "OTHERS"),
        ("BA + CNG", "OTHERS"), ("BA + E 85", "OTHERS"), ("VODÍK", "OTHERS"),
        ("EL + VODÍK", "OTHERS"),          # fuel cell: hydrogen
        ("BA + LPG + EL", "OTHERS"),       # gas wins, as SDA's Benzin + LPG
        ("", "UNKNOWN"),
    ]
    for palivo, want in cases:
        assert fc.base_fuel(fc.fuel_tokens(palivo)) == want, (palivo, want)


def test_hybrid_class():
    cases = [
        ("OVC-HEV", "OVC"), ("ovc-hev", "OVC"), ("OVC_HEV", "OVC"), ("0VC-HEV", "OVC"),
        ("PHEV", "OVC"), ("VHE-RE", "OVC"),
        ("NOVC-HEV", "NOVC"), ("NOVC - HEV", "NOVC"), ("N0VC-HEV", "NOVC"),
        ("novc-hev", "NOVC"), ("NO/NOVC-HEV", "NOVC"), ("NOV-HEV", "NOVC"),
        ("NOVC-HEC", "NOVC"), ("HEV", "NOVC"), ("VHE-NRE", "NOVC"),
        ("", ""), ("NA", ""),
    ]
    for raw, want in cases:
        assert fc.hybrid_class(raw) == want, (raw, want)


def test_co2_and_direct_plug_in():
    assert fc.co2_combined(" /  / 22") == 22.0
    assert fc.co2_combined("130 / 95 / 108") == 108.0
    assert fc.co2_combined("28,5") == 28.5
    assert fc.co2_combined(" /  / ") is None
    assert fc.plug_in_direct("OVC", 140.0) is True       # class beats CO2 (Euro 6e-bis)
    assert fc.plug_in_direct("NOVC", 40.0) is False
    assert fc.plug_in_direct("", 35.0) is True
    assert fc.plug_in_direct("", 60.0) is True
    assert fc.plug_in_direct("", 61.0) is None           # → the variant decides
    assert fc.plug_in_direct("", None) is None


def test_scope_and_variant_evidence():
    rows = [
        rec(cat="M1"), rec(cat="M1G"),                               # Whole ×2
        rec(first="2025-03-01", first_cz="2026-09-02"),             # used import
        rec(cat="N1"), rec(cat="N1G"),                               # Vans
        rec(cat="N2"), rec(cat="N3G"),                               # HDV
        rec(cat="M3"), rec(cat="M2"),                                # Buses
        rec(cat="N1", first="2025-01-01", first_cz="2026-09-03"),   # used van: no variant
        rec(cat="O1"), rec(cat="L3e-A3"), rec(cat="T3b"),           # out of scope
        rec(reg="RHSV"),                                             # historic register
        rec(first=""),                                               # no first date
        rec(first="2015-12-31"),                                     # before HISTORY_FROM
        # hybrids: direct evidence
        rec(fuel="BA + EL", hclass="OVC-HEV", co2="120"),           # PHEV (class)
        rec(fuel="BA + EL", co2="25"),                               # PHEV (CO2)
        rec(fuel="BA + EL", hclass="NOVC-HEV", co2="25"),           # not (class)
        # variant V1 has two OVC records → its unclassified sibling is a PHEV
        rec(fuel="BA + EL", typ="V1", hclass="OVC-HEV"),
        rec(fuel="BA + EL", typ="V1", hclass="OVC-HEV"),
        rec(fuel="BA + EL", typ="V1", co2="95"),                     # → PHEV
        # variant V2 is NOVC → its sibling is a petrol hybrid (PETROL)
        rec(fuel="BA + EL", typ="V2", hclass="NOVC-HEV", co2="100"),
        rec(fuel="BA + EL", typ="V2", co2="99"),                     # → PETROL
        rec(fuel="NM + EL", typ="V3", co2="140"),                    # no evidence → DIESEL
        rec(fuel="EL", model="ENYAQ"), rec(fuel="BA + LPG"),
    ]
    t = fc.tally_lines(extract(rows), dt.date(2026, 10, 1))
    w = t.month("Whole", "2026-09")
    # PETROL: M1 + M1G, the NOVC hybrid, V2's NOVC record and its sibling
    assert w == {"BEV": 1, "PHEV": 5, "PETROL": 5, "DIESEL": 1, "OTHERS": 1,
                 "TOTAL": 13}, w
    assert t.month("Used", "2026-09")["TOTAL"] == 1
    assert t.month("Vans", "2026-09")["TOTAL"] == 2
    assert t.month("HDV", "2026-09")["TOTAL"] == 2
    assert t.month("Buses", "2026-09")["TOTAL"] == 2
    assert t.periods("Whole") == ["2026-09"]
    assert t.complete_to == "2026-09"
    # the brand/model tallies resolve the pending hybrids the same way
    phev = sum(n for (v, p, f, b, m), n in t.models.items() if v == "Whole" and f == "PHEV")
    assert phev == 5, phev


def test_complete_month_and_snapshot():
    assert fc.complete_month(dt.date(2026, 10, 1)) == "2026-09"
    assert fc.complete_month(dt.date(2026, 10, 15)) == "2026-09"
    assert fc.complete_month(dt.date(2027, 1, 1)) == "2026-12"
    assert fc.complete_month(None) is None
    assert fc.snapshot_from_disposition(
        "attachment; filename=RSV_vypis_vozidel_20261001.csv") == dt.date(2026, 10, 1)
    assert fc.snapshot_from_disposition("attachment; filename=x.csv") is None
    assert fc.snapshot_from_disposition(None) is None


def test_whole_estimate():
    have = {
        "2026-07": {"source": "RSV (dataovozidlech.cz)", "HEV": "1", "PETROL": "1", "DIESEL": "1"},
        "2026-08": {"source": "ACEA", "HEV": "4762.0", "PETROL": "7264.0", "DIESEL": "2746.0"},
        "2026-06": {"source": "ACEA", "HEV": "6312.0", "PETROL": "11154.0", "DIESEL": "4564.0"},
    }
    p, shares = fc.reference_split(have, "2026-09")
    assert p == "2026-08"
    assert abs(sum(shares.values()) - 1) < 1e-9
    reg = {"BEV": 2000, "PHEV": 1000, "PETROL": 12000, "DIESEL": 3500, "OTHERS": 500,
           "TOTAL": 19000}
    row, note = fc.whole_row(reg, have, "2026-09")
    assert row["BEV"] == 2000 and row["PHEV"] == 1000 and row["OTHERS"] == 500
    assert row["HEV"] + row["PETROL"] + row["DIESEL"] == 15500
    assert row["TOTAL"] == 19000
    assert "estimated from the 2026-08 ACEA split" in note
    # an own (register) row is never the reference
    assert fc.reference_split({"2026-08": have["2026-07"]}, "2026-09") is None
    assert fc.split_remainder(10, {"HEV": 1 / 3, "PETROL": 1 / 3, "DIESEL": 1 / 3}) \
        in ({"HEV": 4, "PETROL": 3, "DIESEL": 3}, {"HEV": 3, "PETROL": 4, "DIESEL": 3},
            {"HEV": 3, "PETROL": 3, "DIESEL": 4})


def test_months_to_write():
    rows = [rec(first=d) for d in ("2016-01-05", "2026-07-01", "2026-08-01", "2026-09-01")]
    t = fc.tally_lines(extract(rows), dt.date(2026, 10, 1))
    have = {"2026-07": {}, "2026-08": {}}
    assert fc.months_to_write(t, "Whole", have, "2026-09", False, False) == ["2026-09"]
    assert fc.months_to_write(t, "Whole", {**have, "2026-09": {}}, "2026-09",
                              False, False) == []
    # backfill never reaches before WHOLE_FROM for Whole …
    assert fc.months_to_write(t, "Whole", {}, "2026-09", True, False) == ["2026-09"]
    assert fc.months_to_write(t, "Whole", {"2026-06": {}}, "2026-09", False, False) == \
        ["2026-09"]
    # … but does for the register-only series
    vans = fc.tally_lines(extract([rec(cat="N1", first=d) for d in
                                   ("2016-01-05", "2026-07-01", "2026-08-01", "2026-09-01")]),
                          dt.date(2026, 10, 1))
    assert fc.months_to_write(vans, "Vans", {}, "2026-09", True, False) == \
        ["2016-01", "2026-07", "2026-08", "2026-09"]
    assert fc.months_to_write(vans, "Vans", {"2026-06": {}}, "2026-09", False, False) == \
        ["2026-07", "2026-08", "2026-09"]   # a missed month is caught up


def test_upsert_line_level():
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "Czechia.csv"
        head = ",".join(fc.csv_columns("Whole")) + "\n"
        old = ("2026-07,monthly,Whole,ACEA,1538.0,1068.0,5005.0,8376.0,3684.0,476.0,"
               "20147.0,derived\n"
               "2026-08,monthly,Whole,ACEA,1497.0,953.0,4762.0,7264.0,2746.0,496.0,"
               "17718.0,https://x\n")
        path.write_text(head + old, encoding="utf-8")
        row = {"BEV": 1, "PHEV": 2, "HEV": 3, "PETROL": 4, "DIESEL": 5, "OTHERS": 6, "TOTAL": 21}
        new = fc.render_line("Whole", "2026-09", row, "n")
        st = fc.upsert_lines(path, "Whole", {"2026-09": new}, force=False)
        assert st["added"] == 1
        text = path.read_text(encoding="utf-8")
        assert text.startswith(head + old)                       # untouched, byte for byte
        assert text.endswith(new + "\n")
        # a foreign row is never replaced, not even with force
        foreign = fc.render_line("Whole", "2026-08", row, "")
        st = fc.upsert_lines(path, "Whole", {"2026-08": foreign}, force=True)
        assert st == {"added": 0, "updated": 0, "unchanged": 0, "skipped": 1}
        # an own row only with force
        again = fc.render_line("Whole", "2026-09", {**row, "BEV": 9, "TOTAL": 29}, "n")
        assert fc.upsert_lines(path, "Whole", {"2026-09": again}, False)["skipped"] == 1
        assert fc.upsert_lines(path, "Whole", {"2026-09": again}, True)["updated"] == 1
        # a register-only file gets its own column set, without HEV
        p2 = Path(d) / "Czechia_Vans.csv"
        line = fc.render_line("Vans", "2016-01", {"BEV": 1, "PHEV": 0, "PETROL": 2,
                                                  "DIESEL": 3, "OTHERS": 0, "TOTAL": 6})
        fc.upsert_lines(p2, "Vans", {"2016-01": line}, False)
        assert p2.read_text().splitlines()[0] == \
            "period,time_interval,variant,source,BEV,PHEV,PETROL,DIESEL,OTHERS,TOTAL,notes"


def test_gzip_stream():
    rows = [rec(fuel="EL"), rec(fuel="BA", model='SUPERB "COMBI"\nLINE')]
    raw = "﻿" + "".join(extract(rows))
    blob = gzip.compress(raw.encode("utf-8"))

    class Raw:
        def stream(self, n, decode_content=False):
            for i in range(0, len(blob), 7):          # tiny chunks: lines span chunks
                yield blob[i:i + 7]

    class Resp:
        headers = {"Content-Encoding": "gzip"}
        raw = Raw()

    t = fc.tally_lines(fc.stream_lines(Resp()), dt.date(2026, 10, 1))
    assert t.month("Whole", "2026-09") == {"BEV": 1, "PHEV": 0, "PETROL": 1, "DIESEL": 0,
                                           "OTHERS": 0, "TOTAL": 2}

    class Cut(Raw):
        def stream(self, n, decode_content=False):
            yield blob[: len(blob) // 2]

    Resp.raw = Cut()
    try:
        list(fc.stream_lines(Resp()))
    except fc.Truncated:
        pass
    else:
        raise AssertionError("a cut gzip stream must raise Truncated")


def test_schema_drift_aborts():
    lines = extract([rec()])
    lines[0] = lines[0].replace(fc.C_FUEL, "Pohon")
    try:
        fc.tally_lines(lines)
    except SystemExit as e:
        assert "required columns missing" in str(e)
    else:
        raise AssertionError("a missing column must abort")


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"ok  {t.__name__}")
    print(f"{len(tests)} tests passed")


if __name__ == "__main__":
    main()
