"""Denmark: Statbank line-level upsert and the ACEA HEV split. No network."""
import contextlib
import csv
import io
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import backfill_denmark_bil51 as bf  # noqa: E402
import build_series  # noqa: E402
import denmark_hev as dh  # noqa: E402
import fetch_denmark as fd  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
HEADER = ",".join(fd.CSV_COLUMNS) + "\n"
# 2026-09 as Statbank (BIL53) and ACEA published it.
SB_2026_09 = {"BEV": 17777.0, "PHEV": 22.0, "PETROL": 1665.0, "DIESEL": 599.0,
              "OTHERS": 0.0, "TOTAL": 20063.0}
ACEA_2026_09 = {"BEV": 17784, "PHEV": 23, "HEV": 1427, "OTHERS": 0,
                "PETROL": 515, "DIESEL": 276, "TOTAL": 20025}


def _quiet(fn, *a, **kw):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*a, **kw)


def _row(period, vals, variant="Whole", notes=""):
    return {"period": period, "time_interval": "monthly", "variant": variant,
            "source": fd.SOURCE, "HEV": "", "FLEXFUEL": "", "notes": notes, **vals}


def _csv(tmp, rows):
    p = Path(tmp) / "Denmark.csv"
    p.write_text(HEADER + "".join(fd._line(r) for r in rows), encoding="utf-8")
    return p


def _read(p):
    with open(p, encoding="utf-8", newline="") as f:
        return {r["period"]: r for r in csv.DictReader(f)}


def _months(start, n):
    y, m = map(int, start.split("-"))
    for _ in range(n):
        yield f"{y}-{m:02d}"
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


# ---------------------------------------------------------------- Statbank
def test_parse_dataset_maps_propellants_and_refuses_new_codes():
    ds = {"dimension": {"id": ["DRIV", "Tid"], "size": [3, 1],
                        "DRIV": {"category": {"index": {"20205": 0, "20225": 1, "20231": 2},
                                              "label": {}}},
                        "Tid": {"category": {"index": {"2026M10": 0}}}},
          "value": [1745, 16673, 1]}
    out = fd.parse_dataset(ds, "Whole")
    assert out == {"2026-10": {"BEV": 16673.0, "PHEV": 0.0, "PETROL": 1745.0,
                               "DIESEL": 0.0, "OTHERS": 1.0}}
    ds["dimension"]["DRIV"]["category"]["index"]["20299"] = 3
    ds["dimension"]["size"] = [4, 1]
    ds["value"].append(5)
    try:
        fd.parse_dataset(ds, "Whole")
    except RuntimeError as e:
        assert "20299" in str(e)
    else:
        raise AssertionError("an unmapped DRIV code must abort")


def test_upsert_keeps_unchanged_lines_byte_for_byte():
    """The repo's CSV is exactly what an unchanged fetch writes back."""
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "Denmark.csv"
        shutil.copy(ROOT / "data" / "Denmark.csv", p)
        before = p.read_bytes()
        rows = {}
        for r in csv.DictReader(io.StringIO(before.decode())):
            if r["period"] >= "2018-01":
                rows[(r["period"], "Whole")] = _row(
                    r["period"], {k: float(r[k]) for k in fd.STATBANK_COLS})
        added, updated = _quiet(fd.upsert_csv, str(p), rows)
        assert (added, updated) == (0, 0)
        assert p.read_bytes() == before


def test_upsert_appends_a_new_month_and_rewrites_only_a_restated_one():
    with tempfile.TemporaryDirectory() as tmp:
        p = _csv(tmp, [_row("2026-08", {**SB_2026_09, "TOTAL": 20063.0}, notes="keep me"),
                       _row("2026-09", SB_2026_09)])
        lines = p.read_text().splitlines()
        new = {("2026-08", "Whole"): _row("2026-08", {**SB_2026_09, "BEV": 17778.0,
                                                      "TOTAL": 20064.0}),
               ("2026-09", "Whole"): _row("2026-09", SB_2026_09),
               ("2026-10", "Whole"): _row("2026-10", SB_2026_09)}
        assert _quiet(fd.upsert_csv, str(p), new) == (1, 1)
        out = p.read_text().splitlines()
        assert out[2] == lines[2]                      # 2026-09 untouched
        rows = _read(p)
        assert rows["2026-08"]["BEV"] == "17778.0" and rows["2026-08"]["notes"] == "keep me"
        assert list(rows) == ["2026-08", "2026-09", "2026-10"]


# ---------------------------------------------------------------- HEV split
def test_pool_split_keeps_statbank_totals_and_takes_hybrids_from_diesel_too():
    row = _row("2026-11", SB_2026_09)
    upd = dh.acea_merge(row, ACEA_2026_09)
    assert upd == {"HEV": 1457.0, "PETROL": 525.0, "DIESEL": 282.0,
                   "notes": dh.ACEA_NOTE + " [Statbank petrol 1665, diesel 599]"}
    assert upd["HEV"] + upd["PETROL"] + upd["DIESEL"] == 1665 + 599


def test_acea_gates():
    row = _row("2026-11", SB_2026_09)
    assert dh.acea_merge(_row("2026-10", SB_2026_09), ACEA_2026_09) is None   # no backfill
    assert dh.acea_merge(row, {**ACEA_2026_09, "TOTAL": 19500}) is None      # not the month
    assert dh.acea_merge(row, {**ACEA_2026_09, "BEV": 17000}) is None
    # PHEV is Statbank's: a few plug-ins apart (2026-04: 113 vs 119) is no refusal.
    assert dh.acea_merge(row, {**ACEA_2026_09, "PHEV": 30}) is not None
    # Feb 2026: ACEA 11,933 vs Statbank 12,059 (1.0 %) is still the month.
    feb = _row("2026-11", {**SB_2026_09, "TOTAL": 12059.0})
    assert dh.same_month(feb, {"TOTAL": 11933, "BEV": SB_2026_09["BEV"]})
    assert dh.acea_merge(row, {**ACEA_2026_09, "HEV": 0, "PETROL": 0, "DIESEL": 0}) is None


def test_notes_keep_statbank_fuels_and_a_restatement_carries_the_shares():
    split = _row("2026-11", SB_2026_09)
    split.update({k: str(v) for k, v in dh.acea_merge(split, ACEA_2026_09).items()})
    assert dh.split_kind(split) == "acea"
    assert dh.statbank_fuels(split) == (1665.0, 599.0)
    assert fd._statbank_view(split) == {**SB_2026_09}
    restated = _row("2026-11", {**SB_2026_09, "PETROL": 1700.0, "TOTAL": 20098.0})
    out = dh.carry_split(split, restated)
    assert out["HEV"] + out["PETROL"] + out["DIESEL"] == 1700 + 599
    assert out["notes"].endswith("[Statbank petrol 1700, diesel 599]")
    assert dh.split_kind(out) == "acea"
    # A row without a split is passed through.
    assert dh.carry_split(_row("2026-11", SB_2026_09), restated) is restated


def _ready_csv(tmp, periods, pre_split=True):
    rows = [_row("2017-12", {"BEV": 53.0, "PHEV": 185.0, "OTHERS": 6.0, "TOTAL": 16482.0,
                             "PETROL": 9324.0 if pre_split else "",
                             "DIESEL": 6912.0 if pre_split else ""})]
    rows += [_row(p, SB_2026_09) for p in periods]
    return _csv(tmp, rows)


def test_ready_blocks_while_history_has_no_combustion_split():
    with tempfile.TemporaryDirectory() as tmp:
        p = _ready_csv(tmp, ["2026-11"], pre_split=False)
        assert not _quiet(dh.ready, p)
        before = p.read_bytes()
        assert _quiet(dh.apply_acea, "2026-11", ACEA_2026_09, p) is False
        assert _quiet(dh.estimate_newest, p) == []
        assert p.read_bytes() == before


def test_the_repo_csv_has_no_unsplit_rows():
    """backfill_denmark_bil51.py --write gave the 48 sheet rows 2014-2017
    their petrol/diesel on 2026-11-22: no Whole row may be unsplit now,
    so the HEV split may write."""
    rows = dh.whole_rows(ROOT / "data" / "Denmark.csv")
    assert dh.unsplit_history(rows) == []
    assert dh.ready(ROOT / "data" / "Denmark.csv", quiet=True)


def test_apply_acea_then_estimate_then_reestimate():
    with tempfile.TemporaryDirectory() as tmp:
        p = _ready_csv(tmp, ["2026-11", "2026-12", "2027-01"])
        assert _quiet(dh.estimate_newest, p) == []            # nothing to chain from yet
        assert _quiet(dh.apply_acea, "2026-11", ACEA_2026_09, p) is True
        assert _quiet(dh.apply_acea, "2026-11", ACEA_2026_09, p) is False   # idempotent
        assert _quiet(dh.estimate_newest, p) == ["2026-12", "2027-01"]
        rows = _read(p)
        assert dh.split_kind(rows["2026-12"]) == "previous"
        assert "2026-11's shares" in rows["2026-12"]["notes"]
        assert "2026-12's shares" in rows["2027-01"]["notes"]
        assert rows["2026-12"]["HEV"] == "1457.0"
        # ACEA's December lands: January (estimated from December) follows it.
        _quiet(dh.apply_acea, "2026-12", {**ACEA_2026_09, "HEV": 1000, "PETROL": 942}, p)
        rows = _read(p)
        assert dh.split_kind(rows["2026-12"]) == "acea"
        assert rows["2026-12"]["HEV"] == rows["2027-01"]["HEV"] == str(float(round(2264 * 1000 / 2218)))
        for r in rows.values():
            if r["period"] >= "2026-11":
                assert float(r["HEV"]) + float(r["PETROL"]) + float(r["DIESEL"]) == 2264
                assert dh.statbank_fuels(r) == (1665.0, 599.0)
        # Lines before HEV_FILL_FROM never change.
        assert rows["2017-12"]["HEV"] == ""


def test_upsert_keeps_a_split_month_when_statbank_did_not_change_it():
    with tempfile.TemporaryDirectory() as tmp:
        p = _ready_csv(tmp, ["2026-11"])
        _quiet(dh.apply_acea, "2026-11", ACEA_2026_09, p)
        before = p.read_bytes()
        new = {("2026-11", "Whole"): _row("2026-11", SB_2026_09)}
        assert _quiet(fd.upsert_csv, str(p), new) == (0, 0)
        assert p.read_bytes() == before
        new = {("2026-11", "Whole"): _row("2026-11", {**SB_2026_09, "DIESEL": 600.0,
                                                      "TOTAL": 20064.0})}
        assert _quiet(fd.upsert_csv, str(p), new) == (0, 1)
        r = _read(p)["2026-11"]
        assert dh.split_kind(r) == "acea" and dh.statbank_fuels(r) == (1665.0, 600.0)
        assert float(r["HEV"]) + float(r["PETROL"]) + float(r["DIESEL"]) == 2265


def test_series_keeps_every_month_once_history_is_split():
    """Why ready() exists: with 2014-2017 petrol/diesel the first HEV month
    costs the interactive series nothing; without it 48 months vanish."""
    # The repo CSV carries BIL51's 2014-2017 petrol/diesel since 2026-11-22.
    rows = list(csv.DictReader(open(ROOT / "data" / "Denmark.csv", encoding="utf-8")))
    n = len(build_series.build_country("Denmark", [dict(r) for r in rows])["m"])
    hev = [dict(r) for r in rows]
    hev[-1].update(HEV="1000.0", PETROL=str(float(hev[-1]["PETROL"]) - 1000))
    assert len(build_series.build_country("Denmark", hev)["m"]) == n
    # The state before the fill: those 48 rows without petrol/diesel.
    for r in hev:
        if r["period"] < "2018-01":
            r.update(PETROL="", DIESEL="")
    assert len(build_series.build_country("Denmark", hev)["m"]) == n - 48


# ---------------------------------------------------------------- BIL51
def test_bil51_plan_fills_only_blank_matching_rows():
    ds = {"dimension": {"id": ["EJER", "DRIV", "Tid"], "size": [1, 6, 2],
                        "DRIV": {"category": {"index": {"20200": 0, "20205": 1, "20210": 2,
                                                        "20225": 3, "20233": 4, "20215": 5}}},
                        "Tid": {"category": {"index": {"2017M11": 0, "2017M12": 1}}}},
          "value": [18014, 16482, 10187, 9324, 7506, 6912, 124, 53, 197, 184, 0, 9]}
    b = bf.parse_bil51(ds)
    assert b["2017-12"] == {"TOTAL": 16482, "BEV": 53, "PHEV": 184, "PETROL": 9324,
                            "DIESEL": 6912, "OTHERS": 9}
    with tempfile.TemporaryDirectory() as tmp:
        p = _csv(tmp, [_row("2017-11", {"BEV": 124.0, "PHEV": 197.0, "OTHERS": 0.0,
                                        "TOTAL": 18015.0, "PETROL": "", "DIESEL": ""}),
                       _row("2017-12", {"BEV": 53.0, "PHEV": 184.0, "OTHERS": 6.0,
                                        "TOTAL": 16482.0, "PETROL": "", "DIESEL": ""},
                            notes="backfill: sheet")])
        todo = _quiet(bf.plan, p, b)
        assert list(todo) == ["2017-12"]               # 2017-11 TOTAL differs: left blank
        assert todo["2017-12"]["gap"] == 3.0
        lines = p.read_text().splitlines()
        bf.write(p, todo, "2026-11-22")
        out = p.read_text().splitlines()
        assert out[1] == lines[1]
        r = _read(p)["2017-12"]
        assert (r["PETROL"], r["DIESEL"], r["TOTAL"]) == ("9324.0", "6912.0", "16482.0")
        assert r["notes"] == "backfill: sheet; PETROL/DIESEL api.statbank.dk (BIL51), filled 2026-11-22"


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    for name, fn in tests:
        fn()
        print(f"ok  {name}")
    print(f"{len(tests)} passed")
