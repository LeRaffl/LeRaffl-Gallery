#!/usr/bin/env python3
"""Regression tests for scripts/fetch_fleet_eurostat.py (no network).

Run:  python scripts/test_fetch_fleet_eurostat.py

The failure modes are silent: a wrong JSON-stat index would put one
country's cars under another, a hybrid folded into the wrong parent moves
stock between bands, and a careless upsert would overwrite a national-source
fleet series. These cases pin the JSON-stat decoding, the hierarchy
decomposition in every degraded form a reporting country uses, the row gates
(start year, no ICE split, TOTAL residual), the notes, and the upsert.
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_fleet_eurostat as fe  # noqa: E402

HEADER = ",".join(fe.FLEET_COLUMNS)

# Sweden 2024 as Eurostat publishes it (every level sums exactly).
SE_2024 = {
    "TOTAL": 4976987, "PET": 2844941, "PET_X_HYB": 2337374,
    "ELC_PET_HYB": 208416, "ELC_PET_PI": 299151, "DIE": 1572610,
    "DIE_X_HYB": 1557502, "ELC_DIE_HYB": 729, "ELC_DIE_PI": 14379,
    "ALT": 559436, "ELC": 358255, "HYD_FCELL": 39, "REN_OTH": 166781,
    "GAS": 14626, "LPG": 209, "OTH": 23,
}


def jsonstat(cells, flags=None):
    """Tiny JSON-stat 2.0 document in Eurostat's dimension order."""
    dims = {
        "freq": ["A"], "unit": ["NR"], "mot_nrg": [], "geo": [],
        "time": [], "leg_form": ["TOTAL", "PER_PHY"],
    }
    for (geo, year, m, _leg) in cells:
        for dim, val in (("geo", geo), ("time", str(year)), ("mot_nrg", m)):
            if val not in dims[dim]:
                dims[dim].append(val)
    ids = list(dims)
    sizes = [len(dims[d]) for d in ids]

    def flat(pos):
        f = 0
        for d, s in zip(ids, sizes):
            f = f * s + dims[d].index(pos[d])
        return str(f)

    def pos_of(key):
        geo, year, m, leg = key
        return {"freq": "A", "unit": "NR", "mot_nrg": m, "geo": geo,
                "time": str(year), "leg_form": leg}

    return {
        "id": ids, "size": sizes,
        "dimension": {d: {"category": {"index": {v: i for i, v in enumerate(dims[d])}}}
                      for d in ids},
        "value": {flat(pos_of(k)): v for k, v in cells.items()},
        "status": {flat(pos_of(k)): f for k, f in (flags or {}).items()},
    }


def test_parse_jsonstat_keeps_total_legal_form_and_decodes_positions():
    cells = {
        ("SE", 2024, "TOTAL", "TOTAL"): 100, ("SE", 2024, "ELC", "TOTAL"): 7,
        ("SE", 2024, "ELC", "PER_PHY"): 3,           # a slice, dropped
        ("CH", 2023, "TOTAL", "TOTAL"): 50, ("CH", 2023, "ELC", "TOTAL"): 2,
    }
    values, flags = fe.parse_jsonstat(
        jsonstat(cells, {("CH", 2023, "ELC", "TOTAL"): "i"}))
    assert values == {("SE", 2024, "TOTAL"): 100, ("SE", 2024, "ELC"): 7,
                      ("CH", 2023, "TOTAL"): 50, ("CH", 2023, "ELC"): 2}, values
    assert flags == {("CH", 2023, "ELC"): "i"}, flags


def test_full_split():
    cols, notes = fe.decompose(SE_2024)
    assert cols["BEV"] == 358255
    assert cols["PHEV"] == 299151 + 14379
    assert cols["HEV"] == 208416 + 729
    assert cols["PETROL"] == 2337374 and cols["DIESEL"] == 1557502
    assert cols["CNG"] == 14626 and cols["LPG"] == 209
    # HYD + REN_OTH + OTH + the part of ALT with no leaf (19,503)
    assert cols["OTHERS"] == 39 + 166781 + 23 + 19503, cols["OTHERS"]
    assert sum(v for k, v in cols.items() if k != "TOTAL") == cols["TOTAL"]
    assert notes == []


def test_no_plug_in_leaf_is_a_combined_hybrid_bucket():
    # Ireland 2020: hybrid leaf but no plug-in leaf.
    obs = {"TOTAL": 2291940, "PET": 925710, "PET_X_HYB": 851700,
           "ELC_PET_HYB": 74010, "DIE": 1345100, "DIE_X_HYB": 1343460,
           "ELC_DIE_HYB": 1640, "ALT": 21120, "ELC": 12720, "OTH": 8400}
    cols, notes = fe.decompose(obs)
    assert cols["PHEV"] is None
    assert cols["HEV"] == 74010 + 1640
    assert notes == ["HEV = combined PHEV+HEV (source did not split)"]


def test_no_excluding_hybrids_leaf_keeps_hybrids_in_ice():
    # Czechia before 2022: only the petrol / diesel family totals.
    obs = {"TOTAL": 1000, "PET": 600, "DIE": 380, "ALT": 20, "ELC": 5, "LPG": 15}
    cols, notes = fe.decompose(obs)
    assert cols["PETROL"] == 600 and cols["DIESEL"] == 380
    assert cols["PHEV"] is None and cols["HEV"] is None
    assert notes == ["hybrids not split out are in PETROL/DIESEL"]


def test_no_hybrid_leaf_at_all_is_not_a_measured_zero():
    # Slovenia until 2021: PET == PET_X_HYB and no hybrid leaf.
    obs = {"TOTAL": 1000, "PET": 600, "PET_X_HYB": 600, "DIE": 390,
           "DIE_X_HYB": 390, "ALT": 10, "ELC": 10}
    cols, notes = fe.decompose(obs)
    assert cols["PHEV"] is None and cols["HEV"] is None
    assert notes == ["no hybrid figure (hybrids sit in another column)"]


def test_plug_in_leaf_without_excluding_leaf():
    # Poland-style: family total + plug-in leaf only. The plug-ins come out
    # of PETROL, the other hybrids stay in it (unknown, not zero).
    obs = {"TOTAL": 1000, "PET": 600, "ELC_PET_PI": 10, "DIE": 380,
           "ELC_DIE_PI": 2, "ALT": 20, "ELC": 20}
    cols, notes = fe.decompose(obs)
    assert cols["PHEV"] == 12
    assert cols["HEV"] is None
    assert cols["PETROL"] == 590 and cols["DIESEL"] == 378
    assert notes == ["hybrids not split out are in PETROL/DIESEL"]


def test_missing_family_total_does_not_invent_zero_hybrids():
    # Bulgaria 2025: PET_X_HYB and the plug-in leaf, no PET, no hybrid leaf.
    obs = {"TOTAL": 1000, "PET_X_HYB": 500, "ELC_PET_PI": 5, "DIE": 480,
           "DIE_X_HYB": 470, "ELC_DIE_HYB": 8, "ELC_DIE_PI": 2, "ELC": 15}
    cols, _ = fe.decompose(obs)
    assert cols["PHEV"] == 7
    assert cols["HEV"] == 8, cols["HEV"]        # diesel only; petrol unknown


def test_plug_in_split_in_one_family_only_stays_combined():
    obs = {"TOTAL": 1000, "PET": 600, "PET_X_HYB": 560, "ELC_PET_HYB": 30,
           "ELC_PET_PI": 10, "DIE": 390, "DIE_X_HYB": 380, "ELC_DIE_HYB": 10,
           "ALT": 10, "ELC": 10}
    cols, notes = fe.decompose(obs)
    assert cols["PHEV"] is None and cols["HEV"] == 50
    assert "HEV = combined PHEV+HEV (source did not split)" in notes


def test_measured_zero_hybrids_stay_zero():
    obs = {"TOTAL": 100, "PET": 70, "PET_X_HYB": 70, "ELC_PET_HYB": 0,
           "ELC_PET_PI": 0, "DIE": 30, "DIE_X_HYB": 30, "ELC_DIE_HYB": 0,
           "ELC_DIE_PI": 0}
    cols, _ = fe.decompose(obs)
    assert cols["PHEV"] == 0 and cols["HEV"] == 0


def test_no_petrol_or_diesel_figure_is_unusable():
    # Greece / Slovakia: only TOTAL and the alternative fuels.
    assert fe.decompose({"TOTAL": 100, "ALT": 5, "ELC": 2, "ELC_PET_PI": 1}) is None
    assert fe.decompose({"TOTAL": 100, "PET": 60, "ELC": 2}) is None
    assert fe.decompose({"PET": 60, "DIE": 40}) is None


def test_build_rows_gates_and_notes():
    values = {}
    for m, v in SE_2024.items():
        values[("SE", 2024, m)] = v
        values[("SE", 2012, m)] = v                   # before "from"
    # 2023: the leaves miss 20 % of TOTAL -> not written
    values.update({("SE", 2023, "TOTAL"): 1000, ("SE", 2023, "PET"): 500,
                   ("SE", 2023, "DIE"): 300})
    flags = {("SE", 2024, "ELC"): "i"}
    spec = {"SE": {"name": "Sweden", "from": 2013,
                   "caveats": [(2024, 2024, "test caveat")]}}
    log = []
    rows = fe.build_rows(values, flags, spec, log=log.append)
    assert [r["year"] for r in rows] == [2024], rows
    r = rows[0]
    assert r["country"] == "Sweden" and r["variant"] == "Whole"
    assert r["source"] == fe.SOURCE
    assert r["notes"] == "some cells imputed by Eurostat; test caveat", r["notes"]
    assert any("2023" in line and "miss TOTAL" in line for line in log), log


def test_every_configured_country_has_a_name_and_known_keys():
    for geo, spec in fe.COUNTRIES.items():
        assert len(geo) == 2 and geo.isupper(), geo
        assert set(spec) <= {"name", "from", "caveats"}, spec
        for lo, hi, text in spec.get("caveats", []):
            assert lo <= hi and "," not in text, (geo, text)


def _row(country, year, source=fe.SOURCE, bev=1, total=10):
    r = {c: None for c in fe.FLEET_COLUMNS}
    r.update(country=country, variant="Whole", year=year, source=source,
             BEV=bev, TOTAL=total, notes="")
    return r


def test_upsert_replaces_own_rows_keeps_others_appends_new():
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "fleet.csv"
        other = "Norway,Whole,2024,,800000,,,,,1,2,,,,,,3,, "
        lines = [HEADER,
                 other,
                 fe.row_to_line(_row("Sweden", 2023, bev=5)),
                 fe.row_to_line(_row("Sweden", 2024, bev=6)),
                 "Denmark,Whole,1993,,0,,,,,1,2,,,,,,,,"]
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")
        n_new, n_kept = fe.upsert(
            [_row("Sweden", 2023, bev=7), _row("Sweden", 2024, bev=8),
             _row("Sweden", 2025, bev=9), _row("Belgium", 2025, bev=4)], p)
        out = p.read_text(encoding="utf-8").splitlines()
        assert (n_new, n_kept) == (4, 2)
        assert out[0] == HEADER and out[1] == other     # byte-for-byte
        assert [l.split(",")[2] for l in out[2:5]] == ["2023", "2024", "2025"]
        assert out[2].split(",")[4] == "7"
        assert out[5].startswith("Denmark,")
        assert out[6].startswith("Belgium,Whole,2025,")


def test_upsert_refuses_a_national_source_country():
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "fleet.csv"
        p.write_text(HEADER + "\nGermany,Whole,2024,KBA FZ 13.2.1,1,,,,,,,,,,,,,,\n",
                     encoding="utf-8")
        try:
            fe.upsert([_row("Germany", 2024)], p)
        except RuntimeError as e:
            assert "another source" in str(e)
        else:
            raise AssertionError("overwrote a national-source series")
        # also a curated row with no source at all
        p.write_text(HEADER + "\nAustria,Whole,2024,,1,,,,,,,,,,,,,,\n", encoding="utf-8")
        try:
            fe.upsert([_row("Austria", 2024)], p)
        except RuntimeError:
            pass
        else:
            raise AssertionError("overwrote a curated series")


def test_row_with_a_comma_is_rejected():
    r = _row("Sweden", 2024)
    r["notes"] = "a, b"
    try:
        fe.row_to_line(r)
    except ValueError:
        pass
    else:
        raise AssertionError("wrote an unquoted comma")


def test_rows_match_the_frontend_and_r_readers():
    # Written rows must round-trip through a plain CSV reader with the
    # schema's 19 columns (index.html parseCSV, R read.csv).
    import csv
    import io
    rows = fe.build_rows({("SE", 2024, m): v for m, v in SE_2024.items()}, {},
                         {"SE": {"name": "Sweden"}}, log=lambda *_: None)
    text = HEADER + "\n" + "\n".join(fe.row_to_line(r) for r in rows) + "\n"
    parsed = list(csv.DictReader(io.StringIO(text)))
    assert len(parsed) == 1 and parsed[0]["PHEV"] == str(299151 + 14379)
    assert all(len(row) == len(fe.FLEET_COLUMNS) for row in parsed)


def main() -> int:
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
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
