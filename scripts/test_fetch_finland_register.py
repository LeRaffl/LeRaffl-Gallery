"""Register shadow for Finland. No network, no CSV write."""
import contextlib
import csv
import io
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_finland_register as fn


def test_fuel_bucket_splits_full_hybrid_out_of_petrol():
    assert fn.fuel_bucket("01", "true", "02") == "HEV"
    assert fn.fuel_bucket("01", "true", "01") == "PHEV"
    assert fn.fuel_bucket("04", "false", "") == "BEV"
    assert fn.fuel_bucket("01", "false", "") == "PETROL"
    assert fn.fuel_bucket("02", "false", "") == "DIESEL"
    # An unclassified hybrid is not a silent HEV.
    assert fn.fuel_bucket("01", "true", "03") == "OTHERS"


def test_dates_are_not_iso():
    assert fn.registration_period("15.09.2026") == "2026-09"
    assert fn.registration_period("2026-09-15") is None
    assert fn.use_period("20260915") == "2026-09"
    assert fn.use_period("15.09.2026") is None


def test_cohort_keeps_used_imports_out_of_whole():
    assert fn.cohort("M1", "2026-09", "2026-09") == "whole"
    assert fn.cohort("M1G", "2026-09", "2026-09") == "whole"
    assert fn.cohort("M1", "2026-09", "2024-03") == "used"
    assert fn.cohort("M1", "2026-09", None) is None
    assert fn.cohort("M1", "2026-09", "2026-10") is None
    assert fn.cohort("N1", "2026-09", "2026-09") is None


def test_enrich_keeps_statfin_total_and_refuses_a_negative_residual():
    statfin = {"TOTAL": 7566, "BEV": 3644, "PHEV": 911, "DIESEL": 300, "OTHERS": 0}
    ok = fn.enrich_statfin(statfin, {"HEV": 1800, "PETROL": 800})
    assert ok is not None
    assert ok["TOTAL"] == 7566 and ok["BEV"] == 3644 and ok["PHEV"] == 911
    assert ok["DIESEL"] == 300 and ok["HEV"] == 1800 and ok["PETROL"] == 800
    assert ok["OTHERS"] == 111
    assert "Traficom register" in ok["notes"] and "first use" in ok["notes"]
    assert fn.enrich_statfin(statfin, {"HEV": 2712, "PETROL": 1}) is None
    # A month StatFin has not published yet is a refusal, not a crash.
    assert fn.enrich_statfin(None, {"HEV": 1, "PETROL": 1}) is None


def test_fill_window_keeps_the_thinned_years_on_acea():
    """Register HEV before 2025-01 sits on a thinned cohort (about -15% in
    2014) and would understate the hybrid share against a full StatFin
    total. Those months stay with ACEA."""
    assert fn.in_fill_window("2025-01")
    assert fn.in_fill_window("2026-09")
    assert not fn.in_fill_window("2024-12")
    assert not fn.in_fill_window("2014-06")


def test_count_rows_splits_whole_and_used_for_one_month():
    rows = [
        {"ajoneuvoluokka": "M1", "ensirekisterointipvm": "15.09.2026",
         "kayttoonottopvm": "20260915", "kayttovoima": "01",
         "sahkohybridi": "true", "sahkohybridinluokka": "02"},
        {"ajoneuvoluokka": "M1", "ensirekisterointipvm": "15.09.2026",
         "kayttoonottopvm": "20240301", "kayttovoima": "04",
         "sahkohybridi": "false", "sahkohybridinluokka": ""},
        {"ajoneuvoluokka": "M1", "ensirekisterointipvm": "2026-09-15",
         "kayttoonottopvm": "20260915", "kayttovoima": "01",
         "sahkohybridi": "false", "sahkohybridinluokka": ""},
    ]
    counted = fn.count_rows(rows, "2026-09")
    assert counted["whole"]["HEV"] == 1
    assert counted["used"]["BEV"] == 1
    assert sum(counted["whole"].values()) == 1


def test_tally_keeps_every_month_in_one_pass():
    rows = [
        {"ajoneuvoluokka": "M1", "ensirekisterointipvm": "15.06.2026",
         "kayttoonottopvm": "20260615", "kayttovoima": "01",
         "sahkohybridi": "true", "sahkohybridinluokka": "02"},
        {"ajoneuvoluokka": "M1G", "ensirekisterointipvm": "02.09.2026",
         "kayttoonottopvm": "20220101", "kayttovoima": "04",
         "sahkohybridi": "false", "sahkohybridinluokka": ""},
    ]
    tallied = fn.tally(rows)
    assert tallied["2026-06"]["whole"]["HEV"] == 1
    assert tallied["2026-09"]["used"]["BEV"] == 1
    assert "used" not in tallied["2026-06"]
    assert "whole" not in tallied["2026-09"]


def _snapshot(path: Path, rows: list[dict]) -> None:
    cols = ["ajoneuvoluokka", "ensirekisterointipvm", "kayttoonottopvm",
            "kayttovoima", "sahkohybridi", "sahkohybridinluokka"]
    body = ";".join(cols) + "\n" + "".join(
        ";".join(r[c] for c in cols) + "\n" for r in rows)
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("Ajoneuvorekisteri.csv", body.encode("iso-8859-1"))


def test_shadow_reads_the_zip_and_keeps_the_thinned_years_out():
    """End to end through a tiny snapshot: the month inside the fill window
    is enriched, the same split before 2025-01 is printed and refused, and
    neither touches the CSV."""
    def car(day, fuel="01", hyb="false", cls=""):
        d, m, y = day.split(".")
        return {"ajoneuvoluokka": "M1", "ensirekisterointipvm": day,
                "kayttoonottopvm": y + m + d, "kayttovoima": fuel,
                "sahkohybridi": hyb, "sahkohybridinluokka": cls}
    rows = [car("03.09.2026", hyb="true", cls="02"), car("04.09.2026"),
            car("05.09.2026", "04"),
            car("03.06.2024", hyb="true", cls="02"), car("04.06.2024")]
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        zpath = tmp / "Ajoneuvorekisteri.zip"
        _snapshot(zpath, rows)
        csv_path = tmp / "Finland.csv"
        csv_path.write_text(
            "period,time_interval,variant,source,BEV,PHEV,HEV,PETROL,DIESEL,OTHERS,TOTAL,notes\n"
            "2024-06,monthly,Whole,StatFin,1.0,0.0,,3.0,0.0,0.0,4.0,\n"
            "2026-09,monthly,Whole,StatFin,1.0,0.0,,3.0,0.0,0.0,4.0,\n",
            encoding="utf-8")
        before = csv_path.read_bytes()
        with contextlib.redirect_stdout(io.StringIO()):
            ok = fn.shadow_hev("2026-09", zpath, csv_path)
            early = fn.shadow_hev("2024-06", zpath, csv_path)
            window = fn.shadow_window(zpath, csv_path)
        assert ok is not None and ok["HEV"] == 1 and ok["PETROL"] == 1
        assert ok["TOTAL"] == 4.0 and ok["BEV"] == 1.0 and ok["OTHERS"] == 1.0
        assert early is None
        by_period = {w["period"]: w for w in window}
        assert by_period["2026-09"]["ok"] and not by_period["2024-06"]["ok"]
        assert csv_path.read_bytes() == before


HEAD = "period,time_interval,variant,source,BEV,PHEV,HEV,PETROL,DIESEL,FLEXFUEL,OTHERS,TOTAL,notes\n"


def _csv(tmp: Path, lines: list[str]) -> Path:
    path = tmp / "Finland.csv"
    path.write_text(HEAD + "".join(l + "\n" for l in lines), encoding="utf-8")
    return path


def test_acea_merge_splits_statfin_petrol_by_acea_share():
    """ACEA's HEV+petrol runs above StatFin's petrol (2024-11: 2,917 vs
    2,906), so it is a share, not a count. From 2025-01, never over the
    register, only on StatFin's month."""
    row = {"period": "2025-07", "TOTAL": "5425.0", "BEV": "1971.0", "PHEV": "1141.0",
           "HEV": "", "PETROL": "2042.0", "DIESEL": "250.0", "OTHERS": "21.0", "notes": ""}
    acea = {"TOTAL": 5425, "BEV": 1971, "PHEV": 1141, "HEV": 1425, "PETROL": 637, "DIESEL": 250}
    upd = fn.acea_merge(row, acea)
    assert upd["HEV"] == round(2042 * 1425 / 2062) and upd["HEV"] + upd["PETROL"] == 2042
    assert upd["OTHERS"] == 21.0 and upd["notes"] == fn.ACEA_NOTE
    assert "estimated" in fn.ACEA_NOTE                                    # invariant 6
    # A second merge reads StatFin's petrol back from HEV + PETROL.
    again = fn.acea_merge(dict(row, HEV=str(upd["HEV"]), PETROL=str(upd["PETROL"]),
                               notes=fn.ACEA_NOTE), acea)
    assert again["HEV"] == upd["HEV"] and again["PETROL"] == upd["PETROL"]
    assert fn.acea_merge(dict(row, period="2024-12"), acea) is None
    reg = dict(row, HEV="1361.0", notes=fn.register_note("2026-09-30"))
    assert fn.acea_merge(reg, acea) is None
    assert fn.acea_merge(row, dict(acea, TOTAL=5600)) is None          # not the same month
    assert fn.acea_merge(row, dict(acea, BEV=2100)) is None


def test_estimate_newest_uses_the_previous_months_share():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        lines = [
            "2024-12,monthly,Whole,StatFin,1.0,0.0,,100.0,0.0,,0.0,101.0,",
            "2026-09,monthly,Whole,StatFin,4338.0,765.0,1197.0,481.0,145.0,,59.0,6985.0,"
            + '"' + fn.register_note("2026-09-30") + '"',
            "2026-10,monthly,Whole,StatFin,3000.0,600.0,,1527.0,100.0,,0.0,5227.0,",
            "2026-11,monthly,Whole,StatFin,3000.0,600.0,,1000.0,100.0,,0.0,4700.0,",
        ]
        path = _csv(tmp, lines)
        with contextlib.redirect_stdout(io.StringIO()):
            assert fn.estimate_newest(path) == ["2026-10", "2026-11"]
            assert fn.estimate_newest(path) == []
        text = path.read_text(encoding="utf-8").splitlines()
        rows = {r["period"]: r for r in csv.DictReader(text)}
    share = 1197 / (1197 + 481)
    assert float(rows["2026-10"]["HEV"]) == round(1527 * share)
    assert float(rows["2026-10"]["HEV"]) + float(rows["2026-10"]["PETROL"]) == 1527
    assert float(rows["2026-10"]["OTHERS"]) == 0.0
    assert "2026-09's HEV share" in rows["2026-10"]["notes"]
    assert "2026-10's HEV share" in rows["2026-11"]["notes"]           # chains
    assert fn.split_kind(rows["2026-11"]) == "previous"
    assert text[1] == lines[0] and rows["2024-12"]["HEV"] == ""          # before 2025: blank


def test_carry_split_keeps_hev_through_a_statfin_restatement():
    old = {"period": "2026-09", "HEV": "1197.0", "PETROL": "481.0", "OTHERS": "59.0",
           "notes": fn.register_note("2026-09-30")}
    new = {"period": "2026-09", "TOTAL": 7000.0, "BEV": 4340.0, "PHEV": 765.0, "HEV": "",
           "PETROL": 1700.0, "DIESEL": 145.0, "OTHERS": 52.0, "notes": ""}
    kept = fn.carry_split(old, new)
    assert kept["HEV"] == "1197.0" and kept["PETROL"] == "481.0" and kept["TOTAL"] == 7000.0
    assert kept["OTHERS"] == 7000 - 4340 - 765 - 1197 - 481 - 145
    assert kept["notes"] == old["notes"]
    with contextlib.redirect_stdout(io.StringIO()):
        assert fn.carry_split(old, dict(new, TOTAL=5000.0)) is not None
        assert fn.carry_split(old, dict(new, TOTAL=5000.0))["HEV"] == ""   # dropped
    assert fn.carry_split(dict(old, notes="manual"), new) is new          # not ours
    # An estimate keeps its share of the new StatFin petrol; OTHERS stays StatFin's.
    est = {"period": "2026-10", "HEV": "1089.0", "PETROL": "438.0", "OTHERS": "0.0",
           "notes": fn.PREVIOUS_NOTE.format(prev="2026-09")}
    moved = fn.carry_split(est, dict(new, PETROL=1600.0, OTHERS=3.0))
    assert moved["HEV"] == round(1600 * 1089 / 1527) and moved["HEV"] + moved["PETROL"] == 1600
    assert moved["OTHERS"] == 3.0 and moved["notes"] == est["notes"]


def test_apply_register_covers_full_months_and_replaces_acea():
    """A snapshot dated the 30th covers its own month; it replaces an ACEA
    gap-fill, leaves 2024 (ACEA's years) alone and writes line-level."""
    def car(day, fuel="01", hyb="false", cls=""):
        d, m, y = day.split(".")
        return {"ajoneuvoluokka": "M1", "ensirekisterointipvm": day,
                "kayttoonottopvm": y + m + d, "kayttovoima": fuel,
                "sahkohybridi": hyb, "sahkohybridinluokka": cls}
    rows = [car("03.09.2026", hyb="true", cls="02"), car("04.09.2026"), car("30.09.2026", "04"),
            car("03.08.2026", hyb="true", cls="02"), car("04.06.2024", hyb="true", cls="02")]
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        zpath = tmp / "Ajoneuvorekisteri.zip"
        _snapshot(zpath, rows)
        lines = [
            "2024-06,monthly,Whole,StatFin,1.0,0.0,,3.0,0.0,,0.0,4.0,",
            "2026-08,monthly,Whole,StatFin,1.0,0.0,1.0,2.0,0.0,,0.0,4.0," + '"' + fn.ACEA_NOTE + '"',
            "2026-09,monthly,Whole,StatFin,1.0,0.0,,3.0,0.0,,0.0,4.0,",
            "2026-10,monthly,Whole,StatFin,1.0,0.0,,3.0,0.0,,0.0,4.0,",
        ]
        path = _csv(tmp, lines)
        with contextlib.redirect_stdout(io.StringIO()):
            written = fn.apply_register(zpath, path)
            again = fn.apply_register(zpath, path)
        text = path.read_text(encoding="utf-8").splitlines()
        rows_out = {r["period"]: r for r in csv.DictReader(text)}
        assert written == ["2026-08", "2026-09"] and again == []
        assert text[1] == lines[0] and text[4] == lines[3]                 # 2024 + October untouched
        sep = rows_out["2026-09"]
        assert (sep["HEV"], sep["PETROL"], sep["OTHERS"]) == ("1.0", "1.0", "1.0")
        assert sep["notes"] == fn.register_note("2026-09-30")
        assert rows_out["2026-08"]["notes"].startswith(fn.REGISTER_NOTE)  # ACEA replaced
        assert fn.newest_snapshot_date(path) == "2026-09-30"
        # The snapshot published on 14 October is that one; January's is new.
        assert not fn.snapshot_is_new("Wed, 14 Oct 2026 09:42:59 GMT", path)
        assert fn.snapshot_is_new("Wed, 13 Jan 2027 09:00:00 GMT", path)


def test_covered_through():
    assert fn.covered_through("2026-09-30") == "2026-09"
    assert fn.covered_through("2026-09-12") == "2026-08"
    assert fn.covered_through("2027-01-03") == "2026-12"


def test_apply_acea_writes_one_line_and_skips_register_months():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        lines = ["2026-10,monthly,Whole,StatFin,2000.0,800.0,,3200.0,900.0,,100.0,7000.0,",
                 "2026-09,monthly,Whole,StatFin,1.0,0.0,1.0,2.0,0.0,,0.0,4.0,"
                 + '"' + fn.register_note("2026-09-30") + '"']
        path = _csv(tmp, lines)
        acea = {"TOTAL": 7000, "BEV": 2000, "PHEV": 800, "HEV": 1500, "PETROL": 1700, "DIESEL": 900}
        with contextlib.redirect_stdout(io.StringIO()):
            assert fn.apply_acea("2026-10", acea, path)
            assert not fn.apply_acea("2026-10", acea, path)                 # no-op the 2nd time
            assert not fn.apply_acea("2026-09", dict(acea, TOTAL=4, BEV=1, PHEV=0), path)
            assert not fn.apply_acea("2026-11", acea, path)                 # no StatFin row yet
        text = path.read_text(encoding="utf-8").splitlines()
        assert text[2] == lines[1]
        row = next(csv.DictReader([text[0], text[1]]))
        assert row["HEV"] == "1500.0" and row["PETROL"] == "1700.0" and row["OTHERS"] == "100.0"


def test_fetch_finland_upsert_keeps_the_split():
    import fetch_finland as ff
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        path = _csv(tmp, [
            "2025-05,monthly,Whole,pxdata.stat.fi (StatFin 121d),2296.0,1435.0,1643.0,"
            "994.0,257.0,,217.0,6842.0," + '"' + fn.register_note("2026-09-30") + '"',
            "2026-10,monthly,Whole,pxdata.stat.fi (StatFin 121d),3000.0,600.0,1089.0,"
            "438.0,100.0,,0.0,5227.0," + '"' + fn.PREVIOUS_NOTE.format(prev="2026-09") + '"'])

        def statfin(period, total, bev, phev, petrol, diesel, others):
            return {"period": period, "time_interval": "monthly", "variant": "Whole",
                    "source": ff.SOURCE, "BEV": bev, "PHEV": phev, "HEV": "", "PETROL": petrol,
                    "DIESEL": diesel, "FLEXFUEL": "", "OTHERS": others, "TOTAL": total, "notes": ""}
        new = {("2025-05", "Whole"): statfin("2025-05", 6853.0, 2296.0, 1435.0, 2854.0, 257.0, 11.0),
               ("2026-10", "Whole"): statfin("2026-10", 5230.0, 3000.0, 600.0, 1530.0, 100.0, 0.0)}
        with contextlib.redirect_stdout(io.StringIO()) as out:
            ff.upsert_csv(str(path), new)
        rows = {r["period"]: r for r in csv.DictReader(path.read_text(encoding="utf-8").splitlines())}
    reg = rows["2025-05"]
    assert float(reg["HEV"]) == 1643 and float(reg["PETROL"]) == 994 and float(reg["TOTAL"]) == 6853
    assert float(reg["OTHERS"]) == 6853 - 2296 - 1435 - 1643 - 994 - 257
    assert reg["notes"].startswith(fn.REGISTER_NOTE)
    est = rows["2026-10"]
    assert float(est["HEV"]) + float(est["PETROL"]) == 1530 and float(est["OTHERS"]) == 0
    assert "WARNING" not in out.getvalue()

if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    failed = 0
    for name, fn_ in tests:
        try:
            fn_()
        except Exception as exc:
            failed += 1
            print(f"FAIL {name}: {exc}")
        else:
            print(f"ok  {name}")
    print(f"{len(tests) - failed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
